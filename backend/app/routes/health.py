"""Health endpoint for the Command Center backend itself.

This reports whether the backend process is up. It does not call IRIS —
IRIS connectivity is a separate concern for a later step.
"""

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
