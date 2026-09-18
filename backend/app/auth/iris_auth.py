"""Authentication/session foundation for obtaining and holding an IRIS JWT.

Grounded in what was directly verified against a real IRIS 2026.2 instance
(see docs/phase-1-iris-container-verification.md):

- POST {base_url}/api/admin/login with {"user": ..., "password": ...} returns,
  on success, a FLAT JSON body (no result/status/console wrapper):
  {"access_token": ..., "refresh_token": ..., "sub": ..., "iat": ..., "exp": ...}
- On failure it returns 401 with an empty body.
- The observed access_token lifetime was ~60 seconds (exp - iat).

The /refresh, /logout, and /revoke endpoints were never verified, so this
layer does not use the refresh_token yet — it simply re-authenticates with
the configured credentials once the access token is close to expiring.

The session/token is held in memory only. It is never written to disk,
logged, or included in any exception message.
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

    def __repr__(self) -> str:  # never leak the token via logs/debuggers
        return f"IRISSession(sub={self.sub!r}, exp={self.exp!r}, access_token=<redacted>, refresh_token=<redacted>)"

    __str__ = __repr__

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.exp - _EXPIRY_LEEWAY_SECONDS)


class IRISAuthClient:
    """Obtains and caches a valid IRIS session, re-authenticating as needed."""

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
            # Deliberately do not include the response body: it could, in
            # principle, echo back request data. Only the status is safe.
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
