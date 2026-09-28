"""Resolve Issues: detects problems in live IRIS data and suggests the operation that fixes them.

This route only reports; the fix runs through the operation's own route
(with authorization, confirmation, verification and a trace).

Six issue types. Resolvable:

- database_dismounted: a configured database IRIS reports as not mounted,
  that isn't an IRIS system database or mirrored. Suggested fix:
  database.mount (read-write). It's only reported when the database list
  and the storage list agree on the directory. Each issue also lists the
  namespaces that use the database for Globals or Routines (from GET
  /v2/namespaces), or null if they couldn't be read.
- web_app_namespace_missing: an enabled web application whose namespace
  isn't in GET /v2/namespaces, so it can't serve requests. Suggested fix:
  web_app.set_enabled with Enabled false. System apps and the apps
  web_app.set_enabled refuses (/api/admin, /api/mgmnt) are never reported.
  If the web-app data can't be read, the check is listed in
  `issue_checks_unavailable` and database issues are still reported.
- journal_purge_archived_off: journal archiving is configured (ArchiveName
  is set) but PurgeArchived is off. Suggested fix:
  journal.update_purge_archived with PurgeArchived true. With no
  ArchiveName the setting has no effect, so nothing is reported. If the
  journal settings can't be read, the check is listed in
  `issue_checks_unavailable`.

Detection-only (no operation; the catalog entry names the page to look into):

- system_monitor_not_running: GET /v2/monitor/dashboard/main reports
  Status.SystemMonitor false.
- task_manager_not_running: GET /v2/task/manager reports a Status other than
  "Running".
- database_full: IRIS reports a mounted database as Full (POST
  /v2/database-dir/info, only its Full field is read), or its MaxSize is a
  number and Size has reached it (GET /v2/database-dirs). If a mounted
  database's Full flag can't be read, the check is listed in
  `issue_checks_unavailable` and anything found is still reported.

Each detection-only check that can't read its IRIS data is also listed in
`issue_checks_unavailable`.

Custom Issue Rules (app/resolution/custom_rules.py) are evaluated here too:
one GET /v2/monitor/dashboard/main read for all of them. A matching rule is
reported as issue kind "custom:<name>", and every rule's detection-only
catalog entry is added to `resolutions`. A rule whose signal has no number
right now (e.g. LicenseUse "" with no license limit), or all rules if the
dashboard can't be read, are listed in `issue_checks_unavailable`.

The response also carries the Issue Resolution Catalog entries
(`resolutions`, keyed by issue kind), so the UI can explain each issue.

`recommendations` and `recommendations_unavailable` are kept for
compatibility. Their only check (journal_purge_archived_off) is now an
issue, so both are always empty.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Discriminator, Field, Tag, ValidationError

from app.dependencies import get_iris_client
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.execution.web_app_set_enabled_handler import _PROTECTED_APPS, _normalize
from app.iris_client.client import IRISClient
from app.resolution import custom_rules
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.models import IssueResolution
from app.iris_client.exceptions import IRISClientError
from app.models.iris import DatabaseStorageEntry, JournalSettings, NamespaceEntry, WebAppEntry
from app.routes.iris import (
    get_database_storage,
    get_databases,
    get_journal_settings,
    get_monitor_dashboard,
    get_namespaces,
    get_task_manager,
    get_web_apps,
)

router = APIRouter(prefix="/api/iris", tags=["issues"])

MOUNT_OPERATION = "database.mount"
PURGE_ARCHIVED_OPERATION = "journal.update_purge_archived"
WEB_APP_SET_ENABLED_OPERATION = "web_app.set_enabled"

# Namespace fields whose database the namespace can't work without.
_NAMESPACE_DB_ROLES = ("Globals", "Routines")


class AffectedNamespace(BaseModel):
    namespace: str
    uses: list[str]  # "Globals" and/or "Routines"


class DatabaseMountIssue(BaseModel):
    kind: Literal["database_dismounted"] = "database_dismounted"
    database: str
    directory: str
    status: str
    mount_required: bool
    mount_at_startup: bool
    mirrored: bool
    affected_namespaces: list[AffectedNamespace] | None  # None if namespaces couldn't be read
    explanation: str
    recommended_operation: str = MOUNT_OPERATION
    parameters: dict[str, str | bool]


class RecommendationEvidence(BaseModel):
    source: str  # e.g. "GET /v2/journal/settings"
    field: str
    value: str | bool


class Recommendation(BaseModel):
    kind: str
    title: str
    severity: str  # "low" or "medium", as in the catalog's IssueSeverity
    target: str
    evidence: list[RecommendationEvidence]
    explanation: str
    recommended_operation: str
    parameters: dict[str, str | bool]


class WebAppNamespaceIssue(BaseModel):
    kind: Literal["web_app_namespace_missing"] = "web_app_namespace_missing"
    web_app: str
    namespace: str
    enabled: bool
    app_type: str
    explanation: str
    recommended_operation: str = WEB_APP_SET_ENABLED_OPERATION
    parameters: dict[str, str | bool]


class JournalPurgeArchivedIssue(BaseModel):
    kind: Literal["journal_purge_archived_off"] = "journal_purge_archived_off"
    archive_name: str
    purge_archived: bool
    explanation: str
    recommended_operation: str = PURGE_ARCHIVED_OPERATION
    parameters: dict[str, str | bool]


# Detection-only issues: no recommended operation or parameters.


class SystemMonitorIssue(BaseModel):
    kind: Literal["system_monitor_not_running"] = "system_monitor_not_running"
    system_monitor: bool
    up_time: str
    explanation: str


class TaskManagerIssue(BaseModel):
    kind: Literal["task_manager_not_running"] = "task_manager_not_running"
    status: str
    explanation: str


class DatabaseFullIssue(BaseModel):
    kind: Literal["database_full"] = "database_full"
    database: str | None  # None if the database list doesn't name this directory
    directory: str
    size: int  # MB
    max_size: int | str  # MB, or "Unlimited"
    full: bool | None  # IRIS's Full flag; None if it couldn't be read
    reasons: list[Literal["iris_reports_full", "max_size_reached"]]
    explanation: str


class CustomRuleIssue(BaseModel):
    """A Custom Issue Rule whose condition holds (detection-only)."""

    kind: str = Field(pattern=r"^custom:[a-z][a-z0-9_]{2,39}$")  # "custom:<rule name>"
    rule: str
    title: str
    signal: str
    signal_label: str
    operator: str
    threshold: float
    value: float  # the live value that matched
    explanation: str


def _issue_tag(issue: object) -> str | None:
    kind = issue.get("kind") if isinstance(issue, dict) else getattr(issue, "kind", None)
    return "custom" if isinstance(kind, str) and kind.startswith(custom_rules.CUSTOM_PREFIX) else kind


Issue = Annotated[
    Annotated[DatabaseMountIssue, Tag("database_dismounted")]
    | Annotated[WebAppNamespaceIssue, Tag("web_app_namespace_missing")]
    | Annotated[JournalPurgeArchivedIssue, Tag("journal_purge_archived_off")]
    | Annotated[SystemMonitorIssue, Tag("system_monitor_not_running")]
    | Annotated[TaskManagerIssue, Tag("task_manager_not_running")]
    | Annotated[DatabaseFullIssue, Tag("database_full")]
    | Annotated[CustomRuleIssue, Tag("custom")],
    Discriminator(_issue_tag),
]


class IssuesResponse(BaseModel):
    issues: list[Issue]
    resolutions: dict[str, IssueResolution]
    issue_checks_unavailable: list[str] = []  # issue checks whose IRIS data couldn't be read
    # Kept for compatibility; always empty now (see the module docstring).
    recommendations: list[Recommendation] = []
    recommendations_unavailable: list[str] = []


def _dir_key(directory: str) -> str:
    return directory.rstrip("/\\")


def _affected_namespaces(name: str, namespaces: list[NamespaceEntry] | None) -> list[AffectedNamespace] | None:
    if namespaces is None:
        return None
    affected = []
    for ns in namespaces:
        uses = [role for role in _NAMESPACE_DB_ROLES if getattr(ns, role).upper() == name.upper()]
        if uses:
            affected.append(AffectedNamespace(namespace=ns.Name, uses=uses))
    return affected


def _describe_namespaces(affected: list[AffectedNamespace] | None) -> str:
    if affected is None:
        return " Which namespaces use it couldn't be read."
    if not affected:
        return " No namespace uses it for Globals or Routines."
    listed = ", ".join(f"{a.namespace} ({', '.join(a.uses)})" for a in affected)
    return f" Namespaces that depend on it: {listed}."


def _explain(
    name: str, directory: str, status: str, mount_at_startup: bool, affected: list[AffectedNamespace] | None
) -> str:
    return (
        f"Database {name} ({directory}) is reported by IRIS as \"{status}\", so its data is not "
        f"available to IRIS. It is not a system or mirrored database"
        + (", and IRIS is configured to mount it at startup." if mount_at_startup else ".")
        + _describe_namespaces(affected)
        + " Recommended fix: mount it read-write with the database.mount operation."
    )


async def _read_namespaces(client: IRISClient) -> list[NamespaceEntry] | None:
    """The namespace list, or None if it can't be read (the issue is still reported)."""
    try:
        return (await get_namespaces(client)).result
    except (HTTPException, ValidationError):
        return None


async def get_issues(client: IRISClient) -> IssuesResponse:
    """The detected issues and the catalog, without recommendations. The
    Issue Resolution Rehearsal uses this directly."""
    databases = (await get_databases(client)).result
    storage = {_dir_key(entry.Directory): entry for entry in (await get_database_storage(client)).result}

    issues: list[DatabaseMountIssue] = []
    namespaces: list[NamespaceEntry] | None = None
    namespaces_read = False
    for db in databases:
        dir_entry = storage.get(_dir_key(db.Directory))
        if dir_entry is None or dir_entry.Status.lower().startswith("mounted"):
            continue
        if db.Name.upper() in _SYSTEM_DATABASES or dir_entry.Mirrored:
            continue
        if not namespaces_read:  # only read namespaces when there's an issue
            namespaces, namespaces_read = await _read_namespaces(client), True
        affected = _affected_namespaces(db.Name, namespaces)
        issues.append(
            DatabaseMountIssue(
                database=db.Name,
                directory=dir_entry.Directory,
                status=dir_entry.Status,
                mount_required=db.MountRequired,
                mount_at_startup=db.MountAtStartup,
                mirrored=dir_entry.Mirrored,
                affected_namespaces=affected,
                explanation=_explain(db.Name, dir_entry.Directory, dir_entry.Status, db.MountAtStartup, affected),
                parameters={"Directory": dir_entry.Directory, "ReadOnly": False},
            )
        )
    return IssuesResponse(issues=issues, resolutions=ISSUE_CATALOG)


# --- journal_purge_archived_off ---


def _journal_issues(settings: JournalSettings) -> list[JournalPurgeArchivedIssue]:
    archive = settings.ArchiveName.strip()
    if not archive or settings.PurgeArchived:
        return []
    return [
        JournalPurgeArchivedIssue(
            archive_name=archive,
            purge_archived=settings.PurgeArchived,
            explanation=(
                f"Journal archiving is configured (ArchiveName \"{archive}\"), but PurgeArchived is off, so "
                "IRIS keeps journal files in the journal directory after they are archived. "
                "Recommended fix: turn PurgeArchived on with the journal.update_purge_archived operation."
            ),
            parameters={"PurgeArchived": True},
        )
    ]


async def find_journal_issues(client: IRISClient) -> list[JournalPurgeArchivedIssue] | None:
    """journal_purge_archived_off issues, or None if the settings couldn't be read. Read-only."""
    try:
        settings = (await get_journal_settings(client)).result
    except (HTTPException, ValidationError):
        return None
    return _journal_issues(settings)


# --- web_app_namespace_missing ---


def _web_app_candidates(apps: list[WebAppEntry]) -> list[WebAppEntry]:
    """Enabled apps web_app.set_enabled could disable (never System or protected apps)."""
    return [
        app for app in apps
        if app.Enabled and app.Namespace
        and not app.IsSystemApp and "system" not in app.Type.lower()
        and _normalize(app.Name) not in _PROTECTED_APPS
    ]


def _web_app_namespace_issues(apps: list[WebAppEntry], namespaces: list[NamespaceEntry]) -> list[WebAppNamespaceIssue]:
    existing = {ns.Name.upper() for ns in namespaces}
    return [
        WebAppNamespaceIssue(
            web_app=app.Name,
            namespace=app.Namespace,
            enabled=app.Enabled,
            app_type=app.Type,
            explanation=(
                f"Web application {app.Name} is enabled but its namespace {app.Namespace} does not exist, "
                "so it can't serve requests. Recommended fix: disable it with the web_app.set_enabled "
                "operation until the namespace exists or the application is reconfigured."
            ),
            parameters={"Name": app.Name, "Enabled": False},
        )
        for app in apps
        if app.Namespace.upper() not in existing
    ]


async def find_web_app_issues(client: IRISClient) -> list[WebAppNamespaceIssue] | None:
    """web_app_namespace_missing issues, or None if the data couldn't be read. Read-only."""
    try:
        apps = _web_app_candidates((await get_web_apps(client)).result)
        # Only read namespaces when there's an app to check.
        namespaces = (await get_namespaces(client)).result if apps else []
    except (HTTPException, ValidationError):
        return None
    return _web_app_namespace_issues(apps, namespaces)


# --- detection-only: system_monitor_not_running, task_manager_not_running, database_full ---


async def find_system_monitor_issues(client: IRISClient) -> list[SystemMonitorIssue] | None:
    """system_monitor_not_running, or None if the dashboard couldn't be read. Read-only."""
    try:
        status = (await get_monitor_dashboard(client)).result.Status
    except (HTTPException, ValidationError):
        return None
    if status.SystemMonitor:
        return []
    return [
        SystemMonitorIssue(
            system_monitor=status.SystemMonitor,
            up_time=status.UpTime,
            explanation=(
                "IRIS reports that its System Monitor is not running (Status.SystemMonitor is false), so the "
                "health indicators and alert counts IRIS reports are not being updated and may be out of date."
            ),
        )
    ]


async def find_task_manager_issues(client: IRISClient) -> list[TaskManagerIssue] | None:
    """task_manager_not_running, or None if the status couldn't be read. Read-only."""
    try:
        status = (await get_task_manager(client)).result.Status
    except (HTTPException, ValidationError):
        return None
    if status == "Running":
        return []
    return [
        TaskManagerIssue(
            status=status,
            explanation=(
                f"IRIS reports the Task Manager status as \"{status}\", not \"Running\", so no scheduled task "
                "runs, including IRIS's own maintenance tasks."
            ),
        )
    ]


async def _read_full_flag(client: IRISClient, directory: str) -> bool | None:
    """IRIS's Full flag for one database (POST /v2/database-dir/info, an async
    task), or None if it couldn't be read. Only Full is read, so other fields
    IRIS sends in an unexpected shape don't matter here."""
    try:
        task = await client.wait_for_async_task(
            await client.post_async_task("/v2/database-dir/info", params={"dir": directory})
        )
    except IRISClientError:
        return None
    result = task.get("Result") if isinstance(task, dict) else None
    full = result.get("Full") if isinstance(result, dict) else None
    return full if isinstance(full, bool) else None


def _max_size_reached(entry: DatabaseStorageEntry) -> bool:
    return isinstance(entry.MaxSize, int) and entry.MaxSize > 0 and entry.Size >= entry.MaxSize


def _explain_full(name: str, entry: DatabaseStorageEntry, reasons: list[str]) -> str:
    parts = []
    if "iris_reports_full" in reasons:
        parts.append("IRIS reports it as Full")
    if "max_size_reached" in reasons:
        parts.append(f"its size ({entry.Size} MB) has reached its maximum size ({entry.MaxSize} MB)")
    return (
        f"Database {name} ({entry.Directory}) can't grow: {' and '.join(parts)}. "
        "Writes that need new space in it will fail."
    )


async def find_database_full_issues(client: IRISClient) -> tuple[list[DatabaseFullIssue] | None, bool]:
    """(database_full issues or None if storage couldn't be read, whether every
    mounted database's Full flag was read). Read-only."""
    try:
        storage = (await get_database_storage(client)).result
    except (HTTPException, ValidationError):
        return None, False
    mounted = [entry for entry in storage if entry.Status.lower().startswith("mounted")]
    flags = dict(zip(
        (entry.Directory for entry in mounted),
        await asyncio.gather(*(_read_full_flag(client, entry.Directory) for entry in mounted)),
    ))
    complete = all(flag is not None for flag in flags.values())

    found: list[tuple[DatabaseStorageEntry, list[str]]] = []
    for entry in storage:
        reasons = []
        if flags.get(entry.Directory) is True:
            reasons.append("iris_reports_full")
        if _max_size_reached(entry):
            reasons.append("max_size_reached")
        if reasons:
            found.append((entry, reasons))
    if not found:
        return [], complete

    # Name the databases (only read when something was found).
    try:
        names = {_dir_key(db.Directory): db.Name for db in (await get_databases(client)).result}
    except (HTTPException, ValidationError):
        names = {}
    issues = []
    for entry, reasons in found:
        name = names.get(_dir_key(entry.Directory))
        issues.append(
            DatabaseFullIssue(
                database=name,
                directory=entry.Directory,
                size=entry.Size,
                max_size=entry.MaxSize,
                full=flags.get(entry.Directory),
                reasons=reasons,
                explanation=_explain_full(name or entry.Directory, entry, reasons),
            )
        )
    return issues, complete


# --- Custom Issue Rules ---


async def evaluate_custom_rules(client: IRISClient) -> tuple[list[CustomRuleIssue], list[str]]:
    """(issues for rules whose condition holds, rule kinds that couldn't be
    evaluated). One dashboard read for every rule; nothing if there are none."""
    rules = custom_rules.list_rules()
    if not rules:
        return [], []
    try:
        dashboard = (await get_monitor_dashboard(client)).result
    except (HTTPException, ValidationError):
        return [], [rule.issue_type for rule in rules]
    stale = "" if dashboard.Status.SystemMonitor else (
        " IRIS's System Monitor is not running, so this value may be out of date."
    )
    issues: list[CustomRuleIssue] = []
    unavailable: list[str] = []
    for rule in rules:
        matched, value = rule.evaluate(dashboard)
        if matched is None:
            unavailable.append(rule.issue_type)
        elif matched:
            signal = custom_rules.SIGNALS[rule.signal]
            issues.append(
                CustomRuleIssue(
                    kind=rule.issue_type,
                    rule=rule.name,
                    title=rule.title,
                    signal=rule.signal,
                    signal_label=signal.label,
                    operator=rule.operator,
                    threshold=rule.value,
                    value=value,
                    explanation=(
                        f"{signal.label} is {value:g}{signal.unit and ' ' + signal.unit}, and the custom rule "
                        f"reports it while {rule.condition_text()}.{stale} {rule.guidance}"
                    ),
                )
            )
    return issues, unavailable


@router.get("/issues", response_model=IssuesResponse)
async def list_issues(client: IRISClient = Depends(get_iris_client)) -> IssuesResponse:
    # Database issues first (the part the Issue Resolution Rehearsal also
    # uses), then the web-app and journal checks.
    response = await get_issues(client)
    for kind, found in (
        ("web_app_namespace_missing", await find_web_app_issues(client)),
        ("journal_purge_archived_off", await find_journal_issues(client)),
        ("system_monitor_not_running", await find_system_monitor_issues(client)),
        ("task_manager_not_running", await find_task_manager_issues(client)),
    ):
        if found is None:
            response.issue_checks_unavailable.append(kind)
        else:
            response.issues += found
    full, complete = await find_database_full_issues(client)
    response.issues += full or []
    if not complete:
        response.issue_checks_unavailable.append("database_full")
    custom, custom_unavailable = await evaluate_custom_rules(client)
    response.issues += custom
    response.issue_checks_unavailable += custom_unavailable
    response.resolutions = {
        **response.resolutions,
        **{rule.issue_type: rule.to_catalog_entry() for rule in custom_rules.list_rules()},
    }
    return response
