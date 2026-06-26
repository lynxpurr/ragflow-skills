from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.routing import (
    REQUIRED_ROUTE_TEST_CATEGORIES,
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
                        "hints": ["api", "configuration", "runtime", "ux"],
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
                "question": "Unmatched topic question",
                "expected": "kb:general",
                "category": "fuzzy",
                "locale": "en",
            },
            {
                "id": "boundary",
                "question": "luxury onboarding topic",
                "expected": "kb:general",
                "category": "substring_conflict",
                "locale": "en",
            },
        ]

        report = run_route_report(self.sample_config(), queries)
        markdown = render_route_report_markdown(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema"], "ragflow_route_report_v1")
        self.assertEqual(report["summary"]["kb_count"], 3)
        self.assertEqual(report["summary"]["route_test_total"], 3)
        self.assertEqual(report["summary"]["missing_route_test_count"], 1)
        self.assertEqual(report["summary"]["missing_params_count"], 2)
        self.assertEqual(report["summary"]["params_coverage_count"], 1)
        self.assertEqual(report["summary"]["route_test_category_gap_count"], len(REQUIRED_ROUTE_TEST_CATEGORIES) - 3)
        self.assertEqual(report["hint_coverage"][1]["param_coverage"]["missing"], [])
        self.assertEqual(report["coverage_by_category"]["exact"]["total"], 1)
        self.assertEqual(report["coverage_by_locale"]["en"]["total"], 3)
        self.assertTrue(report["word_boundary_hints"])
        self.assertTrue(report["substring_conflicts"])
        self.assertEqual(report["summary"]["english_hint_count"], 8)
        self.assertGreater(report["summary"]["english_hint_coverage_rate"], 0.0)
        self.assertIn("english_hint_coverage", report)
        self.assertEqual(report["english_hint_coverage"][1]["categories"]["exact"]["matched_english_hints"], ["api", "configuration"])
        self.assertIn("fuzzy", report["english_hint_coverage"][0]["categories"])
        self.assertTrue(report["english_hint_category_gaps"])
        self.assertEqual(report["word_boundary_conflicts"][0]["hint"], "ux")
        self.assertEqual(report["word_boundary_conflicts"][0]["risk_kind"], "acronym")
        self.assertIn("RAGFlow Route Report", markdown)
        self.assertIn("Missing Route Tests", markdown)
        self.assertIn("Category Coverage", markdown)
        self.assertIn("English Hint Coverage", markdown)
        self.assertIn("Word Boundary Conflicts", markdown)
        self.assertIn("Required Route-Test Categories", markdown)

    def test_route_test_category_coverage_and_expected_no_route(self) -> None:
        config = RoutingConfig.from_dict(
            {
                "version": "0.1",
                "knowledge_bases": [
                    {
                        "name": "kb:general",
                        "dataset_id": "ds-general",
                        "hints": ["general", "onboarding"],
                        "params": {"top_k": 5, "similarity_threshold": 0.1},
                    },
                    {
                        "name": "kb:technical",
                        "dataset_id": "ds-technical",
                        "hints": ["api", "configuration", "runtime"],
                        "params": {"top_k": 6, "similarity_threshold": 0.1},
                    },
                ],
            }
        )
        queries = [
            {
                "id": "exact",
                "question": "API configuration",
                "expected": "kb:technical",
                "category": "exact",
                "locale": "en",
            },
            {
                "id": "fuzzy",
                "question": "developer runtime help",
                "expected": "kb:technical",
                "category": "fuzzy",
                "locale": "en",
            },
            {
                "id": "short",
                "question": "api",
                "expected": "kb:technical",
                "category": "short query",
                "locale": "en",
            },
            {
                "id": "long",
                "question": "Please explain the API runtime configuration path for a developer integration.",
                "expected": "kb:technical",
                "category": "long-query",
                "locale": "en",
            },
            {
                "id": "mixed-language",
                "question": "API runtime 配置",
                "expected": "kb:technical",
                "category": "mixed_language",
                "locale": "mixed",
            },
            {
                "id": "negative",
                "question": "billing invoice policy",
                "expected": "__no_route__",
                "expected_no_route": True,
                "category": "negative",
                "locale": "en",
                "negative_class": "out_of_scope",
            },
            {
                "id": "substring",
                "question": "runtime API configuration",
                "expected": "kb:technical",
                "category": "substring conflict",
                "locale": "en",
            },
            {
                "id": "wildcard",
                "question": "general onboarding",
                "expected": "kb:general",
                "category": "wildcard-shadowing",
                "locale": "en",
            },
        ]

        route_test = run_route_tests(config, queries)
        report = run_route_report(config, queries)
        route_test_markdown = render_route_test_markdown(route_test)

        self.assertTrue(route_test["ok"])
        self.assertEqual(route_test["required_route_test_categories"]["missing"], [])
        self.assertEqual(route_test["required_route_test_categories"]["present"], sorted(REQUIRED_ROUTE_TEST_CATEGORIES))
        self.assertTrue(report["required_route_test_categories"]["complete"])
        self.assertEqual(report["summary"]["route_test_category_gap_count"], 0)
        self.assertEqual(report["summary"]["expected_no_route_pass_count"], 1)
        self.assertEqual(report["coverage_by_negative_class"]["out_of_scope"]["passed"], 1)
        self.assertIn("Category Summary", route_test_markdown)
        self.assertIn("Locale Summary", route_test_markdown)
        self.assertIn("Negative Query Summary", route_test_markdown)

    def test_route_report_lints_kb_routing_hints_confusion(self) -> None:
        config = RoutingConfig.from_dict(
            {
                "version": "0.1",
                "kb_routing_hints": {"technical": ["api"]},
                "knowledge_bases": [
                    {
                        "name": "kb:technical",
                        "dataset_id": "ds-technical",
                        "hints": ["api"],
                        "kb_routing_hints": ["ignored"],
                        "metadata": {"kb_routing_hints": ["descriptive-only"]},
                    }
                ],
            }
        )

        report = run_route_report(config, [])
        diagnose = run_route_diagnose(config, [])
        markdown = render_route_report_markdown(report)

        self.assertEqual(report["summary"]["config_lint_count"], 3)
        self.assertEqual({item["category"] for item in report["config_lints"]}, {"kb_routing_hints_confusion"})
        self.assertIn("knowledge_bases[0].kb_routing_hints", {item["path"] for item in report["config_lints"]})
        self.assertIn("kb_routing_hints_confusion", {issue["category"] for issue in diagnose["issues"]})
        self.assertIn("Config Lints", markdown)

    def test_public_route_templates_use_neutral_fixtures(self) -> None:
        root = Path(__file__).resolve().parents[3]
        template_dir = root / "skills" / "ragflow-query" / "templates"
        payloads = [
            json.loads((template_dir / "routing-config.example.json").read_text(encoding="utf-8")),
            json.loads((template_dir / "route-test-queries.example.json").read_text(encoding="utf-8")),
        ]
        text = json.dumps(payloads, ensure_ascii=False).lower()

        forbidden_terms = {
            "dedao",
            "得到",
            "薛兆丰",
            "/home/",
            "/users/",
            "localhost:9380",
            "127.0.0.1:9380",
            "private",
        }
        self.assertFalse([term for term in sorted(forbidden_terms) if term in text])
        self.assertIn("kb:general-sample", text)
        self.assertIn("kb:technical-sample", text)
        self.assertIn("dataset-general-sample", text)
        self.assertIn("dataset-technical-sample", text)

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
            {
                "id": "unexpected-route",
                "question": "general help",
                "expected": "__no_route__",
                "expected_no_route": True,
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
        self.assertIn("unexpected_route", categories)
        self.assertIn("RAGFlow Route Diagnosis", markdown)
        self.assertIn("regex_order_issue", markdown)


if __name__ == "__main__":
    unittest.main()
