"""Shared FastAPI dependencies (the clients created at startup in app/main.py)."""

from fastapi import Depends, HTTPException, Request

from app.embedded_python.diagnostics import EmbeddedPythonDiagnostics
from app.iris_client.client import IRISClient
from app.knowledge.store import IRISKnowledgeStore
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


def get_knowledge_store(request: Request) -> IRISKnowledgeStore | None:
    """Returns None when knowledge search is turned off."""
    return getattr(request.app.state, "knowledge_store", None)


async def get_caller_privileges(
    client: IRISClient = Depends(get_iris_client),
) -> frozenset[str]:
    """Privileges the current IRIS session actually holds.

    Read from IRIS's /info (entries with use: true). This is the only source
    authorization uses, so a caller can't claim privileges through the request.
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
