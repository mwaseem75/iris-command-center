"""The reusable authorization service.

`authorize()` is a pure function: given an operation name, the caller's
available privileges, and whether explicit confirmation was received, it
returns a structured decision. It never calls IRIS, never performs the
operation, and never mutates anything — it only decides.

Deliberately absent from this module, by design (see
docs/authorization-model.md): any bypass flag, "force" parameter, admin
override, or privilege-escalation path. There is no way to call this
function and get an authorized-to-proceed result other than by actually
holding the required privilege and (for mutating operations) actually
supplying confirmation_received=True. Possessing a valid IRIS session/JWT
is not, by itself, sufficient — a caller must be checked against the
specific privilege each operation declares.
"""

from app.authorization.models import AuthorizationDenialReason, AuthorizationResult
from app.authorization.operations import OperationKind, get_operation
from app.authorization.privileges import parse_available_privileges


def authorize(
    operation_name: str,
    available_privileges: object,
    *,
    confirmation_received: bool = False,
) -> AuthorizationResult:
    """Decide whether `operation_name` may proceed.

    `available_privileges` is whatever the caller has (e.g. the keys of a
    real IRIS `/info` response's `privileges` object where `use` is true) —
    it is parsed defensively via `parse_available_privileges`, which never
    raises and never recognizes an unknown name (including "ConfigStore")
    as a real privilege.
    """
    operation = get_operation(operation_name)
    if operation is None:
        return AuthorizationResult(
            operation_name=operation_name,
            authorized=False,
            confirmation_required=False,
            confirmation_received=confirmation_received,
            can_proceed=False,
            denial_reason=AuthorizationDenialReason.UNKNOWN_OPERATION,
            detail=f"No operation named {operation_name!r} is registered.",
        )

    confirmed_privileges = parse_available_privileges(available_privileges)
    has_privilege = bool(operation.required_privileges & confirmed_privileges)

    if not has_privilege:
        required_names = sorted(p.value for p in operation.required_privileges)
        return AuthorizationResult(
            operation_name=operation_name,
            authorized=False,
            confirmation_required=operation.confirmation_required,
            confirmation_received=confirmation_received,
            can_proceed=False,
            denial_reason=AuthorizationDenialReason.MISSING_PRIVILEGE,
            detail=(
                f"Operation {operation_name!r} requires one of {required_names} "
                "privileges, none of which were found among the caller's confirmed "
                "available privileges."
            ),
        )

    if operation.kind is OperationKind.MUTATING and not confirmation_received:
        return AuthorizationResult(
            operation_name=operation_name,
            authorized=True,
            confirmation_required=True,
            confirmation_received=False,
            can_proceed=False,
            denial_reason=AuthorizationDenialReason.CONFIRMATION_REQUIRED,
            detail=(
                f"Operation {operation_name!r} is authorized but is a mutating "
                "operation that requires explicit confirmation before it can proceed."
            ),
        )

    return AuthorizationResult(
        operation_name=operation_name,
        authorized=True,
        confirmation_required=operation.confirmation_required,
        confirmation_received=confirmation_received,
        can_proceed=True,
        denial_reason=None,
        detail=(
            "Authorized; read-only, no confirmation required."
            if operation.kind is OperationKind.READ_ONLY
            else "Authorized and confirmed."
        ),
    )
