"""The Issue Resolution Catalog: one entry per issue type the Command Center
can detect and resolve.

For now there is one: a dismounted database, resolved with database.mount.
The detection itself lives in app/routes/issues.py and the fix in the
database.mount handler; this entry describes both so they can be explained
and checked in one place.
"""

from typing import Any

from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.observability.models import ResolutionContext
from app.resolution.models import (
    DetectionEvidence,
    IssueResolution,
    IssueSeverity,
    ParameterBinding,
    VerificationRule,
    WorkflowStep,
    WorkflowStepKind,
)

DATABASE_DISMOUNTED = IssueResolution(
    issue_type="database_dismounted",
    title="Dismounted database",
    severity=IssueSeverity.HIGH,
    detection_evidence=(
        DetectionEvidence(
            source="GET /v2/databases",
            field="Directory",
            condition="The database is configured on the instance.",
            issue_field="directory",
        ),
        DetectionEvidence(
            source="GET /v2/database-dirs",
            field="Status",
            condition="The status for the same directory doesn't start with \"Mounted\".",
            issue_field="status",
        ),
        DetectionEvidence(
            source="GET /v2/database-dirs",
            field="Mirrored",
            condition="The database is not mirrored.",
            issue_field="mirrored",
        ),
        DetectionEvidence(
            source="GET /v2/databases",
            field="Name",
            condition="The database is not one of IRIS's own system databases.",
            issue_field="database",
        ),
    ),
    explanation=(
        "IRIS reports the database as not mounted, so its data isn't available to IRIS or to "
        "the applications that use it."
    ),
    recommended_solution="Mount the database read-write with database.mount.",
    operation="database.mount",
    parameters=(
        ParameterBinding(name="Directory", from_issue_field="directory"),
        ParameterBinding(name="ReadOnly", value=False),
    ),
    prerequisites=(
        "The caller holds one of the operation's required privileges.",
        "IRIS still reports the database as dismounted when the dry run runs.",
        "The directory is still a configured database.",
    ),
    workflow_steps=(
        WorkflowStep(
            kind=WorkflowStepKind.DETECTED,
            title="Detected issue",
            description="GET /api/iris/issues reports the database as dismounted.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.RECOMMENDED,
            title="Recommended fix",
            description="database.mount, read-write, with the detected directory.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.DRY_RUN,
            title="Dry-run check",
            description="database.mount dry run: checks the mount state with IRIS and sends nothing.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.CONFIRMATION,
            title="Confirmation",
            description="The user explicitly confirms the previewed request.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.EXECUTION,
            title="Execution",
            description="The executor authorizes the request and the handler sends the mount to IRIS.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.VERIFICATION,
            title="Verification",
            description="The handler re-reads the database state and checks it's mounted.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.TRACE,
            title="Trace",
            description="The attempt is recorded as an execution trace in Observability.",
        ),
    ),
    verification_rules=(
        VerificationRule(
            source="POST /v2/database-dir/info",
            condition="Mounted is true for the directory.",
            checked_by="operation",
        ),
        VerificationRule(
            source="GET /api/iris/issues",
            condition="The database is no longer reported as dismounted.",
            checked_by="issue_detection",
        ),
    ),
    safety_restrictions=(
        "Never used for IRIS's own system databases.",
        "Never used for mirrored databases.",
        "Always preceded by a dry run; nothing is sent to IRIS before the user confirms.",
        "The recommended fix mounts read-write; the Cluster option is never sent.",
        "Goes through the normal authorization, confirmation and verification; there's no bypass.",
    ),
    excluded_databases=_SYSTEM_DATABASES,
)

ISSUE_CATALOG: dict[str, IssueResolution] = {
    entry.issue_type: entry for entry in (DATABASE_DISMOUNTED,)
}


def get_issue_resolution(issue_type: str) -> IssueResolution | None:
    """The catalog entry for `issue_type`, or None if there isn't one."""
    return ISSUE_CATALOG.get(issue_type)


def resolves_with(issue_type: str, operation_name: str) -> bool:
    """True if `issue_type` is in the catalog and is resolved by `operation_name`."""
    entry = ISSUE_CATALOG.get(issue_type)
    return entry is not None and entry.operation == operation_name


def trace_context(
    issue_type: str | None, operation_name: str, parameters: dict[str, Any]
) -> ResolutionContext | None:
    """The resolution context to record on a trace, or None when the request
    isn't part of a known resolution for this operation."""
    if not issue_type or not resolves_with(issue_type, operation_name):
        return None
    entry = ISSUE_CATALOG[issue_type]
    # The resource is the parameter filled in from the detected issue.
    resource_param = next((b.name for b in entry.parameters if b.from_issue_field), None)
    resource = parameters.get(resource_param) if resource_param else None
    return ResolutionContext(
        issue_type=entry.issue_type,
        issue_title=entry.title,
        severity=entry.severity.value,
        resource=None if resource is None else str(resource),
    )
