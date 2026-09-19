"""Pure natural-language intent classification for the AI Assistant. No
IRIS call, no network I/O, no state — this module only maps a free-text
question to one of a small, fixed set of KNOWN intents the assistant can
actually answer using the Command Center's existing /api/iris/* routes
(see app/routes/assistant.py, which is the only caller of this module and
the only place any IRIS call happens).

This is deliberately NOT an LLM or any external model call — it is a
small, fully deterministic keyword classifier. An unrecognized question
maps to Intent.UNKNOWN, never a guess.

JOURNAL_OPERATION is the one non-read-only intent: it identifies that the
caller is asking about the existing journal.update_purge_archived
operation. Recognizing this intent NEVER executes anything by itself —
see app/assistant/journal_operation.py, which routes any actual execution
through the existing authorization/execution framework, gated by explicit
confirmation parsed by `parse_purge_archived_request` below.
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
    """Order matters: the journal/PurgeArchived operation and other
    specific domain keywords (database/web app/task/process) are checked
    before the generic system/status fallback, so e.g. "database status"
    is never mistaken for a generic system-status question just because it
    also contains "status"."""
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
    """Extracts (target_value, is_confirmed) from a natural-language
    message about the journal.update_purge_archived operation.

    `target_value` is None whenever the message doesn't contain an
    unambiguous true/false request (e.g. both or neither of the true/false
    word sets are present) — this module must never guess a mutation
    value.

    `is_confirmed` is True ONLY when the message contains an explicit
    confirmation word ("confirm"/"confirmed"/"proceed"). This is the ONLY
    way this module ever signals confirmation to the caller — there is no
    default-confirmed path and no way to skip this check.
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
