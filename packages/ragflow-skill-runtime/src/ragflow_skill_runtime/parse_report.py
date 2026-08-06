"""Offline parser performance and KB parse-state reports."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .kb_build import (
    BuildError,
    MULTIMODAL_KB_MANIFEST_SCHEMA,
    extract_document_id,
    extract_document_items,
    extract_document_name,
    kb_refresh_report_document_status_payload,
    load_kb_refresh_report,
    normalize_document_state,
    parse_state_failed,
    parse_state_succeeded,
    summarize_kb_refresh_observed_state,
)
from .manifests import KbDocumentEntry, KbManifest, ManifestError, load_kb_manifest
from .performance_warnings import (
    chunk_count_performance_warnings,
    performance_warning_report,
    phase_timing_performance_warnings,
)
from .profiles import ChunkProfile, ProfileError, SUPPORTED_PARSER_KEYS, load_profile


PARSE_REPORT_SCHEMA = "ragflow_parse_report_v1"

TIMING_RE = re.compile(
    r"\b(?P<phase>parse|parser|layout|ocr|table|chunk|embedding|embed|image|vision)"
    r"[\w\s:./-]{0,80}?"
    r"(?P<duration>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ms|milliseconds?|s|sec|secs|seconds?|m|min|mins|minutes?)\b",
    re.IGNORECASE,
)

ERROR_WORDS = ("[error]", " error", "exception", "traceback", " failed", "failure")
WARNING_WORDS = ("[warn]", " warning", " warn ", "timeout", "slow")
DETAIL_DOCUMENT_COUNT_KEYS = (
    "document_count",
    "documents_count",
    "doc_count",
    "doc_num",
    "document_num",
    "total_documents",
    "total_doc_count",
)
DETAIL_CHUNK_COUNT_KEYS = (
    "chunk_count",
    "chunks_count",
    "chunk_num",
    "total_chunks",
    "total_chunk_count",
)
DETAIL_NESTED_KEYS = ("dataset", "kb", "knowledgebase", "knowledge_base", "detail", "details", "summary")
PARSER_CONFIG_KEYS = ("parser_config", "parserConfig")
VISUAL_PARSER_KEY_PARTS = ("layout", "visual", "ocr", "image", "table", "vision")


class ParseReportError(RuntimeError):
    """Raised when parse-report inputs cannot be loaded."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ParseReportError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ParseReportError(f"file is not valid JSON: {source}") from exc


def _read_json_mapping(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ParseReportError(f"file must contain a JSON object: {Path(path)}")
    return payload


def _load_multimodal_manifest(path: str | Path) -> dict[str, Any]:
    payload = _read_json_mapping(path)
    if payload.get("schema") != MULTIMODAL_KB_MANIFEST_SCHEMA:
        raise ParseReportError(f"multimodal KB manifest schema must be {MULTIMODAL_KB_MANIFEST_SCHEMA}: {path}")
    payload["_source_path"] = str(path)
    return payload


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "none"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None


def _issue(
    *,
    severity: str,
    code: str,
    message: str,
    field: str | None = None,
    document_id: str | None = None,
    source: str | None = None,
    recommendation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if field:
        payload["field"] = field
    if document_id:
        payload["document_id"] = document_id
    if source:
        payload["source"] = source
    if recommendation:
        payload["recommendation"] = recommendation
    return payload


def _path_keys(*values: str | None) -> list[str]:
    keys: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        path = Path(text)
        candidates = {text, text.replace("\\", "/"), path.name}
        if path.name:
            candidates.add(path.name.lower())
        keys.extend(candidate.lower() for candidate in candidates if candidate)
    return keys


def _extract_status_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    observed_documents = payload.get("observed_documents")
    if isinstance(observed_documents, list):
        return [item for item in observed_documents if isinstance(item, Mapping)]
    items = extract_document_items(payload)
    if items:
        return items

    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        return []
    for key in ("docs", "documents", "items", "list", "document_states"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            output: list[Mapping[str, Any]] = []
            for document_id, item in value.items():
                if not isinstance(item, Mapping):
                    continue
                copied = dict(item)
                copied.setdefault("id", str(document_id))
                output.append(copied)
            return output
    return []


def load_document_status_payload(path: str | Path) -> dict[str, Any]:
    """Load a user-supplied document status payload for offline parse reporting."""

    payload = _read_json(path)
    items = _extract_status_items(payload)
    if not items:
        raise ParseReportError(
            "documents JSON must contain a document list in data.docs, data.documents, "
            "documents, items, list, document_states, or as a top-level list"
        )
    return {"payload": payload, "items": items}


def _index_document_statuses(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    indexed: list[dict[str, Any]] = []
    for item in items:
        document_id = extract_document_id(item)
        state = normalize_document_state(item, document_id=document_id)
        if not state.get("document_id") and document_id:
            state["document_id"] = document_id
        name = extract_document_name(item)
        entry = {
            "document_id": str(state.get("document_id") or ""),
            "name": name,
            "state": state,
            "raw": dict(item),
        }
        indexed.append(entry)
        if entry["document_id"]:
            by_id[entry["document_id"]] = entry
        for key in _path_keys(name, str(item.get("markdown_path") or ""), str(item.get("source_path") or "")):
            by_name.setdefault(key, entry)
    return {"items": indexed, "by_id": by_id, "by_name": by_name}


def _match_status_entry(document: KbDocumentEntry, index: Mapping[str, Any]) -> dict[str, Any] | None:
    by_id = index.get("by_id", {})
    if isinstance(by_id, Mapping) and document.document_id in by_id:
        item = by_id.get(document.document_id)
        return item if isinstance(item, dict) else None

    by_name = index.get("by_name", {})
    if not isinstance(by_name, Mapping):
        return None
    for key in _path_keys(document.markdown_path, document.source_path):
        item = by_name.get(key)
        if isinstance(item, dict):
            return item
    return None


def _detail_count_from_mapping(payload: Mapping[str, Any], keys: Iterable[str]) -> int | None:
    roots: list[Mapping[str, Any]] = [payload]
    data = payload.get("data")
    if isinstance(data, Mapping):
        roots.append(data)
        for nested_key in DETAIL_NESTED_KEYS:
            nested = data.get(nested_key)
            if isinstance(nested, Mapping):
                roots.append(nested)
    for nested_key in DETAIL_NESTED_KEYS:
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            roots.append(nested)

    for root in roots:
        for key in keys:
            value = _as_int(root.get(key))
            if value is not None:
                return value
    return None


def _extract_detail_counts(payload: Any) -> dict[str, int | None]:
    if not isinstance(payload, Mapping):
        return {"document_count": None, "chunk_count": None}
    document_count = _detail_count_from_mapping(payload, DETAIL_DOCUMENT_COUNT_KEYS)
    if document_count is None:
        data = payload.get("data", payload)
        if isinstance(data, Mapping):
            document_count = _as_int(data.get("total"))
    return {
        "document_count": document_count,
        "chunk_count": _detail_count_from_mapping(payload, DETAIL_CHUNK_COUNT_KEYS),
    }


def _extract_effective_parser_config(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None

    roots: list[tuple[str, Mapping[str, Any]]] = [("documents_json", payload)]
    data = payload.get("data")
    if isinstance(data, Mapping):
        roots.append(("documents_json.data", data))
        for nested_key in DETAIL_NESTED_KEYS:
            nested = data.get(nested_key)
            if isinstance(nested, Mapping):
                roots.append((f"documents_json.data.{nested_key}", nested))
    for nested_key in DETAIL_NESTED_KEYS:
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            roots.append((f"documents_json.{nested_key}", nested))

    for prefix, root in roots:
        for key in PARSER_CONFIG_KEYS:
            value = root.get(key)
            if isinstance(value, Mapping):
                return dict(value), f"{prefix}.{key}"
        parser = root.get("parser")
        if isinstance(parser, Mapping):
            for key in PARSER_CONFIG_KEYS:
                value = parser.get(key)
                if isinstance(value, Mapping):
                    return dict(value), f"{prefix}.parser.{key}"
    return None, None


def _multimodal_manifest_summary(
    multimodal_manifest: Mapping[str, Any] | None,
    *,
    kb_manifest: KbManifest,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not multimodal_manifest:
        return {
            "available": False,
            "source": None,
            "markdown_document_count": len(kb_manifest.documents),
            "visual_document_count": 0,
            "thumbnail_document_count": 0,
            "vlm_observed_document_count": 0,
            "visual_chunk_count": 0,
        }, []

    summary = multimodal_manifest.get("summary", {}) if isinstance(multimodal_manifest.get("summary"), Mapping) else {}
    visual_documents = multimodal_manifest.get("visual_documents")
    if not isinstance(visual_documents, list):
        visual_documents = []
    visual_chunk_count = sum(_as_int(item.get("chunk_count")) or 0 for item in visual_documents if isinstance(item, Mapping))
    thumbnail_count = sum(
        1
        for item in visual_documents
        if isinstance(item, Mapping)
        and isinstance(item.get("thumbnail"), Mapping)
        and bool(item["thumbnail"].get("url"))
    )
    vlm_count = sum(1 for item in visual_documents if isinstance(item, Mapping) and item.get("vlm_status"))
    manifest_dataset = multimodal_manifest.get("dataset", {}) if isinstance(multimodal_manifest.get("dataset"), Mapping) else {}
    issues: list[dict[str, Any]] = []
    if manifest_dataset.get("id") and manifest_dataset.get("id") != kb_manifest.dataset.id:
        issues.append(
            _issue(
                severity="warning",
                code="multimodal_manifest_dataset_mismatch",
                field="multimodal_manifest.dataset.id",
                message="Multimodal KB manifest dataset ID differs from kb_manifest dataset ID.",
                recommendation="Regenerate the multimodal manifest from the same dataset before trusting visual parse evidence.",
            )
        )

    def summary_count(key: str, fallback: int) -> int:
        value = _as_int(summary.get(key))
        return fallback if value is None else value

    return {
        "available": True,
        "source": multimodal_manifest.get("_source_path"),
        "markdown_document_count": summary_count("markdown_document_count", len(kb_manifest.documents)),
        "visual_document_count": summary_count("visual_document_count", len(visual_documents)),
        "thumbnail_document_count": summary_count("thumbnail_document_count", thumbnail_count),
        "vlm_observed_document_count": summary_count("vlm_observed_document_count", vlm_count),
        "visual_chunk_count": visual_chunk_count,
    }, issues


def _state_label(state: Mapping[str, Any]) -> str:
    if parse_state_failed(state):
        return "failed"
    if parse_state_succeeded(state):
        return "succeeded"
    status = str(state.get("status") or "").strip()
    return "pending" if status else "unknown"


def _effective_chunk_count(manifest_chunk_count: int | None, observed_chunk_count: Any) -> int | None:
    observed = _as_int(observed_chunk_count)
    if observed is not None:
        return observed
    return manifest_chunk_count


def _manifest_markdown_stats(kb_manifest: KbManifest) -> dict[str, Any]:
    existing_sizes: list[int] = []
    missing = 0
    for document in kb_manifest.documents:
        if not document.markdown_path:
            continue
        path = Path(document.markdown_path)
        if not path.exists() or not path.is_file():
            missing += 1
            continue
        existing_sizes.append(path.stat().st_size)
    largest = max(existing_sizes) if existing_sizes else 0
    return {
        "existing_markdown_count": len(existing_sizes),
        "missing_markdown_count": missing,
        "largest_markdown_bytes": largest,
        "large_markdown_count": sum(1 for size in existing_sizes if size >= 1_000_000),
    }


def _load_parser_config(path: str | Path) -> dict[str, Any]:
    payload = _read_json_mapping(path)
    if isinstance(payload.get("parser_config"), Mapping):
        return dict(payload["parser_config"])
    return dict(payload)


def _load_profile_from_manifest(kb_manifest: KbManifest) -> ChunkProfile | None:
    if not kb_manifest.profile:
        return None
    try:
        return ChunkProfile.from_dict(kb_manifest.profile)
    except (ProfileError, TypeError, ValueError):
        return None


def _public_parser_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in config.items() if not str(key).startswith("__")}


def _diff_parser_configs(requested: Mapping[str, Any], effective: Mapping[str, Any]) -> dict[str, Any]:
    requested_public = _public_parser_config(requested)
    effective_public = _public_parser_config(effective)
    requested_keys = set(requested_public)
    effective_keys = set(effective_public)
    changed = sorted(key for key in requested_keys & effective_keys if requested_public.get(key) != effective_public.get(key))
    return {
        "missing_effective_keys": sorted(requested_keys - effective_keys),
        "extra_effective_keys": sorted(effective_keys - requested_keys),
        "changed_values": [
            {"key": key, "requested": requested_public.get(key), "effective": effective_public.get(key)}
            for key in changed
        ],
        "drift": bool((requested_keys - effective_keys) or (effective_keys - requested_keys) or changed),
    }


def _profile_visibility_report(
    *,
    kb_manifest: KbManifest,
    requested_profile: ChunkProfile | None,
    effective_parser_config: Mapping[str, Any],
    effective_source: str,
    parser_config_path: str | Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_profile = _load_profile_from_manifest(kb_manifest)
    requested = requested_profile or manifest_profile
    requested_config = dict(requested.parser_config) if requested else {}
    effective_config = dict(effective_parser_config)
    drift = _diff_parser_configs(requested_config, effective_config) if requested_config or effective_config else {
        "missing_effective_keys": [],
        "extra_effective_keys": [],
        "changed_values": [],
        "drift": False,
    }
    unsupported = sorted(
        key
        for key in effective_config
        if not str(key).startswith("__") and key not in SUPPORTED_PARSER_KEYS
    )
    requested_profile_payload = asdict(requested) if requested else None
    if requested_profile_payload:
        requested_profile_payload["id"] = requested_profile_payload.pop("profile_id")
    effective_profile_payload = asdict(manifest_profile) if manifest_profile else None
    if effective_profile_payload:
        effective_profile_payload["id"] = effective_profile_payload.pop("profile_id")
    report = {
        "available": bool(requested_config or effective_config),
        "advisory_only": True,
        "mutation": "none",
        "requested_source": "profile" if requested_profile else "kb_manifest.profile" if manifest_profile else "none",
        "effective_source": effective_source,
        "requested_profile": requested_profile_payload,
        "effective_profile": effective_profile_payload,
        "requested_parser_config": requested_config,
        "effective_parser_config": effective_config,
        "parser_config_override": str(parser_config_path) if parser_config_path else None,
        "unsupported_effective_keys": unsupported,
        "drift": drift,
    }
    issues: list[dict[str, Any]] = []
    if unsupported:
        issues.append(
            _issue(
                severity="warning",
                code="effective_parser_config_unsupported_keys",
                field="profile_visibility.effective_parser_config",
                message="Effective parser settings include keys outside the public profile contract.",
                recommendation="Treat unsupported parser settings as advisory and verify them through a profile lint or live parse report before relying on them.",
            )
        )
    if drift["drift"]:
        issues.append(
            _issue(
                severity="warning",
                code="requested_effective_profile_drift",
                field="profile_visibility.drift",
                message="Requested parser settings differ from the effective parser settings available in current-suite artifacts.",
                recommendation="Review requested versus effective settings before using this build as profile-parity evidence.",
            )
        )
    return report, issues


def _parser_settings_report(
    *,
    kb_manifest: KbManifest,
    profile_path: str | Path | None,
    parser_config_path: str | Path | None,
    markdown_stats: Mapping[str, Any],
) -> tuple[dict[str, Any], ChunkProfile | None, ChunkProfile | None]:
    profile: ChunkProfile | None = None
    profile_source = "none"
    profile_load_issue: dict[str, Any] | None = None
    if profile_path:
        try:
            profile = load_profile(profile_path)
            profile_source = str(profile_path)
        except ProfileError as exc:
            profile_load_issue = _issue(
                severity="warning",
                code="profile_load_failed",
                message=str(exc),
                source=str(profile_path),
                recommendation="Provide a valid chunk profile or omit --profile to use the manifest profile.",
            )
    if profile is None:
        profile = _load_profile_from_manifest(kb_manifest)
        profile_source = "kb_manifest.profile" if profile is not None else "none"

    requested_profile = profile if profile_path and profile_load_issue is None else None
    effective_profile = _load_profile_from_manifest(kb_manifest)
    parser_config: dict[str, Any] = dict(profile.parser_config) if profile else {}
    parser_config_source = profile_source
    parser_config_load_issue: dict[str, Any] | None = None
    if parser_config_path:
        try:
            parser_config = _load_parser_config(parser_config_path)
            parser_config_source = str(parser_config_path)
        except ParseReportError as exc:
            parser_config_load_issue = _issue(
                severity="warning",
                code="parser_config_load_failed",
                message=str(exc),
                source=str(parser_config_path),
                recommendation="Provide a JSON object or an object with parser_config.",
            )

    issues: list[dict[str, Any]] = []
    for optional_issue in (profile_load_issue, parser_config_load_issue):
        if optional_issue:
            issues.append(optional_issue)

    auto_questions = _as_int(parser_config.get("auto_questions"))
    if auto_questions and auto_questions > 0:
        issues.append(
            _issue(
                severity="warning",
                code="auto_questions_enabled",
                field="parser_config.auto_questions",
                message=f"auto_questions is enabled at {auto_questions}; this can slow parsing and add LLM-backed cost.",
                recommendation="Disable auto_questions for baseline builds, then benchmark a small value before rollout.",
            )
        )

    auto_keywords = _as_int(parser_config.get("auto_keywords"))
    if auto_keywords is not None and auto_keywords > 10:
        issues.append(
            _issue(
                severity="warning",
                code="auto_keywords_excessive",
                field="parser_config.auto_keywords",
                message=f"auto_keywords is {auto_keywords}; high keyword counts can slow parsing and pollute retrieval.",
                recommendation="Try 0-5 keywords first and keep increases tied to benchmark deltas.",
            )
        )
    elif auto_keywords is not None and auto_keywords > 0:
        issues.append(
            _issue(
                severity="info",
                code="auto_keywords_enabled",
                field="parser_config.auto_keywords",
                message=f"auto_keywords is enabled at {auto_keywords}.",
                recommendation="Keep keyword generation only when benchmark reports show a retrieval gain.",
            )
        )

    visual_keys = []
    unsupported_keys = []
    for key, value in sorted(parser_config.items()):
        lower = str(key).lower()
        if any(part in lower for part in VISUAL_PARSER_KEY_PARTS) and _is_truthy(value):
            visual_keys.append(key)
            issues.append(
                _issue(
                    severity="warning",
                    code="visual_or_layout_parser_enabled",
                    field=f"parser_config.{key}",
                    message=f"{key} is enabled; visual, OCR, image, or table processing can dominate parse time.",
                    recommendation="Use this setting only for corpora that need layout/image/table evidence.",
                )
            )
        if key.startswith("__"):
            continue
        if key not in SUPPORTED_PARSER_KEYS:
            unsupported_keys.append(key)
            issues.append(
                _issue(
                    severity="warning",
                    code="unsupported_parser_key",
                    field=f"parser_config.{key}",
                    message="parser_config key is outside the public profile contract.",
                    recommendation="Keep provider-specific keys only when a probe or benchmark requires them.",
                )
            )
        if "context" in lower:
            numeric = _as_int(value)
            if numeric is not None and numeric > 2000:
                issues.append(
                    _issue(
                        severity="warning",
                        code="large_parser_context",
                        field=f"parser_config.{key}",
                        message=f"{key} is {numeric}; large image/table context windows can slow parsing.",
                        recommendation="Reduce context limits unless grounded QA needs larger table or image spans.",
                    )
                )

    if visual_keys and int(markdown_stats.get("large_markdown_count") or 0) > 0:
        issues.append(
            _issue(
                severity="warning",
                code="visual_layout_large_markdown",
                message="Visual/layout parser settings are enabled while local Markdown stats include large files.",
                recommendation="Run a small parse benchmark or split large files before enabling visual layout processing.",
            )
        )

    profile_payload = asdict(profile) if profile else None
    if profile_payload:
        profile_payload["id"] = profile_payload.pop("profile_id")
    return {
        "source": parser_config_source,
        "profile_source": profile_source,
        "profile": profile_payload,
        "parser_config": parser_config,
        "expensive_setting_count": sum(1 for item in issues if item["severity"] == "warning"),
        "unsupported_keys": unsupported_keys,
        "visual_or_layout_keys": visual_keys,
        "issues": issues,
    }, requested_profile, effective_profile


def _duration_ms(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized.startswith("ms") or normalized.startswith("millisecond"):
        return value
    if normalized in {"m", "min", "mins"} or normalized.startswith("minute"):
        return value * 60_000.0
    return value * 1000.0


def _line_has_error(line: str) -> bool:
    lower = f" {line.lower()}"
    if "no error" in lower or "without error" in lower:
        return False
    return any(word in lower for word in ERROR_WORDS)


def _line_has_warning(line: str) -> bool:
    lower = f" {line.lower()} "
    return any(word in lower for word in WARNING_WORDS)


def _parse_logs(paths: Iterable[str | Path]) -> dict[str, Any]:
    totals: dict[str, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
    error_lines: list[dict[str, Any]] = []
    warning_lines: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    lines_scanned = 0

    for path_value in paths:
        path = Path(path_value)
        file_errors = 0
        file_warnings = 0
        file_timings = 0
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError as exc:
            raise ParseReportError(f"parse log not found: {path}") from exc
        for line_number, line in enumerate(lines, start=1):
            lines_scanned += 1
            if _line_has_error(line):
                file_errors += 1
                if len(error_lines) < 20:
                    error_lines.append({"path": str(path), "line": line_number, "message": line.strip()[:240]})
            elif _line_has_warning(line):
                file_warnings += 1
                if len(warning_lines) < 20:
                    warning_lines.append({"path": str(path), "line": line_number, "message": line.strip()[:240]})

            for match in TIMING_RE.finditer(line):
                phase = match.group("phase").lower()
                if phase == "parser":
                    phase = "parse"
                if phase == "embed":
                    phase = "embedding"
                duration = _as_float(match.group("duration"))
                if duration is None:
                    continue
                duration_ms = _duration_ms(duration, match.group("unit"))
                totals[phase]["count"] = int(totals[phase]["count"]) + 1
                totals[phase]["total_ms"] = float(totals[phase]["total_ms"]) + duration_ms
                totals[phase]["max_ms"] = max(float(totals[phase]["max_ms"]), duration_ms)
                file_timings += 1

        files.append(
            {
                "path": str(path),
                "lines": len(lines),
                "error_count": file_errors,
                "warning_count": file_warnings,
                "timing_count": file_timings,
            }
        )

    phase_timings = []
    for phase, values in sorted(totals.items()):
        count = int(values["count"])
        total_ms = round(float(values["total_ms"]), 3)
        max_ms = round(float(values["max_ms"]), 3)
        phase_timings.append(
            {
                "phase": phase,
                "count": count,
                "total_ms": total_ms,
                "max_ms": max_ms,
                "avg_ms": round(total_ms / count, 3) if count else 0.0,
            }
        )
    slowest = max(phase_timings, key=lambda item: item["total_ms"], default=None)
    return {
        "log_count": len(files),
        "files": files,
        "lines_scanned": lines_scanned,
        "error_count": sum(file["error_count"] for file in files),
        "warning_count": sum(file["warning_count"] for file in files),
        "error_lines": error_lines,
        "warning_lines": warning_lines,
        "phase_timings": phase_timings,
        "slowest_phase": slowest,
    }


def _empty_parse_log_summary() -> dict[str, Any]:
    return {
        "log_count": 0,
        "files": [],
        "lines_scanned": 0,
        "error_count": 0,
        "warning_count": 0,
        "error_lines": [],
        "warning_lines": [],
        "phase_timings": [],
        "slowest_phase": None,
    }


def _document_states_report(
    *,
    kb_manifest: KbManifest,
    document_status_index: Mapping[str, Any] | None,
    documents_json_supplied: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    report_items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    matched_observed_ids: set[str] = set()
    matched_manifest_count = 0
    status_counts: Counter[str] = Counter()
    effective_chunk_total = 0
    manifest_chunk_total = 0
    observed_chunk_total = 0
    observed_chunk_documents = 0
    chunk_mismatches = 0

    for document in kb_manifest.documents:
        manifest_state = {
            "document_id": document.document_id,
            "status": document.status or "",
            "chunk_count": document.chunk_count,
        }
        matched = _match_status_entry(document, document_status_index) if document_status_index else None
        if matched:
            matched_manifest_count += 1
            matched_id = str(matched.get("document_id") or "")
            if matched_id:
                matched_observed_ids.add(matched_id)
        observed_state = matched.get("state") if matched else None
        if not isinstance(observed_state, Mapping):
            observed_state = None

        effective_state = observed_state or manifest_state
        label = _state_label(effective_state)
        status_counts[label] += 1

        observed_chunk_count = observed_state.get("chunk_count") if observed_state else None
        effective_chunks = _effective_chunk_count(document.chunk_count, observed_chunk_count)
        if effective_chunks is not None:
            effective_chunk_total += effective_chunks
        if document.chunk_count is not None:
            manifest_chunk_total += document.chunk_count
        observed_chunks = _as_int(observed_chunk_count)
        if observed_chunks is not None:
            observed_chunk_documents += 1
            observed_chunk_total += observed_chunks

        document_issues: list[str] = []
        if documents_json_supplied and not matched:
            document_issues.append("status_missing")
            issues.append(
                _issue(
                    severity="warning",
                    code="document_status_missing",
                    document_id=document.document_id,
                    message="Document from kb_manifest was not found in supplied document status JSON.",
                    recommendation="Export a fresh RAGFlow document list or ensure document IDs/names match the manifest.",
                )
            )
        if label == "failed":
            document_issues.append("parse_failed")
            message = "Document parse state indicates failure."
            progress_msg = str(effective_state.get("progress_msg") or "").strip()
            if progress_msg:
                message = f"{message} Progress message: {progress_msg[:160]}"
            issues.append(
                _issue(
                    severity="warning",
                    code="document_parse_failed",
                    document_id=document.document_id,
                    message=message,
                    recommendation="Inspect the supplied parse logs or RAGFlow progress message before retrying parse.",
                )
            )
        elif label in {"pending", "unknown"}:
            document_issues.append("parse_not_complete")
            issues.append(
                _issue(
                    severity="warning",
                    code="document_parse_not_complete",
                    document_id=document.document_id,
                    message="Document parse state is not completed.",
                    recommendation="Wait for parse completion or export a fresher document status JSON.",
                )
            )

        if label == "succeeded" and effective_chunks == 0:
            document_issues.append("zero_chunks")
            issues.append(
                _issue(
                    severity="warning",
                    code="succeeded_with_zero_chunks",
                    document_id=document.document_id,
                    message="Document appears parsed but has zero chunks.",
                    recommendation="Review source Markdown size, parser profile, and RAGFlow chunking status.",
                )
            )

        if document.chunk_count is not None and observed_chunks is not None and document.chunk_count != observed_chunks:
            chunk_mismatches += 1
            document_issues.append("chunk_count_mismatch")
            issues.append(
                _issue(
                    severity="warning",
                    code="document_chunk_count_mismatch",
                    document_id=document.document_id,
                    message=(
                        f"kb_manifest chunk_count={document.chunk_count} differs from supplied "
                        f"document status chunk_count={observed_chunks}."
                    ),
                    recommendation="Refresh the manifest or document list before comparing benchmark results.",
                )
            )

        report_items.append(
            {
                "document_id": document.document_id,
                "source_path": document.source_path,
                "markdown_path": document.markdown_path,
                "manifest_status": document.status,
                "manifest_chunk_count": document.chunk_count,
                "observed_status": observed_state.get("status") if observed_state else None,
                "observed_chunk_count": observed_chunks,
                "progress": observed_state.get("progress") if observed_state else None,
                "progress_msg": observed_state.get("progress_msg") if observed_state else "",
                "parse_state": label,
                "effective_chunk_count": effective_chunks,
                "issues": document_issues,
            }
        )

    observed_items = []
    if document_status_index:
        raw_items = document_status_index.get("items")
        if isinstance(raw_items, list):
            observed_items = [item for item in raw_items if isinstance(item, Mapping)]
    unmatched_observed = [
        item
        for item in observed_items
        if str(item.get("document_id") or "") and str(item.get("document_id") or "") not in matched_observed_ids
    ]

    summary = {
        "manifest_document_count": len(kb_manifest.documents),
        "matched_status_document_count": matched_manifest_count,
        "unmatched_status_document_count": len(unmatched_observed),
        "status_counts": dict(sorted(status_counts.items())),
        "manifest_chunk_total": manifest_chunk_total,
        "observed_chunk_total": observed_chunk_total if observed_chunk_documents else None,
        "effective_chunk_total": effective_chunk_total,
        "observed_chunk_document_count": observed_chunk_documents,
        "chunk_mismatch_count": chunk_mismatches,
        "failed_document_count": status_counts["failed"],
        "pending_document_count": status_counts["pending"] + status_counts["unknown"],
        "zero_chunk_document_count": sum(1 for item in report_items if item["effective_chunk_count"] == 0),
    }
    return report_items, issues, summary


def _chunk_consistency_report(
    *,
    document_summary: Mapping[str, Any],
    detail_counts: Mapping[str, int | None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def add_check(name: str, left_label: str, left_value: int | None, right_label: str, right_value: int | None) -> None:
        if left_value is None or right_value is None:
            checks.append({"name": name, "status": "not_available", left_label: left_value, right_label: right_value})
            return
        status = "match" if left_value == right_value else "mismatch"
        checks.append({"name": name, "status": status, left_label: left_value, right_label: right_value})
        if status == "mismatch":
            issues.append(
                _issue(
                    severity="warning",
                    code=f"{name}_mismatch",
                    message=f"{left_label}={left_value} differs from {right_label}={right_value}.",
                    recommendation="Treat count fields as stale until a fresh list/detail export agrees.",
                )
            )

    add_check(
        "manifest_vs_observed_chunks",
        "manifest_chunk_total",
        _as_int(document_summary.get("manifest_chunk_total")),
        "observed_chunk_total",
        _as_int(document_summary.get("observed_chunk_total")),
    )
    add_check(
        "detail_vs_observed_documents",
        "detail_document_count",
        detail_counts.get("document_count"),
        "observed_document_count",
        _as_int(document_summary.get("matched_status_document_count")),
    )
    add_check(
        "detail_vs_observed_chunks",
        "detail_chunk_count",
        detail_counts.get("chunk_count"),
        "observed_chunk_total",
        _as_int(document_summary.get("observed_chunk_total")),
    )

    mismatch_count = sum(1 for check in checks if check["status"] == "mismatch")
    return {
        "detail_counts": dict(detail_counts),
        "checks": checks,
        "mismatch_count": mismatch_count,
        "status": "REVIEW" if mismatch_count else "PASS",
    }, issues


def _issues_from_parse_logs(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if int(summary.get("error_count") or 0) > 0:
        issues.append(
            _issue(
                severity="warning",
                code="parse_log_error_lines",
                message=f"Supplied parse logs contain {summary.get('error_count')} error-like lines.",
                recommendation="Inspect parse log excerpts before trusting parse success or latency numbers.",
            )
        )
    if not summary.get("phase_timings") and int(summary.get("log_count") or 0) > 0:
        issues.append(
            _issue(
                severity="info",
                code="parse_log_no_phase_timings",
                message="Supplied parse logs were read but no parse phase timing patterns were found.",
                recommendation="Include logs with phase names and durations such as layout 1.2s or embedding 420ms.",
            )
        )
    return issues


def _next_steps(issues: Iterable[Mapping[str, Any]], *, documents_json_supplied: bool, parse_logs_supplied: bool) -> list[str]:
    codes = {str(issue.get("code") or "") for issue in issues}
    steps: list[str] = []
    if "observed_state_document_list_api_zero_documents" in codes:
        steps.append(
            "Treat the refresh observed-state as a version-specific read-only API limitation when build, parse, or chunk evidence exists elsewhere."
        )
    if not documents_json_supplied:
        steps.append("Export a read-only RAGFlow document-list/status JSON to compare live parse state with kb_manifest.")
    if not parse_logs_supplied:
        steps.append("Attach parser progress logs when investigating slow parse phases.")
    if {"document_parse_failed", "parse_log_error_lines"} & codes:
        steps.append("Review failed document IDs and log excerpts before retrying parse from the host UI or API.")
    if {"auto_questions_enabled", "auto_keywords_excessive", "visual_or_layout_parser_enabled"} & codes:
        steps.append("Benchmark a cheaper parser profile before enabling expensive enrichment or visual layout settings broadly.")
    if any(code.endswith("_mismatch") or code == "document_chunk_count_mismatch" for code in codes):
        steps.append("Refresh manifest/detail/list sidecars before using chunk counts for benchmark comparisons.")
    if "succeeded_with_zero_chunks" in codes:
        steps.append("Inspect zero-chunk documents for empty Markdown, unsupported file conversion output, or parser chunking limits.")
    if not steps:
        steps.append("Keep this report with the KB build artifacts as the offline parse-health baseline.")
    return steps


def create_parse_report(
    *,
    kb_manifest_path: str | Path,
    documents_json_path: str | Path | None = None,
    observed_state_path: str | Path | None = None,
    multimodal_kb_manifest_path: str | Path | None = None,
    parse_log_paths: Iterable[str | Path] | None = None,
    profile_path: str | Path | None = None,
    parser_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create an offline parse-state and parser-performance report."""

    try:
        kb_manifest = load_kb_manifest(kb_manifest_path)
    except ManifestError as exc:
        raise ParseReportError(str(exc)) from exc
    if documents_json_path and observed_state_path:
        raise ParseReportError("use either --documents-json or --observed-state, not both")

    inputs = {
        "kb_manifest": str(kb_manifest_path),
        "documents_json": str(documents_json_path) if documents_json_path else None,
        "observed_state": str(observed_state_path) if observed_state_path else None,
        "multimodal_kb_manifest": str(multimodal_kb_manifest_path) if multimodal_kb_manifest_path else None,
        "parse_logs": [str(path) for path in (parse_log_paths or [])],
        "profile": str(profile_path) if profile_path else None,
        "parser_config": str(parser_config_path) if parser_config_path else None,
    }

    multimodal_manifest = _load_multimodal_manifest(multimodal_kb_manifest_path) if multimodal_kb_manifest_path else None
    observed_state_report: dict[str, Any] | None = None
    observed_state_summary = {"available": False, "schema": None, "source": None, "summary": {}}
    observed_state_issue_codes: set[str] = set()
    documents_payload: Any = None
    document_status_index = None
    detail_counts = {"document_count": None, "chunk_count": None}
    api_effective_parser_config: dict[str, Any] | None = None
    api_effective_parser_config_source: str | None = None
    if documents_json_path:
        loaded = load_document_status_payload(documents_json_path)
        documents_payload = loaded["payload"]
        document_status_index = _index_document_statuses(loaded["items"])
        detail_counts = _extract_detail_counts(documents_payload)
        api_effective_parser_config, api_effective_parser_config_source = _extract_effective_parser_config(
            documents_payload
        )
    elif observed_state_path:
        try:
            observed_state_report = load_kb_refresh_report(observed_state_path)
        except BuildError as exc:
            raise ParseReportError(str(exc)) from exc
        observed_state_summary = summarize_kb_refresh_observed_state(
            observed_state_report,
            dataset_id=kb_manifest.dataset.id,
        )
        issue_codes = observed_state_summary.get("issue_codes")
        if isinstance(issue_codes, list):
            observed_state_issue_codes = {str(code) for code in issue_codes if code}
        documents_payload = kb_refresh_report_document_status_payload(observed_state_report)
        observed_items = _extract_status_items(documents_payload)
        document_status_index = _index_document_statuses(observed_items)
        detail_counts = _extract_detail_counts(documents_payload)
        api_effective_parser_config, api_effective_parser_config_source = _extract_effective_parser_config(
            documents_payload
        )

    parse_log_list = list(parse_log_paths or [])
    parse_log_summary = _parse_logs(parse_log_list) if parse_log_list else _empty_parse_log_summary()
    markdown_stats = _manifest_markdown_stats(kb_manifest)
    parser_settings, requested_profile, effective_profile = _parser_settings_report(
        kb_manifest=kb_manifest,
        profile_path=profile_path,
        parser_config_path=parser_config_path,
        markdown_stats=markdown_stats,
    )
    if parser_config_path:
        visibility_effective_config = parser_settings.get("parser_config", {})
        visibility_effective_source = str(parser_settings.get("source") or "none")
    elif api_effective_parser_config is not None:
        visibility_effective_config = api_effective_parser_config
        visibility_effective_source = str(api_effective_parser_config_source or "documents_json.parser_config")
    elif effective_profile is not None:
        visibility_effective_config = effective_profile.parser_config
        visibility_effective_source = "kb_manifest.profile"
    else:
        visibility_effective_config = parser_settings.get("parser_config", {})
        visibility_effective_source = str(parser_settings.get("source") or "none")
    profile_visibility, profile_visibility_issues = _profile_visibility_report(
        kb_manifest=kb_manifest,
        requested_profile=requested_profile,
        effective_parser_config=visibility_effective_config,
        effective_source=visibility_effective_source,
        parser_config_path=parser_config_path,
    )
    document_states, document_issues, document_summary = _document_states_report(
        kb_manifest=kb_manifest,
        document_status_index=document_status_index,
        documents_json_supplied=bool(documents_json_path),
    )
    multimodal_summary, multimodal_issues = _multimodal_manifest_summary(
        multimodal_manifest,
        kb_manifest=kb_manifest,
    )
    chunk_consistency, chunk_issues = _chunk_consistency_report(
        document_summary=document_summary,
        detail_counts=detail_counts,
    )
    performance_warnings = performance_warning_report(
        [
            *phase_timing_performance_warnings(parse_log_summary.get("phase_timings") or []),
            *chunk_count_performance_warnings(
                total_chunk_count=document_summary.get("effective_chunk_total"),
                documents=document_states,
            ),
        ]
    )

    issues = []
    if "document_list_api_zero_documents" in observed_state_issue_codes:
        issues.append(
            _issue(
                severity="warning",
                code="observed_state_document_list_api_zero_documents",
                message=(
                    "The supplied refresh-report observed-state recorded a zero-document document-list response "
                    "despite separate manifest parse/chunk evidence."
                ),
                recommendation=(
                    "Treat this as a version-specific read-only API limitation; use build, parse, smoke, or chunk "
                    "evidence for lifecycle decisions until a compatible document-list endpoint is available."
                ),
            )
        )
    if not kb_manifest.documents:
        issues.append(
            _issue(
                severity="warning",
                code="kb_manifest_has_no_documents",
                message="kb_manifest contains no documents.",
                recommendation="Run parse-report after a build manifest with document IDs is available.",
            )
        )
    if not documents_json_path and not observed_state_path:
        issues.append(
            _issue(
                severity="info",
                code="document_status_json_missing",
                message="No document status JSON was supplied; report uses kb_manifest statuses only.",
                recommendation=(
                    "Provide --observed-state from refresh-report or --documents-json with a read-only "
                    "exported document list for live-state comparison."
                ),
            )
        )
    issues.extend(document_issues)
    issues.extend(multimodal_issues)
    issues.extend(chunk_issues)
    issues.extend(parser_settings["issues"])
    issues.extend(profile_visibility_issues)
    issues.extend(_issues_from_parse_logs(parse_log_summary))
    issues.extend(performance_warnings["warnings"])

    issue_counts = Counter(str(issue.get("severity") or "info") for issue in issues)
    status = "FAIL" if issue_counts.get("error", 0) else "REVIEW" if issues else "PASS"
    ok = not issue_counts.get("error", 0)

    return {
        "ok": ok,
        "schema": PARSE_REPORT_SCHEMA,
        "created_at": _now(),
        "status": status,
        "advisory_only": True,
        "mutation": "none",
        "execution": {
            "status": "not_run",
            "ragflow_calls": 0,
            "db_calls": 0,
            "redis_calls": 0,
            "docker_calls": 0,
            "system_service_calls": 0,
        },
        "inputs": inputs,
        "dataset": {
            "id": kb_manifest.dataset.id,
            "name": kb_manifest.dataset.name,
            "manifest_version": kb_manifest.version,
            "ragflow_base_url": kb_manifest.ragflow_base_url,
        },
        "summary": {
            **document_summary,
            "visual_document_count": multimodal_summary["visual_document_count"],
            "thumbnail_document_count": multimodal_summary["thumbnail_document_count"],
            "vlm_observed_document_count": multimodal_summary["vlm_observed_document_count"],
            "visual_chunk_count": multimodal_summary["visual_chunk_count"],
            "performance_warning_count": performance_warnings["summary"]["warning_count"],
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "document_states": document_states,
        "observed_state": observed_state_summary,
        "multimodal_manifest": multimodal_summary,
        "chunk_consistency": chunk_consistency,
        "parser_settings": parser_settings,
        "profile_visibility": profile_visibility,
        "markdown_stats": markdown_stats,
        "parse_log_summary": parse_log_summary,
        "performance_warnings": performance_warnings,
        "issues": issues,
        "next_steps": _next_steps(
            issues,
            documents_json_supplied=bool(documents_json_path or observed_state_path),
            parse_logs_supplied=bool(parse_log_list),
        ),
    }


def _md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_parse_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown summary for a parse report."""

    dataset = report.get("dataset", {}) if isinstance(report.get("dataset"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    chunk_consistency = report.get("chunk_consistency", {}) if isinstance(report.get("chunk_consistency"), Mapping) else {}
    parser_settings = report.get("parser_settings", {}) if isinstance(report.get("parser_settings"), Mapping) else {}
    profile_visibility = report.get("profile_visibility", {}) if isinstance(report.get("profile_visibility"), Mapping) else {}
    parse_logs = report.get("parse_log_summary", {}) if isinstance(report.get("parse_log_summary"), Mapping) else {}
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    document_states = report.get("document_states", []) if isinstance(report.get("document_states"), list) else []
    next_steps = report.get("next_steps", []) if isinstance(report.get("next_steps"), list) else []

    lines = [
        "# RAGFlow Parse Report",
        "",
        f"- Schema: `{report.get('schema', PARSE_REPORT_SCHEMA)}`",
        f"- Status: `{report.get('status', 'UNKNOWN')}`",
        f"- Dataset: `{dataset.get('name', '')}` (`{dataset.get('id', '')}`)",
        f"- Mutation: `{report.get('mutation', 'none')}`",
        "",
        "## Summary",
        "",
        f"- Manifest documents: {summary.get('manifest_document_count', 0)}",
        f"- Failed documents: {summary.get('failed_document_count', 0)}",
        f"- Pending/unknown documents: {summary.get('pending_document_count', 0)}",
        f"- Zero-chunk documents: {summary.get('zero_chunk_document_count', 0)}",
        f"- Effective chunks: {summary.get('effective_chunk_total', 0)}",
        f"- Visual documents: {summary.get('visual_document_count', 0)}",
        f"- Visual chunks: {summary.get('visual_chunk_count', 0)}",
        f"- Visual thumbnails: {summary.get('thumbnail_document_count', 0)}",
        f"- VLM-observed documents: {summary.get('vlm_observed_document_count', 0)}",
        f"- Chunk consistency: `{chunk_consistency.get('status', 'PASS')}`",
        "",
        "## Document States",
        "",
        "| Document | Parse State | Manifest Chunks | Observed Chunks | Issues |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in document_states[:25]:
        if not isinstance(item, Mapping):
            continue
        issue_text = ", ".join(str(value) for value in item.get("issues", []) if value) or "-"
        lines.append(
            "| "
            f"{_md_escape(item.get('document_id'))} | "
            f"{_md_escape(item.get('parse_state'))} | "
            f"{_md_escape(item.get('manifest_chunk_count'))} | "
            f"{_md_escape(item.get('observed_chunk_count'))} | "
            f"{_md_escape(issue_text)} |"
        )
    if len(document_states) > 25:
        lines.append(f"| ... | {len(document_states) - 25} additional documents omitted |  |  |  |")

    lines.extend(
        [
            "",
            "## Parser Settings",
            "",
            f"- Source: `{parser_settings.get('source', 'none')}`",
            f"- Warning settings: {parser_settings.get('expensive_setting_count', 0)}",
            f"- Unsupported keys: {', '.join(parser_settings.get('unsupported_keys', []) or []) or '-'}",
            f"- Visual/layout keys: {', '.join(parser_settings.get('visual_or_layout_keys', []) or []) or '-'}",
            f"- Requested/effective drift: {profile_visibility.get('drift', {}).get('drift', False) if isinstance(profile_visibility.get('drift'), Mapping) else False}",
            f"- Effective unsupported keys: {', '.join(profile_visibility.get('unsupported_effective_keys', []) or []) or '-'}",
            "",
            "## Parse Logs",
            "",
            f"- Logs: {parse_logs.get('log_count', 0)}",
            f"- Lines scanned: {parse_logs.get('lines_scanned', 0)}",
            f"- Error-like lines: {parse_logs.get('error_count', 0)}",
            f"- Warning-like lines: {parse_logs.get('warning_count', 0)}",
        ]
    )
    slowest = parse_logs.get("slowest_phase")
    if isinstance(slowest, Mapping):
        lines.append(f"- Slowest phase: `{slowest.get('phase')}` total {slowest.get('total_ms')} ms")

    phase_timings = parse_logs.get("phase_timings", [])
    if isinstance(phase_timings, list) and phase_timings:
        lines.extend(["", "| Phase | Count | Total ms | Max ms |", "| --- | ---: | ---: | ---: |"])
        for item in phase_timings:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_md_escape(item.get('phase'))} | "
                f"{_md_escape(item.get('count'))} | "
                f"{_md_escape(item.get('total_ms'))} | "
                f"{_md_escape(item.get('max_ms'))} |"
            )

    lines.extend(["", "## Issues", ""])
    if issues:
        for issue in issues[:30]:
            if not isinstance(issue, Mapping):
                continue
            target = f" `{issue.get('document_id')}`" if issue.get("document_id") else ""
            lines.append(
                f"- `{issue.get('severity', 'info')}` `{issue.get('code', 'issue')}`{target}: "
                f"{issue.get('message', '')}"
            )
        if len(issues) > 30:
            lines.append(f"- ... {len(issues) - 30} additional issues omitted.")
    else:
        lines.append("- No issues found.")

    lines.extend(["", "## Next Steps", ""])
    for step in next_steps:
        lines.append(f"- {step}")

    lines.extend(
        [
            "",
            "## Execution Guard",
            "",
            "- RAGFlow calls: 0",
            "- DB calls: 0",
            "- Redis calls: 0",
            "- Docker calls: 0",
            "- System service calls: 0",
        ]
    )
    return "\n".join(lines) + "\n"
