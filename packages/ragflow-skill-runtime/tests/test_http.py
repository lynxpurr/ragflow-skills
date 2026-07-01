from __future__ import annotations

from types import SimpleNamespace
import unittest

from ragflow_skill_runtime import RAGFlowClient, RagflowConfig


class RecordingHTTPClient:
    def __init__(self) -> None:
        self.calls = []

    def request_json(self, method, url, *, json_body=None, **kwargs):
        self.calls.append((method, url, json_body, kwargs))
        return SimpleNamespace(data={"code": 0})


class HttpClientConfigTests(unittest.TestCase):
    def test_ragflow_client_passes_verify_ssl_to_http_client(self) -> None:
        client = RAGFlowClient(
            RagflowConfig(
                base_url="https://ragflow.example.test",
                api_key="test-key",
                verify_ssl=False,
            )
        )

        self.assertFalse(client.http.verify_ssl)

    def test_delete_dataset_uses_batch_delete_endpoint(self) -> None:
        client = RAGFlowClient(RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key"))
        recorder = RecordingHTTPClient()
        client.http = recorder

        response = client.delete_dataset("ds-delete")

        self.assertEqual(response, {"code": 0})
        self.assertEqual(len(recorder.calls), 1)
        method, url, body, _kwargs = recorder.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, "https://ragflow.example.test/api/v1/datasets")
        self.assertEqual(body, {"ids": ["ds-delete"]})


if __name__ == "__main__":
    unittest.main()
