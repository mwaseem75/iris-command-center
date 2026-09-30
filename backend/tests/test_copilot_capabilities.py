"""Phase 3.5a: COPILOT_CAPABILITIES is the single, closed Copilot allowlist.

Everything is mocked: no IRIS call and no real operation.
"""

from dataclasses import fields, replace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authorization.operations import (
    OPERATION_REGISTRY,
    OperationDefinition,
    OperationKind,
    RiskLevel,
)
from app.authorization.privileges import IRISPrivilege
from app.copilot import capabilities as capabilities_module
from app.copilot.capabilities import (
    COPILOT_CAPABILITIES,
    CopilotCapability,
    describe_capabilities,
    get_capability,
    validate_capabilities,
)
from app.copilot.execution import CopilotExecutionService
from app.copilot.intents import CopilotIntent, classify_intent
from app.copilot.planner import CATALOG_OPERATIONS, CopilotPlanningService
from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.models.copilot import (
    CopilotAuthorizationReason,
    CopilotAuthorizationResult,
    CopilotExecutionStatus,
    CopilotOperation,
    CopilotOperationParameters,
    CopilotOperationPlan,
    CopilotOperationTarget,
    CopilotPlanRequest,
    CopilotPlanningReason,
    CopilotTargetKind,
    CopilotWebAppDisableParameters,
)
from app.resolution.catalog import ISSUE_CATALOG

_APPROVED = {"journal.update_purge_archived", "database.mount", "web_app.set_enabled"}


# --- the catalog itself ---


def test_catalog_is_closed_to_exactly_the_three_approved_operations() -> None:
    assert {operation.value for operation in COPILOT_CAPABILITIES} == _APPROVED
    assert set(COPILOT_CAPABILITIES) == set(CopilotOperation)
    for operation, capability in COPILOT_CAPABILITIES.items():
        assert capability.operation is operation


@pytest.mark.parametrize("operation", list(CopilotOperation))
def test_every_capability_is_a_registered_confirmed_mutation(operation: CopilotOperation) -> None:
    definition = OPERATION_REGISTRY[operation.value]

    assert definition.kind is OperationKind.MUTATING
    assert definition.confirmation_required is True


def test_issue_backed_capabilities_agree_with_the_issue_catalog() -> None:
    issue_backed = {
        operation.value: capability.issue_type
        for operation, capability in COPILOT_CAPABILITIES.items()
        if capability.issue_type is not None
    }

    assert issue_backed == {
        "database.mount": "database_dismounted",
        "web_app.set_enabled": "web_app_namespace_missing",
    }
    for operation, issue_type in issue_backed.items():
        assert ISSUE_CATALOG[issue_type].operation == operation
    purge = COPILOT_CAPABILITIES[CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED]
    assert purge.issue_type is None
    assert purge.target_identifier == "journal-settings"


def test_each_capability_builds_its_existing_handler() -> None:
    client = AsyncMock()
    expected = {
        CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED: JournalUpdatePurgeArchivedHandler,
        CopilotOperation.DATABASE_MOUNT: DatabaseMountHandler,
        CopilotOperation.WEB_APP_SET_ENABLED: WebAppSetEnabledHandler,
    }
    for operation, handler_class in expected.items():
        assert isinstance(COPILOT_CAPABILITIES[operation].handler_factory(client), handler_class)


def test_execution_registers_exactly_the_catalog_handlers() -> None:
    service = CopilotExecutionService(AsyncMock(), frozenset())

    assert set(service._executor._handlers) == _APPROVED


def test_planning_specs_exist_only_for_issue_backed_capabilities() -> None:
    assert set(CATALOG_OPERATIONS) == {
        operation for operation, capability in COPILOT_CAPABILITIES.items() if capability.issue_type
    }
    for operation, spec in CATALOG_OPERATIONS.items():
        assert spec.capability is COPILOT_CAPABILITIES[operation]
        assert spec.issue_type == COPILOT_CAPABILITIES[operation].issue_type


@pytest.mark.parametrize(
    "name",
    [
        "database.dismount", "database.create", "namespace.create", "web_app.update_description",
        "user.set_enabled", "task.run_now", "delete_task", "demo.safe-operation",
        "list_tasks", "unknown.operation", "",
    ],
)
def test_registered_but_unapproved_or_unknown_operations_have_no_capability(name: str) -> None:
    assert get_capability(name) is None


def test_unhashable_lookup_is_denied_not_raised() -> None:
    assert get_capability(["database.mount"]) is None


# --- the load-time checks reject a misconfigured catalog ---


def _catalog(**changes: CopilotCapability | None) -> dict[CopilotOperation, CopilotCapability]:
    catalog = dict(COPILOT_CAPABILITIES)
    for name, capability in changes.items():
        operation = CopilotOperation[name]
        if capability is None:
            del catalog[operation]
        else:
            catalog[operation] = capability
    return catalog


def test_the_real_catalog_passes_validation() -> None:
    validate_capabilities(COPILOT_CAPABILITIES)


_MOUNT = COPILOT_CAPABILITIES[CopilotOperation.DATABASE_MOUNT]
_PURGE = COPILOT_CAPABILITIES[CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED]


@pytest.mark.parametrize(
    "catalog",
    [
        # missing capability
        _catalog(DATABASE_MOUNT=None),
        # entry names another operation
        _catalog(DATABASE_MOUNT=replace(_MOUNT, operation=CopilotOperation.WEB_APP_SET_ENABLED)),
        # issue type the catalog doesn't resolve with this operation
        _catalog(DATABASE_MOUNT=replace(_MOUNT, issue_type="web_app_namespace_missing")),
        _catalog(DATABASE_MOUNT=replace(_MOUNT, issue_type="database_full")),
        # both, or neither, of issue_type / target_identifier
        _catalog(DATABASE_MOUNT=replace(_MOUNT, target_identifier="x")),
        _catalog(JOURNAL_UPDATE_PURGE_ARCHIVED=replace(_PURGE, target_identifier=None)),
    ],
)
def test_misconfigured_catalogs_are_rejected(catalog) -> None:
    with pytest.raises(ValueError):
        validate_capabilities(catalog)


def test_a_capability_that_is_not_a_registered_mutation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_only = OperationDefinition(
        name="database.mount",
        description="test",
        kind=OperationKind.READ_ONLY,
        required_privileges=frozenset({IRISPrivilege.OPERATE}),
        risk_level=RiskLevel.NONE,
        confirmation_required=False,
    )
    monkeypatch.setattr(
        capabilities_module,
        "get_operation",
        lambda name: read_only if name == "database.mount" else OPERATION_REGISTRY.get(name),
    )

    with pytest.raises(ValueError, match="registered mutation"):
        validate_capabilities(COPILOT_CAPABILITIES)


# --- planning, plan validation and execution all consult the catalog ---


def _web_app_plan() -> CopilotOperationPlan:
    return CopilotOperationPlan(
        operation=CopilotOperation.WEB_APP_SET_ENABLED,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.WEB_APP, identifier="/csp/x", issue_id="a" * 64
        ),
        parameters=CopilotWebAppDisableParameters(Name="/csp/x"),
        reason="test",
        requires_confirmation=True,
    )


def _purge_plan() -> CopilotOperationPlan:
    return CopilotOperationPlan(
        operation=CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED,
        target=CopilotOperationTarget(
            kind=CopilotTargetKind.JOURNAL_SETTINGS, identifier="journal-settings"
        ),
        parameters=CopilotOperationParameters(PurgeArchived=True),
        reason="test",
        requires_confirmation=True,
    )


def test_plan_validation_reads_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _web_app_plan()  # valid while approved
    monkeypatch.delitem(COPILOT_CAPABILITIES, CopilotOperation.WEB_APP_SET_ENABLED)

    with pytest.raises(ValidationError):
        _web_app_plan()


def test_planner_refuses_an_operation_removed_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = "Enable PurgeArchived."
    request = CopilotPlanRequest(
        message=message,
        intent=classify_intent(message),
        proposed_action="Set PurgeArchived to true",
        requires_confirmation=True,
    )
    assert CopilotPlanningService().plan(request).reason is CopilotPlanningReason.PLAN_CREATED

    monkeypatch.delitem(COPILOT_CAPABILITIES, CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED)
    result = CopilotPlanningService().plan(request)

    assert result.plan is None
    assert result.reason is CopilotPlanningReason.UNSUPPORTED_ACTION


@pytest.mark.asyncio
async def test_execution_refuses_an_operation_removed_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _purge_plan()
    authorization = CopilotAuthorizationResult(
        authorized=True,
        requires_confirmation=False,
        ready_to_execute=True,
        reason=CopilotAuthorizationReason.AUTHORIZED,
        required_privileges=["Journal", "Manage"],
        operation=plan.operation,
        target=plan.target,
    )
    executor = AsyncMock(spec=OperationExecutor)
    monkeypatch.delitem(COPILOT_CAPABILITIES, CopilotOperation.JOURNAL_UPDATE_PURGE_ARCHIVED)

    result = await CopilotExecutionService(AsyncMock(), frozenset({"Manage"}), executor).execute(
        plan, authorization, confirmed=True
    )

    assert result.status is CopilotExecutionStatus.EXECUTION_REJECTED
    assert result.detail == "This Copilot operation is not supported."
    executor.execute.assert_not_awaited()


@pytest.mark.parametrize("name", ["database.dismount", "user.set_enabled", "task.run_now"])
def test_unapproved_registered_operations_cannot_form_a_plan(name: str) -> None:
    with pytest.raises(ValidationError):
        CopilotOperationPlan.model_validate(
            {
                "operation": name,
                "target": {"kind": "database", "identifier": "X", "issue_id": "a" * 64},
                "parameters": {"Directory": "/db/", "ReadOnly": False},
                "reason": "test",
                "requires_confirmation": True,
            }
        )


# --- Phase 3.5b: descriptive metadata ---


@pytest.mark.parametrize("operation", list(CopilotOperation))
def test_every_capability_has_its_descriptive_metadata(operation: CopilotOperation) -> None:
    capability = COPILOT_CAPABILITIES[operation]

    assert capability.title.strip()
    assert capability.example_requests and all(e.strip() for e in capability.example_requests)
    assert capability.constraints and all(c.strip() for c in capability.constraints)
    assert capability.verification.strip()
    assert capability.undo is None or capability.undo.strip()


def test_capability_metadata_does_not_duplicate_registry_or_issue_catalog_fields() -> None:
    names = {field.name for field in fields(CopilotCapability)}

    owned_elsewhere = {
        # OPERATION_REGISTRY
        "name", "description", "kind", "required_privileges", "risk_level",
        "confirmation_required",
        # ISSUE_CATALOG
        "severity", "prerequisites", "safety_restrictions", "verification_rules",
        "workflow_steps", "parameters",
    }
    assert not names & owned_elsewhere


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"title": "   "},
        {"example_requests": ()},
        {"example_requests": ("Mount database IPM", " ")},
        {"example_requests": ("Mount database IPM", "Mount database IPM")},
        {"example_requests": ["Mount database IPM"]},
        {"constraints": ()},
        {"constraints": ("",)},
        {"verification": ""},
        {"undo": ""},
    ],
)
def test_capabilities_with_missing_or_blank_metadata_are_rejected(change: dict) -> None:
    with pytest.raises(ValueError):
        validate_capabilities(_catalog(DATABASE_MOUNT=replace(_MOUNT, **change)))


def test_undo_may_be_none() -> None:
    validate_capabilities(_catalog(DATABASE_MOUNT=replace(_MOUNT, undo=None)))


def test_example_requests_are_valid_discovery_examples() -> None:
    # Valid chat requests that ask for a change, each pointing at one
    # capability. This deliberately doesn't depend on any provider's wording.
    seen: set[str] = set()
    for capability in COPILOT_CAPABILITIES.values():
        for example in capability.example_requests:
            CopilotPlanRequest(message=example, intent=CopilotIntent.RESOLUTION_REQUEST)
            assert classify_intent(example) is CopilotIntent.RESOLUTION_REQUEST, example
            assert example.casefold() not in seen, f"{example!r} is listed for two capabilities"
            seen.add(example.casefold())


# --- describe_capabilities() and GET /api/iris/copilot/capabilities ---


def test_description_joins_the_catalog_with_its_sources_without_copying() -> None:
    summaries = describe_capabilities()

    assert [s.operation for s in summaries] == list(CopilotOperation)
    for summary in summaries:
        capability = COPILOT_CAPABILITIES[summary.operation]
        definition = OPERATION_REGISTRY[summary.operation.value]
        assert summary.title == capability.title
        assert summary.example_requests == list(capability.example_requests)
        assert summary.constraints == list(capability.constraints)
        assert summary.verification == capability.verification
        assert summary.undo == capability.undo
        assert summary.target_kind is capability.target_kind
        assert summary.required_privileges == sorted(p.value for p in definition.required_privileges)
        assert summary.risk_level is definition.risk_level
        assert summary.confirmation_required is definition.confirmation_required
        if capability.issue_type is None:
            assert (summary.issue_type, summary.issue_title, summary.issue_severity) == (None, None, None)
        else:
            issue = ISSUE_CATALOG[capability.issue_type]
            assert summary.issue_type == capability.issue_type
            assert summary.issue_title == issue.title
            assert summary.issue_severity == issue.severity.value


def test_description_follows_registry_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Read at request time, not copied: a registry change shows up directly.
    original = OPERATION_REGISTRY["database.mount"]
    monkeypatch.setitem(
        OPERATION_REGISTRY, "database.mount", original.model_copy(update={"risk_level": RiskLevel.HIGH})
    )

    mount = next(s for s in describe_capabilities() if s.operation is CopilotOperation.DATABASE_MOUNT)

    assert mount.risk_level is RiskLevel.HIGH


def test_capabilities_endpoint_is_read_only_and_exposes_no_internals(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    with patch.object(OperationExecutor, "execute", new_callable=AsyncMock) as execute:
        response = client.get("/api/iris/copilot/capabilities")

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert [c["operation"] for c in capabilities] == [o.value for o in CopilotOperation]
    assert capabilities == [s.model_dump(mode="json") for s in describe_capabilities()]
    for entry in capabilities:
        assert not {"handler_factory", "parameters_model", "target_identifier"} & set(entry)
    for method in ("get", "post", "put", "delete"):
        getattr(mock_iris_client, method).assert_not_awaited()
    execute.assert_not_awaited()
