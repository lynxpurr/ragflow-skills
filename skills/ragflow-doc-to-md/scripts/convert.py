#!/usr/bin/env python3
"""Convert documents into a Markdown handoff bundle."""

from __future__ import annotations

from pathlib import Path
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from typing import Any


def bootstrap_runtime() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    ConvertedDocument,
    DEFAULT_HARD_MAX_CHARS,
    DEFAULT_MIN_SEGMENT_CHARS,
    DEFAULT_SOFT_MAX_CHARS,
    DocConvertError,
    DocQualityError,
    DocPostprocessError,
    DocSegmentError,
    QualityDocument,
    convert_source_to_markdown,
    create_rich_handoff_package,
    configured_private_hosts_from_urls,
    discover_source_documents,
    extract_markdown_title,
    HandoffError,
    load_doc_manifest_payload,
    load_skill_config,
    make_doc_manifest_payload,
    make_doc_runtime_report_payload,
    make_handoff_comparison_payload,
    make_ragflow_ingest_plan_payload,
    make_quality_report_payload,
    materialize_segments,
    plan_markdown_segmentation,
    postprocess_handoff,
    postprocess_single_markdown,
    probe_conversion_backends,
    quality_documents_from_manifest,
    render_backend_probe_markdown,
    render_backend_warmup_markdown,
    render_doc_runtime_markdown,
    render_handoff_comparison_markdown,
    render_quality_markdown,
    safe_markdown_name,
    sanitize_report_payload,
    semantic_rename_markdown_images,
    sha256_file,
    write_doc_ingest_readiness_report,
    write_formal_handoff_manifest,
    warmup_conversion_backend,
)


BACKEND_CHOICES = {
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
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_ASSIGNMENT_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;\"']+)"
)
DOC_SPLIT_CHECKPOINT_SCHEMA = "ragflow_doc_split_checkpoint_v1"
THIN_PREVIEW_HANDOFF_MODE = "thin_preview"
FORMAL_INGEST_HANDOFF_MODE = "formal_ingest"
POSTPROCESS_PROFILE_CHOICES = [
    "none",
    "safe",
    "ocr",
    "chunk-markers",
    "chunk-markers-conservative",
    "chunk-markers-dense",
    "chunk-markers-ragflux-like",
]
FORMAL_PREP_SOURCE_EXTENSIONS = {
    ".bmp",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".tif",
    ".tiff",
    ".webp",
    ".xls",
    ".xlsx",
}


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_digest(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _thin_preview_handoff_advisory(sources: list[Any]) -> list[dict[str, Any]]:
    candidate_extensions = sorted(
        {
            source.path.suffix.lower()
            for source in sources
            if getattr(source, "path", None) is not None
            and source.path.suffix.lower() in FORMAL_PREP_SOURCE_EXTENSIONS
        }
    )
    severity = "review" if candidate_extensions else "info"
    message = (
        "This output is a thin preview handoff. For formal RAGFlow ingestion, use "
        "`ragflow-doc-to-md pipeline` so postprocess, rich sidecars, retrieval hints, "
        "and the non-secret ingest plan are generated together."
    )
    return [
        {
            "code": "formal_ingest_pipeline_recommended",
            "severity": severity,
            "message": message,
            "recommended_command": [
                "ragflow-doc-to-md",
                "pipeline",
                "--input",
                "<source-docs>",
                "--output",
                "<handoff>",
                "--postprocess-profile",
                "chunk-markers",
                "--json",
            ],
            "formal_candidate_input": bool(candidate_extensions),
            "formal_candidate_extensions": candidate_extensions,
        }
    ]


def _formal_ingest_handoff_advisory() -> list[dict[str, Any]]:
    return [
        {
            "code": "inspect_and_dry_run_before_live_build",
            "severity": "info",
            "message": (
                "Formal ingest handoff generated. Run `ragflow-kb-build inspect-handoff` "
                "and a dry-run build before any live RAGFlow mutation."
            ),
            "recommended_commands": [
                [
                    "ragflow-kb-build",
                    "inspect-handoff",
                    "--handoff",
                    "<handoff>",
                    "--report-json",
                    "<run>/handoff_inspection.json",
                    "--report-md",
                    "<run>/handoff_inspection.md",
                ],
                [
                    "ragflow-kb-build",
                    "--doc-manifest",
                    "<handoff>/doc_manifest.json",
                    "--kb-name",
                    "<kb-name>",
                    "--profile",
                    "<reviewed-profile.json>",
                    "--dry-run",
                    "--json",
                ],
            ],
        }
    ]


def _chunk_marker_count(postprocess_report: dict[str, Any]) -> int:
    summary = postprocess_report.get("summary", {}) if isinstance(postprocess_report.get("summary"), dict) else {}
    rule_counts = summary.get("rule_counts", {}) if isinstance(summary.get("rule_counts"), dict) else {}
    return sum(int(value or 0) for key, value in rule_counts.items() if str(key).startswith("chunk_markers."))


def _formal_ingest_readiness_signals(
    *,
    postprocess_report: dict[str, Any],
    postprocess_profile: str,
    package_payload: dict[str, Any],
    ingest_plan_name: str,
    retrieval_hints_name: str,
    chunk_profile_report_name: str | None = None,
    ingest_readiness_name: str | None = None,
    ingest_readiness_status: str | None = None,
    ingest_readiness_score: int | None = None,
) -> dict[str, Any]:
    rich_sidecars = [
        "metadata",
        "artifact_index",
        "profile_suggestions",
        "retrieval_hints",
        "assistant_profile",
        "assistant_test_plan",
        "formal_handoff_manifest",
        "package_readme",
    ]
    return {
        "chunk_markers": {
            "enabled": postprocess_profile.startswith("chunk-markers"),
            "generated": _chunk_marker_count(postprocess_report) > 0,
            "profile": postprocess_profile,
            "marker_count": _chunk_marker_count(postprocess_report),
            "chunk_profile_report": chunk_profile_report_name,
        },
        "rich_sidecars": {
            "generated": True,
            "complete": all(bool(package_payload.get(name)) for name in rich_sidecars),
            "files": {name: package_payload.get(name) for name in rich_sidecars},
        },
        "retrieval_hints": {
            "generated": bool(package_payload.get("retrieval_hints")),
            "path": retrieval_hints_name,
            "section_boundary_count": package_payload.get("retrieval_hint_count"),
        },
        "ragflow_ingest_plan": {
            "generated": True,
            "path": ingest_plan_name,
            "stores_api_credentials": False,
            "mutation_default": "dry_run_first",
        },
        "ingest_readiness": {
            "generated": bool(ingest_readiness_name),
            "path": ingest_readiness_name,
            "status": ingest_readiness_status,
            "advisory_score": ingest_readiness_score,
        },
        "formal_handoff_manifest": {
            "generated": bool(package_payload.get("formal_handoff_manifest")),
            "path": package_payload.get("formal_handoff_manifest"),
            "schema": package_payload.get("formal_handoff_manifest_schema"),
            "package_hash": package_payload.get("formal_handoff_package_hash"),
        },
        "recommended_next_steps": {
            "inspect_handoff": "ragflow-kb-build inspect-handoff --handoff <handoff>",
            "dry_run": "ragflow-kb-build --doc-manifest <handoff>/doc_manifest.json --dry-run",
            "live_mutation_requires_user_approval": True,
        },
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _render_simple_yaml(value: Any, *, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_render_simple_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_render_simple_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def _write_yaml_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_simple_yaml(payload) + "\n", encoding="utf-8")


def _safe_handoff_sidecar_name(value: str | None, *, label: str) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise DocConvertError(f"{label} must be a relative handoff path without '..'")
    return path.as_posix()


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _remote_api_key(args: argparse.Namespace, config) -> str | None:
    return args.remote_api_key or config.doc_to_md.remote_api_key


def _remote_url(args: argparse.Namespace, config) -> str | None:
    return args.remote_url or config.doc_to_md.remote_url


def _backend(args: argparse.Namespace, config) -> str:
    backend = args.backend or config.doc_to_md.backend or "auto"
    if backend not in BACKEND_CHOICES:
        allowed = ", ".join(sorted(BACKEND_CHOICES))
        raise DocConvertError(f"DOC_TO_MD_BACKEND must be one of: {allowed}")
    return backend


def _remote_timeout(args: argparse.Namespace) -> float:
    value = args.remote_timeout
    if value in (None, ""):
        return 120.0
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be a number of seconds") from exc
    if timeout <= 0:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be greater than zero")
    return timeout


def _mineru_asset_mode(args: argparse.Namespace, config) -> str:
    mode = _config_or_arg(args, "mineru_asset_mode", config.mineru.asset_mode, "markdown_only")
    normalized = str(mode or "markdown_only").strip().lower().replace("-", "_")
    allowed = {"markdown_only", "markdown_assets"}
    if normalized not in allowed:
        raise DocConvertError("MINERU_ASSET_MODE must be one of: markdown_only, markdown_assets")
    return normalized


def _sidecar_path(root: Path, name: str | None) -> Path | None:
    if not name:
        return None
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _collect_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_collect_urls(item))
        return urls
    if isinstance(value, (list, tuple)):
        urls = []
        for item in value:
            urls.extend(_collect_urls(item))
        return urls
    return []


def _collect_secret_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        values: list[str] = []
        for match in _ASSIGNMENT_SECRET_VALUE_RE.finditer(value):
            secret = match.group(1).strip()
            if len(secret) < 4:
                continue
            values.append(secret)
            stem = Path(secret).stem
            if len(stem) >= 4 and stem != secret:
                values.append(stem)
        return values
    if isinstance(value, dict):
        secrets: list[str] = []
        for item in value.values():
            secrets.extend(_collect_secret_literals(item))
        return secrets
    if isinstance(value, (list, tuple)):
        secrets = []
        for item in value:
            secrets.extend(_collect_secret_literals(item))
        return secrets
    return []


def _collect_manifest_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    source_root = manifest.get("source_root")
    if source_root:
        paths.append(str(source_root))
    documents = manifest.get("documents", [])
    if isinstance(documents, list):
        for item in documents:
            if not isinstance(item, dict):
                continue
            for key in ("source_path", "markdown_path"):
                value = item.get(key)
                if value:
                    paths.append(str(value))
    return paths


def _manifest_assets_from_remote_attempts(
    remote_attempts: list[dict[str, Any]],
    *,
    start_index: int,
    asset_renames: dict[str, str] | None = None,
) -> dict[str, Any]:
    rename_map = asset_renames or {}
    images: list[dict[str, Any]] = []
    for attempt in remote_attempts[start_index:]:
        if not isinstance(attempt, dict):
            continue
        policy = attempt.get("asset_policy") if isinstance(attempt.get("asset_policy"), dict) else {}
        saved = policy.get("saved") if isinstance(policy.get("saved"), dict) else {}
        image_assets = saved.get("image_assets") if isinstance(saved.get("image_assets"), list) else []
        for item in image_assets:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str) or not path:
                continue
            path = rename_map.get(path, path)
            entry = {"path": f"documents/{path}"}
            if isinstance(item.get("sha256"), str):
                entry["sha256"] = item["sha256"]
            if isinstance(item.get("bytes"), str) and item["bytes"].isdigit():
                entry["bytes"] = int(item["bytes"])
            images.append(entry)
    return {"images": images} if images else {}


def _apply_semantic_image_rename_records_to_remote_attempts(
    remote_attempts: list[dict[str, Any]],
    *,
    start_index: int,
    records: list[dict[str, str]],
) -> dict[str, str]:
    rename_map = {
        item["old_path"]: item["new_path"]
        for item in records
        if isinstance(item.get("old_path"), str) and isinstance(item.get("new_path"), str)
    }
    if not rename_map:
        return {}
    for attempt in remote_attempts[start_index:]:
        if not isinstance(attempt, dict):
            continue
        policy = attempt.get("asset_policy")
        if not isinstance(policy, dict):
            continue
        saved = policy.get("saved")
        if not isinstance(saved, dict):
            continue
        image_paths = saved.get("image_paths")
        if isinstance(image_paths, list):
            saved["image_paths"] = [
                rename_map.get(path, path) if isinstance(path, str) else path
                for path in image_paths
            ]
        image_assets = saved.get("image_assets")
        if isinstance(image_assets, list):
            for item in image_assets:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if isinstance(path, str):
                    item["path"] = rename_map.get(path, path)
        saved["image_naming"] = {
            "mode": "semantic_alias",
            "renamed_count": len(rename_map),
            "reason": "opaque hash filenames were replaced with deterministic semantic names",
        }
    return rename_map


def _sanitize_generated_report(
    report: dict[str, Any],
    redaction_report: str | None,
    *,
    explicit_secrets: list[str | None] | None = None,
    url_candidates: list[str | None] | None = None,
    home_paths: list[str | None] | None = None,
    config_paths: list[str | None] | None = None,
) -> dict[str, Any]:
    if not redaction_report:
        return report
    urls = [*(url_candidates or []), *_collect_urls(report)]
    secrets = [*(explicit_secrets or []), *_collect_secret_literals(report)]
    sanitized, redaction_payload = sanitize_report_payload(
        report,
        explicit_secrets=secrets,
        private_hosts=configured_private_hosts_from_urls(urls),
        home_paths=home_paths,
        config_paths=config_paths,
    )
    redaction_path = Path(redaction_report)
    redaction_path.parent.mkdir(parents=True, exist_ok=True)
    redaction_path.write_text(json.dumps(redaction_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sanitized


def _sanitize_output_payload(
    payload: dict[str, Any],
    *,
    explicit_secrets: list[str | None] | None = None,
    url_candidates: list[str | None] | None = None,
    home_paths: list[str | None] | None = None,
    config_paths: list[str | None] | None = None,
) -> dict[str, Any]:
    urls = [*(url_candidates or []), *_collect_urls(payload)]
    sanitized, _redaction_payload = sanitize_report_payload(
        payload,
        explicit_secrets=explicit_secrets,
        private_hosts=configured_private_hosts_from_urls(urls),
        home_paths=home_paths,
        config_paths=config_paths,
    )
    return sanitized


def _read_optional_json_report(path: str | None, *, label: str) -> dict[str, Any] | None:
    if not path:
        return None
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffError(f"{label} not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffError(f"{label} is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise HandoffError(f"{label} must contain a JSON object: {source}")
    return payload


def _split_source_hashes(markdown_path: str | Path) -> dict[str, str]:
    path = Path(markdown_path)
    return {str(path): sha256_file(path)}


def _split_request_hash(
    *,
    plan,
    markdown_path: str | Path,
    output_dir: str | Path,
    plan_output: str | Path | None,
    soft_max_chars: int,
    hard_max_chars: int,
    min_segment_chars: int,
    source_hashes: dict[str, str],
) -> str:
    payload = {
        "schema": DOC_SPLIT_CHECKPOINT_SCHEMA,
        "markdown_path": str(Path(markdown_path)),
        "output_dir": str(Path(output_dir)),
        "plan_output": str(Path(plan_output)) if plan_output else None,
        "soft_max_chars": soft_max_chars,
        "hard_max_chars": hard_max_chars,
        "min_segment_chars": min_segment_chars,
        "source_hashes": source_hashes,
        "plan": {
            "schema": "doc_segmentation_plan_v1",
            "strategy": "heading_boundary_v1",
            "document_name": plan.document_name,
            "recommended": plan.recommended,
            "reason": plan.reason,
            "totals": {
                "chars": plan.total_chars,
                "lines": plan.total_lines,
                "images": plan.total_images,
                "chunk_markers": plan.total_chunk_markers,
            },
            "segments": [
                {
                    "index": segment.index,
                    "title": segment.title,
                    "start_line": segment.start_line,
                    "end_line": segment.end_line,
                    "char_count": segment.char_count,
                    "image_count": segment.image_count,
                    "chunk_marker_count": segment.chunk_marker_count,
                    "suggested_markdown_path": segment.suggested_markdown_path,
                }
                for segment in plan.segments
            ],
            "warnings": plan.warnings,
        },
    }
    return _stable_digest(payload)


def _read_split_checkpoint(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocSegmentError(f"split checkpoint is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise DocSegmentError("split checkpoint must be a JSON object")
    if payload.get("schema") != DOC_SPLIT_CHECKPOINT_SCHEMA:
        raise DocSegmentError(f"split checkpoint schema must be {DOC_SPLIT_CHECKPOINT_SCHEMA}")
    processed = payload.get("processed_segment_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise DocSegmentError("split checkpoint processed_segment_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, dict):
        raise DocSegmentError("split checkpoint source_hashes must be an object")
    return dict(payload)


def _validate_split_checkpoint(
    checkpoint: dict[str, Any],
    *,
    source_hashes: dict[str, str],
    request_hash: str,
    markdown_path: str | Path,
    output_dir: str | Path,
    plan_output: str | Path | None,
    soft_max_chars: int,
    hard_max_chars: int,
    min_segment_chars: int,
) -> None:
    if dict(checkpoint.get("source_hashes") or {}) != dict(source_hashes):
        raise DocSegmentError("split checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("request_hash") or "") != request_hash:
        raise DocSegmentError("split checkpoint request hash does not match current request")
    expected_markdown = str(Path(markdown_path))
    if (checkpoint.get("markdown_path") or None) != expected_markdown:
        raise DocSegmentError("split checkpoint markdown path does not match current request")
    expected_output = str(Path(output_dir))
    if (checkpoint.get("output_dir") or None) != expected_output:
        raise DocSegmentError("split checkpoint output_dir does not match current request")
    expected_plan = str(Path(plan_output)) if plan_output else None
    if (checkpoint.get("plan_output") or None) != expected_plan:
        raise DocSegmentError("split checkpoint plan_output does not match current request")
    parameters = checkpoint.get("parameters")
    expected_parameters = {
        "soft_max_chars": soft_max_chars,
        "hard_max_chars": hard_max_chars,
        "min_segment_chars": min_segment_chars,
    }
    if not isinstance(parameters, dict) or parameters != expected_parameters:
        raise DocSegmentError("split checkpoint parameters do not match current request")


def _write_split_checkpoint(
    *,
    checkpoint_path: str | Path,
    markdown_path: str | Path,
    output_dir: str | Path,
    plan_output: str | Path | None,
    soft_max_chars: int,
    hard_max_chars: int,
    min_segment_chars: int,
    source_hashes: dict[str, str],
    request_hash: str,
    processed_segment_ids: list[str],
    total_segment_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_segment_ids))
    payload = {
        "schema": DOC_SPLIT_CHECKPOINT_SCHEMA,
        "created_at": created_at or _utc_now(),
        "updated_at": _utc_now(),
        "markdown_path": str(Path(markdown_path)),
        "output_dir": str(Path(output_dir)),
        "plan_output": str(Path(plan_output)) if plan_output else None,
        "parameters": {
            "soft_max_chars": soft_max_chars,
            "hard_max_chars": hard_max_chars,
            "min_segment_chars": min_segment_chars,
        },
        "source_hashes": dict(source_hashes),
        "request_hash": request_hash,
        "processed_segment_ids": processed,
        "summary": {
            "processed_segment_count": len(processed),
            "total_segment_count": total_segment_count,
            "remaining_segment_count": max(total_segment_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    checkpoint_file = Path(checkpoint_path)
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _apply_split_checkpoint(
    *,
    plan,
    checkpoint_path: str | None,
    resume: bool,
    batch_size: int | None,
    markdown_path: str | Path,
    output_dir: str | Path,
    plan_output: str | Path | None,
    soft_max_chars: int,
    hard_max_chars: int,
    min_segment_chars: int,
    force: bool,
) -> dict[str, Any]:
    source_hashes = _split_source_hashes(markdown_path)
    request_hash = _split_request_hash(
        plan=plan,
        markdown_path=markdown_path,
        output_dir=output_dir,
        plan_output=plan_output,
        soft_max_chars=soft_max_chars,
        hard_max_chars=hard_max_chars,
        min_segment_chars=min_segment_chars,
        source_hashes=source_hashes,
    )
    processed_segment_ids: list[str] = []
    checkpoint_created_at: str | None = None
    if checkpoint_path and resume:
        checkpoint = _read_split_checkpoint(Path(checkpoint_path))
        _validate_split_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            request_hash=request_hash,
            markdown_path=markdown_path,
            output_dir=output_dir,
            plan_output=plan_output,
            soft_max_chars=soft_max_chars,
            hard_max_chars=hard_max_chars,
            min_segment_chars=min_segment_chars,
        )
        processed_segment_ids = list(checkpoint.get("processed_segment_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    segment_ids = [f"segment-{segment.index:03d}" for segment in plan.segments]
    unknown_processed = sorted(set(processed_segment_ids) - set(segment_ids))
    if unknown_processed:
        raise DocSegmentError(
            "split checkpoint contains segment ids that are not present in current plan: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_segment_ids)
    remaining_segment_ids = [segment_id for segment_id in segment_ids if segment_id not in processed_set]
    next_segment_ids = remaining_segment_ids if batch_size is None else remaining_segment_ids[:batch_size]
    selected_segment_ids = set(processed_segment_ids) | set(next_segment_ids)
    completed = len(selected_segment_ids) >= len(segment_ids)
    segment_lookup = {f"segment-{segment.index:03d}": segment for segment in plan.segments}
    selected_segments = [segment_lookup[segment_id] for segment_id in segment_ids if segment_id in selected_segment_ids]
    next_segments = [segment_lookup[segment_id] for segment_id in next_segment_ids]

    output = Path(output_dir)
    if output.exists() and any(output.iterdir()) and not (force or resume):
        raise DocSegmentError(f"segment output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if resume:
        for segment_id in processed_segment_ids:
            segment = segment_lookup[segment_id]
            target = output / Path(segment.suggested_markdown_path).name
            if not target.exists():
                raise DocSegmentError(f"split checkpoint processed segment output is missing: {target}")
    source_lines = plan.markdown_path.read_text(encoding="utf-8").splitlines(keepends=True) or [""]
    written_paths: list[Path] = []
    for segment in next_segments:
        target = output / Path(segment.suggested_markdown_path).name
        text = "".join(source_lines[segment.start_line - 1:segment.end_line])
        target.write_text(text, encoding="utf-8")
        written_paths.append(target)

    checkpoint_payload = None
    if checkpoint_path:
        checkpoint_payload = _write_split_checkpoint(
            checkpoint_path=checkpoint_path,
            markdown_path=markdown_path,
            output_dir=output_dir,
            plan_output=plan_output,
            soft_max_chars=soft_max_chars,
            hard_max_chars=hard_max_chars,
            min_segment_chars=min_segment_chars,
            source_hashes=source_hashes,
            request_hash=request_hash,
            processed_segment_ids=[segment_id for segment_id in segment_ids if segment_id in selected_segment_ids],
            total_segment_count=len(segment_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    materialized = {
        "ok": True,
        "segmentation_plan": plan.to_dict(),
        "output_dir": str(output),
        "segment_paths": [str(output / Path(segment.suggested_markdown_path).name) for segment in selected_segments],
        "segment_count": len(selected_segments),
        "checkpoint": {
            "enabled": bool(checkpoint_path),
            "path": str(checkpoint_path) if checkpoint_path else None,
            "resume": bool(resume),
            "batch_size": batch_size,
            "processed_segment_count": len(selected_segments),
            "new_segment_count": len(next_segments),
            "remaining_segment_count": max(len(segment_ids) - len(selected_segments), 0),
            "total_segment_count": len(segment_ids),
            "completed": completed,
            "next_segment_ids": list(next_segment_ids),
        },
    }
    if checkpoint_payload:
        materialized["checkpoint_payload"] = checkpoint_payload
    if written_paths:
        materialized["written_segment_paths"] = [str(path) for path in written_paths]
    return materialized


def _relative_manifest_path(path: Path, *, manifest_base: Path) -> str:
    try:
        return os.path.relpath(path, manifest_base).replace(os.sep, "/")
    except ValueError:
        return str(path)


def _build_split_manifest_payload(
    *,
    payload: dict[str, Any],
    markdown_path: str | Path,
    output_dir: str | Path,
    manifest_output: str | Path,
    plan_output: str | Path | None,
) -> dict[str, Any]:
    plan = payload.get("segmentation_plan")
    if not isinstance(plan, dict):
        raise DocSegmentError("split payload is missing segmentation_plan")
    raw_segments = plan.get("segments")
    if not isinstance(raw_segments, list):
        raise DocSegmentError("split segmentation_plan.segments must be a list")
    segment_paths = payload.get("segment_paths")
    if not isinstance(segment_paths, list) or not all(isinstance(item, str) for item in segment_paths):
        raise DocSegmentError("split payload segment_paths must be a list of strings")

    manifest_path = Path(manifest_output)
    manifest_base = manifest_path.parent
    output = Path(output_dir)
    selected_by_name = {Path(path).name for path in segment_paths}
    source_markdown = Path(markdown_path)
    source_path = _relative_manifest_path(source_markdown, manifest_base=manifest_base)
    documents: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        suggested = item.get("suggested_markdown_path")
        if not isinstance(suggested, str) or not suggested:
            continue
        target = output / Path(suggested).name
        if target.name not in selected_by_name:
            continue
        if not target.exists():
            raise DocSegmentError(f"split manifest segment output is missing: {target}")
        documents.append(
            {
                "source_path": source_path,
                "markdown_path": _relative_manifest_path(target, manifest_base=manifest_base),
                "sha256": sha256_file(target),
                "title": item.get("title") if isinstance(item.get("title"), str) else None,
                "warnings": [],
                "segment": {
                    "index": item.get("index"),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "char_count": item.get("char_count"),
                    "image_count": item.get("image_count"),
                    "chunk_marker_count": item.get("chunk_marker_count"),
                    "suggested_markdown_path": suggested,
                },
            }
        )
    if not documents:
        raise DocSegmentError("split manifest would contain no materialized segments")

    checkpoint = payload.get("checkpoint") if isinstance(payload.get("checkpoint"), dict) else {}
    return {
        "version": "0.1",
        "created_at": _utc_now(),
        "source_root": ".",
        "documents": documents,
        "split": {
            "source_markdown_path": source_path,
            "segmentation_plan": _relative_manifest_path(Path(plan_output), manifest_base=manifest_base)
            if plan_output
            else None,
            "strategy": plan.get("strategy"),
            "document_name": plan.get("document_name"),
            "segment_count": len(documents),
            "total_segment_count": len(raw_segments),
            "completed": bool(checkpoint.get("completed", len(documents) >= len(raw_segments))),
        },
    }


def _postprocess_report_path(args: argparse.Namespace) -> Path:
    if args.report_json:
        return Path(args.report_json)
    if args.doc_manifest:
        if args.write:
            return Path(args.doc_manifest).parent / "postprocess_report.json"
        return Path(args.output) / "postprocess_report.json"
    if args.output:
        output = Path(args.output)
        return (output if output.exists() and output.is_dir() else output.parent) / "postprocess_report.json"
    return Path(args.markdown).parent / "postprocess_report.json"


def _postprocess_chunk_profile_report_path(args: argparse.Namespace) -> Path | None:
    raw = getattr(args, "chunk_profile_report_json", None)
    if raw:
        return Path(raw)
    profile = getattr(args, "profile", "")
    if not isinstance(profile, str) or not profile.startswith("chunk-markers"):
        return None
    if args.doc_manifest:
        if args.write:
            return Path(args.doc_manifest).parent / "chunk_profile_report.json"
        return Path(args.output) / "chunk_profile_report.json"
    if args.output:
        output = Path(args.output)
        return (output if output.exists() and output.is_dir() else output.parent) / "chunk_profile_report.json"
    return Path(args.markdown).parent / "chunk_profile_report.json"


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)


def _stage_timing(
    *,
    stage: str,
    operation: str,
    started: float,
    status: str = "success",
    backend: str | None = None,
    source_path: str | None = None,
    detail: str | None = None,
    timing_source: str = "monotonic_clock",
    included_in_stage: str | None = None,
    counts_toward_total: bool | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "stage": stage,
        "operation": operation,
        "status": status,
        "duration_ms": _elapsed_ms(started),
        "timing_source": timing_source,
    }
    if backend:
        item["backend"] = backend
    if source_path:
        item["source_path"] = source_path
    if detail:
        item["detail"] = detail
    if included_in_stage:
        item["included_in_stage"] = included_in_stage
    if counts_toward_total is not None:
        item["counts_toward_total"] = counts_toward_total
    return item


def _included_stage_timing(
    *,
    stage: str,
    operation: str,
    included_in_stage: str,
    status: str = "success",
    backend: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "stage": stage,
        "operation": operation,
        "status": status,
        "duration_ms": None,
        "timing_source": "included_in_parent_stage",
        "included_in_stage": included_in_stage,
        "counts_toward_total": False,
    }
    if backend:
        item["backend"] = backend
    if detail:
        item["detail"] = detail
    return item


def _conversion_stage_status(
    process_attempts: list[dict[str, Any]],
    remote_attempts: list[dict[str, Any]],
    *,
    failed: bool,
) -> str:
    recent = [*process_attempts, *remote_attempts]
    if any(item.get("status") == "timeout" for item in recent):
        return "timeout"
    if any(item.get("status") == "execution_error" for item in recent):
        return "execution_error"
    if failed:
        return "failed"
    return "success"


def _conversion_runtime_context(
    *,
    backend: str,
    mineru_asset_mode: str,
    mineru_is_ocr: bool,
    mineru_enable_table: bool,
    mineru_enable_formula: bool,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "configured_backend": backend,
        "mineru_asset_mode": mineru_asset_mode,
        "ocr_requested": bool(mineru_is_ocr),
        "table_parsing_requested": bool(mineru_enable_table),
        "formula_parsing_requested": bool(mineru_enable_formula),
    }
    if backend != "auto":
        context["backend"] = backend
    if backend == "mineru-cli":
        context.update(
            {
                "cold_warm": "cold_local_process",
                "mineru_execution": "local_process_per_document",
                "persistent_mineru_reused": False,
                "local_process_startup_included": True,
            }
        )
    elif backend in {"mineru", "mineru-agent", "mineru-fastapi", "mineru-sync", "mineru-local"}:
        context.update(
            {
                "cold_warm": "warm_persistent_service",
                "mineru_execution": "persistent_service_reused",
                "persistent_mineru_reused": True,
                "local_process_startup_included": False,
            }
        )
    elif backend in {"builtin", "pandoc", "remote"}:
        context.update(
            {
                "cold_warm": "not_applicable",
                "mineru_execution": "not_applicable",
                "persistent_mineru_reused": None,
                "local_process_startup_included": False,
            }
        )
    return context


def _conversion_slow_path_warnings(
    *,
    sources: list[Any],
    backend: str,
    mineru_asset_mode: str,
    mineru_is_ocr: bool,
    mineru_enable_table: bool,
    mineru_enable_formula: bool,
) -> list[dict[str, str]]:
    mineru_candidate = backend.startswith("mineru") or (
        backend == "auto"
        and any(Path(getattr(source, "source_path", "")).suffix.lower() in FORMAL_PREP_SOURCE_EXTENSIONS for source in sources)
    )
    if not mineru_candidate:
        return []
    warnings: list[dict[str, str]] = []
    if mineru_is_ocr:
        warnings.append(
            {
                "code": "ocr_slow_path",
                "severity": "review",
                "message": "OCR mode was requested; conversion time may include text recognition slow path.",
            }
        )
    if mineru_enable_table:
        warnings.append(
            {
                "code": "table_slow_path",
                "severity": "info",
                "message": "Table parsing was enabled; table structure detection may add parser latency.",
            }
        )
    if mineru_enable_formula:
        warnings.append(
            {
                "code": "formula_slow_path",
                "severity": "info",
                "message": "Formula parsing was enabled; model-side formula handling may add parser latency.",
            }
        )
    if mineru_asset_mode == "markdown_assets":
        warnings.append(
            {
                "code": "asset_materialization_slow_path",
                "severity": "info",
                "message": "Markdown asset materialization was requested; image download/copy time is reported separately when measurable.",
            }
        )
    return warnings


def _make_runtime_report(
    *,
    output_root: Path,
    process_attempts: list[dict[str, Any]],
    remote_attempts: list[dict[str, Any]] | None = None,
    handoff_mode: str | None = None,
    handoff_advisory: list[dict[str, Any]] | None = None,
    stage_timings: list[dict[str, Any]] | None = None,
    runtime_context: dict[str, Any] | None = None,
    slow_path_warnings: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    if not process_attempts and not remote_attempts and not stage_timings and not slow_path_warnings:
        return None
    return make_doc_runtime_report_payload(
        output_root=output_root,
        process_attempts=process_attempts,
        remote_attempts=remote_attempts,
        handoff_mode=handoff_mode,
        handoff_advisory=handoff_advisory,
        stage_timings=stage_timings,
        runtime_context=runtime_context,
        slow_path_warnings=slow_path_warnings,
    )


def _quality_table_summary(quality_report: dict[str, Any] | None) -> dict[str, int]:
    summary = {
        "table_count": 0,
        "markdown_table_count": 0,
        "html_table_count": 0,
        "html_table_review_warning_count": 0,
    }
    if not isinstance(quality_report, dict):
        return summary
    documents = quality_report.get("documents")
    if not isinstance(documents, list):
        return summary
    for document in documents:
        if not isinstance(document, dict):
            continue
        signals = document.get("quality_signals")
        if not isinstance(signals, dict):
            continue
        table_count = int(signals.get("table_count", 0) or 0)
        markdown_table_count = int(signals.get("markdown_table_count", table_count) or 0)
        html_table_count = int(signals.get("html_table_count", 0) or 0)
        summary["table_count"] += table_count
        summary["markdown_table_count"] += markdown_table_count
        summary["html_table_count"] += html_table_count
        summary["html_table_review_warning_count"] += int(
            signals.get("html_table_review_warning_count", 0) or 0
        )
    return summary


def _attach_runtime_quality_summary(
    *,
    runtime_report: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
) -> None:
    if not isinstance(runtime_report, dict):
        return
    table_summary = _quality_table_summary(quality_report)
    runtime_report["document_quality_summary"] = table_summary
    summary = runtime_report.get("summary")
    if isinstance(summary, dict):
        summary["quality_table_count"] = table_summary["table_count"]
        summary["quality_markdown_table_count"] = table_summary["markdown_table_count"]
        summary["quality_html_table_count"] = table_summary["html_table_count"]
        summary["quality_html_table_review_warning_count"] = table_summary["html_table_review_warning_count"]


def _runtime_report_paths(output_root: Path, args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    return _sidecar_path(output_root, args.runtime_report_name), _sidecar_path(output_root, args.runtime_report_md)


def _write_runtime_report_payload(
    *,
    output_root: Path,
    args: argparse.Namespace,
    report: dict[str, Any] | None,
) -> tuple[Path | None, Path | None]:
    if not report:
        return None, None
    report_json_path = _sidecar_path(output_root, args.runtime_report_name)
    if report_json_path:
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_path = _sidecar_path(output_root, args.runtime_report_md)
    if report_md_path:
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        report_md_path.write_text(render_doc_runtime_markdown(report), encoding="utf-8")
    return report_json_path, report_md_path


def _explicit_runtime_stage_timings(report: dict[str, Any]) -> list[dict[str, Any]]:
    performance = report.get("performance")
    if not isinstance(performance, dict):
        return []
    timings = performance.get("stage_timings")
    if not isinstance(timings, list):
        return []
    return [
        dict(item)
        for item in timings
        if isinstance(item, dict) and not item.get("derived_from_attempt")
    ]


def _runtime_context_from_report(report: dict[str, Any]) -> dict[str, Any]:
    performance = report.get("performance")
    if not isinstance(performance, dict):
        return {}
    context = performance.get("runtime_context")
    return dict(context) if isinstance(context, dict) else {}


def _slow_path_warnings_from_report(report: dict[str, Any]) -> list[dict[str, str]]:
    performance = report.get("performance")
    if not isinstance(performance, dict):
        return []
    warnings = performance.get("slow_path_warnings")
    if not isinstance(warnings, list):
        return []
    return [dict(item) for item in warnings if isinstance(item, dict)]


def _rewrite_runtime_report_payload(
    *,
    output_root: Path,
    args: argparse.Namespace,
    stage_timings: list[dict[str, Any]] | None = None,
    runtime_context: dict[str, Any] | None = None,
    slow_path_warnings: list[dict[str, str]] | None = None,
    handoff_mode: str | None = None,
    handoff_advisory: list[dict[str, Any]] | None = None,
    formal_ingest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    report_path = _sidecar_path(output_root, args.runtime_report_name)
    if not report_path or not report_path.is_file():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        return None
    merged_context = _runtime_context_from_report(report)
    if runtime_context:
        merged_context.update(runtime_context)
    merged_warnings = _slow_path_warnings_from_report(report)
    if slow_path_warnings:
        existing_codes = {str(item.get("code")) for item in merged_warnings}
        for item in slow_path_warnings:
            if str(item.get("code")) not in existing_codes:
                merged_warnings.append(dict(item))
    rebuilt = make_doc_runtime_report_payload(
        output_root=output_root,
        process_attempts=report.get("process_attempts", []) if isinstance(report.get("process_attempts"), list) else [],
        remote_attempts=report.get("remote_attempts", []) if isinstance(report.get("remote_attempts"), list) else [],
        handoff_mode=handoff_mode or report.get("handoff_mode"),
        handoff_advisory=handoff_advisory
        if handoff_advisory is not None
        else report.get("handoff_advisory") if isinstance(report.get("handoff_advisory"), list) else None,
        stage_timings=[*_explicit_runtime_stage_timings(report), *(stage_timings or [])],
        runtime_context=merged_context,
        slow_path_warnings=merged_warnings,
    )
    for key in ("document_quality_summary",):
        if key in report:
            rebuilt[key] = report[key]
    table_summary = rebuilt.get("document_quality_summary")
    summary = rebuilt.get("summary")
    if isinstance(table_summary, dict) and isinstance(summary, dict):
        summary["quality_table_count"] = table_summary.get("table_count", 0)
        summary["quality_markdown_table_count"] = table_summary.get("markdown_table_count", 0)
        summary["quality_html_table_count"] = table_summary.get("html_table_count", 0)
        summary["quality_html_table_review_warning_count"] = table_summary.get(
            "html_table_review_warning_count",
            0,
        )
    if formal_ingest is not None:
        rebuilt["formal_ingest"] = formal_ingest
    elif isinstance(report.get("formal_ingest"), dict):
        rebuilt["formal_ingest"] = report["formal_ingest"]
    report_path.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_path = _sidecar_path(output_root, args.runtime_report_md)
    if report_md_path:
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        report_md_path.write_text(render_doc_runtime_markdown(rebuilt), encoding="utf-8")
    return rebuilt


def _sanitize_conversion_reports(
    *,
    quality_report: dict[str, Any] | None,
    runtime_report: dict[str, Any] | None,
    args: argparse.Namespace,
    config: Any,
    output_root: Path,
    remote_url: str | None,
    remote_api_key: str | None,
    mineru_base_url: str | None,
    mineru_api_key: str | None,
    mineru_cli_path: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not args.redaction_report:
        return quality_report, runtime_report
    bundle: dict[str, Any] = {}
    if quality_report is not None:
        bundle["quality_report"] = quality_report
    if runtime_report is not None:
        bundle["runtime_report"] = runtime_report
    sanitized = _sanitize_generated_report(
        bundle,
        args.redaction_report,
        explicit_secrets=[
            remote_api_key,
            mineru_api_key,
            args.remote_api_key,
            args.mineru_api_key,
            config.doc_to_md.remote_api_key,
            config.mineru.api_key,
        ],
        url_candidates=[remote_url, mineru_base_url],
        home_paths=[
            args.input,
            args.output,
            args.config,
            str(output_root),
            mineru_cli_path,
            os.environ.get("MINERU_CLI_PATH"),
        ],
        config_paths=[
            args.input,
            args.output,
            args.config,
            args.quality_report_name,
            args.quality_report_md,
            args.runtime_report_name,
            args.runtime_report_md,
            args.redaction_report,
            os.environ.get("RAGFLOW_CONFIG"),
        ],
    )
    return sanitized.get("quality_report"), sanitized.get("runtime_report")


def _config_or_arg(args: argparse.Namespace, field: str, config_value, default=None):
    value = getattr(args, field)
    return value if value not in (None, "") else config_value if config_value not in (None, "") else default


def _float_config_or_arg(
    args: argparse.Namespace,
    field: str,
    config_value,
    default: float,
    *,
    label: str,
) -> float:
    value = getattr(args, field)
    if value is None:
        value = config_value
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError(f"{label} must be a number of seconds") from exc
    if parsed <= 0:
        raise DocConvertError(f"{label} must be greater than zero")
    return parsed


def _bool_config_or_arg(args: argparse.Namespace, field: str, config_value, default: bool, *, label: str) -> bool:
    value = getattr(args, field)
    if value is None:
        value = config_value
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise DocConvertError(f"{label} must be true or false")


def _run(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = _backend(args, config)
        remote_url = _remote_url(args, config)
        remote_timeout = (
            _remote_timeout(args)
            if args.remote_timeout is not None
            else config.doc_to_md.remote_timeout or 120.0
        )
        remote_api_key = _remote_api_key(args, config)
        mineru_base_url = _config_or_arg(args, "mineru_base_url", config.mineru.base_url)
        mineru_api_key = _config_or_arg(args, "mineru_api_key", config.mineru.api_key)
        mineru_cli_path = _config_or_arg(args, "mineru_cli_path", config.mineru.cli_path)
        mineru_timeout = _float_config_or_arg(
            args,
            "mineru_timeout",
            config.mineru.timeout,
            300.0,
            label="MINERU_TIMEOUT",
        )
        mineru_poll_interval = _float_config_or_arg(
            args,
            "mineru_poll_interval",
            config.mineru.poll_interval,
            3.0,
            label="MINERU_POLL_INTERVAL",
        )
        mineru_verify_ssl = _bool_config_or_arg(
            args,
            "mineru_verify_ssl",
            config.mineru.verify_ssl,
            True,
            label="MINERU_VERIFY_SSL",
        )
        mineru_asset_mode = _mineru_asset_mode(args, config)
        mineru_cli_backend = _config_or_arg(
            args,
            "mineru_cli_backend",
            config.mineru.cli_backend,
            "pipeline",
        ) or "pipeline"
        mineru_language = _config_or_arg(args, "mineru_language", config.mineru.language, "ch") or "ch"
        mineru_page_range = _config_or_arg(args, "mineru_page_range", config.mineru.page_range)
        mineru_enable_table = _bool_config_or_arg(
            args,
            "mineru_enable_table",
            config.mineru.enable_table,
            True,
            label="MINERU_ENABLE_TABLE",
        )
        mineru_is_ocr = _bool_config_or_arg(
            args,
            "mineru_is_ocr",
            config.mineru.is_ocr,
            False,
            label="MINERU_IS_OCR",
        )
        mineru_enable_formula = _bool_config_or_arg(
            args,
            "mineru_enable_formula",
            config.mineru.enable_formula,
            True,
            label="MINERU_ENABLE_FORMULA",
        )
        output_root = Path(args.output).expanduser().resolve()
        sources = discover_source_documents(args.input, recursive=not args.no_recursive)
        sources = [
            source
            for source in sources
            if source.path != output_root and output_root not in source.path.parents
        ]
        if not sources:
            raise DocConvertError("no input files found outside the output directory")
        handoff_mode = THIN_PREVIEW_HANDOFF_MODE
        handoff_advisory = _thin_preview_handoff_advisory(sources)
        runtime_context = _conversion_runtime_context(
            backend=backend,
            mineru_asset_mode=mineru_asset_mode,
            mineru_is_ocr=mineru_is_ocr,
            mineru_enable_table=mineru_enable_table,
            mineru_enable_formula=mineru_enable_formula,
        )
        slow_path_warnings = _conversion_slow_path_warnings(
            sources=sources,
            backend=backend,
            mineru_asset_mode=mineru_asset_mode,
            mineru_is_ocr=mineru_is_ocr,
            mineru_enable_table=mineru_enable_table,
            mineru_enable_formula=mineru_enable_formula,
        )

        docs_dir = output_root / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        converted: list[ConvertedDocument] = []
        skipped: list[dict[str, str]] = []
        process_attempts: list[dict[str, Any]] = []
        remote_attempts: list[dict[str, Any]] = []
        stage_timings: list[dict[str, Any]] = []

        for source in sources:
            output_name = safe_markdown_name(source, used=used_names)
            markdown_path = docs_dir / output_name
            conversion_started = time.monotonic()
            process_attempt_start = len(process_attempts)
            remote_attempt_start = len(remote_attempts)
            try:
                markdown, warnings = convert_source_to_markdown(
                    source,
                    mode=args.mode,
                    backend=backend,
                    remote_url=remote_url,
                    remote_api_key=remote_api_key,
                    remote_timeout=remote_timeout,
                    mineru_base_url=mineru_base_url,
                    mineru_api_key=mineru_api_key,
                    mineru_timeout=mineru_timeout,
                    mineru_poll_interval=mineru_poll_interval,
                    mineru_verify_ssl=mineru_verify_ssl,
                    mineru_cli_path=mineru_cli_path,
                    mineru_cli_backend=mineru_cli_backend,
                    asset_output_dir=markdown_path.parent,
                    asset_document_stem=markdown_path.stem,
                    mineru_language=mineru_language,
                    mineru_page_range=mineru_page_range,
                    mineru_enable_table=mineru_enable_table,
                    mineru_is_ocr=mineru_is_ocr,
                    mineru_enable_formula=mineru_enable_formula,
                    mineru_asset_mode=mineru_asset_mode,
                    process_attempts=process_attempts,
                    remote_attempts=remote_attempts,
                    allow_image_fallback=not args.no_image_fallback,
                )
            except (UnicodeDecodeError, OSError, DocConvertError) as exc:
                stage_timings.append(
                    _stage_timing(
                        stage="conversion",
                        operation=backend,
                        started=conversion_started,
                        status=_conversion_stage_status(
                            process_attempts[process_attempt_start:],
                            remote_attempts[remote_attempt_start:],
                            failed=True,
                        ),
                        backend=backend,
                        source_path=source.source_path,
                        detail=exc.__class__.__name__,
                    )
                )
                if args.strict:
                    runtime_report = _make_runtime_report(
                        output_root=output_root,
                        process_attempts=process_attempts,
                        remote_attempts=remote_attempts,
                        handoff_mode=handoff_mode,
                        handoff_advisory=handoff_advisory,
                        stage_timings=stage_timings,
                        runtime_context=runtime_context,
                        slow_path_warnings=slow_path_warnings,
                    )
                    _, runtime_report = _sanitize_conversion_reports(
                        quality_report=None,
                        runtime_report=runtime_report,
                        args=args,
                        config=config,
                        output_root=output_root,
                        remote_url=remote_url,
                        remote_api_key=remote_api_key,
                        mineru_base_url=mineru_base_url,
                        mineru_api_key=mineru_api_key,
                        mineru_cli_path=mineru_cli_path,
                    )
                    _write_runtime_report_payload(
                        output_root=output_root,
                        args=args,
                        report=runtime_report,
                    )
                    raise DocConvertError(str(exc)) from exc
                skipped.append({"source_path": source.source_path, "reason": str(exc)})
                continue

            stage_timings.append(
                _stage_timing(
                    stage="conversion",
                    operation=backend,
                    started=conversion_started,
                    status=_conversion_stage_status(
                        process_attempts[process_attempt_start:],
                        remote_attempts[remote_attempt_start:],
                        failed=False,
                    ),
                    backend=backend,
                    source_path=source.source_path,
                )
            )
            markdown_path.write_text(markdown, encoding="utf-8")
            markdown, image_rename_records = semantic_rename_markdown_images(
                markdown,
                markdown_path=markdown_path,
                source_root=markdown_path.parent,
            )
            if image_rename_records:
                markdown_path.write_text(markdown, encoding="utf-8")
            image_asset_renames = _apply_semantic_image_rename_records_to_remote_attempts(
                remote_attempts,
                start_index=remote_attempt_start,
                records=image_rename_records,
            )
            converted.append(
                ConvertedDocument(
                    source=source,
                    markdown_path=markdown_path,
                    sha256=sha256_file(source.path),
                    title=extract_markdown_title(markdown),
                    warnings=warnings,
                    assets=_manifest_assets_from_remote_attempts(
                        remote_attempts,
                        start_index=remote_attempt_start,
                        asset_renames=image_asset_renames,
                    ),
                )
            )

        runtime_report = _make_runtime_report(
            output_root=output_root,
            process_attempts=process_attempts,
            remote_attempts=remote_attempts,
            handoff_mode=handoff_mode,
            handoff_advisory=handoff_advisory,
            stage_timings=stage_timings,
            runtime_context=runtime_context,
            slow_path_warnings=slow_path_warnings,
        )
        if not converted:
            _, runtime_report = _sanitize_conversion_reports(
                quality_report=None,
                runtime_report=runtime_report,
                args=args,
                config=config,
                output_root=output_root,
                remote_url=remote_url,
                remote_api_key=remote_api_key,
                mineru_base_url=mineru_base_url,
                mineru_api_key=mineru_api_key,
                mineru_cli_path=mineru_cli_path,
            )
            _write_runtime_report_payload(
                output_root=output_root,
                args=args,
                report=runtime_report,
            )
            raise DocConvertError("no documents were converted")

        manifest = make_doc_manifest_payload(output_root=output_root, documents=converted)
        manifest["handoff_mode"] = handoff_mode
        manifest["handoff_advisory"] = handoff_advisory
        quality_documents = [
            QualityDocument(
                source_path=document.source.source_path,
                markdown_path=document.markdown_path,
                warnings=document.warnings,
            )
            for document in converted
        ]
        quality_report = make_quality_report_payload(
            output_root=output_root,
            documents=quality_documents,
        )
        _attach_runtime_quality_summary(
            runtime_report=runtime_report,
            quality_report=quality_report,
        )
        quality_report, runtime_report = _sanitize_conversion_reports(
            quality_report=quality_report,
            runtime_report=runtime_report,
            args=args,
            config=config,
            output_root=output_root,
            remote_url=remote_url,
            remote_api_key=remote_api_key,
            mineru_base_url=mineru_base_url,
            mineru_api_key=mineru_api_key,
            mineru_cli_path=mineru_cli_path,
        )
        runtime_report_path, runtime_report_md_path = _write_runtime_report_payload(
            output_root=output_root,
            args=args,
            report=runtime_report,
        )
        quality_report_path = _sidecar_path(output_root, args.quality_report_name)
        if quality_report_path:
            quality_report_path.parent.mkdir(parents=True, exist_ok=True)
            quality_report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["quality_report"] = args.quality_report_name
        quality_report_md_path = _sidecar_path(output_root, args.quality_report_md)
        if quality_report_md_path:
            quality_report_md_path.parent.mkdir(parents=True, exist_ok=True)
            quality_report_md_path.write_text(render_quality_markdown(quality_report), encoding="utf-8")
            manifest["quality_report_md"] = args.quality_report_md
        if runtime_report_path:
            manifest["runtime_report"] = args.runtime_report_name
        if runtime_report_md_path:
            manifest["runtime_report_md"] = args.runtime_report_md
        manifest["quality_gate"] = quality_report["gate"]
        manifest_path = output_root / args.manifest_name
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        response = {
            "ok": True,
            "doc_manifest": str(manifest_path),
            "handoff_mode": handoff_mode,
            "handoff_advisory": handoff_advisory,
            "quality_report": str(quality_report_path) if quality_report_path else None,
            "quality_gate": quality_report["gate"],
            "runtime_report": str(runtime_report_path) if runtime_report_path else None,
            "runtime_summary": runtime_report["summary"] if runtime_report else None,
            "document_count": len(converted),
            "skipped": skipped,
        }
        if args.redaction_report:
            response = _sanitize_output_payload(
                response,
                explicit_secrets=[remote_api_key, mineru_api_key],
                url_candidates=[remote_url, mineru_base_url],
                home_paths=[args.input, args.output, str(output_root), mineru_cli_path],
                config_paths=[
                    args.input,
                    args.output,
                    args.config,
                    str(manifest_path),
                    str(quality_report_path) if quality_report_path else None,
                    str(runtime_report_path) if runtime_report_path else None,
                    args.redaction_report,
                ],
            )
        _dump_json(response)
        return 0 if not skipped else 1
    except (DocConvertError, DocQualityError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_convert_captured(args: argparse.Namespace) -> tuple[int, dict[str, Any], str]:
    buffer = io.StringIO()
    convert_args = argparse.Namespace(**vars(args))
    convert_args.json = True
    with contextlib.redirect_stdout(buffer):
        return_code = _run(convert_args)
    raw = buffer.getvalue().strip()
    payload: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {"ok": False, "raw_stdout": raw}
    return return_code, payload, raw


def _update_manifest_postprocess_report(
    manifest_path: Path,
    *,
    postprocess_report_name: str,
    chunk_profile_report_name: str | None = None,
) -> None:
    manifest = load_doc_manifest_payload(manifest_path)
    updated = dict(manifest)
    updated["postprocess_report"] = postprocess_report_name
    if chunk_profile_report_name:
        updated["chunk_profile_report"] = chunk_profile_report_name
    manifest_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_manifest_handoff_state(
    manifest_path: Path,
    *,
    handoff_mode: str,
    handoff_advisory: list[dict[str, Any]],
    formal_ingest: dict[str, Any] | None = None,
) -> None:
    manifest = load_doc_manifest_payload(manifest_path)
    updated = dict(manifest)
    updated["handoff_mode"] = handoff_mode
    updated["handoff_advisory"] = handoff_advisory
    if formal_ingest is not None:
        updated["formal_ingest"] = formal_ingest
    manifest_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_runtime_report_handoff_state(
    *,
    output_root: Path,
    args: argparse.Namespace,
    handoff_mode: str,
    handoff_advisory: list[dict[str, Any]],
    formal_ingest: dict[str, Any] | None = None,
    stage_timings: list[dict[str, Any]] | None = None,
    runtime_context: dict[str, Any] | None = None,
    slow_path_warnings: list[dict[str, str]] | None = None,
) -> None:
    if not getattr(args, "runtime_report_name", None):
        return
    _rewrite_runtime_report_payload(
        output_root=output_root,
        args=args,
        stage_timings=stage_timings,
        runtime_context=runtime_context,
        slow_path_warnings=slow_path_warnings,
        handoff_mode=handoff_mode,
        handoff_advisory=handoff_advisory,
        formal_ingest=formal_ingest,
    )


def _run_pipeline(args: argparse.Namespace) -> int:
    try:
        output_root = Path(args.output).expanduser().resolve()
        manifest_path = output_root / args.manifest_name
        pipeline_stage_timings: list[dict[str, Any]] = []

        convert_code, convert_payload, raw_convert_stdout = _run_convert_captured(args)
        if convert_code != 0:
            response = {
                "ok": False,
                "stage": "convert",
                "error": "convert stage failed or skipped documents",
                "convert": convert_payload or {"raw_stdout": raw_convert_stdout},
            }
            _dump_json(response)
            return convert_code

        postprocess_report_name = _safe_handoff_sidecar_name(
            args.postprocess_report_name,
            label="--postprocess-report-name",
        ) or "postprocess_report.json"
        chunk_profile_report_name = None
        if args.postprocess_profile.startswith("chunk-markers"):
            chunk_profile_report_name = _safe_handoff_sidecar_name(
                args.chunk_profile_report_name,
                label="--chunk-profile-report-name",
            ) or "chunk_profile_report.json"
        postprocess_report_path = output_root / postprocess_report_name
        chunk_profile_report_path = output_root / chunk_profile_report_name if chunk_profile_report_name else None
        postprocess_started = time.monotonic()
        postprocess_report = postprocess_handoff(
            manifest_path,
            profile=args.postprocess_profile,
            write=True,
            report_json=postprocess_report_path,
            chunk_profile_report_json=chunk_profile_report_path,
        )
        pipeline_stage_timings.append(
            _stage_timing(
                stage="postprocess",
                operation=args.postprocess_profile,
                started=postprocess_started,
                status="success",
                detail=f"changed_documents={postprocess_report.get('summary', {}).get('changed_documents')}",
            )
        )
        _update_manifest_postprocess_report(
            manifest_path,
            postprocess_report_name=postprocess_report_name,
            chunk_profile_report_name=chunk_profile_report_name,
        )
        handoff_advisory = _formal_ingest_handoff_advisory()
        _update_manifest_handoff_state(
            manifest_path,
            handoff_mode=FORMAL_INGEST_HANDOFF_MODE,
            handoff_advisory=handoff_advisory,
        )

        metadata_name = _safe_handoff_sidecar_name(args.metadata_name, label="--metadata-name") or "metadata.json"
        artifact_index_name = _safe_handoff_sidecar_name(args.artifact_index_name, label="--artifact-index-name") or "artifact_index.json"
        profile_suggestions_name = _safe_handoff_sidecar_name(args.profile_suggestions_name, label="--profile-suggestions-name") or "profile_suggestions.json"
        retrieval_hints_name = _safe_handoff_sidecar_name(args.retrieval_hints_name, label="--retrieval-hints-name") or "retrieval_hints.json"
        assistant_profile_name = _safe_handoff_sidecar_name(args.assistant_profile_name, label="--assistant-profile-name") or "assistant_profile.json"
        assistant_test_plan_name = _safe_handoff_sidecar_name(args.assistant_test_plan_name, label="--assistant-test-plan-name") or "assistant_test_plan.json"
        ingest_readiness_name = _safe_handoff_sidecar_name(args.ingest_readiness_name, label="--ingest-readiness-name") or "ingest_readiness_report.json"
        ingest_readiness_md_name = _safe_handoff_sidecar_name(args.ingest_readiness_md_name, label="--ingest-readiness-md-name") if args.ingest_readiness_md_name else None
        formal_manifest_name = _safe_handoff_sidecar_name(args.formal_manifest_name, label="--formal-manifest-name") or "formal_handoff_manifest.json"
        package_readme_name = _safe_handoff_sidecar_name(args.package_readme_name, label="--package-readme-name") or "package_readme.md"
        package_started = time.monotonic()
        package_payload = create_rich_handoff_package(
            handoff_root=output_root,
            doc_manifest_name=args.manifest_name,
            metadata_name=metadata_name,
            artifact_index_name=artifact_index_name,
            profile_suggestions_name=profile_suggestions_name,
            retrieval_hints_name=retrieval_hints_name,
            assistant_profile_name=assistant_profile_name,
            assistant_test_plan_name=assistant_test_plan_name,
            ingest_readiness_name=ingest_readiness_name,
            ingest_readiness_md_name=ingest_readiness_md_name,
            formal_handoff_manifest_name=formal_manifest_name,
            package_readme_name=package_readme_name,
        )
        pipeline_stage_timings.append(
            _stage_timing(
                stage="package",
                operation="rich_handoff_package",
                started=package_started,
                status="success",
                detail=f"sidecars={len(package_payload.get('sidecars', []))}",
            )
        )
        pipeline_stage_timings.append(
            _included_stage_timing(
                stage="hints",
                operation="retrieval_hints",
                included_in_stage="package",
                status="success",
                detail=retrieval_hints_name,
            )
        )

        ingest_plan_name = _safe_handoff_sidecar_name(args.ingest_plan_name, label="--ingest-plan-name")
        if not ingest_plan_name:
            raise DocConvertError("--ingest-plan-name must not be empty")
        ingest_plan_started = time.monotonic()
        ingest_plan = make_ragflow_ingest_plan_payload(
            handoff_root=output_root,
            doc_manifest_name=args.manifest_name,
            package_payload=package_payload,
            postprocess_report_name=postprocess_report_name,
            chunk_profile_report_name=chunk_profile_report_name,
        )
        ingest_plan_path = output_root / ingest_plan_name
        _write_yaml_payload(ingest_plan_path, ingest_plan)
        pipeline_stage_timings.append(
            _stage_timing(
                stage="ingest_plan",
                operation="write_non_secret_ingest_plan",
                started=ingest_plan_started,
                status="success",
            )
        )
        readiness_started = time.monotonic()
        ingest_readiness = write_doc_ingest_readiness_report(
            handoff_root=output_root,
            doc_manifest_name=args.manifest_name,
            ingest_readiness_name=ingest_readiness_name,
            ingest_readiness_md_name=ingest_readiness_md_name,
            sidecar_names={
                "metadata": metadata_name,
                "artifact_index": artifact_index_name,
                "profile_suggestions": profile_suggestions_name,
                "retrieval_hints": retrieval_hints_name,
                "assistant_profile": assistant_profile_name,
                "assistant_test_plan": assistant_test_plan_name,
                "package_readme": package_readme_name,
                "quality_report": convert_payload.get("quality_report_name") or args.quality_report_name,
                "postprocess_report": postprocess_report_name,
                "chunk_profile_report": chunk_profile_report_name,
                "ragflow_ingest_plan": ingest_plan_name,
            },
        )
        pipeline_stage_timings.append(
            _stage_timing(
                stage="ingest_plan",
                operation="readiness_report",
                started=readiness_started,
                status=ingest_readiness["status"],
                detail=f"score={ingest_readiness['advisory_score']}",
            )
        )
        package_payload["ingest_readiness"] = ingest_readiness_name
        package_payload["ingest_readiness_md"] = ingest_readiness_md_name
        package_payload["ingest_readiness_status"] = ingest_readiness["status"]
        package_payload["ingest_readiness_score"] = ingest_readiness["advisory_score"]
        formal_manifest_started = time.monotonic()
        formal_handoff_manifest = write_formal_handoff_manifest(
            handoff_root=output_root,
            doc_manifest_name=args.manifest_name,
            formal_handoff_manifest_name=formal_manifest_name,
            sidecar_names={
                "metadata": metadata_name,
                "artifact_index": artifact_index_name,
                "profile_suggestions": profile_suggestions_name,
                "retrieval_hints": retrieval_hints_name,
                "assistant_profile": assistant_profile_name,
                "assistant_test_plan": assistant_test_plan_name,
                "ingest_readiness": ingest_readiness_name,
                "ingest_readiness_md": ingest_readiness_md_name,
                "package_readme": package_readme_name,
                "quality_report": convert_payload.get("quality_report_name") or args.quality_report_name,
                "postprocess_report": postprocess_report_name,
                "chunk_profile_report": chunk_profile_report_name,
                "ragflow_ingest_plan": ingest_plan_name,
            },
        )
        pipeline_stage_timings.append(
            _stage_timing(
                stage="package",
                operation="formal_handoff_manifest",
                started=formal_manifest_started,
                status="success",
                detail=formal_manifest_name,
            )
        )
        package_payload["formal_handoff_manifest"] = formal_manifest_name
        package_payload["formal_handoff_manifest_schema"] = formal_handoff_manifest["schema"]
        package_payload["formal_handoff_package_hash"] = formal_handoff_manifest["package_hash"]

        alias_path: Path | None = None
        alias_name = _safe_handoff_sidecar_name(args.ragflow_config_alias, label="--ragflow-config-alias")
        if alias_name:
            alias_path = output_root / alias_name
            _write_yaml_payload(alias_path, ingest_plan)

        formal_ingest = _formal_ingest_readiness_signals(
            postprocess_report=postprocess_report,
            postprocess_profile=args.postprocess_profile,
            package_payload=package_payload,
            ingest_plan_name=ingest_plan_name,
            retrieval_hints_name=retrieval_hints_name,
            chunk_profile_report_name=chunk_profile_report_name,
            ingest_readiness_name=ingest_readiness_name,
            ingest_readiness_status=ingest_readiness["status"],
            ingest_readiness_score=ingest_readiness["advisory_score"],
        )
        _update_manifest_handoff_state(
            manifest_path,
            handoff_mode=FORMAL_INGEST_HANDOFF_MODE,
            handoff_advisory=handoff_advisory,
            formal_ingest=formal_ingest,
        )
        _update_runtime_report_handoff_state(
            output_root=output_root,
            args=args,
            handoff_mode=FORMAL_INGEST_HANDOFF_MODE,
            handoff_advisory=handoff_advisory,
            formal_ingest=formal_ingest,
            stage_timings=pipeline_stage_timings,
            runtime_context={"pipeline_mode": FORMAL_INGEST_HANDOFF_MODE},
        )

        response = {
            "ok": True,
            "handoff_mode": FORMAL_INGEST_HANDOFF_MODE,
            "handoff_advisory": handoff_advisory,
            "formal_ingest": formal_ingest,
            "pipeline": {
                "schema": "ragflow_doc_to_md_pipeline_summary_v1",
                "handoff_mode": FORMAL_INGEST_HANDOFF_MODE,
                "formal_ingest": formal_ingest,
                "stages": {
                    "convert": {"ok": True, "doc_manifest": str(manifest_path)},
                    "postprocess": {
                        "ok": True,
                        "profile": args.postprocess_profile,
                        "postprocess_report": str(postprocess_report_path),
                        "chunk_profile_report": str(chunk_profile_report_path) if chunk_profile_report_path else None,
                        "changed_documents": postprocess_report.get("summary", {}).get("changed_documents"),
                    },
                    "package": {"ok": True, **package_payload},
                    "ingest_plan": {"ok": True, "path": str(ingest_plan_path), "alias": str(alias_path) if alias_path else None},
                },
            },
            "doc_manifest": str(manifest_path),
            "quality_report": convert_payload.get("quality_report"),
            "quality_gate": convert_payload.get("quality_gate"),
            "runtime_report": convert_payload.get("runtime_report"),
            "postprocess_report": str(postprocess_report_path),
            "chunk_profile_report": str(chunk_profile_report_path) if chunk_profile_report_path else None,
            "handoff_package": package_payload,
            "retrieval_hints": str(output_root / retrieval_hints_name),
            "ingest_readiness_report": str(output_root / ingest_readiness_name),
            "ingest_readiness_report_md": str(output_root / ingest_readiness_md_name) if ingest_readiness_md_name else None,
            "formal_handoff_manifest": str(output_root / formal_manifest_name),
            "ragflow_ingest_plan": str(ingest_plan_path),
            "ragflow_config_alias": str(alias_path) if alias_path else None,
            "document_count": convert_payload.get("document_count"),
            "skipped": convert_payload.get("skipped", []),
        }
        if args.redaction_report:
            response = _sanitize_output_payload(
                response,
                home_paths=[args.input, args.output, str(output_root)],
                config_paths=[
                    args.input,
                    args.output,
                    args.config,
                    str(manifest_path),
                    str(postprocess_report_path),
                    str(ingest_plan_path),
                    str(alias_path) if alias_path else None,
                    args.redaction_report,
                ],
            )
        _dump_json(response)
        return 0
    except (DocConvertError, DocPostprocessError, DocQualityError, HandoffError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect(args: argparse.Namespace) -> int:
    try:
        manifest = load_doc_manifest_payload(args.doc_manifest)
        output_root, documents = quality_documents_from_manifest(
            manifest,
            manifest_path=args.doc_manifest,
        )
        report = make_quality_report_payload(output_root=output_root, documents=documents)
        report = _sanitize_generated_report(
            report,
            args.redaction_report,
            url_candidates=_collect_urls(manifest),
            home_paths=[
                args.doc_manifest,
                args.report_json,
                args.report_md,
                *_collect_manifest_paths(manifest),
            ],
            config_paths=[args.doc_manifest, args.report_json, args.report_md, args.redaction_report],
        )
        report_json = Path(args.report_json) if args.report_json else Path(args.doc_manifest).parent / "quality_report.json"
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_quality_markdown(report), encoding="utf-8")
        response = {
            "ok": True,
            "quality_report": str(report_json),
            "quality_report_md": str(args.report_md) if args.report_md else None,
            "quality_gate": report["gate"],
            "document_count": len(documents),
        }
        if args.redaction_report:
            response = _sanitize_output_payload(
                response,
                url_candidates=_collect_urls(manifest),
                home_paths=[args.doc_manifest, args.report_json, args.report_md, *_collect_manifest_paths(manifest)],
                config_paths=[args.doc_manifest, args.report_json, args.report_md, args.redaction_report],
            )
        _dump_json(response)
        if args.fail_on_blocked and report["gate"].get("status") == "BLOCKED":
            return 1
        return 0
    except (DocQualityError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_segment_plan(args: argparse.Namespace) -> int:
    try:
        plan = plan_markdown_segmentation(
            args.markdown,
            soft_max_chars=args.soft_max_chars,
            hard_max_chars=args.hard_max_chars,
            min_segment_chars=args.min_segment_chars,
        )
        response = {
            "ok": True,
            "segmentation_plan": plan.to_dict(),
            "output": args.output,
        }
        if args.redaction_report:
            response = _sanitize_generated_report(
                response,
                args.redaction_report,
                home_paths=[args.markdown, args.output],
                config_paths=[args.markdown, args.output, args.redaction_report],
            )
        payload = response["segmentation_plan"]
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _dump_json(response)
        return 0
    except (DocSegmentError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_split(args: argparse.Namespace) -> int:
    try:
        if args.resume and not args.checkpoint:
            raise DocSegmentError("split --resume requires --checkpoint")
        if args.batch_size is not None and not args.checkpoint:
            raise DocSegmentError("split --batch-size requires --checkpoint")
        if args.batch_size is not None and args.batch_size <= 0:
            raise DocSegmentError("split --batch-size must be greater than zero")
        if args.checkpoint:
            plan = plan_markdown_segmentation(
                args.markdown,
                soft_max_chars=args.soft_max_chars,
                hard_max_chars=args.hard_max_chars,
                min_segment_chars=args.min_segment_chars,
            )
            payload = _apply_split_checkpoint(
                plan=plan,
                checkpoint_path=args.checkpoint,
                resume=args.resume,
                batch_size=args.batch_size,
                markdown_path=args.markdown,
                output_dir=args.output,
                plan_output=args.plan_output,
                soft_max_chars=args.soft_max_chars,
                hard_max_chars=args.hard_max_chars,
                min_segment_chars=args.min_segment_chars,
                force=args.force,
            )
        else:
            materialized = materialize_segments(
                args.markdown,
                output_dir=args.output,
                plan_output=None,
                soft_max_chars=args.soft_max_chars,
                hard_max_chars=args.hard_max_chars,
                min_segment_chars=args.min_segment_chars,
                force=args.force,
            )
            payload = materialized.to_dict()
        manifest_payload = None
        if args.manifest_output:
            manifest_payload = _build_split_manifest_payload(
                payload=payload,
                markdown_path=args.markdown,
                output_dir=args.output,
                manifest_output=args.manifest_output,
                plan_output=args.plan_output,
            )
            payload["split_manifest"] = {
                "path": args.manifest_output,
                "document_count": len(manifest_payload["documents"]),
                "completed": manifest_payload.get("split", {}).get("completed"),
            }
        if args.redaction_report:
            sanitized = _sanitize_generated_report(
                {"payload": payload, "split_manifest_payload": manifest_payload}
                if manifest_payload
                else payload,
                args.redaction_report,
                home_paths=[args.markdown, args.output, args.plan_output, args.checkpoint, args.manifest_output],
                config_paths=[
                    args.markdown,
                    args.output,
                    args.plan_output,
                    args.checkpoint,
                    args.manifest_output,
                    args.redaction_report,
                ],
            )
            if manifest_payload:
                payload = sanitized["payload"]
                manifest_payload = sanitized["split_manifest_payload"]
            else:
                payload = sanitized
        if args.plan_output:
            plan_output = Path(args.plan_output)
            plan_output.parent.mkdir(parents=True, exist_ok=True)
            plan_output.write_text(
                json.dumps(payload["segmentation_plan"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if args.manifest_output and manifest_payload:
            manifest_output = Path(args.manifest_output)
            manifest_output.parent.mkdir(parents=True, exist_ok=True)
            manifest_output.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _dump_json(payload)
        return 0
    except (DocSegmentError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_package(args: argparse.Namespace) -> int:
    try:
        if not args.rich:
            raise HandoffError("package currently supports only --rich")
        payload = create_rich_handoff_package(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
            metadata_name=args.metadata_name,
            artifact_index_name=args.artifact_index_name,
            profile_suggestions_name=args.profile_suggestions_name,
            retrieval_hints_name=args.retrieval_hints_name,
            assistant_profile_name=args.assistant_profile_name,
            assistant_test_plan_name=args.assistant_test_plan_name,
            ingest_readiness_name=args.ingest_readiness_name,
            ingest_readiness_md_name=args.ingest_readiness_md_name,
            formal_handoff_manifest_name=args.formal_manifest_name,
            package_readme_name=args.package_readme_name,
        )
        _dump_json({"ok": True, "package": payload})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_compare_retained_package(args: argparse.Namespace) -> int:
    try:
        replacement_live_evidence = _read_optional_json_report(
            args.replacement_live_evidence,
            label="replacement live evidence",
        )
        retained_live_evidence = _read_optional_json_report(
            args.retained_live_evidence,
            label="retained-package live evidence",
        )
        report = make_handoff_comparison_payload(
            retained_package=args.retained_package,
            replacement_handoff=args.replacement_handoff,
            paired_live_ab_status=args.paired_live_ab_status,
            replacement_live_evidence=replacement_live_evidence,
            retained_live_evidence=retained_live_evidence,
        )
        if args.redaction_report:
            report = _sanitize_generated_report(
                report,
                args.redaction_report,
                home_paths=[
                    args.retained_package,
                    args.replacement_handoff,
                    args.report_json,
                    args.report_md,
                    args.replacement_live_evidence,
                    args.retained_live_evidence,
                ],
                config_paths=[
                    args.retained_package,
                    args.replacement_handoff,
                    args.report_json,
                    args.report_md,
                    args.redaction_report,
                    args.replacement_live_evidence,
                    args.retained_live_evidence,
                ],
            )
        report_json_path = Path(args.report_json) if args.report_json else None
        if report_json_path:
            report_json_path.parent.mkdir(parents=True, exist_ok=True)
            report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_md_path = Path(args.report_md) if args.report_md else None
        if report_md_path:
            report_md_path.parent.mkdir(parents=True, exist_ok=True)
            report_md_path.write_text(render_handoff_comparison_markdown(report), encoding="utf-8")
        static = report.get("static_comparison") if isinstance(report.get("static_comparison"), dict) else {}
        normalized = static.get("normalized_text") if isinstance(static.get("normalized_text"), dict) else {}
        live = report.get("live_evidence") if isinstance(report.get("live_evidence"), dict) else {}
        paired_live_ab = live.get("paired_live_ab") if isinstance(live.get("paired_live_ab"), dict) else {}
        response = {
            "ok": True,
            "schema": report.get("schema"),
            "report_json": str(report_json_path) if report_json_path else None,
            "report_md": str(report_md_path) if report_md_path else None,
            "static_status": static.get("status"),
            "normalized_text_similarity": normalized.get("similarity"),
            "paired_live_ab": paired_live_ab,
            "safety": report.get("safety"),
        }
        if args.redaction_report:
            response = _sanitize_output_payload(
                response,
                home_paths=[
                    args.retained_package,
                    args.replacement_handoff,
                    args.report_json,
                    args.report_md,
                    args.replacement_live_evidence,
                    args.retained_live_evidence,
                ],
                config_paths=[
                    args.retained_package,
                    args.replacement_handoff,
                    args.report_json,
                    args.report_md,
                    args.redaction_report,
                    args.replacement_live_evidence,
                    args.retained_live_evidence,
                ],
            )
        _dump_json(response)
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_postprocess(args: argparse.Namespace) -> int:
    try:
        if bool(args.markdown) == bool(args.doc_manifest):
            raise DocPostprocessError("provide exactly one of --markdown or --doc-manifest")
        report_json = args.report_json
        chunk_profile_report_json = str(_postprocess_chunk_profile_report_path(args) or "") or None
        if args.redaction_report:
            raw_report_dir = tempfile.TemporaryDirectory(prefix="ragflow-doc-postprocess-report-")
            report_json = str(Path(raw_report_dir.name) / "postprocess_report.json")
            chunk_profile_report_json = None
        else:
            raw_report_dir = None
        try:
            if args.markdown:
                report = postprocess_single_markdown(
                    args.markdown,
                    profile=args.profile,
                    output_path=args.output,
                    write=args.write,
                    report_json=report_json,
                    chunk_profile_report_json=chunk_profile_report_json,
                )
            else:
                report = postprocess_handoff(
                    args.doc_manifest,
                    profile=args.profile,
                    output_dir=args.output,
                    write=args.write,
                    report_json=report_json,
                    chunk_profile_report_json=chunk_profile_report_json,
                )
            if args.redaction_report:
                report = _sanitize_generated_report(
                    report,
                    args.redaction_report,
                    home_paths=[args.markdown, args.doc_manifest, args.output, args.report_json],
                    config_paths=[
                        args.markdown,
                        args.doc_manifest,
                        args.output,
                        args.report_json,
                        getattr(args, "chunk_profile_report_json", None),
                        args.redaction_report,
                    ],
                )
                report_path = _postprocess_report_path(args)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                chunk_report_path = _postprocess_chunk_profile_report_path(args)
                chunk_report = report.get("chunk_profile_report") if isinstance(report, dict) else None
                if chunk_report_path and isinstance(chunk_report, dict):
                    chunk_report_path.parent.mkdir(parents=True, exist_ok=True)
                    chunk_report_path.write_text(json.dumps(chunk_report, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if raw_report_dir is not None:
                raw_report_dir.cleanup()
        _dump_json({"ok": True, "postprocess_report": report})
        return 0
    except (DocPostprocessError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_backend_probe(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = args.backend or config.doc_to_md.backend or "auto"
        remote_url = _config_or_arg(args, "remote_url", config.doc_to_md.remote_url)
        mineru_base_url = _config_or_arg(args, "mineru_base_url", config.mineru.base_url)
        mineru_api_key = _config_or_arg(args, "mineru_api_key", config.mineru.api_key)
        mineru_cli_path = _config_or_arg(args, "mineru_cli_path", config.mineru.cli_path)
        mineru_verify_ssl = _bool_config_or_arg(
            args,
            "mineru_verify_ssl",
            config.mineru.verify_ssl,
            True,
            label="MINERU_VERIFY_SSL",
        )
        report = probe_conversion_backends(
            backend=backend,
            remote_url=remote_url,
            mineru_base_url=mineru_base_url,
            mineru_api_key=mineru_api_key,
            mineru_cli_path=mineru_cli_path,
            mineru_verify_ssl=mineru_verify_ssl,
            network_check=args.network_check,
            timeout=args.probe_timeout,
        )
        if args.redaction_report:
            report, redaction_report = sanitize_report_payload(
                report,
                explicit_secrets=[config.doc_to_md.remote_api_key, config.mineru.api_key, args.mineru_api_key],
                private_hosts=configured_private_hosts_from_urls([remote_url, mineru_base_url]),
                home_paths=[mineru_cli_path],
                config_paths=[args.config, os.environ.get("RAGFLOW_CONFIG")],
            )
            redaction_path = Path(args.redaction_report)
            redaction_path.parent.mkdir(parents=True, exist_ok=True)
            redaction_path.write_text(json.dumps(redaction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_backend_probe_markdown(report), encoding="utf-8")
        if args.json or not args.report_json:
            _dump_json(report)
        if args.fail_on_unavailable:
            statuses = [item.get("status") for item in report.get("backends", []) if isinstance(item, dict)]
            if "available" not in statuses:
                return 1
            if report.get("selected_backend") != "auto" and any(status != "available" for status in statuses):
                return 1
        return 0
    except (DocConvertError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_backend_warmup(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = args.backend or config.doc_to_md.backend or "auto"
        remote_timeout = (
            _remote_timeout(args)
            if args.remote_timeout is not None
            else config.doc_to_md.remote_timeout or 120.0
        )
        report = warmup_conversion_backend(
            fixture_path=args.fixture,
            backend=backend,
            output_markdown=args.output_markdown,
            remote_url=_config_or_arg(args, "remote_url", config.doc_to_md.remote_url),
            remote_api_key=_remote_api_key(args, config),
            remote_timeout=remote_timeout,
            mineru_base_url=_config_or_arg(args, "mineru_base_url", config.mineru.base_url),
            mineru_api_key=_config_or_arg(args, "mineru_api_key", config.mineru.api_key),
            mineru_timeout=_float_config_or_arg(
                args,
                "mineru_timeout",
                config.mineru.timeout,
                300.0,
                label="MINERU_TIMEOUT",
            ),
            mineru_poll_interval=_float_config_or_arg(
                args,
                "mineru_poll_interval",
                config.mineru.poll_interval,
                3.0,
                label="MINERU_POLL_INTERVAL",
            ),
            mineru_verify_ssl=_bool_config_or_arg(
                args,
                "mineru_verify_ssl",
                config.mineru.verify_ssl,
                True,
                label="MINERU_VERIFY_SSL",
            ),
            mineru_cli_path=_config_or_arg(args, "mineru_cli_path", config.mineru.cli_path),
            mineru_cli_backend=_config_or_arg(
                args,
                "mineru_cli_backend",
                config.mineru.cli_backend,
                "pipeline",
            )
            or "pipeline",
            mineru_language=_config_or_arg(args, "mineru_language", config.mineru.language, "ch") or "ch",
            mineru_page_range=_config_or_arg(args, "mineru_page_range", config.mineru.page_range),
            mineru_enable_table=_bool_config_or_arg(
                args,
                "mineru_enable_table",
                config.mineru.enable_table,
                True,
                label="MINERU_ENABLE_TABLE",
            ),
            mineru_is_ocr=_bool_config_or_arg(
                args,
                "mineru_is_ocr",
                config.mineru.is_ocr,
                False,
                label="MINERU_IS_OCR",
            ),
            mineru_enable_formula=_bool_config_or_arg(
                args,
                "mineru_enable_formula",
                config.mineru.enable_formula,
                True,
                label="MINERU_ENABLE_FORMULA",
            ),
        )
        report = _sanitize_generated_report(
            report,
            args.redaction_report,
            explicit_secrets=[
                config.doc_to_md.remote_api_key,
                config.mineru.api_key,
                args.remote_api_key,
                args.mineru_api_key,
            ],
            url_candidates=[
                _config_or_arg(args, "remote_url", config.doc_to_md.remote_url),
                _config_or_arg(args, "mineru_base_url", config.mineru.base_url),
            ],
            home_paths=[
                args.fixture,
                args.output_markdown,
                _config_or_arg(args, "mineru_cli_path", config.mineru.cli_path),
            ],
            config_paths=[
                args.config,
                os.environ.get("RAGFLOW_CONFIG"),
                args.report_json,
                args.report_md,
                args.redaction_report,
            ],
        )
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_backend_warmup_markdown(report), encoding="utf-8")
        if args.json or not args.report_json:
            _dump_json(report)
        if args.fail_on_failed and report.get("status") != "success":
            return 1
        return 0
    except (DocConvertError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _add_segmentation_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--soft-max-chars", type=int, default=DEFAULT_SOFT_MAX_CHARS)
    parser.add_argument("--hard-max-chars", type=int, default=DEFAULT_HARD_MAX_CHARS)
    parser.add_argument("--min-segment-chars", type=int, default=DEFAULT_MIN_SEGMENT_CHARS)
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")


def build_inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a doc_manifest handoff and write a quality report")
    parser.add_argument("--doc-manifest", required=True, help="Path to doc_manifest.json")
    parser.add_argument("--report-json", help="Output quality_report.json path; defaults beside the doc manifest")
    parser.add_argument("--report-md", help="Optional Markdown quality report path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--fail-on-blocked", action="store_true", help="Return exit code 1 when the gate status is BLOCKED")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_segment_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan Markdown segmentation without writing segment files")
    parser.add_argument("--markdown", required=True, help="Markdown file to inspect")
    parser.add_argument("--output", help="Optional segmentation_plan.json output path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    _add_segmentation_threshold_args(parser)
    return parser


def build_split_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize Markdown segments from a long document")
    parser.add_argument("--markdown", required=True, help="Markdown file to split")
    parser.add_argument("--output", required=True, help="Output directory for segment Markdown files")
    parser.add_argument("--plan-output", help="Optional segmentation_plan.json output path")
    parser.add_argument("--manifest-output", help="Optional doc_manifest.json output path for materialized segments")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--checkpoint", help="Checkpoint path for resumable bounded split execution")
    parser.add_argument("--resume", action="store_true", help="Resume from an existing split checkpoint")
    parser.add_argument("--batch-size", type=int, help="Write at most this many new segments in this run")
    parser.add_argument("--force", action="store_true", help="Allow writing into a non-empty output directory")
    _add_segmentation_threshold_args(parser)
    return parser


def build_package_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create optional rich handoff sidecars beside a doc_manifest")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--rich", action="store_true", help="Generate rich package sidecars")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--metadata-name", default="metadata.json", help="Metadata sidecar name")
    parser.add_argument("--artifact-index-name", default="artifact_index.json", help="Artifact index sidecar name")
    parser.add_argument("--profile-suggestions-name", default="profile_suggestions.json", help="Profile suggestions sidecar name")
    parser.add_argument("--retrieval-hints-name", default="retrieval_hints.json", help="Retrieval hints sidecar name")
    parser.add_argument("--assistant-profile-name", default="assistant_profile.json", help="Assistant profile sidecar name")
    parser.add_argument("--assistant-test-plan-name", default="assistant_test_plan.json", help="Assistant test plan sidecar name")
    parser.add_argument("--ingest-readiness-name", default="ingest_readiness_report.json", help="Ingest readiness JSON sidecar name")
    parser.add_argument("--ingest-readiness-md-name", default="ingest_readiness_report.md", help="Ingest readiness Markdown sidecar name")
    parser.add_argument("--formal-manifest-name", default="formal_handoff_manifest.json", help="Package-level formal handoff audit manifest name")
    parser.add_argument("--package-readme-name", default="package_readme.md", help="Package README sidecar name")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_postprocess_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply deterministic Markdown post-processing profiles")
    parser.add_argument("--markdown", help="Single Markdown file to post-process")
    parser.add_argument("--doc-manifest", help="Process every Markdown file referenced by a doc_manifest")
    parser.add_argument("--profile", choices=POSTPROCESS_PROFILE_CHOICES, default="safe")
    parser.add_argument("--output", help="Output file for --markdown or output handoff directory for --doc-manifest")
    parser.add_argument("--write", action="store_true", help="Rewrite the source Markdown file(s) in place")
    parser.add_argument("--report-json", help="Optional postprocess_report.json output path")
    parser.add_argument("--chunk-profile-report-json", help="Optional chunk_profile_report.json output path for chunk-marker profiles")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def _add_backend_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Unified config file; defaults to RAGFLOW_CONFIG or .ragflow/config*.yaml")
    parser.add_argument("--backend", choices=sorted(BACKEND_CHOICES), help="Backend to inspect; auto uses configured backend selection")
    parser.add_argument("--remote-url", help="Remote conversion endpoint; defaults to DOC_TO_MD_REMOTE_URL")
    parser.add_argument("--mineru-base-url", help="MinerU service base URL")
    parser.add_argument("--mineru-api-key", help="MinerU API key; probe reports presence only, warmup uses it for service calls")
    parser.add_argument("--mineru-verify-ssl", help="MinerU TLS certificate verification true/false; defaults to MINERU_VERIFY_SSL or true")
    parser.add_argument("--mineru-cli-path", help="Local MinerU CLI path; defaults to MINERU_CLI_PATH or PATH lookup")


def build_backend_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect document conversion backend readiness")
    sub = parser.add_subparsers(dest="backend_command", required=True)
    probe = sub.add_parser("probe", help="Probe configured conversion backend readiness")
    _add_backend_config_args(probe)
    probe.add_argument("--network-check", action="store_true", help="Attempt a bounded endpoint reachability check")
    probe.add_argument("--probe-timeout", type=float, default=2.0, help="Maximum seconds for each network probe")
    probe.add_argument("--report-json", help="Optional backend probe JSON report path")
    probe.add_argument("--report-md", help="Optional backend probe Markdown report path")
    probe.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    probe.add_argument("--fail-on-unavailable", action="store_true", help="Return non-zero when the selected backend is unavailable")
    probe.add_argument("--json", action="store_true", help="Emit JSON")
    probe.set_defaults(func=_run_backend_probe)
    warmup = sub.add_parser("warmup", help="Run an explicit fixture through a configured conversion backend")
    _add_backend_config_args(warmup)
    warmup.add_argument("--fixture", required=True, help="Tiny user-approved fixture file to convert")
    warmup.add_argument("--output-markdown", help="Optional converted Markdown output path")
    warmup.add_argument("--remote-api-key", help="Remote conversion bearer token; defaults to DOC_TO_MD_REMOTE_API_KEY")
    warmup.add_argument("--remote-timeout", type=float, help="Remote conversion timeout in seconds; defaults to DOC_TO_MD_TIMEOUT or 120")
    warmup.add_argument("--mineru-timeout", type=float, help="MinerU parse timeout in seconds; defaults to MINERU_TIMEOUT or 300")
    warmup.add_argument("--mineru-poll-interval", type=float, help="MinerU parse polling interval; defaults to MINERU_POLL_INTERVAL or 3")
    warmup.add_argument("--mineru-cli-backend", help="Local MinerU CLI backend passed with -b; defaults to MINERU_CLI_BACKEND, mineru.cli_backend, or pipeline")
    warmup.add_argument("--mineru-language", help="MinerU language option; defaults to MINERU_LANGUAGE or ch")
    warmup.add_argument("--mineru-page-range", help="MinerU page range; defaults to MINERU_PAGE_RANGE")
    warmup.add_argument("--mineru-enable-table", help="MinerU table parsing true/false; defaults to MINERU_ENABLE_TABLE or true")
    warmup.add_argument("--mineru-is-ocr", help="MinerU OCR mode true/false; defaults to MINERU_IS_OCR or false")
    warmup.add_argument("--mineru-enable-formula", help="MinerU formula parsing true/false; defaults to MINERU_ENABLE_FORMULA or true")
    warmup.add_argument("--report-json", help="Optional backend warmup JSON report path")
    warmup.add_argument("--report-md", help="Optional backend warmup Markdown report path")
    warmup.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    warmup.add_argument("--fail-on-failed", action="store_true", help="Return non-zero when warmup conversion fails")
    warmup.add_argument("--json", action="store_true", help="Emit JSON")
    warmup.set_defaults(func=_run_backend_warmup)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert documents into a Markdown handoff bundle",
        epilog="Commands: pipeline, compare-retained-package, backend probe, backend warmup, inspect, segment-plan, split.",
    )
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--output", required=True, help="Output handoff directory")
    parser.add_argument("--config", help="Unified config file; defaults to RAGFLOW_CONFIG or .ragflow/config*.yaml")
    parser.add_argument("--mode", choices=["auto", "passthrough", "convert"], default="auto")
    parser.add_argument("--backend", choices=sorted(BACKEND_CHOICES), help="Conversion backend; defaults to DOC_TO_MD_BACKEND or auto")
    parser.add_argument("--remote-url", help="Remote conversion endpoint; defaults to DOC_TO_MD_REMOTE_URL")
    parser.add_argument("--remote-api-key", help="Remote conversion bearer token; defaults to DOC_TO_MD_REMOTE_API_KEY")
    parser.add_argument("--remote-timeout", type=float, help="Remote conversion timeout in seconds; defaults to DOC_TO_MD_TIMEOUT or 120")
    parser.add_argument("--mineru-base-url", help="MinerU service base URL; Agent API defaults to MINERU_BASE_URL or https://mineru.net/api/v1/agent, mineru-sync appends /parse when needed, mineru-fastapi uses /tasks")
    parser.add_argument("--mineru-api-key", help="MinerU API key; defaults to MINERU_API_KEY")
    parser.add_argument("--mineru-timeout", type=float, help="MinerU parse timeout in seconds; defaults to MINERU_TIMEOUT or 300")
    parser.add_argument("--mineru-poll-interval", type=float, help="MinerU parse polling interval; defaults to MINERU_POLL_INTERVAL or 3")
    parser.add_argument("--mineru-verify-ssl", help="MinerU TLS certificate verification true/false; defaults to MINERU_VERIFY_SSL or true")
    parser.add_argument("--mineru-cli-path", help="Local MinerU CLI path; defaults to MINERU_CLI_PATH, mineru.cli_path, or PATH lookup")
    parser.add_argument("--mineru-cli-backend", help="Local MinerU CLI backend passed with -b; defaults to MINERU_CLI_BACKEND, mineru.cli_backend, or pipeline")
    parser.add_argument("--mineru-language", help="MinerU language option; defaults to MINERU_LANGUAGE or ch")
    parser.add_argument("--mineru-page-range", help="MinerU page range; defaults to MINERU_PAGE_RANGE")
    parser.add_argument("--mineru-enable-table", help="MinerU table parsing true/false; defaults to MINERU_ENABLE_TABLE or true")
    parser.add_argument("--mineru-is-ocr", help="MinerU OCR mode true/false; defaults to MINERU_IS_OCR or false")
    parser.add_argument("--mineru-enable-formula", help="MinerU formula parsing true/false; defaults to MINERU_ENABLE_FORMULA or true")
    parser.add_argument("--mineru-asset-mode", choices=["markdown_only", "markdown_assets"], help="MinerU FastAPI asset handling; defaults to MINERU_ASSET_MODE or markdown_only")
    parser.add_argument("--manifest-name", default="doc_manifest.json")
    parser.add_argument("--quality-report-name", default="quality_report.json", help="Quality report sidecar name under the output directory")
    parser.add_argument("--quality-report-md", help="Optional Markdown quality report sidecar name under the output directory")
    parser.add_argument("--runtime-report-name", default="runtime_report.json", help="Runtime telemetry report sidecar name; records stage timings and process/remote attempts when available")
    parser.add_argument("--runtime-report-md", help="Optional Markdown runtime report sidecar name under the output directory")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--no-image-fallback", action="store_true", help="Skip source-image Markdown fallback when OCR/conversion is unavailable")
    parser.add_argument("--no-recursive", action="store_true", help="Do not recurse into input directories")
    parser.add_argument("--strict", action="store_true", help="Fail on the first skipped file")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_pipeline_parser() -> argparse.ArgumentParser:
    parser = build_parser()
    parser.description = "Run convert -> postprocess -> rich package -> non-secret ingest plan"
    parser.add_argument("--postprocess-profile", choices=POSTPROCESS_PROFILE_CHOICES, default="chunk-markers", help="Post-processing profile for the formal handoff")
    parser.add_argument("--postprocess-report-name", default="postprocess_report.json", help="Postprocess report sidecar name under the output directory")
    parser.add_argument("--chunk-profile-report-name", default="chunk_profile_report.json", help="Chunk profile report sidecar name under the output directory")
    parser.add_argument("--metadata-name", default="metadata.json", help="Rich package metadata sidecar name")
    parser.add_argument("--artifact-index-name", default="artifact_index.json", help="Rich package artifact index sidecar name")
    parser.add_argument("--profile-suggestions-name", default="profile_suggestions.json", help="Rich package profile suggestions sidecar name")
    parser.add_argument("--retrieval-hints-name", default="retrieval_hints.json", help="Rich package retrieval hints sidecar name")
    parser.add_argument("--assistant-profile-name", default="assistant_profile.json", help="Rich package assistant profile sidecar name")
    parser.add_argument("--assistant-test-plan-name", default="assistant_test_plan.json", help="Rich package assistant test plan sidecar name")
    parser.add_argument("--ingest-readiness-name", default="ingest_readiness_report.json", help="Rich package ingest readiness JSON sidecar name")
    parser.add_argument("--ingest-readiness-md-name", default="ingest_readiness_report.md", help="Rich package ingest readiness Markdown sidecar name")
    parser.add_argument("--formal-manifest-name", default="formal_handoff_manifest.json", help="Package-level formal handoff audit manifest name")
    parser.add_argument("--package-readme-name", default="package_readme.md", help="Rich package README sidecar name")
    parser.add_argument("--ingest-plan-name", default="ragflow_ingest_plan.yaml", help="Non-secret RAGFlow ingest plan sidecar name")
    parser.add_argument("--ragflow-config-alias", help="Optional non-secret compatibility alias such as ragflow_config.yaml")
    return parser


def build_compare_retained_package_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a retained legacy ingestion package with a formal replacement handoff",
    )
    parser.add_argument("--retained-package", required=True, help="Retained legacy ingestion package root; ragflow_input/ is auto-selected when present")
    parser.add_argument("--replacement-handoff", required=True, help="ragflow-doc-to-md pipeline handoff root")
    parser.add_argument("--report-json", help="Optional JSON comparison report output path")
    parser.add_argument("--report-md", help="Optional Markdown comparison report output path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument(
        "--paired-live-ab-status",
        choices=["not_run", "executed"],
        default="not_run",
        help="Whether a strict paired RAGFlow live A/B was separately approved and executed",
    )
    parser.add_argument("--replacement-live-evidence", help="Optional existing JSON summary for replacement-path live evidence")
    parser.add_argument("--retained-live-evidence", help="Optional existing JSON summary for retained-package paired live evidence")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect":
            return _run_inspect(build_inspect_parser().parse_args(command_args))
        if command == "segment-plan":
            return _run_segment_plan(build_segment_plan_parser().parse_args(command_args))
        if command == "split":
            return _run_split(build_split_parser().parse_args(command_args))
        if command == "package":
            return _run_package(build_package_parser().parse_args(command_args))
        if command == "postprocess":
            return _run_postprocess(build_postprocess_parser().parse_args(command_args))
        if command == "pipeline":
            return _run_pipeline(build_pipeline_parser().parse_args(command_args))
        if command == "compare-retained-package":
            return _run_compare_retained_package(build_compare_retained_package_parser().parse_args(command_args))
        if command == "backend":
            parsed = build_backend_parser().parse_args(command_args)
            return parsed.func(parsed)
    return _run(build_parser().parse_args(actual_argv))


if __name__ == "__main__":
    raise SystemExit(main())
