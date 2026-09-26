"""One-time automatic Demo Activity at backend startup.

Off by default (Settings.auto_run_demo_activity). When on, app/main.py's
lifespan starts StartupDemoActivity in the background; it:

1. Waits for IRIS: fetches the session's privileges with the same
   get_caller_privileges() the manual POST /api/iris/demo/rehearsal route
   uses (a bounded number of attempts; if IRIS never answers, this startup
   gives up and a later startup tries again).
2. Reads the completion marker ^CommandCenterDemo("autoRun","completedAt")
   from the persistent USER database (Settings.iris_namespace) over IRIS's
   Native API — the same driver and lazy-connection pattern as
   app/observability/iris_trace_writer.py. If it is set, nothing runs. If
   it cannot be read, nothing runs either (running without knowing would
   break "only once").
3. Runs the EXISTING rehearsal — app/execution/demo_rehearsal.run_rehearsal,
   unchanged: the same executor, handlers, authorization, verification and
   restoration, and the same process-wide lock, so it can never overlap a
   manually triggered rehearsal (if one is running, this run is skipped).
4. Sets the marker ONLY when the rehearsal's status is "completed". A
   stopped or restore_failed rehearsal leaves it unset, so a later startup
   retries.

Confirmation: the rehearsal is run with confirmed=True. The explicit
confirmation is the operator's deliberate AUTO_RUN_DEMO_ACTIVITY=true
opt-in (default false); every operation still goes through the existing
authorization → execution → post-action verification framework. No other
operation is run.

The marker is a single global node (no table, class or new dependency);
it holds only an ISO-8601 UTC timestamp.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import HTTPException

from app.config import Settings
from app.dependencies import get_caller_privileges
from app.execution.demo_rehearsal import RehearsalInProgressError, run_rehearsal
from app.iris_client.client import IRISClient

logger = logging.getLogger(__name__)

MARKER_GLOBAL = "CommandCenterDemo"
MARKER_SUBSCRIPTS = ("autoRun", "completedAt")

READY_ATTEMPTS = 12
READY_DELAY_SECONDS = 5.0

AutoRunOutcome = Literal[
    "completed",          # rehearsal completed and the marker was set
    "completed_unmarked",  # rehearsal completed but the marker could not be written
    "already_completed",  # marker found — nothing ran
    "failed",             # rehearsal did not complete — marker left unset
    "busy",               # a manual rehearsal was running — skipped
    "iris_unavailable",   # IRIS (REST or marker) not reachable — nothing ran
]


class DemoAutoRunMarker:
    """The persistent completion marker. Blocking Native API calls — use
    only off the event loop. Each method raises on failure (after dropping
    the connection so the next call reconnects)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._iris: Any = None
        self._lock = threading.Lock()

    def _ensure_connected(self) -> None:
        if self._iris is not None:
            return

        import iris  # noqa: PLC0415 - deliberately lazy, like IRISTraceWriter

        hostname = urlsplit(self._settings.iris_base_url).hostname
        self._connection = iris.connect(
            hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )
        self._iris = iris.createIRIS(self._connection)

    def _reset(self) -> None:
        connection, self._connection, self._iris = self._connection, None, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - already failing; just discard it
                pass

    def is_completed_sync(self) -> bool:
        with self._lock:
            try:
                self._ensure_connected()
                return bool(self._iris.get(MARKER_GLOBAL, *MARKER_SUBSCRIPTS))
            except Exception:
                self._reset()
                raise

    def mark_completed_sync(self, completed_at: str) -> None:
        with self._lock:
            try:
                self._ensure_connected()
                self._iris.set(completed_at, MARKER_GLOBAL, *MARKER_SUBSCRIPTS)
            except Exception:
                self._reset()
                raise

    def close(self) -> None:
        with self._lock:
            self._reset()


class StartupDemoActivity:
    """Created and started by app/main.py's lifespan only when
    Settings.auto_run_demo_activity is True."""

    def __init__(
        self,
        client: IRISClient,
        marker: DemoAutoRunMarker,
        *,
        ready_attempts: int = READY_ATTEMPTS,
        ready_delay_seconds: float = READY_DELAY_SECONDS,
    ):
        self._client = client
        self._marker = marker
        self._ready_attempts = ready_attempts
        self._ready_delay_seconds = ready_delay_seconds
        self._rehearsal_started = False
        self._task: asyncio.Task[AutoRunOutcome] | None = None

    async def _wait_for_privileges(self) -> frozenset[str] | None:
        for attempt in range(self._ready_attempts):
            try:
                return await get_caller_privileges(self._client)
            except HTTPException:
                if attempt + 1 < self._ready_attempts:
                    await asyncio.sleep(self._ready_delay_seconds)
        return None

    async def run(self) -> AutoRunOutcome:
        """Never raises (except cancellation). Returns what happened."""
        privileges = await self._wait_for_privileges()
        if privileges is None:
            logger.warning("Automatic Demo Activity skipped: IRIS was not reachable; a later startup will retry.")
            return "iris_unavailable"

        loop = asyncio.get_running_loop()
        try:
            if await loop.run_in_executor(None, self._marker.is_completed_sync):
                logger.info("Automatic Demo Activity already completed earlier; not running it again.")
                return "already_completed"
        except Exception:  # noqa: BLE001 - unknown marker state: do not run
            logger.warning(
                "Automatic Demo Activity skipped: could not read its completion marker; a later startup will retry.",
                exc_info=True,
            )
            return "iris_unavailable"

        self._rehearsal_started = True
        try:
            result = await run_rehearsal(self._client, privileges, True)
        except RehearsalInProgressError:
            logger.warning("Automatic Demo Activity skipped: a manual Demo Activity is already running.")
            return "busy"
        except Exception:  # noqa: BLE001 - never crash the backend over the demo
            logger.warning("Automatic Demo Activity failed unexpectedly; a later startup will retry.", exc_info=True)
            return "failed"

        if result.status != "completed":
            logger.warning(
                "Automatic Demo Activity did not complete (%s: %s); not marked, a later startup will retry.",
                result.status,
                result.detail,
            )
            return "failed"

        completed_at = datetime.now(timezone.utc).isoformat()
        try:
            await loop.run_in_executor(None, self._marker.mark_completed_sync, completed_at)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Automatic Demo Activity completed, but its completion marker could not be written; "
                "it may run again on a later startup.",
                exc_info=True,
            )
            return "completed_unmarked"
        logger.info("Automatic Demo Activity completed and marked done (%s).", completed_at)
        return "completed"

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Called at shutdown. Still waiting for IRIS → cancelled. Once the
        rehearsal has started it is awaited instead, so its restoration
        steps are never interrupted."""
        if self._task is not None:
            if not self._rehearsal_started:
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await asyncio.get_running_loop().run_in_executor(None, self._marker.close)
