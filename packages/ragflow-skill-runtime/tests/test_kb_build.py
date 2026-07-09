from __future__ import annotations

import json
import unittest
from pathlib import Path
import tempfile
import zipfile

from ragflow_skill_runtime.kb_build import (
    BuildError,
    BuildDocument,
    KB_ASSET_UPLOAD_PLAN_SCHEMA,
    BUILD_PAYLOAD_PREVIEW_SCHEMA,
    HANDOFF_CONSUMPTION_STATUS_SCHEMA,
    PARAMETER_MATERIALIZATION_INVENTORY_SCHEMA,
    PARAMETER_READ_BACK_AUDIT_SCHEMA,
    MULTIMODAL_KB_MANIFEST_SCHEMA,
    create_kb_asset_upload_plan,
    discover_markdown_documents,
    extract_document_states,
    extract_dataset_id,
    extract_document_id,
    extract_document_items,
    extract_document_name,
    extract_uploaded_document_id,
    make_handoff_consumption_status,
    make_build_payload_preview,
    make_kb_manifest_payload,
    make_multimodal_kb_manifest_payload,
    make_parameter_materialization_inventory,
    create_parameter_read_back_audit,
    normalize_document_state,
    write_kb_asset_upload_zip,
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

    def test_create_kb_asset_upload_plan_reports_images_and_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            image_dir = handoff / "documents" / "images"
            image_dir.mkdir(parents=True)
            (handoff / "documents" / "sample.md").write_text(
                "# Sample\n\n![ok](images/ok.png)\n![missing](images/missing.png)\n![remote](https://example.test/a.png)\n",
                encoding="utf-8",
            )
            (image_dir / "ok.png").write_bytes(b"ok-image")
            (image_dir / "orphan.png").write_bytes(b"orphan-image")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [
                            {
                                "source_path": "sample.pdf",
                                "markdown_path": "documents/sample.md",
                                "assets": {"images": [{"path": "documents/images/ok.png"}]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )

            plan = create_kb_asset_upload_plan(doc_manifest_path=manifest)

        self.assertEqual(plan["schema"], KB_ASSET_UPLOAD_PLAN_SCHEMA)
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(plan["offline_only"])
        self.assertFalse(plan["live_upload_enabled"])
        self.assertEqual(plan["ragflow_calls"], 0)
        self.assertEqual(plan["summary"]["planned_image_file_count"], 1)
        self.assertEqual(plan["summary"]["markdown_image_reference_count"], 2)
        self.assertEqual(plan["summary"]["discovered_image_artifact_count"], 3)
        self.assertEqual(plan["summary"]["missing_image_count"], 1)
        self.assertEqual(plan["summary"]["missing_image_asset_count"], 1)
        self.assertEqual(plan["summary"]["orphan_image_count"], 1)
        self.assertEqual(plan["summary"]["unreferenced_handoff_image_count"], 1)
        self.assertEqual(plan["summary"]["remote_image_reference_count"], 1)
        self.assertGreaterEqual(plan["summary"]["sidecar_file_count"], 2)
        self.assertIn("image_missing", {issue["code"] for issue in plan["issues"]})
        self.assertIn("orphan_images_detected", {issue["code"] for issue in plan["issues"]})

    def test_asset_upload_plan_v2_separates_discovered_images_from_planned_upload_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            image_dir = handoff / "documents" / "images"
            sidecar_dir = handoff / "artifacts" / "images"
            residual_dir = handoff / "images"
            outside_dir = Path(tmp) / "outside"
            image_dir.mkdir(parents=True)
            sidecar_dir.mkdir(parents=True)
            residual_dir.mkdir(parents=True)
            outside_dir.mkdir()
            markdown = handoff / "documents" / "sample.md"
            markdown.write_text(
                "# Sample\n\n"
                "![referenced](images/ref.png)\n"
                "![missing](images/missing.png)\n"
                "![outside](../../outside/outside.png)\n",
                encoding="utf-8",
            )
            (image_dir / "ref.png").write_bytes(b"referenced")
            (image_dir / "manifest-only.png").write_bytes(b"manifest")
            (sidecar_dir / "sidecar.png").write_bytes(b"sidecar")
            (residual_dir / "residual.png").write_bytes(b"residual")
            (outside_dir / "outside.png").write_bytes(b"outside")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "sample.pdf",
                                "markdown_path": "documents/sample.md",
                                "assets": {"images": [{"path": "documents/images/manifest-only.png"}]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "artifact_index.json").write_text(
                json.dumps(
                    {
                        "schema": "ragflow_artifact_index_v1",
                        "artifacts": [{"path": "artifacts/images/sidecar.png", "type": "image"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = create_kb_asset_upload_plan(doc_manifest_path=manifest)

        self.assertEqual(plan["schema"], "ragflow_kb_asset_upload_plan_v2")
        self.assertEqual(plan["summary"]["markdown_referenced_image_count"], 1)
        self.assertEqual(plan["summary"]["manifest_listed_image_count"], 1)
        self.assertEqual(plan["summary"]["sidecar_referenced_image_count"], 1)
        self.assertEqual(plan["summary"]["residual_unreferenced_image_count"], 1)
        self.assertEqual(plan["summary"]["outside_handoff_image_count"], 1)
        self.assertEqual(plan["summary"]["missing_image_count"], 1)
        self.assertEqual(plan["summary"]["discovered_image_artifact_count"], 6)
        self.assertEqual(plan["summary"]["planned_visual_upload_file_count"], 1)
        self.assertEqual(
            {item["asset_class"] for item in plan["discovered_image_artifacts"]},
            {
                "markdown_referenced",
                "manifest_listed",
                "sidecar_referenced",
                "residual_unreferenced",
                "outside_handoff",
                "missing",
            },
        )
        self.assertEqual(
            [item["source_path"] for item in plan["planned_visual_upload_files"]],
            ["documents/images/ref.png"],
        )
        self.assertNotIn(
            "documents/images/manifest-only.png",
            {item["source_path"] for item in plan["planned_visual_upload_files"]},
        )

    def test_asset_upload_plan_resolves_sidecar_images_under_documents_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            image_dir = handoff / "documents" / "images"
            image_dir.mkdir(parents=True)
            (handoff / "documents" / "sample.md").write_text("# Sample\n\nNo inline images.\n", encoding="utf-8")
            (image_dir / "sidecar-only.png").write_bytes(b"sidecar")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "sample.pdf", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "artifact_index.json").write_text(
                json.dumps(
                    {
                        "schema": "ragflow_artifact_index_v1",
                        "artifacts": [{"path": "images/sidecar-only.png", "type": "image"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = create_kb_asset_upload_plan(doc_manifest_path=manifest)

        self.assertEqual(plan["summary"]["sidecar_referenced_image_count"], 1)
        self.assertEqual(plan["summary"]["missing_image_count"], 0)
        self.assertNotIn("image_missing", {issue["code"] for issue in plan["issues"]})
        self.assertIn(
            "documents/images/sidecar-only.png",
            {item["source_path"] for item in plan["discovered_image_artifacts"]},
        )

    def test_asset_upload_plan_classifies_apollo_style_referenced_and_residual_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            image_dir = handoff / "documents" / "images"
            residual_dir = handoff / "artifacts" / "images"
            image_dir.mkdir(parents=True)
            residual_dir.mkdir(parents=True)
            refs = []
            for index in range(15):
                name = f"page-{index:02d}.png"
                refs.append(name)
                (image_dir / name).write_bytes(f"referenced-{index}".encode("utf-8"))
            for index in range(6):
                (residual_dir / f"{index:064x}.png").write_bytes(f"residual-{index}".encode("utf-8"))
            markdown = handoff / "documents" / "sample.md"
            markdown.write_text(
                "# APOLLO\n\n" + "\n".join(f"![page {index}](images/{name})" for index, name in enumerate(refs)),
                encoding="utf-8",
            )
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "apollo.pdf", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = create_kb_asset_upload_plan(doc_manifest_path=manifest)

        self.assertEqual(plan["status"], "ready_with_review")
        self.assertEqual(plan["summary"]["markdown_referenced_image_count"], 15)
        self.assertEqual(plan["summary"]["residual_unreferenced_image_count"], 6)
        self.assertEqual(plan["summary"]["planned_visual_upload_file_count"], 15)
        self.assertIn("residual_images_detected", {issue["code"] for issue in plan["issues"]})
        self.assertIn("residual_images_likely_hash_named", {issue["code"] for issue in plan["issues"]})

    def test_write_kb_asset_upload_zip_contains_projected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            image_dir = handoff / "documents" / "images"
            image_dir.mkdir(parents=True)
            (handoff / "documents" / "sample.md").write_text("# Sample\n\n![ok](images/ok.png)\n", encoding="utf-8")
            (image_dir / "ok.png").write_bytes(b"ok-image")
            (handoff / "metadata.json").write_text(json.dumps({"schema": "ragflow_document_metadata_v1"}), encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "sample.pdf", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            plan = create_kb_asset_upload_plan(doc_manifest_path=manifest)
            zip_path = Path(tmp) / "asset-package.zip"
            zip_record = write_kb_asset_upload_zip(plan, output_path=zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(zip_record["file_count"], plan["summary"]["projected_upload_file_count"])
        self.assertIn("documents/sample.md", names)
        self.assertIn("documents/images/ok.png", names)
        self.assertIn("doc_manifest.json", names)
        self.assertIn("metadata.json", names)

    def test_extract_dataset_id_from_nested_response(self) -> None:
        self.assertEqual(extract_dataset_id({"data": {"id": "ds-1"}}), "ds-1")

    def test_extract_uploaded_document_id_from_list_response(self) -> None:
        self.assertEqual(extract_uploaded_document_id({"data": [{"id": "doc-1"}]}), "doc-1")

    def test_extract_document_items_names_and_ids(self) -> None:
        items = extract_document_items(
            {
                "data": {
                    "items": [
                        {"id": "doc-1", "name": "a.md"},
                        {"document_id": "doc-2", "docnm_kwd": "b.md"},
                    ]
                }
            }
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(extract_document_id(items[0]), "doc-1")
        self.assertEqual(extract_document_name(items[1]), "b.md")

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

    def test_build_payload_preview_separates_sent_local_only_and_advisory_fields(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "table-atomic-zh-2048",
                "language": "Chinese",
                "chunk_size": 2048,
                "chunk_overlap": 0,
                "parser_config": {
                    "chunk_token_num": 2048,
                    "delimiter": "`<!-- chunk -->`",
                    "auto_keywords": 1,
                    "auto_questions": 0,
                    "__language__": "Chinese",
                },
            }
        )

        preview = make_build_payload_preview(
            kb_name="kb:test",
            profile=profile,
            retrieval_hints={
                "schema": "ragflow_retrieval_hints_v1",
                "keyword_candidates": ["apollo", "ontology"],
                "question_candidates": ["What changed?"],
                "image_artifacts": [{"path": "images/page.png"}],
            },
            ragflow_ingest_plan={
                "schema": "ragflow_ingest_plan_v1",
                "recommended_build": {"parser_profile": {"language": "zh"}},
            },
        )
        fields = {item["field"]: item for item in preview["fields"]}

        self.assertEqual(preview["schema"], BUILD_PAYLOAD_PREVIEW_SCHEMA)
        self.assertEqual(preview["dataset_create_payload"]["language"], "Chinese")
        self.assertEqual(fields["language"]["status"], "materialized_to_ragflow")
        self.assertEqual(fields["parser_config.delimiter"]["status"], "materialized_to_ragflow")
        self.assertEqual(fields["parser_config.__language__"]["status"], "local_audit_only")
        self.assertEqual(fields["chunk_overlap"]["status"], "local_audit_only")
        self.assertEqual(fields["retrieval_hints.keyword_candidates"]["status"], "advisory_after_build")
        self.assertEqual(fields["retrieval_hints.question_candidates"]["status"], "advisory_after_build")
        self.assertEqual(preview["summary"]["ragflow_field_count"], 6)
        self.assertEqual(preview["summary"]["retrieval_hint_keyword_candidate_count"], 2)

    def test_parameter_materialization_inventory_classifies_sidecars_and_ui_controls(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "delimiter-en-768",
                "chunk_size": 768,
                "chunk_overlap": 64,
                "parser_config": {
                    "chunk_token_num": 768,
                    "delimiter": "`<!-- chunk -->`",
                    "auto_keywords": 0,
                    "auto_questions": 1,
                    "__language__": "English",
                },
            }
        )

        inventory = make_parameter_materialization_inventory(
            profile=profile,
            profile_suggestions={
                "schema": "ragflow_profile_suggestions_v1",
                "suggestions": [
                    {
                        "id": "table-atomic",
                        "parser_config": {
                            "chunk_token_num": 1024,
                            "delimiter": "`<!-- chunk -->`",
                        },
                    }
                ],
            },
            retrieval_hints={
                "schema": "ragflow_retrieval_hints_v1",
                "keyword_candidates": [{"term": "tsn"}],
                "question_candidates": [{"question": "What changed?"}],
                "image_artifacts": [{"path": "images/page.png"}],
                "table_artifacts": [{"path": "artifacts/tables/table.md"}],
            },
            ragflow_ingest_plan={
                "schema": "ragflow_ingest_plan_v1",
                "recommended_build": {
                    "parser_profile": {
                        "language": "en",
                        "postprocess_profile": "chunk-markers-dense",
                    }
                },
            },
            metadata={"schema": "ragflow_document_metadata_v1", "documents": []},
        )
        by_field = {item["field"]: item for item in inventory["fields"]}

        self.assertEqual(inventory["schema"], PARAMETER_MATERIALIZATION_INVENTORY_SCHEMA)
        self.assertIn("unknown_api_mapping", inventory["status_values"])
        self.assertIn("native_parser_only", inventory["status_values"])
        self.assertEqual(
            by_field["profile.parser_config.chunk_token_num"]["status"],
            "materialized_to_ragflow",
        )
        self.assertEqual(
            by_field["profile.parser_config.delimiter"]["parser_path_scope"],
            "markdown_handoff",
        )
        self.assertEqual(
            by_field["profile.chunk_overlap"]["status"],
            "local_audit_only",
        )
        self.assertEqual(
            by_field["profile_suggestions.suggestions[].parser_config.delimiter"]["status"],
            "advisory_after_build",
        )
        self.assertEqual(
            by_field["retrieval_hints.keyword_candidates"]["status"],
            "advisory_after_build",
        )
        self.assertEqual(
            by_field["retrieval_hints.image_artifacts"]["status"],
            "unsupported_or_gated",
        )
        self.assertEqual(
            by_field["ragflow_ingest_plan.recommended_build.parser_profile.language"]["status"],
            "materialized_to_ragflow",
        )
        self.assertEqual(by_field["metadata.json"]["status"], "local_audit_only")
        self.assertEqual(by_field["ragflow_ui.page_index"]["status"], "unknown_api_mapping")
        self.assertEqual(by_field["ragflow_ui.table_to_html"]["status"], "native_parser_only")
        self.assertEqual(by_field["ragflow_ui.table_to_html"]["parser_path_scope"], "deepdoc_native")
        self.assertEqual(inventory["safety"]["ragflow_calls"], 0)
        self.assertFalse(inventory["safety"]["writes_live_ragflow"])

    def test_parameter_read_back_audit_compares_requested_observed_and_ui_controls(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "delimiter-en-768",
                "chunk_size": 768,
                "chunk_method": "naive",
                "parser_config": {
                    "chunk_token_num": 768,
                    "delimiter": "<!-- chunk -->",
                    "auto_questions": 1,
                },
                "language": "en",
            }
        )
        preview = make_build_payload_preview(kb_name="kb:private-name", profile=profile)
        inventory = make_parameter_materialization_inventory(profile=profile)
        dry_run = {
            "schema": "ragflow_kb_build_dry_run_v1",
            "build_payload_preview": preview,
            "parameter_materialization_inventory": inventory,
        }
        observed_state = {
            "schema": "ragflow_observed_fixture_v1",
            "data": {
                "parser_config": {
                    "chunk_token_num": 768,
                    "delimiter": "\n\n",
                    "auto_keywords": 0,
                },
                "language": "en",
            },
        }

        audit = create_parameter_read_back_audit(dry_run_report=dry_run, observed_state=observed_state)

        self.assertEqual(audit["schema"], PARAMETER_READ_BACK_AUDIT_SCHEMA)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["status"], "REVIEW")
        self.assertTrue(audit["advisory_only"])
        self.assertEqual(audit["mutation"], "none")
        self.assertEqual(audit["observed_state"]["parser_config_source"], "observed_state.data.parser_config")
        self.assertEqual(audit["summary"]["observed_match_count"], 3)
        self.assertEqual(audit["summary"]["observed_changed_count"], 1)
        self.assertEqual(audit["summary"]["observed_missing_count"], 1)
        self.assertEqual(audit["summary"]["unknown_api_mapping_count"], 5)
        self.assertEqual(audit["summary"]["native_parser_only_count"], 1)
        by_field = {item["field"]: item for item in audit["fields"]}
        self.assertEqual(by_field["dataset.language"]["audit_status"], "observed_match")
        self.assertEqual(by_field["dataset.parser_config.chunk_token_num"]["audit_status"], "observed_match")
        self.assertEqual(by_field["dataset.parser_config.delimiter"]["audit_status"], "observed_changed")
        self.assertEqual(by_field["dataset.parser_config.delimiter"]["requested_value"], "<!-- chunk -->")
        self.assertEqual(by_field["dataset.parser_config.delimiter"]["observed_value"], "\n\n")
        self.assertEqual(by_field["dataset.parser_config.auto_questions"]["audit_status"], "observed_missing")
        self.assertEqual(by_field["ragflow_ui.page_index"]["audit_status"], "unknown_api_mapping")
        self.assertEqual(by_field["ragflow_ui.page_index"]["ui_label"], "PageIndex")
        self.assertEqual(by_field["ragflow_ui.table_to_html"]["audit_status"], "native_parser_only")
        self.assertEqual(audit["safety"]["ragflow_calls"], 0)
        self.assertFalse(audit["safety"]["writes_live_ragflow"])
        self.assertFalse(audit["safety"]["raw_chunks_included"])

    def test_handoff_consumption_status_classifies_core_sidecars_assets_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            docs_dir = handoff / "documents"
            image_dir = docs_dir / "images"
            table_dir = handoff / "artifacts" / "tables"
            image_dir.mkdir(parents=True)
            table_dir.mkdir(parents=True)
            markdown = docs_dir / "sample.md"
            markdown.write_text("# Sample\n\n![diagram](images/diagram.png)\n", encoding="utf-8")
            (image_dir / "diagram.png").write_bytes(b"image")
            (table_dir / "sample.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [{"source_path": "source.pdf", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            (handoff / "metadata.json").write_text(
                json.dumps({"schema": "ragflow_metadata_v1", "documents": []}),
                encoding="utf-8",
            )
            (handoff / "profile_suggestions.json").write_text(
                json.dumps(
                    {
                        "schema": "ragflow_profile_suggestions_v1",
                        "suggestions": [
                            {
                                "id": "table-atomic-zh-4096",
                                "parser_config": {"chunk_token_num": 4096, "delimiter": "`<!-- chunk -->`"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints = {
                "schema": "ragflow_retrieval_hints_v1",
                "keyword_candidates": [{"term": "sample"}],
                "question_candidates": [{"question": "What is sample?"}],
                "image_artifacts": [{"path": "images/diagram.png"}],
                "table_artifacts": [{"path": "artifacts/tables/sample.csv", "document": "documents/sample.md"}],
            }
            (handoff / "retrieval_hints.json").write_text(json.dumps(retrieval_hints), encoding="utf-8")
            (handoff / "assistant_profile.json").write_text(
                json.dumps({"schema": "ragflow_assistant_profile_v1", "profile_id": "review"}),
                encoding="utf-8",
            )
            ingest_plan = {
                "schema": "ragflow_ingest_plan_v1",
                "recommended_build": {"parser_profile": {"language": "zh"}},
            }
            (handoff / "ragflow_ingest_plan.json").write_text(json.dumps(ingest_plan), encoding="utf-8")

            report = make_handoff_consumption_status(
                doc_manifest_path=manifest,
                documents=[BuildDocument(path=markdown, manifest_source_path="source.pdf")],
                metadata_path=handoff / "metadata.json",
                retrieval_hints=retrieval_hints,
                retrieval_hints_path=handoff / "retrieval_hints.json",
                ragflow_ingest_plan=ingest_plan,
                ragflow_ingest_plan_path=handoff / "ragflow_ingest_plan.json",
            )

        self.assertEqual(report["schema"], HANDOFF_CONSUMPTION_STATUS_SCHEMA)
        by_artifact = {item["artifact"]: item for item in report["artifacts"]}
        self.assertEqual(by_artifact["doc_manifest.json"]["status"], "materialized_to_manifest")
        self.assertEqual(by_artifact["documents/sample.md"]["status"], "materialized_to_ragflow")
        self.assertEqual(by_artifact["quality_report.json"]["status"], "local_audit_only")
        self.assertEqual(by_artifact["profile_suggestions.json"]["status"], "advisory_after_build")
        self.assertEqual(by_artifact["retrieval_hints.json"]["status"], "advisory_after_build")
        self.assertEqual(by_artifact["metadata.json"]["status"], "materialized_to_manifest")
        self.assertEqual(by_artifact["assistant_profile.json"]["status"], "advisory_after_build")
        self.assertEqual(by_artifact["ragflow_ingest_plan.json"]["status"], "materialized_to_ragflow")
        image_record = next(item for item in report["artifacts"] if item["kind"] == "image_asset")
        table_record = next(item for item in report["artifacts"] if item["kind"] == "table_artifact")
        self.assertEqual(image_record["status"], "unsupported_or_gated")
        self.assertEqual(table_record["status"], "local_audit_only")
        self.assertEqual(report["summary"]["status_counts"]["advisory_after_build"], 3)
        self.assertEqual(report["summary"]["image_asset_count"], 1)
        self.assertEqual(report["summary"]["table_artifact_count"], 1)

    def test_make_multimodal_kb_manifest_links_markdown_visuals_and_observed_state(self) -> None:
        profile = ChunkProfile.from_dict({"profile_id": "default-zh-1024", "chunk_size": 1024})
        payload = make_multimodal_kb_manifest_payload(
            base_url="https://ragflow.example.test/api/v1",
            dataset_id="ds-visual",
            dataset_name="visual-fixture",
            profile=profile,
            markdown_documents=[
                (
                    BuildDocument(path=Path("documents/source.md"), manifest_source_path="source.pdf"),
                    "doc-md",
                    "DONE",
                    7,
                )
            ],
            asset_upload_plan={
                "schema": "ragflow_kb_asset_upload_plan_v2",
                "planned_visual_upload_files": [
                    {
                        "source_path": "documents/images/page-00.png",
                        "package_path": "documents/images/page-00.png",
                        "asset_class": "markdown_referenced",
                        "sha256": "abc123",
                        "mime_type": "image/png",
                    }
                ],
            },
            document_list_response={
                "data": {
                    "items": [
                        {
                            "id": "doc-md",
                            "name": "source.md",
                            "run": "DONE",
                            "chunk_count": 7,
                            "mime_type": "text/markdown",
                        },
                        {
                            "id": "doc-image",
                            "name": "page-00.png",
                            "run": "DONE",
                            "chunk_count": 2,
                            "mime_type": "image/png",
                            "thumbnail_url": "thumbnails/page-00.png",
                            "vlm_status": "completed",
                        },
                    ]
                }
            },
        )

        self.assertEqual(payload["schema"], MULTIMODAL_KB_MANIFEST_SCHEMA)
        self.assertEqual(payload["summary"]["markdown_document_count"], 1)
        self.assertEqual(payload["summary"]["visual_document_count"], 1)
        self.assertEqual(payload["summary"]["thumbnail_document_count"], 1)
        self.assertEqual(payload["summary"]["vlm_observed_document_count"], 1)
        visual = payload["visual_documents"][0]
        self.assertEqual(visual["document_id"], "doc-image")
        self.assertEqual(visual["source_path"], "documents/images/page-00.png")
        self.assertEqual(visual["asset_class"], "markdown_referenced")
        self.assertEqual(visual["sha256"], "abc123")
        self.assertEqual(visual["status"], "done")
        self.assertEqual(visual["chunk_count"], 2)
        self.assertEqual(visual["thumbnail"]["url"], "thumbnails/page-00.png")
        self.assertEqual(visual["vlm_status"], "completed")

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

    def test_extract_document_states_preserves_visual_document_observations(self) -> None:
        states = extract_document_states(
            {
                "data": {
                    "docs": [
                        {
                            "id": "img-1",
                            "name": "figure.png",
                            "run": "DONE",
                            "chunk_count": "3",
                            "mime_type": "image/png",
                            "thumbnail_url": "thumbs/figure.png",
                            "vlm_status": "completed",
                        },
                        "malformed",
                        {"id": "", "name": "missing-id.png"},
                    ]
                }
            }
        )

        self.assertEqual(set(states), {"img-1"})
        self.assertEqual(states["img-1"]["document_kind"], "image")
        self.assertEqual(states["img-1"]["name"], "figure.png")
        self.assertEqual(states["img-1"]["chunk_count"], 3)
        self.assertEqual(states["img-1"]["thumbnail"]["url"], "thumbs/figure.png")
        self.assertEqual(states["img-1"]["vlm_status"], "completed")
        self.assertEqual(extract_document_states({"data": {"items": "not-a-list"}}), {})

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
