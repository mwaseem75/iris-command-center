"""The Command Center's second MUTATING route (after
journal.update_purge_archived) — namespace.create, this project's first
Namespace mutation.

Exposed as `POST /api/iris/namespaces`: the SAME resource path
`GET /api/iris/namespaces` (app/routes/iris.py) already uses to list
namespaces, with POST as the natural "create" verb on that collection.
This deliberately differs from journal.update_purge_archived's own,
deliberately-divergent path choice (`/api/iris/journal/purge-archived`,
not `/api/iris/journal/settings`) — that divergence exists specifically
because that operation only ever touches ONE field of a much larger
JournalSettings object it does not otherwise expose for writing. That
reasoning doesn't apply here: this operation creates an entire new
namespace resource, so mirroring the collection's own GET path is the
more accurate, more RESTful choice.

Privilege: `%Admin_Manage:U` — the ONLY privilege mainspec_v2.json
documents for both `PUT /v2/namespace` ("Create/Edit a namespace") and
`POST /v2/namespace/enable-interop`, and already a CONFIRMED member of
this project's `IRISPrivilege` enum (see app/authorization/privileges.py's
module docstring — individually exercised during Phase 1 verification).
No new privilege was invented for this operation.

Neither endpoint has been called against a real IRIS instance as of this
implementation — see docs/api-capability-matrix.md.
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
    """The public request body for this route.

    `confirmed` defaults to False (safe default) and is the ONLY way to
    supply confirmation — there is no "force"/"skip_confirmation" field,
    the same discipline as JournalPurgeArchivedOperationRequest.

    `extra="forbid"`: a caller sending any field beyond these seven gets
    an explicit 422 rather than having it silently ignored.
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
    """Always returns HTTP 200 with a structured OperationResult — the real
    outcome (authorized, confirmation_required, dry_run, success,
    execution_failed, verification_failed, ...) is in `result.status`, the
    same convention POST /api/iris/journal/purge-archived already uses.
    """
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
