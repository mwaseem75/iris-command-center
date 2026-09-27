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
    IssueResolution,
    ParameterBinding,
    VerificationRule,
    WorkflowStepKind,
)
from app.routes.issues import DatabaseMountIssue

OK = {"errors": [], "summary": ""}


def _entry_data(**overrides: Any) -> dict[str, Any]:
    """The database_dismounted entry as plain data, with some fields replaced."""
    data = {name: getattr(DATABASE_DISMOUNTED, name) for name in IssueResolution.model_fields}
    data.update(overrides)
    return data


# --- the catalog ---


def test_catalog_starts_with_only_the_dismounted_database_issue() -> None:
    assert list(ISSUE_CATALOG) == ["database_dismounted"]
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
    databases = [{"Name": "DEMO", "Directory": "/data/demo/", "Server": "", "ClusterMountMode": False,
                  "MountRequired": False, "MountAtStartup": True, "StreamLocation": "", "Status": ""}]
    dirs = [{"Directory": "/data/demo/", "Size": 1, "MaxSize": "Unlimited", "Status": "Dismounted",
             "Mirrored": False, "Encrypted": False}]
    bodies = {"/v2/databases": databases, "/v2/database-dirs": dirs}
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
    linked = [e.issue_field for e in DATABASE_DISMOUNTED.detection_evidence]
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
