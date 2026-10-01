"""Phase 4A step 3: the instance compatibility handshake.

All HTTP goes to a fake IRIS through httpx.MockTransport; it mirrors what the
live IRIS 2026.2 primary answered (401 without credentials, JSON 404 for an
unconfigured feature, HTML 404 for an unknown route, Basic auth on /api/mgmnt).
"""

import base64
import json
import logging
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from app.capabilities import CAPABILITY_REGISTRY
from app.instances.credentials import CredentialStoreError
from app.instances.handshake import REQUIRED_ENDPOINTS, check_connection, check_instance
from app.instances.models import InstanceCheckStatus
from app.instances.registry import InstanceRegistry, primary_from_settings
from tests.test_instances_registry import _FakePersister, _settings

CANARY = "Pw-HANDSHAKE-CANARY-7c1d-not-real!"
BASE_URL = "http://iris-2:52773"
_RealAsyncClient = httpx.AsyncClient
_HTML_404 = {"status_code": 404, "text": "<HTML><HEAD><TITLE>Not Found</TITLE></HEAD></HTML>",
             "headers": {"content-type": "text/html; charset=UTF-8"}}


def _envelope(result, errors=None) -> dict:
    return {"status": {"errors": errors or [], "summary": ""}, "console": [], "result": result}


class FakeIRIS:
    def __init__(self, *, user="ops", password=CANARY, product="iris", api_version=2, info=None, admin_api=True,
                 missing=(), forbidden=(), mgmnt=True, unreachable=False, crash_on=None, atelier_version=None):
        self.user, self.password, self.product = user, password, product
        self.api_version, self.info = api_version, info
        self.admin_api, self.missing, self.forbidden = admin_api, set(missing), set(forbidden)
        self.mgmnt, self.unreachable, self.crash_on = mgmnt, unreachable, crash_on
        self.atelier_version = atelier_version  # None: no /api/atelier either
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == self.crash_on:
            raise RuntimeError(f"unexpected failure {CANARY}")
        if path.startswith("/api/mgmnt"):
            expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            if not self.mgmnt or request.headers.get("authorization") != expected:
                return httpx.Response(**_HTML_404)
            return httpx.Response(200, json=[{"name": "/api/admin"}])
        if path.startswith("/api/atelier"):
            # Shape seen on the live primary: 401 without/with wrong Basic auth, else
            # {"status", "console", "result": {"content": {"version", "id", "api", ...}}}.
            if self.atelier_version is None:
                return httpx.Response(**_HTML_404)
            expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            if request.headers.get("authorization") != expected:
                return httpx.Response(401, text="", headers={"content-type": "text/html"})
            return httpx.Response(200, json=_envelope({"content": {
                "version": self.atelier_version, "id": "X", "api": 8, "features": [], "namespaces": ["USER"]}}))
        if not self.admin_api:
            return httpx.Response(**_HTML_404)
        if path == "/api/admin/login":
            body = json.loads(request.content)
            if body != {"user": self.user, "password": self.password}:
                return httpx.Response(401, text="", headers={"content-type": "text/html"})
            return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref", "sub": "ops",
                                             "exp": 9_999_999_999})
        if request.headers.get("authorization") != "Bearer tok":
            return httpx.Response(401, text="", headers={"content-type": "text/html"})
        sub = path.removeprefix("/api/admin")
        if sub == "/info":
            return httpx.Response(200, json=self.info or _envelope({
                "apiVersion": self.api_version, "username": "ops", "serverVersion": "IRIS 2026.2 (Build 221U)",
                "systemMode": "", "product": self.product, "namespaces": [], "privileges": {},
            }))
        if sub in self.missing:
            return httpx.Response(**_HTML_404)
        if sub in self.forbidden:
            return httpx.Response(403, json=_envelope({}, [{"error": "ERROR #822: Access Denied", "code": 822}]))
        if sub == "/v2/security/oauth2/server":  # existing route, feature not configured
            return httpx.Response(404, json=_envelope({}, [{"error": "ERROR #8864: OAuth 2.0 server is not configured.",
                                                              "code": 8864}]))
        return httpx.Response(200, json=_envelope([]))


@pytest.fixture
def iris(monkeypatch: pytest.MonkeyPatch):
    """Route every httpx.AsyncClient (IRISClient's and the probe's) to a FakeIRIS."""
    state = {"fake": FakeIRIS()}
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: _RealAsyncClient(transport=httpx.MockTransport(lambda r: state["fake"](r))),
    )

    def use(**options) -> FakeIRIS:
        state["fake"] = FakeIRIS(**options)
        return state["fake"]

    return use


async def _check(password: str = CANARY):
    return await check_connection(
        base_url=BASE_URL, username="ops", password=SecretStr(password), namespace="USER", settings=_settings()
    )


# --- required endpoints come from the capability matrix ---


def test_required_endpoints_are_derived_from_the_capability_matrix() -> None:
    verified = {
        c.endpoint.removeprefix("/api/admin") for c in CAPABILITY_REGISTRY
        if c.verification_status == "Verified" and c.method == "GET" and c.command_center_path
        and c.endpoint.startswith("/api/admin/v2/")
    }
    assert set(REQUIRED_ENDPOINTS) == verified
    assert len(REQUIRED_ENDPOINTS) == 13
    assert "/v2/async-result" not in REQUIRED_ENDPOINTS  # needs a parameter
    assert all(p.startswith("/v2/") for p in REQUIRED_ENDPOINTS)


# --- outcomes ---


@pytest.mark.asyncio
async def test_compatible_instance(iris) -> None:
    fake = iris()

    check = await _check()

    assert check.status is InstanceCheckStatus.COMPATIBLE
    assert (check.product, check.server_version, check.api_version, check.username) == (
        "iris", "IRIS 2026.2 (Build 221U)", 2, "ops",
    )
    assert check.endpoints_ok == list(REQUIRED_ENDPOINTS)  # the unconfigured OAuth2 server counts
    assert check.endpoints_missing == []
    assert check.mgmnt_api_available is True
    assert (check.failure, check.detail) == (None, None)
    assert {r.url.host for r in fake.requests} == {"iris-2"}  # only the instance itself


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
@pytest.mark.asyncio
async def test_unreachable_instance(iris, monkeypatch, error) -> None:
    def refuse(request):
        raise error("no route", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _RealAsyncClient(transport=httpx.MockTransport(refuse)))

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.UNREACHABLE, "unreachable")
    assert check.product is None and check.endpoints_ok == []


@pytest.mark.asyncio
async def test_server_without_the_admin_api_is_incompatible_before_any_login(iris) -> None:
    fake = iris(admin_api=False)

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.INCOMPATIBLE, "admin_api_unavailable")
    assert check.detail == ("The IRIS System Administration API (/api/admin) is not available on this server. "
                            "Requires IRIS 2026.2 or later.")
    assert check.server_version is None  # no Atelier API either, so no version to report
    assert [r.url.path for r in fake.requests] == ["/api/admin/info", "/api/atelier/"]
    assert "authorization" not in fake.requests[0].headers  # the probe sends no credentials


IRIS_2025_3 = "IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2025.3 (Build 230U) Mon Sep 1 2025 10:00:00 EDT"


@pytest.mark.asyncio
async def test_iris_2025_3_without_the_admin_api_is_incompatible_with_its_version(iris) -> None:
    fake = iris(admin_api=False, atelier_version=IRIS_2025_3)

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.INCOMPATIBLE, "admin_api_unavailable")
    assert check.server_version == IRIS_2025_3
    assert check.detail == ("The IRIS System Administration API (/api/admin) is not available on this server. "
                            "Requires IRIS 2026.2 or later.")
    assert [r.url.path for r in fake.requests] == ["/api/admin/info", "/api/atelier/"]
    assert not any(r.url.path == "/api/admin/login" for r in fake.requests)


@pytest.mark.asyncio
async def test_wrong_password_on_a_server_without_the_admin_api_is_auth_failed(iris) -> None:
    iris(admin_api=False, atelier_version=IRIS_2025_3)

    check = await _check(password="wrong-password")

    assert (check.status, check.failure) == (InstanceCheckStatus.AUTH_FAILED, "auth_failed")
    assert check.server_version is None


@pytest.mark.asyncio
async def test_authentication_failure(iris) -> None:
    iris(password="the-real-password")

    check = await _check(password=CANARY)

    assert (check.status, check.failure) == (InstanceCheckStatus.AUTH_FAILED, "auth_failed")
    assert check.endpoints_ok == [] and check.product is None


@pytest.mark.parametrize(
    ("options", "failure"),
    [
        ({"product": "cache"}, "unexpected_identity"),
        ({"api_version": 1}, "unsupported_api_version"),
        ({"api_version": 3}, "unsupported_api_version"),
        ({"info": _envelope({"product": "iris"})}, "unexpected_identity"),  # unrecognized /info shape
    ],
)
@pytest.mark.asyncio
async def test_incompatible_product_or_api(iris, options, failure) -> None:
    iris(**options)

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.INCOMPATIBLE, failure)
    assert check.endpoints_ok == []  # stops before the endpoint checks


@pytest.mark.asyncio
async def test_identity_is_reported_even_when_incompatible(iris) -> None:
    iris(api_version=1)

    check = await _check()

    assert (check.product, check.api_version, check.username) == ("iris", 1, "ops")


@pytest.mark.parametrize(
    ("missing", "forbidden"),
    [({"/v2/web-apps"}, set()), (set(), {"/v2/processes"}), ({"/v2/tasks"}, {"/v2/journal/settings"})],
)
@pytest.mark.asyncio
async def test_missing_or_forbidden_required_endpoint(iris, missing, forbidden) -> None:
    iris(missing=missing, forbidden=forbidden)

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.INCOMPATIBLE, "endpoints_missing")
    assert set(check.endpoints_missing) == missing | forbidden
    assert set(check.endpoints_ok) == set(REQUIRED_ENDPOINTS) - missing - forbidden
    assert check.product == "iris"


@pytest.mark.asyncio
async def test_management_api_is_optional(iris) -> None:
    iris(mgmnt=False)

    check = await _check()

    assert check.status is InstanceCheckStatus.COMPATIBLE
    assert check.mgmnt_api_available is False


@pytest.mark.asyncio
async def test_unexpected_errors_give_a_generic_result(iris) -> None:
    iris(crash_on="/api/admin/v2/namespaces")

    check = await _check()

    assert (check.status, check.failure) == (InstanceCheckStatus.INCOMPATIBLE, "check_failed")
    assert CANARY not in check.model_dump_json()


# --- credentials are resolved per instance ---


def _store(password: str | None = CANARY) -> MagicMock:
    store = MagicMock()
    if password is None:
        store.read_sync.side_effect = CredentialStoreError("could not be read")
    else:
        store.read_sync.return_value = SecretStr(password)
    return store


def _user_instance(registry: InstanceRegistry):
    return registry.add(
        name="Second", base_url=BASE_URL, username="ops", namespace="APP",
        credential_ref="CommandCenter.iris-0123456789ab",
    )


@pytest.mark.asyncio
async def test_registered_instance_uses_its_wallet_credential_and_own_connection(iris) -> None:
    fake = iris()
    registry = InstanceRegistry(primary_from_settings(_settings()))
    instance = _user_instance(registry)
    store = _store()

    check = await check_instance(instance, _settings(), store)

    assert check.status is InstanceCheckStatus.COMPATIBLE
    store.read_sync.assert_called_once_with("CommandCenter.iris-0123456789ab")
    login = next(r for r in fake.requests if r.url.path == "/api/admin/login")
    assert json.loads(login.content) == {"user": "ops", "password": CANARY}
    assert {r.url.host for r in fake.requests} == {"iris-2"}  # never the Primary's URL


@pytest.mark.asyncio
async def test_primary_uses_the_environment_password(iris) -> None:
    fake = iris(user="_SYSTEM", password="primary-env-password-not-stored")
    store = _store()

    check = await check_instance(primary_from_settings(_settings()), _settings(), store)

    assert check.status is InstanceCheckStatus.COMPATIBLE
    store.read_sync.assert_not_called()
    assert {r.url.host for r in fake.requests} == {"iris"}


@pytest.mark.asyncio
async def test_unreadable_credential_is_auth_failed_without_contacting_the_instance(iris) -> None:
    fake = iris()
    registry = InstanceRegistry(primary_from_settings(_settings()))

    check = await check_instance(_user_instance(registry), _settings(), _store(password=None))

    assert (check.status, check.failure) == (InstanceCheckStatus.AUTH_FAILED, "credential_unavailable")
    assert fake.requests == []


# --- no leaks ---


@pytest.mark.parametrize(
    "options",
    [{}, {"password": "other"}, {"api_version": 1}, {"missing": {"/v2/tasks"}}, {"mgmnt": False},
     {"crash_on": "/api/admin/v2/tasks"}, {"admin_api": False, "atelier_version": "IRIS 2025.3 (Build 230U)"}],
)
@pytest.mark.asyncio
async def test_password_never_appears_in_results_or_logs(iris, caplog, options) -> None:
    caplog.set_level(logging.DEBUG)
    fake = iris(**options)

    check = await _check()

    assert CANARY not in check.model_dump_json() and CANARY not in repr(check)
    assert CANARY not in caplog.text
    # Only the login body and the Basic auth of the Management API and (without
    # /api/admin) the Atelier API carry the password.
    for request in fake.requests:
        auth = request.headers.get("authorization", "")
        basic = base64.b64decode(auth.removeprefix("Basic ")).decode() if auth.startswith("Basic ") else ""
        if CANARY in request.content.decode() or CANARY in basic:
            assert request.url.path in ("/api/admin/login", "/api/mgmnt/", "/api/atelier/")
        assert CANARY not in str(request.url)


# --- a check never changes the instance ---


@pytest.mark.parametrize("options", [{}, {"password": "other"}, {"unreachable": True}, {"missing": {"/v2/tasks"}}])
@pytest.mark.asyncio
async def test_check_does_not_modify_the_instance_or_registry(iris, options) -> None:
    iris(**options)
    persister = _FakePersister()
    registry = InstanceRegistry(primary_from_settings(_settings()), persister)
    instance = _user_instance(registry)
    persister.saved.clear()

    await check_instance(instance, _settings(), _store())

    assert registry.get(instance.id) == instance
    assert registry.get(instance.id).last_check is None
    assert persister.saved == {} and persister.deleted == []
