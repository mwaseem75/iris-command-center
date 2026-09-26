"""user.set_enabled: POST /api/iris/security/users/set-enabled.

Runs through the executor like the other operations. The Command Center's
own IRIS login (IRIS_USERNAME) is passed to the handler so it can never be
disabled.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictBool

from app.config import get_settings
from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.execution.user_set_enabled_handler import UserSetEnabledHandler
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "user.set_enabled"


class UserSetEnabledOperationRequest(BaseModel):
    """Request body. Nothing happens without confirmed=true, there's no force/skip
    field, and unknown fields are rejected with 422.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Enabled: StrictBool
    confirmed: bool = False
    dry_run: bool = False


@router.post("/security/users/set-enabled", response_model=OperationResult)
async def set_user_enabled(
    body: UserSetEnabledOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    handler = UserSetEnabledHandler(client, own_username=get_settings().iris_username)
    executor = OperationExecutor({_OPERATION_NAME: handler})
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={"Name": body.Name, "Enabled": body.Enabled},
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
