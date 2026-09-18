"""Routes for the first four VERIFIED, read-only IRIS SysAdmin REST API
endpoints. All authentication/session handling is delegated entirely to the
shared IRISClient (via the get_iris_client dependency) — no route here
performs its own login or holds its own token.

Only GET requests are made against IRIS. No mutating call exists anywhere
in this module.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_iris_client
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import (
    IRISAuthError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)
from app.models.iris import DatabaseEntry, InfoResult, IRISEnvelope, NamespaceEntry, ProcessEntry

router = APIRouter(prefix="/api/iris", tags=["iris"])

_IRIS_CLIENT_ERRORS = (IRISAuthError, IRISConnectionError, IRISTimeoutError, IRISResponseError)


def _as_http_exception(
    exc: IRISAuthError | IRISConnectionError | IRISTimeoutError | IRISResponseError,
) -> HTTPException:
    """Translate an IRIS client error into a safe HTTPException.

    Never includes a credential, password, or JWT value — the underlying
    exceptions never carry one in the first place (see
    app/iris_client/exceptions.py), and only the exception type/status code
    is used here, never the raw IRIS response body.
    """
    if isinstance(exc, IRISAuthError):
        return HTTPException(status_code=502, detail="Could not authenticate with IRIS")
    if isinstance(exc, IRISConnectionError):
        return HTTPException(status_code=502, detail="Could not connect to IRIS")
    if isinstance(exc, IRISTimeoutError):
        return HTTPException(status_code=504, detail="Timed out waiting for IRIS")
    if isinstance(exc, IRISResponseError):
        return HTTPException(
            status_code=502,
            detail=f"IRIS returned an unexpected HTTP {exc.status_code}",
        )
    return HTTPException(status_code=502, detail="Unexpected error communicating with IRIS")


@router.get("/info", response_model=IRISEnvelope[InfoResult])
async def get_info(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[InfoResult]:
    try:
        raw = await client.get("/info")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[InfoResult].model_validate(raw)


@router.get("/namespaces", response_model=IRISEnvelope[list[NamespaceEntry]])
async def get_namespaces(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[NamespaceEntry]]:
    try:
        raw = await client.get("/v2/namespaces")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[NamespaceEntry]].model_validate(raw)


@router.get("/databases", response_model=IRISEnvelope[list[DatabaseEntry]])
async def get_databases(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[DatabaseEntry]]:
    try:
        raw = await client.get("/v2/databases")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[DatabaseEntry]].model_validate(raw)


@router.get("/processes", response_model=IRISEnvelope[list[ProcessEntry]])
async def get_processes(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[ProcessEntry]]:
    try:
        raw = await client.get("/v2/processes")
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc
    return IRISEnvelope[list[ProcessEntry]].model_validate(raw)
