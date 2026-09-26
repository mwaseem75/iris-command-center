"""Tests for the one-time automatic Demo Activity (app/execution/demo_autorun.py)
and its startup wiring. The rehearsal itself is the real, unchanged
app/execution/demo_rehearsal.run_rehearsal running against the same FakeIris
the manual Demo Activity tests use; the completion marker is a fake. No test
contacts IRIS."""

import asyncio
from datetime import datetime
from typing import Any

import pytest

from app.config import Settings, get_settings
from app.execution import demo_autorun, demo_rehearsal
from app.execution.demo_autorun import (
    MARKER_GLOBAL,
    MARKER_SUBSCRIPTS,
    DemoAutoRunMarker,
    StartupDemoActivity,
)
from app.iris_client.exceptions import IRISConnectionError
from app.observability import store
from tests.test_demo_rehearsal import FakeIris


class FakeMarker:
    def __init__(self, *, completed: bool = False, read_error: bool = False, write_error: bool = False):
        self.completed_at: str | None = "2026-01-01T00:00:00+00:00" if completed else None
        self.read_error = read_error
        self.write_error = write_error
        self.reads = 0
        self.writes: list[str] = []
        self.closed = False

    def is_completed_sync(self) -> bool:
        self.reads += 1
        if self.read_error:
            raise RuntimeError("marker unreachable")
        return self.completed_at is not None

    def mark_completed_sync(self, completed_at: str) -> None:
        self.writes.append(completed_at)
        if self.write_error:
            raise RuntimeError("marker unwritable")
        self.completed_at = completed_at

    def close(self) -> None:
        self.closed = True


class UnreachableUntil(FakeIris):
    """/info fails (as an unreachable IRIS) for the first `failures` calls."""

    def __init__(self, failures: int):
        super().__init__()
        self.info_failures_left = failures
        self.info_calls = 0

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/info":
            self.info_calls += 1
            if self.info_failures_left > 0:
                self.info_failures_left -= 1
                raise IRISConnectionError("iris.invalid.test")
        return await super().get(path, params)


@pytest.fixture(autouse=True)
def _isolation(monkeypatch: pytest.MonkeyPatch):
    store.clear_traces()
    monkeypatch.setattr(demo_rehearsal, "WEB_APP_VERIFY_RETRY_DELAYS", ())
    yield
    store.clear_traces()


def _autorun(client: Any, marker: FakeMarker, **kwargs: Any) -> StartupDemoActivity:
    return StartupDemoActivity(client, marker, ready_attempts=3, ready_delay_seconds=0, **kwargs)


# --- first successful run ---


@pytest.mark.asyncio
async def test_first_run_executes_the_existing_rehearsal_and_marks_it_complete() -> None:
    fake, marker = FakeIris(), FakeMarker()

    assert await _autorun(fake, marker).run() == "completed"

    # The real rehearsal ran: journal toggled + restored, web app description changed + restored.
    assert [p[1] for p in fake.puts] == [
        {"PurgeArchived": False},
        {"PurgeArchived": True},
        {"Description": "User app [IRIS Command Center rehearsal]"},
        {"Description": "User app"},
    ]
    assert fake.purge_archived is True and fake.web_apps["/csp/user"]["Description"] == "User app"
    assert fake.posts == []  # nothing beyond the rehearsal's own operations
    # ...through the executor, which recorded a trace for every step.
    assert {t.operation_name for t in store.list_traces()} == {
        "journal.update_purge_archived", "web_app.update_description", "database.mount", "task.run_now",
    }
    # Marker set once, only after completion, with a UTC timestamp.
    assert len(marker.writes) == 1
    assert datetime.fromisoformat(marker.writes[0]).utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_rehearsal_is_run_with_the_sessions_privileges_and_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[frozenset[str], bool]] = []
    real = demo_autorun.run_rehearsal

    async def spy(client: Any, privileges: frozenset[str], confirmed: bool, **kwargs: Any):
        calls.append((privileges, confirmed))
        return await real(client, privileges, confirmed, **kwargs)

    monkeypatch.setattr(demo_autorun, "run_rehearsal", spy)
    await _autorun(FakeIris(), FakeMarker()).run()

    assert calls == [(frozenset({"Manage", "Journal", "Secure", "Operate", "Task"}), True)]


# --- already completed ---


@pytest.mark.asyncio
async def test_already_completed_runs_nothing() -> None:
    fake, marker = FakeIris(), FakeMarker(completed=True)

    assert await _autorun(fake, marker).run() == "already_completed"

    assert fake.puts == [] and store.list_traces() == [] and marker.writes == []


# --- failure and retry ---


@pytest.mark.asyncio
async def test_failed_rehearsal_is_not_marked_and_a_later_startup_retries() -> None:
    fake, marker = FakeIris(), FakeMarker()
    fake.journal_put_error = 500

    assert await _autorun(fake, marker).run() == "failed"
    assert marker.writes == [] and marker.completed_at is None

    fake.journal_put_error = None  # a later startup, IRIS healthy again
    assert await _autorun(fake, marker).run() == "completed"
    assert len(marker.writes) == 1


@pytest.mark.asyncio
async def test_restore_failure_is_not_marked() -> None:
    fake, marker = FakeIris(), FakeMarker()
    fake.web_app_put_errors = [None, 500]  # change works, restore fails

    assert await _autorun(fake, marker).run() == "failed"
    assert marker.writes == []


@pytest.mark.asyncio
async def test_unreachable_iris_runs_nothing_and_leaves_the_marker_untouched() -> None:
    fake, marker = UnreachableUntil(failures=99), FakeMarker()

    assert await _autorun(fake, marker).run() == "iris_unavailable"

    assert fake.info_calls == 3  # the bounded readiness attempts
    assert marker.reads == 0 and marker.writes == [] and fake.puts == []


@pytest.mark.asyncio
async def test_waits_for_iris_to_become_ready() -> None:
    fake, marker = UnreachableUntil(failures=2), FakeMarker()

    assert await _autorun(fake, marker).run() == "completed"
    assert fake.info_calls >= 3


@pytest.mark.asyncio
async def test_unreadable_marker_runs_nothing() -> None:
    fake, marker = FakeIris(), FakeMarker(read_error=True)

    assert await _autorun(fake, marker).run() == "iris_unavailable"
    assert fake.puts == [] and marker.writes == []


@pytest.mark.asyncio
async def test_unwritable_marker_is_reported_after_a_completed_rehearsal() -> None:
    fake, marker = FakeIris(), FakeMarker(write_error=True)

    assert await _autorun(fake, marker).run() == "completed_unmarked"
    assert marker.completed_at is None


# --- concurrency with the manual Demo Activity ---


@pytest.mark.asyncio
async def test_skips_while_a_manual_rehearsal_is_running() -> None:
    fake, marker = FakeIris(), FakeMarker()

    async with demo_rehearsal._rehearsal_lock:  # a manual rehearsal in progress
        assert await _autorun(fake, marker).run() == "busy"

    assert fake.puts == [] and marker.writes == []


class GatedIris(FakeIris):
    """Pauses the rehearsal at its first write until released."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def put(self, path: str, json: Any = None, params: Any = None) -> dict[str, Any]:
        await self.gate.wait()
        return await super().put(path, json, params)


@pytest.mark.asyncio
async def test_a_manual_rehearsal_is_refused_while_the_automatic_one_runs() -> None:
    fake, marker = GatedIris(), FakeMarker()
    task = asyncio.create_task(_autorun(fake, marker).run())
    while not demo_rehearsal._rehearsal_lock.locked():
        await asyncio.sleep(0)

    with pytest.raises(demo_rehearsal.RehearsalInProgressError):
        await demo_rehearsal.run_rehearsal(fake, frozenset({"Journal"}), True)

    fake.gate.set()
    assert await task == "completed"
    assert len(marker.writes) == 1


# --- lifecycle ---


@pytest.mark.asyncio
async def test_stop_cancels_while_still_waiting_for_iris() -> None:
    fake, marker = UnreachableUntil(failures=99), FakeMarker()
    autorun = StartupDemoActivity(fake, marker, ready_attempts=1000, ready_delay_seconds=60)
    autorun.start()
    await asyncio.sleep(0)

    await asyncio.wait_for(autorun.stop(), timeout=2)

    assert autorun._task.cancelled() and marker.closed and marker.writes == []


@pytest.mark.asyncio
async def test_stop_waits_for_a_started_rehearsal_to_finish() -> None:
    fake, marker = GatedIris(), FakeMarker()
    autorun = _autorun(fake, marker)
    autorun.start()
    while not demo_rehearsal._rehearsal_lock.locked():
        await asyncio.sleep(0)

    stopping = asyncio.create_task(autorun.stop())
    await asyncio.sleep(0.01)
    assert not stopping.done()  # never interrupts a running rehearsal
    fake.gate.set()
    await asyncio.wait_for(stopping, timeout=2)

    assert autorun._task.result() == "completed"
    assert fake.purge_archived is True and fake.web_apps["/csp/user"]["Description"] == "User app"


# --- startup wiring ---


class _SpyAutorun:
    instances: list["_SpyAutorun"] = []

    def __init__(self, client: Any, marker: Any):
        self.marker = marker
        self.started = self.stopped = False
        _SpyAutorun.instances.append(self)

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def lifespan_env(monkeypatch: pytest.MonkeyPatch):
    import app.main as main_module

    _SpyAutorun.instances = []
    monkeypatch.setattr(main_module, "StartupDemoActivity", _SpyAutorun)
    monkeypatch.setenv("ENABLE_KNOWLEDGE_SEARCH", "false")
    monkeypatch.setenv("PERSIST_TRACES_TO_IRIS", "false")
    get_settings.cache_clear()
    yield main_module, monkeypatch
    get_settings.cache_clear()


def test_feature_is_disabled_by_default() -> None:
    assert Settings.model_fields["auto_run_demo_activity"].default is False


@pytest.mark.asyncio
async def test_disabled_startup_never_creates_the_automatic_run(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("AUTO_RUN_DEMO_ACTIVITY", "false")

    async with main_module.lifespan(main_module.app):
        pass

    assert _SpyAutorun.instances == []


@pytest.mark.asyncio
async def test_enabled_startup_starts_in_background_and_stops_at_shutdown(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("AUTO_RUN_DEMO_ACTIVITY", "true")

    async with main_module.lifespan(main_module.app):
        (autorun,) = _SpyAutorun.instances
        assert autorun.started and not autorun.stopped
        assert isinstance(autorun.marker, DemoAutoRunMarker)

    assert autorun.stopped


# --- the persistent marker ---


class _FakeNative:
    def __init__(self) -> None:
        self.nodes: dict[tuple, str] = {}
        self.fail = False

    def get(self, *subscripts: Any) -> str | None:
        if self.fail:
            raise RuntimeError("connection lost")
        return self.nodes.get(subscripts)

    def set(self, value: str, *subscripts: Any) -> None:
        if self.fail:
            raise RuntimeError("connection lost")
        self.nodes[subscripts] = value


def test_marker_reads_and_writes_one_global_node() -> None:
    marker = DemoAutoRunMarker(get_settings())
    native = marker._iris = _FakeNative()

    assert marker.is_completed_sync() is False
    marker.mark_completed_sync("2026-09-26T10:00:00+00:00")

    assert native.nodes == {(MARKER_GLOBAL, *MARKER_SUBSCRIPTS): "2026-09-26T10:00:00+00:00"}
    assert (MARKER_GLOBAL, *MARKER_SUBSCRIPTS) == ("CommandCenterDemo", "autoRun", "completedAt")
    assert marker.is_completed_sync() is True


def test_marker_failure_raises_and_drops_the_connection() -> None:
    marker = DemoAutoRunMarker(get_settings())
    native = marker._iris = _FakeNative()
    native.fail = True

    with pytest.raises(RuntimeError):
        marker.is_completed_sync()
    assert marker._iris is None
