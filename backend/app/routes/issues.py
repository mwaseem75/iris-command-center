"""Resolve Issues: detects problems in live IRIS data and suggests the operation that fixes them.

This route only reports; the fix runs through the operation's own route
(with authorization, confirmation, verification and a trace).

Two issue types:

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

The response also carries the Issue Resolution Catalog entries
(`resolutions`, keyed by issue kind), so the UI can explain each issue.

Recommendations (`recommendations`) are separate from issues: conditions
read from live IRIS state where an existing registered operation is the
suggested change. They are only reported, never run; each one goes through
its operation's own authorization, confirmation and verification.

- journal_purge_archived_off: journal archiving is configured (ArchiveName
  is set) but PurgeArchived is off. Suggested: journal.update_purge_archived
  with PurgeArchived true. With no ArchiveName the setting has no effect,
  so nothing is recommended.

A recommendation check whose IRIS data couldn't be read is listed in
`recommendations_unavailable` instead; issues are still reported.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.dependencies import get_iris_client
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.execution.web_app_set_enabled_handler import _PROTECTED_APPS, _normalize
from app.iris_client.client import IRISClient
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.models import IssueResolution
from app.models.iris import JournalSettings, NamespaceEntry, WebAppEntry
from app.routes.iris import (
    get_database_storage,
    get_databases,
    get_journal_settings,
    get_namespaces,
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


Issue = Annotated[DatabaseMountIssue | WebAppNamespaceIssue, Field(discriminator="kind")]


class IssuesResponse(BaseModel):
    issues: list[Issue]
    resolutions: dict[str, IssueResolution]
    issue_checks_unavailable: list[str] = []  # issue checks whose IRIS data couldn't be read
    recommendations: list[Recommendation] = []
    recommendations_unavailable: list[str] = []  # recommendation checks whose IRIS data couldn't be read


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


# --- Recommendations ---


def _journal_recommendations(settings: JournalSettings) -> list[Recommendation]:
    archive = settings.ArchiveName.strip()
    if not archive or settings.PurgeArchived:
        return []
    return [
        Recommendation(
            kind="journal_purge_archived_off",
            title="Archived journal files are not purged",
            severity="low",
            target="Journal settings",
            evidence=[
                RecommendationEvidence(source="GET /v2/journal/settings", field="ArchiveName", value=archive),
                RecommendationEvidence(source="GET /v2/journal/settings", field="PurgeArchived", value=False),
            ],
            explanation=(
                f"Journal archiving is configured (ArchiveName \"{archive}\"), but PurgeArchived is off, so "
                "IRIS keeps journal files in the journal directory after they are archived. "
                "Recommended: turn PurgeArchived on with the journal.update_purge_archived operation."
            ),
            recommended_operation=PURGE_ARCHIVED_OPERATION,
            parameters={"PurgeArchived": True},
        )
    ]


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


async def find_recommendations(client: IRISClient) -> tuple[list[Recommendation], list[str]]:
    """(recommendations, checks whose data couldn't be read). Read-only."""
    recommendations: list[Recommendation] = []
    unavailable: list[str] = []

    try:
        settings = (await get_journal_settings(client)).result
    except (HTTPException, ValidationError):
        unavailable.append("journal_purge_archived_off")
    else:
        recommendations += _journal_recommendations(settings)

    return recommendations, unavailable


@router.get("/issues", response_model=IssuesResponse)
async def list_issues(client: IRISClient = Depends(get_iris_client)) -> IssuesResponse:
    # Database issues first (the part the Issue Resolution Rehearsal also
    # uses), then the web-app check, then recommendations.
    response = await get_issues(client)
    web_app_issues = await find_web_app_issues(client)
    if web_app_issues is None:
        response.issue_checks_unavailable = ["web_app_namespace_missing"]
    else:
        response.issues += web_app_issues
    response.recommendations, response.recommendations_unavailable = await find_recommendations(client)
    return response
