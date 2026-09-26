"""Tests for the Investigation page routes:
GET /api/iris/security/audit/enabled and GET /api/iris/security/audit/records.

Canned bodies are trimmed real responses.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISAsyncTaskError, IRISResponseError

AUDIT_ENABLED_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {"Enabled": True},
}

# Result of a finished task: real audit records, trimmed to two.
FINISHED_AUDIT_TASK: dict[str, Any] = {
    "State": "Finished",
    "TaskName": "POST /v2/security/audit/records",
    "Console": [],
    "FailureReason": "",
    "Result": [
        {
            "SystemID": "3158de9e5dc1:IRIS",
            "AuditIndex": 393,
            "TimeStamp": "2026-09-19 14:10:36.808",
            "EventSource": "%System",
            "EventType": "%Security",
            "Event": "AuditReport",
            "Pid": 14009,
            "SessionID": "",
            "Username": "_SYSTEM",
            "Description": "List Query",
            "UTCTimeStamp": "2026-09-19 14:10:36.808",
            "JobNumber": 26,
            "Authentication": "Password",
            "ClientExecutableName": "",
            "ClientIPAddress": "",
            "EventData": "Query name:         List\r\n",
            "Namespace": "%SYS",
            "Roles": "%All",
            "RoutineSpec": "",
            "UserInfo": "",
            "JobId": 655386,
            "Status": "",
            "OSUsername": "irisowner",
            "StartupClientIPAddress": "",
        },
        {
            "SystemID": "3158de9e5dc1:IRIS",
            "AuditIndex": 392,
            "TimeStamp": "2026-09-19 06:42:01.310",
            "EventSource": "%System",
            "EventType": "%Security",
            "Event": "AuditChange",
            "Pid": 9538,
            "SessionID": "",
            "Username": "_SYSTEM",
            "Description": "Delete audit data",
            "UTCTimeStamp": "2026-09-19 06:42:01.310",
            "JobNumber": 30,
            "Authentication": "Unauthenticated",
            "ClientExecutableName": "",
            "ClientIPAddress": "",
            "EventData": "Deleted 0 audit records:\r\n",
            "Namespace": "%SYS",
            "Roles": "%All",
            "RoutineSpec": "",
            "UserInfo": "",
            "JobId": 655386,
            "Status": "",
            "OSUsername": "irisowner",
            "StartupClientIPAddress": "",
        },
    ],
}


def test_get_audit_enabled_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = AUDIT_ENABLED_BODY

    response = client.get("/api/iris/security/audit/enabled")

    assert response.status_code == 200
    assert response.json()["result"]["Enabled"] is True
    mock_iris_client.get.assert_awaited_once_with("/v2/security/audit/enabled")


def test_get_audit_enabled_propagates_iris_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(500)

    response = client.get("/api/iris/security/audit/enabled")

    assert response.status_code == 502


def test_get_audit_records_success_with_no_filters(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "030002872038736621054186"
    mock_iris_client.wait_for_async_task.return_value = FINISHED_AUDIT_TASK

    response = client.get("/api/iris/security/audit/records")

    assert response.status_code == 200
    body = response.json()
    assert len(body["result"]) == 2
    assert body["result"][0]["Event"] == "AuditReport"
    assert body["result"][1]["Event"] == "AuditChange"
    # No filters means empty params, which IRIS treats as "everything".
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/security/audit/records", params={}
    )
    mock_iris_client.wait_for_async_task.assert_awaited_once_with("030002872038736621054186")


def test_get_audit_records_forwards_only_documented_filters(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "some-task-id"
    mock_iris_client.wait_for_async_task.return_value = {
        "State": "Finished",
        "TaskName": "POST /v2/security/audit/records",
        "Console": [],
        "FailureReason": "",
        "Result": [],
    }

    response = client.get(
        "/api/iris/security/audit/records",
        params={
            "beginDateTime": "2026-09-19 00:00:00",
            "eventTypes": "%Security",
            "ascending": 0,
        },
    )

    assert response.status_code == 200
    mock_iris_client.post_async_task.assert_awaited_once_with(
        "/v2/security/audit/records",
        params={
            "beginDateTime": "2026-09-19 00:00:00",
            "eventTypes": "%Security",
            "ascending": 0,
        },
    )


def test_get_audit_records_handles_failed_task(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.return_value = "some-task-id"
    mock_iris_client.wait_for_async_task.side_effect = IRISAsyncTaskError(
        "IRIS async task some-task-id ended in state 'Failed': boom", state="Failed"
    )

    response = client.get("/api/iris/security/audit/records")

    assert response.status_code == 502


def test_get_audit_records_handles_post_failure(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.post_async_task.side_effect = IRISAsyncTaskError(
        "IRIS did not return a Location header"
    )

    response = client.get("/api/iris/security/audit/records")

    assert response.status_code == 502
    mock_iris_client.wait_for_async_task.assert_not_awaited()
