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

from ragflow_skill_runtime.health_report import (  # noqa: E402
    HEALTH_REPORT_SCHEMA,
    HealthReportError,
    create_kb_health_report,
    render_kb_health_report_markdown,
)


class HealthReportTests(unittest.TestCase):
    def test_health_report_summarizes_kb_risks_and_execution_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            healthy_manifest = root / "kb_healthy.json"
            empty_manifest = root / "kb_empty.json"
            healthy_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-healthy", "name": "kb:healthy"},
                        "profile": {"id": "healthy-profile", "embedding_model": "bge-m3"},
                        "documents": [
                            {
                                "document_id": "doc-1",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            empty_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-empty", "name": "kb:empty"},
                        "profile": {"id": "empty-profile"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            parse_report = root / "parse_report.json"
            parse_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "ragflow_parse_report_v1",
                        "status": "REVIEW",
                        "dataset": {"id": "ds-healthy", "name": "kb:healthy"},
                        "summary": {
                            "failed_document_count": 1,
                            "pending_document_count": 0,
                            "zero_chunk_document_count": 0,
                            "chunk_mismatch_count": 1,
                            "issue_counts": {"warning": 2},
                        },
                        "chunk_consistency": {"mismatch_count": 1, "status": "REVIEW"},
                        "parser_settings": {"expensive_setting_count": 1},
                        "parse_log_summary": {"error_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            activation_plan = root / "activation_plan.json"
            activation_plan.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "kb_activation_plan_v1",
                        "kb_name": "kb:healthy",
                        "dataset_id": "ds-healthy",
                        "summary": {
                            "blocked_check_count": 0,
                            "review_check_count": 0,
                            "recommendation": "activate",
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = create_kb_health_report(
                kb_manifest_paths=[healthy_manifest, empty_manifest],
                parse_report_paths=[parse_report],
                activation_plan_paths=[activation_plan],
            )
            markdown = render_kb_health_report_markdown(report)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], HEALTH_REPORT_SCHEMA)
        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["execution"]["ragflow_calls"], 0)
        self.assertEqual(report["execution"]["db_calls"], 0)
        self.assertEqual(report["execution"]["redis_calls"], 0)
        self.assertEqual(report["execution"]["docker_calls"], 0)
        self.assertEqual(report["execution"]["system_service_calls"], 0)
        self.assertEqual(report["summary"]["kb_count"], 2)
        self.assertEqual(report["summary"]["embedding_model_count"], 1)
        self.assertEqual(report["summary"]["unknown_embedding_model_count"], 1)
        self.assertEqual(report["summary"]["zero_document_kb_count"], 1)
        self.assertEqual(report["summary"]["zero_chunk_kb_count"], 1)
        self.assertEqual(report["summary"]["route_activation"]["ready"], 1)
        self.assertEqual(report["summary"]["route_activation"]["not_available"], 1)
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("stale_or_failed_parse_state", issue_codes)
        self.assertIn("stale_count_fields", issue_codes)
        self.assertIn("parser_performance_review", issue_codes)
        self.assertIn("zero_or_thin_document_kb", issue_codes)
        self.assertIn("zero_or_thin_chunk_kb", issue_codes)
        self.assertIn("embedding_model_unknown", issue_codes)
        self.assertIn("activation_plan_missing", issue_codes)
        self.assertIn("RAGFlow KB Health Report", markdown)
        self.assertIn("Execution Guard", markdown)

    def test_health_report_warns_when_expected_embedding_model_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-legacy", "name": "kb:legacy"},
                        "profile": {"id": "legacy-profile", "embedding_model": "legacy-embed"},
                        "documents": [
                            {
                                "document_id": "doc-1",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 3,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = create_kb_health_report(
                kb_manifest_paths=[kb_manifest],
                expected_embedding_models=["bge-m3", "bge-large"],
            )
            markdown = render_kb_health_report_markdown(report)

        issue_codes = {issue["code"] for issue in report["issues"]}
        kb_item = report["knowledge_bases"][0]
        self.assertIn("embedding_model_rebuild_required", issue_codes)
        self.assertTrue(kb_item["embedding_model_check"]["rebuild_or_reparse_required"])
        self.assertEqual(kb_item["embedding_model_check"]["status"], "mismatch")
        self.assertEqual(report["summary"]["embedding_model_rebuild_required_kb_count"], 1)
        self.assertEqual(report["inputs"]["expected_embedding_models"], ["bge-m3", "bge-large"])
        self.assertIn("Rebuild/reparse required: 1 KB(s)", markdown)

    def test_health_report_rejects_wrong_parse_report_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds", "name": "kb"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            parse_report = root / "parse_report.json"
            parse_report.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")

            with self.assertRaises(HealthReportError):
                create_kb_health_report(kb_manifest_paths=[kb_manifest], parse_report_paths=[parse_report])


if __name__ == "__main__":
    unittest.main()
