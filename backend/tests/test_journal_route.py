"""Route tests for POST /api/iris/journal/purge-archived, including
privileges from GET /info. Uses a mocked IRISClient.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

INFO_BODY_MANAGE_AND_JOURNAL: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U)",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}, {"name": "USER"}],
        "privileges": {
            "Manage": {"use": True},
            "Journal": {"use": True},
            "Operate": {"use": False},
        },
    },
}

INFO_BODY_NO_RELEVANT_PRIVILEGE: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "guest",
        "serverVersion": "IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U)",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}],
        "privileges": {
            "Operate": {"use": True},
        },
    },
}


def _journal_settings_body(purge_archived: bool) -> dict[str, Any]:
    return {
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
            "PurgeArchived": purge_archived,
            "CompressFiles": True,
            "wijdir": "",
            "targwijsz": 0,
        },
    }


def test_route_without_confirmation_is_blocked_before_put(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_MANAGE_AND_JOURNAL

    response = client.post(
        "/api/iris/journal/purge-archived", json={"PurgeArchived": True, "confirmed": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    mock_iris_client.put.assert_not_awaited()


def test_route_without_required_privilege_is_denied(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_NO_RELEVANT_PRIVILEGE

    response = client.post(
        "/api/iris/journal/purge-archived", json={"PurgeArchived": True, "confirmed": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unauthorized"
    mock_iris_client.put.assert_not_awaited()


def test_route_dry_run_with_confirmation_never_calls_put(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE_AND_JOURNAL,  # get_caller_privileges' /info call
        _journal_settings_body(purge_archived=False),  # handler.dry_run()'s GET
    ]

    response = client.post(
        "/api/iris/journal/purge-archived",
        json={"PurgeArchived": True, "confirmed": True, "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    mock_iris_client.put.assert_not_awaited()


def test_route_rejects_extra_field_with_422(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """Setting ArchiveName (or any other field) gives a 422.

    FastAPI doesn't guarantee body validation runs before dependencies, so the
    /info call can still happen. The important part is the PUT never does.
    """
    mock_iris_client.get.return_value = INFO_BODY_MANAGE_AND_JOURNAL

    response = client.post(
        "/api/iris/journal/purge-archived",
        json={"PurgeArchived": True, "confirmed": True, "ArchiveName": "not-allowed"},
    )

    assert response.status_code == 422
    mock_iris_client.put.assert_not_awaited()


def test_route_real_execution_calls_put_and_verifies(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE_AND_JOURNAL,  # get_caller_privileges
        _journal_settings_body(purge_archived=False),  # pre-action GET
        _journal_settings_body(purge_archived=True),  # post-action verification GET
    ]
    mock_iris_client.put.return_value = _journal_settings_body(purge_archived=True)

    response = client.post(
        "/api/iris/journal/purge-archived",
        json={"PurgeArchived": True, "confirmed": True, "dry_run": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["verification"]["status"] == "verified"
    mock_iris_client.put.assert_awaited_once_with(
        "/v2/journal/settings", json={"PurgeArchived": True}
    )
