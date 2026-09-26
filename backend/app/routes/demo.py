"""POST /api/iris/demo/rehearsal — the user-triggered Demo Activity
rehearsal (see app/execution/demo_rehearsal.py). Never runs on its own: only
an explicit POST starts it, and `confirmed` defaults to False, in which case
the existing framework stops the first operation at its confirmation check
and nothing changes.
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
    """`confirmed` is passed unchanged to every operation's ExecutionContext
    — the same confirmation mechanism as every mutating route. There is no
    force/bypass field (`extra="forbid"`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmed: StrictBool = False
    # "issue_resolution" = the manual IPM Issue Resolution Rehearsal; the
    # automatic startup run always uses the standard rehearsal.
    scenario: Literal["standard", "issue_resolution"] = "standard"


@router.post("/demo/rehearsal", response_model=RehearsalResult)
async def demo_rehearsal(
    body: DemoRehearsalRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> RehearsalResult:
    """HTTP 200 with a structured result (the outcome is in `status` and each
    step), or 409 while another rehearsal is still running."""
    try:
        runner = run_issue_resolution_rehearsal if body.scenario == "issue_resolution" else run_rehearsal
        return await runner(client, privileges, body.confirmed)
    except RehearsalInProgressError as exc:
        raise HTTPException(status_code=409, detail="A demo rehearsal is already running.") from exc
