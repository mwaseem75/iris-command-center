"""Guarded Copilot execution through the existing operation executor."""

from fastapi import HTTPException
from pydantic import ValidationError

from app.authorization.operations import OperationKind, get_operation
from app.copilot.authorization import CopilotAuthorizationService
from app.copilot.planner import CATALOG_OPERATIONS, CatalogOperation, catalog_parameters
from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.iris_client.client import IRISClient
from app.models.copilot import (
    CopilotAuthorizationResult,
    CopilotExecutionResult,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotTargetKind,
)
from app.routes.iris import get_journal_settings
from app.routes.issues import list_issues

_SUPPORTED_OPERATIONS = frozenset(
    {CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED, *CATALOG_OPERATIONS}
)


class _IssuesUnavailable(Exception):
    """The Issue Resolver detection couldn't be read."""


class CopilotExecutionService:
    """Executes allowlisted plans only after a passed authorization gate."""

    def __init__(
        self,
        client: IRISClient,
        available_privileges: frozenset[str],
        executor: OperationExecutor | None = None,
    ):
        self._client = client
        self._available_privileges = available_privileges
        self._executor = executor or OperationExecutor(
            {
                CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED.value: JournalUpdatePurgeArchivedHandler(client),
                CopilotOperation.DATABASE_MOUNT.value: DatabaseMountHandler(client),
                CopilotOperation.WEB_APP_SET_ENABLED.value: WebAppSetEnabledHandler(client),
            }
        )

    async def execute(
        self,
        plan: CopilotOperationPlan,
        authorization: CopilotAuthorizationResult,
        *,
        confirmed: bool,
    ) -> CopilotExecutionResult:
        if plan.operation not in _SUPPORTED_OPERATIONS:
            return self._rejected(plan, "This Copilot operation is not supported.")
        if not _target_matches_operation(plan):
            return self._rejected(plan, "The operation target is invalid.")
        if (
            authorization.operation is not plan.operation
            or authorization.target != plan.target
            or not authorization.authorized
            or authorization.requires_confirmation
            or not authorization.ready_to_execute
            or not confirmed
        ):
            return self._rejected(
                plan,
                "A matching authorization result and explicit confirmation are required.",
            )

        definition = get_operation(plan.operation.value)
        if definition is None or definition.kind is not OperationKind.MUTATING:
            return self._rejected(plan, "The operation is not registered as a mutation.")

        spec = CATALOG_OPERATIONS.get(plan.operation)
        if spec is not None:
            return await self._execute_catalog_resolution(plan, spec)

        failure = await self._run(
            plan,
            OperationRequest(
                operation_name=plan.operation.value,
                parameters={"PurgeArchived": plan.parameters.PurgeArchived},
            ),
        )
        if failure is not None:
            return failure

        try:
            settings = await get_journal_settings(self._client)
            actual = settings.result.PurgeArchived
        except (HTTPException, ValidationError):
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail="The operation ran, but the journal setting could not be re-read.",
            )

        expected = plan.parameters.PurgeArchived
        if actual is not expected:
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                verified_value=actual if isinstance(actual, bool) else None,
                detail="The journal setting does not match the requested value.",
            )
        return CopilotExecutionResult(
            operation=plan.operation,
            target=plan.target,
            status=CopilotExecutionStatus.SUCCESS,
            execution_succeeded=True,
            verification_succeeded=True,
            verified_value=actual,
            detail="The journal setting was updated and verified.",
        )

    async def _execute_catalog_resolution(
        self, plan: CopilotOperationPlan, spec: CatalogOperation
    ) -> CopilotExecutionResult:
        """Re-detect the issue, rebuild trusted parameters from it, then execute.

        The submitted plan only identifies the issue; nothing it carries is sent
        to IRIS unless it exactly matches what the catalog builds from the
        currently detected issue.
        """
        try:
            issue = await self._detected_issue(spec, plan.target.issue_id)
        except _IssuesUnavailable:
            return self._rejected(plan, "The detected issues could not be re-read. Nothing was executed.")
        if issue is None:
            return self._rejected(
                plan, "The Issue Resolver no longer detects this issue. Nothing was executed."
            )
        trusted = catalog_parameters(spec, issue)
        if (
            trusted is None
            or issue.resource.display_name != plan.target.identifier
            or trusted != plan.parameters
        ):
            return self._rejected(
                plan,
                "The plan does not match the currently detected issue. Nothing was executed.",
            )

        failure = await self._run(
            plan,
            OperationRequest(
                operation_name=spec.operation.value,
                parameters=trusted.model_dump(),
                resolution_issue_type=spec.issue_type,
            ),
        )
        if failure is not None:
            return failure

        try:
            still_detected = await self._detected_issue(spec, plan.target.issue_id)
        except _IssuesUnavailable:
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail=f"{spec.completed}, but the detected issues could not be re-read.",
            )
        if still_detected is not None:
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail="The operation was verified, but the Issue Resolver still detects the issue.",
            )
        return CopilotExecutionResult(
            operation=plan.operation,
            target=plan.target,
            status=CopilotExecutionStatus.SUCCESS,
            execution_succeeded=True,
            verification_succeeded=True,
            detail=f"{spec.completed} and the Issue Resolver no longer detects the issue.",
        )

    async def _detected_issue(self, spec: CatalogOperation, issue_id: str | None) -> object | None:
        try:
            response = await list_issues(self._client)
        except (HTTPException, ValidationError):
            raise _IssuesUnavailable from None
        return next(
            (
                issue
                for issue in response.issues
                if isinstance(issue, spec.issue_model) and issue.issue_id == issue_id
            ),
            None,
        )

    async def _run(
        self, plan: CopilotOperationPlan, request: OperationRequest
    ) -> CopilotExecutionResult | None:
        """Run the existing executor; a result means it didn't fully succeed."""
        try:
            operation_result = await self._executor.execute(
                request,
                ExecutionContext(
                    available_privileges=self._available_privileges,
                    confirmation_received=True,
                    dry_run=False,
                ),
            )
        except Exception:
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.EXECUTION_FAILED,
                execution_succeeded=False,
                verification_succeeded=False,
                detail="The existing operation executor failed unexpectedly.",
            )

        if operation_result.status is OperationResultStatus.VERIFICATION_FAILED:
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=(
                    operation_result.handler_result is not None
                    and operation_result.handler_result.outcome is HandlerOutcome.SUCCESS
                ),
                verification_succeeded=False,
                detail="The operation ran, but the executor could not verify its result.",
            )
        if operation_result.status is not OperationResultStatus.SUCCESS:
            handler_result = operation_result.handler_result
            missing_secure = (
                handler_result is not None
                and handler_result.data.get("missing_iris_privilege") == "Secure"
            )
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.EXECUTION_FAILED,
                execution_succeeded=False,
                verification_succeeded=False,
                detail=(
                    "IRIS requires the %Admin_Secure privilege for this change, and the current "
                    "session does not hold it. Nothing was changed."
                    if missing_secure
                    else "The existing operation did not complete successfully."
                ),
            )
        if (
            operation_result.handler_result is None
            or operation_result.handler_result.outcome is not HandlerOutcome.SUCCESS
            or operation_result.verification is None
            or operation_result.verification.status is not PostActionVerificationStatus.VERIFIED
        ):
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail="The operation ran, but its handler verification did not succeed.",
            )
        return None

    @staticmethod
    def _rejected(plan: CopilotOperationPlan, detail: str) -> CopilotExecutionResult:
        return CopilotExecutionResult(
            operation=plan.operation,
            target=plan.target,
            status=CopilotExecutionStatus.EXECUTION_REJECTED,
            execution_succeeded=False,
            verification_succeeded=False,
            detail=detail,
        )


def _target_matches_operation(plan: CopilotOperationPlan) -> bool:
    """Re-checked here because a plan can be built without validation."""
    if plan.operation is CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED:
        return (
            plan.target.kind is CopilotTargetKind.JOURNAL_SETTINGS
            and plan.target.identifier == "journal-settings"
            and isinstance(plan.parameters, CopilotOperationParameters)
        )
    spec = CATALOG_OPERATIONS.get(plan.operation)
    return (
        spec is not None
        and plan.target.kind is spec.target_kind
        and plan.target.issue_id is not None
        and isinstance(plan.parameters, spec.parameters_model)
    )
