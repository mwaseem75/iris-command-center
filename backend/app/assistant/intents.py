"""Pure, read-only natural-language intent classification for the AI
Assistant. No IRIS call, no network I/O, no state — this module only maps
a free-text question to one of a small, fixed set of KNOWN intents the
assistant can actually answer using the Command Center's existing
read-only /api/iris/* routes (see app/routes/assistant.py, which is the
only caller of this module and the only place any IRIS call happens).

This is deliberately NOT an LLM or any external model call — it is a
small, fully deterministic keyword classifier, matching this step's scope
("read-only natural-language queries using the existing IRIS read APIs").
An unrecognized question maps to Intent.UNKNOWN, never a guess.
"""

from enum import Enum


class Intent(str, Enum):
    SYSTEM_STATUS = "system_status"
    PROCESS_COUNT = "process_count"
    PROCESS_LIST = "process_list"
    DATABASE_STATUS = "database_status"
    WEB_APP_STATUS = "web_app_status"
    TASK_INFO = "task_info"
    UNKNOWN = "unknown"


def classify_intent(message: str) -> Intent:
    """Order matters: more specific domain keywords (database/web app/
    task/process) are checked before the generic system/status fallback,
    so e.g. "database status" is never mistaken for a generic
    system-status question just because it also contains "status"."""
    text = (message or "").strip().lower()
    if not text:
        return Intent.UNKNOWN

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
