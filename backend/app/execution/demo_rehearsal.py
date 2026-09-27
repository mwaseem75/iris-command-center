"""Demo Activity: runs a few real operations so a fresh install has some
execution traces to look at, and puts everything back afterwards.

Each step goes through the normal OperationExecutor and handler, same as
the operation's own route (authorization, confirmation, execution,
verification). We never call an IRIS write endpoint directly here; the
direct calls are GETs to pick targets and to read original values.

Steps (stops at the first failure):
1. journal.update_purge_archived: flip PurgeArchived, then restore it.
2. web_app.update_description: on a safe web app (/csp/user if allowed,
   otherwise the first safe one alphabetically) set a temporary
   description, then restore it.
3. database.mount and task.run_now: dry run only, on a candidate if
   there is one, otherwise skipped.

After a change step, the value is re-read and restored if it differs (or
can't be read). A failed restore gives overall status "restore_failed".

The Issue Resolution Rehearsal (run_issue_resolution_rehearsal) is
separate and only runs when triggered manually. It dismounts IPM (dry run
first), checks the issue shows up in GET /api/iris/issues, fixes it with
database.mount using the issue's parameters, and checks it's gone. If
anything fails after the dismount, IPM is mounted again.

It can also run as two separate steps. "Create" dismounts IPM, verifies
IRIS reports it dismounted, and stops, leaving the issue active on purpose
(a failure before that check still remounts IPM). "Resolve" detects the
active IPM issue, fixes it with database.mount and verifies it's gone; on
failure IPM stays dismounted and the result says so.

The results only hold short detail strings and target names/ids, never
handler data or credentials.
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
ISSUE_DATABASE = "IPM"  # database used by the Issue Resolution Rehearsal

_JOURNAL_SETTINGS_PATH = "/v2/journal/settings"
_WEB_APPS_PATH = "/v2/web-apps"
_WEB_APP_PATH = "/v2/web-app"
_DATABASE_DIRS_PATH = "/v2/database-dirs"
_DATABASES_PATH = "/v2/databases"
_TASKS_PATH = "/v2/tasks"

REHEARSAL_MARKER = "[IRIS Command Center rehearsal]"
PREFERRED_WEB_APP = "/csp/user"
_DESCRIPTION_MAX_LENGTH = 256

# Tests use this to shrink the web-app verify delays.
WEB_APP_VERIFY_RETRY_DELAYS: tuple[float, ...] = _WEB_APP_VERIFY_DELAYS

# Only one rehearsal at a time, otherwise two runs could restore each
# other's temporary values.
_rehearsal_lock = asyncio.Lock()

StepStatus = Literal["success", "dry_run", "skipped", "failed", "not_needed"]
RehearsalStatus = Literal["completed", "stopped", "restore_failed"]


class RehearsalStep(BaseModel):
    step: str
    operation_name: str | None = None
    action: Literal["read", "select", "change", "restore", "dry_run", "detect", "fix", "verify"]
    status: StepStatus
    operation_status: str | None = None  # OperationResult.status
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
    """A step failed; stop the sequence (after restoring)."""


def build_rehearsal_executor(client: IRISClient) -> OperationExecutor:
    """Same executor and handlers the operation routes use."""
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
    """Not a System app and not one we depend on (/api/admin, /api/mgmnt).
    Same rules the handler applies.
    """
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

    # --- running one operation ---

    async def run_operation(
        self, operation_name: str, parameters: dict[str, Any], *, dry_run: bool,
        resolution_issue_type: str | None = None,
    ) -> tuple[OperationResult | None, str | None, str | None]:
        """Returns (result, trace_id, error). trace_id is only set when exactly
        one new trace for this operation showed up during the call.
        """
        before = {trace.trace_id for trace in list_traces()}
        try:
            result = await self.executor.execute(
                OperationRequest(
                    operation_name=operation_name,
                    parameters=parameters,
                    resolution_issue_type=resolution_issue_type,
                ),
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

    # --- change something, then always restore it ---

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

        # Assume the write may have happened unless the executor stopped
        # before the handler (denied / unconfirmed / no handler).
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

    # --- steps ---

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
        # Use /csp/user if it's allowed, otherwise the first safe app
        # alphabetically.
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
        """(directory, mounted) for IPM, or None if IPM isn't configured."""
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
        """IPM's entry in GET /api/iris/issues, if any."""
        issues = (await get_issues(self.client)).issues
        return next((i.model_dump() for i in issues if i.database.upper() == ISSUE_DATABASE), None)

    async def ensure_ipm_mounted(self, directory: str) -> None:
        """Mount IPM again via database.mount unless it's already mounted."""
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

    async def dismount_ipm(self) -> tuple[str, bool]:
        """Check IPM is mounted, dry-run then run database.dismount.
        Returns (directory, dismounted)."""
        directory, mounted = await self.read("issue.read", ISSUE_DATABASE, self._ipm_state, "the IPM database")
        if not mounted:
            self.add(step="issue.read", action="read", status="failed", target=ISSUE_DATABASE,
                     detail="IPM is not mounted, so there is nothing to rehearse. Mount it from the Databases page first.")
            raise _Stop
        self.add(step="issue.read", action="read", status="success", target=ISSUE_DATABASE,
                 detail=f"IPM ({directory}) is mounted.")

        # Dry run first so database.dismount's safety checks apply.
        await self.dry_run("issue", DISMOUNT_OPERATION, ISSUE_DATABASE, {"Directory": directory})

        result, trace_id, error = await self.run_operation(DISMOUNT_OPERATION, {"Directory": directory}, dry_run=False)
        status = result.status if result else None
        dismounted = status is OperationResultStatus.SUCCESS
        self.add(step="issue.dismount", operation_name=DISMOUNT_OPERATION, action="change",
                 status="success" if dismounted else "failed", operation_status=status.value if status else "error",
                 target=ISSUE_DATABASE, detail=error or result.detail, trace_id=trace_id)
        return directory, dismounted

    async def detect_and_resolve_ipm(self) -> None:
        """Detect IPM's issue, fix it with the recommended operation, verify it's gone."""
        issue = await self._ipm_issue()
        if issue is None:
            self.add(step="issue.detect", action="detect", status="failed", target=ISSUE_DATABASE,
                     detail="The Command Center issue detection did not report IPM.")
            raise _Stop
        self.add(step="issue.detect", action="detect", status="success", target=ISSUE_DATABASE,
                 detail=f"Command Center Issue: {issue['explanation']}")

        # Fix it the way Resolve Issues would: the recommended operation and the issue's parameters.
        result, trace_id, error = await self.run_operation(
            issue["recommended_operation"], issue["parameters"], dry_run=False,
            resolution_issue_type=issue["kind"])
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

    async def issue_resolution_phase(self) -> None:
        directory, dismounted = await self.dismount_ipm()
        try:
            if not dismounted:
                raise _Stop
            await self.detect_and_resolve_ipm()
        except BaseException:
            # On any failure after the dismount, including cancellation
            # (CancelledError is a BaseException), remount IPM first, then re-raise.
            await self.ensure_ipm_mounted(directory)
            raise

    # --- Two-step demo: Create Demo Issue, then Resolve Demo Issue ---

    async def create_issue_phase(self) -> None:
        """Dismount IPM, verify it's dismounted, then stop and leave the issue
        active on purpose. Only a failure before that verification remounts IPM."""
        directory, dismounted = await self.dismount_ipm()
        try:
            if not dismounted:
                raise _Stop
            state = await self._ipm_state()
            if state is None or state[1]:
                self.add(step="issue.confirm_dismounted", action="verify", status="failed", target=ISSUE_DATABASE,
                         detail="After the dismount, IRIS does not report IPM as dismounted.")
                raise _Stop
        except BaseException:
            await self.ensure_ipm_mounted(directory)
            raise
        self.add(step="issue.confirm_dismounted", action="verify", status="success", target=ISSUE_DATABASE,
                 detail=f"IRIS reports IPM ({directory}) as dismounted. The demo issue stays active until it is resolved.")

    async def resolve_issue_phase(self) -> None:
        """Resolve the active IPM demo issue with the normal detect/fix/verify
        steps. No remount on failure: IPM stays as it was (dismounted)."""
        _, mounted = await self.read("issue.check", ISSUE_DATABASE, self._ipm_state, "the IPM database")
        if mounted:
            self.add(step="issue.check", action="read", status="failed", target=ISSUE_DATABASE,
                     detail="IPM is mounted, so there is no demo issue to resolve. Create it first.")
            raise _Stop
        self.add(step="issue.check", action="read", status="success", target=ISSUE_DATABASE,
                 detail="IPM is dismounted; the demo issue is active.")
        await self.detect_and_resolve_ipm()

    async def run_issue_resolution(self, phase: Callable[[], Awaitable[None]] | None = None,
                                   **summary: str) -> RehearsalResult:
        try:
            await (phase or self.issue_resolution_phase)()
        except _Stop:
            pass
        except Exception as exc:  # noqa: BLE001 - reported as a failed step, never raised
            self.add(step="issue.error", action="read", status="failed", target=ISSUE_DATABASE,
                     detail=f"The rehearsal raised an unexpected error ({exc.__class__.__name__}).")
        return self._summary(**summary)

    async def run(self) -> RehearsalResult:
        try:
            await self.journal_phase()
            await self.web_app_phase()
            await self.dry_run_phase()
        except _Stop:
            pass
        return self._summary()

    def _summary(self, *, completed: str | None = None, stopped: str | None = None) -> RehearsalResult:
        failed = next((s for s in self.steps if s.status == "failed"), None)
        if self.restore_failed:
            status: RehearsalStatus = "restore_failed"
            detail = "Stopped: a temporary change could NOT be restored — see the failed restore step."
        elif failed:
            status = "stopped"
            detail = f"Stopped at {failed.step}; " + (
                stopped or "every temporary change made before it was restored.")
        else:
            status = "completed"
            detail = completed or "Rehearsal completed; every temporary change was restored and verified."
        return RehearsalResult(status=status, confirmed=self.confirmed, detail=detail, steps=self.steps)


async def run_rehearsal(
    client: IRISClient,
    privileges: frozenset[str],
    confirmed: bool,
    *,
    executor: OperationExecutor | None = None,
) -> RehearsalResult:
    """Run the whole rehearsal once. Raises RehearsalInProgressError if one is running."""
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
    step: Literal["full", "create", "resolve"] = "full",
) -> RehearsalResult:
    """Run the Issue Resolution Rehearsal (IPM): the whole cycle ("full"),
    or one step of the two-step demo ("create" or "resolve"). Uses the same
    lock as run_rehearsal, so raises RehearsalInProgressError if one is running.
    """
    if _rehearsal_lock.locked():
        raise RehearsalInProgressError
    async with _rehearsal_lock:
        rehearsal = _Rehearsal(client, privileges, confirmed, executor or build_rehearsal_executor(client))
        if step == "create":
            return await rehearsal.run_issue_resolution(
                rehearsal.create_issue_phase,
                completed="Demo issue created: IPM is dismounted and the issue stays active until it is resolved.",
            )
        if step == "resolve":
            return await rehearsal.run_issue_resolution(
                rehearsal.resolve_issue_phase,
                completed="Demo issue resolved: IPM is mounted again and the issue is gone.",
                stopped="the demo issue may still be active (IPM dismounted). Resolve it again, or mount IPM "
                        "from the Databases page.",
            )
        return await rehearsal.run_issue_resolution()
