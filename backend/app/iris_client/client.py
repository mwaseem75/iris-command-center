"""HTTP client for the IRIS Admin REST API (/api/admin) and /api/mgmnt.

Handles login and error mapping in one place; endpoint-specific code lives
in the routes and handlers. Responses are returned as parsed JSON exactly as
IRIS sent them, because the shape varies: some endpoints wrap results in
status/console/result, others (like /login) don't.

Some read endpoints (e.g. audit records) run as IRIS async tasks: a POST
returns 202 with a Location header, and we poll /v2/async-result for the
result. See post_async_task() and wait_for_async_task().
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

# /api/mgmnt has JWT turned off on 2026.2 (password auth only), so it
# rejects the /api/admin Bearer token. We use HTTP Basic there. See get_mgmnt().
_MGMNT_BASE_PATH = "/api/mgmnt"

# Polling limits for async tasks: 20 x 0.5s = 10s before giving up.
# Small queries usually finish on the first poll.
_DEFAULT_ASYNC_TASK_MAX_ATTEMPTS = 20
_DEFAULT_ASYNC_TASK_POLL_INTERVAL_SECONDS = 0.5
_ASYNC_TASK_TERMINAL_STATES = frozenset({"Finished", "Failed", "Canceled"})


class IRISClient:
    """Authenticated HTTP client for the IRIS Admin REST API."""

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
        """GET a path under /api/admin (e.g. "/info") and return the JSON body."""
        response = await self._request("GET", path, params=params)
        return response.json()

    async def get_mgmnt(self, path: str) -> Any:
        """GET a path under /api/mgmnt using HTTP Basic auth.

        Credentials are only passed through httpx's auth=, never in the URL or
        logs. There's intentionally no way to call /api/mgmnt's write operations.
        """
        url = self._mgmnt_url(path)
        auth = httpx.BasicAuth(
            self._settings.iris_username, self._settings.iris_password.get_secret_value()
        )
        response = await self._send("GET", url, path, auth=auth)
        return response.json()

    def _mgmnt_url(self, path: str) -> httpx.URL:
        """Build a URL under /api/mgmnt, refusing anything that could escape it.

        Rejects paths that don't start with "/" and any "." / ".." segments,
        including percent-encoded ones (httpx would otherwise normalize
        "/../admin" onto /api/admin and send our Basic credentials there).
        """
        base = httpx.URL(self._settings.iris_base_url.rstrip("/") + _MGMNT_BASE_PATH + "/")
        url = httpx.URL(f"{self._settings.iris_base_url.rstrip('/')}{_MGMNT_BASE_PATH}{path}")
        # Check both the raw path and the decoded one.
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

    async def put(
        self, path: str, json: dict[str, Any], params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """PUT to a path under /api/admin. `json` is sent as-is; `params` are optional query parameters."""
        response = await self._request("PUT", path, params=params, json=json)
        return response.json()

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        """DELETE a path under /api/admin (e.g. DELETE /v2/wallet/secret?name=...)."""
        await self._request("DELETE", path, params=params)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synchronous POST to a path under /api/admin.

        For endpoints that answer directly (e.g. POST /v2/database-dir returns
        201 with the new resource), not the 202-and-poll ones. `json` is sent
        as-is; some endpoints take their key as a query parameter instead
        (e.g. POST /v2/database-dir/mount?dir=...).
        """
        response = await self._request("POST", path, params=params, json=json)
        return response.json()

    async def post_async_task(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> str:
        """Start an IRIS async task and return its task id.

        IRIS answers 202 with Location: /api/admin/v1/async-result?id=<id>. We only
        take the id from it and poll /v2/async-result ourselves. Some endpoints
        take a JSON body (e.g. integrity-check), others query params.

        Raises IRISAsyncTaskError if there's no Location header or no id.
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
        """Poll /v2/async-result until the task finishes and return its result.

        Raises IRISAsyncTaskError if the task fails, is canceled, or doesn't
        finish within max_attempts.
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
        """Send a request and map errors. Only the path (not the full URL) goes into error messages."""
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
            # Some 4xx answers are normal outcomes (e.g. 404 from the OAuth2 server
            # endpoint when OAuth2 isn't configured). We always raise here; callers
            # that expect one can catch IRISResponseError and check .status_code.
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            raise IRISResponseError(response.status_code, body=error_body)

        return response
