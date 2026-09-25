"""Tests for database.dismount. Every test uses a fake/mock IRISClient — no
real network call is made, and no test (or anything else in this project)
performs a real POST /v2/database-dir/dismount.

GET /v2/databases and GET /v2/namespaces answers are the REAL ones captured
from icc-iris-dev (plus a custom "APPDATA" database and a mirrored one). The
fake mirrors IRIS's own implementation (see
app/execution/database_dismount_handler.py's docstring): database-dir/info
is an async task reporting Mounted/Mirrored, an unknown directory is a 404,
and the dismount itself takes no body.
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.database_dismount_handler import DatabaseDismountHandler
from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app
from app.observability.store import clear_traces, list_traces

_OPERATION_NAME = "database.dismount"
_ENVELOPE = {"status": {"errors": [], "summary": ""}, "console": []}
_PRIVILEGES = frozenset({"Operate"})


def _db(name: str, directory: str, mount_required: Any) -> dict[str, Any]:
    return {"Name": name, "Directory": directory, "Server": "", "ClusterMountMode": False,
            "MountRequired": mount_required, "MountAtStartup": True, "StreamLocation": "", "Status": "Mounted/RW"}


# Real GET /v2/databases (icc-iris-dev) + two test databases.
_DATABASES = [
    _db("IRISSYS", "/usr/irissys/mgr/", True),
    _db("IRISSECURITY", "/usr/irissys/mgr/irissecurity/", True),
    _db("IRISLIB", "/usr/irissys/mgr/irislib/", True),
    _db("IRISTEMP", "/usr/irissys/mgr/iristemp/", True),
    _db("IRISLOCALDATA", "/usr/irissys/mgr/irislocaldata/", True),
    _db("IRISAUDIT", "/usr/irissys/mgr/irisaudit/", True),
    _db("ENSLIB", "/usr/irissys/mgr/enslib/", False),
    _db("IRISMETRICS", "/usr/irissys/mgr/irismetrics/", True),
    _db("IPM", "/usr/irissys/mgr/zpm/", False),
    _db("USER", "/usr/irissys/mgr/user/", False),
    _db("APPDATA", "/data/appdata/", False),
    _db("REQUIREDAPP", "/data/requiredapp/", True),
    _db("MIRRORED", "/data/mirrored/", False),
    _db("SYSUSED", "/data/sysused/", False),
]


def _ns(name: str, globals_db: str, routines_db: str) -> dict[str, Any]:
    return {"Name": name, "Globals": globals_db, "Routines": routines_db, "Library": "IRISLIB",
            "SysGlobals": "IRISSYS", "SysRoutines": "IRISSYS", "TempGlobals": "IRISTEMP"}


# Real GET /v2/namespaces (icc-iris-dev) + one that makes SYSUSED a %SYS database.
_NAMESPACES = [
    _ns("%ALL", "%DEFAULTDB", "%DEFAULTDB"),
    {**_ns("%SYS", "IRISSYS", "IRISSYS"), "TempGlobals": "SYSUSED"},
    _ns("DDD", "USER", "IRISSECURITY"),
    _ns("TEST", "USER", "USER"),
    _ns("TTTT", "USER", "USER"),
    _ns("USER", "USER", "USER"),
    _ns("APP", "APPDATA", "APPDATA"),
]


class FakeIris:
    """GET /v2/databases, /v2/namespaces; database-dir/info as an async task;
    POST /v2/database-dir/dismount."""

    def __init__(self) -> None:
        self.info = {db["Directory"]: {"Mounted": True, "Mirrored": False} for db in _DATABASES}
        self.info["/data/mirrored/"]["Mirrored"] = True
        self.dismount_changes_state = True
        self.post_error: int | None = None
        self.info_error_after_dismount = False
        self.info_privileges: frozenset[str] = _PRIVILEGES
        self.client = AsyncMock()
        self.client.get.side_effect = self._get
        self.client.post.side_effect = self._post
        self.client.post_async_task.side_effect = self._post_async_task
        self.client.wait_for_async_task.side_effect = self._wait

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/databases":
            return {**_ENVELOPE, "result": copy.deepcopy(_DATABASES)}
        if path == "/v2/namespaces":
            return {**_ENVELOPE, "result": copy.deepcopy(_NAMESPACES)}
        if path == "/info":
            return {**_ENVELOPE, "result": {
                "apiVersion": 2, "username": "test-user", "serverVersion": "IRIS 2026.2", "systemMode": "",
                "product": "iris", "namespaces": [{"name": "%SYS"}],
                "privileges": {p: {"use": True} for p in sorted(self.info_privileges)},
            }}
        raise AssertionError(f"unexpected GET {path}")

    async def _post_async_task(self, path: str, params: dict[str, Any] | None = None, json: Any = None) -> str:
        assert path == "/v2/database-dir/info"
        if self.info_error_after_dismount and self.client.post.await_count:
            raise IRISConnectionError("boom")
        if params["dir"] not in self.info:
            raise IRISResponseError(404)
        return params["dir"]

    async def _wait(self, task_id: str) -> dict[str, Any]:
        return {"State": "Finished", "Result": {**self.info[task_id], "Size": 1, "BlockSize": 8192}}

    async def _post(self, path: str, json: Any = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path == "/v2/database-dir/dismount"
        assert json is None, "dismount takes no request body"
        if self.post_error:
            raise IRISResponseError(self.post_error)
        if self.dismount_changes_state:
            self.info[params["dir"]]["Mounted"] = False
        return {**_ENVELOPE, "result": {}}


@pytest.fixture
def iris() -> FakeIris:
    return FakeIris()


@pytest.fixture
def executor(iris: FakeIris) -> OperationExecutor:
    return OperationExecutor({_OPERATION_NAME: DatabaseDismountHandler(iris.client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))})


def _request(directory: Any = "/data/appdata/", **extra: Any) -> OperationRequest:
    return OperationRequest(operation_name=_OPERATION_NAME, parameters={"Directory": directory, **extra})


def _context(*, privileges: frozenset[str] = _PRIVILEGES, confirmed: bool = True, dry_run: bool = False) -> ExecutionContext:
    return ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run)


def _assert_nothing_dismounted(iris: FakeIris) -> None:
    iris.client.post.assert_not_awaited()


# --- authorization / confirmation ---


@pytest.mark.asyncio
async def test_missing_operate_privilege_is_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Manage", "Secure"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    iris.client.get.assert_not_awaited()
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context(confirmed=False))

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    iris.client.get.assert_not_awaited()
    _assert_nothing_dismounted(iris)


# --- dry run ---


@pytest.mark.asyncio
async def test_dry_run_previews_affected_namespaces_without_dismounting(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/usr/irissys/mgr/user/"), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    data = result.handler_result.data
    assert data["name"] == "USER"
    assert data["namespaces"] == ["DDD", "TEST", "TTTT", "USER"]
    assert data["request"] == {"method": "POST", "path": "/v2/database-dir/dismount",
                               "query": {"dir": "/usr/irissys/mgr/user/"}, "body": None}
    assert "DDD, TEST, TTTT, USER" in result.handler_result.detail
    assert "No request was sent" in result.handler_result.detail
    _assert_nothing_dismounted(iris)
    assert iris.info["/usr/irissys/mgr/user/"]["Mounted"] is True


@pytest.mark.asyncio
async def test_dry_run_of_a_protected_database_is_also_refused(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/usr/irissys/mgr/irislib/"), _context(dry_run=True))

    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    _assert_nothing_dismounted(iris)


# --- refusals ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "directory",
    ["/usr/irissys/mgr/", "/usr/irissys/mgr/irissecurity/", "/usr/irissys/mgr/irislib/", "/usr/irissys/mgr/iristemp/",
     "/usr/irissys/mgr/irislocaldata/", "/usr/irissys/mgr/irisaudit/", "/usr/irissys/mgr/enslib/",
     "/usr/irissys/mgr/irismetrics/"],
)
async def test_iris_system_databases_are_hard_denied(executor: OperationExecutor, iris: FakeIris, directory: str) -> None:
    result = await executor.execute(_request(directory), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["protected"] is True
    assert "IRIS system database" in result.handler_result.detail
    iris.client.post_async_task.assert_not_awaited()
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_mount_required_database_is_hard_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/data/requiredapp/"), _context())

    assert result.handler_result.data["protected"] is True
    assert "Mount Required" in result.handler_result.detail
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_database_used_by_sys_namespace_is_hard_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/data/sysused/"), _context())

    assert result.handler_result.data["protected"] is True
    assert "%SYS namespace" in result.handler_result.detail
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_mirrored_database_is_hard_denied(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/data/mirrored/"), _context())

    assert result.handler_result.data["protected"] is True
    assert "is mirrored" in result.handler_result.detail
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_unconfigured_directory_is_refused(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request("/data/nowhere/"), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "No configured database" in result.handler_result.detail
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_iris_404_on_info_is_refused(executor: OperationExecutor, iris: FakeIris) -> None:
    del iris.info["/data/appdata/"]

    result = await executor.execute(_request(), _context())

    assert "IRIS reports no database" in result.handler_result.detail
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
async def test_already_dismounted_is_a_no_op_failure(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.info["/data/appdata/"]["Mounted"] = False

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.data["already_dismounted"] is True
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [("Mounted", None), ("Mounted", "yes"), ("Mirrored", None)])
async def test_undetermined_state_is_refused_not_guessed(
    executor: OperationExecutor, iris: FakeIris, field: str, value: Any
) -> None:
    iris.info["/data/appdata/"][field] = value

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    _assert_nothing_dismounted(iris)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "phrase"),
    [
        ({"Directory": ""}, "Directory"),
        ({"Directory": "data/appdata/"}, "absolute path"),
        ({"Directory": "/data/../usr/irissys/mgr/"}, "'..'"),
        ({"Directory": "/data/app\0data/"}, "invalid characters"),
        ({"Directory": "/" + "d" * 600}, "too long"),
        ({"Directory": 42}, "Directory"),
        ({}, "Directory"),
        ({"Directory": "/data/appdata/", "ReadOnly": True}, "ReadOnly"),
        ({"Directory": "/data/appdata/", "force": True}, "force"),
    ],
)
async def test_malformed_requests_are_rejected_before_any_iris_call(
    executor: OperationExecutor, iris: FakeIris, parameters: dict[str, Any], phrase: str
) -> None:
    result = await executor.execute(OperationRequest(operation_name=_OPERATION_NAME, parameters=parameters), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert result.handler_result.detail.startswith("Invalid database.dismount request")
    assert phrase in result.handler_result.detail
    iris.client.get.assert_not_awaited()
    _assert_nothing_dismounted(iris)


# --- execution + verification ---


@pytest.mark.asyncio
async def test_dismount_sends_no_body_and_verifies(executor: OperationExecutor, iris: FakeIris) -> None:
    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.SUCCESS
    iris.client.post.assert_awaited_once_with("/v2/database-dir/dismount", params={"dir": "/data/appdata/"})
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "Mounted=False" in result.verification.detail
    assert iris.info["/data/appdata/"]["Mounted"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "phrase"), [(409, "HTTP 409"), (404, "HTTP 404"), (403, "requires %Admin_Operate")])
async def test_iris_errors_on_dismount_are_clear_failures(
    executor: OperationExecutor, iris: FakeIris, code: int, phrase: str
) -> None:
    iris.post_error = code

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert phrase in result.handler_result.detail
    assert "Nothing was changed" in result.handler_result.detail


@pytest.mark.asyncio
async def test_verification_fails_if_still_mounted(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.dismount_changes_state = False

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "4 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(executor: OperationExecutor, iris: FakeIris) -> None:
    iris.info_error_after_dismount = True

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
    mock_iris_client.post.side_effect = fake._post
    mock_iris_client.post_async_task.side_effect = fake._post_async_task
    mock_iris_client.wait_for_async_task.side_effect = fake._wait
    return fake


def test_route_requires_confirmation(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/databases/dismount", json={"Directory": "/data/appdata/"})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.post.assert_not_awaited()


def test_route_dry_run_never_dismounts(client: TestClient, mock_iris_client: AsyncMock) -> None:
    fake = _route_client(mock_iris_client)

    response = client.post("/api/iris/databases/dismount",
                           json={"Directory": "/data/appdata/", "confirmed": True, "dry_run": True})

    assert response.json()["status"] == "dry_run"
    mock_iris_client.post.assert_not_awaited()
    assert fake.info["/data/appdata/"]["Mounted"] is True


def test_route_system_database_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/databases/dismount", json={"Directory": "/usr/irissys/mgr/", "confirmed": True})

    assert response.json()["handler_result"]["data"]["protected"] is True
    mock_iris_client.post.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"Directory": "/data/appdata/", "confirmed": True, "ReadOnly": True},
        {"Directory": "/data/appdata/", "confirmed": True, "force": True},
        {"Directory": 42, "confirmed": True},
        {"confirmed": True},
    ],
)
def test_route_rejects_unknown_fields_and_non_string(
    client: TestClient, mock_iris_client: AsyncMock, payload: dict[str, Any]
) -> None:
    _route_client(mock_iris_client)

    response = client.post("/api/iris/databases/dismount", json=payload)

    assert response.status_code == 422
    mock_iris_client.post.assert_not_awaited()


def test_route_is_post_only() -> None:
    assert set(app.openapi()["paths"]["/api/iris/databases/dismount"]) == {"post"}
