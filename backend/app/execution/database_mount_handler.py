"""The handler for `database.mount` — mount an existing local IRIS database.
Same architecture and discipline as database.create: real validation
against live IRIS read data in both dry_run() and execute(), and only
execute() ever calls the real write (POST /v2/database-dir/mount) —
dry_run() never does.

Endpoint used (`%Admin_Operate:U`, per mainspec_v2.json's own summary,
"(%Admin_Operate:U) Mount a local database"):
  - `POST /v2/database-dir/mount?dir=<Directory>` — keyed by the
    documented `dir` query parameter (`DBDirectory`), with an optional
    JSON body of `ReadOnly`, `Cluster`, `MirrorCatchup`. Only `ReadOnly` is
    wired up here. `Cluster` is deliberately never sent: the spec says
    setting it on a non-cluster member makes the system "try to join the
    cluster" — far outside this operation's intent. `MirrorCatchup` is
    left to IRIS's own default (it is ignored for non-mirrored databases).
  - Synchronous: documented `200 Success` (a plain BaseResponseWithResult,
    no result schema), unlike database.info/integrity-check's 202 async
    tasks. The response body is discarded; verify() is the sole source of
    truth.
  - Documented `409` "database is already mounted" — reported as a clear
    handler FAILURE, never as an unexpected error. Documented `404` "the
    specified database does not exist" — likewise a clear FAILURE.

Mount-state source: `POST /v2/database-dir/info` (async task), whose
result carries a `Mounted: bool` field — already observed live, populated,
via database.info (see app/models/iris.py's DatabaseInfoResult). Neither
GET /v2/database-dir (LocalDatabase has no mount field at all) nor GET
/v2/databases (a free-text `Status`, whose dismounted value has never been
observed) is a reliable mount signal. Only the `Mounted` field itself is
read — the rest of the info result is not parsed, since a DISMOUNTED
database's info result has never been observed live and its other fields
are not assumed to match the mounted case.

As of this implementation, no real mount has been executed against IRIS:
every database on icc-iris-dev is already mounted, and this project has no
dismount operation. All tests use a fake/mock IRIS client (see
backend/tests/test_database_mount.py).
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

_MOUNT_PATH = "/v2/database-dir/mount"
_INFO_PATH = "/v2/database-dir/info"

# Same bounded policy as database.create/namespace.create: one immediate
# check plus three increasing delays, never unbounded.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class DatabaseMountParameters(BaseModel):
    """`Directory` identifies the database (the spec's `dir` query
    parameter); `ReadOnly` is the one documented body field wired up (see
    module docstring for why `Cluster`/`MirrorCatchup` are not)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    ReadOnly: bool = False

    @field_validator("Directory")
    @classmethod
    def _validate_directory(cls, value: str) -> str:
        # Same defensive rules as DatabaseCreateParameters.Directory.
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


# Sentinels for _read_mounted() — distinct from True/False.
_NOT_FOUND = "not_found"
_UNKNOWN = "unknown"


class DatabaseMountHandler(OperationHandler):
    """Requires an IRISClient supplied by the caller (typically a route), so
    it can be unit-tested with a fake/mock client."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        # Overridable only so tests can shrink wall-clock delays to ~0.
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_mounted(self, directory: str) -> bool | str:
        """Read-only: POST /v2/database-dir/info (async task) and return its
        real `Mounted` bool. Returns _NOT_FOUND on the endpoint's documented
        404, _UNKNOWN if `Mounted` is absent or not a bool (never guessed).
        Any other error propagates rather than being misread as a state."""
        try:
            task_id = await self._iris_client.post_async_task(_INFO_PATH, params={"dir": directory})
            task = await self._iris_client.wait_for_async_task(task_id)
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return _NOT_FOUND
            raise
        result = task.get("Result") if isinstance(task, dict) else None
        mounted = result.get("Mounted") if isinstance(result, dict) else None
        return mounted if isinstance(mounted, bool) else _UNKNOWN

    async def _validate(
        self, request: OperationRequest
    ) -> tuple[DatabaseMountParameters, None] | tuple[None, HandlerExecutionResult]:
        """Parses the request and checks the database's real, current mount
        state. Read-only — safe for both dry_run() and execute()."""
        try:
            params = DatabaseMountParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid database.mount request ({field}): {first_error['msg']}")

        mounted = await self._read_mounted(params.Directory)
        if mounted == _NOT_FOUND:
            return None, _failure(
                f"No database exists at directory {params.Directory!r}.",
                directory=params.Directory,
            )
        if mounted is True:
            return None, _failure(
                f"The database at directory {params.Directory!r} is already mounted — "
                "nothing to do.",
                directory=params.Directory,
                already_mounted=True,
            )
        if mounted is not False:
            return None, _failure(
                f"Could not determine the current mount state of {params.Directory!r} "
                "(IRIS's database info did not include a Mounted value).",
                directory=params.Directory,
            )
        return params, None

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Validation and read-only IRIS lookups only — never calls post()."""
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: database at directory {params.Directory!r} is currently "
                f"dismounted and would be mounted {'read-only' if params.ReadOnly else 'read-write'}. "
                "No mount request was sent."
            ),
            data={"directory": params.Directory, "read_only": params.ReadOnly},
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        try:
            await self._iris_client.post(
                _MOUNT_PATH,
                params={"dir": params.Directory},
                json={"ReadOnly": params.ReadOnly},
            )
        except IRISResponseError as exc:
            if exc.status_code == 409:
                return _failure(
                    f"IRIS reported the database at directory {params.Directory!r} is "
                    "already mounted (HTTP 409) — nothing was changed.",
                    directory=params.Directory,
                    already_mounted=True,
                )
            if exc.status_code == 404:
                return _failure(
                    f"IRIS reported no database exists at directory {params.Directory!r} "
                    "(HTTP 404).",
                    directory=params.Directory,
                )
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Mount requested for database at directory {params.Directory!r}.",
            data={"directory": params.Directory, "read_only": params.ReadOnly},
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """A fresh POST /v2/database-dir/info read (independent of the mount
        response), retried with the bounded policy above, confirming IRIS
        now reports `Mounted: true` for this directory."""
        target_directory = execution_result.data.get("directory")

        last_state: bool | str | None = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            if target_directory:
                # The mount itself already happened; a read failure here must
                # surface as VERIFICATION_FAILED, not an unhandled error.
                try:
                    last_state = await self._read_mounted(target_directory)
                except IRISClientError as exc:
                    last_state = f"read error ({exc.__class__.__name__})"
                    continue
                if last_state is True:
                    break

        if last_state is not True:
            attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected the database at directory {target_directory!r} to be mounted, "
                    f"but POST /v2/database-dir/info last reported {last_state!r} for Mounted "
                    f"after {attempts_made} attempts (retried with delays of {attempted_delays})."
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                "Confirmed via POST /v2/database-dir/info: database at directory "
                f"{target_directory!r} now reports Mounted=True{retry_note}."
            ),
        )
