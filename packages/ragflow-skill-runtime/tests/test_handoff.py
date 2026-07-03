from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.assistant_review import review_assistant_test_plan
from ragflow_skill_runtime.handoff import (
    ASSISTANT_PROFILE_SCHEMA,
    ASSISTANT_TEST_PLAN_SCHEMA,
    ARTIFACT_INDEX_SCHEMA,
    DOCUMENT_METADATA_SCHEMA,
    HANDOFF_PACKAGE_SCHEMA,
    PROFILE_SUGGESTIONS_SCHEMA,
    RAGFLOW_INGEST_PLAN_SCHEMA,
    RETRIEVAL_HINTS_SCHEMA,
    create_rich_handoff_package,
    inspect_rich_handoff,
    load_ragflow_ingest_plan,
    make_ragflow_ingest_plan_payload,
    render_handoff_inspection_markdown,
)
from ragflow_skill_runtime.kb_build import BuildDocument
from ragflow_skill_runtime.topology import create_kb_topology_advice


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
            markdown.write_text(
                "# Source\n\n"
                "The APOLLO accuracy is 4.0+4.0L/1000 μm.\n\n"
                "## Specs\n\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 μm |\n\n"
                "![chart](images/chart.jpg)\n",
                encoding="utf-8",
            )
            image.write_bytes(b"fake image bytes")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "handoff_mode": "formal_ingest",
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
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_profile = json.loads((root / "assistant_profile.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((root / "assistant_test_plan.json").read_text(encoding="utf-8"))
            readme = (root / "package_readme.md").read_text(encoding="utf-8")

        self.assertEqual(package["schema"], HANDOFF_PACKAGE_SCHEMA)
        self.assertEqual(package["handoff_mode"], "formal_ingest")
        self.assertEqual(package["document_count"], 1)
        self.assertEqual(package["artifact_count"], 1)
        self.assertGreaterEqual(package["retrieval_hint_count"], 2)
        self.assertGreaterEqual(package["assistant_test_count"], 1)
        self.assertEqual(metadata["schema"], DOCUMENT_METADATA_SCHEMA)
        self.assertEqual(metadata["documents"][0]["markdown"]["path"], "documents/source.md")
        self.assertEqual(metadata["documents"][0]["source_inventory"]["source_format"], "md")
        self.assertEqual(metadata["documents"][0]["source_inventory"]["mime_hint"], "text/markdown")
        self.assertEqual(artifact_index["schema"], ARTIFACT_INDEX_SCHEMA)
        self.assertEqual(artifact_index["artifacts"][0]["path"], "documents/images/chart.jpg")
        self.assertEqual(suggestions["schema"], PROFILE_SUGGESTIONS_SCHEMA)
        self.assertIn("image-rich Markdown detected", suggestions["warnings"][0])
        self.assertEqual(retrieval_hints["schema"], RETRIEVAL_HINTS_SCHEMA)
        self.assertGreaterEqual(len(retrieval_hints["section_boundaries"]), 2)
        self.assertTrue(any(item["term"] == "Specs" for item in retrieval_hints["keyword_candidates"]))
        self.assertTrue(any(item["type"] == "exact_numeric_fact" for item in retrieval_hints["question_candidates"]))
        self.assertEqual(assistant_profile["schema"], ASSISTANT_PROFILE_SCHEMA)
        self.assertTrue(assistant_profile["retrieval"]["require_evidence"])
        self.assertEqual(assistant_test_plan["schema"], ASSISTANT_TEST_PLAN_SCHEMA)
        self.assertTrue(any(case["stage"] == "negative_boundary" for case in assistant_test_plan["cases"]))
        self.assertIn("Handoff mode: `formal_ingest`", readme)
        self.assertIn("ragflow-kb-build inspect-handoff", readme)
        self.assertIn("--dry-run", readme)

    def test_retrieval_hints_include_pages_context_templates_and_layout_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            images = documents / "images"
            images.mkdir(parents=True)
            source = root / "apollo.pdf"
            markdown = documents / "apollo.md"
            image = images / "apollo.png"
            source.write_bytes(b"%PDF fake")
            image.write_bytes(b"fake image bytes")
            markdown.write_text(
                "<!-- page: 1 -->\n"
                "# APOLLO 产品目录\n\n"
                "APOLLO 工业设备用于高精度测量和自动化应用。\n\n"
                "## 技术参数\n\n"
                "| 型号 | 精度 | 尺寸 |\n"
                "| --- | --- | --- |\n"
                "| APOLLO-A | 4.0 μm | 1200 mm |\n\n"
                "外观图展示控制面板和安装结构。\n"
                "![APOLLO 设备外观](images/apollo.png)\n\n"
                "<!-- page: 2 -->\n"
                "<!-- chunk -->\n"
                "## 安装维护\n\n"
                "安装前检查安全注意事项，维护周期为 30 天。\n",
                encoding="utf-8",
            )
            (root / "content_list.json").write_text(
                json.dumps(
                    [
                        {"type": "title", "text": "APOLLO 产品目录", "page": 1, "level": 1},
                        {"type": "image", "caption": "APOLLO 控制面板", "page": 1, "path": "documents/images/apollo.png"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [
                            {
                                "source_path": "apollo.pdf",
                                "markdown_path": "documents/apollo.md",
                                "sha256": "abc",
                                "title": "APOLLO 产品目录",
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

            create_rich_handoff_package(handoff_root=root)
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((root / "assistant_test_plan.json").read_text(encoding="utf-8"))
            topology_advice = create_kb_topology_advice(
                kb_name="kb:apollo-catalog",
                documents=[BuildDocument(markdown)],
                retrieval_hints_path=root / "retrieval_hints.json",
                future_growth="high",
                min_documents=1,
                min_total_chars=100,
            )

        sections = retrieval_hints["section_boundaries"]
        image_artifacts = retrieval_hints["image_artifacts"]
        table_artifacts = retrieval_hints["table_artifacts"]
        preferred_boundaries = retrieval_hints["preferred_boundaries"]
        keywords = retrieval_hints["keyword_candidates"]
        questions = retrieval_hints["question_candidates"]
        numeric = retrieval_hints["numeric_candidates"]
        assistant_stages = {case["stage"] for case in assistant_test_plan["cases"]}
        topology_starter_types = {case["type"] for case in topology_advice["route_test_starters"]}

        tech_section = next(item for item in sections if item["title"] == "技术参数")
        self.assertEqual(tech_section["page_start"], 1)
        self.assertEqual(tech_section["table_count"], 1)
        self.assertEqual(image_artifacts[0]["caption"], "APOLLO 设备外观")
        self.assertEqual(image_artifacts[0]["source_heading"], "技术参数")
        self.assertEqual(image_artifacts[0]["page"], 1)
        self.assertIn("控制面板", image_artifacts[0]["context"])
        self.assertEqual(table_artifacts[0]["source_heading"], "技术参数")
        self.assertEqual(table_artifacts[0]["header_preview"], ["型号", "精度", "尺寸"])
        self.assertEqual(table_artifacts[0]["page"], 1)
        self.assertTrue(any(item["reason"] == "page_boundary" and item["page"] == 2 for item in preferred_boundaries))
        self.assertTrue(any(item["reason"] == "chunk_marker_boundary" for item in preferred_boundaries))
        self.assertTrue(any(item["term"] == "技术参数" for item in keywords))
        self.assertTrue(any(item["term"] == "选型" and "deterministic_template" in item["source"] for item in keywords))
        self.assertTrue(any(item["type"] == "product_spec_lookup" for item in questions))
        self.assertTrue(any(item["value"] == "1200 mm" and item["page"] == 1 for item in numeric))
        self.assertEqual(retrieval_hints["document_type_signals"][0]["document_type"], "zh_product_catalog")
        self.assertEqual(retrieval_hints["layout_sidecars"][0]["status"], "loaded")
        self.assertTrue(any(item.get("text") == "APOLLO 产品目录" for item in retrieval_hints["layout_signals"]))
        self.assertIn("product_spec_lookup", topology_starter_types)
        self.assertIn("visual_fact", topology_starter_types)
        self.assertIn("exact_numeric_fact", topology_starter_types)
        self.assertIn("ocr_image_fact", assistant_stages)
        self.assertIn("exact_numeric_fact", assistant_stages)
        self.assertIn("paraphrase", assistant_stages)

    def test_html_table_hints_feed_topology_and_assistant_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            source = root / "apollo-html.pdf"
            markdown = documents / "apollo-html.md"
            source.write_bytes(b"%PDF fake")
            markdown.write_text(
                "<!-- page: 1 -->\n"
                "# APOLLO 产品目录\n\n"
                "APOLLO 传感器产品用于高精度选型。\n\n"
                "## 技术参数\n\n"
                "下表列出 APOLLO-H 系列规格参数。\n\n"
                "<table>\n"
                "<caption>APOLLO-H 规格参数</caption>\n"
                "<thead><tr><th>型号</th><th>精度</th><th>尺寸</th></tr></thead>\n"
                "<tbody><tr><td>APOLLO-H</td><td>0.01 mm</td><td>250 mm</td></tr></tbody>\n"
                "</table>\n\n"
                "APOLLO-H 适合紧凑安装和高精度测量。\n",
                encoding="utf-8",
            )
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [
                            {
                                "source_path": "apollo-html.pdf",
                                "markdown_path": "documents/apollo-html.md",
                                "sha256": "abc",
                                "title": "APOLLO 产品目录",
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

            create_rich_handoff_package(handoff_root=root)
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((root / "assistant_test_plan.json").read_text(encoding="utf-8"))
            assistant_profile = json.loads((root / "assistant_profile.json").read_text(encoding="utf-8"))
            topology_advice = create_kb_topology_advice(
                kb_name="kb:apollo-html",
                documents=[BuildDocument(markdown)],
                retrieval_hints_path=root / "retrieval_hints.json",
                future_growth="medium",
                min_documents=1,
                min_total_chars=100,
            )
            assistant_review = review_assistant_test_plan(
                assistant_test_plan,
                assistant_profile=assistant_profile,
                retrieval_hints=retrieval_hints,
            )

        tech_section = next(item for item in retrieval_hints["section_boundaries"] if item["title"] == "技术参数")
        table_artifacts = retrieval_hints["table_artifacts"]
        html_table = next(item for item in table_artifacts if item["source"] == "html_table")
        question_types = {item["type"] for item in retrieval_hints["question_candidates"]}
        topology_starter_types = {case["type"] for case in topology_advice["route_test_starters"]}
        assistant_stages = {case["stage"] for case in assistant_test_plan["cases"]}

        self.assertEqual(tech_section["table_count"], 1)
        self.assertEqual(tech_section["html_table_count"], 1)
        self.assertEqual(html_table["source_heading"], "技术参数")
        self.assertEqual(html_table["header_preview"], ["型号", "精度", "尺寸"])
        self.assertEqual(html_table["row_count"], 2)
        self.assertEqual(html_table["column_count"], 3)
        self.assertEqual(html_table["caption"], "APOLLO-H 规格参数")
        self.assertEqual(html_table["page"], 1)
        self.assertTrue(any(item["html_table_count"] == 1 for item in retrieval_hints["documents"]))
        self.assertIn("table_fact", question_types)
        self.assertIn("product_spec_lookup", question_types)
        self.assertIn("product_spec_lookup", topology_starter_types)
        self.assertEqual(topology_advice["signals"]["retrieval_hints"]["table_artifact_count"], 1)
        self.assertIn("exact_numeric_fact", assistant_stages)
        self.assertIn("paraphrase", assistant_stages)
        self.assertEqual(assistant_review["status"], "PASS")
        self.assertEqual(assistant_review["retrieval_hints_summary"]["table_artifact_count"], 1)

    def test_inspect_rich_handoff_reports_optional_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            images = documents / "images"
            images.mkdir(parents=True)
            (documents / "a.md").write_text("# A\n\n![chart](images/chart.png)\n", encoding="utf-8")
            (images / "chart.png").write_bytes(b"fake chart")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_gate": {"status": "PASS"},
                        "documents": [
                            {
                                "source_path": "a.md",
                                "markdown_path": "documents/a.md",
                                "assets": {"images": [{"path": "documents/images/chart.png"}]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            create_rich_handoff_package(handoff_root=root)
            (root / "postprocess_report.json").write_text(
                json.dumps({"schema": "doc_postprocess_report_v1"}),
                encoding="utf-8",
            )
            plan = make_ragflow_ingest_plan_payload(handoff_root=root)
            (root / "ragflow_ingest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (root / "ragflow_ingest_plan.yaml").write_text(
                'schema: "ragflow_ingest_plan_v1"\n',
                encoding="utf-8",
            )

            report = inspect_rich_handoff(handoff_root=root)
            markdown = render_handoff_inspection_markdown(report)

        self.assertEqual(report["document_count"], 1)
        self.assertTrue(report["sidecars"]["metadata"]["exists"])
        self.assertTrue(report["sidecars"]["retrieval_hints"]["exists"])
        self.assertTrue(report["sidecars"]["assistant_profile"]["exists"])
        self.assertTrue(report["sidecars"]["assistant_test_plan"]["exists"])
        self.assertEqual(report["ingestion_readiness"]["status"], "ready")
        self.assertTrue(report["ingestion_readiness"]["image_assets_ok"])
        self.assertEqual(report["assets"]["images"]["missing_image_count"], 0)
        self.assertTrue(report["sidecar_summary"]["rich_complete"])
        self.assertIn("RAGFlow Handoff Inspection", markdown)
        self.assertIn("Ingestion readiness", markdown)
        self.assertIn("metadata", markdown)
        self.assertIn("Retrieval hint sections", markdown)

    def test_inspect_rich_handoff_blocks_missing_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            (documents / "a.md").write_text("# A\n\n![missing](images/missing.png)\n", encoding="utf-8")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_gate": {"status": "PASS"},
                        "documents": [{"source_path": "a.md", "markdown_path": "documents/a.md"}],
                    }
                ),
                encoding="utf-8",
            )

            report = inspect_rich_handoff(handoff_root=root)

        self.assertEqual(report["ingestion_readiness"]["status"], "blocked")
        self.assertEqual(report["assets"]["images"]["missing_image_count"], 1)
        self.assertEqual(report["ingestion_readiness"]["issues"][0]["code"], "image_assets_missing")

    def test_make_ragflow_ingest_plan_is_non_secret_and_points_to_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            (documents / "a.md").write_text("# A\n\nBody\n", encoding="utf-8")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "handoff_mode": "formal_ingest",
                        "quality_report": "quality_report.json",
                        "quality_gate": {"status": "PASS"},
                        "documents": [{"source_path": "a.md", "markdown_path": "documents/a.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (root / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            package = create_rich_handoff_package(handoff_root=root)

            plan = make_ragflow_ingest_plan_payload(handoff_root=root, package_payload=package)

        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertEqual(plan["schema"], RAGFLOW_INGEST_PLAN_SCHEMA)
        self.assertEqual(plan["handoff"]["handoff_mode"], "formal_ingest")
        self.assertEqual(plan["handoff"]["doc_manifest"], "doc_manifest.json")
        self.assertEqual(plan["handoff"]["retrieval_hints"], "retrieval_hints.json")
        self.assertEqual(plan["quality_gate"]["status"], "PASS")
        self.assertEqual(plan["recommended_build"]["inspect_command"][0], "ragflow-kb-build")
        self.assertEqual(plan["recommended_build"]["dry_run_command"][0], "ragflow-kb-build")
        self.assertFalse(plan["safety"]["stores_api_credentials"])
        self.assertNotIn("api_key:", serialized)
        self.assertNotIn("base_url:", serialized)

    def test_load_ragflow_ingest_plan_reads_generated_yaml_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "ragflow_ingest_plan.yaml"
            plan_path.write_text(
                "\n".join(
                    [
                        'schema: "ragflow_ingest_plan_v1"',
                        "handoff:",
                        '  doc_manifest: "doc_manifest.json"',
                        '  retrieval_hints: "retrieval_hints.json"',
                        "recommended_build:",
                        '  command: "ragflow-kb-build"',
                        "  dry_run_command:",
                        '    - "ragflow-kb-build"',
                        '    - "--dry-run"',
                        "safety:",
                        "  stores_api_credentials: false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            plan = load_ragflow_ingest_plan(plan_path)

        self.assertEqual(plan["schema"], RAGFLOW_INGEST_PLAN_SCHEMA)
        self.assertEqual(plan["handoff"]["doc_manifest"], "doc_manifest.json")
        self.assertEqual(plan["recommended_build"]["dry_run_command"][1], "--dry-run")
        self.assertFalse(plan["safety"]["stores_api_credentials"])


if __name__ == "__main__":
    unittest.main()
