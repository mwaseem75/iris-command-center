"""Bounded operational context returned to the AI Operations Copilot."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

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
    cpu_time: int | None = None


class CopilotWebAppContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    namespace: str | None = None
    enabled: bool
    app_type: str | None = None


class CopilotTaskContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    namespace: str | None = None
    suspended: bool
    next_scheduled: str | None = None


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
    processes: list[CopilotProcessContext]
    processes_total: int | None = None
    web_apps: list[CopilotWebAppContext]
    web_apps_total: int | None = None
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


# Each allowlisted operation's only valid target kind and parameter model.
_OPERATION_SHAPES: dict[CopilotOperation, tuple[CopilotTargetKind, type[BaseModel]]] = {
    CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED: (
        CopilotTargetKind.JOURNAL_SETTINGS,
        CopilotOperationParameters,
    ),
    CopilotOperation.DATABASE_MOUNT: (
        CopilotTargetKind.DATABASE,
        CopilotDatabaseMountParameters,
    ),
    CopilotOperation.WEB_APP_SET_ENABLED: (
        CopilotTargetKind.WEB_APP,
        CopilotWebAppDisableParameters,
    ),
}


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

    @model_validator(mode="after")
    def _shape_matches_operation(self) -> "CopilotOperationPlan":
        target_kind, parameters_model = _OPERATION_SHAPES[self.operation]
        if self.target.kind is not target_kind or type(self.parameters) is not parameters_model:
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


class CopilotExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CopilotOperation
    target: CopilotOperationTarget
    status: CopilotExecutionStatus
    execution_succeeded: StrictBool
    verification_succeeded: StrictBool
    verified_value: StrictBool | None = None
    detail: str
