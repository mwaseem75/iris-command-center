"""Wires the AI Assistant to the EXISTING journal.update_purge_archived
operation, entirely through the already-existing authorization/execution
framework (app/execution/executor.py, app/execution/journal_purge_archived_handler.py,
app/authorization/service.py). This module makes no IRIS call of its own
outside that framework, holds no duplicate authorization/confirmation
logic, and never mutates anything directly — it only builds the same
OperationRequest/ExecutionContext the existing
POST /api/iris/journal/purge-archived route already builds (see
app/routes/journal.py), and turns the resulting OperationResult into a
short chat reply.

There is no bypass, "force", or default-confirmed path anywhere in this
module: `confirmation_received` is set ONLY from
app.assistant.intents.parse_purge_archived_request's explicit-confirmation
parsing, and the underlying ExecutionContext model itself has no bypass
field to set even if this module wanted one (see
app/execution/models.py:ExecutionContext's docstring).
"""

from app.assistant.intents import parse_purge_archived_request
from app.authorization.operations import get_operation
from app.dependencies import get_caller_privileges
from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import ExecutionContext, OperationRequest, OperationResultStatus
from app.iris_client.client import IRISClient

JOURNAL_OPERATION_NAME = "journal.update_purge_archived"


def _required_privileges_text() -> str:
    operation = get_operation(JOURNAL_OPERATION_NAME)
    assert operation is not None  # registered at import time — see operations.py
    return " or ".join(sorted(p.value for p in operation.required_privileges))


async def handle_journal_operation_message(message: str, client: IRISClient) -> str:
    operation = get_operation(JOURNAL_OPERATION_NAME)
    assert operation is not None  # registered at import time — see operations.py

    target, confirmed = parse_purge_archived_request(message)
    privileges_text = _required_privileges_text()

    if target is None:
        # Pure information request — no IRIS call, no authorization check;
        # this is exactly the operation's own registry metadata, the same
        # data GET /api/iris/operations already exposes.
        return (
            f"{operation.description} Required privilege: {privileges_text}. "
            "This is a mutating operation and always requires explicit confirmation "
            "before it runs — nothing is changed by asking about it. To proceed, tell "
            'me the value and confirm in the same message, e.g. "confirm purge '
            'archived true" or "confirm purge archived false".'
        )

    # A concrete target was given (with or without confirmation) — ALWAYS
    # routed through the existing authorization/execution framework, which
    # decides authorization and confirmation-gating itself; this module
    # never pre-empts or duplicates that decision.
    caller_privileges = await get_caller_privileges(client)
    executor = OperationExecutor(
        {JOURNAL_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)}
    )
    request = OperationRequest(
        operation_name=JOURNAL_OPERATION_NAME,
        parameters={"PurgeArchived": target},
    )
    context = ExecutionContext(
        available_privileges=caller_privileges,
        confirmation_received=confirmed,
        dry_run=False,
    )
    result = await executor.execute(request, context)

    target_word = str(target).lower()

    if result.status is OperationResultStatus.UNAUTHORIZED:
        return f"I can't do that: {result.detail}"

    if result.status is OperationResultStatus.CONFIRMATION_REQUIRED:
        return (
            f"You asked to set PurgeArchived to {target_word}. {result.detail} Nothing "
            f'has been changed. To proceed, reply: "confirm purge archived {target_word}".'
        )

    if result.status is OperationResultStatus.SUCCESS:
        detail = result.handler_result.detail if result.handler_result else result.detail
        return f"Done. {detail}"

    if result.status is OperationResultStatus.VERIFICATION_FAILED:
        return f"The change was sent, but I couldn't confirm it took effect: {result.detail}"

    if result.status is OperationResultStatus.EXECUTION_FAILED:
        return f"I couldn't complete that change: {result.detail}"

    # UNKNOWN_OPERATION / NO_HANDLER — not expected for this fixed,
    # always-registered operation, but never fabricate a nicer message.
    return result.detail
