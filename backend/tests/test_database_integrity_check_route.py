"""Tests for GET /api/iris/databases/integrity-check?dir=<Directory>.

We've never run a real integrity check, so the task results below are made
up. They use different `Result` shapes (dict, list, null) to show the route
doesn't assume anything about it.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISAsyncTaskError, IRISResponseError


def _finished_task(result: Any) -> dict[str, Any]:
    """The usual async-task envelope around a made-up `result`."""
    return {
        "State": "Finished",
        "TaskName": "POST /v2/database-dir/integrity-check",
        "Console": [],
        "FailureReason": "",
        "Result": result,
        "TimeQueued": "2026-09-23 10:00:00",
        "TimeStarted": "2026-09-23 10:00:00",
        "TimeFinished": "2026-09-23 10:00:05",
    }


def test_get_database_integrity_check_success_with_dict_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "task-dict-001"
    mock_iris_client.wait_for_async_task.return_value = _finished_task(
        {"ErrorCount": 0, "GlobalsChecked": 42}
    )

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["State"] == "Finished"
    assert body["Result"] == {"ErrorCount": 0, "GlobalsChecked": 42}
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/database-dir/integrity-check",
        json={"Databases": [{"Directory": "/usr/irissys/mgr/user/"}]},
    )
    mock_iris_client.wait_for_async_task.assert_awaited_once_with("task-dict-001")


def test_get_database_integrity_check_success_with_list_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A list Result comes back unchanged too, not just a dict."""
    mock_iris_client.post_async_task.return_value = "task-list-002"
    mock_iris_client.wait_for_async_task.return_value = _finished_task(
        ["no errors found"]
    )

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 200
    assert response.json()["Result"] == ["no errors found"]


def test_get_database_integrity_check_success_with_null_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "task-null-003"
    mock_iris_client.wait_for_async_task.return_value = _finished_task(None)

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 200
    assert response.json()["Result"] is None


def test_get_database_integrity_check_forwards_optional_fields_when_provided(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "task-004"
    mock_iris_client.wait_for_async_task.return_value = _finished_task({})

    response = client.get(
        "/api/iris/databases/integrity-check",
        params={"dir": "/usr/irissys/mgr/user/", "maxProcesses": 4, "partialCheck": True},
    )

    assert response.status_code == 200
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/database-dir/integrity-check",
        json={
            "Databases": [{"Directory": "/usr/irissys/mgr/user/"}],
            "MaxProcesses": 4,
            "PartialCheck": True,
        },
    )


def test_get_database_integrity_check_omits_optional_fields_when_not_provided(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "task-005"
    mock_iris_client.wait_for_async_task.return_value = _finished_task({})

    client.get("/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"})

    _, kwargs = mock_iris_client.post_async_task.call_args
    assert "MaxProcesses" not in kwargs["json"]
    assert "PartialCheck" not in kwargs["json"]


def test_get_database_integrity_check_requires_dir_query_param(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    response = client.get("/api/iris/databases/integrity-check")

    assert response.status_code == 422
    mock_iris_client.post_async_task.assert_not_awaited()


def test_get_database_integrity_check_handles_failed_task(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "some-task-id"
    mock_iris_client.wait_for_async_task.side_effect = IRISAsyncTaskError(
        "IRIS async task some-task-id ended in state 'Failed': boom", state="Failed"
    )

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 502


def test_get_database_integrity_check_handles_post_failure(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.side_effect = IRISAsyncTaskError(
        "IRIS did not return a Location header"
    )

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 502
    mock_iris_client.wait_for_async_task.assert_not_awaited()


def test_get_database_integrity_check_propagates_iris_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.side_effect = IRISResponseError(500)

    response = client.get(
        "/api/iris/databases/integrity-check", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 502
    mock_iris_client.wait_for_async_task.assert_not_awaited()
