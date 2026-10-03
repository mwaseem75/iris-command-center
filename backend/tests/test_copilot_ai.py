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
    CopilotProcessContext,
    CopilotWebAppContext,
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
    assert output.observations == ["All issue checks ran."]
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


# --- process questions (read-only, from the process context) ---

def _process_request(message: str, *, available: bool = True, focus: bool = True) -> CopilotAIRequest:
    top = [
        CopilotProcessContext(pid=2468, namespace="%SYS", routine="%SYS.Job", state="HANG", cpu_time=34980),
        CopilotProcessContext(pid=3456, namespace="USER", routine="MyApp.Service", state="RUNW", cpu_time=1200),
    ]
    focus_process = CopilotProcessContext(
        pid=2468, username="operator", namespace="%SYS", routine="%SYS.Job", state="HANG",
        cpu_time=34980, commands=10, globals=4, elapsed_time="30:44:28",
    )
    return CopilotAIRequest(
        message=message,
        intent=classify_intent(message),
        context=CopilotOperationalContext(
            databases=[],
            processes=top if available else [],
            processes_total=42 if available else None,
            processes_by_state={"RUNW": 12, "EVTW": 12, "HANG": 2} if available else {},
            processes_by_namespace={"%SYS": 24, "(none)": 12, "USER": 6} if available else {},
            processes_top_cpu=top if available else [],
            process_focus=focus_process if available and focus else None,
            web_apps=[],
            tasks=[],
            unavailable=[] if available else ["processes"],
        ),
    )


@pytest.mark.asyncio
async def test_process_state_summary_reports_states_as_iris_gives_them() -> None:
    output = await DeterministicCopilotProvider().generate(_process_request("Show processes by state"))

    assert output.answer.startswith("IRIS reports 42 processes in 3 states.")
    assert output.observations == ["State RUNW: 12", "State EVTW: 12", "State HANG: 2"]
    text = (output.answer + " ".join(output.observations)).lower()
    for judgement in ("hung", "stuck", "problem", "unhealthy"):
        assert judgement not in text


@pytest.mark.asyncio
async def test_process_namespace_summary() -> None:
    output = await DeterministicCopilotProvider().generate(_process_request("Show processes by namespace"))

    assert output.answer.startswith("IRIS reports 42 processes across 3 namespaces")
    assert output.observations == ["Namespace %SYS: 24", "Namespace (none): 12", "Namespace USER: 6"]


@pytest.mark.asyncio
async def test_top_processes_by_cumulative_cpu_time_never_claim_a_rate() -> None:
    output = await DeterministicCopilotProvider().generate(
        _process_request("Which processes have the highest cumulative CPU time?")
    )

    assert "cumulative CPU time as reported by IRIS, not current CPU usage" in output.answer
    assert output.observations[0].startswith("PID 2468: 34980 ms")
    assert output.observations[1].startswith("PID 3456: 1200 ms")
    assert "utilization" not in output.answer.lower() and "%" not in output.answer


@pytest.mark.asyncio
async def test_process_summary_combines_states_namespaces_and_top_cpu() -> None:
    output = await DeterministicCopilotProvider().generate(_process_request("Summarize process activity"))

    assert output.answer == "IRIS reports 42 processes across 3 namespaces."
    assert output.observations == [
        "By state: RUNW 12, EVTW 12, HANG 2.",
        "By namespace: %SYS 24, (none) 12, USER 6.",
        "Highest cumulative CPU time: PID 2468 (%SYS.Job), 34980 ms.",
    ]


@pytest.mark.asyncio
async def test_pid_question_returns_that_processes_fields() -> None:
    request = _process_request("Explain PID 2468")
    output = await DeterministicCopilotProvider().generate(request)

    assert request.intent is CopilotIntent.READ_ONLY_QUERY
    assert output.answer == "PID 2468 is in state HANG, running %SYS.Job in %SYS."
    assert "Elapsed time: 30:44:28" in output.observations
    assert "Username: operator" in output.observations
    assert any(line.startswith("CPU time: 34980 ms (cumulative") for line in output.observations)


@pytest.mark.asyncio
async def test_missing_pid_is_reported_as_not_found() -> None:
    output = await DeterministicCopilotProvider().generate(_process_request("Explain PID 99999", focus=False))

    assert output.answer == "PID 99999 was not found in the current process data (42 processes reported)."
    assert output.observations == []


@pytest.mark.asyncio
async def test_unavailable_process_data_is_not_assessed() -> None:
    for message in ("Summarize process activity", "Explain PID 2468"):
        output = await DeterministicCopilotProvider().generate(_process_request(message, available=False))

        assert output.answer == (
            "Process information could not be read, so process activity could not be assessed."
        )
        assert output.observations == ["Context unavailable for: processes."]
        assert output.proposed_action is None


@pytest.mark.asyncio
async def test_process_change_requests_stay_proposals_free() -> None:
    request = _process_request("Stop process 2468")
    output = await DeterministicCopilotProvider().generate(request)

    assert request.intent is CopilotIntent.RESOLUTION_REQUEST
    assert output.proposed_action is None
    assert output.requires_confirmation is False


# --- database and web application questions (read-only, from the context) ---

def _inventory_request(message: str, *, issues: list[CopilotIssueContext] | None = None,
                       issues_total: int | None = 0, available: bool = True) -> CopilotAIRequest:
    return CopilotAIRequest(
        message=message,
        intent=classify_intent(message),
        context=CopilotOperationalContext(
            databases=[CopilotDatabaseContext(name=name, status="Mounted/RW") for name in ("USER", "IPM")],
            databases_total=12 if available else None,
            databases_by_status={"Mounted/RW": 9, "Mounted/R": 2, "Dismounted": 1} if available else {},
            processes=[],
            web_apps=[CopilotWebAppContext(name="/csp/old", namespace="GONE", enabled=False, app_type="CSP")],
            web_apps_total=23 if available else None,
            web_apps_by_state={"Enabled": 21, "Disabled": 2} if available else {},
            web_apps_by_namespace={"%SYS": 15, "USER": 7, "GONE": 1} if available else {},
            web_apps_by_type={"CSP": 14, "System,CSP": 9} if available else {},
            web_apps_disabled=["/csp/old", "/csp/test"] if available else [],
            tasks=[],
            issues=issues or [],
            issues_total=issues_total,
            unavailable=[] if available else ["databases", "web_apps"],
        ),
    )


def _detected_issue(kind: str, title: str, resource: str) -> CopilotIssueContext:
    return CopilotIssueContext(kind=kind, title=title, resource_type="x", resource_name=resource,
                               readiness="ready", resolvable=False)


@pytest.mark.asyncio
async def test_database_answer_reports_status_counts_and_names_without_sizes() -> None:
    output = await DeterministicCopilotProvider().generate(_inventory_request("Summarize database status"))

    assert output.answer == (
        "IRIS reports 12 databases: Mounted/RW 9, Mounted/R 2, Dismounted 1. "
        "The Issue Resolver detects no dismounted or full databases."
    )
    assert output.observations == [
        "Status Mounted/RW: 9", "Status Mounted/R: 2", "Status Dismounted: 1",
        "Databases: USER, IPM and 10 more.",
    ]
    text = (output.answer + " ".join(output.observations)).lower()
    for word in ("size", "storage", " mb", " gb", "free"):
        assert word not in text


@pytest.mark.asyncio
async def test_database_answer_lists_detected_dismounted_and_full_databases() -> None:
    request = _inventory_request("Which databases need attention?", issues_total=3, issues=[
        _detected_issue("database_dismounted", "Database dismounted", "IPM"),
        _detected_issue("database_full", "Database full", "USER"),
        _detected_issue("audit_logging_disabled", "Auditing disabled", "Auditing"),
    ])
    output = await DeterministicCopilotProvider().generate(request)

    assert request.intent is CopilotIntent.READ_ONLY_QUERY
    assert output.answer.endswith("The Issue Resolver detects dismounted or full databases: 2.")
    assert output.observations[:2] == ["Database dismounted: IPM", "Database full: USER"]
    assert not any("Auditing" in line for line in output.observations)


@pytest.mark.asyncio
async def test_database_answer_when_issue_detection_or_databases_are_unavailable() -> None:
    no_detection = await DeterministicCopilotProvider().generate(
        _inventory_request("Show dismounted databases", issues_total=None)
    )
    assert no_detection.answer.endswith(
        "Issue detection could not be read, so dismounted or full databases are unknown."
    )
    unavailable = await DeterministicCopilotProvider().generate(
        _inventory_request("Summarize database status", available=False)
    )
    assert unavailable.answer == (
        "Database information could not be read, so database status could not be assessed."
    )


@pytest.mark.asyncio
async def test_web_app_answer_reports_enabled_state_namespaces_and_types() -> None:
    output = await DeterministicCopilotProvider().generate(_inventory_request("Which web apps are disabled?"))

    assert output.answer == (
        "IRIS reports 23 web applications: 21 enabled, 2 disabled. "
        "The Issue Resolver detects no web applications with a missing namespace."
    )
    assert output.observations == [
        "Disabled: /csp/old, /csp/test.",
        "By namespace: %SYS 15, USER 7, GONE 1.",
        "By type (as reported by IRIS): CSP 14, System,CSP 9.",
    ]


@pytest.mark.asyncio
async def test_web_app_namespace_question_and_detected_missing_namespace() -> None:
    request = _inventory_request("Show web apps by namespace", issues_total=1, issues=[
        _detected_issue("web_app_namespace_missing", "Web application namespace missing", "/csp/old"),
    ])
    output = await DeterministicCopilotProvider().generate(request)

    assert output.answer.endswith("The Issue Resolver detects web applications with a missing namespace: 1.")
    assert output.observations == [
        "Web application namespace missing: /csp/old",
        "Namespace %SYS: 15", "Namespace USER: 7", "Namespace GONE: 1",
    ]


@pytest.mark.asyncio
async def test_web_app_answer_when_web_apps_are_unavailable() -> None:
    output = await DeterministicCopilotProvider().generate(
        _inventory_request("Summarize web applications", available=False)
    )

    assert output.answer == (
        "Web application information could not be read, so web applications could not be assessed."
    )
    assert output.observations == ["Context unavailable for: databases, web_apps."]


@pytest.mark.asyncio
async def test_database_and_web_app_change_requests_get_no_new_proposals() -> None:
    for message in ("Dismount database USER", "Enable web app /csp/old"):
        request = _inventory_request(message)
        output = await DeterministicCopilotProvider().generate(request)
        assert request.intent is CopilotIntent.RESOLUTION_REQUEST
        assert output.proposed_action is None
