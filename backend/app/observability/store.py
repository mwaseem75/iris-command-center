"""In-memory store for execution traces (lost on restart unless IRIS
persistence is on).

Keeps the newest _MAX_TRACES. GET /api/iris/observability/traces reads only
from here; list_traces()/get_trace() never call IRIS.

If app/main.py registers a persister (only when persist_traces_to_iris is
on), record_trace() also starts a background write to IRIS. It isn't
awaited, so it can't slow down or fail the request, and any error from it
is swallowed.
"""

import asyncio
from collections import deque
from typing import Protocol

from app.observability.models import ExecutionTrace

_MAX_TRACES = 200

_traces: deque[ExecutionTrace] = deque(maxlen=_MAX_TRACES)


class _TracePersister(Protocol):
    """What a persister must provide. IRISTraceWriter fits it, and this way we
    don't import it (or the optional `iris` package) here.
    """

    def persist_sync(self, trace: ExecutionTrace) -> None: ...


_persister: _TracePersister | None = None

# Keep references to background tasks so they aren't garbage-collected
# before finishing; each one removes itself when done.
_pending_persist_tasks: set[asyncio.Task] = set()


def set_trace_persister(persister: _TracePersister | None) -> None:
    """Called from app/main.py. None turns background persistence off."""
    global _persister
    _persister = persister


async def _persist_in_background(persister: _TracePersister, trace: ExecutionTrace) -> None:
    try:
        await asyncio.get_running_loop().run_in_executor(None, persister.persist_sync, trace)
    except Exception:  # noqa: BLE001 - must never propagate into record_trace()'s caller
        pass


def record_trace(trace: ExecutionTrace) -> None:
    _traces.appendleft(trace)  # newest first, like list_traces()

    if _persister is None:
        return
    try:
        task = asyncio.get_running_loop().create_task(_persist_in_background(_persister, trace))
    except RuntimeError:
        # No running event loop (sync code or tests), so nothing to schedule.
        # The in-memory record is already done.
        return
    _pending_persist_tasks.add(task)
    task.add_done_callback(_pending_persist_tasks.discard)


def hydrate_traces(traces: list[ExecutionTrace]) -> int:
    """Startup only: add traces loaded from IRIS (newest first) after the ones
    already in memory, since they're older.

    Doesn't re-save them, skips duplicate trace_ids, and stops at _MAX_TRACES
    so it never pushes out newer entries. Returns how many were added.
    """
    present = {trace.trace_id for trace in _traces}
    added = 0
    for trace in traces:
        if len(_traces) >= _MAX_TRACES:
            break
        if trace.trace_id in present:
            continue
        _traces.append(trace)
        present.add(trace.trace_id)
        added += 1
    return added


def list_traces() -> list[ExecutionTrace]:
    return list(_traces)


def get_trace(trace_id: str) -> ExecutionTrace | None:
    for trace in _traces:
        if trace.trace_id == trace_id:
            return trace
    return None


def clear_traces() -> None:
    """For tests only."""
    _traces.clear()
