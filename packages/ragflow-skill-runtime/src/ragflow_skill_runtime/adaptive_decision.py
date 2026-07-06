"""Deterministic adaptive conversion decisions for RAGFlow handoffs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_inspect import DOCUMENT_FEATURES_SCHEMA


PIPELINE_DECISION_SCHEMA = "ragflow_pipeline_decision_v1"
ADAPTIVE_PIPELINE_SUMMARY_SCHEMA = "ragflow_adaptive_pipeline_summary_v1"

ADAPTIVE_POLICIES = {"formal", "fast-preview", "table-atomic"}
TABLE_QUALITY_MODES = {"standard", "auto", "high"}
BACKENDS = {
    "auto",
    "builtin",
    "mineru",
    "mineru-agent",
    "mineru-cli",
    "mineru-fastapi",
    "mineru-local",
    "mineru-sync",
    "pandoc",
    "remote",
}
POSTPROCESS_PROFILES = {
    "none",
    "safe",
    "ocr",
    "chunk-markers",
    "chunk-markers-conservative",
    "chunk-markers-dense",
    "chunk-markers-ragflux-like",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bool(summary: Mapping[str, Any], key: str) -> bool:
    return bool(summary.get(key))


def _int(summary: Mapping[str, Any], key: str) -> int:
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _normal_language(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    if text in {"zh", "chinese", "cn", "zho", "ch"} or text.startswith("ch,"):
        return "zh"
    if text in {"en", "english", "eng"}:
        return "en"
    return "auto"


def _feature_language_hint(features: Mapping[str, Any]) -> str:
    documents = features.get("documents")
    if not isinstance(documents, list):
        return "auto"
    for item in documents:
        if not isinstance(item, Mapping):
            continue
        sample = item.get("sample") if isinstance(item.get("sample"), Mapping) else {}
        if str(sample.get("language_source") or "") == "filename_hint":
            language = _normal_language(sample.get("language"))
            if language != "auto":
                return language
        language_hint = _normal_language(item.get("language_hint"))
        if language_hint != "auto":
            return language_hint
    return "auto"


def _table_profile(language: str) -> dict[str, Any]:
    label = "Chinese" if language == "zh" else "English" if language == "en" else "auto"
    suffix = "zh" if language == "zh" else "en" if language == "en" else "auto"
    return {
        "id": f"table-atomic-{suffix}-4096",
        "chunk_method": "naive",
        "chunk_size": 4096,
        "chunk_overlap": 0,
        "parser_config": {
            "chunk_token_num": 4096,
            "delimiter": "`<!-- chunk -->`",
            "auto_keywords": 0,
            "auto_questions": 0,
            "__language__": label,
        },
        "avoid_children_delimiter": True,
    }


def _default_profile(language: str) -> dict[str, Any]:
    chunk_size = 512 if language == "zh" else 768 if language == "en" else 640
    overlap = 64 if chunk_size <= 512 else 96 if chunk_size >= 768 else 80
    label = "Chinese" if language == "zh" else "English" if language == "en" else "auto"
    suffix = "zh" if language == "zh" else "en" if language == "en" else "auto"
    return {
        "id": f"adaptive-default-{suffix}-{chunk_size}",
        "chunk_method": "naive",
        "chunk_size": chunk_size,
        "chunk_overlap": overlap,
        "parser_config": {
            "chunk_token_num": chunk_size,
            "auto_keywords": 0,
            "auto_questions": 0,
            "__language__": label,
        },
    }


def _source_kind_counts(summary: Mapping[str, Any]) -> dict[str, int]:
    raw = summary.get("source_kind_counts")
    if not isinstance(raw, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        try:
            counts[str(key)] = int(value or 0)
        except (TypeError, ValueError):
            counts[str(key)] = 0
    return counts


def _validated_choice(value: str | None, *, allowed: set[str], label: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower().replace("_", "-")
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"{label} must be one of: {allowed_text}")
    return normalized


def _apply_overrides(decision: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    applied: dict[str, Any] = {}
    recommendation = decision["recommendation"]
    for key, allowed in (
        ("backend", BACKENDS),
        ("table_quality", TABLE_QUALITY_MODES),
        ("postprocess_profile", POSTPROCESS_PROFILES),
    ):
        if key not in overrides:
            continue
        value = _validated_choice(str(overrides.get(key)), allowed=allowed, label=key)
        if value:
            recommendation[key] = value
            applied[key] = value
    if "mineru_fastapi_backend" in overrides:
        value = str(overrides.get("mineru_fastapi_backend") or "").strip()
        if value:
            recommendation["mineru_fastapi_backend"] = value
            applied["mineru_fastapi_backend"] = value
    if "mineru_asset_mode" in overrides:
        value = str(overrides.get("mineru_asset_mode") or "").strip()
        if value in {"markdown_only", "markdown_assets"}:
            recommendation["mineru_asset_mode"] = value
            applied["mineru_asset_mode"] = value
        elif value:
            raise ValueError("mineru_asset_mode must be markdown_only or markdown_assets")
    if applied:
        decision["overrides"] = {"applied": applied}
        decision["confidence"] = "manual_override"
        decision.setdefault("warnings", []).append(
            {
                "code": "manual_decision_override",
                "severity": "review",
                "message": "User-provided adaptive decision overrides were applied.",
            }
        )


def make_pipeline_decision(
    features: Mapping[str, Any],
    *,
    requested_backend: str | None = None,
    requested_language: str | None = None,
    requested_table_quality: str | None = None,
    requested_postprocess_profile: str | None = None,
    requested_mineru_fastapi_backend: str | None = None,
    requested_mineru_asset_mode: str | None = None,
    policy: str = "formal",
    backend_probe_status: str | None = None,
    allow_table_quality_fallback: bool = False,
    decision_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic pipeline decision from lightweight source features."""

    if features.get("schema") != DOCUMENT_FEATURES_SCHEMA:
        raise ValueError(f"features must use schema {DOCUMENT_FEATURES_SCHEMA}")
    normalized_policy = _validated_choice(policy, allowed=ADAPTIVE_POLICIES, label="policy") or "formal"
    backend = _validated_choice(requested_backend, allowed=BACKENDS, label="backend") or "auto"
    requested_quality = _validated_choice(
        requested_table_quality,
        allowed=TABLE_QUALITY_MODES,
        label="table_quality",
    )
    requested_postprocess = _validated_choice(
        requested_postprocess_profile,
        allowed=POSTPROCESS_PROFILES,
        label="postprocess_profile",
    )
    summary = features.get("summary") if isinstance(features.get("summary"), Mapping) else {}
    inspected_language = _normal_language(summary.get("primary_language"))
    user_language = _normal_language(requested_language)
    table_heavy = _bool(summary, "table_heavy")
    has_tables = _int(summary, "sample_table_count") > 0
    source_kind_counts = _source_kind_counts(summary)
    conversion_table_candidate = any(
        source_kind_counts.get(kind, 0) > 0
        for kind in {"pdf", "office", "image", "structured_document"}
    )
    source_table_signal = (has_tables or table_heavy) and conversion_table_candidate
    image_rich = _bool(summary, "image_rich")
    long_document = _bool(summary, "long_document")
    formal_candidate = _bool(summary, "has_formal_ingest_candidates")
    low_text_pdf_count = _int(summary, "scanned_or_low_text_pdf_count")
    numeric_signal_count = _int(summary, "numeric_or_unit_signal_count")
    fastapi_probe_green = backend_probe_status in {None, "", "not_run", "available"}
    feature_hint_language = _feature_language_hint(features)
    if low_text_pdf_count and user_language != "auto":
        language = user_language
        language_source = "user_hint"
    elif low_text_pdf_count and feature_hint_language != "auto":
        language = feature_hint_language
        language_source = "filename_hint"
    else:
        language = inspected_language
        language_source = "inspect_source"

    reasons: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if normalized_policy == "fast-preview":
        postprocess = requested_postprocess or "safe"
        table_quality = requested_quality or "standard"
        asset_mode = requested_mineru_asset_mode or "markdown_only"
        profile = _default_profile(language)
        reasons.append({"code": "fast_preview_policy", "message": "Fast preview keeps low-cost defaults."})
    else:
        if source_table_signal and backend == "auto" and fastapi_probe_green:
            backend = "mineru-fastapi"
            reasons.append(
                {
                    "code": "table_signal_mineru_fastapi_backend",
                    "message": (
                        "Source inspection found table signals in conversion-required input; "
                        "MinerU FastAPI is selected so high-quality table extraction can run."
                    ),
                }
            )
        elif source_table_signal and backend == "auto" and not fastapi_probe_green:
            warnings.append(
                {
                    "code": "table_signal_fastapi_probe_not_green",
                    "severity": "review",
                    "message": (
                        "Source inspection found table signals, but MinerU FastAPI probe is not green; "
                        "review backend health before enabling high-quality table extraction."
                    ),
                }
            )
        postprocess = requested_postprocess or "chunk-markers-dense"
        asset_mode = requested_mineru_asset_mode or "markdown_assets"
        if has_tables or table_heavy or normalized_policy == "table-atomic":
            profile = _table_profile(language)
            reasons.append({"code": "table_atomic_profile", "message": "Table signals select dense markers and a table-atomic KB profile."})
        else:
            profile = _default_profile(language)
            reasons.append({"code": "default_profile", "message": "No table signal requires the table-atomic profile."})
        if requested_quality:
            table_quality = requested_quality
            reasons.append({"code": "requested_table_quality", "message": "User-requested table quality is preserved."})
        elif backend == "mineru-fastapi" and source_table_signal and fastapi_probe_green:
            table_quality = "high"
            reasons.append(
                {
                    "code": "source_table_high_accuracy",
                    "message": (
                        "Source inspection detected table signals before conversion; "
                        "high-quality table extraction is enabled with a high-accuracy MinerU backend."
                    ),
                }
            )
        elif backend == "mineru-fastapi" and (table_heavy or numeric_signal_count >= 6) and fastapi_probe_green:
            table_quality = "high"
            reasons.append({"code": "high_accuracy_table_signal", "message": "Table-heavy or numeric formal content selects high table quality when FastAPI capability is not known bad."})
        elif formal_candidate or has_tables:
            table_quality = "auto"
            reasons.append({"code": "formal_auto_table_quality", "message": "Formal source or table signals select table-quality auto."})
        else:
            table_quality = "standard"
            reasons.append({"code": "standard_table_quality", "message": "No formal table signal requires high-accuracy table extraction."})

    # If a scanned/low-text PDF has no table evidence, stay compatible. A real
    # table signal should still prefer the high-quality table backend.
    if low_text_pdf_count and not requested_quality and not source_table_signal:
        table_quality = "standard"
        warnings.append(
            {
                "code": "scanned_pdf_standard_table_quality",
                "severity": "info",
                "message": "Scanned or low-text PDF detected; defaulting to standard table quality for broad compatibility.",
            }
        )

    if formal_candidate and backend == "auto":
        reasons.append({"code": "backend_auto_preserved", "message": "Backend auto is preserved so configured host routing remains authoritative."})
    if backend == "mineru-fastapi" and backend_probe_status and backend_probe_status not in {"available", "not_run"}:
        warnings.append(
            {
                "code": "mineru_fastapi_probe_not_green",
                "severity": "review",
                "message": f"MinerU FastAPI probe status is {backend_probe_status}; review before relying on high table quality.",
            }
        )
    if low_text_pdf_count:
        warnings.append(
            {
                "code": "scanned_or_low_text_pdf",
                "severity": "review",
                "message": "At least one PDF has little extractable preview text; OCR/conversion quality needs review.",
            }
        )
        if language_source in {"user_hint", "filename_hint"}:
            warnings.append(
                {
                    "code": "low_text_pdf_language_hint",
                    "severity": "info",
                    "message": f"Low-text PDF language uses {language_source} because preview text is not reliable.",
                }
            )
    if long_document:
        warnings.append(
            {
                "code": "long_document_review",
                "severity": "review",
                "message": "Large source size or page-count estimate detected; consider segment-plan/split after conversion.",
            }
        )
    if image_rich:
        warnings.append(
            {
                "code": "image_asset_review",
                "severity": "info",
                "message": "Image-rich content should be reviewed with asset-upload-plan before live KB build.",
            }
        )
    if table_quality == "high" and backend != "mineru-fastapi":
        warnings.append(
            {
                "code": "high_table_quality_requires_fastapi",
                "severity": "review",
                "message": "High table quality is only applied by the MinerU FastAPI backend.",
            }
        )

    # Respect user's explicit backend choice unless they requested a high-accuracy
    # table quality mode that requires a specific backend family.
    if requested_mineru_fastapi_backend:
        effective_mineru_fastapi_backend = requested_mineru_fastapi_backend
    elif table_quality == "high":
        effective_mineru_fastapi_backend = "hybrid-auto-engine"
    else:
        effective_mineru_fastapi_backend = "pipeline"

    recommendation = {
        "backend": backend,
        "table_quality": table_quality,
        "postprocess_profile": postprocess,
        "mineru_asset_mode": asset_mode,
        "mineru_fastapi_backend": effective_mineru_fastapi_backend,
        "allow_table_quality_fallback": bool(allow_table_quality_fallback),
        "kb_profile": profile,
    }
    confidence = "high" if not warnings else "review"
    decision = {
        "schema": PIPELINE_DECISION_SCHEMA,
        "created_at": _utc_now(),
        "policy": normalized_policy,
        "confidence": confidence,
        "features_schema": features.get("schema"),
        "signals": {
            "primary_language": language,
            "inspected_primary_language": inspected_language,
            "user_requested_language": user_language if user_language != "auto" else None,
            "language_source": language_source,
            "formal_ingest_candidate": formal_candidate,
            "table_heavy": table_heavy,
            "has_tables": has_tables,
            "image_rich": image_rich,
            "long_document": long_document,
            "scanned_or_low_text_pdf_count": low_text_pdf_count,
            "numeric_or_unit_signal_count": numeric_signal_count,
            "backend_probe_status": backend_probe_status or "not_run",
        },
        "recommendation": recommendation,
        "reasons": reasons,
        "warnings": warnings,
        "script_owned_llm_calls": 0,
        "live_mutation_enabled": False,
    }
    if decision_overrides:
        _apply_overrides(decision, decision_overrides)
    return decision


def pipeline_args_from_decision(
    decision: Mapping[str, Any],
    *,
    input_path: str,
    output_path: str,
) -> list[str]:
    """Build non-secret pipeline args from a decision."""

    recommendation = decision.get("recommendation") if isinstance(decision.get("recommendation"), Mapping) else {}
    args = [
        "pipeline",
        "--input",
        input_path,
        "--output",
        output_path,
        "--backend",
        str(recommendation.get("backend") or "auto"),
        "--table-quality",
        str(recommendation.get("table_quality") or "standard"),
        "--postprocess-profile",
        str(recommendation.get("postprocess_profile") or "chunk-markers-dense"),
    ]
    asset_mode = recommendation.get("mineru_asset_mode")
    if asset_mode:
        args.extend(["--mineru-asset-mode", str(asset_mode)])
    fastapi_backend = recommendation.get("mineru_fastapi_backend")
    if fastapi_backend:
        args.extend(["--mineru-fastapi-backend", str(fastapi_backend)])
    if recommendation.get("allow_table_quality_fallback"):
        args.append("--allow-table-quality-fallback")
    args.append("--json")
    return args


def load_decision_overrides(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("decision override must be a JSON object")
    return payload


def make_adaptive_pipeline_summary(
    *,
    features: Mapping[str, Any],
    decision: Mapping[str, Any],
    pipeline_result: Mapping[str, Any] | None = None,
    pipeline_exit_code: int | None = None,
    handoff_root: str | Path | None = None,
) -> dict[str, Any]:
    """Summarize adaptive conversion and the next offline review commands."""

    output_root = str(handoff_root) if handoff_root is not None else "<handoff>"
    pipeline_ok = bool(pipeline_result.get("ok")) if isinstance(pipeline_result, Mapping) else None
    formal_ingest = pipeline_result.get("formal_ingest") if isinstance(pipeline_result, Mapping) else {}
    readiness = formal_ingest.get("ingest_readiness") if isinstance(formal_ingest, Mapping) else None
    kb_profile = {}
    recommendation = decision.get("recommendation") if isinstance(decision.get("recommendation"), Mapping) else {}
    if isinstance(recommendation.get("kb_profile"), Mapping):
        kb_profile = dict(recommendation["kb_profile"])
    signals = decision.get("signals") if isinstance(decision.get("signals"), Mapping) else {}
    review_commands = [
        [
            "ragflow-kb-build",
            "inspect-handoff",
            "--handoff",
            output_root,
            "--report-json",
            "<run>/inspect_handoff.json",
            "--report-md",
            "<run>/inspect_handoff.md",
            "--redaction-report",
            "<run>/inspect_handoff.redaction.json",
        ],
        [
            "ragflow-kb-build",
            "asset-upload-plan",
            "--doc-manifest",
            f"{output_root}/doc_manifest.json",
            "--report-json",
            "<run>/asset_upload_plan.json",
            "--report-md",
            "<run>/asset_upload_plan.md",
            "--redaction-report",
            "<run>/asset_upload_plan.redaction.json",
        ],
        [
            "ragflow-kb-build",
            "--doc-manifest",
            f"{output_root}/doc_manifest.json",
            "--profile",
            "<reviewed-profile.json>",
            "--dry-run",
            "--json",
        ],
    ]
    warnings = list(decision.get("warnings", [])) if isinstance(decision.get("warnings"), list) else []
    decision_profile_id = str(kb_profile.get("id") or kb_profile.get("profile_id") or "")
    post_conversion_profile_id = None
    if isinstance(pipeline_result, Mapping):
        package = pipeline_result.get("handoff_package")
        if isinstance(package, Mapping):
            profile = package.get("profile_suggestions")
            if isinstance(profile, Mapping):
                suggestions = profile.get("suggestions")
                if isinstance(suggestions, list):
                    for suggestion in suggestions:
                        if not isinstance(suggestion, Mapping):
                            continue
                        suggestion_id = str(suggestion.get("id") or "")
                        if suggestion_id.startswith("table-atomic-"):
                            post_conversion_profile_id = suggestion_id
                            break
                    if post_conversion_profile_id is None and suggestions and isinstance(suggestions[0], Mapping):
                        post_conversion_profile_id = str(suggestions[0].get("id") or "")
    if (
        decision_profile_id
        and post_conversion_profile_id
        and decision_profile_id != post_conversion_profile_id
    ):
        warnings.append(
            {
                "code": "profile_language_mismatch",
                "severity": "review",
                "message": (
                    "Post-conversion profile suggestion differs from the adaptive decision; "
                    "review the KB profile before live ingestion."
                ),
            }
        )
    if pipeline_exit_code not in (None, 0):
        warnings.append(
            {
                "code": "pipeline_failed",
                "severity": "error",
                "message": "Adaptive pipeline execution failed before offline KB review.",
            }
        )
    return {
        "schema": ADAPTIVE_PIPELINE_SUMMARY_SCHEMA,
        "created_at": _utc_now(),
        "ok": pipeline_ok if pipeline_ok is not None else True,
        "pipeline_exit_code": pipeline_exit_code,
        "features_schema": features.get("schema"),
        "decision_schema": decision.get("schema"),
        "decision_confidence": decision.get("confidence"),
        "inspected_primary_language": signals.get("inspected_primary_language"),
        "decision_primary_language": signals.get("primary_language"),
        "effective_language_source": signals.get("language_source"),
        "user_requested_language": signals.get("user_requested_language"),
        "recommended_profile_id": kb_profile.get("id") or kb_profile.get("profile_id"),
        "post_conversion_profile_id": post_conversion_profile_id,
        "handoff_root": output_root,
        "ingest_readiness_status": readiness,
        "quality_gate_status": (
            pipeline_result.get("quality_gate", {}).get("status")
            if isinstance(pipeline_result, Mapping) and isinstance(pipeline_result.get("quality_gate"), Mapping)
            else None
        ),
        "review_commands": review_commands,
        "warnings": warnings,
        "script_owned_llm_calls": 0,
        "live_mutation_enabled": False,
    }


def render_pipeline_decision_markdown(report: Mapping[str, Any]) -> str:
    recommendation = report.get("recommendation") if isinstance(report.get("recommendation"), Mapping) else {}
    signals = report.get("signals") if isinstance(report.get("signals"), Mapping) else {}
    lines = [
        "# RAGFlow Adaptive Pipeline Decision",
        "",
        f"- schema: `{report.get('schema', PIPELINE_DECISION_SCHEMA)}`",
        f"- policy: `{report.get('policy', 'formal')}`",
        f"- confidence: `{report.get('confidence', 'unknown')}`",
        f"- backend: `{recommendation.get('backend', 'auto')}`",
        f"- table quality: `{recommendation.get('table_quality', 'standard')}`",
        f"- postprocess profile: `{recommendation.get('postprocess_profile', 'safe')}`",
        f"- asset mode: `{recommendation.get('mineru_asset_mode', 'markdown_only')}`",
        f"- recommended KB profile: `{(recommendation.get('kb_profile') or {}).get('id', 'none') if isinstance(recommendation.get('kb_profile'), Mapping) else 'none'}`",
        "",
        "## Signals",
        "",
    ]
    for key, value in sorted(signals.items()):
        lines.append(f"- {key}: `{value}`")
    reasons = report.get("reasons") if isinstance(report.get("reasons"), list) else []
    if reasons:
        lines.extend(["", "## Reasons", ""])
        for reason in reasons:
            if isinstance(reason, Mapping):
                lines.append(f"- `{reason.get('code')}`: {reason.get('message')}")
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            if isinstance(warning, Mapping):
                lines.append(f"- `{warning.get('code')}` ({warning.get('severity', 'review')}): {warning.get('message')}")
    lines.append("")
    return "\n".join(lines)


def render_adaptive_pipeline_summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RAGFlow Adaptive Pipeline Summary",
        "",
        f"- schema: `{report.get('schema', ADAPTIVE_PIPELINE_SUMMARY_SCHEMA)}`",
        f"- ok: `{report.get('ok')}`",
        f"- pipeline exit code: `{report.get('pipeline_exit_code')}`",
        f"- decision confidence: `{report.get('decision_confidence', 'unknown')}`",
        f"- inspected language: `{report.get('inspected_primary_language', 'unknown')}`",
        f"- decision language: `{report.get('decision_primary_language', 'unknown')}`",
        f"- effective language source: `{report.get('effective_language_source', 'unknown')}`",
        f"- user requested language: `{report.get('user_requested_language', None)}`",
        f"- recommended profile: `{report.get('recommended_profile_id', 'none')}`",
        f"- ingest readiness: `{report.get('ingest_readiness_status', 'unknown')}`",
        "",
        "## Offline Review Commands",
        "",
    ]
    for command in report.get("review_commands", []):
        if isinstance(command, list):
            lines.append("- `" + " ".join(str(part) for part in command) + "`")
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            if isinstance(warning, Mapping):
                lines.append(f"- `{warning.get('code')}` ({warning.get('severity', 'review')}): {warning.get('message')}")
    lines.append("")
    return "\n".join(lines)
