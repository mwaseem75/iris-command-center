"""Handler for database.create (POST /v2/database-dir, %Admin_Manage:U).

Both dry_run() and execute() validate against live IRIS data; only
execute() sends the POST.

IRIS identifies databases by Directory; there's no Name field in this
request (the Name in GET /v2/databases is derived by IRIS). We accept
Directory plus a few optional fields (ResourceName, Size,
GlobalJournalState, Encrypted).

Verification gotcha: a database created with POST /v2/database-dir is
mounted and usable, but it does NOT show up in GET /v2/databases, because
that list comes from the CPF [Databases] section. So verify() checks
GET /v2/database-dir?dir=<Directory> instead (404 means "not there yet"),
retrying briefly. The pre-create collision checks still use
GET /v2/databases, since those are about configured databases.

Directories are compared case-sensitively (Linux paths), ignoring a
trailing slash.
"""

import asyncio
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

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
from app.iris_client.exceptions import IRISResponseError
from app.models.iris import DatabaseEntry, IRISEnvelope

_DATABASES_PATH = "/v2/databases"
_DATABASE_DIR_PATH = "/v2/database-dir"

# Our own sanity check, not an IRIS rule: an absolute path, no NUL byte,
# at most 500 characters.
_DIRECTORY_PATTERN = re.compile(r"^/[^\0]{0,499}$")

# verify() retry schedule: check once, then after 0.2s, 0.5s and 1.0s
# (at most 1.7s extra), same as namespace.create.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class DatabaseCreateParameters(BaseModel):
    """Request fields. Directory is the only required one; the others are a
    subset of the optional fields IRIS accepts. Unknown fields are rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Directory: str
    ResourceName: str | None = None
    Size: int | None = None
    GlobalJournalState: bool | None = None
    Encrypted: bool | None = None

    @field_validator("Directory")
    @classmethod
    def _validate_directory(cls, value: str) -> str:
        if not value:
            raise ValueError("Directory is required and cannot be empty.")
        if not value.startswith("/"):
            raise ValueError("Directory must be an absolute path (starting with '/').")
        if ".." in value.split("/"):
            raise ValueError("Directory must not contain '..' path segments.")
        if not _DIRECTORY_PATTERN.match(value):
            raise ValueError("Directory contains invalid characters or is too long.")
        return value

    @field_validator("ResourceName")
    @classmethod
    def _validate_resource_name(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("ResourceName cannot be empty when provided.")
        return value

    @field_validator("Size")
    @classmethod
    def _validate_size(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Size must be zero or a positive integer when provided.")
        return value


def _failure(detail: str) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail)


def _normalize_directory(directory: str) -> str:
    """Normalize a directory for comparison: add a trailing slash (IRIS always
    returns one). Case is kept because these are Linux paths.
    """
    return f"{directory.rstrip('/')}/"


def _derive_expected_name(directory: str) -> str | None:
    """Guess the database Name IRIS will derive: the last path segment,
    uppercased (".../mgr/user/" -> "USER").

    Only used to catch likely name collisions before creating. verify() never
    relies on it. Returns None if there's no usable segment.
    """
    segments = [segment for segment in directory.split("/") if segment]
    if not segments:
        return None
    return segments[-1].upper()


class DatabaseCreateHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        # Tests shrink these delays; production uses the defaults above.
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_databases(self) -> list[DatabaseEntry]:
        raw = await self._iris_client.get(_DATABASES_PATH)
        envelope = IRISEnvelope[list[DatabaseEntry]].model_validate(raw)
        return envelope.result

    async def _read_database_dir(self, directory: str) -> dict[str, Any] | None:
        """GET /v2/database-dir?dir=<directory>, used by verify().

        Returns the result dict when the database exists, None on 404 (not there
        yet). Other errors are raised so a real failure isn't mistaken for
        "keep waiting".
        """
        try:
            raw = await self._iris_client.get(_DATABASE_DIR_PATH, params={"dir": directory})
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return None
            raise
        return raw.get("result") if isinstance(raw, dict) else None

    async def _validate(
        self, request: OperationRequest
    ) -> tuple[DatabaseCreateParameters, None] | tuple[None, HandlerExecutionResult]:
        """Parse and validate the request. Only reads the database list, so it's
        safe for both dry_run() and execute(). Returns (params, None) or
        (None, failure_result).
        """
        try:
            params = DatabaseCreateParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid database.create request ({field}): {first_error['msg']}")

        existing_databases = await self._read_databases()

        requested_directory = _normalize_directory(params.Directory)
        for db in existing_databases:
            if _normalize_directory(db.Directory) == requested_directory:
                return None, _failure(
                    f"A database already exists at directory {params.Directory!r} "
                    f"(Name={db.Name!r})."
                )

        # This also blocks IRIS's own databases: they're already in the list,
        # so a directory that would derive to e.g. IRISSYS collides here.
        expected_name = _derive_expected_name(params.Directory)
        if expected_name is not None:
            for db in existing_databases:
                if db.Name.upper() == expected_name:
                    return None, _failure(
                        f"A database named {db.Name!r} already exists, and this "
                        f"directory would be expected to resolve to that same name. "
                        "Choose a different directory."
                    )

        return params, None

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Validate and read from IRIS only; never sends the POST."""
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: would create a database at directory {params.Directory!r}"
                f"{f', ResourceName={params.ResourceName!r}' if params.ResourceName else ''}. "
                "No POST request was sent."
            ),
            data={
                "directory": params.Directory,
                "resource_name": params.ResourceName,
                "size": params.Size,
                "global_journal_state": params.GlobalJournalState,
                "encrypted": params.Encrypted,
            },
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        body: dict[str, Any] = {"Directory": params.Directory}
        if params.ResourceName is not None:
            body["ResourceName"] = params.ResourceName
        if params.Size is not None:
            body["Size"] = params.Size
        if params.GlobalJournalState is not None:
            body["GlobalJournalState"] = params.GlobalJournalState
        if params.Encrypted is not None:
            body["Encrypted"] = params.Encrypted

        # The response body isn't needed; verify() checks what was created.
        await self._iris_client.post(_DATABASE_DIR_PATH, json=body)

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Database creation requested at directory {params.Directory!r}.",
            data={
                "directory": params.Directory,
                "resource_name": params.ResourceName,
            },
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Check the database now exists with GET /v2/database-dir?dir=<Directory>.

        We can't use GET /v2/databases here (see the module docstring). Retries a
        few times on 404 in case IRIS is slow to report it, and matches on the
        Directory we asked for.
        """
        target_directory = execution_result.data.get("directory")

        result_data: dict[str, Any] | None = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1

            if target_directory:
                result_data = await self._read_database_dir(target_directory)
                if result_data is not None:
                    break

        if result_data is None:
            attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected a database at directory {target_directory!r} to exist "
                    f"after creation, but GET /v2/database-dir still reported it missing "
                    f"after {attempts_made} attempts (retried with delays of "
                    f"{attempted_delays})."
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                f"Confirmed via GET /v2/database-dir: database now exists at directory "
                f"{target_directory!r} (ResourceName={result_data.get('ResourceName')!r}, "
                f"ReadOnly={result_data.get('ReadOnly')}, "
                f"GlobalJournalState={result_data.get('GlobalJournalState')}){retry_note}."
            ),
        )
