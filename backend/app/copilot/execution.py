"""Guarded Copilot execution through the existing operation executor."""

from fastapi import HTTPException
from pydantic import ValidationError

from app.authorization.operations import OperationKind, get_operation
from app.copilot.authorization import CopilotAuthorizationService
from app.copilot.capabilities import COPILOT_CAPABILITIES, CopilotCapability, get_capability
from app.copilot.planner import CATALOG_OPERATIONS, CatalogOperation, catalog_parameters, is_protected
from app.copilot.trace import CopilotStage, CopilotTrace
from app.execution.executor import OperationExecutor
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
    CopilotFailure,
    CopilotOperationPlan,
)
from app.observability.store import get_trace
from app.routes.iris import get_journal_settings
from app.routes.issues import list_issues


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
                operation.value: capability.handler_factory(client)
                for operation, capability in COPILOT_CAPABILITIES.items()
            }
        )

    async def execute(
        self,
        plan: CopilotOperationPlan,
        authorization: CopilotAuthorizationResult,
        *,
        confirmed: bool,
    ) -> CopilotExecutionResult:
        """Run the plan and record the "copilot.execute" trace. The trace only
        observes: every decision is made by _execute as before."""
        trace = CopilotTrace("copilot.execute")
        plan_trace = get_trace(plan.trace_id) if plan.trace_id else None
        trace.stage(
            CopilotStage.REQUESTED,
            operation=plan.operation,
            target_kind=plan.target.kind,
            target=plan.target.identifier,
            # Linked only if that plan trace exists; an unknown id is ignored.
            plan_trace_id=(
                plan_trace.trace_id
                if plan_trace is not None and plan_trace.operation_name == "copilot.plan"
                else None
            ),
        )
        result = await self._execute(plan, authorization, confirmed=confirmed, trace=trace)
        trace.finish(CopilotStage.RESOLVED)
        # The API's failure is the trace's recorded failure: one code, one source.
        return result.model_copy(update={"trace_id": trace.trace_id, "failure": trace.failure})

    async def _execute(
        self,
        plan: CopilotOperationPlan,
        authorization: CopilotAuthorizationResult,
        *,
        confirmed: bool,
        trace: CopilotTrace,
    ) -> CopilotExecutionResult:
        capability = get_capability(plan.operation)
        if capability is None:
            trace.fail(CopilotFailure.PLAN_REJECTED, reason="unsupported_operation")
            return self._rejected(plan, "This Copilot operation is not supported.")
        if not _target_matches_operation(plan, capability):
            trace.fail(CopilotFailure.TARGET_CHANGED, reason="invalid_target")
            return self._rejected(plan, "The operation target is invalid.")
        if (
            authorization.operation is not plan.operation
            or authorization.target != plan.target
            or not authorization.authorized
            or authorization.requires_confirmation
            or not authorization.ready_to_execute
            or not confirmed
        ):
            # Classification only; the decision above is unchanged.
            if not confirmed:
                trace.set_result(confirmation_result="required_not_received")
                trace.fail(CopilotFailure.AUTHORIZATION_FAILED, reason="not_confirmed")
            elif not authorization.authorized:
                trace.set_result(confirmation_result="received", authorization_result="denied")
                trace.fail(CopilotFailure.AUTHORIZATION_FAILED, reason=authorization.reason)
            elif authorization.target != plan.target:
                trace.set_result(confirmation_result="received")
                trace.fail(CopilotFailure.TARGET_CHANGED, reason="authorized_target_differs")
            else:
                trace.set_result(confirmation_result="received")
                trace.fail(CopilotFailure.AUTHORIZATION_FAILED, reason="authorization_mismatch")
            return self._rejected(
                plan,
                "A matching authorization result and explicit confirmation are required.",
            )
        trace.set_result(confirmation_result="received", authorization_result="authorized")
        trace.stage(CopilotStage.CONFIRMATION_RECEIVED, confirmed=True)
        trace.stage(CopilotStage.AUTHORIZED, reason=authorization.reason)

        definition = get_operation(plan.operation.value)
        if definition is None or definition.kind is not OperationKind.MUTATING:
            trace.fail(CopilotFailure.PLAN_REJECTED, reason="not_a_registered_mutation")
            return self._rejected(plan, "The operation is not registered as a mutation.")

        if capability.issue_type is not None:
            return await self._execute_catalog_resolution(
                plan, CATALOG_OPERATIONS[capability.operation], trace
            )

        failure = await self._run(
            plan,
            OperationRequest(
                operation_name=plan.operation.value,
                parameters={"PurgeArchived": plan.parameters.PurgeArchived},
            ),
            trace,
        )
        if failure is not None:
            return failure

        try:
            settings = await get_journal_settings(self._client)
            actual = settings.result.PurgeArchived
        except (HTTPException, ValidationError):
            trace.set_result(verification_result="failed")
            trace.fail(CopilotFailure.VERIFICATION_FAILED, reason="setting_unreadable")
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
            trace.set_result(verification_result="failed")
            trace.fail(CopilotFailure.VERIFICATION_FAILED, reason="setting_mismatch", setting_matches=False)
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                verified_value=actual if isinstance(actual, bool) else None,
                detail="The journal setting does not match the requested value.",
            )
        trace.set_result(verification_result="verified")
        trace.stage(CopilotStage.VERIFICATION, handler_verification="verified", setting_matches=True)
        trace.stage(CopilotStage.RESOLVED)
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
        self, plan: CopilotOperationPlan, spec: CatalogOperation, trace: CopilotTrace
    ) -> CopilotExecutionResult:
        """Re-detect the issue, rebuild trusted parameters from it, then execute.

        The submitted plan only identifies the issue; nothing it carries is sent
        to IRIS unless it exactly matches what the catalog builds from the
        currently detected issue.
        """
        issue_attributes = {"issue_type": spec.issue_type, "issue_id": plan.target.issue_id}
        try:
            issue = await self._detected_issue(spec, plan.target.issue_id)
        except _IssuesUnavailable:
            trace.fail(CopilotFailure.ISSUE_NOT_DETECTED, reason="issues_unavailable", **issue_attributes)
            return self._rejected(plan, "The detected issues could not be re-read. Nothing was executed.")
        if issue is None:
            trace.fail(CopilotFailure.ISSUE_NOT_DETECTED, reason="no_longer_detected", **issue_attributes)
            return self._rejected(
                plan, "The Issue Resolver no longer detects this issue. Nothing was executed."
            )
        trusted = catalog_parameters(spec, issue)
        if (
            trusted is None
            or issue.resource.display_name != plan.target.identifier
            or trusted != plan.parameters
        ):
            # Classification only; the decision above is unchanged.
            if is_protected(spec, issue):
                trace.fail(CopilotFailure.RESOURCE_PROTECTED, **issue_attributes)
            elif trusted is not None and issue.resource.display_name != plan.target.identifier:
                trace.fail(CopilotFailure.TARGET_CHANGED, reason="identifier_differs", **issue_attributes)
            else:
                trace.fail(CopilotFailure.PARAMETER_MISMATCH, **issue_attributes)
            return self._rejected(
                plan,
                "The plan does not match the currently detected issue. Nothing was executed.",
            )
        trace.stage(CopilotStage.ISSUE_DETECTED, **issue_attributes)

        failure = await self._run(
            plan,
            OperationRequest(
                operation_name=spec.operation.value,
                parameters=trusted.model_dump(),
                resolution_issue_type=spec.issue_type,
            ),
            trace,
        )
        if failure is not None:
            return failure

        try:
            still_detected = await self._detected_issue(spec, plan.target.issue_id)
        except _IssuesUnavailable:
            trace.set_result(verification_result="failed")
            trace.fail(CopilotFailure.VERIFICATION_FAILED, reason="issues_unreadable", **issue_attributes)
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail=f"{spec.completed}, but the detected issues could not be re-read.",
            )
        if still_detected is not None:
            trace.set_result(verification_result="failed")
            trace.fail(CopilotFailure.ISSUE_STILL_DETECTED, issue_cleared=False, **issue_attributes)
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.VERIFICATION_FAILED,
                execution_succeeded=True,
                verification_succeeded=False,
                detail="The operation was verified, but the Issue Resolver still detects the issue.",
            )
        trace.set_result(verification_result="verified")
        trace.stage(
            CopilotStage.VERIFICATION, handler_verification="verified", issue_cleared=True, **issue_attributes
        )
        trace.stage(CopilotStage.RESOLVED, **issue_attributes)
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
        self, plan: CopilotOperationPlan, request: OperationRequest, trace: CopilotTrace
    ) -> CopilotExecutionResult | None:
        """Run the existing executor; a result means it didn't fully succeed."""
        trace.stage(CopilotStage.EXECUTING, operation=request.operation_name)
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
            trace.set_result(execution_result="failed")
            trace.fail(CopilotFailure.EXECUTION_FAILED, reason="executor_error")
            return CopilotExecutionResult(
                operation=plan.operation,
                target=plan.target,
                status=CopilotExecutionStatus.EXECUTION_FAILED,
                execution_succeeded=False,
                verification_succeeded=False,
                detail="The existing operation executor failed unexpectedly.",
            )

        # Link to the executor's own trace (informational only).
        executed = {
            "operation_status": operation_result.status,
            "operation_trace_id": operation_result.trace_id,
        }
        if operation_result.status is OperationResultStatus.VERIFICATION_FAILED:
            trace.set_result(execution_result="success", verification_result="failed")
            trace.stage(CopilotStage.EXECUTED, **executed)
            trace.fail(CopilotFailure.VERIFICATION_FAILED, reason="executor_verification")
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
            trace.set_result(execution_result="failed")
            # Classification from the handler's own structured refusal data.
            if missing_secure:
                trace.fail(CopilotFailure.AUTHORIZATION_FAILED, reason="missing_admin_secure", **executed)
            elif handler_result is not None and handler_result.data.get("protected") is True:
                trace.fail(CopilotFailure.RESOURCE_PROTECTED, reason="handler_protected", **executed)
            else:
                trace.fail(CopilotFailure.EXECUTION_FAILED, reason="operation_not_successful", **executed)
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
        trace.set_result(execution_result="success")
        trace.stage(CopilotStage.EXECUTED, **executed)
        if (
            operation_result.handler_result is None
            or operation_result.handler_result.outcome is not HandlerOutcome.SUCCESS
            or operation_result.verification is None
            or operation_result.verification.status is not PostActionVerificationStatus.VERIFIED
        ):
            trace.set_result(verification_result="failed")
            trace.fail(CopilotFailure.VERIFICATION_FAILED, reason="handler_verification")
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


def _target_matches_operation(plan: CopilotOperationPlan, capability: CopilotCapability) -> bool:
    """Re-checked here because a plan can be built without validation."""
    if plan.target.kind is not capability.target_kind or not isinstance(
        plan.parameters, capability.parameters_model
    ):
        return False
    if capability.issue_type is None:
        return plan.target.identifier == capability.target_identifier
    return plan.target.issue_id is not None
