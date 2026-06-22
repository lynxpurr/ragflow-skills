from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.manifests import ManifestError, load_doc_manifest, load_kb_manifest


class ManifestTests(unittest.TestCase):
    def test_load_doc_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc_manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "created_at": "2026-06-22T00:00:00Z",
                        "source_root": "./input",
                        "documents": [
                            {
                                "source_path": "a.pdf",
                                "markdown_path": "documents/a.md",
                                "sha256": "abc",
                                "warnings": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest = load_doc_manifest(path)
        self.assertEqual(manifest.version, "0.1")
        self.assertEqual(manifest.documents[0].markdown_path, "documents/a.md")

    def test_doc_manifest_requires_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc_manifest.json"
            path.write_text(json.dumps({"version": "0.1", "documents": []}), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_doc_manifest(path)

    def test_load_kb_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kb_manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "dataset-id", "name": "kb:project"},
                        "profile": {"id": "default"},
                        "documents": [
                            {
                                "document_id": "doc-id",
                                "markdown_path": "documents/a.md",
                                "status": "parsed",
                                "chunk_count": 3,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest = load_kb_manifest(path)
        self.assertEqual(manifest.dataset.id, "dataset-id")
        self.assertEqual(manifest.documents[0].chunk_count, 3)

    def test_kb_manifest_requires_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kb_manifest.json"
            path.write_text(json.dumps({"version": "0.1", "documents": []}), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_kb_manifest(path)


if __name__ == "__main__":
    unittest.main()
