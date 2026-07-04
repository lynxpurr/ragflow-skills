from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.doc_postprocess import (
    CHUNK_PROFILE_REPORT_SCHEMA,
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

    def test_ocr_cleanup_preserves_html_and_markdown_table_blocks(self) -> None:
        html_table = (
            "<table><tr><td>型 号</td><td>HP-TMe</td></tr>"
            "<tr><td>温 度</td><td>18 °C - 22 °C</td></tr></table>"
        )
        pipe_table = "| 字 段 | 值 |\n| --- | --- |\n| 精 度 | 4 μ m |\n"
        text = f"龙 门 式 结构 ， 精度 高\n\n{html_table}\n\n{pipe_table}\n结 束 。\n"

        processed, rules = postprocess_markdown_text(text, profile="ocr")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertIn("龙门式结构，精度高", processed)
        self.assertIn("结束。", processed)
        self.assertIn(html_table, processed)
        self.assertIn(pipe_table, processed)
        self.assertGreater(counts["ocr.cjk_spaces"], 0)

    def test_chunk_markers_insert_before_later_headings(self) -> None:
        processed, rules = postprocess_markdown_text("# One\nBody\n## Two\nBody\n", profile="chunk-markers")
        counts = {rule.rule_id: rule.count for rule in rules}

        self.assertIn("Body\n\n<!-- chunk -->\n## Two", processed)
        self.assertEqual(counts["chunk_markers.heading_boundaries"], 1)

    def test_chunk_markers_report_table_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "table.md"
            markdown.write_text(
                "# One\n\n"
                "<table><tr><td>型 号</td><td>HP-TMe</td></tr></table>\n\n"
                "## Two\n\n结 束 。\n",
                encoding="utf-8",
            )

            report = postprocess_single_markdown(
                markdown,
                profile="chunk-markers",
                output_path=root / "out.md",
            )
            output_text = (root / "out.md").read_text(encoding="utf-8")

        document = report["documents"][0]
        table_integrity = document["table_integrity"]
        self.assertTrue(table_integrity["ok"])
        self.assertEqual(table_integrity["html_table_count_before"], 1)
        self.assertEqual(table_integrity["html_table_count_after"], 1)
        self.assertTrue(table_integrity["html_table_fingerprints_unchanged"])
        self.assertEqual(table_integrity["chunk_marker_inside_html_table_count"], 0)
        self.assertFalse(table_integrity["postprocess_table_delta"]["html_table_count_changed"])
        self.assertFalse(table_integrity["postprocess_table_delta"]["html_table_fingerprints_changed"])
        self.assertFalse(table_integrity["postprocess_table_delta"]["html_table_cell_count_changed"])
        self.assertIn("<table><tr><td>型 号</td><td>HP-TMe</td></tr></table>", output_text)
        self.assertIn("结束。", output_text)

    def test_chunk_marker_profiles_emit_stable_report_sidecar(self) -> None:
        text = (
            "# APOLLO Catalog\n\n"
            "Intro paragraph.\n\n"
            "<!-- page: 1 -->\n\n"
            "## Specs\n\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| Accuracy | 4.0 um |\n\n"
            "![diagram](images/apollo.png)\n\n"
            "- Confirm base\n"
            "- Calibrate sensor\n\n"
            "### Maintenance\n\n"
            "Body.\n\n"
            "#### Appendix\n\n"
            "More.\n\n"
            "##### Detail\n\n"
            "Fine.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "catalog.md"
            markdown.write_text(text, encoding="utf-8")
            reports: dict[str, dict[str, object]] = {}
            for profile in ("chunk-markers-conservative", "chunk-markers-dense", "chunk-markers-ragflux-like"):
                output = root / f"{profile}.md"
                report_json = root / f"{profile}.postprocess.json"
                chunk_report_json = root / f"{profile}.chunk-profile.json"

                report = postprocess_single_markdown(
                    markdown,
                    profile=profile,
                    output_path=output,
                    report_json=report_json,
                    chunk_profile_report_json=chunk_report_json,
                )
                chunk_report = json.loads(chunk_report_json.read_text(encoding="utf-8"))
                reports[profile] = chunk_report

                self.assertEqual(report["chunk_profile_report"]["schema"], CHUNK_PROFILE_REPORT_SCHEMA)
                self.assertEqual(chunk_report["schema"], CHUNK_PROFILE_REPORT_SCHEMA)
                self.assertEqual(chunk_report["profile"], profile)
                self.assertEqual(chunk_report["summary"]["documents"], 1)
                self.assertEqual(chunk_report["documents"][0]["markdown_path"], "catalog.md")

        conservative = reports["chunk-markers-conservative"]["summary"]
        dense = reports["chunk-markers-dense"]["summary"]
        ragflux = reports["chunk-markers-ragflux-like"]["summary"]
        dense_types = dense["marker_type_counts"]
        ragflux_types = ragflux["marker_type_counts"]

        self.assertLess(conservative["marker_count"], dense["marker_count"])
        self.assertLess(dense["marker_count"], ragflux["marker_count"])
        self.assertGreater(dense_types["heading"], 0)
        self.assertGreater(dense_types["page"], 0)
        self.assertGreater(dense_types["table"], 0)
        self.assertGreater(dense_types["image"], 0)
        self.assertEqual(dense_types["list"], 0)
        self.assertGreater(ragflux_types["list"], 0)
        self.assertGreaterEqual(ragflux["preferred_boundary_aligned_marker_count"], ragflux["marker_count"])

    def test_chunk_marker_fixture_profiles_have_monotonic_marker_counts(self) -> None:
        fixtures = {
            "product_catalog": (
                "# APOLLO Catalog\n\n"
                "Overview.\n\n"
                "<!-- page: 1 -->\n"
                "## Specs\n\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 um |\n\n"
                "![diagram](images/apollo.png)\n\n"
                "- Base inspection\n"
                "- Sensor calibration\n"
            ),
            "paper": (
                "# Sample Paper\n\n"
                "Abstract text.\n\n"
                "## Method\n\n"
                "Method body.\n\n"
                "### Dataset\n\n"
                "Dataset body.\n\n"
                "#### Hyperparameters\n\n"
                "Parameter body.\n"
            ),
            "contract": (
                "# Service Agreement\n\n"
                "The parties agree as follows.\n\n"
                "1. Scope of work\n"
                "2. Payment terms\n"
                "3. Termination\n\n"
                "## Liability\n\n"
                "Liability text.\n"
            ),
            "long_document": "# Operations Manual\n\nIntro.\n\n"
            + "\n".join(f"## Section {index}\nBody {index}\n" for index in range(1, 10)),
        }
        profiles = ("chunk-markers-conservative", "chunk-markers-dense", "chunk-markers-ragflux-like")
        dense_delta = 0
        ragflux_delta = 0

        for name, text in fixtures.items():
            counts: list[int] = []
            for profile in profiles:
                processed, _rules = postprocess_markdown_text(text, profile=profile)
                counts.append(processed.count("<!-- chunk -->"))
            self.assertLessEqual(counts[0], counts[1], name)
            self.assertLessEqual(counts[1], counts[2], name)
            dense_delta += counts[1] - counts[0]
            ragflux_delta += counts[2] - counts[1]

        self.assertGreater(dense_delta, 0)
        self.assertGreater(ragflux_delta, 0)

    def test_chunk_profile_density_warnings_detect_sparse_dense_and_empty_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sparse_markdown = root / "sparse.md"
            sparse_markdown.write_text("\n".join(f"plain line {index}" for index in range(12)) + "\n", encoding="utf-8")
            sparse_report = postprocess_single_markdown(
                sparse_markdown,
                profile="chunk-markers-conservative",
                output_path=root / "sparse.out.md",
            )

            dense_markdown = root / "dense.md"
            dense_markdown.write_text(
                "# Dense\n\n<!-- chunk -->\n\n<!-- chunk -->\nBody\n<!-- chunk -->\n",
                encoding="utf-8",
            )
            dense_report = postprocess_single_markdown(
                dense_markdown,
                profile="chunk-markers-conservative",
                output_path=root / "dense.out.md",
            )

        sparse_codes = {warning["code"] for warning in sparse_report["chunk_profile_report"]["documents"][0]["warnings"]}
        dense_codes = {warning["code"] for warning in dense_report["chunk_profile_report"]["documents"][0]["warnings"]}

        self.assertIn("marker_density_too_sparse", sparse_codes)
        self.assertIn("marker_density_too_dense", dense_codes)
        self.assertIn("consecutive_chunk_markers", dense_codes)
        self.assertIn("empty_chunk_section", dense_codes)

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
