"""Structured models for the operation execution framework.

None of these models, and nothing in this package, calls IRIS. That only
happens (in a future step) inside a real OperationHandler's `execute()`
method — and no such handler exists yet anywhere in this project.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.authorization.models import AuthorizationResult


class OperationRequest(BaseModel):
    """What the caller is asking to happen. `parameters` is deliberately a
    generic, open dict — this step defines no operation that reads it; it
    exists so a future real handler can accept operation-specific input
    without changing this model."""

    model_config = ConfigDict(frozen=True)

    operation_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    """The trust boundary for one execution attempt.

    `available_privileges` must, in a real deployment, come from a trusted
    source the backend itself established — e.g. the authenticated caller's
    own IRIS session privileges, obtained via a real GET /info call using
    their session's JWT — never taken directly from client-submitted request
    body/query data. No route in this project populates this field from
    anywhere yet (no route uses this framework at all), so that boundary has
    not yet been crossed by any code; it is stated here as a hard
    requirement for whichever future step wires a real route to this
    executor.

    There is deliberately no "force", "skip_confirmation", "bypass", or
    similar field anywhere on this model. See
    test_execution_context_has_no_bypass_fields.
    """

    model_config = ConfigDict(frozen=True)

    available_privileges: frozenset[str] = Field(default_factory=frozenset)
    confirmation_received: bool = False
    dry_run: bool = False


class HandlerOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class HandlerExecutionResult(BaseModel):
    """What a handler's execute() or dry_run() returned. `data` is generic,
    handler-defined content (e.g. what would change, or what did change) —
    never a credential or token value."""

    model_config = ConfigDict(frozen=True)

    outcome: HandlerOutcome
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class PostActionVerificationStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"  # dry-run, or the operation defines no verification
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"


class PostActionVerificationResult(BaseModel):
    """The outcome of checking IRIS's actual resulting state after a real
    execution. Always NOT_APPLICABLE for a dry-run — a dry-run never
    changes anything, so there is nothing to verify."""

    model_config = ConfigDict(frozen=True)

    status: PostActionVerificationStatus
    detail: str


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
    """The single, structured outcome of OperationExecutor.execute(). Every
    code path through the executor returns exactly one of these — there is
    no separate exception-based control flow for authorization/confirmation
    denial (only genuinely unexpected handler errors are ever caught and
    turned into EXECUTION_FAILED; see executor.py)."""

    model_config = ConfigDict(frozen=True)

    operation_name: str
    status: OperationResultStatus
    authorization: AuthorizationResult | None = None
    handler_result: HandlerExecutionResult | None = None
    verification: PostActionVerificationResult | None = None
    detail: str
