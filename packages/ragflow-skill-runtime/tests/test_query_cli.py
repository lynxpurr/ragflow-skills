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
        self.assertIn("fusion", payload["trace"])
        self.assertEqual(len(payload["chunks"]), 2)

    def test_rewrite_command_writes_plan_outputs(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "rewrite.json"
            report_md = root / "rewrite.md"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "rewrite",
                        "How do I configure runtime?",
                        "--rewrite",
                        "simple",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(payload["schema"], "ragflow_query_rewrite_plan_v1")
        self.assertGreaterEqual(payload["summary"]["generated_query_count"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Rewrite Plan", markdown)
        self.assertIn("how to configure runtime", markdown)

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
            self.assertTrue(trace_json.exists())
            self.assertIn("RAGFlow Query Trace", trace_md.read_text(encoding="utf-8"))
            self.assertEqual(audit_code, 0)
            self.assertTrue(audit_payload["ok"])
            self.assertTrue(audit_json.exists())
            self.assertIn("RAGFlow Citation Audit", audit_md.read_text(encoding="utf-8"))
            self.assertEqual(diagnostic_code, 0)
            self.assertTrue(diagnostic_payload["ok"])
            self.assertEqual(diagnostic_payload["schema"], "ragflow_query_diagnostic_report_v1")
            self.assertTrue(diagnostic_json.exists())
            self.assertIn("RAGFlow Query Diagnostic", diagnostic_md.read_text(encoding="utf-8"))

    def test_pollution_report_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            report_json = root / "pollution.json"
            report_md = root / "pollution.md"
            query_output.write_text(
                json.dumps(
                    {
                        "question": "how to use runtime",
                        "dataset_ids": ["ds-1"],
                        "chunks": [
                            {
                                "content": "runtime configuration details",
                                "document_name": "runtime.md",
                                "similarity": 0.9,
                            },
                            {
                                "content": "translation term only match",
                                "document_name": "polluted.md",
                                "similarity": 0.4,
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
                        "pollution-report",
                        "--query-output",
                        str(query_output),
                        "--expanded-term",
                        "translation",
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_query_pollution_report_v1")
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Pollution Report", markdown)
        self.assertIn("translation", markdown)

    def test_rerank_ab_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_output = root / "query.json"
            rerank_json = root / "rerank.json"
            report_json = root / "rerank_report.json"
            report_md = root / "rerank_report.md"
            query_output.write_text(
                json.dumps(
                    {
                        "question": "where is the best evidence",
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
                                "content": "best evidence has the target phrase",
                                "document_name": "best.md",
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
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_query_rerank_ab_report_v1")
        self.assertEqual(payload["summary"]["candidate_expected_chunk_hit_count"], 1)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Query Rerank A/B Report", markdown)
        self.assertIn("best.md", markdown)

    def test_cross_language_ab_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            report_json = root / "cross_language_ab.json"
            report_md = root / "cross_language_ab.md"
            baseline.write_text(
                json.dumps(
                    {
                        "question": "runtime config",
                        "chunks": [
                            {
                                "chunk_id": "shared",
                                "content": "Runtime config evidence.",
                                "document_name": "runtime.md",
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
                        "question": "runtime config",
                        "chunks": [
                            {
                                "chunk_id": "translated",
                                "content": "Translated runtime config evidence.",
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
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_cross_language_ab_report_v1")
        self.assertEqual(payload["summary"]["top1_stability_rate"], 0.0)
        self.assertTrue(report_json_exists)
        self.assertIn("RAGFlow Cross-Language A/B Report", markdown)

    def test_fusion_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_a = root / "query-a.json"
            query_b = root / "query-b.json"
            report_json = root / "fusion.json"
            report_md = root / "fusion.md"
            query_a.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
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
                                "content": "B only evidence.",
                                "document_name": "b.md",
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
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_fusion_report_v1")
        self.assertEqual(payload["summary"]["source_count"], 2)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Fusion Report", markdown)
        self.assertIn("shared.md", markdown)

    def test_fusion_test_can_write_json_and_markdown(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_a = root / "query-a.json"
            query_b = root / "query-b.json"
            cases = root / "cases.json"
            report_json = root / "fusion_test.json"
            report_md = root / "fusion_test.md"
            query_a.write_text(
                json.dumps(
                    {
                        "question": "shared answer",
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
                                "content": "B only evidence.",
                                "document_name": "b.md",
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
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_json_exists = report_json.exists()
            report_md_exists = report_md.exists()
            markdown = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(payload["schema"], "ragflow_fusion_test_report_v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cases"][0]["summary"]["top_source_count"], 2)
        self.assertTrue(report_json_exists)
        self.assertTrue(report_md_exists)
        self.assertIn("RAGFlow Fusion Test Report", markdown)
        self.assertIn("shared-evidence", markdown)

    def test_route_commands_use_routing_config(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routing = root / "routing.json"
            routes = root / "routes.json"
            bad_routes = root / "bad-routes.json"
            report_md = root / "route-test.md"
            route_report_json = root / "route-report.json"
            route_report_md = root / "route-report.md"
            route_diagnose_json = root / "route-diagnose.json"
            route_diagnose_md = root / "route-diagnose.md"
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
                                "question": "How does the API runtime work?",
                                "expected_kb": "kb:technical",
                                "category": "exact",
                                "locale": "en",
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
                    ]
                )
            route_report_payload = json.loads(stdout.getvalue())
            route_report_markdown = route_report_md.read_text(encoding="utf-8")
            route_report_file_payload = json.loads(route_report_json.read_text(encoding="utf-8"))

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
                    ]
                )
            route_diagnose_payload = json.loads(stdout.getvalue())
            route_diagnose_markdown = route_diagnose_md.read_text(encoding="utf-8")
            route_diagnose_file_payload = json.loads(route_diagnose_json.read_text(encoding="utf-8"))

        self.assertEqual(list_code, 0)
        self.assertEqual(list_payload["count"], 3)
        self.assertEqual(route_code, 0)
        self.assertEqual(route_payload["selected"]["dataset_id"], "ds-technical")
        self.assertEqual(test_code, 0)
        self.assertEqual(route_test_payload["metrics"]["accuracy"], 1.0)
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
        self.assertIn("RAGFlow Route Report", route_report_markdown)
        self.assertIn("Missing Route Tests", route_report_markdown)
        self.assertIn("Config Lints", route_report_markdown)
        self.assertIn("English Hint Coverage", route_report_markdown)
        self.assertIn("Required Route-Test Categories", route_report_markdown)
        self.assertEqual(route_diagnose_code, 1)
        self.assertEqual(route_diagnose_payload["schema"], "ragflow_route_diagnose_report_v1")
        self.assertEqual(route_diagnose_payload["issues"][0]["category"], "missing_hint")
        self.assertEqual(route_diagnose_file_payload["schema"], "ragflow_route_diagnose_report_v1")
        self.assertIn("RAGFlow Route Diagnosis", route_diagnose_markdown)

    def test_centroid_build_plan_only_writes_reports(self) -> None:
        module = load_query_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            snapshot = root / "chunk_snapshot.json"
            report_json = root / "centroid_plan.json"
            report_md = root / "centroid_plan.md"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-technical", "name": "kb:technical"},
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
                        "example-embedding",
                        "--embedding-dimension",
                        "3",
                        "--index-output",
                        str(root / "centroids.json"),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            file_payload = json.loads(report_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_route_centroid_build_plan_v1")
        self.assertEqual(file_payload["index_schema"], "ragflow_route_centroid_index_v1")
        self.assertEqual(payload["summary"]["ready_centroid_count"], 1)
        self.assertIn("RAGFlow Centroid Build Plan", markdown)

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
                        "example-embedding",
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
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            file_payload = json.loads(report_json.read_text(encoding="utf-8"))
            index_payload = json.loads(index_output.read_text(encoding="utf-8"))
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "ragflow_route_centroid_build_report_v1")
        self.assertEqual(file_payload["summary"]["completed"], True)
        self.assertEqual(index_payload["schema"], "ragflow_route_centroid_index_v1")
        self.assertEqual(index_payload["centroids"][0]["vector"], [2.0, 3.0])
        self.assertEqual(checkpoint_payload["schema"], "ragflow_route_centroid_build_checkpoint_v1")
        self.assertIn("RAGFlow Centroid Build Report", markdown)

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
