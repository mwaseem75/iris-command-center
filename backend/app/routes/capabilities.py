"""A single, read-only route that serves the API Capability Explorer's data
(app/capabilities.py's CAPABILITY_REGISTRY — see that module's docstring for
what it is and where it comes from).

This route makes NO request to IRIS and requires no privilege to call: it
exposes only project-maintained metadata about the IRIS SysAdmin REST API
surface, not IRIS data itself — the exact same reasoning
app/routes/operations.py already documents for OPERATION_REGISTRY.

`available` is the one thing computed here rather than read verbatim off
the registry: for each entry with a `command_center_path`, this checks the
running app's OWN OpenAPI schema for a route matching that path and method
— never a hand-maintained boolean — so this list can never silently drift
out of sync with which routes actually exist. An entry with no
`command_center_path` (IRIS capabilities this backend only ever calls
internally, like login or async-task polling) is always `available=False`.
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
