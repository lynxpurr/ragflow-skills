from __future__ import annotations

from types import SimpleNamespace
import unittest

from ragflow_skill_runtime import RAGFlowClient, RagflowConfig
from ragflow_skill_runtime.http import HTTPError


class RecordingHTTPClient:
    def __init__(self, response=None) -> None:
        self.calls = []
        self.response = {"code": 0} if response is None else response

    def request_json(self, method, url, *, json_body=None, **kwargs):
        self.calls.append((method, url, json_body, kwargs))
        return SimpleNamespace(data=self.response)


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

    def test_update_dataset_uses_dataset_resource(self) -> None:
        client = RAGFlowClient(RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key"))
        recorder = RecordingHTTPClient()
        client.http = recorder

        response = client.update_dataset("ds-update", {"language": "English"})

        self.assertEqual(response, {"code": 0})
        self.assertEqual(len(recorder.calls), 1)
        method, url, body, _kwargs = recorder.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://ragflow.example.test/api/v1/datasets/ds-update")
        self.assertEqual(body, {"language": "English"})

    def test_update_dataset_rejects_nonzero_application_code(self) -> None:
        for code in (100, "100"):
            with self.subTest(code=code):
                client = RAGFlowClient(
                    RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key")
                )
                recorder = RecordingHTTPClient({"code": code, "message": "update rejected"})
                client.http = recorder

                with self.assertRaisesRegex(HTTPError, "update rejected"):
                    client.update_dataset("ds-update", {"language": "English"})

    def test_create_dataset_normalizes_v0255_create_profile_fields(self) -> None:
        client = RAGFlowClient(RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key"))
        recorder = RecordingHTTPClient({"code": 0, "data": {"id": "ds-create"}})
        client.http = recorder

        client.create_dataset(
            "kb:test",
            profile={
                "language": "English",
                "chunk_method": "naive",
                "parser_config": {
                    "chunk_token_num": 512,
                    "delimiter": "",
                    "__language__": "English",
                },
            },
        )

        _method, _url, body, _kwargs = recorder.calls[0]
        self.assertNotIn("language", body)
        self.assertEqual(body["parser_config"], {"chunk_token_num": 512})

    def test_trigger_parse_uses_dataset_chunks_endpoint(self) -> None:
        client = RAGFlowClient(RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key"))
        recorder = RecordingHTTPClient({"code": 0, "data": True})
        client.http = recorder

        response = client.trigger_parse("ds-parse", ["doc-a", "doc-b"])

        self.assertEqual(response, {"code": 0, "data": True})
        self.assertEqual(len(recorder.calls), 1)
        method, url, body, _kwargs = recorder.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://ragflow.example.test/api/v1/datasets/ds-parse/chunks")
        self.assertEqual(body, {"document_ids": ["doc-a", "doc-b"]})

    def test_trigger_parse_rejects_nonzero_application_code(self) -> None:
        for code in (100, "100"):
            with self.subTest(code=code):
                client = RAGFlowClient(
                    RagflowConfig(base_url="https://ragflow.example.test", api_key="test-key")
                )
                recorder = RecordingHTTPClient({"code": code, "message": "parse rejected"})
                client.http = recorder

                with self.assertRaisesRegex(RuntimeError, "application code 100: parse rejected"):
                    client.trigger_parse("ds-parse", ["doc-a"])

                self.assertEqual(len(recorder.calls), 1)


if __name__ == "__main__":
    unittest.main()
