"""Tests for GET /api/iris/databases/info?dir=<Directory> — the Database
Explorer's "View Info" drawer action (database.info).

Uses mocks (fixtures shared via conftest.py) rather than the real IRIS
container. The canned task body is the ACTUAL response captured while
verifying this endpoint against icc-iris-dev (POST /v2/database-dir/info
for the real USER database), not invented data — see
app/models/iris.py's DatabaseInfoResult docstring.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISAsyncTaskError, IRISResponseError

# The Result object inside a Finished AsyncTask, as returned by
# wait_for_async_task — captured live from `POST /v2/database-dir/info`
# for dir=/usr/irissys/mgr/user/.
FINISHED_DATABASE_INFO_TASK: dict[str, Any] = {
    "State": "Finished",
    "TaskName": "POST /v2/database-dir/info",
    "Console": [],
    "FailureReason": "",
    "Result": {
        "Size": 11,
        "ExpansionSize": 0,
        "MaxSize": 0,
        "ReadOnlyReason": "",
        "EncryptionKeyID": "",
        "BlockSize": 8192,
        "Blocks": 1408,
        "AvailableSpace": 9.9,
        "DiskFree": "951.34GB",
        "EndFree": 9,
        "LastExpansionTime": "2026-09-17 21:08:05",
        "MirrorSetName": "",
        "MirrorDBName": "",
        "SFN": 7,
        "Mirrored": False,
        "Encrypted": False,
        "Full": False,
        "Mounted": True,
        "MirrorFailoverDB": False,
    },
    "TimeQueued": "2026-09-22 17:02:47",
    "TimeStarted": "2026-09-22 17:02:47",
    "TimeFinished": "2026-09-22 17:02:47",
}


def test_get_database_info_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.post_async_task.return_value = "909684469023707471409894"
    mock_iris_client.wait_for_async_task.return_value = FINISHED_DATABASE_INFO_TASK

    response = client.get(
        "/api/iris/databases/info", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["Size"] == 11
    assert result["BlockSize"] == 8192
    assert result["Blocks"] == 1408
    assert result["DiskFree"] == "951.34GB"
    assert result["Mounted"] is True
    assert result["Encrypted"] is False
    assert result["Mirrored"] is False
    assert result["Full"] is False
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/database-dir/info", params={"dir": "/usr/irissys/mgr/user/"}
    )
    mock_iris_client.wait_for_async_task.assert_awaited_once_with("909684469023707471409894")


def test_get_database_info_requires_dir_query_param(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    response = client.get("/api/iris/databases/info")

    assert response.status_code == 422
    mock_iris_client.post_async_task.assert_not_awaited()


def test_get_database_info_handles_failed_task(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "some-task-id"
    mock_iris_client.wait_for_async_task.side_effect = IRISAsyncTaskError(
        "IRIS async task some-task-id ended in state 'Failed': boom", state="Failed"
    )

    response = client.get(
        "/api/iris/databases/info", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 502


def test_get_database_info_handles_post_failure(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.side_effect = IRISAsyncTaskError(
        "IRIS did not return a Location header"
    )

    response = client.get(
        "/api/iris/databases/info", params={"dir": "/usr/irissys/mgr/user/"}
    )

    assert response.status_code == 502
    mock_iris_client.wait_for_async_task.assert_not_awaited()


def test_get_database_info_propagates_not_found(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A directory with no database (mainspec_v2.json documents a 404 for
    this case) reaches IRIS as a real HTTP error via post_async_task's own
    request — surfaced the same generic, safe way every other IRIS client
    error in this route is."""
    mock_iris_client.post_async_task.side_effect = IRISResponseError(404)

    response = client.get(
        "/api/iris/databases/info", params={"dir": "/usr/irissys/mgr/does-not-exist/"}
    )

    assert response.status_code == 502
    mock_iris_client.wait_for_async_task.assert_not_awaited()
