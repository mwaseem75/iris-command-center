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

import asyncio
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

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
    OAuth2ServerClientEntry,
    OAuth2ServerConfigView,
    OAuth2ServerDefinitionEntry,
    ProcessEntry,
    RestEndpoint,
    RestEndpointParameter,
    RestRouteMap,
    TaskDetail,
    TaskEntry,
    TaskInfo,
    TaskManagerStatus,
    TaskOverviewEntry,
    WebAppDetail,
    WebAppEntry,
    WebSessionEntry,
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



@router.get("/web-sessions", response_model=IRISEnvelope[list[WebSessionEntry]])
async def get_web_sessions(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[WebSessionEntry]]:
    """Active CSP/REST web sessions (GET /v2/web-sessions) — the data behind
    the Web Apps Explorer's read-only Sessions section.

    Every session's IRIS `ID` (the CSP session identifier, and the exact
    value DELETE /v2/web-session?id= takes) is removed here, server-side:
    WebSessionEntry does not model it, so validation drops it and neither
    the browser nor any response ever sees it. Read-only; never gated by
    the authorization/confirmation/execution framework, like every other
    route in this file.
    """
    try:
        raw = await client.get("/v2/web-sessions")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[WebSessionEntry]].model_validate(raw)

# Swagger 2.0 path-item keys that are HTTP operations (everything else in a
# path item, e.g. "parameters", is not an endpoint).
_SWAGGER_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _rest_parameter(raw: dict[str, Any], shared: dict[str, Any]) -> RestEndpointParameter:
    """One Swagger parameter, with a "#/parameters/<name>" $ref resolved
    against the spec's own top-level `parameters`. A $ref that can't be
    resolved is kept verbatim as `ref` — never guessed."""
    ref = raw.get("$ref")
    if isinstance(ref, str):
        prefix = "#/parameters/"
        target = shared.get(ref[len(prefix):]) if ref.startswith(prefix) else None
        if not isinstance(target, dict):
            return RestEndpointParameter(ref=ref)
        raw = target
    schema = raw.get("schema")
    required = raw.get("required")
    return RestEndpointParameter(
        name=_optional_str(raw.get("name")),
        location=_optional_str(raw.get("in")),
        required=required if isinstance(required, bool) else None,
        type=_optional_str(raw.get("type")),
        description=_optional_str(raw.get("description")),
        pattern=_optional_str(raw.get("pattern")),
        bodySchema=schema if isinstance(schema, dict) else None,
    )


def _rest_endpoints(spec: dict[str, Any]) -> list[RestEndpoint]:
    """Flattens a Swagger 2.0 `paths` object into one RestEndpoint per
    (path, method), in the document's own order. Path-level parameters
    (Swagger lets a path item declare them for all its operations) are
    prepended to each operation's own."""
    shared = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {}
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    endpoints: list[RestEndpoint] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        path_params = item.get("parameters") if isinstance(item.get("parameters"), list) else []
        for method, operation in item.items():
            if method.lower() not in _SWAGGER_HTTP_METHODS or not isinstance(operation, dict):
                continue
            op_params = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
            endpoints.append(
                RestEndpoint(
                    method=method.upper(),
                    path=path,
                    operationId=_optional_str(operation.get("operationId")),
                    serviceMethod=_optional_str(operation.get("x-ISC_ServiceMethod")),
                    summary=_optional_str(operation.get("summary")),
                    description=_optional_str(operation.get("description")),
                    parameters=[
                        _rest_parameter(param, shared)
                        for param in [*path_params, *op_params]
                        if isinstance(param, dict)
                    ],
                )
            )
    return endpoints


@router.get("/web-apps/rest-endpoints", response_model=IRISEnvelope[RestRouteMap])
async def get_web_app_rest_endpoints(
    name: str,
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[RestRouteMap]:
    """The REST route map of one web application, keyed by its real Name —
    the data behind the Web Apps Explorer's "REST Endpoints" tab.

    Two read-only GETs against IRIS's API Management API (/api/mgmnt — not
    part of mainspec_v2.json; see IRISClient.get_mgmnt for why it uses HTTP
    Basic rather than the /api/admin JWT):
      1. GET /api/mgmnt/ — IRIS's own list of REST applications in every
         namespace. An app not in this list is not a REST app as far as
         IRIS is concerned (404 here), and the list supplies the app's real
         namespace for step 2 rather than trusting the caller.
      2. GET /api/mgmnt/v1/{namespace}/spec{name} — a Swagger 2.0 document
         IRIS generates from the dispatch class's route map. IRIS answers
         404 when it cannot generate one (observed live for
         /api/interop-editors), surfaced here as a distinct 404 detail.

    Never gated by the authorization/confirmation/execution framework:
    nothing here changes IRIS state, like every other route in this file.
    """
    try:
        rest_apps = await client.get_mgmnt("/")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    entry = None
    if isinstance(rest_apps, list):
        entry = next(
            (app for app in rest_apps if isinstance(app, dict) and app.get("name") == name),
            None,
        )
    namespace = entry.get("namespace") if entry else None
    if not isinstance(namespace, str) or not namespace:
        raise HTTPException(
            status_code=404, detail="IRIS does not list this web application as a REST application"
        )

    spec_path = f"/v1/{quote(namespace, safe='')}/spec{quote(name, safe='/')}"
    try:
        spec = await client.get_mgmnt(spec_path)
    except IRISResponseError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="IRIS could not generate a REST route map for this web application",
            ) from exc
        raise _as_http_exception(exc) from exc
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    if not isinstance(spec, dict):
        raise HTTPException(status_code=502, detail="IRIS returned an unexpected REST route map")

    enabled = entry.get("enabled")
    route_map = RestRouteMap(
        name=name,
        namespace=namespace,
        dispatchClass=_optional_str(entry.get("dispatchClass")) or "",
        enabled=enabled if isinstance(enabled, bool) else None,
        basePath=_optional_str(spec.get("basePath")),
        swagger=_optional_str(spec.get("swagger")),
        endpoints=_rest_endpoints(spec),
    )
    return IRISEnvelope[RestRouteMap](
        status={"errors": [], "summary": ""}, console=[], result=route_map
    )


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


# At most this many GET /v2/task/info calls are in flight at once for one
# overview request (16 tasks on icc-iris-dev).
_TASK_INFO_CONCURRENCY = 8


def _task_state(info: TaskInfo | None) -> str | None:
    """A task's run state, derived from GET /v2/task/info only — never from
    the list's `Suspended`, which was observed reporting `false` for
    suspended tasks. "Running" is mainspec_v2.json's documented Status -1
    (JobRunning) and wins over Suspended, because a suspended task's job can
    still be executing. None when the info call failed: unknown, not guessed."""
    if info is None:
        return None
    if info.Status == "-1":
        return "Running"
    if info.Suspended:
        return "Suspended"
    return "Not Running"


@router.get("/tasks/overview", response_model=IRISEnvelope[list[TaskOverviewEntry]])
async def get_tasks_overview(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[TaskOverviewEntry]]:
    """Every task from GET /v2/tasks, each merged with its own GET
    /v2/task/info (run status, last result, reliable Suspended flag) and a
    derived State — the data behind the Tasks view's table and KPI cards.

    The list call failing fails the request. A single task's info call
    failing does not: that task's Info/State are None and a warning is
    added to status.errors (naming only the task id), so the rest of the
    page still renders. Read-only: only GETs are sent.
    """
    try:
        raw = await client.get("/v2/tasks")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    listing = IRISEnvelope[list[TaskEntry]].model_validate(raw)

    semaphore = asyncio.Semaphore(_TASK_INFO_CONCURRENCY)

    async def read_info(task_id: int) -> TaskInfo | None:
        async with semaphore:
            try:
                body = await client.get("/v2/task/info", params={"id": task_id})
                return TaskInfo.model_validate(body.get("result") if isinstance(body, dict) else None)
            except (*_IRIS_CLIENT_ERRORS, ValidationError):
                return None

    infos = await asyncio.gather(*(read_info(task.Id) for task in listing.result))

    errors = list(listing.status.errors)
    entries: list[TaskOverviewEntry] = []
    for task, info in zip(listing.result, infos):
        if info is None:
            errors.append({"error": f"Run state unavailable for task {task.Id}", "taskId": task.Id})
        entries.append(
            TaskOverviewEntry(
                Id=task.Id,
                Name=task.Name,
                Type=task.Type,
                Namespace=task.Namespace,
                Description=task.Description,
                LastFinished=task.LastFinished,
                NextScheduled=task.NextScheduled,
                Info=info,
                State=_task_state(info),
            )
        )

    missing = sum(1 for info in infos if info is None)
    summary = listing.status.summary
    if missing and not summary:
        summary = f"Run state unavailable for {missing} task{'' if missing == 1 else 's'}"
    return IRISEnvelope[list[TaskOverviewEntry]](
        status={"errors": errors, "summary": summary}, console=listing.console, result=entries
    )


# Settings keys (case-insensitive substrings) whose values never leave this
# backend. Settings is TaskClass-specific and arbitrary; e.g. the built-in
# Diagnostic Report task's Settings include SMTPPass.
_SENSITIVE_SETTING_MARKERS = (
    "pass",
    "pwd",
    "secret",
    "token",
    "credential",
    "apikey",
    "api_key",
    "privatekey",
    "private_key",
)


def _is_sensitive_setting(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_SETTING_MARKERS)


def _redact_settings(value: Any, path: str, redacted: list[str]) -> Any:
    """Returns a copy of `value` with every sensitive key's value replaced by
    None, recursing into nested objects/arrays; each redacted key path is
    appended to `redacted`. The value is redacted whether or not it is
    empty, so a response never reveals whether a secret is set."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if _is_sensitive_setting(str(key)):
                result[key] = None
                redacted.append(key_path)
            else:
                result[key] = _redact_settings(item, key_path, redacted)
        return result
    if isinstance(value, list):
        return [_redact_settings(item, f"{path}[{i}]", redacted) for i, item in enumerate(value)]
    return value


@router.get("/tasks/detail", response_model=IRISEnvelope[TaskDetail])
async def get_task_detail(
    id: int,
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[TaskDetail]:
    """Full configuration of one task (GET /v2/task?id=), the data behind
    the Tasks view's detail drawer. `id` is mainspec_v2.json's own query
    parameter name. Sensitive Settings keys are redacted here, server-side,
    before the response is built (see _redact_settings). IRIS's documented
    404 for an unknown id is surfaced as a 404. Read-only: a plain GET.
    """
    try:
        raw = await client.get("/v2/task", params={"id": id})
    except IRISResponseError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="IRIS reports no task with this id") from exc
        raise _as_http_exception(exc) from exc
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc

    result = raw.get("result") if isinstance(raw, dict) else None
    if isinstance(result, dict):
        redacted: list[str] = []
        result = {**result, "Settings": _redact_settings(result.get("Settings"), "", redacted)}
        result["RedactedSettings"] = redacted
        raw = {**raw, "result": result}
    return IRISEnvelope[TaskDetail].model_validate(raw)


@router.get("/tasks/manager", response_model=IRISEnvelope[TaskManagerStatus])
async def get_task_manager(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[TaskManagerStatus]:
    """The Task Manager's own status (GET /v2/task/manager). Read-only."""
    try:
        raw = await client.get("/v2/task/manager")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[TaskManagerStatus].model_validate(raw)


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


# The three OAuth2 routes below return allowlisted fields only (the same
# models as app/routes/security_access.py's OAuth overview), never IRIS's
# raw body: IRIS's OAuth2 classes also hold client secrets and tokens.
# response_model_exclude_none keeps a field IRIS didn't report out of the
# response, so the documented "not configured" body stays `result: {}`.


@router.get(
    "/security/oauth2/server",
    response_model=IRISEnvelope[OAuth2ServerConfigView],
    response_model_exclude_none=True,
)
async def get_oauth2_server(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[OAuth2ServerConfigView]:
    """View this instance's OAuth2 Authorization Server configuration.

    IRIS returns a documented, valid `404` when it isn't configured to act
    as an OAuth2 Authorization Server (see api-capability-matrix.md) — that
    is an application-level fact, not a communication failure. This route
    treats it as a normal, successful read: it returns HTTP 200 with the
    real status/console/result body IRIS sent, rather than propagating it
    as an upstream error. A real "configured" success body has never been
    observed on this instance, so every allowlisted field is optional.
    """
    try:
        raw = await client.get("/v2/security/oauth2/server")
    except IRISResponseError as exc:
        if exc.status_code == 404 and exc.body is not None:
            return IRISEnvelope[OAuth2ServerConfigView].model_validate(exc.body)
        raise _as_http_exception(exc) from exc
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[OAuth2ServerConfigView].model_validate(raw)


@router.get(
    "/security/oauth2/client/server-definitions",
    response_model=IRISEnvelope[list[OAuth2ServerDefinitionEntry]],
    response_model_exclude_none=True,
)
async def get_oauth2_client_server_definitions(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[OAuth2ServerDefinitionEntry]]:
    # No entry shape has ever been observed populated (result was always []).
    try:
        raw = await client.get("/v2/security/oauth2/client/server-definitions")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[OAuth2ServerDefinitionEntry]].model_validate(raw)


@router.get(
    "/security/oauth2/server/clients",
    response_model=IRISEnvelope[list[OAuth2ServerClientEntry]],
    response_model_exclude_none=True,
)
async def get_oauth2_server_clients(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[OAuth2ServerClientEntry]]:
    # No entry shape has ever been observed populated (result was always []).
    try:
        raw = await client.get("/v2/security/oauth2/server/clients")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[OAuth2ServerClientEntry]].model_validate(raw)


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
