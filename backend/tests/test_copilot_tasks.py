"""Phase 3.5c: read-only task catalog in the Copilot context and answers.

Everything is mocked: no IRIS call and no task operation. Tasks come from the
existing task overview (GET /v2/tasks plus /v2/task/info per task) and the
existing task detail (GET /v2/task) for the tasks kept in the context.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.copilot.ai import DeterministicCopilotProvider
from app.copilot.capabilities import get_capability
from app.copilot.context import CopilotContextService
from app.copilot.intents import CopilotIntent, classify_intent, is_task_detail_question
from app.copilot.planner import CopilotPlanningService
from app.execution.executor import OperationExecutor
from app.iris_client.exceptions import IRISConnectionError
from app.models.copilot import (
    CopilotAIRequest,
    CopilotOperationalContext,
    CopilotPlanRequest,
    CopilotTaskContext,
)
from app.routes.issues import IssuesResponse
from tests.test_copilot_context import (
    _body,
    _database,
    _info_result,
    _process,
    _task_detail,
    _task_info,
    _web_app,
)

_LIMIT = 10
_TEXT_LIMIT = 160


def _task(task_id: int, name: str, *, list_suspended: bool = False) -> dict[str, object]:
    return {
        "Name": name, "Type": "System", "Namespace": "%SYS", "Description": "not included",
        "Id": task_id, "Suspended": list_suspended, "LastFinished": "2026-09-30 00:00:00",
        "NextScheduled": "2026-10-01 02:00:00",
    }


def _client(
    tasks: list[dict[str, object]],
    *,
    infos: dict[int, dict[str, object] | Exception] | None = None,
    details: dict[int, dict[str, object] | Exception] | None = None,
    tasks_error: Exception | None = None,
) -> AsyncMock:
    """IRIS mock: per-task info/detail by id, with optional failures."""
    infos = infos or {}
    details = details or {}
    fixed = {
        "/info": _body(_info_result()),
        "/v2/databases": _body([_database("DB0")]),
        "/v2/processes": _body([_process(0)]),
        "/v2/web-apps": _body([_web_app("/app0")]),
    }

    async def get(path: str, params=None):
        if path == "/v2/tasks":
            if tasks_error is not None:
                raise tasks_error
            return _body(tasks)
        if path in ("/v2/task/info", "/v2/task"):
            source, default = (infos, _task_info()) if path == "/v2/task/info" else (details, _task_detail())
            value = source.get(params["id"], default)
            if isinstance(value, Exception):
                raise value
            return _body(value)
        return fixed[path]

    client = AsyncMock()
    client.get.side_effect = get
    return client


@pytest.fixture(autouse=True)
def no_issues():
    with patch(
        "app.copilot.context.list_issues",
        new_callable=AsyncMock,
        return_value=IssuesResponse(issues=[], resolutions={}),
    ):
        yield


def _calls(client: AsyncMock, path: str) -> list[int]:
    return [
        call.kwargs.get("params", call.args[1] if len(call.args) > 1 else {})["id"]
        for call in client.get.await_args_list
        if call.args[0] == path
    ]


# --- context: task catalog and details ---


@pytest.mark.asyncio
async def test_task_context_has_state_schedule_run_as_and_runs() -> None:
    client = _client([_task(7, "Integrity Check")])

    context = await CopilotContextService(client).get_context()

    assert context.tasks == [
        CopilotTaskContext(
            id=7, name="Integrity Check", namespace="%SYS", type="System",
            state="Not Running", suspended=False, error=None,
            last_finished="2026-09-30 00:00:00", next_scheduled="2026-10-01 02:00:00",
            run_as_user="operator", time_period="Daily", time_period_every="1",
            daily_frequency="Once", daily_start_time="02:00:00", suspend_on_error=True,
        )
    ]
    assert context.tasks_total == 1
    serialized = context.model_dump_json()
    for excluded in ("not included", "SMTPPass", "secret-value", "User.Task", "Settings"):
        assert excluded not in serialized


@pytest.mark.parametrize(
    ("list_suspended", "info", "state", "suspended"),
    [
        # The list's Suspended flag is ignored; /v2/task/info decides.
        (False, _task_info(suspended=True), "Suspended", True),
        (True, _task_info(suspended=False), "Not Running", False),
        (False, _task_info(status="-1", suspended=True), "Running", True),
    ],
)
@pytest.mark.asyncio
async def test_state_comes_from_task_info_not_the_list_flag(
    list_suspended: bool, info: dict[str, object], state: str, suspended: bool
) -> None:
    client = _client([_task(1, "T", list_suspended=list_suspended)], infos={1: info})

    task = (await CopilotContextService(client).get_context()).tasks[0]

    assert (task.state, task.suspended) == (state, suspended)


@pytest.mark.asyncio
async def test_error_is_capped_and_empty_error_is_none() -> None:
    client = _client(
        [_task(1, "Failing"), _task(2, "Fine")],
        infos={1: _task_info(error="E" * 400), 2: _task_info(error="")},
    )

    tasks = (await CopilotContextService(client).get_context()).tasks

    assert tasks[0].error == "E" * _TEXT_LIMIT
    assert tasks[1].error is None


@pytest.mark.asyncio
async def test_context_keeps_at_most_ten_tasks_and_reads_details_only_for_them() -> None:
    client = _client([_task(i, f"Task{i}") for i in range(1, _LIMIT + 4)])

    context = await CopilotContextService(client).get_context()

    assert len(context.tasks) == _LIMIT
    assert context.tasks_total == _LIMIT + 3
    assert sorted(_calls(client, "/v2/task")) == list(range(1, _LIMIT + 1))


@pytest.mark.asyncio
async def test_failed_info_read_leaves_the_task_listed_without_state() -> None:
    client = _client(
        [_task(1, "NoInfo"), _task(2, "Ok")],
        infos={1: IRISConnectionError("info unavailable")},
    )

    context = await CopilotContextService(client).get_context()

    no_info = context.tasks[0]
    assert (no_info.name, no_info.state, no_info.suspended, no_info.error) == ("NoInfo", None, None, None)
    assert no_info.run_as_user == "operator"
    assert context.tasks[1].state == "Not Running"
    assert context.unavailable == []


@pytest.mark.asyncio
async def test_failed_detail_read_leaves_only_detail_fields_empty() -> None:
    client = _client([_task(1, "NoDetail")], details={1: IRISConnectionError("detail unavailable")})

    task = (await CopilotContextService(client).get_context()).tasks[0]

    assert task.state == "Not Running"
    assert (task.run_as_user, task.time_period, task.daily_frequency, task.suspend_on_error) == (
        None, None, None, None,
    )


@pytest.mark.asyncio
async def test_failed_task_listing_marks_tasks_unavailable_and_keeps_other_sources() -> None:
    client = _client([], tasks_error=IRISConnectionError("tasks unavailable"))

    context = await CopilotContextService(client).get_context()

    assert context.unavailable == ["tasks"]
    assert context.tasks == []
    assert context.tasks_total is None
    assert context.databases and context.processes and context.web_apps
    assert _calls(client, "/v2/task/info") == [] and _calls(client, "/v2/task") == []


@pytest.mark.asyncio
async def test_task_context_only_reads_iris() -> None:
    client = _client([_task(i, f"Task{i}") for i in range(1, 4)])

    await CopilotContextService(client).get_context()

    client.post.assert_not_awaited()
    client.put.assert_not_awaited()
    client.delete.assert_not_awaited()


# --- deterministic read-only answers ---


def _task_context(**values: object) -> CopilotTaskContext:
    return CopilotTaskContext(**{"id": 1, "name": "T", "state": "Not Running", **values})


def _request(message: str, tasks: list[CopilotTaskContext], *, total: int | None = None,
             unavailable: list[str] | None = None) -> CopilotAIRequest:
    return CopilotAIRequest(
        message=message,
        intent=classify_intent(message),
        context=CopilotOperationalContext(
            databases=[], processes=[], web_apps=[], tasks=tasks,
            tasks_total=len(tasks) if total is None and unavailable is None else total,
            unavailable=unavailable or [],
        ),
    )


@pytest.mark.asyncio
async def test_suspended_and_error_tasks_are_reported_read_only() -> None:
    tasks = [
        _task_context(id=1, name="Integrity Check", type="System", state="Suspended", suspended=True),
        _task_context(id=2, name="Purge Journal", error="Task Has Expired"),
        _task_context(id=3, name="Switch Journal"),
    ]
    request = _request("Which tasks are suspended?", tasks)

    output = await DeterministicCopilotProvider().generate(request)

    assert request.intent is CopilotIntent.READ_ONLY_QUERY
    assert output.answer == "Of the 3 tasks: 1 suspended, 1 with an error reported. Nothing is changed from here."
    assert output.observations == [
        "Suspended: Integrity Check (System)",
        "Error reported for Purge Journal: Task Has Expired",
    ]
    assert output.proposed_action is None
    assert output.requires_confirmation is False


@pytest.mark.asyncio
async def test_counts_are_scoped_to_the_tasks_shown() -> None:
    tasks = [_task_context(id=i, name=f"T{i}") for i in range(_LIMIT)]

    output = await DeterministicCopilotProvider().generate(
        _request("Are any tasks failing?", tasks, total=16)
    )

    assert output.answer.startswith("Of the 10 tasks shown (16 in total): 0 suspended, 0 with an error")
    assert output.observations == [
        "No suspended tasks among those shown.",
        "No task errors among those shown.",
    ]
    assert output.proposed_action is None


@pytest.mark.asyncio
async def test_unknown_run_state_is_reported() -> None:
    output = await DeterministicCopilotProvider().generate(
        _request("Show the tasks", [_task_context(state=None, suspended=None)])
    )

    assert "Run state unavailable for 1 task." in output.observations


@pytest.mark.asyncio
async def test_unreadable_tasks_are_reported_without_guessing() -> None:
    output = await DeterministicCopilotProvider().generate(
        _request("Which tasks are suspended?", [], unavailable=["tasks"])
    )

    assert output.answer == "Task information could not be read, so task states are unknown."
    assert output.observations == ["Context unavailable for: tasks."]
    assert output.proposed_action is None
    assert output.requires_confirmation is False


@pytest.mark.asyncio
async def test_non_task_read_only_questions_keep_the_generic_answer() -> None:
    output = await DeterministicCopilotProvider().generate(
        _request("List the databases", [_task_context(state="Suspended")])
    )

    assert output.answer == "Here is the available read-only operational context."


# --- task operations stay outside the Copilot catalog ---


@pytest.mark.parametrize(
    "name", ["task.run_now", "task.suspend", "task.resume", "delete_task", "list_tasks"]
)
def test_task_operations_are_not_copilot_capabilities(name: str) -> None:
    assert get_capability(name) is None


@pytest.mark.parametrize(
    ("message", "proposal"),
    [
        ("Run the task now", "task.run_now"),
        ("Resume task Integrity Check", "Resume task Integrity Check"),
        ("Suspend task Purge Journal", "Suspend task Purge Journal"),
        ("Delete task Purge Journal", "Delete task Purge Journal"),
    ],
)
def test_task_mutation_requests_get_no_plan(message: str, proposal: str) -> None:
    result = CopilotPlanningService().plan(
        CopilotPlanRequest(
            message=message,
            intent=classify_intent(message),
            proposed_action=proposal,
            requires_confirmation=True,
        )
    )

    assert result.plan is None


@pytest.mark.parametrize(
    "message", ["Resume task Integrity Check", "Suspend task Purge Journal", "Run the task now"]
)
@pytest.mark.asyncio
async def test_provider_never_proposes_task_mutations(message: str) -> None:
    output = await DeterministicCopilotProvider().generate(_request(message, []))

    assert output.proposed_action is None
    assert output.requires_confirmation is False


def test_ask_about_tasks_is_read_only_end_to_end(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    iris = _client(
        [_task(1, "Integrity Check"), _task(2, "Purge Journal")],
        infos={1: _task_info(suspended=True), 2: _task_info(error="Task Has Expired")},
    )
    mock_iris_client.get.side_effect = iris.get.side_effect

    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.post("/api/iris/copilot/ask", json={"message": "Which tasks are suspended?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "read_only_query"
    assert body["answer"].startswith("Of the 2 tasks: 1 suspended, 1 with an error reported.")
    assert "Suspended: Integrity Check (System)" in body["observations"]
    assert body["proposed_action"] is None
    assert body["requires_confirmation"] is False
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    execute.assert_not_awaited()


# --- optimization: task details only for questions that need them ---


def _ask(client: TestClient, iris_mock: AsyncMock, iris: AsyncMock, message: str) -> dict:
    iris_mock.get.side_effect = iris.get.side_effect
    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.post("/api/iris/copilot/ask", json={"message": message})
    assert response.status_code == 200
    execute.assert_not_awaited()
    iris_mock.post.assert_not_awaited()
    iris_mock.put.assert_not_awaited()
    return response.json()


def _path_counts(iris_mock: AsyncMock) -> dict[str, int]:
    counts: dict[str, int] = {}
    for call in iris_mock.get.await_args_list:
        counts[call.args[0]] = counts.get(call.args[0], 0) + 1
    return counts


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Which tasks run as _SYSTEM?", True),
        ("What is the task schedule?", True),
        ("When are tasks scheduled?", True),
        ("Which task runs daily?", True),
        ("Show task frequency", True),
        ("What start time does each task have?", True),
        ("Which tasks suspend on error?", True),
        ("Which tasks are suspended?", False),
        ("Are any tasks failing?", False),
        ("Which tasks have errors?", False),
        ("When is each task's next run?", False),
        ("Show the tasks", False),
        ("What is the backup schedule?", False),  # not about tasks
    ],
)
def test_task_detail_question_detection(message: str, expected: bool) -> None:
    assert is_task_detail_question(message) is expected


def test_state_and_error_question_makes_no_task_detail_calls(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    iris = _client(
        [_task(i, f"Task{i}") for i in range(1, _LIMIT + 4)],
        infos={1: _task_info(suspended=True), 2: _task_info(error="Task Has Expired")},
    )

    body = _ask(client, mock_iris_client, iris, "Which tasks are suspended?")

    counts = _path_counts(mock_iris_client)
    assert counts.get("/v2/task", 0) == 0
    assert counts["/v2/tasks"] == 1
    assert counts["/v2/task/info"] == _LIMIT + 3
    assert body["answer"].startswith("Of the 10 tasks shown (13 in total): 1 suspended, 1 with an error")
    assert body["proposed_action"] is None and body["requires_confirmation"] is False


def test_detail_question_fetches_details_only_for_the_tasks_shown(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    iris = _client([_task(i, f"Task{i}") for i in range(1, _LIMIT + 4)])

    body = _ask(client, mock_iris_client, iris, "Which tasks run as operator and on what schedule?")

    detail_ids = sorted(
        call.kwargs["params"]["id"]
        for call in mock_iris_client.get.await_args_list
        if call.args[0] == "/v2/task"
    )
    assert detail_ids == list(range(1, _LIMIT + 1))
    assert body["observations"][0] == (
        "Task1: runs as operator; TimePeriod Daily, every 1; DailyFrequency Once, "
        "DailyStartTime 02:00:00; next run 2026-10-01 02:00:00; suspend on error: yes."
    )
    assert body["proposed_action"] is None and body["requires_confirmation"] is False


def test_non_task_question_makes_no_task_detail_calls(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    iris = _client([_task(1, "Task1"), _task(2, "Task2")])

    _ask(client, mock_iris_client, iris, "Is IRIS healthy?")

    assert _path_counts(mock_iris_client).get("/v2/task", 0) == 0


@pytest.mark.asyncio
async def test_context_without_details_keeps_state_and_leaves_detail_fields_empty() -> None:
    client = _client([_task(1, "T")], infos={1: _task_info(suspended=True, error="boom")})

    context = await CopilotContextService(client).get_context(task_details=False)

    task = context.tasks[0]
    assert (task.state, task.suspended, task.error, task.next_scheduled) == (
        "Suspended", True, "boom", "2026-10-01 02:00:00",
    )
    assert (task.run_as_user, task.time_period, task.suspend_on_error) == (None, None, None)
    assert _calls(client, "/v2/task") == []


@pytest.mark.asyncio
async def test_detail_answer_reports_unavailable_details() -> None:
    output = await DeterministicCopilotProvider().generate(
        _request("Which tasks run as _SYSTEM?", [_task_context(name="NoDetail")])
    )

    assert output.observations == ["NoDetail: details unavailable."]
    assert output.proposed_action is None
    assert output.requires_confirmation is False
