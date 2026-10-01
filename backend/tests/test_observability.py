"""Tests for execution tracing, how the executor records traces, and
GET /api/iris/observability/traces. Uses a fake IRIS client.
"""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import ExecutionContext, OperationRequest
from app.observability.store import clear_traces, get_trace, list_traces, record_trace
from app.observability.models import ExecutionTrace, Span

_OPERATION_NAME = "journal.update_purge_archived"


@pytest.fixture(autouse=True)
def _clear_trace_store() -> None:
    # The trace store is a module global, so clear it before each test.
    clear_traces()


def _journal_settings_body(purge_archived: bool) -> dict[str, Any]:
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {
            "AlternateDirectory": "/usr/irissys/mgr/journal/",
            "ArchiveName": "",
            "BackupsBeforePurge": 2,
            "CurrentDirectory": "/usr/irissys/mgr/journal/",
            "DaysBeforePurge": 2,
            "FileSizeLimit": 1024,
            "FreezeOnError": False,
            "JournalFilePrefix": "",
            "JournalcspSession": False,
            "PurgeArchived": purge_archived,
            "CompressFiles": True,
            "wijdir": "",
            "targwijsz": 0,
        },
    }


def _request(purge_archived: bool = True) -> OperationRequest:
    return OperationRequest(
        operation_name=_OPERATION_NAME, parameters={"PurgeArchived": purge_archived}
    )


def _context(*, privileges: frozenset[str], confirmed: bool = False) -> ExecutionContext:
    return ExecutionContext(available_privileges=privileges, confirmation_received=confirmed)


# --- successful execution produces a complete, correctly-shaped trace ---


@pytest.mark.asyncio
async def test_successful_execution_records_a_complete_trace() -> None:
    client = AsyncMock()
    client.get.side_effect = [
        _journal_settings_body(False),  # pre-action
        _journal_settings_body(True),  # post-action verification
    ]
    client.put.return_value = _journal_settings_body(True)
    executor = OperationExecutor({_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)})

    result = await executor.execute(
        _request(purge_archived=True), _context(privileges=frozenset({"Manage"}), confirmed=True)
    )

    traces = list_traces()
    assert len(traces) == 1
    trace = traces[0]

    assert trace.operation_name == _OPERATION_NAME
    assert trace.status == result.status.value == "success"
    assert trace.trace_id  # got a real id
    assert trace.start_time is not None
    assert trace.end_time is not None
    assert trace.duration_ms is not None and trace.duration_ms >= 0

    assert trace.authorization_result == "authorized"
    assert trace.confirmation_result == "received"
    assert trace.execution_result == "success"
    assert trace.verification_result == "verified"

    span_names = [span.name for span in trace.spans]
    assert span_names == ["authorization", "confirmation", "execution", "verification"]
    for span in trace.spans:
        assert span.status == "ok"
        assert span.duration_ms is not None and span.duration_ms >= 0
        assert span.start_time is not None
        assert span.end_time is not None

    # get_trace() retrieves the same trace by id.
    assert get_trace(trace.trace_id) is not None
    assert get_trace(trace.trace_id).trace_id == trace.trace_id
    assert get_trace("not-a-real-id") is None


# --- unauthorized attempt: confirmation/execution/verification skipped ---


@pytest.mark.asyncio
async def test_unauthorized_attempt_records_skipped_downstream_spans() -> None:
    client = AsyncMock()
    executor = OperationExecutor({_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)})

    result = await executor.execute(_request(), _context(privileges=frozenset()))

    assert result.status.value == "unauthorized"
    trace = list_traces()[0]
    assert trace.status == "unauthorized"
    assert trace.authorization_result.startswith("denied:")
    assert trace.confirmation_result == "skipped"
    assert trace.execution_result == "skipped"
    assert trace.verification_result == "skipped"

    spans_by_name = {span.name: span for span in trace.spans}
    assert spans_by_name["authorization"].status == "error"
    assert spans_by_name["confirmation"].status == "skipped"
    assert spans_by_name["execution"].status == "skipped"
    assert spans_by_name["verification"].status == "skipped"
    client.get.assert_not_awaited()
    client.put.assert_not_awaited()


# --- authorized but not confirmed: execution/verification skipped ---


@pytest.mark.asyncio
async def test_confirmation_required_records_skipped_execution_and_verification() -> None:
    client = AsyncMock()
    executor = OperationExecutor({_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)})

    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Manage"}), confirmed=False)
    )

    assert result.status.value == "confirmation_required"
    trace = list_traces()[0]
    assert trace.status == "confirmation_required"
    assert trace.authorization_result == "authorized"
    assert trace.confirmation_result == "required_not_received"
    assert trace.execution_result == "skipped"
    assert trace.verification_result == "skipped"

    spans_by_name = {span.name: span for span in trace.spans}
    assert spans_by_name["confirmation"].status == "error"
    assert spans_by_name["execution"].status == "skipped"
    client.put.assert_not_awaited()


# --- no trace ever contains a secret ---


@pytest.mark.asyncio
async def test_trace_never_contains_forbidden_sensitive_substrings() -> None:
    client = AsyncMock()
    client.get.side_effect = [
        _journal_settings_body(False),
        _journal_settings_body(True),
    ]
    client.put.return_value = _journal_settings_body(True)
    executor = OperationExecutor({_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)})

    await executor.execute(
        _request(purge_archived=True), _context(privileges=frozenset({"Journal"}), confirmed=True)
    )

    trace = list_traces()[0]
    serialized = trace.model_dump_json().lower()
    # "authorization" is a normal word here (authorization_result), so we
    # look for credential-like substrings instead.
    for forbidden in ("password", "bearer ", "jwt", "secret"):
        assert forbidden not in serialized, f"trace unexpectedly contains {forbidden!r}"


# --- in-memory store: capped size, newest-first ---


def test_store_is_capped_and_newest_first() -> None:
    from app.observability import store as store_module

    for i in range(store_module._MAX_TRACES + 10):
        record_trace(ExecutionTrace(operation_name=f"op-{i}"))

    traces = list_traces()
    assert len(traces) == store_module._MAX_TRACES
    # The most recently recorded trace (op-<last>) is first.
    assert traces[0].operation_name == f"op-{store_module._MAX_TRACES + 9}"


def test_span_requires_all_fields_and_defaults_events_empty() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    span = Span(name="authorization", start_time=now, end_time=now, duration_ms=1.0, status="ok")
    assert span.events == []
    assert span.attributes == {}


# --- GET /api/iris/observability/traces: read-only, no IRIS call ---


def test_traces_route_returns_empty_list_when_no_traces_recorded(client: TestClient) -> None:
    response = client.get("/api/iris/observability/traces")

    assert response.status_code == 200
    assert response.json() == {"traces": []}


def test_traces_route_returns_recorded_traces(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    record_trace(ExecutionTrace(operation_name=_OPERATION_NAME, status="success"))

    response = client.get("/api/iris/observability/traces")

    assert response.status_code == 200
    body = response.json()
    assert len(body["traces"]) == 1
    assert body["traces"][0]["operation_name"] == _OPERATION_NAME
    assert body["traces"][0]["status"] == "success"
    # This route makes no IRIS call at all.
    mock_iris_client.get.assert_not_awaited()


def test_traces_route_never_uses_a_mutating_http_method(client: TestClient) -> None:
    response = client.post("/api/iris/observability/traces")
    assert response.status_code == 405


# --- instance identity on traces ---


@pytest.mark.asyncio
async def test_a_change_records_the_primary_as_its_instance() -> None:
    client = AsyncMock()
    client.get.side_effect = [_journal_settings_body(False), _journal_settings_body(True)]
    client.put.return_value = _journal_settings_body(True)
    executor = OperationExecutor({_OPERATION_NAME: JournalUpdatePurgeArchivedHandler(client)})
    await executor.execute(_request(purge_archived=True), _context(privileges=frozenset({"Manage"}), confirmed=True))
    assert list_traces()[0].instance_id == "primary"


@pytest.mark.asyncio
async def test_an_executor_without_an_instance_records_none() -> None:
    # Instance-registry changes (routes/instances.py) pass instance_id=None.
    executor = OperationExecutor({}, instance_id=None)
    await executor.execute(_request(), _context(privileges=frozenset({"Manage"}), confirmed=True))
    assert list_traces()[0].instance_id is None


def test_a_trace_saved_before_instance_identity_loads_without_one() -> None:
    # Persisted traces are ExecutionTrace JSON; older ones have no instance_id.
    old = ExecutionTrace(operation_name=_OPERATION_NAME).model_dump(mode="json")
    del old["instance_id"]
    loaded = ExecutionTrace.model_validate_json(json.dumps(old))
    assert loaded.instance_id is None


def test_traces_route_includes_the_instance(client: TestClient) -> None:
    record_trace(ExecutionTrace(operation_name=_OPERATION_NAME, instance_id="primary"))
    record_trace(ExecutionTrace(operation_name=_OPERATION_NAME))
    traces = client.get("/api/iris/observability/traces").json()["traces"]
    assert [trace["instance_id"] for trace in traces] == [None, "primary"]
