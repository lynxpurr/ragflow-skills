from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.assistant_review import (
    ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA,
    AssistantReviewError,
    load_assistant_profile,
    load_retrieval_hints,
    recommend_assistant_profile,
    render_assistant_profile_recommendation_markdown,
)


class AssistantReviewTests(unittest.TestCase):
    def sample_profile(self) -> dict:
        return {
            "schema": "ragflow_assistant_profile_v1",
            "profile_id": "handoff-review-default",
            "status": "review_required",
            "retrieval": {
                "top_k": 5,
                "similarity_threshold": 0.2,
                "vector_weight": 0.7,
                "bm25_weight": 0.0,
                "require_evidence": True,
                "quote_numeric_facts": True,
                "citation_format": "[n]",
            },
            "answer_policy": [
                "Answer only from retrieved evidence.",
                "Say that the source does not contain the answer when evidence is missing.",
            ],
        }

    def sample_hints(self) -> dict:
        return {
            "schema": "ragflow_retrieval_hints_v1",
            "document_count": 1,
            "section_boundaries": [{"title": f"Section {index}", "image_count": 1 if index == 1 else 0} for index in range(9)],
            "keyword_candidates": [{"term": "runtime"}, {"term": "assistant"}],
            "question_candidates": [{"question": "How should assistant review work?"}],
            "numeric_candidates": [{"value": "42"}],
            "table_artifacts": [{"path": "artifacts/table.csv"}],
            "image_artifacts": [{"path": "documents/images/chart.png"}],
            "quality_risks": [],
        }

    def test_recommend_assistant_profile_uses_hints_without_mutation(self) -> None:
        report = recommend_assistant_profile(
            self.sample_profile(),
            retrieval_hints=self.sample_hints(),
            inputs={"assistant_profile": "assistant_profile.json", "retrieval_hints": "retrieval_hints.json"},
        )
        markdown = render_assistant_profile_recommendation_markdown(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema"], ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["advisory_only"])
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["recommended_settings"]["top_k"], 8)
        self.assertEqual(report["recommended_settings"]["bm25_weight"], 0.3)
        self.assertEqual(report["recommended_settings"]["no_answer_policy"], "abstain_when_evidence_missing")
        self.assertIn("RAGFlow Assistant Profile Recommendation", markdown)

    def test_recommend_assistant_profile_warns_without_retrieval_hints(self) -> None:
        report = recommend_assistant_profile(self.sample_profile())

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(report["issues"][0]["code"], "retrieval_hints_not_supplied")
        self.assertFalse(report["retrieval_hints_summary"]["provided"])

    def test_load_assistant_review_sidecars_require_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "assistant_profile.json"
            hints_path = root / "retrieval_hints.json"
            bad_path = root / "bad.json"
            profile_path.write_text(json.dumps(self.sample_profile()), encoding="utf-8")
            hints_path.write_text(json.dumps(self.sample_hints()), encoding="utf-8")
            bad_path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")

            profile = load_assistant_profile(profile_path)
            hints = load_retrieval_hints(hints_path)

            with self.assertRaisesRegex(AssistantReviewError, "assistant profile schema"):
                load_assistant_profile(bad_path)

        self.assertEqual(profile["schema"], "ragflow_assistant_profile_v1")
        self.assertEqual(hints["schema"], "ragflow_retrieval_hints_v1")


if __name__ == "__main__":
    unittest.main()
