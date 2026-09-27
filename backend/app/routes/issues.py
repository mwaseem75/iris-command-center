"""Resolve Issues: detects problems in live IRIS data and suggests the operation that fixes them.

This route only reports; the fix runs through the operation's own route
(with authorization, confirmation, verification and a trace).

Currently one issue type: database_dismounted. A configured database IRIS
reports as not mounted, that isn't an IRIS system database or mirrored.
Suggested fix: database.mount (read-write). It's only reported when the
database list and the storage list agree on the directory.

Each issue also lists the namespaces that use the database for Globals or
Routines (from GET /v2/namespaces), or null if they couldn't be read.

The response also carries the Issue Resolution Catalog entries
(`resolutions`, keyed by issue kind), so the UI can explain each issue.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from app.dependencies import get_iris_client
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.iris_client.client import IRISClient
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.models import IssueResolution
from app.models.iris import NamespaceEntry
from app.routes.iris import get_database_storage, get_databases, get_namespaces

router = APIRouter(prefix="/api/iris", tags=["issues"])

MOUNT_OPERATION = "database.mount"

# Namespace fields whose database the namespace can't work without.
_NAMESPACE_DB_ROLES = ("Globals", "Routines")


class AffectedNamespace(BaseModel):
    namespace: str
    uses: list[str]  # "Globals" and/or "Routines"


class DatabaseMountIssue(BaseModel):
    kind: str = "database_dismounted"
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


class IssuesResponse(BaseModel):
    issues: list[DatabaseMountIssue]
    resolutions: dict[str, IssueResolution]


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


@router.get("/issues", response_model=IssuesResponse)
async def get_issues(client: IRISClient = Depends(get_iris_client)) -> IssuesResponse:
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
