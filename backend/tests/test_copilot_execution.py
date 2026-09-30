"""Tests for the gated Copilot executor and journal setting verification."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.copilot.execution import CopilotExecutionService
from app.execution.executor import OperationExecutor
from app.execution.models import (
    HandlerExecutionResult,
    HandlerOutcome,
    OperationResult,
    OperationResultStatus,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotAuthorizationResult,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotTargetKind,
)
from app.routes.copilot import get_caller_privileges


def _plan(value: bool = True) -> CopilotOperationPlan:
    return CopilotOperationPlan(
        operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.JOURNAL_SETTINGS,
            identifier="journal-settings",
        ),
        parameters=CopilotOperationParameters(PurgeArchived=value),
        reason="Requested by the operator.",
        requires_confirmation=True,
    )


def _authorization(
    *,
    authorized: bool = True,
    requires_confirmation: bool = False,
    ready: bool = True,
) -> CopilotAuthorizationResult:
    return CopilotAuthorizationResult(
        authorized=authorized,
        requires_confirmation=requires_confirmation,
        ready_to_execute=ready,
        reason=(
            CopilotAuthorizationReason.AUTHORIZED
            if authorized and ready
            else CopilotAuthorizationReason.CONFIRMATION_REQUIRED
            if authorized
            else CopilotAuthorizationReason.MISSING_PRIVILEGE
        ),
        required_privileges=["Journal", "Manage"],
        operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
        target=_plan().target,
    )


def _operation_result(
    *,
    status: OperationResultStatus = OperationResultStatus.SUCCESS,
    actual: bool = True,
    verification_status: PostActionVerificationStatus = PostActionVerificationStatus.VERIFIED,
    outcome: HandlerOutcome = HandlerOutcome.SUCCESS,
) -> OperationResult:
    return OperationResult(
        operation_name=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED.value,
        status=status,
        handler_result=HandlerExecutionResult(
            outcome=outcome,
            detail="executor result",
            data={"requested_purge_archived": actual},
        ),
        verification=PostActionVerificationResult(
            status=verification_status,
            detail="handler verification",
            evidence={"purge_archived": actual},
        ),
        detail="executor result",
    )


def _settings(value: object):
    return SimpleNamespace(result=SimpleNamespace(PurgeArchived=value))


@pytest.mark.asyncio
async def test_ready_authorization_calls_existing_executor_and_verifies_true() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(actual=True)
    client = AsyncMock()
    service = CopilotExecutionService(client, frozenset({"Manage"}), executor)

    with patch("app.copilot.execution.get_journal_settings", new=AsyncMock(return_value=_settings(True))) as verify:
        result = await service.execute(_plan(True), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.SUCCESS
    assert result.execution_succeeded is True
    assert result.verification_succeeded is True
    assert result.verified_value is True
    executor.execute.assert_awaited_once()
    verify.assert_awaited_once_with(client)


@pytest.mark.parametrize(
    ("authorization", "confirmed"),
    [
        (_authorization(ready=False, requires_confirmation=True), False),
        (_authorization(authorized=False, ready=False), True),
        (_authorization(ready=False, requires_confirmation=True), True),
    ],
)
@pytest.mark.asyncio
async def test_unready_unauthorized_or_unconfirmed_never_calls_executor(
    authorization: CopilotAuthorizationResult,
    confirmed: bool,
) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    result = await service.execute(_plan(), authorization, confirmed=confirmed)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_operation_with_another_operations_target_never_calls_executor() -> None:
    # database.mount is supported now; with the journal target and parameters
    # it's still rejected. Unsupported operations are rejected by the models.
    plan = _plan().model_copy(update={"operation": "database.mount"})
    executor = AsyncMock(spec=OperationExecutor)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    result = await service.execute(plan, _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_exception_returns_structured_failure_without_retry() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.side_effect = RuntimeError("private executor detail")
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    result = await service.execute(_plan(), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_FAILED
    assert result.execution_succeeded is False
    assert "private executor detail" not in result.detail
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_failure_status_is_not_reported_as_success() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(
        status=OperationResultStatus.EXECUTION_FAILED
    )
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    result = await service.execute(_plan(), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_FAILED
    assert result.execution_succeeded is False
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_success_but_handler_verification_failure_is_unsuccessful() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(
        status=OperationResultStatus.VERIFICATION_FAILED,
        verification_status=PostActionVerificationStatus.VERIFICATION_FAILED
    )
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    result = await service.execute(_plan(), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.execution_succeeded is True
    assert result.verification_succeeded is False
    executor.execute.assert_awaited_once()


@pytest.mark.parametrize(
    ("actual", "expected"),
    [(False, True), ("unexpected", None)],
)
@pytest.mark.asyncio
async def test_readback_mismatch_or_unexpected_value_is_unsuccessful(
    actual: object,
    expected: bool | None,
) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(actual=True)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor)

    with patch(
        "app.copilot.execution.get_journal_settings",
        new=AsyncMock(return_value=_settings(actual)),
    ):
        result = await service.execute(_plan(True), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.execution_succeeded is True
    assert result.verification_succeeded is False
    assert result.verified_value is expected


@pytest.mark.asyncio
async def test_false_setting_is_verified_as_false() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(actual=False)
    service = CopilotExecutionService(AsyncMock(), frozenset({"Journal"}), executor)

    with patch(
        "app.copilot.execution.get_journal_settings",
        new=AsyncMock(return_value=_settings(False)),
    ):
        result = await service.execute(_plan(False), _authorization(), confirmed=True)

    assert result.status is CopilotExecutionStatus.SUCCESS
    assert result.verified_value is False
    executor.execute.assert_awaited_once()


def test_execute_endpoint_requires_confirmation_and_never_accepts_raw_message(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/iris/copilot/execute",
        json={
            "plan": _plan().model_dump(mode="json"),
            "authorization": _authorization().model_dump(mode="json"),
            "confirmed": False,
            "message": "execute it",
        },
    )

    assert response.status_code == 422


def test_execute_endpoint_revalidates_authorization_before_service(
    client: TestClient,
    mock_iris_client: AsyncMock,
) -> None:
    from app.main import app

    app.dependency_overrides[get_caller_privileges] = lambda: frozenset()
    try:
        response = client.post(
            "/api/iris/copilot/execute",
            json={
                "plan": _plan().model_dump(mode="json"),
                "authorization": _authorization().model_dump(mode="json"),
                "confirmed": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)

    assert response.status_code == 200
    assert response.json()["status"] == "execution_rejected"
    assert mock_iris_client.put.assert_not_awaited() is None
    assert mock_iris_client.post.assert_not_awaited() is None
    mock_iris_client.get.assert_not_awaited()
