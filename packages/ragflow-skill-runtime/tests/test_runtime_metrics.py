from __future__ import annotations

import unittest

from ragflow_skill_runtime import (
    RUNTIME_METRICS_SCHEMA,
    RuntimeMetrics,
    build_runtime_metrics_summary,
    latency_summary_ms,
)


class RuntimeMetricsTests(unittest.TestCase):
    def test_latency_summary_uses_nearest_rank_percentiles(self) -> None:
        summary = latency_summary_ms([50, 10, 40, 30, 20])

        self.assertEqual(summary["sample_count"], 5)
        self.assertEqual(summary["min"], 10.0)
        self.assertEqual(summary["max"], 50.0)
        self.assertEqual(summary["average"], 30.0)
        self.assertEqual(summary["p50"], 30.0)
        self.assertEqual(summary["p95"], 50.0)
        self.assertEqual(summary["p99"], 50.0)

    def test_latency_summary_handles_empty_samples(self) -> None:
        summary = latency_summary_ms([])

        self.assertEqual(summary["sample_count"], 0)
        self.assertIsNone(summary["p50"])
        self.assertIsNone(summary["p95"])
        self.assertIsNone(summary["p99"])

    def test_runtime_metrics_report_collects_counters_gauges_and_latency(self) -> None:
        metrics = RuntimeMetrics(operation="unit-test")
        metrics.increment_counter("requests", 2)
        metrics.increment_counter("requests")
        metrics.set_gauge("success_ratio", 2 / 3)
        metrics.observe_latency_ms(12.3456)
        metrics.observe_latency_ms(20)

        report = metrics.to_report()

        self.assertEqual(report["schema"], RUNTIME_METRICS_SCHEMA)
        self.assertEqual(report["operation"], "unit-test")
        self.assertEqual(report["counters"]["requests"], 3)
        self.assertEqual(report["gauges"]["success_ratio"], 0.667)
        self.assertEqual(report["latency_ms"]["sample_count"], 2)
        self.assertEqual(report["latency_ms"]["p50"], 12.346)
        self.assertEqual(report["latency_ms"]["p95"], 20.0)
        self.assertEqual(report["summary"]["counter_count"], 1)
        self.assertEqual(report["summary"]["gauge_count"], 1)

    def test_build_runtime_metrics_summary_is_json_stable(self) -> None:
        report = build_runtime_metrics_summary(
            "summary-test",
            counters={"b": 2, "a": 1},
            gauges={"ratio": 0.25},
            latency_samples_ms=[5, 15],
        )

        self.assertEqual(report["schema"], "ragflow_runtime_metrics_v1")
        self.assertEqual(list(report["counters"]), ["a", "b"])
        self.assertEqual(report["gauges"]["ratio"], 0.25)
        self.assertEqual(report["latency_ms"]["average"], 10.0)


if __name__ == "__main__":
    unittest.main()
