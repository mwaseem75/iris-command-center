"""Tests for the Issue Resolution Catalog (app/resolution). No IRIS calls,
except the route consistency check, which uses the mocked client."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authorization.operations import OPERATION_REGISTRY, OperationKind
from app.authorization.privileges import IRISPrivilege
from app.execution.database_dismount_handler import _SYSTEM_DATABASES
from app.resolution.catalog import DATABASE_DISMOUNTED, ISSUE_CATALOG, get_issue_resolution
from app.resolution.models import (
    WORKFLOW_ORDER,
    DetectionEvidence,
    InvestigationDestination,
    IssueResolution,
    IssueSeverity,
    ParameterBinding,
    VerificationRule,
    WorkflowStepKind,
)
from app.routes.issues import DatabaseMountIssue

OK = {"errors": [], "summary": ""}


def _dashboard() -> dict[str, Any]:
    from tests.test_issues_route import _dashboard as dashboard
    return dashboard()


def _entry_data(**overrides: Any) -> dict[str, Any]:
    """The database_dismounted entry as plain data, with some fields replaced."""
    data = {name: getattr(DATABASE_DISMOUNTED, name) for name in IssueResolution.model_fields}
    data.update(overrides)
    return data


# --- the catalog ---


def test_catalog_has_the_built_in_issue_types() -> None:
    assert list(ISSUE_CATALOG) == [
        "database_dismounted", "web_app_namespace_missing", "journal_purge_archived_off",
        "system_monitor_not_running", "task_manager_not_running", "database_full",
        "audit_logging_disabled",
    ]
    assert get_issue_resolution("database_dismounted") is DATABASE_DISMOUNTED


def test_unknown_issue_type_has_no_resolution() -> None:
    assert get_issue_resolution("something_else") is None


def test_dismounted_database_uses_the_registered_mount_operation() -> None:
    definition = OPERATION_REGISTRY["database.mount"]
    assert DATABASE_DISMOUNTED.operation == "database.mount"
    assert DATABASE_DISMOUNTED.operation_definition is definition
    assert definition.kind is OperationKind.MUTATING


def test_privileges_and_confirmation_come_from_the_operation_registry() -> None:
    definition = OPERATION_REGISTRY["database.mount"]
    assert DATABASE_DISMOUNTED.required_privileges == definition.required_privileges == frozenset({IRISPrivilege.OPERATE})
    assert DATABASE_DISMOUNTED.confirmation_required is True


def test_workflow_is_the_full_resolution_path_in_order() -> None:
    kinds = [step.kind for step in DATABASE_DISMOUNTED.workflow_steps]
    assert kinds == list(WORKFLOW_ORDER)
    assert [k.value for k in kinds] == ["detected", "recommended", "check", "confirm", "execute", "verify", "trace"]


def test_safety_excludes_the_same_system_databases_as_dismount() -> None:
    assert DATABASE_DISMOUNTED.excluded_databases == _SYSTEM_DATABASES
    restrictions = " ".join(DATABASE_DISMOUNTED.safety_restrictions).lower()
    assert "system databases" in restrictions
    assert "mirrored" in restrictions
    assert "dry run" in restrictions


def test_verification_includes_the_handlers_mounted_check() -> None:
    operation_rules = [r for r in DATABASE_DISMOUNTED.verification_rules if r.checked_by == "operation"]
    assert [r.source for r in operation_rules] == ["POST /v2/database-dir/info"]


def test_serialized_entry_includes_derived_privileges() -> None:
    dumped = DATABASE_DISMOUNTED.model_dump(mode="json")
    assert dumped["required_privileges"] == ["Operate"]
    assert dumped["confirmation_required"] is True
    assert dumped["workflow_steps"][2]["kind"] == "check"


def test_entries_are_immutable() -> None:
    with pytest.raises(ValidationError):
        DATABASE_DISMOUNTED.operation = "database.dismount"


# --- consistency with the detector (GET /api/iris/issues) ---


def test_entry_matches_what_the_issues_route_reports(client: TestClient, mock_iris_client: AsyncMock) -> None:
    from tests.test_issues_route import _monitor_process

    databases = [{"Name": "DEMO", "Directory": "/data/demo/", "Server": "", "ClusterMountMode": False,
                  "MountRequired": False, "MountAtStartup": True, "StreamLocation": "", "Status": ""}]
    dirs = [{"Directory": "/data/demo/", "Size": 1, "MaxSize": "Unlimited", "Status": "Dismounted",
             "Mirrored": False, "Encrypted": False}]
    journal = {"AlternateDirectory": "", "ArchiveName": "", "BackupsBeforePurge": 2, "CurrentDirectory": "",
               "DaysBeforePurge": 2, "FileSizeLimit": 1024, "FreezeOnError": False, "JournalFilePrefix": "",
               "JournalcspSession": False, "PurgeArchived": False, "CompressFiles": True, "wijdir": "", "targwijsz": 0}
    bodies = {"/v2/databases": databases, "/v2/database-dirs": dirs, "/v2/namespaces": [],
              "/v2/journal/settings": journal, "/v2/web-apps": [],  # read by the other issue checks
              "/v2/task/manager": {"Status": "Running"}, "/v2/security/audit/enabled": {"Enabled": True},
              "/v2/monitor/dashboard/main": _dashboard(), "/v2/processes": [_monitor_process()]}
    mock_iris_client.get.side_effect = lambda path, **_: {"status": OK, "console": [], "result": bodies[path]}

    (issue,) = client.get("/api/iris/issues").json()["issues"]

    assert issue["kind"] == DATABASE_DISMOUNTED.issue_type
    assert issue["recommended_operation"] == DATABASE_DISMOUNTED.operation
    expected = {
        b.name: (issue[b.from_issue_field] if b.from_issue_field else b.value)
        for b in DATABASE_DISMOUNTED.parameters
    }
    assert issue["parameters"] == expected


def test_every_live_evidence_field_exists_on_the_detected_issue() -> None:
    issue_fields = set(DatabaseMountIssue.model_fields)
    linked = [e.issue_field for e in DATABASE_DISMOUNTED.detection_evidence + DATABASE_DISMOUNTED.impact_evidence]
    assert all(linked), "every piece of evidence should point at its live value"
    assert set(linked) <= issue_fields


def test_risk_level_comes_from_the_operation_registry() -> None:
    assert DATABASE_DISMOUNTED.risk_level is OPERATION_REGISTRY["database.mount"].risk_level


def test_route_model_defaults_match_the_catalog() -> None:
    fields = DatabaseMountIssue.model_fields
    assert fields["kind"].default == DATABASE_DISMOUNTED.issue_type
    assert fields["recommended_operation"].default == DATABASE_DISMOUNTED.operation


# --- the model's rules ---


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not in OPERATION_REGISTRY"):
        IssueResolution(**_entry_data(operation="database.fix_everything"))


def test_read_only_operation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="can't resolve an issue"):
        IssueResolution(**_entry_data(operation="database.info"))


def test_workflow_without_a_dry_run_is_rejected() -> None:
    steps = tuple(s for s in DATABASE_DISMOUNTED.workflow_steps if s.kind is not WorkflowStepKind.DRY_RUN)
    with pytest.raises(ValidationError, match="workflow steps must be"):
        IssueResolution(**_entry_data(workflow_steps=steps))


def test_confirmation_before_the_dry_run_is_rejected() -> None:
    steps = list(DATABASE_DISMOUNTED.workflow_steps)
    steps[2], steps[3] = steps[3], steps[2]
    with pytest.raises(ValidationError, match="workflow steps must be"):
        IssueResolution(**_entry_data(workflow_steps=tuple(steps)))


@pytest.mark.parametrize("section", ["detection_evidence", "parameters", "verification_rules", "safety_restrictions"])
def test_empty_required_section_is_rejected(section: str) -> None:
    with pytest.raises(ValidationError, match=f"{section} must not be empty"):
        IssueResolution(**_entry_data(**{section: ()}))


def test_verification_must_include_an_operation_check() -> None:
    rules = (VerificationRule(source="GET /api/iris/issues", condition="gone", checked_by="issue_detection"),)
    with pytest.raises(ValidationError, match="checked by the operation"):
        IssueResolution(**_entry_data(verification_rules=rules))


def test_parameter_binding_needs_exactly_one_source() -> None:
    with pytest.raises(ValidationError):
        ParameterBinding(name="Directory")
    with pytest.raises(ValidationError):
        ParameterBinding(name="Directory", from_issue_field="directory", value="/x/")


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        IssueResolution(**_entry_data(force=True))


def test_dismounted_database_records_affected_namespaces_as_impact() -> None:
    (impact,) = DATABASE_DISMOUNTED.impact_evidence
    assert impact.source == "GET /v2/namespaces"
    assert impact.issue_field == "affected_namespaces"
    # Impact is extra context; detection and the fix are unchanged.
    assert "affected_namespaces" not in {e.issue_field for e in DATABASE_DISMOUNTED.detection_evidence}
    assert DATABASE_DISMOUNTED.operation == "database.mount"


# --- web_app_namespace_missing ---


def test_web_app_entry_uses_the_registered_set_enabled_operation() -> None:
    from app.resolution.catalog import WEB_APP_NAMESPACE_MISSING as entry

    definition = OPERATION_REGISTRY["web_app.set_enabled"]
    assert entry.operation == "web_app.set_enabled"
    assert definition.kind is OperationKind.MUTATING
    assert entry.required_privileges == definition.required_privileges
    assert entry.risk_level is definition.risk_level and entry.confirmation_required is True


def test_web_app_entry_disables_the_detected_app_and_nothing_else() -> None:
    from app.resolution.catalog import WEB_APP_NAMESPACE_MISSING as entry

    bindings = {b.name: b for b in entry.parameters}
    assert set(bindings) == {"Name", "Enabled"}
    assert bindings["Name"].from_issue_field == "web_app"
    assert bindings["Enabled"].value is False


def test_every_web_app_evidence_field_exists_on_the_detected_issue() -> None:
    from app.resolution.catalog import WEB_APP_NAMESPACE_MISSING as entry
    from app.routes.issues import WebAppNamespaceIssue

    linked = [e.issue_field for e in entry.detection_evidence]
    assert all(linked) and set(linked) <= set(WebAppNamespaceIssue.model_fields)


# --- journal_purge_archived_off ---


def test_journal_entry_uses_the_registered_purge_archived_operation() -> None:
    from app.resolution.catalog import JOURNAL_PURGE_ARCHIVED_OFF as entry

    definition = OPERATION_REGISTRY["journal.update_purge_archived"]
    assert entry.operation == "journal.update_purge_archived"
    assert definition.kind is OperationKind.MUTATING
    assert entry.required_privileges == definition.required_privileges
    assert entry.risk_level is definition.risk_level and entry.confirmation_required is True
    assert entry.severity.value == "low"


def test_journal_entry_only_turns_purge_archived_on() -> None:
    from app.resolution.catalog import JOURNAL_PURGE_ARCHIVED_OFF as entry

    (binding,) = entry.parameters
    assert binding.name == "PurgeArchived" and binding.value is True and binding.from_issue_field is None


def test_every_journal_evidence_field_exists_on_the_detected_issue() -> None:
    from app.resolution.catalog import JOURNAL_PURGE_ARCHIVED_OFF as entry
    from app.routes.issues import JournalPurgeArchivedIssue

    linked = [e.issue_field for e in entry.detection_evidence]
    assert all(linked) and set(linked) <= set(JournalPurgeArchivedIssue.model_fields)


# --- detection-only entries ---


def _detection_only(**overrides: Any) -> IssueResolution:
    data: dict[str, Any] = {
        "issue_type": "example_detection_only",
        "title": "Example detection-only issue",
        "severity": IssueSeverity.MEDIUM,
        "detection_evidence": (
            DetectionEvidence(source="GET /v2/example", field="Status", condition="Status isn't Normal."),
        ),
        "explanation": "Something IRIS reports that no registered operation fixes.",
        "recommended_solution": "Look into it on the Tasks page.",
        "investigation": InvestigationDestination(page="tasks", description="Check the task's last result."),
    }
    data.update(overrides)
    return IssueResolution(**data)


RESOLVABLE = ("database_dismounted", "web_app_namespace_missing", "journal_purge_archived_off")
DETECTION_ONLY = {"system_monitor_not_running": "system", "task_manager_not_running": "tasks", "database_full": "databases"}


def test_existing_entries_stay_resolvable() -> None:
    for entry in (ISSUE_CATALOG[name] for name in RESOLVABLE):
        assert entry.resolvable is True
        assert entry.operation is not None and entry.investigation is None
        dumped = entry.model_dump(mode="json")
        assert dumped["resolvable"] is True and dumped["investigation"] is None
        assert dumped["risk_level"] and dumped["required_privileges"] and dumped["confirmation_required"] is True


def test_detection_only_entry_has_an_investigation_and_no_operation() -> None:
    entry = _detection_only()

    assert entry.resolvable is False and entry.operation is None
    assert entry.investigation.page == "tasks"
    assert entry.operation_definition is None
    dumped = entry.model_dump(mode="json")
    assert dumped["resolvable"] is False
    assert dumped["required_privileges"] == [] and dumped["risk_level"] is None
    assert dumped["confirmation_required"] is False
    assert dumped["parameters"] == [] and dumped["workflow_steps"] == []


def test_detection_only_entry_is_never_resolved_by_an_operation() -> None:
    from app.resolution import catalog

    entry = _detection_only()
    original = catalog.ISSUE_CATALOG
    catalog.ISSUE_CATALOG = {**original, entry.issue_type: entry}
    try:
        for operation in ("database.mount", "web_app.set_enabled", "journal.update_purge_archived"):
            assert not catalog.resolves_with(entry.issue_type, operation)
            assert catalog.trace_context(entry.issue_type, operation, {}) is None
    finally:
        catalog.ISSUE_CATALOG = original


def test_an_entry_needs_exactly_one_of_operation_or_investigation() -> None:
    with pytest.raises(ValidationError, match="exactly one of"):
        _detection_only(investigation=None)  # neither
    with pytest.raises(ValidationError, match="exactly one of"):
        IssueResolution(**_entry_data(investigation=InvestigationDestination(page="databases", description="x")))


@pytest.mark.parametrize("field, value", [
    ("parameters", (ParameterBinding(name="Directory", value="/x/"),)),
    ("workflow_steps", DATABASE_DISMOUNTED.workflow_steps),
])
def test_detection_only_entry_rejects_a_resolution_path(field: str, value: Any) -> None:
    with pytest.raises(ValidationError, match=f"no operation, so no {field}"):
        _detection_only(**{field: value})


def test_detection_only_entry_rejects_an_operation_verification() -> None:
    rules = (VerificationRule(source="GET /x", condition="fixed", checked_by="operation"),)
    with pytest.raises(ValidationError, match="no operation to verify"):
        _detection_only(verification_rules=rules)
    # Re-detection is fine: the issue is gone when it's no longer reported.
    ok = (VerificationRule(source="GET /api/iris/issues", condition="gone", checked_by="issue_detection"),)
    assert _detection_only(verification_rules=ok).verification_rules == ok


def test_detection_only_entry_still_needs_detection_evidence() -> None:
    with pytest.raises(ValidationError, match="detection_evidence must not be empty"):
        _detection_only(detection_evidence=())


def test_investigation_destination_needs_a_page_and_description() -> None:
    with pytest.raises(ValidationError, match="needs a page and a description"):
        InvestigationDestination(page=" ", description="Check it.")
    with pytest.raises(ValidationError, match="needs a page and a description"):
        InvestigationDestination(page="tasks", description="")


def test_resolvable_entry_without_its_resolution_path_is_still_rejected() -> None:
    # Omitting the (now optional) sections must not bypass the resolvable checks.
    with pytest.raises(ValidationError, match="parameters must not be empty"):
        IssueResolution(**_entry_data(parameters=()))
    with pytest.raises(ValidationError, match="workflow steps must be"):
        IssueResolution(**_entry_data(workflow_steps=()))


# --- the built-in detection-only entries ---


@pytest.mark.parametrize("issue_type, page", DETECTION_ONLY.items())
def test_detection_only_entries_investigate_the_right_page(issue_type: str, page: str) -> None:
    entry = ISSUE_CATALOG[issue_type]
    assert entry.resolvable is False and entry.operation is None
    assert entry.investigation.page == page
    assert entry.parameters == () and entry.workflow_steps == ()
    assert all(rule.checked_by == "issue_detection" for rule in entry.verification_rules)
    assert "nothing is run" in entry.recommended_solution


@pytest.mark.parametrize("issue_type", DETECTION_ONLY)
def test_detection_only_evidence_fields_exist_on_the_detected_issue(issue_type: str) -> None:
    from app.routes.issues import DatabaseFullIssue, SystemMonitorIssue, TaskManagerIssue

    model = {"system_monitor_not_running": SystemMonitorIssue, "task_manager_not_running": TaskManagerIssue,
             "database_full": DatabaseFullIssue}[issue_type]
    linked = [e.issue_field for e in ISSUE_CATALOG[issue_type].detection_evidence]
    assert all(linked) and set(linked) <= set(model.model_fields)


@pytest.mark.parametrize("issue_type", DETECTION_ONLY)
def test_no_operation_resolves_a_detection_only_entry(issue_type: str) -> None:
    from app.authorization.operations import OPERATION_REGISTRY
    from app.resolution.catalog import resolves_with, trace_context

    for operation in OPERATION_REGISTRY:
        assert not resolves_with(issue_type, operation)
        assert trace_context(issue_type, operation, {}) is None
