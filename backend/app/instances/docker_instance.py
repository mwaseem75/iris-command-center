"""Registers docker-compose.yml's iris-2 as the Docker-managed IRIS-2 at startup.

docker-compose.yml passes iris-2's URL, user, namespace and password to the
backend (IRIS2_*). app/main.py starts StartupDockerInstance in the
background, so the backend never waits for iris-2 and the Primary works
whether or not iris-2 is up. It:

1. Waits until iris-2 answers, then runs the same live compatibility check
   as instance.create (handshake.check_connection). Nothing is stored unless
   it passes.
2. Not registered yet: add_instance, exactly like instance.create, so the
   password goes to the Wallet and the definition to ^CommandCenterInstance.
3. Already registered (same URL, e.g. a previous start or added by hand):
   keeps that definition and its id, aligns username/namespace with the
   environment, and re-stores the password only when the Wallet doesn't hold
   it (the Wallet is lost whenever the Primary's container is recreated) or
   it changed.

A failure is logged as a warning and changes nothing; the next start tries
again. The password is never logged.

Only hosts in DOCKER_MANAGED_HOSTS are accepted, so the instance is always
Docker-managed: it can't be edited or deleted from the console.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.instances.credentials import (
    CredentialStoreError,
    WalletCredentialStore,
    add_instance,
    update_instance,
)
from app.instances.handshake import check_connection
from app.instances.models import DOCKER_MANAGED_HOSTS, InstanceCheck, InstanceCheckStatus, normalize_base_url
from app.instances.registry import InstancePersistenceError, InstanceRegistry, InstanceRegistryError

logger = logging.getLogger(__name__)

INSTANCE_NAME = "IRIS-2"
# iris-2 may still be starting (it doesn't gate the backend): about 2 minutes.
READY_ATTEMPTS = 24
READY_DELAY_SECONDS = 5.0
# A failed login is retried only once: iris-2 sets its password just after
# IRIS starts, but every failure counts towards IRIS's invalid-login limit,
# which disables the account.
AUTH_ATTEMPTS = 2

RegistrationOutcome = Literal[
    "registered",  # added, with its password in the Wallet
    "updated",  # already registered; definition and/or stored password refreshed
    "unchanged",  # already registered and up to date
    "not_configured",  # IRIS2_BASE_URL or IRIS2_PASSWORD not set
    "invalid_config",  # IRIS2_BASE_URL invalid or not a Docker-managed host
    "unreachable",
    "auth_failed",
    "incompatible",
    "failed",  # the registry or the Wallet couldn't be updated
]


def is_configured(settings: Settings) -> bool:
    password = settings.iris2_password
    return bool(settings.iris2_base_url) and password is not None and bool(password.get_secret_value().strip())


class StartupDockerInstance:
    """Started by app/main.py only when is_configured(settings)."""

    def __init__(
        self,
        registry: InstanceRegistry,
        store: WalletCredentialStore,
        settings: Settings,
        *,
        ready_attempts: int = READY_ATTEMPTS,
        ready_delay_seconds: float = READY_DELAY_SECONDS,
    ):
        self._registry = registry
        self._store = store
        self._settings = settings
        self._ready_attempts = ready_attempts
        self._ready_delay_seconds = ready_delay_seconds
        self._writing = False
        self._task: asyncio.Task[RegistrationOutcome] | None = None

    async def run(self) -> RegistrationOutcome:
        """Never raises (except on cancellation). Returns what happened."""
        if not is_configured(self._settings):
            return "not_configured"
        try:
            base_url = normalize_base_url(self._settings.iris2_base_url or "")
        except ValueError:
            logger.warning("IRIS-2 was not auto-registered: IRIS2_BASE_URL is not a valid http(s) URL.")
            return "invalid_config"
        if urlsplit(base_url).hostname not in DOCKER_MANAGED_HOSTS:
            logger.warning(
                "IRIS-2 was not auto-registered: IRIS2_BASE_URL's host is not a Docker-managed host (%s).",
                ", ".join(sorted(DOCKER_MANAGED_HOSTS)),
            )
            return "invalid_config"

        check = await self._wait_for_check(base_url)
        if check.status is not InstanceCheckStatus.COMPATIBLE:
            self._warn_not_registered(base_url, check)
            return check.status.value  # type: ignore[return-value]

        self._writing = True
        try:
            return await self._register(base_url, check)
        except (InstanceRegistryError, InstancePersistenceError, CredentialStoreError, ValidationError) as exc:
            reason = str(exc) if not isinstance(exc, ValidationError) else "invalid instance definition."
            logger.warning("IRIS-2 was not auto-registered: %s", reason)
            return "failed"
        except Exception:  # noqa: BLE001 - never crash the backend over iris-2
            logger.warning("IRIS-2 was not auto-registered: unexpected error.", exc_info=True)
            return "failed"
        finally:
            self._writing = False

    async def _wait_for_check(self, base_url: str) -> InstanceCheck:
        auth_failures = 0
        for attempt in range(self._ready_attempts):
            check = await check_connection(
                base_url=base_url,
                username=self._settings.iris2_username,
                password=self._password,
                namespace=self._settings.iris2_namespace,
                settings=self._settings,
            )
            if check.status is InstanceCheckStatus.AUTH_FAILED:
                auth_failures += 1
                if auth_failures >= AUTH_ATTEMPTS:
                    return check
            elif check.status is not InstanceCheckStatus.UNREACHABLE:
                return check
            if attempt + 1 < self._ready_attempts:
                await asyncio.sleep(self._ready_delay_seconds)
        return check

    async def _register(self, base_url: str, check: InstanceCheck) -> RegistrationOutcome:
        username, namespace = self._settings.iris2_username, self._settings.iris2_namespace
        existing = self._registry.find_by_url(base_url)
        if existing is None:
            instance = await add_instance(
                self._registry, self._store, name=INSTANCE_NAME, base_url=base_url,
                username=username, password=self._password, namespace=namespace,
            )
            await asyncio.to_thread(self._registry.record_check, instance.id, check)
            logger.info("IRIS-2 auto-registered as Docker-managed instance %s (%s).", instance.id, base_url)
            return "registered"
        if existing.primary:
            raise InstanceRegistryError("IRIS2_BASE_URL is the Primary's URL.")

        changes = {
            field: value
            for field, value in (("username", username), ("namespace", namespace))
            if getattr(existing, field) != value
        }
        password = None if await self._password_is_stored(existing.credential_ref) else self._password
        if changes or password is not None:
            await update_instance(self._registry, self._store, existing.id, password=password, **changes)
        await asyncio.to_thread(self._registry.record_check, existing.id, check)
        if changes or password is not None:
            refreshed = sorted(changes) + (["stored password"] if password is not None else [])
            logger.info("IRIS-2 (%s) is already registered; refreshed: %s.", existing.id, ", ".join(refreshed))
            return "updated"
        logger.info("IRIS-2 (%s) is already registered and up to date.", existing.id)
        return "unchanged"

    async def _password_is_stored(self, ref: str | None) -> bool:
        if ref is None:
            return False
        try:
            stored = await asyncio.to_thread(self._store.read_sync, ref)
        except CredentialStoreError:
            return False  # e.g. the Wallet was lost with the Primary's container
        return hmac.compare_digest(
            stored.get_secret_value().encode(), self._password.get_secret_value().encode()
        )

    @property
    def _password(self) -> SecretStr:
        assert self._settings.iris2_password is not None  # is_configured()
        return self._settings.iris2_password

    def _warn_not_registered(self, base_url: str, check: InstanceCheck) -> None:
        if check.status is InstanceCheckStatus.AUTH_FAILED:
            logger.warning(
                "IRIS-2 was not auto-registered: login as %s at %s failed. IRIS2_PASSWORD must match iris-2's "
                "password; after changing it in .env, run `docker compose up -d --force-recreate iris-2`. "
                "The Primary is unaffected.",
                self._settings.iris2_username, base_url,
            )
        elif check.status is InstanceCheckStatus.UNREACHABLE:
            logger.warning(
                "IRIS-2 was not auto-registered: %s could not be reached; the next start will try again. "
                "The Primary is unaffected.",
                base_url,
            )
        else:
            logger.warning(
                "IRIS-2 was not auto-registered: %s is not compatible (%s). The Primary is unaffected.",
                base_url, check.failure,
            )

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Called at shutdown: cancel while waiting for iris-2, but let a
        registration that is writing finish, so it is never left half done."""
        if self._task is None:
            return
        if not self._writing:
            self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
