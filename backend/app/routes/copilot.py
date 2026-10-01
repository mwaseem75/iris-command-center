"""Classification-only endpoint for the AI Operations Copilot."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.copilot.context import CopilotContextService
from app.copilot.ai import CopilotAIProvider, create_copilot_provider
from app.copilot.authorization import CopilotAuthorizationService
from app.copilot.capabilities import describe_capabilities
from app.copilot.execution import CopilotExecutionService
from app.copilot.intents import CopilotIntent, classify_intent, is_task_detail_question
from app.copilot.planner import CatalogOperation, CopilotPlanningService, catalog_operation_for
from app.copilot.reasoning import CopilotReasoningService
from app.dependencies import get_caller_privileges, get_iris_client, get_read_client
from app.iris_client.client import IRISClient
from app.models.copilot import (
    CopilotAskResponse,
    CopilotAuthorizationRequest,
    CopilotAuthorizationResult,
    CopilotCapabilitiesResponse,
    CopilotExecutionRequest,
    CopilotExecutionResult,
    CopilotFailure,
    CopilotOperationalContext,
    CopilotPlanRequest,
    CopilotPlanningResult,
)
from app.copilot.trace import CopilotStage, CopilotTrace
from app.routes.issues import IssuesResponse, list_issues

router = APIRouter(prefix="/api/iris/copilot", tags=["copilot"])


class CopilotClassifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(..., min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank.")
        return value


class CopilotClassifyResponse(BaseModel):
    intent: CopilotIntent


def get_copilot_ai_provider() -> CopilotAIProvider:
    return create_copilot_provider()


@router.post("/classify", response_model=CopilotClassifyResponse)
async def classify_copilot_request(body: CopilotClassifyRequest) -> CopilotClassifyResponse:
    return CopilotClassifyResponse(intent=classify_intent(body.message))


@router.get("/capabilities", response_model=CopilotCapabilitiesResponse)
async def list_copilot_capabilities() -> CopilotCapabilitiesResponse:
    """The closed catalog of operations the Copilot may propose. Read-only; no IRIS call."""
    return CopilotCapabilitiesResponse(capabilities=describe_capabilities())


@router.get("/context", response_model=CopilotOperationalContext)
async def get_copilot_context(
    client: IRISClient = Depends(get_read_client),
) -> CopilotOperationalContext:
    return await CopilotContextService(client).get_context()


@router.post("/ask", response_model=CopilotAskResponse)
async def ask_copilot(
    body: CopilotClassifyRequest,
    client: IRISClient = Depends(get_read_client),
    provider: CopilotAIProvider = Depends(get_copilot_ai_provider),
) -> CopilotAskResponse:
    intent = classify_intent(body.message)
    reasoning = CopilotReasoningService(provider)
    if intent is CopilotIntent.UNKNOWN:
        return await reasoning.reason(body.message, intent, None)
    # Task details cost one IRIS call per task; read them only when asked for.
    context = await CopilotContextService(client).get_context(
        task_details=is_task_detail_question(body.message)
    )
    return await reasoning.reason(body.message, intent, context)


@router.post("/plan", response_model=CopilotPlanningResult)
async def plan_copilot_operation(
    body: CopilotPlanRequest,
    client: IRISClient = Depends(get_iris_client),
) -> CopilotPlanningResult:
    # Only a catalog-backed proposal needs the current (read-only) issue
    # detection; the plan's target and parameters come from it.
    issues = None
    spec = catalog_operation_for(body)
    if spec is not None:
        try:
            issues = await list_issues(client)
        except (HTTPException, ValidationError):
            issues = None
    result = CopilotPlanningService().plan(body, issues)
    if result.intent is not CopilotIntent.RESOLUTION_REQUEST:
        return result  # only change requests are traced
    return _record_plan_trace(body, result, spec, issues)


def _record_plan_trace(
    body: CopilotPlanRequest,
    result: CopilotPlanningResult,
    spec: CatalogOperation | None,
    issues: IssuesResponse | None,
) -> CopilotPlanningResult:
    """Record the "copilot.plan" trace; the plan returned carries its id."""
    trace = CopilotTrace("copilot.plan")
    # Never the message text itself: only its length.
    trace.stage(CopilotStage.REQUESTED, message_length=len(body.message))
    trace.stage(CopilotStage.CLASSIFIED, intent=result.intent)
    plan = result.plan
    if spec is not None and issues is not None:
        detected = sum(1 for issue in issues.issues if issue.kind == spec.issue_type)
        attributes = {
            "issue_type": spec.issue_type,
            "issues_detected": detected,
            "issue_id": plan.target.issue_id if plan else None,
        }
        trace.stage(CopilotStage.ISSUE_DETECTED, error=plan is None, **attributes)
    if plan is None:
        trace.fail(CopilotFailure.PLAN_REJECTED, reason=result.reason)
        trace.finish(CopilotStage.PLAN_CREATED)  # status becomes plan_rejected
        return result
    trace.stage(
        CopilotStage.PLAN_CREATED,
        operation=plan.operation,
        target_kind=plan.target.kind,
        target=plan.target.identifier,
    )
    trace.stage(CopilotStage.CONFIRMATION_REQUIRED, confirmation_required=plan.requires_confirmation)
    trace.finish(CopilotStage.PLAN_CREATED)
    return result.model_copy(update={"plan": plan.model_copy(update={"trace_id": trace.trace_id})})


@router.post("/authorize", response_model=CopilotAuthorizationResult)
async def authorize_copilot_plan(
    body: CopilotAuthorizationRequest,
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> CopilotAuthorizationResult:
    return CopilotAuthorizationService().authorize_plan(
        body.plan,
        privileges,
        confirmed=body.confirmed,
    )


@router.post("/execute", response_model=CopilotExecutionResult)
async def execute_copilot_plan(
    body: CopilotExecutionRequest,
    client: IRISClient = Depends(get_iris_client),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> CopilotExecutionResult:
    execution = CopilotExecutionService(client, privileges)
    submitted = body.authorization
    if (
        not submitted.authorized
        or submitted.requires_confirmation
        or not submitted.ready_to_execute
        or submitted.operation is not body.plan.operation
        or submitted.target != body.plan.target
        or not body.confirmed
    ):
        return await execution.execute(body.plan, submitted, confirmed=body.confirmed)

    authorization = CopilotAuthorizationService().authorize_plan(
        body.plan,
        privileges,
        confirmed=True,
    )
    return await execution.execute(body.plan, authorization, confirmed=True)
