"""Authorization and explicit-confirmation gate for validated Copilot plans."""

from app.authorization.models import AuthorizationDenialReason
from app.authorization.operations import OperationKind, get_operation
from app.authorization.service import authorize
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotAuthorizationResult,
    CopilotOperationPlan,
)


class CopilotAuthorizationService:
    """Checks plans using existing authorization rules and never executes them."""

    def authorize_plan(
        self,
        plan: CopilotOperationPlan,
        available_privileges: frozenset[str],
        *,
        confirmed: bool,
    ) -> CopilotAuthorizationResult:
        definition = get_operation(plan.operation.value)
        if definition is None:
            return CopilotAuthorizationResult(
                authorized=False,
                requires_confirmation=False,
                ready_to_execute=False,
                reason=CopilotAuthorizationReason.UNKNOWN_OPERATION,
                required_privileges=[],
                operation=plan.operation,
                target=plan.target,
            )
        if definition.kind is not OperationKind.MUTATING:
            return CopilotAuthorizationResult(
                authorized=False,
                requires_confirmation=False,
                ready_to_execute=False,
                reason=CopilotAuthorizationReason.UNSUPPORTED_OPERATION,
                required_privileges=sorted(
                    privilege.value for privilege in definition.required_privileges
                ),
                operation=plan.operation,
                target=plan.target,
            )

        authorization = authorize(
            definition.name,
            available_privileges,
            confirmation_received=confirmed,
        )
        requires_confirmation = definition.confirmation_required and not confirmed
        ready_to_execute = (
            authorization.authorized
            and authorization.can_proceed
            and not requires_confirmation
        )

        if not authorization.authorized:
            reason = (
                CopilotAuthorizationReason.MISSING_PRIVILEGE
                if authorization.denial_reason is AuthorizationDenialReason.MISSING_PRIVILEGE
                else CopilotAuthorizationReason.UNKNOWN_OPERATION
            )
        elif requires_confirmation:
            reason = CopilotAuthorizationReason.CONFIRMATION_REQUIRED
        else:
            reason = CopilotAuthorizationReason.AUTHORIZED

        return CopilotAuthorizationResult(
            authorized=authorization.authorized,
            requires_confirmation=requires_confirmation,
            ready_to_execute=ready_to_execute,
            reason=reason,
            required_privileges=sorted(
                privilege.value for privilege in definition.required_privileges
            ),
            operation=plan.operation,
            target=plan.target,
        )
