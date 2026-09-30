"""Copilot lifecycle traces, recorded with the existing TraceRecorder and
trace store (app/observability): no separate logging system.

A Copilot change request produces two ordinary ExecutionTraces, one span per
lifecycle stage:
- "copilot.plan" (POST /plan, change requests only): requested, classified,
  issue_detected, plan_created, confirmation_required, or plan_rejected.
- "copilot.execute" (POST /execute): requested, confirmation_received,
  authorized, issue_detected, executing, executed, verification, resolved, or
  a failure stage named by its CopilotFailure code (the same code the API
  returns in CopilotExecutionResult.failure).

Trace ids only link these traces to each other and to the executor's own
trace; nothing reads them to make a decision. Attributes are limited to the
keys and value types below, so user text and secrets can't be recorded.
"""

from enum import Enum

from app.models.copilot import CopilotFailure
from app.observability.tracer import TraceRecorder


class CopilotStage(str, Enum):
    REQUESTED = "requested"
    CLASSIFIED = "classified"
    ISSUE_DETECTED = "issue_detected"
    PLAN_CREATED = "plan_created"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_RECEIVED = "confirmation_received"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFICATION = "verification"
    RESOLVED = "resolved"
    # Failures are recorded with CopilotFailure (app/models/copilot.py): the
    # same codes the API returns in CopilotExecutionResult.failure.


_ALLOWED_ATTRIBUTES = frozenset({
    "confirmation_required", "confirmed", "handler_verification", "intent", "issue_cleared",
    "issue_id", "issue_type", "issues_detected", "message_length", "operation",
    "operation_status", "operation_trace_id", "plan_trace_id", "reason", "setting_matches",
    "target", "target_kind",
})
_MAX_TEXT = 160


def _safe(attributes: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in attributes.items():
        if key not in _ALLOWED_ATTRIBUTES:
            raise ValueError(f"Trace attribute {key!r} is not allowed.")
        if value is None:
            continue
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, str):
            value = value[:_MAX_TEXT]
        elif not isinstance(value, (bool, int, float)):
            raise ValueError(f"Trace attribute {key!r} must be a string, number or boolean.")
        safe[key] = value
    return safe


class CopilotTrace:
    """One Copilot lifecycle trace; recorded into the store by finish()."""

    def __init__(self, name: str):
        self._recorder = TraceRecorder(name)
        self._timer = self._recorder.timer()
        self.failure: CopilotFailure | None = None

    @property
    def trace_id(self) -> str:
        return self._recorder.trace_id

    def stage(self, stage: CopilotStage, *, error: bool = False, **attributes: object) -> None:
        """A lifecycle stage; `error` marks a stage that didn't hold (e.g. no
        matching issue detected while planning) without being the failure."""
        # Each span covers the time since the previous stage.
        self._recorder.span(
            stage.value, self._timer, status="error" if error else "ok", **_safe(attributes)
        )
        self._timer = self._recorder.timer()

    def fail(self, failure: CopilotFailure, **attributes: object) -> None:
        """Record the failure; the trace's status becomes its code."""
        self._recorder.span(failure.value, self._timer, status="error", **_safe(attributes))
        self._timer = self._recorder.timer()
        self.failure = failure

    def set_result(self, **fields: str | None) -> None:
        """authorization_result / confirmation_result / execution_result /
        verification_result on the trace, as the executor's traces have."""
        self._recorder.set_result(**fields)

    def finish(self, success: CopilotStage) -> None:
        self._recorder.finish((self.failure or success).value)
