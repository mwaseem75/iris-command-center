"""Bounded operational context returned to the AI Operations Copilot."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.authorization.operations import RiskLevel
from app.copilot.intents import CopilotIntent


class CopilotInfoContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product: str | None = None
    server_version: str | None = None
    system_mode: str | None = None
    api_version: int | None = None


class CopilotDatabaseContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: str | None = None
    directory: str | None = None


class CopilotProcessContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pid: int
    username: str | None = None
    namespace: str | None = None
    routine: str | None = None
    state: str | None = None
    cpu_time: int | None = None  # cumulative, in ms, as IRIS reports it
    commands: int | None = None
    globals: int | None = None
    elapsed_time: str | None = None


class CopilotWebAppContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    namespace: str | None = None
    enabled: bool
    app_type: str | None = None


class CopilotTaskContext(BaseModel):
    """One task from the existing task overview (GET /v2/tasks plus each
    task's /v2/task/info), with schedule and run-as from GET /v2/task. Fields
    are None when their IRIS read failed; schedule values are IRIS's own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    name: str
    namespace: str | None = None
    type: str | None = None
    # From /v2/task/info (the list's own Suspended flag is unreliable).
    state: Literal["Running", "Not Running", "Suspended"] | None = None
    suspended: bool | None = None
    error: str | None = None
    last_finished: str | None = None
    next_scheduled: str | None = None
    # From GET /v2/task (None if that read failed).
    run_as_user: str | None = None
    time_period: str | None = None
    time_period_every: str | None = None
    daily_frequency: str | None = None
    daily_start_time: str | None = None
    suspend_on_error: bool | None = None


class CopilotIssueContext(BaseModel):
    """An active Issue Resolver finding; no identifiers, parameters or paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    title: str | None = None
    severity: str | None = None
    resource_type: str
    resource_name: str
    readiness: str
    explanation: str | None = None
    resolvable: bool
    # Informational only; Copilot planning never reads it.
    recommended_operation: str | None = None


class CopilotOperationalContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    info: CopilotInfoContext | None = None
    databases: list[CopilotDatabaseContext]
    databases_total: int | None = None
    databases_by_status: dict[str, int] = {}  # over every database
    processes: list[CopilotProcessContext]
    processes_total: int | None = None
    # Summaries over every process from the same /v2/processes read.
    processes_by_state: dict[str, int] = {}
    processes_by_namespace: dict[str, int] = {}
    processes_top_cpu: list[CopilotProcessContext] = []
    # The process a question names by PID, if IRIS reported it.
    process_focus: CopilotProcessContext | None = None
    web_apps: list[CopilotWebAppContext]
    web_apps_total: int | None = None
    # Over every web application, from the same /v2/web-apps read.
    web_apps_by_state: dict[str, int] = {}  # "Enabled" / "Disabled"
    web_apps_by_namespace: dict[str, int] = {}
    web_apps_by_type: dict[str, int] = {}
    web_apps_disabled: list[str] = []  # names, at most 10
    tasks: list[CopilotTaskContext]
    tasks_total: int | None = None
    issues: list[CopilotIssueContext] = []
    issues_total: int | None = None
    issue_checks_unavailable: list[str] = []
    unavailable: list[str]


class CopilotAIRequest(BaseModel):
    """Structured input passed to a reasoning provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(..., min_length=1, max_length=500)
    intent: CopilotIntent
    context: CopilotOperationalContext


class CopilotAIOutput(BaseModel):
    """Provider output contains descriptive text only, never executable tools."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(..., min_length=1, max_length=1000)
    observations: list[str] = Field(default_factory=list, max_length=8)
    proposed_action: str | None = Field(default=None, max_length=300)
    requires_confirmation: bool = False


class CopilotAskResponse(CopilotAIOutput):
    intent: CopilotIntent


class CopilotOperation(str, Enum):
    JOURNAL_UPDATE_PURGE_ARCHIVED = "journal.update_purge_archived"
    DATABASE_MOUNT = "database.mount"
    WEB_APP_SET_ENABLED = "web_app.set_enabled"


class CopilotTargetKind(str, Enum):
    JOURNAL_SETTINGS = "journal_settings"
    DATABASE = "database"
    WEB_APP = "web_app"


class CopilotOperationTarget(BaseModel):
    """The journal settings, or a resource identified by a detected issue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: CopilotTargetKind
    identifier: str = Field(..., min_length=1, max_length=256)
    issue_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _identity_matches_kind(self) -> "CopilotOperationTarget":
        if self.kind is CopilotTargetKind.JOURNAL_SETTINGS:
            if self.identifier != "journal-settings" or self.issue_id is not None:
                raise ValueError("The journal settings target is fixed.")
        elif self.issue_id is None:
            raise ValueError("A resource target must reference a detected issue.")
        return self


class CopilotOperationParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    PurgeArchived: StrictBool


class CopilotDatabaseMountParameters(BaseModel):
    """database.mount parameters, always built from the detected issue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str = Field(..., min_length=1, max_length=260)
    ReadOnly: StrictBool = False

    @field_validator("ReadOnly")
    @classmethod
    def _read_write_only(cls, value: bool) -> bool:
        if value:
            raise ValueError("Copilot only mounts databases read-write.")
        return value


class CopilotWebAppDisableParameters(BaseModel):
    """web_app.set_enabled parameters, always built from the detected issue.
    Copilot can only disable a web application."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str = Field(..., min_length=2, max_length=256, pattern=r"^/[^\x00-\x1f]*$")
    Enabled: StrictBool = False

    @field_validator("Enabled")
    @classmethod
    def _disable_only(cls, value: bool) -> bool:
        if value:
            raise ValueError("Copilot can only disable web applications.")
        return value


class CopilotOperationPlan(BaseModel):
    """Validated, descriptive plan; it is not authorization or execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CopilotOperation
    target: CopilotOperationTarget
    parameters: (
        CopilotOperationParameters | CopilotDatabaseMountParameters | CopilotWebAppDisableParameters
    )
    reason: str = Field(..., min_length=1, max_length=300)
    requires_confirmation: StrictBool
    # The "copilot.plan" trace. Informational only: it links the execute
    # trace to the plan trace and is never used to decide anything.
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @model_validator(mode="after")
    def _shape_matches_operation(self) -> "CopilotOperationPlan":
        # Imported here: the capability catalog imports these models.
        from app.copilot.capabilities import get_capability

        capability = get_capability(self.operation)
        if (
            capability is None
            or self.target.kind is not capability.target_kind
            or type(self.parameters) is not capability.parameters_model
        ):
            raise ValueError("The target and parameters don't match the operation.")
        return self


class CopilotPlanRequest(BaseModel):
    """Reasoning result plus original message supplied to the planning gateway."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(..., min_length=1, max_length=500)
    intent: CopilotIntent
    proposed_action: str | None = Field(default=None, max_length=300)
    requires_confirmation: StrictBool = False

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank.")
        return value


class CopilotPlanningReason(str, Enum):
    PLAN_CREATED = "plan_created"
    NO_OPERATION_PROPOSED = "no_operation_proposed"
    UNSUPPORTED_INTENT = "unsupported_intent"
    UNSUPPORTED_ACTION = "unsupported_action"
    INTENT_MISMATCH = "intent_mismatch"
    ISSUE_NOT_DETECTED = "issue_not_detected"
    AMBIGUOUS_TARGET = "ambiguous_target"
    ISSUES_UNAVAILABLE = "issues_unavailable"
    RESOURCE_PROTECTED = "resource_protected"


class CopilotPlanningResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: CopilotIntent
    plan: CopilotOperationPlan | None = None
    reason: CopilotPlanningReason


class CopilotAuthorizationReason(str, Enum):
    AUTHORIZED = "authorized"
    CONFIRMATION_REQUIRED = "confirmation_required"
    MISSING_PRIVILEGE = "missing_required_privilege"
    UNKNOWN_OPERATION = "unknown_operation"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class CopilotAuthorizationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: CopilotOperationPlan
    confirmed: StrictBool = False


class CopilotAuthorizationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authorized: StrictBool
    requires_confirmation: StrictBool
    ready_to_execute: StrictBool
    reason: CopilotAuthorizationReason
    required_privileges: list[str]
    operation: CopilotOperation
    target: CopilotOperationTarget


class CopilotExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: CopilotOperationPlan
    authorization: CopilotAuthorizationResult
    confirmed: StrictBool = False


class CopilotExecutionStatus(str, Enum):
    EXECUTION_REJECTED = "execution_rejected"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    SUCCESS = "success"


class CopilotFailure(str, Enum):
    """Why a Copilot operation didn't succeed. The same codes name the failure
    stages of the Copilot trace (app/copilot/trace.py)."""

    PLAN_REJECTED = "plan_rejected"
    AUTHORIZATION_FAILED = "authorization_failed"
    ISSUE_NOT_DETECTED = "issue_not_detected"
    TARGET_CHANGED = "target_changed"
    PARAMETER_MISMATCH = "parameter_mismatch"
    RESOURCE_PROTECTED = "resource_protected"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    ISSUE_STILL_DETECTED = "issue_still_detected"


class CopilotExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CopilotOperation
    target: CopilotOperationTarget
    status: CopilotExecutionStatus
    execution_succeeded: StrictBool
    verification_succeeded: StrictBool
    verified_value: StrictBool | None = None
    detail: str
    # The structured reason, or None on success; `status` stays the broad outcome.
    failure: CopilotFailure | None = None
    # The "copilot.execute" trace (informational only).
    trace_id: str | None = None


class CopilotCapabilitySummary(BaseModel):
    """Public, read-only view of one Copilot capability. Privileges, risk and
    confirmation come from OPERATION_REGISTRY; the issue's title and severity
    from ISSUE_CATALOG. Handlers and parameter models are never exposed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CopilotOperation
    title: str
    target_kind: CopilotTargetKind
    issue_type: str | None
    issue_title: str | None
    issue_severity: str | None
    example_requests: list[str]
    constraints: list[str]
    verification: str
    undo: str | None
    required_privileges: list[str]
    risk_level: RiskLevel
    confirmation_required: bool


class CopilotCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capabilities: list[CopilotCapabilitySummary]
