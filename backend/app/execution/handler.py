"""The handler abstraction. This is the seam future steps use to give
individual operations their own implementation without putting
operation-specific logic into OperationExecutor itself — the executor only
ever calls these three methods, generically, on whichever handler is
registered for the operation it's running.

No concrete subclass in this project may call a real IRIS mutating
endpoint yet. The only concrete handler that exists (demo_handler.py) is
explicitly synthetic and never performs any IO at all.
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
        """Return what WOULD happen, performing no IO of any kind — no IRIS
        call, mutating or otherwise. Required of every handler; there is no
        default implementation, so a handler author cannot forget this and
        accidentally fall through to a real call."""
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Perform the real operation. Not implemented by any handler in
        this project yet (see demo_handler.py, whose implementation is
        still fully synthetic/no-IO, deliberately)."""
        raise NotImplementedError

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Check IRIS's actual resulting state after a real execute() call.
        Optional — the default is NOT_APPLICABLE, meaning this operation
        defines no post-action verification. Only ever called by the
        executor after a real (non-dry-run) execute() that succeeded."""
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.NOT_APPLICABLE,
            detail="This handler defines no post-action verification.",
        )
