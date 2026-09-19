"""A single, read-only route exposing the in-memory execution trace store
(app/observability/store.py). This route makes NO request to IRIS — traces
are populated entirely by app/execution/executor.py's OperationExecutor as
a side effect of real operation attempts (see app/observability/tracer.py)
— and requires no privilege to call, since it exposes only already-
recorded, already-safe trace data (see app/observability/models.py's
module docstring for what is and is never recorded).

No mutating call exists anywhere in this module.
"""

from fastapi import APIRouter

from app.models.schemas import TraceListResponse
from app.observability.store import list_traces

router = APIRouter(prefix="/api/iris", tags=["observability"])


@router.get("/observability/traces", response_model=TraceListResponse)
async def get_execution_traces() -> TraceListResponse:
    return TraceListResponse(traces=list_traces())
