"""Tests for the four wired-up IRIS read-only routes.

Uses mocks (an AsyncMock standing in for IRISClient, injected via FastAPI's
dependency_overrides) rather than the real IRIS container — per Step 2's
instruction, this suite must not require icc-iris-dev to be running. The
canned response bodies below are the ACTUAL response bodies captured during
Phase 1 verification (see docs/api-capability-matrix.md /
docs/phase-1-iris-container-verification.md), not invented data — the
process/database/namespace lists are trimmed subsets of the real captured
entries, not fabricated ones.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_iris_client
from app.iris_client.exceptions import (
    IRISAuthError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)
from app.main import app

INFO_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "apiVersion": 2,
        "username": "_SYSTEM",
        "serverVersion": "IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.2 (Build 221U) Fri Jun 26 2026 09:58:52 EDT",
        "systemMode": "",
        "product": "iris",
        "namespaces": [{"name": "%SYS"}, {"name": "USER"}],
        "privileges": {
            "Manage": {"use": True},
            "Operate": {"use": True},
            "Secure": {"use": True},
        },
    },
}

NAMESPACES_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "%SYS",
            "Globals": "IRISSYS",
            "Routines": "IRISSYS",
            "SysGlobals": "IRISSYS",
            "SysRoutines": "IRISSYS",
            "Library": "IRISLIB",
            "TempGlobals": "IRISTEMP",
        },
        {
            "Name": "USER",
            "Globals": "USER",
            "Routines": "USER",
            "SysGlobals": "IRISSYS",
            "SysRoutines": "IRISSYS",
            "Library": "IRISLIB",
            "TempGlobals": "IRISTEMP",
        },
    ],
}

DATABASES_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Name": "IRISSYS",
            "Directory": "/usr/irissys/mgr/",
            "Server": "",
            "ClusterMountMode": False,
            "MountRequired": True,
            "MountAtStartup": True,
            "StreamLocation": "",
            "Status": "Mounted/RW",
        },
        {
            "Name": "USER",
            "Directory": "/usr/irissys/mgr/user/",
            "Server": "",
            "ClusterMountMode": False,
            "MountRequired": False,
            "MountAtStartup": False,
            "StreamLocation": "",
            "Status": "Mounted/RW",
        },
    ],
}

PROCESSES_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "Job": 1,
            "Pid": 415,
            "Username": "",
            "Device": "",
            "Nspace": "",
            "Routine": "CONTROL",
            "Commands": 0,
            "Globals": 0,
            "State": "RUN",
            "ClientName": "",
            "EXEname": "",
            "IPAddress": "",
            "CanBeExamined": False,
            "CanBeSuspended": False,
            "CanBeTerminated": False,
            "CanReceiveBroadcast": False,
            "PrvGblBlkCnt": 0,
            "OSUserName": "irisowner",
            "CPUTime": 830,
            "ParentPid": 0,
            "ElapsedTime": "12:21:08",
        },
        {
            "Job": 19,
            "Pid": 712,
            "Username": "_SYSTEM",
            "Device": "|TCP|localhost:1972",
            "Nspace": "%SYS",
            "Routine": "%SYS.sqlcq.uEoUGEdc0ZCI2Rchsl5nnBtZuFAR.1",
            "Commands": 341313,
            "Globals": 22089,
            "State": "RUN",
            "ClientName": "localhost",
            "EXEname": "CSPa24.so",
            "IPAddress": "172.17.0.1",
            "CanBeExamined": False,
            "CanBeSuspended": False,
            "CanBeTerminated": False,
            "CanReceiveBroadcast": False,
            "PrvGblBlkCnt": 11,
            "OSUserName": "irisowner",
            "CPUTime": 920,
            "ParentPid": 476,
            "ElapsedTime": "12:18:13",
        },
    ],
}


@pytest.fixture
def mock_iris_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(mock_iris_client: AsyncMock) -> TestClient:
    app.dependency_overrides[get_iris_client] = lambda: mock_iris_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# --- Successful responses + client-interaction (proves routes delegate to
#     the shared client rather than duplicating auth/request logic) ---


def test_get_info_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = INFO_BODY

    response = client.get("/api/iris/info")

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["apiVersion"] == 2
    assert body["result"]["username"] == "_SYSTEM"
    assert body["result"]["privileges"]["Manage"]["use"] is True
    mock_iris_client.get.assert_awaited_once_with("/info")


def test_get_namespaces_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = NAMESPACES_BODY

    response = client.get("/api/iris/namespaces")

    assert response.status_code == 200
    body = response.json()
    assert [n["Name"] for n in body["result"]] == ["%SYS", "USER"]
    mock_iris_client.get.assert_awaited_once_with("/v2/namespaces")


def test_get_databases_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = DATABASES_BODY

    response = client.get("/api/iris/databases")

    assert response.status_code == 200
    body = response.json()
    assert body["result"][0]["Name"] == "IRISSYS"
    assert body["result"][0]["Status"] == "Mounted/RW"
    mock_iris_client.get.assert_awaited_once_with("/v2/databases")


def test_get_processes_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = PROCESSES_BODY

    response = client.get("/api/iris/processes")

    assert response.status_code == 200
    body = response.json()
    assert body["result"][1]["Username"] == "_SYSTEM"
    assert body["result"][1]["Routine"].startswith("%SYS.sqlcq")
    mock_iris_client.get.assert_awaited_once_with("/v2/processes")


# --- Representative IRIS error handling, without exposing credentials/JWTs ---


def test_get_info_translates_connection_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("Could not connect to IRIS calling /info")

    response = client.get("/api/iris/info")

    assert response.status_code == 502
    assert "credential" not in response.text.lower()
    assert "password" not in response.text.lower()
    assert "token" not in response.text.lower()


def test_get_namespaces_translates_timeout_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISTimeoutError("Timed out calling IRIS /v2/namespaces")

    response = client.get("/api/iris/namespaces")

    assert response.status_code == 504


def test_get_databases_translates_auth_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISAuthError("IRIS login failed with HTTP 401")

    response = client.get("/api/iris/databases")

    assert response.status_code == 502
    assert "credential" not in response.text.lower()
    assert "password" not in response.text.lower()


def test_get_processes_translates_response_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(500)

    response = client.get("/api/iris/processes")

    assert response.status_code == 502
    assert "500" in response.text
