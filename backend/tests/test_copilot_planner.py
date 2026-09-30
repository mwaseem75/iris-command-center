"""Tests for the deterministic, non-executing Copilot planning gateway."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.copilot.intents import CopilotIntent
from app.copilot.planner import CopilotPlanningService
from app.execution.executor import OperationExecutor
from app.models.copilot import (
    CopilotOperation,
    CopilotOperationPlan,
    CopilotPlanRequest,
    CopilotPlanningReason,
)


def _request(
    message: str,
    intent: CopilotIntent,
    proposed_action: str | None,
    *,
    requires_confirmation: bool = False,
) -> CopilotPlanRequest:
    return CopilotPlanRequest(
        message=message,
        intent=intent,
        proposed_action=proposed_action,
        requires_confirmation=requires_confirmation,
    )


def test_supported_journal_operation_produces_closed_plan() -> None:
    result = CopilotPlanningService().plan(
        _request(
            "Set PurgeArchived to true",
            CopilotIntent.RESOLUTION_REQUEST,
            "Set PurgeArchived to true",
        )
    )

    assert result.reason is CopilotPlanningReason.PLAN_CREATED
    assert result.intent is CopilotIntent.RESOLUTION_REQUEST
    assert result.plan is not None
    assert result.plan.operation is CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED
    assert result.plan.target.identifier == "journal-settings"
    assert result.plan.parameters.PurgeArchived is True
    assert result.plan.requires_confirmation is True


@pytest.mark.parametrize(
    "proposal",
    [
        "Disable database SAMPLE",
        "database.disable SAMPLE",
        "run shell command rm -rf /",
        "__import__('os').system('whoami')",
        "UPDATE databases SET enabled = false",
    ],
)
def test_unsupported_or_arbitrary_proposals_do_not_create_plans(proposal: str) -> None:
    result = CopilotPlanningService().plan(
        _request("Disable database SAMPLE", CopilotIntent.RESOLUTION_REQUEST, proposal)
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


def test_proposed_value_must_match_explicit_user_request() -> None:
    result = CopilotPlanningService().plan(
        _request(
            "Set PurgeArchived to true",
            CopilotIntent.RESOLUTION_REQUEST,
            "Set PurgeArchived to false",
        )
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


def test_negated_user_request_does_not_create_a_plan() -> None:
    result = CopilotPlanningService().plan(
        _request(
            "Do not set PurgeArchived to true",
            CopilotIntent.RESOLUTION_REQUEST,
            "Set PurgeArchived to true",
        )
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


def test_ai_confirmation_flag_is_ignored_for_mutation_plan() -> None:
    result = CopilotPlanningService().plan(
        _request(
            "Set PurgeArchived to false",
            CopilotIntent.RESOLUTION_REQUEST,
            "Set PurgeArchived to false",
            requires_confirmation=False,
        )
    )

    assert result.plan is not None
    assert result.plan.requires_confirmation is True


@pytest.mark.parametrize(
    "intent",
    [
        CopilotIntent.ISSUE_INVESTIGATION,
        CopilotIntent.HEALTH_STATUS,
        CopilotIntent.READ_ONLY_QUERY,
    ],
)
def test_read_only_intents_produce_no_mutation_plan(intent: CopilotIntent) -> None:
    message = {
        CopilotIntent.ISSUE_INVESTIGATION: "Why is the database unavailable?",
        CopilotIntent.HEALTH_STATUS: "Show health status",
        CopilotIntent.READ_ONLY_QUERY: "List databases",
    }[intent]
    result = CopilotPlanningService().plan(
        _request(message, intent, "Set PurgeArchived to true")
    )

    assert result.intent is intent
    assert result.plan is None
    assert result.reason is CopilotPlanningReason.NO_OPERATION_PROPOSED


def test_unknown_intent_produces_no_plan() -> None:
    result = CopilotPlanningService().plan(
        _request("Tell me a joke", CopilotIntent.UNKNOWN, "Set PurgeArchived to true")
    )

    assert result.intent is CopilotIntent.UNKNOWN
    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_INTENT


def test_ai_intent_must_match_deterministic_message_classification() -> None:
    result = CopilotPlanningService().plan(
        _request(
            "List databases",
            CopilotIntent.RESOLUTION_REQUEST,
            "Set PurgeArchived to true",
        )
    )

    assert result.intent is CopilotIntent.READ_ONLY_QUERY
    assert result.plan is None
    assert result.reason is CopilotPlanningReason.INTENT_MISMATCH


def test_operation_enum_and_plan_reject_unregistered_or_unstructured_values() -> None:
    with pytest.raises(ValueError):
        CopilotOperation("database.disable")
    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(
            {
                "operation": "database.disable",
                "target": "SAMPLE",
                "parameters": {"command": "anything"},
                "reason": "AI said so",
                "requires_confirmation": False,
            }
        )


def test_plan_endpoint_never_invokes_executor_or_iris_mutation(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.post(
            "/api/iris/copilot/plan",
            json={
                "message": "Set PurgeArchived to true",
                "intent": "resolution_request",
                "proposed_action": "Set PurgeArchived to true",
                "requires_confirmation": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "resolution_request"
    assert body["reason"] == "plan_created"
    assert body["plan"]["operation"] == "journal.update_purge_archived"
    assert body["plan"]["requires_confirmation"] is True
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    mock_iris_client.delete.assert_not_awaited()
    execute.assert_not_awaited()


def test_plan_endpoint_rejects_invalid_request(client: TestClient) -> None:
    response = client.post(
        "/api/iris/copilot/plan",
        json={
            "message": " ",
            "intent": "resolution_request",
            "proposed_action": "Set PurgeArchived to true",
        },
    )

    assert response.status_code == 422
