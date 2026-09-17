"""Unit tests for health_analyzer.analyze() — the pure scoring logic.

Runs with a plain stdlib interpreter, no IRIS or psutil required:

    python -m unittest discover -s iris/python/tests -v

(or, from iris/python/: python -m unittest tests.test_health_analyzer -v)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health_analyzer import analyze  # noqa: E402


HEALTHY_PYTHON_METRICS = {
    "cpu_percent": 12.0,
    "memory_percent": 40.0,
    "memory_total_bytes": 8_000_000_000,
    "memory_available_bytes": 4_800_000_000,
}


class AnalyzeHealthyCaseTests(unittest.TestCase):
    def test_all_metrics_nominal_yields_healthy_status_and_full_score(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {})
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["severity"], "none")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["anomalies"], [])

    def test_missing_iris_metrics_does_not_crash_or_flag_anything(self):
        result = analyze(HEALTHY_PYTHON_METRICS, None)
        self.assertEqual(result["status"], "healthy")


class CpuAndMemoryTierTests(unittest.TestCase):
    def test_cpu_warning_tier_deducts_points_without_reaching_critical(self):
        metrics = {**HEALTHY_PYTHON_METRICS, "cpu_percent": 80.0}
        result = analyze(metrics, {})
        self.assertEqual(result["score"], 88)  # 100 - 12
        self.assertEqual(result["severity"], "warning")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["metric"], "cpu_percent")

    def test_cpu_critical_tier_deducts_more_and_raises_an_anomaly(self):
        metrics = {**HEALTHY_PYTHON_METRICS, "cpu_percent": 95.0}
        result = analyze(metrics, {})
        self.assertEqual(result["score"], 72)  # 100 - 28
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["status"], "warning")  # 72 is still >= 60
        self.assertEqual(len(result["anomalies"]), 1)

    def test_memory_critical_pushes_status_to_critical_when_combined_with_cpu(self):
        metrics = {**HEALTHY_PYTHON_METRICS, "cpu_percent": 95.0, "memory_percent": 95.0}
        result = analyze(metrics, {})
        self.assertEqual(result["score"], 44)  # 100 - 28 - 28
        self.assertEqual(result["status"], "critical")
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(len(result["warnings"]), 2)


class IrisMetricsTests(unittest.TestCase):
    def test_license_ratio_computed_correctly_and_flagged_at_critical_threshold(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"license_used": 96, "license_limit": 100})
        self.assertEqual(result["severity"], "critical")
        self.assertIn("96/100", result["warnings"][0]["message"])

    def test_license_ratio_below_threshold_is_not_flagged(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"license_used": 50, "license_limit": 100})
        self.assertEqual(result["warnings"], [])

    def test_zero_license_limit_does_not_raise_division_by_zero(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"license_used": 0, "license_limit": 0})
        self.assertEqual(result["status"], "healthy")

    def test_failed_tasks_below_three_is_warning_at_or_above_is_critical(self):
        warning_result = analyze(HEALTHY_PYTHON_METRICS, {"failed_tasks_24h": 1})
        critical_result = analyze(HEALTHY_PYTHON_METRICS, {"failed_tasks_24h": 3})
        self.assertEqual(warning_result["warnings"][0]["severity"], "warning")
        self.assertEqual(critical_result["warnings"][0]["severity"], "critical")

    def test_serious_audit_alerts_flagged_with_recommendation(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"serious_audit_alerts": 2})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("Security page", result["recommendations"][0])

    def test_shared_memory_percent_computed_from_used_and_allocated_pages(self):
        result = analyze(
            HEALTHY_PYTHON_METRICS,
            {"shared_memory_used_pages": 950, "shared_memory_allocated_pages": 1000},
        )
        self.assertEqual(result["severity"], "critical")

    def test_databases_near_full_lists_names_in_message(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"databases_near_full": ["USER", "ENSLIB"]})
        self.assertIn("USER", result["warnings"][0]["message"])
        self.assertIn("ENSLIB", result["warnings"][0]["message"])
        self.assertEqual(result["warnings"][0]["severity"], "critical")  # 2 dbs >= 2

    def test_single_database_near_full_is_only_a_warning(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"databases_near_full": ["USER"]})
        self.assertEqual(result["warnings"][0]["severity"], "warning")

    def test_empty_databases_near_full_list_is_not_flagged(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {"databases_near_full": []})
        self.assertEqual(result["warnings"], [])


class ResponseShapeTests(unittest.TestCase):
    def test_result_always_has_all_expected_keys(self):
        result = analyze(HEALTHY_PYTHON_METRICS, {})
        for key in ("score", "status", "severity", "warnings", "recommendations", "anomalies", "checkedAt"):
            self.assertIn(key, result)

    def test_score_never_goes_below_zero_even_with_every_metric_critical(self):
        result = analyze(
            {"cpu_percent": 100, "memory_percent": 100, "memory_total_bytes": 1, "memory_available_bytes": 0},
            {
                "license_used": 100,
                "license_limit": 100,
                "failed_tasks_24h": 10,
                "serious_audit_alerts": 10,
                "shared_memory_used_pages": 100,
                "shared_memory_allocated_pages": 100,
                "databases_near_full": ["A", "B", "C"],
            },
        )
        self.assertGreaterEqual(result["score"], 0)
        self.assertEqual(result["status"], "critical")


if __name__ == "__main__":
    unittest.main()
