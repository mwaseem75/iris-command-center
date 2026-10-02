"""Tests for the AI Assistant: the intent classifier and
GET /api/iris/assistant/query (with the conftest mock client).
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.assistant.intents import Intent, classify_intent
from app.assistant.responses import JOURNAL_CHANGE_REPLY
from app.iris_client.exceptions import IRISConnectionError

# --- classify_intent ---


def test_classify_intent_system_status() -> None:
    assert classify_intent("Show me the current IRIS system status") is Intent.SYSTEM_STATUS
    assert classify_intent("what version is this") is Intent.SYSTEM_STATUS


def test_classify_intent_process_count() -> None:
    assert classify_intent("How many processes are running?") is Intent.PROCESS_COUNT


def test_classify_intent_process_list() -> None:
    assert classify_intent("list the processes") is Intent.PROCESS_LIST
    assert classify_intent("which processes are running") is Intent.PROCESS_LIST


def test_classify_intent_database_status() -> None:
    assert classify_intent("Show database status") is Intent.DATABASE_STATUS


def test_classify_intent_web_app_status() -> None:
    assert classify_intent("what's the web app status") is Intent.WEB_APP_STATUS
    assert classify_intent("tell me about webapps") is Intent.WEB_APP_STATUS


def test_classify_intent_task_info() -> None:
    assert classify_intent("what tasks are scheduled") is Intent.TASK_INFO


def test_classify_intent_unknown() -> None:
    assert classify_intent("what's the weather today") is Intent.UNKNOWN
    assert classify_intent("") is Intent.UNKNOWN
    assert classify_intent("   ") is Intent.UNKNOWN


def test_classify_intent_journal_operation() -> None:
    assert classify_intent("change the purge archived setting") is Intent.JOURNAL_OPERATION
    assert classify_intent("turn on purge archived") is Intent.JOURNAL_OPERATION
    assert classify_intent("confirm purge archived true") is Intent.JOURNAL_OPERATION
    assert classify_intent("set PurgeArchived to false") is Intent.JOURNAL_OPERATION
    assert classify_intent("update_purge_archived") is Intent.JOURNAL_OPERATION
    assert classify_intent("journal.update_purge_archived") is Intent.JOURNAL_OPERATION



# --- GET /api/iris/assistant/query ---

INFO_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS for UNIX 2026.2 (Build 221U)",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}],
        "privileges": {"Manage": {"use": True}},
    },
}

PROCESSES_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Job": 1, "Pid": 415, "Username": "", "Device": "", "Nspace": "",
            "Routine": "CONTROL", "Commands": 0, "Globals": 0, "State": "RUN",
            "ClientName": "", "EXEname": "", "IPAddress": "", "CanBeExamined": False,
            "CanBeSuspended": False, "CanBeTerminated": False, "CanReceiveBroadcast": False,
            "PrvGblBlkCnt": 0, "OSUserName": "irisowner", "CPUTime": 830, "ParentPid": 0,
            "ElapsedTime": "12:21:08",
        },
    ],
}

DATABASES_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "IRISSYS", "Directory": "/usr/irissys/mgr/", "Server": "",
            "ClusterMountMode": False, "MountRequired": True, "MountAtStartup": True,
            "StreamLocation": "", "Status": "Mounted/RW",
        },
    ],
}

WEB_APPS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "/api/admin", "Namespace": "%SYS", "NamespaceDefault": False,
            "Enabled": True, "Type": "CSP", "Resource": "", "AuthenticationMethods": ["Password"],
            "IsSystemApp": False, "DispatchClass": "",
        },
        {
            "Name": "/csp/sys", "Namespace": "%SYS", "NamespaceDefault": True,
            "Enabled": False, "Type": "CSP", "Resource": "", "AuthenticationMethods": ["Password"],
            "IsSystemApp": True, "DispatchClass": "",
        },
    ],
}

TASKS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "Switch Journal", "Type": "System", "Namespace": "%SYS",
            "Description": "Switches the journal file at midnight every day",
            "Id": 1, "Suspended": False, "LastFinished": "2026-09-18 09:23:00",
            "NextScheduled": "2026-09-19 00:00:00",
        },
    ],
}

EMPTY_LIST_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [],
}


def test_assistant_system_status(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = INFO_BODY

    response = client.get(
        "/api/iris/assistant/query", params={"message": "Show me the current IRIS system status"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "system_status"
    assert "_SYSTEM" in body["reply"]
    assert "iris" in body["reply"]
    mock_iris_client.get.assert_awaited_once_with("/info")


def test_assistant_process_count(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = PROCESSES_BODY

    response = client.get(
        "/api/iris/assistant/query", params={"message": "How many processes are running?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "process_count"
    assert "1 process is currently running." == body["reply"]
    mock_iris_client.get.assert_awaited_once_with("/v2/processes")


def test_assistant_process_list(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = PROCESSES_BODY

    response = client.get("/api/iris/assistant/query", params={"message": "list processes"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "process_list"
    assert "CONTROL" in body["reply"]


def test_assistant_database_status(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = DATABASES_BODY

    response = client.get(
        "/api/iris/assistant/query", params={"message": "Show database status"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "database_status"
    assert "IRISSYS" in body["reply"]
    assert "Mounted/RW" in body["reply"]


def test_assistant_web_app_status(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = WEB_APPS_BODY

    response = client.get(
        "/api/iris/assistant/query", params={"message": "what's the web app status"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "web_app_status"
    assert "2 web applications" in body["reply"]
    assert "1 enabled" in body["reply"]


def test_assistant_task_info(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = TASKS_BODY

    response = client.get(
        "/api/iris/assistant/query", params={"message": "what tasks are scheduled"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "task_info"
    assert "Switch Journal" in body["reply"]


def test_assistant_empty_result_is_handled_gracefully(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = EMPTY_LIST_BODY

    response = client.get("/api/iris/assistant/query", params={"message": "list processes"})

    assert response.status_code == 200
    assert "No processes" in response.json()["reply"]


def test_assistant_unknown_question_is_graceful_not_a_guess(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    response = client.get(
        "/api/iris/assistant/query", params={"message": "what's the weather today"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unknown"
    assert "read-only questions" in body["reply"]
    # An unrecognized question shouldn't call IRIS at all.
    mock_iris_client.get.assert_not_awaited()


def test_assistant_iris_unreachable_is_a_graceful_reply_not_an_http_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("connection refused")

    response = client.get(
        "/api/iris/assistant/query", params={"message": "Show me the current IRIS system status"}
    )

    # get_info() turns this into an HTTPException; the assistant catches it
    # and answers in chat instead of returning an error.
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "system_status"
    assert "couldn't reach IRIS" in body["reply"]


def test_assistant_unmapped_exception_still_surfaces_as_server_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = RuntimeError("boom")

    # Only HTTPExceptions get the friendly chat reply. Anything unexpected
    # isn't swallowed: TestClient re-raises it.
    with pytest.raises(RuntimeError, match="boom"):
        client.get(
            "/api/iris/assistant/query",
            params={"message": "Show me the current IRIS system status"},
        )


def test_assistant_never_uses_a_mutating_http_method(client: TestClient) -> None:
    # The endpoint is GET only.
    response = client.post("/api/iris/assistant/query", params={"message": "hi"})
    assert response.status_code == 405


# --- journal PurgeArchived change requests: never executed here ---
# The legacy GET endpoint answers them with a pointer to the Copilot, which
# plans, authorizes, confirms, executes and verifies the change.


@pytest.mark.parametrize("message", [
    "change the purge archived setting",
    "set purge archived to true",
    "confirm purge archived true",
    "proceed: journal.update_purge_archived false",
])
def test_assistant_journal_request_never_mutates_or_calls_iris(
    client: TestClient, mock_iris_client: AsyncMock, message: str
) -> None:
    response = client.get("/api/iris/assistant/query", params={"message": message})

    assert response.status_code == 200
    assert response.json() == {"reply": JOURNAL_CHANGE_REPLY, "intent": "journal_operation"}
    mock_iris_client.get.assert_not_awaited()
    mock_iris_client.put.assert_not_awaited()
    mock_iris_client.post.assert_not_awaited()
    mock_iris_client.post_async_task.assert_not_awaited()


def test_assistant_journal_operation_never_bypasses_confirmation() -> None:
    # ExecutionContext has no field for skipping confirmation.
    from app.execution.models import ExecutionContext

    assert set(ExecutionContext.model_fields.keys()) == {
        "available_privileges",
        "confirmation_received",
        "dry_run",
    }
