"""Tests for the read-only Wallet routes in app/routes/security_access.py.

icc-iris-dev has no wallet collections, so populated bodies here follow
mainspec_v2.json's WalletCollectionList / WalletCollection /
WalletSecretList shapes. To prove the allowlist, several canned bodies
deliberately carry value-bearing fields IRIS is NOT documented to return on
these GETs (`Secret`, `WalletSecretConfig`, `Password`) with sentinel
values; none of those values may ever appear in a response.
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
SENTINELS = ("sentinel-secret-value", "sentinel-password", "sentinel-api-key", "sentinel-private-key")
ALLOWED_IRIS_PATHS = {"/v2/wallet/collections", "/v2/wallet/collection", "/v2/wallet/secrets"}


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


COLLECTIONS = [
    {"Name": "Payments", "EditResource": "%Admin_Wallet:USE", "UseResource": "%DB_USER:READ",
     # Not documented for this GET — must be dropped.
     "Secret": "sentinel-secret-value"},
    {"Name": "Integrations", "EditResource": "%Admin_Manage", "UseResource": "%Development"},
]

SECRETS = {
    "Payments": [
        {"Name": "Payments.StripeKey", "Type": "%Wallet.KeyValue",
         # Not documented for this GET — must be dropped.
         "WalletSecretConfig": {"Secret": {"user": "u", "password": "sentinel-password"}},
         "Secret": "sentinel-api-key"},
        {"Name": "Payments.SigningKey", "Type": "%Wallet.RSA", "PrivateKey": "sentinel-private-key"},
    ],
    "Integrations": [],
}


def fake_iris(failing: set[str] = frozenset()):
    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path in ALLOWED_IRIS_PATHS, f"unexpected IRIS path {path}"
        if path == "/v2/wallet/collections":
            return envelope(copy.deepcopy(COLLECTIONS))
        if path == "/v2/wallet/collection":
            match = next((c for c in COLLECTIONS if c["Name"] == params["name"]), None)
            if match is None:
                raise IRISResponseError(404)
            return envelope({**{k: v for k, v in match.items() if k != "Name"}, "Password": "sentinel-password"})
        collection = params["collection"]
        if collection in failing:
            raise IRISResponseError(500)
        if collection not in SECRETS:
            raise IRISResponseError(404)
        return envelope(copy.deepcopy(SECRETS[collection]))

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


def assert_no_secret_values(text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text
    for field in ("Secret", "WalletSecretConfig", "Password", "PrivateKey"):
        assert f'"{field}"' not in text


def test_overview_returns_names_types_and_permissions_only(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/wallet/overview")

    assert response.status_code == 200
    assert_no_secret_values(response.text)
    body = response.json()
    assert body["status"] == OK
    assert body["result"] == [
        {"Name": "Payments", "EditResource": "%Admin_Wallet:USE", "UseResource": "%DB_USER:READ",
         "Secrets": [{"Name": "Payments.StripeKey", "Type": "%Wallet.KeyValue"},
                     {"Name": "Payments.SigningKey", "Type": "%Wallet.RSA"}]},
        {"Name": "Integrations", "EditResource": "%Admin_Manage", "UseResource": "%Development", "Secrets": []},
    ]
    assert_only_gets(iris)


def test_overview_empty_wallet(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """The live icc-iris-dev case: no collections at all."""
    mock_iris_client.get.return_value = envelope([])

    body = client.get("/api/iris/security/wallet/overview").json()

    assert body == {"status": OK, "console": [], "result": []}
    mock_iris_client.get.assert_awaited_once_with("/v2/wallet/collections")


def test_overview_secret_list_failure_is_a_warning(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(failing={"Payments"})

    body = client.get("/api/iris/security/wallet/overview").json()

    by_name = {c["Name"]: c for c in body["result"]}
    assert by_name["Payments"]["Secrets"] is None
    assert by_name["Integrations"]["Secrets"] == []
    assert body["status"]["errors"] == [{"error": "Secret list unavailable for Payments", "collection": "Payments"}]
    assert body["status"]["summary"] == "Secret list unavailable for 1 collection"


def test_collection_detail_drops_unexpected_fields(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/wallet/collections/detail", params={"name": "Payments"})

    assert response.status_code == 200
    assert_no_secret_values(response.text)
    assert response.json()["result"] == {"EditResource": "%Admin_Wallet:USE", "UseResource": "%DB_USER:READ"}
    assert_only_gets(iris)


def test_collection_detail_unknown_is_404(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/wallet/collections/detail", params={"name": "Nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no wallet collection with this name"


def test_secrets_returns_names_and_types_only(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/wallet/secrets", params={"collection": "Payments"})

    assert response.status_code == 200
    assert_no_secret_values(response.text)
    assert response.json()["result"] == [
        {"Name": "Payments.StripeKey", "Type": "%Wallet.KeyValue"},
        {"Name": "Payments.SigningKey", "Type": "%Wallet.RSA"},
    ]
    iris.get.assert_awaited_once_with("/v2/wallet/secrets", params={"collection": "Payments"})
    assert_only_gets(iris)


def test_secrets_requires_collection_and_handles_unknown(client: TestClient, iris: AsyncMock) -> None:
    assert client.get("/api/iris/security/wallet/secrets").status_code == 422
    iris.get.assert_not_awaited()
    response = client.get("/api/iris/security/wallet/secrets", params={"collection": "Nope"})
    assert response.status_code == 404


def test_connection_error_is_generic(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/security/wallet/overview")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


def test_wallet_routes_are_registered_as_get_only() -> None:
    # The OpenAPI schema lists every registered route and its methods,
    # including those in included routers.
    paths = app.openapi()["paths"]
    wallet_paths = {path: ops for path, ops in paths.items() if path.startswith("/api/iris/security/wallet")}
    assert set(wallet_paths) == {
        "/api/iris/security/wallet/overview",
        "/api/iris/security/wallet/collections/detail",
        "/api/iris/security/wallet/secrets",
    }
    for ops in wallet_paths.values():
        assert set(ops) == {"get"}


def test_route_module_never_calls_a_mutating_or_secret_value_endpoint() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "routes" / "security_access.py").read_text(encoding="utf-8")
    for forbidden in ("client.put", "client.post", "client.delete", '"/v2/wallet/secret"', "/v2/wallet/secret\""):
        assert forbidden not in source
