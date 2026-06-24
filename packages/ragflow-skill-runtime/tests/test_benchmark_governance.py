from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.benchmark_governance import (
    BENCHMARK_DELTA_REPORT_SCHEMA,
    BENCHMARK_GATE_REPORT_SCHEMA,
    BENCHMARK_IMPORT_REPORT_SCHEMA,
    BENCHMARK_PREFLIGHT_REPORT_SCHEMA,
    BENCHMARK_SAMPLE_REPORT_SCHEMA,
    BENCHMARK_SUMMARY_REPORT_SCHEMA,
    BENCHMARK_TREND_REPORT_SCHEMA,
    CHUNK_SNAPSHOT_REPORT_SCHEMA,
    delta_benchmark_reports,
    gate_benchmark_report,
    import_benchmark_dataset,
    preflight_benchmark_dataset,
    sample_benchmark_dataset,
    snapshot_chunks,
    summarize_benchmark_report,
    trend_benchmark_reports,
)


class BenchmarkGovernanceTests(unittest.TestCase):
    def test_import_and_preflight_benchmark_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            output = root / "benchmark"
            queries.write_text(
                json.dumps({"queries": [{"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}}]}),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")

            import_report = import_benchmark_dataset(
                queries_path=queries,
                qrels_path=qrels,
                output_dir=output,
                name="example-benchmark",
            )
            preflight = preflight_benchmark_dataset(manifest_path=output / "manifest.json")

        self.assertEqual(import_report["schema"], BENCHMARK_IMPORT_REPORT_SCHEMA)
        self.assertTrue(import_report["ok"])
        self.assertEqual(import_report["summary"]["query_count"], 1)
        self.assertEqual(preflight["schema"], BENCHMARK_PREFLIGHT_REPORT_SCHEMA)
        self.assertTrue(preflight["ok"], preflight["issues"])

    def test_snapshot_chunks_from_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "validation_report.json"
            snapshot_path = root / "chunk_snapshot.json"
            report_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "q1",
                                "top_chunks": [
                                    {
                                        "content": "Expected evidence body",
                                        "document_name": "source.md",
                                        "chunk_id": "chunk-a",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = snapshot_chunks(input_path=report_path, output_path=snapshot_path)
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], CHUNK_SNAPSHOT_REPORT_SCHEMA)
        self.assertEqual(snapshot["schema"], "ragflow_chunk_snapshot_v1")
        self.assertEqual(snapshot["summary"]["chunk_count"], 1)
        self.assertTrue(snapshot["chunks"][0]["stable_hash"].startswith("sha256:"))
        self.assertIn("chunk-a", snapshot["chunks"][0]["aliases"])

    def test_sample_benchmark_dataset_is_deterministic_and_filters_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            imported = root / "benchmark"
            sampled = root / "sampled"
            sampled_again = root / "sampled-again"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {"id": "q1", "question": "Fact one?", "metadata": {"type": "fact"}},
                            {"id": "q2", "question": "Fact two?", "metadata": {"type": "fact"}},
                            {"id": "q3", "question": "How to compare?", "metadata": {"type": "comparison"}},
                            {"id": "q4", "question": "How to troubleshoot?", "metadata": {"type": "diagnostic"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps(
                    {
                        "q1": {"one.md": 1},
                        "q2": {"two.md": 1},
                        "q3": {"three.md": 1},
                        "q4": {"four.md": 1},
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {"query_id": "q1", "answer": "one"},
                            {"query_id": "q2", "answer": "two"},
                            {"query_id": "q3", "answer": "three"},
                            {"query_id": "q4", "answer": "four"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            import_benchmark_dataset(queries_path=queries, qrels_path=qrels, qa_path=qa, output_dir=imported)

            sample = sample_benchmark_dataset(
                manifest_path=imported / "manifest.json",
                output_dir=sampled,
                sample_size=3,
                strategy="stratified",
                seed=7,
            )
            sample_again = sample_benchmark_dataset(
                manifest_path=imported / "manifest.json",
                output_dir=sampled_again,
                sample_size=3,
                strategy="stratified",
                seed=7,
            )
            sampled_queries = json.loads((sampled / "queries.json").read_text(encoding="utf-8"))
            sampled_qrels = json.loads((sampled / "qrels.json").read_text(encoding="utf-8"))
            sampled_qa = json.loads((sampled / "qa.json").read_text(encoding="utf-8"))
            manifest = json.loads((sampled / "manifest.json").read_text(encoding="utf-8"))

        selected_ids = [query["id"] for query in sampled_queries["queries"]]
        self.assertEqual(sample["schema"], BENCHMARK_SAMPLE_REPORT_SCHEMA)
        self.assertEqual(sample["sampling"]["selected_query_ids"], sample_again["sampling"]["selected_query_ids"])
        self.assertEqual(len(selected_ids), 3)
        self.assertEqual(set(sampled_qrels["qrels"][index]["query_id"] for index in range(len(sampled_qrels["qrels"]))), set(selected_ids))
        self.assertEqual(set(item["query_id"] for item in sampled_qa["items"]), set(selected_ids))
        self.assertEqual(manifest["sampling"]["strategy"], "stratified")
        self.assertEqual(manifest["sampling"]["seed"], 7)

    def test_preflight_fails_when_query_has_no_qrels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "Missing qrel?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q2": {"source.md": 1}}), encoding="utf-8")

            report = preflight_benchmark_dataset(queries_path=queries, qrels_path=qrels)

        self.assertFalse(report["ok"])
        self.assertIn("query_without_qrels", {issue["code"] for issue in report["issues"]})

    def test_summarize_and_gate_existing_benchmark_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "benchmark_report.json"
            gate_path = root / "gate.json"
            report_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            },
                            "query_type_breakdown": {"fact": {"query_count": 1, "hit_rate": 1.0}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate_path.write_text(json.dumps({"thresholds": {"min_hit_rate": 1.0, "max_empty_result_rate": 0.0}}), encoding="utf-8")

            summary = summarize_benchmark_report(report_path)
            gate = gate_benchmark_report(report_path=report_path, gate_config_path=gate_path)

        self.assertEqual(summary["schema"], BENCHMARK_SUMMARY_REPORT_SCHEMA)
        self.assertTrue(summary["ok"])
        self.assertEqual(gate["schema"], BENCHMARK_GATE_REPORT_SCHEMA)
        self.assertTrue(gate["ok"], gate["gate"])

    def test_summarize_reports_root_cause_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "benchmark_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "query_count": 2,
                                "hit_rate": 0.5,
                                "mrr": 0.25,
                                "precision_at_k": 0.2,
                                "recall_at_k": 0.5,
                                "ndcg_at_k": 0.3,
                                "map_at_k": 0.25,
                                "empty_result_rate": 0.5,
                                "supporting_document_coverage": 0.5,
                                "tag_pollution_rate": 0.2,
                                "grounded_answer_rate": 0.7,
                                "citation_coverage": 0.4,
                                "over_abstention_rate": 0.1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_benchmark_report(report_path)

        hint_codes = {hint["code"] for hint in summary["quality_hints"]}
        self.assertIn("retrieval_coverage_gap", hint_codes)
        self.assertIn("ranking_gap", hint_codes)
        self.assertIn("tag_pollution", hint_codes)
        self.assertIn("generation_grounding_gap", hint_codes)
        self.assertIn("citation_gap", hint_codes)
        self.assertIn("over_abstention", hint_codes)

    def test_trend_and_delta_reports_compare_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            gate = root / "gate.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 0.8,
                                "precision_at_k": 0.4,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.8,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate.write_text(json.dumps({"thresholds": {"min_mrr": 0.9, "max_mrr_drop": 0.05}}), encoding="utf-8")

            trend = trend_benchmark_reports(
                current_report_path=current,
                baseline_report_path=baseline,
                gate_config_path=gate,
            )
            delta = delta_benchmark_reports(current_report_path=current, baseline_report_path=baseline)

        self.assertEqual(trend["schema"], BENCHMARK_TREND_REPORT_SCHEMA)
        self.assertTrue(trend["ok"], trend["gate"])
        self.assertAlmostEqual(trend["delta"]["mrr"]["absolute"], 0.2)
        self.assertEqual(delta["schema"], BENCHMARK_DELTA_REPORT_SCHEMA)
        self.assertIn("mrr", delta["summary"]["improved"])

    def test_trend_and_delta_reports_root_cause_regression_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 0.9,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.9,
                                "empty_result_rate": 0.0,
                                "tag_pollution_rate": 0.0,
                                "grounded_answer_rate": 1.0,
                                "citation_coverage": 1.0,
                                "over_abstention_rate": 0.0,
                                "average_latency_ms": 100.0,
                                "estimated_cost_usd": 0.01,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 0.8,
                                "mrr": 0.6,
                                "recall_at_k": 0.8,
                                "ndcg_at_k": 0.6,
                                "map_at_k": 0.6,
                                "empty_result_rate": 0.1,
                                "tag_pollution_rate": 0.2,
                                "grounded_answer_rate": 0.6,
                                "citation_coverage": 0.5,
                                "over_abstention_rate": 0.2,
                                "average_latency_ms": 250.0,
                                "estimated_cost_usd": 0.03,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            trend = trend_benchmark_reports(current_report_path=current, baseline_report_path=baseline)
            delta = delta_benchmark_reports(current_report_path=current, baseline_report_path=baseline)

        trend_codes = {hint["code"] for hint in trend["quality_hints"]}
        delta_codes = {hint["code"] for hint in delta["quality_hints"]}
        for code in {
            "retrieval_coverage_gap",
            "ranking_gap",
            "tag_pollution",
            "generation_grounding_gap",
            "citation_gap",
            "over_abstention",
            "cost_or_latency_regression",
        }:
            self.assertIn(code, trend_codes)
            self.assertIn(code, delta_codes)


if __name__ == "__main__":
    unittest.main()
