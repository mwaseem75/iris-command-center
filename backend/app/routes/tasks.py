"""task.run_now: POST /api/iris/tasks/run-now.

Runs through the executor (authorization, confirmation, execution,
verification) like the other operations.
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
    """Request body. Needs confirmed=true; no force/skip or scheduling fields,
    and unknown fields are rejected with 422.
    """

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
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_OPERATION_NAME: TaskRunNowHandler(client)})
    request = OperationRequest(operation_name=_OPERATION_NAME, parameters={"Id": body.Id})
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
