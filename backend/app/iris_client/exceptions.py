"""Errors raised by the IRIS client. Messages never include credentials or tokens."""

from typing import Any


class IRISClientError(Exception):
    """Base class for IRIS client errors."""


class IRISAuthError(IRISClientError):
    """Login to IRIS failed (e.g. wrong credentials)."""


class IRISConnectionError(IRISClientError):
    """IRIS couldn't be reached."""


class IRISTimeoutError(IRISClientError):
    """IRIS didn't answer within the configured timeout."""


class IRISResponseError(IRISClientError):
    """IRIS returned a non-success HTTP status.

    `body` is the parsed JSON body if there was one. Some 4xx responses are
    expected outcomes (e.g. 404 when OAuth2 isn't configured), so callers can
    check the body.
    """

    def __init__(self, status_code: int, message: str = "", body: dict[str, Any] | None = None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"IRIS responded with HTTP {status_code}" + (f": {message}" if message else ""))


class IRISAsyncTaskError(IRISClientError):
    """An IRIS async task didn't produce a usable result.

    Happens when the 202 had no Location header, the task failed or was
    canceled, or it didn't finish in time. `state` is the last task state
    seen (None if we never got a task id).
    """

    def __init__(self, message: str, state: str | None = None):
        self.state = state
        super().__init__(message)
