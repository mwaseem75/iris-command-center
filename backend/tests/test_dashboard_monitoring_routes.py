"""Tests for the Dashboard's two read-only monitoring routes:
GET /api/iris/monitor/dashboard (GET /v2/monitor/dashboard/main) and
GET /api/iris/databases/storage (GET /v2/database-dirs).

Canned bodies are ACTUAL responses captured from icc-iris-dev (trimmed),
plus the spec's documented variants: LicenseUse "" when there is no license
limit, and a BusyProcesses Process of "" (both observed forms).
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app

OK = {"errors": [], "summary": ""}

DASHBOARD: dict[str, Any] = {
    "Performance": {"GlobalRefsPerSecond": 195, "GlobalRefs": 999227, "GlobalSetKill": 127120, "RoutineRefs": 583775,
                    "LogicalRequests": 912230, "DiskReads": 12847, "DiskWrites": 4459, "CacheEfficiency": 57.74},
    "ECP": {"ECPClients": "Normal", "ECPClientTraffic": 0, "ECPServers": "Normal", "ECPServerTraffic": 0,
            "ShadowConnections": "Normal", "Shadows": "Normal"},
    "Status": {"UpTime": "0d  2h 05m", "LastBackup": "Never", "SystemMonitor": False},
    "SystemUsage": {"DatabaseSpace": "Normal", "DatabaseJournal": "Normal", "JournalSpace": "Normal",
                    "JournalEntries": 2124, "LockTable": "Normal", "WriteDaemon": "Normal", "Processes": 5,
                    "CSPSessions": 0, "BusyProcesses": [{"Process": 666, "Commands": 103855},
                                                        {"Process": "", "Commands": 0}]},
    "Alerts": {"SeriousAlerts": 0, "ApplicationErrors": 0},
    "Licensing": {"LicenseLimit": 8, "LicenseUse": 0, "LicenseUseHigh": 13},
    "UpcomingTasks": [{"Task": "Switch Journal", "Time": "00:00", "Status": "Scheduled"}],
}

DATABASE_DIRS = [
    {"Directory": "/usr/irissys/mgr/", "Encrypted": False, "EncryptionKeyID": "", "EncryptionVersion": 0,
     "MaxSize": "Unlimited", "Mirrored": False, "Resource": "%DB_IRISSYS", "SFN": 0, "Size": 70, "Status": "Mounted/RW"},
    {"Directory": "/usr/irissys/mgr/user/", "Encrypted": True, "EncryptionKeyID": "key-id-not-for-the-browser",
     "EncryptionVersion": 2, "MaxSize": 2048, "Mirrored": False, "Resource": "%DB_USER", "SFN": 9, "Size": 11,
     "Status": "Mounted/RW"},
]


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


def test_monitor_dashboard(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = envelope(copy.deepcopy(DASHBOARD))

    response = client.get("/api/iris/monitor/dashboard")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["Performance"]["CacheEfficiency"] == 57.74
    assert result["Status"]["SystemMonitor"] is False
    assert result["SystemUsage"]["BusyProcesses"] == [{"Process": 666, "Commands": 103855}, {"Process": "", "Commands": 0}]
    mock_iris_client.get.assert_awaited_once_with("/v2/monitor/dashboard/main")
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_monitor_dashboard_license_without_limit(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(DASHBOARD)
    body["Licensing"].update({"LicenseUse": "", "LicenseUseHigh": ""})
    mock_iris_client.get.return_value = envelope(body)

    licensing = client.get("/api/iris/monitor/dashboard").json()["result"]["Licensing"]

    assert licensing == {"LicenseLimit": 8, "LicenseUse": "", "LicenseUseHigh": ""}


def test_monitor_dashboard_unexpected_shape_is_rejected(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(DASHBOARD)
    del body["Alerts"]
    mock_iris_client.get.return_value = envelope(body)

    with pytest.raises(ValidationError):
        client.get("/api/iris/monitor/dashboard")


def test_database_storage_drops_encryption_key_id(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = envelope(copy.deepcopy(DATABASE_DIRS))

    response = client.get("/api/iris/databases/storage")

    assert response.status_code == 200
    assert "key-id-not-for-the-browser" not in response.text
    assert response.json()["result"] == [
        {"Directory": "/usr/irissys/mgr/", "Size": 70, "MaxSize": "Unlimited", "Status": "Mounted/RW",
         "Mirrored": False, "Encrypted": False},
        {"Directory": "/usr/irissys/mgr/user/", "Size": 11, "MaxSize": 2048, "Status": "Mounted/RW",
         "Mirrored": False, "Encrypted": True},
    ]
    mock_iris_client.get.assert_awaited_once_with("/v2/database-dirs")


@pytest.mark.parametrize("path", ["/api/iris/monitor/dashboard", "/api/iris/databases/storage"])
@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [(IRISConnectionError("boom"), 502, "Could not connect to IRIS"),
     (IRISResponseError(403), 502, "IRIS returned an unexpected HTTP 403")],
)
def test_errors_are_generic(
    client: TestClient, mock_iris_client: AsyncMock, path: str, error: Exception, status: int, detail: str
) -> None:
    mock_iris_client.get.side_effect = error

    response = client.get(path)

    assert response.status_code == status
    assert response.json()["detail"] == detail


def test_routes_are_get_only() -> None:
    paths = app.openapi()["paths"]
    assert set(paths["/api/iris/monitor/dashboard"]) == {"get"}
    assert set(paths["/api/iris/databases/storage"]) == {"get"}
