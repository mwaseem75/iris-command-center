"""Keyword-based intent matching for the AI Assistant (no LLM).

Maps a question to one of a fixed set of intents; anything else is UNKNOWN.
JOURNAL_OPERATION (a PurgeArchived change request) is only answered with a
pointer to the Copilot; nothing here changes IRIS.
"""

from enum import Enum


class Intent(str, Enum):
    SYSTEM_STATUS = "system_status"
    PROCESS_COUNT = "process_count"
    PROCESS_LIST = "process_list"
    DATABASE_STATUS = "database_status"
    WEB_APP_STATUS = "web_app_status"
    TASK_INFO = "task_info"
    JOURNAL_OPERATION = "journal_operation"
    UNKNOWN = "unknown"


def classify_intent(message: str) -> Intent:
    """Specific topics (journal, database, web app, task, process) are checked
    before the generic status fallback, so "database status" isn't treated as
    a system status question.
    """
    text = (message or "").strip().lower()
    if not text:
        return Intent.UNKNOWN

    if "purge archived" in text or "purgearchived" in text or "purge_archived" in text:
        return Intent.JOURNAL_OPERATION

    if "database" in text:
        return Intent.DATABASE_STATUS

    if "web app" in text or "webapp" in text:
        return Intent.WEB_APP_STATUS

    if "task" in text:
        return Intent.TASK_INFO

    if "process" in text:
        if "list" in text or "which" in text:
            return Intent.PROCESS_LIST
        return Intent.PROCESS_COUNT

    if "system" in text or "status" in text or "version" in text or "info" in text:
        return Intent.SYSTEM_STATUS

    return Intent.UNKNOWN
