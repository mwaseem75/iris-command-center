"""Tests for database.mount, using a mocked IRISClient."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.execution.database_mount_handler import DatabaseMountHandler
from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.iris_client.exceptions import IRISAsyncTaskError, IRISResponseError

_OPERATION_NAME = "database.mount"
_DIRECTORY = "/usr/irissys/mgr/mydb/"


def _info_task(mounted: Any) -> dict[str, Any]:
    """Finished POST /v2/database-dir/info task with just the fields the handler reads."""
    return {
        "State": "Finished",
        "TaskName": "POST /v2/database-dir/info",
        "Console": [],
        "FailureReason": "",
        "Result": {"Mounted": mounted, "ReadOnlyReason": ""},
        "TimeQueued": "",
        "TimeStarted": "",
        "TimeFinished": "",
    }


@pytest.fixture
def fake_iris_client() -> AsyncMock:
    client = AsyncMock()
    client.post_async_task.return_value = "task-1"
    client.post.return_value = {"status": {"errors": [], "summary": ""}, "console": [], "result": {}}
    return client


@pytest.fixture
def executor(fake_iris_client: AsyncMock) -> OperationExecutor:
    handler = DatabaseMountHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(directory: str = _DIRECTORY, read_only: bool | None = None) -> OperationRequest:
    params: dict[str, Any] = {"Directory": directory}
    if read_only is not None:
        params["ReadOnly"] = read_only
    return OperationRequest(operation_name=_OPERATION_NAME, parameters=params)


def _context(
    *, privileges: frozenset[str] = frozenset({"Operate"}), confirmed: bool = True, dry_run: bool = False
) -> ExecutionContext:
    return ExecutionContext(
        available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run
    )


# --- authorization / confirmation ---


@pytest.mark.asyncio
async def test_missing_operate_privilege_is_denied(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset({"Manage"})))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    fake_iris_client.post_async_task.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(_request(), _context(confirmed=False))

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    fake_iris_client.post_async_task.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


# --- dry-run ---


@pytest.mark.asyncio
async def test_dry_run_on_dismounted_database_succeeds_without_mounting(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(False)

    result = await executor.execute(_request(read_only=True), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert result.handler_result.data == {"directory": _DIRECTORY, "read_only": True}
    fake_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/database-dir/info", params={"dir": _DIRECTORY}
    )
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_on_already_mounted_database_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(True)

    result = await executor.execute(_request(), _context(dry_run=True))

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already mounted" in result.handler_result.detail
    assert result.handler_result.data["already_mounted"] is True
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_on_missing_database_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.post_async_task.side_effect = IRISResponseError(404, body=None)

    result = await executor.execute(_request(), _context(dry_run=True))

    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "No database exists" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_mount_state_is_rejected_not_guessed(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(None)

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "Could not determine" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("directory", ["", "relative/path", "/usr/../etc/"])
async def test_invalid_directory_is_rejected_before_any_iris_call(
    executor: OperationExecutor, fake_iris_client: AsyncMock, directory: str
) -> None:
    result = await executor.execute(_request(directory=directory), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.post_async_task.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


# --- execution + verification ---


@pytest.mark.asyncio
async def test_successful_mount_sends_documented_request_and_verifies(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.side_effect = [_info_task(False), _info_task(True)]

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    fake_iris_client.post.assert_awaited_once_with(
        "/v2/database-dir/mount", params={"dir": _DIRECTORY}, json={"ReadOnly": False}
    )


@pytest.mark.asyncio
async def test_mount_never_sends_cluster_or_mirror_fields(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.side_effect = [_info_task(False), _info_task(True)]

    await executor.execute(_request(read_only=True), _context())

    body = fake_iris_client.post.await_args.kwargs["json"]
    assert body == {"ReadOnly": True}


@pytest.mark.asyncio
async def test_409_is_reported_as_already_mounted(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(False)
    fake_iris_client.post.side_effect = IRISResponseError(409, body=None)

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "already mounted" in result.handler_result.detail
    assert "409" in result.handler_result.detail
    assert result.verification is None


@pytest.mark.asyncio
async def test_already_mounted_at_execute_time_never_posts(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(True)

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_retries_until_mounted(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.side_effect = [
        _info_task(False),  # _validate()
        _info_task(False),  # verify attempt 1
        _info_task(True),  # verify attempt 2
    ]

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.SUCCESS
    assert "took 2 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_is_bounded_and_fails_if_never_mounted(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.return_value = _info_task(False)

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    # 1 validation read + 4 verify reads (one right away, three retries).
    assert fake_iris_client.wait_for_async_task.await_count == 5
    assert "after 4 attempts" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_read_error_is_verification_failed_not_a_crash(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    fake_iris_client.wait_for_async_task.side_effect = [
        _info_task(False),
        *[IRISAsyncTaskError("boom", state="Failed")] * 4,
    ]

    result = await executor.execute(_request(), _context())

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "IRISAsyncTaskError" in result.verification.detail


# --- route ---

_INFO_BODY_OPERATE: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS 2026.2",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}],
        "privileges": {"Operate": {"use": True}},
    },
}

_INFO_BODY_MANAGE_ONLY: dict[str, Any] = {
    **_INFO_BODY_OPERATE,
    "result": {**_INFO_BODY_OPERATE["result"], "privileges": {"Manage": {"use": True}}},
}


def test_route_requires_confirmation(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = _INFO_BODY_OPERATE

    response = client.post("/api/iris/databases/mount", json={"Directory": _DIRECTORY})

    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"
    mock_iris_client.post.assert_not_awaited()


def test_route_without_operate_is_denied(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = _INFO_BODY_MANAGE_ONLY

    response = client.post(
        "/api/iris/databases/mount", json={"Directory": _DIRECTORY, "confirmed": True}
    )

    assert response.json()["status"] == "unauthorized"
    mock_iris_client.post.assert_not_awaited()


def test_route_dry_run_never_mounts(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = _INFO_BODY_OPERATE
    mock_iris_client.post_async_task.return_value = "task-1"
    mock_iris_client.wait_for_async_task.return_value = _info_task(False)

    response = client.post(
        "/api/iris/databases/mount",
        json={"Directory": _DIRECTORY, "confirmed": True, "dry_run": True},
    )

    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["outcome"] == "success"
    mock_iris_client.post.assert_not_awaited()


def test_route_rejects_unknown_fields(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = _INFO_BODY_OPERATE

    response = client.post(
        "/api/iris/databases/mount",
        json={"Directory": _DIRECTORY, "confirmed": True, "Cluster": True},
    )

    assert response.status_code == 422
    mock_iris_client.post.assert_not_awaited()
