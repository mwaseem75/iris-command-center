"""Focused tests for the optional, feature-flagged IRIS execution-trace
persistence added in app/observability/iris_trace_writer.py and wired into
app/observability/store.py's record_trace(). No test here makes a real
network call or contacts a real IRIS instance — IRISTraceWriter's IRIS
Native API handle is always a fake/mock.

Two things these tests exist to guarantee:
  1. With no persister registered (the default), record_trace() behaves
     exactly as covered by test_observability.py — untouched by this file.
  2. With a persister registered, a persistence failure of any kind can
     NEVER raise out of record_trace() or otherwise affect the in-memory
     store it protects.
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
    # store._persister/_pending_persist_tasks are process-global module
    # state, same as store._traces — reset before AND after every test so
    # a persister registered here can never leak into another test file.
    store.clear_traces()
    store.set_trace_persister(None)
    yield
    store.clear_traces()
    store.set_trace_persister(None)


def _trace(name: str = "demo.op") -> ExecutionTrace:
    return ExecutionTrace(operation_name=name)


class _FakePersister:
    """Records every trace passed to persist_sync(); raises if configured
    to, so tests can exercise store.py's failure-swallowing behavior."""

    def __init__(self, *, raises: bool = False):
        self.calls: list[ExecutionTrace] = []
        self._raises = raises

    def persist_sync(self, trace: ExecutionTrace) -> None:
        self.calls.append(trace)
        if self._raises:
            raise RuntimeError("simulated IRIS persistence failure")


async def _drain_pending_persist_tasks() -> None:
    """Awaits every in-flight background persistence task store.py is
    currently tracking — the deterministic alternative to sleeping and
    hoping a background task has finished."""
    while store._pending_persist_tasks:
        await asyncio.gather(*store._pending_persist_tasks, return_exceptions=True)


# --- store.py: record_trace() + the optional persister hook ---


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
    # The in-memory store is unaffected either way.
    assert store.list_traces() == [trace]


@pytest.mark.asyncio
async def test_record_trace_never_raises_when_persister_raises() -> None:
    persister = _FakePersister(raises=True)
    store.set_trace_persister(persister)

    store.record_trace(_trace())  # must not raise synchronously
    await _drain_pending_persist_tasks()  # the background task must not raise either

    assert persister.calls  # it was still attempted


def test_record_trace_with_persister_but_no_running_loop_does_not_raise() -> None:
    # A plain (non-async) test function has no running event loop — this
    # is the same situation test_observability.py's existing sync tests
    # (e.g. test_store_is_capped_and_newest_first) call record_trace() from.
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


# --- IRISTraceWriter: sequence/eviction bookkeeping and failure isolation ---


class _FakeIrisNative:
    """Minimal stand-in for the object iris.createIRIS() returns — only the
    get/set/kill subset IRISTraceWriter.persist_sync() actually calls."""

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
    writer = IRISTraceWriter.__new__(IRISTraceWriter)  # bypass __init__'s Settings requirement
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
    # The oldest surviving entry (seq 1) was evicted to hold the cap at 200.
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
