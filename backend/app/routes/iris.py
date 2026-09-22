"""Routes for the VERIFIED, read-only IRIS SysAdmin REST API endpoints.
All authentication/session handling is delegated entirely to the shared
IRISClient (via the get_iris_client dependency) — no route here performs
its own login or holds its own token.

No route in this module ever changes IRIS state. GET /security/audit/records
and GET /databases/info are the exceptions to "only GET requests are made
against IRIS": IRIS itself models each as a (potentially long-running)
async task, started via POST and polled via GET (see
app/iris_client/client.py's post_async_task/wait_for_async_task and
docs/api-capability-matrix.md) — that POST is IRIS's own read/query
mechanism, not a mutation, and is not gated by this project's
authorization/confirmation/execution framework, the same way every other
route here isn't.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_iris_client
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import (
    IRISAsyncTaskError,
    IRISAuthError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)
from app.models.iris import (
    AuditEnabledResult,
    AuditRecordEntry,
    DatabaseEntry,
    DatabaseInfoResult,
    DatabaseIntegrityCheckResult,
    ExternalLanguageServerEntry,
    InfoResult,
    IRISEnvelope,
    JournalSettings,
    NamespaceEntry,
    ProcessEntry,
    TaskEntry,
    WebAppDetail,
    WebAppEntry,
)

router = APIRouter(prefix="/api/iris", tags=["iris"])

_IRIS_CLIENT_ERRORS = (
    IRISAuthError,
    IRISConnectionError,
    IRISTimeoutError,
    IRISResponseError,
    IRISAsyncTaskError,
)


def _as_http_exception(
    exc: IRISAuthError | IRISConnectionError | IRISTimeoutError | IRISResponseError | IRISAsyncTaskError,
) -> HTTPException:
    """Translate an IRIS client error into a safe HTTPException.

    Never includes a credential, password, or JWT value — the underlying
    exceptions never carry one in the first place (see
    app/iris_client/exceptions.py), and only the exception type/status code
    is used here, never the raw IRIS response body.
    """
    if isinstance(exc, IRISAuthError):
        return HTTPException(status_code=502, detail="Could not authenticate with IRIS")
    if isinstance(exc, IRISConnectionError):
        return HTTPException(status_code=502, detail="Could not connect to IRIS")
    if isinstance(exc, IRISTimeoutError):
        return HTTPException(status_code=504, detail="Timed out waiting for IRIS")
    if isinstance(exc, IRISResponseError):
        return HTTPException(
            status_code=502,
            detail=f"IRIS returned an unexpected HTTP {exc.status_code}",
        )
    if isinstance(exc, IRISAsyncTaskError):
        # IRIS's own task state ("Failed"/"Canceled") is a safe, non-sensitive
        # string — it is not a credential or raw response body, so it is
        # surfaced as-is, the same discipline as the other branches here.
        return HTTPException(
            status_code=502,
            detail=f"IRIS's audit record query did not complete successfully ({exc.state or 'timed out'})",
        )
    return HTTPException(status_code=502, detail="Unexpected error communicating with IRIS")


@router.get("/info", response_model=IRISEnvelope[InfoResult])
async def get_info(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[InfoResult]:
    try:
        raw = await client.get("/info")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[InfoResult].model_validate(raw)


@router.get("/namespaces", response_model=IRISEnvelope[list[NamespaceEntry]])
async def get_namespaces(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[NamespaceEntry]]:
    try:
        raw = await client.get("/v2/namespaces")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[NamespaceEntry]].model_validate(raw)


@router.get("/databases", response_model=IRISEnvelope[list[DatabaseEntry]])
async def get_databases(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[DatabaseEntry]]:
    try:
        raw = await client.get("/v2/databases")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[DatabaseEntry]].model_validate(raw)


@router.get("/databases/info", response_model=IRISEnvelope[DatabaseInfoResult])
async def get_database_info(
    dir: str,
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[DatabaseInfoResult]:
    """Non-configurable storage info (block size, allocated size, available
    space, host disk free space, mount/full/encrypted/mirrored status) for
    one database, keyed by its real Directory — the data behind the
    Database Explorer's "View Info" drawer action.

    `dir` is exactly mainspec_v2.json's own documented query parameter name
    for `POST /v2/database-dir/info` (the `DBDirectory` component) — not
    renamed, matching this file's existing discipline (see
    get_audit_records' filter parameters).

    Read-only: mainspec_v2.json documents this as a plain informational
    view (no request body, nothing configurable is changed), even though
    IRIS itself runs it as an async task (POST to start, then poll to
    completion — same pattern get_audit_records above already uses). This
    route is therefore, like every other route in this file, never gated
    by this project's authorization/confirmation/execution framework.
    """
    try:
        task_id = await client.post_async_task("/v2/database-dir/info", params={"dir": dir})
        task = await client.wait_for_async_task(task_id)
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    return IRISEnvelope[DatabaseInfoResult].model_validate(
        {"status": {"errors": [], "summary": ""}, "console": [], "result": task.get("Result", {})}
    )


@router.get("/databases/integrity-check", response_model=DatabaseIntegrityCheckResult)
async def get_database_integrity_check(
    dir: str,
    maxProcesses: int | None = None,
    partialCheck: bool | None = None,
    client: IRISClient = Depends(get_iris_client),
) -> DatabaseIntegrityCheckResult:
    """Run an integrity check on one database, keyed by its real Directory —
    the data behind the Database Explorer's "Run Integrity Check" drawer
    action.

    `dir` is translated into mainspec_v2.json's own documented request body
    for `POST /v2/database-dir/integrity-check` — `{"Databases": [{"Directory":
    dir}], ...}` — a JSON body, unlike GET /databases/info's plain `dir` query
    parameter, because that is genuinely this endpoint's real, documented
    shape (an array of {Directory, Globals} entries, not a single query
    param) — confirmed by reading spec/mainspec_v2.json directly, not
    guessed. This route only ever checks the ONE database its own `dir`
    names (a single-entry `Databases` array), matching every other
    single-database action in this file (get_database_info); the spec's own
    optional per-entry `Globals` filter and bulk multi-database checking are
    not exposed here — a deliberately smaller, focused surface for this
    first pass. `maxProcesses`/`partialCheck` map directly to the spec's own
    optional `MaxProcesses`/`PartialCheck` body fields, forwarded only when
    the caller actually supplies them.

    Unlike get_database_info, this endpoint's response has NEVER been
    observed against a real IRIS instance — an integrity check is a real,
    resource-intensive scan of live data, not a quick metadata read, and
    executing one was explicitly out of scope for this implementation (see
    DatabaseIntegrityCheckResult's own docstring in app/models/iris.py).
    This route therefore returns IRIS's own async-task envelope RAW — State,
    TaskName, Console, FailureReason, Result, Time* — rather than unwrapping
    just a `Result` the way get_database_info does, since this operation's
    real outcome may be conveyed via Console/FailureReason as much as via
    Result, and `Result`'s own shape is intentionally left untyped (`Any`)
    rather than guessed.

    Read-only: mainspec_v2.json documents this as verifying existing data,
    never modifying it, even though IRIS itself runs it as an async task
    (POST to start, then poll to completion — same pattern get_database_info
    and get_audit_records above already use). This route is therefore, like
    every other route in this file, never gated by this project's
    authorization/confirmation/execution framework.
    """
    body: dict[str, Any] = {"Databases": [{"Directory": dir}]}
    if maxProcesses is not None:
        body["MaxProcesses"] = maxProcesses
    if partialCheck is not None:
        body["PartialCheck"] = partialCheck

    try:
        task_id = await client.post_async_task("/v2/database-dir/integrity-check", json=body)
        task = await client.wait_for_async_task(task_id)
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    return DatabaseIntegrityCheckResult.model_validate(task)


@router.get("/processes", response_model=IRISEnvelope[list[ProcessEntry]])
async def get_processes(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[ProcessEntry]]:
    try:
        raw = await client.get("/v2/processes")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[ProcessEntry]].model_validate(raw)


@router.get("/web-apps", response_model=IRISEnvelope[list[WebAppEntry]])
async def get_web_apps(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[WebAppEntry]]:
    try:
        raw = await client.get("/v2/web-apps")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[WebAppEntry]].model_validate(raw)


@router.get("/web-apps/detail", response_model=IRISEnvelope[WebAppDetail])
async def get_web_app_detail(
    name: str,
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[WebAppDetail]:
    """Full configuration of one web application, keyed by its real Name
    (e.g. "/api/admin") — the data behind the Web Apps Explorer's detail
    drawer.

    `name` is exactly mainspec_v2.json's own documented query parameter for
    `GET /v2/web-app`, not renamed. A query parameter (not a path segment)
    because web app names themselves contain slashes. Read-only: a plain
    GET, never gated by the authorization/confirmation/execution framework,
    like every other route in this file.
    """
    try:
        raw = await client.get("/v2/web-app", params={"name": name})
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[WebAppDetail].model_validate(raw)


@router.get("/ext-lang-servers", response_model=IRISEnvelope[list[ExternalLanguageServerEntry]])
async def get_ext_lang_servers(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[ExternalLanguageServerEntry]]:
    try:
        raw = await client.get("/v2/ext-lang-servers")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[ExternalLanguageServerEntry]].model_validate(raw)


@router.get("/tasks", response_model=IRISEnvelope[list[TaskEntry]])
async def get_tasks(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[list[TaskEntry]]:
    try:
        raw = await client.get("/v2/tasks")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[TaskEntry]].model_validate(raw)


@router.get("/fs-access-purposes", response_model=IRISEnvelope[list[Any]])
async def get_fs_access_purposes(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # No entry shape has ever been observed populated on this instance
    # (result was always []); see app/models/iris.py's module docstring.
    try:
        raw = await client.get("/v2/fs-access-purposes")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[Any]].model_validate(raw)


@router.get("/journal/settings", response_model=IRISEnvelope[JournalSettings])
async def get_journal_settings(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[JournalSettings]:
    try:
        raw = await client.get("/v2/journal/settings")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[JournalSettings].model_validate(raw)


@router.get("/security/oauth2/server", response_model=IRISEnvelope[dict[str, Any]])
async def get_oauth2_server(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[dict[str, Any]]:
    """View this instance's OAuth2 Authorization Server configuration.

    IRIS returns a documented, valid `404` when it isn't configured to act
    as an OAuth2 Authorization Server (see api-capability-matrix.md) — that
    is an application-level fact, not a communication failure. This route
    treats it as a normal, successful read: it returns HTTP 200 with the
    real status/console/result body IRIS sent, rather than propagating it
    as an upstream error. A real "configured" success body has never been
    observed on this instance, so `result` is typed permissively.
    """
    try:
        raw = await client.get("/v2/security/oauth2/server")
    except IRISResponseError as exc:
        if exc.status_code == 404 and exc.body is not None:
            return IRISEnvelope[dict[str, Any]].model_validate(exc.body)
        raise _as_http_exception(exc) from exc
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[dict[str, Any]].model_validate(raw)


@router.get(
    "/security/oauth2/client/server-definitions",
    response_model=IRISEnvelope[list[Any]],
)
async def get_oauth2_client_server_definitions(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # No entry shape has ever been observed populated (result was always []).
    try:
        raw = await client.get("/v2/security/oauth2/client/server-definitions")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[Any]].model_validate(raw)


@router.get("/security/oauth2/server/clients", response_model=IRISEnvelope[list[Any]])
async def get_oauth2_server_clients(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # No entry shape has ever been observed populated (result was always []).
    try:
        raw = await client.get("/v2/security/oauth2/server/clients")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[Any]].model_validate(raw)


@router.get("/wallet/collections", response_model=IRISEnvelope[list[Any]])
async def get_wallet_collections(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # No entry shape has ever been observed populated (result was always []).
    try:
        raw = await client.get("/v2/wallet/collections")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[Any]].model_validate(raw)


@router.get("/security/audit/enabled", response_model=IRISEnvelope[AuditEnabledResult])
async def get_audit_enabled(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[AuditEnabledResult]:
    try:
        raw = await client.get("/v2/security/audit/enabled")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[AuditEnabledResult].model_validate(raw)


@router.get("/security/audit/records", response_model=IRISEnvelope[list[AuditRecordEntry]])
async def get_audit_records(
    client: IRISClient = Depends(get_iris_client),
    beginDateTime: str | None = None,
    endDateTime: str | None = None,
    eventSources: str | None = None,
    eventTypes: str | None = None,
    events: str | None = None,
    usernames: str | None = None,
    systemIDs: str | None = None,
    pids: str | None = None,
    namespaces: str | None = None,
    authentication: str | None = None,
    ascending: int | None = None,
    jsonSearch: str | None = None,
) -> IRISEnvelope[list[AuditRecordEntry]]:
    """Search IRIS's security audit log — the data behind the Logs /
    Investigation view.

    Every query parameter here is exactly one `spec/mainspec_v2.json`
    documents for `POST /v2/security/audit/records` (comma-separated filter
    lists, an ascending/descending flag, and a JSON-field search string) —
    none is invented, and all are optional, matching an unfiltered "list
    everything" query when omitted.

    IRIS runs this as an async task (POST to start, then poll to
    completion — see app/iris_client/client.py's post_async_task/
    wait_for_async_task and docs/api-capability-matrix.md); this route waits
    for that polling to finish and returns just the finished task's `Result`
    array, in the same IRISEnvelope[list[...]] shape every other list route
    in this file already returns, so the frontend never needs to know about
    IRIS's task/polling mechanics.
    """
    params = {
        "beginDateTime": beginDateTime,
        "endDateTime": endDateTime,
        "eventSources": eventSources,
        "eventTypes": eventTypes,
        "events": events,
        "usernames": usernames,
        "systemIDs": systemIDs,
        "pids": pids,
        "namespaces": namespaces,
        "authentication": authentication,
        "ascending": ascending,
        "jsonSearch": jsonSearch,
    }
    params = {key: value for key, value in params.items() if value is not None}

    try:
        task_id = await client.post_async_task("/v2/security/audit/records", params=params)
        task = await client.wait_for_async_task(task_id)
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    return IRISEnvelope[list[AuditRecordEntry]].model_validate(
        {"status": {"errors": [], "summary": ""}, "console": [], "result": task.get("Result", [])}
    )
