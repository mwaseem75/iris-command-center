"""Tests for Custom Issue Rules (V1): the rule model, evaluation in
GET /api/iris/issues, the /api/iris/issue-rules routes and the IRIS writer.
IRIS is mocked; the Native API is a fake."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencies import get_caller_privileges
from app.iris_client.exceptions import IRISResponseError
from app.main import app
from app.models.iris import MonitorDashboard
from app.resolution import custom_rules
from app.resolution.catalog import resolves_with, trace_context
from app.resolution.custom_rules import CustomIssueRule, IRISIssueRuleWriter
from tests.test_issues_route import HEALTHY, OK, USER_NS, _dashboard, _mock


def _rule(**overrides: Any) -> dict[str, Any]:
    data = {"name": "serious_alerts_seen", "title": "Serious alerts reported", "severity": "high",
            "signal": "serious_alerts", "operator": ">", "value": 0, "investigation_page": "investigation",
            "guidance": "Check the audit trail around the alert time."}
    data.update(overrides)
    return data


class FakePersister:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.saved: list[str] = []
        self.deleted: list[str] = []

    def save_sync(self, rule: CustomIssueRule) -> bool:
        self.saved.append(rule.name)
        return self.ok

    def delete_sync(self, name: str) -> bool:
        self.deleted.append(name)
        return self.ok


@pytest.fixture(autouse=True)
def _isolation():
    custom_rules.clear_rules()
    custom_rules.set_rule_persister(None)
    yield
    custom_rules.clear_rules()
    custom_rules.set_rule_persister(None)
    app.dependency_overrides.pop(get_caller_privileges, None)


def _privileges(*names: str) -> None:
    app.dependency_overrides[get_caller_privileges] = lambda: frozenset(names)


# --- the rule model ---


def test_a_valid_rule_is_accepted_and_trimmed() -> None:
    rule = CustomIssueRule(**_rule(title="  Serious alerts reported  "))
    assert rule.title == "Serious alerts reported"
    assert rule.issue_type == "custom:serious_alerts_seen"
    assert rule.condition_text() == "Serious alerts > 0"


@pytest.mark.parametrize("overrides", [
    {"name": "Bad Name"}, {"name": "ab"}, {"name": "1abc"}, {"name": "x" * 41},
    {"signal": "GlobalRefs"}, {"signal": "__import__('os')"},
    {"operator": "=~"}, {"operator": "and"},
    {"value": float("inf")}, {"value": float("nan")}, {"value": 1e13}, {"value": "1+1"},
    {"investigation_page": "https://example.com"}, {"investigation_page": "operations"},
    {"severity": "urgent"},
    {"title": ""}, {"title": "x" * 81}, {"guidance": "bad\x00text"}, {"guidance": "y" * 501},
])
def test_invalid_rules_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CustomIssueRule(**_rule(**overrides))


def test_unknown_fields_like_code_or_operations_are_rejected() -> None:
    for extra in ({"expression": "x > 1"}, {"operation": "database.mount"}, {"url": "http://x"}):
        with pytest.raises(ValidationError):
            CustomIssueRule(**_rule(**extra))


def test_only_current_value_signals_are_offered() -> None:
    assert set(custom_rules.SIGNALS) == {
        "processes", "csp_sessions", "serious_alerts", "application_errors",
        "license_use_percent", "cache_efficiency", "global_refs_per_second",
    }
    dashboard = MonitorDashboard.model_validate(_dashboard())
    for signal in custom_rules.SIGNALS.values():
        assert isinstance(signal.read(dashboard), float)


@pytest.mark.parametrize("operator, value, expected", [
    (">", 4, True), (">", 5, False), (">=", 5, True), ("<", 6, True), ("<=", 4, False), ("==", 5, True), ("!=", 5, False),
])
def test_operators_compare_the_live_value(operator: str, value: float, expected: bool) -> None:
    rule = CustomIssueRule(**_rule(signal="processes", operator=operator, value=value))
    assert rule.evaluate(MonitorDashboard.model_validate(_dashboard())) == (expected, 5.0)  # Processes is 5


def test_a_signal_without_a_number_is_not_evaluated() -> None:
    body = _dashboard()
    body["Licensing"]["LicenseUse"] = ""  # IRIS sends "" with no license limit
    rule = CustomIssueRule(**_rule(signal="license_use_percent", operator=">", value=80))
    assert rule.evaluate(MonitorDashboard.model_validate(body)) == (None, None)


def test_a_rule_is_a_detection_only_catalog_entry_that_nothing_resolves() -> None:
    from app.authorization.operations import OPERATION_REGISTRY

    entry = CustomIssueRule(**_rule()).to_catalog_entry()

    assert entry.issue_type == "custom:serious_alerts_seen" and entry.resolvable is False
    assert entry.operation is None and entry.investigation.page == "investigation"
    assert entry.detection_evidence[0].field == "Alerts.SeriousAlerts"
    for operation in OPERATION_REGISTRY:
        assert not resolves_with(entry.issue_type, operation)
        assert trace_context(entry.issue_type, operation, {}) is None


# --- evaluation in GET /api/iris/issues ---


def _issues_with(client: TestClient, mock: AsyncMock, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    _mock(mock, *HEALTHY, USER_NS)
    if dashboard is not None:
        original = mock.get.side_effect
        mock.get.side_effect = lambda path, **kw: (
            {"status": OK, "console": [], "result": dashboard} if path == "/v2/monitor/dashboard/main"
            else original(path, **kw))
    return client.get("/api/iris/issues").json()


def test_no_rules_means_no_extra_issues_or_catalog_entries(client: TestClient, mock_iris_client: AsyncMock) -> None:
    body = _issues_with(client, mock_iris_client)
    assert not any(k.startswith("custom:") for k in body["resolutions"])
    assert not any(i["kind"].startswith("custom:") for i in body["issues"])


def test_a_matching_rule_is_reported_with_its_live_value(client: TestClient, mock_iris_client: AsyncMock) -> None:
    custom_rules.add_rule(CustomIssueRule(**_rule()))
    dashboard = _dashboard()
    dashboard["Alerts"]["SeriousAlerts"] = 2

    body = _issues_with(client, mock_iris_client, dashboard)

    (issue,) = [i for i in body["issues"] if i["kind"].startswith("custom:")]
    assert issue["kind"] == "custom:serious_alerts_seen" and issue["rule"] == "serious_alerts_seen"
    assert issue["value"] == 2 and issue["threshold"] == 0 and issue["operator"] == ">"
    assert "Serious alerts is 2" in issue["explanation"] and "Check the audit trail" in issue["explanation"]
    entry = body["resolutions"]["custom:serious_alerts_seen"]
    assert entry["resolvable"] is False and entry["investigation"]["page"] == "investigation"
    assert entry["title"] == "Serious alerts reported" and entry["severity"] == "high"
    mock_iris_client.post.assert_not_called()
    mock_iris_client.put.assert_not_called()


def test_a_rule_that_does_not_match_only_adds_its_catalog_entry(client: TestClient, mock_iris_client: AsyncMock) -> None:
    custom_rules.add_rule(CustomIssueRule(**_rule()))  # SeriousAlerts is 0 in the default dashboard

    body = _issues_with(client, mock_iris_client)

    assert not any(i["kind"].startswith("custom:") for i in body["issues"])
    assert "custom:serious_alerts_seen" in body["resolutions"]
    assert body["issue_checks_unavailable"] == []


def test_a_stale_value_is_flagged_when_the_system_monitor_is_off(client: TestClient, mock_iris_client: AsyncMock) -> None:
    custom_rules.add_rule(CustomIssueRule(**_rule(signal="processes", operator=">=", value=1)))
    body = _issues_with(client, mock_iris_client, _dashboard(system_monitor=False))
    (issue,) = [i for i in body["issues"] if i["kind"].startswith("custom:")]
    assert "may be out of date" in issue["explanation"]


def test_rules_that_cannot_be_evaluated_are_reported(client: TestClient, mock_iris_client: AsyncMock) -> None:
    custom_rules.add_rule(CustomIssueRule(**_rule(name="license_high", signal="license_use_percent", value=80)))
    custom_rules.add_rule(CustomIssueRule(**_rule()))
    dashboard = _dashboard()
    dashboard["Licensing"]["LicenseUse"] = ""

    body = _issues_with(client, mock_iris_client, dashboard)

    assert body["issue_checks_unavailable"] == ["custom:license_high"]


def test_an_unreadable_dashboard_makes_every_rule_unavailable(client: TestClient, mock_iris_client: AsyncMock) -> None:
    custom_rules.add_rule(CustomIssueRule(**_rule()))
    _mock(mock_iris_client, *HEALTHY, USER_NS)
    original = mock_iris_client.get.side_effect

    def get(path: str, **kw: Any) -> dict[str, Any]:
        if path == "/v2/monitor/dashboard/main":
            raise IRISResponseError(500)
        return original(path, **kw)

    mock_iris_client.get.side_effect = get
    body = client.get("/api/iris/issues").json()

    assert "custom:serious_alerts_seen" in body["issue_checks_unavailable"]
    assert "custom:serious_alerts_seen" in body["resolutions"]  # still explained


# --- the /api/iris/issue-rules routes ---


def test_list_shows_the_fixed_vocabulary(client: TestClient) -> None:
    body = client.get("/api/iris/issue-rules").json()
    assert body["rules"] == [] and body["persisted_to_iris"] is False and body["max_rules"] == 20
    assert {s["key"] for s in body["signals"]} == set(custom_rules.SIGNALS)
    assert body["operators"] == [">", ">=", "<", "<=", "==", "!="]
    assert {p["key"] for p in body["pages"]} == set(custom_rules.INVESTIGATION_PAGES)


def test_creating_or_deleting_a_rule_needs_manage(client: TestClient) -> None:
    _privileges("Operate")
    response = client.post("/api/iris/issue-rules", json=_rule())
    assert response.status_code == 403
    assert custom_rules.list_rules() == []

    custom_rules.add_rule(CustomIssueRule(**_rule()))
    deleted = client.post("/api/iris/issue-rules/delete", json={"name": "serious_alerts_seen", "confirmed": True})
    assert deleted.status_code == 403 and len(custom_rules.list_rules()) == 1


def test_create_and_delete_a_rule(client: TestClient) -> None:
    _privileges("Manage")
    persister = FakePersister()
    custom_rules.set_rule_persister(persister)

    created = client.post("/api/iris/issue-rules", json=_rule())
    assert created.status_code == 201
    assert created.json()["persisted"] is True and created.json()["rule"]["name"] == "serious_alerts_seen"
    assert [r["name"] for r in client.get("/api/iris/issue-rules").json()["rules"]] == ["serious_alerts_seen"]

    assert client.post("/api/iris/issue-rules/delete", json={"name": "serious_alerts_seen"}).status_code == 428
    deleted = client.post("/api/iris/issue-rules/delete", json={"name": "serious_alerts_seen", "confirmed": True})
    assert deleted.status_code == 200 and deleted.json() == {"rule": None, "deleted": "serious_alerts_seen",
                                                              "persisted": True}
    assert custom_rules.list_rules() == []
    assert persister.saved == ["serious_alerts_seen"] and persister.deleted == ["serious_alerts_seen"]


def test_without_iris_persistence_rules_are_kept_in_memory(client: TestClient) -> None:
    _privileges("Manage")
    assert client.post("/api/iris/issue-rules", json=_rule()).json()["persisted"] is False
    assert len(custom_rules.list_rules()) == 1


def test_a_failed_iris_save_is_reported(client: TestClient) -> None:
    _privileges("Manage")
    custom_rules.set_rule_persister(FakePersister(ok=False))
    assert client.post("/api/iris/issue-rules", json=_rule()).json()["persisted"] is False


def test_conflicts_and_bad_requests(client: TestClient) -> None:
    _privileges("Manage")
    assert client.post("/api/iris/issue-rules", json=_rule()).status_code == 201
    assert client.post("/api/iris/issue-rules", json=_rule()).status_code == 409  # duplicate
    assert client.post("/api/iris/issue-rules", json=_rule(name="database_full")).status_code == 409  # built-in
    assert client.post("/api/iris/issue-rules", json=_rule(name="other", signal="nope")).status_code == 422
    assert client.post("/api/iris/issue-rules/delete", json={"name": "missing", "confirmed": True}).status_code == 404
    assert client.post("/api/iris/issue-rules/delete",
                       json={"name": "serious_alerts_seen", "confirmed": True, "force": True}).status_code == 422


def test_the_number_of_rules_is_limited(client: TestClient) -> None:
    _privileges("Manage")
    for i in range(custom_rules.MAX_RULES):
        assert client.post("/api/iris/issue-rules", json=_rule(name=f"rule_{i:02d}")).status_code == 201
    assert client.post("/api/iris/issue-rules", json=_rule(name="one_too_many")).status_code == 409


# --- the IRIS writer (fake Native API) ---


class FakeNativeIRIS:
    def __init__(self) -> None:
        self.data: dict[tuple, Any] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise RuntimeError("connection lost")

    def set(self, value: Any, *keys: Any) -> None:
        self._check()
        self.data[keys] = value

    def get(self, *keys: Any) -> Any:
        self._check()
        return self.data.get(keys)

    def kill(self, *keys: Any) -> None:
        self._check()
        self.data.pop(keys, None)

    def nextSubscript(self, reverse: bool, *keys: Any) -> str | None:  # noqa: N802 - Native API name
        self._check()
        *prefix, last = keys
        subs = sorted(k[len(prefix)] for k in self.data if list(k[:len(prefix)]) == prefix and len(k) > len(prefix))
        later = [s for s in subs if s > last]
        return later[0] if later else None


def _writer() -> tuple[IRISIssueRuleWriter, FakeNativeIRIS]:
    from app.config import Settings

    writer = IRISIssueRuleWriter(Settings(iris_base_url="http://iris.invalid.test:52773", iris_username="u",
                                          iris_password="test-password-not-real"))
    fake = FakeNativeIRIS()
    writer._iris = fake  # skip the real connection
    return writer, fake


def test_writer_saves_loads_and_deletes_rules() -> None:
    writer, fake = _writer()
    first, second = CustomIssueRule(**_rule(name="alpha_rule")), CustomIssueRule(**_rule(name="beta_rule"))

    assert writer.save_sync(first) and writer.save_sync(second)
    assert ("CommandCenterIssueRule", "rule", "alpha_rule") in fake.data
    assert [r.name for r in writer.load_all_sync()] == ["alpha_rule", "beta_rule"]

    assert writer.delete_sync("alpha_rule")
    assert [r.name for r in writer.load_all_sync()] == ["beta_rule"]


def test_writer_skips_broken_entries_and_never_raises() -> None:
    writer, fake = _writer()
    writer.save_sync(CustomIssueRule(**_rule(name="good_rule")))
    fake.data[("CommandCenterIssueRule", "rule", "broken_rule")] = '{"name": "broken_rule", "operator": "eval"}'

    assert [r.name for r in writer.load_all_sync()] == ["good_rule"]

    fake.fail = True
    assert writer.save_sync(CustomIssueRule(**_rule(name="later_rule"))) is False
    assert writer.delete_sync("good_rule") is False
    assert writer.load_all_sync() == []


def test_startup_hydration_keeps_at_most_the_limit() -> None:
    rules = [CustomIssueRule(**_rule(name=f"rule_{i:02d}")) for i in range(custom_rules.MAX_RULES + 5)]
    assert custom_rules.hydrate_rules(rules) == custom_rules.MAX_RULES


# --- non-finite numbers in a rejected request (found by the live E2E test) ---


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_value_is_a_422_not_a_500(client: TestClient, token: str) -> None:
    # JSON allows these tokens in practice; the 422 must still be valid JSON.
    _privileges("Manage")
    body = ('{"name": "nan_rule", "title": "t", "severity": "low", "signal": "processes", "operator": ">", '
            f'"value": {token}, "investigation_page": "processes", "guidance": "g"}}')
    response = client.post("/api/iris/issue-rules", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "value"] and "finite number" in error["msg"]
    assert custom_rules.list_rules() == []


# --- reconnect once after IRIS dropped the kept connection ---


class _FakeIrisModule:
    """The `iris` module: numbered connections; one can "die" (EPIPE after an IRIS restart)."""

    def __init__(self) -> None:
        self.globals: dict[tuple, Any] = {}
        self.connections: list[dict] = []
        self.down = False

    def connect(self, *args: Any) -> Any:
        if self.down:
            raise RuntimeError("<COMMUNICATION LINK ERROR> Failed to connect")
        state = {"dead": False, "closed": False}
        self.connections.append(state)
        return type("Connection", (), {"state": state, "close": lambda self: state.update(closed=True)})()

    def createIRIS(self, handle: Any) -> Any:  # noqa: N802 - Native API name
        module, state = self, handle.state

        def check() -> None:
            if state["dead"] or state["closed"]:
                raise RuntimeError("<COMMUNICATION LINK ERROR> Error code: 32 EPIPE")

        class Native:
            def set(self, value: Any, *keys: Any) -> None:
                check()
                module.globals[keys] = value

            def kill(self, *keys: Any) -> None:
                check()
                module.globals.pop(keys, None)

        return Native()


@pytest.fixture
def fake_iris_module(monkeypatch: pytest.MonkeyPatch) -> _FakeIrisModule:
    import sys

    module = _FakeIrisModule()
    monkeypatch.setitem(sys.modules, "iris", module)
    return module


def test_writer_reconnects_once_after_the_connection_died(fake_iris_module: _FakeIrisModule) -> None:
    writer, _ = _writer()
    writer._iris = None  # use the fake module, not the in-memory fake
    rule = CustomIssueRule(**_rule(name="alpha_rule"))
    assert writer.save_sync(rule)
    fake_iris_module.connections[0]["dead"] = True  # IRIS restarted

    assert writer.delete_sync("alpha_rule") is True
    assert ("CommandCenterIssueRule", "rule", "alpha_rule") not in fake_iris_module.globals
    assert len(fake_iris_module.connections) == 2 and fake_iris_module.connections[0]["closed"]


def test_writer_reports_a_failure_when_iris_is_still_down(fake_iris_module: _FakeIrisModule) -> None:
    writer, _ = _writer()
    writer._iris = None
    assert writer.save_sync(CustomIssueRule(**_rule(name="alpha_rule")))
    fake_iris_module.connections[0]["dead"] = True
    fake_iris_module.down = True

    assert writer.save_sync(CustomIssueRule(**_rule(name="beta_rule"))) is False  # one retry, then reported
    assert len(fake_iris_module.connections) == 1
    fake_iris_module.down = False
    assert writer.save_sync(CustomIssueRule(**_rule(name="beta_rule"))) is True  # not stuck on a dead connection
