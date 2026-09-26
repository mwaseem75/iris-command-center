"""Logs in to the IRIS Admin API and keeps the JWT in memory.

POST /api/admin/login returns a flat body with access_token/refresh_token
(401 with an empty body on failure). Tokens live about 60 seconds. We don't
use the refresh token; we just log in again shortly before expiry.
The token is never logged or written anywhere.
"""

import time
from asyncio import Lock
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.iris_client.exceptions import IRISAuthError, IRISConnectionError, IRISTimeoutError

_EXPIRY_LEEWAY_SECONDS = 5.0


@dataclass
class IRISSession:
    access_token: str
    refresh_token: str
    sub: str
    exp: float

    def __repr__(self) -> str:  # keep the token out of logs and reprs
        return f"IRISSession(sub={self.sub!r}, exp={self.exp!r}, access_token=<redacted>, refresh_token=<redacted>)"

    __str__ = __repr__

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.exp - _EXPIRY_LEEWAY_SECONDS)


class IRISAuthClient:
    """Gets and caches an IRIS session, logging in again when needed."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient):
        self._settings = settings
        self._http = http_client
        self._session: IRISSession | None = None
        self._lock = Lock()

    async def get_valid_session(self) -> IRISSession:
        async with self._lock:
            if self._session is None or self._session.is_expired:
                self._session = await self._login()
            return self._session

    async def _login(self) -> IRISSession:
        url = f"{self._settings.iris_base_url.rstrip('/')}/api/admin/login"
        payload = {
            "user": self._settings.iris_username,
            "password": self._settings.iris_password.get_secret_value(),
        }
        try:
            response = await self._http.post(
                url,
                json=payload,
                timeout=self._settings.iris_request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise IRISTimeoutError("Timed out authenticating against IRIS") from exc
        except httpx.ConnectError as exc:
            raise IRISConnectionError("Could not connect to IRIS to authenticate") from exc

        if response.status_code != 200:
            # Don't include the response body, only the status code.
            raise IRISAuthError(f"IRIS login failed with HTTP {response.status_code}")

        body = response.json()
        try:
            return IRISSession(
                access_token=body["access_token"],
                refresh_token=body["refresh_token"],
                sub=body["sub"],
                exp=float(body["exp"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IRISAuthError(
                "IRIS login response did not match the verified LoginResponse shape"
            ) from exc
