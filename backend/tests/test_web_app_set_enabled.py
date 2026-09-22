"""Tests for web_app.set_enabled. Every test uses a fake/mock IRISClient —
no real network call is made, and no test (or anything else in this
project) performs a real PUT /v2/web-app.

The fake IRIS keeps a tiny amount of state so a PUT is observable by the
verification reads, mirroring what IRIS's own implementation does (see
app/execution/web_app_set_enabled_handler.py's docstring): the PUT changes
only Enabled. List entries are real GET /v2/web-apps entries captured from
icc-iris-dev.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.execution.web_app_set_enabled_handler import WebAppSetEnabledHandler
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.observability.store import clear_traces, list_traces

_OPERATION_NAME = "web_app.set_enabled"
_ENVELOPE = {"status": {"errors": [], "summary": ""}, "console": []}

# Real GET /v2/web-apps entries (subset) from icc-iris-dev.
_LIVE_ENTRIES: list[dict[str, Any]] = [
    {"Name": "/api/admin", "Namespace": "%SYS", "NamespaceDefault": False, "Enabled": True,
     "Type": "CSP", "Resource": "", "AuthenticationMethods": ["Password"],
     "IsSystemApp": False, "DispatchClass": "%Api.Admin"},
    {"Name": "/api/mgmnt", "Namespace": "%SYS", "NamespaceDefault": False, "Enabled": True,
     "Type": "CSP", "Resource": "", "AuthenticationMethods": ["Password"],
     "IsSystemApp": False, "DispatchClass": "%Api.Mgmnt.v2.disp"},
    {"Name": "/csp/sys", "Namespace": "%SYS", "NamespaceDefault": True, "Enabled": True,
     "Type": "System,CSP", "Resource": "", "AuthenticationMethods": ["Unauthenticated", "Password"],
     "IsSystemApp": False, "DispatchClass": ""},
    {"Name": "/csp/user", "Namespace": "USER", "NamespaceDefault": True, "Enabled": True,
     "Type": "CSP", "Resource": "", "AuthenticationMethods": ["Unauthenticated", "Password"],
     "IsSystemApp": False, "DispatchClass": ""},
    {"Name": "/api/iam", "Namespace": "%SYS", "NamespaceDefault": False, "Enabled": False,
     "Type": "CSP", "Resource": "%IAM", "AuthenticationMethods": ["Password"],
     "IsSystemApp": False, "DispatchClass": "%Api.IAM.v1.disp"},
]

_PRIVILEGES = frozenset({"Manage", "Secure"})


class FakeIris:
    """Answers the handler's reads from `entries`; a PUT changes only the
    named app's Enabled, like IRIS's MergeJsonAndProperties()."""

    def __init__(self, entries: list[dict[str, Any]] | None = None):
        self.entries = [dict(e) for e in (entries or _LIVE_ENTRIES)]
        self.detail_enabled_override: Any = "unset"
        self.client = AsyncMock()
        self.client.get.side_effect = self._get
        self.client.put.side_effect = self._put

    def _entry(self, name: str) -> dict[str, Any] | None:
        return next((e for e in self.entries if e["Name"] == name), None)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/web-apps":
            return {**_ENVELOPE, "result": [dict(e) for e in self.entries]}
        if path == "/v2/web-app":
            entry = self._entry(params["name"])
            if entry is None:
                raise IRISResponseError(404)
            enabled = entry["Enabled"] if self.detail_enabled_override == "unset" else self.detail_enabled_override
            return {**_ENVELOPE, "result": {"Enabled": enabled, "NameSpace": entry["Namespace"]}}
        if path == "/info":
            return {**_ENVELOPE, "result": {
                "apiVersion": 2, "username": "_SYSTEM", "serverVersion": "IRIS 2026.2",
                "systemMode": "", "product": "iris", "namespaces": [{"name": "%SYS"}],
                "privileges": {p: {"use": True} for p in sorted(self.info_privileges)},
            }}
        raise AssertionError(f"unexpected GET {path}")

    info_privileges: frozenset[str] = _PRIVILEGES

    async def _put(self, path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = self._entry(params["name"])
        entry["Enabled"] = json["Enabled"]
        return {**_ENVELOPE, "result": {"Enabled": json["Enabled"]}}


@pytest.fixture
def iris() -> FakeIris:
    return FakeIris()


@pytest.fixture
def executor(iris: FakeIris) -> OperationExecutor:
    handler = WebAppSetEnabledHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(name: str = "/csp/user", enabled: Any = False, **extra: Any) -> OperationRequest:
    return OperationRequest(
        operation_name=_OPERATION_NAME, parameters={"Name": name, "Enabled": enabled, **extra}
    )


def _context(
    *, privileges: frozenset[str] = _PRIVILEGES, confirmed: bool = True, dry_run: bool = False
) -> ExecutionContext:
    return ExecutionContext(
        available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run
    )


# --- authorization / confirmation (the executor never reaches the handler) ---


@pytest.mark.asyncio
async def test_missing_manage_privilege_is_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Secure", "Operate"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(confirmed=False))

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_manage_without_secure_is_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris
) -> None:
    """IRIS enforces %Admin_Secure for PUT /v2/web-app — without it the
    handler refuses rather than letting IRIS 403 mid-execution."""
    result = await executor.execute(_request(), _context(privileges=frozenset({"Manage"})))

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "%Admin_Secure" in result.detail
    assert result.handler_result.data["missing_iris_privilege"] == "Secure"
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


# --- dry run ---


@pytest.mark.asyncio
async def test_dry_run_previews_exact_partial_request_without_writing(
    executor: OperationExecutor, iris: FakeIris
) -> None:
    result = await executor.execute(_request(enabled=False), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result.outcome.value == "success"
    data = result.handler_result.data
    assert data["enabled_before"] is True
    assert data["enabled_after"] is False
    assert data["type_before"] == "CSP"
    assert data["request"] == {
        "method": "PUT",
        "path": "/v2/web-app",
        "query": {"name": "/csp/user"},
        "body": {"Enabled": False},
    }
    iris.client.put.assert_not_awaited()
    assert iris._entry("/csp/user")["Enabled"] is True


# --- hard denies and validation (never a write) ---


@pytest.mark.parametrize("name", ["/api/admin", "/API/Admin/", "/api/mgmnt", "/api/mgmnt/"])
@pytest.mark.asyncio
async def test_command_center_dependencies_are_hard_denied(
    executor: OperationExecutor, iris: FakeIris, name: str
) -> None:
    for dry_run in (True, False):
        result = await executor.execute(_request(name=name), _context(dry_run=dry_run))
        assert result.handler_result.outcome.value == "failure"
        assert result.handler_result.data["protected"] is True
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_type_app_is_hard_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    """IRIS's PUT always resets Type to plain CSP, which would clear the
    System flag of a "System,CSP" app such as the Management Portal."""
    result = await executor.execute(_request(name="/csp/sys"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    assert result.handler_result.data["type"] == "System,CSP"
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_system_app_flag_is_hard_denied(iris: FakeIris) -> None:
    iris.entries.append({**_LIVE_ENTRIES[3], "Name": "/csp/flagged", "IsSystemApp": True})
    executor = OperationExecutor({_OPERATION_NAME: WebAppSetEnabledHandler(iris.client)})

    result = await executor.execute(_request(name="/csp/flagged"), _context())

    assert result.handler_result.data["protected"] is True
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_app_is_rejected_and_never_created(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="/csp/does-not-exist"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "No web application named" in result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_state_is_a_no_op_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="/csp/user", enabled=True), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["no_change"] is True
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_undetermined_current_state_is_rejected_not_guessed(
    executor: OperationExecutor, iris: FakeIris
) -> None:
    iris.detail_enabled_override = None

    result = await executor.execute(_request(), _context())

    assert "Could not determine" in result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.parametrize(
    "parameters",
    [
        {"Name": "/csp/user", "Enabled": "false"},  # not a real bool
        {"Name": "/csp/user", "Enabled": 0},
        {"Name": "csp/user", "Enabled": False},
        {"Name": "/csp/../api/admin", "Enabled": False},
        {"Name": "", "Enabled": False},
        {"Name": "/csp/user", "Enabled": False, "NameSpace": "USER"},  # only Enabled may change
    ],
)
@pytest.mark.asyncio
async def test_invalid_requests_are_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, parameters: dict[str, Any]
) -> None:
    request = OperationRequest(operation_name=_OPERATION_NAME, parameters=parameters)

    result = await executor.execute(request, _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "Invalid web_app.set_enabled request" in result.detail
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


# --- execution + verification ---


@pytest.mark.asyncio
async def test_successful_disable_sends_only_enabled_and_verifies(
    executor: OperationExecutor, iris: FakeIris
) -> None:
    result = await executor.execute(_request(name="/csp/user", enabled=False), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.put.assert_awaited_once_with(
        "/v2/web-app", json={"Enabled": False}, params={"name": "/csp/user"}
    )
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "Enabled=False" in result.verification.detail
    assert "'CSP'" in result.verification.detail


@pytest.mark.asyncio
async def test_successful_enable_of_disabled_app(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="/api/iam", enabled=True), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.put.assert_awaited_once_with(
        "/v2/web-app", json={"Enabled": True}, params={"name": "/api/iam"}
    )


@pytest.mark.asyncio
async def test_403_from_iris_is_a_clear_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.client.put.side_effect = IRISResponseError(403)

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "HTTP 403" in result.detail
    assert result.verification is None


@pytest.mark.asyncio
async def test_verification_fails_if_state_never_changes(iris: FakeIris) -> None:
    async def ignored_put(path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**_ENVELOPE, "result": {}}

    iris.client.put.side_effect = ignored_put
    handler = WebAppSetEnabledHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(_request(enabled=False), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "after 4 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_fails_if_type_changed(iris: FakeIris) -> None:
    original_put = iris._put

    async def type_changing_put(path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = await original_put(path, json, params)
        iris._entry(params["name"])["Type"] = "Something,Else"
        return body

    iris.client.put.side_effect = type_changing_put
    handler = WebAppSetEnabledHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(_request(enabled=False), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "Type changed" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(iris: FakeIris) -> None:
    handler = WebAppSetEnabledHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})
    original_get = iris._get
    put_done = {"value": False}

    async def get_failing_after_put(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if put_done["value"]:
            raise IRISConnectionError("gone")
        return await original_get(path, params)

    async def put(path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        put_done["value"] = True
        return await iris._put(path, json, params)

    iris.client.get.side_effect = get_failing_after_put
    iris.client.put.side_effect = put

    result = await executor.execute(_request(enabled=False), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "read error" in result.verification.detail


@pytest.mark.asyncio
async def test_trace_records_every_stage(executor: OperationExecutor) -> None:
    clear_traces()

    await executor.execute(_request(enabled=False), _context())

    trace = list_traces()[0]
    assert trace.operation_name == _OPERATION_NAME
    assert trace.status == "success"
    assert [s.name for s in trace.spans] == ["authorization", "confirmation", "execution", "verification"]
    assert trace.verification_result == "verified"
    clear_traces()


# --- route ---


def _route_client(client: TestClient, mock_iris_client: AsyncMock, privileges: frozenset[str] = _PRIVILEGES) -> FakeIris:
    fake = FakeIris()
    fake.info_privileges = privileges
    mock_iris_client.get.side_effect = fake._get
    mock_iris_client.put.side_effect = fake._put
    return fake


def test_route_requires_confirmation(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(client, mock_iris_client)

    response = client.post("/api/iris/web-apps/set-enabled", json={"Name": "/csp/user", "Enabled": False})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.put.assert_not_awaited()


def test_route_without_manage_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(client, mock_iris_client, privileges=frozenset({"Secure", "Operate"}))

    response = client.post(
        "/api/iris/web-apps/set-enabled",
        json={"Name": "/csp/user", "Enabled": False, "confirmed": True},
    )

    assert response.json()["status"] == "unauthorized"
    mock_iris_client.put.assert_not_awaited()


def test_route_dry_run_never_writes(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(client, mock_iris_client)

    response = client.post(
        "/api/iris/web-apps/set-enabled",
        json={"Name": "/csp/user", "Enabled": False, "confirmed": True, "dry_run": True},
    )

    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["data"]["request"]["body"] == {"Enabled": False}
    mock_iris_client.put.assert_not_awaited()


def test_route_admin_app_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(client, mock_iris_client)

    response = client.post(
        "/api/iris/web-apps/set-enabled",
        json={"Name": "/api/admin", "Enabled": False, "confirmed": True},
    )

    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["handler_result"]["data"]["protected"] is True
    mock_iris_client.put.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"Name": "/csp/user", "Enabled": False, "confirmed": True, "NameSpace": "USER"},
        {"Name": "/csp/user", "Enabled": False, "confirmed": True, "force": True},
        {"Name": "/csp/user", "Enabled": "false", "confirmed": True},
        {"Name": "/csp/user", "confirmed": True},
    ],
)
def test_route_rejects_unknown_fields_and_non_bool(
    client: TestClient, mock_iris_client: AsyncMock, payload: dict[str, Any]
) -> None:
    _route_client(client, mock_iris_client)

    response = client.post("/api/iris/web-apps/set-enabled", json=payload)

    assert response.status_code == 422
    mock_iris_client.put.assert_not_awaited()
