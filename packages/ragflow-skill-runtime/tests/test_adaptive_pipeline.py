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
    pipeline_args_from_decision,
    render_document_features_markdown,
)


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
CONVERT_SCRIPT = ROOT / "skills" / "ragflow-doc-to-md" / "scripts" / "convert.py"
DOC_TO_MD_ENV_VARS = {
    "RAGFLOW_CONFIG",
    "DOC_TO_MD_BACKEND",
    "DOC_TO_MD_TABLE_QUALITY",
    "DOC_TO_MD_ALLOW_TABLE_QUALITY_FALLBACK",
    "MINERU_API_KEY",
    "MINERU_BASE_URL",
    "MINERU_CLI_PATH",
    "MINERU_CLI_BACKEND",
    "MINERU_FASTAPI_BACKEND",
    "MINERU_FASTAPI_SERVER_URL",
    "MINERU_TIMEOUT",
    "MINERU_POLL_INTERVAL",
    "MINERU_VERIFY_SSL",
    "MINERU_LANGUAGE",
    "MINERU_PAGE_RANGE",
    "MINERU_ENABLE_TABLE",
    "MINERU_IS_OCR",
    "MINERU_ENABLE_FORMULA",
    "MINERU_ASSET_MODE",
    "MINERU_V4_MODEL_VERSION",
    "MINERU_V4_RESULT_MODE",
    "MINERU_V4_DATA_ID_PREFIX",
}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for name in DOC_TO_MD_ENV_VARS:
        env.pop(name, None)
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

    def test_scanned_pdf_filename_hint_prevents_binary_sample_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "APOLLO-CN-2021-WEB.pdf"
            garbage = bytes([0xF1, 0x9D, 0x62, 0x40, 0x21, 0x90, 0x84, 0xDE, 0x64, 0xFE, 0x20]) * 80
            source.write_bytes(
                b"%PDF-1.7\n"
                b"1 0 obj << /Type /Page >> endobj\n"
                b"2 0 obj ("
                + garbage
                + b") endobj\n"
                + b"0" * 12000
            )

            report = inspect_source_document(source)
            decision = make_pipeline_decision(
                report,
                requested_backend="mineru-fastapi",
                requested_language="ch",
                requested_table_quality="standard",
                requested_mineru_fastapi_backend="pipeline",
                policy="table-atomic",
            )

        document = report["documents"][0]
        self.assertEqual(report["summary"]["primary_language"], "zh")
        self.assertEqual(document["sample"]["language_source"], "filename_hint")
        self.assertIn(document["pdf_text_sample_quality"], {"binary_garbage", "low_text"})
        self.assertTrue(document["risks"]["scanned_or_low_text_pdf"])
        self.assertEqual(decision["signals"]["language_source"], "user_hint")
        self.assertEqual(decision["recommendation"]["kb_profile"]["id"], "table-atomic-zh-4096")
        self.assertEqual(decision["recommendation"]["mineru_fastapi_backend"], "pipeline")

    def test_scanned_pdf_without_filename_hint_stays_unknown_not_confident_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "scanned-sample.pdf"
            garbage = bytes([0xF1, 0x9D, 0x62, 0x40, 0x21, 0x90, 0x84, 0xDE, 0x64, 0xFE, 0x20]) * 80
            source.write_bytes(
                b"%PDF-1.7\n"
                b"1 0 obj << /Type /Page >> endobj\n"
                b"2 0 obj ("
                + garbage
                + b") endobj\n"
                + b"0" * 12000
            )

            report = inspect_source_document(source)
            decision = make_pipeline_decision(
                report,
                requested_backend="mineru-fastapi",
                requested_table_quality="standard",
                requested_mineru_fastapi_backend="pipeline",
                policy="table-atomic",
            )

        document = report["documents"][0]
        self.assertEqual(report["summary"]["primary_language"], "unknown")
        self.assertEqual(document["sample"]["language_source"], "unknown_low_confidence")
        self.assertNotEqual(document["sample"]["language"], "en")
        self.assertIn(document["pdf_text_sample_quality"], {"binary_garbage", "low_text"})
        self.assertTrue(document["risks"]["scanned_or_low_text_pdf"])
        self.assertEqual(decision["signals"]["language_source"], "inspect_source")
        self.assertEqual(decision["signals"]["primary_language"], "auto")
        self.assertEqual(decision["recommendation"]["kb_profile"]["id"], "table-atomic-auto-4096")

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

    def test_decision_preserves_explicit_pandoc_epub_postprocess_profile(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"markdown": 1},
                "table_heavy": False,
                "sample_table_count": 0,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(
            features,
            requested_backend="pandoc",
            requested_postprocess_profile="pandoc-epub",
        )

        self.assertEqual(decision["recommendation"]["postprocess_profile"], "pandoc-epub")

    def test_pdf_table_signal_promotes_auto_backend_to_high_quality_fastapi(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"pdf": 1},
                "table_heavy": False,
                "sample_table_count": 1,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(features, requested_backend="auto")

        self.assertEqual(decision["recommendation"]["backend"], "mineru-fastapi")
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["recommendation"]["mineru_fastapi_backend"], "hybrid-auto-engine")
        reason_codes = {item["code"] for item in decision["reasons"]}
        self.assertIn("table_signal_mineru_fastapi_backend", reason_codes)
        self.assertIn("source_table_high_accuracy", reason_codes)

    def test_pdf_table_signal_uses_v4_platform_model_when_requested(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"pdf": 1},
                "table_heavy": False,
                "sample_table_count": 1,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(features, requested_backend="mineru-v4")
        args = pipeline_args_from_decision(decision, input_path="<input>", output_path="<handoff>")

        self.assertEqual(decision["recommendation"]["backend"], "mineru-v4")
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["recommendation"]["mineru_v4_model_version"], "vlm")
        self.assertIn("--mineru-v4-model-version", args)
        self.assertIn("vlm", args)

    def test_pdf_table_signal_preserves_explicit_v4_html_model(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"pdf": 1},
                "table_heavy": False,
                "sample_table_count": 1,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(
            features,
            requested_backend="mineru-v4",
            requested_mineru_v4_model_version="MinerU-HTML",
        )

        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["recommendation"]["mineru_v4_model_version"], "MinerU-HTML")

    def test_low_text_pdf_table_signal_still_uses_high_quality_table_extraction(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"pdf": 1},
                "table_heavy": False,
                "sample_table_count": 1,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 1,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(features, requested_backend="auto")

        self.assertEqual(decision["recommendation"]["backend"], "mineru-fastapi")
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        warning_codes = {item["code"] for item in decision["warnings"]}
        self.assertNotIn("scanned_pdf_standard_table_quality", warning_codes)

    def test_pdf_table_signal_does_not_force_fastapi_when_probe_is_not_green(self) -> None:
        features = {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "primary_language": "zh",
                "source_kind_counts": {"pdf": 1},
                "table_heavy": False,
                "sample_table_count": 1,
                "has_formal_ingest_candidates": True,
                "image_rich": False,
                "long_document": False,
                "scanned_or_low_text_pdf_count": 0,
                "numeric_or_unit_signal_count": 0,
            },
        }

        decision = make_pipeline_decision(
            features,
            requested_backend="auto",
            backend_probe_status="missing",
        )

        self.assertEqual(decision["recommendation"]["backend"], "auto")
        self.assertEqual(decision["recommendation"]["table_quality"], "auto")
        warning_codes = {item["code"] for item in decision["warnings"]}
        self.assertIn("table_signal_fastapi_probe_not_green", warning_codes)

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

    def test_adaptive_decision_only_cli_promotes_pdf_table_signal_to_high_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            output = root / "handoff"
            source.mkdir()
            (source / "spec.pdf").write_bytes(
                b"%PDF-1.7\n"
                b"1 0 obj << /Type /Page >> endobj\n"
                b"2 0 obj (| Model | Accuracy |\\n| --- | --- |\\n| APOLLO-H | 0.02 mm |) endobj\n"
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
            decision = json.loads((output / "pipeline_decision.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision["recommendation"]["backend"], "mineru-fastapi")
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["recommendation"]["mineru_fastapi_backend"], "hybrid-auto-engine")

    def test_adaptive_decision_only_preserves_explicit_pipeline_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            output = root / "handoff"
            source.mkdir()
            (source / "APOLLO-CN-2021-WEB.pdf").write_bytes(
                b"%PDF-1.7\n1 0 obj << /Type /Page >> endobj\n"
                + b"2 0 obj (\xf1\x9db@!\x90\x84\xded\xfe " * 80
                + b") endobj\n"
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
                    "--backend",
                    "mineru-fastapi",
                    "--mineru-language",
                    "ch",
                    "--adaptive-policy",
                    "table-atomic",
                    "--table-quality",
                    "high",
                    "--mineru-fastapi-backend",
                    "pipeline",
                    "--decision-only",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            decision = json.loads((output / "pipeline_decision.json").read_text(encoding="utf-8"))
            summary = json.loads((output / "adaptive_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision["recommendation"]["table_quality"], "high")
        self.assertEqual(decision["signals"]["user_requested_language"], "zh")
        self.assertEqual(decision["recommendation"]["mineru_fastapi_backend"], "pipeline")
        self.assertEqual(decision["recommendation"]["kb_profile"]["id"], "table-atomic-zh-4096")
        self.assertEqual(summary["inspected_primary_language"], "zh")
        self.assertEqual(summary["decision_primary_language"], "zh")
        self.assertEqual(summary["effective_language_source"], "user_hint")
        self.assertEqual(summary["user_requested_language"], "zh")

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
        self.assertEqual(payload["adaptive_summary"]["inspected_primary_language"], "zh")
        self.assertEqual(payload["adaptive_summary"]["decision_primary_language"], "zh")
        self.assertEqual(payload["adaptive_summary"]["effective_language_source"], "inspect_source")
        self.assertEqual(payload["adaptive_summary"]["recommended_profile_id"], "table-atomic-zh-4096")
        self.assertTrue(manifest_exists)
        self.assertTrue(hints_exists)


if __name__ == "__main__":
    unittest.main()
