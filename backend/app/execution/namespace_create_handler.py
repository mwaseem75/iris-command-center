"""Handler for namespace.create (PUT /v2/namespace?name=..., %Admin_Manage:U).

Both dry_run() and execute() validate against live IRIS data; only
execute() sends the PUT. If Interop is requested we also call
POST /v2/namespace/enable-interop afterwards (an async task, polled with
the client's existing post_async_task/wait_for_async_task).

Two things we found testing against a real instance:
- IRIS uppercases namespace names ("tttt" is stored as "TTTT"), so names
  are compared case-insensitively (_same_namespace_name).
- Right after the PUT, GET /v2/namespaces sometimes doesn't list the new
  namespace yet. verify() retries a few times before giving up.

Only Name, Globals, Routines and TempGlobals are sent to IRIS.
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

# Our own sanity check (IRIS doesn't document a pattern): starts with a
# letter (so no % system namespaces), then letters/digits/underscore, at
# most 31 characters.
_NAMESPACE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,30}$")

# verify() retry schedule: check once, then after 0.2s, 0.5s and 1.0s
# (at most 1.7s extra).
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.2, 0.5, 1.0)


class NamespaceCreateParameters(BaseModel):
    """Request fields.

    Globals and Routines are required when creating a namespace; TempGlobals
    is optional. Interop isn't an IRIS field: if true we also enable
    interoperability after creating (off by default). Unknown fields are
    rejected.
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
    """Compare namespace names case-insensitively, since IRIS uppercases them.
    Used for both the duplicate check and verify().
    """
    return a is not None and b is not None and a.casefold() == b.casefold()


class NamespaceCreateHandler(OperationHandler):
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
        """Parse and validate the request. Only reads from IRIS (namespace and
        database lists), so it's safe for both dry_run() and execute(). Returns
        (params, None) or (None, failure_result).
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
        """Validate and read from IRIS only; never sends the PUT or POST."""
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

        # Not parsing the PUT response; verify() checks what was created.
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
                # The namespace itself was created, so a failed interop step doesn't
                # fail the whole operation. It's reported in the detail and in `data`.
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
        """Check the namespace now exists with the requested Globals/Routines, via a
        fresh GET /v2/namespaces.

        Retries a few times if it isn't listed yet (see module docstring). Once
        it's found, the database check runs once; we only retry for presence.
        """
        target_name = execution_result.data.get("name")

        match = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1

            namespaces = await self._read_namespaces()
            # Case-insensitive: IRIS may have uppercased the name.
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
