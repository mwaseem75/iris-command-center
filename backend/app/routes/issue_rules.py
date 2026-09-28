"""Custom Issue Rules: list, create and delete (V1).

A rule is detection-only data (see app/resolution/custom_rules.py); it's
evaluated by GET /api/iris/issues and never runs anything against IRIS.

Creating or deleting a rule changes Command Center configuration (and, with
PERSIST_ISSUE_RULES_TO_IRIS, the ^CommandCenterIssueRule global), so it
requires the caller's live IRIS Manage privilege (read from /info, like
every operation's authorization). Deleting also requires confirmed=true.
Like every other change, both are POSTs (the frontend never sends DELETE).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from app.dependencies import get_caller_privileges
from app.resolution import custom_rules
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.custom_rules import CustomIssueRule, RuleConflictError

router = APIRouter(prefix="/api/iris", tags=["issue-rules"])

_REQUIRED_PRIVILEGE = "Manage"


class SignalOption(BaseModel):
    key: str
    label: str
    field: str
    unit: str


class PageOption(BaseModel):
    key: str
    label: str


class IssueRulesResponse(BaseModel):
    rules: list[CustomIssueRule]
    signals: list[SignalOption]
    operators: list[str]
    pages: list[PageOption]
    max_rules: int
    persisted_to_iris: bool  # whether rules are saved to IRIS (else memory only)


class IssueRuleDeleteRequest(BaseModel):
    """Nothing is deleted without confirmed=true. Unknown fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    confirmed: StrictBool = False


class IssueRuleChange(BaseModel):
    rule: CustomIssueRule | None = None
    deleted: str | None = None
    persisted: bool  # False when saving to IRIS is off or failed


def _require_manage(privileges: frozenset[str]) -> None:
    if _REQUIRED_PRIVILEGE not in privileges:
        raise HTTPException(status_code=403, detail="Managing custom issue rules requires the Manage privilege.")


async def _persist(call, *args) -> bool:
    persister = custom_rules.get_persister()
    if persister is None:
        return False
    return await asyncio.get_running_loop().run_in_executor(None, getattr(persister, call), *args)


@router.get("/issue-rules", response_model=IssueRulesResponse)
async def list_issue_rules() -> IssueRulesResponse:
    return IssueRulesResponse(
        rules=custom_rules.list_rules(),
        signals=[SignalOption(key=s.key, label=s.label, field=s.field, unit=s.unit)
                 for s in custom_rules.SIGNALS.values()],
        operators=list(custom_rules.OPERATORS),
        pages=[PageOption(key=k, label=v) for k, v in custom_rules.INVESTIGATION_PAGES.items()],
        max_rules=custom_rules.MAX_RULES,
        persisted_to_iris=custom_rules.persistence_enabled(),
    )


@router.post("/issue-rules", response_model=IssueRuleChange, status_code=201)
async def create_issue_rule(
    rule: CustomIssueRule,
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> IssueRuleChange:
    """422 for an invalid rule, 403 without Manage, 409 for a duplicate name or too many rules."""
    _require_manage(privileges)
    if rule.name in ISSUE_CATALOG:
        raise HTTPException(status_code=409, detail=f"{rule.name!r} is a built-in issue type.")
    try:
        custom_rules.add_rule(rule)
    except RuleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IssueRuleChange(rule=rule, persisted=await _persist("save_sync", rule))


@router.post("/issue-rules/delete", response_model=IssueRuleChange)
async def delete_issue_rule(
    body: IssueRuleDeleteRequest,
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> IssueRuleChange:
    """403 without Manage, 428 without confirmed=true, 404 for an unknown rule."""
    _require_manage(privileges)
    if not body.confirmed:
        raise HTTPException(status_code=428, detail="Deleting a custom issue rule requires confirmed=true.")
    if not custom_rules.remove_rule(body.name):
        raise HTTPException(status_code=404, detail=f"No custom rule named {body.name!r}.")
    return IssueRuleChange(deleted=body.name, persisted=await _persist("delete_sync", body.name))
