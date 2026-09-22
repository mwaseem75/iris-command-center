"""Route-level tests for POST /api/iris/databases (database.create) —
proves the HTTP wiring (including privilege sourcing via
get_caller_privileges, which calls GET /info) works end-to-end, using a
mocked IRISClient. No real network call is made anywhere in this file, and
no test performs a real database creation.
"""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

INFO_BODY_MANAGE: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U)",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}, {"name": "USER"}],
        "privileges": {"Manage": {"use": True}, "Journal": {"use": False}},
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
        "privileges": {"Operate": {"use": True}},
    },
}


def _databases_body(names: list[str]) -> dict[str, Any]:
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": [
            {
                "Name": name,
                "Directory": f"/usr/irissys/mgr/{name.lower()}/",
                "Server": "",
                "ClusterMountMode": False,
                "MountRequired": True,
                "MountAtStartup": True,
                "StreamLocation": "",
                "Status": "Mounted/RW",
            }
            for name in names
        ],
    }


def _database_dir_found(resource_name: str = "%DB_MYDB") -> dict[str, Any]:
    """A real-shaped GET /v2/database-dir?dir=<Directory> envelope — see
    test_database_create.py's identical helper for the live-confirmed
    LocalDatabase shape this represents."""
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {
            "MaxSize": 0,
            "ExpansionSize": 0,
            "NewVolumeThreshold": 0,
            "NewVolumeDirectory": "/usr/irissys/mgr/mydb/",
            "ResourceName": resource_name,
            "NewGlobalIsKeep": False,
            "NewGlobalCollation": 5,
            "ClusterMountMode": False,
            "ReadOnly": False,
            "GlobalJournalState": False,
        },
    }


_REQUEST_BODY = {"Directory": "/usr/irissys/mgr/mydb/"}


def test_route_without_confirmation_is_blocked_before_post(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_MANAGE

    response = client.post("/api/iris/databases", json={**_REQUEST_BODY, "confirmed": False})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    mock_iris_client.post.assert_not_awaited()


def test_route_without_required_privilege_is_denied(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_NO_RELEVANT_PRIVILEGE

    response = client.post("/api/iris/databases", json={**_REQUEST_BODY, "confirmed": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unauthorized"
    mock_iris_client.post.assert_not_awaited()


def test_route_dry_run_with_confirmation_never_calls_post(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE,  # get_caller_privileges' /info call
        _databases_body(["USER", "IRISTEMP"]),  # handler.dry_run()'s databases read
    ]

    response = client.post(
        "/api/iris/databases", json={**_REQUEST_BODY, "confirmed": True, "dry_run": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    mock_iris_client.post.assert_not_awaited()


def test_route_rejects_extra_field_with_422(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A caller attempting to also set an unlisted field via this endpoint
    gets an explicit 422, not a silently-ignored extra field. POST is
    never reached (see test_namespace_route.py's identical test for the
    note on why /info may still be called before the body is ultimately
    rejected)."""
    mock_iris_client.get.return_value = INFO_BODY_MANAGE

    response = client.post(
        "/api/iris/databases",
        json={**_REQUEST_BODY, "confirmed": True, "Password": "not-allowed"},
    )

    assert response.status_code == 422
    mock_iris_client.post.assert_not_awaited()


def test_route_rejects_existing_directory_as_a_structured_failure(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A directory collision is a domain validation failure
    (HandlerOutcome.FAILURE), not an HTTP-level rejection — the route
    still returns 200 with a structured, non-success OperationResult, the
    same convention every other validation failure in this project uses."""
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE,
        _databases_body(["USER", "IRISTEMP"]),
    ]

    response = client.post(
        "/api/iris/databases",
        json={"Directory": "/usr/irissys/mgr/user/", "confirmed": True, "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["outcome"] == "failure"
    assert "already exists" in body["handler_result"]["detail"]
    mock_iris_client.post.assert_not_awaited()


def test_route_real_execution_calls_post_and_verifies(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE,  # get_caller_privileges
        _databases_body(["USER", "IRISTEMP"]),  # pre-action databases read
        _database_dir_found(),  # post-action verification read (GET /v2/database-dir)
    ]
    mock_iris_client.post.return_value = {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {"ResourceName": "%DB_MYDB"},
    }

    response = client.post(
        "/api/iris/databases", json={**_REQUEST_BODY, "confirmed": True, "dry_run": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["verification"]["status"] == "verified"
    mock_iris_client.post.assert_awaited_once_with(
        "/v2/database-dir", json={"Directory": "/usr/irissys/mgr/mydb/"}
    )
