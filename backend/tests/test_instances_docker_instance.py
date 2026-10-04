"""Automatic registration of docker-compose.yml's iris-2 as the Docker-managed IRIS-2.

The registry is real (with a fake persister); the Wallet store is a fake; the
compatibility handshake is patched. No IRIS call. A canary password proves it
never reaches logs or the saved definition.
"""

import logging
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.instances import docker_instance
from app.instances.credentials import credential_ref_for
from app.instances.docker_instance import StartupDockerInstance, is_configured
from app.instances.models import InstanceCheckStatus, InstanceView
from app.instances.registry import InstanceRegistry, primary_from_settings
from tests.test_instances_registry import _FakePersister, _settings
from tests.test_instances_routes import DOCKER_URL, FakeStore, _check, _delete, _update

CANARY = "Pw-IRIS2-CANARY-7c4d-not-real!"
OLD_CANARY = "Pw-IRIS2-OLD-CANARY-2e9a-not-real!"


def _iris2_settings(**overrides):
    values = {"iris2_base_url": DOCKER_URL, "iris2_password": SecretStr(CANARY)} | overrides
    return _settings().model_copy(update=values)


class _Env:
    def __init__(self, monkeypatch, *checks, persister: _FakePersister | None = None):
        self.persister = persister or _FakePersister()
        self.registry = InstanceRegistry(primary_from_settings(_settings()), self.persister)
        self.registry.load(list(self.persister.saved.values()))
        self.store = FakeStore()
        self.check = AsyncMock(side_effect=list(checks) or None, return_value=_check())
        monkeypatch.setattr(docker_instance, "check_connection", self.check)

    async def run(self, settings=None, **kwargs) -> str:
        kwargs = {"ready_attempts": 3, "ready_delay_seconds": 0} | kwargs
        return await StartupDockerInstance(self.registry, self.store, settings or _iris2_settings(), **kwargs).run()

    def others(self):
        return [i for i in self.registry.list() if not i.primary]


# --- registration ---


@pytest.mark.asyncio
async def test_registers_iris_2_with_its_password_in_the_wallet(monkeypatch, caplog) -> None:
    env = _Env(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        assert await env.run() == "registered"

    primary, iris2 = env.registry.list()
    assert primary.primary and primary.name == "Primary"
    assert (iris2.name, iris2.base_url, iris2.username, iris2.namespace, iris2.active) == (
        "IRIS-2", DOCKER_URL, "_SYSTEM", "USER", True)
    assert iris2.credential_ref == credential_ref_for(iris2.id)
    assert env.store.secrets == {iris2.credential_ref: CANARY}
    assert iris2.last_check is not None and iris2.last_check.status is InstanceCheckStatus.COMPATIBLE
    # Saved without the password; the check ran with the configured connection.
    assert CANARY not in env.persister.saved[iris2.id].model_dump_json()
    kwargs = env.check.await_args.kwargs
    assert (kwargs["base_url"], kwargs["username"], kwargs["namespace"]) == (DOCKER_URL, "_SYSTEM", "USER")
    assert kwargs["password"].get_secret_value() == CANARY
    assert CANARY not in caplog.text
    assert "IRIS-2 auto-registered" in caplog.text


@pytest.mark.asyncio
async def test_registered_iris_2_is_docker_managed_and_protected(client, monkeypatch) -> None:
    from tests.test_instances_routes import Env

    from app.main import app
    from app.dependencies import get_caller_privileges, get_credential_store, get_instance_registry

    routes = Env(monkeypatch)  # the route handlers' handshake is patched too
    env = _Env(monkeypatch)
    env.registry, env.store = routes.registry, routes.store
    assert await env.run() == "registered"
    (iris2,) = env.others()
    app.dependency_overrides[get_instance_registry] = lambda: env.registry
    app.dependency_overrides[get_credential_store] = lambda: env.store
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_caller_privileges] = lambda: routes.privileges

    assert InstanceView.of(iris2).docker_managed
    listed = client.get("/api/iris/instances").json()["instances"]
    assert [(i["name"], i["docker_managed"]) for i in listed] == [("Primary", False), ("IRIS-2", True)]
    for body in (_update(client, iris2.id, name="Renamed"), _delete(client, iris2.id)):
        assert body["handler_result"]["outcome"] == "failure"
        assert "managed by Docker Compose" in body["handler_result"]["detail"]
    assert env.registry.get(iris2.id).name == "IRIS-2"
    assert env.store.secrets == {iris2.credential_ref: CANARY}


# --- idempotent restarts ---


@pytest.mark.asyncio
async def test_a_restart_reuses_the_registration_without_duplicates(monkeypatch) -> None:
    first = _Env(monkeypatch)
    assert await first.run() == "registered"
    (registered,) = first.others()

    # A new backend process: same saved definitions, same Wallet.
    restarted = _Env(monkeypatch, persister=first.persister)
    restarted.store = first.store
    for _ in range(2):
        assert await restarted.run() == "unchanged"

    assert [i.id for i in restarted.others()] == [registered.id]
    assert first.store.saves == [registered.credential_ref]  # never re-stored
    assert len(first.persister.saved) == 1


@pytest.mark.asyncio
async def test_an_existing_registration_gets_its_lost_wallet_secret_back(monkeypatch) -> None:
    """After `docker compose down` the Primary's Wallet is empty but the definition persists."""
    first = _Env(monkeypatch)
    await first.run()
    (registered,) = first.others()

    restarted = _Env(monkeypatch, persister=first.persister)  # new, empty Wallet
    assert await restarted.run() == "updated"

    (instance,) = restarted.others()
    assert (instance.id, instance.created_at) == (registered.id, registered.created_at)
    assert restarted.store.secrets == {registered.credential_ref: CANARY}


@pytest.mark.asyncio
async def test_an_existing_registration_is_aligned_with_the_environment(monkeypatch) -> None:
    """IRIS-2 added by hand earlier (other user, stale password): reused and updated, not duplicated."""
    env = _Env(monkeypatch)
    manual = env.registry.add(name="My iris-2", base_url=DOCKER_URL + "/", username="ops",
                              credential_ref=credential_ref_for("iris-0123456789ab"), instance_id="iris-0123456789ab")
    env.store.secrets[manual.credential_ref] = OLD_CANARY

    assert await env.run() == "updated"

    (instance,) = env.others()
    assert (instance.id, instance.name, instance.username) == (manual.id, "My iris-2", "_SYSTEM")
    assert env.store.secrets == {manual.credential_ref: CANARY}


@pytest.mark.asyncio
async def test_user_defined_instances_are_left_alone(monkeypatch) -> None:
    env = _Env(monkeypatch)
    other = env.registry.add(name="OVH", base_url="https://ovh.example:52773", username="ops",
                             credential_ref=credential_ref_for("iris-aaaaaaaaaaaa"), instance_id="iris-aaaaaaaaaaaa")

    assert await env.run() == "registered"

    assert env.registry.get(other.id) == other
    assert [i.name for i in env.registry.list()] == ["Primary", "OVH", "IRIS-2"]


# --- failures: nothing stored, the Primary unaffected ---


@pytest.mark.asyncio
async def test_failed_login_stores_nothing_and_warns_without_the_password(monkeypatch, caplog) -> None:
    failed = _check(InstanceCheckStatus.AUTH_FAILED)
    env = _Env(monkeypatch, failed, failed, failed, failed)
    with caplog.at_level(logging.DEBUG):
        assert await env.run(ready_attempts=10) == "auth_failed"

    # Retried once only: every failure counts towards iris-2's invalid-login limit.
    assert env.check.await_count == docker_instance.AUTH_ATTEMPTS == 2
    assert env.others() == [] and env.store.saves == [] and env.persister.saved == {}
    assert [i.name for i in env.registry.list()] == ["Primary"]
    assert "IRIS-2 was not auto-registered: login as _SYSTEM" in caplog.text
    assert CANARY not in caplog.text


@pytest.mark.asyncio
async def test_unreachable_iris_2_is_waited_for_then_registered(monkeypatch) -> None:
    down = _check(InstanceCheckStatus.UNREACHABLE)
    env = _Env(monkeypatch, down, down, _check())
    assert await env.run(ready_attempts=3) == "registered"
    assert env.check.await_count == 3


@pytest.mark.asyncio
async def test_iris_2_that_stays_down_is_not_registered(monkeypatch, caplog) -> None:
    down = _check(InstanceCheckStatus.UNREACHABLE)
    env = _Env(monkeypatch, down, down, down)
    with caplog.at_level(logging.WARNING):
        assert await env.run(ready_attempts=3) == "unreachable"
    assert env.others() == [] and env.store.saves == []
    assert "could not be reached" in caplog.text


@pytest.mark.asyncio
async def test_a_wallet_failure_leaves_no_partial_registration(monkeypatch, caplog) -> None:
    env = _Env(monkeypatch)
    env.store.fail_save = True
    with caplog.at_level(logging.WARNING):
        assert await env.run() == "failed"
    assert env.others() == [] and env.persister.saved == {} and env.store.secrets == {}
    assert "IRIS-2 was not auto-registered" in caplog.text


@pytest.mark.asyncio
async def test_a_registry_failure_removes_the_stored_secret(monkeypatch) -> None:
    env = _Env(monkeypatch, persister=_FakePersister(ok=False))
    assert await env.run() == "failed"
    assert env.others() == [] and env.store.secrets == {}


@pytest.mark.parametrize(
    "overrides",
    [{"iris2_base_url": "http://elsewhere:52773"}, {"iris2_base_url": "not a url"}],
)
@pytest.mark.asyncio
async def test_only_a_docker_managed_url_is_registered(monkeypatch, overrides) -> None:
    env = _Env(monkeypatch)
    assert await env.run(_iris2_settings(**overrides)) == "invalid_config"
    env.check.assert_not_awaited()
    assert env.others() == []


@pytest.mark.parametrize(
    "overrides",
    [{"iris2_base_url": None}, {"iris2_password": None}, {"iris2_password": SecretStr("  ")}],
)
def test_registration_needs_a_url_and_a_password(overrides) -> None:
    assert not is_configured(_iris2_settings(**overrides))
    assert is_configured(_iris2_settings())


# --- startup ---


@pytest.fixture
def lifespan_env(monkeypatch: pytest.MonkeyPatch):
    import app.main as main_module

    for name in ("ENABLE_KNOWLEDGE_SEARCH", "PERSIST_TRACES_TO_IRIS", "PERSIST_ISSUE_RULES_TO_IRIS",
                 "AUTO_RUN_DEMO_ACTIVITY"):
        monkeypatch.setenv(name, "false")
    monkeypatch.setattr("app.instances.registry.IRISInstanceWriter.load_all_sync", lambda self: [])
    get_settings.cache_clear()
    yield main_module, monkeypatch
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_startup_without_iris2_settings_registers_nothing(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.delenv("IRIS2_BASE_URL", raising=False)
    monkeypatch.delenv("IRIS2_PASSWORD", raising=False)
    started = AsyncMock()
    monkeypatch.setattr(StartupDockerInstance, "run", started)

    async with main_module.lifespan(main_module.app):
        pass

    started.assert_not_awaited()


class _Recorded(StartupDockerInstance):
    created: list["_Recorded"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, ready_delay_seconds=0, **kwargs)
        _Recorded.created.append(self)


@pytest.mark.asyncio
async def test_startup_keeps_the_primary_when_iris_2_cannot_be_registered(lifespan_env, caplog) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("IRIS2_BASE_URL", DOCKER_URL)
    monkeypatch.setenv("IRIS2_PASSWORD", CANARY)
    monkeypatch.setattr(docker_instance, "check_connection", AsyncMock(return_value=_check(InstanceCheckStatus.AUTH_FAILED)))
    monkeypatch.setattr(docker_instance, "StartupDockerInstance", _Recorded)
    _Recorded.created = []

    with caplog.at_level(logging.WARNING):
        async with main_module.lifespan(main_module.app):
            # Startup returned without waiting for iris-2; let the background task finish.
            (registration,) = _Recorded.created
            assert await registration._task == "auth_failed"
            registry = main_module.app.state.instance_registry
            assert [i.name for i in registry.list()] == ["Primary"]
            assert registry.primary.active

    assert "IRIS-2 was not auto-registered" in caplog.text
    assert CANARY not in caplog.text
