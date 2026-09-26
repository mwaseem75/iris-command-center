"""Database operations: create (POST /api/iris/databases), mount and dismount.

Creating uses POST on the same collection path the database list uses.
Create needs %Admin_Manage:U, mount/dismount need %Admin_Operate:U. All of
them go through the executor (authorization, confirmation, verification).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.database_create_handler import DatabaseCreateHandler
from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.database_dismount_handler import DatabaseDismountHandler
from app.execution.executor import OperationExecutor
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "database.create"


class DatabaseCreateOperationRequest(BaseModel):
    """Request body. Nothing happens without confirmed=true, there's no force/skip
    field, and unknown fields are rejected with 422.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    ResourceName: str | None = None
    Size: int | None = None
    GlobalJournalState: bool | None = None
    Encrypted: bool | None = None
    confirmed: bool = False
    dry_run: bool = False


@router.post("/databases", response_model=OperationResult)
async def create_database(
    body: DatabaseCreateOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_OPERATION_NAME: DatabaseCreateHandler(client)})
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={
            "Directory": body.Directory,
            "ResourceName": body.ResourceName,
            "Size": body.Size,
            "GlobalJournalState": body.GlobalJournalState,
            "Encrypted": body.Encrypted,
        },
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)


_MOUNT_OPERATION_NAME = "database.mount"


class DatabaseMountOperationRequest(BaseModel):
    """Request body for mount (same rules as create)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    ReadOnly: bool = False
    confirmed: bool = False
    dry_run: bool = False


@router.post("/databases/mount", response_model=OperationResult)
async def mount_database(
    body: DatabaseMountOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """database.mount. Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_MOUNT_OPERATION_NAME: DatabaseMountHandler(client)})
    request = OperationRequest(
        operation_name=_MOUNT_OPERATION_NAME,
        parameters={"Directory": body.Directory, "ReadOnly": body.ReadOnly},
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)


_DISMOUNT_OPERATION_NAME = "database.dismount"


class DatabaseDismountOperationRequest(BaseModel):
    """Request body for dismount: just the Directory (same rules as create)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    confirmed: bool = False
    dry_run: bool = False


@router.post("/databases/dismount", response_model=OperationResult)
async def dismount_database(
    body: DatabaseDismountOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """database.dismount. Always returns 200 with an OperationResult; the outcome is in `status`."""
    executor = OperationExecutor({_DISMOUNT_OPERATION_NAME: DatabaseDismountHandler(client)})
    request = OperationRequest(
        operation_name=_DISMOUNT_OPERATION_NAME,
        parameters={"Directory": body.Directory},
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
