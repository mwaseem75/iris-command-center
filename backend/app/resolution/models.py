"""Models for the Issue Resolution Catalog.

Each catalog entry describes one kind of issue and how it's resolved: how
it's detected, why it matters, which registered operation fixes it, the
steps the fix goes through, how the result is verified, and what the fix
must never do. Entries are plain data; nothing here detects issues or runs
operations.

The operation is looked up in OPERATION_REGISTRY, so its privileges, risk
and confirmation rule come from there instead of being repeated here.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from app.authorization.operations import (
    OPERATION_REGISTRY,
    OperationDefinition,
    OperationKind,
    RiskLevel,
)
from app.authorization.privileges import IRISPrivilege


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowStepKind(str, Enum):
    """The stages every resolution goes through, in this order. The keys
    match the Resolve Issues tracker in the frontend."""

    DETECTED = "detected"
    RECOMMENDED = "recommended"
    DRY_RUN = "check"
    CONFIRMATION = "confirm"
    EXECUTION = "execute"
    VERIFICATION = "verify"
    TRACE = "trace"


# The order the steps must appear in.
WORKFLOW_ORDER: tuple[WorkflowStepKind, ...] = tuple(WorkflowStepKind)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DetectionEvidence(_Frozen):
    """One condition the detector checks, and the IRIS data it reads."""

    source: str        # e.g. "GET /v2/database-dirs"
    field: str         # e.g. "Status"
    condition: str     # what must be true for the issue to be reported
    issue_field: str | None = None  # field of the detected issue holding the live value


class ParameterBinding(_Frozen):
    """Where one operation parameter comes from: a field of the detected
    issue, or a fixed value."""

    name: str
    from_issue_field: str | None = None
    value: Any = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "ParameterBinding":
        if (self.from_issue_field is None) == (self.value is None):
            raise ValueError(f"Parameter {self.name!r} needs either from_issue_field or a fixed value.")
        return self


class WorkflowStep(_Frozen):
    kind: WorkflowStepKind
    title: str
    description: str


class VerificationRule(_Frozen):
    """A check that must pass after the operation runs."""

    source: str        # e.g. "POST /v2/database-dir/info"
    condition: str
    checked_by: str    # "operation" (the handler's verify()) or "issue_detection"


class IssueResolution(_Frozen):
    """One catalog entry: an issue type and its resolution."""

    issue_type: str
    title: str
    severity: IssueSeverity
    detection_evidence: tuple[DetectionEvidence, ...]
    explanation: str
    recommended_solution: str
    operation: str
    parameters: tuple[ParameterBinding, ...]
    prerequisites: tuple[str, ...]
    workflow_steps: tuple[WorkflowStep, ...]
    verification_rules: tuple[VerificationRule, ...]
    safety_restrictions: tuple[str, ...]
    excluded_databases: frozenset[str] = frozenset()

    @property
    def operation_definition(self) -> OperationDefinition:
        return OPERATION_REGISTRY[self.operation]

    @computed_field
    @property
    def required_privileges(self) -> frozenset[IRISPrivilege]:
        """Any one of these is enough, as in the operation registry."""
        return self.operation_definition.required_privileges

    @computed_field
    @property
    def confirmation_required(self) -> bool:
        return self.operation_definition.confirmation_required

    @computed_field
    @property
    def risk_level(self) -> RiskLevel:
        return self.operation_definition.risk_level

    @model_validator(mode="after")
    def _operation_is_registered_and_mutating(self) -> "IssueResolution":
        definition = OPERATION_REGISTRY.get(self.operation)
        if definition is None:
            raise ValueError(f"{self.issue_type}: operation {self.operation!r} is not in OPERATION_REGISTRY.")
        if definition.kind is not OperationKind.MUTATING:
            raise ValueError(f"{self.issue_type}: operation {self.operation!r} doesn't change anything, so it can't resolve an issue.")
        return self

    @model_validator(mode="after")
    def _workflow_follows_the_standard_order(self) -> "IssueResolution":
        kinds = tuple(step.kind for step in self.workflow_steps)
        if kinds != WORKFLOW_ORDER:
            raise ValueError(
                f"{self.issue_type}: workflow steps must be {[k.value for k in WORKFLOW_ORDER]}, "
                f"got {[k.value for k in kinds]}."
            )
        return self

    @model_validator(mode="after")
    def _required_sections_not_empty(self) -> "IssueResolution":
        for name in ("detection_evidence", "parameters", "verification_rules", "safety_restrictions"):
            if not getattr(self, name):
                raise ValueError(f"{self.issue_type}: {name} must not be empty.")
        return self

    @model_validator(mode="after")
    def _verification_includes_the_operation(self) -> "IssueResolution":
        if not any(rule.checked_by == "operation" for rule in self.verification_rules):
            raise ValueError(f"{self.issue_type}: at least one verification rule must be checked by the operation.")
        return self
