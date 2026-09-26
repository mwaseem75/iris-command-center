"""Tests for POST /api/iris/demo/rehearsal (app/execution/demo_rehearsal.py).

Uses a fake IRIS client that keeps state, so changes and restores can be
checked against it.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_iris_client
from app.execution import demo_rehearsal
from app.execution.executor import OperationExecutor
from app.iris_client.exceptions import IRISResponseError
from app.main import app
from app.observability import store

_OK = {"errors": [], "summary": ""}
PASSWORD = "test-password-not-real"  # conftest's IRIS_PASSWORD


class FakeIris:
    """Enough of IRISClient for the four handlers and the rehearsal's lookups."""

    def __init__(self) -> None:
        self.privileges = {"Manage": True, "Journal": True, "Secure": True, "Operate": True, "Task": True}
        self.purge_archived = True
        self.web_apps: dict[str, dict[str, Any]] = {
            "/api/admin": {"Type": "CSP", "Description": "admin api", "Enabled": True},
            "/api/mgmnt": {"Type": "CSP", "Description": "mgmnt api", "Enabled": True},
            "/csp/sys": {"Type": "System,CSP", "IsSystemApp": True, "Description": "system", "Enabled": True},
            "/csp/user": {"Type": "CSP", "Description": "User app", "Enabled": True},
        }
        self.database_dirs = [
            {"Directory": "/usr/irissys/mgr/user/", "Status": "Mounted/RW"},
            {"Directory": "/usr/irissys/mgr/demo/", "Status": "Dismounted"},
        ]
        self.mounted = {"/usr/irissys/mgr/user/": True, "/usr/irissys/mgr/demo/": False}
        self.tasks = [
            {"Id": 1, "Name": "Purge Journal", "Type": "System", "Suspended": False},
            {"Id": 42, "Name": "Nightly report", "Type": "User", "Suspended": False},
        ]
        # Fault injection
        self.journal_put_error: int | None = None
        self.web_app_put_errors: list[int | None] = []  # consumed per PUT
        self.flip_enabled_on_next_web_app_put = False
        # Call log
        self.puts: list[tuple[str, Any, Any]] = []
        self.posts: list[tuple[str, Any, Any]] = []
        self.async_tasks: list[tuple[str, Any]] = []

    def _env(self, result: Any) -> dict[str, Any]:
        return {"status": _OK, "console": [], "result": result}

    def _journal(self) -> dict[str, Any]:
        return self._env({
            "AlternateDirectory": "/j2/", "ArchiveName": "", "BackupsBeforePurge": 2,
            "CurrentDirectory": "/j/", "DaysBeforePurge": 2, "FileSizeLimit": 1024,
            "FreezeOnError": False, "JournalFilePrefix": "", "JournalcspSession": False,
            "PurgeArchived": self.purge_archived, "CompressFiles": True, "wijdir": "", "targwijsz": 0,
        })

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/info":
            return self._env({
                "apiVersion": 2, "username": "_SYSTEM", "serverVersion": "IRIS 2026.2", "systemMode": "",
                "product": "iris", "namespaces": [{"name": "USER"}],
                "privileges": {k: {"use": v} for k, v in self.privileges.items()},
            })
        if path == "/v2/journal/settings":
            return self._journal()
        if path == "/v2/web-apps":
            return self._env([{"Name": n, **{k: v for k, v in a.items() if k in ("Type", "IsSystemApp")}}
                              for n, a in self.web_apps.items()])
        if path == "/v2/web-app":
            app_ = self.web_apps.get(params["name"])
            if app_ is None:
                raise IRISResponseError(404)
            return self._env({"Name": params["name"], "Description": app_["Description"],
                              "Enabled": app_["Enabled"], "Password": "must-never-leak"})
        if path == "/v2/database-dirs":
            return self._env(self.database_dirs)
        if path == "/v2/tasks":
            return self._env(self.tasks)
        if path in ("/v2/task/info", "/v2/task"):
            task = next((t for t in self.tasks if t["Id"] == params["id"]), None)
            if task is None:
                raise IRISResponseError(404)
            return self._env({"Name": task["Name"], "Type": task["Type"], "Suspended": task["Suspended"],
                              "Status": "1"})
        if path == "/v2/task/manager":
            return self._env({"Status": "Running"})
        raise AssertionError(f"unexpected GET {path}")

    async def put(self, path: str, json: Any = None, params: Any = None) -> dict[str, Any]:
        self.puts.append((path, json, params))
        if path == "/v2/journal/settings":
            if self.journal_put_error:
                raise IRISResponseError(self.journal_put_error)
            self.purge_archived = json["PurgeArchived"]
            return self._journal()
        if path == "/v2/web-app":
            error = self.web_app_put_errors.pop(0) if self.web_app_put_errors else None
            if error:
                raise IRISResponseError(error)
            app_ = self.web_apps[params["name"]]
            app_["Description"] = json["Description"]
            if self.flip_enabled_on_next_web_app_put:
                self.flip_enabled_on_next_web_app_put = False
                app_["Enabled"] = not app_["Enabled"]
            return self._env({})
        raise AssertionError(f"unexpected PUT {path}")

    async def post(self, path: str, json: Any = None, params: Any = None) -> dict[str, Any]:
        self.posts.append((path, json, params))
        raise AssertionError(f"a rehearsal must never POST ({path})")

    async def post_async_task(self, path: str, params: Any = None, json: Any = None) -> str:
        self.async_tasks.append((path, params))
        assert path == "/v2/database-dir/info"
        return params["dir"]

    async def wait_for_async_task(self, task_id: str) -> dict[str, Any]:
        return {"Result": {"Mounted": self.mounted[task_id]}}


@pytest.fixture(autouse=True)
def _isolation(monkeypatch: pytest.MonkeyPatch):
    store.clear_traces()
    monkeypatch.setattr(demo_rehearsal, "WEB_APP_VERIFY_RETRY_DELAYS", ())
    yield
    store.clear_traces()
    app.dependency_overrides.clear()


@pytest.fixture
def fake() -> FakeIris:
    return FakeIris()


@pytest.fixture
def http(fake: FakeIris) -> TestClient:
    app.dependency_overrides[get_iris_client] = lambda: fake
    return TestClient(app)


def _post(http: TestClient, confirmed: bool = True) -> dict[str, Any]:
    response = http.post("/api/iris/demo/rehearsal", json={"confirmed": confirmed})
    assert response.status_code == 200
    return response.json()


def _steps(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["step"]: step for step in body["steps"]}


# --- the happy path ---


def test_successful_rehearsal_changes_restores_and_dry_runs(http: TestClient, fake: FakeIris) -> None:
    body = _post(http)

    assert body["status"] == "completed"
    steps = _steps(body)
    assert [s["step"] for s in body["steps"]] == [
        "journal.read", "journal.change", "journal.restore",
        "web_app.select", "web_app.read", "web_app.change", "web_app.restore",
        "database.dry_run", "task.dry_run",
    ]
    for name in ("journal.change", "journal.restore", "web_app.change", "web_app.restore"):
        assert steps[name]["status"] == "success"
        assert steps[name]["operation_status"] == "success"
    assert steps["database.dry_run"]["status"] == "dry_run"
    assert steps["task.dry_run"]["status"] == "dry_run"

    # Everything is back to its original value.
    assert fake.purge_archived is True
    assert fake.web_apps["/csp/user"]["Description"] == "User app"
    assert [p[1] for p in fake.puts] == [
        {"PurgeArchived": False},
        {"PurgeArchived": True},
        {"Description": "User app [IRIS Command Center rehearsal]"},
        {"Description": "User app"},
    ]

    # Each step includes the id of its execution trace.
    recorded = {t.trace_id: t for t in store.list_traces()}
    for name in ("journal.change", "journal.restore", "web_app.change", "web_app.restore",
                 "database.dry_run", "task.dry_run"):
        assert steps[name]["trace_id"] in recorded
        assert recorded[steps[name]["trace_id"]].operation_name == steps[name]["operation_name"]
    assert recorded[steps["task.dry_run"]["trace_id"]].status == "dry_run"


def test_existing_operation_executor_is_used_with_the_callers_confirmation(
    http: TestClient, fake: FakeIris, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bool, bool]] = []
    original_execute = OperationExecutor.execute

    async def spy(self, request, context):  # type: ignore[no-untyped-def]
        calls.append((request.operation_name, context.confirmation_received, context.dry_run))
        return await original_execute(self, request, context)

    monkeypatch.setattr(OperationExecutor, "execute", spy)

    _post(http)

    assert calls == [
        ("journal.update_purge_archived", True, False),
        ("journal.update_purge_archived", True, False),
        ("web_app.update_description", True, False),
        ("web_app.update_description", True, False),
        ("database.mount", True, True),
        ("task.run_now", True, True),
    ]


# --- confirmation and first-step failure ---


def test_without_confirmation_the_framework_stops_the_first_operation(http: TestClient, fake: FakeIris) -> None:
    body = _post(http, confirmed=False)

    assert body["status"] == "stopped"
    assert body["confirmed"] is False
    change = _steps(body)["journal.change"]
    assert change["operation_status"] == "confirmation_required"
    assert change["status"] == "failed"
    assert "journal.restore" not in _steps(body)  # nothing reached the handler
    assert fake.puts == [] and fake.posts == []


def test_first_step_failure_stops_the_rehearsal(http: TestClient, fake: FakeIris) -> None:
    fake.journal_put_error = 500

    body = _post(http)

    steps = _steps(body)
    assert body["status"] == "stopped"
    assert steps["journal.change"]["status"] == "failed"
    assert steps["journal.change"]["operation_status"] == "execution_failed"
    # The re-read showed the original value, so no restore was needed.
    assert steps["journal.restore"]["status"] == "not_needed"
    assert not any(name.startswith(("web_app", "database", "task")) for name in steps)
    assert fake.purge_archived is True


def test_missing_privilege_is_denied_by_the_existing_authorization(http: TestClient, fake: FakeIris) -> None:
    fake.privileges = {"Operate": True}

    body = _post(http)

    assert _steps(body)["journal.change"]["operation_status"] == "unauthorized"
    assert fake.puts == []


# --- restoration ---


def test_later_failure_restores_the_temporary_change(http: TestClient, fake: FakeIris) -> None:
    # The web-app PUT sets the Description but also flips Enabled, so
    # verification fails after the change went through.
    fake.flip_enabled_on_next_web_app_put = True

    body = _post(http)

    steps = _steps(body)
    assert body["status"] == "stopped"
    assert steps["journal.restore"]["status"] == "success"  # earlier phase fully restored
    assert steps["web_app.change"]["operation_status"] == "verification_failed"
    assert steps["web_app.restore"]["status"] == "success"
    assert fake.web_apps["/csp/user"]["Description"] == "User app"
    assert fake.purge_archived is True
    assert "database.dry_run" not in steps  # stopped at the first failure


def test_restoration_failure_is_reported_clearly(http: TestClient, fake: FakeIris) -> None:
    fake.web_app_put_errors = [None, 400]  # the change succeeds, the restore is rejected

    body = _post(http)

    restore = _steps(body)["web_app.restore"]
    assert body["status"] == "restore_failed"
    assert "could NOT be restored" in body["detail"]
    assert restore["status"] == "failed"
    assert "RESTORATION FAILED" in restore["detail"]
    assert "'User app'" in restore["detail"]  # tells the user what to fix by hand
    assert fake.web_apps["/csp/user"]["Description"] != "User app"
    assert "database.dry_run" not in _steps(body)


# --- dry-runs and candidate safety ---


def test_dry_run_steps_never_mutate(http: TestClient, fake: FakeIris) -> None:
    body = _post(http)

    steps = _steps(body)
    assert steps["database.dry_run"]["target"] == "/usr/irissys/mgr/demo/"
    assert steps["task.dry_run"]["target"] == "task 42"  # the User task, not the System one
    assert fake.posts == []  # no POST /v2/database-dir/mount, no POST /v2/task/run
    assert all(path in ("/v2/journal/settings", "/v2/web-app") for path, _, _ in fake.puts)
    assert fake.async_tasks == [("/v2/database-dir/info", {"dir": "/usr/irissys/mgr/demo/"})]  # read-only info
    assert fake.mounted["/usr/irissys/mgr/demo/"] is False


def test_dry_runs_are_skipped_without_valid_candidates(http: TestClient, fake: FakeIris) -> None:
    fake.database_dirs = [{"Directory": "/usr/irissys/mgr/user/", "Status": "Mounted/RW"}]
    fake.tasks = [{"Id": 1, "Name": "Purge Journal", "Type": "System", "Suspended": False}]

    body = _post(http)

    steps = _steps(body)
    assert body["status"] == "completed"
    assert steps["database.dry_run"]["status"] == "skipped"
    assert steps["task.dry_run"]["status"] == "skipped"
    assert fake.async_tasks == []


def test_protected_and_system_web_apps_are_skipped(http: TestClient, fake: FakeIris) -> None:
    del fake.web_apps["/csp/user"]

    body = _post(http)

    select = _steps(body)["web_app.select"]
    assert select["status"] == "skipped"
    assert "web_app.change" not in _steps(body)
    assert not any(path == "/v2/web-app" for path, _, _ in fake.puts)
    assert body["status"] == "completed"


def test_csp_user_is_preferred_over_earlier_safe_apps(http: TestClient, fake: FakeIris) -> None:
    fake.web_apps["/api/atelier"] = {"Type": "CSP", "Description": "Atelier REST Apis", "Enabled": True}

    body = _post(http)

    assert _steps(body)["web_app.select"]["target"] == "/csp/user"
    assert fake.web_apps["/api/atelier"]["Description"] == "Atelier REST Apis"
    assert all(params == {"name": "/csp/user"} for path, _, params in fake.puts if path == "/v2/web-app")


def test_without_csp_user_the_first_safe_app_is_selected(http: TestClient, fake: FakeIris) -> None:
    del fake.web_apps["/csp/user"]
    fake.web_apps["/ui/interop"] = {"Type": "CSP", "Description": "Interoperability", "Enabled": True}
    fake.web_apps["/api/atelier"] = {"Type": "CSP", "Description": "Atelier REST Apis", "Enabled": True}

    body = _post(http)

    assert _steps(body)["web_app.select"]["target"] == "/api/atelier"
    assert body["status"] == "completed"
    assert fake.web_apps["/api/atelier"]["Description"] == "Atelier REST Apis"


def test_an_unsafe_csp_user_is_never_preferred(http: TestClient, fake: FakeIris) -> None:
    fake.web_apps["/csp/user"]["Type"] = "System,CSP"
    fake.web_apps["/api/atelier"] = {"Type": "CSP", "Description": "Atelier REST Apis", "Enabled": True}

    body = _post(http)

    assert _steps(body)["web_app.select"]["target"] == "/api/atelier"
    assert fake.web_apps["/csp/user"]["Description"] == "User app"


@pytest.mark.parametrize(
    ("entry", "safe"),
    [
        ({"Name": "/csp/user", "Type": "CSP"}, True),
        ({"Name": "/api/admin", "Type": "CSP"}, False),
        ({"Name": "/API/Mgmnt/", "Type": "CSP"}, False),
        ({"Name": "/csp/sys", "Type": "System,CSP"}, False),
        ({"Name": "/csp/x", "Type": "CSP", "IsSystemApp": True}, False),
        ({"Name": "/csp/x"}, False),  # unknown Type is never treated as safe
    ],
)
def test_is_safe_web_app(entry: dict[str, Any], safe: bool) -> None:
    assert demo_rehearsal.is_safe_web_app(entry) is safe


def test_temporary_description_always_differs_and_fits() -> None:
    assert demo_rehearsal.temporary_description("") == "[IRIS Command Center rehearsal]"
    long = "x" * 256
    assert demo_rehearsal.temporary_description(long) == "[IRIS Command Center rehearsal]"
    marker = "[IRIS Command Center rehearsal]"
    assert demo_rehearsal.temporary_description(marker) != marker


# --- exposure ---


def test_response_contains_no_secrets_or_sensitive_fields(http: TestClient, fake: FakeIris) -> None:
    text = json.dumps(_post(http))

    for forbidden in (PASSWORD, "must-never-leak", "Password", "Authorization", "Bearer", "_SYSTEM", "jwt"):
        assert forbidden not in text


def test_rehearsal_rejects_unknown_fields(http: TestClient) -> None:
    response = http.post("/api/iris/demo/rehearsal", json={"confirmed": True, "force": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_second_concurrent_rehearsal_is_refused(fake: FakeIris) -> None:
    async with demo_rehearsal._rehearsal_lock:
        with pytest.raises(demo_rehearsal.RehearsalInProgressError):
            await demo_rehearsal.run_rehearsal(fake, frozenset(), True)
