from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.metadata_governance import (
    RAGFLOW_METADATA_SCHEMA,
    RAGFLOW_TAGSET_SCHEMA,
    SEGMENT_METADATA_REPORT_SCHEMA,
    export_tagset_payload,
    lint_metadata_payload,
    lint_tagset_payload,
    make_metadata_template_payload,
    make_tagset_template_payload,
    merge_metadata_payloads,
    segment_metadata_report_file,
    tagset_report_payload,
)


class MetadataGovernanceTests(unittest.TestCase):
    def test_metadata_lint_accepts_safe_public_fields(self) -> None:
        report = lint_metadata_payload(
            {
                "schema": RAGFLOW_METADATA_SCHEMA,
                "defaults": {"domain": "example-domain", "locale": "en"},
                "documents": [
                    {
                        "path": "documents/example.md",
                        "metadata": {
                            "topic": "example-topic",
                            "module": "example-module",
                            "doc_type": "manual",
                            "audience": "example-audience",
                            "question_types": ["fact"],
                            "entities": ["ExampleEntity"],
                            "summary": "Placeholder summary.",
                            "source_uri": "https://example.com/source",
                            "source_hash": "0" * 64,
                        },
                        "tags": ["example-tag"],
                    }
                ],
            }
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["document_count"], 1)
        self.assertIn("domain", report["normalized_preview"]["documents"][0]["metadata"])

    def test_metadata_lint_redacts_secret_like_values(self) -> None:
        secret = "token=" + "sample-secret-value"
        report = lint_metadata_payload(
            {
                "schema": RAGFLOW_METADATA_SCHEMA,
                "documents": [
                    {
                        "path": "documents/example.md",
                        "metadata": {"source_uri": "https://example.com/private?" + secret},
                    }
                ],
            }
        )

        self.assertFalse(report["ok"])
        self.assertIn("metadata_value_looks_secret", {issue["code"] for issue in report["issues"]})
        self.assertNotIn(secret, json.dumps(report, ensure_ascii=False))
        self.assertIn("[REDACTED]", json.dumps(report, ensure_ascii=False))

    def test_metadata_merge_uses_user_metadata_over_handoff_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc_manifest = root / "doc_manifest.json"
            handoff_metadata = root / "metadata.json"
            user_metadata = root / "user_metadata.json"
            doc_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "source/example.pdf",
                                "markdown_path": "documents/example.md",
                                "title": "Manifest Title",
                                "sha256": "1" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            handoff_metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_document_metadata_v1",
                        "documents": [
                            {
                                "markdown": {"path": "documents/example.md"},
                                "title": "Handoff Topic",
                                "locale": "en",
                                "source_sha256": "2" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            user_metadata.write_text(
                json.dumps(
                    {
                        "schema": RAGFLOW_METADATA_SCHEMA,
                        "documents": [
                            {
                                "path": "documents/example.md",
                                "metadata": {"topic": "User Topic", "domain": "public-domain"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = merge_metadata_payloads(
                doc_manifest_path=doc_manifest,
                handoff_metadata_path=handoff_metadata,
                user_metadata_path=user_metadata,
            )

        merged = report["metadata"]["documents"][0]
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(merged["metadata"]["topic"], "User Topic")
        self.assertEqual(merged["metadata"]["domain"], "public-domain")
        self.assertGreaterEqual(report["summary"]["conflict_count"], 1)
        self.assertEqual(merged["metadata_sources"]["topic"], "user")

    def test_metadata_and_tagset_templates_are_placeholder_only(self) -> None:
        metadata = make_metadata_template_payload()
        tagset = make_tagset_template_payload()

        self.assertEqual(metadata["schema"], RAGFLOW_METADATA_SCHEMA)
        self.assertEqual(tagset["schema"], RAGFLOW_TAGSET_SCHEMA)
        combined = json.dumps({"metadata": metadata, "tagset": tagset}, ensure_ascii=False)
        self.assertIn("example.com", combined)
        self.assertNotIn("/home/", combined)

    def test_tagset_lint_report_and_export(self) -> None:
        tagset = {
            "schema": RAGFLOW_TAGSET_SCHEMA,
            "tags": [
                {
                    "name": "example-tag",
                    "label": "Example Tag",
                    "aliases": ["example"],
                    "metadata_defaults": {"domain": "example-domain"},
                }
            ],
            "assignments": [
                {"path": "documents/example.md", "tags": ["example-tag"]},
                {"path": "documents/orphan.md", "tags": ["missing-tag"]},
            ],
        }

        lint_report = lint_tagset_payload(tagset)
        coverage_report = tagset_report_payload(tagset)
        csv_export = export_tagset_payload({"schema": RAGFLOW_TAGSET_SCHEMA, "tags": tagset["tags"]}, fmt="csv")

        self.assertTrue(lint_report["ok"], lint_report["issues"])
        self.assertEqual(coverage_report["summary"]["orphan_tag_count"], 1)
        self.assertIn("assignment_orphan_tag", {issue["code"] for issue in coverage_report["issues"]})
        self.assertIn("name,label,description,aliases", csv_export)
        self.assertIn("example-tag", csv_export)

    def test_segment_metadata_report_matches_metadata_and_segmentation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            metadata = root / "metadata.json"
            segmentation_plan = root / "segmentation_plan.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "c" * 64,
                                "document_name": "long.part-001.md",
                                "document_id": "doc-1",
                                "content_preview": "Segment one content.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata.write_text(
                json.dumps(
                    {
                        "schema": RAGFLOW_METADATA_SCHEMA,
                        "documents": [
                            {
                                "path": "segments/long.part-001.md",
                                "metadata": {"topic": "Segment Topic", "source_hash": "1" * 64},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            segmentation_plan.write_text(
                json.dumps(
                    {
                        "schema": "doc_segmentation_plan_v1",
                        "segments": [
                            {
                                "index": 1,
                                "title": "One",
                                "suggested_markdown_path": "segments/long.part-001.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = segment_metadata_report_file(
                chunk_snapshot_path=snapshot,
                metadata_path=metadata,
                segmentation_plan_path=segmentation_plan,
            )

        self.assertEqual(report["schema"], SEGMENT_METADATA_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["metadata_document_coverage"], 1.0)
        self.assertEqual(report["summary"]["segment_hint_coverage"], 1.0)
        self.assertEqual(report["summary"]["segmentation_plan_coverage"], 1.0)

    def test_segment_metadata_report_deduplicates_missing_segment_alias_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            segmentation_plan = root / "segmentation_plan.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "c" * 64,
                                "document_name": "long.part-001.md",
                                "content_preview": "Segment one content.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            segmentation_plan.write_text(
                json.dumps(
                    {
                        "schema": "doc_segmentation_plan_v1",
                        "segments": [
                            {"index": 1, "suggested_markdown_path": "segments/long.part-001.md"},
                            {"index": 2, "suggested_markdown_path": "segments/long.part-002.md"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = segment_metadata_report_file(
                chunk_snapshot_path=snapshot,
                segmentation_plan_path=segmentation_plan,
            )

        missing_segment_issues = [
            issue for issue in report["issues"] if issue["code"] == "segment_without_chunk"
        ]
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["segmentation_plan_coverage"], 0.5)
        self.assertEqual(missing_segment_issues, [
            {
                "severity": "warning",
                "code": "segment_without_chunk",
                "message": "segmentation plan segment was not observed in the chunk snapshot",
                "field": "segments.2",
            }
        ])


if __name__ == "__main__":
    unittest.main()
