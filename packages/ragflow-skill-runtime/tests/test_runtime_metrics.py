from __future__ import annotations

import unittest

from ragflow_skill_runtime import (
    RUNTIME_METRICS_SCHEMA,
    RuntimeMetrics,
    build_runtime_metrics_summary,
    latency_summary_ms,
    normalize_stage_timing,
    throughput_summary,
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
            throughput={
                "upload": throughput_summary(item_count=4, duration_ms=2000, unit="document"),
            },
        )

        self.assertEqual(report["schema"], "ragflow_runtime_metrics_v1")
        self.assertEqual(list(report["counters"]), ["a", "b"])
        self.assertEqual(report["gauges"]["ratio"], 0.25)
        self.assertEqual(report["latency_ms"]["average"], 10.0)
        self.assertEqual(report["summary"]["throughput_stage_count"], 1)
        self.assertEqual(report["throughput"]["upload"]["unit"], "document")
        self.assertEqual(report["throughput"]["upload"]["item_count"], 4)
        self.assertEqual(report["throughput"]["upload"]["duration_ms"], 2000.0)
        self.assertEqual(report["throughput"]["upload"]["items_per_second"], 2.0)
        self.assertEqual(report["throughput"]["upload"]["ms_per_item"], 500.0)

    def test_runtime_metrics_standardizes_stage_timings(self) -> None:
        normalized = normalize_stage_timing(
            {
                "stage": "package",
                "operation": "rich_handoff_package",
                "duration_ms": 12.3456,
                "status": "success",
                "timing_source": "unit-test",
            }
        )

        self.assertEqual(normalized["stage"], "package")
        self.assertEqual(normalized["standard_stage"], "packaging")
        self.assertEqual(normalized["category"], "conversion")
        self.assertEqual(normalized["duration_ms"], 12.346)

        report = build_runtime_metrics_summary(
            "stage-summary-test",
            stage_timings=[
                {"stage": "markdown_upload", "operation": "upload", "duration_ms": 30},
                {"stage": "image_upload", "operation": "upload", "duration_ms": 40},
                {"stage": "wait_parse", "operation": "poll", "duration_ms": 50},
                {"stage": "validate", "operation": "benchmark", "duration_ms": 60},
                {"stage": "retrieval", "operation": "query", "duration_ms": 70, "included_in_stage": "query"},
                {"stage": "cleanup", "operation": "preview", "duration_ms": None},
            ],
        )

        self.assertEqual(report["summary"]["stage_timing_count"], 6)
        self.assertEqual(report["summary"]["stage_timing_known_duration_ms"], 250.0)
        self.assertEqual(report["summary"]["stage_timing_counts_by_standard_stage"]["parse_wait"], 1)
        standard_stages = {item["standard_stage"] for item in report["stage_timings"]}
        self.assertTrue({"markdown_upload", "image_upload", "parse_wait", "validation", "query", "cleanup"}.issubset(standard_stages))

    def test_throughput_summary_handles_zero_duration_without_dividing(self) -> None:
        summary = throughput_summary(item_count=3, duration_ms=0, unit="image")

        self.assertEqual(summary["unit"], "image")
        self.assertEqual(summary["item_count"], 3)
        self.assertEqual(summary["duration_ms"], 0.0)
        self.assertIsNone(summary["items_per_second"])
        self.assertIsNone(summary["ms_per_item"])


if __name__ == "__main__":
    unittest.main()
