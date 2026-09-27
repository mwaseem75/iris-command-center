"""POST /api/iris/demo/rehearsal: runs the Demo Activity rehearsal on request.

With confirmed=false (the default) the first operation stops at its
confirmation check and nothing changes.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from app.dependencies import get_caller_privileges, get_iris_client
from app.execution.demo_rehearsal import (
    RehearsalInProgressError,
    RehearsalResult,
    run_issue_resolution_rehearsal,
    run_rehearsal,
)
from app.iris_client.client import IRISClient

router = APIRouter(prefix="/api/iris", tags=["iris-operations"])


class DemoRehearsalRequest(BaseModel):
    """`confirmed` goes to every operation, like any mutating route. Extra fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmed: StrictBool = False
    # "issue_resolution" runs the manual IPM rehearsal; "issue_create" and
    # "issue_resolve" run its two steps separately (Create Demo Issue, then
    # Resolve Demo Issue). The automatic startup run always uses the standard one.
    scenario: Literal["standard", "issue_resolution", "issue_create", "issue_resolve"] = "standard"


@router.post("/demo/rehearsal", response_model=RehearsalResult)
async def demo_rehearsal(
    body: DemoRehearsalRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> RehearsalResult:
    """Returns 200 with the result, or 409 if a rehearsal is already running."""
    try:
        if body.scenario == "issue_create":
            return await run_issue_resolution_rehearsal(client, privileges, body.confirmed, step="create")
        if body.scenario == "issue_resolve":
            return await run_issue_resolution_rehearsal(client, privileges, body.confirmed, step="resolve")
        runner = run_issue_resolution_rehearsal if body.scenario == "issue_resolution" else run_rehearsal
        return await runner(client, privileges, body.confirmed)
    except RehearsalInProgressError as exc:
        raise HTTPException(status_code=409, detail="A demo rehearsal is already running.") from exc
