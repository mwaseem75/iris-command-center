"""Tests for GET /api/iris/issues (dismounted databases). IRIS is mocked."""

import re
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


def _journal(*, archive_name: str = "", purge_archived: bool = False) -> dict[str, Any]:
    return {"AlternateDirectory": "/usr/irissys/mgr/journal/", "ArchiveName": archive_name, "BackupsBeforePurge": 2,
            "CurrentDirectory": "/usr/irissys/mgr/journal/", "DaysBeforePurge": 2, "FileSizeLimit": 1024,
            "FreezeOnError": False, "JournalFilePrefix": "", "JournalcspSession": False,
            "PurgeArchived": purge_archived, "CompressFiles": True, "wijdir": "", "targwijsz": 0}


def _app(name: str, namespace: str, *, enabled: bool = True, app_type: str = "CSP",
         is_system: bool = False) -> dict[str, Any]:
    return {"Name": name, "Namespace": namespace, "NamespaceDefault": False, "Enabled": enabled, "Type": app_type,
            "Resource": "", "AuthenticationMethods": ["Password"], "IsSystemApp": is_system, "DispatchClass": ""}


def _mock(mock: AsyncMock, databases: list[dict], dirs: list[dict], namespaces: list[dict] | None = None, *,
          journal: dict[str, Any] | None = None, web_apps: list[dict] | None = None) -> None:
    bodies = {"/v2/databases": databases, "/v2/database-dirs": dirs, "/v2/namespaces": namespaces or [],
              "/v2/journal/settings": journal or _journal(), "/v2/web-apps": web_apps or []}
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
    bodies = {"/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
              "/v2/journal/settings": _journal(), "/v2/web-apps": []}

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


def test_recommends_purge_archived_when_archiving_is_configured(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    _mock(mock_iris_client, *MOUNTED, journal=_journal(archive_name="NightlyArchive", purge_archived=False))

    (rec,) = _recommendations(client)["items"]

    assert rec["kind"] == "journal_purge_archived_off"
    assert rec["recommended_operation"] == "journal.update_purge_archived"
    assert rec["parameters"] == {"PurgeArchived": True}
    assert {"source": "GET /v2/journal/settings", "field": "ArchiveName", "value": "NightlyArchive"} in rec["evidence"]
    assert "NightlyArchive" in rec["explanation"]


def test_no_purge_archived_recommendation_without_archiving_or_when_already_on(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    for journal in (_journal(archive_name="  ", purge_archived=False),
                    _journal(archive_name="NightlyArchive", purge_archived=True)):
        _mock(mock_iris_client, *MOUNTED, journal=journal)
        assert _recommendations(client)["items"] == []


def test_recommended_operations_are_registered_mutations(client: TestClient, mock_iris_client: AsyncMock) -> None:
    from app.authorization.operations import OPERATION_REGISTRY, OperationKind

    _mock(mock_iris_client, *MOUNTED, USER_NS, journal=_journal(archive_name="A"))

    items = _recommendations(client)["items"]

    assert [r["kind"] for r in items] == ["journal_purge_archived_off"]
    for rec in items:
        definition = OPERATION_REGISTRY[rec["recommended_operation"]]
        assert definition.kind is OperationKind.MUTATING and definition.confirmation_required


def test_unreadable_recommendation_data_is_reported_and_issues_still_work(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    bodies = {"/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
              "/v2/namespaces": [], "/v2/web-apps": []}

    def get(path: str, **_: Any) -> dict[str, Any]:
        if path == "/v2/journal/settings":
            raise IRISResponseError(500)
        return {"status": OK, "console": [], "result": bodies[path]}

    mock_iris_client.get.side_effect = get

    response = client.get("/api/iris/issues")

    assert response.status_code == 200
    body = response.json()
    assert [i["kind"] for i in body["issues"]] == ["database_dismounted"]
    assert body["recommendations"] == []
    assert body["recommendations_unavailable"] == ["journal_purge_archived_off"]


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


def test_database_and_web_app_issues_are_reported_together(client: TestClient, mock_iris_client: AsyncMock) -> None:
    _mock(mock_iris_client, [_db("DEMO", "/data/demo/")], [_dir("/data/demo/", "Dismounted")], USER_NS,
          web_apps=[_app("/csp/orders", "ORDERS")])

    body = _issues(client)

    assert [i["kind"] for i in body["issues"]] == ["database_dismounted", "web_app_namespace_missing"]
    assert list(body["resolutions"]) == ["database_dismounted", "web_app_namespace_missing"]


def test_unreadable_web_apps_are_reported_and_database_issues_still_work(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    bodies = {"/v2/databases": [_db("DEMO", "/data/demo/")], "/v2/database-dirs": [_dir("/data/demo/", "Dismounted")],
              "/v2/namespaces": [], "/v2/journal/settings": _journal()}

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
