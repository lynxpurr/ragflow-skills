#!/usr/bin/env python3
"""Aggregate sanitized field-trial metrics from existing public reports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import configured_private_hosts_from_urls, sanitize_report_payload  # noqa: E402


SCHEMA = "ragflow_field_trial_metrics_v1"
FIELD_TRIAL_RECORD_SCHEMA = "ragflow_field_trial_record_v1"
RETIREMENT_MATRIX_SCHEMA = "ragflow_retirement_observation_matrix_v1"
RETIREMENT_SAMPLE_TYPES = (
    "scanned_pdf",
    "extractable_pdf",
    "image_heavy_pdf",
    "long_document",
    "complex_table",
    "office_table_document",
    "mixed_language",
    "low_quality_ocr",
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_HOME_PATH_RE = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+(?:/[^\s\"'<>]*)?")
_CONFIG_PATH_RE = re.compile(r"[^\s\"'<>]*(?:config|auth|vault)[^\s\"'<>]*\.(?:json|ya?ml|toml)")
_SUMMARY_OUTPUT_NAMES = {
    "field_trial_summary.json",
    "field_trial_summary.md",
    "field_trial_summary.redaction.json",
}
_TRIGGER_KEYS = {
    "serve": "serve",
    "local_service": "serve",
    "private bridge": "private_bridge",
    "private_bridge": "private_bridge",
    "remote conversion": "remote_conversion",
    "remote_conversion": "remote_conversion",
    "provider": "provider",
    "provider_abstraction": "provider",
    "reranker": "reranker",
    "llm": "llm_backend",
    "llm backend": "llm_backend",
    "llm_backend": "llm_backend",
    "none": "none",
}
_SAMPLE_TYPE_ALIASES = {
    "scan": "scanned_pdf",
    "scanned": "scanned_pdf",
    "scanned_document": "scanned_pdf",
    "scanned_pdf": "scanned_pdf",
    "extractable": "extractable_pdf",
    "extractable_pdf": "extractable_pdf",
    "digital_pdf": "extractable_pdf",
    "text_pdf": "extractable_pdf",
    "long": "long_document",
    "long_document": "long_document",
    "long_doc": "long_document",
    "paper": "extractable_pdf",
    "research_paper": "extractable_pdf",
    "academic_paper": "extractable_pdf",
    "contract": "extractable_pdf",
    "agreement": "extractable_pdf",
    "complex_table": "complex_table",
    "table": "complex_table",
    "tables": "complex_table",
    "image_heavy": "image_heavy_pdf",
    "image_heavy_pdf": "image_heavy_pdf",
    "many_images": "image_heavy_pdf",
    "images": "image_heavy_pdf",
    "office_table": "office_table_document",
    "office_table_document": "office_table_document",
    "office_tables": "office_table_document",
    "docx_table": "office_table_document",
    "pptx_table": "office_table_document",
    "xlsx_table": "office_table_document",
    "mixed_language": "mixed_language",
    "mixed_lang": "mixed_language",
    "multilingual": "mixed_language",
    "low_quality_ocr": "low_quality_ocr",
    "ocr": "low_quality_ocr",
    "poor_ocr": "low_quality_ocr",
    "multi_document": "multi_document_handoff",
    "multi_document_handoff": "multi_document_handoff",
    "batch": "multi_document_handoff",
    "batch_handoff": "multi_document_handoff",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            yield from _string_values(item)


def _detected_urls(payload: Any) -> list[str]:
    urls: set[str] = set()
    for value in _string_values(payload):
        urls.update(match.group(0).rstrip(".,);]") for match in _URL_RE.finditer(value))
    return sorted(urls)


def _detected_home_paths(payload: Any) -> list[str]:
    paths: set[str] = set()
    for value in _string_values(payload):
        paths.update(match.group(0).rstrip(".,);]") for match in _HOME_PATH_RE.finditer(value))
    return sorted(paths, key=len, reverse=True)


def _detected_config_paths(payload: Any) -> list[str]:
    paths: set[str] = set()
    for value in _string_values(payload):
        paths.update(match.group(0).rstrip(".,);]") for match in _CONFIG_PATH_RE.finditer(value))
    return sorted(paths, key=len, reverse=True)


def _is_redaction_sidecar(path: Path) -> bool:
    lowered = path.name.lower()
    return lowered.endswith(".redaction.json") or "redaction" in lowered


def _iter_json_paths(run_roots: Sequence[Path]) -> Iterable[Path]:
    for root in run_roots:
        if root.is_file() and root.suffix.lower() == ".json":
            if root.name not in _SUMMARY_OUTPUT_NAMES and not _is_redaction_sidecar(root):
                yield root
            continue
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            if path.name in _SUMMARY_OUTPUT_NAMES or _is_redaction_sidecar(path):
                continue
            yield path


def _relative(path: Path, roots: Sequence[Path]) -> str:
    for root in roots:
        base = root if root.is_dir() else root.parent
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return path.name


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"cannot read JSON: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "JSON report must be an object"
    return payload, None


def _schema(payload: Mapping[str, Any]) -> str:
    return str(payload.get("schema") or "")


def _quality_status(payload: Mapping[str, Any]) -> str:
    gate = payload.get("quality_gate")
    if not isinstance(gate, Mapping):
        gate = payload.get("gate")
    if not isinstance(gate, Mapping):
        return "UNKNOWN"
    return str(gate.get("status") or "UNKNOWN")


def _quality_summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    gate = payload.get("quality_gate")
    if not isinstance(gate, Mapping):
        gate = payload.get("gate")
    if not isinstance(gate, Mapping):
        return {}
    summary = gate.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _is_doc_manifest(path: Path, payload: Mapping[str, Any]) -> bool:
    return path.name == "doc_manifest.json" or (
        payload.get("version") == "0.1"
        and isinstance(payload.get("documents"), list)
        and ("source_root" in payload or "quality_gate" in payload)
    )


def _is_kb_manifest(path: Path, payload: Mapping[str, Any]) -> bool:
    return path.name == "kb_manifest.json" or _schema(payload) in {"ragflow_kb_manifest_v1"}


def _is_release_report(schema: str, path: Path) -> bool:
    lowered = path.name.lower()
    if schema in {
        "ragflow_release_hygiene_check_v1",
        "ragflow_consumer_acceptance_v1",
        "ragflow_platform_smoke_matrix_v1",
        "ragflow_build_release_check_v1",
        "ragflow_runtime_wheel_export_v1",
    }:
        return True
    return any(token in lowered for token in ("release", "hygiene", "platform", "consumer", "wheel"))


def _classify_report(path: Path, payload: Mapping[str, Any]) -> set[str]:
    schema = _schema(payload)
    classes: set[str] = set()
    if _is_doc_manifest(path, payload):
        classes.add("doc_manifest")
    if schema == "doc_quality_report_v1":
        classes.add("quality_report")
    if _is_kb_manifest(path, payload) or schema.startswith(
        (
            "ragflow_kb_",
            "ragflow_parse_",
            "ragflow_profile_",
            "ragflow_benchmark_",
            "ragflow_optimization_",
            "ragflow_handoff_",
            "ragflow_append_",
            "ragflow_cleanup_",
            "ragflow_model_provider_",
        )
    ):
        classes.add("kb_build")
    if schema.startswith(
        (
            "ragflow_query_",
            "ragflow_route_",
            "ragflow_fusion_",
            "ragflow_cross_language_",
            "ragflow_agentic_",
            "ragflow_answer_",
        )
    ) or schema in {"ragflow_citation_audit_v1", "ragflow_query_trace_v1"}:
        classes.add("query")
    if "chunks" in payload or "retrieval_status" in payload or "retrieval_status_report" in payload:
        classes.add("query")
    if _is_release_report(schema, path):
        classes.add("release")
    if schema == FIELD_TRIAL_RECORD_SCHEMA or "gated_trigger" in payload:
        classes.add("field_trial_record")
    return classes


def _runtime_partial_summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    partial = payload.get("runtime_partial_failure")
    if not isinstance(partial, Mapping):
        return {}
    summary = partial.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _runtime_metrics(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = payload.get("runtime_metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _latency_average_ms(metrics: Mapping[str, Any]) -> float | None:
    latency = metrics.get("latency_ms")
    if isinstance(latency, Mapping):
        return _safe_float(latency.get("average"))
    return None


def _normalize_trigger(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return _TRIGGER_KEYS.get(text, text if text in set(_TRIGGER_KEYS.values()) else "")


def _extract_triggers(payload: Mapping[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    for key in ("gated_trigger", "trigger", "gated_triggers"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif value is not None:
            raw_values.append(value)
    triggers = [_normalize_trigger(value) for value in raw_values]
    return sorted({trigger for trigger in triggers if trigger and trigger != "none"})


def _normalize_sample_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    return _SAMPLE_TYPE_ALIASES.get(text, "other")


def _extract_sample_types(payload: Mapping[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    for key in ("sample_type", "sample_types", "document_type", "document_types", "source_type"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif value is not None:
            raw_values.append(value)
    input_summary = payload.get("input_summary")
    if isinstance(input_summary, Mapping):
        for key in ("sample_type", "sample_types", "document_type", "document_types", "source_type"):
            value = input_summary.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif value is not None:
                raw_values.append(value)
    normalized = [_normalize_sample_type(value) for value in raw_values]
    return sorted({item for item in normalized if item})


def _root_key(path: Path, roots: Sequence[Path]) -> str:
    for index, root in enumerate(roots):
        base = root if root.is_dir() else root.parent
        try:
            path.relative_to(base)
        except ValueError:
            continue
        return str(index)
    return "unknown"


def _collect_root_sample_types(paths: Sequence[Path], roots: Sequence[Path]) -> dict[str, list[str]]:
    by_root: dict[str, set[str]] = {}
    for path in paths:
        payload, _ = _load_json(path)
        if not payload:
            continue
        if _schema(payload) != FIELD_TRIAL_RECORD_SCHEMA and "gated_trigger" not in payload:
            continue
        sample_types = _extract_sample_types(payload)
        if not sample_types:
            continue
        by_root.setdefault(_root_key(path, roots), set()).update(sample_types)
    return {key: sorted(value) for key, value in by_root.items()}


def _new_matrix_signal_counts() -> dict[str, Any]:
    return {
        "quality": {
            "report_count": 0,
            "pass_count": 0,
            "pass_with_review_count": 0,
            "blocked_count": 0,
            "warning_count": 0,
            "error_count": 0,
        },
        "assets": {
            "local_image_asset_count": 0,
            "missing_asset_issue_count": 0,
        },
        "chunking": {
            "chunk_profile_report_count": 0,
            "chunk_marker_count": 0,
            "warning_count": 0,
        },
        "hints": {
            "retrieval_hints_count": 0,
            "section_boundary_count": 0,
            "preferred_boundary_count": 0,
            "question_candidate_count": 0,
            "table_artifact_count": 0,
            "image_artifact_count": 0,
        },
        "dry_run": {
            "passed_count": 0,
            "failed_count": 0,
        },
        "live_parse": {
            "report_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "chunk_count": 0,
        },
        "query": {
            "output_count": 0,
            "zero_result_count": 0,
            "evidence_count": 0,
        },
        "cleanup": {
            "plan_count": 0,
            "execution_count": 0,
            "executed_count": 0,
        },
        "comparison": {
            "report_count": 0,
            "paired_live_ab_executed_count": 0,
        },
    }


def _new_matrix_entry(sample_type: str, *, expected: bool) -> dict[str, Any]:
    return {
        "sample_type": sample_type,
        "expected": expected,
        "status": "missing" if expected else "observed",
        "report_count": 0,
        "sources": [],
        "signals": _new_matrix_signal_counts(),
        "findings": [],
    }


def _new_retirement_matrix() -> dict[str, Any]:
    coverage = {
        sample_type: _new_matrix_entry(sample_type, expected=True)
        for sample_type in RETIREMENT_SAMPLE_TYPES
    }
    return {
        "schema": RETIREMENT_MATRIX_SCHEMA,
        "expected_sample_types": list(RETIREMENT_SAMPLE_TYPES),
        "coverage": coverage,
    }


def _matrix_entry(matrix: dict[str, Any], sample_type: str) -> dict[str, Any]:
    coverage = matrix.setdefault("coverage", {})
    if sample_type not in coverage:
        coverage[sample_type] = _new_matrix_entry(sample_type, expected=False)
    return coverage[sample_type]


def _list_count(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    return len(value) if isinstance(value, list) else 0


def _doc_manifest_image_asset_count(payload: Mapping[str, Any]) -> int:
    count = 0
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return 0
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        assets = document.get("assets")
        if not isinstance(assets, Mapping):
            continue
        images = assets.get("images")
        if isinstance(images, list):
            count += len(images)
    return count


def _append_matrix_source(entry: dict[str, Any], relative_path: str) -> None:
    sources = entry.setdefault("sources", [])
    if relative_path not in sources and len(sources) < 20:
        sources.append(relative_path)


def _update_quality_matrix(entry: dict[str, Any], payload: Mapping[str, Any]) -> None:
    quality = entry["signals"]["quality"]
    status = _quality_status(payload).upper()
    summary = _quality_summary(payload)
    quality["report_count"] += 1
    quality["warning_count"] += _safe_int(summary.get("warnings"))
    quality["error_count"] += _safe_int(summary.get("errors"))
    if status == "PASS":
        quality["pass_count"] += 1
    elif status == "PASS_WITH_REVIEW":
        quality["pass_with_review_count"] += 1
    elif status == "BLOCKED":
        quality["blocked_count"] += 1


def _update_matrix_for_payload(
    matrix: dict[str, Any],
    *,
    sample_types: Sequence[str],
    relative_path: str,
    payload: Mapping[str, Any],
    classes: set[str],
    schema: str,
) -> None:
    for sample_type in sample_types or ["unspecified"]:
        entry = _matrix_entry(matrix, sample_type)
        entry["report_count"] += 1
        _append_matrix_source(entry, relative_path)
        signals = entry["signals"]

        if "doc_manifest" in classes:
            _update_quality_matrix(entry, payload)
            signals["assets"]["local_image_asset_count"] += _doc_manifest_image_asset_count(payload)

        if "quality_report" in classes:
            _update_quality_matrix(entry, payload)
            for document in payload.get("documents", []) if isinstance(payload.get("documents"), list) else []:
                if not isinstance(document, Mapping):
                    continue
                for issue in document.get("issues", []) if isinstance(document.get("issues"), list) else []:
                    if not isinstance(issue, Mapping):
                        continue
                    issue_type = str(issue.get("issue_type") or issue.get("code") or "")
                    if "image" in issue_type and "missing" in issue_type:
                        signals["assets"]["missing_asset_issue_count"] += 1

        if schema == "ragflow_chunk_profile_report_v1":
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            signals["chunking"]["chunk_profile_report_count"] += 1
            signals["chunking"]["chunk_marker_count"] += _safe_int(summary.get("marker_count"))
            signals["chunking"]["warning_count"] += _safe_int(summary.get("warning_count"))

        if schema == "ragflow_retrieval_hints_v1":
            signals["hints"]["retrieval_hints_count"] += 1
            signals["hints"]["section_boundary_count"] += _list_count(payload, "section_boundaries")
            signals["hints"]["preferred_boundary_count"] += _list_count(payload, "preferred_boundaries")
            signals["hints"]["question_candidate_count"] += _list_count(payload, "question_candidates")
            signals["hints"]["table_artifact_count"] += _list_count(payload, "table_artifacts")
            signals["hints"]["image_artifact_count"] += _list_count(payload, "image_artifacts")

        if payload.get("dry_run") is True:
            if payload.get("ok") is False:
                signals["dry_run"]["failed_count"] += 1
            else:
                signals["dry_run"]["passed_count"] += 1

        if schema == "ragflow_parse_report_v1":
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            status = str(payload.get("status") or summary.get("status") or "").lower()
            signals["live_parse"]["report_count"] += 1
            signals["live_parse"]["chunk_count"] += _safe_int(
                summary.get("chunk_count") or summary.get("parsed_chunk_count") or payload.get("chunk_count")
            )
            if payload.get("ok") is False or status in {"failed", "error", "timeout"}:
                signals["live_parse"]["failed_count"] += 1
            else:
                signals["live_parse"]["passed_count"] += 1

        if "chunks" in payload or "retrieval_status" in payload:
            chunks = payload.get("chunks")
            evidence = payload.get("evidence")
            zero_result = isinstance(chunks, list) and not chunks
            if str(payload.get("retrieval_status") or "").lower() in {"empty", "zero_results", "no_results"}:
                zero_result = True
            signals["query"]["output_count"] += 1
            signals["query"]["zero_result_count"] += 1 if zero_result else 0
            signals["query"]["evidence_count"] += len(evidence) if isinstance(evidence, list) else 0

        if schema in {"ragflow_cleanup_plan_v1", "ragflow_optimization_cleanup_plan_v1"}:
            signals["cleanup"]["plan_count"] += 1
        if schema in {"ragflow_cleanup_execution_report_v1", "ragflow_optimization_cleanup_execution_report_v1"}:
            signals["cleanup"]["execution_count"] += 1
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            if payload.get("ok") is not False and (
                summary.get("cleanup_executed") is True
                or summary.get("deleted_target_count")
                or summary.get("deleted_count")
                or summary.get("success_count")
            ):
                signals["cleanup"]["executed_count"] += 1

        if schema == "ragflow_handoff_comparison_v1":
            signals["comparison"]["report_count"] += 1
            paired = payload.get("live_evidence", {}).get("paired_live_ab", {}) if isinstance(payload.get("live_evidence"), Mapping) else {}
            if isinstance(paired, Mapping) and paired.get("status") == "executed":
                signals["comparison"]["paired_live_ab_executed_count"] += 1


def _finalize_retirement_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    coverage = matrix.get("coverage", {}) if isinstance(matrix.get("coverage"), Mapping) else {}
    missing_expected: list[str] = []
    observed_expected = 0
    needs_review = 0
    passed = 0
    for sample_type, entry in coverage.items():
        if not isinstance(entry, dict):
            continue
        signals = entry.get("signals", {}) if isinstance(entry.get("signals"), Mapping) else {}
        quality = signals.get("quality", {}) if isinstance(signals.get("quality"), Mapping) else {}
        dry_run = signals.get("dry_run", {}) if isinstance(signals.get("dry_run"), Mapping) else {}
        live_parse = signals.get("live_parse", {}) if isinstance(signals.get("live_parse"), Mapping) else {}
        query = signals.get("query", {}) if isinstance(signals.get("query"), Mapping) else {}
        report_count = _safe_int(entry.get("report_count"))
        if report_count == 0:
            entry["status"] = "missing"
            if entry.get("expected"):
                missing_expected.append(str(sample_type))
            continue
        if entry.get("expected"):
            observed_expected += 1
        if quality.get("blocked_count") or dry_run.get("failed_count") or live_parse.get("failed_count") or query.get("zero_result_count"):
            entry["status"] = "needs_review"
            needs_review += 1
        elif (
            quality.get("pass_count")
            or quality.get("pass_with_review_count")
        ) and (
            dry_run.get("passed_count")
            or live_parse.get("passed_count")
            or query.get("output_count")
        ):
            entry["status"] = "passed"
            passed += 1
        else:
            entry["status"] = "observed"
    matrix["summary"] = {
        "expected_sample_type_count": len(RETIREMENT_SAMPLE_TYPES),
        "observed_expected_sample_type_count": observed_expected,
        "missing_expected_sample_types": missing_expected,
        "missing_expected_sample_type_count": len(missing_expected),
        "needs_review_sample_type_count": needs_review,
        "passed_sample_type_count": passed,
    }
    if missing_expected:
        status = "insufficient_samples"
    elif needs_review:
        status = "needs_review"
    else:
        status = "ready_for_review"
    matrix["retirement_assessment"] = {
        "status": status,
        "strict_paired_live_ab_required_for_live_parity": True,
        "default_live_mutation": "not_performed",
    }
    return matrix


def _append_trigger(triggers: dict[str, dict[str, Any]], track: str, reason: str, source: str) -> None:
    entry = triggers.setdefault(track, {"track": track, "count": 0, "reasons": [], "sources": []})
    entry["count"] += 1
    if reason not in entry["reasons"]:
        entry["reasons"].append(reason)
    if source not in entry["sources"]:
        entry["sources"].append(source)


def build_field_trial_metrics(
    run_roots: Sequence[str | Path],
    *,
    explicit_secrets: Sequence[str | None] | None = None,
    private_urls: Sequence[str | None] | None = None,
    home_paths: Sequence[str | None] | None = None,
    config_paths: Sequence[str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan explicit run roots and return a sanitized metrics report plus redaction sidecar."""

    roots = [Path(root).expanduser() for root in run_roots]
    findings: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    schemas: Counter[str] = Counter()
    quality_statuses: Counter[str] = Counter()
    runtime_statuses: Counter[str] = Counter()
    release_statuses: Counter[str] = Counter()
    triggers: dict[str, dict[str, Any]] = {}
    detected_urls: list[str] = []
    detected_homes: list[str] = []
    detected_configs: list[str] = []
    json_paths = list(_iter_json_paths(roots))
    root_sample_types = _collect_root_sample_types(json_paths, roots)
    retirement_matrix = _new_retirement_matrix()

    metrics = {
        "handoff": {
            "doc_manifest_count": 0,
            "document_count": 0,
            "quality_report_count": 0,
            "quality_error_count": 0,
            "quality_warning_count": 0,
            "blocked_quality_count": 0,
            "missing_asset_issue_count": 0,
            "empty_document_issue_count": 0,
        },
        "kb_build": {
            "report_count": 0,
            "runtime_failure_count": 0,
            "runtime_timeout_count": 0,
            "latency_average_samples_ms": [],
        },
        "query": {
            "report_count": 0,
            "query_output_count": 0,
            "zero_result_count": 0,
            "citation_audit_count": 0,
            "citation_audit_failure_count": 0,
            "answer_evaluation_count": 0,
            "answer_evaluation_failure_count": 0,
            "runtime_failure_count": 0,
            "runtime_timeout_count": 0,
        },
        "release": {
            "report_count": 0,
            "ok_count": 0,
            "failure_count": 0,
        },
        "cleanup": {
            "plan_count": 0,
            "execution_count": 0,
            "executed_count": 0,
            "cleanup_required_count": 0,
            "ready_target_count": 0,
            "pending_target_count": 0,
            "invalid_target_count": 0,
            "deleted_target_count": 0,
            "failed_target_count": 0,
            "post_cleanup_unverified_count": 0,
        },
        "field_trial_records": {
            "record_count": 0,
        },
    }

    for root in roots:
        if not root.exists():
            findings.append({"check": "missing_run_root", "path": str(root), "message": "run root does not exist"})
        elif not (root.is_dir() or root.is_file()):
            findings.append({"check": "invalid_run_root", "path": str(root), "message": "run root must be a directory or JSON file"})

    for path in json_paths:
        relative_path = _relative(path, roots)
        payload, error = _load_json(path)
        if payload is None:
            findings.append({"check": "unreadable_report", "path": relative_path, "message": error or "cannot load JSON"})
            continue

        detected_urls.extend(_detected_urls(payload))
        detected_homes.extend(_detected_home_paths(payload))
        detected_configs.extend(_detected_config_paths(payload))
        schema = _schema(payload)
        if schema:
            schemas[schema] += 1
        classes = _classify_report(path, payload)
        if not classes:
            classes.add("unknown")
        sample_types = (
            _extract_sample_types(payload)
            or root_sample_types.get(_root_key(path, roots), [])
            or ["unspecified"]
        )

        report_entry = {
            "path": relative_path,
            "schema": schema or None,
            "classes": sorted(classes),
            "ok": payload.get("ok") if isinstance(payload.get("ok"), bool) else None,
        }
        reports.append(report_entry)
        _update_matrix_for_payload(
            retirement_matrix,
            sample_types=sample_types,
            relative_path=relative_path,
            payload=payload,
            classes=classes,
            schema=schema,
        )

        if "doc_manifest" in classes:
            documents = payload.get("documents") if isinstance(payload.get("documents"), list) else []
            metrics["handoff"]["doc_manifest_count"] += 1
            metrics["handoff"]["document_count"] += len(documents)
            status = _quality_status(payload)
            quality_statuses[status] += 1
            if status == "BLOCKED":
                metrics["handoff"]["blocked_quality_count"] += 1

        if "quality_report" in classes:
            metrics["handoff"]["quality_report_count"] += 1
            summary = _quality_summary(payload)
            metrics["handoff"]["quality_error_count"] += _safe_int(summary.get("errors"))
            metrics["handoff"]["quality_warning_count"] += _safe_int(summary.get("warnings"))
            if _quality_status(payload) == "BLOCKED":
                metrics["handoff"]["blocked_quality_count"] += 1
            for document in payload.get("documents", []) if isinstance(payload.get("documents"), list) else []:
                if not isinstance(document, Mapping):
                    continue
                for issue in document.get("issues", []) if isinstance(document.get("issues"), list) else []:
                    if not isinstance(issue, Mapping):
                        continue
                    issue_type = str(issue.get("issue_type") or issue.get("code") or "")
                    if "image" in issue_type and "missing" in issue_type:
                        metrics["handoff"]["missing_asset_issue_count"] += 1
                    if "empty" in issue_type:
                        metrics["handoff"]["empty_document_issue_count"] += 1

        if "kb_build" in classes:
            metrics["kb_build"]["report_count"] += 1
            partial_summary = _runtime_partial_summary(payload)
            if partial_summary:
                runtime_statuses[str(partial_summary.get("status") or "unknown")] += 1
                metrics["kb_build"]["runtime_failure_count"] += _safe_int(partial_summary.get("failure_count"))
                metrics["kb_build"]["runtime_timeout_count"] += _safe_int(partial_summary.get("timeout_count"))
            latency = _latency_average_ms(_runtime_metrics(payload))
            if latency is not None:
                metrics["kb_build"]["latency_average_samples_ms"].append(latency)

        if "query" in classes:
            metrics["query"]["report_count"] += 1
            if "chunks" in payload or "retrieval_status" in payload:
                metrics["query"]["query_output_count"] += 1
                zero_result = False
                chunks = payload.get("chunks")
                if isinstance(chunks, list) and not chunks:
                    zero_result = True
                if str(payload.get("retrieval_status") or "").lower() in {"empty", "zero_results", "no_results"}:
                    zero_result = True
                if zero_result:
                    metrics["query"]["zero_result_count"] += 1
            if schema == "ragflow_citation_audit_v1":
                metrics["query"]["citation_audit_count"] += 1
                if payload.get("ok") is False:
                    metrics["query"]["citation_audit_failure_count"] += 1
            if schema == "ragflow_answer_evaluation_report_v1":
                metrics["query"]["answer_evaluation_count"] += 1
                if payload.get("ok") is False or str(payload.get("status") or "").upper() == "FAIL":
                    metrics["query"]["answer_evaluation_failure_count"] += 1
            partial_summary = _runtime_partial_summary(payload)
            if partial_summary:
                runtime_statuses[str(partial_summary.get("status") or "unknown")] += 1
                metrics["query"]["runtime_failure_count"] += _safe_int(partial_summary.get("failure_count"))
                metrics["query"]["runtime_timeout_count"] += _safe_int(partial_summary.get("timeout_count"))

        if "release" in classes:
            metrics["release"]["report_count"] += 1
            if payload.get("ok") is False:
                metrics["release"]["failure_count"] += 1
                release_statuses["failed"] += 1
            elif payload.get("ok") is True:
                metrics["release"]["ok_count"] += 1
                release_statuses["ok"] += 1
            else:
                release_statuses["unknown"] += 1

        if schema in {"ragflow_cleanup_plan_v1", "ragflow_optimization_cleanup_plan_v1"}:
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            metrics["cleanup"]["plan_count"] += 1
            metrics["cleanup"]["cleanup_required_count"] += _safe_int(summary.get("target_count"))
            metrics["cleanup"]["ready_target_count"] += _safe_int(summary.get("ready_target_count"))
            metrics["cleanup"]["pending_target_count"] += _safe_int(summary.get("pending_target_count"))
            metrics["cleanup"]["invalid_target_count"] += _safe_int(summary.get("invalid_target_count"))

        if schema in {"ragflow_cleanup_execution_report_v1", "ragflow_optimization_cleanup_execution_report_v1"}:
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            verification = (
                payload.get("post_cleanup_verification")
                if isinstance(payload.get("post_cleanup_verification"), Mapping)
                else {}
            )
            cleanup_executed = payload.get("ok") is not False and (
                summary.get("cleanup_executed") is True
                or summary.get("deleted_target_count")
                or summary.get("deleted_count")
                or summary.get("success_count")
            )
            metrics["cleanup"]["execution_count"] += 1
            metrics["cleanup"]["executed_count"] += 1 if cleanup_executed else 0
            metrics["cleanup"]["deleted_target_count"] += _safe_int(
                summary.get("deleted_target_count") or summary.get("deleted_count") or summary.get("success_count")
            )
            metrics["cleanup"]["failed_target_count"] += _safe_int(
                summary.get("failed_target_count") or summary.get("failed_count")
            )
            verification_status = str(verification.get("status") or "").lower()
            if cleanup_executed and verification_status not in {"verified", "passed"}:
                metrics["cleanup"]["post_cleanup_unverified_count"] += 1

        if "field_trial_record" in classes:
            metrics["field_trial_records"]["record_count"] += 1
            for trigger in _extract_triggers(payload):
                _append_trigger(triggers, trigger, "field trial record requested gated work", relative_path)

    if metrics["handoff"]["blocked_quality_count"]:
        _append_trigger(triggers, "handoff_quality", "blocked handoff quality gate observed", "quality reports")
    if metrics["query"]["zero_result_count"]:
        _append_trigger(triggers, "query_quality", "zero-result query output observed", "query reports")
    if metrics["query"]["citation_audit_failure_count"] or metrics["query"]["answer_evaluation_failure_count"]:
        _append_trigger(triggers, "query_quality", "answer or citation review failure observed", "query reports")
    if metrics["release"]["failure_count"]:
        _append_trigger(triggers, "release_health", "release-facing report failure observed", "release reports")

    recognized_count = sum(1 for report in reports if report["classes"] != ["unknown"])
    raw_report = {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "ok": not findings,
        "summary": {
            "run_root_count": len(roots),
            "json_report_count": len(reports),
            "recognized_report_count": recognized_count,
            "unknown_report_count": len(reports) - recognized_count,
            "finding_count": len(findings),
            "triggered_track_count": len(triggers),
        },
        "run_roots": [str(root) for root in roots],
        "schema_counts": _counter_payload(schemas),
        "quality_gate_status_counts": _counter_payload(quality_statuses),
        "runtime_partial_failure_status_counts": _counter_payload(runtime_statuses),
        "release_status_counts": _counter_payload(release_statuses),
        "metrics": metrics,
        "retirement_observation_matrix": _finalize_retirement_matrix(retirement_matrix),
        "gated_triggers": [triggers[key] for key in sorted(triggers)],
        "reports": reports,
        "findings": findings,
    }
    all_urls = [*(private_urls or []), *detected_urls]
    all_home_paths = [*(home_paths or []), *detected_homes, *[str(root) for root in roots]]
    all_config_paths = [*(config_paths or []), *detected_configs]
    sanitized, redaction_report = sanitize_report_payload(
        raw_report,
        explicit_secrets=explicit_secrets,
        private_hosts=configured_private_hosts_from_urls(all_urls),
        home_paths=all_home_paths,
        config_paths=all_config_paths,
    )
    return sanitized, redaction_report


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), Mapping) else {}
    handoff = metrics.get("handoff", {}) if isinstance(metrics.get("handoff"), Mapping) else {}
    kb_build = metrics.get("kb_build", {}) if isinstance(metrics.get("kb_build"), Mapping) else {}
    query = metrics.get("query", {}) if isinstance(metrics.get("query"), Mapping) else {}
    release = metrics.get("release", {}) if isinstance(metrics.get("release"), Mapping) else {}
    cleanup = metrics.get("cleanup", {}) if isinstance(metrics.get("cleanup"), Mapping) else {}
    matrix = (
        report.get("retirement_observation_matrix", {})
        if isinstance(report.get("retirement_observation_matrix"), Mapping)
        else {}
    )
    matrix_summary = matrix.get("summary", {}) if isinstance(matrix.get("summary"), Mapping) else {}
    assessment = (
        matrix.get("retirement_assessment", {})
        if isinstance(matrix.get("retirement_assessment"), Mapping)
        else {}
    )
    lines = [
        "# RAGFlow Field Trial Metrics",
        "",
        f"- schema: `{report.get('schema', SCHEMA)}`",
        f"- reports scanned: `{summary.get('json_report_count', 0)}`",
        f"- recognized reports: `{summary.get('recognized_report_count', 0)}`",
        f"- findings: `{summary.get('finding_count', 0)}`",
        f"- triggered tracks: `{summary.get('triggered_track_count', 0)}`",
        "",
        "## Metrics",
        "",
        "| Area | Key Metrics |",
        "| --- | --- |",
        "| Handoff | doc manifests: `{}`, documents: `{}`, blocked quality: `{}`, warnings: `{}` |".format(
            handoff.get("doc_manifest_count", 0),
            handoff.get("document_count", 0),
            handoff.get("blocked_quality_count", 0),
            handoff.get("quality_warning_count", 0),
        ),
        "| KB Build | reports: `{}`, runtime failures: `{}`, runtime timeouts: `{}` |".format(
            kb_build.get("report_count", 0),
            kb_build.get("runtime_failure_count", 0),
            kb_build.get("runtime_timeout_count", 0),
        ),
        "| Query | reports: `{}`, zero results: `{}`, citation failures: `{}`, answer eval failures: `{}` |".format(
            query.get("report_count", 0),
            query.get("zero_result_count", 0),
            query.get("citation_audit_failure_count", 0),
            query.get("answer_evaluation_failure_count", 0),
        ),
        "| Release | reports: `{}`, ok: `{}`, failed: `{}` |".format(
            release.get("report_count", 0),
            release.get("ok_count", 0),
            release.get("failure_count", 0),
        ),
        "| Cleanup | plans: `{}`, executions: `{}`, deleted targets: `{}`, pending targets: `{}`, unverified executions: `{}` |".format(
            cleanup.get("plan_count", 0),
            cleanup.get("execution_count", 0),
            cleanup.get("deleted_target_count", 0),
            cleanup.get("pending_target_count", 0),
            cleanup.get("post_cleanup_unverified_count", 0),
        ),
        "",
        "## Retirement Observation Matrix",
        "",
        f"- schema: `{matrix.get('schema', RETIREMENT_MATRIX_SCHEMA)}`",
        f"- status: `{assessment.get('status', 'unknown')}`",
        f"- observed expected sample types: `{matrix_summary.get('observed_expected_sample_type_count', 0)}` / `{matrix_summary.get('expected_sample_type_count', len(RETIREMENT_SAMPLE_TYPES))}`",
        f"- missing expected sample types: `{matrix_summary.get('missing_expected_sample_type_count', 0)}`",
        f"- needs-review sample types: `{matrix_summary.get('needs_review_sample_type_count', 0)}`",
        "",
        "| Sample Type | Status | Reports | Quality Pass/Review/Blocked | Dry-Run Pass/Fail | Parse Pass/Fail | Query Zero/Total |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    coverage = matrix.get("coverage", {}) if isinstance(matrix.get("coverage"), Mapping) else {}
    ordered_sample_types = [*RETIREMENT_SAMPLE_TYPES, *sorted(key for key in coverage if key not in RETIREMENT_SAMPLE_TYPES)]
    for sample_type in ordered_sample_types:
        entry = coverage.get(sample_type)
        if not isinstance(entry, Mapping):
            continue
        signals = entry.get("signals", {}) if isinstance(entry.get("signals"), Mapping) else {}
        quality = signals.get("quality", {}) if isinstance(signals.get("quality"), Mapping) else {}
        dry_run = signals.get("dry_run", {}) if isinstance(signals.get("dry_run"), Mapping) else {}
        live_parse = signals.get("live_parse", {}) if isinstance(signals.get("live_parse"), Mapping) else {}
        query = signals.get("query", {}) if isinstance(signals.get("query"), Mapping) else {}
        lines.append(
            "| `{}` | `{}` | `{}` | `{}/{}/{}` | `{}/{}` | `{}/{}` | `{}/{}` |".format(
                sample_type,
                entry.get("status", "missing"),
                entry.get("report_count", 0),
                quality.get("pass_count", 0),
                quality.get("pass_with_review_count", 0),
                quality.get("blocked_count", 0),
                dry_run.get("passed_count", 0),
                dry_run.get("failed_count", 0),
                live_parse.get("passed_count", 0),
                live_parse.get("failed_count", 0),
                query.get("zero_result_count", 0),
                query.get("output_count", 0),
            )
        )
    lines.extend(
        [
        "",
        "## Gated Triggers",
        "",
        ]
    )
    triggers = report.get("gated_triggers") if isinstance(report.get("gated_triggers"), list) else []
    if not triggers:
        lines.append("- none")
    for trigger in triggers:
        if not isinstance(trigger, Mapping):
            continue
        reasons = "; ".join(str(reason) for reason in trigger.get("reasons", []) if str(reason))
        lines.append(f"- `{trigger.get('track')}` count `{trigger.get('count', 0)}`: {reasons}")
    if report.get("findings"):
        lines.extend(["", "## Findings", ""])
        for finding in report["findings"]:
            if isinstance(finding, Mapping):
                lines.append(f"- `{finding.get('check')}` `{finding.get('path')}`: {finding.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate sanitized field-trial metrics from explicit run directories")
    parser.add_argument("run_roots", nargs="+", help="Run directory or JSON report path to scan")
    parser.add_argument("--report-json", help="Optional JSON metrics output path")
    parser.add_argument("--report-md", help="Optional Markdown metrics output path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar output path")
    parser.add_argument("--explicit-secret", action="append", default=[], help="Secret literal to redact; repeatable")
    parser.add_argument("--private-url", action="append", default=[], help="Private endpoint URL used for host redaction; repeatable")
    parser.add_argument("--home-path", action="append", default=[], help="Private home/work path to redact; repeatable")
    parser.add_argument("--config-path", action="append", default=[], help="Private config path to redact; repeatable")
    args = parser.parse_args(argv)

    report, redaction_report = build_field_trial_metrics(
        args.run_roots,
        explicit_secrets=args.explicit_secret,
        private_urls=args.private_url,
        home_paths=args.home_path,
        config_paths=args.config_path,
    )
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_json:
        path = Path(args.report_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered_json, encoding="utf-8")
    if args.report_md:
        path = Path(args.report_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")
    if args.redaction_report:
        path = Path(args.redaction_report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redaction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(rendered_json, end="")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
