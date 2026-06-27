from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime.parse_report import (  # noqa: E402
    PARSE_REPORT_SCHEMA,
    ParseReportError,
    create_parse_report,
    render_parse_report_markdown,
)


class ParseReportTests(unittest.TestCase):
    def test_parse_report_summarizes_status_logs_settings_and_count_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "guide.md"
            broken = root / "broken.md"
            source.write_text("# Guide\n\nKnown parse content.\n", encoding="utf-8")
            broken.write_text("# Broken\n\nImage-heavy source.\n", encoding="utf-8")
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "ragflow_base_url": "https://ragflow.example.test/api/v1",
                        "dataset": {"id": "ds-parse", "name": "kb:parse"},
                        "profile": {"id": "manifest-profile"},
                        "documents": [
                            {
                                "document_id": "doc-ok",
                                "source_path": str(source),
                                "markdown_path": str(source),
                                "status": "done",
                                "chunk_count": 1,
                            },
                            {
                                "document_id": "doc-fail",
                                "source_path": str(broken),
                                "markdown_path": str(broken),
                                "status": "done",
                                "chunk_count": 0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            documents_json = root / "documents.json"
            documents_json.write_text(
                json.dumps(
                    {
                        "data": {
                            "doc_count": 2,
                            "chunk_count": 3,
                            "docs": [
                                {"id": "doc-ok", "name": "guide.md", "run": "1", "progress": 1, "chunk_count": 2},
                                {
                                    "id": "doc-fail",
                                    "name": "broken.md",
                                    "run": "-1",
                                    "progress": -1,
                                    "progress_msg": "[ERROR] OCR failed",
                                    "chunk_count": 0,
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "slow-profile",
                        "chunk_size": 768,
                        "chunk_overlap": 96,
                        "parser_config": {
                            "chunk_token_num": 768,
                            "auto_keywords": 12,
                            "auto_questions": 3,
                            "layout_recognize": True,
                            "table_context_size": 4096,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            parse_log = root / "parse.log"
            parse_log.write_text(
                "layout recognition finished in 2.5s\n"
                "embedding phase took 420ms\n"
                "[ERROR] parser failed for doc-fail\n",
                encoding="utf-8",
            )

            report = create_parse_report(
                kb_manifest_path=kb_manifest,
                documents_json_path=documents_json,
                parse_log_paths=[parse_log],
                profile_path=profile,
            )
            markdown = render_parse_report_markdown(report)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], PARSE_REPORT_SCHEMA)
        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["execution"]["ragflow_calls"], 0)
        self.assertEqual(report["execution"]["db_calls"], 0)
        self.assertEqual(report["execution"]["redis_calls"], 0)
        self.assertEqual(report["execution"]["docker_calls"], 0)
        self.assertEqual(report["execution"]["system_service_calls"], 0)
        self.assertEqual(report["summary"]["failed_document_count"], 1)
        self.assertEqual(report["summary"]["chunk_mismatch_count"], 1)
        self.assertEqual(report["chunk_consistency"]["mismatch_count"], 2)
        self.assertEqual(report["parse_log_summary"]["error_count"], 1)
        self.assertEqual(report["parse_log_summary"]["slowest_phase"]["phase"], "layout")
        self.assertEqual(report["parser_settings"]["profile"]["id"], "slow-profile")
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("document_parse_failed", issue_codes)
        self.assertIn("document_chunk_count_mismatch", issue_codes)
        self.assertIn("parse_log_error_lines", issue_codes)
        self.assertIn("auto_questions_enabled", issue_codes)
        self.assertIn("auto_keywords_excessive", issue_codes)
        self.assertIn("visual_or_layout_parser_enabled", issue_codes)
        self.assertIn("unsupported_parser_key", issue_codes)
        self.assertIn("RAGFlow Parse Report", markdown)
        self.assertIn("Execution Guard", markdown)

    def test_parse_report_accepts_top_level_document_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-list", "name": "kb:list"},
                        "documents": [
                            {
                                "document_id": "doc-list",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "pending",
                                "chunk_count": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            documents_json = root / "documents.json"
            documents_json.write_text(
                json.dumps([{"id": "doc-list", "name": "source.md", "run": "1", "chunk_count": 1}]),
                encoding="utf-8",
            )

            report = create_parse_report(kb_manifest_path=kb_manifest, documents_json_path=documents_json)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["document_states"][0]["parse_state"], "succeeded")
        self.assertEqual(report["summary"]["matched_status_document_count"], 1)

    def test_parse_report_rejects_documents_json_without_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps({"version": "0.1", "dataset": {"id": "ds", "name": "kb"}, "documents": []}),
                encoding="utf-8",
            )
            documents_json = root / "documents.json"
            documents_json.write_text(json.dumps({"data": {"total": 0}}), encoding="utf-8")

            with self.assertRaises(ParseReportError):
                create_parse_report(kb_manifest_path=kb_manifest, documents_json_path=documents_json)


if __name__ == "__main__":
    unittest.main()
