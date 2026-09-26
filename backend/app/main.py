"""FastAPI app: creates the shared clients at startup and registers the routes.

Optional features switched on by settings:
- PERSIST_TRACES_TO_IRIS: reload saved execution traces at startup and keep
  saving new ones to ^CommandCenterTrace.
- ENABLE_KNOWLEDGE_SEARCH: create/reindex CommandCenter.Knowledge at startup.
- AUTO_RUN_DEMO_ACTIVITY: run the Demo Activity rehearsal once in the
  background (a marker in USER stops it from repeating).

Nothing here talks to IRIS until a route or one of these features needs it.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.embedded_python.diagnostics import EmbeddedPythonDiagnostics
from app.execution.demo_autorun import DemoAutoRunMarker, StartupDemoActivity
from app.iris_client.client import IRISClient
from app.knowledge.store import IRISKnowledgeStore, KnowledgeStoreUnavailableError
from app.observability import store as observability_store
from app.observability.iris_trace_writer import IRISTraceWriter
from app.routes.assistant import router as assistant_router
from app.routes.capabilities import router as capabilities_router
from app.routes.databases import router as databases_router
from app.routes.demo import router as demo_router
from app.routes.health import router as health_router
from app.routes.iris import router as iris_router
from app.routes.issues import router as issues_router
from app.routes.security_access import router as security_access_router
from app.routes.security_users import router as security_users_router
from app.routes.tasks import router as tasks_router
from app.routes.journal import router as journal_router
from app.routes.knowledge import router as knowledge_router
from app.routes.namespaces import router as namespaces_router
from app.routes.observability import router as observability_router
from app.routes.operations import router as operations_router
from app.routes.python import router as python_router
from app.routes.web_apps import router as web_apps_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.iris_client = IRISClient(settings)
    app.state.python_diagnostics = EmbeddedPythonDiagnostics(settings)

    trace_writer: IRISTraceWriter | None = None
    if settings.persist_traces_to_iris:
        trace_writer = IRISTraceWriter(settings)
        # Reload saved traces so they survive a backend restart.
        # The driver is blocking, so run it off the event loop.
        persisted = await asyncio.get_running_loop().run_in_executor(
            None, trace_writer.load_recent_sync
        )
        observability_store.hydrate_traces(persisted)
        observability_store.set_trace_persister(trace_writer)

    knowledge_store: IRISKnowledgeStore | None = None
    if settings.enable_knowledge_search:
        knowledge_store = IRISKnowledgeStore(settings)
        # Build the knowledge table off the event loop. If IRIS isn't
        # reachable yet, the first search will try again.
        try:
            await asyncio.get_running_loop().run_in_executor(None, knowledge_store.ensure_indexed_sync)
        except KnowledgeStoreUnavailableError:
            logger.warning("Knowledge search enabled, but IRIS indexing failed at startup; will retry on first search.")
    app.state.knowledge_store = knowledge_store

    # Runs in the background and waits for IRIS on its own. Stopped
    # before the IRIS client is closed.
    demo_activity: StartupDemoActivity | None = None
    if settings.auto_run_demo_activity:
        demo_activity = StartupDemoActivity(app.state.iris_client, DemoAutoRunMarker(settings))
        demo_activity.start()

    try:
        yield
    finally:
        if demo_activity is not None:
            await demo_activity.stop()
        await app.state.iris_client.aclose()
        app.state.python_diagnostics.close()
        if knowledge_store is not None:
            knowledge_store.close()
        if trace_writer is not None:
            trace_writer.close()
            observability_store.set_trace_persister(None)


app = FastAPI(title="IRIS Command Center", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://localhost:52773"],
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
app.include_router(demo_router)
app.include_router(web_apps_router)
app.include_router(operations_router)
app.include_router(assistant_router)
app.include_router(observability_router)
app.include_router(capabilities_router)
app.include_router(python_router)
app.include_router(knowledge_router)
app.include_router(issues_router)
