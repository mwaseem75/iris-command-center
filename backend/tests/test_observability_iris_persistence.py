"""Tests for the optional IRIS trace persistence (iris_trace_writer.py and
the hook in store.record_trace()). The IRIS connection is always faked.

The main points: with no persister, record_trace() behaves as before; with
one, a failing write never breaks record_trace() or the in-memory store.
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.observability import store
from app.observability.iris_trace_writer import IRISTraceWriter
from app.observability.models import ExecutionTrace


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    # The persister and pending tasks are module globals, so reset them
    # before and after each test.
    store.clear_traces()
    store.set_trace_persister(None)
    yield
    store.clear_traces()
    store.set_trace_persister(None)


def _trace(name: str = "demo.op") -> ExecutionTrace:
    return ExecutionTrace(operation_name=name)


class _FakePersister:
    """Records the traces it's given, or raises if told to."""

    def __init__(self, *, raises: bool = False):
        self.calls: list[ExecutionTrace] = []
        self._raises = raises

    def persist_sync(self, trace: ExecutionTrace) -> None:
        self.calls.append(trace)
        if self._raises:
            raise RuntimeError("simulated IRIS persistence failure")


async def _drain_pending_persist_tasks() -> None:
    """Wait for the background persist tasks instead of sleeping."""
    while store._pending_persist_tasks:
        await asyncio.gather(*store._pending_persist_tasks, return_exceptions=True)


# --- store.record_trace() with a persister ---


@pytest.mark.asyncio
async def test_record_trace_with_no_persister_never_schedules_background_work() -> None:
    store.record_trace(_trace())

    assert store._pending_persist_tasks == set()
    assert store.list_traces()[0].operation_name == "demo.op"


@pytest.mark.asyncio
async def test_record_trace_forwards_to_a_registered_persister() -> None:
    persister = _FakePersister()
    store.set_trace_persister(persister)

    trace = _trace("journal.update_purge_archived")
    store.record_trace(trace)
    await _drain_pending_persist_tasks()

    assert persister.calls == [trace]
    # The in-memory store is fine either way.
    assert store.list_traces() == [trace]


@pytest.mark.asyncio
async def test_record_trace_never_raises_when_persister_raises() -> None:
    persister = _FakePersister(raises=True)
    store.set_trace_persister(persister)

    store.record_trace(_trace())  # must not raise synchronously
    await _drain_pending_persist_tasks()  # and neither does the background task

    assert persister.calls  # it was still attempted


def test_record_trace_with_persister_but_no_running_loop_does_not_raise() -> None:
    # Plain sync test, so no running event loop (same as the sync tests in
    # test_observability.py).
    store.set_trace_persister(_FakePersister())

    store.record_trace(_trace())  # must not raise

    assert store.list_traces()[0].operation_name == "demo.op"


@pytest.mark.asyncio
async def test_set_trace_persister_none_disables_background_persistence_again() -> None:
    persister = _FakePersister()
    store.set_trace_persister(persister)
    store.set_trace_persister(None)

    store.record_trace(_trace())
    await _drain_pending_persist_tasks()

    assert persister.calls == []


# --- IRISTraceWriter: sequence numbers, eviction, failures ---


class _FakeIrisNative:
    """Fake for what iris.createIRIS() returns (just get/set/kill)."""

    def __init__(self) -> None:
        self.values: dict[tuple, str] = {}
        self.calls: list[tuple] = []

    def get(self, *args: Any) -> str | None:
        self.calls.append(("get", args))
        return self.values.get(args)

    def set(self, value: str, *args: Any) -> None:
        self.calls.append(("set", value, args))
        self.values[args] = value

    def kill(self, *args: Any) -> None:
        self.calls.append(("kill", args))
        self.values.pop(args, None)


def _connected_writer(fake_iris: _FakeIrisNative) -> IRISTraceWriter:
    writer = IRISTraceWriter.__new__(IRISTraceWriter)  # skip __init__ (it needs Settings)
    writer._settings = None
    writer._connection = MagicMock()
    writer._iris = fake_iris
    return writer


def test_persist_sync_writes_the_first_trace_at_sequence_one() -> None:
    fake_iris = _FakeIrisNative()
    writer = _connected_writer(fake_iris)

    writer.persist_sync(_trace("first"))

    assert fake_iris.values[("CommandCenterTrace", "seq")] == "1"
    assert "first" in fake_iris.values[("CommandCenterTrace", "trace", 1)]
    assert not any(call[0] == "kill" for call in fake_iris.calls)


def test_persist_sync_evicts_the_oldest_trace_once_over_the_cap() -> None:
    fake_iris = _FakeIrisNative()
    fake_iris.values[("CommandCenterTrace", "seq")] = "200"
    writer = _connected_writer(fake_iris)

    writer.persist_sync(_trace("the-201st"))

    assert fake_iris.values[("CommandCenterTrace", "seq")] == "201"
    assert ("CommandCenterTrace", "trace", 201) in fake_iris.values
    # seq 1 was evicted to keep the cap at 200.
    assert ("kill", ("CommandCenterTrace", "trace", 1)) in fake_iris.calls


def test_persist_sync_swallows_connection_failures() -> None:
    writer = IRISTraceWriter.__new__(IRISTraceWriter)
    writer._settings = None
    writer._connection = None
    writer._iris = None
    writer._ensure_connected = MagicMock(side_effect=ConnectionError("no route to host"))  # type: ignore[method-assign]

    writer.persist_sync(_trace())  # must not raise


def test_close_is_a_no_op_when_never_connected() -> None:
    writer = IRISTraceWriter.__new__(IRISTraceWriter)
    writer._settings = None
    writer._connection = None
    writer._iris = None

    writer.close()  # must not raise


def test_close_swallows_errors_from_the_underlying_connection() -> None:
    writer = IRISTraceWriter.__new__(IRISTraceWriter)
    writer._settings = None
    writer._connection = MagicMock()
    writer._connection.close.side_effect = OSError("already closed")
    writer._iris = MagicMock()

    writer.close()  # must not raise

    assert writer._connection is None
    assert writer._iris is None


# --- Startup: load_recent_sync() + hydrate_traces() ---


def _persisted(fake_iris: _FakeIrisNative, names: list[str]) -> list[ExecutionTrace]:
    """Write `names` (oldest first) with the real persist_sync()."""
    writer = _connected_writer(fake_iris)
    traces = [_trace(name) for name in names]
    for trace in traces:
        writer.persist_sync(trace)
    return traces


def test_load_recent_sync_returns_persisted_traces_newest_first() -> None:
    fake_iris = _FakeIrisNative()
    written = _persisted(fake_iris, ["one", "two", "three"])

    loaded = _connected_writer(fake_iris).load_recent_sync()

    assert [t.operation_name for t in loaded] == ["three", "two", "one"]
    assert loaded[0] == written[2]  # round trip keeps the same schema


def test_load_recent_sync_on_an_empty_global_returns_nothing() -> None:
    assert _connected_writer(_FakeIrisNative()).load_recent_sync() == []


def test_load_recent_sync_reads_only_the_surviving_capped_range() -> None:
    fake_iris = _FakeIrisNative()
    _persisted(fake_iris, [f"op-{i}" for i in range(1, 206)])  # 205 writes, 5 evicted

    loaded = _connected_writer(fake_iris).load_recent_sync()

    assert len(loaded) == 200
    assert loaded[0].operation_name == "op-205"
    assert loaded[-1].operation_name == "op-6"
    # Never reads an evicted or unwritten entry.
    trace_gets = [
        call[1][2]
        for call in fake_iris.calls
        if call[0] == "get" and call[1][:2] == ("CommandCenterTrace", "trace")
    ]
    assert min(trace_gets) == 6


def test_load_recent_sync_skips_missing_and_unparsable_entries() -> None:
    fake_iris = _FakeIrisNative()
    _persisted(fake_iris, ["one", "two", "three"])
    fake_iris.values.pop(("CommandCenterTrace", "trace", 2))
    fake_iris.values[("CommandCenterTrace", "trace", 1)] = "{not json"

    loaded = _connected_writer(fake_iris).load_recent_sync()

    assert [t.operation_name for t in loaded] == ["three"]


def test_load_recent_sync_returns_empty_when_iris_is_unavailable() -> None:
    writer = IRISTraceWriter.__new__(IRISTraceWriter)
    writer._settings = None
    writer._connection = None
    writer._iris = None
    writer._ensure_connected = MagicMock(side_effect=ConnectionError("no route to host"))  # type: ignore[method-assign]

    assert writer.load_recent_sync() == []  # must not raise


def test_hydrate_traces_fills_the_store_without_re_persisting() -> None:
    persister = _FakePersister()
    store.set_trace_persister(persister)
    loaded = [_trace("newer"), _trace("older")]

    assert store.hydrate_traces(loaded) == 2

    assert [t.operation_name for t in store.list_traces()] == ["newer", "older"]
    assert persister.calls == []
    assert store._pending_persist_tasks == set()


def test_hydrate_traces_keeps_live_traces_first_and_skips_duplicates() -> None:
    live = _trace("recorded-this-process")
    store.record_trace(live)

    added = store.hydrate_traces([live, _trace("persisted")])

    assert added == 1
    assert [t.operation_name for t in store.list_traces()] == ["recorded-this-process", "persisted"]


def test_hydrate_traces_preserves_the_store_cap_and_never_evicts_newer_traces() -> None:
    live = _trace("live")
    store.record_trace(live)

    added = store.hydrate_traces([_trace(f"persisted-{i}") for i in range(250)])

    traces = store.list_traces()
    assert added == store._MAX_TRACES - 1
    assert len(traces) == store._MAX_TRACES
    assert traces[0] is live


def test_hydrate_traces_with_nothing_persisted_leaves_the_store_empty() -> None:
    assert store.hydrate_traces([]) == 0
    assert store.list_traces() == []


# --- app/main.py lifespan ---


class _FakeWriter:
    """Replaces IRISTraceWriter in the real lifespan."""

    instances: list["_FakeWriter"] = []
    to_load: list[ExecutionTrace] = []

    def __init__(self, settings: Any) -> None:
        self.closed = False
        _FakeWriter.instances.append(self)

    def load_recent_sync(self) -> list[ExecutionTrace]:
        return list(_FakeWriter.to_load)

    def persist_sync(self, trace: ExecutionTrace) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def _lifespan_env(monkeypatch: pytest.MonkeyPatch):
    import app.main as main_module
    from app.config import get_settings

    _FakeWriter.instances = []
    _FakeWriter.to_load = []
    monkeypatch.setattr(main_module, "IRISTraceWriter", _FakeWriter)
    get_settings.cache_clear()
    yield main_module, monkeypatch
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lifespan_hydrates_persisted_traces_when_enabled(_lifespan_env) -> None:
    main_module, monkeypatch = _lifespan_env
    monkeypatch.setenv("PERSIST_TRACES_TO_IRIS", "true")
    _FakeWriter.to_load = [_trace("before-restart-2"), _trace("before-restart-1")]

    async with main_module.lifespan(main_module.app):
        assert [t.operation_name for t in store.list_traces()] == [
            "before-restart-2",
            "before-restart-1",
        ]
        assert store._persister is _FakeWriter.instances[0]

    assert _FakeWriter.instances[0].closed


@pytest.mark.asyncio
async def test_lifespan_starts_empty_when_nothing_is_persisted(_lifespan_env) -> None:
    main_module, monkeypatch = _lifespan_env
    monkeypatch.setenv("PERSIST_TRACES_TO_IRIS", "true")

    async with main_module.lifespan(main_module.app):
        assert store.list_traces() == []


@pytest.mark.asyncio
async def test_lifespan_does_not_hydrate_when_persistence_is_disabled(_lifespan_env) -> None:
    main_module, monkeypatch = _lifespan_env
    monkeypatch.setenv("PERSIST_TRACES_TO_IRIS", "false")
    _FakeWriter.to_load = [_trace("should-not-load")]

    async with main_module.lifespan(main_module.app):
        assert store.list_traces() == []

    assert _FakeWriter.instances == []


# --- reconnect once after IRIS dropped the kept connection ---


class _FakeIrisModuleWithDeadConnections:
    """The `iris` module: numbered connections; one can "die" (EPIPE after an IRIS restart)."""

    def __init__(self) -> None:
        self.values: dict[tuple, str] = {}
        self.connections: list[dict] = []
        self.down = False

    def connect(self, *args: Any) -> Any:
        if self.down:
            raise RuntimeError("<COMMUNICATION LINK ERROR> Failed to connect")
        state = {"dead": False, "closed": False}
        self.connections.append(state)
        return type("Connection", (), {"state": state, "close": lambda self: state.update(closed=True)})()

    def createIRIS(self, handle: Any) -> Any:  # noqa: N802 - Native API name
        module, state = self, handle.state

        def check() -> None:
            if state["dead"] or state["closed"]:
                raise RuntimeError("<COMMUNICATION LINK ERROR> Error code: 32 EPIPE")

        class Native:
            def get(self, *keys: Any) -> str | None:
                check()
                return module.values.get(keys)

            def set(self, value: str, *keys: Any) -> None:
                check()
                module.values[keys] = value

            def kill(self, *keys: Any) -> None:
                check()
                module.values.pop(keys, None)

        return Native()


def _writer_on(monkeypatch: pytest.MonkeyPatch) -> tuple[IRISTraceWriter, _FakeIrisModuleWithDeadConnections]:
    import sys

    from app.config import Settings

    module = _FakeIrisModuleWithDeadConnections()
    monkeypatch.setitem(sys.modules, "iris", module)
    writer = IRISTraceWriter(Settings(_env_file=None, iris_base_url="http://iris.invalid.test:52773",
                                      iris_username="u", iris_password="test-password-not-real"))
    return writer, module


def test_persist_sync_reconnects_once_after_the_connection_died(monkeypatch: pytest.MonkeyPatch) -> None:
    writer, module = _writer_on(monkeypatch)
    writer.persist_sync(_trace("first"))
    module.connections[0]["dead"] = True  # IRIS restarted

    writer.persist_sync(_trace("second"))

    assert module.values[("CommandCenterTrace", "seq")] == "2"
    assert "second" in module.values[("CommandCenterTrace", "trace", 2)]
    assert len(module.connections) == 2 and module.connections[0]["closed"]


def test_persist_sync_gives_up_after_one_retry_while_iris_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    writer, module = _writer_on(monkeypatch)
    writer.persist_sync(_trace("first"))
    module.connections[0]["dead"] = True
    module.down = True

    writer.persist_sync(_trace("lost"))  # must not raise

    assert module.values[("CommandCenterTrace", "seq")] == "1"
    assert len(module.connections) == 1
