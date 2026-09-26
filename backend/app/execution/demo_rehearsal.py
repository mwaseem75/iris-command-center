"""Demo Activity rehearsal: a user-triggered, controlled sequence of REAL
operations that produces meaningful execution traces on a fresh install —
without leaving any IRIS change behind.

Every step is an existing, registered operation run through the existing
OperationExecutor and its existing handler, exactly as the operation's own
route runs it: authorization (privileges from the live IRIS session),
confirmation (the caller's own `confirmed` flag — never assumed because
this is a rehearsal), execution and post-action verification. Nothing here
calls an IRIS mutation endpoint itself; the only direct IRIS calls are
read-only GETs used to pick candidates and to capture/re-check the original
values. No operation is added to the registry.

Sequence (stops at the first failure):
  1. journal.update_purge_archived: toggle PurgeArchived, then restore it.
  2. web_app.update_description: on a non-System, non-protected web app
     (/csp/user when it is eligible, else the first safe app
     alphabetically), set a temporary Description, then restore it.
  3. database.mount and task.run_now: DRY-RUN ONLY (ExecutionContext
     dry_run=True — the executor only ever calls the handler's dry_run()),
     each on a valid candidate if one exists, otherwise skipped.

Issue Resolution Rehearsal (separate, manual only — run_issue_resolution_
rehearsal(); never part of the automatic startup run): uses the IPM
database to rehearse the Fix Issues flow end to end — dismount IPM with
database.dismount (dry run first, so its safety rules apply), detect the
issue through the existing issue detection (GET /api/iris/issues), fix it
with database.mount using the detected issue's own parameters, then verify
IPM is mounted and the issue is gone. If anything fails after the dismount,
IPM is mounted again (a failed remount is reported as "restore_failed").

Restoration: after a change step whose mutation may have been applied
(success, verification failure or an execution failure), the current value
is re-read; if it differs from the original — or cannot be read — the
original is restored through the same operation, and a failed restoration
is reported explicitly (overall status "restore_failed").

Returned details are the executor's/handlers' own short detail strings plus
names/ids of the chosen targets; no handler `data`, credential, token or
header is ever included.
"""

import asyncio
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from app.execution.database_dismount_handler import DatabaseDismountHandler
from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import ExecutionContext, OperationRequest, OperationResult, OperationResultStatus
from app.execution.task_run_now_handler import TaskRunNowHandler
from app.execution.web_app_set_enabled_handler import _PROTECTED_APPS, _normalize
from app.execution.web_app_update_description_handler import (
    _VERIFY_RETRY_DELAYS_SECONDS as _WEB_APP_VERIFY_DELAYS,
    WebAppUpdateDescriptionHandler,
)
from app.iris_client.client import IRISClient
from app.observability.store import list_traces
from app.routes.issues import get_issues

JOURNAL_OPERATION = "journal.update_purge_archived"
WEB_APP_DESCRIPTION_OPERATION = "web_app.update_description"
MOUNT_OPERATION = "database.mount"
TASK_RUN_OPERATION = "task.run_now"
DISMOUNT_OPERATION = "database.dismount"
ISSUE_DATABASE = "IPM"  # the one database the Issue Resolution Rehearsal uses

_JOURNAL_SETTINGS_PATH = "/v2/journal/settings"
_WEB_APPS_PATH = "/v2/web-apps"
_WEB_APP_PATH = "/v2/web-app"
_DATABASE_DIRS_PATH = "/v2/database-dirs"
_DATABASES_PATH = "/v2/databases"
_TASKS_PATH = "/v2/tasks"

REHEARSAL_MARKER = "[IRIS Command Center rehearsal]"
PREFERRED_WEB_APP = "/csp/user"
_DESCRIPTION_MAX_LENGTH = 256

# Overridable only so tests can shrink the web-app verify retry delays.
WEB_APP_VERIFY_RETRY_DELAYS: tuple[float, ...] = _WEB_APP_VERIFY_DELAYS

# One rehearsal at a time: two overlapping runs could each "restore" the
# other's temporary value.
_rehearsal_lock = asyncio.Lock()

StepStatus = Literal["success", "dry_run", "skipped", "failed", "not_needed"]
RehearsalStatus = Literal["completed", "stopped", "restore_failed"]


class RehearsalStep(BaseModel):
    step: str
    operation_name: str | None = None
    action: Literal["read", "select", "change", "restore", "dry_run", "detect", "fix", "verify"]
    status: StepStatus
    operation_status: str | None = None  # the executor's own OperationResult.status
    target: str | None = None
    detail: str
    trace_id: str | None = None


class RehearsalResult(BaseModel):
    status: RehearsalStatus
    confirmed: bool
    detail: str
    steps: list[RehearsalStep]


class RehearsalInProgressError(Exception):
    """Another rehearsal is already running."""


class _Stop(Exception):
    """Internal: a step failed; the sequence stops (after any restoration)."""


def build_rehearsal_executor(client: IRISClient) -> OperationExecutor:
    """The same executor and handlers the operations' own routes use."""
    return OperationExecutor(
        {
            JOURNAL_OPERATION: JournalUpdatePurgeArchivedHandler(client),
            WEB_APP_DESCRIPTION_OPERATION: WebAppUpdateDescriptionHandler(
                client, verify_retry_delays_seconds=WEB_APP_VERIFY_RETRY_DELAYS
            ),
            MOUNT_OPERATION: DatabaseMountHandler(client),
            TASK_RUN_OPERATION: TaskRunNowHandler(client),
            DISMOUNT_OPERATION: DatabaseDismountHandler(client),
        }
    )


def _result_list(body: Any) -> list[dict[str, Any]]:
    result = body.get("result") if isinstance(body, dict) else None
    return [entry for entry in result if isinstance(entry, dict)] if isinstance(result, list) else []


def _result_object(body: Any) -> dict[str, Any]:
    result = body.get("result") if isinstance(body, dict) else None
    return result if isinstance(result, dict) else {}


def is_safe_web_app(entry: dict[str, Any]) -> bool:
    """Non-System and not one of the apps the Command Center depends on
    (/api/admin, /api/mgmnt) — the same rules the handler itself enforces."""
    name = entry.get("Name")
    if not isinstance(name, str) or not name.startswith("/"):
        return False
    if _normalize(name) in _PROTECTED_APPS:
        return False
    app_type = entry.get("Type")
    if entry.get("IsSystemApp") is True or not isinstance(app_type, str) or "system" in app_type.lower():
        return False
    return True


def temporary_description(original: str) -> str:
    candidate = f"{original} {REHEARSAL_MARKER}".strip()
    if len(candidate) > _DESCRIPTION_MAX_LENGTH:
        candidate = REHEARSAL_MARKER
    if candidate == original:
        candidate = f"{REHEARSAL_MARKER} (temporary)"
    return candidate


class _Rehearsal:
    def __init__(self, client: IRISClient, privileges: frozenset[str], confirmed: bool, executor: OperationExecutor):
        self.client = client
        self.privileges = privileges
        self.confirmed = confirmed
        self.executor = executor
        self.steps: list[RehearsalStep] = []
        self.restore_failed = False

    # --- running one operation through the existing executor ---

    async def run_operation(
        self, operation_name: str, parameters: dict[str, Any], *, dry_run: bool
    ) -> tuple[OperationResult | None, str | None, str | None]:
        """Returns (result, trace_id, error). `trace_id` is reported only when
        exactly one new trace for this operation appeared during the call."""
        before = {trace.trace_id for trace in list_traces()}
        try:
            result = await self.executor.execute(
                OperationRequest(operation_name=operation_name, parameters=parameters),
                ExecutionContext(
                    available_privileges=self.privileges,
                    confirmation_received=self.confirmed,
                    dry_run=dry_run,
                ),
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - reported as a failed step, never raised
            result, error = None, f"The operation raised an unexpected error ({exc.__class__.__name__})."
        new = [t for t in list_traces() if t.trace_id not in before and t.operation_name == operation_name]
        return result, (new[0].trace_id if len(new) == 1 else None), error

    def add(self, **fields: Any) -> RehearsalStep:
        step = RehearsalStep(**fields)
        self.steps.append(step)
        return step

    async def read(self, step: str, target: str | None, reader: Callable[[], Awaitable[Any]], what: str) -> Any:
        try:
            value = await reader()
        except Exception as exc:  # noqa: BLE001
            self.add(step=step, action="read", status="failed", target=target,
                     detail=f"Could not read {what} from IRIS ({exc.__class__.__name__}).")
            raise _Stop from exc
        if value is None:
            self.add(step=step, action="read", status="failed", target=target,
                     detail=f"IRIS did not report {what}.")
            raise _Stop
        return value

    # --- a reversible change followed by guaranteed restoration ---

    async def change_and_restore(
        self,
        *,
        phase: str,
        operation_name: str,
        target: str,
        original: Any,
        changed_parameters: dict[str, Any],
        restore_parameters: dict[str, Any],
        read_current: Callable[[], Awaitable[Any]],
    ) -> None:
        result, trace_id, error = await self.run_operation(operation_name, changed_parameters, dry_run=False)
        status = result.status if result else None
        changed_ok = status is OperationResultStatus.SUCCESS
        self.add(
            step=f"{phase}.change", operation_name=operation_name, action="change",
            status="success" if changed_ok else "failed",
            operation_status=status.value if status else "error",
            target=target, detail=error or result.detail, trace_id=trace_id,
        )

        # The mutation may have been applied unless the framework stopped it
        # before the handler's write (denied / unconfirmed / no handler).
        possibly_applied = status in (
            None,
            OperationResultStatus.SUCCESS,
            OperationResultStatus.VERIFICATION_FAILED,
            OperationResultStatus.EXECUTION_FAILED,
        )
        if possibly_applied:
            await self.restore(phase, operation_name, target, original, restore_parameters, read_current, changed_ok)
        if not changed_ok:
            raise _Stop

    async def restore(
        self,
        phase: str,
        operation_name: str,
        target: str,
        original: Any,
        restore_parameters: dict[str, Any],
        read_current: Callable[[], Awaitable[Any]],
        change_succeeded: bool,
    ) -> None:
        if not change_succeeded:
            try:
                current = await read_current()
            except Exception:  # noqa: BLE001 - unknown state: restore anyway
                current = object()
            if current == original:
                self.add(step=f"{phase}.restore", operation_name=operation_name, action="restore",
                         status="not_needed", target=target,
                         detail="The original value is still in place; nothing to restore.")
                return

        result, trace_id, error = await self.run_operation(operation_name, restore_parameters, dry_run=False)
        status = result.status if result else None
        restored = status is OperationResultStatus.SUCCESS
        if not restored:
            self.restore_failed = True
        self.add(
            step=f"{phase}.restore", operation_name=operation_name, action="restore",
            status="success" if restored else "failed",
            operation_status=status.value if status else "error",
            target=target,
            detail=(error or result.detail) if restored else (
                f"RESTORATION FAILED — {target} may still hold the temporary value; restore it manually "
                f"to {original!r}. {error or result.detail}"
            ),
            trace_id=trace_id,
        )
        if not restored:
            raise _Stop

    async def dry_run(self, phase: str, operation_name: str, target: str, parameters: dict[str, Any]) -> None:
        result, trace_id, error = await self.run_operation(operation_name, parameters, dry_run=True)
        ok = (
            result is not None
            and result.status is OperationResultStatus.DRY_RUN
            and result.handler_result is not None
            and result.handler_result.outcome.value == "success"
        )
        self.add(
            step=f"{phase}.dry_run", operation_name=operation_name, action="dry_run",
            status="dry_run" if ok else "failed",
            operation_status=result.status.value if result else "error",
            target=target,
            detail=error or (result.handler_result.detail if result.handler_result else result.detail),
            trace_id=trace_id,
        )
        if not ok:
            raise _Stop

    # --- the three phases ---

    async def journal_phase(self) -> None:
        async def read_purge_archived() -> bool | None:
            value = _result_object(await self.client.get(_JOURNAL_SETTINGS_PATH)).get("PurgeArchived")
            return value if isinstance(value, bool) else None

        original = await self.read("journal.read", "PurgeArchived", read_purge_archived, "the journal PurgeArchived setting")
        self.add(step="journal.read", action="read", status="success", target="PurgeArchived",
                 detail=f"Current PurgeArchived is {original}.")
        await self.change_and_restore(
            phase="journal", operation_name=JOURNAL_OPERATION, target="PurgeArchived", original=original,
            changed_parameters={"PurgeArchived": not original},
            restore_parameters={"PurgeArchived": original},
            read_current=read_purge_archived,
        )

    async def web_app_phase(self) -> None:
        apps = await self.read("web_app.select", None,
                               lambda: self._list(_WEB_APPS_PATH), "the web application list")
        safe = sorted((e["Name"] for e in apps if is_safe_web_app(e)), key=str.lower)
        skipped = len(apps) - len(safe)
        if not safe:
            self.add(step="web_app.select", action="select", status="skipped",
                     detail=f"No non-System, non-protected web application found ({skipped} skipped).")
            return
        # Prefer the least sensitive demo target when it passed the same
        # safety rules; otherwise the first safe app alphabetically.
        name = next((n for n in safe if _normalize(n) == _normalize(PREFERRED_WEB_APP)), safe[0])
        self.add(step="web_app.select", action="select", status="success", target=name,
                 detail=f"Selected {name!r} ({skipped} System/protected applications skipped).")

        async def read_description() -> str | None:
            value = _result_object(await self.client.get(_WEB_APP_PATH, params={"name": name})).get("Description")
            return value if isinstance(value, str) else None

        original = await self.read("web_app.read", name, read_description, f"{name!r}'s Description")
        self.add(step="web_app.read", action="read", status="success", target=name,
                 detail="Captured the original Description.")
        await self.change_and_restore(
            phase="web_app", operation_name=WEB_APP_DESCRIPTION_OPERATION, target=name, original=original,
            changed_parameters={"Name": name, "Description": temporary_description(original)},
            restore_parameters={"Name": name, "Description": original},
            read_current=read_description,
        )

    async def dry_run_phase(self) -> None:
        dirs = await self.read("database.select", None, lambda: self._list(_DATABASE_DIRS_PATH),
                               "the local database list")
        dismounted = [
            e["Directory"] for e in dirs
            if isinstance(e.get("Directory"), str)
            and isinstance(e.get("Status"), str)
            and not e["Status"].lower().startswith("mounted")
        ]
        if dismounted:
            await self.dry_run("database", MOUNT_OPERATION, dismounted[0],
                               {"Directory": dismounted[0], "ReadOnly": False})
        else:
            self.add(step="database.dry_run", operation_name=MOUNT_OPERATION, action="dry_run",
                     status="skipped", detail="No dismounted database to mount — skipped (no request sent).")

        tasks = await self.read("task.select", None, lambda: self._list(_TASKS_PATH), "the task list")
        runnable = sorted(
            e["Id"] for e in tasks
            if isinstance(e.get("Id"), int) and e.get("Type") == "User" and e.get("Suspended") is False
        )
        if runnable:
            await self.dry_run("task", TASK_RUN_OPERATION, f"task {runnable[0]}", {"Id": runnable[0]})
        else:
            self.add(step="task.dry_run", operation_name=TASK_RUN_OPERATION, action="dry_run",
                     status="skipped",
                     detail="No non-suspended User task (only User tasks may be run) — skipped (no request sent).")

    async def _list(self, path: str) -> list[dict[str, Any]]:
        return _result_list(await self.client.get(path))

    # --- Issue Resolution Rehearsal (manual only) ---

    async def _ipm_state(self) -> tuple[str, bool] | None:
        """(directory, mounted) for IPM from the existing read-only lists,
        or None when IPM is not a configured database."""
        entry = next((e for e in await self._list(_DATABASES_PATH)
                      if isinstance(e.get("Name"), str) and e["Name"].upper() == ISSUE_DATABASE), None)
        if entry is None or not isinstance(entry.get("Directory"), str):
            return None
        directory = entry["Directory"]
        status = next((d.get("Status") for d in await self._list(_DATABASE_DIRS_PATH)
                       if isinstance(d.get("Directory"), str) and d["Directory"].rstrip("/") == directory.rstrip("/")),
                      None)
        return directory, isinstance(status, str) and status.lower().startswith("mounted")

    async def _ipm_issue(self) -> dict[str, Any] | None:
        """IPM's entry in the existing issue detection (GET /api/iris/issues), if any."""
        issues = (await get_issues(self.client)).issues
        return next((i.model_dump() for i in issues if i.database.upper() == ISSUE_DATABASE), None)

    async def ensure_ipm_mounted(self, directory: str) -> None:
        """Restore path: mount IPM again (through database.mount) unless it
        is already mounted. A failed remount is reported explicitly."""
        try:
            state = await self._ipm_state()
        except Exception:  # noqa: BLE001 - unknown state: try the mount anyway
            state = None
        if state is not None and state[1]:
            self.add(step="issue.restore", operation_name=MOUNT_OPERATION, action="restore", status="not_needed",
                     target=ISSUE_DATABASE, detail="IPM is mounted; nothing to restore.")
            return
        result, trace_id, error = await self.run_operation(
            MOUNT_OPERATION, {"Directory": directory, "ReadOnly": False}, dry_run=False)
        restored = result is not None and result.status is OperationResultStatus.SUCCESS
        if not restored:
            self.restore_failed = True
        detail = error or (result.detail if result else "")
        self.add(step="issue.restore", operation_name=MOUNT_OPERATION, action="restore",
                 status="success" if restored else "failed",
                 operation_status=result.status.value if result else "error", target=ISSUE_DATABASE,
                 detail=detail if restored else (
                     f"RESTORATION FAILED — IPM ({directory}) may still be dismounted; mount it from the "
                     f"Databases page. {detail}"),
                 trace_id=trace_id)

    async def issue_resolution_phase(self) -> None:
        directory, mounted = await self.read("issue.read", ISSUE_DATABASE, self._ipm_state, "the IPM database")
        if not mounted:
            self.add(step="issue.read", action="read", status="failed", target=ISSUE_DATABASE,
                     detail="IPM is not mounted, so there is nothing to rehearse. Mount it from the Databases page first.")
            raise _Stop
        self.add(step="issue.read", action="read", status="success", target=ISSUE_DATABASE,
                 detail=f"IPM ({directory}) is mounted.")

        # Eligibility: database.dismount's own safety rules, dry run only.
        await self.dry_run("issue", DISMOUNT_OPERATION, ISSUE_DATABASE, {"Directory": directory})

        result, trace_id, error = await self.run_operation(DISMOUNT_OPERATION, {"Directory": directory}, dry_run=False)
        status = result.status if result else None
        dismounted = status is OperationResultStatus.SUCCESS
        self.add(step="issue.dismount", operation_name=DISMOUNT_OPERATION, action="change",
                 status="success" if dismounted else "failed", operation_status=status.value if status else "error",
                 target=ISSUE_DATABASE, detail=error or result.detail, trace_id=trace_id)
        try:
            if not dismounted:
                raise _Stop

            issue = await self._ipm_issue()
            if issue is None:
                self.add(step="issue.detect", action="detect", status="failed", target=ISSUE_DATABASE,
                         detail="The Command Center issue detection did not report IPM.")
                raise _Stop
            self.add(step="issue.detect", action="detect", status="success", target=ISSUE_DATABASE,
                     detail=f"Command Center Issue: {issue['explanation']}")

            # The Fix Issues flow: the recommended operation with the issue's own parameters.
            result, trace_id, error = await self.run_operation(
                issue["recommended_operation"], issue["parameters"], dry_run=False)
            fixed = result is not None and result.status is OperationResultStatus.SUCCESS
            self.add(step="issue.fix", operation_name=issue["recommended_operation"], action="fix",
                     status="success" if fixed else "failed",
                     operation_status=result.status.value if result else "error",
                     target=ISSUE_DATABASE, detail=error or result.detail, trace_id=trace_id)
            if not fixed:
                raise _Stop

            state = await self._ipm_state()
            still_listed = await self._ipm_issue()
            if state is None or not state[1] or still_listed is not None:
                self.add(step="issue.verify", action="verify", status="failed", target=ISSUE_DATABASE,
                         detail="After the fix, IPM is not reported as mounted or the issue is still listed.")
                raise _Stop
            self.add(step="issue.verify", action="verify", status="success", target=ISSUE_DATABASE,
                     detail="IPM is mounted again and the Command Center issue is gone.")
        except BaseException:
            # Any failure after the dismount — including unexpected errors
            # and cancellation (asyncio.CancelledError is a BaseException) —
            # first makes sure IPM ends up mounted, then re-raises.
            await self.ensure_ipm_mounted(directory)
            raise

    async def run_issue_resolution(self) -> RehearsalResult:
        try:
            await self.issue_resolution_phase()
        except _Stop:
            pass
        except Exception as exc:  # noqa: BLE001 - reported as a failed step, never raised
            self.add(step="issue.error", action="read", status="failed", target=ISSUE_DATABASE,
                     detail=f"The rehearsal raised an unexpected error ({exc.__class__.__name__}).")
        return self._summary()

    async def run(self) -> RehearsalResult:
        try:
            await self.journal_phase()
            await self.web_app_phase()
            await self.dry_run_phase()
        except _Stop:
            pass
        return self._summary()

    def _summary(self) -> RehearsalResult:
        failed = next((s for s in self.steps if s.status == "failed"), None)
        if self.restore_failed:
            status: RehearsalStatus = "restore_failed"
            detail = "Stopped: a temporary change could NOT be restored — see the failed restore step."
        elif failed:
            status = "stopped"
            detail = f"Stopped at {failed.step}; every temporary change made before it was restored."
        else:
            status = "completed"
            detail = "Rehearsal completed; every temporary change was restored and verified."
        return RehearsalResult(status=status, confirmed=self.confirmed, detail=detail, steps=self.steps)


async def run_rehearsal(
    client: IRISClient,
    privileges: frozenset[str],
    confirmed: bool,
    *,
    executor: OperationExecutor | None = None,
) -> RehearsalResult:
    """Runs the whole rehearsal once. Raises RehearsalInProgressError if one
    is already running in this process."""
    if _rehearsal_lock.locked():
        raise RehearsalInProgressError
    async with _rehearsal_lock:
        rehearsal = _Rehearsal(client, privileges, confirmed, executor or build_rehearsal_executor(client))
        return await rehearsal.run()


async def run_issue_resolution_rehearsal(
    client: IRISClient,
    privileges: frozenset[str],
    confirmed: bool,
    *,
    executor: OperationExecutor | None = None,
) -> RehearsalResult:
    """The manual Issue Resolution Rehearsal (IPM). Shares the rehearsal
    lock, so it never overlaps any other rehearsal; raises
    RehearsalInProgressError if one is already running."""
    if _rehearsal_lock.locked():
        raise RehearsalInProgressError
    async with _rehearsal_lock:
        rehearsal = _Rehearsal(client, privileges, confirmed, executor or build_rehearsal_executor(client))
        return await rehearsal.run_issue_resolution()
