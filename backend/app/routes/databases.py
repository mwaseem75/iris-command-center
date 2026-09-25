"""The Command Center's third MUTATING route (after
journal.update_purge_archived and namespace.create) — database.create,
this project's first Database mutation.

Exposed as `POST /api/iris/databases`: the SAME resource path
`GET /api/iris/databases` (app/routes/iris.py) already uses to list
databases, with POST as the natural "create" verb on that collection —
same reasoning namespace.create's own module docstring gives for choosing
`POST /api/iris/namespaces` over a divergent path.

Privilege: `%Admin_Manage:U` — the ONLY privilege mainspec_v2.json
documents for `POST /v2/database-dir` ("Create a local database"), and
already a CONFIRMED member of this project's `IRISPrivilege` enum (see
app/authorization/privileges.py's module docstring — individually
exercised during Phase 1 verification). No new privilege was invented for
this operation.

Neither this endpoint nor a real database creation has been exercised
against a real IRIS instance as of this implementation — see
docs/api-capability-matrix.md.
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
    """The public request body for this route.

    `confirmed` defaults to False (safe default) and is the ONLY way to
    supply confirmation — there is no "force"/"skip_confirmation" field,
    the same discipline as NamespaceCreateOperationRequest.

    `extra="forbid"`: a caller sending any field beyond these six gets an
    explicit 422 rather than having it silently ignored.
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
    """Always returns HTTP 200 with a structured OperationResult — the real
    outcome (authorized, confirmation_required, dry_run, success,
    execution_failed, verification_failed, ...) is in `result.status`, the
    same convention POST /api/iris/namespaces already uses.
    """
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
    """Public request body for POST /api/iris/databases/mount. Same
    discipline as DatabaseCreateOperationRequest: `confirmed` defaults to
    False, no force/skip field, and extra fields are rejected (422)."""

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
    """database.mount (`%Admin_Operate:U`) — always HTTP 200 with a
    structured OperationResult, same convention as create_database()."""
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
    """Public request body for POST /api/iris/databases/dismount. Same
    discipline as DatabaseMountOperationRequest: only the Directory,
    `confirmed` defaults to False, no force/skip field, and extra fields are
    rejected (422)."""

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
    """database.dismount (`%Admin_Operate:U`) — always HTTP 200 with a
    structured OperationResult, same convention as mount_database()."""
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
