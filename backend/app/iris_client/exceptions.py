"""Exceptions raised by the IRIS client/auth layer. Never include a
credential or token value in an exception message."""

from typing import Any


class IRISClientError(Exception):
    """Base class for all IRIS client errors."""


class IRISAuthError(IRISClientError):
    """Raised when authenticating against IRIS fails (e.g. invalid credentials)."""


class IRISConnectionError(IRISClientError):
    """Raised when IRIS cannot be reached at all (network/connection failure)."""


class IRISTimeoutError(IRISClientError):
    """Raised when a request to IRIS exceeds the configured timeout."""


class IRISResponseError(IRISClientError):
    """Raised when IRIS responds with a non-success HTTP status.

    `body` is the parsed JSON response body, when IRIS returned one and it
    was valid JSON, else None. Some 4xx statuses are documented, valid
    application-level outcomes rather than true errors (e.g. GET
    /v2/security/oauth2/server returns 404 with a structured body when
    OAuth2 simply isn't configured — see api-capability-matrix.md). Callers
    that need to distinguish that from a real failure can inspect `.body`
    themselves; this exception never omits it to save space, but it is
    still just the response IRIS already sent — nothing extra is added.
    """

    def __init__(self, status_code: int, message: str = "", body: dict[str, Any] | None = None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"IRIS responded with HTTP {status_code}" + (f": {message}" if message else ""))


class IRISAsyncTaskError(IRISClientError):
    """Raised when IRIS's async-task pattern (POST returns 202 + a Location
    header to poll, see docs/api-capability-matrix.md's "POST
    /v2/security/audit/records" entry) doesn't end in a usable result:

    - the 202 response had no Location header to extract a task id from,
    - the task ended in IRIS's own "Failed" or "Canceled" state, or
    - the task never reached a terminal state within the configured number
      of polling attempts.

    `state` is the last observed IRIS task State (e.g. "Failed", "Running"),
    or None if no Location header was ever obtained.
    """

    def __init__(self, message: str, state: str | None = None):
        self.state = state
        super().__init__(message)
