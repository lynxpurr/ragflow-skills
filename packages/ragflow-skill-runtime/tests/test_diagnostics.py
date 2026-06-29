from __future__ import annotations

import unittest

from ragflow_skill_runtime.diagnostics import diagnose_kb_manifest, probe_ragflow_client, render_diagnostic_markdown
from ragflow_skill_runtime.manifests import KbManifest


class FakeConfig:
    base_url = "https://ragflow.example.test"


class FakeProbeClient:
    config = FakeConfig()

    def list_datasets(self, *, page: int = 1, page_size: int = 50, name: str | None = None):
        return {
            "data": {
                "items": [
                    {"id": "short", "name": "kb:example"},
                    {"id": "0123456789abcdef", "name": "kb:example"},
                ]
            }
        }


class FailingProbeClient:
    config = FakeConfig()

    def list_datasets(self, *, page: int = 1, page_size: int = 50, name: str | None = None):
        raise RuntimeError("HTTP 503 for GET /datasets: unavailable")


class DiagnosticsTests(unittest.TestCase):
    def test_diagnose_manifest_flags_short_ids_and_parse_states(self) -> None:
        manifest = KbManifest.from_dict(
            {
                "version": "0.1",
                "dataset": {"id": "short", "name": "kb:example(1)"},
                "documents": [
                    {"document_id": "doc-short", "status": "running"},
                    {"document_id": "0123456789abcdef", "status": "done", "chunk_count": 0},
                ],
            }
        )

        report = diagnose_kb_manifest(manifest)

        issue_types = {issue["issue_type"] for issue in report["issues"]}
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], "ragflow_kb_diagnostic_report_v1")
        self.assertIn("dataset_id_short", issue_types)
        self.assertIn("dataset_name_suffix_fragment", issue_types)
        self.assertIn("document_parse_not_done", issue_types)
        self.assertIn("document_zero_chunks", issue_types)

    def test_diagnose_manifest_uses_live_states(self) -> None:
        manifest = KbManifest.from_dict(
            {
                "version": "0.1",
                "dataset": {"id": "0123456789abcdef", "name": "kb:example"},
                "documents": [
                    {"document_id": "0123456789abcdef", "status": "uploaded", "chunk_count": None},
                ],
            }
        )

        report = diagnose_kb_manifest(
            manifest,
            live_states={
                "0123456789abcdef": {
                    "status": "failed",
                    "chunk_count": 0,
                    "progress_msg": "[ERROR] provider unavailable",
                }
            },
        )

        self.assertFalse(report["ok"])
        self.assertIn("document_parse_failed", {issue["issue_type"] for issue in report["issues"]})

    def test_probe_reports_dataset_list_shape_and_short_ids(self) -> None:
        report = probe_ragflow_client(FakeProbeClient())
        markdown = render_diagnostic_markdown(report)

        self.assertTrue(report["ok"])
        self.assertTrue(report["capabilities"]["list_datasets"])
        self.assertEqual(report["capabilities"]["dataset_count_sample"], 2)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "completed_with_warnings")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["warning_count"], 1)
        self.assertIn("runtime_partial_failure_status: `completed_with_warnings`", markdown)
        self.assertIn("dataset_id_short", {issue["issue_type"] for issue in report["issues"]})

    def test_probe_runtime_partial_failure_marks_dataset_list_errors(self) -> None:
        report = probe_ragflow_client(FailingProbeClient())

        self.assertFalse(report["ok"])
        self.assertFalse(report["capabilities"]["list_datasets"])
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "failed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
