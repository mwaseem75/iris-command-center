"""Tests for the manual Issue Resolution Rehearsal (IPM) and its scenario
option on POST /api/iris/demo/rehearsal. IRIS is a fake that keeps state.
"""

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
from app.routes.issues import get_issues

OK = {"errors": [], "summary": ""}
IPM_DIR = "/usr/irissys/mgr/zpm/"


class FakeIris:
    def __init__(self) -> None:
        self.mounted = {IPM_DIR: True, "/usr/irissys/mgr/user/": True}
        self.posts: list[tuple[str, Any]] = []
        self.mount_failures = 0  # POST /mount raises this many times
        self.namespaces = [("USER", "USER"), ("%SYS", "IRISSYS")]

    @staticmethod
    def _ns(name: str, db: str) -> dict[str, Any]:
        return {"Name": name, "Globals": db, "Routines": db, "SysGlobals": "IRISSYS", "SysRoutines": "IRISSYS",
                "Library": "IRISLIB", "TempGlobals": "IRISTEMP"}

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
            return self._env([self._ns(name, db) for name, db in self.namespaces])
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
    # Only IPM: one dismount, then one mount. IPM ends up mounted, USER untouched.
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount", "/v2/database-dir/mount"]
    assert fake.mounted == {IPM_DIR: True, "/usr/irissys/mgr/user/": True}
    # Each executed step has its trace id.
    recorded = {t.trace_id: t.operation_name for t in store.list_traces()}
    for name, op in (("issue.dry_run", "database.dismount"), ("issue.dismount", "database.dismount"),
                     ("issue.fix", "database.mount")):
        assert recorded[steps[name]["trace_id"]] == op


def test_only_the_fix_trace_is_labelled_as_an_issue_resolution(fake: FakeIris) -> None:
    steps = _steps(_post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json())
    traces = {t.trace_id: t for t in store.list_traces()}

    fix = traces[steps["issue.fix"]["trace_id"]]
    assert fix.resolution is not None
    assert fix.resolution.issue_type == "database_dismounted"
    assert fix.resolution.issue_title == "Dismounted database"
    assert fix.resolution.resource == IPM_DIR
    # Creating the issue (the dismount) is not part of a resolution.
    for name in ("issue.dry_run", "issue.dismount"):
        assert traces[steps[name]["trace_id"]].resolution is None


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
    # Detection blocks until the task is cancelled, so the cancel arrives
    # after IPM was actually dismounted.
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

    assert fake.mounted[IPM_DIR] is True  # the remount ran before the cancel propagated
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount", "/v2/database-dir/mount"]
    assert not demo_rehearsal._rehearsal_lock.locked()


def test_unknown_scenario_is_rejected(fake: FakeIris) -> None:
    assert _post(fake, {"confirmed": True, "scenario": "anything"}).status_code == 422


def test_detected_issue_lists_namespaces_that_depend_on_ipm(fake: FakeIris) -> None:
    fake.namespaces.append(("IPMAPP", "IPM"))

    body = _post(fake, {"confirmed": True, "scenario": "issue_resolution"}).json()

    assert body["status"] == "completed"
    steps = _steps(body)
    assert "Namespaces that depend on it: IPMAPP (Globals, Routines)." in steps["issue.detect"]["detail"]
    # The resolution itself is unchanged: one dismount, then one mount of IPM.
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount", "/v2/database-dir/mount"]
    assert fake.mounted[IPM_DIR] is True


# --- Two-step demo: Create Demo Issue, then Resolve Demo Issue ---


def test_create_dismounts_ipm_verifies_and_leaves_the_issue_active(fake: FakeIris) -> None:
    body = _post(fake, {"confirmed": True, "scenario": "issue_create"}).json()

    assert body["status"] == "completed"
    assert "stays active" in body["detail"]
    assert [s["step"] for s in body["steps"]] == [
        "issue.read", "issue.dry_run", "issue.dismount", "issue.confirm_dismounted",
    ]
    assert all(s["status"] in ("success", "dry_run") for s in body["steps"])
    # Only the dismount was sent, and IPM is left dismounted on purpose.
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/dismount"]
    assert fake.mounted == {IPM_DIR: False, "/usr/irissys/mgr/user/": True}
    # The real issue is now active in the issue detection (GET /api/iris/issues).
    issues = asyncio.run(get_issues(fake)).issues
    assert [(i.kind, i.database) for i in issues] == [("database_dismounted", "IPM")]


def test_resolve_mounts_ipm_with_the_recommended_operation_and_verifies(fake: FakeIris) -> None:
    _post(fake, {"confirmed": True, "scenario": "issue_create"})
    fake.posts.clear()

    body = _post(fake, {"confirmed": True, "scenario": "issue_resolve"}).json()

    assert body["status"] == "completed"
    assert [s["step"] for s in body["steps"]] == ["issue.check", "issue.detect", "issue.fix", "issue.verify"]
    steps = _steps(body)
    assert steps["issue.fix"]["operation_name"] == "database.mount"
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/mount"]
    assert fake.mounted[IPM_DIR] is True
    fix = {t.trace_id: t for t in store.list_traces()}[steps["issue.fix"]["trace_id"]]
    assert fix.resolution is not None and fix.resolution.issue_type == "database_dismounted"


def test_resolve_without_an_active_issue_changes_nothing(fake: FakeIris) -> None:
    body = _post(fake, {"confirmed": True, "scenario": "issue_resolve"}).json()

    assert body["status"] == "stopped"
    assert _steps(body)["issue.check"]["status"] == "failed"
    assert fake.posts == [] and fake.mounted[IPM_DIR] is True


def test_create_remounts_ipm_if_it_is_not_reported_dismounted(
    fake: FakeIris, monkeypatch: pytest.MonkeyPatch
) -> None:
    # database.dismount's own verification passes, but the storage list
    # still reports IPM mounted: the Create check fails and IPM is restored.
    original_get = fake.get

    async def stale_storage_list(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await original_get(path, params)
        if path == "/v2/database-dirs" and fake.posts:
            for entry in response["result"]:
                entry["Status"] = "Mounted/RW"
        return response

    monkeypatch.setattr(fake, "get", stale_storage_list)
    body = _post(fake, {"confirmed": True, "scenario": "issue_create"}).json()

    assert body["status"] == "stopped"
    steps = _steps(body)
    assert steps["issue.dismount"]["status"] == "success"
    assert steps["issue.confirm_dismounted"]["status"] == "failed"
    assert "issue.restore" in steps  # the remount safety net ran


def test_failed_resolve_leaves_the_issue_active_and_says_so(fake: FakeIris) -> None:
    _post(fake, {"confirmed": True, "scenario": "issue_create"})
    fake.posts.clear()
    fake.mount_failures = 1

    body = _post(fake, {"confirmed": True, "scenario": "issue_resolve"}).json()

    assert body["status"] == "stopped"
    assert _steps(body)["issue.fix"]["status"] == "failed"
    assert "may still be active" in body["detail"]
    assert "issue.restore" not in _steps(body)  # no automatic retry: IPM stays as it was
    assert [p[0] for p in fake.posts] == ["/v2/database-dir/mount"]
    assert fake.mounted[IPM_DIR] is False


@pytest.mark.parametrize("scenario", ["issue_create", "issue_resolve"])
def test_two_step_scenarios_need_confirmation(fake: FakeIris, scenario: str) -> None:
    if scenario == "issue_resolve":
        fake.mounted[IPM_DIR] = False  # an active demo issue
    body = _post(fake, {"confirmed": False, "scenario": scenario}).json()

    assert body["status"] == "stopped"
    assert fake.posts == []


@pytest.mark.asyncio
async def test_two_step_scenarios_share_the_rehearsal_lock(fake: FakeIris) -> None:
    async with demo_rehearsal._rehearsal_lock:
        for step in ("create", "resolve"):
            with pytest.raises(demo_rehearsal.RehearsalInProgressError):
                await demo_rehearsal.run_issue_resolution_rehearsal(fake, frozenset(), True, step=step)
    assert fake.posts == []
