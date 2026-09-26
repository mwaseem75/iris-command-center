"""Tests for the security/config read routes (OAuth2, wallet, audit,
fs-access-purposes, ...). Canned bodies are real IRIS responses.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISResponseError

WEB_APPS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "/api/admin",
            "Namespace": "%SYS",
            "NamespaceDefault": False,
            "Enabled": True,
            "Type": "CSP",
            "Resource": "",
            "AuthenticationMethods": ["Password"],
            "IsSystemApp": False,
            "DispatchClass": "%Api.Admin",
        },
        {
            "Name": "/csp/user",
            "Namespace": "USER",
            "NamespaceDefault": True,
            "Enabled": True,
            "Type": "CSP",
            "Resource": "",
            "AuthenticationMethods": ["Unauthenticated", "Password"],
            "IsSystemApp": False,
            "DispatchClass": "",
        },
    ],
}

EXT_LANG_SERVERS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {"Name": "%Python Server", "Port": 53472, "Type": "Python"},
        {"Name": "%JDBC Server", "Port": 53772, "Type": "JDBC"},
    ],
}

TASKS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "Switch Journal",
            "Type": "System",
            "Namespace": "%SYS",
            "Description": "Switches the journal file at midnight every day",
            "Id": 1,
            "Suspended": False,
            "LastFinished": "2026-09-18 09:23:00",
            "NextScheduled": "2026-09-19 00:00:00",
        },
    ],
}

EMPTY_LIST_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [],
}

JOURNAL_SETTINGS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "AlternateDirectory": "/usr/irissys/mgr/journal/",
        "ArchiveName": "",
        "BackupsBeforePurge": 2,
        "CurrentDirectory": "/usr/irissys/mgr/journal/",
        "DaysBeforePurge": 2,
        "FileSizeLimit": 1024,
        "FreezeOnError": False,
        "JournalFilePrefix": "",
        "JournalcspSession": False,
        "PurgeArchived": False,
        "CompressFiles": True,
        "wijdir": "",
        "targwijsz": 0,
    },
}

OAUTH2_SERVER_NOT_CONFIGURED_BODY: dict[str, Any] = {
    "status": {
        "errors": [
            {
                "error": "ERROR #8864: OAuth 2.0 server is not configured.",
                "code": 8864,
                "domain": "%ObjectErrors",
                "id": "OAuth2NoConfiguration",
            }
        ],
        "summary": "ERROR #8864: OAuth 2.0 server is not configured.",
    },
    "console": [],
    "result": {},
}


# --- Successful responses + client-interaction ---


def test_get_web_apps_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = WEB_APPS_BODY

    response = client.get("/api/iris/web-apps")

    assert response.status_code == 200
    body = response.json()
    assert body["result"][0]["Name"] == "/api/admin"
    assert body["result"][0]["AuthenticationMethods"] == ["Password"]
    mock_iris_client.get.assert_awaited_once_with("/v2/web-apps")


def test_get_ext_lang_servers_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = EXT_LANG_SERVERS_BODY

    response = client.get("/api/iris/ext-lang-servers")

    assert response.status_code == 200
    body = response.json()
    assert body["result"][0]["Port"] == 53472
    mock_iris_client.get.assert_awaited_once_with("/v2/ext-lang-servers")


def test_get_tasks_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = TASKS_BODY

    response = client.get("/api/iris/tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["result"][0]["Name"] == "Switch Journal"
    mock_iris_client.get.assert_awaited_once_with("/v2/tasks")


def test_get_fs_access_purposes_handles_empty_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = EMPTY_LIST_BODY

    response = client.get("/api/iris/fs-access-purposes")

    assert response.status_code == 200
    assert response.json()["result"] == []
    mock_iris_client.get.assert_awaited_once_with("/v2/fs-access-purposes")


def test_get_journal_settings_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = JOURNAL_SETTINGS_BODY

    response = client.get("/api/iris/journal/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["DaysBeforePurge"] == 2
    assert body["result"]["CompressFiles"] is True
    mock_iris_client.get.assert_awaited_once_with("/v2/journal/settings")


def test_get_oauth2_client_server_definitions_handles_empty_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = EMPTY_LIST_BODY

    response = client.get("/api/iris/security/oauth2/client/server-definitions")

    assert response.status_code == 200
    assert response.json()["result"] == []
    mock_iris_client.get.assert_awaited_once_with(
        "/v2/security/oauth2/client/server-definitions"
    )


def test_get_oauth2_server_clients_handles_empty_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = EMPTY_LIST_BODY

    response = client.get("/api/iris/security/oauth2/server/clients")

    assert response.status_code == 200
    assert response.json()["result"] == []
    mock_iris_client.get.assert_awaited_once_with("/v2/security/oauth2/server/clients")


def test_get_wallet_collections_handles_empty_result(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = EMPTY_LIST_BODY

    response = client.get("/api/iris/wallet/collections")

    assert response.status_code == 200
    assert response.json()["result"] == []
    mock_iris_client.get.assert_awaited_once_with("/v2/wallet/collections")


# --- The documented OAuth2 "not configured" application-level case ---


def test_get_oauth2_server_not_configured_is_not_treated_as_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """IRIS's 404 "not configured" is a normal answer here, not a 502."""
    mock_iris_client.get.side_effect = IRISResponseError(
        404, body=OAUTH2_SERVER_NOT_CONFIGURED_BODY
    )

    response = client.get("/api/iris/security/oauth2/server")

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == {}
    assert body["status"]["errors"][0]["id"] == "OAuth2NoConfiguration"
    mock_iris_client.get.assert_awaited_once_with("/v2/security/oauth2/server")


def test_get_oauth2_server_real_failure_without_body_is_translated(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A 404 without a body (e.g. a bad path) is still an error."""
    mock_iris_client.get.side_effect = IRISResponseError(404, body=None)

    response = client.get("/api/iris/security/oauth2/server")

    assert response.status_code == 502


# --- Error handling (test_iris_routes.py covers this more) ---


def test_get_tasks_translates_response_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(500)

    response = client.get("/api/iris/tasks")

    assert response.status_code == 502
    assert "credential" not in response.text.lower()
    assert "password" not in response.text.lower()
    assert "token" not in response.text.lower()
