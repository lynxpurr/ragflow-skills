from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime import (
    RUNTIME_CACHE_REPORT_SCHEMA,
    RuntimeCache,
    runtime_cache_digest,
    runtime_cache_secret_digest,
)


class RuntimeCacheTests(unittest.TestCase):
    def test_cache_digest_is_stable_without_exposing_key_material(self) -> None:
        digest_a = runtime_cache_digest(
            "unit-test",
            {
                "endpoint": "https://ragflow.example.test/api",
                "params": {"top_k": 5, "dataset_ids": ["kb-1"]},
                "secret": runtime_cache_secret_digest("unit-test-secret"),
            },
        )
        digest_b = runtime_cache_digest(
            "unit-test",
            {
                "secret": runtime_cache_secret_digest("unit-test-secret"),
                "params": {"dataset_ids": ["kb-1"], "top_k": 5},
                "endpoint": "https://ragflow.example.test/api",
            },
        )

        self.assertEqual(digest_a, digest_b)
        self.assertTrue(digest_a.startswith("sha256:"))
        self.assertNotIn("unit-test-secret", digest_a)
        self.assertNotIn("ragflow.example.test", digest_a)

    def test_cache_records_miss_write_hit_and_summary(self) -> None:
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            cache = RuntimeCache(
                operation="unit-test",
                cache_dir=Path(tmp),
                ttl_seconds=60,
                namespace="probe",
                clock=lambda: now[0],
            )
            lookup = cache.get({"url": "https://ragflow.example.test/api"})
            store = cache.put(lookup.cache_key, {"status": "reachable", "http_status": 200})
            hit = cache.get({"url": "https://ragflow.example.test/api"})
            report = cache.to_report()

        self.assertEqual(lookup.status, "miss")
        self.assertEqual(store.status, "stored")
        self.assertEqual(hit.status, "hit")
        self.assertEqual(hit.value["status"], "reachable")
        self.assertEqual(hit.age_seconds, 0.0)
        self.assertEqual(report["schema"], RUNTIME_CACHE_REPORT_SCHEMA)
        self.assertTrue(report["enabled"])
        self.assertEqual(report["summary"]["lookup_count"], 2)
        self.assertEqual(report["summary"]["miss_count"], 1)
        self.assertEqual(report["summary"]["hit_count"], 1)
        self.assertEqual(report["summary"]["write_count"], 1)

    def test_cache_marks_expired_entries_stale(self) -> None:
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            cache = RuntimeCache(
                operation="unit-test",
                cache_dir=Path(tmp),
                ttl_seconds=5,
                namespace="probe",
                clock=lambda: now[0],
            )
            lookup = cache.get({"url": "https://ragflow.example.test/api"})
            cache.put(lookup.cache_key, {"status": "reachable"})
            now[0] = 1010.0
            stale = cache.get({"url": "https://ragflow.example.test/api"})
            report = cache.to_report()

        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.age_seconds, 10.0)
        self.assertEqual(report["summary"]["stale_count"], 1)

    def test_disabled_cache_reports_bypass(self) -> None:
        cache = RuntimeCache(operation="unit-test")
        lookup = cache.get({"url": "https://ragflow.example.test/api"})
        report = cache.to_report()

        self.assertEqual(lookup.status, "disabled")
        self.assertFalse(report["enabled"])
        self.assertEqual(report["summary"]["bypass_count"], 1)


if __name__ == "__main__":
    unittest.main()
