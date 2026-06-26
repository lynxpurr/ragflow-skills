from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.centroid_routing import (
    CENTROID_BUILD_PLAN_SCHEMA,
    CENTROID_INDEX_SCHEMA,
    build_centroid_plan,
    render_centroid_plan_markdown,
)


class CentroidRoutingTests(unittest.TestCase):
    def test_build_centroid_plan_from_manifest_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            snapshot = root / "chunk_snapshot.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-technical", "name": "kb:technical"},
                        "documents": [
                            {"document_id": "doc-1", "source_path": "source.md", "chunk_count": 2}
                        ],
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
                                "document_name": "source.md",
                                "chunk_id": "chunk-1",
                                "stable_hash": "sha256:chunk1",
                                "content": "Runtime API configuration evidence.",
                            },
                            {
                                "dataset_id": "ds-technical",
                                "document_name": "source.md",
                                "chunk_id": "chunk-2",
                                "stable_hash": "sha256:chunk2",
                                "content": "Integration setup evidence.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = build_centroid_plan(
                kb_manifest_paths=[manifest],
                chunk_snapshot_paths=[snapshot],
                index_output=root / "centroids.json",
                embedding_model="example-embedding",
                embedding_dimension=3,
                batch_size=16,
            )
            markdown = render_centroid_plan_markdown(report)

        self.assertEqual(report["schema"], CENTROID_BUILD_PLAN_SCHEMA)
        self.assertEqual(report["index_schema"], CENTROID_INDEX_SCHEMA)
        self.assertEqual(report["summary"]["dataset_count"], 1)
        self.assertEqual(report["summary"]["ready_centroid_count"], 1)
        self.assertEqual(report["summary"]["blocked_centroid_count"], 0)
        self.assertEqual(report["summary"]["chunk_count"], 2)
        self.assertTrue(report["datasets"][0]["ready_for_execution"])
        self.assertEqual(report["centroids"][0]["status"], "planned")
        self.assertTrue(report["centroids"][0]["source_hash"].startswith("sha256:"))
        self.assertIn("RAGFlow Centroid Build Plan", markdown)

    def test_manifest_only_plan_reports_needed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-general", "name": "kb:general"},
                        "documents": [{"document_id": "doc-1", "chunk_count": 3}],
                    }
                ),
                encoding="utf-8",
            )

            report = build_centroid_plan(kb_manifest_paths=[manifest])

        self.assertEqual(report["summary"]["ready_centroid_count"], 0)
        self.assertEqual(report["summary"]["blocked_centroid_count"], 1)
        self.assertIn("centroid_needs_chunk_snapshot", {issue["code"] for issue in report["issues"]})
        self.assertIn("embedding_model_not_configured", {issue["code"] for issue in report["issues"]})


if __name__ == "__main__":
    unittest.main()
