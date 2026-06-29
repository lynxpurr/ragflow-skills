from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.doc_convert import (
    ConvertedDocument,
    DEFAULT_MINERU_BASE_URL,
    DocConvertError,
    SourceDocument,
    convert_source_to_markdown,
    copy_local_markdown_assets,
    discover_source_documents,
    extract_markdown_title,
    html_to_markdown,
    make_doc_manifest_payload,
    probe_conversion_backends,
    render_backend_probe_markdown,
    safe_markdown_name,
    sha256_file,
    text_to_markdown,
)
from ragflow_skill_runtime.doc_quality import (
    BLOCKED,
    PASS,
    PASS_WITH_REVIEW,
    QualityDocument,
    make_quality_report_payload,
)
from ragflow_skill_runtime.doc_segment import materialize_segments, plan_markdown_segmentation


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

    def test_auto_does_not_call_default_mineru_service_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.pdf"
            path.write_bytes(b"%PDF fake")
            with self.assertRaisesRegex(DocConvertError, "no converter available"):
                convert_source_to_markdown(
                    SourceDocument(path=path, source_path="paper.pdf"),
                    backend="auto",
                    mineru_base_url=DEFAULT_MINERU_BASE_URL,
                    mineru_api_key=None,
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

    def test_backend_probe_emits_runtime_partial_failure_summary(self) -> None:
        report = probe_conversion_backends(
            backend="auto",
            remote_url="ftp://converter.example.test/convert",
            mineru_base_url=None,
            mineru_api_key=None,
            mineru_cli_path="/definitely/missing/mineru",
            network_check=False,
        )
        markdown = render_backend_probe_markdown(report)

        self.assertEqual(report["schema"], "ragflow_doc_backend_probe_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertTrue(report["runtime_partial_failure"]["summary"]["partial"])
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "partial")
        self.assertGreaterEqual(report["summary"]["runtime_failure_count"], 1)
        self.assertGreaterEqual(report["summary"]["runtime_skipped_count"], 1)
        self.assertIn("runtime_partial_failure_status: `partial`", markdown)
        self.assertIn("runtime_skipped:", markdown)

    def test_quality_report_passes_clean_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "clean.md"
            markdown.parent.mkdir()
            markdown.write_text("# Clean\n\nBody\n", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[QualityDocument(source_path="clean.md", markdown_path=markdown)],
            )

        self.assertEqual(report["gate"]["status"], PASS)
        self.assertEqual(report["gate"]["summary"]["errors"], 0)

    def test_quality_report_blocks_empty_and_missing_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "broken.md"
            empty = root / "documents" / "empty.md"
            markdown.parent.mkdir()
            markdown.write_text("# Broken\n\n![missing](images/nope.png)\n", encoding="utf-8")
            empty.write_text("", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[
                    QualityDocument(source_path="broken.md", markdown_path=markdown),
                    QualityDocument(source_path="empty.md", markdown_path=empty),
                ],
            )

        issue_types = {
            issue["issue_type"]
            for document in report["documents"]
            for issue in document["issues"]
        }
        self.assertEqual(report["gate"]["status"], BLOCKED)
        self.assertIn("image_missing", issue_types)
        self.assertIn("markdown_empty", issue_types)

    def test_copy_local_markdown_assets_rewrites_absolute_temp_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mineru_root = root / "mineru-output"
            mineru_images = mineru_root / "images"
            mineru_images.mkdir(parents=True)
            markdown_path = mineru_root / "paper.md"
            image_path = mineru_images / "chart.jpg"
            image_path.write_bytes(b"fake image bytes")
            markdown_path.write_text(f"# Paper\n\n![chart]({image_path})\n", encoding="utf-8")
            handoff_documents = root / "handoff" / "documents"

            rewritten = copy_local_markdown_assets(
                markdown_path.read_text(encoding="utf-8"),
                markdown_path=markdown_path,
                source_root=mineru_root,
                asset_output_dir=handoff_documents,
            )
            copied = handoff_documents / "images" / "chart.jpg"
            copied_exists = copied.is_file()

        self.assertIn("![chart](images/chart.jpg)", rewritten)
        self.assertTrue(copied_exists)

    def test_quality_report_marks_conversion_warning_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "review.md"
            markdown.parent.mkdir()
            markdown.write_text("# Review\n\nBody\n", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[
                    QualityDocument(
                        source_path="review.docx",
                        markdown_path=markdown,
                        warnings=["pandoc was unavailable; used fallback"],
                    )
                ],
            )

        self.assertEqual(report["gate"]["status"], PASS_WITH_REVIEW)
        self.assertEqual(report["gate"]["summary"]["warnings"], 1)

    def test_plan_markdown_segmentation_uses_heading_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "long.md"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            plan = plan_markdown_segmentation(
                markdown,
                soft_max_chars=50,
                hard_max_chars=90,
                min_segment_chars=20,
            )

        self.assertTrue(plan.recommended)
        self.assertEqual(len(plan.segments), 2)
        self.assertEqual(plan.segments[0].title, "One")
        self.assertEqual(plan.segments[1].title, "Two")

    def test_materialize_segments_writes_segment_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "long.md"
            output = root / "segments"
            plan_output = root / "segmentation_plan.json"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            result = materialize_segments(
                markdown,
                output_dir=output,
                plan_output=plan_output,
                soft_max_chars=50,
                hard_max_chars=90,
                min_segment_chars=20,
            )
            plan_exists = plan_output.exists()
            first_segment_exists = (output / "long.part-001.md").exists()

        self.assertEqual(len(result.segment_paths), 2)
        self.assertTrue(plan_exists)
        self.assertTrue(first_segment_exists)


if __name__ == "__main__":
    unittest.main()
