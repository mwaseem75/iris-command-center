"""Result type returned by the authorization service."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AuthorizationDenialReason(str, Enum):
    UNKNOWN_OPERATION = "unknown_operation"
    MISSING_PRIVILEGE = "missing_privilege"
    CONFIRMATION_REQUIRED = "confirmation_required"


class AuthorizationResult(BaseModel):
    """Outcome of an authorization check.

    `authorized` is only the privilege check. `can_proceed` is the overall
    answer, e.g. a mutating operation can be authorized but still waiting
    for confirmation.
    """

    model_config = ConfigDict(frozen=True)

    operation_name: str
    authorized: bool
    confirmation_required: bool
    confirmation_received: bool
    can_proceed: bool
    denial_reason: AuthorizationDenialReason | None
    detail: str
