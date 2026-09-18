"""Structured authorization decision model. Future API routes should use
this consistently rather than inventing their own ad-hoc authorization
response shapes."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AuthorizationDenialReason(str, Enum):
    UNKNOWN_OPERATION = "unknown_operation"
    MISSING_PRIVILEGE = "missing_privilege"
    CONFIRMATION_REQUIRED = "confirmation_required"


class AuthorizationResult(BaseModel):
    """The outcome of an authorization decision. Never carries a credential,
    token, or privilege claim that wasn't already known to the caller.

    `authorized` reflects the privilege check alone — whether the caller
    holds the operation's required privilege. It can be True even when the
    operation is still blocked overall (a mutating operation that is
    authorized but not yet confirmed): that overall verdict is `can_proceed`.
    """

    model_config = ConfigDict(frozen=True)

    operation_name: str
    authorized: bool
    confirmation_required: bool
    confirmation_received: bool
    can_proceed: bool
    denial_reason: AuthorizationDenialReason | None
    detail: str
