from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from ragflow_skill_runtime.kb_build import (
    BuildError,
    BuildDocument,
    discover_markdown_documents,
    extract_document_states,
    extract_dataset_id,
    extract_uploaded_document_id,
    make_kb_manifest_payload,
    normalize_document_state,
    wait_for_document_states,
)
from ragflow_skill_runtime.manifests import DocManifest, DocumentEntry
from ragflow_skill_runtime.profiles import ChunkProfile


class FakeDocumentClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def list_documents(self, dataset_id):
        self.calls += 1
        return self.responses.pop(0)


class KbBuildTests(unittest.TestCase):
    def test_discover_markdown_documents_requires_existing_files(self) -> None:
        manifest = DocManifest(
            version="0.1",
            created_at=None,
            source_root="/tmp/does-not-exist",
            documents=[
                DocumentEntry(
                    source_path="a.pdf",
                    markdown_path="docs/a.md",
                    warnings=[],
                )
            ],
        )
        with self.assertRaises(BuildError):
            discover_markdown_documents(doc_manifest=manifest)

    def test_discover_doc_manifest_paths_are_relative_to_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs_dir = root / "documents"
            docs_dir.mkdir()
            markdown = docs_dir / "a.md"
            markdown.write_text("# A\n", encoding="utf-8")
            manifest_path = root / "doc_manifest.json"
            manifest = DocManifest(
                version="0.1",
                created_at=None,
                source_root=".",
                documents=[
                    DocumentEntry(
                        source_path="a.pdf",
                        markdown_path="documents/a.md",
                        warnings=[],
                    )
                ],
            )
            docs = discover_markdown_documents(
                doc_manifest=manifest,
                manifest_base_path=manifest_path,
            )

        self.assertEqual(docs[0].path, markdown)

    def test_extract_dataset_id_from_nested_response(self) -> None:
        self.assertEqual(extract_dataset_id({"data": {"id": "ds-1"}}), "ds-1")

    def test_extract_uploaded_document_id_from_list_response(self) -> None:
        self.assertEqual(extract_uploaded_document_id({"data": [{"id": "doc-1"}]}), "doc-1")

    def test_make_kb_manifest_payload(self) -> None:
        profile = ChunkProfile.from_dict({"profile_id": "default-en-768", "chunk_size": 768})
        payload = make_kb_manifest_payload(
            base_url="https://ragflow.example.test/api/v1",
            dataset_id="ds-1",
            dataset_name="kb:test",
            profile=profile,
            documents=[
                (
                    BuildDocument(path=Path("/tmp/a.md"), manifest_source_path="a.pdf"),
                    "doc-1",
                    "uploaded",
                    None,
                )
            ],
        )
        self.assertEqual(payload["dataset"]["id"], "ds-1")
        self.assertEqual(payload["documents"][0]["document_id"], "doc-1")
        self.assertEqual(payload["documents"][0]["source_path"], "a.pdf")
        self.assertEqual(payload["profile"]["id"], "default-en-768")

    def test_normalize_document_state_uses_progress_as_success(self) -> None:
        state = normalize_document_state(
            {"id": "doc-1", "progress": 1.0, "chunk_count": "7"},
        )
        self.assertEqual(state["status"], "1")
        self.assertEqual(state["chunk_count"], 7)

    def test_extract_document_states_filters_requested_ids(self) -> None:
        states = extract_document_states(
            {
                "data": {
                    "docs": [
                        {"id": "doc-1", "run": "DONE", "chunk_count": 4},
                        {"id": "doc-2", "run": "RUNNING"},
                    ]
                }
            },
            document_ids=["doc-1"],
        )
        self.assertEqual(list(states), ["doc-1"])
        self.assertEqual(states["doc-1"]["status"], "done")

    def test_wait_for_document_states_returns_when_all_parsed(self) -> None:
        client = FakeDocumentClient(
            [
                {
                    "data": {
                        "docs": [
                            {"id": "doc-1", "run": "DONE", "chunk_count": 3},
                            {"id": "doc-2", "progress": 1, "chunk_count": 5},
                        ]
                    }
                }
            ]
        )
        states = wait_for_document_states(
            client,
            dataset_id="ds-1",
            document_ids=["doc-1", "doc-2"],
            timeout=1,
            poll_interval=0,
        )
        self.assertEqual(states["doc-1"]["chunk_count"], 3)
        self.assertEqual(states["doc-2"]["status"], "1")


if __name__ == "__main__":
    unittest.main()
