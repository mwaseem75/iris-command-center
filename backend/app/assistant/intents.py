"""Keyword-based intent matching for the AI Assistant (no LLM).

Maps a question to one of a fixed set of intents; anything else is UNKNOWN.
JOURNAL_OPERATION is the only one that can lead to a change, and even then
journal_operation.py runs it through the normal authorization and
confirmation flow.
"""

import re
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


_CONFIRM_WORDS = ("confirm", "confirmed", "proceed")
_TRUE_WORDS = ("true", "on", "enable", "enabled")
_FALSE_WORDS = ("false", "off", "disable", "disabled")


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def parse_purge_archived_request(message: str) -> tuple[bool | None, bool]:
    """Pull (target_value, is_confirmed) out of a PurgeArchived request.

    target_value is None unless the message clearly asks for true or false.
    is_confirmed is only True when the message says confirm/confirmed/proceed.
    """
    text = (message or "").strip().lower()

    has_true = any(_contains_word(text, word) for word in _TRUE_WORDS)
    has_false = any(_contains_word(text, word) for word in _FALSE_WORDS)
    if has_true and not has_false:
        target: bool | None = True
    elif has_false and not has_true:
        target = False
    else:
        target = None

    confirmed = any(_contains_word(text, word) for word in _CONFIRM_WORDS)
    return target, confirmed
