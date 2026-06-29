from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from generated_markdown_audit import (  # noqa: E402
    SANITIZED_MARKDOWN_VERIFIED_COMMANDS,
    SCHEMA,
    render_markdown,
    run_generated_markdown_audit,
)


class GeneratedMarkdownAuditTests(unittest.TestCase):
    def test_generated_markdown_audit_passes_for_public_suite(self) -> None:
        report = run_generated_markdown_audit()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["summary"]["markdown_candidate_count"], len(SANITIZED_MARKDOWN_VERIFIED_COMMANDS))
        self.assertEqual(report["summary"]["verified_count"], len(SANITIZED_MARKDOWN_VERIFIED_COMMANDS))
        self.assertEqual(report["summary"]["missing_count"], 0)
        self.assertEqual(report["summary"]["stale_count"], 0)
        self.assertEqual(report["findings"], [])
        by_command = {entry["command"]: entry for entry in report["commands"]}
        self.assertIn("ragflow-query endpoint-report", by_command)
        self.assertIn("markdown_report", by_command["ragflow-query endpoint-report"]["output_categories"])
        self.assertIn("tools/consumer_acceptance.py", by_command["ragflow-query endpoint-report"]["evidence"])
        self.assertIn("ragflow-query cache-report", by_command)
        self.assertIn("markdown_report", by_command["ragflow-query cache-report"]["output_categories"])

    def test_generated_markdown_audit_reports_missing_and_stale_entries(self) -> None:
        report = run_generated_markdown_audit(
            verified_commands=(
                "ragflow-query endpoint-report",
                "ragflow-query stale-command",
            )
        )

        checks = {finding["check"] for finding in report["findings"]}
        self.assertFalse(report["ok"], report)
        self.assertIn("generated_markdown_missing_audit", checks)
        self.assertIn("generated_markdown_stale_audit", checks)
        self.assertGreater(report["summary"]["missing_count"], 0)
        self.assertEqual(report["summary"]["stale_count"], 1)

    def test_markdown_renderer_summarizes_audit(self) -> None:
        report = run_generated_markdown_audit()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "generated_markdown_audit.md"
            output.write_text(render_markdown(report), encoding="utf-8")
            text = output.read_text(encoding="utf-8")

        self.assertIn("# RAGFlow Generated Markdown Audit", text)
        self.assertIn("missing: `0`", text)
        self.assertIn("`ragflow-query endpoint-report`", text)


if __name__ == "__main__":
    unittest.main()
