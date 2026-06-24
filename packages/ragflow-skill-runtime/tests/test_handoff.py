from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.handoff import (
    ARTIFACT_INDEX_SCHEMA,
    DOCUMENT_METADATA_SCHEMA,
    HANDOFF_PACKAGE_SCHEMA,
    PROFILE_SUGGESTIONS_SCHEMA,
    create_rich_handoff_package,
    inspect_rich_handoff,
    render_handoff_inspection_markdown,
)


class HandoffTests(unittest.TestCase):
    def test_create_rich_handoff_package_indexes_metadata_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            images = documents / "images"
            images.mkdir(parents=True)
            source = root / "source.md"
            markdown = documents / "source.md"
            image = images / "chart.jpg"
            source.write_text("# Source\n", encoding="utf-8")
            markdown.write_text("# Source\n\n![chart](images/chart.jpg)\n", encoding="utf-8")
            image.write_bytes(b"fake image bytes")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [
                            {
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "sha256": "abc",
                                "title": "Source",
                                "warnings": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )

            package = create_rich_handoff_package(handoff_root=root)
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            artifact_index = json.loads((root / "artifact_index.json").read_text(encoding="utf-8"))
            suggestions = json.loads((root / "profile_suggestions.json").read_text(encoding="utf-8"))

        self.assertEqual(package["schema"], HANDOFF_PACKAGE_SCHEMA)
        self.assertEqual(package["document_count"], 1)
        self.assertEqual(package["artifact_count"], 1)
        self.assertEqual(metadata["schema"], DOCUMENT_METADATA_SCHEMA)
        self.assertEqual(metadata["documents"][0]["markdown"]["path"], "documents/source.md")
        self.assertEqual(artifact_index["schema"], ARTIFACT_INDEX_SCHEMA)
        self.assertEqual(artifact_index["artifacts"][0]["path"], "documents/images/chart.jpg")
        self.assertEqual(suggestions["schema"], PROFILE_SUGGESTIONS_SCHEMA)
        self.assertIn("image-rich Markdown detected", suggestions["warnings"][0])

    def test_inspect_rich_handoff_reports_optional_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            (documents / "a.md").write_text("# A\n", encoding="utf-8")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "a.md", "markdown_path": "documents/a.md"}],
                    }
                ),
                encoding="utf-8",
            )
            create_rich_handoff_package(handoff_root=root)

            report = inspect_rich_handoff(handoff_root=root)
            markdown = render_handoff_inspection_markdown(report)

        self.assertEqual(report["document_count"], 1)
        self.assertTrue(report["sidecars"]["metadata"]["exists"])
        self.assertIn("RAGFlow Handoff Inspection", markdown)
        self.assertIn("metadata", markdown)


if __name__ == "__main__":
    unittest.main()
