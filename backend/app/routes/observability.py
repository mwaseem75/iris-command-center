"""Returns the recorded execution traces from the in-memory store. No IRIS call.

Traces are recorded by the executor whenever an operation is attempted.
"""

from fastapi import APIRouter

from app.models.schemas import TraceListResponse
from app.observability.store import list_traces

router = APIRouter(prefix="/api/iris", tags=["observability"])


@router.get("/observability/traces", response_model=TraceListResponse)
async def get_execution_traces() -> TraceListResponse:
    return TraceListResponse(traces=list_traces())
