from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.validation import (
    BenchmarkGate,
    ValidationQuery,
    attach_benchmark_evaluation,
    evaluate_query_result,
    load_benchmark_gate,
    load_benchmark_qrels,
    load_validation_queries,
    render_markdown_report,
    run_retrieval_validation,
)
from ragflow_skill_runtime.retrieval import normalize_retrieval_response


class FakeValidationClient:
    def retrieve(self, *, question, dataset_ids, top_k=3):
        return {
            "data": {
                "chunks": [
                    {
                        "content_with_weight": f"{question} answer contains known term",
                        "docnm_kwd": "source.md",
                        "similarity": 0.9,
                    }
                ]
            }
        }


class ValidationTests(unittest.TestCase):
    def test_load_validation_queries_from_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.json"
            path.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "What is known?",
                                "expected_terms": ["known"],
                                "expected_documents": ["source.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            queries = load_validation_queries(path)

        self.assertEqual(queries[0].id, "q1")
        self.assertEqual(queries[0].expected_terms, ["known"])

    def test_evaluate_query_result_reports_missing_terms(self) -> None:
        query = ValidationQuery(
            id="q1",
            question="Question",
            expected_terms=["present", "missing"],
            expected_documents=["source.md"],
        )
        chunks = normalize_retrieval_response(
            {"data": {"chunks": [{"content": "present body", "document_name": "source.md"}]}}
        )
        result = evaluate_query_result(query, chunks)

        self.assertFalse(result.passed)
        self.assertEqual(result.term_hits, ["present"])
        self.assertEqual(result.missing_terms, ["missing"])

    def test_run_retrieval_validation_metrics(self) -> None:
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="regression",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[
                ValidationQuery(
                    id="q1",
                    question="Known",
                    expected_terms=["known term"],
                    expected_documents=["source.md"],
                )
            ],
            top_k=3,
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.metrics()["pass_rate"], 1.0)
        self.assertIn("q1", render_markdown_report(report))

    def test_load_benchmark_qrels_from_explicit_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qrels.json"
            path.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {"query_id": "q1", "document": "source.md", "relevance": 2},
                            {"query_id": "q1", "chunk_id": "chunk-1", "relevance": 1},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels = load_benchmark_qrels(path)

        self.assertEqual(len(qrels["q1"]), 2)
        self.assertEqual(qrels["q1"][1].field, "chunk_id")

    def test_load_benchmark_qrels_from_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qrels.json"
            path.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            qrels = load_benchmark_qrels(path)

        self.assertEqual(qrels["q1"][0].target, "source.md")

    def test_benchmark_metrics_and_gate(self) -> None:
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[
                ValidationQuery(
                    id="q1",
                    question="Known",
                    expected_terms=["known term"],
                    expected_documents=["source.md"],
                    metadata={"type": "fact"},
                )
            ],
            top_k=3,
        )
        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={"q1": load_benchmark_qrels_dict_item("source.md")},
            cutoff=3,
            gate=BenchmarkGate(min_hit_rate=1.0, min_mrr=1.0, max_empty_result_rate=0.0),
            baseline_metrics={"mrr": 0.5, "hit_rate": 1.0},
            baseline_path="baseline.json",
        )
        payload = benchmarked.to_dict()
        benchmark = payload["benchmark"]

        self.assertTrue(benchmarked.ok)
        self.assertEqual(benchmark["metrics"]["hit_rate"], 1.0)
        self.assertAlmostEqual(benchmark["metrics"]["mrr"], 1.0)
        self.assertAlmostEqual(benchmark["metrics"]["precision_at_k"], 1 / 3)
        self.assertEqual(benchmark["query_type_breakdown"]["fact"]["query_count"], 1)
        self.assertTrue(benchmark["gate"]["ok"])
        self.assertEqual(benchmark["baseline"]["delta"]["mrr"], 0.5)
        self.assertIn("## Benchmark", render_markdown_report(benchmarked))

    def test_benchmark_gate_failure_marks_report_failed(self) -> None:
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[ValidationQuery(id="q1", question="Known")],
            top_k=3,
        )
        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={"q1": load_benchmark_qrels_dict_item("missing.md")},
            cutoff=3,
            gate=BenchmarkGate(min_hit_rate=1.0),
        )

        self.assertFalse(benchmarked.ok)
        self.assertFalse(benchmarked.benchmark.gate["ok"])

    def test_load_benchmark_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            path.write_text(
                json.dumps({"thresholds": {"min_hit_rate": 0.8, "max_mrr_drop": 0.1}}),
                encoding="utf-8",
            )
            gate = load_benchmark_gate(path)

        self.assertEqual(gate.min_hit_rate, 0.8)
        self.assertEqual(gate.max_mrr_drop, 0.1)


def load_benchmark_qrels_dict_item(target: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "qrels.json"
        path.write_text(json.dumps({"q1": {target: 1}}), encoding="utf-8")
        return load_benchmark_qrels(path)["q1"]


if __name__ == "__main__":
    unittest.main()
