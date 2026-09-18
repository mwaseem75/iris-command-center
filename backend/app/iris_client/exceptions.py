"""Exceptions raised by the IRIS client/auth layer. Never include a
credential or token value in an exception message."""


class IRISClientError(Exception):
    """Base class for all IRIS client errors."""


class IRISAuthError(IRISClientError):
    """Raised when authenticating against IRIS fails (e.g. invalid credentials)."""


class IRISConnectionError(IRISClientError):
    """Raised when IRIS cannot be reached at all (network/connection failure)."""


class IRISTimeoutError(IRISClientError):
    """Raised when a request to IRIS exceeds the configured timeout."""


class IRISResponseError(IRISClientError):
    """Raised when IRIS responds with a non-success HTTP status."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"IRIS responded with HTTP {status_code}" + (f": {message}" if message else ""))
