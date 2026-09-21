"""In-memory, process-local store for execution traces — no database, no
external telemetry dependency, per this step's explicit scope. Traces are
lost on process restart, which is an accepted, deliberate limitation, not
an oversight.

Capped at `_MAX_TRACES` (newest evicts oldest) so a long-running process
can never grow this without bound — this project's other explicit safety
requirements (no traced field ever holding a credential — see
app/observability/models.py) already keep every individual trace small
and non-sensitive.

This module remains the ONLY thing GET /api/iris/observability/traces
reads from (see app/routes/observability.py) — that is unchanged by the
optional IRIS persistence below. `list_traces()`/`get_trace()` never call
IRIS and never will, by design of this feature.

Optional IRIS persistence (app/observability/iris_trace_writer.py): off by
default (`_persister` starts `None`, and nothing in this project calls
`set_trace_persister()` except app/main.py's lifespan, and only when
Settings.persist_traces_to_iris is True). When a persister IS registered,
record_trace() additionally schedules a best-effort, fire-and-forget
background write — never awaited inline, so it can never add latency or a
new failure mode to whichever request happens to trigger it. Exceptions
from that background write are swallowed (IRISTraceWriter.persist_sync()
already swallows its own; the wrapper here is defense-in-depth, the same
layered-safety style already used by app/execution/executor.py's own
try/except around handler calls).
"""

import asyncio
from collections import deque
from typing import Protocol

from app.observability.models import ExecutionTrace

_MAX_TRACES = 200

_traces: deque[ExecutionTrace] = deque(maxlen=_MAX_TRACES)


class _TracePersister(Protocol):
    """Structural type for the optional persister — satisfied by
    IRISTraceWriter without this module needing to import it (and,
    therefore, without needing the optional `iris` dependency at all)."""

    def persist_sync(self, trace: ExecutionTrace) -> None: ...


_persister: _TracePersister | None = None

# Strong references to in-flight background persistence tasks. asyncio does
# not keep a task alive on its own once nothing else references it — an
# unreferenced task can be garbage-collected before it completes. Each task
# removes itself from this set via its done-callback once finished.
_pending_persist_tasks: set[asyncio.Task] = set()


def set_trace_persister(persister: _TracePersister | None) -> None:
    """Called only from app/main.py's lifespan. `None` (the default)
    disables background persistence entirely — record_trace() then behaves
    exactly as it did before this feature existed."""
    global _persister
    _persister = persister


async def _persist_in_background(persister: _TracePersister, trace: ExecutionTrace) -> None:
    try:
        await asyncio.get_running_loop().run_in_executor(None, persister.persist_sync, trace)
    except Exception:  # noqa: BLE001 - must never propagate into record_trace()'s caller
        pass


def record_trace(trace: ExecutionTrace) -> None:
    _traces.appendleft(trace)  # newest first, matching list_traces()'s order

    if _persister is None:
        return
    try:
        task = asyncio.get_running_loop().create_task(_persist_in_background(_persister, trace))
    except RuntimeError:
        # No running event loop (e.g. called from synchronous code/tests
        # outside asyncio) — nothing to schedule onto. The in-memory record
        # above has already happened either way.
        return
    _pending_persist_tasks.add(task)
    task.add_done_callback(_pending_persist_tasks.discard)


def list_traces() -> list[ExecutionTrace]:
    return list(_traces)


def get_trace(trace_id: str) -> ExecutionTrace | None:
    for trace in _traces:
        if trace.trace_id == trace_id:
            return trace
    return None


def clear_traces() -> None:
    """Test-only helper — production code never needs to clear the store;
    it self-manages via the deque's maxlen."""
    _traces.clear()
