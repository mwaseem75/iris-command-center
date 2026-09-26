"""The AI Assistant's knowledge corpus, built entirely from the Command
Center's own, already-verified in-code registries:

- app/authorization/operations.py's OPERATION_REGISTRY — what each
  operation does, whether it mutates, its risk, the privileges it needs
  and whether it requires confirmation.
- app/capabilities.py's CAPABILITY_REGISTRY — which IRIS REST endpoints
  have been verified, under which privilege, and whether/how this backend
  exposes them.

Nothing here is hand-written or invented: every document is a plain-text
rendering of registry fields, so the corpus can never drift from the code
it describes. docs/*.md are deliberately not used (they lag the code).

Pure data: no IRIS call, no network I/O, no settings or credentials are
read — the registries contain only public metadata.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.authorization.operations import OPERATION_REGISTRY, OperationDefinition, OperationKind
from app.capabilities import CAPABILITY_REGISTRY, CapabilityEntry


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    source: Literal["operation", "capability"]
    title: str
    body: str


def _operation_document(operation: OperationDefinition) -> KnowledgeDocument:
    kind = "Read-only" if operation.kind is OperationKind.READ_ONLY else "Mutating"
    privileges = ", ".join(sorted(f"%Admin_{p.value}" for p in operation.required_privileges))
    confirmation = "required" if operation.confirmation_required else "not required"
    body = (
        f"{operation.description} "
        f"Kind: {kind}. Risk: {operation.risk_level.value}. "
        f"Requires any of: {privileges}. Confirmation: {confirmation}."
    )
    return KnowledgeDocument(
        doc_id=f"operation:{operation.name}",
        source="operation",
        title=f"Operation {operation.name}",
        body=body,
    )


def _capability_document(entry: CapabilityEntry) -> KnowledgeDocument:
    if entry.command_center_path:
        exposed = f"Command Center route: {entry.command_center_method or 'GET'} {entry.command_center_path}."
    else:
        exposed = "Not exposed as a Command Center route."
    body = (
        f"{entry.capability}. IRIS endpoint: {entry.method} {entry.endpoint}. "
        f"Required privilege: {entry.required_privilege}. "
        f"Verification: {entry.verification_status} ({entry.iris_version}). "
        f"{exposed} Notes: {entry.notes}"
    )
    return KnowledgeDocument(
        doc_id=f"capability:{entry.method} {entry.endpoint}",
        source="capability",
        title=entry.capability,
        body=body,
    )


def build_corpus() -> list[KnowledgeDocument]:
    """Every operation, then every capability, in registry order."""
    return [_operation_document(op) for op in OPERATION_REGISTRY.values()] + [
        _capability_document(entry) for entry in CAPABILITY_REGISTRY
    ]
