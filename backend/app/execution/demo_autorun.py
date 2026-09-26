"""Runs the Demo Activity once, automatically, when the backend starts.

Off by default; enable with AUTO_RUN_DEMO_ACTIVITY=true. On startup,
app/main.py starts StartupDemoActivity in the background, which:

1. Waits for IRIS (fetching the session privileges the same way the
   manual /api/iris/demo/rehearsal route does). Gives up after a few
   tries; the next startup will try again.
2. Reads ^CommandCenterDemo("autoRun","completedAt") in the USER
   namespace over the Native API. If it's set, or can't be read, nothing
   runs.
3. Runs demo_rehearsal.run_rehearsal as-is, with the same lock, so it
   never overlaps a manual run (if one is running this is skipped).
4. Sets the marker only if the rehearsal finished with "completed", so a
   failed run is retried next startup.

The rehearsal runs with confirmed=True: turning on AUTO_RUN_DEMO_ACTIVITY
is the confirmation. Authorization and verification still apply.

The marker is a single global holding an ISO-8601 UTC timestamp.
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
    "completed",  # ran and marker set
    "completed_unmarked",  # ran but couldn't write the marker
    "already_completed",  # marker already set, nothing ran
    "failed",  # rehearsal didn't complete, marker not set
    "busy",  # manual rehearsal was running, skipped
    "iris_unavailable",  # IRIS not reachable, nothing ran
]


class DemoAutoRunMarker:
    """The completion marker. These are blocking Native API calls, so keep them
    off the event loop. On failure they drop the connection (so the next call
    reconnects) and raise.
    """

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
    """Started by app/main.py only when auto_run_demo_activity is on."""

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
        """Never raises (except on cancellation). Returns what happened."""
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
        """Called at shutdown. If we're still waiting for IRIS, cancel. If the
        rehearsal already started, wait for it so its restore steps finish.
        """
        if self._task is not None:
            if not self._rehearsal_started:
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await asyncio.get_running_loop().run_in_executor(None, self._marker.close)
