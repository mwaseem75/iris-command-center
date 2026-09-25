"""FastAPI application entry point.

Phase 2, Step 1: the Command Center's own health endpoint.
Phase 2, Step 2/3: wires up the shared IRISClient (created once at startup,
closed at shutdown) and the 13 verified, read-only IRIS routes.
Phase 2, Step 7: adds the first MUTATING route (journal_router) — see
docs/first-mutation-implementation.md. It has not been called against any
real IRIS instance.
Constructing IRISClient does not itself contact IRIS — no request is made
until a route that needs one is actually called (see app/auth/iris_auth.py:
the session is only obtained lazily, on first use).

Optional IRIS execution-trace persistence (app/observability/
iris_trace_writer.py): off by default (Settings.persist_traces_to_iris).
When enabled, an IRISTraceWriter is constructed here (itself making no
network call until first use — same lazy pattern as IRISClient above) and
registered with app/observability/store.py, which then best-effort,
additionally persists every trace it already records in-memory. Disabled,
this app behaves exactly as it did before this feature existed.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.iris_client.client import IRISClient
from app.observability import store as observability_store
from app.observability.iris_trace_writer import IRISTraceWriter
from app.routes.assistant import router as assistant_router
from app.routes.capabilities import router as capabilities_router
from app.routes.databases import router as databases_router
from app.routes.health import router as health_router
from app.routes.iris import router as iris_router
from app.routes.security_access import router as security_access_router
from app.routes.security_users import router as security_users_router
from app.routes.tasks import router as tasks_router
from app.routes.journal import router as journal_router
from app.routes.namespaces import router as namespaces_router
from app.routes.observability import router as observability_router
from app.routes.operations import router as operations_router
from app.routes.web_apps import router as web_apps_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.iris_client = IRISClient(settings)

    trace_writer: IRISTraceWriter | None = None
    if settings.persist_traces_to_iris:
        trace_writer = IRISTraceWriter(settings)
        observability_store.set_trace_persister(trace_writer)

    try:
        yield
    finally:
        await app.state.iris_client.aclose()
        if trace_writer is not None:
            trace_writer.close()
            observability_store.set_trace_persister(None)


app = FastAPI(title="IRIS Command Center", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(iris_router)
app.include_router(security_access_router)
app.include_router(security_users_router)
app.include_router(tasks_router)
app.include_router(journal_router)
app.include_router(namespaces_router)
app.include_router(databases_router)
app.include_router(web_apps_router)
app.include_router(operations_router)
app.include_router(assistant_router)
app.include_router(observability_router)
app.include_router(capabilities_router)
