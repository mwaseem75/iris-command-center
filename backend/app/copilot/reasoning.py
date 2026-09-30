"""Turn deterministic Copilot intents and bounded context into structured text."""

from app.copilot.ai import CopilotAIProvider
from app.copilot.intents import CopilotIntent
from app.models.copilot import (
    CopilotAIRequest,
    CopilotAskResponse,
    CopilotOperationalContext,
)


class CopilotReasoningService:
    def __init__(self, provider: CopilotAIProvider):
        self._provider = provider

    async def reason(
        self,
        message: str,
        intent: CopilotIntent,
        read_only_context: CopilotOperationalContext | None,
    ) -> CopilotAskResponse:
        if intent is CopilotIntent.UNKNOWN:
            return CopilotAskResponse(
                answer=(
                    "This request is outside the Copilot's supported operational scope. "
                    "Try asking about IRIS health, current operational state, or an issue."
                ),
                intent=intent.value,
            )
        if read_only_context is None:
            raise ValueError("Read-only context is required for supported Copilot intents.")

        request = CopilotAIRequest(
            message=message,
            intent=intent,
            context=read_only_context,
        )
        output = await self._provider.generate(request)
        return CopilotAskResponse(
            answer=output.answer,
            intent=intent.value,
            observations=output.observations,
            proposed_action=output.proposed_action,
            requires_confirmation=output.requires_confirmation,
        )
