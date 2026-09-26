"""Namespace creation: POST /api/iris/namespaces (needs %Admin_Manage:U).

Unlike the journal route, this creates a whole resource, so it uses POST on
the same collection path the namespace list uses. Runs through the executor
with authorization, confirmation and verification.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.execution.namespace_create_handler import NamespaceCreateHandler
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "namespace.create"


class NamespaceCreateOperationRequest(BaseModel):
    """Request body. Nothing happens without confirmed=true, there's no force/skip
    field, and unknown fields are rejected with 422.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Globals: str
    Routines: str
    TempGlobals: str | None = None
    Interop: bool = False
    confirmed: bool = False
    dry_run: bool = False


@router.post("/namespaces", response_model=OperationResult)
async def create_namespace(
    body: NamespaceCreateOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_OPERATION_NAME: NamespaceCreateHandler(client)})
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={
            "Name": body.Name,
            "Globals": body.Globals,
            "Routines": body.Routines,
            "TempGlobals": body.TempGlobals,
            "Interop": body.Interop,
        },
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
