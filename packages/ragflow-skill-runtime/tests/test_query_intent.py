from __future__ import annotations

import unittest

from ragflow_skill_runtime.query_intent import (
    QUERY_INTENT_SCHEMA,
    QUERY_ROUTE_DECISION_SCHEMA,
    QueryIntentError,
    classify_query_intent,
    render_query_intent_markdown,
    render_query_route_decision_markdown,
    route_query_intent,
)


class QueryIntentTests(unittest.TestCase):
    def test_classifies_supported_intents(self) -> None:
        cases = {
            "How do I configure runtime?": "knowledge_query",
            "Compare runtime config versus metadata routing.": "comparison",
            "What about it?": "clarification_needed",
            "What is today's weather?": "out_of_scope",
        }

        for question, expected_intent in cases.items():
            with self.subTest(question=question):
                report = classify_query_intent(question)
                self.assertEqual(report["schema"], QUERY_INTENT_SCHEMA)
                self.assertEqual(report["intent"], expected_intent)
                self.assertIn("confidence", report)
                self.assertIn("low_confidence_disclaimer", report)

    def test_low_confidence_disclaimer_is_structured(self) -> None:
        report = classify_query_intent("How do I configure runtime?", low_confidence_threshold=0.9)
        markdown = render_query_intent_markdown(report)

        self.assertTrue(report["low_confidence"])
        self.assertIsInstance(report["low_confidence_disclaimer"], str)
        self.assertIn("RAGFlow Query Intent", markdown)
        self.assertIn("Disclaimer", markdown)

    def test_route_decision_maps_intent_to_action(self) -> None:
        comparison = route_query_intent("Compare runtime config versus metadata routing.")
        clarification = route_query_intent("What about it?")
        rejected = route_query_intent("What is today's weather?")
        markdown = render_query_route_decision_markdown(comparison)

        self.assertEqual(comparison["schema"], QUERY_ROUTE_DECISION_SCHEMA)
        self.assertEqual(comparison["action"], "retrieve_and_compare")
        self.assertTrue(comparison["should_retrieve"])
        self.assertEqual(clarification["status"], "clarification")
        self.assertFalse(clarification["should_retrieve"])
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("RAGFlow Query Route Decision", markdown)

    def test_rejects_invalid_threshold_and_retrieval_mode(self) -> None:
        with self.assertRaisesRegex(QueryIntentError, "low_confidence_threshold"):
            classify_query_intent("runtime", low_confidence_threshold=2.0)
        with self.assertRaisesRegex(QueryIntentError, "retrieval_mode"):
            route_query_intent("runtime", retrieval_mode="live")


if __name__ == "__main__":
    unittest.main()
