"""Response models for the Command Center's own API (not IRIS's)."""

from pydantic import BaseModel

from app.authorization.operations import OperationKind, RiskLevel
from app.capabilities import CapabilityEntry
from app.observability.models import ExecutionTrace


class HealthResponse(BaseModel):
    status: str


class OperationSummary(BaseModel):
    """Public view of one OperationDefinition, built straight from
    OPERATION_REGISTRY.
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
    """The assistant's answer to one question. `intent` is only there for tests
    and debugging; the UI just shows `reply`.
    """

    reply: str
    intent: str


class CapabilityViewEntry(CapabilityEntry):
    """A CapabilityEntry plus `available`, which is worked out on each request
    by checking whether the route is actually registered.
    """

    available: bool


class CapabilityListResponse(BaseModel):
    capabilities: list[CapabilityViewEntry]


class TraceListResponse(BaseModel):
    """The in-memory trace list. Each trace already includes its spans, so
    there's no separate detail endpoint.
    """

    traces: list[ExecutionTrace]
