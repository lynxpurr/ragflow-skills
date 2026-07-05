from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.assistant_review import review_assistant_test_plan
from ragflow_skill_runtime.handoff import (
    ASSISTANT_PROFILE_SCHEMA,
    ASSISTANT_TEST_PLAN_SCHEMA,
    ASSET_SEMANTICS_SCHEMA,
    ARTIFACT_INDEX_SCHEMA,
    DOC_INGEST_READINESS_SCHEMA,
    DOCUMENT_METADATA_SCHEMA,
    FORMAL_HANDOFF_MANIFEST_SCHEMA,
    HANDOFF_PACKAGE_SCHEMA,
    HANDOFF_COMPARISON_SCHEMA,
    PROFILE_SUGGESTIONS_SCHEMA,
    RAGFLOW_INGEST_PLAN_SCHEMA,
    RETRIEVAL_HINTS_SCHEMA,
    create_rich_handoff_package,
    inspect_rich_handoff,
    load_ragflow_ingest_plan,
    make_doc_ingest_readiness_payload,
    make_formal_handoff_manifest_payload,
    make_handoff_comparison_payload,
    make_ragflow_ingest_plan_payload,
    render_doc_ingest_readiness_markdown,
    render_handoff_comparison_markdown,
    render_handoff_inspection_markdown,
    write_doc_ingest_readiness_report,
    write_formal_handoff_manifest,
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
            ingest_readiness = json.loads((root / "ingest_readiness_report.json").read_text(encoding="utf-8"))
            ingest_readiness_md = (root / "ingest_readiness_report.md").read_text(encoding="utf-8")
            formal_manifest = json.loads((root / "formal_handoff_manifest.json").read_text(encoding="utf-8"))
            readme = (root / "package_readme.md").read_text(encoding="utf-8")
            recomputed_formal_hash = make_formal_handoff_manifest_payload(handoff_root=root)["package_hash"]
            rewritten_formal_manifest = write_formal_handoff_manifest(handoff_root=root)

        self.assertEqual(package["schema"], HANDOFF_PACKAGE_SCHEMA)
        self.assertEqual(package["handoff_mode"], "formal_ingest")
        self.assertEqual(package["document_count"], 1)
        self.assertEqual(package["artifact_count"], 1)
        self.assertEqual(package["asset_semantic_count"], 1)
        self.assertEqual(package["ingest_readiness"], "ingest_readiness_report.json")
        self.assertEqual(package["ingest_readiness_status"], "ready_with_review")
        self.assertEqual(package["formal_handoff_manifest"], "formal_handoff_manifest.json")
        self.assertEqual(package["formal_handoff_manifest_schema"], FORMAL_HANDOFF_MANIFEST_SCHEMA)
        self.assertEqual(package["formal_handoff_package_hash"], formal_manifest["package_hash"])
        self.assertGreaterEqual(package["retrieval_hint_count"], 2)
        self.assertGreaterEqual(package["assistant_test_count"], 1)
        self.assertEqual(metadata["schema"], DOCUMENT_METADATA_SCHEMA)
        self.assertEqual(metadata["documents"][0]["markdown"]["path"], "documents/source.md")
        self.assertEqual(metadata["documents"][0]["source_inventory"]["source_format"], "md")
        self.assertEqual(metadata["documents"][0]["source_inventory"]["mime_hint"], "text/markdown")
        self.assertEqual(artifact_index["schema"], ARTIFACT_INDEX_SCHEMA)
        self.assertEqual(artifact_index["artifacts"][0]["path"], "documents/images/chart.jpg")
        self.assertEqual(artifact_index["asset_semantics"]["schema"], ASSET_SEMANTICS_SCHEMA)
        self.assertEqual(artifact_index["asset_semantics"]["summary"]["image_count"], 1)
        self.assertEqual(artifact_index["asset_semantics"]["images"][0]["bytes"], len(b"fake image bytes"))
        self.assertEqual(artifact_index["asset_semantics"]["images"][0]["semantic_kind"], "chart")
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
        self.assertEqual(ingest_readiness["schema"], DOC_INGEST_READINESS_SCHEMA)
        self.assertEqual(ingest_readiness["status"], "ready_with_review")
        self.assertIn("pipeline_sidecars_incomplete", {issue["code"] for issue in ingest_readiness["issues"]})
        self.assertEqual(formal_manifest["schema"], FORMAL_HANDOFF_MANIFEST_SCHEMA)
        self.assertEqual(formal_manifest["source_document_count"], 1)
        self.assertEqual(formal_manifest["schema_versions"]["metadata"], DOCUMENT_METADATA_SCHEMA)
        self.assertEqual(formal_manifest["schema_versions"]["artifact_index"], ARTIFACT_INDEX_SCHEMA)
        self.assertIn("documents/source.md", {item["path"] for item in formal_manifest["markdown_files"]})
        self.assertIn("documents/images/chart.jpg", {item["path"] for item in formal_manifest["image_assets"]})
        self.assertIn("inspect_handoff", {item["name"] for item in formal_manifest["downstream_command_suggestions"]})
        self.assertEqual(formal_manifest["safety"]["live_ragflow_mutation"], "not_performed")
        self.assertFalse(formal_manifest["safety"]["unsafe_sidecars"])
        self.assertEqual(recomputed_formal_hash, formal_manifest["package_hash"])
        self.assertEqual(rewritten_formal_manifest["package_hash"], formal_manifest["package_hash"])
        self.assertIn("RAGFlow Doc Ingest Readiness", ingest_readiness_md)
        self.assertIn("Handoff mode: `formal_ingest`", readme)
        self.assertIn("formal_handoff_manifest.json", readme)
        self.assertIn("document-level ingestion contract", readme)
        self.assertIn("ingest_readiness_report.json", readme)
        self.assertIn("ragflow-kb-build inspect-handoff", readme)
        self.assertIn("--dry-run", readme)

    def test_handoff_comparison_ignores_retained_intermediates_and_normalizes_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retained_parent = root / "ragflux-retained"
            retained = retained_parent / "ragflow_input"
            retained_images = retained / "images"
            retained_images.mkdir(parents=True)
            (retained_images / "chart.png").write_bytes(b"retained chart")
            (retained / "apollo.md").write_text(
                "# APOLLO Catalog\n\n"
                "<!-- chunk -->\n\n"
                "APOLLO accuracy is 4.0 um.\n\n"
                "![Chart](images/chart.png)\n\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 um |\n",
                encoding="utf-8",
            )
            (retained / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            (retained / "retrieval_hints.json").write_text(
                json.dumps(
                    {
                        "schema": RETRIEVAL_HINTS_SCHEMA,
                        "section_boundaries": [{"title": "APOLLO Catalog"}],
                        "preferred_boundaries": [{"reason": "chunk_marker_boundary"}],
                        "keyword_candidates": [{"term": "APOLLO"}],
                        "question_candidates": [{"question": "What is the accuracy?"}],
                        "table_artifacts": [{"source": "markdown_table"}],
                        "image_artifacts": [{"path": "images/chart.png"}],
                    }
                ),
                encoding="utf-8",
            )
            (retained / "ragflow_config.yaml").write_text("chunk_size: 512\n", encoding="utf-8")
            raw = retained / "raw" / "mineru"
            raw.mkdir(parents=True)
            (raw / "noise.md").write_text("# Noise\n\nThis should not be compared.\n", encoding="utf-8")
            (raw / "noise.png").write_bytes(b"duplicate image cache")

            replacement = root / "replacement"
            replacement_docs = replacement / "documents"
            replacement_images = replacement_docs / "assets"
            replacement_images.mkdir(parents=True)
            (replacement / "source.md").write_text("# Source\n", encoding="utf-8")
            (replacement_images / "chart-renamed.png").write_bytes(b"replacement chart")
            (replacement_docs / "apollo.md").write_text(
                "# APOLLO Catalog\n\n"
                "APOLLO accuracy is 4.0 um.\n\n"
                "![Chart](assets/chart-renamed.png)\n\n"
                "<!-- chunk -->\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 um |\n",
                encoding="utf-8",
            )
            (replacement / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "handoff_mode": "formal_ingest",
                        "quality_report": "quality_report.json",
                        "chunk_profile_report": "chunk_profile_report.json",
                        "quality_gate": {"status": "PASS"},
                        "documents": [
                            {
                                "source_path": "source.md",
                                "markdown_path": "documents/apollo.md",
                                "title": "APOLLO Catalog",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (replacement / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            create_rich_handoff_package(handoff_root=replacement)
            (replacement / "postprocess_report.json").write_text(
                json.dumps({"schema": "doc_postprocess_report_v1"}),
                encoding="utf-8",
            )
            (replacement / "chunk_profile_report.json").write_text(
                json.dumps({"schema": "ragflow_chunk_profile_report_v1", "summary": {"marker_count": 1}}),
                encoding="utf-8",
            )
            (replacement / "ragflow_ingest_plan.yaml").write_text(
                "\n".join(
                    [
                        'schema: "ragflow_ingest_plan_v1"',
                        "handoff:",
                        '  doc_manifest: "doc_manifest.json"',
                        "recommended_build:",
                        "  dry_run_command:",
                        '    - "ragflow-kb-build"',
                        '    - "--dry-run"',
                        "safety:",
                        "  stores_api_credentials: false",
                        "  stores_ragflow_endpoint: false",
                        "  stores_secret: false",
                        '  mutation_default: "dry_run_first"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = make_handoff_comparison_payload(
                retained_package=retained_parent,
                replacement_handoff=replacement,
            )
            markdown = render_handoff_comparison_markdown(report)

        static = report["static_comparison"]
        retained_summary = static["retained_package"]
        replacement_summary = static["replacement_handoff"]
        self.assertEqual(report["schema"], HANDOFF_COMPARISON_SCHEMA)
        self.assertEqual(retained_summary["effective_root"], "ragflow_input")
        self.assertEqual(retained_summary["markdown"]["markdown_file_count"], 1)
        self.assertEqual(retained_summary["images"]["local_image_file_count"], 1)
        self.assertGreaterEqual(retained_summary["scan"]["ignored_directory_count"], 1)
        self.assertEqual(replacement_summary["markdown"]["markdown_file_count"], 1)
        self.assertGreaterEqual(static["normalized_text"]["similarity"], 0.9)
        self.assertEqual(static["deltas"]["chunk_marker_count"], 0)
        self.assertFalse(report["live_evidence"]["paired_live_ab"]["executed"])
        self.assertEqual(report["live_evidence"]["paired_live_ab"]["status"], "not_run")
        self.assertEqual(report["safety"]["live_ragflow_mutation"], "not_performed")
        self.assertIn("strict_paired_live_ab_not_run", {item["code"] for item in static["observations"]})
        self.assertIn("RAGFlow Handoff Comparison", markdown)
        serialized = json.dumps(report, ensure_ascii=False) + markdown
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("noise.md", serialized)

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
                "- 安装前检查底座水平。\n"
                "- 维护前确认急停开关可用。\n\n"
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
            artifact_index = json.loads((root / "artifact_index.json").read_text(encoding="utf-8"))
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
        visual_case = next(case for case in assistant_test_plan["cases"] if case["stage"] == "ocr_image_fact")
        topology_starter_types = {case["type"] for case in topology_advice["route_test_starters"]}
        preferred_reasons = {item["reason"] for item in preferred_boundaries}
        asset_semantics = artifact_index["asset_semantics"]
        image_semantic = asset_semantics["images"][0]

        tech_section = next(item for item in sections if item["title"] == "技术参数")
        self.assertEqual(tech_section["page_start"], 1)
        self.assertEqual(tech_section["table_count"], 1)
        self.assertEqual(asset_semantics["schema"], ASSET_SEMANTICS_SCHEMA)
        self.assertEqual(asset_semantics["summary"]["image_count"], 1)
        self.assertEqual(image_semantic["caption"], "APOLLO 控制面板")
        self.assertEqual(image_semantic["alt_text"], "APOLLO 设备外观")
        self.assertEqual(image_semantic["source_heading"], "技术参数")
        self.assertEqual(image_semantic["page"], 1)
        self.assertEqual(image_semantic["semantic_kind"], "image")
        self.assertEqual(image_semantic["bytes"], len(b"fake image bytes"))
        self.assertFalse(image_semantic["rewrites_markdown"])
        self.assertTrue(image_semantic["semantic_alias"].endswith(".png"))
        self.assertIn("content_list.json", image_semantic["semantic_sources"])
        self.assertEqual(image_artifacts[0]["caption"], "APOLLO 控制面板")
        self.assertEqual(image_artifacts[0]["alt_text"], "APOLLO 设备外观")
        self.assertEqual(image_artifacts[0]["source_heading"], "技术参数")
        self.assertEqual(image_artifacts[0]["page"], 1)
        self.assertEqual(image_artifacts[0]["semantic_kind"], "image")
        self.assertEqual(retrieval_hints["asset_semantics"]["summary"]["image_count"], 1)
        self.assertIn("控制面板", image_artifacts[0]["context"])
        self.assertEqual(table_artifacts[0]["source_heading"], "技术参数")
        self.assertEqual(table_artifacts[0]["header_preview"], ["型号", "精度", "尺寸"])
        self.assertEqual(table_artifacts[0]["page"], 1)
        self.assertTrue(any(item["reason"] == "page_boundary" and item["page"] == 2 for item in preferred_boundaries))
        self.assertTrue(any(item["reason"] == "chunk_marker_boundary" for item in preferred_boundaries))
        self.assertIn("table_boundary", preferred_reasons)
        self.assertIn("image_boundary", preferred_reasons)
        self.assertIn("list_boundary", preferred_reasons)
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
        self.assertEqual(visual_case["source_image"], "documents/images/apollo.png")
        self.assertEqual(visual_case["source_caption"], "APOLLO 控制面板")
        self.assertEqual(visual_case["semantic_kind"], "image")
        self.assertIn("exact_numeric_fact", assistant_stages)
        self.assertIn("paraphrase", assistant_stages)

    def test_asset_semantics_excludes_remote_urls_and_original_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            images = documents / "images"
            images.mkdir(parents=True)
            markdown = documents / "public.md"
            image = images / "public.png"
            image.write_bytes(b"public image bytes")
            markdown.write_text(
                "# Public\n\n"
                "Diagram context for public review.\n"
                "![Public diagram](images/public.png)\n",
                encoding="utf-8",
            )
            (root / "content_list.json").write_text(
                json.dumps(
                    [
                        {
                            "type": "image",
                            "caption": "Public diagram",
                            "page": 3,
                            "path": "documents/images/public.png",
                            "url": "https://example.invalid/raw?token=secret",
                            "source_path": "/tmp/original-secret/public.png",
                        },
                        {
                            "type": "image",
                            "caption": "Ignored remote image",
                            "page": 4,
                            "path": "https://example.invalid/remote.png",
                        },
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
                        "documents": [
                            {
                                "source_path": "public.pdf",
                                "markdown_path": "documents/public.md",
                                "title": "Public",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            create_rich_handoff_package(handoff_root=root)
            artifact_index = json.loads((root / "artifact_index.json").read_text(encoding="utf-8"))
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))

        serialized = json.dumps(artifact_index["asset_semantics"], ensure_ascii=False)
        self.assertEqual(artifact_index["asset_semantics"]["summary"]["image_count"], 1)
        self.assertEqual(artifact_index["asset_semantics"]["images"][0]["caption"], "Public diagram")
        self.assertEqual(retrieval_hints["image_artifacts"][0]["caption"], "Public diagram")
        self.assertNotIn("https://", serialized)
        self.assertNotIn("/tmp/", serialized)
        self.assertNotIn("original-secret", serialized)
        self.assertNotIn("token=secret", serialized)

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
            profile_suggestions = json.loads((root / "profile_suggestions.json").read_text(encoding="utf-8"))
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
        table_profile = next(item for item in profile_suggestions["suggestions"] if item["id"] == "table-atomic-zh-4096")
        question_types = {item["type"] for item in retrieval_hints["question_candidates"]}
        topology_starter_types = {case["type"] for case in topology_advice["route_test_starters"]}
        assistant_stages = {case["stage"] for case in assistant_test_plan["cases"]}

        self.assertEqual(profile_suggestions["signals"]["html_table_count"], 1)
        self.assertEqual(table_profile["postprocess_profile"], "chunk-markers-dense")
        self.assertEqual(table_profile["parser_config"]["delimiter"], "`<!-- chunk -->`")
        self.assertEqual(table_profile["parser_config"]["chunk_token_num"], 4096)
        self.assertTrue(table_profile["avoid_children_delimiter"])
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

    def test_html_table_term_alias_candidates_are_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            markdown = documents / "apollo-alias.md"
            original_text = (
                "<!-- page: 1 -->\n"
                "# APOLLO 产品目录\n\n"
                "## 术语表\n\n"
                "<table>\n"
                "<caption>APOLLO 误差规格</caption>\n"
                "<thead><tr><th>型号</th><th>$MPE_E$</th><th>MPE<sub>P</sub></th></tr></thead>\n"
                "<tbody><tr><td>APOLLO-H</td><td>0.02 mm</td><td>0.03 mm</td></tr></tbody>\n"
                "</table>\n"
            )
            markdown.write_text(original_text, encoding="utf-8")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "apollo-alias.pdf",
                                "markdown_path": "documents/apollo-alias.md",
                                "title": "APOLLO 产品目录",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            create_rich_handoff_package(handoff_root=root)
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((root / "assistant_test_plan.json").read_text(encoding="utf-8"))
            inspect_report = inspect_rich_handoff(handoff_root=root)
            markdown_after = markdown.read_text(encoding="utf-8")

        candidates = retrieval_hints["table_term_alias_candidates"]
        by_source = {item["source_label"]: item for item in candidates}
        stages = {case["stage"] for case in assistant_test_plan["cases"]}

        self.assertEqual(markdown_after, original_text)
        self.assertIn("$MPE_E$", by_source)
        self.assertIn("MPE P", by_source)
        self.assertIn("MPEE", by_source["$MPE_E$"]["candidate_aliases"])
        self.assertIn("MPE_E", by_source["$MPE_E$"]["candidate_aliases"])
        self.assertIn("MPEP", by_source["MPE P"]["candidate_aliases"])
        self.assertIn("MPE_P", by_source["MPE P"]["candidate_aliases"])
        self.assertTrue(all(item["requires_review"] for item in candidates))
        self.assertTrue(all(item["rewrites_markdown"] is False for item in candidates))
        self.assertNotIn("table_term_alias_review", stages)
        self.assertEqual(
            inspect_report["ingestion_readiness"]["checks"]["retrieval_hints_richness"]["table_term_alias_candidate_count"],
            2,
        )

    def test_html_table_semantic_risks_flag_complex_merged_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir()
            markdown = documents / "apollo-risk.md"
            original_text = (
                "<!-- page: 1 -->\n"
                "# APOLLO 扭矩规格\n\n"
                "## HH 系列扭矩参数\n\n"
                "<table>\n"
                "<caption>HH-A / HH-B 扭矩参数</caption>\n"
                "<thead>\n"
                "<tr><th rowspan=\"2\">项目</th><th colspan=\"2\">HH-A</th><th colspan=\"2\">HH-B</th></tr>\n"
                "<tr><th>额定扭矩</th><th>峰值扭矩</th><th>额定扭矩</th><th>峰值扭矩</th></tr>\n"
                "</thead>\n"
                "<tbody><tr><td>输出</td><td>12 N·m</td><td>18 N·m</td><td>10 N·m</td><td>16 N·m</td></tr></tbody>\n"
                "</table>\n"
            )
            markdown.write_text(original_text, encoding="utf-8")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "apollo-risk.pdf",
                                "markdown_path": "documents/apollo-risk.md",
                                "title": "APOLLO 扭矩规格",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            create_rich_handoff_package(handoff_root=root)
            retrieval_hints = json.loads((root / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((root / "assistant_test_plan.json").read_text(encoding="utf-8"))
            assistant_profile = json.loads((root / "assistant_profile.json").read_text(encoding="utf-8"))
            inspect_report = inspect_rich_handoff(handoff_root=root)
            assistant_review = review_assistant_test_plan(
                assistant_test_plan,
                assistant_profile=assistant_profile,
                retrieval_hints=retrieval_hints,
            )
            markdown_after = markdown.read_text(encoding="utf-8")

        html_table = next(item for item in retrieval_hints["table_artifacts"] if item["source"] == "html_table")
        risk_codes = {item["code"] for item in html_table["semantic_risks"]}
        assistant_stages = {case["stage"] for case in assistant_test_plan["cases"]}
        table_case = next(case for case in assistant_test_plan["cases"] if case["stage"] == "table_structure_review")

        self.assertEqual(markdown_after, original_text)
        self.assertEqual(html_table["header_depth"], 2)
        self.assertEqual(html_table["rowspan_count"], 1)
        self.assertEqual(html_table["colspan_count"], 2)
        self.assertTrue(html_table["review_required"])
        self.assertGreaterEqual(html_table["semantic_risk_score"], 4)
        self.assertIn("multi_level_header_review", risk_codes)
        self.assertIn("merged_cells_review", risk_codes)
        self.assertIn("multi_model_header_review", risk_codes)
        self.assertIn("HH-A", html_table["model_label_candidates"])
        self.assertIn("HH-B", html_table["model_label_candidates"])
        self.assertIn("table_structure_review", assistant_stages)
        self.assertIn("multi_model_header_review", table_case["semantic_risk_codes"])
        self.assertIn("HH-A", table_case["model_label_candidates"])
        self.assertEqual(assistant_review["status"], "PASS")
        self.assertEqual(
            inspect_report["ingestion_readiness"]["checks"]["retrieval_hints_richness"]["table_semantic_risk_count"],
            len(html_table["semantic_risks"]),
        )

    def test_inspect_rich_handoff_reports_optional_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            images = documents / "images"
            images.mkdir(parents=True)
            (documents / "a.md").write_text(
                "# A\n\n"
                "<table><tr><th>型号</th><th>精度</th></tr><tr><td>A</td><td>1 um</td></tr></table>\n\n"
                "![chart](images/chart.png)\n",
                encoding="utf-8",
            )
            (images / "chart.png").write_bytes(b"fake chart")
            (root / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_gate": {"status": "PASS"},
                        "quality_report": "quality_report.json",
                        "chunk_profile_report": "chunk_profile_report.json",
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
            (root / "quality_report.json").write_text(
                json.dumps(
                    {
                        "schema": "doc_quality_report_v1",
                        "gate": {"status": "PASS"},
                        "documents": [
                            {
                                "markdown_path": "documents/a.md",
                                "image_count": 1,
                                "quality_signals": {
                                    "table_count": 1,
                                    "html_table_count": 1,
                                    "markdown_table_count": 0,
                                },
                                "issues": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            create_rich_handoff_package(handoff_root=root)
            (root / "postprocess_report.json").write_text(
                json.dumps(
                    {
                        "schema": "doc_postprocess_report_v1",
                        "chunk_profile_report": {
                            "schema": "ragflow_chunk_profile_report_v1",
                            "profile": "chunk-markers",
                            "summary": {"marker_count": 1, "warning_count": 0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "chunk_profile_report.json").write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_profile_report_v1",
                        "profile": "chunk-markers",
                        "summary": {"marker_count": 1, "warning_count": 0},
                    }
                ),
                encoding="utf-8",
            )
            plan = make_ragflow_ingest_plan_payload(handoff_root=root)
            (root / "ragflow_ingest_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (root / "ragflow_ingest_plan.yaml").write_text(
                "\n".join(
                    [
                        'schema: "ragflow_ingest_plan_v1"',
                        "handoff:",
                        '  doc_manifest: "doc_manifest.json"',
                        '  retrieval_hints: "retrieval_hints.json"',
                        "recommended_build:",
                        "  dry_run_command:",
                        '    - "ragflow-kb-build"',
                        '    - "--dry-run"',
                        "safety:",
                        "  stores_api_credentials: false",
                        "  stores_ragflow_endpoint: false",
                        "  stores_secret: false",
                        '  mutation_default: "dry_run_first"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            write_doc_ingest_readiness_report(handoff_root=root)

            report = inspect_rich_handoff(handoff_root=root)
            markdown = render_handoff_inspection_markdown(report)

        self.assertEqual(report["document_count"], 1)
        self.assertTrue(report["sidecars"]["metadata"]["exists"])
        self.assertTrue(report["sidecars"]["retrieval_hints"]["exists"])
        self.assertTrue(report["sidecars"]["assistant_profile"]["exists"])
        self.assertTrue(report["sidecars"]["assistant_test_plan"]["exists"])
        self.assertTrue(report["sidecars"]["ingest_readiness_report"]["exists"])
        self.assertTrue(report["sidecars"]["chunk_profile_report"]["exists"])
        self.assertEqual(report["ingestion_readiness"]["status"], "ready")
        self.assertTrue(report["ingest_readiness_report"]["matches_recomputed_status"])
        self.assertTrue(report["ingestion_readiness"]["image_assets_ok"])
        self.assertEqual(report["assets"]["images"]["missing_image_count"], 0)
        self.assertTrue(report["sidecar_summary"]["rich_complete"])
        self.assertEqual(report["ingestion_readiness"]["checks"]["quality_gate"]["summary"]["table_count"], 1)
        self.assertEqual(report["ingestion_readiness"]["checks"]["quality_gate"]["summary"]["html_table_count"], 1)
        self.assertEqual(report["ingestion_readiness"]["checks"]["artifact_coverage"]["quality_table_count"], 1)
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
            readiness = make_doc_ingest_readiness_payload(handoff_root=root)
            readiness_md = render_doc_ingest_readiness_markdown(readiness)

        self.assertEqual(report["ingestion_readiness"]["status"], "blocked")
        self.assertEqual(report["assets"]["images"]["missing_image_count"], 1)
        self.assertEqual(report["ingestion_readiness"]["issues"][0]["code"], "image_assets_missing")
        self.assertEqual(readiness["schema"], DOC_INGEST_READINESS_SCHEMA)
        self.assertEqual(readiness["status"], "blocked")
        self.assertEqual(readiness["checks"]["local_assets"]["missing_image_count"], 1)
        self.assertIn("image_assets_missing", readiness_md)

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
                        "chunk_profile_report": "chunk_profile_report.json",
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
            (root / "chunk_profile_report.json").write_text(
                json.dumps({"schema": "ragflow_chunk_profile_report_v1"}),
                encoding="utf-8",
            )
            package = create_rich_handoff_package(handoff_root=root)

            plan = make_ragflow_ingest_plan_payload(handoff_root=root, package_payload=package)

        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertEqual(plan["schema"], RAGFLOW_INGEST_PLAN_SCHEMA)
        self.assertEqual(plan["handoff"]["handoff_mode"], "formal_ingest")
        self.assertEqual(plan["handoff"]["doc_manifest"], "doc_manifest.json")
        self.assertEqual(plan["handoff"]["retrieval_hints"], "retrieval_hints.json")
        self.assertEqual(plan["handoff"]["chunk_profile_report"], "chunk_profile_report.json")
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
