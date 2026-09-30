"""Gather bounded, read-only operational context from IRIS."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException
from pydantic import ValidationError

from app.iris_client.client import IRISClient
from app.models.copilot import (
    CopilotDatabaseContext,
    CopilotInfoContext,
    CopilotIssueContext,
    CopilotOperationalContext,
    CopilotProcessContext,
    CopilotTaskContext,
    CopilotWebAppContext,
)
from app.models.iris import (
    DatabaseEntry,
    IRISEnvelope,
    InfoResult,
    ProcessEntry,
    TaskDetail,
    TaskOverviewEntry,
    WebAppEntry,
)
from app.routes.iris import (
    get_databases,
    get_info,
    get_processes,
    get_task_detail,
    get_tasks_overview,
    get_web_apps,
)
from app.routes.issues import IssuesResponse, list_issues

_MAX_ITEMS_PER_SOURCE = 10
_MAX_TEXT_LENGTH = 160
_MAX_EXPLANATION_LENGTH = 320
_T = TypeVar("_T")


def _bounded_text(value: str | None, limit: int = _MAX_TEXT_LENGTH) -> str | None:
    return value[:limit] if value is not None else None


class CopilotContextService:
    """Collects a small snapshot using the existing read-only IRIS routes."""

    def __init__(self, client: IRISClient):
        self._client = client

    async def get_context(self, *, task_details: bool = True) -> CopilotOperationalContext:
        """`task_details` reads GET /v2/task for each task kept in the context
        (schedule, run-as). Without it those fields stay None and no detail
        call is made; state, errors and last/next run are still included."""
        unavailable: list[str] = []

        async def read_source(
            name: str,
            read: Callable[[IRISClient], Awaitable[IRISEnvelope[_T]]],
        ) -> _T | None:
            try:
                envelope = await read(self._client)
            except (HTTPException, ValidationError):
                unavailable.append(name)
                return None
            return envelope.result

        # The Issue Resolver's own detection (read-only); it returns its
        # response directly rather than an IRIS envelope.
        async def read_issues() -> IssuesResponse | None:
            try:
                return await list_issues(self._client)
            except (HTTPException, ValidationError):
                unavailable.append("issues")
                return None

        info, databases, processes, web_apps, tasks, issues = await asyncio.gather(
            read_source("info", get_info),
            read_source("databases", get_databases),
            read_source("processes", get_processes),
            read_source("web_apps", get_web_apps),
            read_source("tasks", get_tasks_overview),
            read_issues(),
        )
        shown_tasks = tasks[:_MAX_ITEMS_PER_SOURCE] if isinstance(tasks, list) else []
        details = (
            await self._task_details(shown_tasks) if task_details else [None] * len(shown_tasks)
        )

        return CopilotOperationalContext(
            info=self._info(info) if isinstance(info, InfoResult) else None,
            databases=self._databases(databases) if isinstance(databases, list) else [],
            databases_total=len(databases) if isinstance(databases, list) else None,
            processes=self._processes(processes) if isinstance(processes, list) else [],
            processes_total=len(processes) if isinstance(processes, list) else None,
            web_apps=self._web_apps(web_apps) if isinstance(web_apps, list) else [],
            web_apps_total=len(web_apps) if isinstance(web_apps, list) else None,
            tasks=self._tasks(tasks, details) if isinstance(tasks, list) else [],
            tasks_total=len(tasks) if isinstance(tasks, list) else None,
            issues=self._issues(issues) if issues is not None else [],
            issues_total=len(issues.issues) if issues is not None else None,
            issue_checks_unavailable=(
                [_bounded_text(kind) or "" for kind in issues.issue_checks_unavailable]
                if issues is not None else []
            ),
            unavailable=unavailable,
        )

    @staticmethod
    def _info(info: InfoResult) -> CopilotInfoContext:
        return CopilotInfoContext(
            product=_bounded_text(info.product),
            server_version=_bounded_text(info.serverVersion),
            system_mode=_bounded_text(info.systemMode),
            api_version=info.apiVersion,
        )

    @staticmethod
    def _databases(databases: list[DatabaseEntry]) -> list[CopilotDatabaseContext]:
        return [
            CopilotDatabaseContext(
                name=_bounded_text(item.Name) or "",
                status=_bounded_text(item.Status),
                directory=_bounded_text(item.Directory),
            )
            for item in databases[:_MAX_ITEMS_PER_SOURCE]
        ]

    @staticmethod
    def _processes(processes: list[ProcessEntry]) -> list[CopilotProcessContext]:
        return [
            CopilotProcessContext(
                pid=item.Pid,
                username=_bounded_text(item.Username),
                namespace=_bounded_text(item.Nspace),
                routine=_bounded_text(item.Routine),
                state=_bounded_text(item.State),
                cpu_time=item.CPUTime,
            )
            for item in processes[:_MAX_ITEMS_PER_SOURCE]
        ]

    @staticmethod
    def _web_apps(web_apps: list[WebAppEntry]) -> list[CopilotWebAppContext]:
        return [
            CopilotWebAppContext(
                name=_bounded_text(item.Name) or "",
                namespace=_bounded_text(item.Namespace),
                enabled=item.Enabled,
                app_type=_bounded_text(item.Type),
            )
            for item in web_apps[:_MAX_ITEMS_PER_SOURCE]
        ]

    async def _task_details(self, tasks: list[TaskOverviewEntry]) -> list[TaskDetail | None]:
        """GET /v2/task for each task kept in the context (schedule, run-as).
        A failed read leaves that task's detail fields None."""

        async def read(task_id: int) -> TaskDetail | None:
            try:
                return (await get_task_detail(task_id, self._client)).result
            except (HTTPException, ValidationError):
                return None

        return list(await asyncio.gather(*(read(task.Id) for task in tasks)))

    @staticmethod
    def _tasks(
        tasks: list[TaskOverviewEntry], details: list[TaskDetail | None]
    ) -> list[CopilotTaskContext]:
        contexts = []
        for item, detail in zip(tasks[:_MAX_ITEMS_PER_SOURCE], details):
            info = item.Info
            contexts.append(
                CopilotTaskContext(
                    id=item.Id,
                    name=_bounded_text(item.Name) or "",
                    namespace=_bounded_text(item.Namespace),
                    type=_bounded_text(item.Type),
                    state=item.State,
                    suspended=info.Suspended if info is not None else None,
                    error=_bounded_text(info.Error) if info is not None and info.Error else None,
                    last_finished=_bounded_text(item.LastFinished),
                    next_scheduled=_bounded_text(item.NextScheduled),
                    run_as_user=_bounded_text(detail.RunAsUser) if detail else None,
                    time_period=_bounded_text(detail.TimePeriod) if detail else None,
                    time_period_every=_bounded_text(str(detail.TimePeriodEvery)) if detail else None,
                    daily_frequency=_bounded_text(detail.DailyFrequency) if detail else None,
                    daily_start_time=_bounded_text(detail.DailyStartTime) if detail else None,
                    suspend_on_error=detail.SuspendOnError if detail else None,
                )
            )
        return contexts

    @staticmethod
    def _issues(response: IssuesResponse) -> list[CopilotIssueContext]:
        issues = []
        for item in response.issues[:_MAX_ITEMS_PER_SOURCE]:
            resolution = response.resolutions.get(item.kind)
            issues.append(
                CopilotIssueContext(
                    kind=_bounded_text(item.kind) or "",
                    title=_bounded_text(resolution.title) if resolution else None,
                    severity=resolution.severity.value if resolution else None,
                    resource_type=_bounded_text(item.resource.type) or "",
                    resource_name=_bounded_text(item.resource.display_name) or "",
                    readiness=item.readiness.value,
                    explanation=_bounded_text(
                        getattr(item, "explanation", None), _MAX_EXPLANATION_LENGTH
                    ),
                    resolvable=resolution is not None and resolution.resolvable,
                    recommended_operation=resolution.operation if resolution else None,
                )
            )
        return issues
