from __future__ import annotations

import contextlib
import importlib.util
import io
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
    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
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


if __name__ == "__main__":
    unittest.main()
