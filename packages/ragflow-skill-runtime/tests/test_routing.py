from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.routing import (
    RoutingConfig,
    load_route_test_queries,
    load_routing_config,
    render_route_test_markdown,
    route_question,
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
                        "params": {"top_k": 6},
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


if __name__ == "__main__":
    unittest.main()
