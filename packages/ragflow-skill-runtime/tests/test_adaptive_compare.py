from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime import (
    ADAPTIVE_PIPELINE_SUMMARY_SCHEMA,
    ADAPTIVE_SUMMARY_COMPARISON_SCHEMA,
    DOCUMENT_FEATURES_SCHEMA,
    PIPELINE_DECISION_SCHEMA,
    compare_adaptive_summary_runs,
    render_adaptive_summary_comparison_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_run(
    root: Path,
    *,
    primary_language: str,
    language_source: str,
    fastapi_backend: str,
    profile_id: str,
    quality_status: str,
    marker_count: int,
    image_count: int,
    renamed_count: int,
) -> None:
    _write_json(
        root / "document_features.json",
        {
            "schema": DOCUMENT_FEATURES_SCHEMA,
            "summary": {
                "document_count": 1,
                "primary_language": primary_language,
                "language_source_counts": {language_source: 1},
                "scanned_or_low_text_pdf_count": 1 if language_source in {"filename_hint", "user_hint"} else 0,
                "sample_table_count": 2,
                "sample_html_table_count": 1,
                "sample_image_ref_count": image_count,
            },
            "documents": [],
        },
    )
    _write_json(
        root / "pipeline_decision.json",
        {
            "schema": PIPELINE_DECISION_SCHEMA,
            "confidence": "review",
            "signals": {
                "primary_language": primary_language,
                "inspected_primary_language": primary_language,
                "language_source": language_source,
            },
            "recommendation": {
                "backend": "mineru-fastapi",
                "table_quality": "standard",
                "postprocess_profile": "chunk-markers-dense",
                "mineru_fastapi_backend": fastapi_backend,
                "mineru_asset_mode": "markdown_assets",
                "kb_profile": {"id": profile_id},
            },
        },
    )
    _write_json(
        root / "adaptive_summary.json",
        {
            "schema": ADAPTIVE_PIPELINE_SUMMARY_SCHEMA,
            "ok": True,
            "pipeline_exit_code": 0,
            "decision_confidence": "review",
            "recommended_profile_id": profile_id,
            "quality_gate_status": quality_status,
            "ingest_readiness_status": "ready_with_review",
            "post_conversion_profile_id": profile_id,
            "warnings": [{"code": "low_text_pdf_language_hint", "severity": "info", "message": "hint"}],
        },
    )
    _write_json(
        root / "quality_report.json",
        {
            "schema": "doc_quality_report_v1",
            "gate": {"status": quality_status},
            "documents": [
                {
                    "quality_signals": {
                        "chunk_marker_table_atomicity": {
                            "chunk_marker_count": marker_count,
                            "marker_inside_table_count": 0,
                            "unbalanced_fragment_count": 0,
                        }
                    }
                }
            ],
        },
    )
    _write_json(
        root / "chunk_profile_report.json",
        {
            "schema": "ragflow_chunk_profile_report_v1",
            "summary": {
                "marker_count": marker_count,
                "preferred_boundary_alignment_ratio": 1.0,
            },
        },
    )
    _write_json(
        root / "runtime_report.json",
        {
            "schema": "ragflow_doc_runtime_report_v1",
            "remote_attempts": [
                {
                    "asset_policy": {
                        "saved": {
                            "image_count": image_count,
                            "image_naming": {"renamed_count": renamed_count},
                        }
                    }
                }
            ],
        },
    )


def _write_adaptive_outcome_sidecars(
    root: Path,
    *,
    build_status: str,
    parse_status: str,
    retrieval_status: str,
    planned_upload_count: int,
    chunk_count: int,
    validation_pass_rate: float,
    query_result_count: int,
    query_latency_ms: float,
) -> None:
    _write_json(
        root / "asset_upload_plan.json",
        {
            "schema": "ragflow_kb_asset_upload_plan_v2",
            "summary": {
                "planned_upload_count": planned_upload_count,
                "referenced_image_count": planned_upload_count,
            },
            "policy": {"default_upload_class": "markdown_referenced"},
        },
    )
    _write_json(
        root / "kb_manifest.json",
        {
            "schema": "ragflow_multimodal_kb_manifest_v1",
            "summary": {
                "status": build_status,
                "document_count": 1,
                "chunk_count": chunk_count,
            },
        },
    )
    _write_json(
        root / "parse_report.json",
        {
            "schema": "ragflow_parse_report_v1",
            "ok": parse_status == "success",
            "summary": {
                "parse_status": parse_status,
                "total_chunk_count": chunk_count,
            },
        },
    )
    _write_json(
        root / "validation_benchmark.json",
        {
            "schema": "ragflow_validation_report_v1",
            "ok": retrieval_status == "pass",
            "metrics": {
                "pass_rate": validation_pass_rate,
                "total": 8,
                "empty_result_rate": 0.0 if retrieval_status == "pass" else 0.25,
                "query_latency_ms": query_latency_ms,
            },
        },
    )
    _write_json(
        root / "query_direct.json",
        {
            "schema": "ragflow_query_result_v1",
            "ok": query_result_count > 0,
            "summary": {"result_count": query_result_count},
            "runtime_metrics": {"latency_ms": {"average": query_latency_ms}},
        },
    )


class AdaptiveSummaryComparisonTests(unittest.TestCase):
    def test_compare_adaptive_summary_runs_highlights_regression_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            _write_run(
                baseline,
                primary_language="zh",
                language_source="filename_hint",
                fastapi_backend="pipeline",
                profile_id="table-atomic-zh-4096",
                quality_status="PASS_WITH_REVIEW",
                marker_count=32,
                image_count=21,
                renamed_count=12,
            )
            _write_run(
                candidate,
                primary_language="en",
                language_source="inspect_source",
                fastapi_backend="hybrid-auto-engine",
                profile_id="table-atomic-en-4096",
                quality_status="BLOCKED",
                marker_count=12,
                image_count=21,
                renamed_count=4,
            )

            report = compare_adaptive_summary_runs(baseline=baseline, candidate=candidate)
            markdown = render_adaptive_summary_comparison_markdown(report)

        self.assertEqual(report["schema"], ADAPTIVE_SUMMARY_COMPARISON_SCHEMA)
        self.assertEqual(report["summary"]["status"], "review")
        self.assertTrue(report["summary"]["language_source_changed"])
        self.assertTrue(report["summary"]["backend_changed"])
        self.assertTrue(report["summary"]["quality_gate_changed"])
        fields = {change["field"] for change in report["changes"]}
        self.assertIn("decision.language_source", fields)
        self.assertIn("decision.mineru_fastapi_backend", fields)
        self.assertIn("outcome.quality_gate_status", fields)
        self.assertIn("outcome.chunk_profile_marker_count", fields)
        self.assertIn("outcome.semantic_rename_ratio", fields)
        self.assertIn("RAGFlow Adaptive Summary Comparison", markdown)

    def test_compare_adaptive_summary_runs_records_decision_build_and_query_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            _write_run(
                baseline,
                primary_language="zh",
                language_source="inspect_source",
                fastapi_backend="hybrid-auto-engine",
                profile_id="table-atomic-zh-4096",
                quality_status="PASS",
                marker_count=24,
                image_count=15,
                renamed_count=15,
            )
            _write_adaptive_outcome_sidecars(
                baseline,
                build_status="ready",
                parse_status="success",
                retrieval_status="pass",
                planned_upload_count=15,
                chunk_count=128,
                validation_pass_rate=1.0,
                query_result_count=5,
                query_latency_ms=90.0,
            )
            _write_run(
                candidate,
                primary_language="zh",
                language_source="inspect_source",
                fastapi_backend="pipeline",
                profile_id="default-zh-512",
                quality_status="PASS_WITH_REVIEW",
                marker_count=8,
                image_count=3,
                renamed_count=1,
            )
            _write_adaptive_outcome_sidecars(
                candidate,
                build_status="review",
                parse_status="failed",
                retrieval_status="failed",
                planned_upload_count=3,
                chunk_count=0,
                validation_pass_rate=0.25,
                query_result_count=0,
                query_latency_ms=240.0,
            )

            report = compare_adaptive_summary_runs(baseline=baseline, candidate=candidate)
            markdown = render_adaptive_summary_comparison_markdown(report)

        self.assertTrue(report["summary"]["parse_outcome_changed"])
        self.assertTrue(report["summary"]["retrieval_outcome_changed"])
        self.assertTrue(report["summary"]["build_query_metrics_compared"])
        self.assertEqual(report["baseline"]["decision_outcome"]["backend"], "mineru-fastapi")
        self.assertEqual(report["baseline"]["decision_outcome"]["table_quality"], "standard")
        self.assertEqual(report["baseline"]["decision_outcome"]["chunk_profile"], "table-atomic-zh-4096")
        self.assertEqual(report["baseline"]["decision_outcome"]["asset_policy"], "markdown_referenced")
        self.assertEqual(report["baseline"]["decision_outcome"]["parse_status"], "success")
        self.assertEqual(report["baseline"]["decision_outcome"]["retrieval_status"], "pass")
        self.assertEqual(report["candidate"]["decision_outcome"]["parse_status"], "failed")
        self.assertEqual(report["candidate"]["outcome"]["validation_pass_rate"], 0.25)
        fields = {change["field"] for change in report["changes"]}
        self.assertIn("decision_outcome.parse_status", fields)
        self.assertIn("decision_outcome.retrieval_status", fields)
        self.assertIn("outcome.validation_pass_rate", fields)
        self.assertIn("Build And Query Outcomes", markdown)


if __name__ == "__main__":
    unittest.main()
