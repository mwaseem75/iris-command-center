"""Phase 5c: Copilot web_app.set_enabled (disable only) for a detected
web_app_namespace_missing issue, plus coverage of the shared catalog-backed
planning/execution structure.

Everything is mocked: no IRIS call, no real web-app change. The Issue Resolver
detection (`list_issues`) is patched; the catalog is the real one.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authorization.operations import OperationKind, get_operation
from app.copilot.ai import DeterministicCopilotProvider
from app.copilot.execution import CopilotExecutionService
from app.copilot.intents import CopilotIntent, classify_intent
from app.copilot.planner import CATALOG_OPERATIONS, CopilotPlanningService
from app.execution.executor import OperationExecutor
from app.execution.handler import OperationHandler
from app.execution.models import (
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    OperationResult,
    OperationResultStatus,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.models.copilot import (
    CopilotAIRequest,
    CopilotAuthorizationReason,
    CopilotAuthorizationResult,
    CopilotDatabaseMountParameters,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationalContext,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotPlanRequest,
    CopilotPlanningReason,
    CopilotTargetKind,
    CopilotWebAppDisableParameters,
)
from app.observability import store
from app.resolution.catalog import ISSUE_CATALOG, trace_context
from app.resolution.history import history_for_issue
from app.resolution.identity import ResolutionReadiness, issue_identity
from app.routes.issues import DatabaseMountIssue, IssuesResponse, WebAppNamespaceIssue

_APP = "/csp/broken"
_MESSAGE = "Disable web app /csp/broken"
_PROPOSAL = "Disable web app /csp/broken"


def _issue(
    name: str = _APP,
    *,
    app_type: str = "CSP",
    enabled: bool = True,
) -> WebAppNamespaceIssue:
    return WebAppNamespaceIssue(
        **issue_identity("web_app_namespace_missing", "web-app", name, name),
        readiness=ResolutionReadiness.READY_TO_CHECK,
        web_app=name,
        namespace="MISSINGNS",
        enabled=enabled,
        app_type=app_type,
        explanation=f"Web application {name} has a missing namespace.",
        parameters={"Name": name, "Enabled": False},
    )


def _mount_issue() -> DatabaseMountIssue:
    return DatabaseMountIssue(
        **issue_identity("database_dismounted", "database", "/db/ipm", "IPM"),
        readiness=ResolutionReadiness.READY_TO_CHECK,
        database="IPM",
        directory="/db/ipm/",
        status="Dismounted",
        mount_required=False,
        mount_at_startup=False,
        mirrored=False,
        affected_namespaces=[],
        explanation="IPM is dismounted.",
        parameters={"Directory": "/db/ipm/", "ReadOnly": False},
    )


def _issues(*issues: object) -> IssuesResponse:
    return IssuesResponse(issues=list(issues), resolutions=dict(ISSUE_CATALOG))


def _plan_request(message: str = _MESSAGE, proposal: str | None = _PROPOSAL) -> CopilotPlanRequest:
    return CopilotPlanRequest(
        message=message,
        intent=classify_intent(message),
        proposed_action=proposal,
        requires_confirmation=True,
    )


def _plan(issue: WebAppNamespaceIssue | None = None) -> CopilotOperationPlan:
    issue = issue or _issue()
    return CopilotOperationPlan(
        operation=CopilotOperation.WEB_APP_SET_ENABLED,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.WEB_APP,
            identifier=issue.resource.display_name,
            issue_id=issue.issue_id,
        ),
        parameters=CopilotWebAppDisableParameters(Name=issue.web_app, Enabled=False),
        reason="Detected.",
        requires_confirmation=True,
    )


def _mount_plan(issue: DatabaseMountIssue) -> CopilotOperationPlan:
    return CopilotOperationPlan(
        operation=CopilotOperation.DATABASE_MOUNT,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.DATABASE, identifier="IPM", issue_id=issue.issue_id
        ),
        parameters=CopilotDatabaseMountParameters(Directory=issue.directory),
        reason="Detected.",
        requires_confirmation=True,
    )


def _authorization(plan: CopilotOperationPlan) -> CopilotAuthorizationResult:
    return CopilotAuthorizationResult(
        authorized=True,
        requires_confirmation=False,
        ready_to_execute=True,
        reason=CopilotAuthorizationReason.AUTHORIZED,
        required_privileges=["Manage"],
        operation=plan.operation,
        target=plan.target,
    )


def _operation_result(
    status: OperationResultStatus = OperationResultStatus.SUCCESS,
    verification: PostActionVerificationStatus = PostActionVerificationStatus.VERIFIED,
) -> OperationResult:
    return OperationResult(
        operation_name="web_app.set_enabled",
        status=status,
        handler_result=HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="disabled"),
        verification=PostActionVerificationResult(status=verification, detail="Enabled=false"),
        detail="executor result",
    )


def _service(executor: object, privileges: frozenset[str] = frozenset({"Manage", "Secure"})):
    return CopilotExecutionService(AsyncMock(), privileges, executor)


# --- models ---


_TARGET = {"kind": "web_app", "identifier": _APP, "issue_id": "a" * 64}


@pytest.mark.parametrize(
    "plan_data",
    [
        # enabling is never a Copilot plan
        {"operation": "web_app.set_enabled", "target": _TARGET,
         "parameters": {"Name": _APP, "Enabled": True}},
        # non-boolean Enabled
        {"operation": "web_app.set_enabled", "target": _TARGET,
         "parameters": {"Name": _APP, "Enabled": "false"}},
        # Name must be a web-app path
        {"operation": "web_app.set_enabled", "target": _TARGET,
         "parameters": {"Name": "csp/broken", "Enabled": False}},
        # extra parameter
        {"operation": "web_app.set_enabled", "target": _TARGET,
         "parameters": {"Name": _APP, "Enabled": False, "NameSpace": "USER"}},
        # web-app target without a detected issue
        {"operation": "web_app.set_enabled", "target": {"kind": "web_app", "identifier": _APP},
         "parameters": {"Name": _APP, "Enabled": False}},
        # web-app operation with mount parameters / a database target
        {"operation": "web_app.set_enabled", "target": _TARGET,
         "parameters": {"Directory": "/db/", "ReadOnly": False}},
        {"operation": "web_app.set_enabled",
         "target": {"kind": "database", "identifier": _APP, "issue_id": "a" * 64},
         "parameters": {"Name": _APP, "Enabled": False}},
        # mount operation with web-app parameters
        {"operation": "database.mount",
         "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
         "parameters": {"Name": _APP, "Enabled": False}},
    ],
)
def test_malformed_or_mismatched_web_app_plans_are_rejected(plan_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(
            {"reason": "test", "requires_confirmation": True, **plan_data}
        )


# --- deterministic provider ---


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Disable web app /csp/broken", "Disable web app /csp/broken"),
        ("Disable the /csp/broken web application.", "Disable web app /csp/broken"),
        ("disable webapp /csp/broken!", "Disable web app /csp/broken"),
        ("Enable web app /csp/broken", None),
        ("Disable web app /csp/broken and /csp/other", None),
        ("Disable web app csp/broken", None),
        ("Please disable web app /csp/broken", None),
    ],
)
@pytest.mark.asyncio
async def test_deterministic_provider_web_app_proposal_is_disable_only_text(
    message: str, expected: str | None
) -> None:
    output = await DeterministicCopilotProvider().generate(
        CopilotAIRequest(
            message=message,
            intent=CopilotIntent.RESOLUTION_REQUEST,
            context=CopilotOperationalContext(
                databases=[], processes=[], web_apps=[], tasks=[], unavailable=[]
            ),
        )
    )

    assert output.proposed_action == expected
    assert output.requires_confirmation is (expected is not None)


# --- planner ---


def test_web_app_plan_is_built_from_the_detected_issue_and_catalog() -> None:
    issue = _issue()

    result = CopilotPlanningService().plan(_plan_request(), _issues(issue))

    assert result.reason is CopilotPlanningReason.PLAN_CREATED
    assert result.plan is not None
    assert result.plan.operation is CopilotOperation.WEB_APP_SET_ENABLED
    assert result.plan.target == CopilotOperationTarget(
        kind=CopilotTargetKind.WEB_APP, identifier=_APP, issue_id=issue.issue_id
    )
    assert result.plan.parameters == CopilotWebAppDisableParameters(Name=_APP, Enabled=False)
    assert result.plan.requires_confirmation is True


def test_name_selects_like_the_handler_but_parameters_use_the_detected_name() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("Disable web app /CSP/Broken/", "Disable web app /CSP/Broken/"),
        _issues(_issue()),
    )

    assert result.plan is not None
    assert result.plan.parameters.Name == _APP
    assert result.plan.target.identifier == _APP


def test_undetected_web_app_is_rejected() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("Disable web app /csp/other", "Disable web app /csp/other"),
        _issues(_issue()),
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.ISSUE_NOT_DETECTED


def test_ambiguous_web_app_name_is_rejected() -> None:
    result = CopilotPlanningService().plan(
        _plan_request(), _issues(_issue(), _issue("/CSP/Broken/"))
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.AMBIGUOUS_TARGET


def test_unavailable_detection_is_rejected() -> None:
    result = CopilotPlanningService().plan(_plan_request(), None)

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.ISSUES_UNAVAILABLE


@pytest.mark.parametrize(
    ("message", "proposal"),
    [
        # extra text / second target / negation
        ("Disable web app /csp/broken now", _PROPOSAL),
        ("Disable web app /csp/broken and web app /csp/other", _PROPOSAL),
        ("Please disable web app /csp/broken", _PROPOSAL),
        ("Do not disable web app /csp/broken", _PROPOSAL),
        # conflicting names
        (_MESSAGE, "Disable web app /csp/other"),
        # enable requests
        ("Enable web app /csp/broken", _PROPOSAL),
        ("Enable web app /csp/broken", "Enable web app /csp/broken"),
    ],
)
def test_extra_text_conflicts_and_enable_requests_are_rejected(message: str, proposal: str) -> None:
    result = CopilotPlanningService().plan(_plan_request(message, proposal), _issues(_issue()))

    assert result.plan is None
    assert result.reason in {
        CopilotPlanningReason.UNSUPPORTED_ACTION,
        CopilotPlanningReason.NO_OPERATION_PROPOSED,
    }


@pytest.mark.parametrize(
    ("issue", "reason"),
    [
        (_issue("/api/admin"), CopilotPlanningReason.RESOURCE_PROTECTED),
        (_issue("/api/mgmnt/"), CopilotPlanningReason.RESOURCE_PROTECTED),
        (_issue(app_type="System,CSP"), CopilotPlanningReason.RESOURCE_PROTECTED),
        # Not protected, just not eligible: it's already disabled.
        (_issue(enabled=False), CopilotPlanningReason.UNSUPPORTED_ACTION),
    ],
)
def test_protected_system_or_disabled_apps_are_never_planned(
    issue: WebAppNamespaceIssue, reason: CopilotPlanningReason
) -> None:
    name = issue.web_app
    result = CopilotPlanningService().plan(
        _plan_request(f"Disable web app {name}", f"Disable web app {name}"), _issues(issue)
    )

    assert result.plan is None
    assert result.reason is reason


# --- execution ---


@pytest.mark.asyncio
async def test_execution_rebuilds_parameters_and_records_the_resolution() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result()
    plan = _plan()
    reader = AsyncMock(side_effect=[_issues(_issue()), _issues()])

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.SUCCESS
    assert result.execution_succeeded is True
    assert result.verification_succeeded is True
    assert "disabled" in result.detail
    request, context = executor.execute.await_args.args
    assert request == OperationRequest(
        operation_name="web_app.set_enabled",
        parameters={"Name": _APP, "Enabled": False},
        resolution_issue_type="web_app_namespace_missing",
    )
    assert context.confirmation_received is True
    assert context.dry_run is False


@pytest.mark.parametrize(
    ("plan", "detected"),
    [
        # no longer detected
        (_plan(), _issues()),
        # tampered Name
        (
            _plan().model_copy(
                update={"parameters": CopilotWebAppDisableParameters(Name="/api/admin")}
            ),
            _issues(_issue()),
        ),
        # tampered Enabled=true (bypassing validation)
        (
            _plan().model_copy(
                update={
                    "parameters": CopilotWebAppDisableParameters.model_construct(
                        Name=_APP, Enabled=True
                    )
                }
            ),
            _issues(_issue()),
        ),
        # tampered identifier
        (
            _plan().model_copy(
                update={"target": _plan().target.model_copy(update={"identifier": "/csp/other"})}
            ),
            _issues(_issue()),
        ),
        # issue_id of another (undetected) app
        (_plan(_issue("/csp/other")), _issues(_issue())),
    ],
)
@pytest.mark.asyncio
async def test_plans_not_matching_the_detected_issue_never_reach_the_executor(
    plan: CopilotOperationPlan, detected: IssuesResponse
) -> None:
    executor = AsyncMock(spec=OperationExecutor)

    with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=detected)):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_detection_never_reaches_the_executor() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    plan = _plan()
    reader = AsyncMock(side_effect=HTTPException(status_code=503))

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("authorization_update", "confirmed"),
    [
        ({}, False),
        ({"authorized": False, "ready_to_execute": False}, True),
        ({"requires_confirmation": True, "ready_to_execute": False}, True),
        ({"operation": CopilotOperation.DATABASE_MOUNT}, True),
    ],
)
@pytest.mark.asyncio
async def test_disable_needs_matching_authorization_and_confirmation(
    authorization_update: dict[str, object], confirmed: bool
) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    plan = _plan()
    reader = AsyncMock(return_value=_issues(_issue()))

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(
            plan, _authorization(plan).model_copy(update=authorization_update), confirmed=confirmed
        )

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue_still_detected_after_disable_is_a_verification_failure() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result()
    plan = _plan()

    with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=_issues(_issue()))):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.execution_succeeded is True
    assert result.verification_succeeded is False


@pytest.mark.asyncio
async def test_handler_verification_failure_is_not_success() -> None:
    # e.g. the handler found the Type changed after the PUT
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result(
        OperationResultStatus.VERIFICATION_FAILED,
        PostActionVerificationStatus.VERIFICATION_FAILED,
    )
    plan = _plan()
    reader = AsyncMock(side_effect=[_issues(_issue()), _issues()])

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.verification_succeeded is False
    assert reader.await_count == 1


@pytest.mark.asyncio
async def test_missing_secure_privilege_is_a_clear_failure_and_changes_nothing() -> None:
    client = AsyncMock()
    executor = OperationExecutor({"web_app.set_enabled": WebAppSetEnabledHandler(client)})
    plan = _plan()
    store.clear_traces()
    try:
        with patch(
            "app.copilot.execution.list_issues", new=AsyncMock(return_value=_issues(_issue()))
        ):
            result = await CopilotExecutionService(client, frozenset({"Manage"}), executor).execute(
                plan, _authorization(plan), confirmed=True
            )
    finally:
        store.clear_traces()

    assert result.status is CopilotExecutionStatus.EXECUTION_FAILED
    assert result.execution_succeeded is False
    assert "%Admin_Secure" in result.detail
    assert "Nothing was changed" in result.detail
    client.put.assert_not_awaited()
    client.post.assert_not_awaited()


# --- resolution history ---


class _DisabledHandler(OperationHandler):
    """Stands in for WebAppSetEnabledHandler; never touches IRIS."""

    def __init__(self) -> None:
        self.requests: list[OperationRequest] = []

    async def dry_run(self, request, context):
        raise AssertionError("Copilot never dry-runs before confirmation.")

    async def execute(self, request, context):
        self.requests.append(request)
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="disabled",
            data={"name": request.parameters["Name"], "enabled_before": True},
        )

    async def verify(self, request, context, execution_result):
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail="Enabled=false",
            evidence={"enabled": False},
        )


def test_trace_resolution_identity_matches_the_detected_issue() -> None:
    issue = _issue()
    context = trace_context(
        "web_app_namespace_missing", "web_app.set_enabled", {"Name": issue.web_app, "Enabled": False}
    )

    assert context is not None
    assert context.issue_id == issue.issue_id


@pytest.mark.asyncio
async def test_successful_disable_appears_in_the_issue_resolution_history() -> None:
    issue = _issue()
    plan = _plan(issue)
    handler = _DisabledHandler()
    executor = OperationExecutor({"web_app.set_enabled": handler})
    store.clear_traces()
    try:
        with patch(
            "app.copilot.execution.list_issues",
            new=AsyncMock(side_effect=[_issues(issue), _issues()]),
        ):
            result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)
        history = history_for_issue(issue.issue_id, store.list_traces())
    finally:
        store.clear_traces()

    assert result.status is CopilotExecutionStatus.SUCCESS
    assert [r.parameters for r in handler.requests] == [{"Name": _APP, "Enabled": False}]
    assert [entry.operation_name for entry in history.history] == ["web_app.set_enabled"]
    assert history.history[0].verification.status == "verified"


# --- shared catalog-backed structure (refactor regression) ---


@pytest.mark.parametrize("operation", list(CATALOG_OPERATIONS))
def test_catalog_operations_match_the_catalog_and_registry(operation: CopilotOperation) -> None:
    spec = CATALOG_OPERATIONS[operation]
    entry = ISSUE_CATALOG[spec.issue_type]
    definition = get_operation(operation.value)

    assert entry.operation == operation.value
    assert definition is not None
    assert definition.kind is OperationKind.MUTATING
    assert definition.confirmation_required is True


def test_only_the_expected_operations_are_catalog_backed() -> None:
    assert set(CATALOG_OPERATIONS) == {
        CopilotOperation.DATABASE_MOUNT,
        CopilotOperation.WEB_APP_SET_ENABLED,
    }


@pytest.mark.parametrize("kind", ["mount", "web_app"])
@pytest.mark.asyncio
async def test_shared_path_passes_each_operations_issue_type(kind: str) -> None:
    issue = _mount_issue() if kind == "mount" else _issue()
    plan = _mount_plan(issue) if kind == "mount" else _plan(issue)
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result()

    with patch(
        "app.copilot.execution.list_issues", new=AsyncMock(side_effect=[_issues(issue), _issues()])
    ):
        result = await _service(executor, frozenset({"Manage", "Operate", "Secure"})).execute(
            plan, _authorization(plan), confirmed=True
        )

    assert result.status is CopilotExecutionStatus.SUCCESS
    request = executor.execute.await_args.args[0]
    assert request.operation_name == plan.operation.value
    assert request.resolution_issue_type == issue.kind


@pytest.mark.parametrize("kind", ["mount", "web_app"])
@pytest.mark.asyncio
async def test_an_issue_of_another_type_never_matches(kind: str) -> None:
    # The detected issue has the plan's issue_id but the other operation's type.
    issue = _mount_issue() if kind == "mount" else _issue()
    other = _issue() if kind == "mount" else _mount_issue()
    plan = _mount_plan(issue) if kind == "mount" else _plan(issue)
    plan = plan.model_copy(
        update={"target": plan.target.model_copy(update={"issue_id": other.issue_id})}
    )
    executor = AsyncMock(spec=OperationExecutor)

    with patch("app.copilot.execution.list_issues", new=AsyncMock(return_value=_issues(other))):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()


# --- routes ---


def _plan_body(message: str = _MESSAGE, proposal: str = _PROPOSAL) -> dict[str, object]:
    return {
        "message": message,
        "intent": "resolution_request",
        "proposed_action": proposal,
        "requires_confirmation": True,
    }


def test_plan_endpoint_plans_disable_from_detection_without_mutation(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    issue = _issue()
    reader = AsyncMock(return_value=_issues(issue))
    with (
        patch("app.routes.copilot.list_issues", new=reader),
        patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute,
    ):
        response = client.post("/api/iris/copilot/plan", json=_plan_body())

    assert response.status_code == 200
    body = response.json()
    assert body["reason"] == "plan_created"
    assert body["plan"]["operation"] == "web_app.set_enabled"
    assert body["plan"]["target"] == {"kind": "web_app", "identifier": _APP, "issue_id": issue.issue_id}
    assert body["plan"]["parameters"] == {"Name": _APP, "Enabled": False}
    reader.assert_awaited_once_with(mock_iris_client)
    execute.assert_not_awaited()
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    mock_iris_client.delete.assert_not_awaited()


def test_enable_request_reads_no_issues_and_creates_no_plan(client: TestClient) -> None:
    reader = AsyncMock()
    with patch("app.routes.copilot.list_issues", new=reader):
        response = client.post(
            "/api/iris/copilot/plan",
            json=_plan_body("Enable web app /csp/broken", "Enable web app /csp/broken"),
        )

    assert response.status_code == 200
    assert response.json()["plan"] is None
    reader.assert_not_awaited()
