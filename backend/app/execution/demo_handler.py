"""The Step 5 demonstration handler for `demo.safe-operation`.

This handler NEVER performs any IO — no HTTP call, no IRIS call, in either
dry_run() or execute(). It exists solely to exercise the OperationExecutor
framework end-to-end (authorization, confirmation, dry-run vs. real-path
dispatch) with something real and runnable, while guaranteeing zero risk:
there is nothing here that could reach IRIS even if every safety check
upstream of it were somehow bypassed.

This is NOT a template to copy for a real mutating operation without
careful review — a real handler's execute() would need to actually call
the (currently nonexistent) IRIS mutating endpoint via IRISClient, which
this project has not implemented for any operation yet.
"""

from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
)


class DemoSafeOperationHandler(OperationHandler):
    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="Simulated: demo.safe-operation would run successfully. No IRIS call was made.",
            data={"simulated": True, "operation": request.operation_name},
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        # Deliberately identical to dry_run(): this demo operation is
        # synthetic and is never meant to touch IRIS in any mode.
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="Simulated: demo.safe-operation ran successfully. No IRIS call was made.",
            data={"simulated": True, "operation": request.operation_name},
        )
