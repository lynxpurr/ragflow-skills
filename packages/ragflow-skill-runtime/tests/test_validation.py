from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.validation import (
    ValidationQuery,
    evaluate_query_result,
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


if __name__ == "__main__":
    unittest.main()
