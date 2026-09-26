"""Lists the registered operations (app/authorization/operations.py). No IRIS call.

The frontend reads operation names, privileges and confirmation rules from
here instead of keeping its own copy.
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
