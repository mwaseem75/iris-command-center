"""Tests for the operation executor, using fake handlers (no IRIS, no network)."""

import pytest

from app.execution.demo_handler import DemoSafeOperationHandler
from app.execution.executor import OperationExecutor
from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)


class RecordingFakeHandler(OperationHandler):
    """Fake handler that records how it was called."""

    def __init__(
        self,
        *,
        execute_outcome: HandlerOutcome = HandlerOutcome.SUCCESS,
        verification_status: PostActionVerificationStatus = PostActionVerificationStatus.VERIFIED,
    ):
        self.dry_run_calls: list[OperationRequest] = []
        self.execute_calls: list[OperationRequest] = []
        self.verify_calls: list[OperationRequest] = []
        self._execute_outcome = execute_outcome
        self._verification_status = verification_status

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        self.dry_run_calls.append(request)
        return HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="simulated")

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        self.execute_calls.append(request)
        return HandlerExecutionResult(
            outcome=self._execute_outcome,
            detail="executed" if self._execute_outcome is HandlerOutcome.SUCCESS else "handler failure",
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        self.verify_calls.append(request)
        return PostActionVerificationResult(
            status=self._verification_status,
            detail="verification result",
        )


def _request(name: str = "demo.safe-operation") -> OperationRequest:
    return OperationRequest(operation_name=name)


def _context(
    *, privileges: frozenset[str] = frozenset({"Manage"}), confirmed: bool = True, dry_run: bool = False
) -> ExecutionContext:
    return ExecutionContext(
        available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run
    )


# --- 1. Unknown operation -> denied ---


@pytest.mark.asyncio
async def test_unknown_operation_is_denied() -> None:
    executor = OperationExecutor()
    result = await executor.execute(_request("no-such-operation"), _context())

    assert result.status is OperationResultStatus.UNKNOWN_OPERATION
    assert result.authorization is None


# --- 2. Missing privilege -> denied ---


@pytest.mark.asyncio
async def test_missing_privilege_is_denied() -> None:
    handler = RecordingFakeHandler()
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(privileges=frozenset({"Operate"}))  # not Manage

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.UNAUTHORIZED
    assert handler.dry_run_calls == []
    assert handler.execute_calls == []


# --- 3. Mutating operation without confirmation -> blocked ---


@pytest.mark.asyncio
async def test_mutating_operation_without_confirmation_is_blocked() -> None:
    handler = RecordingFakeHandler()
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(confirmed=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    assert handler.dry_run_calls == []
    assert handler.execute_calls == []


# --- 4. Mutating operation with confirmation + dry_run -> simulated only ---


@pytest.mark.asyncio
async def test_mutating_operation_with_confirmation_and_dry_run_is_simulated_only() -> None:
    handler = RecordingFakeHandler()
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(confirmed=True, dry_run=True)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.DRY_RUN
    assert len(handler.dry_run_calls) == 1
    assert handler.execute_calls == []  # must not run for real
    assert result.verification is None  # nothing happened, nothing to verify


# --- 5. Safe (demo) operation with required privilege -> succeeds in dry-run ---


@pytest.mark.asyncio
async def test_demo_operation_succeeds_in_dry_run_via_real_handler() -> None:
    """Uses the real DemoSafeOperationHandler instead of a fake."""
    executor = OperationExecutor({"demo.safe-operation": DemoSafeOperationHandler()})
    context = _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert result.handler_result.data == {"simulated": True, "operation": "demo.safe-operation"}


# --- 6. Authorization failure prevents handler execution ---


@pytest.mark.asyncio
async def test_authorization_failure_prevents_any_handler_call() -> None:
    handler = RecordingFakeHandler()
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(privileges=frozenset())  # no privileges at all

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.UNAUTHORIZED
    assert handler.dry_run_calls == []
    assert handler.execute_calls == []
    assert handler.verify_calls == []


# --- 7. Confirmation failure prevents handler execution ---


@pytest.mark.asyncio
async def test_confirmation_failure_prevents_any_handler_call() -> None:
    handler = RecordingFakeHandler()
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(privileges=frozenset({"Manage"}), confirmed=False, dry_run=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    assert handler.dry_run_calls == []
    assert handler.execute_calls == []
    assert handler.verify_calls == []


# --- 8. Handler failure becomes structured execution failure ---


@pytest.mark.asyncio
async def test_handler_failure_becomes_structured_execution_failure() -> None:
    handler = RecordingFakeHandler(execute_outcome=HandlerOutcome.FAILURE)
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(confirmed=True, dry_run=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert handler.verify_calls == []  # never verify a failed execution


@pytest.mark.asyncio
async def test_handler_raising_an_exception_becomes_structured_execution_failure() -> None:
    class RaisingHandler(OperationHandler):
        async def dry_run(self, request, context):  # noqa: D102
            raise AssertionError("not used in this test")

        async def execute(self, request, context):  # noqa: D102
            raise RuntimeError("simulated handler bug — never a real IRIS call")

    executor = OperationExecutor({"demo.safe-operation": RaisingHandler()})
    context = _context(confirmed=True, dry_run=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "credential" not in result.detail.lower()
    assert "password" not in result.detail.lower()


@pytest.mark.asyncio
async def test_handler_dry_run_raising_an_exception_becomes_structured_failure_not_a_crash() -> None:
    """Handlers can do real reads in dry_run() (e.g. the journal handler), and
    those can fail. That should be caught like an execute() failure.
    """

    class RaisingOnDryRunHandler(OperationHandler):
        async def dry_run(self, request, context):  # noqa: D102
            raise RuntimeError("simulated read failure during dry run — never a real PUT")

        async def execute(self, request, context):  # noqa: D102
            raise AssertionError("not used in this test")

    executor = OperationExecutor({"demo.safe-operation": RaisingOnDryRunHandler()})
    context = _context(confirmed=True, dry_run=True)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "credential" not in result.detail.lower()
    assert "password" not in result.detail.lower()


# --- 9. Post-action verification failure is represented separately ---


@pytest.mark.asyncio
async def test_post_action_verification_failure_is_distinct_from_execution_failure() -> None:
    handler = RecordingFakeHandler(
        execute_outcome=HandlerOutcome.SUCCESS,
        verification_status=PostActionVerificationStatus.VERIFICATION_FAILED,
    )
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(confirmed=True, dry_run=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert result.status is not OperationResultStatus.EXECUTION_FAILED
    assert len(handler.execute_calls) == 1
    assert len(handler.verify_calls) == 1


@pytest.mark.asyncio
async def test_successful_execution_with_successful_verification() -> None:
    handler = RecordingFakeHandler(
        execute_outcome=HandlerOutcome.SUCCESS,
        verification_status=PostActionVerificationStatus.VERIFIED,
    )
    executor = OperationExecutor({"demo.safe-operation": handler})
    context = _context(confirmed=True, dry_run=False)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED


# --- No handler registered ---


@pytest.mark.asyncio
async def test_authorized_operation_with_no_registered_handler() -> None:
    executor = OperationExecutor()  # no handlers registered at all
    context = _context(privileges=frozenset({"Manage"}), confirmed=True)

    result = await executor.execute(_request(), context)

    assert result.status is OperationResultStatus.NO_HANDLER
    assert result.authorization is not None
    assert result.authorization.authorized is True


# --- Safety-invariant guards ---


def test_execution_context_has_no_bypass_fields() -> None:
    assert set(ExecutionContext.model_fields.keys()) == {
        "available_privileges",
        "confirmation_received",
        "dry_run",
    }


def test_operation_handler_dry_run_and_execute_are_abstract() -> None:
    with pytest.raises(TypeError):
        OperationHandler()  # type: ignore[abstract]
