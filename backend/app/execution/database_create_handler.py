"""The handler for `database.create` — this project's first Database
mutation, and its third real mutating operation overall (after
journal.update_purge_archived and namespace.create). Same architecture,
same discipline: real validation against live IRIS read data in both
dry_run() and execute(), and only execute() ever calls a real write
(POST /v2/database-dir) — dry_run() never does.

Endpoint used (`%Admin_Manage:U`, per mainspec_v2.json's own summary for
this operation, "(%Admin_Manage:U) Create a local database" — already a
CONFIRMED member of this project's `IRISPrivilege` enum, same privilege
namespace.create uses, no new privilege invented):
  - `POST /v2/database-dir` — create the database.

Unlike `PUT /v2/namespace?name=<Name>`, this endpoint is NOT keyed by a
caller-supplied Name at all — mainspec_v2.json's request schema for this
operation has exactly one required field, `Directory`, plus optional
`ResourceName`, `Size`, `BlockSize`, `VolThreshold`, `GlobalJournalState`,
`Encrypted`, `MirrorDBName`, `MirrorSetName`, `EncryptionKeyID`. There is
no `Name` field anywhere in this request schema — confirmed by reading
spec/mainspec_v2.json directly, not assumed. IRIS databases are identified
by Directory; the `Name` shown by `GET /v2/databases` (this project's
DatabaseEntry.Name) is IRIS's own derived value, not something this
project sets. This handler therefore accepts `Directory` (required) plus
a small, useful subset of the documented optional fields (`ResourceName`,
`Size`, `GlobalJournalState`, `Encrypted`) — not exhaustively every
documented field, matching namespace.create's own precedent of wiring a
useful subset rather than the full schema.

Response shape: `POST /v2/database-dir`'s documented `201 Created` body is
`{status, console, result}` with `result` typed as `LocalDatabase` — a
schema that (per mainspec_v2.json) does not itself include `Directory` or
`Name`. Deliberately not parsed or relied upon here, same caution
namespace.create's own module docstring describes for its own unverified
PUT response: execute() discards the raw response entirely. verify()
below is the sole source of truth for what was actually created.

Two lessons already learned (and fixed) on namespace.create were applied
here proactively, before ever being needed live — one of them held up,
the other did not, and was itself found and fixed after a real rehearsal:

1. Bounded-retry post-action verification. namespace.create's own verify()
   was found, live, to sometimes miss a just-created namespace on an
   immediate GET, because IRIS's own configuration propagation is not
   always instant. verify() below retries with the same small, bounded,
   increasing-delay policy (see _VERIFY_RETRY_DELAYS_SECONDS) — this part
   held up and remains correct.

2. Comparisons should not assume exact string equality where IRIS itself
   may normalize. Directory paths are filesystem paths on a Linux IRIS
   instance (icc-iris-dev) and are therefore genuinely case-SENSITIVE —
   this handler does NOT case-fold Directory comparisons. The one real,
   observed IRIS convention this project HAS confirmed for Directory
   (every value GET /v2/databases has ever returned ends with a trailing
   slash — see docs/api-capability-matrix.md) is normalized for
   comparison (see _normalize_directory()).

verify() originally polled the SAME list endpoint _validate() uses for
its own collision checks, `GET /v2/databases`. A real rehearsal (creating
a database at `/usr/irissys/mgr/iccrehearsal/`) showed this was wrong:
`POST /v2/database-dir` genuinely created and mounted the database
(confirmed independently via the container's own filesystem — a real
IRIS.DAT/iris.lck — and IRIS's own messages.log logging
`[Database.MountedRW] Mounted database /usr/irissys/mgr/iccrehearsal/ ...
read-write`), but it never appeared in `GET /v2/databases`. Inspecting
`/usr/irissys/iris.cpf`'s `[Databases]` section directly showed why:
that list enumerates the PERSISTENT, CPF-registered `Config.Databases`
entries — a different data source than "IRIS currently has a mounted
database at this directory". Creating via `POST /v2/database-dir` does
not add a `[Databases]` CPF entry, so the newly-created database could
never appear there no matter how many times or how long verify() retried
— this was a wrong-endpoint bug, not a propagation-delay one, and no
amount of retrying could ever have fixed it.

The fix, and what verify() does now: `GET /v2/database-dir?dir=<Directory>`
— mainspec_v2.json's own single-database detail endpoint for this exact
resource family, keyed by the `dir` query parameter (`DBDirectory` in the
spec's components — the same Directory this handler actually requested
and controls). Confirmed live (via the same rehearsal, using this
project's own authenticated IRISClient directly, independent of any
route/handler code) to return HTTP 200 with a real `LocalDatabase` body
for a database `GET /v2/databases` does not list. A database IRIS does
not yet consider to exist at that directory returns the endpoint's
documented `404` (`NotFound`) response — treated as "not yet visible, keep
retrying" within the bounded policy; any other error (400/401/403/500) is
left to propagate rather than being swallowed as a false "keep retrying"
signal, since that would hide a genuine failure.

`_validate()`'s own use of `GET /v2/databases` for its pre-creation
directory/derived-name collision checks is UNCHANGED and correct as-is:
that check is specifically about the persistent, CONFIGURED database
list (exactly what `GET /v2/databases` enumerates) — a different,
correctly-scoped concern from "did the database I just created actually
appear".

All tests use a fake/mock IRIS client (see
backend/tests/test_database_create.py) — the live rehearsal above was a
manual verification step, not a change to this project's testing
discipline, and no test performs a real database creation.
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

# Defensive input validation only. mainspec_v2.json's Directory field is
# documented only as "Required." with a plain string type — no pattern, no
# length limit. This regex is this project's OWN conservative safety net
# (reject obviously malformed input before ever calling IRIS), not a
# claimed IRIS-documented rule — same discipline as namespace.create's own
# _NAMESPACE_NAME_PATTERN. Requires an absolute (Unix-style) path — every
# real Directory this project has observed (see
# docs/api-capability-matrix.md) is absolute — with no NUL byte, capped at
# a generous 500 characters.
_DIRECTORY_PATTERN = re.compile(r"^/[^\0]{0,499}$")

# verify()'s bounded retry policy — identical values to namespace.create's
# own (see app/execution/namespace_create_handler.py): three retries (four
# GET /v2/database-dir attempts total: one immediate + these three
# delays), increasing, fixed-length, never unbounded. Worst case added
# latency if the database never appears: 0.2 + 0.5 + 1.0 = 1.7 seconds.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class DatabaseCreateParameters(BaseModel):
    """The public request shape for this operation.

    `Directory` is the only field mainspec_v2.json marks "Required." for
    `POST /v2/database-dir`. The remaining fields are a useful subset of
    that endpoint's documented OPTIONAL fields (BlockSize, VolThreshold,
    MirrorDBName, MirrorSetName, EncryptionKeyID exist in the spec too but
    are not wired up here — a deliberately smaller, focused surface for
    this first pass, same precedent as namespace.create not wiring every
    NamespaceEntry-adjacent field either).

    `extra="forbid"`: any field beyond these four is rejected outright
    rather than silently ignored — same defense-in-depth discipline as
    NamespaceCreateParameters.
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
    """The one real, observed IRIS convention this project has confirmed
    for Directory values (every entry GET /v2/databases has ever returned
    ends with a trailing slash — see docs/api-capability-matrix.md),
    normalized so a caller-supplied Directory differing only by a
    missing/extra trailing slash still compares equal to the real value.
    Deliberately NOT case-folded — Directory is a Linux filesystem path on
    this project's IRIS instance and is genuinely case-sensitive; folding
    case here would be an unconfirmed guess, not an observed fact."""
    return f"{directory.rstrip('/')}/"


def _derive_expected_name(directory: str) -> str | None:
    """This project's OWN defensive heuristic — NOT a documented IRIS
    rule — inferred from every existing real database on icc-iris-dev:
    each one's Name matches its Directory's final path segment, uppercased
    (e.g. ".../mgr/user/" -> "USER", ".../mgr/iristemp/" -> "IRISTEMP";
    see docs/api-capability-matrix.md). Used ONLY for pre-creation
    collision defense in _validate() below (catching a request that would
    likely collide with an existing database's derived name even when its
    literal Directory string differs) — NEVER for post-action verification,
    which only ever trusts a fresh GET's real, observed Directory (see
    verify() below). Returns None for a directory with no non-empty
    segment (already rejected by DatabaseCreateParameters' own validator,
    but handled defensively here too)."""
    segments = [segment for segment in directory.split("/") if segment]
    if not segments:
        return None
    return segments[-1].upper()


class DatabaseCreateHandler(OperationHandler):
    """Requires an IRISClient, supplied by the caller (typically a route),
    so this handler can be unit-tested with a fake/mock client instead of a
    real one — same pattern as NamespaceCreateHandler."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        # Overridable only so tests can shrink real wall-clock delays to
        # ~0 without changing the retry COUNT/behavior being tested (see
        # backend/tests/test_database_create.py) — production code never
        # passes this, so it always gets the real policy above.
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_databases(self) -> list[DatabaseEntry]:
        raw = await self._iris_client.get(_DATABASES_PATH)
        envelope = IRISEnvelope[list[DatabaseEntry]].model_validate(raw)
        return envelope.result

    async def _read_database_dir(self, directory: str) -> dict[str, Any] | None:
        """GET /v2/database-dir?dir=<directory> — mainspec_v2.json's own
        single-database detail endpoint, keyed by the documented `dir`
        query parameter (`DBDirectory`). Used ONLY by verify() below — see
        the module docstring for why this, and not GET /v2/databases, is
        the correct post-action verification source.

        Returns the real `result` (LocalDatabase) dict when IRIS reports a
        database exists at `directory` (HTTP 200) — deliberately kept as a
        raw dict rather than parsed into a strict model, same caution this
        project applies to every not-exhaustively-documented response
        shape. Returns None when IRIS reports no database exists there yet
        (the endpoint's documented `404` "NotFound" response) — the
        correct "not yet visible" signal for verify()'s retry loop. Any
        other error (400/401/403/500) is NOT treated as "not found" and is
        left to propagate — swallowing it as a false "keep retrying" would
        hide a genuine failure.
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
        """Parses and validates the request. Only ever performs a READ-ONLY
        IRIS call (database list) — never POST — so it is safe to call from
        both dry_run() and execute() unchanged. Returns (params, None) on
        success or (None, failure_result) with a specific, human-readable
        reason on any validation failure.
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

        # Also rejects an "obviously unsafe/system" target: every existing
        # system database (IRISSYS, IRISLIB, IRISTEMP, ...) is already
        # present in existing_databases, so a request whose directory would
        # derive to one of their real Names is caught here too — without
        # hardcoding a separate "system database names" list this project
        # cannot actually confirm is complete or stable across instances.
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
        """Validation and read-only IRIS lookups only — never calls post()."""
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

        # The 201 response's `result` (LocalDatabase) is documented but not
        # yet live-verified, and doesn't itself carry Directory/Name (see
        # module docstring) — deliberately discarded. verify() below is the
        # sole source of truth for what was actually created.
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
        """Post-action verification: a fresh GET /v2/database-dir?dir=<Directory>
        (mainspec_v2.json's own single-database detail endpoint, keyed by
        the exact Directory this handler requested) — independent of the
        POST response — confirming a database actually exists there. See
        the module docstring for why this endpoint, and NOT GET
        /v2/databases (used only by _validate()'s pre-creation collision
        checks, a different concern), is the correct source here: a
        database created via POST /v2/database-dir is not necessarily
        added to the persistent, CPF-registered list GET /v2/databases
        enumerates, so checking that list can never find it, no matter how
        many times or how long this retried — confirmed via a real
        rehearsal (see module docstring).

        Retries the GET a small, bounded number of times with increasing
        delay (see _VERIFY_RETRY_DELAYS_SECONDS) if IRIS reports the
        directory doesn't exist yet (its documented 404 response), to
        absorb IRIS's own observed configuration-propagation delay —
        stopping the instant it is found. Matches strictly on Directory
        (the field this handler actually requested and controls), never a
        guessed/derived Name — see _derive_expected_name()'s own docstring
        for why that heuristic is confined to pre-creation validation
        only; this endpoint's response doesn't even include a Name field
        to guess from (see module docstring)."""
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
