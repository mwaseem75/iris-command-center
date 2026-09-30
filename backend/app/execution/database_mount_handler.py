"""Handler for database.mount (POST /v2/database-dir/mount?dir=..., %Admin_Operate:U).

Both dry_run() and execute() validate against live IRIS data; only
execute() sends the mount.

Only ReadOnly is sent in the body. We never send Cluster (on a non-cluster
system it makes IRIS try to join a cluster) and leave MirrorCatchup to IRIS.
The call is synchronous; IRIS answers 409 if already mounted and 404 if the
database doesn't exist, and we report both as failures.

The mount state comes from POST /v2/database-dir/info (its Mounted field).
Neither GET /v2/database-dir nor the free-text Status in GET /v2/databases
is reliable for that.
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

# Verify once right away, then after three growing delays.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class DatabaseMountParameters(BaseModel):
    """`Directory` is the database (the spec's dir parameter); `ReadOnly` is the
    only body field we send.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    ReadOnly: bool = False

    @field_validator("Directory")
    @classmethod
    def _validate_directory(cls, value: str) -> str:
        # Same checks as DatabaseCreateParameters.Directory.
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


# Sentinel values for _read_mounted().
_NOT_FOUND = "not_found"
_UNKNOWN = "unknown"


class DatabaseMountHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        # Tests shrink these delays.
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_mounted(self, directory: str) -> bool | str:
        """Read the Mounted flag from POST /v2/database-dir/info.

        Returns _NOT_FOUND on 404 and _UNKNOWN if Mounted is missing. Other errors
        are raised.
        """
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
        """Parse the request and check the database's current mount state (read-only)."""
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
        """Validate and read from IRIS only; never sends the mount."""
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
            data={"directory": params.Directory, "read_only": params.ReadOnly, "mounted_before": False},
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
            data={"directory": params.Directory, "read_only": params.ReadOnly, "mounted_before": False},
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Re-read /v2/database-dir/info (with retries) and check Mounted is now true."""
        target_directory = execution_result.data.get("directory")

        last_state: bool | str | None = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            if target_directory:
                # The change already happened, so a failed read here is a
                # VERIFICATION_FAILED result, not an exception.
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
                evidence={"mounted": last_state if isinstance(last_state, (bool, str)) else None},
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                "Confirmed via POST /v2/database-dir/info: database at directory "
                f"{target_directory!r} now reports Mounted=True{retry_note}."
            ),
            evidence={"mounted": True},
        )
