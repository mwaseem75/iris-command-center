"""Classification-only endpoint for the AI Operations Copilot."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.copilot.context import CopilotContextService
from app.copilot.ai import CopilotAIProvider, create_copilot_provider
from app.copilot.authorization import CopilotAuthorizationService
from app.copilot.execution import CopilotExecutionService
from app.copilot.intents import CopilotIntent, classify_intent
from app.copilot.planner import CopilotPlanningService, catalog_operation_for
from app.copilot.reasoning import CopilotReasoningService
from app.dependencies import get_caller_privileges, get_iris_client
from app.iris_client.client import IRISClient
from app.models.copilot import (
    CopilotAskResponse,
    CopilotAuthorizationRequest,
    CopilotAuthorizationResult,
    CopilotExecutionRequest,
    CopilotExecutionResult,
    CopilotOperationalContext,
    CopilotPlanRequest,
    CopilotPlanningResult,
)
from app.routes.issues import list_issues

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


@router.get("/context", response_model=CopilotOperationalContext)
async def get_copilot_context(
    client: IRISClient = Depends(get_iris_client),
) -> CopilotOperationalContext:
    return await CopilotContextService(client).get_context()


@router.post("/ask", response_model=CopilotAskResponse)
async def ask_copilot(
    body: CopilotClassifyRequest,
    client: IRISClient = Depends(get_iris_client),
    provider: CopilotAIProvider = Depends(get_copilot_ai_provider),
) -> CopilotAskResponse:
    intent = classify_intent(body.message)
    reasoning = CopilotReasoningService(provider)
    if intent is CopilotIntent.UNKNOWN:
        return await reasoning.reason(body.message, intent, None)
    context = await CopilotContextService(client).get_context()
    return await reasoning.reason(body.message, intent, context)


@router.post("/plan", response_model=CopilotPlanningResult)
async def plan_copilot_operation(
    body: CopilotPlanRequest,
    client: IRISClient = Depends(get_iris_client),
) -> CopilotPlanningResult:
    # Only a catalog-backed proposal needs the current (read-only) issue
    # detection; the plan's target and parameters come from it.
    issues = None
    if catalog_operation_for(body) is not None:
        try:
            issues = await list_issues(client)
        except (HTTPException, ValidationError):
            issues = None
    return CopilotPlanningService().plan(body, issues)


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
