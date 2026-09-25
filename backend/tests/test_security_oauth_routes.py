"""Tests for the read-only OAuth 2.0 routes: the new aggregate/detail routes
in app/routes/security_access.py and the three existing
/api/iris/security/oauth2/* routes in app/routes/iris.py, all of which now
return explicit allowlist models only.

icc-iris-dev has no OAuth 2.0 configuration (server 404 "not configured",
every list empty), so populated bodies follow mainspec_v2.json's shapes. To
prove the allowlists, the canned bodies plant secret-bearing fields IRIS's
OAuth2 classes hold (ClientSecret, ClientPassword, InitialAccessToken,
registration_access_token, client_secret, jwks, ServerPassword,
PrivateKeyPassword, an Authorization header, an Authenticator object) with
sentinel values; none may ever appear in a response.
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
SENTINEL = "sentinel-oauth-secret"
SECRET_FIELDS = (
    "ClientSecret", "ClientPassword", "InitialAccessToken", "registration_access_token", "client_secret",
    "jwks", "ServerPassword", "PrivateKeyPassword", "Authorization", "Authenticator", "access_token",
)


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


def planted(**fields: Any) -> dict[str, Any]:
    """`fields` plus every secret-bearing field, each holding the sentinel."""
    return {**fields, **{name: SENTINEL for name in SECRET_FIELDS}}


SERVER_CONFIG = planted(
    IssuerEndpoint="https://iris.example.test/oauth2", Description="Test authorization server",
    AccessTokenInterval=3600, RefreshTokenInterval=86400, ClientSecretInterval=0,
    SupportedScopes=[{"Scope": "openid", "Description": "OpenID", "Secret": SENTINEL}, "not-an-object"],
    DefaultScope="openid", AllowPublicClientRefresh=False, ForcePKCEForPublicClients=True,
    ServerCredentials="OAuthServerCert", SigningAlgorithm="RS256", SSLConfiguration="DefaultSSL",
    Metadata={"issuer": "https://iris.example.test/oauth2", "token_endpoint": "https://iris.example.test/oauth2/token",
              "jwks_uri": "https://iris.example.test/oauth2/jwks", "scopes_supported": ["openid", {"x": SENTINEL}],
              "jwks": {"keys": [{"d": SENTINEL}]}, "client_secret": SENTINEL},
)
SERVER_CLIENTS = [planted(Name="Portal", ClientId="portal-client-id", ClientType="confidential",
                          Description="Web portal", RedirectURL=["https://portal.example.test/cb"])]
SERVER_CLIENT_DETAIL = planted(
    Name="Portal", RedirectURL=["https://portal.example.test/cb"], ClientType="confidential",
    ClientCredentials="PortalCert",
    Metadata={"client_name": "Portal", "grant_types": ["authorization_code"], "contacts": ["someone@example.test"],
              "client_secret": SENTINEL, "registration_access_token": SENTINEL},
)
DEFINITIONS = [planted(ID="1", IssuerEndpoint="https://idp.example.test", ClientCount=1, ResourceCount=0)]
DEFINITION_DETAIL = planted(IssuerEndpoint="https://idp.example.test", SSLConfiguration="DefaultSSL",
                            Metadata={"issuer": "https://idp.example.test", "jwks": {"keys": [SENTINEL]}})
CLIENT_CONFIGS = [planted(ApplicationName="PortalApp", ClientType="confidential", DefaultScope="openid profile")]
CLIENT_CONFIG_DETAIL = planted(OAuth2ServerDefinition="1", Enabled=True, ClientType="confidential",
                               RedirectionEndpoint="https://iris.example.test/cb", JWTAudience="aud")
RESOURCE_SERVERS = [planted(Name="ApiResource", ServerDefinition="1")]
RESOURCE_SERVER_DETAIL = planted(Enabled=True, IssuerEndpoint="https://idp.example.test", Audiences=["api"],
                                 AccessTokenIsJWT=True, ClientId="api-resource-client",
                                 IntrospectionAuthMethod="client_secret_basic", UseOIDC=False)
MAPPINGS = {"%Service_WebGateway": [planted(Service="%Service_WebGateway", Key="/api/app", Resource="ApiResource")],
            "%Service_Bindings": []}


def fake_iris(server: str = "configured", failing: set[str] = frozenset()):
    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert path.startswith("/v2/security/oauth2/"), f"unexpected IRIS path {path}"
        if path in failing:
            raise IRISResponseError(500)
        if path == "/v2/security/oauth2/server":
            if server == "not-configured":
                raise IRISResponseError(404, body={"status": {"errors": [{"id": "OAuth2NoConfiguration"}], "summary": ""},
                                                   "console": [], "result": {}})
            return envelope(copy.deepcopy(SERVER_CONFIG))
        if path == "/v2/security/oauth2/server/clients":
            return envelope(copy.deepcopy(SERVER_CLIENTS))
        if path == "/v2/security/oauth2/server/client":
            if params != {"clientId": "portal-client-id"}:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(SERVER_CLIENT_DETAIL))
        if path == "/v2/security/oauth2/client/server-definitions":
            return envelope(copy.deepcopy(DEFINITIONS))
        if path == "/v2/security/oauth2/client/server-definition":
            if params != {"serverId": "1"}:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(DEFINITION_DETAIL))
        if path == "/v2/security/oauth2/client/client-configurations":
            return envelope(copy.deepcopy(CLIENT_CONFIGS if params == {"serverId": "1"} else []))
        if path == "/v2/security/oauth2/client/client-configuration":
            if params != {"applicationName": "PortalApp"}:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(CLIENT_CONFIG_DETAIL))
        if path == "/v2/security/oauth2/resource-servers":
            return envelope(copy.deepcopy(RESOURCE_SERVERS))
        if path == "/v2/security/oauth2/resource-server":
            if params != {"name": "ApiResource"}:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(RESOURCE_SERVER_DETAIL))
        if path == "/v2/security/oauth2/resource-server/mappings":
            return envelope(copy.deepcopy(MAPPINGS[params["service"]]))
        raise AssertionError(f"unexpected GET {path}")

    return get


@pytest.fixture
def iris(mock_iris_client: AsyncMock) -> AsyncMock:
    mock_iris_client.get.side_effect = fake_iris()
    return mock_iris_client


def assert_only_gets(mock: AsyncMock) -> None:
    mock.put.assert_not_called()
    mock.post.assert_not_called()
    mock.delete.assert_not_called()


def assert_no_secrets(text: str) -> None:
    assert SENTINEL not in text
    for field in SECRET_FIELDS:
        assert f'"{field}"' not in text
    assert "someone@example.test" not in text  # client metadata `contacts` is not allowlisted


# --- aggregate overview ---


def test_overview_is_allowlisted_and_complete(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/oauth/overview")

    assert response.status_code == 200
    assert_no_secrets(response.text)
    body = response.json()
    assert body["status"] == OK
    result = body["result"]
    assert result["ServerConfigured"] is True
    assert result["Server"]["IssuerEndpoint"] == "https://iris.example.test/oauth2"
    assert result["Server"]["ServerCredentials"] == "OAuthServerCert"
    assert result["Server"]["SupportedScopes"] == [{"Scope": "openid", "Description": "OpenID"}]
    assert result["Server"]["Metadata"]["scopes_supported"] == ["openid"]
    assert result["ServerClients"] == [{"Name": "Portal", "ClientId": "portal-client-id", "ClientType": "confidential",
                                        "Description": "Web portal", "RedirectURL": ["https://portal.example.test/cb"]}]
    [definition] = result["ServerDefinitions"]
    assert definition["ClientConfigurations"] == [
        {"ApplicationName": "PortalApp", "ClientType": "confidential", "DefaultScope": "openid profile"}
    ]
    assert result["ResourceServers"] == [{"Name": "ApiResource", "ServerDefinition": "1"}]
    assert result["ResourceMappings"] == [{"Service": "%Service_WebGateway", "Key": "/api/app", "Resource": "ApiResource"}]
    assert_only_gets(iris)


def test_overview_queries_both_mapping_services(client: TestClient, iris: AsyncMock) -> None:
    client.get("/api/iris/security/oauth/overview")

    services = {
        call.kwargs["params"]["service"]
        for call in iris.get.await_args_list
        if call.args[0] == "/v2/security/oauth2/resource-server/mappings"
    }
    assert services == {"%Service_WebGateway", "%Service_Bindings"}


def test_overview_not_configured_is_honest_not_an_error(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(server="not-configured")

    body = client.get("/api/iris/security/oauth/overview").json()

    assert body["status"] == OK
    assert body["result"]["ServerConfigured"] is False
    assert body["result"]["Server"] is None


def test_overview_empty_instance(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """The live icc-iris-dev case: server not configured, every list empty."""

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/security/oauth2/server":
            raise IRISResponseError(404, body={"status": OK, "console": [], "result": {}})
        return envelope([])

    mock_iris_client.get.side_effect = get

    result = client.get("/api/iris/security/oauth/overview").json()["result"]

    assert result == {"ServerConfigured": False, "Server": None, "ServerClients": [], "ServerDefinitions": [],
                      "ResourceServers": [], "ResourceMappings": []}


def test_overview_failed_parts_are_warnings_not_guesses(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(
        failing={"/v2/security/oauth2/server", "/v2/security/oauth2/resource-servers",
                 "/v2/security/oauth2/client/client-configurations"}
    )

    body = client.get("/api/iris/security/oauth/overview").json()

    result = body["result"]
    assert result["ServerConfigured"] is None and result["Server"] is None
    assert result["ResourceServers"] is None
    assert result["ServerDefinitions"][0]["ClientConfigurations"] is None
    assert result["ServerClients"] is not None
    areas = sorted(error["area"] for error in body["status"]["errors"])
    assert areas == ["authorization server", "client configurations for server definition 1", "resource servers"]
    assert body["status"]["summary"] == "3 OAuth 2.0 areas unavailable"


def test_overview_connection_failure_everywhere_is_still_a_response(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    body = client.get("/api/iris/security/oauth/overview").json()

    assert all(body["result"][key] is None for key in body["result"])
    assert len(body["status"]["errors"]) >= 5


def test_unexpected_types_become_not_reported(client: TestClient, mock_iris_client: AsyncMock) -> None:
    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/v2/security/oauth2/server":
            return envelope({"IssuerEndpoint": {"nested": SENTINEL}, "AccessTokenInterval": True,
                             "CustomizationRoles": [SENTINEL + "-role", {"x": SENTINEL}], "Metadata": "not-an-object"})
        return envelope([])

    mock_iris_client.get.side_effect = get

    response = client.get("/api/iris/security/oauth/overview")
    server = response.json()["result"]["Server"]

    assert server["IssuerEndpoint"] is None
    assert server["AccessTokenInterval"] is None
    assert server["Metadata"] is None
    assert server["CustomizationRoles"] == [SENTINEL + "-role"]  # strings only; the nested object is dropped
    assert '{"x"' not in response.text


# --- detail routes ---


@pytest.mark.parametrize(
    ("path", "params", "expected_subset"),
    [
        ("/oauth/server-clients/detail", {"clientId": "portal-client-id"},
         {"Name": "Portal", "ClientCredentials": "PortalCert"}),
        ("/oauth/server-definitions/detail", {"serverId": "1"}, {"IssuerEndpoint": "https://idp.example.test"}),
        ("/oauth/client-configurations/detail", {"applicationName": "PortalApp"},
         {"OAuth2ServerDefinition": "1", "Enabled": True}),
        ("/oauth/resource-servers/detail", {"name": "ApiResource"},
         {"ClientId": "api-resource-client", "IntrospectionAuthMethod": "client_secret_basic"}),
    ],
)
def test_detail_routes_are_allowlisted(
    client: TestClient, iris: AsyncMock, path: str, params: dict[str, str], expected_subset: dict[str, Any]
) -> None:
    response = client.get(f"/api/iris/security{path}", params=params)

    assert response.status_code == 200
    assert_no_secrets(response.text)
    result = response.json()["result"]
    for key, value in expected_subset.items():
        assert result[key] == value
    assert_only_gets(iris)


def test_client_metadata_is_allowlisted(client: TestClient, iris: AsyncMock) -> None:
    result = client.get("/api/iris/security/oauth/server-clients/detail",
                        params={"clientId": "portal-client-id"}).json()["result"]

    assert result["Metadata"]["client_name"] == "Portal"
    assert result["Metadata"]["grant_types"] == ["authorization_code"]
    assert "contacts" not in result["Metadata"]


@pytest.mark.parametrize(
    ("path", "param", "message"),
    [
        ("/oauth/server-clients/detail", "clientId", "IRIS reports no OAuth 2.0 client with this id"),
        ("/oauth/server-definitions/detail", "serverId", "IRIS reports no OAuth 2.0 server definition with this id"),
        ("/oauth/client-configurations/detail", "applicationName",
         "IRIS reports no OAuth 2.0 client configuration with this name"),
        ("/oauth/resource-servers/detail", "name", "IRIS reports no OAuth 2.0 resource server with this name"),
    ],
)
def test_detail_unknown_is_404_and_param_required(
    client: TestClient, iris: AsyncMock, path: str, param: str, message: str
) -> None:
    response = client.get(f"/api/iris/security{path}", params={param: "nope"})
    assert response.status_code == 404
    assert response.json()["detail"] == message
    assert client.get(f"/api/iris/security{path}").status_code == 422


# --- the three existing /security/oauth2/* routes, now allowlisted ---


def test_existing_oauth2_routes_drop_secret_fields(client: TestClient, iris: AsyncMock) -> None:
    for path in ("/api/iris/security/oauth2/server", "/api/iris/security/oauth2/server/clients",
                 "/api/iris/security/oauth2/client/server-definitions"):
        response = client.get(path)
        assert response.status_code == 200
        assert_no_secrets(response.text)
    server = client.get("/api/iris/security/oauth2/server").json()["result"]
    assert server["IssuerEndpoint"] == "https://iris.example.test/oauth2"
    clients = client.get("/api/iris/security/oauth2/server/clients").json()["result"]
    assert clients[0]["ClientId"] == "portal-client-id"
    assert_only_gets(iris)


# --- GET-only guarantees ---


def test_oauth_routes_are_registered_as_get_only() -> None:
    paths = app.openapi()["paths"]
    oauth_paths = {path: ops for path, ops in paths.items() if path.startswith("/api/iris/security/oauth")}
    assert set(oauth_paths) == {
        "/api/iris/security/oauth/overview",
        "/api/iris/security/oauth/server-clients/detail",
        "/api/iris/security/oauth/server-definitions/detail",
        "/api/iris/security/oauth/client-configurations/detail",
        "/api/iris/security/oauth/resource-servers/detail",
        "/api/iris/security/oauth2/server",
        "/api/iris/security/oauth2/server/clients",
        "/api/iris/security/oauth2/client/server-definitions",
    }
    for ops in oauth_paths.values():
        assert set(ops) == {"get"}


def test_security_route_module_never_calls_a_mutating_method() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "routes" / "security_access.py").read_text(encoding="utf-8")
    for forbidden in ("client.put", "client.post", "client.delete"):
        assert forbidden not in source
