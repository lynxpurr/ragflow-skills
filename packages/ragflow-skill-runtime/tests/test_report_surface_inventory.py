from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from report_surface_inventory import render_markdown, run_report_surface_inventory  # noqa: E402


class ReportSurfaceInventoryTests(unittest.TestCase):
    def test_inventory_covers_public_command_surface(self) -> None:
        report = run_report_surface_inventory()

        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["schema"], "ragflow_report_surface_inventory_v1")
        self.assertEqual(report["summary"]["command_count"], 78)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            report["summary"]["status_counts"],
            {
                "covered": 43,
                "needs_redaction": 26,
                "not_applicable": 9,
            },
        )

    def test_inventory_classifies_representative_surfaces(self) -> None:
        report = run_report_surface_inventory()
        by_command = {entry["command"]: entry for entry in report["commands"]}

        endpoint = by_command["ragflow-query endpoint-report"]
        self.assertEqual(endpoint["status"], "covered")
        self.assertIn("redaction_sidecar", endpoint["output_categories"])

        backend_warmup = by_command["ragflow-doc-to-md backend warmup"]
        self.assertEqual(backend_warmup["status"], "covered")
        self.assertIn("json_report", backend_warmup["output_categories"])
        self.assertIn("redaction_sidecar", backend_warmup["output_categories"])

        doc_convert = by_command["ragflow-doc-to-md"]
        self.assertEqual(doc_convert["status"], "covered")
        self.assertIn("runtime_report", doc_convert["output_categories"])
        self.assertIn("redaction_sidecar", doc_convert["output_categories"])

        split = by_command["ragflow-doc-to-md split"]
        self.assertEqual(split["status"], "covered")
        self.assertIn("plan_json", split["output_categories"])
        self.assertIn("redaction_sidecar", split["output_categories"])

        parse_report = by_command["ragflow-kb-build parse-report"]
        self.assertEqual(parse_report["status"], "covered")
        self.assertIn("redaction_sidecar", parse_report["output_categories"])
        self.assertIn("markdown_report", parse_report["output_categories"])

        metadata_lint = by_command["ragflow-kb-build metadata lint"]
        self.assertEqual(metadata_lint["status"], "covered")
        self.assertIn("redaction_sidecar", metadata_lint["output_categories"])

        activation_plan = by_command["ragflow-kb-build activation-plan"]
        self.assertEqual(activation_plan["status"], "covered")
        self.assertIn("redaction_sidecar", activation_plan["output_categories"])

        optimize = by_command["ragflow-kb-build optimize"]
        self.assertEqual(optimize["status"], "covered")
        self.assertIn("redaction_sidecar", optimize["output_categories"])

        template = by_command["ragflow-kb-build metadata generate-template"]
        self.assertEqual(template["status"], "not_applicable")
        self.assertIn("artifact_json", template["output_categories"])

    def test_markdown_renderer_summarizes_inventory(self) -> None:
        report = run_report_surface_inventory()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "inventory.md"
            output.write_text(render_markdown(report), encoding="utf-8")
            text = output.read_text(encoding="utf-8")

        self.assertIn("# RAGFlow Report Surface Inventory", text)
        self.assertIn("`ragflow-query endpoint-report`", text)
        self.assertIn("needs redaction: `26`", text)


if __name__ == "__main__":
    unittest.main()
