"""OperationExecutor: the reusable service that sits after authorization
and before any real IRIS mutation.

Contains no operation-specific logic — every branch here is generic,
driven entirely by the looked-up OperationDefinition, the Step 4
authorization decision, and whichever handler is registered for the
operation. Adding a new operation never requires touching this file: it
means adding a registry entry (app/authorization/operations.py) and a
handler (app/execution/handler.py subclass), then calling
register_handler().

Every call to execute() also records a structured ExecutionTrace (see
app/observability/) spanning authorization -> confirmation -> execution ->
verification — this is pure, additive observability: it changes nothing
about the OperationResult this method returns, the authorization decision,
or whether/how a handler runs. Only safe, already-non-sensitive values
(operation names, statuses, privilege NAMES, short reason strings) are
ever passed into a span's attributes — never a credential, token, or
Authorization header.
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


class OperationExecutor:
    """Handlers are supplied via the constructor / register_handler(), not
    read from a hidden global — this keeps the executor trivially testable
    with fake handlers and keeps handler wiring explicit."""

    def __init__(self, handlers: dict[str, OperationHandler] | None = None):
        self._handlers: dict[str, OperationHandler] = dict(handlers or {})

    def register_handler(self, operation_name: str, handler: OperationHandler) -> None:
        self._handlers[operation_name] = handler

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> OperationResult:
        recorder = TraceRecorder(request.operation_name)

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

        # Authorization failure (missing privilege, or an otherwise-unknown
        # operation authorize() itself rejected) — the handler is never
        # reached. Checked before anything else that follows.
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

        # Authorized, but a mutating operation still awaiting confirmation.
        # The handler is never reached here either.
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
                verification=None,  # a dry-run changes nothing; there is nothing to verify
                detail="Dry run — no IRIS mutation call was made.",
            )

        # --- Real execution path. No concrete handler in this project
        # implements a real IRIS mutation yet (see handler.py, demo_handler.py). ---
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
