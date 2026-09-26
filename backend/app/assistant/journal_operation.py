"""Lets the AI Assistant run journal.update_purge_archived.

It builds the same request the /api/iris/journal/purge-archived route does
and hands it to the normal executor, so authorization, confirmation and
verification all apply. Confirmation only comes from an explicit
"confirm"/"proceed" in the message.
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
    assert operation is not None  # registered in operations.py
    return " or ".join(sorted(p.value for p in operation.required_privileges))


async def handle_journal_operation_message(message: str, client: IRISClient) -> str:
    operation = get_operation(JOURNAL_OPERATION_NAME)
    assert operation is not None  # registered in operations.py

    target, confirmed = parse_purge_archived_request(message)
    privileges_text = _required_privileges_text()

    if target is None:
        # Just describing the operation; no IRIS call needed.
        return (
            f"{operation.description} Required privilege: {privileges_text}. "
            "This is a mutating operation and always requires explicit confirmation "
            "before it runs — nothing is changed by asking about it. To proceed, tell "
            'me the value and confirm in the same message, e.g. "confirm purge '
            'archived true" or "confirm purge archived false".'
        )

    # A target value was given, so let the executor decide
    # (authorization and confirmation happen there).
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

    # Shouldn't happen for this operation, but report it as-is.
    return result.detail
