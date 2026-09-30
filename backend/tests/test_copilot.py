"""Tests for deterministic Copilot intent classification and its API."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.copilot.intents import CopilotIntent, classify_intent
from app.execution.executor import OperationExecutor


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Why is this database unavailable?", CopilotIntent.ISSUE_INVESTIGATION),
        ("Show me the Health Center status", CopilotIntent.HEALTH_STATUS),
        ("List the databases", CopilotIntent.READ_ONLY_QUERY),
        ("Fix the database availability issue", CopilotIntent.RESOLUTION_REQUEST),
        ("Tell me a joke", CopilotIntent.UNKNOWN),
        ("Should we look into it?", CopilotIntent.UNKNOWN),
        ("   ", CopilotIntent.UNKNOWN),
    ],
)
def test_classify_intent(message: str, expected: CopilotIntent) -> None:
    assert classify_intent(message) is expected


@pytest.mark.parametrize(
    "message",
    [
        "Disable the database and show its status",
        "Please resolve this issue with the web application",
        "Set the task schedule and report task status",
        "Run the task now and show its status",
    ],
)
def test_resolution_language_takes_precedence_over_resource_keywords(message: str) -> None:
    assert classify_intent(message) is CopilotIntent.RESOLUTION_REQUEST


def test_explanatory_run_question_is_not_a_resolution_request() -> None:
    assert classify_intent("How do scheduled tasks run?") is CopilotIntent.READ_ONLY_QUERY


def test_classifier_does_not_require_iris() -> None:
    assert classify_intent("Why is this database unavailable?") is CopilotIntent.ISSUE_INVESTIGATION


def test_classify_endpoint_returns_only_controlled_intent(client: TestClient) -> None:
    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.post(
            "/api/iris/copilot/classify",
            json={"message": "Why is this database unavailable?"},
        )

    assert response.status_code == 200
    assert response.json() == {"intent": "issue_investigation"}
    execute.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 501},
        {},
        {"message": "List databases", "extra": "not accepted"},
        {"message": 123},
    ],
)
def test_classify_endpoint_rejects_invalid_requests(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post("/api/iris/copilot/classify", json=payload)

    assert response.status_code == 422


def test_classify_endpoint_does_not_access_iris(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    response = client.post(
        "/api/iris/copilot/classify",
        json={"message": "List the databases"},
    )

    assert response.status_code == 200
    mock_iris_client.get.assert_not_awaited()
    mock_iris_client.post.assert_not_awaited()
