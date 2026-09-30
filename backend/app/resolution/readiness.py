"""Resolution readiness derived from the issue resolution catalog."""

from typing import Any, Mapping

from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.identity import ResolutionReadiness
from app.resolution.models import IssueResolution


def readiness_for_issue(
    issue_type: str,
    parameters: Mapping[str, Any],
    *,
    evidence_complete: bool = True,
    resolution: IssueResolution | None = None,
) -> ResolutionReadiness:
    """Describe whether the catalog can support checking this issue.

    This is independent of caller privileges and does not predict operation
    success. Missing or unusable operation parameters are conservative
    insufficient-evidence results.
    """
    entry = resolution or ISSUE_CATALOG.get(issue_type)
    if entry is None or not evidence_complete:
        return ResolutionReadiness.INSUFFICIENT_EVIDENCE
    if entry.operation is None:
        return ResolutionReadiness.INVESTIGATION_REQUIRED

    for binding in entry.parameters:
        if binding.from_issue_field is not None:
            value = parameters.get(binding.name)
            if value is None or (isinstance(value, str) and not value.strip()):
                return ResolutionReadiness.INSUFFICIENT_EVIDENCE
        elif binding.value is None:
            return ResolutionReadiness.INSUFFICIENT_EVIDENCE
    return ResolutionReadiness.READY_TO_CHECK
