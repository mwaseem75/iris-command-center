"""HealthAnalyzer — the Embedded Python bonus feature.

Design: this module owns exactly two things Embedded Python is uniquely
positioned to provide inside IRIS:

1. Real OS-level metrics via `psutil` (CPU%, memory%) — the SysAdmin REST API
   this project is built on has NO endpoint that returns these; confirmed
   empirically in Phase 3 (see docs/api-matrix.md section 12) and is the
   entire reason this bonus exists as a separate feature rather than another
   dashboard card.
2. The scoring/analysis logic that turns raw metrics into a health score,
   status, warnings, severity, recommendations, and anomalies.

IRIS-specific inputs (license usage, active processes, failed tasks, audit
alert counts, shared-memory usage, databases near full) are NOT re-derived
here by guessing ObjectScript class/method names from Python — this project's
own SysAdmin REST API already exposes all of them, tested and documented in
docs/api-matrix.md, and the frontend already fetches most of them for the
dashboard. They're passed in as `iris_metrics`, gathered by the caller.

`analyze()` is pure — no IRIS dependency, no psutil call inside it — so it's
independently unit-testable with plain dicts (see tests/test_health_analyzer.py,
runnable with nothing but a stdlib Python interpreter). `gather_and_analyze()`
is the thin, IRIS-side entry point that adds real psutil data and calls it;
that's the only piece that needs an IRIS process to exercise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds. Centralized so tests and callers can see exactly what triggers
# a warning vs. a critical finding — no magic numbers scattered through the
# scoring logic below.
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "cpu_percent": {"warning": 75.0, "critical": 90.0},
    "memory_percent": {"warning": 80.0, "critical": 93.0},
    "license_ratio": {"warning": 0.85, "critical": 0.95},
    "shared_memory_percent": {"warning": 80.0, "critical": 93.0},
}

SCORE_PENALTIES = {
    "warning": 12,
    "critical": 28,
}

STATUS_THRESHOLDS = {"healthy": 85, "warning": 60}  # below "warning" -> "critical"


def _tier(value: float | None, warning: float, critical: float) -> str | None:
    """Returns 'critical', 'warning', or None for a metric against its thresholds."""
    if value is None:
        return None
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return None


def analyze(python_metrics: dict[str, Any], iris_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure scoring function — no I/O, no IRIS, no psutil calls. Safe to unit test directly.

    :param python_metrics: {"cpu_percent": float, "memory_percent": float,
        "memory_total_bytes": int, "memory_available_bytes": int}
    :param iris_metrics: optional dict of already-gathered IRIS metrics:
        {"license_used": int, "license_limit": int, "active_processes": int,
         "csp_sessions": int, "failed_tasks_24h": int, "serious_audit_alerts": int,
         "shared_memory_used_pages": int, "shared_memory_allocated_pages": int,
         "databases_near_full": [str, ...]}
        Any key may be omitted; that check is simply skipped.
    :returns: {"score": int, "status": str, "severity": str, "warnings": [...],
        "recommendations": [...], "anomalies": [...], "checkedAt": iso8601 str}
    """
    iris_metrics = iris_metrics or {}
    score = 100
    warnings: list[dict[str, str]] = []
    anomalies: list[str] = []
    recommendations: list[str] = []
    worst_severity = "none"

    severity_rank = {"none": 0, "warning": 1, "critical": 2}

    def flag(metric: str, tier: str | None, message: str, recommendation: str, anomaly: str | None = None) -> None:
        nonlocal score, worst_severity
        if tier is None:
            return
        score -= SCORE_PENALTIES[tier]
        warnings.append({"metric": metric, "severity": tier, "message": message})
        recommendations.append(recommendation)
        if anomaly:
            anomalies.append(anomaly)
        if severity_rank[tier] > severity_rank[worst_severity]:
            worst_severity = tier

    cpu = python_metrics.get("cpu_percent")
    cpu_tier = _tier(cpu, **THRESHOLDS["cpu_percent"])
    flag(
        "cpu_percent",
        cpu_tier,
        f"CPU usage is {cpu:.1f}%." if cpu is not None else "CPU usage unavailable.",
        "Check the Processes page for runaway or long-running processes consuming CPU.",
        anomaly=f"Sustained high CPU usage ({cpu:.1f}%)" if cpu_tier == "critical" else None,
    )

    mem = python_metrics.get("memory_percent")
    mem_tier = _tier(mem, **THRESHOLDS["memory_percent"])
    flag(
        "memory_percent",
        mem_tier,
        f"Memory usage is {mem:.1f}%." if mem is not None else "Memory usage unavailable.",
        "Review process memory consumption and consider whether global buffer or gmheap settings need adjustment.",
        anomaly=f"Sustained high memory usage ({mem:.1f}%)" if mem_tier == "critical" else None,
    )

    lic_used = iris_metrics.get("license_used")
    lic_limit = iris_metrics.get("license_limit")
    if lic_used is not None and lic_limit:
        ratio = lic_used / lic_limit
        lic_tier = _tier(ratio, **THRESHOLDS["license_ratio"])
        flag(
            "license_ratio",
            lic_tier,
            f"License usage is {lic_used}/{lic_limit} ({ratio * 100:.0f}%).",
            "Review active connections on the Dashboard and consider licensing headroom before it's exhausted.",
            anomaly="License usage near capacity" if lic_tier == "critical" else None,
        )

    failed_tasks = iris_metrics.get("failed_tasks_24h")
    if failed_tasks:
        tier = "critical" if failed_tasks >= 3 else "warning"
        flag(
            "failed_tasks_24h",
            tier,
            f"{failed_tasks} task(s) failed in the last 24 hours.",
            "Review Task History on the Tasks page to diagnose the failure(s).",
        )

    serious_alerts = iris_metrics.get("serious_audit_alerts")
    if serious_alerts:
        tier = "critical" if serious_alerts >= 3 else "warning"
        flag(
            "serious_audit_alerts",
            tier,
            f"{serious_alerts} serious audit alert(s) reported.",
            "Review the Audit tab on the Security page for details.",
        )

    smh_used = iris_metrics.get("shared_memory_used_pages")
    smh_total = iris_metrics.get("shared_memory_allocated_pages")
    if smh_used is not None and smh_total:
        pct = (smh_used / smh_total) * 100
        smh_tier = _tier(pct, **THRESHOLDS["shared_memory_percent"])
        flag(
            "shared_memory_percent",
            smh_tier,
            f"Shared memory usage is {pct:.0f}%.",
            "Review shared memory allocation on the Dashboard's Shared Memory card.",
        )

    near_full = iris_metrics.get("databases_near_full") or []
    if near_full:
        tier = "critical" if len(near_full) >= 2 else "warning"
        flag(
            "databases_near_full",
            tier,
            f"{len(near_full)} database(s) near their size limit: {', '.join(near_full)}.",
            "Review database sizing on the Databases page and expand or compact as needed.",
        )

    score = max(0, min(100, score))
    if score >= STATUS_THRESHOLDS["healthy"]:
        status = "healthy"
    elif score >= STATUS_THRESHOLDS["warning"]:
        status = "warning"
    else:
        status = "critical"

    return {
        "score": score,
        "status": status,
        "severity": worst_severity,
        "warnings": warnings,
        "recommendations": recommendations,
        "anomalies": anomalies,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def gather_python_metrics() -> dict[str, Any]:
    """The one function in this module that touches psutil. Isolated so
    `analyze()` above never needs psutil (or an IRIS process) to be tested."""
    import psutil

    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "memory_percent": vm.percent,
        "memory_total_bytes": vm.total,
        "memory_available_bytes": vm.available,
    }


def gather_and_analyze(iris_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """IRIS-side entry point: real psutil metrics + caller-supplied IRIS
    metrics, scored. This is what iris/classes/ISOE/HealthAnalyzer.cls calls."""
    python_metrics = gather_python_metrics()
    result = analyze(python_metrics, iris_metrics)
    result["pythonMetrics"] = python_metrics
    return result
