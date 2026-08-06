from __future__ import annotations

import unittest

from ragflow_skill_runtime.query_session import (
    QUERY_SESSION_ENRICHMENT_SCHEMA,
    QUERY_SESSION_INSPECTION_SCHEMA,
    QUERY_SESSION_SCHEMA,
    QuerySessionError,
    build_query_session_inspection,
    detect_follow_up_reference,
    enrich_query_with_session,
    normalize_query_session,
    render_query_session_enrichment_markdown,
    render_query_session_inspection_markdown,
)


class QuerySessionTests(unittest.TestCase):
    def test_normalizes_session_and_inspects_bounded_context(self) -> None:
        session = normalize_query_session(
            {
                "session_id": "s1",
                "turns": [
                    {"role": "user", "content": "How do I configure runtime settings?"},
                    {"role": "assistant", "content": "Use a runtime config file."},
                    {"role": "user", "content": "What about it?"},
                ],
            }
        )
        report = build_query_session_inspection(session, max_turns=2, max_tokens=200)
        markdown = render_query_session_inspection_markdown(report)

        self.assertEqual(session["schema"], QUERY_SESSION_SCHEMA)
        self.assertEqual(report["schema"], QUERY_SESSION_INSPECTION_SCHEMA)
        self.assertEqual(report["limits"]["selected_turn_count"], 2)
        self.assertTrue(report["limits"]["truncated_by_turns"])
        self.assertTrue(report["latest_user_follow_up"]["needs_context"])
        self.assertEqual(report["anchor_turn"]["role"], "assistant")
        self.assertIn("RAGFlow Query Session Inspection", markdown)

    def test_enriches_short_follow_up_from_recent_session(self) -> None:
        report = enrich_query_with_session(
            "What about it?",
            {"turns": [{"role": "user", "content": "How do I configure runtime settings?"}]},
        )
        markdown = render_query_session_enrichment_markdown(report)

        self.assertEqual(report["schema"], QUERY_SESSION_ENRICHMENT_SCHEMA)
        self.assertTrue(report["context_applied"])
        self.assertFalse(report["requires_clarification"])
        self.assertIn("How do I configure runtime settings?", report["enriched_question"])
        self.assertEqual(report["route_decision"]["status"], "retrieval_planned")
        self.assertIn("RAGFlow Query Session Enrichment", markdown)

    def test_requires_clarification_without_anchor_context(self) -> None:
        report = enrich_query_with_session("What about it?", {"turns": []})

        self.assertFalse(report["context_applied"])
        self.assertTrue(report["requires_clarification"])
        self.assertEqual(report["route_decision"]["status"], "clarification")
        self.assertTrue(report["warnings"])

    def test_detects_omitted_subject_follow_up(self) -> None:
        signals = detect_follow_up_reference("And deployment?")

        self.assertTrue(signals["needs_context"])
        self.assertTrue(signals["omitted_subject"])

    def test_rejects_invalid_session_and_limits(self) -> None:
        with self.assertRaisesRegex(QuerySessionError, "turns"):
            normalize_query_session({"messages": "bad"})
        with self.assertRaisesRegex(QuerySessionError, "max_turns"):
            build_query_session_inspection({"turns": []}, max_turns=0)


if __name__ == "__main__":
    unittest.main()
