"""Tests for the manual Issue Resolution Rehearsal (IPM) in
app/execution/demo_rehearsal.py and its scenario option on
POST /api/iris/demo/rehearsal. IRIS is a stateful fake; nothing real runs."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_iris_client
from app.execution import demo_rehearsal
from app.iris_client.exceptions import IRISResponseError
from app.main import app
from app.observability import store

OK = {"errors": [], "summary": ""}
IPM_DIR = "/usr/irissys/mgr/zpm/"


class FakeIris:
    def __init__(self) -> None:
        self.mounted = {IPM_DIR: True, "/usr/irissys/mgr/user/": True}
        self.posts: list[tuple[str, Any]] = []
        self.mount_failures = 0  # POST /mount raises this many times

    def _env(self, result: Any) -> dict[str, Any]:
        return {"status": OK, "console": [], "result": result}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/info":
            return self._env({"apiVersion": 2, "username": "_SYSTEM", "serverVersion": "IRIS", "systemMode": "",
                              "product": "iris", "namespaces": [],
                              "privileges": {p: {"use": True} for p in ("Manage", "Operate", "Journal", "Secure", "Task")}})
        if path == "/v2/databases":
            return self._env([
                {"Name": "IPM", "Directory": IPM_DIR, "Server": "", "ClusterMountMode": False, "MountRequired": False,
                 "MountAtStartup": False, "StreamLocation": "", "Status": ""},
                {"Name": "USER", "Directory": "/usr/irissys/mgr/user/", "Server": "", "ClusterMountMode": False,
                 "MountRequired": False, "MountAtStartup": True, "StreamLocation": "", "Status": ""},
            ])
        if path == "/v2/database-dirs":
            return self._env([{"Directory": d, "Size": 17, "MaxSize": "Unlimited", "Mirrored": False, "Encrypted": False,
                               "Status": "Mounted/RW" if m else "Dismounted"} for d, m in self.mounted.items()])
        if path == "/v2/namespaces":
            return self._env([{"Name": "USER", "Globals": "USER", "Routines": "USER"},
                              {"Name": "%SYS", "Globals": "IRISSYS", "Routines": "IRISSYS"}])
        raise AssertionError(f"unexpected GET {path}")

    async def post(self, path: str, json: Any = None, params: Any = None) -> dict[str, Any]:
        self.posts.append((path, params))
        directory = (params or {}).get("dir")
        assert directory == IPM_DIR, "only IPM may ever be dismounted/mounted"
        if path == "/v2/database-dir/dismount":
            self.mounted[directory] = False
        elif path == "/v2/database-dir/mount":
            if self.mount_failures:
                self.mount_failures -= 1
                raise IRISResponseError(500)
            self.mounted[directory] = True
        else:
            raise AssertionError(f"unexpected POST {path}")
        return self._env({})

    async def post_async_task(self, path: str, params: Any = None, json: Any = None) -> str:
        assert path == "/v2/database-dir/info"
        return params["dir"]

    async def wait_for_async_task(self, task_id: str) -> dict[str, Any]:
        return {"Result": {"Mounted": self.mounted[task_id], "Mirrored": False}}


@pytest.fixture(autouse=True)
def _isolation():
    store.clear_traces()
    yield
    store.clear_traces()
    app.dependency_overrides.clear()


@pytest.fixture
def fake() -> FakeIris:
    return FakeIris()


def _post(fake: FakeIris, body: dict[str, Any]) -> Any:
    app.dependency_overrides[get_iris_client] = lambda: fake
    return TestClient(app).post("/api/iris/demo/rehearsal", json=body)


def _steps(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["step"]: s for s in result["steps"]}


def test_full_issue_resolution_flow(fake: FakeIris) -> None:
    response = _post(fake, {"confirmed": True, "scenario": "issue_resolution"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [s["step"] for s in body["steps"]] == [
        "issue.read", "issue.dry_run", "issue.dismount", "issue.detect", "issue.fix", "issue.verify",
    ]
    steps = _steps(body)
    assert all(s["status"] in ("success", "dry_run") for s in body["steps"])
    assert steps["issue.detect"]["detail"].startswith("Command Center Issue: Database IPM")
    assert steps["issue.fix"]["operation_name"] == "database.mount"
    # Only IPM, exactly one dismount then one mount; IPM ends mounted, USER untouched.
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount", "/v2/database-dir/mount"]
    assert fake.mounted == {IPM_DIR: True, "/usr/irissys/mgr/user/": True}
    # Each executed step carries the trace the existing executor recorded.
    recorded = {t.trace_id: t.operation_name for t in store.list_traces()}
    for name, op in (("issue.dry_run", "database.dismount"), ("issue.dismount", "database.dismount"),
                     ("issue.fix", "database.mount")):
        assert recorded[steps[name]["trace_id"]] == op


def test_standard_scenario_is_still_the_default(fake: FakeIris, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def standard(*args: Any, **kwargs: Any):
        called.append("standard")
        return demo_rehearsal.RehearsalResult(status="completed", confirmed=True, detail="x", steps=[])

    monkeypatch.setattr("app.routes.demo.run_rehearsal", standard)
    assert _post(fake, {"confirmed": True}).status_code == 200
    assert called == ["standard"] and fake.posts == []


def test_not_mounted_ipm_stops_before_any_write(fake: FakeIris) -> None:
    fake.mounted[IPM_DIR] = False
    body = _post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json()

    assert body["status"] == "stopped"
    assert fake.posts == []


def test_without_confirmation_nothing_is_dismounted(fake: FakeIris) -> None:
    body = _post(fake, {"confirmed": False, "scenario": "issue_resolution"}).json()

    assert body["status"] == "stopped"
    assert fake.posts == [] and fake.mounted[IPM_DIR] is True


def test_detection_failure_restores_ipm(fake: FakeIris, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_issues(client: Any):
        return SimpleNamespace(issues=[])

    monkeypatch.setattr(demo_rehearsal, "get_issues", no_issues)
    body = _post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json()

    assert body["status"] == "stopped"
    assert _steps(body)["issue.detect"]["status"] == "failed"
    assert _steps(body)["issue.restore"]["status"] == "success"
    assert fake.mounted[IPM_DIR] is True


def test_fix_failure_restores_ipm(fake: FakeIris) -> None:
    fake.mount_failures = 1  # the fix's mount fails once; the restore mount succeeds
    body = _post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json()

    assert body["status"] == "stopped"
    assert _steps(body)["issue.fix"]["status"] == "failed"
    assert _steps(body)["issue.restore"]["status"] == "success"
    assert fake.mounted[IPM_DIR] is True


def test_failed_restore_is_reported(fake: FakeIris) -> None:
    fake.mount_failures = 2  # both the fix and the restore fail
    body = _post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json()

    assert body["status"] == "restore_failed"
    assert "RESTORATION FAILED" in _steps(body)["issue.restore"]["detail"]


@pytest.mark.asyncio
async def test_shares_the_rehearsal_lock(fake: FakeIris) -> None:
    async with demo_rehearsal._rehearsal_lock:
        with pytest.raises(demo_rehearsal.RehearsalInProgressError):
            await demo_rehearsal.run_issue_resolution_rehearsal(fake, frozenset(), True)
    assert fake.posts == []


@pytest.mark.asyncio
async def test_cancellation_after_dismount_still_remounts_ipm(
    fake: FakeIris, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Detection blocks until the task is cancelled — i.e. cancellation arrives
    # after IPM has really been dismounted.
    reached_detection = asyncio.Event()

    async def blocking_detection(client: Any):
        reached_detection.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(demo_rehearsal, "get_issues", blocking_detection)
    task = asyncio.create_task(demo_rehearsal.run_issue_resolution_rehearsal(fake, frozenset({"Operate"}), True))
    await asyncio.wait_for(reached_detection.wait(), timeout=2)
    assert fake.mounted[IPM_DIR] is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.mounted[IPM_DIR] is True  # the remount ran before cancellation propagated
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount", "/v2/database-dir/mount"]
    assert not demo_rehearsal._rehearsal_lock.locked()


def test_unknown_scenario_is_rejected(fake: FakeIris) -> None:
    assert _post(fake, {"confirmed": True, "scenario": "anything"}).status_code == 422
