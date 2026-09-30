"""Read-only issue resolution history projected from execution traces."""

from datetime import datetime
from typing import Sequence

from pydantic import BaseModel

from app.observability.models import ExecutionTrace
from app.resolution.identity import IssueResourceReference, issue_identity
from app.execution.models import ResolutionAction, ResolutionBefore


class ResolutionHistoryResult(BaseModel):
    operation_status: str | None
    execution_status: str | None


class ResolutionHistoryVerification(BaseModel):
    status: str | None


class IssueResolutionHistoryEntry(BaseModel):
    issue_id: str
    trace_id: str
    resource: IssueResourceReference | None
    operation_name: str
    timestamp: datetime
    before: ResolutionBefore | None
    action: ResolutionAction | None
    result: ResolutionHistoryResult
    after: dict[str, bool | str | None] | None
    verification: ResolutionHistoryVerification


class IssueResolutionHistoryResponse(BaseModel):
    issue_id: str
    history: list[IssueResolutionHistoryEntry]


def _legacy_resolution_identity(
    issue_type: str, resource: str | None
) -> tuple[str | None, IssueResourceReference | None]:
    """Recover identity for persisted traces written before issue_id was added."""
    if issue_type == "database_dismounted" and resource:
        resource_type = "database"
        canonical_key = resource.rstrip("/\\")
        display_name = resource
    elif issue_type == "web_app_namespace_missing" and resource:
        resource_type = "web-app"
        canonical_key = resource
        display_name = resource
    elif issue_type == "journal_purge_archived_off":
        resource_type = "journal-settings"
        canonical_key = "journal-settings"
        display_name = "Journal settings"
    else:
        return None, None

    identity = issue_identity(issue_type, resource_type, canonical_key, display_name)
    return identity["issue_id"], identity["resource"]


def history_for_issue(
    issue_id: str,
    traces: Sequence[ExecutionTrace],
) -> IssueResolutionHistoryResponse:
    """Project matching traces into a small, payload-safe history response."""
    matching: list[tuple[ExecutionTrace, str, IssueResourceReference | None]] = []
    for trace in traces:
        resolution = trace.resolution
        if resolution is None:
            continue

        trace_issue_id = resolution.issue_id
        resource = resolution.resource_reference
        if trace_issue_id is None and trace.lifecycle is not None:
            trace_issue_id = trace.lifecycle.before.issue_id
            resource = resource or trace.lifecycle.before.resource
        if trace_issue_id is None:
            trace_issue_id, legacy_resource = _legacy_resolution_identity(
                resolution.issue_type, resolution.resource
            )
            resource = resource or legacy_resource
        if trace_issue_id == issue_id:
            matching.append((trace, trace_issue_id, resource))

    matching.sort(key=lambda item: (item[0].start_time, item[0].trace_id), reverse=True)
    return IssueResolutionHistoryResponse(
        issue_id=issue_id,
        history=[
            IssueResolutionHistoryEntry(
                issue_id=matched_issue_id,
                trace_id=trace.trace_id,
                resource=resource,
                operation_name=trace.operation_name,
                timestamp=trace.start_time,
                before=trace.lifecycle.before if trace.lifecycle else None,
                action=trace.lifecycle.action if trace.lifecycle else None,
                result=ResolutionHistoryResult(
                    operation_status=trace.status,
                    execution_status=trace.execution_result,
                ),
                after=trace.lifecycle.after if trace.lifecycle else None,
                verification=ResolutionHistoryVerification(status=trace.verification_result),
            )
            for trace, matched_issue_id, resource in matching
        ],
    )
