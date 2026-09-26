"""Tests for the X.509 routes in app/routes/security_access.py.

Our instance has no X.509 credentials, so the bodies follow the spec.
Some include key fields IRIS shouldn't return here (PrivateKey,
PrivateKeyPassword, PrivateKeyFile, CertificateFile, a PEM Certificate)
set to a sentinel, which must never show up in a response.
"""

import copy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError
from app.main import app

OK = {"errors": [], "summary": ""}
SENTINELS = (
    "sentinel-private-key",
    "sentinel-key-password",
    "/sentinel/private.key",
    "/sentinel/cert.pem",
    "-----BEGIN PRIVATE KEY-----",
)
FORBIDDEN_FIELDS = ("PrivateKey", "PrivateKeyPassword", "PrivateKeyFile", "CertificateFile", "Certificate\"")
ALLOWED_IRIS_PATHS = {
    "/v2/security/x509-credentials",
    "/v2/security/x509-credential",
    "/v2/security/x509-credential/certificate",
}


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


CREDENTIALS = [
    {"Alias": "WebServer", "HasPrivateKey": True, "OwnerList": ["_SYSTEM"], "PeerNames": ["api.example.test"],
     "CAFile": "/usr/irissys/mgr/ca.pem",
     # Not returned by this GET, so it must be dropped.
     "PrivateKey": "sentinel-private-key", "PrivateKeyFile": "/sentinel/private.key"},
    {"Alias": "PartnerCA", "HasPrivateKey": False, "OwnerList": [], "PeerNames": [], "CAFile": ""},
]

DETAILS = {
    "WebServer": {"OwnerList": ["_SYSTEM"], "PeerNames": ["api.example.test"], "CAFile": "/usr/irissys/mgr/ca.pem",
                  "PrivateKeyPassword": "sentinel-key-password", "CertificateFile": "/sentinel/cert.pem"},
    "PartnerCA": {"OwnerList": [], "PeerNames": [], "CAFile": ""},
}

CERTIFICATES = {
    "WebServer": {"HasPrivateKey": True, "SerialNumber": "10769702131171890123", "IssuerDN": "CN=Example CA",
                  "SubjectDN": "CN=api.example.test", "ValidityNotBefore": "2026-01-01 00:00:00",
                  "ValidityNotAfter": "2027-01-01 00:00:00",
                  "Certificate": "-----BEGIN PRIVATE KEY-----sentinel-private-key"},
    "PartnerCA": {"HasPrivateKey": False, "SerialNumber": "42", "IssuerDN": "CN=Partner Root",
                  "SubjectDN": "CN=Partner Root", "ValidityNotBefore": "2020-01-01 00:00:00",
                  "ValidityNotAfter": "2025-01-01 00:00:00"},
}


def fake_iris(failing: set[str] = frozenset()):
    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path in ALLOWED_IRIS_PATHS, f"unexpected IRIS path {path}"
        if path == "/v2/security/x509-credentials":
            return envelope(copy.deepcopy(CREDENTIALS))
        alias = params["alias"]
        if path == "/v2/security/x509-credential":
            if alias not in DETAILS:
                raise IRISResponseError(404)
            return envelope(dict(DETAILS[alias]))
        if alias in failing:
            raise IRISResponseError(500)
        if alias not in CERTIFICATES:
            raise IRISResponseError(404)
        return envelope(dict(CERTIFICATES[alias]))

    return get


@pytest.fixture
def iris(mock_iris_client: AsyncMock) -> AsyncMock:
    mock_iris_client.get.side_effect = fake_iris()
    return mock_iris_client


def assert_only_gets(mock: AsyncMock) -> None:
    mock.put.assert_not_called()
    mock.post.assert_not_called()
    mock.delete.assert_not_called()
    for call in mock.get.await_args_list:
        assert call.args[0] in ALLOWED_IRIS_PATHS


def assert_no_key_material(text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text
    for field in FORBIDDEN_FIELDS:
        assert f'"{field}' not in text.replace('"Certificate":{', "").replace('"Certificate":null', "")


def test_overview_merges_metadata_only(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/x509/overview")

    assert response.status_code == 200
    assert_no_key_material(response.text)
    body = response.json()
    assert body["status"] == OK
    web, partner = body["result"]
    assert set(web) == {"Alias", "HasPrivateKey", "OwnerList", "PeerNames", "CAFile", "Certificate"}
    assert web["Certificate"] == {
        "HasPrivateKey": True, "SerialNumber": "10769702131171890123", "IssuerDN": "CN=Example CA",
        "SubjectDN": "CN=api.example.test", "ValidityNotBefore": "2026-01-01 00:00:00",
        "ValidityNotAfter": "2027-01-01 00:00:00",
    }
    assert partner["OwnerList"] == [] and partner["HasPrivateKey"] is False
    assert_only_gets(iris)


def test_overview_empty(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """No credentials at all (what our instance has)."""
    mock_iris_client.get.return_value = envelope([])

    body = client.get("/api/iris/security/x509/overview").json()

    assert body == {"status": OK, "console": [], "result": []}
    mock_iris_client.get.assert_awaited_once_with("/v2/security/x509-credentials")


def test_overview_certificate_failure_is_a_warning(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(failing={"WebServer"})

    body = client.get("/api/iris/security/x509/overview").json()

    by_alias = {c["Alias"]: c for c in body["result"]}
    assert by_alias["WebServer"]["Certificate"] is None
    assert by_alias["PartnerCA"]["Certificate"]["SerialNumber"] == "42"
    assert body["status"]["errors"] == [{"error": "Certificate unavailable for WebServer", "alias": "WebServer"}]
    assert body["status"]["summary"] == "Certificate unavailable for 1 credential"


def test_credential_detail_drops_key_fields(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/x509/credentials/detail", params={"alias": "WebServer"})

    assert response.status_code == 200
    assert_no_key_material(response.text)
    assert response.json()["result"] == {
        "OwnerList": ["_SYSTEM"], "PeerNames": ["api.example.test"], "CAFile": "/usr/irissys/mgr/ca.pem",
    }
    iris.get.assert_awaited_once_with("/v2/security/x509-credential", params={"alias": "WebServer"})
    assert_only_gets(iris)


def test_certificate_returns_metadata_only(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/x509/credentials/certificate", params={"alias": "WebServer"})

    assert response.status_code == 200
    assert_no_key_material(response.text)
    assert set(response.json()["result"]) == {
        "HasPrivateKey", "SerialNumber", "IssuerDN", "SubjectDN", "ValidityNotBefore", "ValidityNotAfter",
    }
    assert_only_gets(iris)


def test_missing_optional_fields_are_null_not_errors(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = envelope({"SubjectDN": "CN=only-subject"})

    result = client.get("/api/iris/security/x509/credentials/certificate", params={"alias": "x"}).json()["result"]

    assert result["SubjectDN"] == "CN=only-subject"
    assert result["ValidityNotAfter"] is None


def test_unknown_alias_is_404_and_alias_is_required(client: TestClient, iris: AsyncMock) -> None:
    for path in ("detail", "certificate"):
        response = client.get(f"/api/iris/security/x509/credentials/{path}", params={"alias": "Nope"})
        assert response.status_code == 404
        assert response.json()["detail"] == "IRIS reports no X.509 credential with this alias"
    iris.get.reset_mock()
    assert client.get("/api/iris/security/x509/credentials/detail").status_code == 422
    iris.get.assert_not_awaited()


def test_connection_error_is_generic(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/security/x509/overview")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


def test_x509_routes_are_registered_as_get_only() -> None:
    paths = app.openapi()["paths"]
    x509_paths = {path: ops for path, ops in paths.items() if path.startswith("/api/iris/security/x509")}
    assert set(x509_paths) == {
        "/api/iris/security/x509/overview",
        "/api/iris/security/x509/credentials/detail",
        "/api/iris/security/x509/credentials/certificate",
    }
    for ops in x509_paths.values():
        assert set(ops) == {"get"}


def test_route_module_never_calls_a_mutating_method() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "routes" / "security_access.py").read_text(encoding="utf-8")
    for forbidden in ("client.put", "client.post", "client.delete", "PrivateKeyPassword"):
        assert forbidden not in source
