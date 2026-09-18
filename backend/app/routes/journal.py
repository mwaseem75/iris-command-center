"""The Command Center's first MUTATING route.

Deliberately NOT `/api/iris/journal/settings` (which would mirror IRIS's
own `/api/admin/v2/journal/settings` path directly) — this is a distinct,
operation-scoped public API surface, per this step's explicit instruction
not to mirror the IRIS path. It exposes exactly one operation
(`journal.update_purge_archived`, see app/authorization/operations.py),
not the full JournalSettings object.

This route has NOT been called against any real IRIS instance as of Phase 2
Step 7 — see docs/first-mutation-implementation.md.
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
    """The public request body for this route.

    `confirmed` defaults to False (safe default) and is the ONLY way to
    supply confirmation — there is no "force" or "skip_confirmation" field,
    and none is planned. Leaving `confirmed` False (or omitting it) is
    guaranteed, by the Step 4/5 framework this route delegates to, to stop
    before any PUT is sent.

    `extra="forbid"`: a caller sending any field beyond these three (e.g.
    ArchiveName, or any other JournalSettings property) gets an explicit
    422 rather than having it silently ignored.
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
    """Always returns HTTP 200 with a structured OperationResult — the real
    outcome (authorized, confirmation_required, dry_run, success,
    execution_failed, verification_failed, ...) is in `result.status`, the
    same convention this project already uses (e.g. the OAuth2 "not
    configured" case in app/routes/iris.py). This keeps "the HTTP
    transaction succeeded" and "the requested operation succeeded" as two
    separate, non-conflated facts.
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
