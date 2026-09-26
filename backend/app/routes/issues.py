"""Fix Issues (MVP): deterministic, read-only issue detection.

GET /api/iris/issues reports actionable issues found in live IRIS data, each
paired with the EXISTING registered operation that fixes it. This route never
fixes anything itself: the fix always goes through that operation's own
route (authorization → explicit confirmation → execution → verification,
with an execution trace recorded by the existing framework).

Only one issue kind exists so far:

  database_dismounted — a configured database whose directory IRIS reports
  as not mounted, that is not one of IRIS's own system databases (the same
  _SYSTEM_DATABASES list database.dismount already refuses) and is not
  mirrored. Recommended fix: database.mount (read-write).

Data comes only from the existing read routes (GET /api/iris/databases and
/api/iris/databases/storage); nothing is invented, and an issue is reported
only when both sources agree on the directory.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_iris_client
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.iris_client.client import IRISClient
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
    explanation: str
    recommended_operation: str = MOUNT_OPERATION
    parameters: dict[str, str | bool]


class IssuesResponse(BaseModel):
    issues: list[DatabaseMountIssue]


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
                explanation=_explain(db.Name, dir_entry.Directory, dir_entry.Status, db.MountAtStartup),
                parameters={"Directory": dir_entry.Directory, "ReadOnly": False},
            )
        )
    return IssuesResponse(issues=issues)
