"""Tests for GET /api/iris/web-apps/rest-endpoints?name=<Name> (the REST
Endpoints tab) and for IRISClient.get_mgmnt().

No real IRIS calls. The canned bodies are copied from real /api/mgmnt/
responses (the /api/iknow description is trimmed).
"""

import time
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.iris_auth import IRISSession
from app.config import Settings
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

_UNEXPECTED = {"description": "(Unexpected Error)"}
_EXPECTED = {"description": "(Expected Result)"}

# GET /api/mgmnt/ (a few of the real entries).
REST_APPS: list[dict[str, Any]] = [
    {
        "name": "/api/monitor",
        "dispatchClass": "%Api.Monitor",
        "namespace": "%SYS",
        "swaggerSpec": "/api/mgmnt/v1/%25SYS/spec/api/monitor",
        "enabled": True,
    },
    {
        "name": "/api/iknow",
        "dispatchClass": "%Api.iKnow",
        "namespace": "%SYS",
        "swaggerSpec": "/api/mgmnt/v1/%25SYS/spec/api/iknow",
        "enabled": True,
    },
    {
        "name": "/api/interop-editors",
        "dispatchClass": "%Api.InteropEditors",
        "namespace": "%SYS",
        "swaggerSpec": "/api/mgmnt/v1/%25SYS/spec/api/interop-editors",
        "enabled": True,
    },
]

MONITOR_SPEC: dict[str, Any] = {
    "basePath": "/api/monitor",
    "paths": {
        "/metrics": {
            "get": {
                "description": " Collect the system metrics and send them to the client in Prometheus Exposition Format. ",
                "x-ISC_ServiceMethod": "metrics",
                "operationId": "metrics",
                "responses": {"default": _UNEXPECTED, "200": _EXPECTED},
            }
        },
        "/interop/interfaces/year/{number}": {
            "get": {
                "parameters": [{"name": "number", "in": "path", "required": True, "type": "string"}],
                "x-ISC_ServiceMethod": "interfacesByYear",
                "operationId": "interfacesByYear",
                "responses": {"default": _UNEXPECTED, "200": _EXPECTED},
            }
        },
    },
    "info": {"title": "", "description": "", "version": "", "x-ISC_Namespace": "%SYS"},
    "swagger": "2.0",
}

IKNOW_SPEC: dict[str, Any] = {
    "basePath": "/api/iknow",
    "parameters": {
        "namespace": {"name": "namespace", "in": "path", "description": "", "required": True, "type": "string"}
    },
    "paths": {
        "/v1/{namespace}/domain/{domain}/entities": {
            "get": {
                "summary": " Entities ",
                "parameters": [
                    {"name": "domain", "in": "path", "required": True, "type": "string"},
                    {"$ref": "#/parameters/namespace"},
                ],
                "x-ISC_ServiceMethod": "GetEntitiesGET",
                "operationId": "GetEntitiesGET",
                "responses": {"default": _UNEXPECTED, "200": _EXPECTED},
            },
            "post": {
                "parameters": [
                    {"name": "domain", "in": "path", "required": True, "type": "string"},
                    {
                        "name": "payloadBody",
                        "in": "body",
                        "description": "Request body contents",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                    {"$ref": "#/parameters/namespace"},
                ],
                "x-ISC_ServiceMethod": "GetEntities",
                "operationId": "GetEntities",
                "responses": {"default": _UNEXPECTED, "200": _EXPECTED},
            },
        }
    },
    "info": {"title": "", "description": "", "version": "", "x-ISC_Namespace": "%SYS"},
    "swagger": "2.0",
}


def _mgmnt(responses: dict[str, Any]) -> AsyncMock:
    """Fake get_mgmnt that answers by path; Exception values are raised."""

    async def fake(path: str) -> Any:
        value = responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    return AsyncMock(side_effect=fake)


# --- Route ---


def test_rest_endpoints_success(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get_mgmnt = _mgmnt(
        {"/": REST_APPS, "/v1/%25SYS/spec/api/monitor": MONITOR_SPEC}
    )

    response = client.get("/api/iris/web-apps/rest-endpoints", params={"name": "/api/monitor"})

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["name"] == "/api/monitor"
    assert result["namespace"] == "%SYS"
    assert result["dispatchClass"] == "%Api.Monitor"
    assert result["enabled"] is True
    assert result["basePath"] == "/api/monitor"
    assert result["swagger"] == "2.0"
    assert [(e["method"], e["path"], e["serviceMethod"]) for e in result["endpoints"]] == [
        ("GET", "/metrics", "metrics"),
        ("GET", "/interop/interfaces/year/{number}", "interfacesByYear"),
    ]
    assert result["endpoints"][1]["parameters"] == [
        {
            "name": "number",
            "location": "path",
            "required": True,
            "type": "string",
            "description": None,
            "pattern": None,
            "bodySchema": None,
            "ref": None,
        }
    ]
    # The spec URL uses IRIS's own namespace, same as the swaggerSpec it
    # advertises for this app.
    assert [c.args[0] for c in mock_iris_client.get_mgmnt.await_args_list] == [
        "/",
        "/v1/%25SYS/spec/api/monitor",
    ]
    mock_iris_client.put.assert_not_called()
    mock_iris_client.post.assert_not_called()


def test_rest_endpoints_resolves_shared_parameter_refs_and_body_schema(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get_mgmnt = _mgmnt(
        {"/": REST_APPS, "/v1/%25SYS/spec/api/iknow": IKNOW_SPEC}
    )

    response = client.get("/api/iris/web-apps/rest-endpoints", params={"name": "/api/iknow"})

    assert response.status_code == 200
    get_op, post_op = response.json()["result"]["endpoints"]
    assert (get_op["method"], post_op["method"]) == ("GET", "POST")
    assert get_op["summary"] == " Entities "
    assert [p["name"] for p in get_op["parameters"]] == ["domain", "namespace"]
    assert get_op["parameters"][1]["location"] == "path"
    assert get_op["parameters"][1]["ref"] is None
    body = post_op["parameters"][1]
    assert body["location"] == "body"
    assert body["bodySchema"] == {"type": "string"}


def test_rest_endpoints_keeps_unresolvable_ref_verbatim(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    spec = {**IKNOW_SPEC, "parameters": {}}
    mock_iris_client.get_mgmnt = _mgmnt({"/": REST_APPS, "/v1/%25SYS/spec/api/iknow": spec})

    response = client.get("/api/iris/web-apps/rest-endpoints", params={"name": "/api/iknow"})

    param = response.json()["result"]["endpoints"][0]["parameters"][1]
    assert param["ref"] == "#/parameters/namespace"
    assert param["name"] is None


def test_rest_endpoints_rejects_app_iris_does_not_list_as_rest(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """A CSP app like /csp/user isn't in IRIS's REST list, so no spec request is made."""
    mock_iris_client.get_mgmnt = _mgmnt({"/": REST_APPS})

    response = client.get("/api/iris/web-apps/rest-endpoints", params={"name": "/csp/user"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS does not list this web application as a REST application"
    assert mock_iris_client.get_mgmnt.await_count == 1


def test_rest_endpoints_reports_when_iris_cannot_generate_a_route_map(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    """/api/interop-editors is a REST app, but IRIS 404s its spec (ERROR #8750)."""
    mock_iris_client.get_mgmnt = _mgmnt(
        {
            "/": REST_APPS,
            "/v1/%25SYS/spec/api/interop-editors": IRISResponseError(404),
        }
    )

    response = client.get(
        "/api/iris/web-apps/rest-endpoints", params={"name": "/api/interop-editors"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "IRIS could not generate a REST route map for this web application"
    )


def test_rest_endpoints_maps_other_iris_errors_safely(
    client: TestClient, mock_iris_client: AsyncMock
) -> None:
    mock_iris_client.get_mgmnt = _mgmnt({"/": IRISConnectionError("boom")})

    response = client.get("/api/iris/web-apps/rest-endpoints", params={"name": "/api/monitor"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


def test_rest_endpoints_requires_name(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get_mgmnt = AsyncMock()

    response = client.get("/api/iris/web-apps/rest-endpoints")

    assert response.status_code == 422
    mock_iris_client.get_mgmnt.assert_not_awaited()


# --- IRISClient.get_mgmnt transport ---


def _make_client(handler) -> IRISClient:
    settings = Settings(
        iris_base_url="http://iris.invalid.test:52773",
        iris_username="test-user",
        iris_password="test-password-not-real",
    )
    client = IRISClient(settings)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._auth._session = IRISSession(
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        sub="test-user",
        exp=time.time() + 3600,
    )
    return client


@pytest.mark.asyncio
async def test_get_mgmnt_uses_basic_auth_get_only_against_api_mgmnt() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=REST_APPS)

    client = _make_client(handler)
    body = await client.get_mgmnt("/")

    assert body == REST_APPS
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == "http://iris.invalid.test:52773/api/mgmnt/"
    expected = httpx.BasicAuth("test-user", "test-password-not-real")._auth_header
    assert request.headers["Authorization"] == expected
    assert "fake-access-token" not in request.headers["Authorization"]


@pytest.mark.parametrize(
    "path",
    [
        "/../admin/v2/web-apps",  # httpx would normalize this to /api/admin/...
        "/v1/%25SYS/spec/../../../admin/info",
        "/%2e%2e/admin/v2/web-apps",  # survives normalization, decodes to ".."
        "/%2E%2e/admin",
        "/v1/./x",
        "@evil.example/x",  # no leading slash: /api/mgmnt@evil...
        ".evil.example/x",
        "",
    ],
)
@pytest.mark.asyncio
async def test_get_mgmnt_refuses_paths_outside_api_mgmnt(path: str) -> None:
    """Basic credentials only go to /api/mgmnt/ on the configured host. Paths
    that escape it are refused before any request is built.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    with pytest.raises(ValueError) as excinfo:
        await client.get_mgmnt(path)

    assert seen == []
    assert "test-password-not-real" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_get_mgmnt_does_not_follow_redirects() -> None:
    """Redirects aren't followed, so the Basic header can't be sent elsewhere."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://evil.example/steal"}, json={})

    client = _make_client(handler)
    await client.get_mgmnt("/")

    assert [str(r.url) for r in seen] == ["http://iris.invalid.test:52773/api/mgmnt/"]


@pytest.mark.asyncio
async def test_jwt_requests_are_unchanged_and_never_carry_basic_auth() -> None:
    """/api/admin requests still only send the Bearer token, never Basic auth."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": {"errors": [], "summary": ""}, "result": []})

    client = _make_client(handler)
    await client.get("/v2/web-apps", params={"maxRows": 5})
    await client.get_mgmnt("/")
    await client.get("/info")

    admin_requests = [r for r in seen if r.url.path.startswith("/api/admin/")]
    assert [r.url.path for r in admin_requests] == ["/api/admin/v2/web-apps", "/api/admin/info"]
    assert admin_requests[0].url.params["maxRows"] == "5"
    for request in admin_requests:
        assert request.headers["Authorization"] == "Bearer fake-access-token"
    (mgmnt_request,) = [r for r in seen if r.url.path.startswith("/api/mgmnt/")]
    assert mgmnt_request.headers["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_get_mgmnt_error_never_carries_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="")

    client = _make_client(handler)
    with pytest.raises(IRISResponseError) as excinfo:
        await client.get_mgmnt("/v1/%25SYS/spec/api/monitor")

    assert excinfo.value.status_code == 401
    assert "test-password-not-real" not in str(excinfo.value)
    assert "test-password-not-real" not in repr(excinfo.value)
