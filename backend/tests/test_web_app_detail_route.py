"""Tests for GET /api/iris/web-apps/detail?name=<Name> — the Web Apps
Explorer's detail drawer.

Uses mocks (fixtures shared via conftest.py) rather than the real IRIS
container. The canned body is the ACTUAL `GET /v2/web-app?name=/csp/user`
response captured from icc-iris-dev, not invented data — see
app/models/iris.py's WebAppDetail comment.
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

WEB_APP_DETAIL_BODY: dict[str, Any] = {
    "status": {"errors": [], "summary": ""},
    "console": [],
    "result": {
        "AutheEnabled": 96,
        "AutoCompile": False,
        "ChangePasswordPage": "",
        "CookiePath": "/csp/user/",
        "CorsAllowlist": [],
        "CorsCredentialsAllowed": False,
        "CorsHeadersList": [],
        "CSPZENEnabled": True,
        "CSRFToken": False,
        "DeepSeeEnabled": False,
        "Description": "User Namespace applications",
        "DispatchClass": "",
        "Enabled": True,
        "ErrorPage": "",
        "EventClass": "",
        "GroupById": "%ISCMgtPortal",
        "iKnowEnabled": False,
        "InbndWebServicesEnabled": True,
        "IsNameSpaceDefault": True,
        "JWTAuthEnabled": False,
        "JWTAccessTokenTimeout": 60,
        "JWTRefreshTokenTimeout": 900,
        "LockCSPName": True,
        "LoginPage": "",
        "NameSpace": "USER",
        "Package": "",
        "Path": "/usr/irissys/csp/user/",
        "PermittedClasses": "",
        "Recurse": True,
        "RedirectEmptyPath": False,
        "Resource": "",
        "ServeFiles": "Always and cached",
        "ServeFilesTimeout": 3600,
        "SuperClass": "",
        "Timeout": 900,
        "TraceEnabled": False,
        "TwoFactorEnabled": False,
        "UseCookies": "Always",
        "SessionScope": "Strict",
        "UserCookieScope": "Strict",
        "WSGIAppLocation": "",
        "WSGIAppName": "",
        "WSGICallable": "app",
        "WSGIDebug": False,
        "WSGIType": "WSGI",
        "MatchRoles": [{"MatchRole": "", "TargetRoles": ["%DB_USER"]}],
    },
}


def test_get_web_app_detail_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = WEB_APP_DETAIL_BODY

    response = client.get("/api/iris/web-apps/detail", params={"name": "/csp/user"})

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["NameSpace"] == "USER"
    assert result["AutheEnabled"] == 96
    assert result["Path"] == "/usr/irissys/csp/user/"
    assert result["WSGIType"] == "WSGI"
    assert result["MatchRoles"] == [{"MatchRole": "", "TargetRoles": ["%DB_USER"]}]
    assert len(result) == 46
    mock_iris_client.get.assert_awaited_once_with("/v2/web-app", params={"name": "/csp/user"})
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post.assert_not_called()


def test_get_web_app_detail_requires_name(client: TestClient, mock_iris_client: AsyncMock) -> None:
    response = client.get("/api/iris/web-apps/detail")

    assert response.status_code == 422
    mock_iris_client.get.assert_not_awaited()


def test_get_web_app_detail_propagates_not_found(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """mainspec_v2.json documents a 404 for an unknown web app name — it is
    surfaced the same generic, safe way as every other IRIS client error."""
    mock_iris_client.get.side_effect = IRISResponseError(404)

    response = client.get("/api/iris/web-apps/detail", params={"name": "/does-not-exist"})

    assert response.status_code == 502
    assert response.json()["detail"] == "IRIS returned an unexpected HTTP 404"


def test_get_web_app_detail_handles_connection_error(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/web-apps/detail", params={"name": "/csp/user"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


def test_get_web_app_detail_rejects_unexpected_shape(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A response missing an observed field is not silently passed through
    with invented defaults."""
    body = copy.deepcopy(WEB_APP_DETAIL_BODY)
    del body["result"]["NameSpace"]
    mock_iris_client.get.return_value = body

    with pytest.raises(ValidationError):
        client.get("/api/iris/web-apps/detail", params={"name": "/csp/user"})
