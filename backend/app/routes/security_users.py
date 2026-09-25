"""Mutating route for IRIS users: user.set_enabled.

Exposed as `POST /api/iris/security/users/set-enabled`, alongside the
read-only `GET /api/iris/security/users*` routes in
app/routes/security_access.py. Every request runs through the shared
OperationExecutor (authorization -> confirmation -> execution ->
verification, with a recorded trace), exactly like
POST /api/iris/web-apps/set-enabled.

The Command Center's own IRIS sign-in account (the configured
IRIS_USERNAME) is passed to the handler so it is always protected.

No real PUT /v2/security/user has been executed against IRIS as of this
implementation — see app/execution/user_set_enabled_handler.py.
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
    """Public request body. Same discipline as web_app.set_enabled:
    `confirmed` defaults to False and is the only way to confirm, there is
    no force/skip field, and extra fields are rejected (422)."""

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
    """Always HTTP 200 with a structured OperationResult — the real outcome
    is in `result.status`, the same convention as the other operations."""
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
