"""Tests for GET /api/iris/issues (dismounted databases). IRIS is mocked."""

import re
from typing import Any
from unittest.mock import AsyncMock

import pytest
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


def _journal(*, archive_name: str = "", purge_archived: bool = False) -> dict[str, Any]:
    return {"AlternateDirectory": "/usr/irissys/mgr/journal/", "ArchiveName": archive_name, "BackupsBeforePurge": 2,
            "CurrentDirectory": "/usr/irissys/mgr/journal/", "DaysBeforePurge": 2, "FileSizeLimit": 1024,
            "FreezeOnError": False, "JournalFilePrefix": "", "JournalcspSession": False,
            "PurgeArchived": purge_archived, "CompressFiles": True, "wijdir": "", "targwijsz": 0}


def _app(name: str, namespace: str, *, enabled: bool = True, app_type: str = "CSP",
         is_system: bool = False) -> dict[str, Any]:
    return {"Name": name, "Namespace": namespace, "NamespaceDefault": False, "Enabled": enabled, "Type": app_type,
            "Resource": "", "AuthenticationMethods": ["Password"], "IsSystemApp": is_system, "DispatchClass": ""}


# Trimmed real GET /v2/monitor/dashboard/main (see test_dashboard_monitoring_routes.py).
def _dashboard(*, system_monitor: bool = True) -> dict[str, Any]:
    return {
        "Performance": {"GlobalRefsPerSecond": 195, "GlobalRefs": 999227, "GlobalSetKill": 127120,
                        "RoutineRefs": 583775, "LogicalRequests": 912230, "DiskReads": 12847, "DiskWrites": 4459,
                        "CacheEfficiency": 57.74},
        "ECP": {"ECPClients": "Normal", "ECPClientTraffic": 0, "ECPServers": "Normal", "ECPServerTraffic": 0,
                "ShadowConnections": "Normal", "Shadows": "Normal"},
        "Status": {"UpTime": "0d  2h 05m", "LastBackup": "Never", "SystemMonitor": system_monitor},
        "SystemUsage": {"DatabaseSpace": "Normal", "DatabaseJournal": "Normal", "JournalSpace": "Normal",
                        "JournalEntries": 2124, "LockTable": "Normal", "WriteDaemon": "Normal", "Processes": 5,
                        "CSPSessions": 0, "BusyProcesses": [{"Process": "", "Commands": 0}]},
        "Alerts": {"SeriousAlerts": 0, "ApplicationErrors": 0},
        "Licensing": {"LicenseLimit": 8, "LicenseUse": 0, "LicenseUseHigh": 0},
        "UpcomingTasks": [],
    }


def _healthy(mock: AsyncMock, bodies: dict[str, Any], *, system_monitor: bool = True,
             task_manager: str = "Running", full: dict[str, Any] | None = None) -> dict[str, Any]:
    """Adds the detection-only checks' reads (healthy unless told otherwise).
    `full` maps a directory to the Full value its database-dir/info task returns."""
    bodies.setdefault("/v2/monitor/dashboard/main", _dashboard(system_monitor=system_monitor))
    bodies.setdefault("/v2/task/manager", {"Status": task_manager})
    flags = full or {}
    mock.post_async_task.side_effect = lambda path, params=None, json=None: params["dir"]
    mock.wait_for_async_task.side_effect = lambda task_id: {"Result": {"Full": flags.get(task_id, False)}}
    return bodies


def _mock(mock: AsyncMock, databases: list[dict], dirs: list[dict], namespaces: list[dict] | None = None, *,
          journal: dict[str, Any] | None = None, web_apps: list[dict] | None = None, **checks: Any) -> None:
    bodies = _healthy(mock, {"/v2/databases": databases, "/v2/database-dirs": dirs,
                             "/v2/namespaces": namespaces or [], "/v2/journal/settings": journal or _journal(),
                             "/v2/web-apps": web_apps or []}, **checks)
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
    bodies = _healthy(mock_iris_client, {
        "/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
        "/v2/journal/settings": _journal(), "/v2/web-apps": []})

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


def test_explanation_keeps_the_sentences_the_issue_resolver_evidence_reads(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    # issue-resolver.js parses these fixed sentences for its Evidence chain.
    _mock(mock_iris_client, [_db("DEMO", "/data/demo/")], [_dir("/data/demo/", "Dismounted")],
          [_ns("APP", "DEMO", "USER")])

    (issue,) = client.get("/api/iris/issues").json()["issues"]

    assert re.search(r'Database DEMO \(/data/demo/\) is reported by IRIS as "Dismounted"', issue["explanation"])
    assert re.search(r"Namespaces that depend on it: [^.]+\.", issue["explanation"])


# --- recommendations ---

MOUNTED = ([_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user/", "Mounted/RW")])
USER_NS = [_ns("USER", "USER", "USER"), _ns("%SYS", "IRISSYS", "IRISSYS")]


def _recommendations(client: TestClient) -> dict[str, Any]:
    body = client.get("/api/iris/issues").json()
    return {"items": body["recommendations"], "unavailable": body["recommendations_unavailable"],
            "issues": body["issues"]}


def test_no_recommendations_for_a_healthy_instance(client: TestClient, mock_iris_client: AsyncMock) -> None:
    # Mirrors the live dev instance: no ArchiveName, every app's namespace exists.
    _mock(mock_iris_client, *MOUNTED, USER_NS, journal=_journal(archive_name="", purge_archived=False),
          web_apps=[_app("/csp/user", "USER"), _app("/api/monitor", "%SYS")])

    result = _recommendations(client)

    assert result["items"] == [] and result["unavailable"] == []
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_purge_archived_off_is_an_issue_when_archiving_is_configured(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock(mock_iris_client, *MOUNTED, journal=_journal(archive_name="NightlyArchive", purge_archived=False))

    body = client.get("/api/iris/issues").json()

    (issue,) = body["issues"]
    assert issue["kind"] == "journal_purge_archived_off"
    assert issue["archive_name"] == "NightlyArchive" and issue["purge_archived"] is False
    assert issue["recommended_operation"] == "journal.update_purge_archived"
    assert issue["parameters"] == {"PurgeArchived": True}
    assert "NightlyArchive" in issue["explanation"]
    # No longer a recommendation (the fields stay, empty, for compatibility).
    assert body["recommendations"] == [] and body["recommendations_unavailable"] == []
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_no_purge_archived_issue_without_archiving_or_when_already_on(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    for journal in (_journal(archive_name="  ", purge_archived=False),
                    _journal(archive_name="NightlyArchive", purge_archived=True)):
        _mock(mock_iris_client, *MOUNTED, journal=journal)
        assert client.get("/api/iris/issues").json()["issues"] == []


def test_journal_issue_parameters_match_the_catalog_entry(client: TestClient, mock_iris_client: AsyncMock) -> None:
    from app.resolution.catalog import JOURNAL_PURGE_ARCHIVED_OFF as entry

    _mock(mock_iris_client, *MOUNTED, journal=_journal(archive_name="A"))

    (issue,) = client.get("/api/iris/issues").json()["issues"]

    assert issue["recommended_operation"] == entry.operation
    assert issue["parameters"] == {b.name: b.value for b in entry.parameters}
    for evidence in entry.detection_evidence:
        assert evidence.issue_field in issue


def test_unreadable_journal_settings_are_reported_and_other_issues_still_work(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    bodies = _healthy(mock_iris_client, {
        "/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
        "/v2/namespaces": [], "/v2/web-apps": []})

    def get(path: str, **_: Any) -> dict[str, Any]:
        if path == "/v2/journal/settings":
            raise IRISResponseError(500)
        return {"status": OK, "console": [], "result": bodies[path]}

    mock_iris_client.get.side_effect = get

    response = client.get("/api/iris/issues")

    assert response.status_code == 200
    body = response.json()
    assert [i["kind"] for i in body["issues"]] == ["database_dismounted"]
    assert body["issue_checks_unavailable"] == ["journal_purge_archived_off"]
    assert body["recommendations_unavailable"] == []


# --- web_app_namespace_missing ---


def _issues(client: TestClient) -> dict[str, Any]:
    return client.get("/api/iris/issues").json()


def test_reports_an_enabled_web_app_whose_namespace_is_missing(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock(mock_iris_client, *MOUNTED, USER_NS,
          web_apps=[_app("/csp/orders", "ORDERS"), _app("/csp/user", "user")])  # namespaces compare case-insensitively

    body = _issues(client)

    (issue,) = body["issues"]
    assert issue["kind"] == "web_app_namespace_missing"
    assert issue["web_app"] == "/csp/orders"
    assert issue["namespace"] == "ORDERS"
    assert issue["enabled"] is True and issue["app_type"] == "CSP"
    assert issue["recommended_operation"] == "web_app.set_enabled"
    assert issue["parameters"] == {"Name": "/csp/orders", "Enabled": False}
    assert "ORDERS" in issue["explanation"]
    assert body["issue_checks_unavailable"] == []
    assert body["recommendations"] == []  # no longer a recommendation
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_never_reports_a_web_app_set_enabled_would_refuse(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, *MOUNTED, USER_NS, web_apps=[
        _app("/csp/gone", "GONE", enabled=False),                # already disabled
        _app("/csp/sysapp", "GONE", app_type="System,CSP"),      # System type
        _app("/csp/flagged", "GONE", is_system=True),            # IsSystemApp
        _app("/api/admin/", "GONE"),                             # the Command Center's own API
        _app("/API/MGMNT", "GONE"),
    ])

    assert _issues(client)["issues"] == []


def test_issue_parameters_match_the_catalog_entry(client: TestClient, mock_iris_client: AsyncMock) -> None:
    from app.resolution.catalog import WEB_APP_NAMESPACE_MISSING

    _mock(mock_iris_client, *MOUNTED, USER_NS, web_apps=[_app("/csp/orders", "ORDERS")])

    (issue,) = _issues(client)["issues"]

    assert issue["recommended_operation"] == WEB_APP_NAMESPACE_MISSING.operation
    expected = {b.name: (issue[b.from_issue_field] if b.from_issue_field else b.value)
                for b in WEB_APP_NAMESPACE_MISSING.parameters}
    assert issue["parameters"] == expected
    for evidence in WEB_APP_NAMESPACE_MISSING.detection_evidence:
        assert evidence.issue_field in issue


def test_all_issue_kinds_are_reported_together(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("DEMO", "/data/demo/")], [_dir("/data/demo/", "Dismounted")], USER_NS,
          web_apps=[_app("/csp/orders", "ORDERS")], journal=_journal(archive_name="A"))

    body = _issues(client)

    kinds = ["database_dismounted", "web_app_namespace_missing", "journal_purge_archived_off"]
    assert [i["kind"] for i in body["issues"]] == kinds
    assert list(body["resolutions"])[:3] == kinds


def test_unreadable_web_apps_are_reported_and_database_issues_still_work(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    bodies = _healthy(mock_iris_client, {
        "/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
        "/v2/namespaces": [], "/v2/journal/settings": _journal()})

    def get(path: str, **_: Any) -> dict[str, Any]:
        if path == "/v2/web-apps":
            raise IRISResponseError(500)
        return {"status": OK, "console": [], "result": bodies[path]}

    mock_iris_client.get.side_effect = get

    body = _issues(client)

    assert [i["kind"] for i in body["issues"]] == ["database_dismounted"]
    assert body["issue_checks_unavailable"] == ["web_app_namespace_missing"]
    assert body["recommendations_unavailable"] == []


def test_the_rehearsal_detector_still_reports_only_database_issues(mock_iris_client: AsyncMock) -> None:
    import asyncio

    from app.routes.issues import get_issues

    _mock(mock_iris_client, [_db("DEMO", "/data/demo/")], [_dir("/data/demo/", "Dismounted")], USER_NS,
          web_apps=[_app("/csp/orders", "ORDERS")])

    issues = asyncio.run(get_issues(mock_iris_client)).issues

    assert [i.kind for i in issues] == ["database_dismounted"]
    called = [call.args[0] for call in mock_iris_client.get.call_args_list]
    assert "/v2/web-apps" not in called


# --- detection-only: system_monitor_not_running, task_manager_not_running, database_full ---

HEALTHY = ([_db("USER", "/usr/irissys/mgr/user/")], [_dir("/usr/irissys/mgr/user/", "Mounted/RW")])


def _storage(directory: str, *, size: int, max_size: int | str, status: str = "Mounted/RW") -> dict[str, Any]:
    return {**_dir(directory, status), "Size": size, "MaxSize": max_size}


def _detection_only(body: dict[str, Any]) -> list[dict[str, Any]]:
    kinds = ("system_monitor_not_running", "task_manager_not_running", "database_full")
    return [i for i in body["issues"] if i["kind"] in kinds]


def test_healthy_instance_has_no_detection_only_issues(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, *HEALTHY, USER_NS)

    body = _issues(client)

    assert _detection_only(body) == [] and body["issue_checks_unavailable"] == []
    mock_iris_client.post.assert_not_called()  # database-dir/info goes through post_async_task only
    mock_iris_client.put.assert_not_called()


def test_reports_the_system_monitor_not_running(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, *HEALTHY, USER_NS, system_monitor=False)

    (issue,) = _detection_only(_issues(client))

    assert issue["kind"] == "system_monitor_not_running"
    assert issue["system_monitor"] is False and issue["up_time"] == "0d  2h 05m"
    assert "SystemMonitor is false" in issue["explanation"]
    assert "recommended_operation" not in issue and "parameters" not in issue


@pytest.mark.parametrize("status", ["Stopped", "Suspended", ""])
def test_reports_the_task_manager_not_running(status: str, client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, *HEALTHY, USER_NS, task_manager=status)

    (issue,) = _detection_only(_issues(client))

    assert issue["kind"] == "task_manager_not_running" and issue["status"] == status
    assert "recommended_operation" not in issue


def test_reports_a_database_iris_says_is_full(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("APP", "/data/app/")], [_storage("/data/app/", size=40, max_size="Unlimited")],
          USER_NS, full={"/data/app/": True})

    (issue,) = _detection_only(_issues(client))

    assert issue["kind"] == "database_full"
    assert issue["database"] == "APP" and issue["directory"] == "/data/app/"
    assert issue["full"] is True and issue["reasons"] == ["iris_reports_full"]
    assert "IRIS reports it as Full" in issue["explanation"]


def test_reports_a_database_at_its_maximum_size(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("APP", "/data/app/")], [_storage("/data/app/", size=2048, max_size=2048)], USER_NS)

    (issue,) = _detection_only(_issues(client))

    assert issue["reasons"] == ["max_size_reached"] and issue["full"] is False
    assert issue["size"] == 2048 and issue["max_size"] == 2048
    assert "(2048 MB) has reached its maximum size (2048 MB)" in issue["explanation"]


@pytest.mark.parametrize("size, max_size", [(2047, 2048), (5000, "Unlimited"), (10, 0)])
def test_room_to_grow_or_no_limit_is_not_full(size: int, max_size: Any, client: TestClient,
                                              mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("APP", "/data/app/")], [_storage("/data/app/", size=size, max_size=max_size)],
          USER_NS)

    assert _detection_only(_issues(client)) == []


def test_full_flag_is_only_read_for_mounted_databases(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("APP", "/data/app/"), _db("OFF", "/data/off/")],
          [_storage("/data/app/", size=1, max_size="Unlimited"),
           _storage("/data/off/", size=1, max_size="Unlimited", status="Dismounted")], USER_NS)

    _issues(client)

    asked = [call.kwargs["params"]["dir"] for call in mock_iris_client.post_async_task.call_args_list]
    assert asked == ["/data/app/"]
    assert all(call.args[0] == "/v2/database-dir/info" for call in mock_iris_client.post_async_task.call_args_list)


def test_unreadable_full_flag_is_reported_and_a_reached_max_size_still_is(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock(mock_iris_client, [_db("APP", "/data/app/")], [_storage("/data/app/", size=64, max_size=64)], USER_NS)
    mock_iris_client.wait_for_async_task.side_effect = IRISResponseError(500)

    body = _issues(client)

    (issue,) = _detection_only(body)
    assert issue["reasons"] == ["max_size_reached"] and issue["full"] is None
    assert body["issue_checks_unavailable"] == ["database_full"]


def test_unreadable_detection_only_data_is_reported_and_other_issues_still_work(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    bodies = _healthy(mock_iris_client, {
        "/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
        "/v2/namespaces": [], "/v2/web-apps": [], "/v2/journal/settings": _journal()})

    def get(path: str, **_: Any) -> dict[str, Any]:
        if path in ("/v2/monitor/dashboard/main", "/v2/task/manager"):
            raise IRISResponseError(500)
        return {"status": OK, "console": [], "result": bodies[path]}

    mock_iris_client.get.side_effect = get

    body = _issues(client)

    assert [i["kind"] for i in body["issues"]] == ["database_dismounted"]
    assert body["issue_checks_unavailable"] == ["system_monitor_not_running", "task_manager_not_running"]


def test_detection_only_issues_match_their_catalog_entries(client: TestClient, mock_iris_client: AsyncMock) -> None:
    from app.resolution.catalog import ISSUE_CATALOG

    _mock(mock_iris_client, [_db("APP", "/data/app/")], [_storage("/data/app/", size=8, max_size=8)], USER_NS,
          system_monitor=False, task_manager="Stopped", full={"/data/app/": True})

    issues = _detection_only(_issues(client))

    assert [i["kind"] for i in issues] == ["system_monitor_not_running", "task_manager_not_running", "database_full"]
    for issue in issues:
        entry = ISSUE_CATALOG[issue["kind"]]
        assert entry.resolvable is False and entry.investigation is not None
        for evidence in entry.detection_evidence:
            assert evidence.issue_field in issue
