from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from runtime_resilience_inventory import render_markdown, run_runtime_resilience_inventory  # noqa: E402


class RuntimeResilienceInventoryTests(unittest.TestCase):
    def test_inventory_summarizes_runtime_resilience_status(self) -> None:
        report = run_runtime_resilience_inventory()

        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["schema"], "ragflow_runtime_resilience_inventory_v1")
        self.assertEqual(report["summary"]["command_count"], 102)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            report["summary"]["status_counts"],
            {
                "candidate": 0,
                "covered": 22,
                "deferred": 0,
                "not_applicable": 80,
            },
        )

    def test_inventory_classifies_representative_runtime_surfaces(self) -> None:
        report = run_runtime_resilience_inventory()
        by_command = {entry["command"]: entry for entry in report["commands"]}

        endpoint = by_command["ragflow-query endpoint-report"]
        self.assertEqual(endpoint["status"], "covered")
        self.assertEqual(
            endpoint["features"],
            ["cache", "circuit_breaker", "metrics", "partial_failure", "rate_limit", "retry"],
        )

        fallback = by_command["ragflow-query fallback-test"]
        self.assertEqual(fallback["status"], "covered")
        self.assertEqual(fallback["features"], ["partial_failure"])

        validation_suggestions = by_command["ragflow-query validation-suggestions"]
        self.assertEqual(validation_suggestions["status"], "not_applicable")
        self.assertEqual(validation_suggestions["features"], [])

        backend_probe = by_command["ragflow-doc-to-md backend probe"]
        self.assertEqual(backend_probe["status"], "covered")
        self.assertEqual(backend_probe["features"], ["partial_failure"])

        model_providers = by_command["ragflow-kb-build model-providers probe"]
        self.assertEqual(model_providers["status"], "covered")
        self.assertEqual(model_providers["features"], ["partial_failure"])

        kb_probe = by_command["ragflow-kb-build probe"]
        self.assertEqual(kb_probe["status"], "covered")
        self.assertEqual(kb_probe["features"], ["partial_failure"])

        inspect_kb = by_command["ragflow-kb-build inspect-kb"]
        self.assertEqual(inspect_kb["status"], "covered")
        self.assertEqual(inspect_kb["features"], ["partial_failure"])

        benchmark_import = by_command["ragflow-kb-build benchmark import"]
        self.assertEqual(benchmark_import["status"], "covered")
        self.assertEqual(benchmark_import["features"], ["checkpoint_resume"])

        qa_generate = by_command["ragflow-kb-build qa generate"]
        self.assertEqual(qa_generate["status"], "covered")
        self.assertEqual(qa_generate["features"], ["checkpoint_resume"])

        profile_experiment = by_command["ragflow-kb-build profile experiment"]
        self.assertEqual(profile_experiment["status"], "covered")
        self.assertEqual(profile_experiment["features"], ["checkpoint_resume", "partial_failure"])

        profile_decision = by_command["ragflow-kb-build profile decision"]
        self.assertEqual(profile_decision["status"], "not_applicable")
        self.assertEqual(profile_decision["features"], [])

        optimize = by_command["ragflow-kb-build optimize"]
        self.assertEqual(optimize["status"], "covered")
        self.assertEqual(optimize["features"], ["checkpoint_resume", "partial_failure"])

        doc_split = by_command["ragflow-doc-to-md split"]
        self.assertEqual(doc_split["status"], "covered")
        self.assertEqual(doc_split["features"], ["checkpoint_resume"])

        validate = by_command["ragflow-kb-build validate"]
        self.assertEqual(validate["status"], "covered")
        self.assertEqual(validate["features"], ["partial_failure"])

        snapshot = by_command["ragflow-kb-build snapshot-chunks"]
        self.assertEqual(snapshot["status"], "covered")
        self.assertEqual(snapshot["features"], ["partial_failure"])

        qa_validate = by_command["ragflow-kb-build qa validate"]
        self.assertEqual(qa_validate["status"], "covered")
        self.assertEqual(qa_validate["features"], ["partial_failure"])

        qa_map = by_command["ragflow-kb-build qa map-evidence"]
        self.assertEqual(qa_map["status"], "covered")
        self.assertEqual(qa_map["features"], ["partial_failure"])

        live_build = by_command["ragflow-kb-build"]
        self.assertEqual(live_build["status"], "covered")
        self.assertEqual(live_build["features"], ["metrics", "partial_failure"])

        image_ingestion_execute = by_command["ragflow-kb-build image-ingestion-execute"]
        self.assertEqual(image_ingestion_execute["status"], "covered")
        self.assertEqual(image_ingestion_execute["features"], ["partial_failure"])

        consistency_check = by_command["ragflow-kb-build consistency-check"]
        self.assertEqual(consistency_check["status"], "not_applicable")
        self.assertEqual(consistency_check["features"], [])

        ask = by_command["ragflow-query ask"]
        self.assertEqual(ask["status"], "covered")
        self.assertEqual(ask["features"], ["metrics", "partial_failure", "retry"])

        adaptive_compare = by_command["ragflow-doc-to-md compare-adaptive-summaries"]
        self.assertEqual(adaptive_compare["status"], "not_applicable")
        self.assertEqual(adaptive_compare["features"], [])

        template = by_command["ragflow-kb-build metadata generate-template"]
        self.assertEqual(template["status"], "not_applicable")
        self.assertEqual(template["features"], [])

        suggest_request = by_command["ragflow-kb-build metadata suggest-request"]
        self.assertEqual(suggest_request["status"], "not_applicable")
        self.assertEqual(suggest_request["features"], [])

        qa_suggest_request = by_command["ragflow-kb-build qa suggest-request"]
        self.assertEqual(qa_suggest_request["status"], "not_applicable")
        self.assertEqual(qa_suggest_request["features"], [])

        qa_suggest_review = by_command["ragflow-kb-build qa suggest-review"]
        self.assertEqual(qa_suggest_review["status"], "not_applicable")
        self.assertEqual(qa_suggest_review["features"], [])

        optimize_readiness = by_command["ragflow-kb-build optimize readiness"]
        self.assertEqual(optimize_readiness["status"], "not_applicable")
        self.assertEqual(optimize_readiness["features"], [])

        agentic_answer_request = by_command["ragflow-query agentic-answer request"]
        self.assertEqual(agentic_answer_request["status"], "not_applicable")
        self.assertEqual(agentic_answer_request["features"], [])

        agentic_answer_review = by_command["ragflow-query agentic-answer review"]
        self.assertEqual(agentic_answer_review["status"], "not_applicable")
        self.assertEqual(agentic_answer_review["features"], [])

        evaluator_request = by_command["ragflow-query evaluator request"]
        self.assertEqual(evaluator_request["status"], "not_applicable")
        self.assertEqual(evaluator_request["features"], [])

        evaluator_review = by_command["ragflow-query evaluator review"]
        self.assertEqual(evaluator_review["status"], "not_applicable")
        self.assertEqual(evaluator_review["features"], [])

    def test_markdown_renderer_summarizes_runtime_inventory(self) -> None:
        report = run_runtime_resilience_inventory()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "runtime-inventory.md"
            output.write_text(render_markdown(report), encoding="utf-8")
            text = output.read_text(encoding="utf-8")

        self.assertIn("# RAGFlow Runtime Resilience Inventory", text)
        self.assertIn("`ragflow-query endpoint-report`", text)
        self.assertIn("candidate: `0`", text)
        self.assertIn("deferred: `0`", text)
        self.assertIn("`checkpoint_resume`: `6`", text)
        self.assertIn("`metrics`: `3`", text)


if __name__ == "__main__":
    unittest.main()
