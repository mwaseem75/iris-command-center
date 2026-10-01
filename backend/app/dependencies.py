"""Shared FastAPI dependencies (the clients created at startup in app/main.py)."""

from fastapi import Depends, HTTPException, Query, Request

from app.embedded_python.diagnostics import EmbeddedPythonDiagnostics
from app.instances.clients import InactiveInstanceError, InstanceClientPool, UnknownInstanceError
from app.instances.credentials import CredentialStoreError, WalletCredentialStore
from app.instances.models import PRIMARY_INSTANCE_ID
from app.instances.registry import InstanceRegistry
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


def get_instance_registry(request: Request) -> InstanceRegistry:
    return request.app.state.instance_registry


def get_credential_store(request: Request) -> WalletCredentialStore:
    return request.app.state.credential_store


def get_instance_clients(request: Request) -> InstanceClientPool | None:
    """None until startup has created it (e.g. in tests that skip startup)."""
    return getattr(request.app.state, "instance_clients", None)


async def get_read_client(
    instance: str | None = Query(
        default=None,
        max_length=64,
        description="Registered instance id to read from (default: the Primary).",
    ),
    primary_client: IRISClient = Depends(get_iris_client),
    clients: InstanceClientPool | None = Depends(get_instance_clients),
) -> IRISClient:
    """The IRIS client for an instance-scoped read route.

    No `instance` (or "primary") is the Primary, exactly as before. Any other
    id must be a registered, active instance; its credential is resolved here
    from the IRIS Wallet and never reaches the caller. Only read routes use
    this; changes always go to the Primary.
    """
    if instance is None or instance == PRIMARY_INSTANCE_ID:
        return primary_client
    if clients is None:
        raise HTTPException(status_code=503, detail="Instances are not available yet.")
    try:
        return await clients.client_for_id(instance)
    except UnknownInstanceError:
        raise HTTPException(status_code=404, detail="No instance with this id.") from None
    except InactiveInstanceError:
        raise HTTPException(status_code=409, detail="The instance is inactive.") from None
    except CredentialStoreError:
        raise HTTPException(status_code=502, detail="The instance's stored credential could not be read.") from None


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
