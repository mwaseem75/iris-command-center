"""The handler for `journal.update_purge_archived` — the project's first
REAL mutating operation handler (see docs/first-mutation-selection.md and
docs/first-mutation-implementation.md).

As of Phase 2 Step 7, this handler exists and is fully implemented, but has
NOT been executed against any real IRIS instance. All tests exercising it
use a fake/mock IRIS client — see backend/tests/test_journal_purge_archived.py.

Only the `PurgeArchived` field of IRIS's JournalSettings is ever read from
the request or sent in the PUT body — no other journal setting is touched
by this handler.
"""

from pydantic import BaseModel, ConfigDict

from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.iris_client.client import IRISClient
from app.models.iris import IRISEnvelope, JournalSettings

_JOURNAL_SETTINGS_PATH = "/v2/journal/settings"


class JournalPurgeArchivedParameters(BaseModel):
    """The ONLY parameter this operation accepts. Field name matches IRIS's
    own JournalSettings.PurgeArchived exactly, since this is sent verbatim
    as the PUT body — no translation, no other JournalSettings field is
    exposed through this operation.

    `extra="forbid"`: any other field (e.g. ArchiveName, or any other
    JournalSettings property) is REJECTED outright rather than silently
    ignored. The PUT body is, separately, always built as a hardcoded
    {"PurgeArchived": ...} literal regardless — this is defense-in-depth,
    not the only thing preventing other fields from being sent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    PurgeArchived: bool


class JournalUpdatePurgeArchivedHandler(OperationHandler):
    """Requires an IRISClient, supplied by the caller (typically a route),
    so this handler can be unit-tested with a fake/mock client instead of a
    real one. See app/dependencies.py for how a real IRISClient is normally
    obtained."""

    def __init__(self, iris_client: IRISClient):
        self._iris_client = iris_client

    def _target_value(self, request: OperationRequest) -> bool:
        params = JournalPurgeArchivedParameters.model_validate(request.parameters)
        return params.PurgeArchived

    async def _read_current_purge_archived(self) -> bool:
        raw = await self._iris_client.get(_JOURNAL_SETTINGS_PATH)
        envelope = IRISEnvelope[JournalSettings].model_validate(raw)
        return envelope.result.PurgeArchived

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Reads current state (a GET, not a mutation) to make the
        simulation informative, but NEVER calls put()."""
        target = self._target_value(request)
        current = await self._read_current_purge_archived()
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: would change PurgeArchived from {current} to {target}. "
                "No PUT request was sent."
            ),
            data={
                "original_purge_archived": current,
                "requested_purge_archived": target,
                "would_send": {"PurgeArchived": target},
            },
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        target = self._target_value(request)

        # Pre-action state capture, per this step's requirement 8 — the
        # original value is preserved in the result's `data` so a future
        # explicit rollback operation has it available. No credential or
        # JWT is ever placed in `data`.
        original = await self._read_current_purge_archived()

        put_raw = await self._iris_client.put(
            _JOURNAL_SETTINGS_PATH, json={"PurgeArchived": target}
        )
        put_envelope = IRISEnvelope[JournalSettings].model_validate(put_raw)

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"PurgeArchived updated from {original} to {target}.",
            data={
                "original_purge_archived": original,
                "requested_purge_archived": target,
                "put_response_purge_archived": put_envelope.result.PurgeArchived,
            },
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Post-action verification: a fresh GET, independent of the PUT
        response, confirming the requested value actually persisted."""
        target = execution_result.data.get("requested_purge_archived")
        actual = await self._read_current_purge_archived()

        if actual == target:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFIED,
                detail=f"Confirmed via GET: PurgeArchived is now {actual}, as requested.",
            )

        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFICATION_FAILED,
            detail=(
                f"Expected PurgeArchived={target} after the PUT, but a follow-up GET "
                f"returned {actual!r}."
            ),
        )
