"""Tests for task.run_now. Every test uses a fake/mock IRISClient — no real
network call is made, and no test (or anything else in this project)
performs a real POST /v2/task/run.

The fake IRIS mirrors IRIS's own implementation (see
app/execution/task_run_now_handler.py's docstring): GET /v2/task/info and
GET /v2/task answer 404 for an unknown id, POST /v2/task/run answers `{}`,
and a run shows up in /v2/task/info as a changed LastSchedule (the Task
Manager picked it up) or as Status -1 (running) — or, within a short window,
not at all.
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.execution.task_run_now_handler import TaskRunNowHandler
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app
from app.observability.store import clear_traces, list_traces

_OPERATION_NAME = "task.run_now"
_ENVELOPE = {"status": {"errors": [], "summary": ""}, "console": []}
_PRIVILEGES = frozenset({"Task"})


def _info(task_type: str = "User", *, suspended: Any = False, status: str = "1") -> dict[str, Any]:
    info = {"Type": task_type, "Status": status, "Error": "Success", "LastSchedule": "2026-09-24 01:00:00",
            "LastStarted": "2026-09-24 01:00:05", "LastFinished": "2026-09-24 01:00:09",
            "NextScheduled": "2026-09-26 01:00:00", "Suspended": suspended}
    if suspended is None:
        del info["Suspended"]
    return info


_TASKS: dict[int, dict[str, Any]] = {
    101: {"name": "Nightly Export", "info": _info()},
    102: {"name": "Paused Report", "info": _info(suspended=True)},
    103: {"name": "Busy Job", "info": _info(status="-1")},
    104: {"name": "Odd Job", "info": _info(suspended=None)},
    1: {"name": "Switch Journal", "info": _info("System")},
    2: {"name": "Purge Journal", "info": _info("System")},
    13: {"name": "Feature Tracker", "info": _info("System")},
    50: {"name": "Maintenance Job", "info": _info("Maintenance")},
}


class FakeIris:
    """GET /v2/task, /v2/task/info, /v2/task/manager and POST /v2/task/run.
    `run_effect` decides what a run makes visible: "picked-up" changes
    LastSchedule, "running" sets Status -1, "nothing" changes nothing."""

    def __init__(self) -> None:
        self.tasks = copy.deepcopy(_TASKS)
        self.manager_status: Any = "Running"
        self.run_effect = "picked-up"
        self.post_error: int | None = None
        self.info_privileges: frozenset[str] = _PRIVILEGES
        self.client = AsyncMock()
        self.client.get.side_effect = self._get
        self.client.post.side_effect = self._post

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path in ("/v2/task", "/v2/task/info"):
            task = self.tasks.get(params["id"])
            if task is None:
                raise IRISResponseError(404)
            if path == "/v2/task":
                return {**_ENVELOPE, "result": {"Name": task["name"], "TaskClass": "User.Export", "Settings": {}}}
            return {**_ENVELOPE, "result": copy.deepcopy(task["info"])}
        if path == "/v2/task/manager":
            return {**_ENVELOPE, "result": {} if self.manager_status is None else {"Status": self.manager_status}}
        if path == "/info":
            return {**_ENVELOPE, "result": {
                "apiVersion": 2, "username": "test-user", "serverVersion": "IRIS 2026.2", "systemMode": "",
                "product": "iris", "namespaces": [{"name": "%SYS"}],
                "privileges": {p: {"use": True} for p in sorted(self.info_privileges)},
            }}
        raise AssertionError(f"unexpected GET {path}")

    async def _post(self, path: str, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path == "/v2/task/run"
        if self.post_error:
            raise IRISResponseError(self.post_error)
        info = self.tasks[params["id"]]["info"]
        if self.run_effect == "picked-up":
            info["LastSchedule"] = "2026-09-25 12:00:00"
        elif self.run_effect == "running":
            info["Status"] = "-1"
        return {**_ENVELOPE, "result": {}}


@pytest.fixture
def iris() -> FakeIris:
    return FakeIris()


@pytest.fixture
def executor(iris: FakeIris) -> OperationExecutor:
    return OperationExecutor({_OPERATION_NAME: TaskRunNowHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))})


def _request(task_id: Any = 101, **extra: Any) -> OperationRequest:
    return OperationRequest(operation_name=_OPERATION_NAME, parameters={"Id": task_id, **extra})


def _context(*, privileges: frozenset[str] = _PRIVILEGES, confirmed: bool = True, dry_run: bool = False) -> ExecutionContext:
    return ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run)


# --- authorization / confirmation (the executor never reaches the handler) ---


@pytest.mark.asyncio
async def test_missing_task_privilege_is_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Operate", "Manage"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    iris.client.get.assert_not_awaited()
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(confirmed=False))

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    iris.client.get.assert_not_awaited()
    iris.client.post.assert_not_awaited()


# --- dry run ---


@pytest.mark.asyncio
async def test_dry_run_previews_exact_request_without_running(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    data = result.handler_result.data
    assert data["request"] == {"method": "POST", "path": "/v2/task/run", "query": {"id": 101}, "body": {"RunNow": True}}
    assert data["name"] == "Nightly Export" and data["type"] == "User"
    assert "No request was sent" in result.handler_result.detail
    assert "60 seconds" in result.handler_result.detail
    iris.client.post.assert_not_awaited()
    assert iris.tasks[101]["info"]["LastSchedule"] == "2026-09-24 01:00:00"


@pytest.mark.asyncio
async def test_dry_run_of_a_refused_task_is_also_refused(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(1), _context(dry_run=True))

    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    iris.client.post.assert_not_awaited()


# --- refusals ---


@pytest.mark.asyncio
@pytest.mark.parametrize(("task_id", "task_type"), [(1, "System"), (2, "System"), (13, "System"), (50, "Maintenance")])
async def test_system_and_maintenance_tasks_are_hard_denied(
    executor: OperationExecutor, iris: FakeIris, task_id: int, task_type: str
) -> None:
    result = await executor.execute(_request(task_id), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    assert result.handler_result.data["type"] == task_type
    assert "only User tasks" in result.handler_result.detail
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_task_is_rejected(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(999), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "no task with id 999" in result.handler_result.detail
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("task_id", "phrase"), [(102, "is suspended"), (104, "unknown suspended state")])
async def test_suspended_or_unknown_suspension_is_refused(
    executor: OperationExecutor, iris: FakeIris, task_id: int, phrase: str
) -> None:
    result = await executor.execute(_request(task_id), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert phrase in result.handler_result.detail
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_running_is_a_no_op_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(103), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["no_change"] is True
    assert "already running" in result.handler_result.detail
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_status", ["Suspended", "Not running", None])
async def test_task_manager_not_running_is_refused(
    executor: OperationExecutor, iris: FakeIris, manager_status: Any
) -> None:
    iris.manager_status = manager_status

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "not Running" in result.handler_result.detail
    iris.client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters",
    [{"Id": 0}, {"Id": -3}, {"Id": "101"}, {"Id": 101.0}, {"Id": True}, {},
     {"Id": 101, "Datetime": "2026-12-31 23:59:59"}, {"Id": 101, "RunNow": False}, {"Id": 101, "force": True}],
)
async def test_invalid_requests_are_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, parameters: dict[str, Any]
) -> None:
    result = await executor.execute(OperationRequest(operation_name=_OPERATION_NAME, parameters=parameters), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.detail.startswith("Invalid task.run_now request")
    iris.client.get.assert_not_awaited()
    iris.client.post.assert_not_awaited()


# --- execution + verification ---


@pytest.mark.asyncio
async def test_run_sends_only_run_now_and_verifies_pickup(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.post.assert_awaited_once_with("/v2/task/run", json={"RunNow": True}, params={"id": 101})
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "LastSchedule '2026-09-24 01:00:00' → '2026-09-25 12:00:00'" in result.verification.detail


@pytest.mark.asyncio
async def test_running_status_verifies(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.run_effect = "running"

    result = await executor.execute(_request(), _context())

    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "is running (Status -1)" in result.verification.detail


@pytest.mark.asyncio
async def test_no_observed_signal_is_verification_failed_with_reason(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.run_effect = "nothing"

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "no run signal was observed" in result.verification.detail
    assert "4 attempts" in result.verification.detail
    assert "polls every 60 seconds" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(executor: OperationExecutor, iris: FakeIris) -> None:
    original_get = iris.client.get.side_effect

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/task/info" and iris.client.post.await_count:
            raise IRISConnectionError("boom")
        return await original_get(path, params)

    iris.client.get.side_effect = get

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "read error" in result.verification.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "phrase"), [(403, "requires %Admin_Task"), (404, "no task with id"), (400, "invalid")])
async def test_iris_errors_on_run_are_clear_failures(
    executor: OperationExecutor, iris: FakeIris, code: int, phrase: str
) -> None:
    iris.post_error = code

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert phrase in result.handler_result.detail
    assert "Nothing was run" in result.handler_result.detail


@pytest.mark.asyncio
async def test_trace_records_every_stage(executor: OperationExecutor) -> None:
    clear_traces()

    await executor.execute(_request(), _context())

    trace = list_traces()[0]
    assert trace.operation_name == _OPERATION_NAME
    assert trace.status == "success"
    assert [s.name for s in trace.spans] == ["authorization", "confirmation", "execution", "verification"]
    assert trace.verification_result == "verified"
    clear_traces()


# --- route ---


def _route_client(mock_iris_client: AsyncMock, privileges: frozenset[str] = _PRIVILEGES) -> FakeIris:
    fake = FakeIris()
    fake.info_privileges = privileges
    mock_iris_client.get.side_effect = fake._get
    mock_iris_client.post.side_effect = fake._post
    return fake


def test_route_requires_confirmation(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/tasks/run-now", json={"Id": 101})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.post.assert_not_awaited()


def test_route_without_task_privilege_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client, privileges=frozenset({"Operate"}))

    response = client.post("/api/iris/tasks/run-now", json={"Id": 101, "confirmed": True})

    assert response.json()["status"] == "unauthorized"
    mock_iris_client.post.assert_not_awaited()


def test_route_dry_run_never_runs(client: TestClient, mock_iris_client: AsyncMock) -> None:
    fake = _route_client(mock_iris_client)

    response = client.post("/api/iris/tasks/run-now", json={"Id": 101, "confirmed": True, "dry_run": True})

    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["data"]["request"]["body"] == {"RunNow": True}
    mock_iris_client.post.assert_not_awaited()
    assert fake.tasks[101]["info"]["LastSchedule"] == "2026-09-24 01:00:00"


def test_route_system_task_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/tasks/run-now", json={"Id": 1, "confirmed": True})

    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["handler_result"]["data"]["protected"] is True
    mock_iris_client.post.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"Id": 101, "confirmed": True, "Datetime": "2026-12-31 23:59:59"},
        {"Id": 101, "confirmed": True, "RunNow": False},
        {"Id": 101, "confirmed": True, "force": True},
        {"Id": "101", "confirmed": True},
        {"confirmed": True},
    ],
)
def test_route_rejects_scheduling_unknown_fields_and_non_int(
    client: TestClient, mock_iris_client: AsyncMock, payload: dict[str, Any]
) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/tasks/run-now", json=payload)

    assert response.status_code == 422
    mock_iris_client.post.assert_not_awaited()


def test_route_is_post_only() -> None:
    assert set(app.openapi()["paths"]["/api/iris/tasks/run-now"]) == {"post"}
