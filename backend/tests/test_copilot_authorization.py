"""Tests for Copilot authorization and confirmation without execution."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.copilot.authorization import CopilotAuthorizationService
from app.execution.executor import OperationExecutor
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotAuthorizationRequest,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotPlanRequest,
    CopilotPlanningReason,
    CopilotPlanningResult,
    CopilotTargetKind,
)
from app.routes.copilot import get_caller_privileges


def _plan() -> CopilotOperationPlan:
    return CopilotOperationPlan(
        operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.JOURNAL_SETTINGS,
            identifier="journal-settings",
        ),
        parameters=CopilotOperationParameters(PurgeArchived=True),
        reason="Operator requested the journal setting update.",
        requires_confirmation=True,
    )


def test_valid_plan_without_confirmation_is_authorized_but_not_ready() -> None:
    result = CopilotAuthorizationService().authorize_plan(
        _plan(),
        frozenset({"Manage"}),
        confirmed=False,
    )

    assert result.authorized is True
    assert result.requires_confirmation is True
    assert result.ready_to_execute is False
    assert result.reason is CopilotAuthorizationReason.CONFIRMATION_REQUIRED


def test_valid_plan_with_explicit_confirmation_is_ready_but_not_executed() -> None:
    result = CopilotAuthorizationService().authorize_plan(
        _plan(),
        frozenset({"Journal"}),
        confirmed=True,
    )

    assert result.authorized is True
    assert result.requires_confirmation is False
    assert result.ready_to_execute is True
    assert result.operation is CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED
    assert result.required_privileges == ["Journal", "Manage"]


def test_missing_privilege_is_not_ready() -> None:
    result = CopilotAuthorizationService().authorize_plan(
        _plan(),
        frozenset(),
        confirmed=True,
    )

    assert result.authorized is False
    assert result.ready_to_execute is False
    assert result.reason is CopilotAuthorizationReason.MISSING_PRIVILEGE


def test_ai_confirmation_flag_cannot_bypass_gate() -> None:
    ai_proposal = _plan().model_copy(update={"requires_confirmation": False})
    request = CopilotAuthorizationRequest.model_validate(
        {"plan": ai_proposal.model_dump(mode="json"), "confirmed": False}
    )
    result = CopilotAuthorizationService().authorize_plan(
        request.plan,
        frozenset({"Manage"}),
        confirmed=request.confirmed,
    )

    assert request.plan.requires_confirmation is False
    assert result.requires_confirmation is True
    assert result.ready_to_execute is False


@pytest.mark.parametrize(
    "plan_data",
    [
        {"operation": "unknown.mutate"},
        {
            "operation": "journal.update_purge_archived",
            "target": {"kind": "journal_settings"},
            "parameters": {"PurgeArchived": True},
            "reason": "missing target identifier",
            "requires_confirmation": True,
        },
        {
            "operation": "journal.update_purge_archived",
            "target": {"kind": "journal_settings", "identifier": "journal-settings"},
            "parameters": {"PurgeArchived": "true"},
            "reason": "wrong parameter type",
            "requires_confirmation": True,
        },
        {
            "operation": "journal.update_purge_archived",
            "target": {"kind": "journal_settings", "identifier": "journal-settings"},
            "parameters": {"PurgeArchived": True, "command": "anything"},
            "reason": "extra parameter",
            "requires_confirmation": True,
        },
    ],
)
def test_unsupported_or_malformed_plan_is_rejected(plan_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(plan_data)


def test_read_only_or_unknown_intent_cannot_enter_mutation_authorization() -> None:
    request = CopilotPlanRequest(
        message="List databases",
        intent="read_only_query",
        proposed_action=None,
    )
    planning_result = CopilotPlanningResult(
        intent=request.intent,
        plan=None,
        reason=CopilotPlanningReason.NO_OPERATION_PROPOSED,
    )

    assert planning_result.plan is None
    with pytest.raises(ValidationError):
        CopilotAuthorizationRequest.model_validate(
            {"plan": {"intent": "read_only_query"}, "confirmed": True}
        )


@pytest.mark.parametrize("confirmed", [False, True])
def test_authorize_endpoint_never_invokes_executor_or_iris_mutation(
    client: TestClient,
    mock_iris_client: AsyncMock,
    confirmed: bool,
) -> None:
    from app.main import app

    app.dependency_overrides[get_caller_privileges] = lambda: frozenset({"Manage"})
    try:
        with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
            response = client.post(
                "/api/iris/copilot/authorize",
                json={
                    "plan": _plan().model_dump(mode="json"),
                    "confirmed": confirmed,
                },
            )
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)

    assert response.status_code == 200
    assert response.json()["ready_to_execute"] is confirmed
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    mock_iris_client.delete.assert_not_awaited()
    execute.assert_not_awaited()


def test_authorize_endpoint_rejects_non_boolean_confirmation(client: TestClient) -> None:
    from app.main import app

    # Privileges are a dependency (read from IRIS /info), resolved before the
    # body is validated; this test is about the body only.
    app.dependency_overrides[get_caller_privileges] = lambda: frozenset({"Manage"})
    try:
        response = client.post(
            "/api/iris/copilot/authorize",
            json={"plan": _plan().model_dump(mode="json"), "confirmed": "yes"},
        )
    finally:
        app.dependency_overrides.pop(get_caller_privileges, None)

    assert response.status_code == 422
