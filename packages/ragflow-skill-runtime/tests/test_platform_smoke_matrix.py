from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from platform_smoke_matrix import run_smoke_matrix, selected_profiles  # noqa: E402


class PlatformSmokeMatrixTests(unittest.TestCase):
    def test_selected_profiles_rejects_unknown_id(self) -> None:
        with self.assertRaises(SystemExit):
            selected_profiles(["missing-profile"])

    def test_run_smoke_matrix_for_source_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_smoke_matrix(
                dist_dir=Path(tmp) / "dist",
                work_root=Path(tmp) / "work",
                profile_ids=["hermes-local-source"],
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["built_skills"], ["ragflow-doc-to-md", "ragflow-kb-build", "ragflow-query"])
        self.assertEqual(len(payload["profiles"]), 1)
        profile = payload["profiles"][0]
        self.assertEqual(profile["id"], "hermes-local-source")
        self.assertTrue(profile["ok"], profile)
        check_names = [item["name"] for item in profile["checks"]]
        self.assertIn("doc-to-md passthrough", check_names)
        self.assertIn("query direct and host-assisted", check_names)

    def test_run_smoke_matrix_for_strict_vendor_env_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_smoke_matrix(
                dist_dir=Path(tmp) / "dist",
                work_root=Path(tmp) / "work",
                profile_ids=["strict-vendor-env"],
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(len(payload["profiles"]), 1)
        profile = payload["profiles"][0]
        self.assertEqual(profile["id"], "strict-vendor-env")
        self.assertEqual(profile["config_mode"], "env")
        self.assertTrue(profile["ok"], profile)
        check_names = [item["name"] for item in profile["checks"]]
        self.assertIn("doc-to-md convert redaction", check_names)
        self.assertIn("doc-to-md image fallback", check_names)
        self.assertIn("image fallback preserves source image with review gate", check_names)
        self.assertIn("doc-to-md mineru-cli auto backend", check_names)
        self.assertIn("mineru-cli markdown produced", check_names)
        self.assertIn("mineru-cli local image asset copied", check_names)
        self.assertIn("mineru-cli quality gate passes with local image", check_names)
        self.assertIn("mineru-cli runtime report summarizes process attempt", check_names)
        self.assertIn("doc-to-md mineru env backend", check_names)
        self.assertIn("mineru service markdown produced", check_names)
        self.assertIn("doc-to-md mineru-sync env backend", check_names)
        self.assertIn("mineru-sync service markdown produced", check_names)
        self.assertIn("doc-to-md backend probe", check_names)
        self.assertIn("doc-to-md backend warmup", check_names)
        self.assertIn("kb model-providers probe", check_names)
        self.assertIn("kb append redaction", check_names)
        self.assertIn("kb append redaction sidecar", check_names)
        self.assertIn("kb cleanup redaction", check_names)
        self.assertIn("kb cleanup redaction sidecar", check_names)
        self.assertIn("kb inspect-handoff redaction", check_names)
        self.assertIn("kb metadata lint redaction", check_names)
        self.assertIn("kb tagset report redaction", check_names)
        self.assertIn("kb topology advise redaction", check_names)
        self.assertIn("kb topology split-plan redaction", check_names)
        self.assertIn("kb activation-plan redaction", check_names)
        self.assertIn("kb optimize plan-only redaction", check_names)
        self.assertIn("kb optimize cleanup-plan redaction", check_names)
        self.assertIn("kb optimize summarize redaction", check_names)
        self.assertIn("kb profile lint redaction", check_names)
        self.assertIn("kb profile experiment redaction", check_names)
        self.assertIn("kb benchmark import redaction", check_names)
        self.assertIn("kb benchmark preflight redaction", check_names)
        self.assertIn("kb benchmark sample redaction", check_names)
        self.assertIn("kb benchmark delta redaction", check_names)
        self.assertIn("kb benchmark suggest redaction", check_names)
        self.assertIn("kb validation redaction", check_names)
        self.assertIn("kb qa generate redaction", check_names)
        self.assertIn("kb qa generate redaction sidecar", check_names)
        self.assertIn("kb qa validate redaction", check_names)
        self.assertIn("kb qa validate redaction sidecar", check_names)
        self.assertIn("kb snapshot-chunks redaction", check_names)
        self.assertIn("kb qa map-evidence redaction", check_names)
        self.assertIn("kb segment-metadata redaction", check_names)
        self.assertIn("kb suppression-report redaction", check_names)
        self.assertIn("query endpoint-report", check_names)
        self.assertIn("query endpoint-report runtime metrics", check_names)
        self.assertIn("query endpoint-report retry policy", check_names)
        self.assertIn("query endpoint-report runtime cache", check_names)
        self.assertIn("query endpoint-report runtime rate limit", check_names)
        self.assertIn("query endpoint-report runtime circuit breaker", check_names)
        self.assertIn("query fallback-test", check_names)
        self.assertTrue(
            any(path.endswith("mineru-handoff/doc_manifest.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("mineru-cli-handoff/doc_manifest.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("mineru-cli-handoff/runtime_report.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("image-fallback-handoff/quality_report.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any("/image-fallback-handoff/documents/images/diagram-" in path for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("backend_probe.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("backend_probe_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("convert_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("backend_warmup.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("backend_warmup_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("postprocess_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("model_provider_probe.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("model_provider_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("append_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("cleanup_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("handoff_inspection_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("metadata_lint_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("tagset_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_topology_advice_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_split_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_activation_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("optimization_cleanup_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("best_profile_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_lint_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("profile_experiment_matrix_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("validation_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_import_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_preflight_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_sample_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_delta_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("benchmark_suggestions_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("chunk_snapshot_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_generate_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_validate_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("qa_evidence_map_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("segment_metadata_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("suppression_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("parse_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("kb_health_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_endpoint_report.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_endpoint_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_rewrite_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_intent_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_intent_route_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_session_inspect_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_session_enrich_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_agentic_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("citation_audit_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fallback_test_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("centroid_plan_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("centroid_build_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("assistant_profile_recommendation_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("assistant_test_plan_review_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_answer_eval_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_diagnostic_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_pollution_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_rerank_ab_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_cross_language_ab_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fusion_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fusion_test_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_test_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_report_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_diagnose_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("route_activation_check_redaction.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fallback_test.json") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("query_fallback_test.md") for path in profile["artifacts"]),
            profile["artifacts"],
        )
        self.assertTrue(
            any(path.endswith("validation_report.md") for path in profile["artifacts"]),
            profile["artifacts"],
        )

    def test_legacy_saas_profile_aliases_to_strict_vendor_env(self) -> None:
        profiles = selected_profiles(["saas-sandbox-https"])

        self.assertEqual([profile.id for profile in profiles], ["strict-vendor-env"])

    def test_legacy_manus_profile_aliases_to_artifact_runner(self) -> None:
        profiles = selected_profiles(["manus-artifact-cli"])

        self.assertEqual([profile.id for profile in profiles], ["artifact-runner-cli"])


if __name__ == "__main__":
    unittest.main()
