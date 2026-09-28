"""The Issue Resolution Catalog: one entry per issue type the Command Center
can detect and resolve.

Three entries: a dismounted database, resolved with database.mount; an
enabled web application whose namespace doesn't exist, resolved by
disabling it with web_app.set_enabled; and archived journal files that are
not purged while archiving is configured, resolved by turning PurgeArchived
on with journal.update_purge_archived. Three detection-only entries (no
operation; they name the page to investigate on): the System Monitor or the
Task Manager not running, and a full database. The detection lives in
app/routes/issues.py and the fixes in the operation handlers; each entry
describes both so they can be explained and checked in one place.
"""

from typing import Any

from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.observability.models import ResolutionContext
from app.resolution.models import (
    DetectionEvidence,
    InvestigationDestination,
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
    impact_evidence=(
        DetectionEvidence(
            source="GET /v2/namespaces",
            field="Globals, Routines",
            condition=(
                "Namespaces that use this database for Globals or Routines can't reach that data or "
                "code until it's mounted again."
            ),
            issue_field="affected_namespaces",
        ),
    ),
)

WEB_APP_NAMESPACE_MISSING = IssueResolution(
    issue_type="web_app_namespace_missing",
    title="Web application with a missing namespace",
    severity=IssueSeverity.MEDIUM,
    detection_evidence=(
        DetectionEvidence(
            source="GET /v2/web-apps",
            field="Enabled",
            condition="The web application is enabled.",
            issue_field="enabled",
        ),
        DetectionEvidence(
            source="GET /v2/web-apps",
            field="Namespace",
            condition="Its namespace is not in GET /v2/namespaces.",
            issue_field="namespace",
        ),
        DetectionEvidence(
            source="GET /v2/web-apps",
            field="Type, IsSystemApp",
            condition="It is not a System web application.",
            issue_field="app_type",
        ),
        DetectionEvidence(
            source="GET /v2/web-apps",
            field="Name",
            condition="It is not /api/admin or /api/mgmnt, which the Command Center itself uses.",
            issue_field="web_app",
        ),
    ),
    explanation=(
        "IRIS runs every request for a web application in its namespace. The namespace doesn't exist, "
        "so the application is enabled but can't serve requests."
    ),
    recommended_solution=(
        "Disable the web application with web_app.set_enabled until its namespace exists or it is reconfigured."
    ),
    operation="web_app.set_enabled",
    parameters=(
        ParameterBinding(name="Name", from_issue_field="web_app"),
        ParameterBinding(name="Enabled", value=False),
    ),
    prerequisites=(
        "The caller holds one of the operation's required privileges, and the Secure privilege the handler checks.",
        "IRIS still reports the web application as enabled when the dry run runs.",
        "The web application is not a System app or one the Command Center itself uses.",
    ),
    workflow_steps=(
        WorkflowStep(
            kind=WorkflowStepKind.DETECTED,
            title="Detected issue",
            description="GET /api/iris/issues reports an enabled web application whose namespace doesn't exist.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.RECOMMENDED,
            title="Recommended fix",
            description="web_app.set_enabled with Enabled false, for the detected web application.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.DRY_RUN,
            title="Dry-run check",
            description="web_app.set_enabled dry run: checks the application with IRIS and sends nothing.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.CONFIRMATION,
            title="Confirmation",
            description="The user explicitly confirms the previewed request.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.EXECUTION,
            title="Execution",
            description="The executor authorizes the request and the handler sends only {\"Enabled\": false} to IRIS.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.VERIFICATION,
            title="Verification",
            description="The handler re-reads the web application and checks it's disabled and its Type unchanged.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.TRACE,
            title="Trace",
            description="The attempt is recorded as an execution trace in Observability.",
        ),
    ),
    verification_rules=(
        VerificationRule(
            source="GET /v2/web-app, GET /v2/web-apps",
            condition="Enabled is false for the web application.",
            checked_by="operation",
        ),
        VerificationRule(
            source="GET /api/iris/issues",
            condition="The web application is no longer reported.",
            checked_by="issue_detection",
        ),
    ),
    safety_restrictions=(
        "Never used for System web applications (IRIS's PUT would clear their System flag).",
        "Never used for /api/admin or /api/mgmnt, which the Command Center itself uses.",
        "Only the Enabled setting is sent; it can be turned back on with the same operation.",
        "Always preceded by a dry run; nothing is sent to IRIS before the user confirms.",
        "Goes through the normal authorization, confirmation and verification; there's no bypass.",
    ),
)

JOURNAL_PURGE_ARCHIVED_OFF = IssueResolution(
    issue_type="journal_purge_archived_off",
    title="Archived journal files are not purged",
    severity=IssueSeverity.LOW,
    detection_evidence=(
        DetectionEvidence(
            source="GET /v2/journal/settings",
            field="ArchiveName",
            condition="Journal archiving is configured (ArchiveName is not empty).",
            issue_field="archive_name",
        ),
        DetectionEvidence(
            source="GET /v2/journal/settings",
            field="PurgeArchived",
            condition="PurgeArchived is false.",
            issue_field="purge_archived",
        ),
    ),
    explanation=(
        "Journal archiving is configured, but IRIS keeps journal files in the journal directory after they "
        "are archived, so they use disk space there. PurgeArchived only has an effect when archiving is "
        "configured, so this is never reported without an ArchiveName."
    ),
    recommended_solution="Turn PurgeArchived on with journal.update_purge_archived.",
    operation="journal.update_purge_archived",
    parameters=(
        ParameterBinding(name="PurgeArchived", value=True),
    ),
    prerequisites=(
        "The caller holds one of the operation's required privileges.",
        "IRIS still reports PurgeArchived as false when the change is made.",
    ),
    workflow_steps=(
        WorkflowStep(
            kind=WorkflowStepKind.DETECTED,
            title="Detected issue",
            description="GET /api/iris/issues reports archiving configured with PurgeArchived off.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.RECOMMENDED,
            title="Recommended fix",
            description="journal.update_purge_archived with PurgeArchived true.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.DRY_RUN,
            title="Dry-run check",
            description="journal.update_purge_archived dry run: reads the current value and sends nothing.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.CONFIRMATION,
            title="Confirmation",
            description="The user explicitly confirms the change.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.EXECUTION,
            title="Execution",
            description="The executor authorizes the request and the handler sends only {\"PurgeArchived\": true} to IRIS.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.VERIFICATION,
            title="Verification",
            description="The handler re-reads the journal settings and checks PurgeArchived is true.",
        ),
        WorkflowStep(
            kind=WorkflowStepKind.TRACE,
            title="Trace",
            description="The attempt is recorded as an execution trace in Observability.",
        ),
    ),
    verification_rules=(
        VerificationRule(
            source="GET /v2/journal/settings",
            condition="PurgeArchived is true.",
            checked_by="operation",
        ),
        VerificationRule(
            source="GET /api/iris/issues",
            condition="The issue is no longer reported.",
            checked_by="issue_detection",
        ),
    ),
    safety_restrictions=(
        "Only PurgeArchived is sent; no other journal setting is changed.",
        "It can be turned back off with the same operation; the original value is recorded in the result.",
        "Nothing is sent to IRIS before the user confirms.",
        "Goes through the normal authorization, confirmation and verification; there's no bypass.",
    ),
)

# --- Detection-only entries: no operation resolves them; they say where to look. ---

_GONE_WHEN_NOT_REPORTED = VerificationRule(
    source="GET /api/iris/issues",
    condition="The issue is no longer reported.",
    checked_by="issue_detection",
)

SYSTEM_MONITOR_NOT_RUNNING = IssueResolution(
    issue_type="system_monitor_not_running",
    title="System Monitor not running",
    severity=IssueSeverity.MEDIUM,
    detection_evidence=(
        DetectionEvidence(
            source="GET /v2/processes",
            field="Routine",
            condition="No %SYS.Monitor.Control process is present in %SYS.",
            issue_field="system_monitor",
        ),
    ),
    explanation=(
        "IRIS's System Monitor is not running, so the health indicators IRIS reports (database space, "
        "journal space, lock table, write daemon) and its alert counts are not being updated and may be "
        "out of date."
    ),
    recommended_solution=(
        "Look into it on the System page. The Command Center has no operation for this; nothing is run from here."
    ),
    investigation=InvestigationDestination(
        page="system",
        description="Check the instance state; the Dashboard's System Health shows the indicators that depend on it.",
    ),
    verification_rules=(_GONE_WHEN_NOT_REPORTED,),
)

TASK_MANAGER_NOT_RUNNING = IssueResolution(
    issue_type="task_manager_not_running",
    title="Task Manager not running",
    severity=IssueSeverity.HIGH,
    detection_evidence=(
        DetectionEvidence(
            source="GET /v2/task/manager",
            field="Status",
            condition="The Task Manager status is not \"Running\".",
            issue_field="status",
        ),
    ),
    explanation=(
        "IRIS's Task Manager is not running, so no scheduled task runs, including IRIS's own maintenance "
        "tasks such as switching and purging journals."
    ),
    recommended_solution=(
        "Look into it on the Tasks page. The Command Center has no operation for this; nothing is run from here."
    ),
    investigation=InvestigationDestination(
        page="tasks",
        description="Check the Task Manager status and which scheduled tasks are affected.",
    ),
    verification_rules=(_GONE_WHEN_NOT_REPORTED,),
)

DATABASE_FULL = IssueResolution(
    issue_type="database_full",
    title="Database full",
    severity=IssueSeverity.HIGH,
    detection_evidence=(
        DetectionEvidence(
            source="POST /v2/database-dir/info",
            field="Full",
            condition="IRIS reports the mounted database as Full.",
            issue_field="full",
        ),
        DetectionEvidence(
            source="GET /v2/database-dirs",
            field="Size, MaxSize",
            condition="MaxSize is a number (not \"Unlimited\") and Size has reached it.",
            issue_field="size",
        ),
    ),
    explanation=(
        "The database can't grow: IRIS reports it as full, or it has reached its configured maximum size. "
        "Writes that need new space in it will fail."
    ),
    recommended_solution=(
        "Look into it on the Databases page. The Command Center has no operation for this; nothing is run from here."
    ),
    investigation=InvestigationDestination(
        page="databases",
        description="Check the database's size, maximum size and free space.",
    ),
    verification_rules=(_GONE_WHEN_NOT_REPORTED,),
)

ISSUE_CATALOG: dict[str, IssueResolution] = {
    entry.issue_type: entry
    for entry in (
        DATABASE_DISMOUNTED,
        WEB_APP_NAMESPACE_MISSING,
        JOURNAL_PURGE_ARCHIVED_OFF,
        SYSTEM_MONITOR_NOT_RUNNING,
        TASK_MANAGER_NOT_RUNNING,
        DATABASE_FULL,
    )
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
