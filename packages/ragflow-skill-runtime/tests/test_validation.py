from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.validation import (
    BenchmarkGate,
    CHUNK_SNAPSHOT_SCHEMA,
    MULTIMODAL_BENCHMARK_CATEGORIES,
    MULTIMODAL_BENCHMARK_SCHEMA,
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


class PartialFailureValidationClient(FakeValidationClient):
    def retrieve(self, *, question, dataset_ids, top_k=3):
        if "Timeout" in question:
            raise TimeoutError("timed out retrieving chunks")
        return super().retrieve(question=question, dataset_ids=dataset_ids, top_k=top_k)


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

    def test_validation_report_marks_semantic_failures_as_runtime_warnings(self) -> None:
        report = run_retrieval_validation(
            FakeValidationClient(),
            level="regression",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[
                ValidationQuery(
                    id="q-missing",
                    question="Known",
                    expected_terms=["not returned"],
                    expected_documents=["source.md"],
                )
            ],
            top_k=3,
        )
        payload = report.to_dict()

        self.assertFalse(report.ok)
        self.assertEqual(payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "completed_with_warnings")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["warning_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["failure_count"], 0)
        self.assertEqual(payload["metrics"]["runtime_partial_failure_status"], "completed_with_warnings")
        self.assertIn("runtime_partial_failure_status: `completed_with_warnings`", render_markdown_report(report))

    def test_validation_report_marks_client_timeouts_as_partial_failures(self) -> None:
        report = run_retrieval_validation(
            PartialFailureValidationClient(),
            level="regression",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[
                ValidationQuery(
                    id="q-ok",
                    question="Known",
                    expected_terms=["known term"],
                    expected_documents=["source.md"],
                ),
                ValidationQuery(id="q-timeout", question="Timeout please"),
            ],
            top_k=3,
        )
        payload = report.to_dict()

        self.assertFalse(report.ok)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["timeout_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["status_counts"]["timeout"], 1)
        self.assertEqual(payload["metrics"]["runtime_timeout_count"], 1)
        self.assertIn("runtime_partial_failure_status: `partial`", render_markdown_report(report))

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

    def test_load_benchmark_qrels_preserves_multimodal_metadata_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qrels.json"
            path.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {
                                "query_id": "q-image",
                                "expected_documents": ["diagram.png"],
                                "expected_chunks": ["sha256:abc"],
                                "expected_modality": "image",
                                "benchmark_category": "visual_identification",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels = load_benchmark_qrels(path)

        self.assertEqual([qrel.field for qrel in qrels["q-image"]], ["document", "expected_chunk"])
        self.assertEqual(qrels["q-image"][0].metadata["expected_modality"], "image")
        self.assertEqual(qrels["q-image"][1].metadata["benchmark_category"], "visual_identification")

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

    def test_benchmark_without_gate_reports_not_configured_status(self) -> None:
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
            qrels={"q1": load_benchmark_qrels_dict_item("source.md")},
            cutoff=3,
        )
        payload = benchmarked.to_dict()
        gate = payload["benchmark"]["gate"]

        self.assertTrue(benchmarked.ok)
        self.assertEqual(gate["status"], "not_configured")
        self.assertFalse(gate["configured"])
        self.assertTrue(gate["ok"])
        self.assertIsNone(gate["failure_type"])
        self.assertEqual(gate["checks"], [])
        self.assertEqual(payload["status"]["failure_type"], None)
        self.assertEqual(payload["status"]["benchmark_gate_status"], "not_configured")

    def test_benchmark_gate_status_reports_passed_and_strict_threshold_failure(self) -> None:
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
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(id="q1", question="Known"),
                    passed=True,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )

        passed = attach_benchmark_evaluation(
            report,
            qrels={"q1": load_benchmark_qrels_dict_item("source.md")},
            cutoff=3,
            gate=BenchmarkGate(min_hit_rate=1.0),
        )
        failed = attach_benchmark_evaluation(
            report,
            qrels={
                "q1": [
                    *load_benchmark_qrels_dict_item("source.md"),
                    *load_benchmark_qrels_dict_item("missing-stable-hash", field="expected_chunk"),
                ]
            },
            cutoff=3,
            gate=BenchmarkGate(min_strict_chunk_recall_at_k=1.0),
        )

        passed_gate = passed.to_dict()["benchmark"]["gate"]
        failed_payload = failed.to_dict()
        failed_gate = failed_payload["benchmark"]["gate"]

        self.assertEqual(passed_gate["status"], "passed")
        self.assertTrue(passed_gate["configured"])
        self.assertIsNone(passed_gate["failure_type"])
        self.assertEqual(failed_gate["status"], "failed")
        self.assertEqual(failed_gate["failure_type"], "threshold")
        self.assertEqual(failed_gate["failed_metrics"], ["strict_chunk_recall_at_k"])
        self.assertEqual(failed_payload["status"]["failure_type"], "gate_threshold")
        self.assertEqual(failed_payload["status"]["benchmark_gate_status"], "failed")

    def test_benchmark_reports_expected_term_metrics_when_strict_chunk_hash_misses(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "<table><tr><td>alpha revenue</td></tr></table>",
                            "document_name": "source.md",
                            "chunk_id": "candidate-chunk-1",
                        },
                        {
                            "content": "<table><tr><td>beta margin</td></tr></table>",
                            "document_name": "source.md",
                            "chunk_id": "candidate-chunk-2",
                        },
                    ]
                }
            }
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-table",
                        question="Which table values?",
                        expected_terms=["alpha revenue", "beta margin"],
                        metadata={"benchmark_category": "table_value"},
                    ),
                    passed=True,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-table": [
                    *load_benchmark_qrels_inline(
                        [
                            {
                                "query_id": "q-table",
                                "document": "source.md",
                                "expected_modality": "table",
                                "benchmark_category": "table_value",
                            }
                        ]
                    )["q-table"],
                    *load_benchmark_qrels_dict_item("sha256:missing-reference", field="expected_chunk"),
                ]
            },
            cutoff=3,
        )
        benchmark = benchmarked.to_dict()["benchmark"]
        metrics = benchmark["metrics"]
        per_query = benchmark["per_query"][0]
        markdown = render_markdown_report(benchmarked)

        self.assertEqual(per_query["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(per_query["expected_chunk_hit_rate"], 0.0)
        self.assertEqual(per_query["expected_term_recall_at_k"], 1.0)
        self.assertEqual(per_query["expected_term_hit_rate"], 1.0)
        self.assertEqual(per_query["expected_term_count"], 2)
        self.assertEqual(per_query["matched_expected_terms"], 2)
        self.assertEqual(per_query["table_term_recall_at_k"], 1.0)
        self.assertEqual(per_query["table_term_hit_rate"], 1.0)
        self.assertEqual(metrics["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(metrics["expected_term_recall_at_k"], 1.0)
        self.assertEqual(metrics["expected_term_hit_rate"], 1.0)
        self.assertEqual(metrics["expected_term_count"], 2)
        self.assertEqual(metrics["matched_expected_terms"], 2)
        self.assertEqual(metrics["table_term_recall_at_k"], 1.0)
        self.assertEqual(metrics["table_term_hit_rate"], 1.0)
        self.assertIn("Strict chunk recall@k", markdown)
        self.assertIn("Expected term recall@k", markdown)
        self.assertIn("Table term recall@k", markdown)

    def test_benchmark_reports_candidate_snapshot_expected_chunk_matches_when_boundaries_differ(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "Same source table first candidate chunk has alpha revenue",
                            "document_name": "source.md",
                            "chunk_id": "candidate-chunk-1",
                        },
                        {
                            "content": "Same source table second candidate chunk has beta margin",
                            "document_name": "source.md",
                            "chunk_id": "candidate-chunk-2",
                        },
                    ]
                }
            }
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-table",
                        question="Which table values?",
                        expected_terms=["alpha revenue", "beta margin"],
                        metadata={"benchmark_category": "table_value"},
                    ),
                    passed=True,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )
        candidate_snapshot = {
            "schema": CHUNK_SNAPSHOT_SCHEMA,
            "chunks": [
                {
                    "stable_hash": stable_chunk_hash(chunks[0]),
                    "chunk_id": "candidate-chunk-1",
                    "content": chunks[0].content,
                    "aliases": [stable_chunk_hash(chunks[0]), "candidate-chunk-1"],
                },
                {
                    "stable_hash": stable_chunk_hash(chunks[1]),
                    "chunk_id": "candidate-chunk-2",
                    "content": chunks[1].content,
                    "aliases": [stable_chunk_hash(chunks[1]), "candidate-chunk-2"],
                },
            ],
        }

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-table": [
                    *load_benchmark_qrels_dict_item("source.md"),
                    *load_benchmark_qrels_dict_item("sha256:reference-boundary-hash", field="expected_chunk"),
                ]
            },
            cutoff=3,
            chunk_snapshot=candidate_snapshot,
        )
        benchmark = benchmarked.to_dict()["benchmark"]
        metrics = benchmark["metrics"]
        per_query = benchmark["per_query"][0]
        markdown = render_markdown_report(benchmarked)

        self.assertEqual(per_query["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(per_query["matched_expected_chunks"], 0)
        self.assertEqual(per_query["candidate_snapshot_expected_chunk_recall_at_k"], 1.0)
        self.assertEqual(per_query["candidate_snapshot_expected_chunk_hit_rate"], 1.0)
        self.assertEqual(per_query["candidate_snapshot_expected_chunk_count"], 2)
        self.assertEqual(per_query["matched_candidate_snapshot_expected_chunks"], 2)
        self.assertEqual(metrics["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(metrics["candidate_snapshot_expected_chunk_recall_at_k"], 1.0)
        self.assertEqual(metrics["candidate_snapshot_expected_chunk_hit_rate"], 1.0)
        self.assertEqual(metrics["candidate_snapshot_expected_chunk_count"], 2)
        self.assertEqual(metrics["matched_candidate_snapshot_expected_chunks"], 2)
        self.assertIn("Strict chunk recall@k", markdown)
        self.assertIn("Candidate snapshot expected chunk recall@k", markdown)

    def test_benchmark_gate_can_fail_expected_and_table_term_thresholds(self) -> None:
        chunks = normalize_retrieval_response(
            {"data": {"chunks": [{"content": "<table><tr><td>present value</td></tr></table>", "document_name": "source.md"}]}}
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-table",
                        question="Which table value?",
                        expected_terms=["present value", "absent value"],
                        metadata={"benchmark_category": "table_value"},
                    ),
                    passed=False,
                    chunk_count=len(chunks),
                    chunks=chunks,
                )
            ],
        )

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-table": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-table",
                            "document": "source.md",
                            "expected_modality": "table",
                            "benchmark_category": "table_value",
                        }
                    ]
                )["q-table"]
            },
            cutoff=3,
            gate=BenchmarkGate(
                min_expected_term_recall_at_k=1.0,
                min_table_term_recall_at_k=1.0,
            ),
        )
        payload = benchmarked.to_dict()
        gate = payload["benchmark"]["gate"]

        self.assertFalse(benchmarked.ok)
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(gate["failure_type"], "threshold")
        self.assertEqual(
            gate["failed_metrics"],
            ["expected_term_recall_at_k", "table_term_recall_at_k"],
        )
        self.assertEqual(gate["thresholds"]["min_expected_term_recall_at_k"], 1.0)
        self.assertEqual(gate["thresholds"]["min_table_term_recall_at_k"], 1.0)
        self.assertEqual(payload["status"]["failure_type"], "case_and_gate_threshold")

    def test_benchmark_expected_term_metrics_cover_text_mixed_and_missing_cases(self) -> None:
        text_chunks = normalize_retrieval_response(
            {"data": {"chunks": [{"content": "plain alpha fact", "document_name": "source.md"}]}}
        )
        mixed_chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {"content": "<table><tr><td>table value</td></tr></table>", "document_name": "source.md"},
                        {"content": "caption evidence", "document_name": "diagram.png", "metadata": {"modality": "image"}},
                    ]
                }
            }
        )
        missing_chunks = normalize_retrieval_response(
            {"data": {"chunks": [{"content": "<table><tr><td>present value</td></tr></table>", "document_name": "source.md"}]}}
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-text",
                        question="Which text fact?",
                        expected_terms=["plain alpha"],
                        metadata={"benchmark_category": "text_fact"},
                    ),
                    passed=True,
                    chunk_count=len(text_chunks),
                    chunks=text_chunks,
                ),
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-mixed",
                        question="Which mixed evidence?",
                        expected_terms=["table value", "caption evidence"],
                        metadata={"benchmark_category": "mixed_table_plus_image"},
                    ),
                    passed=True,
                    chunk_count=len(mixed_chunks),
                    chunks=mixed_chunks,
                ),
                ValidationCaseResult(
                    query=ValidationQuery(
                        id="q-missing",
                        question="Which missing table value?",
                        expected_terms=["present value", "absent value"],
                        metadata={"benchmark_category": "table_value"},
                    ),
                    passed=False,
                    chunk_count=len(missing_chunks),
                    chunks=missing_chunks,
                ),
            ],
        )

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-text": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-text",
                            "document": "source.md",
                            "expected_modality": "text",
                            "benchmark_category": "text_fact",
                        }
                    ]
                )["q-text"],
                "q-mixed": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-mixed",
                            "document": "source.md",
                            "expected_modality": "mixed",
                            "benchmark_category": "mixed_table_plus_image",
                        }
                    ]
                )["q-mixed"],
                "q-missing": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-missing",
                            "document": "source.md",
                            "expected_modality": "table",
                            "benchmark_category": "table_value",
                        }
                    ]
                )["q-missing"],
            },
            cutoff=3,
        )
        benchmark = benchmarked.to_dict()["benchmark"]
        metrics = benchmark["metrics"]
        by_id = {item["id"]: item for item in benchmark["per_query"]}

        self.assertNotIn("table_term_recall_at_k", by_id["q-text"])
        self.assertEqual(by_id["q-mixed"]["expected_term_recall_at_k"], 1.0)
        self.assertEqual(by_id["q-mixed"]["table_term_recall_at_k"], 1.0)
        self.assertEqual(by_id["q-missing"]["expected_term_recall_at_k"], 0.5)
        self.assertEqual(by_id["q-missing"]["expected_term_hit_rate"], 0.0)
        self.assertEqual(metrics["expected_term_query_count"], 3)
        self.assertAlmostEqual(metrics["expected_term_recall_at_k"], (1.0 + 1.0 + 0.5) / 3)
        self.assertAlmostEqual(metrics["expected_term_hit_rate"], (1.0 + 1.0 + 0.0) / 3)
        self.assertEqual(metrics["expected_term_count"], 5)
        self.assertEqual(metrics["matched_expected_terms"], 4)
        self.assertEqual(metrics["table_term_query_count"], 2)
        self.assertAlmostEqual(metrics["table_term_recall_at_k"], (1.0 + 0.5) / 2)
        self.assertAlmostEqual(metrics["table_term_hit_rate"], (1.0 + 0.0) / 2)

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

        self.assertEqual(benchmark["schema"], "ragflow_benchmark_report_v1")
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

    def test_benchmark_reports_multimodal_categories_and_image_metrics(self) -> None:
        image_chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "visual evidence",
                            "document_name": "diagram.png",
                            "mime_type": "image/png",
                            "metadata": {"modality": "image"},
                        },
                        {
                            "content": "nearby caption text",
                            "document_name": "source.md",
                            "metadata": {"modality": "text"},
                        },
                    ]
                }
            }
        )
        table_chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "<table><tr><td>42</td></tr></table>",
                            "document_name": "source.md",
                            "metadata": {"modality": "table"},
                        }
                    ]
                }
            }
        )
        text_chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "Known answer with text evidence",
                            "document_name": "source.md",
                            "metadata": {"modality": "text"},
                        }
                    ]
                }
            }
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(id="q-image", question="Which diagram?", metadata={"type": "visual_identification"}),
                    passed=True,
                    chunk_count=len(image_chunks),
                    chunks=image_chunks,
                ),
                ValidationCaseResult(
                    query=ValidationQuery(id="q-table", question="Which value?", metadata={"benchmark_category": "table_value"}),
                    passed=True,
                    chunk_count=len(table_chunks),
                    chunks=table_chunks,
                ),
                ValidationCaseResult(
                    query=ValidationQuery(id="q-text", question="Which fact?", metadata={"benchmark_category": "text_fact"}),
                    passed=True,
                    chunk_count=len(text_chunks),
                    chunks=text_chunks,
                ),
            ],
        )
        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-image": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-image",
                            "document": "diagram.png",
                            "expected_modality": "image",
                            "benchmark_category": "visual_identification",
                        }
                    ]
                )["q-image"],
                "q-table": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-table",
                            "document": "source.md",
                            "expected_modality": "table",
                            "benchmark_category": "table_value",
                        }
                    ]
                )["q-table"],
                "q-text": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-text",
                            "document": "source.md",
                            "expected_modality": "text",
                            "benchmark_category": "text_fact",
                        }
                    ]
                )["q-text"],
            },
            cutoff=2,
        )
        benchmark = benchmarked.to_dict()["benchmark"]
        metrics = benchmark["metrics"]
        multimodal = benchmark["multimodal"]
        markdown = render_markdown_report(benchmarked)

        self.assertEqual(multimodal["schema"], MULTIMODAL_BENCHMARK_SCHEMA)
        self.assertEqual(multimodal["allowed_categories"], list(MULTIMODAL_BENCHMARK_CATEGORIES))
        self.assertEqual(multimodal["category_counts"]["visual_identification"], 1)
        self.assertEqual(multimodal["category_counts"]["table_value"], 1)
        self.assertEqual(multimodal["category_counts"]["text_fact"], 1)
        self.assertEqual(multimodal["expected_modality_counts"], {"image": 1, "table": 1, "text": 1})
        self.assertEqual(multimodal["result_modality_distribution"]["image"], 1)
        self.assertEqual(multimodal["result_modality_distribution"]["table"], 1)
        self.assertEqual(multimodal["result_modality_distribution"]["text"], 2)
        self.assertEqual(metrics["image_scope_query_count"], 1)
        self.assertEqual(metrics["image_precision_at_k"], 0.5)
        self.assertEqual(metrics["image_recall_at_k"], 1.0)
        self.assertEqual(metrics["image_recall"], 1.0)
        self.assertEqual(metrics["visual_coverage_rate"], 1.0)
        self.assertEqual(benchmark["per_query"][0]["result_modality_distribution"], {"image": 1, "text": 1})
        self.assertIn("Multimodal", markdown)
        self.assertIn("Image recall@k", markdown)

    def test_benchmark_classifies_markdown_table_markup_as_table_modality(self) -> None:
        table_chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content": "<table><tr><td>42</td></tr></table>",
                            "document_name": "source.md",
                        }
                    ]
                }
            }
        )
        report = ValidationReport(
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            cases=[
                ValidationCaseResult(
                    query=ValidationQuery(id="q-table", question="Which value?", metadata={"benchmark_category": "table_value"}),
                    passed=True,
                    chunk_count=len(table_chunks),
                    chunks=table_chunks,
                )
            ],
        )

        benchmarked = attach_benchmark_evaluation(
            report,
            qrels={
                "q-table": load_benchmark_qrels_inline(
                    [
                        {
                            "query_id": "q-table",
                            "document": "source.md",
                            "expected_modality": "table",
                            "benchmark_category": "table_value",
                        }
                    ]
                )["q-table"]
            },
            cutoff=2,
        )
        benchmark = benchmarked.to_dict()["benchmark"]

        self.assertEqual(benchmark["metrics"]["table_recall_at_k"], 1.0)
        self.assertEqual(benchmark["per_query"][0]["table_result_count"], 1)
        self.assertEqual(benchmark["per_query"][0]["result_modality_distribution"], {"table": 1})

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

    def test_validation_status_distinguishes_case_failure_from_gate_failure(self) -> None:
        case_failure = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[ValidationQuery(id="q1", question="Known", expected_terms=["not returned"])],
            top_k=3,
        )
        case_failure = attach_benchmark_evaluation(
            case_failure,
            qrels={"q1": load_benchmark_qrels_dict_item("source.md")},
            cutoff=3,
        )
        gate_failure = run_retrieval_validation(
            FakeValidationClient(),
            level="benchmark",
            dataset_id="ds-1",
            dataset_name="kb:test",
            queries=[ValidationQuery(id="q1", question="Known")],
            top_k=3,
        )
        gate_failure = attach_benchmark_evaluation(
            gate_failure,
            qrels={"q1": load_benchmark_qrels_dict_item("missing.md")},
            cutoff=3,
            gate=BenchmarkGate(min_hit_rate=1.0),
        )

        self.assertEqual(case_failure.to_dict()["status"]["failure_type"], "case")
        self.assertEqual(case_failure.to_dict()["status"]["benchmark_gate_status"], "not_configured")
        self.assertEqual(gate_failure.to_dict()["status"]["failure_type"], "gate_threshold")
        self.assertEqual(gate_failure.to_dict()["status"]["benchmark_gate_status"], "failed")

    def test_load_benchmark_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            path.write_text(
                json.dumps(
                    {
                        "thresholds": {
                            "min_hit_rate": 0.8,
                            "min_expected_term_recall_at_k": 0.9,
                            "min_table_term_recall_at_k": 0.7,
                            "max_mrr_drop": 0.1,
                        }
                    }
                ),
                encoding="utf-8",
            )
            gate = load_benchmark_gate(path)

        self.assertEqual(gate.min_hit_rate, 0.8)
        self.assertEqual(gate.min_expected_term_recall_at_k, 0.9)
        self.assertEqual(gate.min_table_term_recall_at_k, 0.7)
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


def load_benchmark_qrels_inline(items):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "qrels.json"
        path.write_text(json.dumps({"qrels": items}), encoding="utf-8")
        return load_benchmark_qrels(path)


if __name__ == "__main__":
    unittest.main()
