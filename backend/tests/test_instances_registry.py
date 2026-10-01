"""Phase 4A step 1: instance model and registry. No IRIS connection is made."""

from datetime import datetime, timezone

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.instances.models import (
    PRIMARY_INSTANCE_ID,
    InstanceCheck,
    InstanceCheckStatus,
    InstanceDefinition,
)
from app.instances.registry import (
    InstancePersistenceError,
    InstanceRegistry,
    InstanceRegistryError,
    IRISInstanceWriter,
    primary_from_settings,
)

_PRIMARY_PASSWORD = "primary-env-password-not-stored"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        iris_base_url="http://iris:52773",
        iris_username="_SYSTEM",
        iris_password=SecretStr(_PRIMARY_PASSWORD),
        iris_namespace="USER",
    )


class _FakePersister:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.saved: dict[str, InstanceDefinition] = {}
        self.deleted: list[str] = []

    def save_sync(self, instance: InstanceDefinition) -> bool:
        if self.ok:
            self.saved[instance.id] = instance
        return self.ok

    def delete_sync(self, instance_id: str) -> bool:
        if self.ok:
            self.deleted.append(instance_id)
            self.saved.pop(instance_id, None)
        return self.ok


def _registry(persister: _FakePersister | None = None) -> InstanceRegistry:
    return InstanceRegistry(primary_from_settings(_settings()), persister)


def _add(registry: InstanceRegistry, url: str = "http://iris-2:52773", name: str = "Second") -> InstanceDefinition:
    return registry.add(name=name, base_url=url, username="ops", credential_ref="ref-1")


# --- the Primary ---


def test_primary_comes_from_the_environment_and_holds_no_password() -> None:
    primary = primary_from_settings(_settings())

    assert (primary.id, primary.primary, primary.active) == (PRIMARY_INSTANCE_ID, True, True)
    assert (primary.base_url, primary.username, primary.namespace) == ("http://iris:52773", "_SYSTEM", "USER")
    assert primary.credential_ref is None
    assert "password" not in InstanceDefinition.model_fields
    assert _PRIMARY_PASSWORD not in primary.model_dump_json()


def test_registry_always_has_the_primary_first() -> None:
    registry = _registry()
    _add(registry)

    assert registry.primary.id == PRIMARY_INSTANCE_ID
    assert registry.list()[0].primary is True
    assert len(registry.list()) == 2


def test_registry_requires_a_primary() -> None:
    not_primary = primary_from_settings(_settings()).model_copy(update={"primary": False})

    with pytest.raises(ValueError):
        InstanceRegistry(not_primary)


@pytest.mark.parametrize(
    "action",
    [
        lambda r: r.delete(PRIMARY_INSTANCE_ID),
        lambda r: r.set_active(PRIMARY_INSTANCE_ID, False),
        lambda r: r.update(PRIMARY_INSTANCE_ID, name="Renamed"),
    ],
)
def test_primary_cannot_be_deleted_deactivated_or_changed(action) -> None:
    persister = _FakePersister()
    registry = _registry(persister)

    with pytest.raises(InstanceRegistryError):
        action(registry)

    assert registry.primary.active is True and registry.primary.name == "Primary"
    assert persister.saved == {} and persister.deleted == []


def test_activating_the_primary_is_a_no_op() -> None:
    registry = _registry()

    assert registry.set_active(PRIMARY_INSTANCE_ID, True) is registry.primary


def test_at_least_one_instance_always_remains() -> None:
    registry = _registry()
    added = _add(registry)
    registry.delete(added.id)

    with pytest.raises(InstanceRegistryError):
        registry.delete(PRIMARY_INSTANCE_ID)
    assert [i.id for i in registry.list()] == [PRIMARY_INSTANCE_ID]


def test_the_primary_is_never_persisted() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    check = InstanceCheck(checked_at=datetime.now(timezone.utc), status=InstanceCheckStatus.COMPATIBLE)

    registry.record_check(PRIMARY_INSTANCE_ID, check)

    assert registry.primary.last_check == check
    assert persister.saved == {}


# --- user-defined instances ---


def test_add_persists_an_active_instance_with_a_stable_unique_id() -> None:
    persister = _FakePersister()
    registry = _registry(persister)

    first = _add(registry)
    second = _add(registry, url="http://iris-3:52773", name="Third")

    assert first.id != second.id
    assert first.id.startswith("iris-") and first.id != PRIMARY_INSTANCE_ID
    assert (first.active, first.primary, first.credential_ref) == (True, False, "ref-1")
    assert persister.saved == {first.id: first, second.id: second}


def test_update_keeps_the_id_and_creation_time() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    added = _add(registry)

    updated = registry.update(added.id, name="Renamed", namespace="APP")

    assert (updated.id, updated.created_at) == (added.id, added.created_at)
    assert (updated.name, updated.namespace) == ("Renamed", "APP")
    assert updated.updated_at >= added.updated_at
    assert persister.saved[added.id] == updated


@pytest.mark.parametrize("field", ["id", "primary", "active", "created_at", "password", "last_check"])
def test_update_refuses_fields_that_cannot_be_edited(field: str) -> None:
    registry = _registry()
    added = _add(registry)

    with pytest.raises(InstanceRegistryError):
        registry.update(added.id, **{field: "x"})
    assert registry.get(added.id) == added


@pytest.mark.parametrize(
    "url",
    ["http://iris:52773", "http://IRIS:52773/", "http://iris-2:52773"],
)
def test_duplicate_urls_are_refused(url: str) -> None:
    registry = _registry()
    _add(registry)

    with pytest.raises(InstanceRegistryError):
        _add(registry, url=url, name="Duplicate")
    assert len(registry.list()) == 2


def test_update_cannot_take_another_instances_url() -> None:
    registry = _registry()
    second = _add(registry)
    _add(registry, url="http://iris-3:52773", name="Third")

    with pytest.raises(InstanceRegistryError):
        registry.update(second.id, base_url="http://iris-3:52773")


def test_deactivation_preserves_the_definition() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    added = _add(registry)

    inactive = registry.set_active(added.id, False)
    active_again = registry.set_active(added.id, True)

    assert inactive.active is False and registry.get(added.id) is not None
    assert inactive.model_dump(exclude={"active", "updated_at"}) == added.model_dump(exclude={"active", "updated_at"})
    assert active_again.active is True
    assert persister.saved[added.id].active is True


def test_delete_removes_and_persists() -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    added = _add(registry)

    registry.delete(added.id)

    assert registry.get(added.id) is None
    assert persister.deleted == [added.id]


@pytest.mark.parametrize(
    "action",
    [
        lambda r: r.delete("iris-missing"),
        lambda r: r.update("iris-missing", name="x"),
        lambda r: r.set_active("iris-missing", False),
        lambda r: r.record_check(
            "iris-missing", InstanceCheck(checked_at=datetime.now(timezone.utc), status="compatible")
        ),
    ],
)
def test_unknown_instances_are_refused(action) -> None:
    with pytest.raises(InstanceRegistryError):
        action(_registry())


# --- persistence failures leave everything unchanged ---


def test_failed_save_on_add_changes_nothing() -> None:
    registry = _registry(_FakePersister(ok=False))

    with pytest.raises(InstancePersistenceError):
        _add(registry)
    assert [i.id for i in registry.list()] == [PRIMARY_INSTANCE_ID]


@pytest.mark.parametrize(
    "action",
    [
        lambda r, i: r.update(i, name="Renamed"),
        lambda r, i: r.set_active(i, False),
        lambda r, i: r.delete(i),
        lambda r, i: r.record_check(
            i, InstanceCheck(checked_at=datetime.now(timezone.utc), status="compatible")
        ),
    ],
)
def test_failed_persistence_leaves_the_instance_unchanged(action) -> None:
    persister = _FakePersister()
    registry = _registry(persister)
    added = _add(registry)
    persister.ok = False

    with pytest.raises(InstancePersistenceError):
        action(registry, added.id)
    assert registry.get(added.id) == added


# --- loading saved instances ---


def _definition(instance_id: str, url: str, **values) -> InstanceDefinition:
    now = datetime.now(timezone.utc)
    return InstanceDefinition(
        id=instance_id, name=instance_id, base_url=url, username="ops",
        created_at=values.pop("created_at", now), updated_at=now, **values,
    )


def test_load_adds_saved_instances_and_skips_invalid_ones() -> None:
    registry = _registry()
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    good = _definition("iris-aaaa", "http://iris-2:52773", created_at=early)
    inactive = _definition("iris-bbbb", "http://iris-3:52773", active=False)

    registry.load([
        inactive,
        good,
        _definition("primary", "http://elsewhere:52773", primary=True),  # claims to be the Primary
        _definition("iris-aaaa", "http://iris-4:52773"),  # duplicate id
        _definition("iris-cccc", "http://IRIS:52773"),  # the Primary's URL
    ])

    assert [i.id for i in registry.list()] == [PRIMARY_INSTANCE_ID, "iris-aaaa", "iris-bbbb"]
    assert registry.get("iris-bbbb").active is False
    assert registry.primary.base_url == "http://iris:52773"


def test_load_writes_nothing_back() -> None:
    persister = _FakePersister()
    registry = _registry(persister)

    registry.load([_definition("iris-aaaa", "http://iris-2:52773")])

    assert persister.saved == {}


# --- the model ---


@pytest.mark.parametrize(
    "url",
    [
        "ftp://iris-2:52773",
        "iris-2:52773",
        "http://ops:secret@iris-2:52773",
        "http://iris-2:52773/?token=abc",
        "http://iris-2:52773/#x",
    ],
)
def test_unsafe_or_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        _definition("iris-aaaa", url)


def test_definitions_reject_unknown_fields_such_as_a_password() -> None:
    data = _definition("iris-aaaa", "http://iris-2:52773").model_dump() | {"password": "x"}

    with pytest.raises(ValidationError):
        InstanceDefinition.model_validate(data)


@pytest.mark.parametrize("instance_id", ["", "a", "Has-Upper", "has space", "-leading", "x" * 41])
def test_invalid_ids_are_rejected(instance_id: str) -> None:
    with pytest.raises(ValidationError):
        _definition(instance_id, "http://iris-2:52773")


def test_trailing_slash_is_normalized() -> None:
    assert _definition("iris-aaaa", "http://iris-2:52773/").base_url == "http://iris-2:52773"


# --- the IRIS writer (^CommandCenterInstance), with a fake Native API ---


class _FakeIRIS:
    def __init__(self) -> None:
        self.nodes: dict[tuple, str] = {}

    def set(self, value, *subscripts) -> None:
        self.nodes[subscripts] = value

    def get(self, *subscripts):
        return self.nodes.get(subscripts)

    def kill(self, *subscripts) -> None:
        self.nodes.pop(subscripts, None)

    def nextSubscript(self, reverse, global_name, level, key):  # noqa: N802 - Native API name
        keys = sorted(s[2] for s in self.nodes if s[:2] == (global_name, level))
        later = [k for k in keys if k > key] if key else keys
        return later[0] if later else ""


def _writer(fake: _FakeIRIS) -> IRISInstanceWriter:
    writer = IRISInstanceWriter(_settings())
    writer._iris = fake  # already "connected"
    return writer


def test_writer_round_trips_instances_in_the_global() -> None:
    fake = _FakeIRIS()
    writer = _writer(fake)
    first = _definition("iris-aaaa", "http://iris-2:52773")
    second = _definition("iris-bbbb", "http://iris-3:52773", active=False)

    assert writer.save_sync(first) and writer.save_sync(second)

    assert set(fake.nodes) == {
        ("CommandCenterInstance", "instance", "iris-aaaa"),
        ("CommandCenterInstance", "instance", "iris-bbbb"),
    }
    assert writer.load_all_sync() == [first, second]
    assert writer.delete_sync("iris-aaaa")
    assert writer.load_all_sync() == [second]


def test_writer_never_saves_the_primary() -> None:
    fake = _FakeIRIS()

    assert _writer(fake).save_sync(primary_from_settings(_settings())) is False
    assert fake.nodes == {}


def test_writer_skips_unreadable_entries() -> None:
    fake = _FakeIRIS()
    writer = _writer(fake)
    good = _definition("iris-aaaa", "http://iris-2:52773")
    writer.save_sync(good)
    fake.nodes[("CommandCenterInstance", "instance", "iris-zzzz")] = "{not json"

    assert writer.load_all_sync() == [good]


def test_writer_never_raises_when_iris_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    writer = IRISInstanceWriter(_settings())

    def fail() -> None:
        raise ConnectionError("no superserver")

    monkeypatch.setattr(writer, "_ensure_connected", fail)

    assert writer.save_sync(_definition("iris-aaaa", "http://iris-2:52773")) is False
    assert writer.delete_sync("iris-aaaa") is False
    assert writer.load_all_sync() == []


# --- IRISInstanceWriter: a connection IRIS has closed (e.g. IRIS restarted) ---


class _FakeIrisModule:
    """Stands in for the `iris` Native API module: numbered connections, one
    global store, and connections that can "die" like after an IRIS restart."""

    def __init__(self) -> None:
        self.globals: dict[tuple, str] = {}
        self.connections: list[dict] = []
        self.down = False  # IRIS not accepting connections

    def connect(self, *args):
        if self.down:
            raise RuntimeError("<COMMUNICATION LINK ERROR> Failed to connect")
        connection = {"dead": False, "closed": False}
        self.connections.append(connection)

        class Connection:
            def close(self_inner):
                connection["closed"] = True

        handle = Connection()
        handle.state = connection
        return handle

    def createIRIS(self, handle):  # noqa: N802 - Native API name
        module, state = self, handle.state

        class Native:
            def _check(self_inner):
                if state["dead"] or state["closed"]:
                    raise RuntimeError("<COMMUNICATION LINK ERROR> Failed to send message; Error code: 32 EPIPE")

            def set(self_inner, value, *subscripts):
                self_inner._check()
                module.globals[subscripts] = value

            def kill(self_inner, *subscripts):
                self_inner._check()
                module.globals.pop(subscripts, None)

            def nextSubscript(self_inner, reverse, *subscripts):  # noqa: N802
                self_inner._check()
                return ""

        return Native()


@pytest.fixture
def fake_iris(monkeypatch) -> _FakeIrisModule:
    import sys

    module = _FakeIrisModule()
    monkeypatch.setitem(sys.modules, "iris", module)
    return module


def _ovh_definition(instance_id: str = "iris-b88b4c354a7e") -> InstanceDefinition:
    registry = InstanceRegistry(primary_from_settings(_settings()))
    return registry.add(name="OVH", base_url="https://ovh.example:52773", username="ops",
                        credential_ref=f"CommandCenter.{instance_id}", instance_id=instance_id)


def test_a_save_after_iris_dropped_the_connection_reconnects_and_persists(fake_iris) -> None:
    from app.instances.registry import IRISInstanceWriter

    writer = IRISInstanceWriter(_settings())
    writer.load_all_sync()                 # startup opens the kept connection
    fake_iris.connections[0]["dead"] = True   # IRIS restarted: that socket is gone (EPIPE)

    instance = _ovh_definition()
    assert writer.save_sync(instance) is True
    assert fake_iris.globals[("CommandCenterInstance", "instance", instance.id)] == instance.model_dump_json()
    assert len(fake_iris.connections) == 2 and fake_iris.connections[0]["closed"]  # the dead one is dropped
    # The new connection is kept for the next write.
    assert writer.delete_sync(instance.id) is True
    assert len(fake_iris.connections) == 2
    assert ("CommandCenterInstance", "instance", instance.id) not in fake_iris.globals


def test_a_save_while_iris_is_still_down_fails_but_the_next_one_reconnects(fake_iris) -> None:
    from app.instances.registry import IRISInstanceWriter

    writer = IRISInstanceWriter(_settings())
    writer.load_all_sync()
    fake_iris.connections[0]["dead"] = True
    fake_iris.down = True
    assert writer.save_sync(_ovh_definition()) is False   # reported, not silently "saved"

    fake_iris.down = False                               # IRIS is back: no permanently stale connection
    instance = _ovh_definition()
    assert writer.save_sync(instance) is True
    assert ("CommandCenterInstance", "instance", instance.id) in fake_iris.globals
