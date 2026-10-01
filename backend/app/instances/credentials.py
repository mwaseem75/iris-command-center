"""Credentials of user-defined instances, kept in the IRIS Secure Wallet.

Each instance's password is a %Wallet.KeyValue secret named
"CommandCenter.<instance id>" ({"password": ...}) in the CommandCenter
collection of the Primary. Both of the collection's resources are
%Admin_Wallet:USE, so only sessions holding that privilege can use or edit
the secrets; a secret can't be read back over REST at all.

- Written and deleted with the System Administration API
  (PUT /v2/wallet/collection, PUT and DELETE /v2/wallet/secret).
- Read only here, over the Native API with %Wallet.KeyValue.GetSecretValue
  (verified on IRIS 2026.2), into a SecretStr.

Only refs this module builds are accepted, so a stored or forged ref can't
read another Wallet secret. Passwords are never logged, put in an exception
message, or returned by anything but resolve/read.

The Primary has no ref: its password is IRIS_PASSWORD.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.config import Settings
from app.instances.models import InstanceDefinition
from app.instances.registry import InstanceRegistry, InstanceRegistryError
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISClientError

WALLET_COLLECTION = "CommandCenter"
_WALLET_RESOURCE = "%Admin_Wallet:USE"
_REF_PATTERN = re.compile(rf"^{WALLET_COLLECTION}\.iris-[0-9a-f]{{12}}$")


class CredentialStoreError(Exception):
    """A credential couldn't be stored, read or deleted. Never carries the value."""


def credential_ref_for(instance_id: str) -> str:
    ref = f"{WALLET_COLLECTION}.{instance_id}"
    _check_ref(ref)
    return ref


def _check_ref(ref: str) -> None:
    if not isinstance(ref, str) or not _REF_PATTERN.fullmatch(ref):
        raise CredentialStoreError("Not a Command Center credential reference.")


def _has_value(password: SecretStr | None) -> bool:
    return password is not None and bool(password.get_secret_value().strip())


class WalletCredentialStore:
    """Stores and reads instance passwords in the Primary's Wallet."""

    def __init__(self, client: IRISClient, settings: Settings):
        self._client = client
        self._settings = settings
        self._collection_ready = False
        self._iris: Any = None
        self._connection: Any = None

    def __repr__(self) -> str:
        return f"WalletCredentialStore(collection={WALLET_COLLECTION!r})"

    async def save(self, instance_id: str, password: SecretStr) -> str:
        """Create or replace the instance's secret; returns its ref."""
        if not _has_value(password):
            raise CredentialStoreError("A password is required.")
        ref = credential_ref_for(instance_id)
        await self._ensure_collection()
        try:
            await self._client.put(
                "/v2/wallet/secret",
                params={"name": ref},
                json={
                    "Type": "%Wallet.KeyValue",
                    "WalletSecretConfig": {"Secret": {"password": password.get_secret_value()}},
                },
            )
        except IRISClientError:
            raise CredentialStoreError("The credential could not be stored in the IRIS Wallet.") from None
        return ref

    async def delete(self, ref: str) -> None:
        _check_ref(ref)
        try:
            await self._client.delete("/v2/wallet/secret", params={"name": ref})
        except IRISClientError:
            raise CredentialStoreError("The credential could not be deleted from the IRIS Wallet.") from None

    async def exists(self, ref: str) -> bool:
        """Whether the secret is in the collection (lists names only, never values)."""
        _check_ref(ref)
        try:
            listing = await self._client.get("/v2/wallet/secrets", params={"collection": WALLET_COLLECTION})
        except IRISClientError:
            raise CredentialStoreError("The IRIS Wallet could not be read.") from None
        return any(isinstance(s, dict) and s.get("Name") == ref for s in listing.get("result") or [])

    def read_sync(self, ref: str) -> SecretStr:
        """Blocking (Native API): call from a thread."""
        _check_ref(ref)
        try:
            self._ensure_connected()
            raw = self._iris.classMethodValue("%Wallet.KeyValue", "GetSecretValue", ref)
            password = _password_from(raw)
        except Exception:  # noqa: BLE001 - the value must never reach a message
            raise CredentialStoreError("The credential could not be read from the IRIS Wallet.") from None
        return SecretStr(password)

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        try:
            await self._client.put(
                "/v2/wallet/collection",
                params={"name": WALLET_COLLECTION},
                json={"UseResource": _WALLET_RESOURCE, "EditResource": _WALLET_RESOURCE},
            )
        except IRISClientError:
            raise CredentialStoreError("The Command Center Wallet collection could not be prepared.") from None
        self._collection_ready = True

    def _ensure_connected(self) -> None:
        if self._iris is not None:
            return
        import iris  # noqa: PLC0415 - lazy, like the other Native API writers

        self._connection = iris.connect(
            urlsplit(self._settings.iris_base_url).hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )
        self._iris = iris.createIRIS(self._connection)

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001
                pass
        self._connection = None
        self._iris = None


def _password_from(raw: Any) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(raw)["password"]
    if not isinstance(value, str) or not value:
        raise ValueError("no password in the secret")
    return value


def resolve_password(instance: InstanceDefinition, settings: Settings, store: WalletCredentialStore) -> SecretStr:
    """The password to connect to `instance`. Blocking for user-defined ones."""
    if instance.primary:
        return settings.iris_password
    if instance.credential_ref is None:
        raise CredentialStoreError("This instance has no stored credential.")
    return store.read_sync(instance.credential_ref)


# --- lifecycle: the registry entry and its Wallet secret together ---


async def add_instance(
    registry: InstanceRegistry,
    store: WalletCredentialStore,
    *,
    name: str,
    base_url: str,
    username: str,
    password: SecretStr,
    namespace: str = "USER",
) -> InstanceDefinition:
    """Store the secret first; if the instance then can't be added, remove it."""
    instance_id = registry.new_id()
    ref = await store.save(instance_id, password)
    try:
        return registry.add(
            name=name, base_url=base_url, username=username, namespace=namespace,
            credential_ref=ref, instance_id=instance_id,
        )
    except Exception:
        await store.delete(ref)
        raise


async def update_instance(
    registry: InstanceRegistry,
    store: WalletCredentialStore,
    instance_id: str,
    *,
    password: SecretStr | None = None,
    **changes: Any,
) -> InstanceDefinition:
    """A blank or missing password keeps the stored one."""
    if "credential_ref" in changes:
        raise InstanceRegistryError("The credential reference can't be set directly.")
    instance = registry.update(instance_id, **changes) if changes else _user_defined(registry, instance_id)
    if _has_value(password):
        ref = await store.save(instance.id, password)
        # Always recorded, so updated_at also marks a new password (cached
        # instance clients are rebuilt when it changes).
        instance = registry.update(instance.id, credential_ref=ref)
    return instance


async def delete_instance(registry: InstanceRegistry, store: WalletCredentialStore, instance_id: str) -> None:
    """Delete the secret first, so a password is never left behind without its instance."""
    instance = _user_defined(registry, instance_id)
    if instance.credential_ref is not None:
        await store.delete(instance.credential_ref)
    registry.delete(instance_id)


def _user_defined(registry: InstanceRegistry, instance_id: str) -> InstanceDefinition:
    instance = registry.get(instance_id)
    if instance is None:
        raise InstanceRegistryError(f"No instance with id {instance_id!r}.")
    if instance.primary:
        raise InstanceRegistryError("The Primary instance's credential comes from the environment.")
    return instance
