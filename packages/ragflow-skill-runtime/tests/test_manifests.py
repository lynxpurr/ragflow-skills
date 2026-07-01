from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.manifests import (
    DOC_MANIFEST_JSON_SCHEMA,
    KB_MANIFEST_JSON_SCHEMA,
    ManifestError,
    load_doc_manifest,
    load_kb_manifest,
    manifest_json_schemas,
    validate_payload_with_json_schema,
)


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
                                "source_path": "source.pdf",
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
        self.assertEqual(manifest.documents[0].source_path, "source.pdf")
        self.assertEqual(manifest.documents[0].chunk_count, 3)

    def test_kb_manifest_requires_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kb_manifest.json"
            path.write_text(json.dumps({"version": "0.1", "documents": []}), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_kb_manifest(path)

    def test_manifest_json_schemas_are_defensive_copies(self) -> None:
        schemas = manifest_json_schemas()

        schemas["doc_manifest"]["properties"]["version"]["const"] = "mutated"

        self.assertEqual(DOC_MANIFEST_JSON_SCHEMA["properties"]["version"]["const"], "0.1")
        self.assertEqual(KB_MANIFEST_JSON_SCHEMA["properties"]["version"]["const"], "0.1")

    def test_doc_manifest_json_schema_accepts_current_shape(self) -> None:
        payload = {
            "version": "0.1",
            "source_root": ".",
            "documents": [
                {
                    "source_path": "source.pdf",
                    "markdown_path": "documents/source.md",
                    "warnings": [],
                }
            ],
        }

        validate_payload_with_json_schema(payload, DOC_MANIFEST_JSON_SCHEMA)

    def test_doc_manifest_json_schema_rejects_empty_documents(self) -> None:
        with self.assertRaisesRegex(ManifestError, "documents"):
            validate_payload_with_json_schema(
                {"version": "0.1", "documents": []},
                DOC_MANIFEST_JSON_SCHEMA,
            )

    def test_kb_manifest_json_schema_rejects_invalid_chunk_count(self) -> None:
        with self.assertRaisesRegex(ManifestError, "chunk_count"):
            validate_payload_with_json_schema(
                {
                    "version": "0.1",
                    "dataset": {"id": "dataset-id", "name": "kb:project"},
                    "documents": [
                        {
                            "document_id": "doc-id",
                            "chunk_count": -1,
                        }
                    ],
                },
                KB_MANIFEST_JSON_SCHEMA,
            )


if __name__ == "__main__":
    unittest.main()
