from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.metadata_governance import (
    RAGFLOW_METADATA_SCHEMA,
    RAGFLOW_TAGSET_SCHEMA,
    export_tagset_payload,
    lint_metadata_payload,
    lint_tagset_payload,
    make_metadata_template_payload,
    make_tagset_template_payload,
    merge_metadata_payloads,
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


if __name__ == "__main__":
    unittest.main()
