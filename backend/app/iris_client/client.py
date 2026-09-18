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

The response body is returned exactly as IRIS sent it (parsed JSON), with no
assumption about a result/status/console wrapper being present — verification
showed that wrapper is used by some operations (e.g. GET /info) but not others
(e.g. POST /login, which is flat). See docs/api-capability-matrix.md for the
per-endpoint, per-operation breakdown. Callers are responsible for interpreting
the shape appropriate to the specific endpoint they called.
"""

from typing import Any

import httpx

from app.auth.iris_auth import IRISAuthClient
from app.config import Settings
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError, IRISTimeoutError

_API_BASE_PATH = "/api/admin"


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
        return await self._request("GET", path, params=params)

    async def put(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        """Perform an authenticated PUT against the IRIS SysAdmin REST API.

        `path` is relative to /api/admin, e.g. "/v2/journal/settings". `json`
        is sent as the request body exactly as given — this method does not
        add, remove, or infer any field. Returns the parsed JSON response
        body verbatim.
        """
        return await self._request("PUT", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._auth.get_valid_session()
        url = f"{self._settings.iris_base_url.rstrip('/')}{_API_BASE_PATH}{path}"
        headers = {"Authorization": f"Bearer {session.access_token}"}

        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
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

        return response.json()
