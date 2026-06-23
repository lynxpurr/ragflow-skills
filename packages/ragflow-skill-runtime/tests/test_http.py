from __future__ import annotations

import unittest

from ragflow_skill_runtime import RAGFlowClient, RagflowConfig


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


if __name__ == "__main__":
    unittest.main()
