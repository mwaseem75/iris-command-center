"""Web application operations: set-enabled and update-description.

Both run through the executor (authorization, confirmation, execution,
verification). The registry asks for Manage; the handlers also require
Secure because IRIS's own PUT /v2/web-app checks it.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.execution.web_app_update_description_handler import WebAppUpdateDescriptionHandler
from app.iris_client.client import IRISClient
from app.resolution.catalog import resolves_with

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "web_app.set_enabled"


class WebAppSetEnabledOperationRequest(BaseModel):
    """Request body. Nothing happens without confirmed=true, there's no force/skip
    field, and unknown fields are rejected with 422. `resolution_issue_type` is
    set when the change is part of an Issue Resolution workflow; it only labels
    the trace (same as database.mount).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Enabled: StrictBool
    confirmed: bool = False
    dry_run: bool = False
    resolution_issue_type: str | None = None


@router.post("/web-apps/set-enabled", response_model=OperationResult)
async def set_web_app_enabled(
    body: WebAppSetEnabledOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    issue_type = body.resolution_issue_type
    if issue_type is not None and not resolves_with(issue_type, _OPERATION_NAME):
        raise HTTPException(
            status_code=422,
            detail=f"{issue_type!r} is not an issue type resolved by {_OPERATION_NAME}.",
        )
    executor = OperationExecutor({_OPERATION_NAME: WebAppSetEnabledHandler(client)})
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={"Name": body.Name, "Enabled": body.Enabled},
        resolution_issue_type=issue_type,
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)


_UPDATE_DESCRIPTION_OPERATION = "web_app.update_description"


class WebAppUpdateDescriptionOperationRequest(BaseModel):
    """Request body for update-description: just Name and Description (same rules)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Description: StrictStr
    confirmed: bool = False
    dry_run: bool = False


@router.post("/web-apps/update-description", response_model=OperationResult)
async def update_web_app_description(
    body: WebAppUpdateDescriptionOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_UPDATE_DESCRIPTION_OPERATION: WebAppUpdateDescriptionHandler(client)})
    request = OperationRequest(
        operation_name=_UPDATE_DESCRIPTION_OPERATION,
        parameters={"Name": body.Name, "Description": body.Description},
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
