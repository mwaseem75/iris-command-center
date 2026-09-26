"""Handler for database.dismount (POST /v2/database-dir/dismount?dir=..., no body).

IRIS itself only refuses to dismount the manager's database (IRISSYS, 409);
it would happily dismount IRISLIB, IRISTEMP, IRISAUDIT and so on. So we
refuse, before sending anything:
- IRIS's own databases (_SYSTEM_DATABASES)
- databases with MountRequired not explicitly false
- databases used by the %SYS namespace in any role
- mirrored databases
- directories that aren't a configured database, don't exist, are already
  dismounted, or whose mount state we can't read

The dry run also lists the namespaces that use the database, so you can
see what will be affected.
"""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.execution.database_create_handler import _DIRECTORY_PATTERN
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

_DISMOUNT_PATH = "/v2/database-dir/dismount"
_INFO_PATH = "/v2/database-dir/info"
_DATABASES_PATH = "/v2/databases"
_NAMESPACES_PATH = "/v2/namespaces"

# Databases IRIS creates for itself (compared by name, case-insensitive).
_SYSTEM_DATABASES = frozenset(
    {"IRISSYS", "IRISSECURITY", "IRISLIB", "IRISTEMP", "IRISLOCALDATA", "IRISAUDIT", "IRISMETRICS", "ENSLIB"}
)

# Namespace fields that name a database.
_NAMESPACE_DB_FIELDS = ("Globals", "Routines", "Library", "SysGlobals", "SysRoutines", "TempGlobals")

# Same retry schedule as database.mount.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)

# Sentinel values for _read_info().
_NOT_FOUND = "not_found"


class DatabaseDismountParameters(BaseModel):
    """`Directory` is the database (the spec's dir parameter). No other input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str

    @field_validator("Directory")
    @classmethod
    def _validate_directory(cls, value: str) -> str:
        # Same checks as database.mount / database.create.
        if not value:
            raise ValueError("Directory is required and cannot be empty.")
        if not value.startswith("/"):
            raise ValueError("Directory must be an absolute path (starting with '/').")
        if ".." in value.split("/"):
            raise ValueError("Directory must not contain '..' path segments.")
        if not _DIRECTORY_PATTERN.match(value):
            raise ValueError("Directory contains invalid characters or is too long.")
        return value


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


class DatabaseDismountHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_info(self, directory: str) -> dict[str, Any] | str:
        """Read Mounted and Mirrored from POST /v2/database-dir/info
        (None if missing), or _NOT_FOUND on 404.
        """
        try:
            task_id = await self._iris_client.post_async_task(_INFO_PATH, params={"dir": directory})
            task = await self._iris_client.wait_for_async_task(task_id)
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return _NOT_FOUND
            raise
        result = task.get("Result") if isinstance(task, dict) else None
        result = result if isinstance(result, dict) else {}
        return {
            key: result.get(key) if isinstance(result.get(key), bool) else None for key in ("Mounted", "Mirrored")
        }

    async def _read_list(self, path: str) -> list[dict[str, Any]]:
        body = await self._iris_client.get(path)
        entries = body.get("result") if isinstance(body, dict) else None
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    async def _validate(
        self, request: OperationRequest
    ) -> tuple[DatabaseDismountParameters, dict[str, Any]] | tuple[None, HandlerExecutionResult]:
        """All checks before the write, in order: request, configured database,
        system database, MountRequired, %SYS use, mount state, mirroring.
        """
        try:
            params = DatabaseDismountParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            message = first_error["msg"].removeprefix("Value error, ")
            return None, _failure(f"Invalid database.dismount request ({field}): {message}")

        databases = await self._read_list(_DATABASES_PATH)
        entry = next((db for db in databases if db.get("Directory") == params.Directory), None)
        if entry is None or not isinstance(entry.get("Name"), str):
            return None, _failure(
                f"No configured database uses directory {params.Directory!r} (GET /v2/databases) — nothing was changed.",
                directory=params.Directory,
            )
        name = entry["Name"]

        if name.upper() in _SYSTEM_DATABASES:
            return None, _failure(
                f"{name} is an IRIS system database and is protected: dismounting it can stop IRIS itself "
                "(or its security, auditing, temporary storage or libraries) from working.",
                directory=params.Directory,
                name=name,
                protected=True,
            )
        if entry.get("MountRequired") is not False:
            reason = "is marked Mount Required" if entry.get("MountRequired") is True else "has an unknown Mount Required setting"
            return None, _failure(
                f"{name} {reason} in IRIS and is protected — IRIS expects it to stay mounted.",
                directory=params.Directory,
                name=name,
                protected=True,
            )

        namespaces = await self._read_list(_NAMESPACES_PATH)
        users = sorted(
            ns["Name"] for ns in namespaces
            if isinstance(ns.get("Name"), str) and any(ns.get(field) == name for field in _NAMESPACE_DB_FIELDS)
        )
        if "%SYS" in users:
            return None, _failure(
                f"{name} is used by the %SYS namespace and is protected.",
                directory=params.Directory,
                name=name,
                protected=True,
            )

        info = await self._read_info(params.Directory)
        if info == _NOT_FOUND:
            return None, _failure(
                f"IRIS reports no database at directory {params.Directory!r} — nothing was changed.",
                directory=params.Directory,
                name=name,
            )
        if info["Mirrored"] is not False:
            reason = "is mirrored" if info["Mirrored"] is True else "has an unknown mirroring state"
            return None, _failure(
                f"{name} {reason} and is protected — dismounting it is left to IRIS's mirroring tools.",
                directory=params.Directory,
                name=name,
                protected=True,
            )
        if info["Mounted"] is False:
            return None, _failure(
                f"{name} is already dismounted — nothing to do.",
                directory=params.Directory,
                name=name,
                already_dismounted=True,
            )
        if info["Mounted"] is not True:
            return None, _failure(
                f"Could not determine whether {name} is mounted (IRIS's database info did not include a "
                "Mounted value) — nothing was changed.",
                directory=params.Directory,
                name=name,
            )

        return params, {"name": name, "namespaces": users}

    def _change_data(self, params: DatabaseDismountParameters, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "directory": params.Directory,
            "name": state["name"],
            "namespaces": state["namespaces"],
            "request": {"method": "POST", "path": _DISMOUNT_PATH, "query": {"dir": params.Directory}, "body": None},
        }

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        """Validate and read from IRIS only; never sends the dismount."""
        params, result = await self._validate(request)
        if params is None:
            return result
        affected = ", ".join(result["namespaces"]) if result["namespaces"] else "none"
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: {result['name']} ({params.Directory}) is mounted and would be dismounted via POST "
                f"/v2/database-dir/dismount (no request body). Namespaces that map this database and would lose "
                f"access to it: {affected}. It stays dismounted until it is mounted again. No request was sent."
            ),
            data=self._change_data(params, result),
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        params, result = await self._validate(request)
        if params is None:
            return result

        try:
            await self._iris_client.post(_DISMOUNT_PATH, params={"dir": params.Directory})
        except IRISResponseError as exc:
            if exc.status_code == 409:
                return _failure(
                    f"IRIS refused to dismount {result['name']} (HTTP 409 — it cannot dismount this database). "
                    "Nothing was changed.",
                    directory=params.Directory,
                    name=result["name"],
                )
            if exc.status_code == 404:
                return _failure(
                    f"IRIS reports no database at directory {params.Directory!r} (HTTP 404). Nothing was changed.",
                    directory=params.Directory,
                )
            if exc.status_code == 403:
                return _failure(
                    f"IRIS denied dismounting {result['name']} (HTTP 403) — it requires %Admin_Operate. "
                    "Nothing was changed.",
                    directory=params.Directory,
                )
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Dismount requested for {result['name']} ({params.Directory}).",
            data=self._change_data(params, result),
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Re-read /v2/database-dir/info (with retries) and check Mounted is now false."""
        directory = execution_result.data.get("directory")
        name = execution_result.data.get("name")

        last_state: Any = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The change already happened, so a failed read here is a
            # VERIFICATION_FAILED result, not an exception.
            try:
                info = await self._read_info(directory)
            except IRISClientError as exc:
                last_state = f"read error ({exc.__class__.__name__})"
                continue
            last_state = info if info == _NOT_FOUND else info["Mounted"]
            if last_state is False:
                break

        if last_state is not False:
            attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected {name} ({directory}) to be dismounted, but POST /v2/database-dir/info last "
                    f"reported {last_state!r} for Mounted after {attempts_made} attempts (retried with delays of "
                    f"{attempted_delays})."
                ),
            )
        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=f"Confirmed via POST /v2/database-dir/info: {name} ({directory}) now reports Mounted=False{retry_note}.",
        )
