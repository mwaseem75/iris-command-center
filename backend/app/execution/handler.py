"""Base class for operation handlers.

The executor calls dry_run(), execute() and verify() on whichever handler
is registered for an operation, so operation-specific code lives here and
not in the executor.
"""

from abc import ABC, abstractmethod

from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)


class OperationHandler(ABC):
    @abstractmethod
    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Report what would happen without calling IRIS for writes.
        Every handler must implement this.
        """
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Perform the operation against IRIS."""
        raise NotImplementedError

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Re-check IRIS after a successful execute(). Defaults to NOT_APPLICABLE."""
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.NOT_APPLICABLE,
            detail="This handler defines no post-action verification.",
        )
