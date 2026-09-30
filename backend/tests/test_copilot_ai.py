"""Tests for the deterministic Copilot AI provider (no network access)."""

import pytest

from app.copilot.ai import (
    CopilotAIProvider,
    DeterministicCopilotProvider,
    create_copilot_provider,
)
from app.copilot.intents import CopilotIntent, classify_intent
from app.models.copilot import (
    CopilotAIRequest,
    CopilotDatabaseContext,
    CopilotIssueContext,
    CopilotOperationalContext,
)
from app.routes.copilot import get_copilot_ai_provider


def _request(
    intent: CopilotIntent = CopilotIntent.HEALTH_STATUS,
    *,
    database_status: str = "mounted",
    message: str = "Summarize the current state.",
) -> CopilotAIRequest:
    return CopilotAIRequest(
        message=message,
        intent=intent,
        context=CopilotOperationalContext(
            info=None,
            databases=[
                CopilotDatabaseContext(
                    name="USER",
                    status=database_status,
                    directory="/iris/db",
                )
            ],
            databases_total=1,
            processes=[],
            processes_total=0,
            web_apps=[],
            web_apps_total=0,
            tasks=[],
            tasks_total=0,
            unavailable=[],
        ),
    )


@pytest.mark.asyncio
async def test_deterministic_provider_remains_available() -> None:
    output = await DeterministicCopilotProvider().generate(
        _request(CopilotIntent.HEALTH_STATUS)
    )

    assert output.answer
    assert output.observations


@pytest.mark.parametrize(
    ("message", "expected_action"),
    [
        ("Enable PurgeArchived.", "Set PurgeArchived to true"),
        ("Disable PurgeArchived.", "Set PurgeArchived to false"),
    ],
)
@pytest.mark.asyncio
async def test_deterministic_provider_proposes_supported_purge_archived_action(
    message: str,
    expected_action: str,
) -> None:
    intent = classify_intent(message)
    output = await DeterministicCopilotProvider().generate(
        _request(intent, message=message)
    )

    assert intent is CopilotIntent.RESOLUTION_REQUEST
    assert output.proposed_action == expected_action
    assert output.requires_confirmation is True


@pytest.mark.asyncio
async def test_deterministic_provider_does_not_propose_for_read_only_request() -> None:
    message = "Show me the databases."
    intent = classify_intent(message)
    output = await DeterministicCopilotProvider().generate(
        _request(intent, message=message)
    )

    assert intent is CopilotIntent.READ_ONLY_QUERY
    assert output.proposed_action is None
    assert output.requires_confirmation is False


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Disable the SAMPLE database.", CopilotIntent.RESOLUTION_REQUEST),
        ("Yes, do it.", CopilotIntent.UNKNOWN),
    ],
)
@pytest.mark.asyncio
async def test_deterministic_provider_does_not_fabricate_unsupported_proposal(
    message: str,
    intent: CopilotIntent,
) -> None:
    assert classify_intent(message) is intent
    output = await DeterministicCopilotProvider().generate(
        _request(intent, message=message)
    )

    assert output.proposed_action is None
    assert output.requires_confirmation is False


def test_provider_factory_returns_the_deterministic_provider() -> None:
    provider: CopilotAIProvider = create_copilot_provider()

    assert isinstance(provider, DeterministicCopilotProvider)
    assert isinstance(get_copilot_ai_provider(), DeterministicCopilotProvider)


def _issue_request(
    issues: list[CopilotIssueContext],
    *,
    issues_total: int | None,
    issue_checks_unavailable: list[str] | None = None,
) -> CopilotAIRequest:
    message = "Are there any issues?"
    return CopilotAIRequest(
        message=message,
        intent=classify_intent(message),
        context=_request().context.model_copy(
            update={
                "issues": issues,
                "issues_total": issues_total,
                "issue_checks_unavailable": issue_checks_unavailable or [],
            }
        ),
    )


def _issue(**values: object) -> CopilotIssueContext:
    return CopilotIssueContext(
        **{
            "kind": "database_dismounted",
            "title": "Database dismounted",
            "severity": "medium",
            "resource_type": "database",
            "resource_name": "IPM",
            "readiness": "ready_to_check",
            "explanation": "Database IPM is dismounted.",
            "resolvable": True,
            "recommended_operation": "database.mount",
            **values,
        }
    )


@pytest.mark.asyncio
async def test_deterministic_issue_investigation_reports_active_issues() -> None:
    request = _issue_request(
        [_issue(), _issue(kind="audit_logging_disabled", title=None, severity=None,
                          resource_name="Auditing", explanation=None, resolvable=False,
                          recommended_operation=None)],
        issues_total=3,
        issue_checks_unavailable=["database_full"],
    )

    output = await DeterministicCopilotProvider().generate(request)

    assert request.intent is CopilotIntent.ISSUE_INVESTIGATION
    assert "3 active issues" in output.answer
    assert "first 2" in output.answer
    assert output.observations == [
        "Issue checks that could not run: database_full.",
        "[medium] Database dismounted (IPM): Database IPM is dismounted.",
        "audit_logging_disabled (Auditing)",
    ]
    assert output.proposed_action is None
    assert output.requires_confirmation is False


@pytest.mark.asyncio
async def test_deterministic_issue_investigation_with_no_active_issues() -> None:
    output = await DeterministicCopilotProvider().generate(
        _issue_request([], issues_total=0)
    )

    assert output.answer == "The Issue Resolver reports no active issues."
    assert output.observations == []
    assert output.proposed_action is None
    assert output.requires_confirmation is False


@pytest.mark.asyncio
async def test_deterministic_issue_investigation_when_issues_unavailable() -> None:
    request = _issue_request([], issues_total=None)
    request = request.model_copy(
        update={"context": request.context.model_copy(update={"unavailable": ["issues"]})}
    )

    output = await DeterministicCopilotProvider().generate(request)

    assert "could not be read" in output.answer
    assert output.observations == ["Context unavailable for: issues."]
    assert "not retrieve Issue Resolver findings" not in output.answer
    assert output.proposed_action is None
    assert output.requires_confirmation is False
