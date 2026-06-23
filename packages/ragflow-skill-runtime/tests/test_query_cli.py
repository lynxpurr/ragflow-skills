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

    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
        FakeQueryClient.last_request = {
            "question": question,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
        }
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
        self.assertEqual(code, 2)

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
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertIn('"ok": true', stdout.getvalue().lower())

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

            self.assertEqual(code, 0, query_output.read_text(encoding="utf-8"))
            self.assertIn("evidence", payload)
            self.assertIn("trace", payload)
            self.assertEqual(payload["trace"]["schema"], "ragflow_query_trace_v1")
            self.assertTrue(trace_json.exists())
            self.assertIn("RAGFlow Query Trace", trace_md.read_text(encoding="utf-8"))
            self.assertEqual(audit_code, 0)
            self.assertTrue(audit_payload["ok"])
            self.assertTrue(audit_json.exists())
            self.assertIn("RAGFlow Citation Audit", audit_md.read_text(encoding="utf-8"))

    def test_route_commands_use_routing_config(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routing = root / "routing.json"
            routes = root / "routes.json"
            report_md = root / "route-test.md"
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
                                "hints": ["api", "runtime"],
                            },
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
                                "id": "q1",
                                "question": "How does the API runtime work?",
                                "expected_kb": "kb:technical",
                            }
                        ]
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
                        "--report-md",
                        str(report_md),
                    ]
                )
            route_test_payload = json.loads(stdout.getvalue())
            route_test_markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(list_code, 0)
        self.assertEqual(list_payload["count"], 2)
        self.assertEqual(route_code, 0)
        self.assertEqual(route_payload["selected"]["dataset_id"], "ds-technical")
        self.assertEqual(test_code, 0)
        self.assertEqual(route_test_payload["metrics"]["accuracy"], 1.0)
        self.assertIn("Route Test", route_test_markdown)

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
