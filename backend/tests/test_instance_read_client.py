"""Phase 4B step 2: instance-scoped reads (?instance=<id>) for the Dashboard routes.

The registry is real (with a fake persister); the Wallet store and the IRIS
clients are fakes, so no IRIS call is made.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.dependencies import get_instance_clients, get_iris_client
from app.instances.clients import InactiveInstanceError, InstanceClientPool, UnknownInstanceError
from app.instances.credentials import CredentialStoreError, credential_ref_for
from app.instances.registry import InstanceRegistry, primary_from_settings
from app.iris_client.exceptions import IRISConnectionError
from tests.test_instances_registry import _FakePersister, _settings

CANARY = "Pw-READ-CANARY-77aa-not-real!"

DASHBOARD_ROUTES = [
    "/api/iris/info", "/api/iris/namespaces", "/api/iris/databases", "/api/iris/databases/storage",
    "/api/iris/monitor/dashboard", "/api/iris/processes", "/api/iris/web-apps", "/api/iris/tasks",
    "/api/iris/tasks/overview",
    "/api/iris/health",  # Health Center (Phase 4B step 3)
    "/api/iris/issues",  # Issue Resolver: detection only; its fixes stay on the Primary
]


def _info(user: str) -> dict:
    return {"status": {"errors": []}, "result": {"apiVersion": 2, "username": user, "serverVersion": "IRIS 2026.2",
                                                  "systemMode": "", "product": "iris", "namespaces": [], "privileges": {}}}


def _client(user: str) -> AsyncMock:
    client = AsyncMock()

    async def get(path, params=None):
        if path == "/info":
            return _info(user)
        if path == "/v2/namespaces":
            return {"status": {"errors": []}, "result": [{"Name": f"{user}-NS", "Globals": "USER", "Library": "IRISLIB",
                                                          "Routines": "USER", "SysGlobals": "IRISSYS",
                                                          "SysRoutines": "IRISSYS", "TempGlobals": "IRISTEMP"}]}
        raise IRISConnectionError(f"{user} fake has no {path}")

    client.get.side_effect = get
    return client


class FakePool:
    """Resolves ids like InstanceClientPool.client_for_id, with fake clients."""

    def __init__(self, registry) -> None:
        self.registry = registry
        self.clients: dict[str, AsyncMock] = {}
        self.fail = False

    async def client_for_id(self, instance_id):
        instance = self.registry.get(instance_id)
        if instance is None:
            raise UnknownInstanceError(instance_id)
        if not instance.active:
            raise InactiveInstanceError(instance_id)
        return await self.client_for(instance)

    async def client_for(self, instance):
        if self.fail:
            raise CredentialStoreError("The credential could not be read from the IRIS Wallet.")
        return self.clients.setdefault(instance.id, _client(instance.name))


class Env:
    def __init__(self) -> None:
        self.registry = InstanceRegistry(primary_from_settings(_settings()), _FakePersister())
        self.second = self.registry.add(name="IRIS-2", base_url="http://iris-2:52773", username="ops",
                                        credential_ref=credential_ref_for("iris-0123456789ab"),
                                        instance_id="iris-0123456789ab")
        self.primary_client = _client("primary-user")
        self.pool = FakePool(self.registry)


@pytest.fixture
def env(client: TestClient):
    from app.main import app

    state = Env()
    app.dependency_overrides[get_iris_client] = lambda: state.primary_client
    app.dependency_overrides[get_instance_clients] = lambda: state.pool
    yield state


@pytest.mark.parametrize("query", ["", "?instance=primary"])
def test_without_an_instance_the_primary_is_read_as_before(client, env, query) -> None:
    body = client.get(f"/api/iris/info{query}").json()
    assert body["result"]["username"] == "primary-user"
    assert env.pool.clients == {}


@pytest.mark.parametrize("path", DASHBOARD_ROUTES)
def test_dashboard_routes_read_the_selected_instance(client, env, path) -> None:
    response = client.get(f"{path}?instance={env.second.id}")
    # The fake answers /info and /v2/namespaces; anything else raises a
    # connection error, which proves the instance's client was asked.
    assert response.status_code in (200, 502), response.text
    assert env.second.id in env.pool.clients
    assert env.pool.clients[env.second.id].get.await_count >= 1
    env.primary_client.get.assert_not_awaited()


def test_info_and_namespaces_come_from_the_selected_instance(client, env) -> None:
    assert client.get(f"/api/iris/info?instance={env.second.id}").json()["result"]["username"] == "IRIS-2"
    names = client.get(f"/api/iris/namespaces?instance={env.second.id}").json()["result"]
    assert names[0]["Name"] == "IRIS-2-NS"


def test_unknown_instance_is_404(client, env) -> None:
    response = client.get("/api/iris/info?instance=iris-ffffffffffff")
    assert (response.status_code, response.json()["detail"]) == (404, "No instance with this id.")
    env.primary_client.get.assert_not_awaited()


def test_inactive_instance_is_409_and_not_read(client, env) -> None:
    env.registry.set_active(env.second.id, False)
    response = client.get(f"/api/iris/processes?instance={env.second.id}")
    assert (response.status_code, response.json()["detail"]) == (409, "The instance is inactive.")
    assert env.pool.clients == {}
    env.primary_client.get.assert_not_awaited()  # never silently the Primary


def test_unreadable_credential_is_a_generic_502(client, env) -> None:
    env.pool.fail = True
    response = client.get(f"/api/iris/info?instance={env.second.id}")
    assert (response.status_code, response.json()["detail"]) == (502, "The instance's stored credential could not be read.")


def test_unreachable_instance_uses_the_existing_error_mapping(client, env) -> None:
    unreachable = AsyncMock()
    unreachable.get.side_effect = IRISConnectionError("connection refused to http://iris-2:52773")
    env.pool.clients[env.second.id] = unreachable
    response = client.get(f"/api/iris/info?instance={env.second.id}")
    assert (response.status_code, response.json()["detail"]) == (502, "Could not connect to IRIS")


def test_instance_parameter_is_bounded(client, env) -> None:
    assert client.get("/api/iris/info?instance=" + "x" * 65).status_code == 422


# Changes, the Copilot's plan/authorize/execute, and data read through the
# Primary's own connection or kept by Command Center are never instance-scoped.
PRIMARY_ONLY = [
    "/api/iris/python/diagnostics", "/api/iris/messages-log", "/api/iris/copilot/plan",
    "/api/iris/copilot/authorize", "/api/iris/copilot/execute", "/api/iris/observability/traces",
    "/api/iris/operations", "/api/iris/knowledge/search",
]


def _scoped_routes() -> list[tuple[str, str]]:
    from app.main import app

    return sorted((method, path) for path, methods in app.openapi()["paths"].items()
                  for method, spec in methods.items()
                  if any(p.get("name") == "instance" for p in spec.get("parameters", [])))


def test_only_reads_are_instance_scoped() -> None:
    scoped = _scoped_routes()
    paths = {path for _, path in scoped}
    assert set(DASHBOARD_ROUTES) <= paths
    assert {"/api/iris/security/users", "/api/iris/web-apps/detail", "/api/iris/security/audit/records",
            "/api/iris/assistant/query", "/api/iris/copilot/context"} <= paths
    # Every scoped route is a GET, except the Copilot's read-only answer.
    assert [route for route in scoped if route[0] != "get"] == [("post", "/api/iris/copilot/ask")]
    assert not paths & set(PRIMARY_ONLY)


def test_change_routes_have_no_instance_parameter() -> None:
    from app.main import app

    for path, methods in app.openapi()["paths"].items():
        for method, spec in methods.items():
            if method in ("post", "put", "delete") and path != "/api/iris/copilot/ask":
                assert not any(p.get("name") == "instance" for p in spec.get("parameters", [])), (method, path)


@pytest.mark.parametrize("path", [
    "/api/iris/security/users", "/api/iris/security/oauth/overview", "/api/iris/web-apps/detail?name=/csp/user",
    "/api/iris/tasks/manager", "/api/iris/journal/settings", "/api/iris/ext-lang-servers",
])
def test_other_screen_reads_follow_the_selected_instance(client, env, path) -> None:
    joiner = "&" if "?" in path else "?"
    response = client.get(f"{path}{joiner}instance={env.second.id}")
    assert response.status_code in (200, 502), response.text  # the fake has no data for these
    assert env.pool.clients[env.second.id].get.await_count >= 1
    env.primary_client.get.assert_not_awaited()


def test_assistant_reads_the_selected_instance(client, env) -> None:
    body = client.get("/api/iris/assistant/query",
                      params={"message": "Show me the current IRIS system status", "instance": env.second.id}).json()
    assert body["intent"] == "system_status"
    assert env.pool.clients[env.second.id].get.await_count >= 1
    env.primary_client.get.assert_not_awaited()


def test_assistant_change_requests_stay_on_the_primary(client, env) -> None:
    from app.assistant.responses import PRIMARY_ONLY_REPLY

    body = client.get("/api/iris/assistant/query",
                      params={"message": "confirm purge archived true", "instance": env.second.id}).json()
    assert (body["intent"], body["reply"]) == ("journal_operation", PRIMARY_ONLY_REPLY)
    env.primary_client.get.assert_not_awaited()
    env.primary_client.put.assert_not_awaited()
    assert env.pool.clients[env.second.id].put.await_count == 0


def test_copilot_context_reads_the_selected_instance(client, env) -> None:
    client.get(f"/api/iris/copilot/context?instance={env.second.id}")
    assert env.pool.clients[env.second.id].get.await_count >= 1
    env.primary_client.get.assert_not_awaited()


def test_copilot_plan_ignores_an_instance_parameter(client, env) -> None:
    # Planning has no instance parameter: it always reads the Primary's issues.
    client.post(f"/api/iris/copilot/plan?instance={env.second.id}",
                json={"message": "mount database USER", "intent": "resolution_request"})
    assert env.pool.clients == {}


# --- the client pool ---


def _definition(registry, **changes):
    instance = registry.get("iris-0123456789ab")
    return instance.model_copy(update=changes) if changes else instance


@pytest.mark.asyncio
async def test_pool_builds_a_client_from_the_wallet_and_caches_it(monkeypatch) -> None:
    env = Env()
    store = AsyncMock()
    reads = []

    def read_sync(ref):
        reads.append(ref)
        return SecretStr(CANARY)

    store.read_sync = read_sync
    built = []
    monkeypatch.setattr("app.instances.clients.IRISClient", lambda settings: built.append(settings) or AsyncMock())
    pool = InstanceClientPool(env.primary_client, _settings(), store, env.registry)

    first = await pool.client_for_id(env.second.id)
    again = await pool.client_for(env.second)

    assert first is again and len(built) == 1 and reads == [env.second.credential_ref]
    settings = built[0]
    assert (settings.iris_base_url, settings.iris_username, settings.iris_namespace) == ("http://iris-2:52773", "ops", "USER")
    assert settings.iris_password.get_secret_value() == CANARY
    assert await pool.client_for(env.registry.get("primary")) is env.primary_client
    assert CANARY not in repr(pool)


@pytest.mark.asyncio
async def test_pool_rebuilds_and_closes_when_the_definition_changes(monkeypatch) -> None:
    env = Env()
    store = AsyncMock()
    store.read_sync = lambda ref: SecretStr(CANARY)
    monkeypatch.setattr("app.instances.clients.IRISClient", lambda settings: AsyncMock())
    pool = InstanceClientPool(env.primary_client, _settings(), store, env.registry)

    old = await pool.client_for(env.second)
    changed = env.second.model_copy(update={"updated_at": env.second.updated_at + timedelta(seconds=1)})
    new = await pool.client_for(changed)

    assert new is not old
    old.aclose.assert_awaited_once()
    await pool.aclose()
    new.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_credential_failure_propagates_without_the_value(monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    env = Env()
    store = AsyncMock()

    def read_sync(ref):
        raise CredentialStoreError("The credential could not be read from the IRIS Wallet.")

    store.read_sync = read_sync
    pool = InstanceClientPool(env.primary_client, _settings(), store, env.registry)
    with pytest.raises(CredentialStoreError):
        await pool.client_for(env.second)
    assert CANARY not in caplog.text


def test_a_new_password_changes_updated_at(monkeypatch) -> None:
    import asyncio

    from app.instances.credentials import update_instance

    env = Env()
    later = env.second.updated_at + timedelta(minutes=1)
    monkeypatch.setattr("app.instances.registry._now", lambda: later)
    store = AsyncMock()
    store.save.return_value = env.second.credential_ref
    before = env.second.updated_at
    updated = asyncio.run(update_instance(env.registry, store, env.second.id, password=SecretStr(CANARY)))
    assert updated.updated_at > before
    assert CANARY not in json.dumps(updated.model_dump(mode="json"))


def test_no_password_or_wallet_reference_in_scoped_responses(client, env, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    texts = [client.get(f"{path}?instance={env.second.id}").text for path in DASHBOARD_ROUTES]
    env.registry.set_active(env.second.id, False)
    texts.append(client.get(f"/api/iris/info?instance={env.second.id}").text)
    for text in (*texts, caplog.text):
        assert CANARY not in text and "CommandCenter." not in text and "credential_ref" not in text


@pytest.mark.asyncio
async def test_pool_refuses_unknown_and_inactive_ids() -> None:
    env = Env()
    pool = InstanceClientPool(env.primary_client, _settings(), AsyncMock(), env.registry)
    with pytest.raises(UnknownInstanceError):
        await pool.client_for_id("iris-ffffffffffff")
    env.registry.set_active(env.second.id, False)
    with pytest.raises(InactiveInstanceError):
        await pool.client_for_id(env.second.id)


def test_without_startup_the_primary_still_works_and_instances_are_503(client, monkeypatch) -> None:
    # The shared `client` fixture skips startup (no pool): plain reads are unchanged.
    from app.main import app

    monkeypatch.delattr(app.state, "instance_clients", raising=False)  # left by another test's startup
    app.dependency_overrides[get_iris_client] = lambda: _client("primary-user")
    assert client.get("/api/iris/info").status_code == 200
    assert client.get("/api/iris/info?instance=iris-0123456789ab").status_code == 503


def test_health_report_checks_the_selected_instance(client, env) -> None:
    # Every IRIS read behind the report goes to IRIS-2; none to the Primary.
    response = client.get(f"/api/iris/health?instance={env.second.id}")
    assert response.status_code == 200
    assert env.pool.clients[env.second.id].get.await_count > 1
    env.primary_client.get.assert_not_awaited()

    env.registry.set_active(env.second.id, False)
    response = client.get(f"/api/iris/health?instance={env.second.id}")
    assert (response.status_code, response.json()["detail"]) == (409, "The instance is inactive.")
    assert client.get("/api/iris/health?instance=iris-ffffffffffff").status_code == 404
    env.primary_client.get.assert_not_awaited()


def test_issues_for_the_selected_instance_never_come_from_the_primary(client, env) -> None:
    unreachable = AsyncMock()
    unreachable.get.side_effect = IRISConnectionError("connection refused to http://iris-2:52773")
    env.pool.clients[env.second.id] = unreachable
    response = client.get(f"/api/iris/issues?instance={env.second.id}")
    # Each check that can't read IRIS is reported unavailable; the Primary is never read instead.
    assert unreachable.get.await_count >= 1
    env.primary_client.get.assert_not_awaited()
    if response.status_code == 200:
        assert response.json()["issue_checks_unavailable"]
    env.registry.set_active(env.second.id, False)
    assert client.get(f"/api/iris/issues?instance={env.second.id}").status_code == 409
    env.primary_client.get.assert_not_awaited()
