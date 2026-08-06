from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from field_trial_metrics import (  # noqa: E402
    RETIREMENT_MATRIX_SCHEMA,
    SCHEMA,
    build_field_trial_metrics,
    render_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FieldTrialMetricsTests(unittest.TestCase):
    def test_retirement_matrix_tracks_quality_improvement_sample_classes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run-001"
            expected_sample_types = [
                "scanned_pdf",
                "extractable_pdf",
                "image_heavy_pdf",
                "long_document",
                "complex_table",
                "office_table_document",
                "mixed_language",
                "low_quality_ocr",
            ]
            _write_json(
                run / "field_trial_record.json",
                {
                    "schema": "ragflow_field_trial_record_v1",
                    "workflow": "doc-to-md",
                    "sample_types": expected_sample_types,
                    "gated_trigger": "none",
                },
            )

            report, _redaction = build_field_trial_metrics([run])

        matrix = report["retirement_observation_matrix"]
        self.assertEqual(matrix["expected_sample_types"], expected_sample_types)
        self.assertEqual(matrix["summary"]["expected_sample_type_count"], 8)
        self.assertEqual(matrix["summary"]["observed_expected_sample_type_count"], 8)
        self.assertEqual(matrix["summary"]["missing_expected_sample_type_count"], 0)
        for sample_type in expected_sample_types:
            self.assertIn(sample_type, matrix["coverage"])

    def test_aggregates_core_field_trial_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run-001"
            private_home = "/home" + "/private-user"
            fake_secret = "field-trial-secret-value"
            fake_endpoint = "http://" + ".".join(("100", "64", "10", "20")) + f":9380/api?token={fake_secret}"
            private_config = f"{private_home}/.ragflow/config.local.yaml"
            _write_json(
                run / "handoff" / "doc_manifest.json",
                {
                    "version": "0.1",
                    "source_root": ".",
                    "quality_gate": {"status": "BLOCKED", "summary": {"documents": 2, "errors": 1, "warnings": 1}},
                    "documents": [
                        {
                            "source_path": f"{private_home}/private/source-a.pdf",
                            "markdown_path": "documents/a.md",
                            "title": "Private Title",
                        },
                        {
                            "source_path": f"{private_home}/private/source-b.pdf",
                            "markdown_path": "documents/b.md",
                        },
                    ],
                },
            )
            _write_json(
                run / "handoff" / "quality_report.json",
                {
                    "schema": "doc_quality_report_v1",
                    "gate": {"status": "BLOCKED", "summary": {"documents": 2, "errors": 1, "warnings": 2}},
                    "documents": [
                        {
                            "markdown_path": "documents/a.md",
                            "issues": [
                                {"severity": "error", "issue_type": "empty_markdown"},
                                {"severity": "warning", "issue_type": "image_missing"},
                            ],
                        }
                    ],
                },
            )
            _write_json(
                run / "query.json",
                {
                    "ok": True,
                    "question": "placeholder question",
                    "chunks": [],
                    "retrieval_status": "empty",
                    "runtime_partial_failure": {
                        "summary": {"status": "partial", "failure_count": 1, "timeout_count": 1}
                    },
                    "runtime_metrics": {
                        "schema": "ragflow_runtime_metrics_v1",
                        "latency_ms": {"average": 42.0},
                    },
                    "endpoint": fake_endpoint,
                    "config_path": private_config,
                },
            )
            _write_json(
                run / "citation_audit.json",
                {
                    "schema": "ragflow_citation_audit_v1",
                    "ok": False,
                    "metrics": {"errors": 1, "warnings": 0},
                },
            )
            _write_json(
                run / "release_hygiene.json",
                {"schema": "ragflow_release_hygiene_check_v1", "ok": True},
            )
            _write_json(
                run / "handoff" / "chunk_profile_report.json",
                {"schema": "ragflow_chunk_profile_report_v1", "summary": {"marker_count": 9, "warning_count": 1}},
            )
            _write_json(
                run / "handoff" / "retrieval_hints.json",
                {
                    "schema": "ragflow_retrieval_hints_v1",
                    "section_boundaries": [{"title": "A"}],
                    "preferred_boundaries": [{"reason": "heading"}],
                    "question_candidates": [{"question": "Q?"}],
                    "table_artifacts": [{"source": "html_table"}],
                    "image_artifacts": [{"path": "images/a.png"}],
                },
            )
            _write_json(run / "kb_build_dry_run.json", {"ok": True, "dry_run": True})
            _write_json(run / "parse_report.json", {"schema": "ragflow_parse_report_v1", "ok": True, "summary": {"chunk_count": 13}})
            _write_json(
                run / "cleanup_execute.json",
                {
                    "schema": "ragflow_optimization_cleanup_execution_report_v1",
                    "ok": True,
                    "summary": {"cleanup_executed": True},
                },
            )
            _write_json(
                run / "field_trial_record.json",
                {
                    "schema": "ragflow_field_trial_record_v1",
                    "workflow": "host-agent",
                    "sample_types": ["scanned", "complex_table"],
                    "gated_trigger": "serve",
                    "friction": f"Repeated CLI calls with api_key={fake_secret}",
                },
            )

            report, redaction = build_field_trial_metrics([run], explicit_secrets=[fake_secret])

        self.assertEqual(report["schema"], SCHEMA)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["json_report_count"], 11)
        self.assertEqual(report["metrics"]["handoff"]["doc_manifest_count"], 1)
        self.assertEqual(report["metrics"]["handoff"]["document_count"], 2)
        self.assertEqual(report["metrics"]["handoff"]["blocked_quality_count"], 2)
        self.assertEqual(report["metrics"]["handoff"]["missing_asset_issue_count"], 1)
        self.assertEqual(report["metrics"]["handoff"]["empty_document_issue_count"], 1)
        self.assertEqual(report["metrics"]["query"]["zero_result_count"], 1)
        self.assertEqual(report["metrics"]["query"]["citation_audit_failure_count"], 1)
        self.assertEqual(report["metrics"]["release"]["ok_count"], 1)
        trigger_tracks = {trigger["track"] for trigger in report["gated_triggers"]}
        self.assertIn("serve", trigger_tracks)
        self.assertIn("handoff_quality", trigger_tracks)
        self.assertIn("query_quality", trigger_tracks)
        matrix = report["retirement_observation_matrix"]
        self.assertEqual(matrix["schema"], "ragflow_retirement_observation_matrix_v1")
        self.assertEqual(matrix["schema"], RETIREMENT_MATRIX_SCHEMA)
        self.assertEqual(matrix["summary"]["observed_expected_sample_type_count"], 2)
        self.assertEqual(matrix["summary"]["missing_expected_sample_type_count"], 6)
        scanned = matrix["coverage"]["scanned_pdf"]
        self.assertEqual(scanned["status"], "needs_review")
        self.assertEqual(scanned["signals"]["chunking"]["chunk_marker_count"], 9)
        self.assertEqual(scanned["signals"]["hints"]["table_artifact_count"], 1)
        self.assertEqual(scanned["signals"]["dry_run"]["passed_count"], 1)
        self.assertEqual(scanned["signals"]["live_parse"]["chunk_count"], 13)
        self.assertEqual(scanned["signals"]["cleanup"]["executed_count"], 1)
        combined = json.dumps(report, ensure_ascii=False) + json.dumps(redaction, ensure_ascii=False)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(private_home, combined)
        self.assertNotIn(private_config, combined)
        self.assertIn("<redacted:home-path>", combined)
        self.assertGreaterEqual(redaction["summary"]["redaction_count"], 1)

    def test_cleanup_execution_reports_feed_top_level_cleanup_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run-cleanup"
            _write_json(
                run / "cleanup_plan.json",
                {
                    "schema": "ragflow_optimization_cleanup_plan_v1",
                    "ok": True,
                    "summary": {
                        "target_count": 2,
                        "ready_target_count": 1,
                        "pending_target_count": 1,
                        "invalid_target_count": 0,
                    },
                },
            )
            _write_json(
                run / "cleanup_execution_report.json",
                {
                    "schema": "ragflow_optimization_cleanup_execution_report_v1",
                    "ok": True,
                    "summary": {
                        "target_count": 1,
                        "deleted_target_count": 1,
                        "failed_target_count": 0,
                        "post_cleanup_verified": False,
                    },
                    "post_cleanup_verification": {"status": "not_checked", "network_checked": False},
                },
            )
            _write_json(
                run / "field_trial_record.json",
                {
                    "schema": "ragflow_field_trial_record_v1",
                    "workflow": "kb-build",
                    "sample_types": ["scanned_pdf"],
                    "gated_trigger": "none",
                },
            )

            report, _ = build_field_trial_metrics([run])

        cleanup = report["metrics"]["cleanup"]
        self.assertEqual(cleanup["plan_count"], 1)
        self.assertEqual(cleanup["execution_count"], 1)
        self.assertEqual(cleanup["executed_count"], 1)
        self.assertEqual(cleanup["cleanup_required_count"], 2)
        self.assertEqual(cleanup["ready_target_count"], 1)
        self.assertEqual(cleanup["pending_target_count"], 1)
        self.assertEqual(cleanup["deleted_target_count"], 1)
        self.assertEqual(cleanup["failed_target_count"], 0)
        self.assertEqual(cleanup["post_cleanup_unverified_count"], 1)
        matrix_cleanup = report["retirement_observation_matrix"]["coverage"]["scanned_pdf"]["signals"]["cleanup"]
        self.assertEqual(matrix_cleanup["execution_count"], 1)
        self.assertEqual(matrix_cleanup["executed_count"], 1)

    def test_markdown_renderer_summarizes_metrics(self) -> None:
        report = {
            "schema": SCHEMA,
            "summary": {
                "json_report_count": 2,
                "recognized_report_count": 2,
                "finding_count": 0,
                "triggered_track_count": 1,
            },
            "metrics": {
                "handoff": {
                    "doc_manifest_count": 1,
                    "document_count": 2,
                    "blocked_quality_count": 0,
                    "quality_warning_count": 1,
                },
                "kb_build": {"report_count": 1, "runtime_failure_count": 0, "runtime_timeout_count": 0},
                "query": {
                    "report_count": 0,
                    "zero_result_count": 0,
                    "citation_audit_failure_count": 0,
                    "answer_evaluation_failure_count": 0,
                },
                "release": {"report_count": 0, "ok_count": 0, "failure_count": 0},
                "cleanup": {
                    "plan_count": 1,
                    "execution_count": 1,
                    "executed_count": 1,
                    "cleanup_required_count": 1,
                    "pending_target_count": 0,
                    "deleted_target_count": 1,
                    "post_cleanup_unverified_count": 1,
                },
            },
            "gated_triggers": [{"track": "serve", "count": 1, "reasons": ["host needs lifecycle"]}],
            "retirement_observation_matrix": {
                "schema": RETIREMENT_MATRIX_SCHEMA,
                "summary": {
                    "expected_sample_type_count": 8,
                    "observed_expected_sample_type_count": 1,
                    "missing_expected_sample_type_count": 7,
                    "needs_review_sample_type_count": 0,
                },
                "retirement_assessment": {"status": "insufficient_samples"},
                "coverage": {
                    "scanned_pdf": {
                        "status": "passed",
                        "report_count": 2,
                        "signals": {
                            "quality": {"pass_count": 1, "pass_with_review_count": 0, "blocked_count": 0},
                            "dry_run": {"passed_count": 1, "failed_count": 0},
                            "live_parse": {"passed_count": 0, "failed_count": 0},
                            "query": {"zero_result_count": 0, "output_count": 0},
                        },
                    }
                },
            },
            "findings": [],
        }

        text = render_markdown(report)

        self.assertIn("# RAGFlow Field Trial Metrics", text)
        self.assertIn("reports scanned: `2`", text)
        self.assertIn("## Retirement Observation Matrix", text)
        self.assertIn("| `scanned_pdf` | `passed` | `2` |", text)
        self.assertIn("Cleanup", text)
        self.assertIn("`serve`", text)

    def test_cli_writes_json_markdown_and_redaction_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run-001"
            _write_json(run / "release_hygiene.json", {"schema": "ragflow_release_hygiene_check_v1", "ok": True})
            output_json = root / "field_trial_summary.json"
            output_md = root / "field_trial_summary.md"
            redaction_json = root / "field_trial_summary.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_DIR / "field_trial_metrics.py"),
                    str(run),
                    "--report-json",
                    str(output_json),
                    "--report-md",
                    str(output_md),
                    "--redaction-report",
                    str(redaction_json),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertTrue(redaction_json.exists())
            self.assertIn('"schema": "ragflow_field_trial_metrics_v1"', result.stdout)


if __name__ == "__main__":
    unittest.main()
