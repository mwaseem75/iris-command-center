"""Route-level tests for POST /api/iris/namespaces (namespace.create) —
proves the HTTP wiring (including privilege sourcing via
get_caller_privileges, which calls GET /info) works end-to-end, using a
mocked IRISClient. No real network call is made anywhere in this file, and
no test performs a real namespace creation.
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


def _namespaces_body(names: list[str]) -> dict[str, Any]:
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": [
            {
                "Name": name,
                "Globals": "USER",
                "Routines": "USER",
                "SysGlobals": "IRISSYS",
                "SysRoutines": "IRISSYS",
                "Library": "IRISLIB",
                "TempGlobals": "IRISTEMP",
            }
            for name in names
        ],
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


_REQUEST_BODY = {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}


def test_route_without_confirmation_is_blocked_before_put(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_MANAGE

    response = client.post("/api/iris/namespaces", json={**_REQUEST_BODY, "confirmed": False})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    mock_iris_client.put.assert_not_awaited()


def test_route_without_required_privilege_is_denied(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.return_value = INFO_BODY_NO_RELEVANT_PRIVILEGE

    response = client.post("/api/iris/namespaces", json={**_REQUEST_BODY, "confirmed": True})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unauthorized"
    mock_iris_client.put.assert_not_awaited()


def test_route_dry_run_with_confirmation_never_calls_put(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE,  # get_caller_privileges' /info call
        _namespaces_body(["%SYS", "USER"]),  # handler.dry_run()'s namespaces read
        _databases_body(["USER", "IRISTEMP"]),  # handler.dry_run()'s databases read
    ]

    response = client.post(
        "/api/iris/namespaces", json={**_REQUEST_BODY, "confirmed": True, "dry_run": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    mock_iris_client.put.assert_not_awaited()


def test_route_rejects_extra_field_with_422(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A caller attempting to also set an unlisted field via this endpoint
    gets an explicit 422, not a silently-ignored extra field. PUT is never
    reached (see test_journal_route.py's identical test for the note on
    why /info may still be called before the body is ultimately rejected).
    """
    mock_iris_client.get.return_value = INFO_BODY_MANAGE

    response = client.post(
        "/api/iris/namespaces",
        json={**_REQUEST_BODY, "confirmed": True, "SysGlobals": "not-allowed"},
    )

    assert response.status_code == 422
    mock_iris_client.put.assert_not_awaited()


def test_route_rejects_system_namespace_name_as_a_structured_failure(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A %-prefixed Name is a domain validation failure (HandlerOutcome.
    FAILURE), not an HTTP-level rejection — the route still returns 200
    with a structured, non-success OperationResult, the same convention
    every other validation failure in this project uses."""
    mock_iris_client.get.return_value = INFO_BODY_MANAGE

    response = client.post(
        "/api/iris/namespaces",
        json={"Name": "%CUSTOM", "Globals": "USER", "Routines": "USER", "confirmed": True, "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["handler_result"]["outcome"] == "failure"
    assert "System-namespace" in body["handler_result"]["detail"]
    mock_iris_client.put.assert_not_awaited()


def test_route_real_execution_calls_put_and_verifies(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = [
        INFO_BODY_MANAGE,  # get_caller_privileges
        _namespaces_body(["%SYS", "USER"]),  # pre-action namespaces read
        _databases_body(["USER", "IRISTEMP"]),  # pre-action databases read
        _namespaces_body(["%SYS", "USER", "NEWAPP"]),  # post-action verification read
    ]
    mock_iris_client.put.return_value = {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {"Globals": "USER", "Routines": "USER"},
    }

    response = client.post(
        "/api/iris/namespaces", json={**_REQUEST_BODY, "confirmed": True, "dry_run": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["verification"]["status"] == "verified"
    mock_iris_client.put.assert_awaited_once_with(
        "/v2/namespace?name=NEWAPP", json={"Globals": "USER", "Routines": "USER"}
    )
