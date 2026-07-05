"""Compare deterministic adaptive document-pipeline run summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adaptive_decision import ADAPTIVE_PIPELINE_SUMMARY_SCHEMA, PIPELINE_DECISION_SCHEMA
from .doc_inspect import DOCUMENT_FEATURES_SCHEMA


ADAPTIVE_SUMMARY_COMPARISON_SCHEMA = "ragflow_adaptive_summary_comparison_v1"


class AdaptiveSummaryComparisonError(RuntimeError):
    """Raised when adaptive comparison inputs cannot be loaded."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AdaptiveSummaryComparisonError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise AdaptiveSummaryComparisonError(f"file is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise AdaptiveSummaryComparisonError(f"file must contain a JSON object: {source}")
    return payload


def _optional_sidecars(root: Path) -> dict[str, dict[str, Any]]:
    sidecars: dict[str, dict[str, Any]] = {}
    for key, name in (
        ("runtime_report", "runtime_report.json"),
        ("quality_report", "quality_report.json"),
        ("postprocess_report", "postprocess_report.json"),
        ("chunk_profile_report", "chunk_profile_report.json"),
        ("ingest_readiness_report", "ingest_readiness_report.json"),
    ):
        path = root / name
        if path.is_file():
            sidecars[key] = _read_json_mapping(path)
    return sidecars


def _load_run_bundle(path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    source = Path(path)
    if source.is_dir():
        root = source
        features = _read_json_mapping(root / "document_features.json")
        decision = _read_json_mapping(root / "pipeline_decision.json")
        summary = _read_json_mapping(root / "adaptive_summary.json")
    else:
        root = source.parent
        summary = _read_json_mapping(source)
        if summary.get("schema") != ADAPTIVE_PIPELINE_SUMMARY_SCHEMA:
            raise AdaptiveSummaryComparisonError(
                f"adaptive summary must use schema {ADAPTIVE_PIPELINE_SUMMARY_SCHEMA}: {source}"
            )
        features = _read_json_mapping(root / "document_features.json")
        decision = _read_json_mapping(root / "pipeline_decision.json")

    if features.get("schema") != DOCUMENT_FEATURES_SCHEMA:
        raise AdaptiveSummaryComparisonError(f"document_features.json must use schema {DOCUMENT_FEATURES_SCHEMA}: {root}")
    if decision.get("schema") != PIPELINE_DECISION_SCHEMA:
        raise AdaptiveSummaryComparisonError(f"pipeline_decision.json must use schema {PIPELINE_DECISION_SCHEMA}: {root}")
    if summary.get("schema") != ADAPTIVE_PIPELINE_SUMMARY_SCHEMA:
        raise AdaptiveSummaryComparisonError(f"adaptive_summary.json must use schema {ADAPTIVE_PIPELINE_SUMMARY_SCHEMA}: {root}")
    return root, features, decision, summary, _optional_sidecars(root)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _quality_gate_status(
    summary: Mapping[str, Any],
    pipeline_result: Mapping[str, Any],
    quality_report: Mapping[str, Any],
) -> str | None:
    value = summary.get("quality_gate_status")
    if isinstance(value, str) and value:
        return value
    quality_gate = _as_mapping(pipeline_result.get("quality_gate"))
    value = quality_gate.get("status")
    if value:
        return str(value)
    gate = _as_mapping(quality_report.get("gate"))
    value = gate.get("status")
    return str(value) if value else None


def _summary_pipeline_result(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(summary.get("pipeline_result"))


def _quality_report_from_pipeline(pipeline_result: Mapping[str, Any], quality_report: Mapping[str, Any]) -> Mapping[str, Any]:
    if quality_report:
        return quality_report
    quality = pipeline_result.get("quality_report")
    if isinstance(quality, Mapping):
        return quality
    quality_path = pipeline_result.get("quality_report")
    if isinstance(quality_path, str) and quality_path.strip():
        path = Path(quality_path)
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, Mapping) else {}
    return {}


def _quality_signal_totals(pipeline_result: Mapping[str, Any], quality_report: Mapping[str, Any]) -> dict[str, Any]:
    quality_report = _quality_report_from_pipeline(pipeline_result, quality_report)
    documents = quality_report.get("documents") if isinstance(quality_report.get("documents"), list) else []
    marker_count = 0
    marker_inside_table_count = 0
    unbalanced_fragment_count = 0
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        signals = _as_mapping(document.get("quality_signals"))
        atomicity = _as_mapping(signals.get("chunk_marker_table_atomicity"))
        marker_count += _as_int(atomicity.get("chunk_marker_count"))
        marker_inside_table_count += _as_int(atomicity.get("marker_inside_table_count"))
        unbalanced_fragment_count += _as_int(atomicity.get("unbalanced_fragment_count"))
    return {
        "chunk_marker_count": marker_count,
        "marker_inside_table_count": marker_inside_table_count,
        "unbalanced_table_fragment_count": unbalanced_fragment_count,
    }


def _image_naming_stats(pipeline_result: Mapping[str, Any], runtime_report_sidecar: Mapping[str, Any]) -> dict[str, Any]:
    runtime_report = runtime_report_sidecar if runtime_report_sidecar else _as_mapping(pipeline_result.get("runtime_report"))
    remote_attempts = runtime_report.get("remote_attempts")
    attempts = remote_attempts if isinstance(remote_attempts, list) else []
    discovered = 0
    renamed = 0
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        policy = _as_mapping(attempt.get("asset_policy"))
        saved = _as_mapping(policy.get("saved"))
        discovered += _as_int(saved.get("image_count"))
        naming = _as_mapping(saved.get("image_naming"))
        renamed += _as_int(naming.get("renamed_count"))
    ratio = round(renamed / discovered, 6) if discovered else None
    return {
        "discovered_image_count": discovered,
        "semantic_rename_count": renamed,
        "semantic_rename_ratio": ratio,
    }


def _chunk_marker_stats(postprocess_report: Mapping[str, Any], chunk_profile_report: Mapping[str, Any]) -> dict[str, Any]:
    source = chunk_profile_report
    if not source:
        embedded = postprocess_report.get("chunk_profile_report")
        source = embedded if isinstance(embedded, Mapping) else {}
    summary = _as_mapping(source.get("summary"))
    return {
        "chunk_profile_marker_count": _as_int(summary.get("marker_count")),
        "chunk_profile_alignment_ratio": summary.get("preferred_boundary_alignment_ratio"),
    }


def _run_extract(label: str, path: str | Path) -> dict[str, Any]:
    root, features, decision, summary, sidecars = _load_run_bundle(path)
    feature_summary = _as_mapping(features.get("summary"))
    signals = _as_mapping(decision.get("signals"))
    recommendation = _as_mapping(decision.get("recommendation"))
    profile = _as_mapping(recommendation.get("kb_profile"))
    pipeline_result = _summary_pipeline_result(summary)
    quality_report = sidecars.get("quality_report", {})
    runtime_report = sidecars.get("runtime_report", {})
    postprocess_report = sidecars.get("postprocess_report", {})
    chunk_profile_report = sidecars.get("chunk_profile_report", {})
    ingest_readiness_report = sidecars.get("ingest_readiness_report", {})
    ingest_summary = _as_mapping(ingest_readiness_report.get("summary"))
    image_stats = _image_naming_stats(pipeline_result, runtime_report)
    quality_signals = _quality_signal_totals(pipeline_result, quality_report)
    chunk_stats = _chunk_marker_stats(postprocess_report, chunk_profile_report)
    return {
        "label": label,
        "root": str(root),
        "schemas": {
            "features": features.get("schema"),
            "decision": decision.get("schema"),
            "summary": summary.get("schema"),
        },
        "ok": bool(summary.get("ok", True)),
        "source": {
            "document_count": _as_int(feature_summary.get("document_count")),
            "primary_language": feature_summary.get("primary_language") or "unknown",
            "language_source_counts": dict(_as_mapping(feature_summary.get("language_source_counts"))),
            "scanned_or_low_text_pdf_count": _as_int(feature_summary.get("scanned_or_low_text_pdf_count")),
            "sample_table_count": _as_int(feature_summary.get("sample_table_count")),
            "sample_html_table_count": _as_int(feature_summary.get("sample_html_table_count")),
            "sample_image_ref_count": _as_int(feature_summary.get("sample_image_ref_count")),
        },
        "decision": {
            "confidence": decision.get("confidence") or "unknown",
            "primary_language": signals.get("primary_language") or "auto",
            "inspected_primary_language": signals.get("inspected_primary_language") or "auto",
            "language_source": signals.get("language_source") or "unknown",
            "backend": recommendation.get("backend") or "auto",
            "table_quality": recommendation.get("table_quality") or "standard",
            "postprocess_profile": recommendation.get("postprocess_profile") or "none",
            "mineru_fastapi_backend": recommendation.get("mineru_fastapi_backend") or "pipeline",
            "mineru_asset_mode": recommendation.get("mineru_asset_mode") or "markdown_only",
            "recommended_profile_id": profile.get("id") or profile.get("profile_id") or summary.get("recommended_profile_id"),
        },
        "outcome": {
            "pipeline_exit_code": summary.get("pipeline_exit_code"),
            "quality_gate_status": _quality_gate_status(summary, pipeline_result, quality_report),
            "ingest_readiness_status": summary.get("ingest_readiness_status") or ingest_readiness_report.get("status"),
            "ingest_readiness_score": ingest_readiness_report.get("advisory_score") or ingest_summary.get("advisory_score"),
            "post_conversion_profile_id": summary.get("post_conversion_profile_id"),
            **image_stats,
            **quality_signals,
            **chunk_stats,
        },
        "warning_codes": [
            str(item.get("code"))
            for item in summary.get("warnings", [])
            if isinstance(item, Mapping) and item.get("code")
        ],
    }


def _change(
    *,
    field: str,
    before: Any,
    after: Any,
    severity: str = "info",
    message: str = "",
) -> dict[str, Any] | None:
    if before == after:
        return None
    return {
        "field": field,
        "before": before,
        "after": after,
        "severity": severity,
        "message": message or f"{field} changed",
    }


def _ratio_delta(before: Any, after: Any) -> float | None:
    if before is None or after is None:
        return None
    return round(_as_float(after) - _as_float(before), 6)


def compare_adaptive_summary_runs(
    *,
    baseline: str | Path,
    candidate: str | Path,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> dict[str, Any]:
    """Compare two adaptive runs without converting documents or calling RAGFlow."""

    before = _run_extract(baseline_label, baseline)
    after = _run_extract(candidate_label, candidate)
    changes: list[dict[str, Any]] = []

    comparisons = (
        ("source.primary_language", before["source"]["primary_language"], after["source"]["primary_language"], "review"),
        (
            "decision.inspected_primary_language",
            before["decision"]["inspected_primary_language"],
            after["decision"]["inspected_primary_language"],
            "review",
        ),
        ("decision.language_source", before["decision"]["language_source"], after["decision"]["language_source"], "review"),
        ("decision.backend", before["decision"]["backend"], after["decision"]["backend"], "review"),
        (
            "decision.mineru_fastapi_backend",
            before["decision"]["mineru_fastapi_backend"],
            after["decision"]["mineru_fastapi_backend"],
            "review",
        ),
        ("decision.table_quality", before["decision"]["table_quality"], after["decision"]["table_quality"], "review"),
        (
            "decision.postprocess_profile",
            before["decision"]["postprocess_profile"],
            after["decision"]["postprocess_profile"],
            "info",
        ),
        (
            "decision.recommended_profile_id",
            before["decision"]["recommended_profile_id"],
            after["decision"]["recommended_profile_id"],
            "review",
        ),
        (
            "outcome.post_conversion_profile_id",
            before["outcome"]["post_conversion_profile_id"],
            after["outcome"]["post_conversion_profile_id"],
            "review",
        ),
        (
            "outcome.quality_gate_status",
            before["outcome"]["quality_gate_status"],
            after["outcome"]["quality_gate_status"],
            "warning",
        ),
        (
            "outcome.ingest_readiness_status",
            before["outcome"]["ingest_readiness_status"],
            after["outcome"]["ingest_readiness_status"],
            "warning",
        ),
        (
            "outcome.chunk_marker_count",
            before["outcome"]["chunk_marker_count"],
            after["outcome"]["chunk_marker_count"],
            "info",
        ),
        (
            "outcome.chunk_profile_marker_count",
            before["outcome"]["chunk_profile_marker_count"],
            after["outcome"]["chunk_profile_marker_count"],
            "info",
        ),
        (
            "outcome.chunk_profile_alignment_ratio",
            before["outcome"]["chunk_profile_alignment_ratio"],
            after["outcome"]["chunk_profile_alignment_ratio"],
            "info",
        ),
        (
            "outcome.marker_inside_table_count",
            before["outcome"]["marker_inside_table_count"],
            after["outcome"]["marker_inside_table_count"],
            "review",
        ),
        (
            "outcome.unbalanced_table_fragment_count",
            before["outcome"]["unbalanced_table_fragment_count"],
            after["outcome"]["unbalanced_table_fragment_count"],
            "review",
        ),
    )
    for field, before_value, after_value, severity in comparisons:
        item = _change(field=field, before=before_value, after=after_value, severity=severity)
        if item:
            changes.append(item)

    numeric_comparisons = (
        ("source.scanned_or_low_text_pdf_count", before["source"], after["source"], "scanned_or_low_text_pdf_count"),
        ("source.sample_table_count", before["source"], after["source"], "sample_table_count"),
        ("source.sample_html_table_count", before["source"], after["source"], "sample_html_table_count"),
        ("source.sample_image_ref_count", before["source"], after["source"], "sample_image_ref_count"),
        ("outcome.discovered_image_count", before["outcome"], after["outcome"], "discovered_image_count"),
        ("outcome.semantic_rename_count", before["outcome"], after["outcome"], "semantic_rename_count"),
    )
    for field, before_root, after_root, key in numeric_comparisons:
        item = _change(
            field=field,
            before=before_root.get(key),
            after=after_root.get(key),
            severity="info",
        )
        if item:
            changes.append(item)

    ratio_before = before["outcome"]["semantic_rename_ratio"]
    ratio_after = after["outcome"]["semantic_rename_ratio"]
    ratio_change = _change(
        field="outcome.semantic_rename_ratio",
        before=ratio_before,
        after=ratio_after,
        severity="info",
        message="semantic image rename ratio changed",
    )
    if ratio_change:
        ratio_change["delta"] = _ratio_delta(ratio_before, ratio_after)
        changes.append(ratio_change)

    warning_changes = {
        "added": sorted(set(after["warning_codes"]) - set(before["warning_codes"])),
        "removed": sorted(set(before["warning_codes"]) - set(after["warning_codes"])),
    }
    if warning_changes["added"] or warning_changes["removed"]:
        changes.append(
            {
                "field": "warning_codes",
                "before": before["warning_codes"],
                "after": after["warning_codes"],
                "severity": "review",
                "message": "adaptive warning code set changed",
                "added": warning_changes["added"],
                "removed": warning_changes["removed"],
            }
        )

    review_count = sum(1 for item in changes if item.get("severity") in {"review", "warning"})
    return {
        "schema": ADAPTIVE_SUMMARY_COMPARISON_SCHEMA,
        "created_at": _utc_now(),
        "ok": True,
        "offline_only": True,
        "mutation": "none",
        "execution": {
            "ragflow_calls": 0,
            "mineru_calls": 0,
            "conversion_runs": 0,
            "script_owned_llm_calls": 0,
        },
        "summary": {
            "status": "review" if review_count else "pass",
            "change_count": len(changes),
            "review_change_count": review_count,
            "language_source_changed": before["decision"]["language_source"] != after["decision"]["language_source"],
            "backend_changed": (
                before["decision"]["backend"] != after["decision"]["backend"]
                or before["decision"]["mineru_fastapi_backend"] != after["decision"]["mineru_fastapi_backend"]
            ),
            "quality_gate_changed": before["outcome"]["quality_gate_status"] != after["outcome"]["quality_gate_status"],
            "table_profile_changed": before["decision"]["recommended_profile_id"] != after["decision"]["recommended_profile_id"],
            "table_atomicity_changed": (
                before["outcome"]["chunk_marker_count"] != after["outcome"]["chunk_marker_count"]
                or before["outcome"]["marker_inside_table_count"] != after["outcome"]["marker_inside_table_count"]
                or before["outcome"]["unbalanced_table_fragment_count"] != after["outcome"]["unbalanced_table_fragment_count"]
            ),
            "image_naming_ratio_delta": _ratio_delta(ratio_before, ratio_after),
        },
        "baseline": before,
        "candidate": after,
        "changes": changes,
    }


def render_adaptive_summary_comparison_markdown(report: Mapping[str, Any]) -> str:
    summary = _as_mapping(report.get("summary"))
    baseline = _as_mapping(report.get("baseline"))
    candidate = _as_mapping(report.get("candidate"))
    lines = [
        "# RAGFlow Adaptive Summary Comparison",
        "",
        f"- schema: `{report.get('schema', ADAPTIVE_SUMMARY_COMPARISON_SCHEMA)}`",
        f"- status: `{summary.get('status', 'unknown')}`",
        f"- changes: `{summary.get('change_count', 0)}`",
        f"- review changes: `{summary.get('review_change_count', 0)}`",
        f"- language source changed: `{summary.get('language_source_changed', False)}`",
        f"- backend changed: `{summary.get('backend_changed', False)}`",
        f"- quality gate changed: `{summary.get('quality_gate_changed', False)}`",
        f"- image naming ratio delta: `{summary.get('image_naming_ratio_delta')}`",
        "",
        "| Run | Language Source | Backend | FastAPI Backend | Profile | Quality Gate | Image Rename Ratio |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for item in (baseline, candidate):
        decision = _as_mapping(item.get("decision"))
        outcome = _as_mapping(item.get("outcome"))
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                item.get("label", ""),
                decision.get("language_source", "unknown"),
                decision.get("backend", "auto"),
                decision.get("mineru_fastapi_backend", "pipeline"),
                decision.get("recommended_profile_id", "none"),
                outcome.get("quality_gate_status", "unknown"),
                outcome.get("semantic_rename_ratio"),
            )
        )
    changes = report.get("changes") if isinstance(report.get("changes"), list) else []
    if changes:
        lines.extend(["", "## Changes", ""])
        for item in changes:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- `{}` ({}): `{}` -> `{}`".format(
                    item.get("field", ""),
                    item.get("severity", "info"),
                    item.get("before"),
                    item.get("after"),
                )
            )
    lines.append("")
    return "\n".join(lines)
