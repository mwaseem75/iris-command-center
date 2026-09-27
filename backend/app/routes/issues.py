"""Resolve Issues: detects problems in live IRIS data and suggests the operation that fixes them.

This route only reports; the fix runs through the operation's own route
(with authorization, confirmation, verification and a trace).

Currently one issue type: database_dismounted. A configured database IRIS
reports as not mounted, that isn't an IRIS system database or mirrored.
Suggested fix: database.mount (read-write). It's only reported when the
database list and the storage list agree on the directory.

The response also carries the Issue Resolution Catalog entries
(`resolutions`, keyed by issue kind), so the UI can explain each issue.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_iris_client
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.iris_client.client import IRISClient
from app.resolution.catalog import ISSUE_CATALOG
from app.resolution.models import IssueResolution
from app.routes.iris import get_database_storage, get_databases

router = APIRouter(prefix="/api/iris", tags=["issues"])

MOUNT_OPERATION = "database.mount"


class DatabaseMountIssue(BaseModel):
    kind: str = "database_dismounted"
    database: str
    directory: str
    status: str
    mount_required: bool
    mount_at_startup: bool
    mirrored: bool
    explanation: str
    recommended_operation: str = MOUNT_OPERATION
    parameters: dict[str, str | bool]


class IssuesResponse(BaseModel):
    issues: list[DatabaseMountIssue]
    resolutions: dict[str, IssueResolution]


def _dir_key(directory: str) -> str:
    return directory.rstrip("/\\")


def _explain(name: str, directory: str, status: str, mount_at_startup: bool) -> str:
    return (
        f"Database {name} ({directory}) is reported by IRIS as \"{status}\", so its data is not "
        f"available to IRIS. It is not a system or mirrored database"
        + (", and IRIS is configured to mount it at startup." if mount_at_startup else ".")
        + " Recommended fix: mount it read-write with the database.mount operation."
    )


@router.get("/issues", response_model=IssuesResponse)
async def get_issues(client: IRISClient = Depends(get_iris_client)) -> IssuesResponse:
    databases = (await get_databases(client)).result
    storage = {_dir_key(entry.Directory): entry for entry in (await get_database_storage(client)).result}

    issues: list[DatabaseMountIssue] = []
    for db in databases:
        dir_entry = storage.get(_dir_key(db.Directory))
        if dir_entry is None or dir_entry.Status.lower().startswith("mounted"):
            continue
        if db.Name.upper() in _SYSTEM_DATABASES or dir_entry.Mirrored:
            continue
        issues.append(
            DatabaseMountIssue(
                database=db.Name,
                directory=dir_entry.Directory,
                status=dir_entry.Status,
                mount_required=db.MountRequired,
                mount_at_startup=db.MountAtStartup,
                mirrored=dir_entry.Mirrored,
                explanation=_explain(db.Name, dir_entry.Directory, dir_entry.Status, db.MountAtStartup),
                parameters={"Directory": dir_entry.Directory, "ReadOnly": False},
            )
        )
    return IssuesResponse(issues=issues, resolutions=ISSUE_CATALOG)
