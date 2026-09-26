"""Tests for user.set_enabled, using a fake IRIS client.

Like the real API, GET and PUT return the full user object and a PUT only
changes the keys sent. The users have fake personal data (email, phone,
provider, comment) so we can check it never leaks into results, responses
or traces.
"""

import copy
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.execution.user_set_enabled_handler import UserSetEnabledHandler
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app
from app.observability.store import clear_traces, list_traces

_OPERATION_NAME = "user.set_enabled"
_ENVELOPE = {"status": {"errors": [], "summary": ""}, "console": []}
_PRIVILEGES = frozenset({"Secure"})
PII = ("pii-email@example.invalid", "555-0100-pii", "pii-carrier", "pii-comment-text")


def _user(enabled: bool, roles: list[str], escalation: list[str] | None = None) -> dict[str, Any]:
    """A full GET /v2/security/user result."""
    return {
        "AccountNeverExpires": True, "AutheEnabled": 0, "ChangePassword": False,
        "Comment": "pii-comment-text", "EmailAddress": "pii-email@example.invalid", "Enabled": enabled,
        "ExpirationDate": "", "FullName": "Test Person", "HOTPKeyDisplay": False, "NameSpace": "",
        "PasswordNeverExpires": False, "PhoneNumber": "555-0100-pii", "PhoneProvider": "pii-carrier",
        "Roles": roles, "EscalationRoles": escalation or [], "Routine": "",
    }


_USERS: dict[str, dict[str, Any]] = {
    "jdoe": _user(True, ["%Developer"]),
    "analyst": _user(False, ["%SQL"]),
    "opsadmin": _user(True, ["%Manager"], ["%All"]),
    "boss": _user(True, ["%All"]),
    "test-user": _user(True, ["%Developer"]),  # the route's configured IRIS_USERNAME (conftest.py)
}


class FakeIris:
    """GET/PUT /v2/security/user over `users`. A PUT only changes the keys sent
    and returns the full object.
    """

    def __init__(self) -> None:
        self.users = copy.deepcopy(_USERS)
        self.put_changes_state = True
        self.roles_after_put: list[str] | None = None
        self.put_error: int | None = None
        self.info_privileges: frozenset[str] = _PRIVILEGES
        self.client = AsyncMock()
        self.client.get.side_effect = self._get
        self.client.put.side_effect = self._put

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/security/user":
            user = self.users.get(params["name"])
            if user is None:
                raise IRISResponseError(404)
            return {**_ENVELOPE, "result": copy.deepcopy(user)}
        if path == "/info":
            return {**_ENVELOPE, "result": {
                "apiVersion": 2, "username": "test-user", "serverVersion": "IRIS 2026.2",
                "systemMode": "", "product": "iris", "namespaces": [{"name": "%SYS"}],
                "privileges": {p: {"use": True} for p in sorted(self.info_privileges)},
            }}
        raise AssertionError(f"unexpected GET {path}")

    async def _put(self, path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path == "/v2/security/user"
        if self.put_error:
            raise IRISResponseError(self.put_error)
        user = self.users[params["name"]]
        if self.put_changes_state:
            user.update(json)
        if self.roles_after_put is not None:
            user["Roles"] = self.roles_after_put
        return {**_ENVELOPE, "result": copy.deepcopy(user)}


@pytest.fixture
def iris() -> FakeIris:
    return FakeIris()


def _executor(iris: FakeIris, own_username: str | None = "svc-command-center") -> OperationExecutor:
    handler = UserSetEnabledHandler(
        iris.client, own_username=own_username, verify_retry_delays_seconds=(0.0, 0.0, 0.0)
    )
    return OperationExecutor({_OPERATION_NAME: handler})


@pytest.fixture
def executor(iris: FakeIris) -> OperationExecutor:
    return _executor(iris)


def _request(name: str = "jdoe", enabled: Any = False, **extra: Any) -> OperationRequest:
    return OperationRequest(operation_name=_OPERATION_NAME, parameters={"Name": name, "Enabled": enabled, **extra})


def _context(*, privileges: frozenset[str] = _PRIVILEGES, confirmed: bool = True, dry_run: bool = False) -> ExecutionContext:
    return ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run)


def assert_no_pii(text: str) -> None:
    for value in PII:
        assert value not in text
    for field in ("EmailAddress", "PhoneNumber", "PhoneProvider", "Comment", "Password"):
        assert f'"{field}"' not in text


# --- authorization / confirmation (handler never reached) ---


@pytest.mark.asyncio
async def test_missing_secure_privilege_is_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Manage", "Operate"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(confirmed=False))

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


# --- dry run ---


@pytest.mark.asyncio
async def test_dry_run_previews_exact_partial_request_without_writing(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(enabled=False), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    data = result.handler_result.data
    assert data["enabled_before"] is True and data["enabled_after"] is False
    assert data["request"] == {"method": "PUT", "path": "/v2/security/user", "query": {"name": "jdoe"},
                               "body": {"Enabled": False}}
    assert "No request was sent" in result.handler_result.detail
    assert_no_pii(result.model_dump_json())
    iris.client.put.assert_not_awaited()
    assert iris.users["jdoe"]["Enabled"] is True


@pytest.mark.asyncio
async def test_dry_run_of_a_denied_request_is_also_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="boss"), _context(dry_run=True))

    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    iris.client.put.assert_not_awaited()


# --- hard denies, unknown users, no-ops ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["_SYSTEM", "_system", "Admin", "SuperUser", "CSPSystem", "CSPSYSTEM", "UnknownUser", "_Ensemble", "_PUBLIC",
     "IAM", "irisowner"],
)
async def test_predefined_accounts_are_hard_denied_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, name: str
) -> None:
    result = await executor.execute(_request(name=name, enabled=False), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_center_own_account_is_hard_denied(iris: FakeIris) -> None:
    iris.users["svc-command-center"] = _user(True, ["%Developer"])
    executor = _executor(iris, own_username="svc-command-center")

    result = await executor.execute(_request(name="SVC-Command-Center"), _context())

    assert result.handler_result.data["protected"] is True
    assert "signs in with" in result.handler_result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "enabled"), [("boss", False), ("opsadmin", False)])
async def test_super_user_role_holders_are_hard_denied(
    executor: OperationExecutor, iris: FakeIris, name: str, enabled: bool
) -> None:
    result = await executor.execute(_request(name=name, enabled=enabled), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    assert "%All" in result.handler_result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_user_is_rejected_and_never_created(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="ghost"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "no user named 'ghost'" in result.handler_result.detail
    iris.client.put.assert_not_awaited()
    assert "ghost" not in iris.users


@pytest.mark.asyncio
async def test_same_state_is_a_no_op_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="jdoe", enabled=True), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["no_change"] is True
    assert "already enabled" in result.handler_result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["Enabled", "Roles", "EscalationRoles"])
async def test_undetermined_state_is_rejected_not_guessed(executor: OperationExecutor, iris: FakeIris, field: str) -> None:
    del iris.users["jdoe"][field]

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters",
    [
        {"Name": "", "Enabled": False},
        {"Name": "   ", "Enabled": False},
        {"Name": " jdoe", "Enabled": False},
        {"Name": "jd\noe", "Enabled": False},
        {"Name": "jdoe", "Enabled": "false"},
        {"Name": "jdoe", "Enabled": 0},
        {"Name": "jdoe"},
        {"Name": "jdoe", "Enabled": False, "EmailAddress": "x@example.invalid"},
        {"Name": "jdoe", "Enabled": False, "force": True},
    ],
)
async def test_invalid_requests_are_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, parameters: dict[str, Any]
) -> None:
    result = await executor.execute(OperationRequest(operation_name=_OPERATION_NAME, parameters=parameters), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.detail.startswith("Invalid user.set_enabled request")
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


# --- execution + verification ---


@pytest.mark.asyncio
async def test_successful_disable_sends_only_enabled_and_verifies(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="jdoe", enabled=False), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.put.assert_awaited_once_with("/v2/security/user", json={"Enabled": False}, params={"name": "jdoe"})
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "roles are unchanged" in result.verification.detail
    assert iris.users["jdoe"]["Enabled"] is False
    # The PUT response had the full user object; none of it comes back.
    assert_no_pii(result.model_dump_json())


@pytest.mark.asyncio
async def test_successful_enable_of_disabled_user(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="analyst", enabled=True), _context())

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert iris.users["analyst"]["Enabled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "phrase"), [(403, "requires %Admin_Secure"), (404, "no user named"), (400, "invalid")])
async def test_iris_errors_on_put_are_clear_failures(
    executor: OperationExecutor, iris: FakeIris, code: int, phrase: str
) -> None:
    iris.put_error = code

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert phrase in result.handler_result.detail
    assert "Nothing was changed" in result.handler_result.detail


@pytest.mark.asyncio
async def test_verification_fails_if_state_never_changes(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.put_changes_state = False

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "Enabled=True" in result.verification.detail
    assert "4 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_fails_if_roles_changed(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.roles_after_put = ["%Developer", "%Manager"]

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "roles changed" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(executor: OperationExecutor, iris: FakeIris) -> None:
    original_get = iris.client.get.side_effect
    calls = {"n": 0}

    async def flaky_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] > 1:  # the validation read succeeds, every verification read fails
            raise IRISConnectionError("boom")
        return await original_get(path, params)

    iris.client.get.side_effect = flaky_get

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "read error" in result.verification.detail


@pytest.mark.asyncio
async def test_trace_records_every_stage_without_pii(executor: OperationExecutor) -> None:
    clear_traces()

    await executor.execute(_request(enabled=False), _context())

    trace = list_traces()[0]
    assert trace.operation_name == _OPERATION_NAME
    assert trace.status == "success"
    assert [s.name for s in trace.spans] == ["authorization", "confirmation", "execution", "verification"]
    assert trace.verification_result == "verified"
    assert_no_pii(json.dumps(trace.model_dump(mode="json")))
    clear_traces()


# --- route ---


def _route_client(mock_iris_client: AsyncMock, privileges: frozenset[str] = _PRIVILEGES) -> FakeIris:
    fake = FakeIris()
    fake.info_privileges = privileges
    mock_iris_client.get.side_effect = fake._get
    mock_iris_client.put.side_effect = fake._put
    return fake


def test_route_requires_confirmation(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/security/users/set-enabled", json={"Name": "jdoe", "Enabled": False})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.put.assert_not_awaited()


def test_route_without_secure_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client, privileges=frozenset({"Manage", "Operate"}))

    response = client.post("/api/iris/security/users/set-enabled",
                           json={"Name": "jdoe", "Enabled": False, "confirmed": True})

    assert response.json()["status"] == "unauthorized"
    mock_iris_client.put.assert_not_awaited()


def test_route_dry_run_never_writes(client: TestClient, mock_iris_client: AsyncMock) -> None:
    fake = _route_client(mock_iris_client)

    response = client.post("/api/iris/security/users/set-enabled",
                           json={"Name": "jdoe", "Enabled": False, "confirmed": True, "dry_run": True})

    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["data"]["request"]["body"] == {"Enabled": False}
    assert_no_pii(response.text)
    mock_iris_client.put.assert_not_awaited()
    assert fake.users["jdoe"]["Enabled"] is True


def test_route_protects_the_configured_iris_username(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """conftest.py sets IRIS_USERNAME=test-user, i.e. our own account."""
    _route_client(mock_iris_client)

    response = client.post("/api/iris/security/users/set-enabled",
                           json={"Name": "TEST-USER", "Enabled": False, "confirmed": True})

    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["handler_result"]["data"]["protected"] is True
    mock_iris_client.put.assert_not_awaited()


def test_route_success_response_has_no_pii(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/security/users/set-enabled",
                           json={"Name": "jdoe", "Enabled": False, "confirmed": True})

    assert response.json()["status"] == "success"
    assert_no_pii(response.text)


@pytest.mark.parametrize(
    "payload",
    [
        {"Name": "jdoe", "Enabled": False, "confirmed": True, "Roles": ["%All"]},
        {"Name": "jdoe", "Enabled": False, "confirmed": True, "force": True},
        {"Name": "jdoe", "Enabled": "false", "confirmed": True},
        {"Name": "jdoe", "confirmed": True},
    ],
)
def test_route_rejects_unknown_fields_and_non_bool(
    client: TestClient, mock_iris_client: AsyncMock, payload: dict[str, Any]
) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/security/users/set-enabled", json=payload)

    assert response.status_code == 422
    mock_iris_client.put.assert_not_awaited()


def test_route_is_post_only() -> None:
    ops = app.openapi()["paths"]["/api/iris/security/users/set-enabled"]
    assert set(ops) == {"post"}
