"""Tests for the read-only Health Center report."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISConnectionError
from app.main import app
from app.resolution import custom_rules
from app.resolution.models import IssueSeverity
from tests.test_issues_route import _app, _db, _dir, _journal, _mock

OK = {"errors": [], "summary": ""}
AUDIT_PATH = "/v2/security/audit/enabled"


@pytest.fixture(autouse=True)
def clear_custom_rules() -> Iterator[None]:
    custom_rules.clear_rules()
    yield
    custom_rules.clear_rules()


def _mock_health(
    iris: AsyncMock,
    databases: list[dict[str, Any]] | None = None,
    directories: list[dict[str, Any]] | None = None,
    *,
    journal: dict[str, Any] | None = None,
    web_apps: list[dict[str, Any]] | None = None,
    fail_task_manager: bool = False,
    **checks: Any,
) -> None:
    _mock(
        iris,
        databases or [],
        directories or [],
        journal=journal,
        web_apps=web_apps,
        **checks,
    )
    issue_reads = iris.get.side_effect

    def read(path: str, **kwargs: Any) -> dict[str, Any]:
        if path == AUDIT_PATH:
            return {"status": OK, "console": [], "result": {"Enabled": True}}
        if fail_task_manager and path == "/v2/task/manager":
            raise IRISConnectionError("IRIS unavailable")
        return issue_reads(path, **kwargs)

    iris.get.side_effect = read


def test_health_report_scores_assessed_categories_and_marks_others_unassessed(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock_health(mock_iris_client)

    response = client.get("/api/iris/health")

    assert response.status_code == 200
    body = response.json()
    categories = {item["id"]: item for item in body["categories"]}
    assert body["status"] == "partial"
    assert body["overall_score"] == 100
    assert {item["score"] for key, item in categories.items() if key in {
        "tasks", "databases", "web-applications", "system"
    }} == {100}
    assert categories["performance"]["status"] == "not_assessed"
    assert categories["security"]["status"] == "not_assessed"
    assert categories["security"]["evidence"][0]["observed_value"] is True
    assert body["findings"] == body["recommendations"] == []
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post_async_task.assert_not_called()


def test_health_report_reuses_issue_evidence_and_severity_penalties(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock_health(
        mock_iris_client,
        [_db("USER", "/data/user/")],
        [_dir("/data/user/", "Dismounted")],
        journal=_journal(archive_name="/archive"),
        web_apps=[_app("/app", "MISSING")],
        monitor_process=False,
    )

    body = client.get("/api/iris/health").json()
    categories = {item["id"]: item for item in body["categories"]}
    findings = {item["check_id"]: item for item in body["findings"]}

    assert categories["databases"]["score"] == 75
    assert categories["web-applications"]["score"] == 90
    assert categories["system"]["score"] == 85
    assert findings["database_dismounted"]["severity"] == "high"
    assert findings["database_dismounted"]["evidence"][0]["observed_value"] == "USER"
    assert findings["system_monitor_not_running"]["investigation"]["page"] == "system"
    assert len(body["recommendations"]) == len(body["findings"])
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post_async_task.assert_not_called()


def test_health_report_marks_failed_checks_unavailable(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock_health(mock_iris_client, fail_task_manager=True)

    body = client.get("/api/iris/health").json()
    tasks = next(item for item in body["categories"] if item["id"] == "tasks")

    assert body["status"] == "partial"
    assert body["overall_score"] == 100
    assert tasks["status"] == "unavailable"
    assert tasks["score"] is None
    assert tasks["unavailable_sources"][0]["check_id"] == "task_manager_not_running"


def test_database_full_uses_existing_read_only_info_task(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    directory = _dir("/data/user/", "Mounted/RW")
    directory.update({"Size": 10, "MaxSize": 10})
    _mock_health(mock_iris_client, [_db("USER", "/data/user/")], [directory])

    body = client.get("/api/iris/health").json()
    finding = next(item for item in body["findings"] if item["check_id"] == "database_full")

    assert finding["evidence"][0]["observed_value"] == {"Size": 10, "MaxSize": 10}
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/database-dir/info", params={"dir": "/data/user/"}
    )
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_custom_performance_rule_provides_a_scoring_baseline(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock_health(mock_iris_client)
    custom_rules.add_rule(
        custom_rules.CustomIssueRule(
            name="cache_efficiency",
            title="Cache efficiency low",
            severity=IssueSeverity.HIGH,
            signal="cache_efficiency",
            operator="<",
            value=70,
            investigation_page="system",
            guidance="Review cache configuration.",
        )
    )

    body = client.get("/api/iris/health").json()
    performance = next(item for item in body["categories"] if item["id"] == "performance")
    finding = next(item for item in body["findings"] if item["check_id"] == "custom:cache_efficiency")

    assert performance["score"] == 75
    assert finding["evidence"][0]["observed_value"] == 57.74


def test_custom_license_use_rule_is_assigned_to_system_category(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock_health(mock_iris_client)
    custom_rules.add_rule(
        custom_rules.CustomIssueRule(
            name="license_use",
            title="License use high",
            severity=IssueSeverity.HIGH,
            signal="license_use_percent",
            operator=">=",
            value=0,
            investigation_page="system",
            guidance="Review license usage.",
        )
    )

    response = client.get("/api/iris/health")

    assert response.status_code == 200
    body = response.json()
    finding = next(
        item for item in body["findings"] if item["check_id"] == "custom:license_use"
    )
    assert finding["category"] == "system"
    assert finding["evidence"][0]["observed_value"] == 0
