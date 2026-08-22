from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
import tempfile

from ragflow_skill_runtime.curated_image_update import (
    CURATED_IMAGE_UPDATE_PLAN_SCHEMA,
    CURATED_IMAGE_UPDATE_REPORT_SCHEMA,
    build_curated_image_update_plan,
    chunk_content_sha256,
    compose_curated_chunk_text,
    create_curated_image_update_report,
    render_curated_image_update_report_markdown,
    verify_curated_image_transport_capability,
)
from ragflow_skill_runtime.kb_build import (
    BuildError,
    create_kb_asset_ingestion_readiness_report,
    create_kb_asset_upload_plan,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _curated_capability(*, with_curated: bool = True) -> dict[str, object]:
    operations = [
        {
            "operation": "visual_document_upload",
            "transport": "multipart_post",
            "endpoint_class": "dataset_documents",
            "supported": True,
        },
        {
            "operation": "visual_document_parse",
            "transport": "json_post",
            "endpoint_class": "dataset_chunks",
            "supported": True,
        },
    ]
    if with_curated:
        operations.append(
            {
                "operation": "curated_image_update",
                "transport": "json_put",
                "endpoint_class": "document_detail",
                "supported": True,
            }
        )
    return {
        "schema": "ragflow_transport_capability_v1",
        "source": "operator",
        "server_version": "fake-fixture",
        "operations": operations,
    }


class CuratedImageUpdateFixture:
    """Build a handoff fixture with one context-bound image asset."""

    MARKDOWN_TEXT = "# Sample\n\n![context](images/context.png)\nSome surrounding text.\n"
    CONTEXT_LINE = "Some surrounding text."

    def __init__(self, root: Path, *, intent: str = "context_bound") -> None:
        image_dir = root / "documents" / "images"
        image_dir.mkdir(parents=True)
        self.markdown = root / "documents" / "sample.md"
        self.markdown.write_text(self.MARKDOWN_TEXT, encoding="utf-8")
        self.image = image_dir / "context.png"
        self.image.write_bytes(b"context-image-bytes")
        self.manifest = root / "doc_manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "version": "0.1",
                    "source_root": ".",
                    "documents": [{"source_path": "sample.pdf", "markdown_path": "documents/sample.md"}],
                }
            ),
            encoding="utf-8",
        )
        self.review = root / "ragflow_canonical_review.json"
        self.review.write_text(
            json.dumps(self.review_payload(intent=intent)),
            encoding="utf-8",
        )
        self.plan = create_kb_asset_upload_plan(
            doc_manifest_path=self.manifest,
            canonical_review_path=self.review,
        )
        self.plan_path = root / "asset_upload_plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def review_payload(self, *, intent: str) -> dict[str, object]:
        selected: dict[str, object] = {
            "path": "documents/images/context.png",
            "sha256": hashlib.sha256(b"context-image-bytes").hexdigest(),
            "role": "figure",
            "canonical_name": "context.png",
            "source_reference": "page:1",
            "ingestion_intent": intent,
        }
        if intent == "context_bound":
            selected["context_selector"] = "line:4-4"
            selected["context_sha256"] = _sha256_text(self.CONTEXT_LINE)
        return {
            "schema": "ragflow_canonical_review_v1",
            "status": "accepted",
            "ok": True,
            "markdown": {
                "candidate": {"sha256": "1" * 64},
                "accepted": {
                    "path": "documents/sample.md",
                    "sha256": hashlib.sha256(self.markdown.read_bytes()).hexdigest(),
                },
            },
            "selected_assets": [selected],
            "summary": {"selected_asset_count": 1, "unresolved_item_count": 0},
        }


class CuratedImageUpdatePlanTests(unittest.TestCase):
    def test_build_plan_composes_heading_and_pinned_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))

            plan = build_curated_image_update_plan(
                asset_plan_path=fixture.plan_path,
                canonical_review_path=fixture.review,
                accepted_markdown_path=fixture.markdown,
            )

        self.assertEqual(plan["schema"], CURATED_IMAGE_UPDATE_PLAN_SCHEMA)
        self.assertEqual(plan["summary"]["planned_update_count"], 1)
        asset = plan["assets"][0]
        self.assertEqual(asset["source_path"], "documents/images/context.png")
        self.assertEqual(asset["canonical_name"], "context.png")
        self.assertEqual(asset["context_selector"], "line:4-4")
        self.assertEqual(asset["curated_text"], "Sample\n\nSome surrounding text.")
        self.assertEqual(asset["curated_text_sha256"], _sha256_text("Sample\n\nSome surrounding text."))

    def test_build_plan_skips_non_context_bound_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp), intent="visual_extract")

            plan = build_curated_image_update_plan(
                asset_plan_path=fixture.plan_path,
                canonical_review_path=fixture.review,
                accepted_markdown_path=fixture.markdown,
            )

        self.assertEqual(plan["summary"]["planned_update_count"], 0)
        self.assertEqual(plan["assets"], [])

    def test_build_plan_rejects_stale_context_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))
            payload = fixture.review_payload(intent="context_bound")
            payload["selected_assets"][0]["context_sha256"] = "0" * 64
            fixture.review.write_text(json.dumps(payload), encoding="utf-8")
            fixture.plan = create_kb_asset_upload_plan(
                doc_manifest_path=fixture.manifest,
                canonical_review_path=fixture.review,
            )
            fixture.plan_path.write_text(json.dumps(fixture.plan), encoding="utf-8")

            with self.assertRaisesRegex(BuildError, "stale asset context hash"):
                build_curated_image_update_plan(
                    asset_plan_path=fixture.plan_path,
                    canonical_review_path=fixture.review,
                    accepted_markdown_path=fixture.markdown,
                )

    def test_build_plan_rejects_review_binding_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))
            payload = fixture.review_payload(intent="context_bound")
            payload["tampered"] = True
            fixture.review.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(BuildError, "does not match the asset upload plan binding"):
                build_curated_image_update_plan(
                    asset_plan_path=fixture.plan_path,
                    canonical_review_path=fixture.review,
                    accepted_markdown_path=fixture.markdown,
                )

    def test_build_plan_rejects_unaccepted_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))
            payload = fixture.review_payload(intent="context_bound")
            payload["status"] = "blocked"
            fixture.review.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(BuildError):
                build_curated_image_update_plan(
                    asset_plan_path=fixture.plan_path,
                    canonical_review_path=fixture.review,
                    accepted_markdown_path=fixture.markdown,
                )

    def test_compose_curated_chunk_text_without_heading(self) -> None:
        text = "intro line\nsecond line\n"
        self.assertEqual(
            compose_curated_chunk_text(text, context_selector="line:2-2"),
            "second line",
        )
        self.assertIsNone(compose_curated_chunk_text(text, context_selector="line:9-9"))

    def test_verify_curated_capability_gate(self) -> None:
        gate = verify_curated_image_transport_capability(_curated_capability())
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["operation"], "curated_image_update")
        with self.assertRaisesRegex(BuildError, "not supported"):
            verify_curated_image_transport_capability(_curated_capability(with_curated=False))


class CuratedImageUpdateReadinessTests(unittest.TestCase):
    def test_readiness_attests_context_bound_capability_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))

            readiness = create_kb_asset_ingestion_readiness_report(
                asset_upload_plan_path=fixture.plan_path,
                transport_capability=_curated_capability(),
            )

        self.assertEqual(readiness["status"], "ready_with_review")
        self.assertTrue(readiness["ok"])
        claim = readiness["checks"]["canonical_context_claim"]
        self.assertEqual(claim["status"], "READY")
        self.assertEqual(claim["capability"], "attested")
        self.assertIn("evidence_sha256", claim)
        self.assertIn("context_bound_capability_attested", {item["code"] for item in readiness["issues"]})

    def test_readiness_stays_blocked_when_evidence_lacks_curated_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CuratedImageUpdateFixture(Path(tmp))

            readiness = create_kb_asset_ingestion_readiness_report(
                asset_upload_plan_path=fixture.plan_path,
                transport_capability=_curated_capability(with_curated=False),
            )

        self.assertEqual(readiness["status"], "blocked")
        self.assertFalse(readiness["ok"])
        self.assertEqual(readiness["checks"]["canonical_context_claim"]["status"], "BLOCKED")
        issue = next(item for item in readiness["issues"] if item["code"] == "context_bound_capability_missing")
        self.assertIn("rejected", issue["message"])


class CuratedImageUpdateReportTests(unittest.TestCase):
    def test_report_counts_and_markdown(self) -> None:
        plan = {
            "schema": CURATED_IMAGE_UPDATE_PLAN_SCHEMA,
            "inputs": {"asset_upload_plan": "plan.json"},
            "assets": [{"source_path": "a.png"}, {"source_path": "b.png"}],
        }
        results = [
            {
                "source_path": "a.png",
                "canonical_name": "a.png",
                "status": "updated",
                "document_id": "doc-1",
                "updated_chunk_id": "chunk-1",
                "warnings": [],
            },
            {
                "source_path": "b.png",
                "canonical_name": "b.png",
                "status": "failed",
                "document_id": "doc-2",
                "error": "boom",
                "warnings": [{"code": "extra_chunks_left_untouched"}],
            },
        ]

        report = create_curated_image_update_report(
            plan=plan,
            dataset_id="ds-1",
            asset_results=results,
        )

        self.assertEqual(report["schema"], CURATED_IMAGE_UPDATE_REPORT_SCHEMA)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual(report["summary"]["updated_asset_count"], 1)
        self.assertEqual(report["summary"]["failed_asset_count"], 1)
        self.assertEqual(report["summary"]["warning_count"], 1)
        markdown = render_curated_image_update_report_markdown(report)
        self.assertIn("partial_failure", markdown)
        self.assertIn("a.png", markdown)

    def test_chunk_content_sha256(self) -> None:
        self.assertEqual(chunk_content_sha256("vlm text"), _sha256_text("vlm text"))


if __name__ == "__main__":
    unittest.main()
