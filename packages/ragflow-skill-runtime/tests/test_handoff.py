from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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

        self.assertEqual(package["schema"], HANDOFF_PACKAGE_SCHEMA)
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
        self.assertEqual(plan["handoff"]["doc_manifest"], "doc_manifest.json")
        self.assertEqual(plan["handoff"]["retrieval_hints"], "retrieval_hints.json")
        self.assertEqual(plan["quality_gate"]["status"], "PASS")
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
