from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.doc_convert import (
    ConvertedDocument,
    DocConvertError,
    SourceDocument,
    convert_source_to_markdown,
    discover_source_documents,
    extract_markdown_title,
    html_to_markdown,
    make_doc_manifest_payload,
    safe_markdown_name,
    sha256_file,
    text_to_markdown,
)


class DocConvertTests(unittest.TestCase):
    def test_discover_source_documents_skips_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "visible.md").write_text("# Visible\n", encoding="utf-8")
            (root / ".hidden.md").write_text("# Hidden\n", encoding="utf-8")
            docs = discover_source_documents(root)

        self.assertEqual([doc.source_path for doc in docs], ["visible.md"])

    def test_text_to_markdown_adds_title(self) -> None:
        markdown = text_to_markdown("Hello\nWorld", title="sample")
        self.assertTrue(markdown.startswith("# sample"))

    def test_html_to_markdown_handles_heading_and_link(self) -> None:
        markdown = html_to_markdown("<h1>Title</h1><p>Hello <a href='https://e.test'>link</a></p>")
        self.assertIn("# Title", markdown)
        self.assertIn("[link](https://e.test)", markdown)

    def test_convert_source_to_markdown_builtin_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("Plain body", encoding="utf-8")
            markdown, warnings = convert_source_to_markdown(
                SourceDocument(path=path, source_path="note.txt"),
                backend="builtin",
            )

        self.assertIn("Plain body", markdown)
        self.assertEqual(warnings, [])

    def test_convert_source_to_markdown_passthrough_rejects_non_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("Plain body", encoding="utf-8")
            with self.assertRaises(DocConvertError):
                convert_source_to_markdown(
                    SourceDocument(path=path, source_path="note.txt"),
                    mode="passthrough",
                )

    def test_safe_markdown_name_deduplicates(self) -> None:
        used: set[str] = set()
        first = safe_markdown_name(
            SourceDocument(path=Path("/tmp/a.md"), source_path="dir/a.md"),
            used=used,
        )
        second = safe_markdown_name(
            SourceDocument(path=Path("/tmp/a.txt"), source_path="other/a.txt"),
            used=used,
        )
        self.assertEqual(first, "a.md")
        self.assertEqual(second, "a-2.md")

    def test_make_doc_manifest_payload_uses_relative_markdown_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs_dir = root / "documents"
            docs_dir.mkdir()
            source_path = root / "input.md"
            source_path.write_text("# Title\n", encoding="utf-8")
            markdown_path = docs_dir / "input.md"
            markdown_path.write_text("# Title\n", encoding="utf-8")

            payload = make_doc_manifest_payload(
                output_root=root,
                documents=[
                    ConvertedDocument(
                        source=SourceDocument(path=source_path, source_path="input.md"),
                        markdown_path=markdown_path,
                        sha256=sha256_file(source_path),
                        title=extract_markdown_title("# Title\n"),
                        warnings=[],
                    )
                ],
            )

        self.assertEqual(payload["documents"][0]["markdown_path"], "documents/input.md")


if __name__ == "__main__":
    unittest.main()
