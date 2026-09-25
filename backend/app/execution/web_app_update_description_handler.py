"""The handler for `web_app.update_description` — change the Description of
an existing IRIS web application. Same architecture and discipline as
web_app.set_enabled (whose protected-app list, name normalization, IRIS
privilege and retry policy it reuses): real validation against live IRIS
read data in both dry_run() and execute(), and only execute() ever calls the
real write — dry_run() never does.

Endpoint: `PUT /v2/web-app?name=<Name>` ("(%Admin_Secure:U) Create/Edit a
web application", mainspec_v2.json), body `{"Description": <string>}` and
nothing else.

Request-shape evidence. IRIS's own implementation was read (read-only, via
the Atelier API) — `%Api.Admin.Endpoints.WebApp.App` on IRIS 2026.2, the same
code path documented in web_app_set_enabled_handler.py:
  - `MergeJsonAndProperties()` copies ONLY keys present in the JSON body into
    the properties passed to `Security.Applications.Modify()` — so
    `{"Description": d}` changes only Description ...
  - ... but it ALWAYS sets `properties("Type") = $$$AppTypeCSP`, so System
    ("System,CSP") apps are hard-denied, exactly as for set_enabled, and
    verify() checks the Type is unchanged.
  - `RunPut()` calls `Security.Applications.Create()` when the app does not
    exist; `ValidateRequest()` then requires NameSpace, so a Description-only
    body would be a 400 — the existence pre-check below refuses it first.
  - `Security.Applications.Description` is `%String(MAXLEN = 256)`, so longer
    values are rejected here rather than by IRIS.
  - The PUT's response (the full app object) is discarded; verify() re-reads.

No real PUT /v2/web-app has been executed against IRIS as of this
implementation. All tests use a fake/mock IRIS client (see
backend/tests/test_web_app_update_description.py).
"""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, field_validator

from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.execution.web_app_set_enabled_handler import (
    _PROTECTED_APPS,
    _REQUIRED_IRIS_PRIVILEGE,
    _VERIFY_RETRY_DELAYS_SECONDS,
    _normalize,
)
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISClientError, IRISResponseError

_WEB_APP_PATH = "/v2/web-app"
_WEB_APPS_PATH = "/v2/web-apps"

# Security.Applications: Property Description As %String(MAXLEN = 256).
_DESCRIPTION_MAX_LENGTH = 256


class WebAppUpdateDescriptionParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Description: StrictStr

    @field_validator("Name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        # The same rules as web_app.set_enabled's Name.
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

    @field_validator("Description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        # An empty string is allowed: it clears the description.
        if len(value) > _DESCRIPTION_MAX_LENGTH:
            raise ValueError(f"Description must be at most {_DESCRIPTION_MAX_LENGTH} characters (IRIS's MAXLEN).")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("Description must not contain control characters (including line breaks).")
        return value


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


class WebAppUpdateDescriptionHandler(OperationHandler):
    """Requires an IRISClient supplied by the caller (typically a route), so
    it can be unit-tested with a fake/mock client."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_list_entry(self, name: str) -> dict[str, Any] | None:
        """Read-only GET /v2/web-apps; the entry whose Name is exactly
        `name`, or None."""
        body = await self._iris_client.get(_WEB_APPS_PATH)
        entries = body.get("result") if isinstance(body, dict) else None
        if not isinstance(entries, list):
            return None
        return next((e for e in entries if isinstance(e, dict) and e.get("Name") == name), None)

    async def _read_detail(self, name: str) -> tuple[str | None, bool | None]:
        """Read-only GET /v2/web-app?name=; the real Description and Enabled
        values, each None if absent or of the wrong type (never guessed)."""
        body = await self._iris_client.get(_WEB_APP_PATH, params={"name": name})
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            return None, None
        description = result.get("Description")
        enabled = result.get("Enabled")
        return (
            description if isinstance(description, str) else None,
            enabled if isinstance(enabled, bool) else None,
        )

    async def _validate(
        self, request: OperationRequest, context: ExecutionContext
    ) -> tuple[WebAppUpdateDescriptionParameters, dict[str, Any]] | tuple[None, HandlerExecutionResult]:
        """Every check that precedes the write, in order: request shape,
        IRIS's own privilege, the hard-deny list, existence, System type, and
        the current Description. Read-only — safe for dry_run() and execute()."""
        try:
            params = WebAppUpdateDescriptionParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            message = first_error["msg"].removeprefix("Value error, ")
            return None, _failure(f"Invalid web_app.update_description request ({field}): {message}")

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
                f"{params.Name!r} is protected and cannot be changed from the Command Center: {protected_reason}.",
                name=params.Name,
                protected=True,
            )

        entry = await self._read_list_entry(params.Name)
        if entry is None:
            return None, _failure(
                f"No web application named {params.Name!r} exists — nothing was changed.", name=params.Name
            )

        app_type = entry.get("Type")
        if entry.get("IsSystemApp") is True or (isinstance(app_type, str) and "system" in app_type.lower()):
            return None, _failure(
                f"{params.Name!r} is a System web application (Type {app_type!r}) and is protected: IRIS's "
                "PUT /v2/web-app always resets an application's Type to plain CSP, which would silently clear "
                "its System flag.",
                name=params.Name,
                protected=True,
                type=app_type,
            )

        description, enabled = await self._read_detail(params.Name)
        if description is None or enabled is None:
            return None, _failure(
                f"Could not read {params.Name!r}'s current Description and Enabled values from IRIS "
                "(GET /v2/web-app) — nothing was changed.",
                name=params.Name,
            )
        if description == params.Description:
            return None, _failure(
                f"{params.Name!r} already has this Description — nothing to do.",
                name=params.Name,
                no_change=True,
            )

        return params, {"type_before": app_type, "description_before": description, "enabled_before": enabled}

    def _change_data(self, params: WebAppUpdateDescriptionParameters, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": params.Name,
            "description_before": state["description_before"],
            "description_after": params.Description,
            "enabled_before": state["enabled_before"],
            "type_before": state["type_before"],
            "request": {
                "method": "PUT",
                "path": _WEB_APP_PATH,
                "query": {"name": params.Name},
                "body": {"Description": params.Description},
            },
        }

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        """Validation and read-only IRIS lookups only — never calls put()."""
        params, result = await self._validate(request, context)
        if params is None:
            return result
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: {params.Name!r} Description would change from {result['description_before']!r} to "
                f"{params.Description!r} via PUT /v2/web-app with the body {{\"Description\": ...}} only — no "
                "other setting is sent. No request was sent."
            ),
            data=self._change_data(params, result),
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        params, result = await self._validate(request, context)
        if params is None:
            return result

        try:
            # The response (the full app object) is deliberately discarded.
            await self._iris_client.put(
                _WEB_APP_PATH, json={"Description": params.Description}, params={"name": params.Name}
            )
        except IRISResponseError as exc:
            if exc.status_code == 403:
                return _failure(
                    f"IRIS denied the change to {params.Name!r} (HTTP 403) — it requires %Admin_Secure. "
                    "Nothing was changed.",
                    name=params.Name,
                )
            if exc.status_code == 400:
                return _failure(
                    f"IRIS rejected the change to {params.Name!r} as invalid (HTTP 400). Nothing was changed.",
                    name=params.Name,
                )
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Requested the new Description for {params.Name!r} via PUT /v2/web-app.",
            data=self._change_data(params, result),
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Fresh reads, independent of the PUT response, retried with the
        bounded policy: GET /v2/web-app must report the requested Description
        and the original Enabled value, and GET /v2/web-apps the original
        Type (IRIS's PUT forces Type to CSP; for the non-System apps this
        operation allows, that must be a no-op)."""
        data = execution_result.data
        name = data.get("name")
        target = data.get("description_after")
        enabled_before = data.get("enabled_before")
        type_before = data.get("type_before")

        last_description: str | None = None
        last_enabled: bool | None = None
        last_type: Any = None
        last_error: str | None = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The change already happened; a read failure here must surface
            # as VERIFICATION_FAILED, not an unhandled error.
            try:
                last_description, last_enabled = await self._read_detail(name)
                entry = await self._read_list_entry(name)
                last_type = entry.get("Type") if entry else None
                last_error = None
            except IRISClientError as exc:
                last_error = f"read error ({exc.__class__.__name__})"
                continue
            if last_description == target and last_enabled is enabled_before and last_type == type_before:
                break

        attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
        if last_error or last_description != target:
            reported = last_error or f"Description={last_description!r}"
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected {name!r} to report Description={target!r}, but GET /v2/web-app last reported "
                    f"{reported} after {attempts_made} attempts (retried with delays of {attempted_delays})."
                ),
            )
        if last_enabled is not enabled_before or last_type != type_before:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"{name!r} now reports the new Description, but another setting changed "
                    f"(Enabled {enabled_before!r} → {last_enabled!r}, Type {type_before!r} → {last_type!r}) — "
                    "only Description was sent."
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                f"Confirmed via GET /v2/web-app: {name!r} now reports the requested Description, Enabled is "
                f"unchanged, and GET /v2/web-apps still reports Type {type_before!r}{retry_note}."
            ),
        )
