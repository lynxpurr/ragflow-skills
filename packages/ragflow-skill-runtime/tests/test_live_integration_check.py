from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from live_integration_check import run_live_check  # noqa: E402


class FakeLiveClient:
    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=3):
        return {
            "data": {
                "chunks": [
                    {
                        "content_with_weight": f"live fake answer for {question}",
                        "docnm_kwd": "live.md",
                        "similarity": 0.93,
                        "kb_id": dataset_ids[0],
                    }
                ]
            }
        }


class LiveIntegrationCheckTests(unittest.TestCase):
    def test_missing_env_skips_successfully(self) -> None:
        payload = run_live_check(env={})

        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["skipped"])
        self.assertIn("RAGFLOW_BASE_URL", payload["missing"])

    def test_complete_env_runs_fake_retrieval(self) -> None:
        args = argparse.Namespace(
            base_url=None,
            api_key=None,
            dataset_id=None,
            question=None,
            top_k=2,
        )
        payload = run_live_check(
            args=args,
            env={
                "RAGFLOW_BASE_URL": "https://ragflow.example.test",
                "RAGFLOW_API_KEY": "test-key",
                "RAGFLOW_DATASET_ID": "ds-live",
                "RAGFLOW_LIVE_QUERY": "Question",
            },
            client_factory=FakeLiveClient,
        )

        self.assertTrue(payload["ok"], payload)
        self.assertFalse(payload["skipped"])
        self.assertEqual(payload["chunk_count"], 1)
        self.assertEqual(payload["dataset_id"], "ds-live")

    def test_invalid_top_k_returns_structured_error(self) -> None:
        payload = run_live_check(env={"RAGFLOW_LIVE_TOP_K": "many"})

        self.assertFalse(payload["ok"])
        self.assertIn("top_k", payload["error"])


if __name__ == "__main__":
    unittest.main()
