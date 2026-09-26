"""Route for the journal.update_purge_archived operation.

It uses its own path rather than mirroring /api/admin/v2/journal/settings,
and only changes PurgeArchived, not the rest of the journal settings.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])

_OPERATION_NAME = "journal.update_purge_archived"


class JournalPurgeArchivedOperationRequest(BaseModel):
    """Request body. Nothing happens without confirmed=true, and there's no
    force/skip field. Unknown fields are rejected with 422.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    PurgeArchived: bool
    confirmed: bool = False
    dry_run: bool = False


@router.post("/journal/purge-archived", response_model=OperationResult)
async def update_journal_purge_archived(
    body: JournalPurgeArchivedOperationRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    """Always returns 200 with an OperationResult; whether the change actually
    happened is in `status` (success, confirmation_required, dry_run, ...).
    """
    executor = OperationExecutor(
        {_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)}
    )
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={"PurgeArchived": body.PurgeArchived},
    )
    context = ExecutionContext(
        available_privileges=privileges,
        confirmation_received=body.confirmed,
        dry_run=body.dry_run,
    )
    return await executor.execute(request, context)
