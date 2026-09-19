"""Pydantic response models for the Command Center backend's own API.

These describe the Command Center's own responses, not IRIS's.
"""

from pydantic import BaseModel

from app.authorization.operations import OperationKind, RiskLevel
from app.capabilities import CapabilityEntry
from app.observability.models import ExecutionTrace


class HealthResponse(BaseModel):
    status: str


class OperationSummary(BaseModel):
    """Public, read-only view of one app.authorization.operations.OperationDefinition.

    This is the ONLY place operation metadata (name, description, required
    privileges, confirmation requirement) is serialized for API consumers —
    it is read directly off the existing OPERATION_REGISTRY, never
    duplicated or re-typed by hand.
    """

    name: str
    description: str
    kind: OperationKind
    required_privileges: list[str]
    risk_level: RiskLevel
    confirmation_required: bool


class OperationsListResponse(BaseModel):
    operations: list[OperationSummary]


class AssistantQueryResponse(BaseModel):
    """The AI Assistant's reply to one read-only natural-language question.

    `intent` is the classified intent name (see
    app.assistant.intents.Intent) — informational only, useful for tests
    and debugging; the frontend only displays `reply`.
    """

    reply: str
    intent: str


class CapabilityViewEntry(CapabilityEntry):
    """One app.capabilities.CapabilityEntry plus `available` — whether this
    backend currently exposes a real, registered route for it. `available`
    is computed fresh on every request by app/routes/capabilities.py
    checking this backend's own actual route table; it is never a
    hand-maintained boolean stored alongside the rest of the entry."""

    available: bool


class CapabilityListResponse(BaseModel):
    capabilities: list[CapabilityViewEntry]


class TraceListResponse(BaseModel):
    """Read-only view of the in-memory execution trace store
    (app/observability/store.py). Each ExecutionTrace already includes its
    full spans list — there is deliberately no separate "detail" endpoint;
    the frontend's expandable trace view renders straight from this."""

    traces: list[ExecutionTrace]
