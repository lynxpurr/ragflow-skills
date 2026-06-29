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
        self.assertEqual(report["summary"]["command_count"], 79)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            report["summary"]["status_counts"],
            {
                "candidate": 7,
                "covered": 12,
                "deferred": 2,
                "not_applicable": 58,
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

        benchmark_import = by_command["ragflow-kb-build benchmark import"]
        self.assertEqual(benchmark_import["status"], "covered")
        self.assertEqual(benchmark_import["features"], ["checkpoint_resume"])

        validate = by_command["ragflow-kb-build validate"]
        self.assertEqual(validate["status"], "covered")
        self.assertEqual(validate["features"], ["partial_failure"])

        snapshot = by_command["ragflow-kb-build snapshot-chunks"]
        self.assertEqual(snapshot["status"], "covered")
        self.assertEqual(snapshot["features"], ["partial_failure"])

        live_build = by_command["ragflow-kb-build"]
        self.assertEqual(live_build["status"], "deferred")
        self.assertIn("retry", live_build["features"])

        template = by_command["ragflow-kb-build metadata generate-template"]
        self.assertEqual(template["status"], "not_applicable")
        self.assertEqual(template["features"], [])

    def test_markdown_renderer_summarizes_runtime_inventory(self) -> None:
        report = run_runtime_resilience_inventory()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "runtime-inventory.md"
            output.write_text(render_markdown(report), encoding="utf-8")
            text = output.read_text(encoding="utf-8")

        self.assertIn("# RAGFlow Runtime Resilience Inventory", text)
        self.assertIn("`ragflow-query endpoint-report`", text)
        self.assertIn("candidate: `7`", text)
        self.assertIn("`checkpoint_resume`: `8`", text)


if __name__ == "__main__":
    unittest.main()
