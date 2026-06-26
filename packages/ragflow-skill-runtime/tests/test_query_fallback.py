from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime import (
    load_query_fallback_test_cases,
    render_query_fallback_test_markdown,
    run_query_fallback_tests,
)


class QueryFallbackTests(unittest.TestCase):
    def test_builtin_fallback_cases_cover_required_modes(self) -> None:
        cases = load_query_fallback_test_cases()
        report = run_query_fallback_tests(cases)
        markdown = render_query_fallback_test_markdown(report)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], "ragflow_query_fallback_test_report_v1")
        self.assertEqual(report["summary"]["covered_required_mode_count"], len(report["required_failure_modes"]))
        self.assertEqual(report["summary"]["fallback_success_rate"], 1.0)
        self.assertEqual(report["summary"]["timeout_count"], 1)
        self.assertEqual(report["summary"]["malformed_llm_json_count"], 1)
        self.assertEqual(report["summary"]["partial_failure_count"], 1)
        self.assertEqual(report["summary"]["llm_unavailable_count"], 1)
        self.assertFalse(report["coverage"]["missing_required_failure_modes"])
        self.assertIn("RAGFlow Query Fallback Test Report", markdown)
        self.assertIn("direct_retrieval", markdown)

    def test_custom_cases_report_missing_required_coverage(self) -> None:
        cases = [
            {
                "id": "single",
                "failure_mode": "llm_unavailable",
                "fallback_strategy": "direct_retrieval",
                "fallback_status": "success",
                "direct_retrieval_chunk_count": 1,
            }
        ]

        report = run_query_fallback_tests(cases)

        self.assertFalse(report["ok"])
        self.assertIn("network_timeout", report["coverage"]["missing_required_failure_modes"])
        self.assertTrue(any(issue["code"] == "missing_fallback_coverage" for issue in report["issues"]))

    def test_load_query_fallback_test_cases_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "timeout",
                                "failure_mode": "network_timeout",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "success",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cases = load_query_fallback_test_cases(path)

        self.assertEqual(cases[0]["id"], "timeout")


if __name__ == "__main__":
    unittest.main()
