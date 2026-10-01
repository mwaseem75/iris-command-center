"""The instance registry: the Primary plus user-defined IRIS instances.

The Primary is built from the environment (IRIS_BASE_URL, IRIS_USERNAME,
IRIS_NAMESPACE) on every start and is never stored; it can't be changed,
deactivated or deleted, so the registry always has at least one instance.

User-defined instances are saved to ^CommandCenterInstance("instance", <id>)
as JSON over the Native API (IRISInstanceWriter) and loaded back at startup.
A change is saved to IRIS before memory is updated, so a failed save leaves
both unchanged. IDs are generated once and never change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import Settings
from app.instances.models import PRIMARY_INSTANCE_ID, InstanceCheck, InstanceDefinition

logger = logging.getLogger(__name__)

_UPDATABLE_FIELDS = frozenset({"name", "base_url", "username", "namespace", "credential_ref"})


class InstanceRegistryError(Exception):
    """The change isn't allowed (unknown instance, the Primary, a duplicate)."""


class InstancePersistenceError(Exception):
    """IRIS couldn't be updated; nothing was changed."""


class _InstancePersister(Protocol):
    def save_sync(self, instance: InstanceDefinition) -> bool: ...
    def delete_sync(self, instance_id: str) -> bool: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def primary_from_settings(settings: Settings) -> InstanceDefinition:
    now = _now()
    return InstanceDefinition(
        id=PRIMARY_INSTANCE_ID,
        name="Primary",
        base_url=settings.iris_base_url,
        username=settings.iris_username,
        namespace=settings.iris_namespace,
        active=True,
        primary=True,
        created_at=now,
        updated_at=now,
    )


def _url_key(base_url: str) -> str:
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{(parts.hostname or '').lower()}:{parts.port or ''}{parts.path.rstrip('/')}"


class InstanceRegistry:
    def __init__(self, primary: InstanceDefinition, persister: _InstancePersister | None = None):
        if not primary.primary or primary.id != PRIMARY_INSTANCE_ID:
            raise ValueError("The registry needs the Primary instance.")
        self._instances: dict[str, InstanceDefinition] = {primary.id: primary}
        self._persister = persister

    def load(self, saved: list[InstanceDefinition]) -> int:
        """Add saved user-defined instances at startup (nothing is written back).
        Entries claiming to be the Primary, duplicates and URL clashes are skipped."""
        for instance in saved:
            if instance.primary or instance.id in self._instances:
                logger.warning("Skipping saved instance %r: Primary or duplicate id.", instance.id)
                continue
            if self.url_in_use(instance.base_url):
                logger.warning("Skipping saved instance %r: its URL is already registered.", instance.id)
                continue
            self._instances[instance.id] = instance
        return len(self._instances)

    def list(self) -> list[InstanceDefinition]:
        """The Primary first, then the others in the order they were created."""
        return sorted(self._instances.values(), key=lambda i: (not i.primary, i.created_at, i.id))

    def get(self, instance_id: str) -> InstanceDefinition | None:
        return self._instances.get(instance_id)

    @property
    def primary(self) -> InstanceDefinition:
        return self._instances[PRIMARY_INSTANCE_ID]

    def add(
        self,
        *,
        name: str,
        base_url: str,
        username: str,
        namespace: str = "USER",
        credential_ref: str | None = None,
        instance_id: str | None = None,
    ) -> InstanceDefinition:
        """`instance_id` comes from new_id() when something (the credential)
        must be keyed by the id before the instance is saved."""
        if instance_id is not None and instance_id in self._instances:
            raise InstanceRegistryError(f"An instance with id {instance_id!r} already exists.")
        now = _now()
        instance = InstanceDefinition(
            id=instance_id or self.new_id(),
            name=name,
            base_url=base_url,
            username=username,
            namespace=namespace,
            credential_ref=credential_ref,
            created_at=now,
            updated_at=now,
        )
        if self.url_in_use(instance.base_url):
            raise InstanceRegistryError("An instance with this URL is already registered.")
        self._save(instance)
        return instance

    def update(self, instance_id: str, **changes: Any) -> InstanceDefinition:
        current = self._user_defined(instance_id)
        unknown = set(changes) - _UPDATABLE_FIELDS
        if unknown:
            raise InstanceRegistryError(f"These fields can't be changed: {', '.join(sorted(unknown))}.")
        instance = InstanceDefinition.model_validate(
            {**current.model_dump(), **changes, "updated_at": _now()}
        )
        if self.url_in_use(instance.base_url, ignore=instance_id):
            raise InstanceRegistryError("An instance with this URL is already registered.")
        self._save(instance)
        return instance

    def set_active(self, instance_id: str, active: bool) -> InstanceDefinition:
        if instance_id == PRIMARY_INSTANCE_ID:
            if not active:
                raise InstanceRegistryError("The Primary instance can't be deactivated.")
            return self.primary
        current = self._user_defined(instance_id)
        if current.active is active:
            return current
        instance = current.model_copy(update={"active": active, "updated_at": _now()})
        self._save(instance)
        return instance

    def record_check(self, instance_id: str, check: InstanceCheck) -> InstanceDefinition:
        """Keep an instance's latest check (saved for user-defined instances)."""
        current = self.get(instance_id)
        if current is None:
            raise InstanceRegistryError(f"No instance with id {instance_id!r}.")
        instance = current.model_copy(update={"last_check": check})
        if instance.primary:
            self._instances[instance.id] = instance
        else:
            self._save(instance)
        return instance

    def delete(self, instance_id: str) -> None:
        if instance_id == PRIMARY_INSTANCE_ID:
            raise InstanceRegistryError("The Primary instance can't be deleted.")
        self._user_defined(instance_id)
        if self._persister is not None and not self._persister.delete_sync(instance_id):
            raise InstancePersistenceError("The instance could not be deleted from IRIS.")
        del self._instances[instance_id]

    def _user_defined(self, instance_id: str) -> InstanceDefinition:
        if instance_id == PRIMARY_INSTANCE_ID:
            raise InstanceRegistryError("The Primary instance comes from the environment and can't be changed.")
        instance = self._instances.get(instance_id)
        if instance is None:
            raise InstanceRegistryError(f"No instance with id {instance_id!r}.")
        return instance

    def _save(self, instance: InstanceDefinition) -> None:
        if self._persister is not None and not self._persister.save_sync(instance):
            raise InstancePersistenceError("The instance could not be saved to IRIS.")
        self._instances[instance.id] = instance

    def url_in_use(self, base_url: str, ignore: str | None = None) -> bool:
        key = _url_key(base_url)
        return any(_url_key(i.base_url) == key for i in self._instances.values() if i.id != ignore)

    def new_id(self) -> str:
        while True:
            instance_id = f"iris-{uuid4().hex[:12]}"
            if instance_id not in self._instances:
                return instance_id


class IRISInstanceWriter:
    """Saves user-defined instances to ^CommandCenterInstance("instance", <id>)
    = JSON, over the Native API in iris_namespace (same connection pattern as
    IRISIssueRuleWriter). Blocking: call from a thread. Never raises; save and
    delete return whether IRIS was updated.

    The connection is opened once and kept. If it has gone (e.g. IRIS was
    restarted after the backend started: EPIPE / timeout on the old socket),
    a save or delete drops it, reconnects and tries once more; both are
    idempotent writes of one global node.
    """

    _GLOBAL = "CommandCenterInstance"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._iris: Any = None

    def _ensure_connected(self) -> None:
        if self._iris is not None:
            return
        import iris  # noqa: PLC0415 - lazy, like IRISIssueRuleWriter

        self._connection = iris.connect(
            urlsplit(self._settings.iris_base_url).hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )
        self._iris = iris.createIRIS(self._connection)

    def _reset(self) -> None:
        """Drop the connection so the next call reconnects."""
        connection, self._connection, self._iris = self._connection, None, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - already failing; just discard it
                pass

    def _write(self, write: Callable[[Any], None]) -> None:
        """Run `write(iris)`; on a failure, reconnect and try once more (raises if that fails too)."""
        try:
            self._ensure_connected()
            write(self._iris)
        except Exception:  # noqa: BLE001 - e.g. a connection IRIS has since closed
            self._reset()
            self._ensure_connected()
            write(self._iris)

    def save_sync(self, instance: InstanceDefinition) -> bool:
        if instance.primary:
            return False  # the Primary always comes from the environment
        try:
            self._write(lambda iris: iris.set(instance.model_dump_json(), self._GLOBAL, "instance", instance.id))
            return True
        except Exception:  # noqa: BLE001 - reported to the caller as not saved
            self._reset()
            logger.warning("Could not save instance %s to IRIS (^%s).", instance.id, self._GLOBAL, exc_info=True)
            return False

    def delete_sync(self, instance_id: str) -> bool:
        try:
            self._write(lambda iris: iris.kill(self._GLOBAL, "instance", instance_id))
            return True
        except Exception:  # noqa: BLE001
            self._reset()
            logger.warning("Could not delete instance %s from IRIS (^%s).", instance_id, self._GLOBAL, exc_info=True)
            return False

    def load_all_sync(self) -> list[InstanceDefinition]:
        """Every saved instance; unreadable entries are skipped. Never raises."""
        instances: list[InstanceDefinition] = []
        try:
            self._ensure_connected()
            key = self._iris.nextSubscript(False, self._GLOBAL, "instance", "")
            while key:
                raw = self._iris.get(self._GLOBAL, "instance", key)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    instances.append(InstanceDefinition.model_validate_json(raw))
                except ValueError:
                    logger.warning("Skipping unreadable instance ^%s(\"instance\",%r).", self._GLOBAL, key)
                key = self._iris.nextSubscript(False, self._GLOBAL, "instance", key)
        except Exception:  # noqa: BLE001 - startup must never fail on this
            self._reset()  # a later save reconnects
            logger.warning("Could not load instances from IRIS (^%s).", self._GLOBAL, exc_info=True)
        return instances

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:  # noqa: BLE001
            logger.warning("Error closing the instance registry IRIS connection.", exc_info=True)
        finally:
            self._connection = None
            self._iris = None
