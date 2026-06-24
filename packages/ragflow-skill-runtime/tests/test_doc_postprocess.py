from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.doc_postprocess import (
    POSTPROCESS_REPORT_SCHEMA,
    DocPostprocessError,
    postprocess_handoff,
    postprocess_markdown_text,
    postprocess_single_markdown,
)


class DocPostprocessTests(unittest.TestCase):
    def test_safe_profile_repairs_heading_spacing_and_blank_lines(self) -> None:
        text = "#Title  \r\n\r\n\r\nBody\r\n![x](.\\images\\a.png)\r\n"

        processed, rules = postprocess_markdown_text(text, profile="safe")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertIn("# Title\n\nBody\n![x](images/a.png)\n", processed)
        self.assertGreater(counts["safe.heading_spacing"], 0)
        self.assertGreater(counts["safe.blank_lines"], 0)
        self.assertGreater(counts["safe.image_paths"], 0)

    def test_safe_profile_rewrites_absolute_temp_image_path(self) -> None:
        text = "![x](/tmp/mineru-run/doc/images/chart.jpg)\n"

        processed, rules = postprocess_markdown_text(text, profile="safe")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertEqual(processed, "![x](images/chart.jpg)\n")
        self.assertGreater(counts["safe.image_paths"], 0)

    def test_ocr_profile_repairs_cjk_spaces_and_ligatures(self) -> None:
        processed, rules = postprocess_markdown_text("龙 门 式 ﬁ 结构 ， 精度 高\n", profile="ocr")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertIn("龙门式 fi 结构，精度高", processed)
        self.assertGreater(counts["ocr.cjk_spaces"], 0)
        self.assertGreater(counts["ocr.ligatures"], 0)

    def test_chunk_markers_insert_before_later_headings(self) -> None:
        processed, rules = postprocess_markdown_text("# One\nBody\n## Two\nBody\n", profile="chunk-markers")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertIn("Body\n\n<!-- chunk -->\n## Two", processed)
        self.assertEqual(counts["chunk_markers.heading_boundaries"], 1)

    def test_single_markdown_requires_output_unless_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "a.md"
            markdown.write_text("#A\n", encoding="utf-8")
            with self.assertRaises(DocPostprocessError):
                postprocess_single_markdown(markdown, profile="safe")

    def test_single_markdown_writes_output_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "a.md"
            output = root / "out.md"
            report_json = root / "report.json"
            markdown.write_text("#A\n\n\nBody", encoding="utf-8")

            report = postprocess_single_markdown(
                markdown,
                profile="safe",
                output_path=output,
                report_json=report_json,
            )
            output_text = output.read_text(encoding="utf-8")
            persisted = json.loads(report_json.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], POSTPROCESS_REPORT_SCHEMA)
        self.assertEqual(persisted["schema"], POSTPROCESS_REPORT_SCHEMA)
        self.assertIn("# A\n\nBody\n", output_text)
        self.assertTrue(report["documents"][0]["changed"])

    def test_single_markdown_default_report_uses_output_file_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "a.md"
            output = root / "clean" / "a.md"
            markdown.write_text("#A\n", encoding="utf-8")

            postprocess_single_markdown(markdown, profile="safe", output_path=output)

            self.assertTrue(output.is_file())
            self.assertTrue((output.parent / "postprocess_report.json").is_file())

    def test_handoff_output_copies_manifest_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            images = docs / "images"
            images.mkdir(parents=True)
            markdown = docs / "a.md"
            markdown.write_text("#A\n\n![chart](images/chart.jpg)\n", encoding="utf-8")
            (images / "chart.jpg").write_bytes(b"fake image")
            (handoff / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "a.md", "markdown_path": "documents/a.md"}],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "processed"

            report = postprocess_handoff(
                handoff / "doc_manifest.json",
                profile="safe",
                output_dir=output,
            )

            self.assertEqual(report["schema"], POSTPROCESS_REPORT_SCHEMA)
            self.assertTrue((output / "doc_manifest.json").is_file())
            self.assertTrue((output / "documents" / "images" / "chart.jpg").is_file())
            self.assertEqual(report["documents"][0]["markdown_path"], "documents/a.md")
            self.assertEqual(report["documents"][0]["output_path"], "documents/a.md")
            self.assertIn("# A", (output / "documents" / "a.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
