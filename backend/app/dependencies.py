"""Shared FastAPI dependencies. The single IRISClient instance is created
once at application startup (see app/main.py's lifespan) and reused across
requests, so routes never construct their own client or duplicate the
authentication/session logic it wraps."""

from fastapi import Depends, HTTPException, Request

from app.embedded_python.diagnostics import EmbeddedPythonDiagnostics
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import (
    IRISAuthError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)
from app.models.iris import InfoResult, IRISEnvelope


def get_iris_client(request: Request) -> IRISClient:
    return request.app.state.iris_client


def get_python_diagnostics(request: Request) -> EmbeddedPythonDiagnostics:
    return request.app.state.python_diagnostics


async def get_caller_privileges(
    client: IRISClient = Depends(get_iris_client),
) -> frozenset[str]:
    """The ONLY legitimate source of `available_privileges` for the
    authorization layer (app/authorization/service.py's `authorize()`).

    Calls the already-Phase-1-verified GET /info endpoint (via the same
    authenticated IRISClient used for every read route) and returns the set
    of privilege names the CURRENT SESSION actually holds (`use: true`).
    This deliberately does not accept anything from the incoming HTTP
    request — a caller cannot claim a privilege by putting it in a request
    body or header; the only way to be authorized is to actually hold the
    privilege on the real IRIS session, confirmed by IRIS itself.
    """
    try:
        raw = await client.get("/info")
    except (IRISAuthError, IRISConnectionError, IRISTimeoutError) as exc:
        raise HTTPException(
            status_code=502, detail="Could not retrieve the caller's privileges from IRIS"
        ) from exc
    except IRISResponseError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"IRIS returned an unexpected HTTP {exc.status_code} for /info",
        ) from exc

    envelope = IRISEnvelope[InfoResult].model_validate(raw)
    return frozenset(name for name, flag in envelope.result.privileges.items() if flag.use)
