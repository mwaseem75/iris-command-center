"""Phase 3.5e: one structured failure vocabulary (CopilotFailure) shared by
the /execute API result and the Copilot trace.

Everything is mocked: no IRIS call and no real operation. For every code, the
API result's `failure` and the trace's status and failure span must match, and
the existing `status` and `detail` stay unchanged.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.copilot.capabilities import COPILOT_CAPABILITIES
from app.copilot.execution import CopilotExecutionService
from app.dependencies import get_caller_privileges
from app.execution.executor import OperationExecutor
from app.execution.models import (
    HandlerExecutionResult,
    HandlerOutcome,
    OperationResult,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotDatabaseMountParameters,
    CopilotExecutionResult,
    CopilotExecutionStatus,
    CopilotFailure,
    CopilotOperation,
)
from app.observability import store
from tests.test_copilot_database_mount import (
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
    _plan as _purge_plan,
)
from tests.test_copilot_web_app import (
    _authorization as _web_app_authorization,
    _issue as _web_app_issue,
    _issues as _web_app_issues,
    _plan as _web_app_plan,
)

_REJECTED_DETAIL = "The plan does not match the currently detected issue. Nothing was executed."
_AUTH_DETAIL = "A matching authorization result and explicit confirmation are required."


@pytest.fixture(autouse=True)
def clean_store():
    store.clear_traces()
    yield
    store.clear_traces()


def _assert_failure(
    result: CopilotExecutionResult,
    failure: CopilotFailure,
    status: CopilotExecutionStatus,
    detail: str | None = None,
    reason: str | None = None,
) -> None:
    """API result and trace carry the same code; status/detail are unchanged."""
    assert result.failure is failure
    assert result.status is status
    if detail is not None:
        assert result.detail == detail
    trace = store.get_trace(result.trace_id)
    assert trace.status == failure.value
    assert (trace.spans[-1].name, trace.spans[-1].status) == (failure.value, "error")
    if reason is not None:
        assert trace.spans[-1].attributes.get("reason") == reason


def _mount(executor: object = None) -> CopilotExecutionService:
    return CopilotExecutionService(
        AsyncMock(), frozenset({"Operate"}), executor or AsyncMock(spec=OperationExecutor)
    )


async def _run_mount(plan, authorization, *, confirmed=True, issues=None, executor=None):
    reader = AsyncMock(side_effect=issues) if issues is not None else AsyncMock()
    with patch("app.copilot.execution.list_issues", new=reader):
        return await _mount(executor).execute(plan, authorization, confirmed=confirmed)


def _executor(result=None, error: Exception | None = None) -> AsyncMock:
    executor = AsyncMock(spec=OperationExecutor)
    if error is not None:
        executor.execute.side_effect = error
    else:
        executor.execute.return_value = result
    return executor


# --- success: no failure ---


@pytest.mark.asyncio
async def test_success_has_no_failure() -> None:
    issue = _issue()
    plan = _plan(issue)
    result = await _run_mount(
        plan, _authorization(plan), issues=[_issues(issue), _issues()],
        executor=OperationExecutor({"database.mount": _MountedHandler()}),
    )

    assert result.status is CopilotExecutionStatus.SUCCESS
    assert result.failure is None
    assert store.get_trace(result.trace_id).status == "resolved"


# --- PLAN_REJECTED ---


@pytest.mark.asyncio
async def test_plan_rejected_for_an_operation_no_longer_approved(monkeypatch) -> None:
    plan, authorization = _purge_plan(), _purge_authorization()
    monkeypatch.delitem(COPILOT_CAPABILITIES, CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED)
    executor = _executor()

    result = await CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor).execute(
        plan, authorization, confirmed=True
    )

    _assert_failure(result, CopilotFailure.PLAN_REJECTED, CopilotExecutionStatus.EXECUTION_REJECTED,
                    "This Copilot operation is not supported.", "unsupported_operation")
    executor.execute.assert_not_awaited()


def test_plan_endpoint_uses_the_same_plan_rejected_code(client: TestClient) -> None:
    with patch("app.routes.copilot.list_issues", new=AsyncMock(return_value=_issues())):
        body = client.post("/api/iris/copilot/plan", json=_plan_body()).json()

    assert body["plan"] is None and body["reason"] == "issue_not_detected"
    [trace] = [t for t in store.list_traces() if t.operation_name == "copilot.plan"]
    assert trace.status == CopilotFailure.PLAN_REJECTED.value
    assert trace.spans[-1].name == CopilotFailure.PLAN_REJECTED.value


# --- AUTHORIZATION_FAILED ---


@pytest.mark.parametrize(
    ("authorization_update", "confirmed", "reason"),
    [
        ({}, False, "not_confirmed"),
        ({"authorized": False, "ready_to_execute": False,
          "reason": CopilotAuthorizationReason.MISSING_PRIVILEGE}, True, "missing_required_privilege"),
        ({"operation": CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED}, True, "authorization_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_authorization_failed(authorization_update, confirmed, reason) -> None:
    plan = _plan()
    executor = _executor()

    result = await _run_mount(
        plan, _authorization(plan).model_copy(update=authorization_update),
        confirmed=confirmed, executor=executor,
    )

    _assert_failure(result, CopilotFailure.AUTHORIZATION_FAILED,
                    CopilotExecutionStatus.EXECUTION_REJECTED, _AUTH_DETAIL, reason)
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_admin_secure_is_authorization_failed_with_unchanged_status() -> None:
    issue = _web_app_issue()
    plan = _web_app_plan(issue)
    client = AsyncMock()
    service = CopilotExecutionService(
        client, frozenset({"Manage"}), OperationExecutor({"web_app.set_enabled": WebAppSetEnabledHandler(client)})
    )
    with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=_web_app_issues(issue))):
        result = await service.execute(plan, _web_app_authorization(plan), confirmed=True)

    _assert_failure(result, CopilotFailure.AUTHORIZATION_FAILED, CopilotExecutionStatus.EXECUTION_FAILED,
                    reason="missing_admin_secure")
    assert "%Admin_Secure" in result.detail
    client.put.assert_not_awaited()


# --- ISSUE_NOT_DETECTED ---


@pytest.mark.parametrize(
    ("issues", "reason"),
    [([_issues()], "no_longer_detected"), (HTTPException(status_code=503), "issues_unavailable")],
)
@pytest.mark.asyncio
async def test_issue_not_detected(issues, reason) -> None:
    plan = _plan()
    executor = _executor()

    result = await _run_mount(plan, _authorization(plan), issues=issues, executor=executor)

    _assert_failure(result, CopilotFailure.ISSUE_NOT_DETECTED,
                    CopilotExecutionStatus.EXECUTION_REJECTED, reason=reason)
    executor.execute.assert_not_awaited()


# --- TARGET_CHANGED ---


@pytest.mark.asyncio
async def test_target_changed_for_an_invalid_target() -> None:
    plan = _plan().model_copy(update={"target": _purge_plan().target})
    executor = _executor()

    result = await _run_mount(plan, _authorization(_plan()), executor=executor)

    _assert_failure(result, CopilotFailure.TARGET_CHANGED, CopilotExecutionStatus.EXECUTION_REJECTED,
                    "The operation target is invalid.", "invalid_target")
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_target_changed_when_the_authorized_target_differs() -> None:
    plan = _plan()
    other = _plan(_issue(directory="/other/zpm/"))
    executor = _executor()

    result = await _run_mount(plan, _authorization(other), executor=executor)

    _assert_failure(result, CopilotFailure.TARGET_CHANGED, CopilotExecutionStatus.EXECUTION_REJECTED,
                    _AUTH_DETAIL, "authorized_target_differs")
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_target_changed_when_the_identifier_no_longer_matches_the_issue() -> None:
    issue = _issue()
    plan = _plan(issue)
    plan = plan.model_copy(update={"target": plan.target.model_copy(update={"identifier": "USER"})})
    executor = _executor()

    result = await _run_mount(plan, _authorization(plan), issues=[_issues(issue)], executor=executor)

    _assert_failure(result, CopilotFailure.TARGET_CHANGED, CopilotExecutionStatus.EXECUTION_REJECTED,
                    _REJECTED_DETAIL, "identifier_differs")
    executor.execute.assert_not_awaited()


# --- PARAMETER_MISMATCH ---


@pytest.mark.asyncio
async def test_parameter_mismatch() -> None:
    issue = _issue()
    plan = _plan(issue).model_copy(
        update={"parameters": CopilotDatabaseMountParameters(Directory="/tmp/evil/")}
    )
    executor = _executor()

    result = await _run_mount(plan, _authorization(plan), issues=[_issues(issue)], executor=executor)

    _assert_failure(result, CopilotFailure.PARAMETER_MISMATCH,
                    CopilotExecutionStatus.EXECUTION_REJECTED, _REJECTED_DETAIL)
    executor.execute.assert_not_awaited()


# --- RESOURCE_PROTECTED ---


@pytest.mark.asyncio
async def test_resource_protected_for_a_mirrored_database_at_execution() -> None:
    issue = _issue(mirrored=True)
    plan = _plan(issue)
    executor = _executor()

    result = await _run_mount(plan, _authorization(plan), issues=[_issues(issue)], executor=executor)

    _assert_failure(result, CopilotFailure.RESOURCE_PROTECTED,
                    CopilotExecutionStatus.EXECUTION_REJECTED, _REJECTED_DETAIL)
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_resource_protected_from_the_handlers_refusal() -> None:
    issue = _web_app_issue()
    plan = _web_app_plan(issue)
    refused = OperationResult(
        operation_name="web_app.set_enabled",
        status=OperationResultStatus.EXECUTION_FAILED,
        handler_result=HandlerExecutionResult(
            outcome=HandlerOutcome.FAILURE, detail="protected", data={"protected": True}
        ),
        detail="protected",
    )
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage", "Secure"}), _executor(refused))
    with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=_web_app_issues(issue))):
        result = await service.execute(plan, _web_app_authorization(plan), confirmed=True)

    _assert_failure(result, CopilotFailure.RESOURCE_PROTECTED, CopilotExecutionStatus.EXECUTION_FAILED,
                    "The existing operation did not complete successfully.", "handler_protected")


def test_plan_endpoint_reports_resource_protected(client: TestClient) -> None:
    issue = _issue("IRISSYS", "/usr/irissys/mgr/")
    with patch("app.routes.copilot.list_issues", new=AsyncMock(return_value=_issues(issue))):
        body = client.post(
            "/api/iris/copilot/plan", json=_plan_body("Mount the IRISSYS database", "Mount database IRISSYS")
        ).json()

    assert body["plan"] is None and body["reason"] == "resource_protected"
    [trace] = store.list_traces()
    assert trace.spans[-1].attributes == {"reason": "resource_protected"}


# --- EXECUTION_FAILED ---


@pytest.mark.parametrize(
    ("executor", "reason"),
    [
        (lambda: _executor(error=RuntimeError("boom")), "executor_error"),
        (lambda: _executor(_operation_result(OperationResultStatus.EXECUTION_FAILED)),
         "operation_not_successful"),
    ],
)
@pytest.mark.asyncio
async def test_execution_failed(executor, reason) -> None:
    issue = _issue()
    plan = _plan(issue)

    result = await _run_mount(plan, _authorization(plan), issues=[_issues(issue)], executor=executor())

    _assert_failure(result, CopilotFailure.EXECUTION_FAILED, CopilotExecutionStatus.EXECUTION_FAILED,
                    reason=reason)


# --- VERIFICATION_FAILED ---


@pytest.mark.parametrize(
    ("executor_result", "issues", "reason"),
    [
        (_operation_result(OperationResultStatus.VERIFICATION_FAILED,
                           PostActionVerificationStatus.VERIFICATION_FAILED),
         lambda i: [_issues(i)], "executor_verification"),
        (_operation_result(), lambda i: [_issues(i), HTTPException(status_code=503)], "issues_unreadable"),
    ],
)
@pytest.mark.asyncio
async def test_verification_failed(executor_result, issues, reason) -> None:
    issue = _issue()
    plan = _plan(issue)

    result = await _run_mount(
        plan, _authorization(plan), issues=issues(issue), executor=_executor(executor_result)
    )

    _assert_failure(result, CopilotFailure.VERIFICATION_FAILED,
                    CopilotExecutionStatus.VERIFICATION_FAILED, reason=reason)


# --- ISSUE_STILL_DETECTED ---


@pytest.mark.asyncio
async def test_issue_still_detected() -> None:
    issue = _issue()
    plan = _plan(issue)

    result = await _run_mount(
        plan, _authorization(plan), issues=[_issues(issue), _issues(issue)], executor=_executor(_operation_result())
    )

    _assert_failure(result, CopilotFailure.ISSUE_STILL_DETECTED, CopilotExecutionStatus.VERIFICATION_FAILED,
                    "The operation was verified, but the Issue Resolver still detects the issue.")


# --- the API returns the code ---


def test_execute_api_returns_failure_and_trace_id(client: TestClient) -> None:
    from app.main import app

    plan = _plan()
    app.dependency_overrides[get_caller_privileges] = lambda: frozenset({"Operate"})
    try:
        with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=_issues())):
            response = client.post(
                "/api/iris/copilot/execute",
                json={"plan": plan.model_dump(mode="json"),
                      "authorization": _authorization(plan).model_dump(mode="json"), "confirmed": True},
            )
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["failure"]) == ("execution_rejected", "issue_not_detected")
    assert store.get_trace(body["trace_id"]).status == "issue_not_detected"


# --- the vocabulary is exactly the agreed nine codes ---


def test_failure_vocabulary_is_exactly_the_nine_codes() -> None:
    assert [code.value for code in CopilotFailure] == [
        "plan_rejected", "authorization_failed", "issue_not_detected", "target_changed",
        "parameter_mismatch", "resource_protected", "execution_failed", "verification_failed",
        "issue_still_detected",
    ]
