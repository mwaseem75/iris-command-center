"""Registry of every operation the Command Center knows about.

Each entry describes an operation (read-only or mutating, required
privileges, risk, whether it needs confirmation). This module doesn't run
anything; the handlers in app/execution do.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from app.authorization.privileges import IRISPrivilege


class OperationKind(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OperationDefinition(BaseModel):
    """Description of one operation.

    Checked when it's created:
    - read-only operations never require confirmation
    - mutating operations always require confirmation
    - at least one privilege is required

    `required_privileges` are alternatives: holding any one of them is enough
    (the spec documents most operations as e.g. "%Admin_Manage:U or
    %Admin_Journal:U").
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    kind: OperationKind
    required_privileges: frozenset[IRISPrivilege]
    risk_level: RiskLevel
    confirmation_required: bool

    @model_validator(mode="after")
    def _confirmation_matches_kind(self) -> "OperationDefinition":
        if self.kind is OperationKind.READ_ONLY and self.confirmation_required:
            raise ValueError(
                f"Operation {self.name!r} is read_only but sets confirmation_required=True; "
                "read-only operations never require confirmation."
            )
        if self.kind is OperationKind.MUTATING and not self.confirmation_required:
            raise ValueError(
                f"Operation {self.name!r} is mutating but sets confirmation_required=False; "
                "every mutating operation must require confirmation."
            )
        return self

    @model_validator(mode="after")
    def _required_privileges_not_empty(self) -> "OperationDefinition":
        if not self.required_privileges:
            raise ValueError(f"Operation {self.name!r} must require at least one privilege.")
        return self


# --- The registry ---

OPERATION_REGISTRY: dict[str, OperationDefinition] = {
    "list_tasks": OperationDefinition(
        name="list_tasks",
        description="View a list of scheduled system tasks (GET /api/iris/tasks).",
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.TASK}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    ),
    "list_namespaces": OperationDefinition(
        name="list_namespaces",
        description="View a list of namespaces (GET /api/iris/namespaces).",
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    ),
    "database.info": OperationDefinition(
        name="database.info",
        description=(
            "View a database's non-configurable storage info — block size, "
            "allocated size, available space, host disk free space, "
            "mount/full/encrypted/mirrored status (GET /api/iris/databases/info"
            "?dir=<Directory>, backed by IRIS's async-task POST "
            "/api/admin/v2/database-dir/info — the same async-task pattern "
            "the audit-records query uses). Read-only; changes nothing."
        ),
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.MANAGE, IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    ),
    "database.integrity_check": OperationDefinition(
        name="database.integrity_check",
        description=(
            "Run an integrity check on a database — GET /api/iris/databases/"
            "integrity-check?dir=<Directory>, backed by IRIS's async-task "
            "POST /api/admin/v2/database-dir/integrity-check (same "
            "async-task pattern as database.info/audit-records). "
            "Read-only: verifies existing data, changes nothing. The result "
            "payload is passed through untyped."
        ),
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    ),
    "delete_task": OperationDefinition(
        name="delete_task",
        description=(
            "Example only, not wired to any route. Mirrors IRIS's DELETE /v2/task "
            "(\"%Admin_Operate:U or %Admin_Task:U\") and is used to test "
            "confirmation gating for mutating operations."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.OPERATE, IRISPrivilege.TASK}),
        risk_level=RiskLevel.HIGH,
        confirmation_required=True,
    ),
    "demo.safe-operation": OperationDefinition(
        name="demo.safe-operation",
        description=(
            "Test operation for the execution framework. Its handler never calls "
            "IRIS; it returns a simulated result so authorization, confirmation "
            "and dry runs can be exercised safely."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.LOW,
        confirmation_required=True,
    ),
    "journal.update_purge_archived": OperationDefinition(
        name="journal.update_purge_archived",
        description=(
            "Update the IRIS journal 'Purge Archived Files' setting "
            "(PUT /api/admin/v2/journal/settings, PurgeArchived field only). "
            "Low risk: the setting only matters when journal archiving is configured."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE, IRISPrivilege.JOURNAL}),
        risk_level=RiskLevel.LOW,
        confirmation_required=True,
    ),
    "namespace.create": OperationDefinition(
        name="namespace.create",
        description=(
            "Create a new IRIS namespace (PUT /api/admin/v2/namespace, plus an optional "
            "POST /api/admin/v2/namespace/enable-interop follow-up when the request's "
            "Interop flag is set) — this project's first Namespace mutation. See "
            "app/execution/namespace_create_handler.py for the full validation and "
            "execution flow (existing-namespace rejection, referenced-database "
            "validation, %-prefixed system-namespace rejection)."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "database.create": OperationDefinition(
        name="database.create",
        description=(
            "Create a new IRIS database (POST /api/admin/v2/database-dir) — this "
            "project's first Database mutation. See "
            "app/execution/database_create_handler.py for the full validation and "
            "execution flow (directory-collision rejection, derived-name collision "
            "rejection covering existing/system databases, and bounded-retry "
            "post-action verification)."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "database.mount": OperationDefinition(
        name="database.mount",
        description=(
            "Mount an existing, currently dismounted IRIS database (POST "
            "/api/admin/v2/database-dir/mount?dir=<Directory>, optional ReadOnly). "
            "Rejected when IRIS already reports it mounted (pre-check via "
            "database-dir/info, and IRIS's own 409); verified afterwards via a "
            "fresh database-dir/info read reporting Mounted=true. See "
            "app/execution/database_mount_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "database.dismount": OperationDefinition(
        name="database.dismount",
        description=(
            "Dismount an existing, currently mounted, non-system IRIS database "
            "(POST /api/admin/v2/database-dir/dismount?dir=<Directory>, no request "
            "body — IRIS's own implementation, %Api.Admin.Endpoints.Database.Actions, "
            "calls SYS.Database.Dismount and requires %Admin_Operate; it refuses only "
            "the manager's database itself). Hard-denied here for IRIS's system "
            "databases, databases marked Mount Required, databases used by the %SYS "
            "namespace, and mirrored databases; unknown directories and databases "
            "already dismounted are refused before any write. The preview names the "
            "namespaces that map the database. Verified afterwards via a fresh "
            "database-dir/info read reporting Mounted=false. See "
            "app/execution/database_dismount_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.HIGH,
        confirmation_required=True,
    ),
    "web_app.set_enabled": OperationDefinition(
        name="web_app.set_enabled",
        description=(
            "Enable or disable an existing IRIS web application (PUT "
            "/api/admin/v2/web-app?name=<Name> with the body {\"Enabled\": "
            "<bool>} only). Requires Manage here; the handler additionally "
            "requires Secure, because IRIS's own implementation "
            "(%Api.Admin.Endpoints.WebApp.App) checks %Admin_Secure. "
            "Hard-denied for the Command Center's own /api/admin and "
            "/api/mgmnt apps and for every System-type app (IRIS's PUT always "
            "resets Type to plain CSP, which would clear the System flag). "
            "Verified afterwards via fresh GET /v2/web-app and GET "
            "/v2/web-apps reads. See app/execution/web_app_set_enabled_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "web_app.update_description": OperationDefinition(
        name="web_app.update_description",
        description=(
            "Change the Description of an existing IRIS web application (PUT "
            "/api/admin/v2/web-app?name=<Name> with the body {\"Description\": "
            "<string>} only — IRIS applies it as a partial update). Same rules as "
            "web_app.set_enabled: Manage here plus Secure in the handler (IRIS "
            "checks %Admin_Secure), and hard-denied for the Command Center's own "
            "/api/admin and /api/mgmnt apps and for every System-type app (IRIS's "
            "PUT always resets Type to plain CSP). Unknown apps, unchanged "
            "descriptions and descriptions over IRIS's 256-character limit or with "
            "control characters are refused before any write. Verified afterwards "
            "via fresh GET /v2/web-app and GET /v2/web-apps reads (Description as "
            "requested, Enabled and Type unchanged). See "
            "app/execution/web_app_update_description_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.LOW,
        confirmation_required=True,
    ),
    "user.set_enabled": OperationDefinition(
        name="user.set_enabled",
        description=(
            "Enable or disable login for an existing IRIS user (PUT "
            "/api/admin/v2/security/user?name=<Name> with the body "
            "{\"Enabled\": <bool>} only — IRIS's own implementation, "
            "%Api.Admin.Endpoints.Security.User, applies it as a partial "
            "update and requires %Admin_Secure). Hard-denied for IRIS's "
            "predefined accounts, the Command Center's own sign-in account, "
            "and any user holding %All (directly or as an escalation role). "
            "Unknown users and no-op requests are refused before any write. "
            "Verified afterwards via fresh GET /v2/security/user reads (Enabled "
            "as requested, roles unchanged). Personal user fields are never "
            "returned. See app/execution/user_set_enabled_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.SECURE}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "task.run_now": OperationDefinition(
        name="task.run_now",
        description=(
            "Ask IRIS's Task Manager to run an existing User task now (POST "
            "/api/admin/v2/task/run?id=<Id> with the body {\"RunNow\": true} "
            "only — IRIS's own implementation, %Api.Admin.Endpoints.Task.CRUD, "
            "calls %SYS.Task.RunNow and requires %Admin_Task). Only tasks of "
            "Type User are allowed: IRIS's System and Maintenance tasks are "
            "hard-denied. Also refused: unknown ids, suspended tasks, tasks "
            "already running, and any request while the Task Manager is not "
            "Running. Scheduling for a later time is not offered. Verified "
            "afterwards via fresh GET /v2/task/info reads (the Task Manager "
            "polls every 60 seconds). See app/execution/task_run_now_handler.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.TASK}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "instance.create": OperationDefinition(
        name="instance.create",
        description=(
            "Register another IRIS instance with Command Center. The connection is "
            "checked live first (System Administration API, identity, API version 2 and "
            "the required endpoints) and only a compatible instance is saved. Its "
            "password goes to the Primary's IRIS Wallet (CommandCenter collection), and "
            "the definition, without the password, to ^CommandCenterInstance. See "
            "app/execution/instance_handlers.py."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.WALLET}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "instance.update": OperationDefinition(
        name="instance.update",
        description=(
            "Change a registered instance's name, URL, user, namespace or password. A "
            "blank password keeps the stored one. Changing how an active instance "
            "connects requires a passing live compatibility check. The Primary comes "
            "from the environment and can't be changed."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.WALLET}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
    "instance.set_active": OperationDefinition(
        name="instance.set_active",
        description=(
            "Activate or deactivate a registered instance. Activation requires a passing "
            "live compatibility check; deactivation keeps the definition and credential. "
            "The Primary can't be deactivated."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.MANAGE}),
        risk_level=RiskLevel.LOW,
        confirmation_required=True,
    ),
    "instance.delete": OperationDefinition(
        name="instance.delete",
        description=(
            "Remove a registered instance: its Wallet secret first, then its definition. "
            "The Primary can't be deleted."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.WALLET}),
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=True,
    ),
}


def get_operation(name: str) -> OperationDefinition | None:
    """Look up an operation by name. Unknown names return None (callers deny)."""
    return OPERATION_REGISTRY.get(name)
