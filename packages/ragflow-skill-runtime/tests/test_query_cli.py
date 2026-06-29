from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


QUERY_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "ragflow-query"
    / "scripts"
    / "query.py"
)


def load_query_module():
    spec = importlib.util.spec_from_file_location("ragflow_query_cli", QUERY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeQueryClient:
    last_request = None
    requests = []

    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
        FakeQueryClient.last_request = {
            "question": question,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
        }
        FakeQueryClient.requests.append(FakeQueryClient.last_request)
        return {
            "data": {
                "chunks": [
                    {
                        "content_with_weight": f"answer for {question}",
                        "docnm_kwd": "source.md",
                        "similarity": 0.88,
                        "kb_id": dataset_ids[0],
                    }
                ]
            }
        }


class QueryCliTests(unittest.TestCase):
    def test_agentic_without_host_assisted_returns_error(self) -> None:
        module = load_query_module()
        code = module.main(["ask", "question", "--mode", "agentic", "--json"])
        self.assertEqual(code, 2)

    def test_missing_dataset_returns_clear_error_before_network(self) -> None:
        module = load_query_module()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--json",
                ]
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 2)
        self.assertEqual(payload["retrieval_status"], "error")
        self.assertEqual(payload["retrieval_status_report"]["schema"], "ragflow_retrieval_status_v1")

    def test_runtime_options_are_accepted_after_subcommand(self) -> None:
        module = load_query_module()
        code = module.main(
            [
                "ask",
                "question",
                "--mode",
                "direct",
                "--json",
                "--base-url",
                "https://ragflow.example.test",
                "--api-key",
                "test-key",
            ]
        )
        self.assertEqual(code, 2)

    def test_endpoint_report_command_writes_redacted_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "endpoint_report.json"
            report_md = root / "endpoint_report.md"
            redaction_json = root / "endpoint_redaction.json"
            cache_dir = root / "endpoint-cache"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "endpoint-report",
                        "--base-url",
                        "https://192.168.10.20:9380",
                        "--api-key",
                        "secret-key",
                        "--endpoint",
                        "vpn=http://100.64.10.20:8080/v1?token=fake-secret",
                        "--retry-budget",
                        "2",
                        "--retry-backoff-seconds",
                        "0",
                        "--cache-dir",
                        str(cache_dir),
                        "--cache-ttl-seconds",
                        "60",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)
            markdown = report_md.read_text(encoding="utf-8")

        combined = "\n".join([output, report_text, redaction_text, markdown])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_query_endpoint_report_v1")
        self.assertEqual(file_payload["schema"], "ragflow_query_endpoint_report_v1")
        self.assertEqual(payload["runtime_metrics"]["schema"], "ragflow_runtime_metrics_v1")
        self.assertEqual(file_payload["runtime_metrics"]["schema"], "ragflow_runtime_metrics_v1")
        self.assertEqual(payload["runtime_cache"]["schema"], "ragflow_runtime_cache_report_v1")
        self.assertTrue(payload["runtime_cache"]["enabled"])
        self.assertEqual(payload["runtime_cache"]["summary"]["lookup_count"], 0)
        self.assertEqual(payload["runtime_metrics"]["counters"]["endpoint_count"], 2)
        self.assertEqual(payload["runtime_metrics"]["latency_ms"]["sample_count"], 0)
        self.assertEqual(payload["retry_policy"]["retry_budget"], 2)
        self.assertEqual(payload["summary"]["network_attempt_count"], 0)
        self.assertEqual(payload["summary"]["retry_count"], 0)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["target_counts"]["explicit_secrets"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["private_hosts"], 1)
        self.assertEqual(payload["endpoints"][0]["endpoint"]["network_zone"], "lan")
        self.assertEqual(payload["endpoints"][1]["endpoint"]["network_zone"], "vpn")
        self.assertIn("RAGFlow Query Endpoint Report", markdown)
        self.assertIn("latency_samples: `0`", markdown)
        self.assertIn("retry_budget: `2`", markdown)
        self.assertIn("retry_count: `0`", markdown)
        self.assertIn("cache_enabled: `true`", markdown)
        self.assertIn("<lan-host>", combined)
        self.assertIn("<vpn-host>", combined)
        self.assertNotIn("192.168.10.20", combined)
        self.assertNotIn("100.64.10.20", combined)
        self.assertNotIn("secret-key", combined)
        self.assertNotIn("fake-secret", combined)
        self.assertNotIn(str(cache_dir), combined)

    def test_evaluate_answer_writes_redacted_report_sidecar(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            report_json = root / "answer_eval.json"
            report_md = root / "answer_eval.md"
            redaction_json = root / "answer_eval_redaction.json"
            private_host = ".".join(["192", "168", "44", "55"])
            fake_token = "fake-eval-token"
            fake_key = "fake-eval-secret"
            home_path = str(Path.home() / ".ragflow" / "config.local.yaml")
            query_output.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "question": (
                            f"Can known term use http://{private_host}:9380/v1?token={fake_token} "
                            f"from {home_path}?"
                        ),
                        "chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "content": "known term is available in this validation chunk",
                                "similarity": 0.91,
                                "document_name": "doc.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            answer = f"The known term is supported [1]. Debug api_key={fake_key} path {query_output}"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "evaluate-answer",
                        "--query-output",
                        str(query_output),
                        "--answer",
                        answer,
                        "--expected-term",
                        "known term",
                        "--require-citation",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_answer_evaluation_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["config_paths"], 4)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(query_output), combined)

    def test_diagnose_result_writes_redacted_report_sidecar(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            trace_json = root / "trace.json"
            audit_json = root / "citation_audit.json"
            report_json = root / "diagnostic.json"
            report_md = root / "diagnostic.md"
            redaction_json = root / "diagnostic_redaction.json"
            private_host = ".".join(["10", "44", "55", "66"])
            fake_token = "fake-diagnostic-token"
            fake_key = "fake-diagnostic-secret"
            home_path = str(Path.home() / ".ragflow" / "diagnostic.local.yaml")
            query_output.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "question": (
                            f"Can known term use http://{private_host}:9380/api?token={fake_token} "
                            f"from {home_path}?"
                        ),
                        "mode": "agentic",
                        "dataset_ids": ["ds-diagnostic"],
                        "chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "content": "known term appears in this diagnostic chunk",
                                "similarity": 0.91,
                                "document_name": "doc.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            trace_json.write_text(
                json.dumps(
                    {
                        "warnings": [
                            f"probe used Bearer {fake_key} at http://{private_host}:8080/path?access_token={fake_token}",
                            f"trace path {trace_json}",
                        ],
                        "route": {"selected": {"reason": "default", "name": home_path, "dataset_id": "ds"}},
                    }
                ),
                encoding="utf-8",
            )
            audit_json.write_text(
                json.dumps(
                    {
                        "metrics": {
                            "invalid_citation_count": 0,
                            "warnings": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "diagnose-result",
                        "--query-output",
                        str(query_output),
                        "--trace-json",
                        str(trace_json),
                        "--citation-audit",
                        str(audit_json),
                        "--expected-term",
                        "known term",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_query_diagnostic_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["bearer_token"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:bearer-token>", combined)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(trace_json), combined)

    def test_kb_manifest_can_supply_dataset_id_before_network(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                """
{
  "version": "0.1",
  "dataset": {"id": "ds-1", "name": "kb:test"},
  "documents": []
}
""".strip(),
                encoding="utf-8",
            )
            code = module.main(
                [
                    "--base-url",
                    "https://127.0.0.1.invalid",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--kb-manifest",
                    str(manifest),
                    "--json",
                ]
            )
        self.assertEqual(code, 2)

    def test_direct_mode_can_succeed_with_fake_client(self) -> None:
        module = load_query_module()
        module.RAGFlowClient = FakeQueryClient
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--dataset-id",
                    "ds-1",
                    "--json",
                ]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["retrieval_status"], "success")
        self.assertEqual(payload["retrieval_status_report"]["schema"], "ragflow_retrieval_status_v1")
        self.assertEqual(payload["metadata"]["retrieval_status"], "success")

    def test_direct_mode_marks_empty_retrieval_status(self) -> None:
        class EmptyClient(FakeQueryClient):
            def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
                return {"data": {"chunks": []}}

        module = load_query_module()
        module.RAGFlowClient = EmptyClient
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--dataset-id",
                    "ds-1",
                    "--json",
                    "--include-trace",
                ]
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(payload["retrieval_status"], "empty")
        self.assertEqual(payload["metadata"]["retrieval_status"], "empty")
        self.assertEqual(payload["trace"]["retrieval"]["status"], "empty")
        self.assertIn("retrieval returned zero chunks", payload["trace"]["warnings"])

    def test_direct_mode_can_fuse_multiple_dataset_results(self) -> None:
        class MultiDatasetClient(FakeQueryClient):
            def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
                FakeQueryClient.last_request = {
                    "question": question,
                    "dataset_ids": dataset_ids,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                }
                FakeQueryClient.requests.append(FakeQueryClient.last_request)
                dataset_id = dataset_ids[0]
                return {
                    "data": {
                        "chunks": [
                            {
                                "id": f"{dataset_id}-chunk",
                                "content_with_weight": f"{dataset_id} answer for {question}",
                                "docnm_kwd": f"{dataset_id}.md",
                                "similarity": 0.9 if dataset_id == "ds-1" else 0.8,
                                "kb_id": dataset_id,
                            }
                        ]
                    }
                }

        module = load_query_module()
        module.RAGFlowClient = MultiDatasetClient
        FakeQueryClient.requests = []
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--dataset-id",
                    "ds-1",
                    "--dataset-id",
                    "ds-2",
                    "--fusion",
                    "rrf",
                    "--json",
                    "--include-trace",
                ]
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual([request["dataset_ids"] for request in FakeQueryClient.requests], [["ds-1"], ["ds-2"]])
        self.assertEqual(payload["fusion"]["schema"], "ragflow_fusion_report_v1")
        self.assertEqual(payload["metadata"]["fusion"], "rrf")
        self.assertEqual(payload["retrieval_status"], "success")
        self.assertIn("fusion", payload["trace"])
        self.assertEqual(len(payload["chunks"]), 2)

    def test_rewrite_command_writes_plan_outputs(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "rewrite.json"
            report_md = root / "rewrite.md"
            redaction_json = root / "rewrite_redaction.json"
            private_host = ".".join(["192", "168", "67", "88"])
            fake_token = "fake-rewrite-token"
            fake_key = "fake-rewrite-secret"
            home_path = str(Path.home() / ".ragflow" / "rewrite.local.yaml")
            question = (
                f"How do I configure runtime using http://{private_host}:9380/v1?token={fake_token} "
                f"api_key={fake_key} from {home_path}?"
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "rewrite",
                        question,
                        "--rewrite",
                        "simple",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8")

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_query_rewrite_plan_v1")
        self.assertGreaterEqual(payload["summary"]["generated_query_count"], 1)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Rewrite Plan", markdown)
        self.assertIn("how to configure runtime", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)

    def test_intent_commands_write_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intent_json = root / "intent.json"
            intent_md = root / "intent.md"
            intent_redaction_json = root / "intent_redaction.json"
            route_json = root / "route.json"
            route_md = root / "route.md"
            route_redaction_json = root / "route_redaction.json"
            private_host = ".".join(["192", "168", "68", "90"])
            fake_token = "fake-intent-token"
            fake_key = "fake-intent-secret"
            question = (
                f"Compare runtime config versus metadata routing at http://{private_host}:9380/v1?token={fake_token} "
                f"api_key={fake_key}"
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                classify_code = module.main(
                    [
                        "intent",
                        "classify",
                        question,
                        "--report-json",
                        str(intent_json),
                        "--report-md",
                        str(intent_md),
                        "--redaction-report",
                        str(intent_redaction_json),
                        "--json",
                    ]
                )
            intent_output = stdout.getvalue()
            intent_payload = json.loads(intent_output)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_code = module.main(
                    [
                        "intent",
                        "route",
                        "What about it?",
                        "--report-json",
                        str(route_json),
                        "--report-md",
                        str(route_md),
                        "--redaction-report",
                        str(route_redaction_json),
                        "--json",
                    ]
                )
            route_output = stdout.getvalue()
            route_payload = json.loads(route_output)

            intent_json_exists = intent_json.exists()
            route_json_exists = route_json.exists()
            intent_report_text = intent_json.read_text(encoding="utf-8")
            intent_redaction_text = intent_redaction_json.read_text(encoding="utf-8")
            intent_redaction_payload = json.loads(intent_redaction_text)
            route_redaction_text = route_redaction_json.read_text(encoding="utf-8")
            route_redaction_payload = json.loads(route_redaction_text)
            intent_markdown = intent_md.read_text(encoding="utf-8")
            route_markdown = route_md.read_text(encoding="utf-8")

        combined = "\n".join([intent_output, intent_report_text, intent_markdown, intent_redaction_text])
        self.assertEqual(classify_code, 0)
        self.assertEqual(intent_payload["schema"], "ragflow_query_intent_v1")
        self.assertEqual(intent_payload["intent"], "comparison")
        self.assertEqual(intent_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(intent_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(intent_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(intent_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertEqual(route_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(route_redaction_payload["target_counts"]["config_paths"], 3)
        self.assertTrue(intent_json_exists)
        self.assertIn("RAGFlow Query Intent", intent_markdown)
        self.assertEqual(route_code, 0)
        self.assertEqual(route_payload["schema"], "ragflow_query_route_decision_v1")
        self.assertEqual(route_payload["status"], "clarification")
        self.assertTrue(route_json_exists)
        self.assertIn("RAGFlow Query Route Decision", route_markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)

    def test_session_commands_write_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "session.json"
            inspect_json = root / "session_inspect.json"
            inspect_md = root / "session_inspect.md"
            inspect_redaction_json = root / "session_inspect_redaction.json"
            enrich_json = root / "session_enrich.json"
            enrich_md = root / "session_enrich.md"
            enrich_redaction_json = root / "session_enrich_redaction.json"
            private_host = ".".join(["192", "168", "69", "91"])
            fake_token = "fake-session-token"
            fake_key = "fake-session-secret"
            home_path = str(Path.home() / ".ragflow" / "session.local.yaml")
            session.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_query_session_v1",
                        "session_id": "cli-session",
                        "turns": [
                            {
                                "role": "user",
                                "content": (
                                    f"How do I configure runtime settings with http://{private_host}:9380/v1?"
                                    f"token={fake_token} api_key={fake_key} from {home_path}?"
                                ),
                            },
                            {"role": "assistant", "content": "Use a runtime config file."},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                inspect_code = module.main(
                    [
                        "session",
                        "inspect",
                        "--session",
                        str(session),
                        "--report-json",
                        str(inspect_json),
                        "--report-md",
                        str(inspect_md),
                        "--redaction-report",
                        str(inspect_redaction_json),
                        "--json",
                    ]
                )
            inspect_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                enrich_code = module.main(
                    [
                        "session",
                        "enrich",
                        "What about it?",
                        "--session",
                        str(session),
                        "--report-json",
                        str(enrich_json),
                        "--report-md",
                        str(enrich_md),
                        "--redaction-report",
                        str(enrich_redaction_json),
                        "--json",
                    ]
                )
            enrich_payload = json.loads(stdout.getvalue())
            inspect_json_exists = inspect_json.exists()
            enrich_json_exists = enrich_json.exists()
            inspect_report_text = inspect_json.read_text(encoding="utf-8")
            enrich_report_text = enrich_json.read_text(encoding="utf-8")
            inspect_redaction_text = inspect_redaction_json.read_text(encoding="utf-8")
            enrich_redaction_text = enrich_redaction_json.read_text(encoding="utf-8")
            inspect_redaction_payload = json.loads(inspect_redaction_text)
            enrich_redaction_payload = json.loads(enrich_redaction_text)
            inspect_markdown = inspect_md.read_text(encoding="utf-8")
            enrich_markdown = enrich_md.read_text(encoding="utf-8")

        combined = "\n".join(
            [
                inspect_report_text,
                enrich_report_text,
                inspect_markdown,
                enrich_markdown,
                inspect_redaction_text,
                enrich_redaction_text,
            ]
        )
        self.assertEqual(inspect_code, 0)
        self.assertEqual(inspect_payload["schema"], "ragflow_query_session_inspection_v1")
        self.assertEqual(inspect_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(inspect_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(inspect_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(inspect_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(inspect_redaction_payload["rule_counts"]["home_path"], 1)
        self.assertTrue(inspect_json_exists)
        self.assertIn("RAGFlow Query Session Inspection", inspect_markdown)
        self.assertEqual(enrich_code, 0)
        self.assertEqual(enrich_payload["schema"], "ragflow_query_session_enrichment_v1")
        self.assertEqual(enrich_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(enrich_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(enrich_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(enrich_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(enrich_redaction_payload["rule_counts"]["home_path"], 1)
        self.assertTrue(enrich_payload["context_applied"])
        self.assertIn("How do I configure runtime settings with", enrich_payload["enriched_question"])
        self.assertTrue(enrich_json_exists)
        self.assertIn("RAGFlow Query Session Enrichment", enrich_markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)

    def test_agentic_plan_command_writes_plan_outputs(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "agentic_plan.json"
            report_md = root / "agentic_plan.md"
            redaction_json = root / "agentic_plan_redaction.json"
            private_host = ".".join(["192", "168", "70", "92"])
            fake_token = "fake-agentic-token"
            fake_key = "fake-agentic-secret"
            home_path = str(Path.home() / ".ragflow" / "agentic.local.yaml")
            question = (
                f"Compare runtime configuration and metadata routing tradeoffs using "
                f"http://{private_host}:9380/v1?token={fake_token} api_key={fake_key} from {home_path}"
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "agentic-plan",
                        question,
                        "--max-subqueries",
                        "2",
                        "--reflection-budget",
                        "1",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8")

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_agentic_plan_v1")
        self.assertEqual(payload["trace_template"]["schema"], "ragflow_agentic_trace_v1")
        self.assertEqual(payload["summary"]["llm_calls"], 0)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Agentic Plan", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)

    def test_ask_rewrite_and_multi_query_record_trace_and_retrievals(self) -> None:
        class RewriteClient(FakeQueryClient):
            def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
                FakeQueryClient.last_request = {
                    "question": question,
                    "dataset_ids": dataset_ids,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                }
                FakeQueryClient.requests.append(FakeQueryClient.last_request)
                chunk_id = "original" if question == "How do I configure runtime?" else question.replace(" ", "-")
                return {
                    "data": {
                        "chunks": [
                            {
                                "id": chunk_id,
                                "content_with_weight": f"answer for {question}",
                                "docnm_kwd": f"{chunk_id}.md",
                                "similarity": 0.9 if chunk_id == "original" else 0.75,
                                "kb_id": dataset_ids[0],
                            }
                        ]
                    }
                }

        module = load_query_module()
        module.RAGFlowClient = RewriteClient
        FakeQueryClient.requests = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            multi_query = root / "multi.json"
            trace_json = root / "trace.json"
            multi_query.write_text(json.dumps({"queries": [{"id": "manual-cn", "query": "运行时 配置"}]}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "--base-url",
                        "https://ragflow.example.test",
                        "--api-key",
                        "test-key",
                        "ask",
                        "How do I configure runtime?",
                        "--mode",
                        "direct",
                        "--dataset-id",
                        "ds-1",
                        "--rewrite",
                        "simple",
                        "--multi-query",
                        str(multi_query),
                        "--trace-json",
                        str(trace_json),
                        "--include-trace",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            trace = json.loads(trace_json.read_text(encoding="utf-8"))

        self.assertEqual(code, 0, stdout.getvalue())
        requested_questions = [request["question"] for request in FakeQueryClient.requests]
        self.assertIn("How do I configure runtime?", requested_questions)
        self.assertIn("how to configure runtime", requested_questions)
        self.assertIn("运行时 配置", requested_questions)
        self.assertEqual(payload["rewrite"]["schema"], "ragflow_query_rewrite_plan_v1")
        self.assertEqual(payload["fusion"]["schema"], "ragflow_fusion_report_v1")
        self.assertEqual(payload["metadata"]["fusion"], "rrf")
        self.assertEqual(len(payload["retrievals"]), len(requested_questions))
        self.assertIn("rewrite", payload["trace"])
        self.assertIn("rewrite", trace)
        self.assertEqual(trace["cost"]["ragflow_retrieval_calls"], len(requested_questions))
        self.assertEqual(trace["rewrite"]["retrieval_queries"][0]["id"], "original")

    def test_hyde_rewrite_is_gated_before_retrieval(self) -> None:
        module = load_query_module()
        module.RAGFlowClient = FakeQueryClient
        FakeQueryClient.requests = []
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "direct",
                    "--dataset-id",
                    "ds-1",
                    "--rewrite",
                    "hyde",
                    "--json",
                ]
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 2)
        self.assertIn("requires explicit LLM config", payload["error"])
        self.assertEqual(FakeQueryClient.requests, [])

    def test_host_assisted_mode_can_succeed_with_fake_client(self) -> None:
        module = load_query_module()
        module.RAGFlowClient = FakeQueryClient
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "question",
                    "--mode",
                    "agentic",
                    "--host-assisted",
                    "--dataset-id",
                    "ds-1",
                    "--json",
                ]
            )
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertIn('"host_assisted": true', stdout.getvalue().lower())

    def test_agentic_host_assisted_retrieves_bounded_subqueries(self) -> None:
        class AgenticClient(FakeQueryClient):
            def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
                FakeQueryClient.last_request = {
                    "question": question,
                    "dataset_ids": dataset_ids,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                }
                FakeQueryClient.requests.append(FakeQueryClient.last_request)
                return {
                    "data": {
                        "chunks": [
                            {
                                "id": question.lower().replace(" ", "-"),
                                "content_with_weight": f"agentic evidence for {question}",
                                "docnm_kwd": "agentic.md",
                                "similarity": 0.86,
                                "kb_id": dataset_ids[0],
                            }
                        ]
                    }
                }

        module = load_query_module()
        module.RAGFlowClient = AgenticClient
        FakeQueryClient.requests = []
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "ask",
                    "Compare runtime configuration and metadata routing tradeoffs",
                    "--mode",
                    "agentic",
                    "--host-assisted",
                    "--dataset-id",
                    "ds-1",
                    "--max-subqueries",
                    "2",
                    "--reflection-budget",
                    "1",
                    "--include-trace",
                    "--json",
                ]
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(payload["agentic_plan"]["schema"], "ragflow_agentic_plan_v1")
        self.assertEqual(payload["agentic_plan"]["summary"]["generated_subquery_count"], 2)
        self.assertEqual(payload["metadata"]["retrieval_call_count"], 3)
        self.assertEqual(len(FakeQueryClient.requests), 3)
        self.assertIn("retrievals", payload)
        self.assertIn("fusion", payload)
        self.assertEqual(payload["trace"]["agentic_plan"]["trace_template"]["llm_calls"], 0)
        self.assertEqual(payload["agentic_trace"]["schema"], "ragflow_agentic_trace_v1")
        self.assertEqual(payload["agentic_trace"]["status"], "retrieval_executed")
        self.assertEqual(payload["agentic_trace"]["retrieval_calls"], 3)
        self.assertEqual(payload["agentic_trace"]["llm_calls"], 0)
        self.assertIsNone(payload["agentic_trace"]["model"])
        self.assertEqual(payload["agentic_trace"]["estimated_tokens"], 0)
        self.assertEqual(payload["agentic_trace"]["cost_trace"]["estimated_total_usd"], 0.0)
        self.assertEqual(payload["metadata"]["agentic_trace"]["schema"], "ragflow_agentic_trace_v1")
        self.assertEqual(payload["trace"]["agentic_trace"]["cost_trace"]["estimated_total_usd"], 0.0)
        self.assertEqual(payload["host_synthesis_contract"]["schema"], "ragflow_host_synthesis_contract_v1")
        self.assertEqual(payload["host_synthesis_contract"]["status"], "ready")
        self.assertEqual(payload["host_synthesis_contract"]["retrieval_status"], "success")
        self.assertEqual(
            payload["host_synthesis_contract"]["citation_policy"]["compatible_with"],
            "audit-citations",
        )
        self.assertEqual(
            payload["host_synthesis_contract"]["citation_policy"]["valid_citation_ids"],
            ["[1]", "[2]", "[3]"],
        )
        self.assertTrue(payload["host_synthesis_contract"]["citation_policy"]["required"])
        self.assertFalse(payload["host_synthesis_contract"]["evidence_policy"]["allow_external_facts"])
        self.assertEqual(
            payload["trace"]["host_synthesis_contract"]["citation_policy"]["format"],
            "numeric_bracket",
        )
        self.assertEqual(payload["retrieval_status"], "success")

    def test_ask_can_write_trace_and_audit_citations(self) -> None:
        module = load_query_module()
        module.RAGFlowClient = FakeQueryClient
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_json = root / "trace.json"
            trace_md = root / "trace.md"
            query_output = root / "query.json"
            audit_json = root / "audit.json"
            audit_md = root / "audit.md"
            answer_eval_json = root / "answer_eval.json"
            answer_eval_md = root / "answer_eval.md"
            diagnostic_json = root / "diagnostic.json"
            diagnostic_md = root / "diagnostic.md"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "--base-url",
                        "https://ragflow.example.test",
                        "--api-key",
                        "test-key",
                        "ask",
                        "question",
                        "--mode",
                        "agentic",
                        "--host-assisted",
                        "--dataset-id",
                        "ds-1",
                        "--json",
                        "--include-trace",
                        "--trace-json",
                        str(trace_json),
                        "--trace-md",
                        str(trace_md),
                    ]
                )
            query_output.write_text(stdout.getvalue(), encoding="utf-8")
            payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_code = module.main(
                    [
                        "audit-citations",
                        "--query-output",
                        str(query_output),
                        "--answer",
                        "The answer is supported by the retrieved evidence [1].",
                        "--report-json",
                        str(audit_json),
                        "--report-md",
                        str(audit_md),
                        "--json",
                    ]
                )
            audit_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                answer_eval_code = module.main(
                    [
                        "evaluate-answer",
                        "--query-output",
                        str(query_output),
                        "--answer",
                        "The answer is supported by the retrieved evidence [1].",
                        "--expected-term",
                        "answer",
                        "--require-citation",
                        "--report-json",
                        str(answer_eval_json),
                        "--report-md",
                        str(answer_eval_md),
                        "--json",
                    ]
                )
            answer_eval_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                diagnostic_code = module.main(
                    [
                        "diagnose-result",
                        "--query-output",
                        str(query_output),
                        "--trace-json",
                        str(trace_json),
                        "--citation-audit",
                        str(audit_json),
                        "--expected-term",
                        "answer",
                        "--report-json",
                        str(diagnostic_json),
                        "--report-md",
                        str(diagnostic_md),
                        "--json",
                    ]
                )
            diagnostic_payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0, query_output.read_text(encoding="utf-8"))
            self.assertIn("evidence", payload)
            self.assertIn("trace", payload)
            self.assertEqual(payload["trace"]["schema"], "ragflow_query_trace_v1")
            self.assertEqual(payload["trace"]["retrieval"]["status"], "success")
            self.assertTrue(trace_json.exists())
            self.assertIn("RAGFlow Query Trace", trace_md.read_text(encoding="utf-8"))
            self.assertEqual(audit_code, 0)
            self.assertTrue(audit_payload["ok"])
            self.assertTrue(audit_json.exists())
            self.assertIn("RAGFlow Citation Audit", audit_md.read_text(encoding="utf-8"))
            self.assertEqual(answer_eval_code, 0)
            self.assertTrue(answer_eval_payload["ok"])
            self.assertEqual(answer_eval_payload["schema"], "ragflow_answer_evaluation_report_v1")
            self.assertTrue(answer_eval_json.exists())
            self.assertIn("RAGFlow Answer Evaluation", answer_eval_md.read_text(encoding="utf-8"))
            self.assertEqual(diagnostic_code, 0)
            self.assertTrue(diagnostic_payload["ok"])
            self.assertEqual(diagnostic_payload["schema"], "ragflow_query_diagnostic_report_v1")
            self.assertTrue(diagnostic_json.exists())
            self.assertIn("RAGFlow Query Diagnostic", diagnostic_md.read_text(encoding="utf-8"))

    def test_audit_citations_writes_redacted_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            report_json = root / "audit.json"
            report_md = root / "audit.md"
            redaction_json = root / "audit_redaction.json"
            private_host = ".".join(["192", "168", "71", "93"])
            fake_token = "fake-audit-token"
            fake_key = "fake-audit-secret"
            home_path = str(Path.home() / ".ragflow" / "audit.local.yaml")
            query_output.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "question": "What is supported?",
                        "evidence": [
                            {
                                "rank": 1,
                                "citation_id": "[1]",
                                "content_preview": "Supported evidence is available.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            answer = (
                "Supported evidence is available [1]. "
                f"Debug http://{private_host}:9380/v1?token={fake_token} api_key={fake_key} from {home_path}."
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "audit-citations",
                        "--query-output",
                        str(query_output),
                        "--answer",
                        answer,
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_citation_audit_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["config_paths"], 3)
        self.assertIn("RAGFlow Citation Audit", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)

    def test_pollution_report_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            trace_json = root / "trace.json"
            report_json = root / "pollution.json"
            report_md = root / "pollution.md"
            redaction_json = root / "pollution_redaction.json"
            private_host = ".".join(["172", "20", "30", "40"])
            fake_token = "fake-pollution-token"
            fake_key = "fake-pollution-secret"
            home_path = str(Path.home() / ".ragflow" / "pollution.local.yaml")
            query_output.write_text(
                json.dumps(
                    {
                        "question": (
                            f"how to use runtime via http://{private_host}:9380/api?token={fake_token} "
                            f"from {home_path} saved at {query_output}"
                        ),
                        "dataset_ids": ["ds-1"],
                        "chunks": [
                            {
                                "content": "runtime configuration details",
                                "document_name": "runtime.md",
                                "similarity": 0.9,
                            },
                            {
                                "content": f"translation term only match api_key={fake_key}",
                                "document_name": home_path,
                                "similarity": 0.4,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            trace_json.write_text(json.dumps({"expanded_terms": ["translation"]}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "pollution-report",
                        "--query-output",
                        str(query_output),
                        "--trace-json",
                        str(trace_json),
                        "--expanded-term",
                        "translation",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([stdout.getvalue(), report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_query_pollution_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["config_paths"], 4)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Pollution Report", markdown)
        self.assertIn("translation", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(query_output), combined)

    def test_rerank_ab_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            rerank_json = root / "rerank.json"
            report_json = root / "rerank_report.json"
            report_md = root / "rerank_report.md"
            redaction_json = root / "rerank_report_redaction.json"
            private_host = ".".join(["172", "21", "31", "41"])
            fake_token = "fake-rerank-token"
            fake_key = "fake-rerank-secret"
            home_path = str(Path.home() / ".ragflow" / "rerank.local.yaml")
            query_output.write_text(
                json.dumps(
                    {
                        "question": (
                            f"where is the best evidence at http://{private_host}:9380/api?token={fake_token} "
                            f"from {home_path} saved at {query_output}"
                        ),
                        "dataset_ids": ["ds-1"],
                        "chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "content": "weak background note",
                                "document_name": "weak.md",
                                "similarity": 0.7,
                            },
                            {
                                "chunk_id": "chunk-2",
                                "content": f"best evidence has the target phrase api_key={fake_key}",
                                "document_name": home_path,
                                "similarity": 0.6,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rerank_json.write_text(
                json.dumps({"results": [{"chunk_id": "chunk-2", "score": 0.99}, {"chunk_id": "chunk-1", "score": 0.2}]}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "rerank-ab",
                        "--query-output",
                        str(query_output),
                        "--rerank-json",
                        str(rerank_json),
                        "--expected-term",
                        "target phrase",
                        "--expected-chunk",
                        "chunk-2",
                        "--top-k",
                        "1",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([stdout.getvalue(), report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_query_rerank_ab_report_v1")
        self.assertEqual(payload["summary"]["candidate_expected_chunk_hit_count"], 1)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Rerank A/B Report", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(query_output), combined)

    def test_cross_language_ab_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            report_json = root / "cross_language_ab.json"
            report_md = root / "cross_language_ab.md"
            redaction_json = root / "cross_language_ab_redaction.json"
            private_host = ".".join(["172", "22", "32", "42"])
            fake_token = "fake-cross-language-token"
            fake_key = "fake-cross-language-secret"
            home_path = str(Path.home() / ".ragflow" / "cross-language.local.yaml")
            question = (
                f"runtime config via http://{private_host}:9380/api?token={fake_token} "
                f"from {home_path} saved at {baseline}"
            )
            baseline.write_text(
                json.dumps(
                    {
                        "question": question,
                        "chunks": [
                            {
                                "chunk_id": "shared",
                                "content": f"Runtime config evidence api_key={fake_key}",
                                "document_name": home_path,
                                "similarity": 0.9,
                            }
                        ],
                        "metadata": {"retrieval_ms": 10.0},
                    }
                ),
                encoding="utf-8",
            )
            candidate.write_text(
                json.dumps(
                    {
                        "question": question,
                        "chunks": [
                            {
                                "chunk_id": "translated",
                                "content": f"Translated runtime config evidence saved at {candidate}",
                                "document_name": "translated.md",
                                "similarity": 0.7,
                            }
                        ],
                        "metadata": {"retrieval_ms": 15.0},
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "cross-language-ab",
                        "--baseline-output",
                        str(baseline),
                        "--candidate-output",
                        str(candidate),
                        "--baseline-label",
                        "original",
                        "--candidate-label",
                        "translate",
                        "--min-top1-stability",
                        "0.9",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            report_json_exists = report_json.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([stdout.getvalue(), report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_cross_language_ab_report_v1")
        self.assertEqual(payload["summary"]["top1_stability_rate"], 0.0)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertIn("RAGFlow Cross-Language A/B Report", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(baseline), combined)
        self.assertNotIn(str(candidate), combined)

    def test_fusion_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_a = root / "query-a.json"
            query_b = root / "query-b.json"
            report_json = root / "fusion.json"
            report_md = root / "fusion.md"
            redaction_json = root / "fusion_redaction.json"
            private_host = ".".join(["172", "23", "33", "43"])
            fake_token = "fake-fusion-token"
            fake_key = "fake-fusion-secret"
            home_path = str(Path.home() / ".ragflow" / "fusion.local.yaml")
            query_a.write_text(
                json.dumps(
                    {
                        "question": (
                            f"shared answer via http://{private_host}:9380/api?token={fake_token} "
                            f"from {home_path} saved at {query_a}"
                        ),
                        "dataset_ids": ["ds-a"],
                        "chunks": [
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.9,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            query_b.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
                        "dataset_ids": ["ds-b"],
                        "chunks": [
                            {
                                "chunk_id": "b-only",
                                "content": f"B only evidence api_key={fake_key} saved at {query_b}",
                                "document_name": home_path,
                                "similarity": 0.8,
                            },
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.7,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "fusion",
                        "--query-output",
                        str(query_a),
                        "--query-output",
                        str(query_b),
                        "--top-k",
                        "2",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([stdout.getvalue(), report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_fusion_report_v1")
        self.assertEqual(payload["summary"]["source_count"], 2)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Fusion Report", markdown)
        self.assertIn("shared.md", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(query_a), combined)
        self.assertNotIn(str(query_b), combined)

    def test_fusion_test_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_a = root / "query-a.json"
            query_b = root / "query-b.json"
            cases = root / "cases.json"
            report_json = root / "fusion_test.json"
            report_md = root / "fusion_test.md"
            redaction_json = root / "fusion_test_redaction.json"
            private_host = ".".join(["172", "23", "33", "44"])
            fake_token = "fake-fusion-test-token"
            fake_key = "fake-fusion-test-secret"
            home_path = str(Path.home() / ".ragflow" / "fusion-test.local.yaml")
            query_a.write_text(
                json.dumps(
                    {
                        "question": (
                            f"shared answer via http://{private_host}:9380/api?token={fake_token} "
                            f"from {home_path} saved at {query_a}"
                        ),
                        "dataset_ids": ["ds-a"],
                        "chunks": [
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.9,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            query_b.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
                        "dataset_ids": ["ds-b"],
                        "chunks": [
                            {
                                "chunk_id": "b-only",
                                "content": f"B only evidence api_key={fake_key} saved at {query_b}",
                                "document_name": home_path,
                                "similarity": 0.8,
                            },
                            {
                                "chunk_id": "shared",
                                "content": "Shared answer evidence.",
                                "document_name": "shared.md",
                                "similarity": 0.7,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cases.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "shared-evidence",
                                "query_outputs": ["query-a.json", "query-b.json"],
                                "top_k": 2,
                                "rrf_k": 60,
                                "expected_top_chunk": "shared",
                                "expected_chunks": ["shared"],
                                "expected_terms": ["Shared answer"],
                                "min_source_count": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "fusion-test",
                        "--cases",
                        str(cases),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([stdout.getvalue(), report_text, markdown, redaction_text])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(payload["schema"], "ragflow_fusion_test_report_v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cases"][0]["summary"]["top_source_count"], 2)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Fusion Test Report", markdown)
        self.assertIn("shared-evidence", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(query_a), combined)
        self.assertNotIn(str(query_b), combined)

    def test_fallback_test_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = root / "fallback_cases.json"
            report_json = root / "fallback_test.json"
            report_md = root / "fallback_test.md"
            redaction_json = root / "fallback_test_redaction.json"
            private_host = ".".join(["192", "168", "72", "94"])
            fake_token = "fake-fallback-token"
            fake_key = "fake-fallback-secret"
            home_path = str(Path.home() / ".ragflow" / "fallback.local.yaml")
            cases.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "llm-unavailable-direct-retrieval",
                                "description": f"LLM unavailable at http://{private_host}:9380/v1?token={fake_token}.",
                                "failure_mode": "llm_unavailable",
                                "primary_status": "unavailable",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "success",
                                "direct_retrieval_chunk_count": 2,
                                "fallback_reason": f"api_key={fake_key} from {home_path}",
                            },
                            {
                                "id": "malformed-llm-json-direct-retrieval",
                                "failure_mode": "malformed_llm_json",
                                "primary_status": "malformed_json",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "success",
                                "direct_retrieval_chunk_count": 1,
                            },
                            {
                                "id": "network-timeout-direct-retrieval",
                                "failure_mode": "network_timeout",
                                "primary_status": "timeout",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "success",
                                "direct_retrieval_chunk_count": 1,
                                "timeout_ms": 1500,
                            },
                            {
                                "id": "partial-failure-preserves-evidence",
                                "failure_mode": "partial_failure",
                                "primary_status": "partial_failure",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "partial",
                                "direct_retrieval_chunk_count": 1,
                                "partial_failure_count": 1,
                            },
                            {
                                "id": "direct-retrieval-fallback",
                                "failure_mode": "direct_retrieval_fallback",
                                "primary_status": "fallback_requested",
                                "fallback_strategy": "direct_retrieval",
                                "fallback_status": "success",
                                "direct_retrieval_chunk_count": 3,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "fallback-test",
                        "--cases",
                        str(cases),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0, output)
        self.assertEqual(payload["schema"], "ragflow_query_fallback_test_report_v1")
        self.assertEqual(file_payload["schema"], "ragflow_query_fallback_test_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["config_paths"], 4)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["summary"]["covered_required_mode_count"],
            len(payload["required_failure_modes"]),
        )
        self.assertEqual(payload["summary"]["fallback_success_rate"], 1.0)
        self.assertIn("RAGFlow Query Fallback Test Report", markdown)
        self.assertIn("direct-retrieval-fallback", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)

    def test_route_commands_use_routing_config(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routing = root / "routing.json"
            routes = root / "routes.json"
            bad_routes = root / "bad-routes.json"
            route_test_json = root / "route-test.json"
            report_md = root / "route-test.md"
            route_test_redaction_json = root / "route-test-redaction.json"
            route_report_json = root / "route-report.json"
            route_report_md = root / "route-report.md"
            route_report_redaction_json = root / "route-report-redaction.json"
            route_diagnose_json = root / "route-diagnose.json"
            route_diagnose_md = root / "route-diagnose.md"
            route_diagnose_redaction_json = root / "route-diagnose-redaction.json"
            route_activation_plan = root / "kb_activation_plan.json"
            route_activation_check_json = root / "route-activation-check.json"
            route_activation_check_md = root / "route-activation-check.md"
            route_activation_redaction_json = root / "route-activation-check-redaction.json"
            private_host = ".".join(["172", "23", "33", "45"])
            diagnose_private_host = ".".join(["172", "23", "33", "46"])
            fake_token = "fake-route-activation-token"
            fake_key = "fake-route-activation-secret"
            diagnose_token = "fake-diagnose-token"
            diagnose_key = "fake-diagnose-secret"
            home_path = str(Path.home() / ".ragflow" / "route-activation.local.yaml")
            diagnose_home_path = str(Path.home() / ".ragflow" / "route-diagnose.local.yaml")
            routing.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": "kb:general",
                                "dataset_id": "ds-general",
                                "hints": ["general", "onboarding"],
                            },
                            {
                                "name": "kb:technical",
                                "dataset_id": "ds-technical",
                                "hints": [
                                    "api",
                                    "runtime",
                                    f"http://{private_host}:9380/route?token={fake_token}",
                                    home_path,
                                ],
                                "kb_routing_hints": ["ignored legacy hint"],
                                "params": {"top_k": 5, "similarity_threshold": 0.1},
                            },
                            {
                                "name": "kb:reference",
                                "dataset_id": "ds-reference",
                                "hints": ["api reference"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bad_routes.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "missing-route-hint",
                                "question": "unmatched topic",
                                "locale": (
                                    f"http://{diagnose_private_host}:9380/bad?token={diagnose_token} "
                                    f"secret={diagnose_key} {diagnose_home_path}"
                                ),
                                "expected_kb": "kb:technical",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            routes.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": (
                                    f"How does the API runtime work? "
                                    f"http://{private_host}:9380/route?token={fake_token} api_key={fake_key}"
                                ),
                                "expected_kb": "kb:technical",
                                "category": "exact",
                                "locale": "en",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            route_activation_plan.write_text(
                json.dumps(
                    {
                        "schema": "kb_activation_plan_v1",
                        "kb_name": "kb:technical",
                        "dataset_id": "ds-technical",
                        "summary": {"blocked_check_count": 0, "review_check_count": 0},
                        "inputs": {
                            "route_config": str(routing),
                            "route_tests": str(routes),
                        },
                        "route_entry_suggestion": {
                            "name": "kb:technical",
                            "dataset_id": "ds-technical",
                            "hints": ["api", "runtime"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                list_code = module.main(["list-kbs", "--routing-config", str(routing)])
            list_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_code = module.main(
                    ["route", "How does the API runtime work?", "--routing-config", str(routing), "--json"]
                )
            route_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                test_code = module.main(
                    [
                        "route-test",
                        "--routing-config",
                        str(routing),
                        "--queries",
                        str(routes),
                        "--report-json",
                        str(route_test_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(route_test_redaction_json),
                    ]
                )
            route_test_payload = json.loads(stdout.getvalue())
            route_test_text = route_test_json.read_text(encoding="utf-8")
            route_test_file_payload = json.loads(route_test_text)
            route_test_markdown = report_md.read_text(encoding="utf-8")
            route_test_redaction_text = route_test_redaction_json.read_text(encoding="utf-8")
            route_test_redaction_payload = json.loads(route_test_redaction_text)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_report_code = module.main(
                    [
                        "route-report",
                        "--routing-config",
                        str(routing),
                        "--queries",
                        str(routes),
                        "--report-json",
                        str(route_report_json),
                        "--report-md",
                        str(route_report_md),
                        "--redaction-report",
                        str(route_report_redaction_json),
                    ]
                )
            route_report_payload = json.loads(stdout.getvalue())
            route_report_text = route_report_json.read_text(encoding="utf-8")
            route_report_markdown = route_report_md.read_text(encoding="utf-8")
            route_report_file_payload = json.loads(route_report_text)
            route_report_redaction_text = route_report_redaction_json.read_text(encoding="utf-8")
            route_report_redaction_payload = json.loads(route_report_redaction_text)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_diagnose_code = module.main(
                    [
                        "route-diagnose",
                        "--routing-config",
                        str(routing),
                        "--queries",
                        str(bad_routes),
                        "--report-json",
                        str(route_diagnose_json),
                        "--report-md",
                        str(route_diagnose_md),
                        "--redaction-report",
                        str(route_diagnose_redaction_json),
                    ]
                )
            route_diagnose_payload = json.loads(stdout.getvalue())
            route_diagnose_text = route_diagnose_json.read_text(encoding="utf-8")
            route_diagnose_markdown = route_diagnose_md.read_text(encoding="utf-8")
            route_diagnose_file_payload = json.loads(route_diagnose_text)
            route_diagnose_redaction_text = route_diagnose_redaction_json.read_text(encoding="utf-8")
            route_diagnose_redaction_payload = json.loads(route_diagnose_redaction_text)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_activation_check_code = module.main(
                    [
                        "route-activation-check",
                        "--activation-plan",
                        str(route_activation_plan),
                        "--routing-config",
                        str(routing),
                        "--queries",
                        str(routes),
                        "--report-json",
                        str(route_activation_check_json),
                        "--report-md",
                        str(route_activation_check_md),
                        "--redaction-report",
                        str(route_activation_redaction_json),
                    ]
                )
            route_activation_check_payload = json.loads(stdout.getvalue())
            route_activation_check_text = route_activation_check_json.read_text(encoding="utf-8")
            route_activation_check_file_payload = json.loads(
                route_activation_check_text
            )
            route_activation_check_markdown = route_activation_check_md.read_text(encoding="utf-8")
            route_activation_redaction_text = route_activation_redaction_json.read_text(encoding="utf-8")
            route_activation_redaction_payload = json.loads(route_activation_redaction_text)

        activation_combined = "\n".join(
            [
                json.dumps(route_activation_check_payload, ensure_ascii=False),
                route_activation_check_text,
                route_activation_check_markdown,
                route_activation_redaction_text,
            ]
        )
        route_review_combined = "\n".join(
            [
                json.dumps(route_test_payload, ensure_ascii=False),
                route_test_text,
                route_test_markdown,
                route_test_redaction_text,
                json.dumps(route_report_payload, ensure_ascii=False),
                route_report_text,
                route_report_markdown,
                route_report_redaction_text,
                json.dumps(route_diagnose_payload, ensure_ascii=False),
                route_diagnose_text,
                route_diagnose_markdown,
                route_diagnose_redaction_text,
            ]
        )
        self.assertEqual(list_code, 0)
        self.assertEqual(list_payload["count"], 3)
        self.assertEqual(route_code, 0)
        self.assertEqual(route_payload["selected"]["dataset_id"], "ds-technical")
        self.assertEqual(test_code, 0)
        self.assertEqual(route_test_payload["metrics"]["accuracy"], 1.0)
        self.assertEqual(route_test_file_payload["schema"], "ragflow_route_test_report_v1")
        self.assertEqual(route_test_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(route_test_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(route_test_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(route_test_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(route_test_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertIn("Route Test", route_test_markdown)
        self.assertEqual(route_report_code, 0)
        self.assertEqual(route_report_payload["schema"], "ragflow_route_report_v1")
        self.assertEqual(route_report_payload["summary"]["missing_route_test_count"], 2)
        self.assertEqual(route_report_payload["summary"]["config_lint_count"], 1)
        self.assertEqual(route_report_payload["config_lints"][0]["category"], "kb_routing_hints_confusion")
        self.assertIn("english_hint_coverage", route_report_payload)
        self.assertGreater(route_report_payload["summary"]["route_test_category_gap_count"], 0)
        self.assertIn("required_route_test_categories", route_report_payload)
        self.assertEqual(route_report_file_payload["schema"], "ragflow_route_report_v1")
        self.assertEqual(route_report_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(route_report_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(route_report_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(route_report_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(route_report_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertIn("RAGFlow Route Report", route_report_markdown)
        self.assertIn("Missing Route Tests", route_report_markdown)
        self.assertIn("Config Lints", route_report_markdown)
        self.assertIn("English Hint Coverage", route_report_markdown)
        self.assertIn("Required Route-Test Categories", route_report_markdown)
        self.assertEqual(route_diagnose_code, 1)
        self.assertEqual(route_diagnose_payload["schema"], "ragflow_route_diagnose_report_v1")
        self.assertEqual(route_diagnose_payload["issues"][0]["category"], "missing_hint")
        self.assertEqual(route_diagnose_file_payload["schema"], "ragflow_route_diagnose_report_v1")
        self.assertEqual(route_diagnose_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(route_diagnose_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(route_diagnose_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(route_diagnose_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(route_diagnose_redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(route_diagnose_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertIn("RAGFlow Route Diagnosis", route_diagnose_markdown)
        self.assertNotIn(private_host, route_review_combined)
        self.assertNotIn(diagnose_private_host, route_review_combined)
        self.assertNotIn(fake_token, route_review_combined)
        self.assertNotIn(fake_key, route_review_combined)
        self.assertNotIn(diagnose_token, route_review_combined)
        self.assertNotIn(diagnose_key, route_review_combined)
        self.assertNotIn(home_path, route_review_combined)
        self.assertNotIn(diagnose_home_path, route_review_combined)
        self.assertNotIn(str(routing), route_review_combined)
        self.assertNotIn(str(routes), route_review_combined)
        self.assertNotIn(str(bad_routes), route_review_combined)
        self.assertEqual(route_activation_check_code, 0)
        self.assertEqual(route_activation_check_payload["schema"], "ragflow_route_activation_check_v1")
        self.assertEqual(route_activation_check_payload["status"], "PASS")
        self.assertEqual(route_activation_check_payload["summary"]["target_route_test_count"], 1)
        self.assertEqual(route_activation_check_file_payload["schema"], "ragflow_route_activation_check_v1")
        self.assertEqual(route_activation_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(route_activation_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(route_activation_redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(route_activation_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(route_activation_redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(route_activation_redaction_payload["rule_counts"]["config_path"], 1)
        self.assertIn("RAGFlow Route Activation Check", route_activation_check_markdown)
        self.assertNotIn(private_host, activation_combined)
        self.assertNotIn(fake_token, activation_combined)
        self.assertNotIn(fake_key, activation_combined)
        self.assertNotIn(home_path, activation_combined)
        self.assertNotIn(str(route_activation_plan), activation_combined)
        self.assertNotIn(str(routing), activation_combined)
        self.assertNotIn(str(routes), activation_combined)

    def test_assistant_profile_recommend_command_writes_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assistant_profile = root / "assistant_profile.json"
            retrieval_hints = root / "retrieval_hints.json"
            report_json = root / "assistant_profile_recommendation.json"
            report_md = root / "assistant_profile_recommendation.md"
            redaction_json = root / "assistant_profile_recommendation_redaction.json"
            private_host = ".".join(("192", "168", "21", "55"))
            fake_token = "fake-assistant-profile-token"
            fake_key = "fake-assistant-profile-key"
            home_path = str(Path.home() / ".ragflow" / "assistant-profile.local.json")
            assistant_profile.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_assistant_profile_v1",
                        "profile_id": (
                            f"neutral-assistant-review http://{private_host}:9380/profile?token={fake_token} "
                            f"api_key={fake_key}"
                        ),
                        "status": f"review_required {home_path}",
                        "retrieval": {
                            "top_k": 5,
                            "similarity_threshold": 0.2,
                            "vector_weight": 0.7,
                            "bm25_weight": 0.0,
                            "require_evidence": True,
                            "quote_numeric_facts": True,
                            "citation_format": "[n]",
                        },
                        "answer_policy": [
                            "Answer only from retrieved evidence.",
                            "Say the source does not contain the answer when evidence is missing.",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "document_count": 1,
                        "section_boundaries": [{"title": f"Section {index}"} for index in range(9)],
                        "keyword_candidates": [{"term": "runtime"}, {"term": "assistant"}],
                        "question_candidates": [{"question": "How should assistant review work?"}],
                        "numeric_candidates": [{"value": "42"}],
                        "table_artifacts": [{"path": "tables/example.csv"}],
                        "image_artifacts": [],
                        "quality_risks": [],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "assistant-profile",
                        "recommend",
                        "--assistant-profile",
                        str(assistant_profile),
                        "--retrieval-hints",
                        str(retrieval_hints),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join(
            [
                json.dumps(payload, ensure_ascii=False),
                report_text,
                markdown,
                redaction_text,
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_assistant_profile_recommendation_v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["recommended_settings"]["top_k"], 8)
        self.assertEqual(payload["recommended_settings"]["bm25_weight"], 0.3)
        self.assertEqual(file_payload["schema"], "ragflow_assistant_profile_recommendation_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertIn("RAGFlow Assistant Profile Recommendation", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(assistant_profile), combined)
        self.assertNotIn(str(retrieval_hints), combined)

    def test_assistant_test_plan_command_writes_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assistant_profile = root / "assistant_profile.json"
            retrieval_hints = root / "retrieval_hints.json"
            test_plan = root / "assistant_test_plan.json"
            report_json = root / "assistant_test_plan_review.json"
            report_md = root / "assistant_test_plan_review.md"
            redaction_json = root / "assistant_test_plan_review_redaction.json"
            private_host = ".".join(("10", "44", "55", "66"))
            fake_token = "fake-assistant-test-plan-token"
            fake_key = "fake-assistant-test-plan-key"
            home_path = str(Path.home() / ".ragflow" / "assistant-test-plan.local.json")
            assistant_profile.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_assistant_profile_v1",
                        "profile_id": "neutral-assistant-review",
                        "status": "review_required",
                        "retrieval": {"require_evidence": True, "citation_format": "[n]"},
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "document_count": 1,
                        "section_boundaries": [
                            {"title": "Overview", "image_count": 0},
                            {"title": "Evidence", "image_count": 1},
                        ],
                        "keyword_candidates": [{"term": "assistant"}],
                        "question_candidates": [
                            {"question": "What should be summarized?"},
                            {"question": "How should the assistant paraphrase?"},
                        ],
                        "numeric_candidates": [{"value": "42"}],
                        "table_artifacts": [],
                        "image_artifacts": [{"path": "images/chart.png"}],
                        "quality_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            test_plan.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_assistant_test_plan_v1",
                        "assistant_profile": "neutral-assistant-review",
                        "status": "review_required",
                        "test_count": 6,
                        "cases": [
                            {
                                "id": "summary-001",
                                "stage": "summary",
                                "question": f"Summarize the evidence from http://{private_host}:9380/kb?token={fake_token}.",
                                "expected_behavior": f"answer from cited retrieved evidence; api_key={fake_key}",
                                "source_document": home_path,
                            },
                            {
                                "id": "numeric-001",
                                "stage": "exact_numeric_fact",
                                "question": "What does the source say about 42?",
                                "expected_behavior": "return the numeric fact with a citation",
                            },
                            {
                                "id": "visual-001",
                                "stage": "ocr_image_fact",
                                "question": "What visual detail appears in Evidence?",
                                "expected_behavior": "answer only when visual evidence is retrieved",
                            },
                            {
                                "id": "flow-001",
                                "stage": "logical_flow",
                                "question": "How are Overview and Evidence related?",
                                "expected_behavior": "compare retrieved source sections only",
                            },
                            {
                                "id": "paraphrase-001",
                                "stage": "paraphrase",
                                "question": "Restate the source evidence in another way.",
                                "expected_behavior": "retrieve the same source section",
                            },
                            {
                                "id": "negative-001",
                                "stage": "negative_boundary",
                                "question": "What private API key is used?",
                                "expected_behavior": "abstain because the source lacks secrets",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "assistant-test-plan",
                        "--test-plan",
                        str(test_plan),
                        "--assistant-profile",
                        str(assistant_profile),
                        "--retrieval-hints",
                        str(retrieval_hints),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join(
            [
                json.dumps(payload, ensure_ascii=False),
                report_text,
                markdown,
                redaction_text,
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_assistant_test_plan_review_v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["execution"]["status"], "not_run")
        self.assertEqual(payload["summary"]["missing_expected_stage_count"], 0)
        self.assertEqual(file_payload["schema"], "ragflow_assistant_test_plan_review_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertIn("RAGFlow Assistant Test Plan Review", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(test_plan), combined)
        self.assertNotIn(str(assistant_profile), combined)
        self.assertNotIn(str(retrieval_hints), combined)

    def test_route_commands_can_use_centroid_tie_breaker(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routing = root / "routing.json"
            routes = root / "routes.json"
            centroids = root / "centroids.json"
            query_vector = root / "query_vector.json"
            routing.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {"name": "kb:alpha", "dataset_id": "ds-alpha", "hints": ["shared"]},
                            {"name": "kb:beta", "dataset_id": "ds-beta", "hints": ["shared"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            routes.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "tie",
                                "question": "shared topic",
                                "expected_kb": "kb:beta",
                                "query_vector": [1.0, 0.0],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            centroids.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_route_centroid_index_v1",
                        "centroids": [
                            {"dataset_id": "ds-alpha", "status": "ready", "vector": [0.0, 1.0]},
                            {"dataset_id": "ds-beta", "status": "ready", "vector": [1.0, 0.0]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            query_vector.write_text(json.dumps({"query_vector": [1.0, 0.0]}), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                route_code = module.main(
                    [
                        "route",
                        "shared topic",
                        "--routing-config",
                        str(routing),
                        "--centroid-index",
                        str(centroids),
                        "--query-vector-json",
                        str(query_vector),
                        "--json",
                    ]
                )
            route_payload = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                test_code = module.main(
                    [
                        "route-test",
                        "--routing-config",
                        str(routing),
                        "--centroid-index",
                        str(centroids),
                        "--queries",
                        str(routes),
                    ]
                )
            route_test_payload = json.loads(stdout.getvalue())

        self.assertEqual(route_code, 0, route_payload)
        self.assertEqual(route_payload["selected"]["name"], "kb:beta")
        self.assertEqual(route_payload["selected"]["tie_breaker"], "centroid")
        self.assertEqual(test_code, 0, route_test_payload)
        self.assertEqual(route_test_payload["metrics"]["accuracy"], 1.0)
        self.assertEqual(route_test_payload["cases"][0]["route"]["selected"]["tie_breaker"], "centroid")

    def test_centroid_build_plan_only_writes_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            snapshot = root / "chunk_snapshot.json"
            report_json = root / "centroid_plan.json"
            report_md = root / "centroid_plan.md"
            redaction_json = root / "centroid_plan_redaction.json"
            index_output = root / "centroids.json"
            private_host = ".".join(["192", "168", "73", "95"])
            fake_token = "fake-centroid-plan-token"
            fake_key = "fake-centroid-plan-secret"
            home_path = str(Path.home() / ".ragflow" / "centroid-plan.local.yaml")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "ds-technical",
                            "name": f"kb:http://{private_host}:9380/v1?token={fake_token}",
                        },
                        "documents": [{"document_id": "doc-1", "chunk_count": 1}],
                    }
                ),
                encoding="utf-8",
            )
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "dataset_id": "ds-technical",
                                "stable_hash": "sha256:chunk",
                                "content": "Centroid planning evidence.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "centroid",
                        "build",
                        "--plan-only",
                        "--kb-manifest",
                        str(manifest),
                        "--chunk-snapshot",
                        str(snapshot),
                        "--embedding-model",
                        f"example-embedding api_key={fake_key}",
                        "--embedding-provider",
                        home_path,
                        "--embedding-dimension",
                        "3",
                        "--index-output",
                        str(index_output),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_route_centroid_build_plan_v1")
        self.assertEqual(file_payload["index_schema"], "ragflow_route_centroid_index_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertEqual(payload["summary"]["ready_centroid_count"], 1)
        self.assertIn("RAGFlow Centroid Build Plan", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(manifest), combined)
        self.assertNotIn(str(snapshot), combined)
        self.assertNotIn(str(index_output), combined)

    def test_centroid_build_writes_index_checkpoint_and_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            snapshot = root / "chunk_snapshot.json"
            index_output = root / "centroids.json"
            checkpoint = root / "centroid.checkpoint.json"
            report_json = root / "centroid_build.json"
            report_md = root / "centroid_build.md"
            redaction_json = root / "centroid_build_redaction.json"
            private_host = ".".join(["192", "168", "74", "96"])
            fake_token = "fake-centroid-build-token"
            fake_key = "fake-centroid-build-secret"
            home_path = str(Path.home() / ".ragflow" / "centroid-build.local.yaml")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-technical", "name": "kb:technical"},
                        "documents": [{"document_id": "doc-1", "chunk_count": 2}],
                    }
                ),
                encoding="utf-8",
            )
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "dataset_id": "ds-technical",
                                "stable_hash": "sha256:chunk1",
                                "content": "Centroid build evidence one.",
                                "embedding": [1.0, 2.0],
                            },
                            {
                                "dataset_id": "ds-technical",
                                "stable_hash": "sha256:chunk2",
                                "content": "Centroid build evidence two.",
                                "embedding": [3.0, 4.0],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "centroid",
                        "build",
                        "--kb-manifest",
                        str(manifest),
                        "--chunk-snapshot",
                        str(snapshot),
                        "--embedding-model",
                        f"http://{private_host}:9380/v1?token={fake_token} api_key={fake_key}",
                        "--embedding-provider",
                        home_path,
                        "--embedding-dimension",
                        "2",
                        "--batch-size",
                        "16",
                        "--checkpoint",
                        str(checkpoint),
                        "--index-output",
                        str(index_output),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction_json),
                        "--json",
                    ]
                )
            output = stdout.getvalue()
            payload = json.loads(output)
            report_text = report_json.read_text(encoding="utf-8")
            file_payload = json.loads(report_text)
            index_payload = json.loads(index_output.read_text(encoding="utf-8"))
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([output, report_text, markdown, redaction_text])
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_route_centroid_build_report_v1")
        self.assertEqual(file_payload["summary"]["completed"], True)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["home_path"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["config_path"], 1)
        self.assertEqual(index_payload["schema"], "ragflow_route_centroid_index_v1")
        self.assertEqual(index_payload["centroids"][0]["vector"], [2.0, 3.0])
        self.assertEqual(checkpoint_payload["schema"], "ragflow_route_centroid_build_checkpoint_v1")
        self.assertIn("RAGFlow Centroid Build Report", markdown)
        self.assertNotIn(private_host, combined)
        self.assertNotIn(fake_token, combined)
        self.assertNotIn(fake_key, combined)
        self.assertNotIn(home_path, combined)
        self.assertNotIn(str(manifest), combined)
        self.assertNotIn(str(snapshot), combined)
        self.assertNotIn(str(index_output), combined)
        self.assertNotIn(str(checkpoint), combined)

    def test_auto_mode_uses_routing_config_with_fake_client(self) -> None:
        module = load_query_module()
        module.RAGFlowClient = FakeQueryClient
        with tempfile.TemporaryDirectory() as tmp:
            routing = Path(tmp) / "routing.json"
            routing.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": "kb:technical",
                                "dataset_id": "ds-technical",
                                "hints": ["api"],
                                "params": {"top_k": 7, "similarity_threshold": 0.2},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "--base-url",
                        "https://ragflow.example.test",
                        "--api-key",
                        "test-key",
                        "ask",
                        "API usage question",
                        "--mode",
                        "auto",
                        "--routing-config",
                        str(routing),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(FakeQueryClient.last_request["dataset_ids"], ["ds-technical"])
        self.assertEqual(FakeQueryClient.last_request["top_k"], 7)
        self.assertEqual(FakeQueryClient.last_request["similarity_threshold"], 0.2)
        self.assertEqual(payload["metadata"]["route"]["selected"]["name"], "kb:technical")


if __name__ == "__main__":
    unittest.main()
