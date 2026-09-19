"""TraceRecorder: the ONLY place ExecutionTrace/Span objects are built.
Used exclusively by app/execution/executor.py, one instance per
OperationExecutor.execute() call — instances are never shared across
calls, so concurrent executions never interleave spans into the same
trace.

This class performs no filtering of its own: it records exactly the
attributes its caller passes it. The discipline of only ever passing safe,
non-sensitive values (operation names, statuses, privilege names, short
reason strings — never a credential, token, or Authorization header) lives
entirely in app/execution/executor.py, the single call site. See
app/observability/models.py's module docstring for the full safety
rationale.
"""

import time
from typing import Any

from app.observability.models import ExecutionTrace, Span, utc_now
from app.observability.store import record_trace


class _SpanTimer:
    __slots__ = ("wall_start", "perf_start")

    def __init__(self) -> None:
        self.wall_start = utc_now()
        self.perf_start = time.perf_counter()


class TraceRecorder:
    def __init__(self, operation_name: str):
        self._trace = ExecutionTrace(operation_name=operation_name)
        self._perf_start = time.perf_counter()

    def timer(self) -> _SpanTimer:
        """Call at the START of a stage, before the work it will time."""
        return _SpanTimer()

    def span(self, name: str, timer: _SpanTimer, *, status: str, **attributes: Any) -> None:
        """Close out a stage that actually ran, using the timer captured
        at its start."""
        end = utc_now()
        duration_ms = (time.perf_counter() - timer.perf_start) * 1000
        self._trace.spans.append(
            Span(
                name=name,
                start_time=timer.wall_start,
                end_time=end,
                duration_ms=duration_ms,
                status=status,
                attributes=attributes,
            )
        )

    def skip(self, name: str, reason: str) -> None:
        """Record a stage that never ran — keeps every trace's spans list
        a complete, consistent four-stage shape regardless of where an
        attempt actually stopped."""
        now = utc_now()
        self._trace.spans.append(
            Span(
                name=name,
                start_time=now,
                end_time=now,
                duration_ms=0.0,
                status="skipped",
                attributes={"reason": reason},
            )
        )

    def set_result(self, **fields: str | None) -> None:
        """Set one or more of the trace's summary result fields
        (authorization_result/confirmation_result/execution_result/
        verification_result) — field names are validated by ExecutionTrace
        itself (an unknown kwarg raises, same as any Pydantic model)."""
        for key, value in fields.items():
            if not hasattr(self._trace, key):
                raise AttributeError(f"ExecutionTrace has no field {key!r}")
            setattr(self._trace, key, value)

    def finish(self, status: str) -> ExecutionTrace:
        self._trace.status = status
        self._trace.end_time = utc_now()
        self._trace.duration_ms = (time.perf_counter() - self._perf_start) * 1000
        record_trace(self._trace)
        return self._trace
