from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime import (
    ADAPTIVE_PIPELINE_SUMMARY_SCHEMA,
    DOCUMENT_FEATURES_SCHEMA,
    PIPELINE_DECISION_SCHEMA,
    inspect_source_document,
    make_pipeline_decision,
    render_document_features_markdown,
)


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
CONVERT_SCRIPT = ROOT / "skills" / "ragflow-doc-to-md" / "scripts" / "convert.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["RAGFLOW_SKILL_RUNTIME_PATH"] = str(RUNTIME_SRC)
    return env


class AdaptivePipelineTests(unittest.TestCase):
    def test_source_inspection_detects_table_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "apollo.md"
            source.write_text(
                "# APOLLO Specs\n\n"
                "| Model | MPE_E |\n"
                "| --- | --- |\n"
                "| HH-A | 0.02 mm |\n",
                encoding="utf-8",
            )

            report = inspect_source_document(source)

        self.assertEqual(report["schema"], DOCUMENT_FEATURES_SCHEMA)
        self.assertEqual(report["summary"]["document_count"], 1)
        self.assertTrue(report["summary"]["table_heavy"])
        self.assertEqual(report["summary"]["sample_markdown_table_count"], 1)
        markdown = render_document_features_markdown(report)
        self.assertIn("RAGFlow Document Source Features", markdown)

    def test_decision_selects_table_atomic_profile(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "table_heavy": True,
                "sample_table_count": 2,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 8,
            },
        }

        decision = make_pipeline_decision(
            features,
            requested_backend="mineru-fastapi",
            backend_probe_status="available",
        )

        self.assertEqual(decision["schema"], PIPELINE_DECISION_SCHEMA)
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["recommendation"]["postprocess_profile"], "chunk-markers-dense")
        self.assertEqual(decision["recommendation"]["kb_profile"]["id"], "table-atomic-zh-4096")
        self.assertEqual(decision["script_owned_llm_calls"], 0)
        self.assertFalse(decision["live_mutation_enabled"])

    def test_inspect_source_cli_emits_reports_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            source.mkdir()
            (source / "notes.txt").write_text("hello world\n", encoding="utf-8")
            report_json = root / "features.json"
            report_md = root / "features.md"
            redaction = root / "features.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "inspect-source",
                    "--input",
                    str(source),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report_payload = json.loads(report_json.read_text(encoding="utf-8"))
            report_markdown = report_md.read_text(encoding="utf-8")
            redaction_exists = redaction.exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], DOCUMENT_FEATURES_SCHEMA)
        self.assertEqual(report_payload["schema"], DOCUMENT_FEATURES_SCHEMA)
        self.assertIn("RAGFlow Document Source Features", report_markdown)
        self.assertTrue(redaction_exists)

    def test_adaptive_decision_only_cli_writes_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            output = root / "handoff"
            source.mkdir()
            (source / "spec.md").write_text(
                "# Specs\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "adaptive",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--decision-only",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            decision = json.loads((output / "pipeline_decision.json").read_text(encoding="utf-8"))
            summary = json.loads((output / "adaptive_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(decision["schema"], PIPELINE_DECISION_SCHEMA)
        self.assertEqual(decision["recommendation"]["kb_profile"]["id"], "table-atomic-en-4096")
        self.assertEqual(summary["schema"], ADAPTIVE_PIPELINE_SUMMARY_SCHEMA)
        self.assertFalse((output / "doc_manifest.json").exists())

    def test_adaptive_cli_runs_pipeline_for_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            output = root / "handoff"
            source.mkdir()
            (source / "spec.md").write_text(
                "# 产品规格\n\n| 型号 | 精度 |\n| --- | --- |\n| HH-A | 0.02 mm |\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "adaptive",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            manifest_exists = (output / "doc_manifest.json").exists()
            hints_exists = (output / "retrieval_hints.json").exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["adaptive_summary"]["schema"], ADAPTIVE_PIPELINE_SUMMARY_SCHEMA)
        self.assertEqual(payload["adaptive_summary"]["recommended_profile_id"], "table-atomic-zh-4096")
        self.assertTrue(manifest_exists)
        self.assertTrue(hints_exists)


if __name__ == "__main__":
    unittest.main()
