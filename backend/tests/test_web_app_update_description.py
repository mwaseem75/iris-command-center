"""Tests for web_app.update_description, using a fake IRIS client.

Like the real API, the PUT only changes the keys sent and always sets Type
to CSP. List entries and descriptions are copied from a real instance.
"""

import copy
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
from app.execution.web_app_update_description_handler import WebAppUpdateDescriptionHandler
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app
from app.observability.store import clear_traces, list_traces

_OPERATION_NAME = "web_app.update_description"
_ENVELOPE = {"status": {"errors": [], "summary": ""}, "console": []}
_PRIVILEGES = frozenset({"Manage", "Secure"})

_APPS: dict[str, dict[str, Any]] = {
    "/csp/user": {"Type": "CSP", "IsSystemApp": False, "Enabled": True, "Description": "User Namespace applications"},
    "/api/iam": {"Type": "CSP", "IsSystemApp": False, "Enabled": False, "Description": ""},
    "/csp/sys": {"Type": "System,CSP", "IsSystemApp": False, "Enabled": True, "Description": "System Management Portal"},
    "/api/admin": {"Type": "CSP", "IsSystemApp": False, "Enabled": True, "Description": "System Administration API"},
    "/api/mgmnt": {"Type": "CSP", "IsSystemApp": False, "Enabled": True, "Description": "API Management"},
    "/flagged": {"Type": "CSP", "IsSystemApp": True, "Enabled": True, "Description": "flagged system app"},
}


class FakeIris:
    """GET /v2/web-apps, GET/PUT /v2/web-app. The PUT merges only keys sent
    and forces Type = CSP, like IRIS's MergeJsonAndProperties()."""

    def __init__(self) -> None:
        self.apps = copy.deepcopy(_APPS)
        self.put_error: int | None = None
        self.put_changes_description = True
        self.put_also_disables = False
        self.info_privileges: frozenset[str] = _PRIVILEGES
        self.client = AsyncMock()
        self.client.get.side_effect = self._get
        self.client.put.side_effect = self._put

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/web-apps":
            return {**_ENVELOPE, "result": [
                {"Name": name, "Namespace": "%SYS", "NamespaceDefault": False, "Enabled": a["Enabled"],
                 "Type": a["Type"], "Resource": "", "AuthenticationMethods": ["Password"],
                 "IsSystemApp": a["IsSystemApp"], "DispatchClass": ""}
                for name, a in self.apps.items()
            ]}
        if path == "/v2/web-app":
            a = self.apps.get(params["name"])
            if a is None:
                raise IRISResponseError(404)
            return {**_ENVELOPE, "result": {"Description": a["Description"], "Enabled": a["Enabled"], "NameSpace": "%SYS"}}
        if path == "/info":
            return {**_ENVELOPE, "result": {
                "apiVersion": 2, "username": "test-user", "serverVersion": "IRIS 2026.2", "systemMode": "",
                "product": "iris", "namespaces": [{"name": "%SYS"}],
                "privileges": {p: {"use": True} for p in sorted(self.info_privileges)},
            }}
        raise AssertionError(f"unexpected GET {path}")

    async def _put(self, path: str, json: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path == "/v2/web-app"
        if self.put_error:
            raise IRISResponseError(self.put_error)
        a = self.apps[params["name"]]
        if self.put_changes_description:
            a.update(json)
        a["Type"] = "CSP"  # IRIS always sets Type to CSP
        if self.put_also_disables:
            a["Enabled"] = False
        return {**_ENVELOPE, "result": {"Description": a["Description"], "Enabled": a["Enabled"]}}


@pytest.fixture
def iris() -> FakeIris:
    return FakeIris()


@pytest.fixture
def executor(iris: FakeIris) -> OperationExecutor:
    handler = WebAppUpdateDescriptionHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(name: str = "/csp/user", description: Any = "User apps (reviewed)", **extra: Any) -> OperationRequest:
    return OperationRequest(operation_name=_OPERATION_NAME, parameters={"Name": name, "Description": description, **extra})


def _context(*, privileges: frozenset[str] = _PRIVILEGES, confirmed: bool = True, dry_run: bool = False) -> ExecutionContext:
    return ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run)


# --- authorization / confirmation ---


@pytest.mark.asyncio
async def test_missing_manage_privilege_is_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Secure"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_manage_without_secure_is_rejected_before_any_iris_call(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Manage"})))

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["missing_iris_privilege"] == "Secure"
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
    result = await executor.execute(_request(), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    data = result.handler_result.data
    assert data["description_before"] == "User Namespace applications"
    assert data["description_after"] == "User apps (reviewed)"
    assert data["request"] == {"method": "PUT", "path": "/v2/web-app", "query": {"name": "/csp/user"},
                               "body": {"Description": "User apps (reviewed)"}}
    assert "No request was sent" in result.handler_result.detail
    iris.client.put.assert_not_awaited()
    assert iris.apps["/csp/user"]["Description"] == "User Namespace applications"


# --- refusals ---


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["/api/admin", "/API/Admin/", "/api/mgmnt"])
async def test_command_center_dependencies_are_hard_denied(executor: OperationExecutor, iris: FakeIris, name: str) -> None:
    result = await executor.execute(_request(name=name), _context())

    assert result.handler_result.data["protected"] is True
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["/csp/sys", "/flagged"])
async def test_system_apps_are_hard_denied(executor: OperationExecutor, iris: FakeIris, name: str) -> None:
    result = await executor.execute(_request(name=name), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    assert "System web application" in result.handler_result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_app_is_rejected_and_never_created(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="/csp/nope"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "No web application named '/csp/nope'" in result.handler_result.detail
    iris.client.put.assert_not_awaited()
    assert "/csp/nope" not in iris.apps


@pytest.mark.asyncio
async def test_same_description_is_a_no_op_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(description="User Namespace applications"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["no_change"] is True
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreadable_current_description_is_rejected_not_guessed(executor: OperationExecutor, iris: FakeIris) -> None:
    original_get = iris.client.get.side_effect

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = await original_get(path, params)
        if path == "/v2/web-app":
            body = {**body, "result": {"Enabled": True}}
        return body

    iris.client.get.side_effect = get

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "Could not read" in result.handler_result.detail
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "phrase"),
    [
        ({"Name": "/csp/user", "Description": "x" * 257}, "at most 256"),
        ({"Name": "/csp/user", "Description": "line one\nline two"}, "control characters"),
        ({"Name": "/csp/user", "Description": "tab\there"}, "control characters"),
        ({"Name": "/csp/user", "Description": 42}, "Description"),
        ({"Name": "/csp/user", "Description": None}, "Description"),
        ({"Name": "/csp/user"}, "Description"),
        ({"Name": "csp/user", "Description": "x"}, "must start with '/'"),
        ({"Name": "/csp/../sys", "Description": "x"}, "'..'"),
        ({"Name": "/csp/user", "Description": "x", "Enabled": False}, "Enabled"),
        ({"Name": "/csp/user", "Description": "x", "NameSpace": "USER"}, "NameSpace"),
    ],
)
async def test_malformed_requests_are_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, parameters: dict[str, Any], phrase: str
) -> None:
    result = await executor.execute(OperationRequest(operation_name=_OPERATION_NAME, parameters=parameters), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.detail.startswith("Invalid web_app.update_description request")
    assert phrase in result.handler_result.detail
    iris.client.get.assert_not_awaited()
    iris.client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_exactly_256_characters_and_empty_are_allowed(executor: OperationExecutor, iris: FakeIris) -> None:
    long_result = await executor.execute(_request(description="d" * 256), _context(dry_run=True))
    empty_result = await executor.execute(_request(description=""), _context(dry_run=True))

    assert long_result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert empty_result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert empty_result.handler_result.data["request"]["body"] == {"Description": ""}


# --- execution + verification ---


@pytest.mark.asyncio
async def test_successful_update_sends_only_description_and_verifies(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.put.assert_awaited_once_with(
        "/v2/web-app", json={"Description": "User apps (reviewed)"}, params={"name": "/csp/user"}
    )
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert iris.apps["/csp/user"]["Description"] == "User apps (reviewed)"
    assert iris.apps["/csp/user"]["Enabled"] is True


@pytest.mark.asyncio
async def test_update_of_a_disabled_app_keeps_it_disabled(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(name="/api/iam", description="IAM API"), _context())

    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert iris.apps["/api/iam"]["Enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "phrase"), [(403, "requires %Admin_Secure"), (400, "invalid")])
async def test_iris_errors_on_put_are_clear_failures(executor: OperationExecutor, iris: FakeIris, code: int, phrase: str) -> None:
    iris.put_error = code

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert phrase in result.handler_result.detail
    assert "Nothing was changed" in result.handler_result.detail


@pytest.mark.asyncio
async def test_verification_fails_if_description_never_changes(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.put_changes_description = False

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "4 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_fails_if_another_setting_changed(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.put_also_disables = True

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "another setting changed" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(executor: OperationExecutor, iris: FakeIris) -> None:
    original_get = iris.client.get.side_effect

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if iris.client.put.await_count:
            raise IRISConnectionError("boom")
        return await original_get(path, params)

    iris.client.get.side_effect = get

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "read error" in result.verification.detail


@pytest.mark.asyncio
async def test_trace_records_every_stage(executor: OperationExecutor) -> None:
    clear_traces()

    await executor.execute(_request(), _context())

    trace = list_traces()[0]
    assert trace.operation_name == _OPERATION_NAME
    assert trace.status == "success"
    assert [s.name for s in trace.spans] == ["authorization", "confirmation", "execution", "verification"]
    assert trace.verification_result == "verified"
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

    response = client.post("/api/iris/web-apps/update-description", json={"Name": "/csp/user", "Description": "x"})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.put.assert_not_awaited()


def test_route_dry_run_never_writes(client: TestClient, mock_iris_client: AsyncMock) -> None:
    fake = _route_client(mock_iris_client)

    response = client.post(
        "/api/iris/web-apps/update-description",
        json={"Name": "/csp/user", "Description": "x", "confirmed": True, "dry_run": True},
    )

    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["data"]["request"]["body"] == {"Description": "x"}
    mock_iris_client.put.assert_not_awaited()
    assert fake.apps["/csp/user"]["Description"] == "User Namespace applications"


def test_route_system_app_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post(
        "/api/iris/web-apps/update-description", json={"Name": "/csp/sys", "Description": "x", "confirmed": True}
    )

    assert response.json()["handler_result"]["data"]["protected"] is True
    mock_iris_client.put.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"Name": "/csp/user", "Description": "x", "confirmed": True, "Enabled": False},
        {"Name": "/csp/user", "Description": "x", "confirmed": True, "force": True},
        {"Name": "/csp/user", "Description": 42, "confirmed": True},
        {"Name": "/csp/user", "confirmed": True},
    ],
)
def test_route_rejects_unknown_fields_and_non_string(
    client: TestClient, mock_iris_client: AsyncMock, payload: dict[str, Any]
) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/web-apps/update-description", json=payload)

    assert response.status_code == 422
    mock_iris_client.put.assert_not_awaited()


def test_route_is_post_only() -> None:
    assert set(app.openapi()["paths"]["/api/iris/web-apps/update-description"]) == {"post"}
