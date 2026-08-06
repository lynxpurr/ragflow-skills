from __future__ import annotations

import contextlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ragflow_skill_runtime import probe_model_providers, render_model_provider_probe_markdown


class FakeProviderClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        value = self.payloads[path]
        if isinstance(value, Exception):
            raise value
        return value


class AdapterProbeHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        AdapterProbeHandler.requests.append((self.path, json.loads(body.decode("utf-8"))))
        if self.path == "/embeddings":
            payload = {"error": {"message": "empty input rejected"}}
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(422)
        elif self.path == "/rerank":
            payload = {"results": []}
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
        else:
            encoded = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def adapter_probe_server():
    AdapterProbeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class ModelProviderProbeTests(unittest.TestCase):
    def test_probe_model_providers_normalizes_embedding_and_rerank_models(self) -> None:
        client = FakeProviderClient(
            {
                "/llm/factories": {
                    "data": {
                        "factories": [
                            {
                                "id": "builtin",
                                "display_name": "Built In",
                                "models": [
                                    {"name": "bge-m3", "type": "embedding"},
                                    {"name": "bge-reranker", "type": "rerank"},
                                ],
                            }
                        ]
                    }
                }
            }
        )

        report = probe_model_providers(
            client,
            endpoint_paths=["/llm/factories"],
            expected_embedding_models=["bge-m3"],
            expected_rerank_models=["bge-reranker"],
        )
        markdown = render_model_provider_probe_markdown(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema"], "ragflow_model_provider_probe_report_v1")
        self.assertEqual(report["summary"]["provider_count"], 1)
        self.assertEqual(report["summary"]["embedding_model_count"], 1)
        self.assertEqual(report["summary"]["rerank_model_count"], 1)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(report["expected_model_checks"][0]["found"], True)
        self.assertIn("RAGFlow Model Provider Probe", markdown)
        self.assertIn("runtime_partial_failure_status: `completed`", markdown)
        self.assertIn("Built In", markdown)

    def test_probe_model_providers_warns_for_missing_expected_model(self) -> None:
        client = FakeProviderClient(
            {
                "/llm/models": {
                    "data": [
                        {"id": "text-embedding-v1", "model_type": "embedding"},
                    ]
                }
            }
        )

        report = probe_model_providers(
            client,
            endpoint_paths=["/llm/models"],
            expected_embedding_models=["missing-embedding"],
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["warning_count"], 1)
        self.assertEqual(report["issues"][0]["code"], "embedding_model_not_registered")
        self.assertFalse(report["expected_model_checks"][0]["found"])

    def test_probe_model_providers_reports_unavailable_endpoints(self) -> None:
        client = FakeProviderClient({"/missing": RuntimeError("HTTP 404 for GET /missing: not found")})

        report = probe_model_providers(client, endpoint_paths=["/missing"])

        self.assertFalse(report["ok"])
        self.assertEqual(report["status_counts"]["missing"], 1)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "failed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["issues"][0]["code"], "model_provider_endpoint_unavailable")

    def test_probe_model_providers_checks_explicit_adapter_empty_input_shapes(self) -> None:
        client = FakeProviderClient(
            {
                "/llm/factories": {
                    "data": {
                        "factories": [
                            {
                                "id": "builtin",
                                "models": [
                                    {"name": "bge-m3", "type": "embedding"},
                                    {"name": "bge-reranker", "type": "rerank"},
                                ],
                            }
                        ]
                    }
                }
            }
        )
        with adapter_probe_server() as base_url:
            report = probe_model_providers(
                client,
                endpoint_paths=["/llm/factories"],
                expected_embedding_models=["bge-m3"],
                expected_rerank_models=["bge-reranker"],
                embedding_adapter_url=f"{base_url}/embeddings",
                rerank_adapter_url=f"{base_url}/rerank",
            )

        requests = {path: payload for path, payload in AdapterProbeHandler.requests}
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["configured_adapter_count"], 2)
        self.assertEqual(report["summary"]["handled_empty_input_adapter_count"], 2)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 3)
        self.assertEqual(report["adapter_status_counts"]["handled_empty_input"], 2)
        self.assertEqual(requests["/embeddings"]["input"], [])
        self.assertEqual(requests["/embeddings"]["model"], "bge-m3")
        self.assertEqual(requests["/rerank"]["documents"], [])
        self.assertEqual(requests["/rerank"]["query"], "")
        self.assertEqual(requests["/rerank"]["model"], "bge-reranker")


if __name__ == "__main__":
    unittest.main()
