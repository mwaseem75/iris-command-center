"""IRIS clients for registered instances, for instance-scoped reads.

The Primary uses the app's shared IRISClient. Any other instance gets its own
IRISClient, built like the connection check (app/instances/handshake.py):
a copy of the settings with the instance's URL, username, namespace and its
password read from the IRIS Wallet. The password stays inside that client;
it's never returned or logged.

Clients are cached per instance and rebuilt when its definition changes
(updated_at also changes when only the password is replaced).
"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.instances.credentials import WalletCredentialStore, resolve_password
from app.instances.models import InstanceDefinition
from app.instances.registry import InstanceRegistry
from app.iris_client.client import IRISClient


class UnknownInstanceError(LookupError):
    """No registered instance has this id."""


class InactiveInstanceError(Exception):
    """The instance is registered but inactive, so it isn't read."""


class InstanceClientPool:
    def __init__(
        self, primary_client: IRISClient, settings: Settings, store: WalletCredentialStore, registry: InstanceRegistry
    ):
        self._primary = primary_client
        self._registry = registry
        self._settings = settings
        self._store = store
        self._clients: dict[str, tuple[tuple, IRISClient]] = {}
        # One at a time: building a client reads the Wallet over the shared
        # Native API connection.
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"InstanceClientPool(cached={sorted(self._clients)!r})"

    async def client_for_id(self, instance_id: str) -> IRISClient:
        """The client for a registered, active instance (by id)."""
        instance = self._registry.get(instance_id)
        if instance is None:
            raise UnknownInstanceError(instance_id)
        if not instance.active:
            raise InactiveInstanceError(instance_id)
        return await self.client_for(instance)

    async def client_for(self, instance: InstanceDefinition) -> IRISClient:
        """The client for `instance`. Raises CredentialStoreError if its password can't be read."""
        if instance.primary:
            return self._primary
        key = (instance.base_url, instance.username, instance.namespace, instance.credential_ref, instance.updated_at)
        async with self._lock:
            cached = self._clients.get(instance.id)
            if cached is not None and cached[0] == key:
                return cached[1]
            password = await asyncio.to_thread(resolve_password, instance, self._settings, self._store)
            client = IRISClient(
                self._settings.model_copy(
                    update={
                        "iris_base_url": instance.base_url.rstrip("/"),
                        "iris_username": instance.username,
                        "iris_password": password,
                        "iris_namespace": instance.namespace,
                    }
                )
            )
            self._clients[instance.id] = (key, client)
        if cached is not None:
            await cached[1].aclose()
        return client

    async def aclose(self) -> None:
        clients = [client for _, client in self._clients.values()]
        self._clients.clear()
        for client in clients:
            await client.aclose()
