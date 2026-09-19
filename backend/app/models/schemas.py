"""Pydantic response models for the Command Center backend's own API.

These describe the Command Center's own responses, not IRIS's.
"""

from pydantic import BaseModel

from app.authorization.operations import OperationKind, RiskLevel


class HealthResponse(BaseModel):
    status: str


class OperationSummary(BaseModel):
    """Public, read-only view of one app.authorization.operations.OperationDefinition.

    This is the ONLY place operation metadata (name, description, required
    privileges, confirmation requirement) is serialized for API consumers —
    it is read directly off the existing OPERATION_REGISTRY, never
    duplicated or re-typed by hand.
    """

    name: str
    description: str
    kind: OperationKind
    required_privileges: list[str]
    risk_level: RiskLevel
    confirmation_required: bool


class OperationsListResponse(BaseModel):
    operations: list[OperationSummary]


class AssistantQueryResponse(BaseModel):
    """The AI Assistant's reply to one read-only natural-language question.

    `intent` is the classified intent name (see
    app.assistant.intents.Intent) — informational only, useful for tests
    and debugging; the frontend only displays `reply`.
    """

    reply: str
    intent: str
