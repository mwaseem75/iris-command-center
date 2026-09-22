"""Reusable IRIS SysAdmin REST API client abstraction.

Provides generic, authenticated GET and PUT methods. It intentionally does
NOT expose per-endpoint methods (e.g. get_namespaces()) yet — those are
added as each one is deliberately wired up. This keeps authentication/request
handling in one place so endpoint-specific handlers can reuse it without
duplicating login or error-handling logic.

PUT was added in Phase 2 Step 7 for the project's first real mutating
operation (PUT /v2/journal/settings — see docs/first-mutation-selection.md
and docs/first-mutation-implementation.md). Adding it here does not call it
anywhere against a real IRIS instance; only a handler explicitly registered
for a confirmed, authorized mutating operation ever invokes it, and no such
call has been made against icc-iris-dev as of this step.

`post_async_task`/`wait_for_async_task` were added for the Logs/Investigation
view's GET /api/iris/security/audit/records route. Several read-only IRIS
SysAdmin endpoints (audit records being the first one this project wires up)
are documented and observed to run as an ASYNC TASK: the initiating call is
a POST that returns 202 with a Location header pointing to a polling
endpoint, not a normal synchronous response — see
docs/api-capability-matrix.md's "POST /v2/security/audit/records" entry for
exactly what was observed against a real instance. This is a read/query
mechanism (IRIS's own API shape for a potentially long-running query), not a
mutating operation — it changes no IRIS state and is not gated by this
project's authorization/confirmation/execution framework, the same way every
other read-only route in app/routes/iris.py isn't.

The response body is returned exactly as IRIS sent it (parsed JSON), with no
assumption about a result/status/console wrapper being present — verification
showed that wrapper is used by some operations (e.g. GET /info) but not others
(e.g. POST /login, which is flat). See docs/api-capability-matrix.md for the
per-endpoint, per-operation breakdown. Callers are responsible for interpreting
the shape appropriate to the specific endpoint they called.
"""

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.auth.iris_auth import IRISAuthClient
from app.config import Settings
from app.iris_client.exceptions import (
    IRISAsyncTaskError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)

_API_BASE_PATH = "/api/admin"

# IRIS's API Management REST application (dispatch class %Api.Mgmnt.v2.disp).
# Verified against icc-iris-dev: its web app has JWT disabled
# (JWTAuthEnabled: false, AutheEnabled: 32 = Password only), so it rejects
# the /api/admin Bearer token with 401 and accepts only HTTP Basic with the
# same configured IRIS credentials. See get_mgmnt().
_MGMNT_BASE_PATH = "/api/mgmnt"

# Verified against icc-iris-dev (see docs/api-capability-matrix.md): a real
# audit-record query task completed within a single poll. These defaults
# give real, larger queries room to complete without making a caller wait
# indefinitely — 20 attempts x 0.5s = 10s of polling before giving up.
_DEFAULT_ASYNC_TASK_MAX_ATTEMPTS = 20
_DEFAULT_ASYNC_TASK_POLL_INTERVAL_SECONDS = 0.5
_ASYNC_TASK_TERMINAL_STATES = frozenset({"Finished", "Failed", "Canceled"})


class IRISClient:
    """Authenticated HTTP client for the IRIS SysAdmin REST API (read-only so far)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient()
        self._auth = IRISAuthClient(settings, self._http)

    async def __aenter__(self) -> "IRISClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform an authenticated GET against the IRIS SysAdmin REST API.

        `path` is relative to /api/admin, e.g. "/info" or "/v2/namespaces".
        Returns the parsed JSON response body verbatim.
        """
        response = await self._request("GET", path, params=params)
        return response.json()

    async def get_mgmnt(self, path: str) -> Any:
        """Perform a read-only GET against IRIS's API Management REST API.

        `path` is relative to /api/mgmnt, e.g. "/" or
        "/v1/%25SYS/spec/api/admin". Authenticates with HTTP Basic using the
        same configured IRIS credentials the JWT login already uses (this
        application does not accept the JWT — see _MGMNT_BASE_PATH). The
        credentials are passed only via httpx's `auth=`, never placed in a
        URL, log line, or exception message. Deliberately GET-only: this
        client exposes no way to call /api/mgmnt's mutating operations.
        Returns the parsed JSON body verbatim (a list for "/", an object for
        a spec).
        """
        url = self._mgmnt_url(path)
        auth = httpx.BasicAuth(
            self._settings.iris_username, self._settings.iris_password.get_secret_value()
        )
        response = await self._send("GET", url, path, auth=auth)
        return response.json()

    def _mgmnt_url(self, path: str) -> httpx.URL:
        """Builds the /api/mgmnt URL for `path`, refusing (before any request
        exists, so the Basic credentials are never attached) anything that
        would not land on the configured IRIS host strictly under
        /api/mgmnt/. httpx normalizes "../" segments, so "/../admin/..."
        would otherwise reach /api/admin/..., and a percent-encoded "%2e%2e"
        survives normalization but decodes to ".." — any dot segment is
        rejected, as is a path not starting with "/" (e.g. "@host" or
        ".suffix"). The error message deliberately names no path or
        credential."""
        base = httpx.URL(self._settings.iris_base_url.rstrip("/") + _MGMNT_BASE_PATH + "/")
        url = httpx.URL(f"{self._settings.iris_base_url.rstrip('/')}{_MGMNT_BASE_PATH}{path}")
        # Checked both before normalization (literal "./" or "../" anywhere —
        # no legitimate /api/mgmnt path has one) and after (decoded "%2e%2e").
        segments = path.split("/") + url.path.split("/")
        if (
            not path.startswith("/")
            or (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port)
            or not url.path.startswith(base.path)
            or "." in segments
            or ".." in segments
        ):
            raise ValueError("Refusing to send IRIS credentials outside /api/mgmnt/")
        return url

    async def put(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        """Perform an authenticated PUT against the IRIS SysAdmin REST API.

        `path` is relative to /api/admin, e.g. "/v2/journal/settings". `json`
        is sent as the request body exactly as given — this method does not
        add, remove, or infer any field. Returns the parsed JSON response
        body verbatim.
        """
        response = await self._request("PUT", path, json=json)
        return response.json()

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an authenticated, SYNCHRONOUS POST against the IRIS
        SysAdmin REST API — for endpoints documented to return their result
        directly (e.g. `POST /v2/database-dir`'s `201 Created` with the
        created resource in `result`), unlike post_async_task()'s
        202-plus-poll pattern used by IRIS's separate async-query endpoints.
        `path` is relative to /api/admin, e.g. "/v2/database-dir". `json` is
        sent as the request body exactly as given — this method does not
        add, remove, or infer any field. Returns the parsed JSON response
        body verbatim.

        `params`: some synchronous endpoints (e.g. POST /v2/database-dir/
        mount) are keyed by a documented query parameter (`dir`) rather
        than a body field — sent exactly as given, same as post_async_task().
        """
        response = await self._request("POST", path, params=params, json=json)
        return response.json()

    async def post_async_task(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> str:
        """Start an IRIS async-task-backed query (e.g. POST
        /v2/security/audit/records) and return its task id.

        A successful call returns HTTP 202 with a `Location` header of the
        form `/api/admin/v1/async-result?id=<task-id>` (verified against a
        real instance — see docs/api-capability-matrix.md; note the actual
        Location path uses `v1`, not `v2`, even though the spec files this
        under `/v2/async-result` — both were verified to work, and
        `wait_for_async_task` always uses the documented `/v2/async-result`
        path itself rather than replaying the Location header's path). Only
        the `id` query parameter is ever extracted; nothing else from the
        header is used or trusted.

        `json`: some async-task-backed endpoints (e.g. POST /v2/database-dir/
        integrity-check) take their real parameters as a JSON request body
        rather than query params, unlike audit-records/database-dir/info —
        added here, not guessed, once a caller with that real shape needed
        it. Sent exactly as given, same discipline as put()/post().

        Raises IRISAsyncTaskError if no Location header (or no `id` within
        it) is present — this project never guesses a task id.
        """
        response = await self._request("POST", path, params=params, json=json)
        location = response.headers.get("Location")
        if not location:
            raise IRISAsyncTaskError(
                f"IRIS did not return a Location header for async task {path!r}"
            )

        task_id = parse_qs(urlsplit(location).query).get("id", [None])[0]
        if not task_id:
            raise IRISAsyncTaskError(
                f"IRIS's Location header for async task {path!r} had no 'id' parameter"
            )
        return task_id

    async def wait_for_async_task(
        self,
        task_id: str,
        *,
        max_attempts: int = _DEFAULT_ASYNC_TASK_MAX_ATTEMPTS,
        poll_interval_seconds: float = _DEFAULT_ASYNC_TASK_POLL_INTERVAL_SECONDS,
    ) -> dict[str, Any]:
        """Poll GET /v2/async-result?id=<task_id> until the task reaches a
        terminal state, then return its `result` object (IRIS's `AsyncTask`
        shape: State, TaskName, Console, FailureReason, Result,
        TimeQueued/TimeStarted/TimeFinished — see docs/api-capability-matrix.md).

        Raises IRISAsyncTaskError if the task ends in IRIS's own "Failed" or
        "Canceled" state, or if it never reaches a terminal state within
        `max_attempts` polls — this method never returns a partial/unfinished
        result.
        """
        last_state: str | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                await asyncio.sleep(poll_interval_seconds)
            body = await self.get("/v2/async-result", params={"id": task_id})
            task = body.get("result", {})
            last_state = task.get("State")
            if last_state == "Finished":
                return task
            if last_state in ("Failed", "Canceled"):
                raise IRISAsyncTaskError(
                    f"IRIS async task {task_id} ended in state {last_state!r}: "
                    f"{task.get('FailureReason', '')}",
                    state=last_state,
                )

        raise IRISAsyncTaskError(
            f"IRIS async task {task_id} did not finish within {max_attempts} polling attempts",
            state=last_state,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        session = await self._auth.get_valid_session()
        url = f"{self._settings.iris_base_url.rstrip('/')}{_API_BASE_PATH}{path}"
        headers = {"Authorization": f"Bearer {session.access_token}"}
        return await self._send(method, url, path, params=params, json=json, headers=headers)

    async def _send(
        self,
        method: str,
        url: str | httpx.URL,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.Response:
        """Shared transport + error mapping for every IRIS request. `path`
        (never the full URL) is the only request detail put in an error
        message."""
        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                auth=auth,
                timeout=self._settings.iris_request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise IRISTimeoutError(f"Timed out calling IRIS {method} {path}") from exc
        except httpx.ConnectError as exc:
            raise IRISConnectionError(f"Could not connect to IRIS calling {method} {path}") from exc

        if response.status_code >= 400:
            # Note for future endpoint-specific wrappers: verification showed
            # some 4xx responses are documented, valid outcomes rather than
            # errors (e.g. GET /v2/security/oauth2/server returns 404 when
            # OAuth2 simply isn't configured — see api-capability-matrix.md).
            # This generic client always raises on 4xx/5xx; callers that need
            # to treat a specific documented status as non-error should catch
            # IRISResponseError and inspect .status_code / .body themselves.
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            raise IRISResponseError(response.status_code, body=error_body)

        return response
