"""The handler for `database.dismount` — dismount an existing, currently
mounted, non-system local IRIS database. Same architecture and discipline as
database.mount: real validation against live IRIS read data in both
dry_run() and execute(), and only execute() ever calls the real write —
dry_run() never does.

Endpoint: `POST /v2/database-dir/dismount?dir=<Directory>` ("(%Admin_Operate:U)
Dismount a local database", mainspec_v2.json), with NO request body.

Request-shape evidence. IRIS's own implementation was read (read-only, via
the Atelier API) — `%Api.Admin.Endpoints.Database.Actions` on IRIS 2026.2:
  - `ValidateSemantics()` opens `SYS.Database` by directory and answers 404
    if it does not exist, before anything runs.
  - `RunDismount()` calls `SYS.Database.Dismount()` synchronously
    (`ShouldRunAsync()` is false) and returns `{}`. The ONLY database IRIS
    itself refuses is the manager's database (error #345 "Cannot dismount
    manager's database", answered as 409). Every other database —
    IRISLIB, IRISTEMP, IRISAUDIT, IRISSECURITY, ... — IRIS would dismount,
    so this handler refuses them itself (see below).
  - `NeedsRequestBody()` is false for dismount; `ResourcesOR()` is
    `%Admin_Operate` (the registry entry's privilege).

Safety policy — refused before any write, from real IRIS data:
  - Any database IRIS installs for itself (_SYSTEM_DATABASES, the
    IRIS*/ENSLIB databases observed on icc-iris-dev).
  - Any database whose GET /v2/databases entry has `MountRequired: true` —
    IRIS's own "must be mounted" flag (true for every IRIS* database live).
  - Any database the %SYS namespace uses in any role (GET /v2/namespaces).
  - Any mirrored database (POST /v2/database-dir/info `Mirrored`).
  - A directory that is not a configured database (not in GET
    /v2/databases), is unknown to IRIS (404), or is already dismounted —
    and any request whose mount state can't be determined.
The dry-run preview also names every namespace that maps this database
(from GET /v2/namespaces), so the operator sees what will be affected.

No real dismount has been executed against IRIS as of this implementation.
All tests use a fake/mock IRIS client (see
backend/tests/test_database_dismount.py).
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

# The databases IRIS installs for its own use (all observed on icc-iris-dev,
# IRIS 2026.2). Compared case-insensitively by database Name.
_SYSTEM_DATABASES = frozenset(
    {"IRISSYS", "IRISSECURITY", "IRISLIB", "IRISTEMP", "IRISLOCALDATA", "IRISAUDIT", "IRISMETRICS", "ENSLIB"}
)

# GET /v2/namespaces fields that name a database.
_NAMESPACE_DB_FIELDS = ("Globals", "Routines", "Library", "SysGlobals", "SysRoutines", "TempGlobals")

# Same bounded policy as database.mount.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)

# Sentinels for _read_info() — distinct from real values.
_NOT_FOUND = "not_found"


class DatabaseDismountParameters(BaseModel):
    """`Directory` identifies the database (the spec's `dir` query
    parameter). Dismount takes no other input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str

    @field_validator("Directory")
    @classmethod
    def _validate_directory(cls, value: str) -> str:
        # Same defensive rules as database.mount / database.create.
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

    async def _read_info(self, directory: str) -> dict[str, Any] | str:
        """Read-only POST /v2/database-dir/info (async task): the real
        `Mounted` / `Mirrored` values (None if absent or not a bool), or
        _NOT_FOUND on the documented 404."""
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
        """Every check that precedes the write, in order: request shape, the
        configured-database entry, system database, MountRequired, %SYS use,
        existence/mount state, mirroring. Read-only — safe for both
        dry_run() and execute()."""
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
        """Validation and read-only IRIS lookups only — never sends the
        dismount."""
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
        """A fresh POST /v2/database-dir/info read (independent of the
        dismount response), retried with the bounded policy above,
        confirming IRIS now reports `Mounted: false`."""
        directory = execution_result.data.get("directory")
        name = execution_result.data.get("name")

        last_state: Any = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The dismount already happened; a read failure here must
            # surface as VERIFICATION_FAILED, not an unhandled error.
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
