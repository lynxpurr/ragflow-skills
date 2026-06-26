from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.observability import (
    audit_citations,
    build_query_trace,
    diagnose_query_result,
    evidence_from_query_payload,
    load_fusion_test_cases,
    query_cross_language_ab_report,
    query_fusion_report,
    query_pollution_report,
    query_rerank_ab_report,
    render_citation_audit_markdown,
    render_query_cross_language_ab_markdown,
    render_query_diagnostic_markdown,
    render_query_fusion_markdown,
    render_query_fusion_test_markdown,
    render_query_pollution_markdown,
    render_query_rerank_ab_markdown,
    render_query_trace_markdown,
    run_fusion_tests,
    weight_evidence,
)
from ragflow_skill_runtime.retrieval import NormalizedChunk


class ObservabilityTests(unittest.TestCase):
    def test_weight_evidence_scores_similarity_and_term_overlap(self) -> None:
        chunks = [
            NormalizedChunk(
                content="RAGFlow runtime configuration supports portable agent integration.",
                similarity=0.9,
                document_name="runtime.md",
                important_keywords=["runtime", "configuration"],
            ),
            NormalizedChunk(
                content="Unrelated release note.",
                similarity=0.2,
                document_name="notes.md",
            ),
        ]

        evidence = weight_evidence("How does runtime configuration work?", chunks)

        self.assertEqual(evidence[0]["citation_id"], "[1]")
        self.assertGreater(evidence[0]["score"], evidence[1]["score"])
        self.assertIn("runtime", evidence[0]["matched_terms"])
        self.assertIn("important-keyword-overlap", evidence[0]["reasons"])

    def test_build_query_trace_and_markdown(self) -> None:
        evidence = [
            {
                "rank": 1,
                "score": 0.9,
                "similarity": 0.9,
                "document_name": "runtime.md",
                "reasons": ["similarity"],
            }
        ]

        trace = build_query_trace(
            question="question",
            requested_mode="agentic",
            effective_mode="agentic",
            dataset_ids=["ds-1"],
            top_k=5,
            similarity_threshold=None,
            host_assisted=True,
            chunk_count=1,
            evidence=evidence,
            timings_ms={"retrieval": 12.3},
        )
        markdown = render_query_trace_markdown(trace)

        self.assertEqual(trace["schema"], "ragflow_query_trace_v1")
        self.assertEqual(trace["cost"]["llm_calls"], 0)
        self.assertIn("RAGFlow Query Trace", markdown)
        self.assertIn("runtime.md", markdown)

    def test_citation_audit_flags_invalid_citations(self) -> None:
        evidence = [{"rank": 1, "content_preview": "Supported answer content."}]

        report = audit_citations("This is supported [1]. This reference is invalid [2].", evidence)
        markdown = render_citation_audit_markdown(report)

        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["invalid_citation_count"], 1)
        self.assertIn("invalid_citation", markdown)

    def test_evidence_from_query_payload_derives_when_absent(self) -> None:
        payload = {
            "question": "portable runtime",
            "chunks": [
                {
                    "content": "Portable runtime evidence.",
                    "similarity": 0.8,
                    "document_name": "runtime.md",
                }
            ],
        }

        evidence = evidence_from_query_payload(payload)

        self.assertEqual(evidence[0]["rank"], 1)
        self.assertEqual(evidence[0]["document_name"], "runtime.md")

    def test_diagnose_query_result_reports_weak_retrieval(self) -> None:
        payload = {
            "question": "portable runtime",
            "mode": "direct",
            "dataset_ids": ["ds-1"],
            "chunks": [
                {
                    "content": "Unrelated chunk.",
                    "similarity": 0.05,
                    "document_name": "notes.md",
                }
            ],
        }
        trace = {"warnings": ["retrieval returned weak evidence"], "route": None}
        audit = {
            "metrics": {
                "invalid_citation_count": 0,
                "warnings": 1,
            }
        }

        report = diagnose_query_result(
            payload,
            trace=trace,
            citation_audit=audit,
            expected_terms=["portable"],
            min_similarity=0.2,
            min_evidence_score=0.7,
        )
        markdown = render_query_diagnostic_markdown(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "REVIEW")
        self.assertGreaterEqual(report["summary"]["warnings"], 3)
        self.assertIn("missing_expected_terms", {issue["code"] for issue in report["issues"]})
        self.assertIn("RAGFlow Query Diagnostic", markdown)

    def test_query_pollution_report_flags_expansion_only_matches(self) -> None:
        payload = {
            "question": "how to use runtime",
            "dataset_ids": ["ds-1"],
            "chunks": [
                {
                    "content": "runtime configuration details",
                    "document_name": "runtime.md",
                    "similarity": 0.9,
                },
                {
                    "content": "translation term only match",
                    "document_name": "polluted.md",
                    "similarity": 0.4,
                },
            ],
        }
        trace = {"expanded_terms": ["translation", "rewrite"]}
        report = query_pollution_report(
            payload,
            trace=trace,
            expanded_terms=["translation"],
            max_examples=3,
        )
        markdown = render_query_pollution_markdown(report)

        self.assertEqual(report["schema"], "ragflow_query_pollution_report_v1")
        self.assertEqual(report["status"], "REVIEW")
        self.assertIn("expansion_only_matches", {issue["code"] for issue in report["issues"]})
        self.assertIn("translation", {item["term"] for item in report["terms"]["bridge_terms"]})
        self.assertIn("RAGFlow Query Pollution Report", markdown)
        self.assertIn("polluted.md", markdown)

    def test_query_rerank_ab_report_compares_external_ordering(self) -> None:
        payload = {
            "question": "where is the best evidence",
            "dataset_ids": ["ds-1"],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "content": "weak background note",
                    "document_name": "weak.md",
                    "similarity": 0.7,
                },
                {
                    "chunk_id": "chunk-2",
                    "content": "best evidence has the target phrase",
                    "document_name": "best.md",
                    "similarity": 0.6,
                },
            ],
        }
        rerank = {"results": [{"chunk_id": "chunk-2", "score": 0.99}, {"chunk_id": "chunk-1", "score": 0.2}]}

        report = query_rerank_ab_report(
            payload,
            rerank_payload=rerank,
            expected_terms=["target phrase"],
            expected_chunks=["chunk-2"],
            top_k=1,
        )
        markdown = render_query_rerank_ab_markdown(report)

        self.assertEqual(report["schema"], "ragflow_query_rerank_ab_report_v1")
        self.assertEqual(report["candidate_source"], "external_rerank")
        self.assertEqual(report["summary"]["candidate_expected_term_hit_count"], 1)
        self.assertEqual(report["summary"]["candidate_expected_chunk_hit_count"], 1)
        self.assertIn("top_rank_changed", {issue["code"] for issue in report["issues"]})
        self.assertIn("best.md", markdown)
        self.assertIn("RAGFlow Query Rerank A/B Report", markdown)

    def test_query_cross_language_ab_report_compares_saved_outputs(self) -> None:
        baseline = [
            {
                "question": "runtime config",
                "chunks": [{"chunk_id": "shared", "content": "Runtime config evidence.", "document_name": "runtime.md", "similarity": 0.9}],
                "metadata": {"retrieval_ms": 10.0},
            },
            {
                "question": "translation support",
                "chunks": [{"chunk_id": "baseline-only", "content": "Baseline evidence.", "document_name": "baseline.md", "similarity": 0.8}],
                "metadata": {"retrieval_ms": 12.0},
            },
            {
                "question": "localized evidence",
                "chunks": [{"chunk_id": "localized", "content": "Localized evidence.", "document_name": "localized.md", "similarity": 0.7}],
                "metadata": {"retrieval_ms": 8.0},
            },
        ]
        candidate = [
            {
                "question": "runtime config",
                "chunks": [{"chunk_id": "shared", "content": "Runtime config evidence.", "document_name": "runtime.md", "similarity": 0.88}],
                "metadata": {"retrieval_ms": 14.0},
            },
            {
                "question": "translation support",
                "chunks": [{"chunk_id": "candidate-only", "content": "Candidate translated evidence.", "document_name": "candidate.md", "similarity": 0.6}],
                "metadata": {"retrieval_ms": 16.0},
            },
            {
                "question": "localized evidence",
                "chunks": [],
                "metadata": {"retrieval_ms": 11.0},
            },
        ]

        report = query_cross_language_ab_report(
            baseline,
            candidate,
            baseline_label="original",
            candidate_label="translate",
            min_top1_stability=0.8,
        )
        markdown = render_query_cross_language_ab_markdown(report)

        self.assertEqual(report["schema"], "ragflow_cross_language_ab_report_v1")
        self.assertEqual(report["status"], "REVIEW")
        self.assertAlmostEqual(report["summary"]["zero_result_rate_delta"], 0.3333)
        self.assertEqual(report["summary"]["top1_stability_rate"], 0.5)
        self.assertLess(report["summary"]["average_chunk_count_delta"], 0)
        self.assertGreater(report["summary"]["average_latency_delta_ms"], 0)
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("candidate_zero_result_regression", issue_codes)
        self.assertIn("top1_stability_below_threshold", issue_codes)
        self.assertIn("RAGFlow Cross-Language A/B Report", markdown)

    def test_query_fusion_report_deduplicates_and_explains_rrf(self) -> None:
        source_a = {
            "question": "shared answer",
            "dataset_ids": ["ds-a"],
            "chunks": [
                {"chunk_id": "shared", "content": "Shared answer evidence.", "document_name": "shared.md", "similarity": 0.9},
                {"chunk_id": "a-only", "content": "A only evidence.", "document_name": "a.md", "similarity": 0.4},
            ],
        }
        source_b = {
            "question": "shared answer",
            "dataset_ids": ["ds-b"],
            "chunks": [
                {"chunk_id": "b-only", "content": "B only evidence.", "document_name": "b.md", "similarity": 0.8},
                {"chunk_id": "shared", "content": "Shared answer evidence.", "document_name": "shared.md", "similarity": 0.7},
            ],
        }

        report = query_fusion_report([source_a, source_b], top_k=3, rrf_k=60)
        markdown = render_query_fusion_markdown(report)

        self.assertEqual(report["schema"], "ragflow_fusion_report_v1")
        self.assertEqual(report["summary"]["source_count"], 2)
        self.assertEqual(report["summary"]["deduplicated_chunk_count"], 1)
        self.assertEqual(report["results"][0]["identity"], "shared")
        self.assertEqual(report["results"][0]["source_count"], 2)
        self.assertIn("deduplicated_chunks", {issue["code"] for issue in report["issues"]})
        self.assertIn("RAGFlow Fusion Report", markdown)
        self.assertIn("shared.md", markdown)

    def test_fusion_test_report_validates_saved_query_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_a = root / "query-a.json"
            query_b = root / "query-b.json"
            cases = root / "cases.json"
            query_a.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
                        "dataset_ids": ["ds-a"],
                        "chunks": [
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.9,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            query_b.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
                        "dataset_ids": ["ds-b"],
                        "chunks": [
                            {
                                "chunk_id": "b-only",
                                "content": "B only evidence.",
                                "document_name": "b.md",
                                "similarity": 0.8,
                            },
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.7,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cases.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "shared-evidence",
                                "query_outputs": ["query-a.json", "query-b.json"],
                                "top_k": 2,
                                "rrf_k": 60,
                                "expected_top_chunk": "shared",
                                "expected_chunks": ["shared"],
                                "expected_terms": ["Shared answer"],
                                "min_source_count": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_fusion_test_cases(cases)
            report = run_fusion_tests(loaded)
            markdown = render_query_fusion_test_markdown(report)

        self.assertTrue(Path(loaded[0]["query_outputs"][0]).is_absolute())
        self.assertEqual(report["schema"], "ragflow_fusion_test_report_v1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["cases"][0]["summary"]["top_source_count"], 2)
        self.assertIn("RAGFlow Fusion Test Report", markdown)
        self.assertIn("shared-evidence", markdown)


if __name__ == "__main__":
    unittest.main()
