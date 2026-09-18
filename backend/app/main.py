"""FastAPI application entry point.

Phase 2, Step 1 (backend foundation): registers only the Command Center's
own health endpoint. No IRIS API call is made at import or startup time.
"""

from fastapi import FastAPI

from app.routes.health import router as health_router

app = FastAPI(title="IRIS Command Center")

app.include_router(health_router)
