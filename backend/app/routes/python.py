"""Endpoint for the Embedded Python host diagnostics (read-only, no parameters)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_python_diagnostics
from app.embedded_python.diagnostics import (
    EmbeddedPythonDiagnostics,
    EmbeddedPythonUnavailableError,
    PythonDiagnostics,
)

router = APIRouter(prefix="/api/iris", tags=["embedded-python"])


@router.get("/python/diagnostics", response_model=PythonDiagnostics)
async def get_embedded_python_diagnostics(
    diagnostics: EmbeddedPythonDiagnostics = Depends(get_python_diagnostics),
) -> PythonDiagnostics:
    # The driver is blocking, so run it in a thread.
    try:
        return await asyncio.get_running_loop().run_in_executor(None, diagnostics.collect_sync)
    except EmbeddedPythonUnavailableError:
        raise HTTPException(
            status_code=502, detail="Could not run Embedded Python diagnostics in IRIS"
        ) from None
