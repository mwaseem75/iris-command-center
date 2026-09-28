"""IRIS's messages.log (the console log), read-only.

IRIS's REST API has no endpoint for it, so the tail of the file is read
inside IRIS through Embedded Python, over the same Native API connection as
the host diagnostics (see EmbeddedPythonDiagnostics.read_messages_log_sync).
The path is fixed: <manager directory>/messages.log; nothing from a request
decides what is read.

Each entry starts with a line like

    09/28/26-01:46:19:123 (1234) 0 [Utility.Event] Journal switched

(timestamp as IRIS writes it, PID, severity 0-3, [source], message). Lines
that don't start that way continue the previous entry's message. Only the
last TAIL_BYTES of the file are read, so the oldest entries of a large log
aren't shown (`truncated`).
"""

from __future__ import annotations

import re

from pydantic import BaseModel

TAIL_BYTES = 1_048_576  # read at most the last 1 MiB
MAX_ENTRIES = 5000      # and return at most this many (newest)
LOG_FILE = "messages.log"

LEVELS = {0: "Info", 1: "Warning", 2: "Severe", 3: "Fatal"}

_ENTRY = re.compile(
    r"^(?P<timestamp>\d{2}/\d{2}/\d{2}-\d{2}:\d{2}:\d{2}:\d{3}) "
    r"\((?P<pid>\d+)\) "
    r"(?P<level>[0-3])"
    r"(?: \[(?P<source>[^\]]*)\])?"
    r" ?(?P<message>.*)$"
)


class MessageLogEntry(BaseModel):
    timestamp: str  # as IRIS writes it (MM/DD/YY-HH:MM:SS:mmm, no timezone)
    pid: int
    level: int
    level_name: str
    source: str | None
    message: str


class MessageLog(BaseModel):
    path: str
    size_bytes: int
    read_bytes: int
    truncated: bool  # True when older entries weren't read (file larger than TAIL_BYTES or entry cap)
    entries: list[MessageLogEntry]  # newest first
    duration_ms: float


def parse_messages_log(text: str) -> tuple[list[MessageLogEntry], bool]:
    """(entries newest first, capped), whether entries were dropped by the cap.

    Lines before the first full entry (a fragment cut off by the tail read)
    are skipped rather than turned into an entry with made-up fields.
    """
    entries: list[MessageLogEntry] = []
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            level = int(match["level"])
            entries.append(MessageLogEntry(
                timestamp=match["timestamp"],
                pid=int(match["pid"]),
                level=level,
                level_name=LEVELS[level],
                source=match["source"],
                message=match["message"],
            ))
        elif entries:
            last = entries[-1]
            entries[-1] = last.model_copy(update={"message": f"{last.message}\n{line}"})
    entries.reverse()
    capped = len(entries) > MAX_ENTRIES
    return entries[:MAX_ENTRIES], capped
