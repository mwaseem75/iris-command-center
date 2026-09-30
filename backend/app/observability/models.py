"""Execution trace models, loosely following OpenTelemetry (trace, spans,
events), without any telemetry SDK.

One trace is built per OperationExecutor.execute() call (by tracer.py) and
kept in store.py. Only safe values are recorded: operation names, times,
durations, statuses, privilege names and short reasons. There's no field
for passwords, tokens or headers.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.execution.models import ResolutionLifecycleEvidence
from app.resolution.identity import IssueResourceReference


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpanEvent(BaseModel):
    """A timestamped event inside a span, e.g. "authorization denied"."""

    name: str
    timestamp: datetime = Field(default_factory=utc_now)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """One stage: authorization, confirmation, execution or verification.

    Stages that didn't run are still recorded as status="skipped" with a
    `reason`, so every trace has the same four spans.
    """

    name: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status: str  # "ok" | "error" | "skipped"
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)


class ResolutionContext(BaseModel):
    """Set when the operation was started from an Issue Resolution workflow.
    The title, severity and stable resource identity come from the catalog and
    its operation parameters, never from client-supplied labels."""

    issue_type: str
    issue_title: str
    severity: str
    resource: str | None = None  # e.g. the database directory being fixed
    issue_id: str | None = None
    resource_reference: IssueResourceReference | None = None


class ExecutionTrace(BaseModel):
    """Everything recorded for one OperationExecutor.execute() call. `trace_id`
    is random and not tied to any session. Resolution traces may include the
    same optional lifecycle evidence returned in OperationResult.
    """

    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    operation_name: str
    start_time: datetime = Field(default_factory=utc_now)
    end_time: datetime | None = None
    duration_ms: float | None = None
    status: str | None = None  # same as OperationResultStatus.value
    authorization_result: str | None = None
    confirmation_result: str | None = None
    execution_result: str | None = None
    verification_result: str | None = None
    resolution: ResolutionContext | None = None  # None for normal operations
    lifecycle: ResolutionLifecycleEvidence | None = None
    spans: list[Span] = Field(default_factory=list)
