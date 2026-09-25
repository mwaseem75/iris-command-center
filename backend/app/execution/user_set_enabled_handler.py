"""The handler for `user.set_enabled` — enable or disable login for an
existing IRIS user. Same architecture and discipline as web_app.set_enabled:
real validation against live IRIS read data in both dry_run() and
execute(), and only execute() ever calls the real write — dry_run() never
does.

Endpoint: `PUT /v2/security/user?name=<Name>` ("(%Admin_Secure:U) Edit a
user", mainspec_v2.json), body `{"Enabled": <bool>}` and nothing else. The
spec documents Enabled as "Allow user to log in. False - Disable login.
True - Enable login."

Request-shape evidence. IRIS's own implementation was read (read-only, via
the Atelier API) before this handler was written —
`%Api.Admin.Endpoints.Security.User` on IRIS 2026.2:
  - `RunPut()` returns 404 when `Security.Users.Exists()` is false, so a PUT
    can never create a user. The existence pre-check below makes that a
    clear failure before any write.
  - `UpdateUser()` copies ONLY keys present in the JSON body (`%IsDefined`)
    into the properties passed to `Security.Users.Modify()` — so
    `{"Enabled": b}` changes only Enabled. A true partial update, with no
    forced side effect (unlike PUT /v2/web-app's Type reset).
  - `ResourcesOR()` is `%Admin_Secure` only — the registry entry's required
    privilege.
  - The PUT's response is the FULL user object (`ObjToJson()`, including
    EmailAddress, PhoneNumber, PhoneProvider and Comment). It is discarded
    here: nothing from it is returned, stored or traced.

Sensitive fields: the user detail this handler reads also carries those
personal fields. Only `Enabled`, `Roles` and `EscalationRoles` are ever
taken from it; the handler's result `data` holds only the user name, the
Enabled values, role names and a description of the request.

No real PUT /v2/security/user has been executed against IRIS as of this
implementation. All tests use a fake/mock IRIS client (see
backend/tests/test_user_set_enabled.py).
"""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, field_validator

from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISClientError, IRISResponseError

_USER_PATH = "/v2/security/user"

# IRIS's predefined accounts (every user on a fresh 2026.2 instance —
# observed live on icc-iris-dev) that IRIS services or administration depend
# on: disabling one can break the Web Gateway (CSPSystem), unauthenticated
# access (UnknownUser), interoperability (_Ensemble) or administration, and
# enabling a disabled one (IAM, _PUBLIC) opens a built-in login. Compared
# case-insensitively.
_PROTECTED_USERS: dict[str, str] = {
    "_system": "it is IRIS's predefined SQL System Manager account",
    "admin": "it is IRIS's predefined System Administrator account",
    "superuser": "it is IRIS's predefined super-user account",
    "cspsystem": "it is the account the Web Gateway uses to connect to IRIS",
    "unknownuser": "it is the account IRIS uses for unauthenticated access",
    "_ensemble": "it is IRIS's internal interoperability manager account",
    "_public": "it is an IRIS internal account that is not for login",
    "iam": "it is the predefined account for IRIS's /api/iam web application",
    "irisowner": "it is the account that installed this IRIS instance",
}

# The super-user role. A holder (directly or as an escalation role) is
# protected in both directions: disabling one risks locking administrators
# out, enabling one opens a super-user login.
_SUPER_USER_ROLE = "%All"

# Same bounded policy as web_app.set_enabled: one immediate check plus three
# increasing delays, never unbounded.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class UserSetEnabledParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Enabled: StrictBool

    @field_validator("Name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Name is required and cannot be empty.")
        if value != value.strip():
            raise ValueError("Name must not start or end with whitespace.")
        if len(value) > 160:
            raise ValueError("Name is too long.")
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("Name must not contain control characters.")
        return value


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


def _state_word(enabled: bool) -> str:
    return "enabled" if enabled else "disabled"


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


class UserSetEnabledHandler(OperationHandler):
    """Requires an IRISClient supplied by the caller (typically a route), so
    it can be unit-tested with a fake/mock client. `own_username` is the IRIS
    account the Command Center itself signs in with — always protected."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        own_username: str | None = None,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        self._own_username = own_username.lower() if own_username else None
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_state(self, name: str) -> dict[str, Any] | None:
        """Read-only GET /v2/security/user?name=; only Enabled, Roles and
        EscalationRoles are kept (never the personal fields). None when IRIS
        reports no such user (404)."""
        try:
            body = await self._iris_client.get(_USER_PATH, params={"name": name})
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return None
            raise
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            return {"enabled": None, "roles": None, "escalation_roles": None}
        enabled = result.get("Enabled")
        return {
            "enabled": enabled if isinstance(enabled, bool) else None,
            "roles": _string_list(result.get("Roles")),
            "escalation_roles": _string_list(result.get("EscalationRoles")),
        }

    async def _validate(
        self, request: OperationRequest, context: ExecutionContext
    ) -> tuple[UserSetEnabledParameters, dict[str, Any]] | tuple[None, HandlerExecutionResult]:
        """Every check that precedes the write, in order: request shape, the
        protected-user list, existence, super-user role, and the current
        state. Read-only — safe for both dry_run() and execute()."""
        try:
            params = UserSetEnabledParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid user.set_enabled request ({field}): {first_error['msg']}")

        normalized = params.Name.lower()
        if self._own_username and normalized == self._own_username:
            return None, _failure(
                f"{params.Name!r} is protected and cannot be enabled or disabled from the "
                "Command Center: it is the IRIS account the Command Center itself signs in with.",
                name=params.Name,
                protected=True,
            )
        protected_reason = _PROTECTED_USERS.get(normalized)
        if protected_reason:
            return None, _failure(
                f"{params.Name!r} is protected and cannot be enabled or disabled from the "
                f"Command Center: {protected_reason}.",
                name=params.Name,
                protected=True,
            )

        state = await self._read_state(params.Name)
        if state is None:
            return None, _failure(
                f"IRIS reports no user named {params.Name!r} — nothing was changed.",
                name=params.Name,
            )

        roles = state["roles"]
        escalation_roles = state["escalation_roles"]
        if roles is None or escalation_roles is None:
            return None, _failure(
                f"Could not read {params.Name!r}'s roles from IRIS, so it cannot be checked "
                "for the super-user role — nothing was changed.",
                name=params.Name,
            )
        if _SUPER_USER_ROLE in roles or _SUPER_USER_ROLE in escalation_roles:
            return None, _failure(
                f"{params.Name!r} holds {_SUPER_USER_ROLE} (the super-user role) and is protected: "
                "disabling it risks locking administrators out, and enabling it opens a "
                "super-user login.",
                name=params.Name,
                protected=True,
            )

        enabled = state["enabled"]
        if enabled is None:
            return None, _failure(
                f"Could not determine whether {params.Name!r} is currently enabled "
                "(GET /v2/security/user did not include an Enabled value).",
                name=params.Name,
            )
        if enabled is params.Enabled:
            return None, _failure(
                f"{params.Name!r} is already {_state_word(enabled)} — nothing to do.",
                name=params.Name,
                enabled=enabled,
                no_change=True,
            )

        return params, {"enabled_before": enabled, "roles": roles, "escalation_roles": escalation_roles}

    def _change_data(self, params: UserSetEnabledParameters, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": params.Name,
            "enabled_before": state["enabled_before"],
            "enabled_after": params.Enabled,
            "roles": state["roles"],
            "escalation_roles": state["escalation_roles"],
            "request": {
                "method": "PUT",
                "path": _USER_PATH,
                "query": {"name": params.Name},
                "body": {"Enabled": params.Enabled},
            },
        }

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Validation and read-only IRIS lookups only — never calls put()."""
        params, result = await self._validate(request, context)
        if params is None:
            return result

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: user {params.Name!r} is currently {_state_word(result['enabled_before'])} "
                f"and would be {_state_word(params.Enabled)} via PUT /v2/security/user with the body "
                f'{{"Enabled": {str(params.Enabled).lower()}}} only — no other setting is sent. '
                "No request was sent."
            ),
            data=self._change_data(params, result),
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        params, result = await self._validate(request, context)
        if params is None:
            return result

        try:
            # The response (the full user object, with personal fields) is
            # deliberately discarded; verify() re-reads only what it needs.
            await self._iris_client.put(_USER_PATH, json={"Enabled": params.Enabled}, params={"name": params.Name})
        except IRISResponseError as exc:
            if exc.status_code == 403:
                return _failure(
                    f"IRIS denied the change to user {params.Name!r} (HTTP 403) — it requires "
                    "%Admin_Secure. Nothing was changed.",
                    name=params.Name,
                )
            if exc.status_code == 404:
                return _failure(
                    f"IRIS reports no user named {params.Name!r} (HTTP 404). Nothing was changed.",
                    name=params.Name,
                )
            if exc.status_code == 400:
                return _failure(
                    f"IRIS rejected the change to user {params.Name!r} as invalid (HTTP 400). "
                    "Nothing was changed.",
                    name=params.Name,
                )
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Requested {_state_word(params.Enabled)} state for user {params.Name!r} via PUT /v2/security/user.",
            data=self._change_data(params, result),
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Fresh GET /v2/security/user reads, independent of the PUT
        response, retried with the bounded policy above: the user must report
        the requested Enabled value, and its Roles / EscalationRoles must be
        unchanged (IRIS's partial update must not have touched them)."""
        data = execution_result.data
        name = data.get("name")
        target = data.get("enabled_after")
        roles_before = data.get("roles")
        escalation_before = data.get("escalation_roles")

        last_enabled: bool | str | None = None
        last_roles: Any = None
        last_escalation: Any = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The change already happened; a read failure here must surface
            # as VERIFICATION_FAILED, not an unhandled error.
            try:
                state = await self._read_state(name)
            except IRISClientError as exc:
                last_enabled = f"read error ({exc.__class__.__name__})"
                continue
            if state is None:
                last_enabled = "user not found"
                continue
            last_enabled = state["enabled"]
            last_roles = state["roles"]
            last_escalation = state["escalation_roles"]
            if last_enabled is target and last_roles == roles_before and last_escalation == escalation_before:
                break

        attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
        if last_enabled is not target:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected user {name!r} to be {_state_word(bool(target))}, but GET "
                    f"/v2/security/user last reported Enabled={last_enabled!r} after "
                    f"{attempts_made} attempts (retried with delays of {attempted_delays})."
                ),
            )
        if last_roles != roles_before or last_escalation != escalation_before:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"User {name!r} is now {_state_word(bool(target))}, but its roles changed "
                    "(GET /v2/security/user) — only Enabled was sent."
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                f"Confirmed via GET /v2/security/user: user {name!r} now reports Enabled={target}, "
                f"and its roles are unchanged{retry_note}."
            ),
        )
