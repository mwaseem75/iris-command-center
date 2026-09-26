"""Tests for GET /api/iris/issues (Fix Issues MVP: dismounted databases).
IRIS is always a mock; the route only reads."""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISConnectionError

OK = {"errors": [], "summary": ""}


def _db(name: str, directory: str, *, mount_required: bool = False, mount_at_startup: bool = True) -> dict[str, Any]:
    return {"Name": name, "Directory": directory, "Server": "", "ClusterMountMode": False,
            "MountRequired": mount_required, "MountAtStartup": mount_at_startup, "StreamLocation": "", "Status": ""}


def _dir(directory: str, status: str, *, mirrored: bool = False) -> dict[str, Any]:
    return {"Directory": directory, "Size": 11, "MaxSize": "Unlimited", "Status": status,
            "Mirrored": mirrored, "Encrypted": False}


def _mock(mock: AsyncMock, databases: list[dict], dirs: list[dict]) -> None:
    bodies = {"/v2/databases": databases, "/v2/database-dirs": dirs}
    mock.get.side_effect = lambda path, **_: {"status": OK, "console": [], "result": bodies[path]}


def test_reports_a_dismounted_non_system_database_with_the_mount_fix(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock(mock_iris_client,
          [_db("USER", "/usr/irissys/mgr/user/"), _db("DEMO", "/usr/irissys/mgr/demo/")],
          [_dir("/usr/irissys/mgr/user/", "Mounted/RW"), _dir("/usr/irissys/mgr/demo/", "Dismounted")])

    response = client.get("/api/iris/issues")

    assert response.status_code == 200
    (issue,) = response.json()["issues"]
    assert issue["kind"] == "database_dismounted"
    assert issue["database"] == "DEMO"
    assert issue["status"] == "Dismounted"
    assert issue["recommended_operation"] == "database.mount"
    assert issue["parameters"] == {"Directory": "/usr/irissys/mgr/demo/", "ReadOnly": False}
    assert "DEMO" in issue["explanation"] and "Dismounted" in issue["explanation"]
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_system_and_mirrored_databases_are_never_reported(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client,
          [_db("IRISTEMP", "/usr/irissys/mgr/iristemp/"), _db("MIR", "/data/mir/")],
          [_dir("/usr/irissys/mgr/iristemp/", "Dismounted"), _dir("/data/mir/", "Dismounted", mirrored=True)])

    assert client.get("/api/iris/issues").json() == {"issues": []}


def test_no_issue_when_everything_is_mounted(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user", "Mounted/RW")])

    assert client.get("/api/iris/issues").json() == {"issues": []}


def test_unreachable_iris_is_a_safe_502(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("iris.invalid.test")

    response = client.get("/api/iris/issues")

    assert response.status_code == 502
    assert "test-password-not-real" not in response.text
