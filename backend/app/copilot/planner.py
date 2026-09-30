"""Deterministic gateway from untrusted Copilot prose to a closed operation plan."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.copilot.intents import CopilotIntent, classify_intent
from app.execution.web_app_set_enabled_handler import _PROTECTED_APPS, _normalize as _web_app_key
from app.models.copilot import (
    CopilotDatabaseMountParameters,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotPlanRequest,
    CopilotPlanningReason,
    CopilotPlanningResult,
    CopilotTargetKind,
    CopilotWebAppDisableParameters,
)
from app.resolution.catalog import get_issue_resolution
from app.resolution.models import IssueResolution
from app.routes.issues import DatabaseMountIssue, IssuesResponse, WebAppNamespaceIssue

_PROPOSAL_PATTERN = re.compile(
    r"^\s*set\s+purge[ _]?archived\s+to\s+(true|false)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_NEGATED_REQUEST_PATTERN = re.compile(r"\b(?:do\s+not|don't|never|not)\b", re.IGNORECASE)
_MESSAGE_PATTERNS = (
    (
        re.compile(
            r"\b(?:set|change|update)\s+(?:the\s+)?purge[ _]?archived\s+(?:to|=)\s*(true|false)\b",
            re.IGNORECASE,
        ),
        {"true": True, "false": False},
    ),
    (
        re.compile(r"\bturn\s+(on|off)\s+(?:the\s+)?purge[ _]?archived\b", re.IGNORECASE),
        {"on": True, "off": False},
    ),
    (
        re.compile(r"\b(enable|disable)\s+(?:the\s+)?purge[ _]?archived\b", re.IGNORECASE),
        {"enable": True, "disable": False},
    ),
)

# database.mount: the database name only selects a currently detected
# database_dismounted issue; its parameters come from the issue catalog.
_DATABASE_NAME = r"([A-Za-z0-9_%-]{1,64})"
_MOUNT_PROPOSAL_PATTERN = re.compile(
    rf"^\s*mount\s+database\s+{_DATABASE_NAME}\s*[.!]?\s*$",
    re.IGNORECASE,
)
_MOUNT_MESSAGE_PATTERNS = (
    re.compile(rf"\bmount\s+(?:the\s+)?{_DATABASE_NAME}\s+database\b", re.IGNORECASE),
    re.compile(rf"\bmount\s+(?:the\s+)?database\s+{_DATABASE_NAME}\b", re.IGNORECASE),
)
_NOT_DATABASE_NAMES = frozenset({"the", "database"})
_DATABASE_WORD = re.compile(r"\bdatabases?\b", re.IGNORECASE)

# web_app.set_enabled (disable only): the whole message must be the request,
# so extra text, a second target or an "enable" never matches.
_WEB_APP_NAME = r"(/\S{0,255}?)"
_WEB_APP_PROPOSAL_PATTERN = re.compile(
    rf"^\s*disable\s+web\s+app\s+{_WEB_APP_NAME}\s*[.!]?\s*$",
    re.IGNORECASE,
)
_WEB_APP_MESSAGE_PATTERNS = (
    re.compile(
        rf"\s*disable\s+(?:the\s+)?web\s*app(?:lication)?\s+{_WEB_APP_NAME}\s*[.!]?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\s*disable\s+(?:the\s+)?{_WEB_APP_NAME}\s+web\s*app(?:lication)?\s*[.!]?\s*",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class CatalogOperation:
    """A Copilot operation that resolves one currently detected Issue Resolver
    issue. The request's name only selects the issue; the plan's target and
    parameters always come from that issue and its catalog entry."""

    operation: CopilotOperation
    issue_type: str
    issue_model: type[BaseModel]
    target_kind: CopilotTargetKind
    parameters_model: type[BaseModel]
    proposal_pattern: re.Pattern[str]
    # The normalized name the message asks for, or None if it isn't exactly one.
    requested_name: Callable[[str], str | None]
    # How names are compared (issue display name, proposal and message).
    name_key: Callable[[str], str]
    # Extra eligibility beyond detection (defense in depth).
    eligible: Callable[[Any, IssueResolution], bool]
    plan_reason: str
    completed: str


def _requested_database_name(message: str) -> str | None:
    # Exactly one database may be mentioned: no negation, no multiple targets.
    if _NEGATED_REQUEST_PATTERN.search(message) or len(_DATABASE_WORD.findall(message)) != 1:
        return None
    names = {
        name.casefold()
        for pattern in _MOUNT_MESSAGE_PATTERNS
        for name in pattern.findall(message)
        if name.casefold() not in _NOT_DATABASE_NAMES
    }
    return names.pop() if len(names) == 1 else None


def _requested_web_app_name(message: str) -> str | None:
    for pattern in _WEB_APP_MESSAGE_PATTERNS:
        match = pattern.fullmatch(message)
        if match is not None:
            return _web_app_key(match.group(1))
    return None


def _database_eligible(issue: DatabaseMountIssue, entry: IssueResolution) -> bool:
    return issue.database.upper() not in entry.excluded_databases and not issue.mirrored


def _web_app_eligible(issue: WebAppNamespaceIssue, entry: IssueResolution) -> bool:
    return (
        issue.enabled
        and _web_app_key(issue.web_app) not in _PROTECTED_APPS
        and "system" not in issue.app_type.lower()
    )


CATALOG_OPERATIONS: dict[CopilotOperation, CatalogOperation] = {
    CopilotOperation.DATABASE_MOUNT: CatalogOperation(
        operation=CopilotOperation.DATABASE_MOUNT,
        issue_type="database_dismounted",
        issue_model=DatabaseMountIssue,
        target_kind=CopilotTargetKind.DATABASE,
        parameters_model=CopilotDatabaseMountParameters,
        proposal_pattern=_MOUNT_PROPOSAL_PATTERN,
        requested_name=_requested_database_name,
        name_key=str.casefold,
        eligible=_database_eligible,
        plan_reason="The Issue Resolver currently detects this database as dismounted.",
        completed="The database was mounted",
    ),
    CopilotOperation.WEB_APP_SET_ENABLED: CatalogOperation(
        operation=CopilotOperation.WEB_APP_SET_ENABLED,
        issue_type="web_app_namespace_missing",
        issue_model=WebAppNamespaceIssue,
        target_kind=CopilotTargetKind.WEB_APP,
        parameters_model=CopilotWebAppDisableParameters,
        proposal_pattern=_WEB_APP_PROPOSAL_PATTERN,
        requested_name=_requested_web_app_name,
        name_key=_web_app_key,
        eligible=_web_app_eligible,
        plan_reason=(
            "The Issue Resolver currently detects this enabled web application's namespace as missing."
        ),
        completed="The web application was disabled",
    ),
}


class CopilotPlanningService:
    """Creates plans only for explicitly allowlisted, parameterized actions."""

    def plan(
        self,
        request: CopilotPlanRequest,
        issues: IssuesResponse | None = None,
    ) -> CopilotPlanningResult:
        """`issues` is the current Issue Resolver detection; only a
        catalog-backed proposal uses it, and None means it couldn't be read."""
        deterministic_intent = classify_intent(request.message)
        if deterministic_intent is CopilotIntent.UNKNOWN:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.UNSUPPORTED_INTENT,
            )
        if deterministic_intent is not request.intent:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.INTENT_MISMATCH,
            )
        if deterministic_intent is not CopilotIntent.RESOLUTION_REQUEST:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.NO_OPERATION_PROPOSED,
            )
        if request.proposed_action is None:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.NO_OPERATION_PROPOSED,
            )

        spec = catalog_operation_for(request)
        if spec is not None:
            return _plan_catalog_operation(spec, request, deterministic_intent, issues)

        proposal = _PROPOSAL_PATTERN.fullmatch(request.proposed_action)
        target_value = _requested_purge_archived_value(request.message)
        if proposal is None or target_value is None:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.UNSUPPORTED_ACTION,
            )

        proposed_value = proposal.group(1).lower() == "true"
        if proposed_value is not target_value:
            return CopilotPlanningResult(
                intent=deterministic_intent,
                reason=CopilotPlanningReason.UNSUPPORTED_ACTION,
            )

        return CopilotPlanningResult(
            intent=deterministic_intent,
            reason=CopilotPlanningReason.PLAN_CREATED,
            plan=CopilotOperationPlan(
                operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
                target=CopilotOperationTarget(
                    kind=CopilotTargetKind.JOURNAL_SETTINGS,
                    identifier="journal-settings",
                ),
                parameters=CopilotOperationParameters(PurgeArchived=target_value),
                reason="The message and exact proposed action agree on the journal setting value.",
                requires_confirmation=True,
            ),
        )


def _requested_purge_archived_value(message: str) -> bool | None:
    if _NEGATED_REQUEST_PATTERN.search(message):
        return None
    matches: list[bool] = []
    for pattern, values in _MESSAGE_PATTERNS:
        matches.extend(values[match.lower()] for match in pattern.findall(message))
    if not matches or any(value is not matches[0] for value in matches):
        return None
    return matches[0]


def catalog_operation_for(request: CopilotPlanRequest) -> CatalogOperation | None:
    """The catalog-backed operation the proposed action names, if any."""
    if request.proposed_action is None:
        return None
    return next(
        (
            spec
            for spec in CATALOG_OPERATIONS.values()
            if spec.proposal_pattern.fullmatch(request.proposed_action) is not None
        ),
        None,
    )


def catalog_parameters(spec: CatalogOperation, issue: Any) -> BaseModel | None:
    """The catalog's parameters for resolving `issue` with `spec`, or None if
    the catalog doesn't resolve it with that operation or it isn't eligible."""
    entry = get_issue_resolution(spec.issue_type)
    if (
        entry is None
        or entry.operation != spec.operation.value
        or not isinstance(issue, spec.issue_model)
        or issue.kind != spec.issue_type
        or not spec.eligible(issue, entry)
    ):
        return None
    values = {
        binding.name: (
            getattr(issue, binding.from_issue_field, None)
            if binding.from_issue_field
            else binding.value
        )
        for binding in entry.parameters
    }
    try:
        return spec.parameters_model(**values)
    except (TypeError, ValidationError):
        return None


def _plan_catalog_operation(
    spec: CatalogOperation,
    request: CopilotPlanRequest,
    intent: CopilotIntent,
    issues: IssuesResponse | None,
) -> CopilotPlanningResult:
    proposal = spec.proposal_pattern.fullmatch(request.proposed_action or "")
    requested = spec.requested_name(request.message)
    if proposal is None or requested is None or spec.name_key(proposal.group(1)) != requested:
        return CopilotPlanningResult(intent=intent, reason=CopilotPlanningReason.UNSUPPORTED_ACTION)
    if issues is None:
        return CopilotPlanningResult(intent=intent, reason=CopilotPlanningReason.ISSUES_UNAVAILABLE)

    matches = [
        issue
        for issue in issues.issues
        if isinstance(issue, spec.issue_model)
        and spec.name_key(issue.resource.display_name) == requested
    ]
    if not matches:
        return CopilotPlanningResult(intent=intent, reason=CopilotPlanningReason.ISSUE_NOT_DETECTED)
    if len(matches) > 1:
        return CopilotPlanningResult(intent=intent, reason=CopilotPlanningReason.AMBIGUOUS_TARGET)

    issue = matches[0]
    parameters = catalog_parameters(spec, issue)
    if parameters is None:
        return CopilotPlanningResult(intent=intent, reason=CopilotPlanningReason.UNSUPPORTED_ACTION)
    return CopilotPlanningResult(
        intent=intent,
        reason=CopilotPlanningReason.PLAN_CREATED,
        plan=CopilotOperationPlan(
            operation=spec.operation,
            target=CopilotOperationTarget(
                kind=spec.target_kind,
                identifier=issue.resource.display_name,
                issue_id=issue.issue_id,
            ),
            parameters=parameters,
            reason=spec.plan_reason,
            requires_confirmation=True,
        ),
    )
