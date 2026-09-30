"""Phase 5b: Copilot database.mount for a detected database_dismounted issue.

Everything is mocked: no IRIS call, no real mount. The Issue Resolver
detection (`list_issues`) is patched; the catalog is the real one.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.copilot.ai import DeterministicCopilotProvider
from app.copilot.execution import CopilotExecutionService
from app.copilot.intents import CopilotIntent, classify_intent
from app.copilot.planner import CopilotPlanningService
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
from app.models.copilot import (
    CopilotAIRequest,
    CopilotAuthorizationReason,
    CopilotAuthorizationResult,
    CopilotDatabaseMountParameters,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationalContext,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotPlanRequest,
    CopilotPlanningReason,
    CopilotTargetKind,
)
from app.observability import store
from app.resolution.catalog import ISSUE_CATALOG, trace_context
from app.resolution.history import history_for_issue
from app.resolution.identity import ResolutionReadiness, issue_identity
from app.routes.issues import DatabaseMountIssue, IssuesResponse

_IPM_DIRECTORY = "/usr/irissys/mgr/zpm/"
_MESSAGE = "Mount the IPM database."
_PROPOSAL = "Mount database IPM"


def _issue(
    name: str = "IPM",
    directory: str = _IPM_DIRECTORY,
    *,
    mirrored: bool = False,
) -> DatabaseMountIssue:
    return DatabaseMountIssue(
        **issue_identity("database_dismounted", "database", directory.rstrip("/"), name),
        readiness=ResolutionReadiness.READY_TO_CHECK,
        database=name,
        directory=directory,
        status="Dismounted",
        mount_required=False,
        mount_at_startup=False,
        mirrored=mirrored,
        affected_namespaces=[],
        explanation=f"Database {name} is dismounted.",
        parameters={"Directory": directory, "ReadOnly": False},
    )


def _issues(*issues: DatabaseMountIssue) -> IssuesResponse:
    return IssuesResponse(issues=list(issues), resolutions=dict(ISSUE_CATALOG))


def _plan_request(message: str = _MESSAGE, proposal: str | None = _PROPOSAL) -> CopilotPlanRequest:
    return CopilotPlanRequest(
        message=message,
        intent=classify_intent(message),
        proposed_action=proposal,
        requires_confirmation=True,
    )


def _plan(issue: DatabaseMountIssue | None = None) -> CopilotOperationPlan:
    issue = issue or _issue()
    return CopilotOperationPlan(
        operation=CopilotOperation.DATABASE_MOUNT,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.DATABASE,
            identifier=issue.resource.display_name,
            issue_id=issue.issue_id,
        ),
        parameters=CopilotDatabaseMountParameters(Directory=issue.directory, ReadOnly=False),
        reason="Detected.",
        requires_confirmation=True,
    )


def _authorization(plan: CopilotOperationPlan) -> CopilotAuthorizationResult:
    return CopilotAuthorizationResult(
        authorized=True,
        requires_confirmation=False,
        ready_to_execute=True,
        reason=CopilotAuthorizationReason.AUTHORIZED,
        required_privileges=["Operate"],
        operation=plan.operation,
        target=plan.target,
    )


def _operation_result(
    status: OperationResultStatus = OperationResultStatus.SUCCESS,
    verification: PostActionVerificationStatus = PostActionVerificationStatus.VERIFIED,
) -> OperationResult:
    return OperationResult(
        operation_name="database.mount",
        status=status,
        handler_result=HandlerExecutionResult(outcome=HandlerOutcome.SUCCESS, detail="mounted"),
        verification=PostActionVerificationResult(status=verification, detail="Mounted=True"),
        detail="executor result",
    )


# --- models ---


@pytest.mark.parametrize(
    "plan_data",
    [
        # mount operation with journal parameters
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
            "parameters": {"PurgeArchived": True},
        },
        # journal operation with mount parameters
        {
            "operation": "journal.update_purge_archived",
            "target": {"kind": "journal_settings", "identifier": "journal-settings"},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": False},
        },
        # database target without a detected issue
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM"},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": False},
        },
        # malformed issue id
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "not-a-hash"},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": False},
        },
        # read-only mount
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": True},
        },
        # non-boolean ReadOnly
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": "false"},
        },
        # extra parameter
        {
            "operation": "database.mount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": False, "Cluster": True},
        },
        # journal target carrying an issue id
        {
            "operation": "journal.update_purge_archived",
            "target": {"kind": "journal_settings", "identifier": "journal-settings", "issue_id": "a" * 64},
            "parameters": {"PurgeArchived": True},
        },
        # still-unsupported operation
        {
            "operation": "database.dismount",
            "target": {"kind": "database", "identifier": "IPM", "issue_id": "a" * 64},
            "parameters": {"Directory": _IPM_DIRECTORY, "ReadOnly": False},
        },
    ],
)
def test_malformed_or_mismatched_mount_plans_are_rejected(plan_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(
            {"reason": "test", "requires_confirmation": True, **plan_data}
        )


# --- deterministic provider ---


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Mount the IPM database.", "Mount database IPM"),
        ("mount database IPM", "Mount database IPM"),
        ("Mount database /usr/irissys/mgr/zpm/", None),
        ("Mount the database", None),
        ("Dismount the IPM database", None),
    ],
)
@pytest.mark.asyncio
async def test_deterministic_provider_mount_proposal_is_text_only(
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


def test_plan_is_built_from_the_detected_issue_and_catalog() -> None:
    issue = _issue()

    result = CopilotPlanningService().plan(_plan_request(), _issues(issue))

    assert result.reason is CopilotPlanningReason.PLAN_CREATED
    plan = result.plan
    assert plan is not None
    assert plan.operation is CopilotOperation.DATABASE_MOUNT
    assert plan.target == CopilotOperationTarget(
        kind=CopilotTargetKind.DATABASE, identifier="IPM", issue_id=issue.issue_id
    )
    assert plan.parameters == CopilotDatabaseMountParameters(Directory=_IPM_DIRECTORY, ReadOnly=False)
    assert plan.requires_confirmation is True


def test_database_name_selects_case_insensitively() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("mount the ipm database", "Mount database ipm"), _issues(_issue())
    )

    assert result.plan is not None
    assert result.plan.target.identifier == "IPM"


def test_directory_in_the_message_is_never_used() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("Mount the IPM database from /tmp/evil/", _PROPOSAL), _issues(_issue())
    )

    assert result.plan is not None
    assert result.plan.parameters.Directory == _IPM_DIRECTORY
    assert "/tmp/evil" not in result.plan.model_dump_json()


def test_directory_as_proposal_is_not_a_mount_plan() -> None:
    result = CopilotPlanningService().plan(
        _plan_request(_MESSAGE, "Mount database /tmp/evil/"), _issues(_issue())
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


def test_undetected_database_is_rejected() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("Mount the USER database", "Mount database USER"), _issues(_issue())
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.ISSUE_NOT_DETECTED


def test_ambiguous_database_name_is_rejected() -> None:
    result = CopilotPlanningService().plan(
        _plan_request(), _issues(_issue(), _issue(directory="/other/zpm/"))
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.AMBIGUOUS_TARGET


def test_unavailable_issue_detection_is_rejected() -> None:
    result = CopilotPlanningService().plan(_plan_request(), None)

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.ISSUES_UNAVAILABLE


@pytest.mark.parametrize(
    ("message", "proposal"),
    [
        ("Mount the IPM database", "Mount database USER"),
        ("Mount the IPM database and the USER database", _PROPOSAL),
        ("Mount the IPM and USER databases", _PROPOSAL),
        ("Do not mount the IPM database", _PROPOSAL),
    ],
)
def test_message_and_proposal_must_name_one_same_database(message: str, proposal: str) -> None:
    result = CopilotPlanningService().plan(_plan_request(message, proposal), _issues(_issue()))

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


@pytest.mark.parametrize(
    "issue",
    [_issue("IRISSYS", "/usr/irissys/mgr/"), _issue(mirrored=True)],
)
def test_system_or_mirrored_databases_are_never_planned(issue: DatabaseMountIssue) -> None:
    name = issue.database
    result = CopilotPlanningService().plan(
        _plan_request(f"Mount the {name} database", f"Mount database {name}"), _issues(issue)
    )

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.RESOURCE_PROTECTED


def test_purge_archived_planning_ignores_issue_detection() -> None:
    result = CopilotPlanningService().plan(
        _plan_request("Enable PurgeArchived.", "Set PurgeArchived to true"), None
    )

    assert result.reason is CopilotPlanningReason.PLAN_CREATED
    assert result.plan is not None
    assert result.plan.operation is CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED
    assert result.plan.parameters == CopilotOperationParameters(PurgeArchived=True)


# --- execution ---


def _service(executor: object) -> CopilotExecutionService:
    return CopilotExecutionService(AsyncMock(), frozenset({"Operate"}), executor)


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
    request, context = executor.execute.await_args.args
    assert request == OperationRequest(
        operation_name="database.mount",
        parameters={"Directory": _IPM_DIRECTORY, "ReadOnly": False},
        resolution_issue_type="database_dismounted",
    )
    assert context.confirmation_received is True
    assert context.dry_run is False
    assert reader.await_count == 2


@pytest.mark.parametrize(
    ("plan", "detected"),
    [
        # the issue is no longer detected
        (_plan(), _issues()),
        # tampered Directory
        (
            _plan().model_copy(
                update={"parameters": CopilotDatabaseMountParameters(Directory="/tmp/evil/")}
            ),
            _issues(_issue()),
        ),
        # issue_id of a different (undetected) issue
        (_plan(_issue(directory="/other/zpm/")), _issues(_issue())),
        # tampered identifier
        (
            _plan().model_copy(
                update={"target": _plan().target.model_copy(update={"identifier": "USER"})}
            ),
            _issues(_issue()),
        ),
        # tampered ReadOnly (bypassing validation)
        (
            _plan().model_copy(
                update={
                    "parameters": CopilotDatabaseMountParameters.model_construct(
                        Directory=_IPM_DIRECTORY, ReadOnly=True
                    )
                }
            ),
            _issues(_issue()),
        ),
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
    assert result.execution_succeeded is False
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_issue_detection_never_reaches_the_executor() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    plan = _plan()
    reader = AsyncMock(side_effect=HTTPException(status_code=503, detail="IRIS unavailable"))

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
        ({"operation": CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED}, True),
    ],
)
@pytest.mark.asyncio
async def test_mount_needs_matching_authorization_and_confirmation(
    authorization_update: dict[str, object], confirmed: bool
) -> None:
    executor = AsyncMock(spec=OperationExecutor)
    plan = _plan()
    authorization = _authorization(plan).model_copy(update=authorization_update)
    reader = AsyncMock(return_value=_issues(_issue()))

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, authorization, confirmed=confirmed)

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    executor.execute.assert_not_awaited()
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue_still_detected_after_mount_is_a_verification_failure() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result()
    plan = _plan()
    reader = AsyncMock(return_value=_issues(_issue()))

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.execution_succeeded is True
    assert result.verification_succeeded is False
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unreadable_issues_after_mount_is_a_verification_failure() -> None:
    executor = AsyncMock(spec=OperationExecutor)
    executor.execute.return_value = _operation_result()
    plan = _plan()
    reader = AsyncMock(side_effect=[_issues(_issue()), HTTPException(status_code=503)])

    with patch("app.copilot.execution.list_issues", new=reader):
        result = await _service(executor).execute(plan, _authorization(plan), confirmed=True)

    assert result.status is CopilotExecutionStatus.VERIFICATION_FAILED
    assert result.execution_succeeded is True
    assert result.verification_succeeded is False


@pytest.mark.asyncio
async def test_handler_verification_failure_is_not_success() -> None:
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


# --- resolution history ---


class _MountedHandler(OperationHandler):
    """Stands in for DatabaseMountHandler; never touches IRIS."""

    def __init__(self) -> None:
        self.requests: list[OperationRequest] = []

    async def dry_run(self, request, context):
        raise AssertionError("Copilot never dry-runs before confirmation.")

    async def execute(self, request, context):
        self.requests.append(request)
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail="mounted",
            data={"directory": request.parameters["Directory"], "mounted_before": False},
        )

    async def verify(self, request, context, execution_result):
        return PostActionVerificationResult(
            status=PostActionVerificationStatus.VERIFIED,
            detail="Mounted=True",
            evidence={"mounted": True},
        )


def test_trace_resolution_identity_matches_the_detected_issue() -> None:
    issue = _issue()
    context = trace_context(
        "database_dismounted", "database.mount", {"Directory": issue.directory, "ReadOnly": False}
    )

    assert context is not None
    assert context.issue_id == issue.issue_id


@pytest.mark.asyncio
async def test_successful_mount_appears_in_the_issue_resolution_history() -> None:
    issue = _issue()
    plan = _plan(issue)
    handler = _MountedHandler()
    executor = OperationExecutor({"database.mount": handler})
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
    assert len(handler.requests) == 1
    assert [entry.operation_name for entry in history.history] == ["database.mount"]
    assert history.history[0].verification.status == "verified"


# --- routes ---


def _plan_body(message: str = _MESSAGE, proposal: str = _PROPOSAL) -> dict[str, object]:
    return {
        "message": message,
        "intent": "resolution_request",
        "proposed_action": proposal,
        "requires_confirmation": True,
    }


def test_plan_endpoint_plans_mount_from_detection_without_mutation(
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
    assert body["plan"]["operation"] == "database.mount"
    assert body["plan"]["target"] == {"kind": "database", "identifier": "IPM", "issue_id": issue.issue_id}
    assert body["plan"]["parameters"] == {"Directory": _IPM_DIRECTORY, "ReadOnly": False}
    reader.assert_awaited_once_with(mock_iris_client)
    execute.assert_not_awaited()
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    mock_iris_client.delete.assert_not_awaited()


def test_plan_endpoint_reports_unavailable_detection(client: TestClient) -> None:
    reader = AsyncMock(side_effect=HTTPException(status_code=503))
    with patch("app.routes.copilot.list_issues", new=reader):
        response = client.post("/api/iris/copilot/plan", json=_plan_body())

    assert response.status_code == 200
    assert response.json() == {
        "intent": "resolution_request",
        "plan": None,
        "reason": "issues_unavailable",
    }


def test_purge_archived_plan_endpoint_does_not_read_issues(client: TestClient) -> None:
    reader = AsyncMock()
    with patch("app.routes.copilot.list_issues", new=reader):
        response = client.post(
            "/api/iris/copilot/plan",
            json=_plan_body("Enable PurgeArchived.", "Set PurgeArchived to true"),
        )

    assert response.status_code == 200
    assert response.json()["plan"]["operation"] == "journal.update_purge_archived"
    reader.assert_not_awaited()
