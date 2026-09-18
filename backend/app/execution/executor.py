"""OperationExecutor: the reusable service that sits after authorization
and before any real IRIS mutation.

Contains no operation-specific logic — every branch here is generic,
driven entirely by the looked-up OperationDefinition, the Step 4
authorization decision, and whichever handler is registered for the
operation. Adding a new operation never requires touching this file: it
means adding a registry entry (app/authorization/operations.py) and a
handler (app/execution/handler.py subclass), then calling
register_handler().
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
        operation = get_operation(request.operation_name)
        if operation is None:
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.UNKNOWN_OPERATION,
                authorization=None,
                detail=f"No operation named {request.operation_name!r} is registered.",
            )

        auth_result = authorize(
            request.operation_name,
            context.available_privileges,
            confirmation_received=context.confirmation_received,
        )

        # Authorization failure (missing privilege, or an otherwise-unknown
        # operation authorize() itself rejected) — the handler is never
        # reached. Checked before anything else that follows.
        if not auth_result.authorized:
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.UNAUTHORIZED,
                authorization=auth_result,
                detail=auth_result.detail,
            )

        # Authorized, but a mutating operation still awaiting confirmation.
        # The handler is never reached here either.
        if not auth_result.can_proceed:
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.CONFIRMATION_REQUIRED,
                authorization=auth_result,
                detail=auth_result.detail,
            )

        handler = self._handlers.get(request.operation_name)
        if handler is None:
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
            # A dry-run's own GET(s) can genuinely fail once a handler
            # performs real IO (Phase 2 Step 7's journal handler is the
            # first to) — caught the same way a real execute() failure is,
            # so a dry-run NEVER crashes out as an unhandled exception. No
            # mutation risk either way: handler.execute() is not reachable
            # from this branch regardless of what happens here.
            try:
                handler_result = await handler.dry_run(request, context)
            except Exception as exc:  # noqa: BLE001 - a handler bug must not crash the executor
                return OperationResult(
                    operation_name=request.operation_name,
                    status=OperationResultStatus.EXECUTION_FAILED,
                    authorization=auth_result,
                    detail=f"Dry run could not complete: {exc.__class__.__name__}",
                )
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
        try:
            handler_result = await handler.execute(request, context)
        except Exception as exc:  # noqa: BLE001 - a handler bug must not crash the executor
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.EXECUTION_FAILED,
                authorization=auth_result,
                detail=f"Handler raised an unexpected error: {exc.__class__.__name__}",
            )

        if handler_result.outcome is HandlerOutcome.FAILURE:
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.EXECUTION_FAILED,
                authorization=auth_result,
                handler_result=handler_result,
                detail=handler_result.detail,
            )

        verification = await handler.verify(request, context, handler_result)
        if verification.status is PostActionVerificationStatus.VERIFICATION_FAILED:
            return OperationResult(
                operation_name=request.operation_name,
                status=OperationResultStatus.VERIFICATION_FAILED,
                authorization=auth_result,
                handler_result=handler_result,
                verification=verification,
                detail=verification.detail,
            )

        return OperationResult(
            operation_name=request.operation_name,
            status=OperationResultStatus.SUCCESS,
            authorization=auth_result,
            handler_result=handler_result,
            verification=verification,
            detail=handler_result.detail,
        )
