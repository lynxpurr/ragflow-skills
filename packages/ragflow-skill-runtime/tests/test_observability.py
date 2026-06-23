from __future__ import annotations

import unittest

from ragflow_skill_runtime.observability import (
    audit_citations,
    build_query_trace,
    evidence_from_query_payload,
    render_citation_audit_markdown,
    render_query_trace_markdown,
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


if __name__ == "__main__":
    unittest.main()
