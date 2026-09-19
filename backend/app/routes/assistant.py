"""The AI Assistant's ONLY backend route: a read-only, natural-language
query endpoint. It never calls IRIS directly — it reuses the exact same,
already-verified route functions app/routes/iris.py exposes (get_info,
get_processes, get_databases, get_web_apps, get_tasks), calling them
in-process with the shared IRISClient, so this module holds no duplicate
IRIS-calling logic and no second copy of their error handling.

No LLM is connected. Understanding is a small, deterministic keyword
classifier (app/assistant/intents.py) — this is intentionally NOT a
general-purpose chat backend. It answers only the fixed set of read-only
questions this step defines; anything else gets a graceful, honest
fallback (app/assistant/responses.UNKNOWN_REPLY), never a guess.

GET, not POST: this endpoint performs no mutation of any kind, so it uses
the same HTTP method as every other Command Center read route, consistent
with the rest of this API surface.

No mutating IRIS call exists anywhere in this module, and no operation
from app/authorization/operations.py is ever executed here — this route
cannot trigger journal.update_purge_archived or any other operation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assistant.intents import Intent, classify_intent
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
        else:
            reply = UNKNOWN_REPLY
    except HTTPException:
        # get_info/get_processes/... already translate IRIS communication
        # failures into an HTTPException (see app/routes/iris.py's
        # _as_http_exception) when called this way. The assistant answers
        # in chat, not with an HTTP error page, so this becomes a plain,
        # non-alarming reply instead — never a raw exception or stack
        # trace, the same discipline every other view in this app follows.
        reply = UNREACHABLE_REPLY

    return AssistantQueryResponse(reply=reply, intent=intent.value)
