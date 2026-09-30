"""TraceRecorder builds the ExecutionTrace for one OperationExecutor.execute()
call. A new one is made per call, so concurrent runs never mix spans.

It records whatever attributes it's given; executor.py is responsible for
only passing safe values.
"""

import time
from datetime import datetime
from typing import Any

from app.execution.models import ResolutionLifecycleEvidence
from app.observability.models import ExecutionTrace, ResolutionContext, Span, utc_now
from app.observability.store import record_trace


class _SpanTimer:
    __slots__ = ("wall_start", "perf_start")

    def __init__(self) -> None:
        self.wall_start = utc_now()
        self.perf_start = time.perf_counter()


class TraceRecorder:
    def __init__(self, operation_name: str, resolution: ResolutionContext | None = None):
        self._trace = ExecutionTrace(operation_name=operation_name, resolution=resolution)
        self._perf_start = time.perf_counter()

    def timer(self) -> _SpanTimer:
        """Call at the start of a stage."""
        return _SpanTimer()

    @property
    def start_time(self) -> datetime:
        return self._trace.start_time

    @property
    def trace_id(self) -> str:
        return self._trace.trace_id

    def set_lifecycle(self, lifecycle: ResolutionLifecycleEvidence | None) -> None:
        self._trace.lifecycle = lifecycle

    def span(self, name: str, timer: _SpanTimer, *, status: str, **attributes: Any) -> None:
        """Record a stage that ran, timed from its timer()."""
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
        """Record a stage that didn't run, so every trace has all four spans."""
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
        """Set trace summary fields (authorization_result, confirmation_result, ...).
        Unknown names raise, since ExecutionTrace is a Pydantic model.
        """
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
