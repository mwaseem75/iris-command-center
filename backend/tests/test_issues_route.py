"""Tests for GET /api/iris/issues (dismounted databases). IRIS is mocked."""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

OK = {"errors": [], "summary": ""}


def _db(name: str, directory: str, *, mount_required: bool = False, mount_at_startup: bool = True) -> dict[str, Any]:
    return {"Name": name, "Directory": directory, "Server": "", "ClusterMountMode": False,
            "MountRequired": mount_required, "MountAtStartup": mount_at_startup, "StreamLocation": "", "Status": ""}


def _dir(directory: str, status: str, *, mirrored: bool = False) -> dict[str, Any]:
    return {"Directory": directory, "Size": 11, "MaxSize": "Unlimited", "Status": status,
            "Mirrored": mirrored, "Encrypted": False}


def _ns(name: str, globals_db: str, routines_db: str) -> dict[str, Any]:
    return {"Name": name, "Globals": globals_db, "Routines": routines_db, "SysGlobals": "IRISSYS",
            "SysRoutines": "IRISSYS", "Library": "IRISLIB", "TempGlobals": "IRISTEMP"}


def _mock(mock: AsyncMock, databases: list[dict], dirs: list[dict], namespaces: list[dict] | None = None) -> None:
    bodies = {"/v2/databases": databases, "/v2/database-dirs": dirs, "/v2/namespaces": namespaces or []}
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
    assert issue["mirrored"] is False
    assert "DEMO" in issue["explanation"] and "Dismounted" in issue["explanation"]
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_system_and_mirrored_databases_are_never_reported(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client,
          [_db("IRISTEMP", "/usr/irissys/mgr/iristemp/"), _db("MIR", "/data/mir/")],
          [_dir("/usr/irissys/mgr/iristemp/", "Dismounted"), _dir("/data/mir/", "Dismounted", mirrored=True)])

    assert client.get("/api/iris/issues").json()["issues"] == []


def test_no_issue_when_everything_is_mounted(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user", "Mounted/RW")])

    assert client.get("/api/iris/issues").json()["issues"] == []


def test_unreachable_iris_is_a_safe_502(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("iris.invalid.test")

    response = client.get("/api/iris/issues")

    assert response.status_code == 502
    assert "test-password-not-real" not in response.text


def test_response_includes_the_resolution_catalog(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user", "Mounted/RW")])

    resolutions = client.get("/api/iris/issues").json()["resolutions"]

    entry = resolutions["database_dismounted"]
    assert entry["operation"] == "database.mount"
    assert entry["severity"] == "high"
    assert entry["risk_level"] == "medium"
    assert entry["required_privileges"] == ["Operate"]
    assert entry["confirmation_required"] is True
    assert [step["kind"] for step in entry["workflow_steps"]] == [
        "detected", "recommended", "check", "confirm", "execute", "verify", "trace",
    ]


# --- affected namespaces ---


def test_lists_the_namespaces_that_use_the_database(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client,
          [_db("DEMO", "/data/demo/")],
          [_dir("/data/demo/", "Dismounted")],
          [_ns("APP", "DEMO", "DEMO"), _ns("REPORTS", "REPORTSDB", "demo"), _ns("USER", "USER", "USER")])

    (issue,) = client.get("/api/iris/issues").json()["issues"]

    assert issue["affected_namespaces"] == [
        {"namespace": "APP", "uses": ["Globals", "Routines"]},
        {"namespace": "REPORTS", "uses": ["Routines"]},  # names compare case-insensitively
    ]
    assert "Namespaces that depend on it: APP (Globals, Routines), REPORTS (Routines)." in issue["explanation"]
    assert issue["recommended_operation"] == "database.mount"
    assert issue["parameters"] == {"Directory": "/data/demo/", "ReadOnly": False}


def test_no_dependent_namespaces_is_an_empty_list(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("DEMO", "/data/demo/")], [_dir("/data/demo/", "Dismounted")],
          [_ns("USER", "USER", "USER")])

    (issue,) = client.get("/api/iris/issues").json()["issues"]

    assert issue["affected_namespaces"] == []
    assert "No namespace uses it for Globals or Routines." in issue["explanation"]


def test_unreadable_namespaces_still_report_the_issue(client: TestClient, mock_iris_client: AsyncMock) -> None:
    bodies = {"/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")]}

    def get(path: str, **_: Any) -> dict[str, Any]:
        if path == "/v2/namespaces":
            raise IRISResponseError(500)
        return {"status": OK, "console": [], "result": bodies[path]}

    mock_iris_client.get.side_effect = get

    response = client.get("/api/iris/issues")

    assert response.status_code == 200
    (issue,) = response.json()["issues"]
    assert issue["affected_namespaces"] is None
    assert "couldn't be read" in issue["explanation"]


def test_namespaces_are_not_read_when_there_are_no_issues(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user", "Mounted/RW")])

    client.get("/api/iris/issues")

    called = [call.args[0] for call in mock_iris_client.get.call_args_list]
    assert "/v2/namespaces" not in called
