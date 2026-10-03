"""Response models for the Command Center's own API (not IRIS's)."""

from datetime import datetime
from typing import Any, Literal

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


HealthCategoryId = Literal[
    "performance", "tasks", "databases", "security", "web-applications", "system"
]
HealthSeverity = Literal["critical", "high", "medium", "low"]
HealthCategoryStatus = Literal[
    "healthy", "warning", "critical", "partial", "unavailable", "not_assessed"
]


class HealthEvidence(BaseModel):
    source: str
    field: str
    observed_value: Any
    value_status: Literal["observed", "unknown", "not_applicable"]
    condition: str


class HealthInvestigationDestination(BaseModel):
    page: str
    description: str


class HealthFinding(BaseModel):
    id: str
    check_id: str
    category: HealthCategoryId
    severity: HealthSeverity
    title: str
    explanation: str
    evidence: list[HealthEvidence]
    recommendation: str | None
    investigation: HealthInvestigationDestination | None


class HealthRecommendation(BaseModel):
    finding_id: str
    category: HealthCategoryId
    text: str
    investigation: HealthInvestigationDestination | None


class HealthUnavailableSource(BaseModel):
    category: HealthCategoryId
    check_id: str
    source: str
    reason: str


class HealthCheckResult(BaseModel):
    """One check of a category, as the Issue Resolver's detection ran it."""

    check_id: str
    status: Literal["passed", "issue_detected", "not_assessed"]
    source: str  # where the check reads its IRIS data
    condition: str  # what makes it report an issue (from the catalog)
    evidence: list[HealthEvidence]  # what it observed, when it could read it
    reason: str | None = None  # why it couldn't be assessed


class HealthCategoryResult(BaseModel):
    id: HealthCategoryId
    name: str
    status: HealthCategoryStatus
    score: int | None
    checks_completed: int
    checks_total: int
    evidence: list[HealthEvidence]
    findings: list[HealthFinding]
    unavailable_sources: list[HealthUnavailableSource]
    checks: list[HealthCheckResult] = []


class HealthReport(BaseModel):
    generated_at: datetime
    status: Literal["healthy", "warning", "critical", "partial", "unavailable"]
    overall_score: int | None
    score_method: str
    penalty_weights: dict[HealthSeverity, int]
    categories: list[HealthCategoryResult]
    findings: list[HealthFinding]
    recommendations: list[HealthRecommendation]
    unavailable_sources: list[HealthUnavailableSource]
