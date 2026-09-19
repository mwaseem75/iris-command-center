"""Direct unit tests for IRISClient's async-task helpers (post_async_task,
wait_for_async_task), added for the Logs/Investigation view's audit-records
route (see docs/api-capability-matrix.md's "POST /v2/security/audit/records"
entry for what these fake responses are modeled on).

Unlike every other IRISClient method, these are tested directly here with a
fake httpx transport, rather than only via a fully-mocked IRISClient in
route tests (see test_iris_routes_step3.py) — a route-level mock replaces
IRISClient entirely, so it would never actually exercise this file's new
Location-header parsing, terminal-state detection, or polling logic. No real
network call is made anywhere in this file.
"""

import time

import httpx
import pytest

from app.auth.iris_auth import IRISSession
from app.config import Settings
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISAsyncTaskError


def _make_client(handler) -> IRISClient:
    settings = Settings(
        iris_base_url="http://iris.invalid.test:52773",
        iris_username="test-user",
        iris_password="test-password-not-real",
    )
    client = IRISClient(settings)
    # Real network is never touched: the httpx transport is swapped for a
    # fake one, and a pre-populated, non-expired session skips the real
    # login call entirely.
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._auth._session = IRISSession(
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        sub="test-user",
        exp=time.time() + 3600,
    )
    return client


@pytest.mark.asyncio
async def test_post_async_task_extracts_id_from_location_header() -> None:
    # The real Location path observed against icc-iris-dev used "v1", not
    # "v2" (see docs/api-capability-matrix.md) — post_async_task must not
    # assume/require any particular path, only the "id" query parameter.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.params["ascending"] == "0"
        return httpx.Response(
            202,
            headers={"Location": "/api/admin/v1/async-result?id=030002872038736621054186"},
            json={"status": {"errors": [], "summary": ""}, "console": [], "result": {}},
        )

    client = _make_client(handler)
    task_id = await client.post_async_task("/v2/security/audit/records", params={"ascending": 0})
    assert task_id == "030002872038736621054186"


@pytest.mark.asyncio
async def test_post_async_task_raises_when_no_location_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202, json={"status": {"errors": [], "summary": ""}, "console": [], "result": {}}
        )

    client = _make_client(handler)
    with pytest.raises(IRISAsyncTaskError):
        await client.post_async_task("/v2/security/audit/records")


@pytest.mark.asyncio
async def test_post_async_task_raises_when_location_has_no_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"Location": "/api/admin/v1/async-result"},
            json={"status": {"errors": [], "summary": ""}, "console": [], "result": {}},
        )

    client = _make_client(handler)
    with pytest.raises(IRISAsyncTaskError):
        await client.post_async_task("/v2/security/audit/records")


@pytest.mark.asyncio
async def test_wait_for_async_task_polls_until_finished() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        state = "Running" if calls["count"] < 3 else "Finished"
        result = [{"SystemID": "3158de9e5dc1:IRIS", "AuditIndex": 1}] if state == "Finished" else []
        return httpx.Response(
            200,
            json={
                "status": {"errors": [], "summary": ""},
                "console": [],
                "result": {
                    "State": state,
                    "TaskName": "POST /v2/security/audit/records",
                    "Console": [],
                    "FailureReason": "",
                    "Result": result,
                },
            },
        )

    client = _make_client(handler)
    task = await client.wait_for_async_task("some-task-id", poll_interval_seconds=0)
    assert task["State"] == "Finished"
    assert task["Result"] == [{"SystemID": "3158de9e5dc1:IRIS", "AuditIndex": 1}]
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_wait_for_async_task_raises_on_failed_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": {"errors": [], "summary": ""},
                "console": [],
                "result": {
                    "State": "Failed",
                    "TaskName": "POST /v2/security/audit/records",
                    "Console": [],
                    "FailureReason": "something went wrong",
                },
            },
        )

    client = _make_client(handler)
    with pytest.raises(IRISAsyncTaskError) as exc_info:
        await client.wait_for_async_task("some-task-id", poll_interval_seconds=0)
    assert exc_info.value.state == "Failed"


@pytest.mark.asyncio
async def test_wait_for_async_task_raises_after_max_attempts_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": {"errors": [], "summary": ""},
                "console": [],
                "result": {
                    "State": "Running",
                    "TaskName": "POST /v2/security/audit/records",
                    "Console": [],
                    "FailureReason": "",
                },
            },
        )

    client = _make_client(handler)
    with pytest.raises(IRISAsyncTaskError) as exc_info:
        await client.wait_for_async_task("some-task-id", max_attempts=2, poll_interval_seconds=0)
    assert exc_info.value.state == "Running"
