from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.validation import (
    BenchmarkGate,
    CHUNK_SNAPSHOT_SCHEMA,
    ValidationCaseResult,
    ValidationQuery,
    ValidationReport,
    attach_benchmark_evaluation,
    evaluate_query_result,
    load_benchmark_gate,
    load_benchmark_qrels,
    load_validation_queries,
    render_markdown_report,
    run_retrieval_validation,
)
from ragflow_skill_runtime.retrieval import stable_chunk_hash, normalize_retrieval_response


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

    def test_validation_report_raw_chunks_are_opt_in(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content_with_weight": "Known answer with policy tag.",
                            "docnm_kwd": "source.md",
                            "id": "chunk-a",
                            "tags": ["policy"],
                        }
                    ]
                }
            }
        )
        report = ValidationReport(
            level="regression",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(id="q1", question="Known?"),
                    passed=True,
                    chunk_count=1,
                    chunks=chunks,
                )
            ],
        )

        default_payload = report.to_dict()
        raw_payload = report.to_dict(include_raw=True)

        self.assertNotIn("raw", default_payload["cases"][0]["top_chunks"][0])
        self.assertEqual(raw_payload["cases"][0]["top_chunks"][0]["raw"]["tags"], ["policy"])

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

    def test_load_benchmark_qrels_with_expected_chunks_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qrels.json"
            path.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {
                                "query_id": "q1",
                                "expected_documents": ["source.md"],
                                "expected_chunks": ["sha256:abc"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels = load_benchmark_qrels(path)

        self.assertEqual([qrel.field for qrel in qrels["q1"]], ["document", "expected_chunk"])
        self.assertEqual(qrels["q1"][1].target, "sha256:abc")

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

    def test_benchmark_strict_chunk_recall_matches_stable_hash_snapshot(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "Expected evidence body",
                            "document_name": "source.md",
                            "chunk_id": "live-chunk-2",
                        }
                    ]
                }
            }
        )
        expected_hash = stable_chunk_hash(chunks[0])
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[ValidationQuery(id="q1", question="Known")],
            top_k=3,
        )
        report = type(report)(
            level=report.level,
            dataset_id=report.dataset_id,
            dataset_name=report.dataset_name,
            cases=[
                type(report.cases[0])(
                    query=report.cases[0].query,
                    passed=True,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )
        chunk_snapshot = {
            "schema": CHUNK_SNAPSHOT_SCHEMA,
            "chunks": [
                {
                    "stable_hash": expected_hash,
                    "chunk_id": "original-chunk-1",
                    "aliases": [expected_hash, "original-chunk-1"],
                }
            ],
        }

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q1": [
                    *load_benchmark_qrels_dict_item("source.md"),
                    *load_benchmark_qrels_dict_item("original-chunk-1", field="expected_chunk"),
                ]
            },
            cutoff=3,
            gate=BenchmarkGate(min_strict_chunk_recall_at_k=1.0, min_expected_chunk_hit_rate=1.0),
            chunk_snapshot=chunk_snapshot,
        )
        benchmark = benchmarked.to_dict()["benchmark"]

        self.assertTrue(benchmarked.ok)
        self.assertEqual(benchmark["metrics"]["recall_at_k"], 1.0)
        self.assertEqual(benchmark["metrics"]["strict_chunk_recall_at_k"], 1.0)
        self.assertEqual(benchmark["metrics"]["expected_chunk_hit_rate"], 1.0)
        self.assertEqual(benchmark["per_query"][0]["matched_expected_chunks"], 1)
        self.assertTrue(benchmark["gate"]["ok"])

    def test_benchmark_reports_pollution_and_tag_metrics(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "Expected evidence body",
                            "document_name": "source.md",
                            "tags": ["policy"],
                        },
                        {
                            "content": "Unrelated evidence body",
                            "document_name": "other.md",
                            "metadata": {"tags": ["finance"]},
                        },
                    ]
                }
            }
        )
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[
                ValidationQuery(
                    id="q1",
                    question="Known",
                    expected_documents=["source.md"],
                    metadata={"type": "fact", "expected_tags": ["policy"], "allowed_tags": ["policy"]},
                )
            ],
            top_k=2,
        )
        report = type(report)(
            level=report.level,
            dataset_id=report.dataset_id,
            dataset_name=report.dataset_name,
            cases=[
                type(report.cases[0])(
                    query=report.cases[0].query,
                    passed=True,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={"q1": load_benchmark_qrels_dict_item("source.md")},
            cutoff=2,
        )
        benchmark = benchmarked.to_dict()["benchmark"]
        metrics = benchmark["metrics"]
        per_query = benchmark["per_query"][0]
        markdown = render_markdown_report(benchmarked)

        self.assertEqual(metrics["wrong_document_rate"], 0.5)
        self.assertEqual(metrics["tag_pollution_rate"], 0.5)
        self.assertEqual(metrics["expected_tag_hit_rate"], 1.0)
        self.assertEqual(metrics["unexpected_tag_hit_rate"], 1.0)
        self.assertEqual(metrics["wrong_document_count"], 1)
        self.assertEqual(metrics["polluted_tagged_chunk_count"], 1)
        self.assertEqual(metrics["unexpected_tag_count"], 1)
        self.assertEqual(per_query["wrong_document_count"], 1)
        self.assertEqual(per_query["unexpected_tag_count"], 1)
        self.assertIn("Wrong-document rate", markdown)
        self.assertIn("Tag pollution rate", markdown)

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


def load_benchmark_qrels_dict_item(target: str, *, field: str = "document"):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "qrels.json"
        if field == "document":
            path.write_text(json.dumps({"q1": {target: 1}}), encoding="utf-8")
        else:
            path.write_text(
                json.dumps({"qrels": [{"query_id": "q1", "target": target, "field": field}]}),
                encoding="utf-8",
            )
        return load_benchmark_qrels(path)["q1"]


if __name__ == "__main__":
    unittest.main()
