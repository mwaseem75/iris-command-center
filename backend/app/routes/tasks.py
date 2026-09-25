"""Mutating route for IRIS tasks: task.run_now.

Exposed as `POST /api/iris/tasks/run-now`, alongside the read-only
`GET /api/iris/tasks*` routes in app/routes/iris.py. Every request runs
through the shared OperationExecutor (authorization -> confirmation ->
execution -> verification, with a recorded trace), exactly like
POST /api/iris/web-apps/set-enabled.

No real POST /v2/task/run has been executed against IRIS as of this
implementation — see app/execution/task_run_now_handler.py.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictInt

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.execution.task_run_now_handler import TaskRunNowHandler
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "task.run_now"


class TaskRunNowOperationRequest(BaseModel):
    """Public request body. `confirmed` defaults to False and is the only way
    to confirm, there is no force/skip field and no scheduling field, and
    extra fields are rejected (422)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Id: StrictInt
    confirmed: bool = False
    dry_run: bool = False


@router.post("/tasks/run-now", response_model=OperationResult)
async def run_task_now(
    body: TaskRunNowOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always HTTP 200 with a structured OperationResult — the real outcome
    is in `result.status`, the same convention as the other operations."""
    executor = OperationExecutor({_OPERATION_NAME: TaskRunNowHandler(client)})
    request = OperationRequest(operation_name=_OPERATION_NAME, parameters={"Id": body.Id})
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
