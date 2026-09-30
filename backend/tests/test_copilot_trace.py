"""Phase 3.5d: Copilot lifecycle traces in the existing trace store.

Everything is mocked: no IRIS call and no real operation. Plan traces are
recorded by POST /plan; execute traces by CopilotExecutionService.execute().
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.copilot.capabilities import COPILOT_CAPABILITIES
from app.copilot.execution import CopilotExecutionService
from app.copilot.trace import CopilotStage, CopilotTrace
from app.execution.executor import OperationExecutor
from app.execution.models import OperationResultStatus, PostActionVerificationStatus
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotDatabaseMountParameters,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationPlan,
)
from app.observability import store
from app.observability.models import ExecutionTrace
from app.resolution.history import history_for_issue
from tests.test_copilot_database_mount import (
    _MESSAGE,
    _PROPOSAL,
    _MountedHandler,
    _authorization,
    _issue,
    _issues,
    _operation_result,
    _plan,
    _plan_body,
)
from tests.test_copilot_execution import (
    _authorization as _purge_authorization,
    _operation_result as _purge_operation_result,
    _plan as _purge_plan,
    _settings,
)


@pytest.fixture(autouse=True)
def clean_store():
    store.clear_traces()
    yield
    store.clear_traces()


def _spans(trace: ExecutionTrace) -> list[tuple[str, str]]:
    return [(span.name, span.status) for span in trace.spans]


def _span(trace: ExecutionTrace, name: str):
    return next(span for span in trace.spans if span.name == name)


def _traces(name: str) -> list[ExecutionTrace]:
    return [t for t in store.list_traces() if t.operation_name == name]


# --- 1. plan traces ---


def test_successful_plan_records_the_planning_lifecycle(client: TestClient) -> None:
    issue = _issue()
    with patch("app.routes.copilot.list_issues", new=AsyncMock(return_value=_issues(issue))):
        body = client.post("/api/iris/copilot/plan", json=_plan_body()).json()

    trace = store.get_trace(body["plan"]["trace_id"])
    assert trace is not None and trace.operation_name == "copilot.plan"
    assert trace.status == "plan_created"
    assert _spans(trace) == [
        ("requested", "ok"), ("classified", "ok"), ("issue_detected", "ok"),
        ("plan_created", "ok"), ("confirmation_required", "ok"),
    ]
    assert _span(trace, "requested").attributes == {"message_length": len(_MESSAGE)}
    assert _span(trace, "classified").attributes == {"intent": "resolution_request"}
    assert _span(trace, "issue_detected").attributes == {
        "issue_type": "database_dismounted", "issues_detected": 1, "issue_id": issue.issue_id,
    }
    assert _span(trace, "plan_created").attributes == {
        "operation": "database.mount", "target_kind": "database", "target": "IPM",
    }
    assert trace.resolution is None  # never a duplicate resolution-history entry


def test_direct_setting_plan_has_no_issue_stage(client: TestClient) -> None:
    body = client.post(
        "/api/iris/copilot/plan", json=_plan_body("Enable PurgeArchived.", "Set PurgeArchived to true")
    ).json()

    trace = store.get_trace(body["plan"]["trace_id"])
    assert [name for name, _ in _spans(trace)] == [
        "requested", "classified", "plan_created", "confirmation_required",
    ]


# --- 2. rejected plan traces ---


def test_plan_for_an_undetected_issue_records_the_rejection(client: TestClient) -> None:
    with patch("app.routes.copilot.list_issues", new=AsyncMock(return_value=_issues())):
        body = client.post("/api/iris/copilot/plan", json=_plan_body()).json()

    assert body["plan"] is None and body["reason"] == "issue_not_detected"
    [trace] = _traces("copilot.plan")
    assert trace.status == "plan_rejected"
    assert _spans(trace) == [
        ("requested", "ok"), ("classified", "ok"), ("issue_detected", "error"), ("plan_rejected", "error"),
    ]
    assert _span(trace, "issue_detected").attributes["issues_detected"] == 0
    assert _span(trace, "plan_rejected").attributes == {"reason": "issue_not_detected"}


def test_unsupported_change_request_records_plan_rejected(client: TestClient) -> None:
    body = client.post(
        "/api/iris/copilot/plan", json=_plan_body("Dismount database IPM", "Dismount database IPM")
    ).json()

    assert body["plan"] is None
    [trace] = _traces("copilot.plan")
    assert _spans(trace) == [("requested", "ok"), ("classified", "ok"), ("plan_rejected", "error")]
    assert _span(trace, "plan_rejected").attributes == {"reason": "unsupported_action"}


def test_raw_message_text_is_never_recorded(client: TestClient) -> None:
    canary = "SECRETCANARY-token-1234"
    client.post(
        "/api/iris/copilot/plan",
        json=_plan_body(f"Mount database {canary} with password {canary}", _PROPOSAL),
    )

    [trace] = _traces("copilot.plan")
    assert canary not in trace.model_dump_json()


def test_read_only_requests_are_not_traced(client: TestClient, mock_iris_client: AsyncMock) -> None:
    client.post(
        "/api/iris/copilot/plan",
        json={"message": "List databases", "intent": "read_only_query", "requires_confirmation": False},
    )
    client.post("/api/iris/copilot/classify", json={"message": "Mount database IPM"})

    assert store.list_traces() == []


# --- 3. execute trace ---


def _mount_service(executor: object) -> CopilotExecutionService:
    return CopilotExecutionService(AsyncMock(), frozenset({"Operate"}), executor)


@pytest.mark.asyncio
async def test_successful_execution_records_the_full_lifecycle_and_links_the_executor_trace() -> None:
    issue = _issue()
    plan = _plan(issue)
    with patch(
        "app.copilot.execution.list_issues", new=AsyncMock(side_effect=[_issues(issue), _issues()])
    ):
        result = await _mount_service(OperationExecutor({"database.mount": _MountedHandler()})).execute(
            plan, _authorization(plan), confirmed=True
        )

    assert result.status is CopilotExecutionStatus.SUCCESS
    trace = store.get_trace(result.trace_id)
    assert trace.operation_name == "copilot.execute" and trace.status == "resolved"
    assert _spans(trace) == [
        ("requested", "ok"), ("confirmation_received", "ok"), ("authorized", "ok"),
        ("issue_detected", "ok"), ("executing", "ok"), ("executed", "ok"),
        ("verification", "ok"), ("resolved", "ok"),
    ]
    assert (trace.authorization_result, trace.confirmation_result,
            trace.execution_result, trace.verification_result) == (
        "authorized", "received", "success", "verified",
    )
    assert _span(trace, "verification").attributes["issue_cleared"] is True
    operation_trace = store.get_trace(_span(trace, "executed").attributes["operation_trace_id"])
    assert operation_trace.operation_name == "database.mount"
    assert operation_trace.resolution.issue_id == issue.issue_id
    # The resolution history still shows only the executor's own trace.
    history = history_for_issue(issue.issue_id, store.list_traces())
    assert [entry.trace_id for entry in history.history] == [operation_trace.trace_id]
    assert trace.resolution is None


@pytest.mark.asyncio
async def test_direct_setting_execution_records_setting_verification() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _purge_operation_result(actual=True)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)
    with patch("app.copilot.execution.get_journal_settings", new=AsyncMock(return_value=_settings(True))):
        result = await service.execute(_purge_plan(True), _purge_authorization(), confirmed=True)

    trace = store.get_trace(result.trace_id)
    assert trace.status == "resolved"
    assert [name for name, _ in _spans(trace)] == [
        "requested", "confirmation_received", "authorized", "executing", "executed",
        "verification", "resolved",
    ]
    assert _span(trace, "verification").attributes["setting_matches"] is True


# --- 4. failure states ---


def _mount_failure_cases():
    issue = _issue()
    plan = _plan(issue)
    tampered = plan.model_copy(
        update={"parameters": CopilotDatabaseMountParameters(Directory="/tmp/evil/")}
    )
    denied = _authorization(plan).model_copy(update={
        "authorized": False, "ready_to_execute": False,
        "reason": CopilotAuthorizationReason.MISSING_PRIVILEGE,
    })
    mismatched = _authorization(plan).model_copy(
        update={"operation": CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED}
    )
    return [
        # (label, plan, authorization, confirmed, issues side effect, executor result, stage, reason)
        ("not confirmed", plan, _authorization(plan), False, None, None, "authorization_failed", "not_confirmed"),
        ("authorization denied", plan, denied, True, None, None,
         "authorization_failed", "missing_required_privilege"),
        ("authorization mismatch", plan, mismatched, True, None, None, "authorization_failed", "authorization_mismatch"),
        ("invalid target", plan.model_copy(update={"target": _purge_plan().target}), _authorization(plan),
         True, None, None, "target_changed", "invalid_target"),
        ("issue gone", plan, _authorization(plan), True, [_issues()], None,
         "issue_not_detected", "no_longer_detected"),
        ("issues unreadable", plan, _authorization(plan), True, HTTPException(status_code=503), None,
         "issue_not_detected", "issues_unavailable"),
        ("tampered parameters", tampered, _authorization(tampered), True, [_issues(issue)], None,
         "parameter_mismatch", None),
        ("executor error", plan, _authorization(plan), True, [_issues(issue)], RuntimeError("boom"),
         "execution_failed", "executor_error"),
        ("operation failed", plan, _authorization(plan), True, [_issues(issue)],
         _operation_result(OperationResultStatus.EXECUTION_FAILED), "execution_failed",
         "operation_not_successful"),
        ("handler verification", plan, _authorization(plan), True, [_issues(issue)],
         _operation_result(OperationResultStatus.VERIFICATION_FAILED,
                           PostActionVerificationStatus.VERIFICATION_FAILED),
         "verification_failed", "executor_verification"),
        ("issue still detected", plan, _authorization(plan), True, [_issues(issue), _issues(issue)],
         _operation_result(), "issue_still_detected", None),
    ]


@pytest.mark.parametrize(
    ("label", "plan", "authorization", "confirmed", "issues", "executor_result", "stage", "reason"),
    _mount_failure_cases(),
    ids=[case[0] for case in _mount_failure_cases()],
)
@pytest.mark.asyncio
async def test_failure_states_are_recorded(
    label, plan, authorization, confirmed, issues, executor_result, stage, reason
) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    if isinstance(executor_result, Exception):
        executor.execute.side_effect = executor_result
    elif executor_result is not None:
        executor.execute.return_value = executor_result
    reader = AsyncMock(side_effect=issues) if issues is not None else AsyncMock()

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _mount_service(executor).execute(plan, authorization, confirmed=confirmed)

    assert result.status is not CopilotExecutionStatus.SUCCESS
    trace = store.get_trace(result.trace_id)
    assert trace.status == stage
    assert trace.spans[-1].name == stage and trace.spans[-1].status == "error"
    assert trace.spans[-1].attributes.get("reason") == reason
    assert "resolved" not in [span.name for span in trace.spans]
    if executor_result is None:
        executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_operation_is_recorded_as_plan_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    plan, authorization = _purge_plan(), _purge_authorization()  # built while approved
    monkeypatch.delitem(COPILOT_CAPABILITIES, CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED)

    result = await CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor).execute(
        plan, authorization, confirmed=True
    )

    trace = store.get_trace(result.trace_id)
    assert (trace.status, trace.spans[-1].attributes) == ("plan_rejected", {"reason": "unsupported_operation"})
    assert result.detail == "This Copilot operation is not supported."
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_setting_mismatch_is_recorded_as_verification_failed() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _purge_operation_result(actual=True)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)
    with patch("app.copilot.execution.get_journal_settings", new=AsyncMock(return_value=_settings(False))):
        result = await service.execute(_purge_plan(True), _purge_authorization(), confirmed=True)

    trace = store.get_trace(result.trace_id)
    assert trace.status == "verification_failed"
    assert trace.spans[-1].attributes == {"reason": "setting_mismatch", "setting_matches": False}


# --- 5. plan -> execute -> executor linkage ---


@pytest.mark.asyncio
async def test_plan_execute_and_executor_traces_are_linked(client: TestClient) -> None:
    issue = _issue()
    with patch("app.routes.copilot.list_issues", new=AsyncMock(return_value=_issues(issue))):
        body = client.post("/api/iris/copilot/plan", json=_plan_body()).json()
    plan = _plan(issue).model_copy(update={"trace_id": body["plan"]["trace_id"]})

    with patch(
        "app.copilot.execution.list_issues", new=AsyncMock(side_effect=[_issues(issue), _issues()])
    ):
        result = await _mount_service(OperationExecutor({"database.mount": _MountedHandler()})).execute(
            plan, _authorization(plan), confirmed=True
        )

    execute_trace = store.get_trace(result.trace_id)
    plan_trace_id = _span(execute_trace, "requested").attributes["plan_trace_id"]
    assert store.get_trace(plan_trace_id).operation_name == "copilot.plan"
    operation_trace_id = _span(execute_trace, "executed").attributes["operation_trace_id"]
    assert store.get_trace(operation_trace_id).operation_name == "database.mount"


@pytest.mark.parametrize("forged", ["f" * 32, "executor"])
@pytest.mark.asyncio
async def test_unknown_or_non_plan_trace_ids_are_not_linked_and_change_nothing(forged: str) -> None:
    issue = _issue()

    async def run(trace_id: str | None):
        plan = _plan(issue).model_copy(update={"trace_id": trace_id})
        with patch(
            "app.copilot.execution.list_issues", new=AsyncMock(side_effect=[_issues(issue), _issues()])
        ):
            return await _mount_service(
                OperationExecutor({"database.mount": _MountedHandler()})
            ).execute(plan, _authorization(plan), confirmed=True)

    baseline = await run(None)
    if forged == "executor":  # a real trace, but not a plan trace
        forged = _span(store.get_trace(baseline.trace_id), "executed").attributes["operation_trace_id"]
    with_forged = await run(forged)

    assert with_forged.model_dump(exclude={"trace_id"}) == baseline.model_dump(exclude={"trace_id"})
    assert "plan_trace_id" not in _span(store.get_trace(with_forged.trace_id), "requested").attributes


@pytest.mark.parametrize("trace_id", ["not-a-trace-id", "F" * 32, "a" * 31, "<script>"])
def test_trace_id_on_the_plan_must_be_a_trace_id(trace_id: str) -> None:
    data = _plan().model_dump(mode="json") | {"trace_id": trace_id}

    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(data)


# --- trace attributes are restricted ---


@pytest.mark.parametrize(
    "attributes",
    [{"message": "Mount database IPM"}, {"parameters": "x"}, {"password": "x"}, {"reason": {"a": 1}}],
)
def test_trace_attributes_are_allowlisted(attributes: dict) -> None:
    with pytest.raises(ValueError):
        CopilotTrace("copilot.test").stage(CopilotStage.REQUESTED, **attributes)
    assert store.list_traces() == []
