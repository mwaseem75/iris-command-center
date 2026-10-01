"""Phase 4A step 4: instance management routes.

The registry is real (with a fake persister); the Wallet store is a fake; the
compatibility handshake is patched to return a chosen result. No IRIS call.
"""

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import get_settings
from app.dependencies import get_caller_privileges, get_credential_store, get_instance_registry
from app.instances.credentials import CredentialStoreError, credential_ref_for
from app.instances.models import PRIMARY_INSTANCE_ID, InstanceCheck, InstanceCheckStatus
from app.instances.registry import InstanceRegistry, primary_from_settings
from app.observability import store as trace_store
from tests.test_instances_registry import _FakePersister, _settings

CANARY = "Pw-ROUTES-CANARY-4b2e-not-real!"
NEW_CANARY = "Pw-ROUTES-NEW-CANARY-8d1f-not-real!"
URL = "http://iris-2:52773"


def _check(status: InstanceCheckStatus = InstanceCheckStatus.COMPATIBLE, **values) -> InstanceCheck:
    defaults = {"product": "iris", "api_version": 2, "server_version": "IRIS 2026.2", "username": "ops",
                "endpoints_ok": ["/v2/namespaces"]}
    if status is not InstanceCheckStatus.COMPATIBLE:
        defaults |= {"failure": status.value, "detail": "Check failed."}
    return InstanceCheck(checked_at=datetime.now(timezone.utc), status=status, **(defaults | values))


class FakeStore:
    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self.saves: list[str] = []
        self.deletes: list[str] = []
        self.fail_save = False

    async def save(self, instance_id: str, password: SecretStr) -> str:
        if self.fail_save:
            raise CredentialStoreError("The credential could not be stored in the IRIS Wallet.")
        ref = credential_ref_for(instance_id)
        self.secrets[ref] = password.get_secret_value()
        self.saves.append(ref)
        return ref

    async def delete(self, ref: str) -> None:
        self.secrets.pop(ref, None)
        self.deletes.append(ref)

    async def exists(self, ref: str) -> bool:
        return ref in self.secrets

    def read_sync(self, ref: str) -> SecretStr:
        if ref not in self.secrets:
            raise CredentialStoreError("The credential could not be read from the IRIS Wallet.")
        return SecretStr(self.secrets[ref])


class Env:
    def __init__(self, monkeypatch) -> None:
        self.persister = _FakePersister()
        self.registry = InstanceRegistry(primary_from_settings(_settings()), self.persister)
        self.store = FakeStore()
        self.privileges = frozenset({"Wallet", "Manage"})
        self.connection_check = AsyncMock(return_value=_check())
        self.instance_check = AsyncMock(return_value=_check())
        for module in ("app.execution.instance_handlers", "app.routes.instances"):
            monkeypatch.setattr(f"{module}.check_connection", self.connection_check)
            monkeypatch.setattr(f"{module}.check_instance", self.instance_check)


@pytest.fixture
def env(client: TestClient, monkeypatch):
    from app.main import app

    state = Env(monkeypatch)
    app.dependency_overrides[get_instance_registry] = lambda: state.registry
    app.dependency_overrides[get_credential_store] = lambda: state.store
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_caller_privileges] = lambda: state.privileges
    trace_store.clear_traces()
    yield state
    trace_store.clear_traces()


def _create(client: TestClient, **body) -> dict:
    payload = {"name": "Second", "base_url": URL, "username": "ops", "password": CANARY, "confirmed": True} | body
    return client.post("/api/iris/instances", json=payload).json()


def _created_id(env: Env) -> str:
    return next(i.id for i in env.registry.list() if not i.primary)


# --- reads ---


def test_list_starts_with_the_protected_primary(client, env) -> None:
    body = client.get("/api/iris/instances").json()

    [primary] = body["instances"]
    assert (primary["id"], primary["primary"], primary["active"], primary["has_credential"]) == (
        PRIMARY_INSTANCE_ID, True, True, True,
    )
    assert "credential_ref" not in primary and "password" not in primary


def test_get_one_and_unknown(client, env) -> None:
    assert client.get("/api/iris/instances/primary").json()["id"] == PRIMARY_INSTANCE_ID
    assert client.get("/api/iris/instances/iris-unknown00000").status_code == 404


# --- connection test (stores nothing) ---


def test_connection_test_returns_the_check_and_stores_nothing(client, env) -> None:
    response = client.post(
        "/api/iris/instances/test", json={"base_url": URL + "/", "username": "ops", "password": CANARY}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "compatible"
    kwargs = env.connection_check.await_args.kwargs
    assert (kwargs["base_url"], kwargs["username"], kwargs["password"].get_secret_value()) == (URL, "ops", CANARY)
    assert len(env.registry.list()) == 1 and env.persister.saved == {} and env.store.saves == []


def test_connection_test_reports_an_incompatible_result(client, env) -> None:
    env.connection_check.return_value = _check(InstanceCheckStatus.UNREACHABLE)

    body = client.post("/api/iris/instances/test", json={"base_url": URL, "username": "ops", "password": "x"}).json()

    assert (body["status"], body["failure"]) == ("unreachable", "unreachable")


@pytest.mark.parametrize(
    "body",
    [
        {"base_url": "ftp://iris-2", "username": "ops", "password": "x"},
        {"base_url": "http://ops:secret@iris-2:52773", "username": "ops", "password": "x"},
        {"base_url": URL, "username": "ops"},
        {"base_url": URL, "username": "ops", "password": "x", "extra": 1},
    ],
)
def test_connection_test_validates_its_input(client, env, body) -> None:
    assert client.post("/api/iris/instances/test", json=body).status_code == 422
    env.connection_check.assert_not_awaited()


# --- create ---


def test_create_registers_an_active_compatible_instance(client, env) -> None:
    body = _create(client)

    assert (body["status"], body["verification"]["status"]) == ("success", "verified")
    instance = body["handler_result"]["data"]["instance"]
    assert (instance["active"], instance["primary"], instance["has_credential"]) == (True, False, True)
    assert env.registry.get(instance["id"]).credential_ref == credential_ref_for(instance["id"])
    assert env.store.saves == [credential_ref_for(instance["id"])]
    assert env.registry.get(instance["id"]).last_check is None  # only a saved check persists it
    assert body["handler_result"]["data"]["check"]["status"] == "compatible"


def test_create_requires_explicit_confirmation(client, env) -> None:
    body = _create(client, confirmed=False)

    assert body["status"] == "confirmation_required"
    assert len(env.registry.list()) == 1 and env.store.saves == []


def test_create_dry_run_checks_but_saves_nothing(client, env) -> None:
    body = _create(client, dry_run=True)

    assert (body["status"], body["handler_result"]["outcome"]) == ("dry_run", "success")
    env.connection_check.assert_awaited_once()
    assert len(env.registry.list()) == 1 and env.store.saves == [] and env.persister.saved == {}


def test_create_requires_the_wallet_privilege(client, env) -> None:
    env.privileges = frozenset({"Manage"})

    body = _create(client)

    assert body["status"] == "unauthorized"
    assert len(env.registry.list()) == 1 and env.store.saves == []


@pytest.mark.parametrize("status", [InstanceCheckStatus.INCOMPATIBLE, InstanceCheckStatus.UNREACHABLE,
                                    InstanceCheckStatus.AUTH_FAILED])
def test_create_refuses_an_incompatible_instance(client, env, status) -> None:
    env.connection_check.return_value = _check(status)

    body = _create(client)

    assert body["status"] == "execution_failed"
    assert body["handler_result"]["data"]["check"]["status"] == status.value
    assert len(env.registry.list()) == 1 and env.store.saves == []


@pytest.mark.parametrize("url", ["http://iris:52773", "http://IRIS:52773/"])
def test_create_refuses_a_duplicate_url(client, env, url) -> None:
    body = _create(client, base_url=url)

    assert body["status"] == "execution_failed" and "already registered" in body["detail"]
    env.connection_check.assert_not_awaited()
    assert len(env.registry.list()) == 1


def test_create_with_a_failing_wallet_changes_nothing(client, env) -> None:
    env.store.fail_save = True

    body = _create(client)

    assert body["status"] == "execution_failed"
    assert "could not be stored" in body["detail"]
    assert len(env.registry.list()) == 1 and env.persister.saved == {}


@pytest.mark.parametrize(
    "body",
    [{"base_url": "not a url"}, {"name": "bad\nname"}, {"namespace": "bad space"}, {"password": "   "}],
)
def test_create_validation_failures_change_nothing(client, env, body) -> None:
    result = _create(client, **body)

    assert result["status"] == "execution_failed"
    assert CANARY not in json.dumps(result)
    assert len(env.registry.list()) == 1 and env.store.saves == []


def test_create_rejects_unknown_fields(client, env) -> None:
    payload = {"name": "x", "base_url": URL, "username": "ops", "password": CANARY, "force": True}
    assert client.post("/api/iris/instances", json=payload).status_code == 422


# --- update ---


def _update(client, instance_id, **body) -> dict:
    return client.put(f"/api/iris/instances/{instance_id}", json={"confirmed": True} | body).json()


def test_rename_needs_no_connection_check(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)
    env.connection_check.reset_mock()
    saves_before = list(env.store.saves)

    body = _update(client, instance_id, name="Renamed")

    assert (body["status"], body["verification"]["status"]) == ("success", "verified")
    assert env.registry.get(instance_id).name == "Renamed"
    env.connection_check.assert_not_awaited()
    assert env.store.saves == saves_before


@pytest.mark.parametrize("password", [None, "", "   "])
def test_blank_password_keeps_the_stored_credential(client, env, password) -> None:
    _create(client)
    instance_id = _created_id(env)
    saves_before = list(env.store.saves)

    body = _update(client, instance_id, namespace="APP", password=password)

    assert body["status"] == "success"
    assert env.store.saves == saves_before
    assert env.store.secrets[credential_ref_for(instance_id)] == CANARY
    # the connection changed, so it was re-checked with the stored password
    assert env.connection_check.await_args.kwargs["password"].get_secret_value() == CANARY


def test_new_password_replaces_the_credential_after_a_passing_check(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = _update(client, instance_id, password=NEW_CANARY)

    assert body["status"] == "success"
    assert env.store.secrets[credential_ref_for(instance_id)] == NEW_CANARY


def test_update_refused_when_the_new_connection_is_incompatible(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)
    before = env.registry.get(instance_id)
    env.connection_check.return_value = _check(InstanceCheckStatus.AUTH_FAILED)

    body = _update(client, instance_id, base_url="http://iris-3:52773")

    assert body["status"] == "execution_failed"
    assert env.registry.get(instance_id) == before


def test_update_cannot_take_another_instances_url(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = _update(client, instance_id, base_url="http://iris:52773")

    assert body["status"] == "execution_failed" and "already registered" in body["detail"]


@pytest.mark.parametrize("body", [{"name": "Renamed"}, {"password": CANARY}])
def test_primary_cannot_be_updated(client, env, body) -> None:
    result = _update(client, PRIMARY_INSTANCE_ID, **body)

    assert result["status"] == "execution_failed"
    assert env.registry.primary.name == "Primary" and env.store.saves == []


# --- saved check ---


def test_saved_check_persists_last_check(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = client.post(f"/api/iris/instances/{instance_id}/check").json()

    assert body["last_check"]["status"] == "compatible"
    assert env.persister.saved[instance_id].last_check is not None


def test_saved_check_records_a_credential_failure(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)
    env.instance_check.return_value = _check(InstanceCheckStatus.AUTH_FAILED, failure="credential_unavailable")

    body = client.post(f"/api/iris/instances/{instance_id}/check").json()

    assert (body["last_check"]["status"], body["last_check"]["failure"]) == ("auth_failed", "credential_unavailable")
    assert env.registry.get(instance_id).active is True  # a check never changes the definition


def test_primary_check_is_kept_in_memory_only(client, env) -> None:
    body = client.post("/api/iris/instances/primary/check").json()

    assert body["last_check"]["status"] == "compatible"
    assert env.persister.saved == {}


def test_check_of_an_unknown_instance_is_404(client, env) -> None:
    assert client.post("/api/iris/instances/iris-unknown00000/check").status_code == 404


# --- activation ---


def _action(client, instance_id, action, **body) -> dict:
    return client.post(f"/api/iris/instances/{instance_id}/{action}", json={"confirmed": True} | body).json()


def test_deactivate_and_reactivate(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    off = _action(client, instance_id, "deactivate")
    assert (off["status"], off["verification"]["status"]) == ("success", "verified")
    assert env.registry.get(instance_id).active is False
    assert env.persister.saved[instance_id].active is False

    on = _action(client, instance_id, "activate")
    assert on["status"] == "success"
    assert env.registry.get(instance_id).active is True
    env.instance_check.assert_awaited_once()  # activation re-checks


def test_activation_requires_a_passing_check(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)
    _action(client, instance_id, "deactivate")
    env.instance_check.return_value = _check(InstanceCheckStatus.UNREACHABLE)

    body = _action(client, instance_id, "activate")

    assert body["status"] == "execution_failed"
    assert env.registry.get(instance_id).active is False


def test_primary_cannot_be_deactivated(client, env) -> None:
    body = _action(client, PRIMARY_INSTANCE_ID, "deactivate")

    assert body["status"] == "execution_failed"
    assert env.registry.primary.active is True


def test_activation_needs_confirmation(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = _action(client, instance_id, "deactivate", confirmed=False)

    assert body["status"] == "confirmation_required"
    assert env.registry.get(instance_id).active is True


# --- delete ---


def _delete(client, instance_id, **body) -> dict:
    return client.request(
        "DELETE", f"/api/iris/instances/{instance_id}", json={"confirmed": True} | body
    ).json()


def test_delete_removes_credential_and_definition(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = _delete(client, instance_id)

    assert (body["status"], body["verification"]["status"]) == ("success", "verified")
    assert env.registry.get(instance_id) is None
    assert env.store.deletes == [credential_ref_for(instance_id)]
    assert env.persister.deleted == [instance_id]


@pytest.mark.parametrize("instance_id", [PRIMARY_INSTANCE_ID, "iris-unknown00000"])
def test_primary_and_unknown_instances_cannot_be_deleted(client, env, instance_id) -> None:
    body = _delete(client, instance_id)

    assert body["status"] == "execution_failed"
    assert env.registry.primary is not None and env.store.deletes == []


def test_delete_needs_confirmation(client, env) -> None:
    _create(client)
    instance_id = _created_id(env)

    body = _delete(client, instance_id, confirmed=False)

    assert body["status"] == "confirmation_required"
    assert env.registry.get(instance_id) is not None


# --- passwords never leak ---


def test_passwords_never_appear_in_responses_traces_registry_or_logs(client, env, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    responses = [
        client.post("/api/iris/instances/test", json={"base_url": URL, "username": "ops", "password": CANARY}).text,
        json.dumps(_create(client)),
    ]
    instance_id = _created_id(env)
    responses += [
        json.dumps(_update(client, instance_id, password=NEW_CANARY)),
        client.post(f"/api/iris/instances/{instance_id}/check").text,
        client.get("/api/iris/instances").text,
        client.get(f"/api/iris/instances/{instance_id}").text,
        json.dumps(_action(client, instance_id, "deactivate")),
    ]
    env.connection_check.return_value = _check(InstanceCheckStatus.AUTH_FAILED)
    responses.append(json.dumps(_create(client, base_url="http://iris-3:52773", password=CANARY)))
    responses.append(json.dumps(_delete(client, instance_id)))

    traces = json.dumps([t.model_dump(mode="json") for t in trace_store.list_traces()])
    persisted = json.dumps([i.model_dump(mode="json") for i in env.persister.saved.values()])
    for text in (*responses, traces, persisted, caplog.text, repr(env.registry.list())):
        assert CANARY not in text and NEW_CANARY not in text
    assert any(t.operation_name == "instance.create" for t in trace_store.list_traces())


# A rejected request must not echo the submitted password: FastAPI's 422 puts
# the offending value (for a missing field, the whole body) in each error's
# `input`, which the app's validation handler leaves out.
_CREATE = {"name": "Second", "base_url": URL, "username": "ops", "password": CANARY, "confirmed": True}


@pytest.mark.parametrize(
    ("method", "path", "body", "loc"),
    [
        # missing required field: pydantic's input is the whole body
        ("POST", "/api/iris/instances", {k: v for k, v in _CREATE.items() if k != "name"}, ["body", "name"]),
        # invalid fields, including the password itself
        ("POST", "/api/iris/instances", _CREATE | {"confirmed": "maybe"}, ["body", "confirmed"]),
        ("POST", "/api/iris/instances", _CREATE | {"password": {"value": CANARY}}, ["body", "password"]),
        ("PUT", "/api/iris/instances/iris-0123456789ab", {"name": 5, "password": CANARY}, ["body", "name"]),
        ("PUT", "/api/iris/instances/iris-0123456789ab", {"password": [CANARY]}, ["body", "password"]),
        # extra (forbidden) field
        ("POST", "/api/iris/instances", _CREATE | {"force": True}, ["body", "force"]),
        ("PUT", "/api/iris/instances/iris-0123456789ab", {"password": CANARY, "force": True}, ["body", "force"]),
        # a body that isn't an object at all
        ("PUT", "/api/iris/instances/iris-0123456789ab", [CANARY], ["body"]),
    ],
)
def test_validation_errors_never_echo_the_password(client, env, method, path, body, loc) -> None:
    response = client.request(method, path, json=body)

    assert response.status_code == 422
    assert CANARY not in response.text
    errors = response.json()["detail"]
    assert all("input" not in error for error in errors)
    # still useful: where and what
    assert any(error["loc"] == loc and error["msg"] and error["type"] for error in errors), errors
    assert len(env.registry.list()) == 1 and env.store.saves == []
    assert trace_store.list_traces() == []  # rejected before the executor
