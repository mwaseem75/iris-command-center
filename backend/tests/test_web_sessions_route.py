"""Tests for GET /api/iris/web-sessions — the Web Apps Explorer's read-only
Sessions section.

Uses mocks (fixtures shared via conftest.py), never the real IRIS
container. The canned entry is the real `GET /v2/web-sessions` entry
captured from icc-iris-dev, except its `ID`, which is replaced by an
obvious placeholder — the real session identifier is never written into
this repository. The key property under test: that identifier never
reaches a response.
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

PLACEHOLDER_SESSION_ID = "SESSIONID-PLACEHOLDER-0001"

WEB_SESSIONS_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": [
        {
            "ID": PLACEHOLDER_SESSION_ID,
            "Username": "_SYSTEM",
            "Preserve": 0,
            "Application": "/csp/sys/",
            "Timeout": "2026-09-23 02:57:48",
            "LicenseId": "_SYSTEM@172.17.0.1",
            "SesProcessId": "",
            "AllowEndSession": False,
        }
    ],
}


def test_get_web_sessions_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = copy.deepcopy(WEB_SESSIONS_BODY)

    response = client.get("/api/iris/web-sessions")

    assert response.status_code == 200
    (session,) = response.json()["result"]
    assert session == {
        "Username": "_SYSTEM",
        "Preserve": 0,
        "Application": "/csp/sys/",
        "Timeout": "2026-09-23 02:57:48",
        "LicenseId": "_SYSTEM@172.17.0.1",
        "SesProcessId": "",
        "AllowEndSession": False,
    }
    mock_iris_client.get.assert_awaited_once_with("/v2/web-sessions")
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post.assert_not_called()


def test_get_web_sessions_never_exposes_session_id(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """The CSP session ID is what DELETE /v2/web-session?id= takes — it must
    not appear anywhere in the response, under any key."""
    mock_iris_client.get.return_value = copy.deepcopy(WEB_SESSIONS_BODY)

    response = client.get("/api/iris/web-sessions")

    assert PLACEHOLDER_SESSION_ID not in response.text
    assert all("ID" not in session for session in response.json()["result"])


def test_get_web_sessions_empty(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(WEB_SESSIONS_BODY)
    body["result"] = []
    mock_iris_client.get.return_value = body

    response = client.get("/api/iris/web-sessions")

    assert response.status_code == 200
    assert response.json()["result"] == []


def test_get_web_sessions_maps_iris_errors_safely(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(403, body={"echo": PLACEHOLDER_SESSION_ID})

    response = client.get("/api/iris/web-sessions")

    assert response.status_code == 502
    assert response.json()["detail"] == "IRIS returned an unexpected HTTP 403"
    assert PLACEHOLDER_SESSION_ID not in response.text


def test_get_web_sessions_handles_connection_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/web-sessions")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"
