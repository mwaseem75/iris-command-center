"""Handler for task.run_now (POST /v2/task/run?id=..., %Admin_Task:U).

Sends {"RunNow": true} and nothing else; scheduling for a later time
isn't offered. Both dry_run() and execute() validate against live IRIS
data; only execute() sends the POST.

Notes from reading %Api.Admin.Endpoints.Task.CRUD on 2026.2:
- An unknown id gives 404; otherwise it calls %SYS.Task.RunNow(id).
- IRIS doesn't check whether the task is already running, so we do.
- The Task Manager only polls every 60 seconds, so the run can start up
  to a minute later.

Only "User" tasks can be run. System and Maintenance tasks belong to IRIS
(purges, journal switches, integrity checks, tasks that send data to
InterSystems...), so they're refused. On a stock instance every task is a
System task, so this is always refused there. We also refuse unknown ids,
suspended tasks, tasks already running (Status -1), and any request while
the Task Manager isn't "Running".

Because of the 60 s polling there's no instant "it ran" signal. verify()
re-reads /v2/task/info a few times and reports VERIFIED only if it sees
Status -1 or a changed LastSchedule, LastStarted or NextScheduled.
"""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError, field_validator

from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISClientError, IRISResponseError

_RUN_PATH = "/v2/task/run"
_TASK_PATH = "/v2/task"
_INFO_PATH = "/v2/task/info"
_MANAGER_PATH = "/v2/task/manager"

_RUNNABLE_TYPE = "User"
_RUNNING_STATUS = "-1"  # Status is -1 while the job is running
_OBSERVED_FIELDS = ("Status", "LastSchedule", "LastStarted", "NextScheduled")

# One immediate check, then three growing delays.
_VERIFY_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)


class TaskRunNowParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    Id: StrictInt

    @field_validator("Id")
    @classmethod
    def _validate_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Id must be a positive task id.")
        return value


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


def _snapshot(info: dict[str, Any]) -> dict[str, str | None]:
    """The /v2/task/info fields a run can change, as strings (or None)."""
    return {field: info.get(field) if isinstance(info.get(field), str) else None for field in _OBSERVED_FIELDS}


class TaskRunNowHandler(OperationHandler):
    """Takes an IRISClient so tests can pass a fake."""

    def __init__(
        self,
        iris_client: IRISClient,
        *,
        verify_retry_delays_seconds: tuple[float, ...] = _VERIFY_RETRY_DELAYS_SECONDS,
    ):
        self._iris_client = iris_client
        self._verify_retry_delays_seconds = verify_retry_delays_seconds

    async def _result(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """A read-only GET's `result` object; None when IRIS answers 404."""
        try:
            body = await (self._iris_client.get(path, params=params) if params else self._iris_client.get(path))
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return None
            raise
        result = body.get("result") if isinstance(body, dict) else None
        return result if isinstance(result, dict) else {}

    async def _validate(
        self, request: OperationRequest, context: ExecutionContext
    ) -> tuple[TaskRunNowParameters, dict[str, Any]] | tuple[None, HandlerExecutionResult]:
        """All checks before the run, in order: request, existence, task type,
        suspended, already running, Task Manager status. Read-only.
        """
        try:
            params = TaskRunNowParameters.model_validate(request.parameters)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field = ".".join(str(part) for part in first_error["loc"]) or "request"
            return None, _failure(f"Invalid task.run_now request ({field}): {first_error['msg']}")

        info = await self._result(_INFO_PATH, {"id": params.Id})
        detail = await self._result(_TASK_PATH, {"id": params.Id}) if info is not None else None
        if info is None or detail is None:
            return None, _failure(f"IRIS reports no task with id {params.Id} — nothing was run.", id=params.Id)

        name = detail.get("Name") if isinstance(detail.get("Name"), str) else None
        label = f"task {params.Id}" + (f" ({name!r})" if name else "")
        task_type = info.get("Type")
        if task_type != _RUNNABLE_TYPE:
            return None, _failure(
                f"{label} is a {task_type!r} task and is protected: only User tasks can be run from the "
                "Command Center. IRIS's System and Maintenance tasks include irreversible purges, journal "
                "switches, heavy scans and tasks that send data to InterSystems.",
                id=params.Id,
                name=name,
                type=task_type,
                protected=True,
            )

        if info.get("Suspended") is not False:
            reason = "is suspended" if info.get("Suspended") is True else "has an unknown suspended state"
            return None, _failure(f"{label} {reason} — resume it in IRIS first. Nothing was run.", id=params.Id, name=name)

        if info.get("Status") == _RUNNING_STATUS:
            return None, _failure(
                f"{label} is already running (Status -1) — nothing to do.", id=params.Id, name=name, no_change=True
            )

        manager = await self._result(_MANAGER_PATH)
        manager_status = manager.get("Status") if isinstance(manager, dict) else None
        if manager_status != "Running":
            return None, _failure(
                f"The IRIS Task Manager is {manager_status or 'in an unknown state'!s}, not Running, so "
                f"{label} would not be picked up. Nothing was run.",
                id=params.Id,
                name=name,
                task_manager=manager_status,
            )

        return params, {"name": name, "type": task_type, "before": _snapshot(info)}

    def _change_data(self, params: TaskRunNowParameters, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": params.Id,
            "name": state["name"],
            "type": state["type"],
            "before": state["before"],
            "request": {"method": "POST", "path": _RUN_PATH, "query": {"id": params.Id}, "body": {"RunNow": True}},
        }

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        """Validate and read from IRIS only; never sends the POST."""
        params, result = await self._validate(request, context)
        if params is None:
            return result
        label = f"task {params.Id}" + (f" ({result['name']!r})" if result["name"] else "")
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=(
                f"Dry run: {label} is a User task, not suspended and not running, and the Task Manager is "
                'Running. It would be scheduled to run now via POST /v2/task/run with the body {"RunNow": true} '
                "only — the Task Manager polls every 60 seconds, so it may start up to a minute later. "
                "No request was sent."
            ),
            data=self._change_data(params, result),
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        params, result = await self._validate(request, context)
        if params is None:
            return result

        try:
            await self._iris_client.post(_RUN_PATH, json={"RunNow": True}, params={"id": params.Id})
        except IRISResponseError as exc:
            if exc.status_code == 403:
                return _failure(
                    f"IRIS denied running task {params.Id} (HTTP 403) — it requires %Admin_Task. Nothing was run.",
                    id=params.Id,
                )
            if exc.status_code == 404:
                return _failure(f"IRIS reports no task with id {params.Id} (HTTP 404). Nothing was run.", id=params.Id)
            if exc.status_code == 400:
                return _failure(f"IRIS rejected the run of task {params.Id} as invalid (HTTP 400). Nothing was run.", id=params.Id)
            raise

        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Asked IRIS to run task {params.Id} now via POST /v2/task/run.",
            data=self._change_data(params, result),
        )

    async def verify(
        self,
        request: OperationRequest,
        context: ExecutionContext,
        execution_result: HandlerExecutionResult,
    ) -> PostActionVerificationResult:
        """Re-read /v2/task/info (with retries). VERIFIED only on a visible run
        signal: Status -1 or a changed LastSchedule / LastStarted / NextScheduled.
        """
        data = execution_result.data
        task_id = data.get("id")
        before = data.get("before") or {}

        last_error: str | None = None
        attempts_made = 0
        for delay_before_this_attempt in (0.0, *self._verify_retry_delays_seconds):
            if delay_before_this_attempt:
                await asyncio.sleep(delay_before_this_attempt)
            attempts_made += 1
            # The run was already requested, so a failed read here is a
            # VERIFICATION_FAILED result, not an exception.
            try:
                info = await self._result(_INFO_PATH, {"id": task_id})
            except IRISClientError as exc:
                last_error = f"read error ({exc.__class__.__name__})"
                continue
            if info is None:
                last_error = "task not found"
                continue
            last_error = None
            after = _snapshot(info)
            if after.get("Status") == _RUNNING_STATUS:
                return PostActionVerificationResult(
                    status=PostActionVerificationStatus.VERIFIED,
                    detail=f"Confirmed via GET /v2/task/info: task {task_id} is running (Status -1).",
                )
            changed = [field for field in _OBSERVED_FIELDS if field != "Status" and after.get(field) != before.get(field)]
            if changed:
                changes = ", ".join(f"{field} {before.get(field)!r} → {after.get(field)!r}" for field in changed)
                return PostActionVerificationResult(
                    status=PostActionVerificationStatus.VERIFIED,
                    detail=f"Confirmed via GET /v2/task/info: task {task_id} was picked up ({changes}).",
                )

        attempted_delays = ", ".join(f"{d:g}s" for d in self._verify_retry_delays_seconds)
        reason = f"the last read failed ({last_error})" if last_error else "no run signal was observed"
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFICATION_FAILED,
            detail=(
                f"IRIS accepted the run request for task {task_id}, but {reason} in GET /v2/task/info after "
                f"{attempts_made} attempts (retried with delays of {attempted_delays}). The Task Manager polls "
                "every 60 seconds — check the task's LastStarted / history again shortly."
            ),
        )
