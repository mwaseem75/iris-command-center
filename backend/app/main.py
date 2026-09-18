"""FastAPI application entry point.

Phase 2, Step 1: the Command Center's own health endpoint.
Phase 2, Step 2: wires up the shared IRISClient (created once at startup,
closed at shutdown) and the first four verified, read-only IRIS routes.
Constructing IRISClient does not itself contact IRIS — no request is made
until a route that needs one is actually called (see app/auth/iris_auth.py:
the session is only obtained lazily, on first use).
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.config import get_settings
from app.iris_client.client import IRISClient
from app.routes.health import router as health_router
from app.routes.iris import router as iris_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.iris_client = IRISClient(get_settings())
    try:
        yield
    finally:
        await app.state.iris_client.aclose()


app = FastAPI(title="IRIS Command Center", lifespan=lifespan)

app.include_router(health_router)
app.include_router(iris_router)
