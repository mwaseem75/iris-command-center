"""Mutating route for web applications: web_app.set_enabled.

Exposed as `POST /api/iris/web-apps/set-enabled`, alongside the read-only
`GET /api/iris/web-apps*` routes in app/routes/iris.py. Every request runs
through the shared OperationExecutor (authorization -> confirmation ->
execution -> verification, with a recorded trace), exactly like
POST /api/iris/databases/mount.

Privilege: this project's registry requires Manage; the handler also
requires Secure, the privilege IRIS's own implementation of PUT
/v2/web-app enforces — see app/execution/web_app_set_enabled_handler.py.

No real PUT /v2/web-app has been executed against IRIS as of this
implementation — see that module's docstring.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictBool

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "web_app.set_enabled"


class WebAppSetEnabledOperationRequest(BaseModel):
    """Public request body. Same discipline as the database routes:
    `confirmed` defaults to False and is the only way to confirm, there is
    no force/skip field, and extra fields are rejected (422)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Enabled: StrictBool
    confirmed: bool = False
    dry_run: bool = False


@router.post("/web-apps/set-enabled", response_model=OperationResult)
async def set_web_app_enabled(
    body: WebAppSetEnabledOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always HTTP 200 with a structured OperationResult — the real outcome
    is in `result.status`, the same convention as the database routes."""
    executor = OperationExecutor({_OPERATION_NAME: WebAppSetEnabledHandler(client)})
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
