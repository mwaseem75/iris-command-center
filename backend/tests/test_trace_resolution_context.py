"""Tests for the Issue Resolution context on execution traces: the executor
labels the trace from the catalog, the label never changes the outcome, it
survives persistence, and the mount route checks the issue type."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
)
from app.main import app
from app.observability import store
from app.observability.models import ExecutionTrace
from app.resolution.catalog import resolves_with, trace_context

OK = {"errors": [], "summary": ""}
DIRECTORY = "/data/demo/"


class _Handler(OperationHandler):
    """Succeeds without touching IRIS and records the parameters it got."""

    def __init__(self) -> None:
        self.parameters: list[dict[str, Any]] = []

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        self.parameters.append(dict(request.parameters))
        return HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="dry run")

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        self.parameters.append(dict(request.parameters))
        return HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="done")


@pytest.fixture(autouse=True)
def _clean_traces():
    store.clear_traces()
    yield
    store.clear_traces()
    app.dependency_overrides.pop(get_iris_client, None)


async def _run(operation: str, issue_type: str | None, *, privileges=frozenset({"Operate", "Manage"}),
               confirmed: bool = True, dry_run: bool = False):
    executor = OperationExecutor({operation: _Handler()})
    result = await executor.execute(
        OperationRequest(operation_name=operation, parameters={"Directory": DIRECTORY},
                         resolution_issue_type=issue_type),
        ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run),
    )
    (trace,) = store.list_traces()
    return result, trace


# --- the catalog helpers ---


def test_trace_context_comes_from_the_catalog() -> None:
    context = trace_context("database_dismounted", "database.mount", {"Directory": DIRECTORY, "ReadOnly": False})
    assert context is not None
    assert context.issue_type == "database_dismounted"
    assert context.issue_title == "Dismounted database"
    assert context.severity == "high"
    assert context.resource == DIRECTORY
    assert context.issue_id
    assert context.resource_reference is not None
    assert context.resource_reference.canonical_key == DIRECTORY.rstrip("/\\")


@pytest.mark.parametrize("issue_type, operation", [
    (None, "database.mount"),
    ("", "database.mount"),
    ("unknown_issue", "database.mount"),
    ("database_dismounted", "database.dismount"),  # not the operation that resolves it
])
def test_no_context_unless_the_catalog_matches(issue_type: str | None, operation: str) -> None:
    assert trace_context(issue_type, operation, {"Directory": DIRECTORY}) is None


def test_resolves_with() -> None:
    assert resolves_with("database_dismounted", "database.mount")
    assert not resolves_with("database_dismounted", "database.dismount")
    assert not resolves_with("unknown_issue", "database.mount")


# --- the executor ---


@pytest.mark.asyncio
async def test_resolution_request_is_labelled_on_the_trace() -> None:
    result, trace = await _run("database.mount", "database_dismounted")
    assert result.status is OperationResultStatus.SUCCESS
    assert trace.resolution is not None
    assert trace.resolution.issue_title == "Dismounted database"
    assert trace.resolution.resource == DIRECTORY


@pytest.mark.asyncio
async def test_normal_operation_has_no_resolution_context() -> None:
    _, trace = await _run("database.mount", None)
    assert trace.resolution is None


@pytest.mark.asyncio
async def test_mismatched_issue_type_is_not_recorded() -> None:
    _, trace = await _run("database.dismount", "database_dismounted")
    assert trace.resolution is None


@pytest.mark.asyncio
@pytest.mark.parametrize("issue_type", [None, "database_dismounted"])
async def test_label_never_changes_authorization_or_confirmation(issue_type: str | None) -> None:
    denied, trace = await _run("database.mount", issue_type, privileges=frozenset())
    assert denied.status is OperationResultStatus.UNAUTHORIZED
    store.clear_traces()
    unconfirmed, _ = await _run("database.mount", issue_type, confirmed=False)
    assert unconfirmed.status is OperationResultStatus.CONFIRMATION_REQUIRED


@pytest.mark.asyncio
async def test_dry_run_is_labelled_too() -> None:
    result, trace = await _run("database.mount", "database_dismounted", dry_run=True)
    assert result.status is OperationResultStatus.DRY_RUN
    assert trace.resolution is not None


# --- persistence (the same JSON the IRIS trace writer stores) ---


@pytest.mark.asyncio
async def test_resolution_context_survives_a_json_round_trip() -> None:
    _, trace = await _run("database.mount", "database_dismounted")
    restored = ExecutionTrace.model_validate_json(trace.model_dump_json())
    assert restored.resolution == trace.resolution


def test_traces_saved_before_this_field_still_load() -> None:
    old = '{"trace_id": "abc", "operation_name": "database.mount", "start_time": "2026-09-27T09:00:00Z", "spans": []}'
    assert ExecutionTrace.model_validate_json(old).resolution is None


# --- the mount route ---


class _FakeIris:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Any]] = []

    async def get(self, path: str, params: Any = None) -> dict[str, Any]:
        assert path == "/info"
        return {"status": OK, "console": [], "result": {
            "apiVersion": 2, "username": "_SYSTEM", "serverVersion": "IRIS", "systemMode": "", "product": "iris",
            "namespaces": [], "privileges": {"Operate": {"use": True}}}}

    async def post(self, path: str, json: Any = None, params: Any = None) -> dict[str, Any]:
        self.posts.append((path, params))
        return {"status": OK, "console": [], "result": {}}

    async def post_async_task(self, path: str, params: Any = None, json: Any = None) -> str:
        return "task"

    async def wait_for_async_task(self, task_id: str) -> dict[str, Any]:
        return {"Result": {"Mounted": False}}


def _mount(body: dict[str, Any]) -> tuple[Any, _FakeIris]:
    fake = _FakeIris()
    app.dependency_overrides[get_iris_client] = lambda: fake
    with TestClient(app) as client:
        response = client.post("/api/iris/databases/mount", json=body)
    return response, fake


def test_route_labels_a_resolution_dry_run() -> None:
    response, fake = _mount({"Directory": DIRECTORY, "confirmed": True, "dry_run": True,
                             "resolution_issue_type": "database_dismounted"})
    assert response.status_code == 200
    assert response.json()["status"] == "dry_run"
    assert fake.posts == []  # a dry run never mounts
    (trace,) = store.list_traces()
    assert trace.resolution is not None and trace.resolution.issue_type == "database_dismounted"


def test_route_without_the_field_is_unchanged() -> None:
    response, _ = _mount({"Directory": DIRECTORY, "confirmed": True, "dry_run": True})
    assert response.status_code == 200
    (trace,) = store.list_traces()
    assert trace.resolution is None


def test_route_rejects_an_unknown_issue_type_before_calling_iris() -> None:
    response, fake = _mount({"Directory": DIRECTORY, "confirmed": True, "dry_run": True,
                             "resolution_issue_type": "made_up"})
    assert response.status_code == 422
    assert fake.posts == []
    assert store.list_traces() == []


# --- web_app_namespace_missing and the set-enabled route ---


def test_web_app_trace_context_comes_from_the_catalog() -> None:
    context = trace_context("web_app_namespace_missing", "web_app.set_enabled", {"Name": "/csp/orders", "Enabled": False})
    assert context is not None
    assert context.issue_type == "web_app_namespace_missing"
    assert context.issue_title == "Web application with a missing namespace"
    assert context.severity == "medium"
    assert context.resource == "/csp/orders"
    assert context.issue_id
    assert context.resource_reference is not None
    assert context.resource_reference.canonical_key == "/csp/orders"
    assert trace_context("web_app_namespace_missing", "database.mount", {"Directory": DIRECTORY}) is None
    assert trace_context("database_dismounted", "web_app.set_enabled", {"Name": "/csp/orders"}) is None


def _set_enabled(body: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Handler]:
    from app.dependencies import get_caller_privileges

    handler = _Handler()
    monkeypatch.setattr("app.routes.web_apps.WebAppSetEnabledHandler", lambda client: handler)
    app.dependency_overrides[get_iris_client] = lambda: object()
    app.dependency_overrides[get_caller_privileges] = lambda: frozenset({"Manage"})
    try:
        with TestClient(app) as client:
            response = client.post("/api/iris/web-apps/set-enabled", json=body)
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)
    return response, handler


def test_set_enabled_route_labels_a_web_app_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    response, handler = _set_enabled({"Name": "/csp/orders", "Enabled": False, "confirmed": True,
                                      "resolution_issue_type": "web_app_namespace_missing"}, monkeypatch)
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert handler.parameters == [{"Name": "/csp/orders", "Enabled": False}]  # the label is never a parameter
    (trace,) = store.list_traces()
    assert trace.resolution is not None
    assert trace.resolution.issue_type == "web_app_namespace_missing"
    assert trace.resolution.resource == "/csp/orders"


def test_set_enabled_route_without_the_field_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    response, _ = _set_enabled({"Name": "/csp/orders", "Enabled": False, "confirmed": True}, monkeypatch)
    assert response.status_code == 200
    (trace,) = store.list_traces()
    assert trace.resolution is None


@pytest.mark.parametrize("issue_type", ["made_up", "database_dismounted"])
def test_set_enabled_route_rejects_an_issue_type_it_does_not_resolve(
    issue_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    response, handler = _set_enabled({"Name": "/csp/orders", "Enabled": False, "confirmed": True,
                                      "resolution_issue_type": issue_type}, monkeypatch)
    assert response.status_code == 422
    assert handler.parameters == []
    assert store.list_traces() == []


def test_mount_route_rejects_the_web_app_issue_type() -> None:
    response, fake = _mount({"Directory": DIRECTORY, "confirmed": True, "dry_run": True,
                             "resolution_issue_type": "web_app_namespace_missing"})
    assert response.status_code == 422 and fake.posts == []



# --- journal_purge_archived_off and the purge-archived route ---


def test_journal_trace_context_comes_from_the_catalog() -> None:
    context = trace_context("journal_purge_archived_off", "journal.update_purge_archived", {"PurgeArchived": True})
    assert context is not None
    assert context.issue_type == "journal_purge_archived_off"
    assert context.issue_title == "Archived journal files are not purged"
    assert context.severity == "low"
    assert context.resource is None  # the only parameter is fixed, not a resource
    assert context.issue_id
    assert context.resource_reference is not None
    assert context.resource_reference.canonical_key == "journal-settings"
    assert trace_context("journal_purge_archived_off", "web_app.set_enabled", {"Name": "/x"}) is None


def _purge_archived(body: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Handler]:
    from app.dependencies import get_caller_privileges

    handler = _Handler()
    monkeypatch.setattr("app.routes.journal.JournalUpdatePurgeArchivedHandler", lambda client: handler)
    app.dependency_overrides[get_iris_client] = lambda: object()
    app.dependency_overrides[get_caller_privileges] = lambda: frozenset({"Manage"})
    try:
        with TestClient(app) as client:
            response = client.post("/api/iris/journal/purge-archived", json=body)
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)
    return response, handler


def test_purge_archived_route_labels_a_journal_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    response, handler = _purge_archived({"PurgeArchived": True, "confirmed": True,
                                         "resolution_issue_type": "journal_purge_archived_off"}, monkeypatch)
    assert response.status_code == 200 and response.json()["status"] == "success"
    assert handler.parameters == [{"PurgeArchived": True}]  # the label is never a parameter
    (trace,) = store.list_traces()
    assert trace.resolution is not None and trace.resolution.issue_type == "journal_purge_archived_off"


def test_purge_archived_route_without_the_field_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    response, _ = _purge_archived({"PurgeArchived": True, "confirmed": True}, monkeypatch)
    assert response.status_code == 200
    (trace,) = store.list_traces()
    assert trace.resolution is None


@pytest.mark.parametrize("issue_type", ["made_up", "web_app_namespace_missing"])
def test_purge_archived_route_rejects_an_issue_type_it_does_not_resolve(
    issue_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    response, handler = _purge_archived({"PurgeArchived": True, "confirmed": True,
                                         "resolution_issue_type": issue_type}, monkeypatch)
    assert response.status_code == 422
    assert handler.parameters == [] and store.list_traces() == []


def test_purge_archived_route_labels_the_check_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    response, handler = _purge_archived({"PurgeArchived": True, "confirmed": True, "dry_run": True,
                                         "resolution_issue_type": "journal_purge_archived_off"}, monkeypatch)
    assert response.status_code == 200 and response.json()["status"] == "dry_run"
    assert handler.parameters == [{"PurgeArchived": True}]  # only the handler's dry_run ran
    (trace,) = store.list_traces()
    assert trace.resolution is not None and trace.resolution.issue_type == "journal_purge_archived_off"
