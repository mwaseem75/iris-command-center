"""Structured execution tracing, inspired by OpenTelemetry's span/trace
model but deliberately minimal — no external telemetry SDK/dependency, no
database. A trace is built once per app.execution.executor.OperationExecutor
.execute() call (see app/observability/tracer.py, the only place these
models are constructed) and recorded into an in-memory store
(app/observability/store.py).

Safety: only safe, non-sensitive attributes are ever recorded here —
operation names, timestamps, durations, statuses, privilege NAMES (never
values a caller supplied), and short status/reason strings. Nothing in
this module has a field for a password, JWT, Authorization header, or any
other credential — there is nowhere to put one. The discipline of only
ever calling `Span(..., attributes={...})` with safe values lives at each
call site in app/execution/executor.py, the same way
app/routes/iris.py's `_as_http_exception` already only ever surfaces an
exception's class name, never its message or a raw response body.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpanEvent(BaseModel):
    """A single, timestamped point of interest within a span — e.g.
    "authorization denied"."""

    name: str
    timestamp: datetime = Field(default_factory=utc_now)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """One stage of the authorization -> confirmation -> execution ->
    verification pipeline. A stage that did not run (e.g. verification
    after execution already failed) is still recorded, with
    status="skipped" and a `reason` attribute, so every trace has a
    complete, consistent four-span shape regardless of where the attempt
    stopped."""

    name: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status: str  # "ok" | "error" | "skipped"
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)


class ExecutionTrace(BaseModel):
    """The full, structured record of one OperationExecutor.execute()
    call. `trace_id` is a fresh, random identifier — it is not derived
    from and never contains any session/request identifier that could be
    linked back to a credential."""

    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    operation_name: str
    start_time: datetime = Field(default_factory=utc_now)
    end_time: datetime | None = None
    duration_ms: float | None = None
    status: str | None = None  # set once, mirrors OperationResultStatus.value
    authorization_result: str | None = None
    confirmation_result: str | None = None
    execution_result: str | None = None
    verification_result: str | None = None
    spans: list[Span] = Field(default_factory=list)
