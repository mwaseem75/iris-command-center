"""AI Assistant query endpoint.

A keyword classifier (intents.py) picks the question type; read-only answers
reuse the route functions in routes/iris.py, and the one journal operation
goes through journal_operation.py. No LLM is involved, and unknown questions
get a fixed help reply.

It's a GET like the other routes; any real change still needs explicit
confirmation in the message.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.assistant.intents import Intent, classify_intent
from app.assistant.journal_operation import handle_journal_operation_message
from app.assistant.responses import (
    PRIMARY_ONLY_REPLY,
    UNKNOWN_REPLY,
    UNREACHABLE_REPLY,
    format_database_status,
    format_process_count,
    format_process_list,
    format_system_status,
    format_task_info,
    format_web_app_status,
)
from app.dependencies import get_iris_client, get_read_client
from app.iris_client.client import IRISClient
from app.models.schemas import AssistantQueryResponse
from app.routes.iris import get_databases, get_info, get_processes, get_tasks, get_web_apps

router = APIRouter(prefix="/api/iris", tags=["assistant"])


@router.get("/assistant/query", response_model=AssistantQueryResponse)
async def query_assistant(
    message: str = Query(..., min_length=1, max_length=500),
    client: IRISClient = Depends(get_read_client),
    primary: IRISClient = Depends(get_iris_client),
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
            reply = (
                await handle_journal_operation_message(message, primary)
                if client is primary
                else PRIMARY_ONLY_REPLY
            )
        else:
            reply = UNKNOWN_REPLY
    except HTTPException:
        # The route functions raise HTTPException when IRIS can't be
        # reached. Show a friendly chat reply instead of an error page.
        reply = UNREACHABLE_REPLY

    return AssistantQueryResponse(reply=reply, intent=intent.value)
