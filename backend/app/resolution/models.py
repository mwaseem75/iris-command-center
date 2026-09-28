"""Models for the Issue Resolution Catalog.

Each catalog entry describes one kind of issue: how it's detected and why
it matters. An entry is one of two kinds:

- Resolvable: it names the registered operation that fixes it, the steps
  the fix goes through, how the result is verified, and what the fix must
  never do.
- Detection-only: no operation; instead an `investigation` destination says
  where in the Command Center to look into it. Nothing can be run from it.

Entries are plain data; nothing here detects issues or runs operations.

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


class InvestigationDestination(_Frozen):
    """Where to look into a detection-only issue: a Command Center page
    (its view name, e.g. "tasks") and what to check there."""

    page: str
    description: str

    @model_validator(mode="after")
    def _not_empty(self) -> "InvestigationDestination":
        if not self.page.strip() or not self.description.strip():
            raise ValueError("An investigation destination needs a page and a description.")
        return self


class IssueResolution(_Frozen):
    """One catalog entry: an issue type and either its resolution (an
    operation) or, for a detection-only issue, where to investigate it."""

    issue_type: str
    title: str
    severity: IssueSeverity
    detection_evidence: tuple[DetectionEvidence, ...]
    explanation: str
    recommended_solution: str
    # Exactly one of these: `operation` (resolvable) or `investigation` (detection-only).
    operation: str | None = None
    investigation: InvestigationDestination | None = None
    # The resolution path; required for resolvable entries, empty for detection-only ones.
    parameters: tuple[ParameterBinding, ...] = ()
    prerequisites: tuple[str, ...] = ()
    workflow_steps: tuple[WorkflowStep, ...] = ()
    verification_rules: tuple[VerificationRule, ...] = ()
    safety_restrictions: tuple[str, ...] = ()
    excluded_databases: frozenset[str] = frozenset()
    # What else the issue affects (not needed to detect it), e.g. dependent namespaces.
    impact_evidence: tuple[DetectionEvidence, ...] = ()

    @computed_field
    @property
    def resolvable(self) -> bool:
        """True if a registered operation resolves this issue."""
        return self.operation is not None

    @property
    def operation_definition(self) -> OperationDefinition | None:
        return OPERATION_REGISTRY[self.operation] if self.operation is not None else None

    @computed_field
    @property
    def required_privileges(self) -> frozenset[IRISPrivilege]:
        """Any one of these is enough, as in the operation registry. Empty for
        a detection-only entry."""
        definition = self.operation_definition
        return definition.required_privileges if definition else frozenset()

    @computed_field
    @property
    def confirmation_required(self) -> bool:
        definition = self.operation_definition
        return definition.confirmation_required if definition else False

    @computed_field
    @property
    def risk_level(self) -> RiskLevel | None:
        """None for a detection-only entry (nothing is run)."""
        definition = self.operation_definition
        return definition.risk_level if definition else None

    @model_validator(mode="after")
    def _resolvable_or_detection_only(self) -> "IssueResolution":
        if (self.operation is None) == (self.investigation is None):
            raise ValueError(
                f"{self.issue_type}: needs exactly one of `operation` (resolvable) or "
                "`investigation` (detection-only)."
            )
        return self

    @model_validator(mode="after")
    def _detection_only_has_no_resolution_path(self) -> "IssueResolution":
        if self.operation is not None:
            return self
        for name in ("parameters", "workflow_steps"):
            if getattr(self, name):
                raise ValueError(f"{self.issue_type}: a detection-only entry has no operation, so no {name}.")
        if any(rule.checked_by == "operation" for rule in self.verification_rules):
            raise ValueError(f"{self.issue_type}: a detection-only entry has no operation to verify.")
        return self

    @model_validator(mode="after")
    def _operation_is_registered_and_mutating(self) -> "IssueResolution":
        if self.operation is None:
            return self
        definition = OPERATION_REGISTRY.get(self.operation)
        if definition is None:
            raise ValueError(f"{self.issue_type}: operation {self.operation!r} is not in OPERATION_REGISTRY.")
        if definition.kind is not OperationKind.MUTATING:
            raise ValueError(f"{self.issue_type}: operation {self.operation!r} doesn't change anything, so it can't resolve an issue.")
        return self

    @model_validator(mode="after")
    def _workflow_follows_the_standard_order(self) -> "IssueResolution":
        if self.operation is None:
            return self
        kinds = tuple(step.kind for step in self.workflow_steps)
        if kinds != WORKFLOW_ORDER:
            raise ValueError(
                f"{self.issue_type}: workflow steps must be {[k.value for k in WORKFLOW_ORDER]}, "
                f"got {[k.value for k in kinds]}."
            )
        return self

    @model_validator(mode="after")
    def _required_sections_not_empty(self) -> "IssueResolution":
        required = ("detection_evidence", "parameters", "verification_rules", "safety_restrictions")
        for name in required if self.operation is not None else ("detection_evidence",):
            if not getattr(self, name):
                raise ValueError(f"{self.issue_type}: {name} must not be empty.")
        return self

    @model_validator(mode="after")
    def _verification_includes_the_operation(self) -> "IssueResolution":
        if self.operation is None:
            return self
        if not any(rule.checked_by == "operation" for rule in self.verification_rules):
            raise ValueError(f"{self.issue_type}: at least one verification rule must be checked by the operation.")
        return self
