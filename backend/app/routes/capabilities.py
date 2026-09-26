"""Serves the API Explorer data (app/capabilities.py). No IRIS call.

`available` is worked out here by checking the app's own routes for each
entry's command_center_path, so the list can't drift from what actually
exists. Entries without a path (login, async polling) are never available.
"""

from fastapi import APIRouter, Request

from app.capabilities import CAPABILITY_REGISTRY
from app.models.schemas import CapabilityListResponse, CapabilityViewEntry

router = APIRouter(prefix="/api/iris", tags=["capabilities"])


@router.get("/capabilities", response_model=CapabilityListResponse)
async def list_capabilities(request: Request) -> CapabilityListResponse:
    registered_paths: dict[str, dict] = request.app.openapi()["paths"]

    def is_available(path: str | None, method: str | None) -> bool:
        if path is None or method is None:
            return False
        return method.lower() in registered_paths.get(path, {})

    return CapabilityListResponse(
        capabilities=[
            CapabilityViewEntry(
                **entry.model_dump(),
                available=is_available(entry.command_center_path, entry.command_center_method),
            )
            for entry in CAPABILITY_REGISTRY
        ]
    )
