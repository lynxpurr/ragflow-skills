from __future__ import annotations

import unittest

from ragflow_skill_runtime.manifests import KbDataset, KbManifest
from ragflow_skill_runtime.retrieval import (
    RetrievalError,
    normalize_retrieval_response,
    resolve_dataset_ids,
)


class FakeClient:
    def __init__(self, response):
        self.response = response

    def list_datasets(self, *, page=1, page_size=200, name=None):
        return self.response


class RetrievalTests(unittest.TestCase):
    def test_normalize_ragflow_chunks(self) -> None:
        chunks = normalize_retrieval_response(
            {
                "data": {
                    "chunks": [
                        {
                            "content_with_weight": "body",
                            "docnm_kwd": "doc.md",
                            "similarity": 0.42,
                            "important_kwd": ["ragflow", "query"],
                            "kb_id": "ds-1",
                        }
                    ]
                }
            }
        )
        self.assertEqual(chunks[0].content, "body")
        self.assertEqual(chunks[0].document_name, "doc.md")
        self.assertEqual(chunks[0].important_keywords, ["ragflow", "query"])

    def test_resolve_dataset_ids_from_manifest_and_explicit_ids(self) -> None:
        manifest = KbManifest(
            version="0.1",
            created_at=None,
            ragflow_base_url=None,
            dataset=KbDataset(id="ds-manifest", name="kb:manifest"),
            documents=[],
        )
        ids = resolve_dataset_ids(dataset_ids=["ds-explicit"], kb_manifest=manifest)
        self.assertEqual(ids, ["ds-explicit", "ds-manifest"])

    def test_resolve_dataset_ids_by_name(self) -> None:
        client = FakeClient({"data": {"docs": [{"id": "ds-1", "name": "kb:test"}]}})
        self.assertEqual(resolve_dataset_ids(client=client, dataset_names=["kb:test"]), ["ds-1"])

    def test_resolve_dataset_ids_requires_input(self) -> None:
        with self.assertRaises(RetrievalError):
            resolve_dataset_ids()


if __name__ == "__main__":
    unittest.main()
