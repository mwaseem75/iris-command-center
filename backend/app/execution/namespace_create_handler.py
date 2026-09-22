"""The handler for `namespace.create` — this project's first Namespace
mutation, and its second real mutating operation overall (after
journal.update_purge_archived). Same architecture, same discipline: real
validation against live IRIS read data in both dry_run() and execute(),
and only execute() ever calls a real write (PUT /v2/namespace, plus an
optional POST /v2/namespace/enable-interop) — dry_run() never does.

Endpoints used (both `%Admin_Manage:U`, per mainspec_v2.json — see
docs/authorization-model.md and this handler's own privilege choice below):
  - `PUT  /v2/namespace?name=<Name>`            — create the namespace
  - `POST /v2/namespace/enable-interop?name=<Name>` — optional follow-up,
    only when the request's `Interop` flag is true. mainspec_v2.json's own
    text recommends this "right after creating a namespace". This endpoint
    follows the same async-task (202 + poll) pattern already used by audit
    records (see app/iris_client/client.py's post_async_task/
    wait_for_async_task) — reused as-is here, not reimplemented.

`PUT /v2/namespace` has since been exercised live against icc-iris-dev
(via this project's own UI wizard). That run surfaced a real behavior not
previously documented anywhere in mainspec_v2.json or this project's own
docs: IRIS does not preserve the caller's requested Name casing verbatim
— creating Name="tttt" resulted in IRIS storing and returning the
namespace as "TTTT" (confirmed directly via GET /v2/namespaces through
this project's own authenticated IRISClient, independent of any
HTTP/route layer in between). Namespace names are therefore
case-insensitive identifiers in IRIS, not case-sensitive strings; see
_same_namespace_name() below, used everywhere this handler compares a
requested name against IRIS's own namespace list (both the pre-creation
duplicate check in _validate() and the post-creation check in verify()).
Before this was found, verify() used a case-sensitive `==` comparison,
which reported a namespace IRIS had genuinely just created as
VERIFICATION_FAILED whenever the requested casing wasn't already
IRIS's own canonical form.

All tests exercising this handler still use a fake/mock IRIS client (see
backend/tests/test_namespace_create.py) — the live run above was a manual
verification step, not a change to this project's testing discipline.

A second live behavior was observed on top of the casing issue: an
immediate GET /v2/namespaces right after a successful PUT /v2/namespace
sometimes still did not list the new namespace, while a normal Refresh
moments later did. This is IRIS's own configuration-propagation delay —
not a bug in the PUT itself (execute() is unchanged) and not caching in
this project (_read_namespaces() always performs a fresh GET; there is no
cache anywhere in this handler). verify() below therefore retries its GET
a small, BOUNDED number of times with increasing delay (see
_VERIFY_RETRY_DELAYS_SECONDS) before concluding the namespace is
genuinely missing, stopping the instant it is found. This is strictly
additive to the existing verification contract: execution success is
still never treated as verification success on its own, and a namespace
that never appears across every attempt still reports
VERIFICATION_FAILED exactly as before.

Only `Globals`/`Routines`/`TempGlobals`/`Name` are ever sent to
PUT /v2/namespace — no other NamespaceEntry-only field (SysGlobals,
SysRoutines, Library) is settable through this operation; those are
IRIS-assigned, not part of the documented Namespace create/edit schema.
"""

import asyncio
import re
from typing import Any
from urllib.parse import quote

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
from app.iris_client.exceptions import IRISAsyncTaskError
from app.models.iris import DatabaseEntry, IRISEnvelope, NamespaceEntry

_NAMESPACES_PATH = "/v2/namespaces"
_DATABASES_PATH = "/v2/databases"
_NAMESPACE_PATH = "/v2/namespace"
_ENABLE_INTEROP_PATH = "/v2/namespace/enable-interop"

# Defensive input validation only. mainspec_v2.json's Namespace schema and
# its `name` query parameter are both documented as plain, unconstrained
# strings — no pattern, no length limit anywhere in the spec. This regex is
# this project's OWN conservative safety net (reject obviously malformed
# input before ever calling IRIS), not a claimed IRIS-documented rule.
# Starts with a letter (never `%` — see the dedicated system-namespace
# check below), then letters/digits/underscore, capped at a conservative
# 31 characters (a common identifier-length ceiling).
_NAMESPACE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,30}$")

# verify()'s bounded retry policy for the propagation-delay behavior
# described in the module docstring above. Three retries (four GET
# /v2/namespaces attempts total: one immediate + these three delays),
# increasing so a quick propagation is caught fast while still allowing a
# slower one time to settle. Fixed-length and non-random — never an
# unbounded/backoff-forever loop. Worst case added latency if the
# namespace never appears: 0.2 + 0.5 + 1.0 = 1.7 seconds, on top of the
# one immediate, delay-free attempt.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class NamespaceCreateParameters(BaseModel):
    """The public request shape for this operation.

    `Globals`/`Routines` are required: mainspec_v2.json's Namespace schema
    documents them as "Required on creation, optional on updates" — since
    this operation only ever creates (there is no edit/update operation in
    this project yet), that creation-time requirement is what's enforced
    here. `TempGlobals` carries no such requirement in the spec, so it
    stays optional here too, matching IRIS's own stated rule rather than
    adding a stricter one of our own.

    `Interop` is NOT part of IRIS's Namespace schema — it is this
    operation's own flag for whether to additionally call the real,
    existing `POST /v2/namespace/enable-interop` capability right after
    creation, exactly as mainspec_v2.json's own text recommends
    ("Recommended to use this right after creating a namespace"). Defaults
    to False: enabling interoperability is an extra, explicit choice,
    never an automatic side effect of a plain creation request.

    `extra="forbid"`: any field beyond these five is rejected outright
    rather than silently ignored — same defense-in-depth discipline as
    JournalPurgeArchivedParameters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    Name: str
    Globals: str
    Routines: str
    TempGlobals: str | None = None
    Interop: bool = False

    @field_validator("Name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Name is required and cannot be empty.")
        if value.startswith("%"):
            raise ValueError(
                "System-namespace names (starting with %) cannot be created through "
                "this operation."
            )
        if not _NAMESPACE_NAME_PATTERN.match(value):
            raise ValueError(
                "Name must start with a letter and contain only letters, digits, and "
                "underscores (max 31 characters)."
            )
        return value

    @field_validator("Globals", "Routines")
    @classmethod
    def _validate_required_database_field(cls, value: str) -> str:
        if not value:
            raise ValueError("This field is required and cannot be empty.")
        return value


def _failure(detail: str) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail)


def _same_namespace_name(a: str | None, b: str | None) -> bool:
    """IRIS namespace names are case-insensitive identifiers, not
    case-sensitive strings — observed live against icc-iris-dev:
    requesting creation of Name="tttt" results in IRIS storing and
    returning the namespace as "TTTT" (confirmed via a direct GET
    /v2/namespaces call through this project's own authenticated
    IRISClient, independent of any HTTP/route layer). A plain `==`
    comparison against existing namespace names therefore both (a) misses
    a genuinely-existing namespace whose stored casing differs from the
    caller's input — causing verify() below to report a successful
    creation as VERIFICATION_FAILED — and (b) lets _validate() below miss
    a genuine name collision when the caller's casing differs from the
    existing entry's."""
    return a is not None and b is not None and a.casefold() == b.casefold()


class NamespaceCreateHandler(OperationHandler):
    """Requires an IRISClient, supplied by the caller (typically a route),
    so this handler can be unit-tested with a fake/mock client instead of a
    real one — same pattern as JournalUpdatePurgeArchivedHandler."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        # Overridable only so tests can shrink real wall-clock delays to
        # ~0 without changing the retry COUNT/behavior being tested (see
        # backend/tests/test_namespace_create.py) — production code never
        # passes this, so it always gets the real policy above.
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _read_namespaces(self) -> list[NamespaceEntry]:
        raw = await self._iris_client.get(_NAMESPACES_PATH)
        envelope = IRISEnvelope[list[NamespaceEntry]].model_validate(raw)
        return envelope.result

    async def _read_database_names(self) -> set[str]:
        raw = await self._iris_client.get(_DATABASES_PATH)
        envelope = IRISEnvelope[list[DatabaseEntry]].model_validate(raw)
        return {db.Name for db in envelope.result}

    async def _validate(
        self, request: OperationRequest
    ) -> tuple[NamespaceCreateParameters, None] | tuple[None, HandlerExecutionResult]:
        """Parses and validates the request. Only ever performs READ-ONLY
        IRIS calls (namespace list, database list) — never PUT/POST — so
        it is safe to call from both dry_run() and execute() unchanged.
        Returns (params, None) on success or (None, failure_result) with a
        specific, human-readable reason on any validation failure.
        """
        try:
            params = NamespaceCreateParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid namespace.create request ({field}): {first_error['msg']}")

        existing_namespaces = await self._read_namespaces()
        if any(_same_namespace_name(ns.Name, params.Name) for ns in existing_namespaces):
            return None, _failure(f"Namespace {params.Name!r} already exists.")

        existing_databases = await self._read_database_names()
        for field_name, db_name in (
            ("Globals", params.Globals),
            ("Routines", params.Routines),
            ("TempGlobals", params.TempGlobals),
        ):
            if db_name is not None and db_name not in existing_databases:
                return None, _failure(
                    f"{field_name} database {db_name!r} does not exist. "
                    f"Known databases: {', '.join(sorted(existing_databases)) or '(none)'}."
                )

        return params, None

    async def dry_run(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        """Validation and read-only IRIS lookups only — never calls
        put()/post_async_task()."""
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        interop_note = " and enable interoperability" if params.Interop else ""
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: would create namespace {params.Name!r} "
                f"(Globals={params.Globals}, Routines={params.Routines}, "
                f"TempGlobals={params.TempGlobals or '(IRIS default)'}){interop_note}. "
                "No PUT or POST request was sent."
            ),
            data={
                "name": params.Name,
                "globals": params.Globals,
                "routines": params.Routines,
                "temp_globals": params.TempGlobals,
                "interop_requested": params.Interop,
            },
        )

    async def execute(
        self, request: OperationRequest, context: ExecutionContext
    ) -> HandlerExecutionResult:
        params, failure = await self._validate(request)
        if failure is not None:
            return failure

        body: dict[str, Any] = {"Globals": params.Globals, "Routines": params.Routines}
        if params.TempGlobals is not None:
            body["TempGlobals"] = params.TempGlobals

        # `put_raw`'s shape is documented (result: Namespace, i.e.
        # Globals/Routines/TempGlobals only — Name is the query parameter,
        # never a body/response field per mainspec_v2.json) but not yet
        # live-verified; deliberately not parsed into a strict model here,
        # the same caution first-mutation-implementation.md's original
        # journal handler used before its own live verification.
        await self._iris_client.put(f"{_NAMESPACE_PATH}?name={quote(params.Name)}", json=body)

        interop_enabled = False
        interop_detail = ""
        if params.Interop:
            try:
                task_id = await self._iris_client.post_async_task(
                    f"{_ENABLE_INTEROP_PATH}?name={quote(params.Name)}"
                )
                await self._iris_client.wait_for_async_task(task_id)
                interop_enabled = True
                interop_detail = " Interoperability was also enabled."
            except IRISAsyncTaskError as exc:
                # The namespace itself was already created successfully by
                # the PUT above — that is this operation's primary purpose,
                # so a failure of the optional, secondary interop step does
                # NOT turn the overall outcome into a failure. It is
                # reported plainly instead, both in the detail text and in
                # `data`, so it is never silently lost.
                interop_detail = (
                    f" The namespace was created, but enabling interoperability failed: {exc}"
                )

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Namespace {params.Name!r} created.{interop_detail}",
            data={
                "name": params.Name,
                "globals": params.Globals,
                "routines": params.Routines,
                "temp_globals": params.TempGlobals,
                "interop_requested": params.Interop,
                "interop_enabled": interop_enabled,
            },
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Post-action verification: a fresh GET /v2/namespaces (the same
        already-existing, already-verified list endpoint this project's
        Namespaces view already uses) — independent of the PUT response —
        confirming the namespace actually exists with the requested
        Globals/Routines databases.

        Retries the GET a small, bounded number of times with increasing
        delay (see _VERIFY_RETRY_DELAYS_SECONDS) if the namespace is not
        yet present, to absorb IRIS's own observed configuration-
        propagation delay (see module docstring) — stopping the instant
        it is found. Never retries a FIELD mismatch (Globals/Routines):
        once a namespace by that name is found, that check runs exactly
        once, same as before — retrying is only ever about presence, per
        the propagation-delay behavior actually observed."""
        target_name = execution_result.data.get("name")

        match = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1

            namespaces = await self._read_namespaces()
            # Case-insensitive match — see _same_namespace_name()'s
            # docstring: IRIS may return the namespace under a different
            # casing than the caller requested (observed live:
            # "tttt" -> "TTTT"), and a genuinely-created namespace must
            # not be reported as missing just because of that.
            match = next((ns for ns in namespaces if _same_namespace_name(ns.Name, target_name)), None)
            if match is not None:
                break

        if match is None:
            attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Expected namespace {target_name!r} to exist after creation, but it "
                    f"still did not appear in GET /v2/namespaces after {attempts_made} "
                    f"attempts (retried with delays of {attempted_delays})."
                ),
            )

        expected_globals = execution_result.data.get("globals")
        expected_routines = execution_result.data.get("routines")
        mismatches = []
        if expected_globals is not None and match.Globals != expected_globals:
            mismatches.append(f"Globals is {match.Globals!r}, expected {expected_globals!r}")
        if expected_routines is not None and match.Routines != expected_routines:
            mismatches.append(f"Routines is {match.Routines!r}, expected {expected_routines!r}")

        if mismatches:
            return PostActionVerificationResult(
                status=PostActionVerificationStatus.VERIFICATION_FAILED,
                detail=(
                    f"Namespace {match.Name!r} exists but does not match the request: "
                    + "; ".join(mismatches)
                ),
            )

        retry_note = "" if attempts_made == 1 else f" (took {attempts_made} attempts)"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail=(
                f"Confirmed via GET: namespace {match.Name!r} now exists "
                f"(Globals={match.Globals}, Routines={match.Routines}, "
                f"TempGlobals={match.TempGlobals}){retry_note}."
            ),
        )
