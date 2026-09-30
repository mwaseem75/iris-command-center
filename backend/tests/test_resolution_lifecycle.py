"""Focused tests for lifecycle evidence on supported issue resolutions."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.executor import _lifecycle_evidence
from app.execution.executor import OperationExecutor
from app.execution.handler import OperationHandler
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    OperationResult,
    OperationResultStatus,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.resolution.catalog import trace_context
from app.observability import store as observability_store


@pytest.mark.parametrize(
    ("issue_type", "operation", "parameters", "before_data", "after", "state"),
    [
        (
            "database_dismounted",
            "database.mount",
            {"Directory": "/data/demo/", "ReadOnly": False},
            {"mounted_before": False},
            {"mounted": True},
            {"mounted": False},
        ),
        (
            "web_app_namespace_missing",
            "web_app.set_enabled",
            {"Name": "/csp/orders", "Enabled": False},
            {"enabled_before": True},
            {"enabled": False},
            {"enabled": True},
        ),
        (
            "journal_purge_archived_off",
            "journal.update_purge_archived",
            {"PurgeArchived": True},
            {"original_purge_archived": False},
            {"purge_archived": True},
            {"purge_archived": False},
        ),
    ],
)
def test_lifecycle_evidence_carries_bounded_before_action_and_after(
    issue_type: str,
    operation: str,
    parameters: dict[str, object],
    before_data: dict[str, object],
    after: dict[str, bool],
    state: dict[str, bool],
) -> None:
    request = OperationRequest(
        operation_name=operation,
        parameters=parameters,
        resolution_issue_type=issue_type,
    )
    context = trace_context(issue_type, operation, parameters)
    assert context is not None
    handler_result = HandlerExecutionResult(
        outcome=HandlerOutcome.SUCCESS,
        detail="existing operation detail",
        data=before_data,
    )
    verification = PostActionVerificationResult(
        status=PostActionVerificationStatus.VERIFIED,
        detail="existing verification detail",
        evidence=after,
    )

    lifecycle = _lifecycle_evidence(
        request,
        context,
        datetime.now(timezone.utc),
        handler_result,
        verification,
    )

    assert lifecycle is not None
    assert lifecycle.before.issue_id == context.issue_id
    assert lifecycle.before.resource == context.resource_reference
    assert lifecycle.before.state == state
    assert lifecycle.action.operation_name == operation
    assert lifecycle.action.parameters == parameters
    assert lifecycle.after == after

    result = OperationResult(
        operation_name=operation,
        status=OperationResultStatus.SUCCESS,
        handler_result=handler_result,
        verification=verification,
        detail=handler_result.detail,
        lifecycle=lifecycle,
    )
    assert result.status is OperationResultStatus.SUCCESS
    assert result.handler_result is handler_result
    assert result.verification is verification
    assert result.detail == "existing operation detail"
    assert result.lifecycle == lifecycle


class _LifecycleHandler(OperationHandler):
    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        return HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="dry run")

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="mounted",
            data={"directory": request.parameters["Directory"], "mounted_before": False},
        )

    async def verify(
        self, request: OperationRequest, context: ExecutionContext, execution_result: HandlerExecutionResult
    ) -> PostActionVerificationResult:
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail="mounted",
            evidence={"mounted": True},
        )


@pytest.mark.asyncio
async def test_executor_returns_and_traces_resolution_lifecycle() -> None:
    observability_store.clear_traces()
    parameters = {"Directory": "/data/demo/", "ReadOnly": False}
    result = await OperationExecutor({"database.mount": _LifecycleHandler()}).execute(
        OperationRequest(
            operation_name="database.mount",
            parameters=parameters,
            resolution_issue_type="database_dismounted",
        ),
        ExecutionContext(
            available_privileges=frozenset({"Operate"}),
            confirmation_received=True,
        ),
    )

    (trace,) = observability_store.list_traces()
    assert result.status is OperationResultStatus.SUCCESS
    assert result.lifecycle is not None
    assert result.lifecycle.after == {"mounted": True}
    assert trace.lifecycle == result.lifecycle
    observability_store.clear_traces()


@pytest.mark.asyncio
async def test_database_mount_verification_returns_structured_mounted_state() -> None:
    handler = DatabaseMountHandler(AsyncMock(), verify_retry_delays_seconds=())
    handler._read_mounted = AsyncMock(return_value=True)
    result = HandlerExecutionResult(
        outcome=HandlerOutcome.SUCCESS,
        detail="mounted",
        data={"directory": "/data/demo/"},
    )

    verification = await handler.verify(
        OperationRequest(operation_name="database.mount"),
        ExecutionContext(),
        result,
    )

    assert verification.status is PostActionVerificationStatus.VERIFIED
    assert verification.evidence == {"mounted": True}


@pytest.mark.asyncio
async def test_web_app_verification_returns_structured_disabled_state() -> None:
    handler = WebAppSetEnabledHandler(AsyncMock(), verify_retry_delays_seconds=())
    handler._read_enabled = AsyncMock(return_value=False)
    handler._read_list_entry = AsyncMock(return_value={"Type": "CSP"})
    result = HandlerExecutionResult(
        outcome=HandlerOutcome.SUCCESS,
        detail="disabled",
        data={"name": "/csp/orders", "enabled_after": False, "type_before": "CSP"},
    )

    verification = await handler.verify(
        OperationRequest(operation_name="web_app.set_enabled"),
        ExecutionContext(),
        result,
    )

    assert verification.status is PostActionVerificationStatus.VERIFIED
    assert verification.evidence == {"enabled": False}


@pytest.mark.asyncio
async def test_journal_verification_returns_structured_purge_archived_state() -> None:
    handler = JournalUpdatePurgeArchivedHandler(AsyncMock())
    handler._read_current_purge_archived = AsyncMock(return_value=True)
    result = HandlerExecutionResult(
        outcome=HandlerOutcome.SUCCESS,
        detail="updated",
        data={"requested_purge_archived": True},
    )

    verification = await handler.verify(
        OperationRequest(operation_name="journal.update_purge_archived"),
        ExecutionContext(),
        result,
    )

    assert verification.status is PostActionVerificationStatus.VERIFIED
    assert verification.evidence == {"purge_archived": True}
