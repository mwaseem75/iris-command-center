"""Read-only routes over the IRIS Admin REST API.

Login and tokens are handled by the shared IRISClient. None of these routes
change IRIS state. Audit records, database info and integrity checks are
IRIS async tasks (a POST to start, then polling), but they're still reads.
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
    DatabaseStorageEntry,
    ExternalLanguageServerEntry,
    InfoResult,
    IRISEnvelope,
    JournalSettings,
    MonitorDashboard,
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
    """Map an IRIS client error to an HTTPException without exposing the IRIS response body."""
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
        # IRIS's task state ("Failed"/"Canceled") is safe to show.
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
    """Storage info for one database (sizes, free space, mount state), keyed by
    its Directory. Backs the "View Info" action on the Databases page.

    IRIS runs this as an async task (POST /v2/database-dir/info, then poll).
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
    """Run an integrity check on one database, keyed by its Directory.

    IRIS takes a JSON body here ({"Databases": [{"Directory": dir}], ...}); we
    only check the one database and forward maxProcesses/partialCheck when
    given. The async task envelope (State, Console, FailureReason, Result, ...)
    is returned as-is, because the outcome can be in Console or FailureReason
    and we've never seen a real Result to model it on.
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


@router.get("/databases/storage", response_model=IRISEnvelope[list[DatabaseStorageEntry]])
async def get_database_storage(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[DatabaseStorageEntry]]:
    """Size and status of every local database (GET /v2/database-dirs)."""
    try:
        raw = await client.get("/v2/database-dirs")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[DatabaseStorageEntry]].model_validate(raw)


@router.get("/monitor/dashboard", response_model=IRISEnvelope[MonitorDashboard])
async def get_monitor_dashboard(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[MonitorDashboard]:
    """IRIS system dashboard: performance, health, alerts, licensing, upcoming tasks."""
    try:
        raw = await client.get("/v2/monitor/dashboard/main")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[MonitorDashboard].model_validate(raw)


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
    """Full configuration of one web application, looked up by Name.

    Name is a query parameter because web app names contain slashes.
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
    """Active web sessions (GET /v2/web-sessions).

    The session ID isn't in our model, so it never reaches the browser.
    """
    try:
        raw = await client.get("/v2/web-sessions")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[WebSessionEntry]].model_validate(raw)

# Swagger path-item keys that are HTTP operations (others, like
# "parameters", aren't endpoints).
_SWAGGER_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _rest_parameter(raw: dict[str, Any], shared: dict[str, Any]) -> RestEndpointParameter:
    """One Swagger parameter, with a "#/parameters/<name>" $ref resolved.
    An unresolvable $ref is kept as `ref`.
    """
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
    """Flatten Swagger `paths` into one entry per (path, method), in order.
    Path-level parameters are added in front of each operation's own.
    """
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
    """REST route map of one web application (the "REST Endpoints" tab).

    Uses /api/mgmnt (HTTP Basic, see IRISClient.get_mgmnt):
    1. GET /api/mgmnt/ lists REST apps in every namespace. If the app isn't
       there it's not a REST app (404), and we take its namespace from here.
    2. GET /api/mgmnt/v1/{namespace}/spec{name} returns a Swagger doc built
       from the dispatch class. IRIS returns 404 when it can't build one
       (e.g. /api/interop-editors).
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


# Max concurrent /v2/task/info calls per overview request.
_TASK_INFO_CONCURRENCY = 8


def _task_state(info: TaskInfo | None) -> str | None:
    """Work out a task's state from /v2/task/info.

    We don't trust the list's Suspended flag (it reported false for suspended
    tasks). Status -1 means running, which wins over Suspended. None if the
    info call failed.
    """
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
    """All tasks, each combined with its /v2/task/info and a derived State.

    If the list call fails the request fails. If one task's info call fails,
    that task gets no State and a warning is added to status.errors.
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


# Settings keys (case-insensitive substrings) we never send to the
# browser. E.g. the Diagnostic Report task has an SMTPPass setting.
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
    """Copy `value` with sensitive keys set to None (recursively) and record
    their paths in `redacted`. Empty values are redacted too, so the response
    doesn't reveal whether a secret is set.
    """
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
    """Full configuration of one task (GET /v2/task?id=), with sensitive
    Settings redacted. An unknown id returns 404.
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
    """Task Manager status (GET /v2/task/manager)."""
    try:
        raw = await client.get("/v2/task/manager")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[TaskManagerStatus].model_validate(raw)


@router.get("/fs-access-purposes", response_model=IRISEnvelope[list[Any]])
async def get_fs_access_purposes(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # We've only ever seen an empty list here.
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


# The OAuth2 routes below only return allowlisted fields, because
# IRIS's OAuth2 objects also contain client secrets and tokens.
# response_model_exclude_none keeps unreported fields out, so the
# "not configured" response stays `result: {}`.


@router.get(
    "/security/oauth2/server",
    response_model=IRISEnvelope[OAuth2ServerConfigView],
    response_model_exclude_none=True,
)
async def get_oauth2_server(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[OAuth2ServerConfigView]:
    """OAuth2 Authorization Server configuration.

    IRIS returns 404 when this instance isn't an OAuth2 server. That's a normal
    answer, so we return 200 with IRIS's body instead of an error. All fields
    are optional since we've never seen a configured server here.
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
    # We've only ever seen an empty list here.
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
    # We've only ever seen an empty list here.
    try:
        raw = await client.get("/v2/security/oauth2/server/clients")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[OAuth2ServerClientEntry]].model_validate(raw)


@router.get("/wallet/collections", response_model=IRISEnvelope[list[Any]])
async def get_wallet_collections(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[Any]]:
    # We've only ever seen an empty list here.
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
    """Search the IRIS security audit log (backs the Investigation page).

    The query parameters are the ones POST /v2/security/audit/records accepts;
    all are optional. IRIS runs this as an async task; we wait for it and return
    the Result list in the usual envelope.
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
