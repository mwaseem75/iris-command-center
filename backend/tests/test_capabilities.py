"""Tests for the API Capability Explorer's backend route
(GET /api/iris/capabilities) and its underlying registry
(app/capabilities.py).

No IRIS call is possible from this route — it serves a static,
project-maintained registry — so these tests use the real FastAPI app
directly (via the shared `client` fixture) rather than mocking IRIS.
"""

from fastapi.testclient import TestClient

from app.capabilities import CAPABILITY_REGISTRY
from app.main import app as fastapi_app


def test_list_capabilities_returns_every_registry_entry(client: TestClient) -> None:
    response = client.get("/api/iris/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert len(body["capabilities"]) == len(CAPABILITY_REGISTRY)


def test_list_capabilities_includes_expected_fields(client: TestClient) -> None:
    response = client.get("/api/iris/capabilities")

    entries = {c["capability"]: c for c in response.json()["capabilities"]}
    namespaces_entry = entries["View a list of namespaces"]
    assert namespaces_entry["endpoint"] == "/api/admin/v2/namespaces"
    assert namespaces_entry["method"] == "GET"
    assert namespaces_entry["required_privilege"] == "%Admin_Manage:U"
    assert namespaces_entry["verification_status"] == "Verified"
    assert namespaces_entry["command_center_path"] == "/api/iris/namespaces"


def test_list_capabilities_marks_wired_up_routes_available(client: TestClient) -> None:
    response = client.get("/api/iris/capabilities")

    entries = {c["capability"]: c for c in response.json()["capabilities"]}
    assert entries["View a list of namespaces"]["available"] is True
    assert entries["List wallet collections"]["available"] is True


def test_list_capabilities_marks_internal_only_iris_calls_unavailable(
    client: TestClient,
) -> None:
    response = client.get("/api/iris/capabilities")

    entries = {c["capability"]: c for c in response.json()["capabilities"]}
    # Used internally by app/auth/iris_auth.py and app/iris_client/client.py's
    # wait_for_async_task respectively — never exposed as their own routes.
    assert entries["Authenticate and obtain JWT access/refresh tokens"]["available"] is False
    assert (
        entries["View the status/result of an async task started by another operation"][
            "available"
        ]
        is False
    )


def test_list_capabilities_marks_untested_catch_all_entry_unavailable_and_not_tested(
    client: TestClient,
) -> None:
    response = client.get("/api/iris/capabilities")

    entries = {c["capability"]: c for c in response.json()["capabilities"]}
    catch_all = entries["All other documented IRIS SysAdmin REST API capabilities"]
    assert catch_all["verification_status"] == "Not tested"
    assert catch_all["available"] is False


def test_capability_registry_command_center_paths_are_real_registered_routes() -> None:
    """Guards against registry drift: every entry that CLAIMS to be backed
    by a Command Center route must actually be one, checked against the
    live app's own OpenAPI schema — never hand-duplicated or assumed."""
    registered_paths = fastapi_app.openapi()["paths"]

    for entry in CAPABILITY_REGISTRY:
        if entry.command_center_path is None:
            continue
        assert entry.command_center_path in registered_paths, (
            f"{entry.capability!r} claims command_center_path="
            f"{entry.command_center_path!r}, which is not a real registered route"
        )
        assert entry.command_center_method is not None
        assert entry.command_center_method.lower() in registered_paths[entry.command_center_path]
