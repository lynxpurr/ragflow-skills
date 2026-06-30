from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from runtime_resilience_inventory import render_markdown, run_runtime_resilience_inventory  # noqa: E402


class RuntimeResilienceInventoryTests(unittest.TestCase):
    def test_inventory_summarizes_runtime_resilience_status(self) -> None:
        report = run_runtime_resilience_inventory()

        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["schema"], "ragflow_runtime_resilience_inventory_v1")
        self.assertEqual(report["summary"]["command_count"], 81)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            report["summary"]["status_counts"],
            {
                "candidate": 0,
                "covered": 19,
                "deferred": 2,
                "not_applicable": 60,
            },
        )

    def test_inventory_classifies_representative_runtime_surfaces(self) -> None:
        report = run_runtime_resilience_inventory()
        by_command = {entry["command"]: entry for entry in report["commands"]}

        endpoint = by_command["ragflow-query endpoint-report"]
        self.assertEqual(endpoint["status"], "covered")
        self.assertEqual(
            endpoint["features"],
            ["cache", "circuit_breaker", "metrics", "partial_failure", "rate_limit", "retry"],
        )

        fallback = by_command["ragflow-query fallback-test"]
        self.assertEqual(fallback["status"], "covered")
        self.assertEqual(fallback["features"], ["partial_failure"])

        backend_probe = by_command["ragflow-doc-to-md backend probe"]
        self.assertEqual(backend_probe["status"], "covered")
        self.assertEqual(backend_probe["features"], ["partial_failure"])

        model_providers = by_command["ragflow-kb-build model-providers probe"]
        self.assertEqual(model_providers["status"], "covered")
        self.assertEqual(model_providers["features"], ["partial_failure"])

        kb_probe = by_command["ragflow-kb-build probe"]
        self.assertEqual(kb_probe["status"], "covered")
        self.assertEqual(kb_probe["features"], ["partial_failure"])

        inspect_kb = by_command["ragflow-kb-build inspect-kb"]
        self.assertEqual(inspect_kb["status"], "covered")
        self.assertEqual(inspect_kb["features"], ["partial_failure"])

        benchmark_import = by_command["ragflow-kb-build benchmark import"]
        self.assertEqual(benchmark_import["status"], "covered")
        self.assertEqual(benchmark_import["features"], ["checkpoint_resume"])

        qa_generate = by_command["ragflow-kb-build qa generate"]
        self.assertEqual(qa_generate["status"], "covered")
        self.assertEqual(qa_generate["features"], ["checkpoint_resume"])

        profile_experiment = by_command["ragflow-kb-build profile experiment"]
        self.assertEqual(profile_experiment["status"], "covered")
        self.assertEqual(profile_experiment["features"], ["checkpoint_resume", "partial_failure"])

        optimize = by_command["ragflow-kb-build optimize"]
        self.assertEqual(optimize["status"], "covered")
        self.assertEqual(optimize["features"], ["checkpoint_resume", "partial_failure"])

        doc_split = by_command["ragflow-doc-to-md split"]
        self.assertEqual(doc_split["status"], "covered")
        self.assertEqual(doc_split["features"], ["checkpoint_resume"])

        validate = by_command["ragflow-kb-build validate"]
        self.assertEqual(validate["status"], "covered")
        self.assertEqual(validate["features"], ["partial_failure"])

        snapshot = by_command["ragflow-kb-build snapshot-chunks"]
        self.assertEqual(snapshot["status"], "covered")
        self.assertEqual(snapshot["features"], ["partial_failure"])

        qa_validate = by_command["ragflow-kb-build qa validate"]
        self.assertEqual(qa_validate["status"], "covered")
        self.assertEqual(qa_validate["features"], ["partial_failure"])

        qa_map = by_command["ragflow-kb-build qa map-evidence"]
        self.assertEqual(qa_map["status"], "covered")
        self.assertEqual(qa_map["features"], ["partial_failure"])

        live_build = by_command["ragflow-kb-build"]
        self.assertEqual(live_build["status"], "deferred")
        self.assertIn("retry", live_build["features"])

        template = by_command["ragflow-kb-build metadata generate-template"]
        self.assertEqual(template["status"], "not_applicable")
        self.assertEqual(template["features"], [])

        suggest_request = by_command["ragflow-kb-build metadata suggest-request"]
        self.assertEqual(suggest_request["status"], "not_applicable")
        self.assertEqual(suggest_request["features"], [])

    def test_markdown_renderer_summarizes_runtime_inventory(self) -> None:
        report = run_runtime_resilience_inventory()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "runtime-inventory.md"
            output.write_text(render_markdown(report), encoding="utf-8")
            text = output.read_text(encoding="utf-8")

        self.assertIn("# RAGFlow Runtime Resilience Inventory", text)
        self.assertIn("`ragflow-query endpoint-report`", text)
        self.assertIn("candidate: `0`", text)
        self.assertIn("`checkpoint_resume`: `7`", text)


if __name__ == "__main__":
    unittest.main()
