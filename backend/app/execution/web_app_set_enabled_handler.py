"""Handler for web_app.set_enabled (PUT /v2/web-app?name=..., %Admin_Secure:U).

Sends {"Enabled": b} and nothing else. Both dry_run() and execute()
validate against live IRIS data; only execute() sends the PUT.

From reading %Api.Admin.Endpoints.WebApp.App on 2026.2:
- Only keys present in the body are changed (a partial update)...
- ...but every PUT also sets Type to plain CSP. For a "System,CSP" app
  that would quietly drop the System flag, so System apps are refused and
  verify() checks the Type didn't change.
- A missing app plus no NameSpace in the body is a 400, so this can't
  create an app; we check existence first anyway.
- IRIS requires %Admin_Secure for the PUT (_REQUIRED_IRIS_PRIVILEGE).
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

_WEB_APP_PATH = "/v2/web-app"
_WEB_APPS_PATH = "/v2/web-apps"

# Our registry entry requires Manage, but IRIS also wants %Admin_Secure
# for this PUT. Check it up front instead of hitting a 403 halfway.
_REQUIRED_IRIS_PRIVILEGE = "Secure"

# Web apps the Command Center itself relies on; touching them could cut
# us off from IRIS. Compared case-insensitively, ignoring a trailing slash.
_PROTECTED_APPS: dict[str, str] = {
    "/api/admin": (
        "it is the IRIS SysAdmin API this Command Center authenticates against "
        "and uses for every read and operation"
    ),
    "/api/mgmnt": (
        "it is the IRIS API Management API this Command Center uses for "
        "REST route maps"
    ),
}

# Same retry schedule as database.mount.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


def _normalize(name: str) -> str:
    return name.lower().rstrip("/") or "/"


class WebAppSetEnabledParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Enabled: StrictBool

    @field_validator("Name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Name is required and cannot be empty.")
        if not value.startswith("/"):
            raise ValueError("Name must start with '/'.")
        if len(value) > 256:
            raise ValueError("Name is too long.")
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("Name must not contain control characters.")
        if ".." in value.split("/"):
            raise ValueError("Name must not contain '..' path segments.")
        return value


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


def _state_word(enabled: bool) -> str:
    return "enabled" if enabled else "disabled"


class WebAppSetEnabledHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_list_entry(self, name: str) -> dict[str, Any] | None:
        """GET /v2/web-apps and return the entry named exactly `name`, or None."""
        body = await self._iris_client.get(_WEB_APPS_PATH)
        entries = body.get("result") if isinstance(body, dict) else None
        if not isinstance(entries, list):
            return None
        return next(
            (e for e in entries if isinstance(e, dict) and e.get("Name") == name),
            None,
        )

    async def _read_enabled(self, name: str) -> bool | None:
        """GET /v2/web-app?name= and return Enabled, or None if it's missing or not a bool."""
        body = await self._iris_client.get(_WEB_APP_PATH, params={"name": name})
        result = body.get("result") if isinstance(body, dict) else None
        enabled = result.get("Enabled") if isinstance(result, dict) else None
        return enabled if isinstance(enabled, bool) else None

    async def _validate(
        self, request: OperationRequest, context: ExecutionContext
    ) -> tuple[WebAppSetEnabledParameters, dict[str, Any]] | tuple[None, HandlerExecutionResult]:
        """All checks before the write, in order: request, IRIS privilege, protected
        apps, existence, System type, current state. Read-only.
        """
        try:
            params = WebAppSetEnabledParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid web_app.set_enabled request ({field}): {first_error['msg']}")

        if _REQUIRED_IRIS_PRIVILEGE not in context.available_privileges:
            return None, _failure(
                "IRIS itself requires the %Admin_Secure privilege to modify a web "
                "application (PUT /v2/web-app), and the current session does not hold it.",
                name=params.Name,
                missing_iris_privilege=_REQUIRED_IRIS_PRIVILEGE,
            )

        protected_reason = _PROTECTED_APPS.get(_normalize(params.Name))
        if protected_reason:
            return None, _failure(
                f"{params.Name!r} is protected and cannot be enabled or disabled from "
                f"the Command Center: {protected_reason}.",
                name=params.Name,
                protected=True,
            )

        entry = await self._read_list_entry(params.Name)
        if entry is None:
            return None, _failure(
                f"No web application named {params.Name!r} exists — nothing was changed.",
                name=params.Name,
            )

        app_type = entry.get("Type")
        if entry.get("IsSystemApp") is True or (
            isinstance(app_type, str) and "system" in app_type.lower()
        ):
            return None, _failure(
                f"{params.Name!r} is a System web application (Type {app_type!r}) and is "
                "protected: IRIS's PUT /v2/web-app always resets an application's Type to "
                "plain CSP, which would silently clear its System flag.",
                name=params.Name,
                protected=True,
                type=app_type,
            )

        enabled = await self._read_enabled(params.Name)
        if enabled is None:
            return None, _failure(
                f"Could not determine whether {params.Name!r} is currently enabled "
                "(GET /v2/web-app did not include an Enabled value).",
                name=params.Name,
            )
        if enabled is params.Enabled:
            return None, _failure(
                f"{params.Name!r} is already {_state_word(enabled)} — nothing to do.",
                name=params.Name,
                enabled=enabled,
                no_change=True,
            )

        return params, {"type_before": app_type, "enabled_before": enabled}

    def _change_data(
        self, params: WebAppSetEnabledParameters, state: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "name": params.Name,
            "enabled_before": state["enabled_before"],
            "enabled_after": params.Enabled,
            "type_before": state["type_before"],
            "request": {
                "method": "PUT",
                "path": _WEB_APP_PATH,
                "query": {"name": params.Name},
                "body": {"Enabled": params.Enabled},
            },
        }

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Validate and read from IRIS only; never sends the PUT."""
        params, result = await self._validate(request, context)
        if params is None:
            return result

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: {params.Name!r} is currently {_state_word(result['enabled_before'])} "
                f"and would be {_state_word(params.Enabled)} via PUT /v2/web-app with the body "
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
            await self._iris_client.put(
                _WEB_APP_PATH, json={"Enabled": params.Enabled}, params={"name": params.Name}
            )
        except IRISResponseError as exc:
            if exc.status_code == 403:
                return _failure(
                    f"IRIS denied the change to {params.Name!r} (HTTP 403) — it requires "
                    "%Admin_Secure. Nothing was changed.",
                    name=params.Name,
                )
            if exc.status_code == 400:
                return _failure(
                    f"IRIS rejected the change to {params.Name!r} as invalid (HTTP 400). "
                    "Nothing was changed.",
                    name=params.Name,
                )
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Requested {_state_word(params.Enabled)} state for {params.Name!r} "
                "via PUT /v2/web-app."
            ),
            data=self._change_data(params, result),
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Re-read (with retries): GET /v2/web-app must show the requested Enabled
        value, and GET /v2/web-apps must still show the original Type.
        """
        data = execution_result.data
        name = data.get("name")
        target = data.get("enabled_after")
        type_before = data.get("type_before")

        last_enabled: bool | str | None = None
        last_type: Any = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The change already happened, so a failed read here is a
            # VERIFICATION_FAILED result, not an exception.
            try:
                last_enabled = await self._read_enabled(name)
                entry = await self._read_list_entry(name)
                last_type = entry.get("Type") if entry else None
            except IRISClientError as exc:
                last_enabled = f"read error ({exc.__class__.__name__})"
                continue
            if last_enabled is target and last_type == type_before:
                break

        attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
        if last_enabled is not target:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected {name!r} to be {_state_word(bool(target))}, but GET "
                    f"/v2/web-app last reported Enabled={last_enabled!r} after "
                    f"{attempts_made} attempts (retried with delays of {attempted_delays})."
                ),
            )
        if last_type != type_before:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"{name!r} is now {_state_word(bool(target))}, but its Type changed from "
                    f"{type_before!r} to {last_type!r} (GET /v2/web-apps)."
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                f"Confirmed via GET /v2/web-app: {name!r} now reports "
                f"Enabled={target}, and GET /v2/web-apps still reports Type "
                f"{type_before!r}{retry_note}."
            ),
        )
