"""Deterministic intent classification for the AI Operations Copilot."""

import re
from enum import Enum


class CopilotIntent(str, Enum):
    ISSUE_INVESTIGATION = "issue_investigation"
    HEALTH_STATUS = "health_status"
    READ_ONLY_QUERY = "read_only_query"
    RESOLUTION_REQUEST = "resolution_request"
    UNKNOWN = "unknown"


_RESOLUTION_PATTERNS = (
    r"\b(?:change|set|enable|disable|mount|dismount|restart|start|stop|"
    r"execute|create|delete|remove|update|purge|fix|repair|resolve)\b",
    r"\brun\s+(?:now|the\s+(?:task|operation))\b",
)
_ISSUE_PATTERNS = (
    r"\bissues?\b",
    r"\bfindings?\b",
    r"\binvestigat(?:e|ion|ing)\b",
    r"\broot\s+cause\b",
    r"\bwhy\b",
)
_HEALTH_PATTERNS = (
    r"\bhealth\b",
    r"\bhealthy\b",
    r"\bhealth\s+center\b",
)
_READ_ONLY_PATTERNS = (
    r"\bsystem\b",
    r"\bstatus\b",
    r"\bversion\b",
    r"\bprocess(?:es)?\b",
    r"\bdatabases?\b",
    r"\bstorage\b",
    r"\bweb\s*apps?\b",
    r"\bapplications?\b",
    r"\btasks?\b",
    r"\bschedul(?:e|ed|ing)\b",
    r"\bnamespace(?:s)?\b",
    r"\bjournal\b",
    r"\baudit(?:ing)?\b",
    r"\boperations?\b",
    r"\btraces?\b",
    r"\bprivileges?\b",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) is not None for pattern in patterns)


def classify_intent(message: str) -> CopilotIntent:
    """Classify a request without accessing IRIS or performing an operation."""
    text = message.strip().lower()
    if not text:
        return CopilotIntent.UNKNOWN

    if _matches_any(text, _RESOLUTION_PATTERNS):
        return CopilotIntent.RESOLUTION_REQUEST
    if _matches_any(text, _ISSUE_PATTERNS):
        return CopilotIntent.ISSUE_INVESTIGATION
    if _matches_any(text, _HEALTH_PATTERNS):
        return CopilotIntent.HEALTH_STATUS
    if _matches_any(text, _READ_ONLY_PATTERNS):
        return CopilotIntent.READ_ONLY_QUERY
    return CopilotIntent.UNKNOWN
