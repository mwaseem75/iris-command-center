"""Handler for journal.update_purge_archived.

Only the PurgeArchived journal setting is read from the request or sent
to IRIS (PUT /v2/journal/settings); no other journal setting is changed.
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
    """The only parameter. The PUT body is always built as
    {"PurgeArchived": ...}, and any other field is rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    PurgeArchived: bool


class JournalUpdatePurgeArchivedHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

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
        """Reads the current value (a GET) but never sends the PUT."""
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

        # Keep the original value in `data` so the change can be undone.
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
        """Re-read the setting with a fresh GET and check the new value stuck."""
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
