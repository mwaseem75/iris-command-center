"""Read-only health report built from existing Issue Resolver checks."""

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.dependencies import get_iris_client
from app.iris_client.client import IRISClient
from app.models.schemas import (
    HealthCategoryId,
    HealthCategoryResult,
    HealthEvidence,
    HealthFinding,
    HealthInvestigationDestination,
    HealthRecommendation,
    HealthReport,
    HealthSeverity,
    HealthUnavailableSource,
)
from app.resolution import custom_rules
from app.routes.issues import list_issues
from app.routes.iris import get_audit_enabled

router = APIRouter(prefix="/api/iris", tags=["health-center"])

_PENALTIES: dict[HealthSeverity, int] = {
    "critical": 40,
    "high": 25,
    "medium": 10,
    "low": 5,
}
_CATEGORIES: tuple[tuple[HealthCategoryId, str, tuple[str, ...]], ...] = (
    ("performance", "Performance", ()),
    ("tasks", "Tasks", ("task_manager_not_running",)),
    ("databases", "Databases", ("database_dismounted", "database_full")),
    ("security", "Security", ("audit_status",)),
    ("web-applications", "Web Applications", ("web_app_namespace_missing",)),
    ("system", "System", ("journal_purge_archived_off", "system_monitor_not_running")),
)
_SOURCES = {
    "database_dismounted": "GET /v2/databases and GET /v2/database-dirs",
    "database_full": "GET /v2/database-dirs and POST /v2/database-dir/info",
    "task_manager_not_running": "GET /v2/task/manager",
    "web_app_namespace_missing": "GET /v2/web-apps and GET /v2/namespaces",
    "journal_purge_archived_off": "GET /v2/journal/settings",
    "system_monitor_not_running": "GET /v2/monitor/dashboard/main and GET /v2/processes",
    "audit_status": "GET /v2/security/audit/enabled",
}
_CUSTOM_CATEGORIES: dict[str, HealthCategoryId] = {
    "cache_efficiency": "performance",
    "global_refs_per_second": "performance",
    "license_use_percent": "system",
    "processes": "system",
    "csp_sessions": "system",
    "serious_alerts": "system",
    "application_errors": "system",
}


def _finding(issue: Any, resolution: Any, category: HealthCategoryId) -> HealthFinding:
    evidence = []
    for item in resolution.detection_evidence:
        if issue.kind == "database_full":
            if item.field == "Full" and "iris_reports_full" not in issue.reasons:
                continue
            if item.field == "Size, MaxSize" and "max_size_reached" not in issue.reasons:
                continue

        if item.field == "Size, MaxSize":
            value = {"Size": issue.size, "MaxSize": issue.max_size}
        else:
            value = getattr(issue, item.issue_field, None) if item.issue_field else None
        if value is None or value == "":
            value_status: Literal["observed", "unknown", "not_applicable"] = "unknown"
        elif isinstance(value, str) and value.strip().lower() == "unlimited":
            value_status = "not_applicable"
        else:
            value_status = "observed"
        evidence.append(
            HealthEvidence(
                source=item.source,
                field=item.field,
                observed_value=value,
                value_status=value_status,
                condition=item.condition,
            )
        )

    investigation = resolution.investigation
    identifier = issue.kind
    if issue.kind == "database_dismounted":
        identifier = f"{identifier}:{issue.database}"
    elif issue.kind == "database_full":
        identifier = f"{identifier}:{issue.database or issue.directory}"

    return HealthFinding(
        id=identifier,
        check_id=issue.kind,
        category=category,
        severity=resolution.severity.value,
        title=resolution.title,
        explanation=issue.explanation,
        evidence=evidence,
        recommendation=resolution.recommended_solution,
        investigation=(
            HealthInvestigationDestination(
                page=investigation.page,
                description=investigation.description,
            )
            if investigation
            else None
        ),
    )


@router.get("/health", response_model=HealthReport)
async def get_health_report(
    client: IRISClient = Depends(get_iris_client),
) -> HealthReport:
    rules = custom_rules.list_rules()
    check_categories = {
        check: category
        for category, _, checks in _CATEGORIES
        for check in checks
    }
    for rule in rules:
        check_categories[rule.issue_type] = _CUSTOM_CATEGORIES[rule.signal]

    unavailable: list[HealthUnavailableSource] = []
    findings: list[HealthFinding] = []
    try:
        issues = await list_issues(client)
    except (HTTPException, ValidationError):
        issues = None
        for check, category in check_categories.items():
            if check == "audit_status":
                continue
            unavailable.append(
                HealthUnavailableSource(
                    category=category,
                    check_id=check,
                    source=_SOURCES.get(check, "GET /v2/monitor/dashboard/main"),
                    reason="The existing Issue Resolver checks could not be completed.",
                )
            )
    else:
        for issue in issues.issues:
            category = check_categories[issue.kind]
            findings.append(_finding(issue, issues.resolutions[issue.kind], category))
        for check in issues.issue_checks_unavailable:
            category = check_categories[check]
            unavailable.append(
                HealthUnavailableSource(
                    category=category,
                    check_id=check,
                    source=_SOURCES.get(check, "GET /v2/monitor/dashboard/main"),
                    reason="IRIS data for this check could not be read or evaluated.",
                )
            )

    try:
        audit_enabled = (await get_audit_enabled(client)).result.Enabled
    except (HTTPException, ValidationError):
        audit_enabled = None
        unavailable.append(
            HealthUnavailableSource(
                category="security",
                check_id="audit_status",
                source=_SOURCES["audit_status"],
                reason="IRIS audit status could not be read.",
            )
        )

    if audit_enabled is not None:
        security_evidence = [
            HealthEvidence(
                source=_SOURCES["audit_status"],
                field="Enabled",
                observed_value=audit_enabled,
                value_status="observed",
                condition="IRIS-reported audit status; no security baseline is configured for scoring.",
            )
        ]
    else:
        security_evidence = []

    recommendations = [
        HealthRecommendation(
            finding_id=item.id,
            category=item.category,
            text=item.recommendation,
            investigation=item.investigation,
        )
        for item in findings
        if item.recommendation
    ]

    categories = []
    for category_id, name, base_checks in _CATEGORIES:
        checks = list(base_checks)
        checks.extend(
            rule.issue_type for rule in rules
            if _CUSTOM_CATEGORIES[rule.signal] == category_id
        )
        missing = [item for item in unavailable if item.category == category_id]
        category_findings = [item for item in findings if item.category == category_id]
        completed = len(checks) - len(missing)
        can_score = category_id != "security" and bool(checks) and not missing
        score = max(
            0,
            100 - sum(_PENALTIES[item.severity] for item in category_findings),
        ) if can_score else None

        if score is None:
            status = "partial" if completed else "unavailable" if missing else "not_assessed"
        elif any(item.severity == "critical" for item in category_findings):
            status = "critical"
        else:
            status = "warning" if category_findings else "healthy"

        category_evidence = security_evidence if category_id == "security" else []
        category_evidence += [
            evidence
            for item in category_findings
            for evidence in item.evidence
        ]
        reported = {item.check_id for item in category_findings}
        category_evidence += [
            HealthEvidence(
                source="Existing Issue Resolver detection",
                field=check,
                observed_value="not reported",
                value_status="observed",
                condition="The check completed and did not report this issue.",
            )
            for check in checks
            if check not in reported and check not in {item.check_id for item in missing}
        ]

        categories.append(
            HealthCategoryResult(
                id=category_id,
                name=name,
                status=status,
                score=score,
                checks_completed=completed,
                checks_total=len(checks),
                evidence=category_evidence,
                findings=category_findings,
                unavailable_sources=missing,
            )
        )

    scores = [item.score for item in categories if item.score is not None]
    overall_score = int(sum(scores) / len(scores) + 0.5) if scores else None
    if any(item.score is None for item in categories):
        status = "partial"
    elif any(item.severity == "critical" for item in findings):
        status = "critical"
    else:
        status = "warning" if findings else "healthy"

    return HealthReport(
        generated_at=datetime.now(timezone.utc),
        status=status,
        overall_score=overall_score,
        score_method=(
            "Fully assessed category scores start at 100 and subtract finding "
            "penalties (minimum 0). Overall score is the rounded mean of scored "
            "categories; unassessed categories are excluded."
        ),
        penalty_weights=_PENALTIES,
        categories=categories,
        findings=findings,
        recommendations=recommendations,
        unavailable_sources=unavailable,
    )
