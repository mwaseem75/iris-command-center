"""Deterministic, explainable relationships between detected issues."""

from enum import Enum
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from app.resolution.identity import IssueResourceReference
from app.resolution.models import IssueResolution


class IssueCorrelationKind(str, Enum):
    SHARED_RESOURCE = "shared_resource"
    SHARED_OBSERVATION = "shared_observation"
    OPERATIONAL_DEPENDENCY = "operational_dependency"


class IssueCorrelation(BaseModel):
    """A symmetric link between two distinct detected issue identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issue_id_a: str
    issue_id_b: str
    kind: IssueCorrelationKind
    reason: str
    shared_resource: IssueResourceReference | None = None


class _CorrelatableIssue(Protocol):
    issue_id: str
    kind: str
    resource: IssueResourceReference


_MONITOR_DASHBOARD_SOURCE = "GET /v2/monitor/dashboard/main"


def correlate_issues(
    issues: Sequence[_CorrelatableIssue],
    resolutions: dict[str, IssueResolution],
) -> list[IssueCorrelation]:
    """Return stable pairwise links supported by shared structured facts."""
    correlations: list[IssueCorrelation] = []

    for index, left in enumerate(issues):
        for right in issues[index + 1:]:
            if left.issue_id == right.issue_id:
                continue

            ordered_ids = sorted((left.issue_id, right.issue_id))
            shared_resource = None
            if (
                left.resource.type == right.resource.type
                and left.resource.canonical_key == right.resource.canonical_key
            ):
                shared_resource = min(
                    (left.resource, right.resource),
                    key=lambda resource: resource.display_name,
                )
                correlations.append(
                    IssueCorrelation(
                        issue_id_a=ordered_ids[0],
                        issue_id_b=ordered_ids[1],
                        kind=IssueCorrelationKind.SHARED_RESOURCE,
                        reason="Both findings identify the same canonical resource.",
                        shared_resource=shared_resource,
                    )
                )
                continue

            pair = {left.kind, right.kind}
            if "task_manager_not_running" in pair and "journal_purge_archived_off" in pair:
                correlations.append(
                    IssueCorrelation(
                        issue_id_a=ordered_ids[0],
                        issue_id_b=ordered_ids[1],
                        kind=IssueCorrelationKind.OPERATIONAL_DEPENDENCY,
                        reason=(
                            "The stopped Task Manager prevents scheduled tasks, including journal "
                            "maintenance, from running; the journal finding separately reports "
                            "PurgeArchived is off. This relationship does not assert causation."
                        ),
                    )
                )
                continue

            system_monitor = left if left.kind == "system_monitor_not_running" else right
            custom_issue = left if left.kind.startswith("custom:") else right
            if (
                system_monitor.kind == "system_monitor_not_running"
                and custom_issue.kind.startswith("custom:")
            ):
                resolution = resolutions.get(custom_issue.kind)
                if resolution and any(
                    evidence.source == _MONITOR_DASHBOARD_SOURCE
                    for evidence in resolution.detection_evidence
                ):
                    correlations.append(
                        IssueCorrelation(
                            issue_id_a=ordered_ids[0],
                            issue_id_b=ordered_ids[1],
                            kind=IssueCorrelationKind.SHARED_OBSERVATION,
                            reason=(
                                "The custom finding uses monitor-dashboard data, which may be stale "
                                "while the System Monitor is not running. This is not a causal claim."
                            ),
                        )
                    )

    return sorted(
        correlations,
        key=lambda item: (item.issue_id_a, item.issue_id_b, item.kind.value),
    )
