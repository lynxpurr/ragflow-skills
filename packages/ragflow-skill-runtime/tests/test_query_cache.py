from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime import (
    QUERY_OUTPUT_CACHE_ENTRY_SCHEMA,
    QUERY_OUTPUT_CACHE_REPORT_SCHEMA,
    QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA,
    build_query_output_cache_report,
    render_query_output_cache_markdown,
)


class QueryOutputCacheReportTests(unittest.TestCase):
    @staticmethod
    def _private_route_config() -> str:
        return str(Path("/", "home", "fixture-user", ".ragflow", "private.yaml"))

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
                        "reason": f"route selected from {self._private_route_config()}",
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
        self.assertEqual(first["cache_store"]["schema"], QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA)
        self.assertFalse(first["cache_store"]["enabled"])
        self.assertEqual(first["key_parts"]["retrieval"]["top_k"], 5)
        self.assertEqual(first["key_parts"]["route"]["route_config_version"], "routes-v1")
        self.assertIn("RAGFlow Query Output Cache Report", markdown)
        self.assertIn("invalidation_status: `not_evaluated`", markdown)
        self.assertIn("cache_store_status: `disabled`", markdown)
        self.assertNotIn("How should cached retrieval output be keyed?", serialized)
        self.assertNotIn("cache invalidation key parts", serialized)
        self.assertNotIn("kb:cache", serialized)
        self.assertNotIn(self._private_route_config(), serialized)

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

    def test_query_output_cache_store_dry_run_reports_miss_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_query_output_cache_report(
                self._payload(),
                config_version="retrieval-v1",
                cache_dir=tmp,
                cache_ttl_seconds=60,
                now_epoch=1000.0,
            )
            serialized = json.dumps(report, sort_keys=True)
            markdown = render_query_output_cache_markdown(report)
            files = list(Path(tmp).rglob("*.json"))

        store = report["cache_store"]
        self.assertTrue(store["enabled"])
        self.assertTrue(store["dry_run"])
        self.assertEqual(store["schema"], QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA)
        self.assertEqual(store["entry"]["status"], "miss")
        self.assertEqual(store["write"]["status"], "would_store")
        self.assertEqual(store["summary"]["lookup_count"], 1)
        self.assertEqual(store["summary"]["miss_count"], 1)
        self.assertEqual(store["summary"]["would_write_count"], 1)
        self.assertEqual(store["summary"]["write_count"], 0)
        self.assertEqual(files, [])
        self.assertIn("cache_store_status: `miss`", markdown)
        self.assertNotIn(tmp, serialized)

    def test_query_output_cache_store_reports_hit_and_baseline_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = build_query_output_cache_report(
                self._payload(top_k=5),
                config_version="retrieval-v1",
                cache_ttl_seconds=60,
                now_epoch=1000.0,
            )
            entry_path = root / "query-output" / f"{baseline['cache_key'].replace(':', '-')}.json"
            entry_path.parent.mkdir(parents=True)
            entry_path.write_text(
                json.dumps(
                    {
                        "schema": QUERY_OUTPUT_CACHE_ENTRY_SCHEMA,
                        "operation": "ragflow_query_output",
                        "cache_key": baseline["cache_key"],
                        "created_at_epoch": 1000.0,
                        "ttl_seconds": 60.0,
                        "cache_key_algorithm": "sha256",
                        "query_output_digest": baseline["query_output_digest"],
                        "field_fingerprints": baseline["field_fingerprints"],
                        "key_parts": baseline["key_parts"],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            hit = build_query_output_cache_report(
                self._payload(top_k=5),
                config_version="retrieval-v1",
                cache_dir=root,
                cache_ttl_seconds=60,
                now_epoch=1005.0,
            )
            current = build_query_output_cache_report(
                self._payload(top_k=10),
                baseline_report=baseline,
                config_version="retrieval-v2",
                cache_dir=root,
                cache_ttl_seconds=60,
                now_epoch=1010.0,
            )

        self.assertEqual(hit["cache_store"]["entry"]["status"], "hit")
        self.assertEqual(hit["cache_store"]["entry"]["age_seconds"], 5.0)
        self.assertEqual(hit["cache_store"]["summary"]["hit_count"], 1)
        self.assertEqual(hit["cache_store"]["summary"]["would_write_count"], 0)
        self.assertEqual(current["invalidation"]["status"], "invalidate")
        self.assertEqual(current["cache_store"]["entry"]["status"], "miss")
        self.assertEqual(current["cache_store"]["baseline_entry"]["status"], "hit")
        self.assertTrue(current["cache_store"]["invalidation"]["would_invalidate"])
        self.assertEqual(current["cache_store"]["summary"]["would_invalidate_count"], 1)
        self.assertEqual(current["cache_store"]["summary"]["would_write_count"], 1)

    def test_query_output_cache_store_active_write_and_invalidate_update_metadata_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = build_query_output_cache_report(
                self._payload(top_k=5),
                config_version="retrieval-v1",
                cache_dir=root,
                cache_ttl_seconds=60,
                cache_write=True,
                now_epoch=1000.0,
            )
            baseline_path = root / "query-output" / f"{baseline['cache_key'].replace(':', '-')}.json"
            baseline_entry_text = baseline_path.read_text(encoding="utf-8")

            current = build_query_output_cache_report(
                self._payload(top_k=10),
                baseline_report=baseline,
                config_version="retrieval-v2",
                cache_dir=root,
                cache_ttl_seconds=60,
                cache_write=True,
                cache_invalidate=True,
                now_epoch=1010.0,
            )
            current_path = root / "query-output" / f"{current['cache_key'].replace(':', '-')}.json"
            current_entry_text = current_path.read_text(encoding="utf-8")
            baseline_exists_after_invalidation = baseline_path.exists()
            current_exists_after_write = current_path.exists()

        self.assertTrue(baseline["ok"])
        self.assertEqual(baseline["cache_store"]["write"]["status"], "stored")
        self.assertEqual(baseline["cache_store"]["summary"]["write_count"], 1)
        self.assertIn(QUERY_OUTPUT_CACHE_ENTRY_SCHEMA, baseline_entry_text)
        self.assertFalse(baseline_exists_after_invalidation)
        self.assertTrue(current_exists_after_write)
        self.assertTrue(current["ok"])
        self.assertEqual(current["cache_store"]["write"]["status"], "stored")
        self.assertEqual(current["cache_store"]["invalidation"]["execution_status"], "invalidated")
        self.assertEqual(current["cache_store"]["summary"]["write_count"], 1)
        self.assertEqual(current["cache_store"]["summary"]["invalidate_count"], 1)
        self.assertIn(QUERY_OUTPUT_CACHE_ENTRY_SCHEMA, current_entry_text)
        self.assertNotIn("How should cached retrieval output be keyed?", current_entry_text)
        self.assertNotIn("cache invalidation key parts", current_entry_text)


if __name__ == "__main__":
    unittest.main()
