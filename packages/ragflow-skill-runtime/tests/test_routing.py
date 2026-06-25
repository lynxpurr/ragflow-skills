from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.routing import (
    RoutingConfig,
    load_route_test_queries,
    load_routing_config,
    render_route_diagnose_markdown,
    render_route_report_markdown,
    render_route_test_markdown,
    route_question,
    run_route_diagnose,
    run_route_report,
    run_route_tests,
)


class RoutingTests(unittest.TestCase):
    def sample_config(self) -> RoutingConfig:
        return RoutingConfig.from_dict(
            {
                "version": "0.1",
                "default_kb": "kb:general",
                "knowledge_bases": [
                    {
                        "name": "kb:general",
                        "dataset_id": "ds-general",
                        "description": "General onboarding samples",
                        "hints": ["general", "onboarding"],
                    },
                    {
                        "name": "kb:technical",
                        "dataset_id": "ds-technical",
                        "description": "API configuration and runtime integration",
                        "hints": ["api", "configuration", "runtime"],
                        "params": {"top_k": 6, "similarity_threshold": 0.1},
                    },
                    {
                        "name": "kb:api-extra",
                        "dataset_id": "ds-api-extra",
                        "description": "Additional API references",
                        "hints": ["api docs", "sdk"],
                    },
                ],
            }
        )

    def test_route_question_uses_hints(self) -> None:
        result = route_question(self.sample_config(), "How should I configure the API runtime?")

        self.assertTrue(result.ok)
        self.assertEqual(result.selected.kb.name, "kb:technical")
        self.assertIn("api", result.selected.matched_hints)

    def test_route_question_uses_default_when_no_match(self) -> None:
        result = route_question(self.sample_config(), "An unrelated question")

        self.assertTrue(result.ok)
        self.assertEqual(result.selected.kb.name, "kb:general")
        self.assertEqual(result.selected.reason, "default")

    def test_load_routing_config_and_route_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "routing.json"
            queries_path = root / "routes.json"
            config_path.write_text(json.dumps(self.sample_config().to_dict()), encoding="utf-8")
            queries_path.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "API configuration details",
                                "expected_kb": "kb:technical",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_routing_config(config_path)
            queries = load_route_test_queries(queries_path)
            report = run_route_tests(config, queries)

        self.assertTrue(report["ok"])
        self.assertEqual(report["metrics"]["accuracy"], 1.0)
        self.assertIn("Route Test", render_route_test_markdown(report))

    def test_route_report_summarizes_coverage_and_conflicts(self) -> None:
        queries = [
            {
                "id": "api-config",
                "question": "API configuration details",
                "expected": "kb:technical",
                "category": "exact",
                "locale": "en",
            },
            {
                "id": "fallback",
                "question": "Unmatched onboarding question",
                "expected": "kb:general",
                "category": "fuzzy",
                "locale": "en",
            },
        ]

        report = run_route_report(self.sample_config(), queries)
        markdown = render_route_report_markdown(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema"], "ragflow_route_report_v1")
        self.assertEqual(report["summary"]["kb_count"], 3)
        self.assertEqual(report["summary"]["route_test_total"], 2)
        self.assertEqual(report["summary"]["missing_route_test_count"], 1)
        self.assertEqual(report["summary"]["missing_params_count"], 2)
        self.assertEqual(report["summary"]["params_coverage_count"], 1)
        self.assertEqual(report["hint_coverage"][1]["param_coverage"]["missing"], [])
        self.assertEqual(report["coverage_by_category"]["exact"]["total"], 1)
        self.assertEqual(report["coverage_by_locale"]["en"]["total"], 2)
        self.assertTrue(report["word_boundary_hints"])
        self.assertTrue(report["substring_conflicts"])
        self.assertIn("RAGFlow Route Report", markdown)
        self.assertIn("Missing Route Tests", markdown)
        self.assertIn("Category Coverage", markdown)

    def test_route_diagnose_classifies_failures_and_risks(self) -> None:
        config = RoutingConfig.from_dict(
            {
                "version": "0.1",
                "default_kb": "kb:general",
                "knowledge_bases": [
                    {
                        "name": "kb:general",
                        "dataset_id": "ds-general",
                        "hints": ["general"],
                    },
                    {
                        "name": "kb:alpha",
                        "dataset_id": "ds-alpha",
                        "hints": ["shared", "alpha", "api"],
                        "metadata": {"regex_order_sensitive": True},
                    },
                    {
                        "name": "kb:beta",
                        "dataset_id": "ds-beta",
                        "hints": ["shared", "beta"],
                        "metadata": {"regex_order_sensitive": True},
                    },
                    {
                        "name": "kb:reference",
                        "dataset_id": "ds-reference",
                        "hints": ["api reference"],
                    },
                ],
            }
        )
        queries = [
            {
                "id": "missing-hint",
                "question": "unknown topic",
                "expected": "kb:alpha",
            },
            {
                "id": "missing-kb",
                "question": "general help",
                "expected": "kb:missing",
            },
            {
                "id": "wrong-hint",
                "question": "general help",
                "expected": "kb:alpha",
            },
            {
                "id": "regex-order",
                "question": "shared topic",
                "expected": "kb:beta",
            },
            {
                "id": "acceptable",
                "question": "beta details",
                "expected": "kb:alpha",
                "acceptable_kbs": ["kb:beta"],
            },
        ]

        report = run_route_diagnose(config, queries)
        markdown = render_route_diagnose_markdown(report)
        categories = {issue["category"] for issue in report["issues"]}

        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], "ragflow_route_diagnose_report_v1")
        self.assertIn("missing_hint", categories)
        self.assertIn("missing_kb_config", categories)
        self.assertIn("regex_order_issue", categories)
        self.assertIn("acceptable_ambiguity", categories)
        self.assertIn("priority_conflict", categories)
        self.assertIn("RAGFlow Route Diagnosis", markdown)
        self.assertIn("regex_order_issue", markdown)


if __name__ == "__main__":
    unittest.main()
