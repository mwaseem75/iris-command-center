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
    TaskEntry,
    WebAppEntry,
)
from app.routes.iris import get_databases, get_info, get_processes, get_tasks, get_web_apps
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

    async def get_context(self) -> CopilotOperationalContext:
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
            read_source("tasks", get_tasks),
            read_issues(),
        )

        return CopilotOperationalContext(
            info=self._info(info) if isinstance(info, InfoResult) else None,
            databases=self._databases(databases) if isinstance(databases, list) else [],
            databases_total=len(databases) if isinstance(databases, list) else None,
            processes=self._processes(processes) if isinstance(processes, list) else [],
            processes_total=len(processes) if isinstance(processes, list) else None,
            web_apps=self._web_apps(web_apps) if isinstance(web_apps, list) else [],
            web_apps_total=len(web_apps) if isinstance(web_apps, list) else None,
            tasks=self._tasks(tasks) if isinstance(tasks, list) else [],
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

    @staticmethod
    def _tasks(tasks: list[TaskEntry]) -> list[CopilotTaskContext]:
        return [
            CopilotTaskContext(
                name=_bounded_text(item.Name) or "",
                namespace=_bounded_text(item.Namespace),
                suspended=item.Suspended,
                next_scheduled=_bounded_text(item.NextScheduled),
            )
            for item in tasks[:_MAX_ITEMS_PER_SOURCE]
        ]

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
