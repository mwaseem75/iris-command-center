"""Custom Issue Rules (V1): user-defined, detection-only issues.

A rule compares one live numeric signal to a number, e.g. "SeriousAlerts > 0".
Only a fixed set of signals, operators and investigation pages is allowed;
nothing in a rule is evaluated as code, and a rule never runs anything.

Signals are current values from GET /v2/monitor/dashboard/main (one read
evaluates every rule). Totals since startup (GlobalRefs, DiskReads, ...) are
deliberately not offered: comparing them to a fixed number means nothing.

Each rule becomes a detection-only catalog entry, issue type "custom:<name>",
so it's shown and investigated like the built-in detection-only issues and
can never be resolved by an operation.

Rules live in memory. With PERSIST_ISSUE_RULES_TO_IRIS they're also saved to
^CommandCenterIssueRule over the Native API (see IRISIssueRuleWriter) and
loaded back at startup.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from app.config import Settings
from app.models.iris import MonitorDashboard
from app.resolution.models import (
    DetectionEvidence,
    InvestigationDestination,
    IssueResolution,
    IssueSeverity,
    VerificationRule,
)

logger = logging.getLogger(__name__)

CUSTOM_PREFIX = "custom:"
MAX_RULES = 20

# --- the fixed vocabulary ---


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    field: str  # where it comes from in GET /v2/monitor/dashboard/main
    unit: str
    read: Callable[[MonitorDashboard], float | None]


def _number(value: Any) -> float | None:
    """A number, or None (e.g. LicenseUse is "" when there's no license limit)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


SIGNALS: dict[str, Signal] = {s.key: s for s in (
    Signal("processes", "Processes", "SystemUsage.Processes", "processes",
           lambda d: _number(d.SystemUsage.Processes)),
    Signal("csp_sessions", "CSP sessions", "SystemUsage.CSPSessions", "sessions",
           lambda d: _number(d.SystemUsage.CSPSessions)),
    Signal("serious_alerts", "Serious alerts", "Alerts.SeriousAlerts", "alerts",
           lambda d: _number(d.Alerts.SeriousAlerts)),
    Signal("application_errors", "Application errors", "Alerts.ApplicationErrors", "errors",
           lambda d: _number(d.Alerts.ApplicationErrors)),
    Signal("license_use_percent", "License use", "Licensing.LicenseUse", "%",
           lambda d: _number(d.Licensing.LicenseUse)),
    Signal("cache_efficiency", "Cache efficiency", "Performance.CacheEfficiency", "",
           lambda d: _number(d.Performance.CacheEfficiency)),
    Signal("global_refs_per_second", "Global references per second", "Performance.GlobalRefsPerSecond", "/s",
           lambda d: _number(d.Performance.GlobalRefsPerSecond)),
)}

Operator = Literal[">", ">=", "<", "<=", "==", "!="]
OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

# Existing Command Center pages a rule can point to (their view names).
INVESTIGATION_PAGES: dict[str, str] = {
    "dashboard": "Dashboard",
    "system": "System",
    "processes": "Processes",
    "databases": "Databases",
    "web-apps": "Web Apps",
    "tasks": "Tasks",
    "security": "Security",
    "journal": "Journal",
    "observability": "Observability",
    "investigation": "Investigation",
}

_NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class CustomIssueRule(BaseModel):
    """One rule, exactly as the user entered it. Unknown fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    title: str
    severity: IssueSeverity
    signal: str
    operator: Operator
    value: float
    investigation_page: str
    guidance: str

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME.match(value):
            raise ValueError("Name must be 3-40 characters: lowercase letters, digits and _, starting with a letter.")
        return value

    @field_validator("title", "guidance")
    @classmethod
    def _plain_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        limit = 80 if info.field_name == "title" else 500
        if not value:
            raise ValueError(f"{info.field_name} is required.")
        if len(value) > limit:
            raise ValueError(f"{info.field_name} must be at most {limit} characters.")
        if _CONTROL.search(value):
            raise ValueError(f"{info.field_name} must not contain control characters.")
        return value

    @field_validator("signal")
    @classmethod
    def _known_signal(cls, value: str) -> str:
        if value not in SIGNALS:
            raise ValueError(f"Unknown signal {value!r}; choose one of {sorted(SIGNALS)}.")
        return value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > 1e12:
            raise ValueError("Value must be a finite number.")
        return value

    @field_validator("investigation_page")
    @classmethod
    def _known_page(cls, value: str) -> str:
        if value not in INVESTIGATION_PAGES:
            raise ValueError(f"Unknown page {value!r}; choose one of {sorted(INVESTIGATION_PAGES)}.")
        return value

    @property
    def issue_type(self) -> str:
        return f"{CUSTOM_PREFIX}{self.name}"

    def condition_text(self) -> str:
        signal = SIGNALS[self.signal]
        return f"{signal.label} {self.operator} {self.value:g}"

    def to_catalog_entry(self) -> IssueResolution:
        """The rule as a detection-only catalog entry (never resolvable)."""
        signal = SIGNALS[self.signal]
        page = INVESTIGATION_PAGES[self.investigation_page]
        return IssueResolution(
            issue_type=self.issue_type,
            title=self.title,
            severity=self.severity,
            detection_evidence=(
                DetectionEvidence(
                    source="GET /v2/monitor/dashboard/main",
                    field=signal.field,
                    condition=f"Custom rule: {self.condition_text()}.",
                    issue_field="value",
                ),
            ),
            explanation=f"A custom rule: reported while {self.condition_text()}. {self.guidance}",
            recommended_solution=(
                f"Look into it on the {page} page. This is a custom detection-only rule; nothing is run from here."
            ),
            investigation=InvestigationDestination(page=self.investigation_page, description=self.guidance),
            verification_rules=(
                VerificationRule(
                    source="GET /api/iris/issues",
                    condition="The rule's condition no longer holds.",
                    checked_by="issue_detection",
                ),
            ),
        )

    def evaluate(self, dashboard: MonitorDashboard) -> tuple[bool | None, float | None]:
        """(matched, live value). matched is None if the signal has no number now."""
        value = SIGNALS[self.signal].read(dashboard)
        if value is None:
            return None, None
        return OPERATORS[self.operator](value, self.value), value


# --- the store (in memory; optionally persisted to IRIS) ---


class RuleConflictError(Exception):
    """A rule with that name exists, or the limit is reached."""


class _RulePersister(Protocol):
    def save_sync(self, rule: CustomIssueRule) -> bool: ...
    def delete_sync(self, name: str) -> bool: ...


_rules: dict[str, CustomIssueRule] = {}
_persister: _RulePersister | None = None


def set_rule_persister(persister: _RulePersister | None) -> None:
    global _persister
    _persister = persister


def persistence_enabled() -> bool:
    return _persister is not None


def hydrate_rules(rules: list[CustomIssueRule]) -> int:
    """Load saved rules at startup (in-memory only, nothing is written back)."""
    for rule in rules[:MAX_RULES]:
        _rules.setdefault(rule.name, rule)
    return len(_rules)


def list_rules() -> list[CustomIssueRule]:
    return list(_rules.values())


def add_rule(rule: CustomIssueRule) -> None:
    if rule.name in _rules:
        raise RuleConflictError(f"A custom rule named {rule.name!r} already exists.")
    if len(_rules) >= MAX_RULES:
        raise RuleConflictError(f"At most {MAX_RULES} custom rules are allowed.")
    _rules[rule.name] = rule


def remove_rule(name: str) -> bool:
    return _rules.pop(name, None) is not None


def get_persister() -> _RulePersister | None:
    return _persister


def clear_rules() -> None:
    """Tests only."""
    _rules.clear()


class IRISIssueRuleWriter:
    """Saves rules to ^CommandCenterIssueRule("rule", <name>) = rule JSON, over
    the Native API in iris_namespace (same connection pattern as
    IRISTraceWriter). Blocking: call from a thread. Never raises; the save and
    delete calls return whether IRIS was updated.
    """

    _GLOBAL = "CommandCenterIssueRule"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._iris: Any = None

    def _ensure_connected(self) -> None:
        if self._iris is not None:
            return
        import iris  # noqa: PLC0415 - lazy, like IRISTraceWriter

        self._connection = iris.connect(
            urlsplit(self._settings.iris_base_url).hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )
        self._iris = iris.createIRIS(self._connection)

    def save_sync(self, rule: CustomIssueRule) -> bool:
        try:
            self._ensure_connected()
            self._iris.set(rule.model_dump_json(), self._GLOBAL, "rule", rule.name)
            return True
        except Exception:  # noqa: BLE001 - reported to the caller as not persisted
            logger.warning("Could not save custom issue rule %s to IRIS (^%s).", rule.name, self._GLOBAL, exc_info=True)
            return False

    def delete_sync(self, name: str) -> bool:
        try:
            self._ensure_connected()
            self._iris.kill(self._GLOBAL, "rule", name)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Could not delete custom issue rule %s from IRIS (^%s).", name, self._GLOBAL, exc_info=True)
            return False

    def load_all_sync(self) -> list[CustomIssueRule]:
        """Every saved rule; broken entries are skipped. Never raises."""
        rules: list[CustomIssueRule] = []
        try:
            self._ensure_connected()
            key = self._iris.nextSubscript(False, self._GLOBAL, "rule", "")
            while key:
                raw = self._iris.get(self._GLOBAL, "rule", key)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    rules.append(CustomIssueRule.model_validate_json(raw))
                except ValueError:
                    logger.warning("Skipping unreadable custom issue rule ^%s(\"rule\",%r).", self._GLOBAL, key)
                key = self._iris.nextSubscript(False, self._GLOBAL, "rule", key)
        except Exception:  # noqa: BLE001 - startup must never fail on this
            logger.warning("Could not load custom issue rules from IRIS (^%s).", self._GLOBAL, exc_info=True)
        return rules

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:  # noqa: BLE001
            logger.warning("Error closing the custom issue rule IRIS connection.", exc_info=True)
        finally:
            self._connection = None
            self._iris = None
