"""Closed catalog of the operations the Copilot is approved to run.

This is the single source of truth for Copilot-approved operations: planning,
plan validation and execution all read it, and anything not listed here is
refused. It only adds what the Copilot needs on top of OPERATION_REGISTRY
(app/authorization/operations.py), which stays the source of each operation's
privileges, risk and confirmation rule, and ISSUE_CATALOG
(app/resolution/catalog.py), which stays the source of each issue's title,
severity and resolution details. describe_capabilities() joins the three for
discovery without copying their metadata here.

The catalog is checked when this module is imported, so a misconfigured
entry stops the backend from starting rather than being discovered later.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from app.authorization.operations import OperationKind, get_operation
from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.handler import OperationHandler
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.iris_client.client import IRISClient
from app.models.copilot import (
    CopilotCapabilitySummary,
    CopilotDatabaseMountParameters,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotTargetKind,
    CopilotWebAppDisableParameters,
)
from app.resolution.catalog import ISSUE_CATALOG


@dataclass(frozen=True)
class CopilotCapability:
    """One Copilot-approved operation."""

    operation: CopilotOperation
    target_kind: CopilotTargetKind
    parameters_model: type[BaseModel]
    handler_factory: Callable[[IRISClient], OperationHandler]
    # --- Descriptive metadata (discovery, explanation, confirmation) ---
    # Short, human-readable name of what the capability does.
    title: str
    # Requests a user can make to get this capability proposed.
    example_requests: tuple[str, ...]
    # The Copilot's own limits on the operation (beyond OPERATION_REGISTRY).
    constraints: tuple[str, ...]
    # What must hold before the Copilot reports success.
    verification: str
    # How the change is reversed, or None if it can't be.
    undo: str | None
    # The Issue Resolver issue this operation resolves, or None for a direct
    # setting request (the plan then targets a fixed identifier).
    issue_type: str | None = None
    target_identifier: str | None = None


COPILOT_CAPABILITIES: dict[CopilotOperation, CopilotCapability] = {
    CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED: CopilotCapability(
        operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
        target_kind=CopilotTargetKind.JOURNAL_SETTINGS,
        parameters_model=CopilotOperationParameters,
        handler_factory=JournalUpdatePurgeArchivedHandler,
        title="Set journal PurgeArchived",
        example_requests=("Enable PurgeArchived", "Disable PurgeArchived"),
        constraints=(
            "Only an explicit request for true or false.",
            "Always targets the instance's journal settings.",
        ),
        verification=(
            "The handler verifies the change, and a fresh read of the journal settings shows "
            "the requested PurgeArchived value."
        ),
        undo="Set PurgeArchived back to its previous value.",
        target_identifier="journal-settings",
    ),
    CopilotOperation.DATABASE_MOUNT: CopilotCapability(
        operation=CopilotOperation.DATABASE_MOUNT,
        target_kind=CopilotTargetKind.DATABASE,
        parameters_model=CopilotDatabaseMountParameters,
        handler_factory=DatabaseMountHandler,
        title="Mount a dismounted database",
        example_requests=("Mount database IPM", "Mount the IPM database"),
        constraints=(
            "Only a database the Issue Resolver currently detects as dismounted.",
            "Exactly one database per request; its name only selects the detected issue.",
            "Always mounted read-write; the directory comes from the detected issue.",
        ),
        verification=(
            "The handler reads Mounted = true for the database, and the Issue Resolver no longer "
            "detects the issue."
        ),
        undo="Dismount the database again from the Databases page (database.dismount).",
        issue_type="database_dismounted",
    ),
    CopilotOperation.WEB_APP_SET_ENABLED: CopilotCapability(
        operation=CopilotOperation.WEB_APP_SET_ENABLED,
        target_kind=CopilotTargetKind.WEB_APP,
        parameters_model=CopilotWebAppDisableParameters,
        handler_factory=WebAppSetEnabledHandler,
        title="Disable a web application whose namespace is missing",
        example_requests=("Disable web app /csp/example", "Disable the /csp/example web application"),
        constraints=(
            "Disable only; the Copilot never enables a web application.",
            "Only a web application the Issue Resolver currently detects with a missing namespace.",
            "Exactly one web application per request; its name only selects the detected issue.",
            "Never System web applications or the ones the Command Center itself uses.",
        ),
        verification=(
            "The handler reads the web application as disabled with its Type unchanged, and the "
            "Issue Resolver no longer detects the issue."
        ),
        undo="Re-enable the web application from the Web Applications page.",
        issue_type="web_app_namespace_missing",
    ),
}


def get_capability(operation: object) -> CopilotCapability | None:
    """The approved capability for `operation`, or None (callers deny)."""
    try:
        return COPILOT_CAPABILITIES.get(operation)  # type: ignore[arg-type]
    except TypeError:  # unhashable input
        return None


def describe_capabilities() -> list[CopilotCapabilitySummary]:
    """Public view of the catalog, in CopilotOperation order. Privileges, risk
    and confirmation are read from OPERATION_REGISTRY and the issue's title and
    severity from ISSUE_CATALOG; nothing is copied."""
    summaries = []
    for operation in CopilotOperation:
        capability = COPILOT_CAPABILITIES[operation]
        definition = get_operation(operation.value)
        assert definition is not None  # guaranteed by validate_capabilities
        issue = ISSUE_CATALOG[capability.issue_type] if capability.issue_type else None
        summaries.append(
            CopilotCapabilitySummary(
                operation=operation,
                title=capability.title,
                target_kind=capability.target_kind,
                issue_type=capability.issue_type,
                issue_title=issue.title if issue else None,
                issue_severity=issue.severity.value if issue else None,
                example_requests=list(capability.example_requests),
                constraints=list(capability.constraints),
                verification=capability.verification,
                undo=capability.undo,
                required_privileges=sorted(p.value for p in definition.required_privileges),
                risk_level=definition.risk_level,
                confirmation_required=definition.confirmation_required,
            )
        )
    return summaries


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_capabilities(catalog: Mapping[CopilotOperation, CopilotCapability]) -> None:
    """Raise ValueError unless `catalog` is a consistent, closed allowlist."""
    if set(catalog) != set(CopilotOperation):
        raise ValueError("Every CopilotOperation needs exactly one capability, and no others.")
    for operation, capability in catalog.items():
        if capability.operation is not operation:
            raise ValueError(f"Capability for {operation.value!r} names {capability.operation.value!r}.")
        definition = get_operation(operation.value)
        if (
            definition is None
            or definition.kind is not OperationKind.MUTATING
            or not definition.confirmation_required
        ):
            raise ValueError(
                f"{operation.value!r} must be a registered mutation that requires confirmation."
            )
        if (capability.issue_type is None) == (capability.target_identifier is None):
            raise ValueError(
                f"{operation.value!r} needs exactly one of issue_type or target_identifier."
            )
        if capability.issue_type is not None:
            entry = ISSUE_CATALOG.get(capability.issue_type)
            if entry is None or entry.operation != operation.value:
                raise ValueError(
                    f"{operation.value!r}: issue {capability.issue_type!r} is not resolved by it "
                    "in the Issue Resolution Catalog."
                )
        for field in ("example_requests", "constraints"):
            values = getattr(capability, field)
            if (
                not isinstance(values, tuple)
                or not values
                or not all(_nonblank(value) for value in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError(f"{operation.value!r}: {field} needs distinct, non-blank entries.")
        if not _nonblank(capability.title) or not _nonblank(capability.verification):
            raise ValueError(f"{operation.value!r} needs a title and a verification description.")
        if capability.undo is not None and not _nonblank(capability.undo):
            raise ValueError(f"{operation.value!r}: undo must be None or a non-blank description.")


validate_capabilities(COPILOT_CAPABILITIES)
