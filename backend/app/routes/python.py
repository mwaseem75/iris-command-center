"""A single, read-only route exposing host diagnostics computed by Embedded
Python inside IRIS (see app/embedded_python/diagnostics.py for the fixed
set of calls and the safety rules). It takes no parameters, so nothing a
caller sends can influence which Python code runs inside IRIS.

No mutating call exists anywhere in this module.
"""

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
    # The Native API driver is blocking — keep it off the event loop.
    try:
        return await asyncio.get_running_loop().run_in_executor(None, diagnostics.collect_sync)
    except EmbeddedPythonUnavailableError:
        raise HTTPException(
            status_code=502, detail="Could not run Embedded Python diagnostics in IRIS"
        ) from None
