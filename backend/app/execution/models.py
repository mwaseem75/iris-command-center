"""Request, context and result models for running operations."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.authorization.models import AuthorizationResult
from app.resolution.identity import IssueResourceReference


class OperationRequest(BaseModel):
    """What the caller wants to run. `parameters` is handler-specific input.

    `resolution_issue_type` says the request comes from an Issue Resolution
    workflow. It labels the trace and enables optional lifecycle evidence; it
    never changes authorization, confirmation or what the handler does.
    """

    model_config = ConfigDict(frozen=True)

    operation_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    resolution_issue_type: str | None = None


class ExecutionContext(BaseModel):
    """Everything the executor needs to decide on one attempt.

    `available_privileges` must come from the backend itself (the IRIS
    session's /info), never from the client's request. There's intentionally
    no force/skip/bypass field (see test_execution_context_has_no_bypass_fields).
    """

    model_config = ConfigDict(frozen=True)

    available_privileges: frozenset[str] = Field(default_factory=frozenset)
    confirmation_received: bool = False
    dry_run: bool = False


class HandlerOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class HandlerExecutionResult(BaseModel):
    """What a handler's execute() or dry_run() returned. `data` is handler-specific."""

    model_config = ConfigDict(frozen=True)

    outcome: HandlerOutcome
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class PostActionVerificationStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"  # dry run, or the operation has no verification
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"


class PostActionVerificationResult(BaseModel):
    """Existing verification outcome plus optional structured observed state."""

    model_config = ConfigDict(frozen=True)

    status: PostActionVerificationStatus
    detail: str
    evidence: dict[str, bool | str | None] | None = None


class ResolutionBefore(BaseModel):
    issue_id: str
    resource: IssueResourceReference
    observed_at: datetime
    state: dict[str, bool | str | None]


class ResolutionAction(BaseModel):
    operation_name: str
    parameters: dict[str, bool | str | int | float | None]


class ResolutionLifecycleEvidence(BaseModel):
    """Resolution-specific evidence; result and verification remain on OperationResult."""

    before: ResolutionBefore
    action: ResolutionAction
    after: dict[str, bool | str | None] | None = None


class OperationResultStatus(str, Enum):
    UNKNOWN_OPERATION = "unknown_operation"
    UNAUTHORIZED = "unauthorized"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NO_HANDLER = "no_handler"
    DRY_RUN = "dry_run"
    SUCCESS = "success"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"


class OperationResult(BaseModel):
    """Outcome of OperationExecutor.execute().

    Denials are returned as results, not exceptions; only unexpected handler
    errors are caught and reported as EXECUTION_FAILED.
    """

    model_config = ConfigDict(frozen=True)

    operation_name: str
    status: OperationResultStatus
    authorization: AuthorizationResult | None = None
    handler_result: HandlerExecutionResult | None = None
    verification: PostActionVerificationResult | None = None
    detail: str
    lifecycle: ResolutionLifecycleEvidence | None = None
    # The ExecutionTrace recorded for this run. Informational only: it links
    # other traces (e.g. the Copilot's) to this one and decides nothing.
    trace_id: str | None = None
