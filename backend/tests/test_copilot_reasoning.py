"""Tests for the Copilot's structured, non-executing reasoning layer."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.copilot.ai import CopilotAIProvider, DeterministicCopilotProvider
from app.copilot.intents import CopilotIntent
from app.copilot.reasoning import CopilotReasoningService
from app.execution.executor import OperationExecutor
from app.models.copilot import (
    CopilotAIOutput,
    CopilotAIRequest,
    CopilotAskResponse,
    CopilotOperationalContext,
)
from app.routes.copilot import get_copilot_ai_provider
from app.routes.issues import IssuesResponse


def _context() -> CopilotOperationalContext:
    return CopilotOperationalContext(
        info={"product": "IRIS", "server_version": "2026.2", "api_version": 2},
        databases=[],
        databases_total=0,
        processes=[],
        processes_total=0,
        web_apps=[],
        web_apps_total=0,
        tasks=[],
        tasks_total=0,
        unavailable=[],
    )


class FakeProvider:
    def __init__(self, output: CopilotAIOutput):
        self.output = output
        self.requests: list[CopilotAIRequest] = []

    async def generate(self, request: CopilotAIRequest) -> CopilotAIOutput:
        self.requests.append(request)
        return self.output


def test_provider_abstraction_accepts_a_mock_provider() -> None:
    provider: CopilotAIProvider = FakeProvider(CopilotAIOutput(answer="Mocked"))
    assert isinstance(provider, FakeProvider)


@pytest.mark.asyncio
async def test_reasoning_preserves_deterministic_intent_and_passes_context() -> None:
    provider = FakeProvider(
        CopilotAIOutput(answer="Context summary.", observations=["No databases reported."])
    )
    context = _context()

    response = await CopilotReasoningService(provider).reason(
        "List databases", CopilotIntent.READ_ONLY_QUERY, context
    )

    assert response.intent == CopilotIntent.READ_ONLY_QUERY.value
    assert response.answer == "Context summary."
    assert provider.requests == [
        CopilotAIRequest(
            message="List databases",
            intent=CopilotIntent.READ_ONLY_QUERY,
            context=context,
        )
    ]


def test_structured_response_model_rejects_uncontrolled_fields() -> None:
    response = CopilotAskResponse(
        answer="Plan only.",
        intent=CopilotIntent.RESOLUTION_REQUEST.value,
        observations=[],
        proposed_action="Review through the safety workflow.",
        requires_confirmation=True,
    )
    assert response.model_dump(mode="json") == {
        "answer": "Plan only.",
        "intent": "resolution_request",
        "observations": [],
        "proposed_action": "Review through the safety workflow.",
        "requires_confirmation": True,
    }
    with pytest.raises(ValueError):
        CopilotAskResponse.model_validate(
            {"answer": "x", "intent": "unknown", "tool_call": {"name": "mutate"}}
        )


@pytest.mark.asyncio
async def test_unknown_intent_is_out_of_scope_without_provider_call() -> None:
    provider = FakeProvider(CopilotAIOutput(answer="Should not be used."))

    response = await CopilotReasoningService(provider).reason(
        "Tell me a joke", CopilotIntent.UNKNOWN, _context()
    )

    assert response.intent == "unknown"
    assert "outside" in response.answer.lower()
    assert provider.requests == []


@pytest.mark.asyncio
async def test_resolution_request_is_a_proposal_only() -> None:
    provider = DeterministicCopilotProvider()

    response = await CopilotReasoningService(provider).reason(
        "Disable purge archived", CopilotIntent.RESOLUTION_REQUEST, _context()
    )

    assert response.proposed_action == "Set PurgeArchived to false"
    assert response.requires_confirmation is True
    assert "no operation is executed" in response.answer

    # Only catalog operations are proposed: there's no "disable database".
    response = await CopilotReasoningService(provider).reason(
        "Disable this database", CopilotIntent.RESOLUTION_REQUEST, _context()
    )
    assert response.proposed_action is None
    assert response.requires_confirmation is False
    assert "no operation is executed" in response.answer


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("List databases", "read_only_query"),
        ("Disable the database", "resolution_request"),
    ],
)
def test_ask_endpoint_uses_injected_provider_without_mutations(
    client: TestClient,
    mock_iris_client: AsyncMock,
    message: str,
    expected_intent: str,
) -> None:
    responses = {
        "/info": {
            "status": {"errors": [], "summary": ""},
            "console": [],
            "result": {
                "apiVersion": 2,
                "username": "_SYSTEM",
                "serverVersion": "IRIS 2026.2",
                "systemMode": "",
                "product": "IRIS",
                "namespaces": [],
                "privileges": {},
            },
        },
        "/v2/databases": {"status": {"errors": [], "summary": ""}, "console": [], "result": []},
        "/v2/processes": {"status": {"errors": [], "summary": ""}, "console": [], "result": []},
        "/v2/web-apps": {"status": {"errors": [], "summary": ""}, "console": [], "result": []},
        "/v2/tasks": {"status": {"errors": [], "summary": ""}, "console": [], "result": []},
    }

    async def get(path: str, params=None):
        return responses[path]

    mock_iris_client.get.side_effect = get
    provider = FakeProvider(
        CopilotAIOutput(
            answer="Mock response.",
            proposed_action=(
                "Review this change through the normal safety workflow."
                if expected_intent == "resolution_request" else None
            ),
            requires_confirmation=expected_intent == "resolution_request",
        )
    )
    from app.main import app

    app.dependency_overrides[get_copilot_ai_provider] = lambda: provider
    try:
        with (
            patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute,
            patch(
                "app.copilot.context.list_issues",
                new_callable=AsyncMock,
                return_value=IssuesResponse(issues=[], resolutions={}),
            ),
        ):
            response = client.post(
                "/api/iris/copilot/ask",
                json={"message": message},
            )
    finally:
        app.dependency_overrides.pop(get_copilot_ai_provider, None)

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Mock response.",
        "intent": expected_intent,
        "observations": [],
        "proposed_action": provider.output.proposed_action,
        "requires_confirmation": provider.output.requires_confirmation,
    }
    assert len(provider.requests) == 1
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    execute.assert_not_awaited()


def test_unknown_ask_does_not_fetch_iris_or_call_provider(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    provider = FakeProvider(CopilotAIOutput(answer="Not expected."))
    from app.main import app

    app.dependency_overrides[get_copilot_ai_provider] = lambda: provider
    try:
        response = client.post(
            "/api/iris/copilot/ask",
            json={"message": "Tell me a joke"},
        )
    finally:
        app.dependency_overrides.pop(get_copilot_ai_provider, None)

    assert response.status_code == 200
    assert response.json()["intent"] == "unknown"
    assert "outside" in response.json()["answer"].lower()
    assert provider.requests == []
    mock_iris_client.get.assert_not_awaited()
