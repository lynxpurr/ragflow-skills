from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from consumer_acceptance import (  # noqa: E402
    _github_env,
    _minimal_env,
    _write_fake_mineru_cli,
    run_consumer_acceptance,
)
from export_release_archives import export_release_archives  # noqa: E402


class ConsumerAcceptanceTests(unittest.TestCase):
    def test_fake_mineru_cli_executes_with_secret_shaped_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.pdf"
            source.write_bytes(b"%PDF fake")
            output = root / "output"
            cli_path = _write_fake_mineru_cli(root / "mineru-token=runtime-secret")

            result = subprocess.run(
                [str(cli_path), "-b", "pipeline", "-p", str(source), "-o", str(output)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "sample.md").exists())
            self.assertTrue((output / "images" / "chart.jpg").exists())

    def test_minimal_env_preserves_windows_runtime_context(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "SYSTEMROOT": "C:\\Windows",
                "USERPROFILE": "C:\\Users\\test-user",
                "TEMP": "C:\\Temp",
            },
            clear=True,
        ):
            env = _minimal_env()

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["SYSTEMROOT"], "C:\\Windows")
        self.assertEqual(env["USERPROFILE"], "C:\\Users\\test-user")
        self.assertEqual(env["TEMP"], "C:\\Temp")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_github_env_preserves_auth_context(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "HOME": "/tmp/test-home",
                "GH_TOKEN": "token",
                "GITHUB_TOKEN": "github-token",
            },
            clear=True,
        ):
            env = _github_env()

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["HOME"], "/tmp/test-home")
        self.assertEqual(env["GH_TOKEN"], "token")
        self.assertEqual(env["GITHUB_TOKEN"], "github-token")
        self.assertEqual(env["GH_PROMPT_DISABLED"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_rejects_artifacts_inside_overwritten_work_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "artifacts directory"):
                run_consumer_acceptance(
                    artifacts_dir=root / "work" / "downloads",
                    work_root=root / "work",
                    overwrite=True,
                )

    def test_run_consumer_acceptance_from_local_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_payload = export_release_archives(
                dist_dir=root / "dist",
                output_dir=root / "release-artifacts",
                rebuild=True,
                hygiene=True,
            )
            self.assertTrue(export_payload["ok"], export_payload)

            payload = run_consumer_acceptance(
                artifacts_dir=root / "release-artifacts",
                work_root=root / "consumer",
                live_build=True,
                env={},
            )
            report_json = Path(payload["reports"]["json"])
            report_md = Path(payload["reports"]["markdown"])
            self.assertTrue(report_json.exists(), payload)
            self.assertTrue(report_md.exists(), payload)

        self.assertTrue(payload["ok"], payload)
        check_names = [check["name"] for check in payload["checks"]]
        self.assertIn("vendored runtime present", check_names)
        self.assertIn("canonical-review markdown audit help", check_names)
        self.assertIn("canonical-review asset audit help", check_names)
        self.assertIn("generated report redaction fixture", check_names)
        self.assertIn("doc-to-md passthrough", check_names)
        self.assertIn("quality_report produced", check_names)
        self.assertIn("doc-to-md convert redaction", check_names)
        self.assertIn("doc-to-md convert redaction sidecar", check_names)
        self.assertIn("doc-to-md image fallback", check_names)
        self.assertIn("image fallback preserves source image with review gate", check_names)
        self.assertIn("doc-to-md mineru-cli auto", check_names)
        self.assertIn("mineru-cli doc_manifest produced", check_names)
        self.assertIn("mineru-cli local image asset copied", check_names)
        self.assertIn("mineru-cli quality gate passes with local image", check_names)
        self.assertIn("mineru-cli runtime report summarizes process attempt", check_names)
        self.assertIn("doc-to-md mineru-v4 async", check_names)
        self.assertIn("mineru-v4 markdown produced", check_names)
        self.assertIn("mineru-v4 async protocol exercised", check_names)
        self.assertIn("mineru-v4 reports omit endpoint and signed URLs", check_names)
        self.assertIn("doc-to-md convert runtime redaction", check_names)
        self.assertIn("doc-to-md backend probe", check_names)
        self.assertIn("doc-to-md backend probe partial failure", check_names)
        self.assertIn("doc-to-md backend warmup", check_names)
        self.assertIn("doc-to-md backend warmup redaction", check_names)
        self.assertIn("doc-to-md inspect quality", check_names)
        self.assertIn("doc-to-md inspect redaction", check_names)
        self.assertIn("doc-to-md adaptive decision-only", check_names)
        self.assertIn("doc-to-md segment plan", check_names)
        self.assertIn("doc-to-md segment plan redaction", check_names)
        self.assertIn("doc-to-md split", check_names)
        self.assertIn("doc-to-md split resume", check_names)
        self.assertIn("doc-to-md split redaction", check_names)
        self.assertIn("kb-build split manifest dry-run", check_names)
        self.assertIn("doc-to-md postprocess redaction", check_names)
        self.assertIn("profile api payload filters internal metadata", check_names)
        self.assertIn("kb-build dry-run", check_names)
        self.assertIn("kb-build model-providers probe", check_names)
        self.assertIn("kb-build model-providers partial failure", check_names)
        self.assertIn("kb-build inspect-handoff redaction", check_names)
        self.assertIn("kb-build metadata lint redaction", check_names)
        self.assertIn("kb-build metadata merge redaction", check_names)
        self.assertIn("kb-build metadata suggest-request redaction", check_names)
        self.assertIn("kb-build metadata suggest-review redaction", check_names)
        self.assertIn("kb-build tagset lint redaction", check_names)
        self.assertIn("kb-build tagset report redaction", check_names)
        self.assertIn("kb-build topology advise redaction", check_names)
        self.assertIn("kb-build topology split-plan redaction", check_names)
        self.assertIn("kb-build activation-plan redaction", check_names)
        self.assertIn("kb-build parameter-audit evidence binding", check_names)
        self.assertIn("kb-build parameter-audit redaction", check_names)
        self.assertIn("kb-build parse-report redaction", check_names)
        self.assertIn("kb-build health-report redaction", check_names)
        self.assertIn("kb-build optimize plan-only resume", check_names)
        self.assertIn("kb-build optimize command manifest dry-run", check_names)
        self.assertIn("kb-build optimize plan-only redaction", check_names)
        self.assertIn("kb-build optimize cleanup-plan redaction", check_names)
        self.assertIn("kb-build optimize readiness redaction", check_names)
        self.assertIn("kb-build optimize summarize redaction", check_names)
        self.assertIn("kb-build optimize summary benchmark strength", check_names)
        self.assertIn("kb-build optimize summary benchmark followups", check_names)
        self.assertIn("kb-build optimize summary cleanup lifecycle", check_names)
        self.assertIn("kb-build optimize summary field-trial suggestion", check_names)
        self.assertIn("kb-build benchmark import redaction", check_names)
        self.assertIn("kb-build benchmark import attribution", check_names)
        self.assertIn("kb-build benchmark import selection", check_names)
        self.assertIn("kb-build benchmark preflight redaction", check_names)
        self.assertIn("kb-build benchmark sample redaction", check_names)
        self.assertIn("kb-build benchmark sample attribution", check_names)
        self.assertIn("kb-build benchmark sample selection provenance", check_names)
        self.assertIn("kb-build benchmark summarize redaction", check_names)
        self.assertIn("kb-build benchmark gate redaction", check_names)
        self.assertIn("kb-build benchmark trend redaction", check_names)
        self.assertIn("kb-build benchmark delta redaction", check_names)
        self.assertIn("kb-build benchmark suggest redaction", check_names)
        self.assertIn("kb-build validate redaction", check_names)
        self.assertIn("kb-build qa generate resume", check_names)
        self.assertIn("kb-build qa suggest-request redaction", check_names)
        self.assertIn("kb-build qa suggest-review redaction", check_names)
        self.assertIn("kb-build append help", check_names)
        self.assertIn("kb-build append redaction", check_names)
        self.assertIn("kb-build append redaction sidecar", check_names)
        self.assertIn("kb-build cleanup help", check_names)
        self.assertIn("kb-build cleanup redaction", check_names)
        self.assertIn("kb-build cleanup redaction sidecar", check_names)
        self.assertIn("kb-build diagnose help", check_names)
        self.assertIn("kb-build diagnose redaction", check_names)
        self.assertIn("kb-build probe help", check_names)
        self.assertIn("kb-build probe redaction", check_names)
        self.assertIn("kb-build probe partial failure", check_names)
        self.assertIn("query host-assisted help", check_names)
        self.assertIn("query rewrite help", check_names)
        self.assertIn("query rewrite report", check_names)
        self.assertIn("query rewrite redaction", check_names)
        self.assertIn("query intent classify redaction", check_names)
        self.assertIn("query intent route redaction", check_names)
        self.assertIn("query session inspect redaction", check_names)
        self.assertIn("query session enrich redaction", check_names)
        self.assertIn("query agentic plan redaction", check_names)
        self.assertIn("query agentic-answer request redaction", check_names)
        self.assertIn("query agentic-answer review redaction", check_names)
        self.assertIn("query evaluator request redaction", check_names)
        self.assertIn("query evaluator review redaction", check_names)
        self.assertIn("query endpoint-report", check_names)
        self.assertIn("query endpoint-report runtime metrics", check_names)
        self.assertIn("query endpoint-report retry policy", check_names)
        self.assertIn("query endpoint-report runtime cache", check_names)
        self.assertIn("query endpoint-report runtime rate limit", check_names)
        self.assertIn("query endpoint-report runtime circuit breaker", check_names)
        self.assertIn("query endpoint-report partial failure", check_names)
        self.assertIn("query fallback test partial failure", check_names)
        self.assertIn("query assistant-profile redaction", check_names)
        self.assertIn("query assistant-test-plan redaction", check_names)
        self.assertIn("query centroid build plan-only redaction", check_names)
        self.assertIn("query centroid build redaction", check_names)
        self.assertIn("query citation audit redaction", check_names)
        self.assertIn("query cache-report", check_names)
        self.assertIn("query cache-report invalidation", check_names)
        self.assertIn("query cache-report redaction", check_names)
        self.assertIn("query answer evaluation", check_names)
        self.assertIn("query answer evaluation redaction", check_names)
        self.assertIn("query diagnostic redaction", check_names)
        self.assertIn("query pollution redaction", check_names)
        self.assertIn("query rerank ab redaction", check_names)
        self.assertIn("query cross-language ab redaction", check_names)
        self.assertIn("query fusion redaction", check_names)
        self.assertIn("query fusion test redaction", check_names)
        self.assertIn("query route-test redaction", check_names)
        self.assertIn("query route-report redaction", check_names)
        self.assertIn("query route-diagnose redaction", check_names)
        self.assertIn("query route-activation-check redaction", check_names)
        self.assertIn("query fallback test report", check_names)
        self.assertIn("query fallback test redaction", check_names)
        self.assertIn("query missing config guard", check_names)
        self.assertIn("live build skipped", check_names)
        self.assertTrue(
            any(path.endswith("query_answer_eval_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("parse_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_health_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("metadata_lint_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("metadata_merge_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("metadata_suggestion_request_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("metadata_suggestion_review_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("tagset_lint_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("tagset_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_topology_advice_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_split_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_activation_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("parameter_read_back_audit_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_plan.checkpoint.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_command_manifest.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_cleanup_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("best_profile_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_lint_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_recommendation_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_experiment_matrix_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_experiment.checkpoint.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("handoff_inspection_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_validation_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("diagnostic_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("probe_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_chunk_snapshot_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_generate_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_generate.checkpoint.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_validate_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_evidence_map_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("segment_metadata_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("suppression_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("append_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("cleanup_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_import_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_preflight_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_sample_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_summary_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_gate_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_trend_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_delta_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_suggest_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("backend_warmup_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("convert_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("convert_runtime_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("quality_report.inspect_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("postprocess_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("segmentation_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("split_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("split.checkpoint.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("split_doc_manifest.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_rewrite_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_intent_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_intent_route_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_session_inspect_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_session_enrich_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_agentic_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_agentic_answer_request_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_agentic_answer_review_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("centroid_plan_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("centroid_build_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("citation_audit_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fallback_test_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("assistant_profile_recommendation_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("assistant_test_plan_review_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_diagnostic_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_pollution_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_rerank_ab_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_cross_language_ab_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fusion_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fusion_test_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_test_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_report_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_diagnose_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_activation_check_redaction.json") for path in payload["produced_artifacts"]),
            payload["produced_artifacts"],
        )
        self.assertTrue(payload["reports"]["json"].endswith("consumer-acceptance-report.json"))

    def test_command_manifest_only_redacts_live_acceptance_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_payload = export_release_archives(
                dist_dir=root / "dist",
                output_dir=root / "release-artifacts",
                rebuild=True,
                hygiene=True,
            )
            self.assertTrue(export_payload["ok"], export_payload)
            work = root / "consumer"
            config_path = root / "private" / "ragflow.local.yaml"
            secret = "fake-command-manifest-secret"
            dataset_id = "dataset-command-manifest-private"
            local_host = "local" + "host"
            base_url = f"http://{local_host}:9380"

            payload = run_consumer_acceptance(
                artifacts_dir=root / "release-artifacts",
                work_root=work,
                live=True,
                live_build=True,
                env={
                    "RAGFLOW_BASE_URL": base_url,
                    "RAGFLOW_API_KEY": secret,
                    "RAGFLOW_DATASET_ID": dataset_id,
                    "RAGFLOW_CONFIG": str(config_path),
                },
                command_manifest_only=True,
            )

            self.assertTrue(payload["ok"], payload)
            check_names = [check["name"] for check in payload["checks"]]
            self.assertIn("command manifest dry-run", check_names)
            self.assertIn("live execution skipped by command manifest dry-run", check_names)
            self.assertNotIn("live build disposable kb", check_names)

            manifest_path = Path(payload["command_manifest"]["json"])
            redaction_path = Path(payload["command_manifest"]["redaction"])
            self.assertTrue(manifest_path.exists(), payload)
            self.assertTrue(redaction_path.exists(), payload)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            redaction = json.loads(redaction_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "ragflow_consumer_command_manifest_v1")
            self.assertEqual(manifest["summary"]["mutating_command_count"], 1)
            command_ids = {command["id"] for command in manifest["commands"]}
            self.assertIn("live-query-existing", command_ids)
            self.assertIn("live-build-disposable-kb", command_ids)
            self.assertIn("live-validate-smoke", command_ids)
            self.assertIn("live-query-direct", command_ids)
            self.assertIn("live-query-agentic", command_ids)
            build_command = next(command for command in manifest["commands"] if command["id"] == "live-build-disposable-kb")
            self.assertTrue(build_command["mutates_ragflow"])
            self.assertEqual(build_command["mutation_label"], "creates_dataset_uploads_documents_and_triggers_parse")
            self.assertTrue(build_command["expected_artifacts"])
            self.assertTrue(build_command["cleanup_notes"])

            manifest_text = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, manifest_text)
            self.assertNotIn(dataset_id, manifest_text)
            self.assertNotIn(local_host, manifest_text)
            self.assertNotIn(str(config_path), manifest_text)
            self.assertNotIn(str(work), manifest_text)
            self.assertIn("<env:RAGFLOW_DATASET_ID>", manifest_text)
            self.assertIn("<work>/live/kb_manifest.json", manifest_text)
            self.assertTrue(redaction["ok"])


if __name__ == "__main__":
    unittest.main()
