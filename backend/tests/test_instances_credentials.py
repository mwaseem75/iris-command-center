"""Phase 4A step 2: instance credentials in the IRIS Secure Wallet.

No IRIS connection: the REST client is mocked and the Native API is a fake.
A canary password is used throughout to prove it never leaks.
"""

import json
import logging
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.instances.credentials import (
    WALLET_COLLECTION,
    CredentialStoreError,
    WalletCredentialStore,
    add_instance,
    credential_ref_for,
    delete_instance,
    resolve_password,
    update_instance,
)
from app.instances.models import PRIMARY_INSTANCE_ID
from app.instances.registry import InstanceRegistry, InstanceRegistryError, primary_from_settings
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from tests.test_instances_registry import _FakePersister, _settings

CANARY = "Pw-CANARY-9f3e-not-real!"
NEW_CANARY = "Pw-NEW-CANARY-1a2b-not-real!"


class _FakeNative:
    def __init__(self, secrets: dict[str, str] | None = None, error: Exception | None = None):
        self.secrets = secrets or {}
        self.error = error
        self.calls: list[tuple] = []

    def classMethodValue(self, cls: str, method: str, *args):  # noqa: N802 - Native API name
        self.calls.append((cls, method, *args))
        if self.error is not None:
            raise self.error
        return self.secrets[args[0]]


def _store(native: _FakeNative | None = None, client: AsyncMock | None = None):
    client = client or AsyncMock()
    store = WalletCredentialStore(client, _settings())
    store._iris = native or _FakeNative()  # already "connected"
    return store, client


def _registry(persister: _FakePersister | None = None) -> InstanceRegistry:
    return InstanceRegistry(primary_from_settings(_settings()), persister)


async def _add(registry, store, url="http://iris-2:52773", password=CANARY):
    return await add_instance(
        registry, store, name="Second", base_url=url, username="ops", password=SecretStr(password)
    )


# --- storing ---


@pytest.mark.asyncio
async def test_save_prepares_a_least_privilege_collection_then_stores_the_secret() -> None:
    store, client = _store()

    ref = await store.save("iris-0123456789ab", SecretStr(CANARY))

    assert ref == f"{WALLET_COLLECTION}.iris-0123456789ab"
    collection_call, secret_call = client.put.await_args_list
    assert collection_call.args == ("/v2/wallet/collection",)
    assert collection_call.kwargs == {
        "params": {"name": "CommandCenter"},
        "json": {"UseResource": "%Admin_Wallet:USE", "EditResource": "%Admin_Wallet:USE"},
    }
    assert secret_call.args == ("/v2/wallet/secret",)
    assert secret_call.kwargs == {
        "params": {"name": ref},
        "json": {"Type": "%Wallet.KeyValue", "WalletSecretConfig": {"Secret": {"password": CANARY}}},
    }


@pytest.mark.asyncio
async def test_collection_is_prepared_only_once() -> None:
    store, client = _store()

    await store.save("iris-0123456789ab", SecretStr(CANARY))
    await store.save("iris-ba9876543210", SecretStr(CANARY))

    paths = [call.args[0] for call in client.put.await_args_list]
    assert paths == ["/v2/wallet/collection", "/v2/wallet/secret", "/v2/wallet/secret"]


@pytest.mark.parametrize("password", ["", "   "])
@pytest.mark.asyncio
async def test_a_blank_password_is_never_stored(password: str) -> None:
    store, client = _store()

    with pytest.raises(CredentialStoreError):
        await store.save("iris-0123456789ab", SecretStr(password))
    client.put.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [IRISConnectionError("down"), IRISResponseError(500, body={"errors": [CANARY]})],
)
@pytest.mark.asyncio
async def test_store_failures_never_carry_the_value(error: Exception) -> None:
    client = AsyncMock()
    client.put.side_effect = error
    store, _ = _store(client=client)

    with pytest.raises(CredentialStoreError) as raised:
        await store.save("iris-0123456789ab", SecretStr(CANARY))

    assert CANARY not in str(raised.value) and CANARY not in repr(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


# --- reading ---


def test_read_returns_a_secret_str_from_the_wallet() -> None:
    ref = credential_ref_for("iris-0123456789ab")
    native = _FakeNative({ref: json.dumps({"password": CANARY})})
    store, _ = _store(native)

    password = store.read_sync(ref)

    assert isinstance(password, SecretStr)
    assert password.get_secret_value() == CANARY
    assert CANARY not in repr(password) and CANARY not in str(password)
    assert native.calls == [("%Wallet.KeyValue", "GetSecretValue", ref)]


@pytest.mark.parametrize(
    "native",
    [
        _FakeNative(error=RuntimeError(f"<THROW> GetSecretValue {CANARY}")),
        _FakeNative({"CommandCenter.iris-0123456789ab": "not json"}),
        _FakeNative({"CommandCenter.iris-0123456789ab": json.dumps({"user": "ops"})}),
        _FakeNative({"CommandCenter.iris-0123456789ab": json.dumps({"password": ""})}),
    ],
)
def test_read_failures_are_generic_and_never_carry_the_value(native: _FakeNative) -> None:
    store, _ = _store(native)

    with pytest.raises(CredentialStoreError) as raised:
        store.read_sync("CommandCenter.iris-0123456789ab")

    assert CANARY not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


@pytest.mark.parametrize(
    "ref",
    [
        "Other.iris-0123456789ab",  # another collection
        "CommandCenter.SomeOtherSecret",
        "CommandCenter.iris-0123456789AB",
        "CommandCenter.iris-0123456789ab.extra",
        "CommandCenter.iris-0123456789a",
        "%SYS.Secret",
        "",
        None,
    ],
)
@pytest.mark.asyncio
async def test_only_command_center_refs_are_ever_used(ref) -> None:
    native = _FakeNative()
    store, client = _store(native)

    with pytest.raises(CredentialStoreError):
        store.read_sync(ref)
    with pytest.raises(CredentialStoreError):
        await store.delete(ref)

    assert native.calls == []
    client.delete.assert_not_awaited()


# --- lifecycle ---


@pytest.mark.asyncio
async def test_add_stores_the_secret_and_saves_only_its_reference() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    store, client = _store()

    instance = await _add(registry, store)

    assert instance.credential_ref == credential_ref_for(instance.id)
    assert client.put.await_args_list[-1].kwargs["params"] == {"name": instance.credential_ref}
    assert CANARY not in persister.saved[instance.id].model_dump_json()
    assert CANARY not in instance.model_dump_json() and CANARY not in repr(instance)


@pytest.mark.asyncio
async def test_add_removes_the_secret_when_the_instance_cannot_be_saved() -> None:
    registry = _registry()
    store, client = _store()

    with pytest.raises(InstanceRegistryError):
        await _add(registry, store, url="http://iris:52773")  # the Primary's URL

    stored_ref = client.put.await_args_list[-1].kwargs["params"]["name"]
    client.delete.assert_awaited_once_with("/v2/wallet/secret", params={"name": stored_ref})
    assert [i.id for i in registry.list()] == [PRIMARY_INSTANCE_ID]


@pytest.mark.asyncio
async def test_add_leaves_the_registry_unchanged_when_the_secret_cannot_be_stored() -> None:
    client = AsyncMock()
    client.put.side_effect = IRISConnectionError("down")
    registry = _registry()
    store, _ = _store(client=client)

    with pytest.raises(CredentialStoreError):
        await _add(registry, store)
    assert [i.id for i in registry.list()] == [PRIMARY_INSTANCE_ID]


@pytest.mark.parametrize("password", [None, SecretStr(""), SecretStr("   ")])
@pytest.mark.asyncio
async def test_update_with_a_blank_password_keeps_the_stored_credential(password) -> None:
    registry = _registry()
    store, client = _store()
    instance = await _add(registry, store)
    client.put.reset_mock()

    updated = await update_instance(registry, store, instance.id, password=password, name="Renamed")

    assert updated.name == "Renamed"
    assert updated.credential_ref == instance.credential_ref
    client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_with_a_new_password_replaces_the_secret() -> None:
    registry = _registry()
    store, client = _store()
    instance = await _add(registry, store)
    client.put.reset_mock()

    updated = await update_instance(registry, store, instance.id, password=SecretStr(NEW_CANARY))

    client.put.assert_awaited_once()
    call = client.put.await_args
    assert call.kwargs["params"] == {"name": instance.credential_ref}
    assert call.kwargs["json"]["WalletSecretConfig"]["Secret"]["password"] == NEW_CANARY
    assert updated.credential_ref == instance.credential_ref


@pytest.mark.asyncio
async def test_update_cannot_set_the_reference_directly() -> None:
    registry = _registry()
    store, _ = _store()
    instance = await _add(registry, store)

    with pytest.raises(InstanceRegistryError):
        await update_instance(registry, store, instance.id, credential_ref="CommandCenter.iris-ffffffffffff")
    assert registry.get(instance.id).credential_ref == instance.credential_ref


@pytest.mark.asyncio
async def test_delete_removes_the_secret_then_the_instance() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    store, client = _store()
    instance = await _add(registry, store)

    await delete_instance(registry, store, instance.id)

    client.delete.assert_awaited_once_with("/v2/wallet/secret", params={"name": instance.credential_ref})
    assert registry.get(instance.id) is None and persister.deleted == [instance.id]


@pytest.mark.asyncio
async def test_failed_secret_delete_keeps_the_instance() -> None:
    registry = _registry()
    store, client = _store()
    instance = await _add(registry, store)
    client.delete.side_effect = IRISConnectionError("down")

    with pytest.raises(CredentialStoreError):
        await delete_instance(registry, store, instance.id)
    assert registry.get(instance.id) == instance


@pytest.mark.parametrize(
    "action",
    [
        lambda r, s: delete_instance(r, s, PRIMARY_INSTANCE_ID),
        lambda r, s: update_instance(r, s, PRIMARY_INSTANCE_ID, password=SecretStr(CANARY)),
        lambda r, s: update_instance(r, s, PRIMARY_INSTANCE_ID, name="x"),
    ],
)
@pytest.mark.asyncio
async def test_the_primary_credential_is_never_touched(action) -> None:
    registry = _registry()
    store, client = _store()

    with pytest.raises(InstanceRegistryError):
        await action(registry, store)
    client.put.assert_not_awaited()
    client.delete.assert_not_awaited()


# --- resolving the password to connect ---


def test_primary_password_comes_from_the_environment() -> None:
    store, _ = _store()
    native = store._iris

    password = resolve_password(primary_from_settings(_settings()), _settings(), store)

    assert password.get_secret_value() == "primary-env-password-not-stored"
    assert native.calls == []


@pytest.mark.asyncio
async def test_user_defined_password_comes_from_the_wallet() -> None:
    registry = _registry()
    store, _ = _store()
    instance = await _add(registry, store)
    store._iris.secrets[instance.credential_ref] = json.dumps({"password": CANARY})

    assert resolve_password(instance, _settings(), store).get_secret_value() == CANARY


def test_an_instance_without_a_reference_has_no_password() -> None:
    registry = _registry()
    instance = registry.add(name="Legacy", base_url="http://iris-9:52773", username="ops")
    store, _ = _store()

    with pytest.raises(CredentialStoreError):
        resolve_password(instance, _settings(), store)


# --- the value never shows up in logs or reprs ---


@pytest.mark.asyncio
async def test_password_never_appears_in_logs_or_reprs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    persister = _FakePersister()
    registry = _registry(persister)
    client = AsyncMock()
    store, _ = _store(client=client)

    instance = await _add(registry, store)
    await update_instance(registry, store, instance.id, password=SecretStr(NEW_CANARY))
    client.put.side_effect = IRISResponseError(500, body={"errors": [CANARY]})
    with pytest.raises(CredentialStoreError):
        await update_instance(registry, store, instance.id, password=SecretStr(CANARY))
    await delete_instance(registry, store, instance.id)

    for text in (caplog.text, repr(store), repr(registry.list()), repr(persister.saved)):
        assert CANARY not in text and NEW_CANARY not in text


# --- a Wallet read on a connection IRIS has closed (e.g. IRIS restarted) ---


def test_a_read_after_iris_dropped_the_connection_reconnects_once(monkeypatch) -> None:
    import sys

    ref = credential_ref_for("iris-0123456789ab")
    dead = _FakeNative(error=RuntimeError("<COMMUNICATION LINK ERROR> Failed to send message; Error code: 32 EPIPE"))
    fresh = _FakeNative({ref: json.dumps({"password": CANARY})})
    connects = []

    class _Module:
        @staticmethod
        def connect(*args):
            connects.append(args[0])
            return object()

        @staticmethod
        def createIRIS(connection):  # noqa: N802 - Native API name
            return fresh

    monkeypatch.setitem(sys.modules, "iris", _Module)
    store, _ = _store(dead)   # the kept connection is the dead one

    assert store.read_sync(ref).get_secret_value() == CANARY
    assert len(connects) == 1 and fresh.calls == [("%Wallet.KeyValue", "GetSecretValue", ref)]


def test_a_read_that_still_fails_after_reconnecting_is_generic(monkeypatch) -> None:
    import sys

    error = RuntimeError(f"<COMMUNICATION LINK ERROR> {CANARY}")

    class _Module:
        @staticmethod
        def connect(*args):
            return object()

        @staticmethod
        def createIRIS(connection):  # noqa: N802
            return _FakeNative(error=error)

    monkeypatch.setitem(sys.modules, "iris", _Module)
    store, _ = _store(_FakeNative(error=error))

    with pytest.raises(CredentialStoreError) as raised:
        store.read_sync("CommandCenter.iris-0123456789ab")
    assert CANARY not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert store._iris is None   # dropped, so the next read reconnects


def test_concurrent_reads_and_close_never_use_or_close_the_connection_mid_read(monkeypatch) -> None:
    # Reads come from worker threads (asyncio.to_thread) and close() from
    # shutdown: one at a time on the shared Native API connection.
    import sys
    import threading
    import time

    ref = credential_ref_for("iris-0123456789ab")
    guard = threading.Lock()
    state = {"reading": 0, "most": 0, "closed_mid_read": False}

    class _Connection:
        closed = False

        def close(self):
            with guard:
                state["closed_mid_read"] = state["closed_mid_read"] or state["reading"] > 0
            self.closed = True

    class _Native:
        def __init__(self, connection):
            self.connection = connection

        def classMethodValue(self, *args):  # noqa: N802 - Native API name
            with guard:
                state["reading"] += 1
                state["most"] = max(state["most"], state["reading"])
            time.sleep(0.02)
            with guard:
                state["reading"] -= 1
            if self.connection.closed:
                raise RuntimeError("<COMMUNICATION LINK ERROR> closed")
            return json.dumps({"password": CANARY})

    class _Module:
        connect = staticmethod(lambda *args: _Connection())
        createIRIS = staticmethod(lambda connection: _Native(connection))  # noqa: N815

    monkeypatch.setitem(sys.modules, "iris", _Module)
    store = WalletCredentialStore(AsyncMock(), _settings())
    results: list[str] = []

    def read():
        results.append(store.read_sync(ref).get_secret_value())

    threads = [threading.Thread(target=read) for _ in range(6)] + [threading.Thread(target=store.close)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results == [CANARY] * 6
    assert state["most"] == 1, "two reads used the connection at once"
    assert not state["closed_mid_read"], "the connection was closed during a read"
