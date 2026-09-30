"""Tests for issue resolution history derived from existing traces."""

from datetime import datetime, timezone

from app.execution.models import (
    ResolutionAction,
    ResolutionBefore,
    ResolutionLifecycleEvidence,
)
from app.observability import store
from app.observability.models import ExecutionTrace, ResolutionContext, Span
from app.resolution.history import history_for_issue
from app.resolution.identity import IssueResourceReference, issue_identity


def _trace(
    issue_id: str,
    *,
    timestamp: datetime,
    trace_id: str,
    status: str = "success",
    verification_status: str = "verified",
) -> ExecutionTrace:
    resource = IssueResourceReference(
        type="database",
        canonical_key="/data/demo",
        display_name="DEMO",
    )
    lifecycle = ResolutionLifecycleEvidence(
        before=ResolutionBefore(
            issue_id=issue_id,
            resource=resource,
            observed_at=timestamp,
            state={"mounted": False},
        ),
        action=ResolutionAction(
            operation_name="database.mount",
            parameters={"Directory": "/data/demo/", "ReadOnly": False},
        ),
        after={"mounted": True},
    )
    return ExecutionTrace(
        trace_id=trace_id,
        operation_name="database.mount",
        start_time=timestamp,
        status=status,
        execution_result="success",
        verification_result=verification_status,
        resolution=ResolutionContext(
            issue_type="database_dismounted",
            issue_title="Dismounted database",
            severity="high",
            resource="/data/demo/",
            issue_id=issue_id,
            resource_reference=resource,
        ),
        lifecycle=lifecycle,
    )


def test_history_projects_existing_trace_and_lifecycle_evidence() -> None:
    identity = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    issue_id = identity["issue_id"]
    timestamp = datetime(2026, 9, 30, tzinfo=timezone.utc)

    response = history_for_issue(
        issue_id,
        [_trace(issue_id, timestamp=timestamp, trace_id="trace-1")],
    )

    (entry,) = response.history
    assert entry.issue_id == issue_id
    assert entry.resource == identity["resource"]
    assert entry.operation_name == "database.mount"
    assert entry.timestamp == timestamp
    assert entry.before is not None and entry.before.state == {"mounted": False}
    assert entry.action is not None and entry.action.operation_name == "database.mount"
    assert entry.result.operation_status == "success"
    assert entry.result.execution_status == "success"
    assert entry.after == {"mounted": True}
    assert entry.verification.status == "verified"


def test_history_uses_a_trace_hydrated_from_existing_persistence() -> None:
    identity = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    issue_id = identity["issue_id"]
    trace = _trace(
        issue_id,
        timestamp=datetime(2026, 9, 30, tzinfo=timezone.utc),
        trace_id="persisted-trace",
    )
    store.clear_traces()
    try:
        assert store.hydrate_traces([trace]) == 1
        response = history_for_issue(issue_id, store.list_traces())
        assert [entry.operation_name for entry in response.history] == ["database.mount"]
    finally:
        store.clear_traces()


def test_history_orders_multiple_resolutions_newest_first() -> None:
    identity = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    issue_id = identity["issue_id"]
    older = datetime(2026, 9, 29, tzinfo=timezone.utc)
    newer = datetime(2026, 9, 30, tzinfo=timezone.utc)

    response = history_for_issue(
        issue_id,
        [
            _trace(issue_id, timestamp=older, trace_id="trace-old"),
            _trace(issue_id, timestamp=newer, trace_id="trace-new"),
        ],
    )

    assert [entry.timestamp for entry in response.history] == [newer, older]


def test_history_uses_trace_id_as_a_deterministic_timestamp_tiebreaker() -> None:
    identity = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    issue_id = identity["issue_id"]
    timestamp = datetime(2026, 9, 30, tzinfo=timezone.utc)

    response = history_for_issue(
        issue_id,
        [
            _trace(issue_id, timestamp=timestamp, trace_id="trace-a"),
            _trace(issue_id, timestamp=timestamp, trace_id="trace-z"),
        ],
    )

    assert [entry.trace_id for entry in response.history] == ["trace-z", "trace-a"]


def test_history_is_empty_for_an_issue_without_resolution_traces() -> None:
    response = history_for_issue("never-resolved", [])

    assert response.issue_id == "never-resolved"
    assert response.history == []


def test_history_excludes_unrelated_issue_traces() -> None:
    target = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    unrelated = issue_identity("database_dismounted", "database", "/data/other", "OTHER")

    response = history_for_issue(
        target["issue_id"],
        [
            _trace(
                unrelated["issue_id"],
                timestamp=datetime(2026, 9, 30, tzinfo=timezone.utc),
                trace_id="other",
            )
        ],
    )

    assert response.history == []


def test_history_does_not_expose_arbitrary_trace_payloads() -> None:
    identity = issue_identity("database_dismounted", "database", "/data/demo", "DEMO")
    issue_id = identity["issue_id"]
    trace = _trace(
        issue_id,
        timestamp=datetime(2026, 9, 30, tzinfo=timezone.utc),
        trace_id="trace-safe",
    )
    trace.spans.append(
        Span(
            name="execution",
            start_time=trace.start_time,
            end_time=trace.start_time,
            duration_ms=0,
            status="ok",
            attributes={"password": "not-for-history"},
        )
    )

    history_json = history_for_issue(issue_id, [trace]).model_dump_json()

    assert "not-for-history" not in history_json
    assert "password" not in history_json
