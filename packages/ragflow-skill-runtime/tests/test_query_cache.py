from __future__ import annotations

import json
import unittest

from ragflow_skill_runtime import (
    QUERY_OUTPUT_CACHE_REPORT_SCHEMA,
    build_query_output_cache_report,
    render_query_output_cache_markdown,
)


class QueryOutputCacheReportTests(unittest.TestCase):
    def _payload(self, *, top_k: int = 5) -> dict:
        return {
            "ok": True,
            "question": "How should cached retrieval output be keyed?",
            "mode": "auto",
            "dataset_ids": ["ds-cache"],
            "chunks": [{"chunk_id": "chunk-1", "content": "cache key guidance"}],
            "metadata": {
                "requested_mode": "auto",
                "top_k": top_k,
                "similarity_threshold": 0.2,
                "fusion": "rrf",
                "rewrite": "multi-query",
                "route": {
                    "selected": {
                    "name": "kb:cache",
                    "dataset_id": "ds-cache",
                    "reason": "route selected from /home/tester/.ragflow/private.yaml",
                    "params": {"top_k": top_k},
                }
            },
            },
            "retrievals": [
                {
                    "query_id": "original",
                    "query_kind": "original",
                    "question": "How should cached retrieval output be keyed?",
                },
                {
                    "query_id": "rewrite-1",
                    "query_kind": "rewrite",
                    "question": "cache invalidation key parts",
                },
            ],
        }

    def test_query_output_cache_report_uses_stable_redaction_safe_key_parts(self) -> None:
        first = build_query_output_cache_report(
            self._payload(),
            config_version="retrieval-v1",
            route_config_version="routes-v1",
        )
        second = build_query_output_cache_report(
            self._payload(),
            config_version="retrieval-v1",
            route_config_version="routes-v1",
        )
        markdown = render_query_output_cache_markdown(first)
        serialized = json.dumps(first, sort_keys=True)

        self.assertTrue(first["ok"])
        self.assertEqual(first["schema"], QUERY_OUTPUT_CACHE_REPORT_SCHEMA)
        self.assertEqual(first["cache_key"], second["cache_key"])
        self.assertEqual(first["summary"]["dataset_count"], 1)
        self.assertEqual(first["summary"]["retrieval_query_count"], 2)
        self.assertEqual(first["invalidation"]["status"], "not_evaluated")
        self.assertEqual(first["key_parts"]["retrieval"]["top_k"], 5)
        self.assertEqual(first["key_parts"]["route"]["route_config_version"], "routes-v1")
        self.assertIn("RAGFlow Query Output Cache Report", markdown)
        self.assertIn("invalidation_status: `not_evaluated`", markdown)
        self.assertNotIn("How should cached retrieval output be keyed?", serialized)
        self.assertNotIn("cache invalidation key parts", serialized)
        self.assertNotIn("kb:cache", serialized)
        self.assertNotIn("/home/tester/.ragflow/private.yaml", serialized)

    def test_query_output_cache_report_marks_changed_fields_for_invalidation(self) -> None:
        baseline = build_query_output_cache_report(self._payload(top_k=5), config_version="retrieval-v1")
        current = build_query_output_cache_report(
            self._payload(top_k=10),
            baseline_report=baseline,
            config_version="retrieval-v2",
        )

        self.assertTrue(current["ok"])
        self.assertEqual(current["invalidation"]["status"], "invalidate")
        self.assertIn("retrieval", current["invalidation"]["changed_fields"])
        self.assertIn("route", current["invalidation"]["changed_fields"])
        self.assertIn("config", current["invalidation"]["changed_fields"])
        self.assertNotEqual(current["cache_key"], baseline["cache_key"])


if __name__ == "__main__":
    unittest.main()
