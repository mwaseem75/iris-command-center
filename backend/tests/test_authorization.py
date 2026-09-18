"""Tests for the authorization foundation: privileges, the operation
registry, and the authorize() service. Pure unit tests — no IRIS container,
no network, no mutation of any kind."""

import pytest
from pydantic import ValidationError

from app.authorization.models import AuthorizationDenialReason
from app.authorization.operations import (
    OPERATION_REGISTRY,
    OperationDefinition,
    OperationKind,
    RiskLevel,
    get_operation,
)
from app.authorization.privileges import IRISPrivilege, parse_available_privileges
from app.authorization.service import authorize


# --- 1. Known read-only operation with required privilege -> authorized ---


def test_read_only_operation_with_privilege_is_authorized_and_can_proceed() -> None:
    result = authorize("list_namespaces", available_privileges=["Manage", "Operate"])

    assert result.authorized is True
    assert result.confirmation_required is False
    assert result.can_proceed is True
    assert result.denial_reason is None


# --- 2. Known mutating operation, privilege present, no confirmation -> denied ---


def test_mutating_operation_without_confirmation_is_denied() -> None:
    result = authorize("delete_task", available_privileges=["Task"])

    assert result.authorized is True  # privilege check passed...
    assert result.confirmation_required is True
    assert result.confirmation_received is False
    assert result.can_proceed is False  # ...but still blocked
    assert result.denial_reason is AuthorizationDenialReason.CONFIRMATION_REQUIRED


# --- 3. Known mutating operation, privilege present, confirmed -> allowed to proceed ---


def test_mutating_operation_with_confirmation_can_proceed() -> None:
    result = authorize("delete_task", available_privileges=["Task"], confirmation_received=True)

    assert result.authorized is True
    assert result.confirmation_required is True
    assert result.confirmation_received is True
    assert result.can_proceed is True
    assert result.denial_reason is None


# --- 4. Missing privilege -> denied ---


def test_missing_privilege_is_denied() -> None:
    result = authorize("list_namespaces", available_privileges=["Operate", "Secure"])

    assert result.authorized is False
    assert result.can_proceed is False
    assert result.denial_reason is AuthorizationDenialReason.MISSING_PRIVILEGE


def test_missing_privilege_denies_mutating_operation_even_with_confirmation() -> None:
    """Confirmation never substitutes for privilege — even confirmation_received=True
    must not grant an operation the caller lacks the privilege for."""
    result = authorize("delete_task", available_privileges=[], confirmation_received=True)

    assert result.authorized is False
    assert result.can_proceed is False
    assert result.denial_reason is AuthorizationDenialReason.MISSING_PRIVILEGE


# --- 5. Unknown operation -> denied ---


def test_unknown_operation_is_denied() -> None:
    result = authorize("delete_everything", available_privileges=["Manage", "Operate", "Secure"])

    assert result.authorized is False
    assert result.can_proceed is False
    assert result.denial_reason is AuthorizationDenialReason.UNKNOWN_OPERATION


def test_get_operation_returns_none_for_unregistered_name() -> None:
    assert get_operation("delete_everything") is None
    assert get_operation("") is None


# --- 6. ConfigStore cannot accidentally be treated as a confirmed privilege ---


def test_config_store_is_not_a_known_privilege_enum_member() -> None:
    names = {member.value for member in IRISPrivilege}
    assert "ConfigStore" not in names


def test_config_store_claim_is_silently_dropped_not_granted() -> None:
    parsed = parse_available_privileges(["ConfigStore", "Manage"])

    assert parsed == frozenset({IRISPrivilege.MANAGE})


def test_operation_cannot_require_config_store() -> None:
    """No operation in the registry requires ConfigStore, and none could:
    OperationDefinition.required_privilege is typed as IRISPrivilege, which
    has no ConfigStore member at all."""
    for operation in OPERATION_REGISTRY.values():
        assert operation.required_privilege.value != "ConfigStore"

    with pytest.raises(ValueError):
        IRISPrivilege("ConfigStore")


# --- 7. Unknown/malformed privilege input -> denied safely, never raises ---


@pytest.mark.parametrize(
    "malformed_input",
    [
        None,
        "Manage",  # a bare string, not an iterable of strings
        42,
        {"Manage": True},  # a dict, not a list/set/tuple of strings
        ["Manage", 123, None, "", "not-a-real-privilege"],
    ],
)
def test_parse_available_privileges_never_raises_on_malformed_input(malformed_input: object) -> None:
    result = parse_available_privileges(malformed_input)
    assert isinstance(result, frozenset)


def test_authorize_denies_safely_with_malformed_privilege_input() -> None:
    result = authorize("list_namespaces", available_privileges="Manage")  # bare string, not a list

    assert result.authorized is False
    assert result.can_proceed is False
    assert result.denial_reason is AuthorizationDenialReason.MISSING_PRIVILEGE


def test_authorize_denies_safely_with_none_privilege_input() -> None:
    result = authorize("list_namespaces", available_privileges=None)

    assert result.authorized is False
    assert result.can_proceed is False
    assert result.denial_reason is AuthorizationDenialReason.MISSING_PRIVILEGE


# --- OperationDefinition invariants: cannot construct an unsafe combination ---


def test_read_only_operation_cannot_require_confirmation() -> None:
    with pytest.raises(ValidationError):
        OperationDefinition(
            name="bad",
            description="invalid",
            kind=OperationKind.READ_ONLY,
            required_privilege=IRISPrivilege.MANAGE,
            risk_level=RiskLevel.NONE,
            confirmation_required=True,
        )


def test_mutating_operation_cannot_skip_confirmation() -> None:
    with pytest.raises(ValidationError):
        OperationDefinition(
            name="bad",
            description="invalid",
            kind=OperationKind.MUTATING,
            required_privilege=IRISPrivilege.MANAGE,
            risk_level=RiskLevel.HIGH,
            confirmation_required=False,
        )


def test_operation_registry_has_no_bypass_or_force_fields() -> None:
    """Guards against a future accidental field addition reintroducing a
    bypass mechanism — the model's known fields are exactly this set."""
    assert set(OperationDefinition.model_fields.keys()) == {
        "name",
        "description",
        "kind",
        "required_privilege",
        "risk_level",
        "confirmation_required",
    }
