"""Tests for the Tasks view's read-only routes:
  - GET /api/iris/tasks/overview (GET /v2/tasks + GET /v2/task/info per task),
  - GET /api/iris/tasks/detail?id= (GET /v2/task, Settings redacted),
  - GET /api/iris/tasks/manager (GET /v2/task/manager).

Uses mocks (fixtures shared via conftest.py) rather than the real IRIS
container. Canned bodies are ACTUAL responses captured from icc-iris-dev,
including the observed list/info disagreement on `Suspended` (Integrity
Check, id 4) and the non-date NextScheduled values ("" and
"Runs After #1:00").
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

OK_STATUS = {"errors": [], "summary": ""}

LIST_BODY: dict[str, Any] = {
    "status": OK_STATUS,
    "console": [],
    "result": [
        {"Name": "Switch Journal", "Type": "System", "Namespace": "%SYS",
         "Description": "Switches the journal file at midnight every day", "Id": 1,
         "Suspended": False, "LastFinished": "2026-09-22 08:59:00",
         "NextScheduled": "2026-09-23 00:00:00"},
        {"Name": "Integrity Check", "Type": "System", "Namespace": "%SYS",
         "Description": "Integrity check for databases at 2:00 am every Monday", "Id": 4,
         "Suspended": False, "LastFinished": "", "NextScheduled": "2026-09-28 02:00:00"},
        {"Name": "Diagnostic Report", "Type": "System", "Namespace": "%SYS",
         "Description": "Send system diagnostic reports to WRC On Demand, and/or on a schedule",
         "Id": 6, "Suspended": False, "LastFinished": "", "NextScheduled": ""},
        {"Name": "Purge Audit Database", "Type": "System", "Namespace": "%SYS",
         "Description": "Purges old Audit information after Switch Journal is run", "Id": 7,
         "Suspended": False, "LastFinished": "2026-09-22 08:59:00",
         "NextScheduled": "Runs After #1:00"},
    ],
}

INFO_RESULTS: dict[int, dict[str, Any]] = {
    1: {"Type": "System", "Status": "1", "Error": "Success", "LastSchedule": "2026-09-22 00:00:00",
        "LastStarted": "2026-09-22 08:59:44", "LastFinished": "2026-09-22 08:59:44",
        "NextScheduled": "2026-09-23 00:00:00", "Suspended": False},
    4: {"Type": "System", "Status": "1", "Error": "", "LastSchedule": "2026-09-21 07:40:06",
        "LastStarted": "", "LastFinished": "", "NextScheduled": "2026-09-28 02:00:00",
        "Suspended": True},
    6: {"Type": "System", "Status": "1", "Error": "", "LastSchedule": "", "LastStarted": "",
        "LastFinished": "", "NextScheduled": "", "Suspended": False},
    7: {"Type": "System", "Status": "1", "Error": "Success", "LastSchedule": "2026-09-22 08:59:44",
        "LastStarted": "2026-09-22 08:59:44", "LastFinished": "2026-09-22 08:59:44",
        "NextScheduled": "", "Suspended": False},
}

DIAGNOSTIC_REPORT_DETAIL: dict[str, Any] = {
    "status": OK_STATUS,
    "console": [],
    "result": {
        "Name": "Diagnostic Report", "RunAsUser": "_SYSTEM", "EmailOnCompletion": [],
        "EmailOnError": [], "EmailOnExpiration": [], "ExpiresDays": "", "ExpiresHours": "",
        "ExpiresMinutes": "", "OutputDirectory": "", "OutputFilename": "", "Priority": "Normal",
        "TaskClass": "%SYS.Task.DiagnosticReport", "NameSpace": "%SYS", "TimePeriod": "On Demand",
        "TimePeriodEvery": 7, "TimePeriodDay": "", "DailyFrequency": "Once",
        "DailyFrequencyTime": "", "DailyIncrement": "", "DailyStartTime": "16:32:20",
        "DailyEndTime": "00:00:00", "StartDate": "2026-06-27", "EndDate": "", "RunAfterGUID": "",
        "MirrorStatus": "Any",
        "Description": "Send system diagnostic reports to WRC On Demand, and/or on a schedule",
        "EmailOutput": False, "Expires": False, "OpenOutputFile": False,
        "OutputFileIsBinary": True, "SuspendOnError": False, "SuspendTerminated": False,
        "IsBatch": False, "RescheduleOnStart": False,
        "Settings": {
            "AdvancedReport": 0, "ArchiveDirectory": "", "EmailCC": "",
            "EmailFrom": "DefaultDiagnosticReport@InterSystems.com", "EmailReplyTo": "",
            "SMTPPass": "hunter2-not-real", "SMTPPort": 25, "SMTPSSLCheckServerIdentity": 1,
            "SMTPSSLConfiguration": "", "SMTPServer": "", "SMTPUseSTARTTLS": 0, "SMTPUser": "",
            "WRCHealthCheckEnabled": 0, "WRCIssueNumber": "",
        },
    },
}

INTEGRITY_CHECK_DETAIL: dict[str, Any] = {
    "status": OK_STATUS,
    "console": [],
    "result": {
        **DIAGNOSTIC_REPORT_DETAIL["result"],
        "Name": "Integrity Check", "TaskClass": "%SYS.Task.IntegrityCheck", "Priority": "Low",
        "TimePeriod": "Weekly", "TimePeriodEvery": 1, "TimePeriodDay": 2,
        "DailyStartTime": "02:00:00", "Expires": True,
        "Description": "Integrity check for databases at 2:00 am every Monday",
        "Settings": {"Directory": "/usr/irissys/mgr/", "Filename": "", "KeepDays": 0},
    },
}


def _route_gets(info_results: dict[int, dict[str, Any]] | None = None, failing: set[int] = frozenset()):
    """A mock `client.get` answering GET /v2/tasks and GET /v2/task/info."""
    info_results = INFO_RESULTS if info_results is None else info_results

    async def fake_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/tasks":
            return copy.deepcopy(LIST_BODY)
        if path == "/v2/task/info":
            task_id = params["id"]
            if task_id in failing:
                raise IRISResponseError(403)
            return {"status": OK_STATUS, "console": [], "result": dict(info_results[task_id])}
        raise AssertionError(f"unexpected GET {path}")

    return fake_get


# --- /tasks/overview ---


def test_overview_merges_info_and_derives_state(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = _route_gets()

    response = client.get("/api/iris/tasks/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == {"errors": [], "summary": ""}
    by_id = {entry["Id"]: entry for entry in body["result"]}
    assert [entry["Id"] for entry in body["result"]] == [1, 4, 6, 7]
    assert by_id[1]["State"] == "Not Running"
    # The list said Suspended=false for Integrity Check; /v2/task/info is authoritative.
    assert by_id[4]["State"] == "Suspended"
    assert by_id[4]["Info"]["Suspended"] is True
    assert by_id[6]["State"] == "Not Running"
    assert by_id[1]["Info"]["Error"] == "Success"
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post.assert_not_called()


def test_overview_does_not_expose_list_suspended(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = _route_gets()

    entry = client.get("/api/iris/tasks/overview").json()["result"][0]

    assert "Suspended" not in entry
    assert set(entry) == {
        "Id", "Name", "Type", "Namespace", "Description", "LastFinished", "NextScheduled", "Info", "State",
    }


def test_overview_passes_non_date_next_scheduled_through(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = _route_gets()

    by_id = {e["Id"]: e for e in client.get("/api/iris/tasks/overview").json()["result"]}

    assert by_id[6]["NextScheduled"] == ""
    assert by_id[7]["NextScheduled"] == "Runs After #1:00"


def test_overview_running_status_wins(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """Status "-1" is the spec's documented JobRunning code."""
    infos = copy.deepcopy(INFO_RESULTS)
    infos[1]["Status"] = "-1"
    infos[4]["Status"] = "-1"  # suspended, but its job is executing right now
    mock_iris_client.get.side_effect = _route_gets(infos)

    by_id = {e["Id"]: e for e in client.get("/api/iris/tasks/overview").json()["result"]}

    assert by_id[1]["State"] == "Running"
    assert by_id[4]["State"] == "Running"


def test_overview_info_failure_is_a_warning_not_a_guess(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = _route_gets(failing={4})

    response = client.get("/api/iris/tasks/overview")

    assert response.status_code == 200
    body = response.json()
    by_id = {e["Id"]: e for e in body["result"]}
    assert by_id[4]["Info"] is None
    assert by_id[4]["State"] is None
    assert by_id[1]["State"] == "Not Running"
    assert body["status"]["errors"] == [{"error": "Run state unavailable for task 4", "taskId": 4}]
    assert body["status"]["summary"] == "Run state unavailable for 1 task"


def test_overview_malformed_info_is_treated_as_unavailable(client: TestClient, mock_iris_client: AsyncMock) -> None:
    infos = copy.deepcopy(INFO_RESULTS)
    del infos[6]["Suspended"]
    mock_iris_client.get.side_effect = _route_gets(infos)

    by_id = {e["Id"]: e for e in client.get("/api/iris/tasks/overview").json()["result"]}

    assert by_id[6]["Info"] is None
    assert by_id[6]["State"] is None


def test_overview_calls_info_once_per_task_with_real_ids(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = _route_gets()

    client.get("/api/iris/tasks/overview")

    info_ids = sorted(
        call.kwargs["params"]["id"]
        for call in mock_iris_client.get.await_args_list
        if call.args[0] == "/v2/task/info"
    )
    assert info_ids == [1, 4, 6, 7]


def test_overview_list_failure_fails_request(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/tasks/overview")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


# --- /tasks/detail ---


def test_detail_redacts_sensitive_settings(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = copy.deepcopy(DIAGNOSTIC_REPORT_DETAIL)

    response = client.get("/api/iris/tasks/detail", params={"id": 6})

    assert response.status_code == 200
    assert "hunter2-not-real" not in response.text
    result = response.json()["result"]
    assert result["Settings"]["SMTPPass"] is None
    assert result["RedactedSettings"] == ["SMTPPass"]
    # Non-secret settings are passed through unchanged.
    assert result["Settings"]["SMTPPort"] == 25
    assert result["Settings"]["SMTPUser"] == ""
    assert result["Settings"]["EmailFrom"] == "DefaultDiagnosticReport@InterSystems.com"
    mock_iris_client.get.assert_awaited_once_with("/v2/task", params={"id": 6})
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post.assert_not_called()


def test_detail_redacts_empty_secret_values_too(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(DIAGNOSTIC_REPORT_DETAIL)
    body["result"]["Settings"]["SMTPPass"] = ""
    mock_iris_client.get.return_value = body

    result = client.get("/api/iris/tasks/detail", params={"id": 6}).json()["result"]

    assert result["Settings"]["SMTPPass"] is None
    assert result["RedactedSettings"] == ["SMTPPass"]


def test_detail_redacts_nested_and_varied_keys(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(INTEGRITY_CHECK_DETAIL)
    body["result"]["Settings"] = {
        "KeepDays": 0,
        "Remote": {"ApiKey": "k-not-real", "Host": "h"},
        "AccessToken": "t-not-real",
        "Password": "p-not-real",
        "ClientSecret": "s-not-real",
    }
    mock_iris_client.get.return_value = body

    response = client.get("/api/iris/tasks/detail", params={"id": 4})

    for secret in ("k-not-real", "t-not-real", "p-not-real", "s-not-real"):
        assert secret not in response.text
    result = response.json()["result"]
    assert sorted(result["RedactedSettings"]) == ["AccessToken", "ClientSecret", "Password", "Remote.ApiKey"]
    assert result["Settings"]["Remote"]["Host"] == "h"
    assert result["Settings"]["KeepDays"] == 0


def test_detail_keeps_observed_field_types(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = copy.deepcopy(INTEGRITY_CHECK_DETAIL)

    result = client.get("/api/iris/tasks/detail", params={"id": 4}).json()["result"]

    assert result["TimePeriodEvery"] == 1
    assert result["TimePeriodDay"] == 2
    assert result["ExpiresDays"] == ""
    assert result["DailyIncrement"] == ""
    assert result["RedactedSettings"] == []
    assert result["Settings"] == {"Directory": "/usr/irissys/mgr/", "Filename": "", "KeepDays": 0}


def test_detail_requires_integer_id(client: TestClient, mock_iris_client: AsyncMock) -> None:
    assert client.get("/api/iris/tasks/detail").status_code == 422
    assert client.get("/api/iris/tasks/detail", params={"id": "abc"}).status_code == 422
    mock_iris_client.get.assert_not_awaited()


def test_detail_unknown_id_is_404(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(404)

    response = client.get("/api/iris/tasks/detail", params={"id": 999})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no task with this id"


def test_detail_other_errors_are_generic(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(403)

    response = client.get("/api/iris/tasks/detail", params={"id": 1})

    assert response.status_code == 502
    assert response.json()["detail"] == "IRIS returned an unexpected HTTP 403"


def test_detail_rejects_unexpected_shape(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(INTEGRITY_CHECK_DETAIL)
    del body["result"]["TaskClass"]
    mock_iris_client.get.return_value = body

    with pytest.raises(ValidationError):
        client.get("/api/iris/tasks/detail", params={"id": 4})


# --- /tasks/manager ---


def test_manager_status(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = {"status": OK_STATUS, "console": [], "result": {"Status": "Running"}}

    response = client.get("/api/iris/tasks/manager")

    assert response.status_code == 200
    assert response.json()["result"] == {"Status": "Running"}
    mock_iris_client.get.assert_awaited_once_with("/v2/task/manager")


def test_manager_connection_error(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/tasks/manager")

    assert response.status_code == 502
