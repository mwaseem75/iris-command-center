"""Tests for bounded, read-only Copilot operational context."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.copilot.context import CopilotContextService
from app.execution.executor import OperationExecutor
from app.iris_client.exceptions import IRISConnectionError
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.identity import ResolutionReadiness, issue_identity
from app.routes.issues import DatabaseMountIssue, IssuesResponse, SystemMonitorIssue

_READ_PATHS = (
    "/info",
    "/v2/databases",
    "/v2/processes",
    "/v2/web-apps",
    "/v2/tasks",
    "/v2/task/info",
    "/v2/task",
)
_LIMIT = 10
_TEXT_LIMIT = 160
_EXPLANATION_LIMIT = 320
_CONTEXT_KEYS = {
    "info", "databases", "databases_total", "processes", "processes_total",
    "processes_by_state", "processes_by_namespace", "processes_top_cpu", "process_focus",
    "web_apps", "web_apps_total", "tasks", "tasks_total",
    "issues", "issues_total", "issue_checks_unavailable", "unavailable",
}


def _info_result() -> dict[str, object]:
    return {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS 2026.2",
        "systemMode": "",
        "product": "IRIS",
        "namespaces": [],
        "privileges": {},
    }


def _database(name: str) -> dict[str, object]:
    return {
        "Name": name,
        "Directory": "D:" + "x" * 200,
        "Server": "",
        "ClusterMountMode": False,
        "MountRequired": False,
        "MountAtStartup": True,
        "StreamLocation": "",
        "Status": "Mounted/RW",
    }


def _process(pid: int) -> dict[str, object]:
    return {
        "Job": pid,
        "Pid": pid,
        "Username": "operator",
        "Device": "",
        "Nspace": "USER",
        "Routine": "Routine",
        "Commands": 0,
        "Globals": 0,
        "State": "Running",
        "ClientName": "",
        "EXEname": "",
        "IPAddress": "192.0.2.1",
        "CanBeExamined": True,
        "CanBeSuspended": False,
        "CanBeTerminated": False,
        "CanReceiveBroadcast": False,
        "PrvGblBlkCnt": 0,
        "OSUserName": "operator",
        "CPUTime": 12,
        "ParentPid": 1,
        "ElapsedTime": "00:00:01",
    }


def _web_app(name: str) -> dict[str, object]:
    return {
        "Name": name,
        "Namespace": "USER",
        "NamespaceDefault": False,
        "Enabled": True,
        "Type": "CSP",
        "Resource": "",
        "AuthenticationMethods": [],
        "IsSystemApp": False,
        "DispatchClass": "",
    }


def _task(name: str) -> dict[str, object]:
    return {
        "Name": name,
        "Type": "Task",
        "Namespace": "USER",
        "Description": "not included in Copilot context",
        "Id": 1,
        "Suspended": False,
        "LastFinished": "",
        "NextScheduled": "tomorrow",
    }


def _body(result: object) -> dict[str, object]:
    return {"status": {"errors": [], "summary": ""}, "console": [], "result": result}


def _mount_issue(name: str, explanation: str = "Database is dismounted.") -> DatabaseMountIssue:
    directory = f"/secret/path/{name}/"
    return DatabaseMountIssue(
        **issue_identity("database_dismounted", "database", directory.rstrip("/"), name),
        readiness=ResolutionReadiness.READY_TO_CHECK,
        database=name,
        directory=directory,
        status="Dismounted",
        mount_required=False,
        mount_at_startup=False,
        mirrored=False,
        affected_namespaces=[],
        explanation=explanation,
        parameters={"Directory": directory, "ReadOnly": False},
    )


def _issues_response(
    issues: list[object] | None = None, unavailable: list[str] | None = None
) -> IssuesResponse:
    return IssuesResponse(
        issues=issues or [],
        resolutions=dict(ISSUE_CATALOG),
        issue_checks_unavailable=unavailable or [],
    )


@pytest.fixture(autouse=True)
def list_issues() -> AsyncMock:
    """The Issue Resolver is patched; its detection has its own tests."""
    with patch("app.copilot.context.list_issues", new_callable=AsyncMock) as reader:
        reader.return_value = _issues_response()
        yield reader


def _task_info(*, suspended: bool = False, status: str = "0", error: str = "") -> dict[str, object]:
    return {
        "Type": "User",
        "Status": status,
        "Error": error,
        "LastSchedule": "",
        "LastStarted": "",
        "LastFinished": "yesterday",
        "NextScheduled": "tomorrow",
        "Suspended": suspended,
    }


def _task_detail() -> dict[str, object]:
    return {
        "Name": "Task0", "Description": "not included", "TaskClass": "User.Task",
        "NameSpace": "USER", "RunAsUser": "operator", "Priority": "Normal", "IsBatch": False,
        "MirrorStatus": "", "RescheduleOnStart": False, "SuspendOnError": True,
        "SuspendTerminated": False, "TimePeriod": "Daily", "TimePeriodEvery": 1,
        "TimePeriodDay": "", "DailyFrequency": "Once", "DailyFrequencyTime": "",
        "DailyIncrement": "", "DailyStartTime": "02:00:00", "DailyEndTime": "00:00:00",
        "StartDate": "2026-01-01", "EndDate": "", "RunAfterGUID": "", "Expires": False,
        "ExpiresDays": "", "ExpiresHours": "", "ExpiresMinutes": "", "OpenOutputFile": False,
        "OutputDirectory": "", "OutputFilename": "", "OutputFileIsBinary": False,
        "EmailOutput": False, "EmailOnCompletion": [], "EmailOnError": [],
        "EmailOnExpiration": [], "Settings": {"SMTPPass": "secret-value"},
    }


def _iris_responses(item_count: int = 1) -> dict[str, dict[str, object]]:
    return {
        "/info": _body(_info_result()),
        "/v2/databases": _body([_database(f"DB{index}") for index in range(item_count)]),
        "/v2/processes": _body([_process(index) for index in range(item_count)]),
        "/v2/web-apps": _body([_web_app(f"/app{index}") for index in range(item_count)]),
        "/v2/tasks": _body([_task(f"Task{index}") for index in range(item_count)]),
        # The existing task overview reads each task's info; the context
        # reads each shown task's detail (schedule, run-as).
        "/v2/task/info": _body(_task_info()),
        "/v2/task": _body(_task_detail()),
    }


@pytest.mark.asyncio
async def test_context_gathers_and_normalizes_all_read_only_sources() -> None:
    client = AsyncMock()
    responses = _iris_responses()

    async def get(path: str, params=None):
        return responses[path]

    client.get.side_effect = get

    context = await CopilotContextService(client).get_context()
    payload = context.model_dump(mode="json")

    assert set(payload) == _CONTEXT_KEYS
    assert payload["info"] == {
        "product": "IRIS",
        "server_version": "IRIS 2026.2",
        "system_mode": "",
        "api_version": 2,
    }
    assert payload["databases"][0] == {
        "name": "DB0",
        "status": "Mounted/RW",
        "directory": ("D:" + "x" * 200)[:_TEXT_LIMIT],
    }
    assert "IPAddress" not in str(payload)
    assert "Description" not in str(payload)
    assert {call.args[0] for call in client.get.await_args_list} == set(_READ_PATHS)
    assert len(client.get.await_args_list) == len(_READ_PATHS)


@pytest.mark.asyncio
async def test_context_bounds_lists_and_text_fields() -> None:
    client = AsyncMock()
    responses = _iris_responses(item_count=_LIMIT + 3)

    async def get(path: str, params=None):
        return responses[path]

    client.get.side_effect = get

    context = await CopilotContextService(client).get_context()

    for name in ("databases", "processes", "web_apps", "tasks"):
        assert len(getattr(context, name)) == _LIMIT
        assert getattr(context, f"{name}_total") == _LIMIT + 3
    assert len(context.databases[0].directory) == _TEXT_LIMIT


@pytest.mark.asyncio
async def test_unavailable_optional_source_does_not_hide_other_context() -> None:
    client = AsyncMock()
    responses = _iris_responses()

    async def get(path: str, params=None):
        if path == "/v2/processes":
            raise IRISConnectionError("connection refused")
        return responses[path]

    client.get.side_effect = get
    context = await CopilotContextService(client).get_context()

    assert context.processes == []
    assert context.processes_total is None
    assert context.unavailable == ["processes"]
    assert context.info is not None
    assert context.databases
    assert context.web_apps
    assert context.tasks


def test_context_endpoint_is_read_only_and_never_invokes_executor(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    responses = _iris_responses()

    async def get(path: str, params=None):
        return responses[path]

    mock_iris_client.get.side_effect = get

    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.get("/api/iris/copilot/context")

    assert response.status_code == 200
    assert set(response.json()) == _CONTEXT_KEYS
    assert {call.args[0] for call in mock_iris_client.get.await_args_list} == set(_READ_PATHS)
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    execute.assert_not_awaited()


def _context_client() -> AsyncMock:
    client = AsyncMock()
    responses = _iris_responses()

    async def get(path: str, params=None):
        return responses[path]

    client.get.side_effect = get
    return client


@pytest.mark.asyncio
async def test_context_includes_active_issues_with_allowed_fields_only(
    list_issues: AsyncMock,
) -> None:
    monitor = SystemMonitorIssue(
        **issue_identity("system_monitor_not_running", "process", "%SYS.Monitor", "System Monitor"),
        system_monitor=False,
        up_time="1d",
        explanation="The System Monitor is not running.",
    )
    list_issues.return_value = _issues_response([_mount_issue("IPM"), monitor])
    client = _context_client()

    context = await CopilotContextService(client).get_context()
    payload = context.model_dump(mode="json")

    assert payload["issues_total"] == 2
    assert payload["issues"][0] == {
        "kind": "database_dismounted",
        "title": ISSUE_CATALOG["database_dismounted"].title,
        "severity": ISSUE_CATALOG["database_dismounted"].severity.value,
        "resource_type": "database",
        "resource_name": "IPM",
        "readiness": "ready_to_check",
        "explanation": "Database is dismounted.",
        "resolvable": True,
        "recommended_operation": "database.mount",
    }
    assert payload["issues"][1]["resolvable"] is False
    assert payload["issues"][1]["recommended_operation"] is None
    serialized = str(payload["issues"])
    for excluded in ("issue_id", "canonical_key", "parameters", "directory", "/secret/path"):
        assert excluded not in serialized
    list_issues.assert_awaited_once_with(client)
    client.post.assert_not_awaited()
    client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_bounds_issue_count_and_explanations(list_issues: AsyncMock) -> None:
    list_issues.return_value = _issues_response(
        [_mount_issue(f"DB{index}", "x" * 500) for index in range(_LIMIT + 3)]
    )

    context = await CopilotContextService(_context_client()).get_context()

    assert len(context.issues) == _LIMIT
    assert context.issues_total == _LIMIT + 3
    assert all(len(issue.explanation) == _EXPLANATION_LIMIT for issue in context.issues)


@pytest.mark.asyncio
async def test_context_preserves_unavailable_issue_checks(list_issues: AsyncMock) -> None:
    list_issues.return_value = _issues_response(
        unavailable=["web_app_namespace_missing", "database_full"]
    )

    context = await CopilotContextService(_context_client()).get_context()

    assert context.issues == []
    assert context.issues_total == 0
    assert context.issue_checks_unavailable == ["web_app_namespace_missing", "database_full"]
    assert context.unavailable == []


@pytest.mark.asyncio
async def test_failed_issue_read_does_not_hide_other_context(list_issues: AsyncMock) -> None:
    list_issues.side_effect = HTTPException(status_code=503, detail="IRIS unavailable")

    context = await CopilotContextService(_context_client()).get_context()

    assert context.unavailable == ["issues"]
    assert context.issues == []
    assert context.issues_total is None
    assert context.issue_checks_unavailable == []
    assert context.info is not None
    assert context.databases
    assert context.processes
    assert context.web_apps
    assert context.tasks


@pytest.mark.asyncio
async def test_process_summaries_cover_every_process_from_the_one_read() -> None:
    client = AsyncMock()
    responses = _iris_responses()
    processes = [
        {**_process(pid), "State": state, "Nspace": namespace, "CPUTime": cpu}
        for pid, (state, namespace, cpu) in enumerate(
            [("RUNW", "%SYS", 5), ("EVTW", "", 900), ("RUNW", "USER", 40)] * 5, start=100
        )
    ]
    responses["/v2/processes"] = _body(processes)

    async def get(path: str, params=None):
        return responses[path]

    client.get.side_effect = get
    context = await CopilotContextService(client).get_context(focus_pid=114)

    assert context.processes_total == 15
    assert len(context.processes) == _LIMIT  # the list stays bounded
    assert context.processes_by_state == {"RUNW": 10, "EVTW": 5}
    assert context.processes_by_namespace == {"%SYS": 5, "(none)": 5, "USER": 5}
    assert [p.cpu_time for p in context.processes_top_cpu] == [900, 900, 900, 900, 900]
    assert context.process_focus is not None and context.process_focus.pid == 114
    assert context.process_focus.elapsed_time == "00:00:01"
    assert "192.0.2.1" not in str(context.model_dump())  # no IP address
    paths = [call.args[0] for call in client.get.await_args_list]
    assert paths.count("/v2/processes") == 1


@pytest.mark.asyncio
async def test_unavailable_processes_leave_summaries_empty() -> None:
    client = AsyncMock()
    responses = _iris_responses()

    async def get(path: str, params=None):
        if path == "/v2/processes":
            raise IRISConnectionError("connection refused")
        return responses[path]

    client.get.side_effect = get
    context = await CopilotContextService(client).get_context(focus_pid=1)

    assert context.processes_by_state == {}
    assert context.processes_by_namespace == {}
    assert context.processes_top_cpu == []
    assert context.process_focus is None


def test_ask_about_a_pid_reads_it_from_the_same_process_list(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    responses = _iris_responses(item_count=3)

    async def get(path: str, params=None):
        return responses[path]

    mock_iris_client.get.side_effect = get

    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        found = client.post("/api/iris/copilot/ask", json={"message": "Explain PID 2"}).json()
        missing = client.post("/api/iris/copilot/ask", json={"message": "Explain PID 77"}).json()

    assert found["intent"] == "read_only_query"
    assert found["answer"] == "PID 2 is in state Running, running Routine in USER."
    assert missing["answer"] == "PID 77 was not found in the current process data (3 processes reported)."
    assert found["proposed_action"] is None and found["requires_confirmation"] is False
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    execute.assert_not_awaited()
