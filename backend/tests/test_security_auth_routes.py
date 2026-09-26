"""Tests for the Authentication routes in app/routes/security_access.py:
services, web-auth, superservers and class-access.

Canned bodies are real responses, except where a test needs a value our
instance doesn't have (like a non-empty SMTPUsername), which is marked.
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

OK = {"errors": [], "summary": ""}


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


SERVICES = [
    {"Name": "%Service_Terminal", "Enabled": True, "Public": "Yes",
     "AuthenticationMethods": ["Password", "Operating System"], "AllowedConnections": [],
     "Description": "Controls terminal session on Unix", "HttpOnlyCookies": False, "TwoFactorEnabled": False},
    {"Name": "%Service_Weblink", "Enabled": False, "Public": "N/A", "AuthenticationMethods": ["Unauthenticated"],
     "AllowedConnections": [], "Description": "Controls WebLink", "HttpOnlyCookies": False,
     "TwoFactorEnabled": False},
]

SERVICE_DETAIL = {"AutheEnabled": 48, "ClientSystems": [], "Description": "Controls terminal session on Unix",
                  "Enabled": True}

WEB_AUTH = {
    "AutheAlwaysTryDelegated": False, "AutheCache": True, "AutheDelegated": False, "AutheKB": True,
    "AutheLDAP": False, "AutheLDAPCache": False, "AutheLoginToken": False, "AutheOAuth2": False, "AutheOS": True,
    "AutheOSDelegated": False, "AutheOSLDAP": False, "AutheTwoFactorPW": False, "AutheTwoFactorSMS": False,
    "AutheUnauthenticated": True, "LoginCookieTimeout": 0, "SMTPServer": "",
    # Real value is ""; a non-empty one shows it gets withheld.
    "SMTPUsername": "mailer-account-not-real",
    # Real value is ""; a non-empty one shows it gets withheld.
    "TwoFactorFrom": "2fa-sender@example.invalid",
    "TwoFactorTimeout": 180, "JWTIssuer": "", "JWTSigAlg": "ES256",
}

SUPERSERVERS = [{"Port": 1972, "BindAddress": "0.0.0.0", "Enabled": True, "SystemDefault": True}]

SUPERSERVER_DETAIL = {
    "Description": "System default port", "EnableCacheDirect": False, "EnableClients": True, "EnableCSP": True,
    "EnableDataCheck": True, "EnableECP": True, "EnableMirror": True, "EnableNodeJS": False,
    "EnableShadows": False, "EnableSharding": True, "EnableSNMP": False, "EnableWebLink": False, "Enabled": True,
    "SSLConfig": "", "SSLSupportLevel": 0, "SystemDefault": True,
}

CLASS_ACCESS = [
    {"Name": "all-applications", "AllowType": "AllowClass", "Class": "%SYS.Python.WSGI", "AllowAccess": True,
     "System": True},
    {"Name": "/api/admin", "AllowType": "AllowClass", "Class": "%Api.Admin", "AllowAccess": True, "System": True},
]


def fake_iris(superserver_fails: bool = False):
    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/security/services":
            return envelope(copy.deepcopy(SERVICES))
        if path == "/v2/security/service":
            if params != {"name": "%Service_Terminal"}:
                raise IRISResponseError(404)
            return envelope(dict(SERVICE_DETAIL))
        if path == "/v2/security/web-auth":
            return envelope(dict(WEB_AUTH))
        if path == "/v2/security/superservers":
            return envelope(copy.deepcopy(SUPERSERVERS))
        if path == "/v2/security/superserver":
            assert params == {"port": 1972, "bindAddress": "0.0.0.0"}
            if superserver_fails:
                raise IRISResponseError(500)
            return envelope(dict(SUPERSERVER_DETAIL))
        if path == "/v2/web-app/pct-accesses":
            return envelope(copy.deepcopy(CLASS_ACCESS))
        raise AssertionError(f"unexpected GET {path}")

    return get


@pytest.fixture
def iris(mock_iris_client: AsyncMock) -> AsyncMock:
    mock_iris_client.get.side_effect = fake_iris()
    return mock_iris_client


def assert_read_only(mock: AsyncMock) -> None:
    mock.put.assert_not_called()
    mock.post.assert_not_called()


def test_services_list(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/services")

    assert response.status_code == 200
    assert response.json()["result"] == SERVICES
    assert_read_only(iris)


def test_service_detail(client: TestClient, iris: AsyncMock) -> None:
    result = client.get("/api/iris/security/services/detail", params={"name": "%Service_Terminal"}).json()["result"]

    assert result == SERVICE_DETAIL
    assert_read_only(iris)


def test_service_detail_unknown_is_404(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/services/detail", params={"name": "%Service_Nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no service with this name"


def test_service_detail_requires_name(client: TestClient, iris: AsyncMock) -> None:
    assert client.get("/api/iris/security/services/detail").status_code == 422
    iris.get.assert_not_awaited()


def test_web_auth_withholds_smtp_username_and_two_factor_sender(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/web-auth")

    assert response.status_code == 200
    for value in ("mailer-account-not-real", "2fa-sender@example.invalid"):
        assert value not in response.text
    result = response.json()["result"]
    assert "SMTPUsername" not in result
    assert "TwoFactorFrom" not in result
    assert result["WithheldFields"] == ["SMTPUsername", "TwoFactorFrom"]
    assert result["AutheUnauthenticated"] is True
    assert result["JWTSigAlg"] == "ES256"
    assert result["TwoFactorTimeout"] == 180
    assert_read_only(iris)


def test_web_auth_drops_unmodelled_fields(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """A made-up SMTP password field doesn't get through."""
    mock_iris_client.get.return_value = envelope({**WEB_AUTH, "SMTPPassword": "not-a-real-password"})

    response = client.get("/api/iris/security/web-auth")

    assert "not-a-real-password" not in response.text
    assert "SMTPPassword" not in response.json()["result"]


def test_superservers_merge_detail(client: TestClient, iris: AsyncMock) -> None:
    body = client.get("/api/iris/security/superservers").json()

    assert body["status"] == OK
    [server] = body["result"]
    assert server["Port"] == 1972 and server["BindAddress"] == "0.0.0.0"
    assert server["Detail"]["SSLSupportLevel"] == 0
    assert server["Detail"]["EnableECP"] is True
    assert_read_only(iris)


def test_superserver_detail_failure_is_a_warning(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(superserver_fails=True)

    body = client.get("/api/iris/security/superservers").json()

    assert body["result"][0]["Detail"] is None
    assert body["result"][0]["Enabled"] is True
    assert body["status"]["errors"] == [
        {"error": "Superserver detail unavailable for 0.0.0.0:1972", "port": 1972}
    ]
    assert body["status"]["summary"] == "Superserver detail unavailable for 1 superserver"


def test_class_access(client: TestClient, iris: AsyncMock) -> None:
    assert client.get("/api/iris/security/class-access").json()["result"] == CLASS_ACCESS


def test_empty_lists_are_passed_through(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = envelope([])

    assert client.get("/api/iris/security/class-access").json()["result"] == []
    assert client.get("/api/iris/security/services").json()["result"] == []


def test_connection_errors_are_generic(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    for path in ("services", "web-auth", "superservers", "class-access"):
        response = client.get(f"/api/iris/security/{path}")
        assert response.status_code == 502
        assert response.json()["detail"] == "Could not connect to IRIS"


def test_unexpected_shape_is_rejected(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = copy.deepcopy(SERVICES)
    del body[0]["Public"]
    mock_iris_client.get.return_value = envelope(body)

    with pytest.raises(ValidationError):
        client.get("/api/iris/security/services")
