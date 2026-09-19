"""In-memory, process-local store for execution traces — no database, no
external telemetry dependency, per this step's explicit scope. Traces are
lost on process restart, which is an accepted, deliberate limitation, not
an oversight.

Capped at `_MAX_TRACES` (newest evicts oldest) so a long-running process
can never grow this without bound — this project's other explicit safety
requirements (no traced field ever holding a credential — see
app/observability/models.py) already keep every individual trace small
and non-sensitive.
"""

from collections import deque

from app.observability.models import ExecutionTrace

_MAX_TRACES = 200

_traces: deque[ExecutionTrace] = deque(maxlen=_MAX_TRACES)


def record_trace(trace: ExecutionTrace) -> None:
    _traces.appendleft(trace)  # newest first, matching list_traces()'s order


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
