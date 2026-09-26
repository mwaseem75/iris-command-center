"""Handler for demo.safe-operation, a test operation that never does any IO.

Useful for exercising the executor (authorization, confirmation, dry run
vs. real run) without any chance of touching IRIS.
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
        # Same as dry_run(): this demo operation never touches IRIS.
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="Simulated: demo.safe-operation ran successfully. No IRIS call was made.",
            data={"simulated": True, "operation": request.operation_name},
        )
