"""A single, read-only route that lists the operations already registered
in the authorization/execution framework (app/authorization/operations.py).

This route makes NO request to IRIS — it serializes OPERATION_REGISTRY, a
static, in-process Python dict — and requires no privilege to call, since
it exposes only metadata about what operations exist, not IRIS data itself.
It exists so consumers (the frontend, in particular) never need their own
copy of operation names, descriptions, required privileges, or
confirmation rules: this is the single source of truth, already used
internally by app/routes/journal.py's mutating route.

No mutating call exists anywhere in this module.
"""

from fastapi import APIRouter

from app.authorization.operations import OPERATION_REGISTRY
from app.models.schemas import OperationSummary, OperationsListResponse

router = APIRouter(prefix="/api/iris", tags=["operations"])


@router.get("/operations", response_model=OperationsListResponse)
async def list_operations() -> OperationsListResponse:
    return OperationsListResponse(
        operations=[
            OperationSummary(
                name=operation.name,
                description=operation.description,
                kind=operation.kind,
                required_privileges=sorted(p.value for p in operation.required_privileges),
                risk_level=operation.risk_level,
                confirmation_required=operation.confirmation_required,
            )
            for operation in OPERATION_REGISTRY.values()
        ]
    )
