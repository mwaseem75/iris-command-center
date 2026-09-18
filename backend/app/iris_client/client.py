"""Reusable IRIS SysAdmin REST API client abstraction.

Provides a single generic, authenticated GET method. It intentionally does
NOT expose per-endpoint methods (e.g. get_namespaces()) yet — those are
added in a later step, once each one is deliberately wired up. This keeps
authentication/request handling in one place so future endpoint methods can
reuse it without duplicating login or error-handling logic.

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
        session = await self._auth.get_valid_session()
        url = f"{self._settings.iris_base_url.rstrip('/')}{_API_BASE_PATH}{path}"
        headers = {"Authorization": f"Bearer {session.access_token}"}

        try:
            response = await self._http.get(
                url,
                params=params,
                headers=headers,
                timeout=self._settings.iris_request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise IRISTimeoutError(f"Timed out calling IRIS {path}") from exc
        except httpx.ConnectError as exc:
            raise IRISConnectionError(f"Could not connect to IRIS calling {path}") from exc

        if response.status_code >= 400:
            # Note for future endpoint-specific wrappers: verification showed
            # some 4xx responses are documented, valid outcomes rather than
            # errors (e.g. GET /v2/security/oauth2/server returns 404 when
            # OAuth2 simply isn't configured — see api-capability-matrix.md).
            # This generic client always raises on 4xx/5xx; callers that need
            # to treat a specific documented status as non-error should catch
            # IRISResponseError and inspect .status_code themselves.
            raise IRISResponseError(response.status_code)

        return response.json()
