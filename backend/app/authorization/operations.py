"""The central operation/command model and registry.

An `OperationDefinition` describes an action the Command Center backend
*could* perform against IRIS — its classification, required privilege, risk,
and whether it needs explicit confirmation — as pure data. Defining an
operation here does NOT implement or execute it; nothing in this module (or
anywhere in the authorization package) calls IRIS. See app/routes/iris.py
for the operations that are actually wired up (all read-only, all
registered here with confirmation_required=False).

The registry is intentionally small and explicit: every operation the
authorization layer knows about is listed in OPERATION_REGISTRY, in one
place, rather than scattered as string literals across routes.
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
    """Immutable description of one operation. Three invariants are enforced
    at construction time, not left to callers to remember:

    - A read-only operation can never require confirmation (there is
      nothing to confirm — it doesn't change anything).
    - A mutating operation must always require confirmation. This is a
      deliberate project decision (see docs/authorization-model.md),
      stricter than the minimum this step's requirements state, grounded
      directly in docs/product-requirements.md's mandate that "the system
      must require explicit, unambiguous confirmation before executing any
      mutating operation" with no stated exception. There is no flag
      anywhere to construct a mutating operation that skips confirmation.
    - `required_privileges` must be non-empty.

    `required_privileges` is a set of ALTERNATIVES — the caller needs to
    hold ANY ONE of them, matching how mainspec_v2.json documents most
    operations (e.g. "%Admin_Manage:U or %Admin_Journal:U"). A single-member
    set behaves exactly like the earlier single-privilege model it replaces
    (Phase 2 Step 7 — see docs/authorization-model.md's "Known
    Simplifications" section for the earlier limitation this resolves).
    Nothing here invents a new privilege: every member must already be an
    `IRISPrivilege` enum value.
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
#
# Read-only entries below correspond to the already-implemented, already
# real-container-verified routes in app/routes/iris.py — see
# docs/api-capability-matrix.md for their verification record.

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
            "Read-only: verifies existing data, changes nothing. This "
            "operation has deliberately never been executed against a real "
            "IRIS instance during implementation (a real scan is "
            "resource-intensive); its result payload is therefore left "
            "untyped rather than guessed — see "
            "app/models/iris.py's DatabaseIntegrityCheckResult."
        ),
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    ),
    "delete_task": OperationDefinition(
        name="delete_task",
        description=(
            "Illustrative/example only — NOT implemented or callable anywhere in this "
            "project yet. Corresponds to the spec-documented `DELETE /v2/task` "
            "operation, which mainspec_v2.json lists as requiring "
            "\"%Admin_Operate:U or %Admin_Task:U\" — now represented exactly as that "
            "OR, since Phase 2 Step 7 added multi-privilege support. Exists solely so "
            "the authorization layer's confirmation-gating behavior for mutating "
            "operations has a real, grounded example to be tested against."
        ),
        kind=OperationKind.MUTATING,
        required_privileges=frozenset({IRISPrivilege.OPERATE, IRISPrivilege.TASK}),
        risk_level=RiskLevel.HIGH,
        confirmation_required=True,
    ),
    "demo.safe-operation": OperationDefinition(
        name="demo.safe-operation",
        description=(
            "Phase 2 Step 5 demonstration/test operation for the OperationExecutor "
            "framework. Its handler (app/execution/demo_handler.py) NEVER calls IRIS, "
            "in dry-run or otherwise — it only returns a deterministic, synthetic "
            "simulation result. It exists purely to exercise the execution framework "
            "end-to-end (authorization, confirmation, dry-run, handler dispatch) "
            "without any real IRIS mutation existing anywhere in this project yet."
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
            "Selected as the project's first real mutating operation per "
            "docs/first-mutation-selection.md — see docs/first-mutation-implementation.md "
            "for the handler/route implementation. Chosen because archiving is not "
            "configured on icc-iris-dev (ArchiveName was empty in every Phase 1 "
            "observation), so this specific field has no practical effect on that "
            "instance today."
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
}


def get_operation(name: str) -> OperationDefinition | None:
    """Look up a registered operation by name. Returns None for anything not
    explicitly registered — there is no fallback, default, or wildcard
    operation. An unrecognized name is the caller's (or the service layer's)
    signal to deny, never to guess."""
    return OPERATION_REGISTRY.get(name)
