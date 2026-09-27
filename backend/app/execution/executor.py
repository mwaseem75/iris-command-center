"""Runs operations: authorization, confirmation, execution, verification.

Nothing here is operation-specific. Adding an operation means a registry
entry (app/authorization/operations.py) plus a handler.

Every call also records an execution trace with one span per stage. Only
safe values (operation names, statuses, privilege names, short reasons)
go into span attributes.
"""

from app.authorization.operations import get_operation
from app.authorization.service import authorize
from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResult,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.observability.tracer import TraceRecorder
from app.resolution.catalog import trace_context


class OperationExecutor:
    """Handlers are passed in explicitly, which keeps this easy to test with fakes."""

    def __init__(self, handlers: dict[str, OperationHandler] | None = None):
        self._handlers: dict[str, OperationHandler] = dict(handlers or {})

    def register_handler(self, operation_name: str, handler: OperationHandler) -> None:
        self._handlers[operation_name] = handler

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> OperationResult:
        recorder = TraceRecorder(
            request.operation_name,
            resolution=trace_context(request.resolution_issue_type, request.operation_name, request.parameters),
        )

        operation = get_operation(request.operation_name)
        if operation is None:
            recorder.skip("authorization", "unknown_operation")
            recorder.skip("confirmation", "unknown_operation")
            recorder.skip("execution", "unknown_operation")
            recorder.skip("verification", "unknown_operation")
            recorder.set_result(
                authorization_result="skipped",
                confirmation_result="skipped",
                execution_result="skipped",
                verification_result="skipped",
            )
            recorder.finish(OperationResultStatus.UNKNOWN_OPERATION.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.UNKNOWN_OPERATION,
                authorization=None,
                detail=f"No operation named {request.operation_name!r} is registered.",
            )

        auth_timer = recorder.timer()
        auth_result = authorize(
            request.operation_name,
            context.available_privileges,
            confirmation_received=context.confirmation_received,
        )
        recorder.span(
            "authorization",
            auth_timer,
            status="ok" if auth_result.authorized else "error",
            authorized=auth_result.authorized,
            denial_reason=auth_result.denial_reason.value if auth_result.denial_reason else None,
            required_privileges=sorted(p.value for p in operation.required_privileges),
        )
        recorder.set_result(
            authorization_result=(
                "authorized"
                if auth_result.authorized
                else f"denied:{auth_result.denial_reason.value if auth_result.denial_reason else 'unknown'}"
            )
        )

        # Not authorized (missing privilege or unknown operation): stop before
        # the handler runs.
        if not auth_result.authorized:
            recorder.skip("confirmation", "authorization_denied")
            recorder.skip("execution", "authorization_denied")
            recorder.skip("verification", "authorization_denied")
            recorder.set_result(
                confirmation_result="skipped",
                execution_result="skipped",
                verification_result="skipped",
            )
            recorder.finish(OperationResultStatus.UNAUTHORIZED.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.UNAUTHORIZED,
                authorization=auth_result,
                detail=auth_result.detail,
            )

        confirmation_timer = recorder.timer()
        recorder.span(
            "confirmation",
            confirmation_timer,
            status="ok" if auth_result.can_proceed else "error",
            confirmation_required=auth_result.confirmation_required,
            confirmation_received=auth_result.confirmation_received,
        )
        recorder.set_result(
            confirmation_result=(
                "not_required"
                if not auth_result.confirmation_required
                else "received"
                if auth_result.confirmation_received
                else "required_not_received"
            )
        )

        # Authorized, but a mutating operation still needs confirmation.
        if not auth_result.can_proceed:
            recorder.skip("execution", "confirmation_required")
            recorder.skip("verification", "confirmation_required")
            recorder.set_result(execution_result="skipped", verification_result="skipped")
            recorder.finish(OperationResultStatus.CONFIRMATION_REQUIRED.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.CONFIRMATION_REQUIRED,
                authorization=auth_result,
                detail=auth_result.detail,
            )

        handler = self._handlers.get(request.operation_name)
        if handler is None:
            recorder.skip("execution", "no_handler")
            recorder.skip("verification", "no_handler")
            recorder.set_result(execution_result="skipped", verification_result="skipped")
            recorder.finish(OperationResultStatus.NO_HANDLER.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.NO_HANDLER,
                authorization=auth_result,
                detail=(
                    f"Operation {request.operation_name!r} is authorized but no "
                    "handler is registered for it — nothing can execute yet."
                ),
            )

        if context.dry_run:
            execution_timer = recorder.timer()
            try:
                handler_result = await handler.dry_run(request, context)
            except Exception as exc:  # noqa: BLE001 - a handler bug must not crash the executor
                recorder.span(
                    "execution",
                    execution_timer,
                    status="error",
                    dry_run=True,
                    error_type=exc.__class__.__name__,
                )
                recorder.skip("verification", "dry_run_failed")
                recorder.set_result(
                    execution_result=f"failed:{exc.__class__.__name__}",
                    verification_result="skipped",
                )
                recorder.finish(OperationResultStatus.EXECUTION_FAILED.value)
                return OperationResult(
                    operation_name=request.operation_name,
                    status=OperationResultStatus.EXECUTION_FAILED,
                    authorization=auth_result,
                    detail=f"Dry run could not complete: {exc.__class__.__name__}",
                )
            recorder.span(
                "execution",
                execution_timer,
                status="ok",
                dry_run=True,
                outcome=handler_result.outcome.value,
            )
            recorder.skip("verification", "dry_run")
            recorder.set_result(execution_result="dry_run", verification_result="not_applicable")
            recorder.finish(OperationResultStatus.DRY_RUN.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.DRY_RUN,
                authorization=auth_result,
                handler_result=handler_result,
                verification=None,  # dry runs change nothing, so nothing to verify
                detail="Dry run — no IRIS mutation call was made.",
            )

        # --- Real execution ---
        execution_timer = recorder.timer()
        try:
            handler_result = await handler.execute(request, context)
        except Exception as exc:  # noqa: BLE001 - a handler bug must not crash the executor
            recorder.span(
                "execution", execution_timer, status="error", error_type=exc.__class__.__name__
            )
            recorder.skip("verification", "execution_failed")
            recorder.set_result(
                execution_result=f"failed:{exc.__class__.__name__}",
                verification_result="skipped",
            )
            recorder.finish(OperationResultStatus.EXECUTION_FAILED.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.EXECUTION_FAILED,
                authorization=auth_result,
                detail=f"Handler raised an unexpected error: {exc.__class__.__name__}",
            )

        recorder.span(
            "execution",
            execution_timer,
            status="ok" if handler_result.outcome is HandlerOutcome.SUCCESS else "error",
            outcome=handler_result.outcome.value,
        )
        recorder.set_result(execution_result=handler_result.outcome.value)

        if handler_result.outcome is HandlerOutcome.FAILURE:
            recorder.skip("verification", "execution_failed")
            recorder.set_result(verification_result="skipped")
            recorder.finish(OperationResultStatus.EXECUTION_FAILED.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.EXECUTION_FAILED,
                authorization=auth_result,
                handler_result=handler_result,
                detail=handler_result.detail,
            )

        verification_timer = recorder.timer()
        verification = await handler.verify(request, context, handler_result)
        recorder.span(
            "verification",
            verification_timer,
            status="ok" if verification.status is PostActionVerificationStatus.VERIFIED else "error",
            verification_status=verification.status.value,
        )
        recorder.set_result(verification_result=verification.status.value)

        if verification.status is PostActionVerificationStatus.VERIFICATION_FAILED:
            recorder.finish(OperationResultStatus.VERIFICATION_FAILED.value)
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.VERIFICATION_FAILED,
                authorization=auth_result,
                handler_result=handler_result,
                verification=verification,
                detail=verification.detail,
            )

        recorder.finish(OperationResultStatus.SUCCESS.value)
        return OperationResult(
            operation_name=request.operation_name,
            status=OperationResultStatus.SUCCESS,
            authorization=auth_result,
            handler_result=handler_result,
            verification=verification,
            detail=handler_result.detail,
        )
