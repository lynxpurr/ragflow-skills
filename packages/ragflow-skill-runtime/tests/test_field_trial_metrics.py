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
    SCHEMA,
    build_field_trial_metrics,
    render_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FieldTrialMetricsTests(unittest.TestCase):
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
                run / "field_trial_record.json",
                {
                    "schema": "ragflow_field_trial_record_v1",
                    "workflow": "host-agent",
                    "gated_trigger": "serve",
                    "friction": f"Repeated CLI calls with api_key={fake_secret}",
                },
            )

            report, redaction = build_field_trial_metrics([run], explicit_secrets=[fake_secret])

        self.assertEqual(report["schema"], SCHEMA)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["json_report_count"], 6)
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
        combined = json.dumps(report, ensure_ascii=False) + json.dumps(redaction, ensure_ascii=False)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(private_home, combined)
        self.assertNotIn(private_config, combined)
        self.assertIn("<redacted:home-path>", combined)
        self.assertGreaterEqual(redaction["summary"]["redaction_count"], 1)

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
            },
            "gated_triggers": [{"track": "serve", "count": 1, "reasons": ["host needs lifecycle"]}],
            "findings": [],
        }

        text = render_markdown(report)

        self.assertIn("# RAGFlow Field Trial Metrics", text)
        self.assertIn("reports scanned: `2`", text)
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
