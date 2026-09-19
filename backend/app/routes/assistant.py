"""The AI Assistant's ONLY backend route: a natural-language query
endpoint. It never calls IRIS directly — read-only questions reuse the
exact same, already-verified route functions app/routes/iris.py exposes
(get_info, get_processes, get_databases, get_web_apps, get_tasks), and the
one supported mutating question (about journal.update_purge_archived) is
delegated entirely to app/assistant/journal_operation.py, which itself
routes through the existing authorization/execution framework — nothing
in this module holds duplicate IRIS-calling, authorization, or mutation
logic.

No LLM is connected. Understanding is a small, deterministic keyword
classifier (app/assistant/intents.py) — this is intentionally NOT a
general-purpose chat backend. It answers only the fixed set of questions
this step defines; anything else gets a graceful, honest fallback
(app/assistant/responses.UNKNOWN_REPLY), never a guess.

GET, not POST: even the journal_operation intent never mutates as a
byproduct of the HTTP method itself — every real IRIS write still requires
its own explicit, parsed confirmation (see journal_operation.py) before
the existing execution framework will proceed. This keeps the assistant on
the same HTTP method as every other Command Center route.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assistant.intents import Intent, classify_intent
from app.assistant.journal_operation import handle_journal_operation_message
from app.assistant.responses import (
    UNKNOWN_REPLY,
    UNREACHABLE_REPLY,
    format_database_status,
    format_process_count,
    format_process_list,
    format_system_status,
    format_task_info,
    format_web_app_status,
)
from app.dependencies import get_iris_client
from app.iris_client.client import IRISClient
from app.models.schemas import AssistantQueryResponse
from app.routes.iris import get_databases, get_info, get_processes, get_tasks, get_web_apps

router = APIRouter(prefix="/api/iris", tags=["assistant"])


@router.get("/assistant/query", response_model=AssistantQueryResponse)
async def query_assistant(
    message: str = Query(..., min_length=1, max_length=500),
    client: IRISClient = Depends(get_iris_client),
) -> AssistantQueryResponse:
    intent = classify_intent(message)

    try:
        if intent is Intent.SYSTEM_STATUS:
            envelope = await get_info(client)
            reply = format_system_status(envelope.result)
        elif intent is Intent.PROCESS_COUNT:
            envelope = await get_processes(client)
            reply = format_process_count(envelope.result)
        elif intent is Intent.PROCESS_LIST:
            envelope = await get_processes(client)
            reply = format_process_list(envelope.result)
        elif intent is Intent.DATABASE_STATUS:
            envelope = await get_databases(client)
            reply = format_database_status(envelope.result)
        elif intent is Intent.WEB_APP_STATUS:
            envelope = await get_web_apps(client)
            reply = format_web_app_status(envelope.result)
        elif intent is Intent.TASK_INFO:
            envelope = await get_tasks(client)
            reply = format_task_info(envelope.result)
        elif intent is Intent.JOURNAL_OPERATION:
            reply = await handle_journal_operation_message(message, client)
        else:
            reply = UNKNOWN_REPLY
    except HTTPException:
        # get_info/get_processes/get_caller_privileges/... already translate
        # IRIS communication failures into an HTTPException (see
        # app/routes/iris.py's _as_http_exception and
        # app/dependencies.py's get_caller_privileges) when called this
        # way. The assistant answers in chat, not with an HTTP error page,
        # so this becomes a plain, non-alarming reply instead — never a raw
        # exception or stack trace, the same discipline every other view in
        # this app follows.
        reply = UNREACHABLE_REPLY

    return AssistantQueryResponse(reply=reply, intent=intent.value)
