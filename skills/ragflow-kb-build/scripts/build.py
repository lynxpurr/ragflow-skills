#!/usr/bin/env python3
"""Build a RAGFlow knowledge base from Markdown inputs."""

from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import time
from typing import Any, Mapping


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
    BuildError,
    HandoffError,
    RAGFlowClient,
    ApolloQaError,
    apply_build_profile_language,
    attach_benchmark_evaluation,
    build_runtime_metrics_summary,
    build_runtime_partial_failure_report,
    throughput_summary,
    create_grounded_qa_suggestion_request,
    create_apollo_table_qa_judge_request,
    create_kb_asset_ingestion_readiness_report,
    create_kb_artifact_consistency_report,
    create_kb_asset_upload_plan,
    create_parameter_read_back_audit,
    create_metadata_suggestion_request,
    create_optimization_cleanup_plan,
    create_optimization_live_readiness_report,
    create_optimization_plan,
    discover_markdown_documents,
    check_embedding_model_drift,
    describe_embedding_model,
    inspect_rich_handoff,
    load_benchmark_baseline,
    load_benchmark_gate,
    load_benchmark_qrels,
    load_chunk_snapshot,
    load_config,
    load_doc_manifest,
    load_kb_manifest,
    load_profile,
    load_ragflow_ingest_plan,
    load_validation_queries,
    lint_metadata_file,
    lint_tagset_file,
    make_kb_manifest_payload,
    make_build_payload_preview,
    make_handoff_consumption_status,
    make_parameter_materialization_inventory,
    make_doc_ingest_readiness_payload,
    make_metadata_template_payload,
    make_tagset_template_payload,
    map_grounded_qa_evidence,
    merge_metadata_payloads,
    normalize_embedding_model_expectations,
    chunk_count_performance_warnings,
    performance_warning_report,
    polling_performance_warnings,
    probe_model_providers,
    configured_private_hosts_from_urls,
    create_kb_activation_plan,
    create_kb_health_report,
    create_kb_refresh_report,
    create_kb_split_plan,
    create_kb_topology_advice,
    create_parse_report,
    render_handoff_inspection_markdown,
    render_kb_health_report_markdown,
    render_kb_refresh_report_markdown,
    render_markdown_report,
    render_governance_markdown,
    render_model_provider_probe_markdown,
    render_parse_report_markdown,
    review_metadata_suggestions,
    gate_benchmark_report,
    import_benchmark_dataset,
    preflight_benchmark_dataset,
    render_best_profile_markdown,
    render_benchmark_governance_markdown,
    render_optimization_cleanup_plan_markdown,
    render_optimization_live_readiness_markdown,
    render_suppression_report_markdown,
    review_kb_name_collision,
    sample_benchmark_dataset,
    segment_metadata_report_file,
    render_activation_plan_markdown,
    render_apollo_table_qa_markdown,
    render_kb_asset_ingestion_readiness_markdown,
    render_kb_artifact_consistency_markdown,
    render_kb_asset_upload_plan_markdown,
    render_split_plan_markdown,
    render_topology_advice_markdown,
    render_parameter_read_back_audit_markdown,
    render_optimization_plan_markdown,
    review_grounded_qa_suggestions,
    snapshot_chunks,
    suggest_benchmark_retrieval_parameters,
    summarize_optimization_results,
    summarize_benchmark_report,
    suppression_report_file,
    trend_benchmark_reports,
    delta_benchmark_reports,
    summarize_metadata_for_documents,
    summarize_retrieval_hints,
    stage_duration_performance_warnings,
    export_tagset_file,
    evaluate_apollo_table_qa_results,
    tagset_report_file,
    generate_grounded_qa,
    review_apollo_table_qa_judge_candidate,
    validate_apollo_table_qa_fixture,
    validate_grounded_qa,
    wait_for_document_states,
    write_kb_asset_upload_zip,
    run_retrieval_validation,
    sanitize_report_payload,
)
from ragflow_skill_runtime.benchmark_governance import BenchmarkGovernanceError  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.health_report import HealthReportError  # noqa: E402
from ragflow_skill_runtime.kb_build import (  # noqa: E402
    KB_ASSET_INGESTION_REPORT_SCHEMA,
    KB_ASSET_UPLOAD_PLAN_SCHEMA,
    KB_REFRESH_REPORT_SCHEMA,
    extract_dataset_id,
    extract_document_states,
    extract_uploaded_document_id,
    parse_state_failed,
    parse_state_succeeded,
)
from ragflow_skill_runtime.manifests import ManifestError  # noqa: E402
from ragflow_skill_runtime.metadata_governance import MetadataGovernanceError  # noqa: E402
from ragflow_skill_runtime.parse_report import ParseReportError  # noqa: E402
from ragflow_skill_runtime.profiles import ChunkProfile  # noqa: E402
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402
from ragflow_skill_runtime.profiles import lint_profile  # noqa: E402
from ragflow_skill_runtime.topology import TopologyError  # noqa: E402
from ragflow_skill_runtime.validation import ValidationError  # noqa: E402


_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_ASSIGNMENT_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;\"']+)"
)
KB_INGESTION_CHECKPOINT_SCHEMA = "ragflow_kb_ingestion_checkpoint_v1"
OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA = "ragflow_optimization_plan_checkpoint_v1"
OPTIMIZATION_COMMAND_MANIFEST_SCHEMA = "ragflow_optimization_command_manifest_v1"
OPTIMIZATION_CLEANUP_EXECUTION_REPORT_SCHEMA = "ragflow_optimization_cleanup_execution_report_v1"
OPTIMIZATION_LIVE_READINESS_REPORT_SCHEMA = "ragflow_optimization_live_readiness_report_v1"


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _guard_quality_gate(doc_manifest, *, allow_blocked: bool) -> None:
    if not doc_manifest or allow_blocked:
        return
    gate = getattr(doc_manifest, "quality_gate", {}) or {}
    status = gate.get("status") if isinstance(gate, dict) else None
    if status == "BLOCKED":
        raise BuildError(
            "doc_manifest quality gate is BLOCKED; inspect the quality report or pass "
            "--allow-blocked to upload anyway"
        )


def _quality_gate_status(doc_manifest) -> str:
    if not doc_manifest:
        return "UNKNOWN"
    gate = getattr(doc_manifest, "quality_gate", {}) or {}
    status = gate.get("status") if isinstance(gate, dict) else None
    return str(status or "UNKNOWN")


def _estimated_chunk_lengths_for_text(text: str, *, chunk_size: int, chunk_overlap: int) -> list[int]:
    stripped = text.strip()
    if not stripped:
        return []
    target = max(int(chunk_size or 1), 1)
    step = max(target - max(int(chunk_overlap or 0), 0), 1)
    lengths: list[int] = []
    for start in range(0, len(stripped), step):
        lengths.append(min(target, len(stripped) - start))
    return lengths


def _coefficient_of_variation(values: list[int]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round((variance ** 0.5) / mean, 6)


def _estimated_chunk_size_metrics(docs: list[Any], profile: ChunkProfile) -> dict[str, Any]:
    lengths: list[int] = []
    markdown_char_count = 0
    for doc in docs:
        try:
            text = doc.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        markdown_char_count += len(text)
        lengths.extend(
            _estimated_chunk_lengths_for_text(
                text,
                chunk_size=profile.chunk_size,
                chunk_overlap=profile.chunk_overlap,
            )
        )
    average = round(sum(lengths) / len(lengths), 2) if lengths else 0.0
    return {
        "estimation_basis": "markdown_character_windows",
        "markdown_char_count": markdown_char_count,
        "estimated_chunk_count": len(lengths),
        "estimated_chunk_chars_min": min(lengths) if lengths else 0,
        "estimated_chunk_chars_max": max(lengths) if lengths else 0,
        "estimated_chunk_chars_average": average,
        "estimated_chunk_size_coefficient_of_variation": _coefficient_of_variation(lengths),
    }


def _readiness_issue_codes(ingest_readiness: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(ingest_readiness, Mapping):
        return []
    issues = ingest_readiness.get("issues")
    if not isinstance(issues, list):
        return []
    codes = []
    for issue in issues:
        if isinstance(issue, Mapping) and issue.get("code"):
            codes.append(str(issue["code"]))
    return sorted(set(codes))


def _readiness_issue_count(ingest_readiness: Mapping[str, Any] | None) -> int:
    if not isinstance(ingest_readiness, Mapping):
        return 0
    issues = ingest_readiness.get("issues")
    if not isinstance(issues, list):
        return 0
    return sum(1 for issue in issues if isinstance(issue, Mapping))


def _build_readiness_metrics(
    *,
    docs: list[Any],
    profile: ChunkProfile,
    doc_manifest: Any,
    ingest_readiness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    chunk_metrics = _estimated_chunk_size_metrics(docs, profile)
    profile_lint = lint_profile(profile).to_dict()
    profile_summary = profile_lint.get("summary") if isinstance(profile_lint.get("summary"), Mapping) else {}
    profile_issues = profile_lint.get("issues") if isinstance(profile_lint.get("issues"), list) else []
    warning_codes = sorted(
        {
            str(issue.get("code"))
            for issue in profile_issues
            if isinstance(issue, Mapping) and issue.get("severity") in {"warning", "error"} and issue.get("code")
        }
    )
    readiness_codes = _readiness_issue_codes(ingest_readiness)
    return {
        "advisory_only": True,
        "offline_only": True,
        "document_count": len(docs),
        "selected_profile_id": profile.profile_id,
        "selected_profile_chunk_size": profile.chunk_size,
        "selected_profile_chunk_overlap": profile.chunk_overlap,
        "quality_gate_status": _quality_gate_status(doc_manifest),
        "ingest_readiness_status": str(ingest_readiness.get("status")) if isinstance(ingest_readiness, Mapping) else "not_available",
        "readiness_issue_count": _readiness_issue_count(ingest_readiness),
        "readiness_issue_codes": readiness_codes,
        "parser_profile_error_count": int(profile_summary.get("errors", 0) or 0),
        "parser_profile_warning_count": int(profile_summary.get("warnings", 0) or 0),
        "parser_profile_info_count": int(profile_summary.get("infos", 0) or 0),
        "parser_profile_warning_codes": warning_codes,
        **chunk_metrics,
    }


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json_file(path: str | Path, *, label: str = "file") -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"{label} not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{label} is not valid JSON: {source}") from exc


def _dataset_items_from_response(response: Any) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping):
        return []
    data = response.get("data", response)
    if isinstance(data, Mapping):
        for key in ("datasets", "items", "list", "docs"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def _probe_kb_name_collision(client: Any, *, kb_name: str, page_size: int = 50) -> dict[str, Any]:
    try:
        response = client.list_datasets(page=1, page_size=page_size, name=kb_name)
    except Exception as exc:  # noqa: BLE001 - dry-run probe reports read-only failures as review data.
        return review_kb_name_collision(kb_name, probe_performed=True, probe_error=str(exc))
    return review_kb_name_collision(
        kb_name,
        dataset_candidates=_dataset_items_from_response(response),
        probe_performed=True,
    )


def _write_text_file(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_optional_batch_size(value: int | None, *, label: str) -> None:
    if value is not None and value <= 0:
        raise BuildError(f"{label} batch_size must be positive")


def _batch_values(values: list[str], batch_size: int | None) -> list[list[str]]:
    if not values:
        return []
    effective_size = batch_size if batch_size is not None else len(values)
    return [values[index : index + effective_size] for index in range(0, len(values), effective_size)]


def _new_batch_record(index: int, items: list[Mapping[str, Any]]) -> dict[str, Any]:
    uploaded_document_ids = [
        str(item.get("document_id"))
        for item in items
        if item.get("document_id") is not None and str(item.get("document_id"))
    ]
    document_names = [str(item.get("name") or item.get("source_path") or item.get("document_id") or "") for item in items]
    failed_items = [
        item
        for item in items
        if str(item.get("upload_status") or "uploaded") not in {"uploaded", "success"}
    ]
    retryable_failures = [
        {
            "stage": "upload",
            "message": str(item.get("error") or "upload failed"),
            "retryable": True,
            "document_ids": [],
            "document_names": [str(item.get("name") or item.get("source_path") or "")],
        }
        for item in failed_items
    ]
    if failed_items and uploaded_document_ids:
        upload_status = "partial_failure"
    elif failed_items:
        upload_status = "failed"
    else:
        upload_status = "uploaded"
    return {
        "batch_index": index,
        "planned_document_count": len(items),
        "uploaded_document_count": len(uploaded_document_ids),
        "failed_document_count": len(failed_items),
        "uploaded_document_ids": uploaded_document_ids,
        "document_names": document_names,
        "upload_status": upload_status,
        "parse_trigger_status": "pending" if uploaded_document_ids else "skipped",
        "parse_triggered": False,
        "parse_response_observed": False,
        "retryable": bool(retryable_failures),
        "retryable_failure_count": len(retryable_failures),
        "retryable_failures": retryable_failures,
    }


def _batch_records(items: list[Mapping[str, Any]], batch_size: int | None) -> list[dict[str, Any]]:
    if not items:
        return []
    effective_size = batch_size if batch_size is not None else len(items)
    return [
        _new_batch_record(index + 1, list(items[offset : offset + effective_size]))
        for index, offset in enumerate(range(0, len(items), effective_size))
    ]


def _checkpoint_source_key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def _read_ingestion_checkpoint(path: str | Path, *, operation: str) -> dict[str, Any]:
    payload = _read_json_file(path, label="ingestion checkpoint")
    if not isinstance(payload, dict):
        raise BuildError("ingestion checkpoint must be a JSON object")
    if payload.get("schema") != KB_INGESTION_CHECKPOINT_SCHEMA:
        raise BuildError(f"ingestion checkpoint schema must be {KB_INGESTION_CHECKPOINT_SCHEMA}")
    if payload.get("operation") != operation:
        raise BuildError(f"ingestion checkpoint operation must be {operation}")
    if not isinstance(payload.get("uploaded_documents", []), list):
        raise BuildError("ingestion checkpoint uploaded_documents must be a list")
    return payload


def _checkpoint_dataset_id(checkpoint: Mapping[str, Any]) -> str:
    dataset = checkpoint.get("dataset")
    if not isinstance(dataset, Mapping):
        raise BuildError("ingestion checkpoint dataset must be an object")
    dataset_id = dataset.get("id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise BuildError("ingestion checkpoint dataset.id is required for resume")
    return dataset_id


def _checkpoint_uploaded_map(checkpoint: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in checkpoint.get("uploaded_documents", []):
        if not isinstance(item, Mapping):
            continue
        document_id = item.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            continue
        if str(item.get("upload_status") or "uploaded") not in {"uploaded", "success"}:
            continue
        key = item.get("source_key") or item.get("source_path")
        if isinstance(key, str) and key:
            records[key] = dict(item)
    return records


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _checkpoint_report(
    *,
    checkpoint_path: str | None,
    resume: bool,
    force_reupload_confirmed: bool,
    skipped_upload_count: int,
    new_upload_count: int,
    total_confirmed_upload_count: int,
) -> dict[str, Any]:
    return {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "force_reupload_confirmed": bool(force_reupload_confirmed),
        "skipped_upload_count": skipped_upload_count,
        "new_upload_count": new_upload_count,
        "total_confirmed_upload_count": total_confirmed_upload_count,
    }


def _write_ingestion_checkpoint(
    checkpoint_path: str | None,
    *,
    operation: str,
    dataset_id: str,
    dataset_name: str | None,
    records: Mapping[str, Mapping[str, Any]],
    created_at: str | None = None,
) -> dict[str, Any] | None:
    if not checkpoint_path:
        return None
    uploaded_documents = [dict(record) for _key, record in sorted(records.items())]
    now = _utc_now()
    payload = {
        "schema": KB_INGESTION_CHECKPOINT_SCHEMA,
        "created_at": created_at or now,
        "updated_at": now,
        "operation": operation,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "uploaded_documents": uploaded_documents,
        "summary": {
            "uploaded_document_count": sum(
                1
                for record in uploaded_documents
                if record.get("document_id") and str(record.get("upload_status") or "uploaded") in {"uploaded", "success"}
            ),
            "parse_triggered_document_count": sum(
                1 for record in uploaded_documents if str(record.get("parse_trigger_status") or "") == "success"
            ),
            "parse_waited_document_count": sum(
                1 for record in uploaded_documents if str(record.get("parse_wait_status") or "") == "success"
            ),
        },
    }
    _write_json_file(checkpoint_path, payload)
    return payload


def _mark_batch_parse_skipped(batch: dict[str, Any]) -> None:
    batch["parse_trigger_status"] = "skipped"
    batch["parse_triggered"] = False
    batch["parse_response_observed"] = False


def _mark_batch_parse_success(batch: dict[str, Any], response: Any) -> None:
    batch["parse_trigger_status"] = "success"
    batch["parse_triggered"] = True
    batch["parse_response_observed"] = response is not None


def _mark_batch_parse_failure(batch: dict[str, Any], exc: Exception) -> None:
    batch["parse_trigger_status"] = "failed"
    batch["parse_triggered"] = False
    batch["parse_response_observed"] = False
    failures = list(batch.get("retryable_failures") or [])
    failures.append(
        {
            "stage": "parse_trigger",
            "message": str(exc),
            "retryable": True,
            "document_ids": list(batch.get("uploaded_document_ids") or []),
            "document_names": list(batch.get("document_names") or []),
        }
    )
    batch["retryable_failures"] = failures
    batch["retryable"] = bool(failures)
    batch["retryable_failure_count"] = len(failures)


def _batching_summary(
    *,
    requested_batch_size: int | None,
    planned_document_count: int,
    uploaded_document_count: int,
    parse_batch_count: int,
    parse_document_count: int,
    batches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    batch_records = list(batches or [])
    parse_batch_attempt_count = (
        sum(
            1
            for batch in batch_records
            if str(batch.get("parse_trigger_status") or "") in {"success", "failed"}
        )
        if batch_records
        else parse_batch_count
    )
    failed_batch_count = sum(
        1
        for batch in batch_records
        if str(batch.get("parse_trigger_status") or "") == "failed"
        or str(batch.get("upload_status") or "") in {"failed", "partial_failure"}
    )
    retryable_failure_count = sum(int(batch.get("retryable_failure_count") or 0) for batch in batch_records)
    effective_batch_size = requested_batch_size if requested_batch_size is not None else (
        planned_document_count if planned_document_count > 0 else None
    )
    planned_batch_count = (
        len(_batch_values([""] * planned_document_count, requested_batch_size))
        if planned_document_count > 0
        else 0
    )
    return {
        "enabled": requested_batch_size is not None,
        "requested_batch_size": requested_batch_size,
        "effective_batch_size": effective_batch_size,
        "planned_document_count": planned_document_count,
        "planned_batch_count": planned_batch_count,
        "uploaded_document_count": uploaded_document_count,
        "parse_batch_count": parse_batch_count,
        "parse_batch_attempt_count": parse_batch_attempt_count,
        "parse_document_count": parse_document_count,
        "failed_batch_count": failed_batch_count,
        "retryable_failure_count": retryable_failure_count,
        "batches": batch_records,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(item).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_hash_map(paths: list[str | None]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        source = Path(path)
        if source.exists() and source.is_file():
            hashes[str(source)] = _sha256_file(source)
        elif source.exists() and source.is_dir():
            hashes[str(source)] = _sha256_directory(source)
    return hashes


def _resolve_retrieval_hints_path(args: argparse.Namespace) -> Path | None:
    retrieval_hints_path = Path(args.retrieval_hints) if args.retrieval_hints else None
    if retrieval_hints_path is None and args.doc_manifest:
        candidate_hints = Path(args.doc_manifest).parent / "retrieval_hints.json"
        if candidate_hints.is_file():
            retrieval_hints_path = candidate_hints
    return retrieval_hints_path


def _resolve_profile_suggestions_path(args: argparse.Namespace) -> Path | None:
    if not args.doc_manifest:
        return None
    candidate = Path(args.doc_manifest).parent / "profile_suggestions.json"
    return candidate if candidate.is_file() else None


def _resolve_ingest_plan_path(args: argparse.Namespace) -> Path | None:
    ingest_plan_path = Path(args.ingest_plan) if getattr(args, "ingest_plan", None) else None
    if ingest_plan_path is None and args.doc_manifest:
        handoff_root = Path(args.doc_manifest).parent
        for name in ("ragflow_ingest_plan.yaml", "ragflow_ingest_plan.yml", "ragflow_ingest_plan.json"):
            candidate = handoff_root / name
            if candidate.is_file():
                return candidate
    return ingest_plan_path


def _load_ingest_plan_for_build(args: argparse.Namespace) -> dict[str, Any] | None:
    ingest_plan_path = _resolve_ingest_plan_path(args)
    if ingest_plan_path is None:
        return None
    try:
        return load_ragflow_ingest_plan(ingest_plan_path)
    except HandoffError as exc:
        raise BuildError(str(exc)) from exc


def _post_build_recommendations(
    args: argparse.Namespace,
    *,
    kb_manifest_path: str | Path,
    retrieval_hints_path: str | Path | None,
) -> list[dict[str, Any]]:
    activation_output = Path(kb_manifest_path).with_name("kb_activation_plan.json")
    activation_report_md = Path(kb_manifest_path).with_name("kb_activation_plan.md")
    command: list[str] = [
        "python",
        "scripts/build.py",
        "activation-plan",
        "--kb-manifest",
        str(kb_manifest_path),
    ]
    missing_inputs: list[str] = []
    if args.doc_manifest:
        command.extend(["--doc-manifest", str(args.doc_manifest)])
    else:
        missing_inputs.append("doc_manifest")
    if retrieval_hints_path:
        command.extend(["--retrieval-hints", str(retrieval_hints_path)])
    if args.profile:
        command.extend(["--profile", str(args.profile)])
    else:
        missing_inputs.append("profile")
    command.extend(["--output", str(activation_output), "--report-md", str(activation_report_md), "--json"])
    return [
        {
            "id": "activation-plan",
            "label": "Review KB activation readiness",
            "recommended_when": "after_build_manifest_exists",
            "mutates_ragflow": False,
            "advisory_only": True,
            "requires_artifacts": ["kb_manifest", "doc_manifest"],
            "optional_artifacts": [
                "retrieval_hints",
                "route_config",
                "ingest_plan",
                "chunk_snapshot",
                "route_tests",
            ],
            "missing_required_inputs": missing_inputs,
            "command": command,
            "expected_artifacts": [str(activation_output), str(activation_report_md)],
            "purpose": "Check content, chunk, route, hint, profile, and route-test readiness before editing user-owned routing config.",
        }
    ]


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_path_token(path: Any, *, artifact_dir: str | Path | None) -> str:
    text = str(path)
    if not text:
        return text
    if artifact_dir:
        artifact_root = Path(artifact_dir)
        try:
            relative = Path(text).relative_to(artifact_root)
            return f"<artifact-dir>/{relative.as_posix()}"
        except ValueError:
            pass
    if "://" in text:
        return text
    path_obj = Path(text)
    if path_obj.is_absolute():
        try:
            return f"<cwd>/{path_obj.relative_to(Path.cwd()).as_posix()}"
        except ValueError:
            return f"<path>/{path_obj.name}"
    return path_obj.as_posix()


def _manifest_command_tokens(command: list[Any] | None, *, artifact_dir: str | Path | None) -> list[str]:
    if not command:
        return []
    tokens: list[str] = []
    for token in command:
        text = str(token)
        if "/" in text or "\\" in text or text.endswith((".json", ".md", ".yaml", ".yml", ".py", ".txt")):
            tokens.append(_manifest_path_token(text, artifact_dir=artifact_dir))
        else:
            tokens.append(text)
    return tokens


def _command_entry(
    *,
    command_id: str,
    label: str,
    command: list[Any] | None,
    mutates_ragflow: bool,
    mutation_label: str,
    required_config: list[str],
    expected_artifacts: list[Any],
    cleanup_notes: list[str],
    artifact_dir: str | Path | None,
    enabled: bool = True,
    requires_execute: bool = False,
    source_profile_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": command_id,
        "label": label,
        "profile_id": source_profile_id,
        "enabled": bool(enabled),
        "requires_execute": bool(requires_execute),
        "command": _manifest_command_tokens(command, artifact_dir=artifact_dir),
        "mutates_ragflow": bool(mutates_ragflow),
        "mutation_label": mutation_label,
        "required_config": required_config,
        "missing_config": list(required_config),
        "expected_artifacts": [
            {
                "path": _manifest_path_token(path, artifact_dir=artifact_dir),
                "when": "on_success",
            }
            for path in expected_artifacts
            if path
        ],
        "cleanup_notes": cleanup_notes,
    }


def _build_optimization_command_manifest(plan: Mapping[str, Any], *, output_path: str | Path | None = None) -> dict[str, Any]:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    inputs = plan.get("inputs") if isinstance(plan.get("inputs"), Mapping) else {}
    documents = inputs.get("documents") if isinstance(inputs.get("documents"), list) else []
    artifact_dir = None
    if candidates:
        first = candidates[0]
        if isinstance(first, Mapping):
            artifacts = first.get("artifacts") if isinstance(first.get("artifacts"), Mapping) else {}
            kb_manifest = artifacts.get("kb_manifest")
            if kb_manifest:
                artifact_dir = Path(str(kb_manifest)).parent.parent
    commands: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        profile_id = str(candidate.get("profile_id") or f"candidate-{index + 1}")
        artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), Mapping) else {}
        planned = candidate.get("commands") if isinstance(candidate.get("commands"), Mapping) else {}
        mutation_commands = candidate.get("mutation_commands") if isinstance(candidate.get("mutation_commands"), Mapping) else {}
        build = mutation_commands.get("build") if isinstance(mutation_commands.get("build"), Mapping) else {}
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:build-disposable-kb",
                label=f"Build disposable KB for {profile_id}",
                command=build.get("command") if isinstance(build.get("command"), list) else [],
                mutates_ragflow=True,
                mutation_label="creates_dataset_uploads_documents_and_triggers_parse",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[artifacts.get("kb_manifest")],
                cleanup_notes=[
                    "Disabled in command-manifest dry-run.",
                    "Requires optimize --execute and explicit user confirmation before mutation.",
                    "After live execution, retain the generated kb_manifest.json so cleanup can confirm the exact dataset id and KB name.",
                ],
                artifact_dir=artifact_dir,
                enabled=bool(build.get("enabled")),
                requires_execute=bool(build.get("requires_execute", True)),
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:benchmark-validation",
                label=f"Run benchmark validation for {profile_id}",
                command=planned.get("validate") if isinstance(planned.get("validate"), list) else [],
                mutates_ragflow=False,
                mutation_label="read_only_benchmark_validation",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[artifacts.get("validation_report"), artifacts.get("validation_report_md")],
                cleanup_notes=["No cleanup is required for read-only validation."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:diagnose",
                label=f"Diagnose failed or zero-chunk result for {profile_id}",
                command=planned.get("diagnose") if isinstance(planned.get("diagnose"), list) else [],
                mutates_ragflow=False,
                mutation_label="local_or_read_only_diagnostics",
                required_config=[],
                expected_artifacts=[artifacts.get("diagnostic_report")],
                cleanup_notes=["Diagnostics are advisory and do not create or delete RAGFlow datasets."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:cleanup-preview",
                label=f"Create cleanup preview for {profile_id}",
                command=planned.get("cleanup_preview") if isinstance(planned.get("cleanup_preview"), list) else [],
                mutates_ragflow=False,
                mutation_label="local_cleanup_plan",
                required_config=[],
                expected_artifacts=[artifacts.get("cleanup_plan")],
                cleanup_notes=["Cleanup preview does not delete RAGFlow datasets."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )

    manifest = {
        "ok": bool(plan.get("ok")),
        "schema": OPTIMIZATION_COMMAND_MANIFEST_SCHEMA,
        "created_at": _utc_now(),
        "mode": "dry_run",
        "source": "ragflow-kb-build optimize --plan-only",
        "plan_schema": plan.get("schema"),
        "plan_output": _manifest_path_token(output_path, artifact_dir=artifact_dir) if output_path else None,
        "run_id": plan.get("run_id"),
        "base_kb_name": plan.get("base_kb_name"),
        "mutation_guard": {
            "mutation_allowed": False,
            "execute_required": True,
            "execute_flag": "--execute",
            "cleanup_confirmation_required": True,
            "cleanup_confirmation_flags": ["--confirm-dataset-id", "--confirm-kb-name"],
            "live_execution_status": "gated_build_available_validation_optional_cleanup_pending",
        },
        "inputs": {
            "input": _manifest_path_token(inputs.get("input"), artifact_dir=artifact_dir) if inputs.get("input") else None,
            "doc_manifest": _manifest_path_token(inputs.get("doc_manifest"), artifact_dir=artifact_dir)
            if inputs.get("doc_manifest")
            else None,
            "documents": [_manifest_path_token(item, artifact_dir=artifact_dir) for item in documents],
        },
        "commands": commands,
        "expected_artifacts": [
            artifact
            for command in commands
            for artifact in command["expected_artifacts"]
        ],
        "cleanup": {
            "required_after_live_execution": any(command["mutates_ragflow"] for command in commands),
            "notes": [
                "Review this manifest before enabling any future live optimization execution.",
                "Do not run mutating commands without credentials, explicit confirmation, and a cleanup plan.",
                "Retain candidate kb_manifest.json files after live execution; cleanup needs exact dataset ids and KB names.",
            ],
        },
        "summary": {
            "candidate_count": len(candidates),
            "command_count": len(commands),
            "mutating_command_count": sum(1 for command in commands if command["mutates_ragflow"]),
            "enabled_mutating_command_count": sum(
                1 for command in commands if command["mutates_ragflow"] and command["enabled"]
            ),
            "expected_artifact_count": sum(len(command["expected_artifacts"]) for command in commands),
        },
    }
    return manifest


def _require_optimize_execute_confirmation(args: argparse.Namespace, plan: Mapping[str, Any]) -> None:
    if not args.confirm_live_build:
        raise ProfileError("optimize --execute requires --confirm-live-build")
    if args.confirm_kb_name != plan.get("base_kb_name"):
        raise ProfileError("optimize --execute requires --confirm-kb-name to match --kb-name exactly")
    if args.confirm_run_id != plan.get("run_id"):
        raise ProfileError("optimize --execute requires --confirm-run-id to match the planned run_id exactly")


def _build_candidate_kb(
    *,
    candidate: Mapping[str, Any],
    docs: list[Any],
    config: Any,
    client: Any,
    metadata_summary: dict[str, Any] | None,
    parse_timeout: float,
    poll_interval: float,
    no_parse: bool,
    no_wait: bool,
) -> dict[str, Any]:
    profile_payload = candidate.get("profile") if isinstance(candidate.get("profile"), Mapping) else None
    if profile_payload is None:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing profile payload")
    profile = ChunkProfile.from_dict(profile_payload)
    kb_name = str(candidate.get("disposable_kb_name") or "")
    if not kb_name:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing disposable_kb_name")
    artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), Mapping) else {}
    manifest_path = artifacts.get("kb_manifest")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing artifacts.kb_manifest")

    dataset_response = client.create_dataset(kb_name, profile=profile.to_dataset_payload())
    dataset_id = extract_dataset_id(dataset_response)
    build_language = profile.build_language
    if build_language:
        client.update_dataset(dataset_id, {"language": build_language})
    uploaded = []
    document_ids: list[str] = []
    for doc in docs:
        response = client.upload_document(dataset_id, doc.path)
        document_id = extract_uploaded_document_id(response)
        document_ids.append(document_id)
        uploaded.append((doc, document_id, "uploaded", None))

    parse_response = None
    live_states = {}
    if document_ids and not no_parse:
        parse_response = client.trigger_parse(dataset_id, document_ids)
        if not no_wait:
            live_states = wait_for_document_states(
                client,
                dataset_id=dataset_id,
                document_ids=document_ids,
                timeout=parse_timeout,
                poll_interval=poll_interval,
            )
            uploaded = [
                (
                    doc,
                    document_id,
                    live_states.get(document_id, {}).get("status", status),
                    live_states.get(document_id, {}).get("chunk_count", chunk_count),
                )
                for doc, document_id, status, chunk_count in uploaded
            ]

    payload = make_kb_manifest_payload(
        base_url=config.base_url,
        dataset_id=dataset_id,
        dataset_name=kb_name,
        profile=profile,
        documents=uploaded,
    )
    if metadata_summary:
        payload["metadata_summary"] = metadata_summary
    _write_json_file(manifest_path, payload)
    return {
        "profile_id": candidate.get("profile_id"),
        "disposable_kb_name": kb_name,
        "kb_manifest": manifest_path,
        "dataset_id": dataset_id,
        "document_count": len(uploaded),
        "parse_triggered": bool(document_ids and not no_parse),
        "parse_waited": bool(document_ids and not no_parse and not no_wait),
        "parse_response": parse_response,
        "cleanup_required": True,
    }


def _validate_candidate_benchmark(
    *,
    candidate: Mapping[str, Any],
    client: Any,
    queries_path: str | None,
    qrels_path: str | None,
    gate_config_path: str | None,
    baseline_report_path: str | None,
    chunk_snapshot_path: str | None,
    metadata_summary: dict[str, Any] | None,
    top_k: int,
    metric_cutoff: int | None,
) -> dict[str, Any]:
    if not queries_path:
        raise ValidationError("optimize --validate-benchmark requires benchmark queries")
    if not qrels_path:
        raise ValidationError("optimize --validate-benchmark requires benchmark qrels")
    artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), Mapping) else {}
    manifest_path = artifacts.get("kb_manifest")
    report_path = artifacts.get("validation_report")
    report_md_path = artifacts.get("validation_report_md")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ValidationError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing artifacts.kb_manifest")
    if not isinstance(report_path, str) or not report_path:
        raise ValidationError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing artifacts.validation_report")
    if not isinstance(report_md_path, str) or not report_md_path:
        raise ValidationError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing artifacts.validation_report_md")

    manifest = load_kb_manifest(manifest_path)
    queries = load_validation_queries(queries_path)
    report = run_retrieval_validation(
        client,
        level="benchmark",
        dataset_id=manifest.dataset.id,
        dataset_name=manifest.dataset.name,
        queries=queries,
        top_k=top_k,
    )
    report = attach_benchmark_evaluation(
        report,
        qrels=load_benchmark_qrels(qrels_path),
        cutoff=metric_cutoff or top_k,
        gate=load_benchmark_gate(gate_config_path) if gate_config_path else None,
        baseline_metrics=load_benchmark_baseline(baseline_report_path) if baseline_report_path else None,
        baseline_path=baseline_report_path,
        chunk_snapshot=load_chunk_snapshot(chunk_snapshot_path) if chunk_snapshot_path else None,
    )
    payload = report.to_dict()
    if metadata_summary:
        payload["metadata_summary"] = metadata_summary
    _write_json_file(report_path, payload)
    _write_text_file(report_md_path, render_markdown_report(report))
    benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), Mapping) else {}
    metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), Mapping) else {}
    benchmark_metric_keys = (
        "query_count",
        "hit_rate",
        "mrr",
        "precision_at_k",
        "recall_at_k",
        "ndcg_at_k",
        "map_at_k",
        "strict_chunk_recall_at_k",
        "expected_chunk_hit_rate",
        "candidate_snapshot_expected_chunk_recall_at_k",
        "candidate_snapshot_expected_chunk_hit_rate",
        "expected_term_recall_at_k",
        "expected_term_hit_rate",
        "table_term_recall_at_k",
        "table_term_hit_rate",
        "empty_result_rate",
    )
    benchmark_metrics = {
        key: metrics[key]
        for key in benchmark_metric_keys
        if isinstance(metrics.get(key), (int, float))
    }
    return {
        "profile_id": candidate.get("profile_id"),
        "disposable_kb_name": candidate.get("disposable_kb_name"),
        "validation_report": report_path,
        "validation_report_md": report_md_path,
        "ok": bool(payload.get("ok")),
        "query_count": int(metrics.get("query_count") or 0),
        "benchmark_metrics": benchmark_metrics,
        "metrics": {
            key: metrics[key]
            for key in (
                "hit_rate",
                "mrr",
                "precision_at_k",
                "recall_at_k",
                "ndcg_at_k",
                "map_at_k",
                "empty_result_rate",
            )
            if isinstance(metrics.get(key), (int, float))
        },
    }


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


def _collect_path_like_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if (
            "/" in text
            or "\\" in text
            or text.startswith(("~", "."))
            or text.endswith((".json", ".jsonl", ".md", ".yaml", ".yml", ".py", ".toml", ".txt"))
        ):
            paths = [text]
            if "://" not in text:
                path = Path(text)
                if str(path.parent) not in {"", ".", "/"}:
                    paths.append(str(path.parent))
            return paths
        return []
    if isinstance(value, dict):
        paths: list[str] = []
        for item in value.values():
            paths.extend(_collect_path_like_literals(item))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            paths.extend(_collect_path_like_literals(item))
        return paths
    return []


def _expand_config_paths(paths: list[str | None]) -> list[str | None]:
    expanded: list[str | None] = []
    for raw_path in paths:
        if not raw_path:
            continue
        text = str(raw_path)
        expanded.append(text)
        if "://" in text:
            continue
        parent = Path(text).parent
        if str(parent) not in {"", ".", "/"}:
            expanded.append(str(parent))
    return expanded


def _collect_redaction_context_from_json_paths(paths: list[str | None]) -> tuple[list[str], list[str], list[str]]:
    secrets: list[str] = []
    hosts: list[str] = []
    path_literals: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        try:
            payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            continue
        secrets.extend(_collect_secret_literals(payload))
        hosts.extend(configured_private_hosts_from_urls(_collect_urls(payload)))
        path_literals.extend(_collect_path_like_literals(payload))
    return secrets, hosts, path_literals


def _sanitize_governance_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None],
    output_paths: list[str | None] | None = None,
    extra_secret_literals: list[str] | None = None,
    extra_private_hosts: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    config_paths = [
        *_expand_config_paths(input_paths),
        *_expand_config_paths(output_paths or []),
        *_expand_config_paths(
            [
                getattr(args, "report_json", None),
                getattr(args, "report_md", None),
                getattr(args, "redaction_report", None),
            ]
        ),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[*_collect_secret_literals(report), *(extra_secret_literals or [])],
        private_hosts=[*configured_private_hosts_from_urls(urls), *(extra_private_hosts or [])],
        config_paths=config_paths,
    )
    return sanitized, redaction_report


def _run(args: argparse.Namespace) -> int:
    try:
        _validate_optional_batch_size(args.batch_size, label="build")
        if args.resume and not args.checkpoint:
            raise BuildError("build --resume requires --checkpoint")
        if args.force_reupload_confirmed and not args.resume:
            raise BuildError("build --force-reupload-confirmed requires --resume")
        if args.dry_run and args.resume:
            raise BuildError("build --resume is only supported for live builds")
        stage_results: list[dict[str, Any]] = []
        stage_latency_ms: list[float] = []
        stage_timings: list[dict[str, Any]] = []
        source_profile = load_profile(args.profile)
        ragflow_ingest_plan_path = _resolve_ingest_plan_path(args)
        ragflow_ingest_plan = _load_ingest_plan_for_build(args)
        profile = apply_build_profile_language(source_profile, ragflow_ingest_plan=ragflow_ingest_plan)
        expected_embedding_models = normalize_embedding_model_expectations(args.expected_embedding_model)
        embedding_model = describe_embedding_model(profile)
        embedding_model_check = check_embedding_model_drift(embedding_model, expected_embedding_models)
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        metadata_summary = summarize_metadata_for_documents(args.metadata, [doc.path for doc in docs])
        if metadata_summary and not metadata_summary.get("ok", False):
            raise BuildError("metadata lint failed; run metadata lint for details")
        retrieval_hints_payload = None
        retrieval_hints_path = _resolve_retrieval_hints_path(args)
        if retrieval_hints_path:
            loaded_hints = _read_json_file(retrieval_hints_path, label="retrieval hints")
            if not isinstance(loaded_hints, Mapping):
                raise BuildError("retrieval hints must be a JSON object")
            retrieval_hints_payload = loaded_hints
        profile_suggestions_payload = None
        profile_suggestions_path = _resolve_profile_suggestions_path(args)
        if profile_suggestions_path:
            loaded_profile_suggestions = _read_json_file(profile_suggestions_path, label="profile suggestions")
            if not isinstance(loaded_profile_suggestions, Mapping):
                raise BuildError("profile suggestions must be a JSON object")
            profile_suggestions_payload = loaded_profile_suggestions
        metadata_payload = None
        if args.metadata and Path(args.metadata).suffix.lower() == ".json":
            loaded_metadata = _read_json_file(args.metadata, label="metadata")
            if isinstance(loaded_metadata, Mapping):
                metadata_payload = loaded_metadata
        handoff_consumption_status = make_handoff_consumption_status(
            doc_manifest_path=args.doc_manifest,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints=retrieval_hints_payload,
            retrieval_hints_path=retrieval_hints_path,
            ragflow_ingest_plan=ragflow_ingest_plan,
            ragflow_ingest_plan_path=ragflow_ingest_plan_path,
        )
        if args.dry_run:
            ingest_readiness: dict[str, Any] | None = None
            table_parent_chunk_preflight = {"exists": False, "status": "not_available", "table_count": 0}
            kb_name_collision_review: dict[str, Any]
            if args.doc_manifest:
                try:
                    readiness = make_doc_ingest_readiness_payload(
                        handoff_root=Path(args.doc_manifest).parent,
                        doc_manifest_name=Path(args.doc_manifest).name,
                        selected_profile=profile.to_manifest_dict(),
                    )
                    ingest_readiness = readiness
                    checks = readiness.get("checks") if isinstance(readiness.get("checks"), Mapping) else {}
                    table_parent_chunk_preflight = (
                        checks.get("table_parent_chunk_preflight")
                        if isinstance(checks.get("table_parent_chunk_preflight"), Mapping)
                        else table_parent_chunk_preflight
                    )
                except Exception as exc:
                    table_parent_chunk_preflight = {
                        "exists": False,
                        "status": "not_available",
                        "table_count": 0,
                        "error": str(exc),
                    }
            if args.probe_kb_name_collision:
                try:
                    config = _load_config(args)
                    client = RAGFlowClient(config)
                    kb_name_collision_review = _probe_kb_name_collision(client, kb_name=args.kb_name)
                except Exception as exc:  # noqa: BLE001 - dry-run keeps endpoint probe failures advisory.
                    kb_name_collision_review = review_kb_name_collision(
                        args.kb_name,
                        probe_performed=True,
                        probe_error=str(exc),
                    )
            else:
                kb_name_collision_review = review_kb_name_collision(args.kb_name)
            _dump_json(
                {
                    "ok": True,
                    "dry_run": True,
                    "kb_name": args.kb_name,
                    "profile": profile.to_manifest_dict(),
                    "embedding_model": embedding_model,
                    "embedding_model_check": embedding_model_check,
                    "documents": [str(doc.path) for doc in docs],
                    "metadata_summary": metadata_summary,
                    "retrieval_hints_summary": summarize_retrieval_hints(retrieval_hints_payload),
                    "build_payload_preview": make_build_payload_preview(
                        kb_name=args.kb_name,
                        profile=source_profile,
                        retrieval_hints=retrieval_hints_payload,
                        ragflow_ingest_plan=ragflow_ingest_plan,
                    ),
                    "handoff_consumption_status": handoff_consumption_status,
                    "parameter_materialization_inventory": make_parameter_materialization_inventory(
                        profile=source_profile,
                        profile_suggestions=profile_suggestions_payload,
                        retrieval_hints=retrieval_hints_payload,
                        ragflow_ingest_plan=ragflow_ingest_plan,
                        metadata=metadata_payload,
                    ),
                    "ingest_readiness": ingest_readiness,
                    "build_readiness_metrics": _build_readiness_metrics(
                        docs=docs,
                        profile=profile,
                        doc_manifest=doc_manifest,
                        ingest_readiness=ingest_readiness,
                    ),
                    "kb_name_collision_review": kb_name_collision_review,
                    "table_parent_chunk_preflight": table_parent_chunk_preflight,
                    "batching": _batching_summary(
                        requested_batch_size=args.batch_size,
                        planned_document_count=len(docs),
                        uploaded_document_count=0,
                        parse_batch_count=0,
                        parse_document_count=0,
                    ),
                    "post_build_recommendations": _post_build_recommendations(
                        args,
                        kb_manifest_path=args.output,
                        retrieval_hints_path=retrieval_hints_path,
                    ),
                }
            )
            return 0

        config = _load_config(args)
        client = RAGFlowClient(config)
        build_payload_preview = make_build_payload_preview(
            kb_name=args.kb_name,
            profile=source_profile,
            retrieval_hints=retrieval_hints_payload,
            ragflow_ingest_plan=ragflow_ingest_plan,
        )
        checkpoint_payload: dict[str, Any] | None = None
        checkpoint_created_at: str | None = None
        checkpoint_records: dict[str, dict[str, Any]] = {}
        confirmed_uploads: dict[str, dict[str, Any]] = {}
        checkpoint_skipped_upload_count = 0
        checkpoint_new_upload_count = 0
        if args.resume:
            checkpoint_payload = _read_ingestion_checkpoint(args.checkpoint, operation="markdown_build")
            checkpoint_created_at = str(checkpoint_payload.get("created_at") or "") or None
            checkpoint_dataset = checkpoint_payload.get("dataset") if isinstance(checkpoint_payload.get("dataset"), Mapping) else {}
            checkpoint_kb_name = checkpoint_dataset.get("name") if isinstance(checkpoint_dataset, Mapping) else None
            if checkpoint_kb_name and checkpoint_kb_name != args.kb_name:
                raise BuildError("ingestion checkpoint dataset.name does not match --kb-name")
            dataset_id = _checkpoint_dataset_id(checkpoint_payload)
            confirmed_uploads = _checkpoint_uploaded_map(checkpoint_payload)
            stage_results.append({"label": "create_dataset", "status": "skipped"})
        else:
            stage_start = datetime.now(timezone.utc)
            dataset_response = client.create_dataset(args.kb_name, profile=profile.to_dataset_payload())
            elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
            stage_latency_ms.append(elapsed_ms)
            stage_timings.append(
                {
                    "stage": "create_dataset",
                    "operation": "create_dataset",
                    "status": "success",
                    "duration_ms": elapsed_ms,
                }
            )
            dataset_id = extract_dataset_id(dataset_response)
            build_language = profile.build_language
            if build_language:
                client.update_dataset(dataset_id, {"language": build_language})
            stage_results.append({"label": "create_dataset", "status": "success"})
            _write_ingestion_checkpoint(
                args.checkpoint,
                operation="markdown_build",
                dataset_id=dataset_id,
                dataset_name=args.kb_name,
                records=checkpoint_records,
            )

        uploaded = []
        document_ids: list[str] = []
        parse_items: list[dict[str, Any]] = []
        parse_success_document_ids: list[str] = []
        markdown_upload_duration_ms = 0.0
        markdown_upload_count = 0
        parse_wait_duration_ms = 0.0
        parse_wait_document_count = 0
        for doc in docs:
            source_key = _checkpoint_source_key(doc.path)
            confirmed = confirmed_uploads.get(source_key) if not args.force_reupload_confirmed else None
            if confirmed:
                document_id = str(confirmed["document_id"])
                status = str(confirmed.get("status") or "uploaded")
                chunk_count = _optional_int(confirmed.get("chunk_count"))
                document_ids.append(document_id)
                uploaded.append((doc, document_id, status, chunk_count))
                checkpoint_records[source_key] = {
                    **confirmed,
                    "kind": "markdown",
                    "source_key": source_key,
                    "source_path": str(doc.path),
                    "name": doc.path.name,
                    "document_id": document_id,
                    "upload_status": "uploaded",
                    "checkpoint_resumed": True,
                }
                checkpoint_skipped_upload_count += 1
                parse_trigger_status = str(confirmed.get("parse_trigger_status") or "")
                parse_wait_status = str(confirmed.get("parse_wait_status") or "")
                if args.no_parse:
                    checkpoint_records[source_key]["parse_trigger_status"] = "skipped"
                    checkpoint_records[source_key]["parse_wait_status"] = "skipped"
                elif parse_trigger_status == "success":
                    if not args.no_wait and parse_wait_status != "success":
                        parse_success_document_ids.append(document_id)
                else:
                    parse_items.append(
                        {
                            "name": doc.path.name,
                            "source_key": source_key,
                            "source_path": str(doc.path),
                            "document_id": document_id,
                            "upload_status": "uploaded",
                        }
                    )
                continue
            stage_start = datetime.now(timezone.utc)
            response = client.upload_document(dataset_id, doc.path)
            elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
            stage_latency_ms.append(elapsed_ms)
            document_id = extract_uploaded_document_id(response)
            stage_timings.append(
                {
                    "stage": "markdown_upload",
                    "operation": "upload_document",
                    "status": "success",
                    "duration_ms": elapsed_ms,
                    "document_id": document_id,
                    "document_count": 1,
                }
            )
            markdown_upload_duration_ms += elapsed_ms
            markdown_upload_count += 1
            document_ids.append(document_id)
            uploaded.append((doc, document_id, "uploaded", None))
            item = {
                "name": doc.path.name,
                "source_key": source_key,
                "source_path": str(doc.path),
                "document_id": document_id,
                "upload_status": "uploaded",
            }
            parse_items.append(item)
            checkpoint_records[source_key] = {
                "kind": "markdown",
                "source_key": source_key,
                "source_path": str(doc.path),
                "name": doc.path.name,
                "document_id": document_id,
                "upload_status": "uploaded",
                "status": "uploaded",
                "chunk_count": None,
                "parse_trigger_status": "skipped" if args.no_parse else "pending",
                "parse_triggered": False,
                "parse_wait_status": "skipped" if args.no_parse or args.no_wait else "pending",
            }
            checkpoint_new_upload_count += 1
            stage_results.append({"label": f"upload:{doc.path.name}", "status": "success"})
            _write_ingestion_checkpoint(
                args.checkpoint,
                operation="markdown_build",
                dataset_id=dataset_id,
                dataset_name=args.kb_name,
                records=checkpoint_records,
                created_at=checkpoint_created_at,
            )

        parse_response = None
        parse_responses: list[Any] = []
        parse_errors: list[str] = []
        parse_failed_document_ids: set[str] = set()
        batch_records = _batch_records(parse_items, args.batch_size)
        live_states = {}
        if (parse_items or parse_success_document_ids) and not args.no_parse:
            if not parse_items:
                stage_results.append({"label": "trigger_parse", "status": "skipped"})
            for batch in batch_records:
                parse_batch = list(batch.get("uploaded_document_ids") or [])
                if not parse_batch:
                    _mark_batch_parse_skipped(batch)
                    continue
                stage_start = datetime.now(timezone.utc)
                parse_trigger_status = "success"
                try:
                    response = client.trigger_parse(dataset_id, parse_batch)
                    parse_responses.append(response)
                    parse_success_document_ids.extend(parse_batch)
                    _mark_batch_parse_success(batch, response)
                    for record in checkpoint_records.values():
                        if record.get("document_id") in parse_batch:
                            record["parse_trigger_status"] = "success"
                            record["parse_triggered"] = True
                            if args.no_wait:
                                record["parse_wait_status"] = "skipped"
                    stage_results.append({"label": f"trigger_parse:{batch['batch_index']}", "status": "success"})
                except Exception as exc:
                    parse_trigger_status = "error"
                    parse_errors.append(str(exc))
                    parse_failed_document_ids.update(parse_batch)
                    _mark_batch_parse_failure(batch, exc)
                    for record in checkpoint_records.values():
                        if record.get("document_id") in parse_batch:
                            record["parse_trigger_status"] = "failed"
                            record["parse_triggered"] = False
                            record["parse_wait_status"] = "skipped"
                    stage_results.append({"label": f"trigger_parse:{batch['batch_index']}", "status": "error"})
                    _write_ingestion_checkpoint(
                        args.checkpoint,
                        operation="markdown_build",
                        dataset_id=dataset_id,
                        dataset_name=args.kb_name,
                        records=checkpoint_records,
                        created_at=checkpoint_created_at,
                    )
                    break
                finally:
                    elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                    stage_latency_ms.append(elapsed_ms)
                    stage_timings.append(
                        {
                            "stage": "trigger_parse",
                            "operation": "trigger_parse",
                            "status": parse_trigger_status,
                            "duration_ms": elapsed_ms,
                            "batch_index": batch.get("batch_index"),
                            "document_count": len(parse_batch),
                        }
                    )
                    _write_ingestion_checkpoint(
                        args.checkpoint,
                        operation="markdown_build",
                        dataset_id=dataset_id,
                        dataset_name=args.kb_name,
                        records=checkpoint_records,
                        created_at=checkpoint_created_at,
                    )
            parse_response = parse_responses[0] if len(parse_responses) == 1 else parse_responses
            if not args.no_wait and parse_success_document_ids:
                stage_start = datetime.now(timezone.utc)
                live_states = wait_for_document_states(
                    client,
                    dataset_id=dataset_id,
                    document_ids=parse_success_document_ids,
                    timeout=args.parse_timeout,
                    poll_interval=args.poll_interval,
                )
                elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                stage_latency_ms.append(elapsed_ms)
                parse_wait_duration_ms += elapsed_ms
                parse_wait_document_count += len(parse_success_document_ids)
                failed_states = [
                    str(item.get("status") or "")
                    for item in live_states.values()
                    if isinstance(item, Mapping) and str(item.get("status") or "").lower() not in {"done", "parsed", "success"}
                ]
                parse_wait_status = "warning" if failed_states else "success"
                stage_results.append({"label": "wait_parse", "status": parse_wait_status})
                stage_timings.append(
                    {
                        "stage": "parse_wait",
                        "operation": "wait_for_document_states",
                        "status": parse_wait_status,
                        "duration_ms": elapsed_ms,
                        "document_count": len(parse_success_document_ids),
                    }
                )
                uploaded = [
                    (
                        doc,
                        document_id,
                        "parse_trigger_failed"
                        if document_id in parse_failed_document_ids
                        else live_states.get(document_id, {}).get("status", status),
                        None
                        if document_id in parse_failed_document_ids
                        else live_states.get(document_id, {}).get("chunk_count", chunk_count),
                    )
                    for doc, document_id, status, chunk_count in uploaded
                ]
                for doc, document_id, status, chunk_count in uploaded:
                    record = checkpoint_records.get(_checkpoint_source_key(doc.path))
                    if record is None:
                        continue
                    record["status"] = status
                    record["chunk_count"] = chunk_count
                    if document_id in parse_failed_document_ids:
                        record["parse_wait_status"] = "skipped"
                    elif document_id in live_states:
                        record["parse_wait_status"] = "success"
            else:
                if args.no_wait:
                    for record in checkpoint_records.values():
                        if str(record.get("parse_trigger_status") or "") == "success":
                            record["parse_wait_status"] = "skipped"
                stage_results.append({"label": "wait_parse", "status": "skipped"})
        else:
            for batch in batch_records:
                _mark_batch_parse_skipped(batch)
            if args.no_parse:
                for record in checkpoint_records.values():
                    record["parse_trigger_status"] = "skipped"
                    record["parse_wait_status"] = "skipped"
            stage_results.append({"label": "trigger_parse", "status": "skipped"})
            stage_results.append({"label": "wait_parse", "status": "skipped"})

        _write_ingestion_checkpoint(
            args.checkpoint,
            operation="markdown_build",
            dataset_id=dataset_id,
            dataset_name=args.kb_name,
            records=checkpoint_records,
            created_at=checkpoint_created_at,
        )

        runtime_partial_failure = build_runtime_partial_failure_report(
            "ragflow_kb_build_live",
            stage_results,
            success_statuses=("success",),
            warning_statuses=("warning",),
            failure_statuses=("error", "timeout"),
            skipped_statuses=("skipped",),
            timeout_statuses=("timeout",),
        )
        runtime_metrics = build_runtime_metrics_summary(
            "ragflow_kb_build_live",
            counters={
                "stage_count": len(stage_results),
                "document_count": len(uploaded),
                "parse_triggered": 1 if parse_responses else 0,
                "parse_trigger_count": len(parse_responses),
                "parse_trigger_attempt_count": sum(
                    1
                    for batch in batch_records
                    if str(batch.get("parse_trigger_status") or "") in {"success", "failed"}
                ),
                "retryable_failure_count": sum(int(batch.get("retryable_failure_count") or 0) for batch in batch_records),
                "parse_waited": 1 if document_ids and not args.no_parse and not args.no_wait else 0,
            },
            latency_samples_ms=stage_latency_ms,
            stage_timings=stage_timings,
            throughput={
                **(
                    {
                        "markdown_upload": throughput_summary(
                            item_count=markdown_upload_count,
                            duration_ms=markdown_upload_duration_ms,
                            unit="document",
                        )
                    }
                    if markdown_upload_count
                    else {}
                ),
                **(
                    {
                        "parse_wait": throughput_summary(
                            item_count=parse_wait_document_count,
                            duration_ms=parse_wait_duration_ms,
                            unit="document",
                        )
                    }
                    if parse_wait_document_count
                    else {}
                ),
            },
        )
        batching = _batching_summary(
            requested_batch_size=args.batch_size,
            planned_document_count=len(docs),
            uploaded_document_count=len(uploaded),
            parse_batch_count=len(parse_responses),
            parse_document_count=len(parse_success_document_ids),
            batches=batch_records,
        )
        build_ok = int(runtime_partial_failure["summary"].get("failure_count") or 0) == 0

        payload = make_kb_manifest_payload(
            base_url=config.base_url,
            dataset_id=dataset_id,
            dataset_name=args.kb_name,
            profile=profile,
            documents=uploaded,
            expected_embedding_models=expected_embedding_models,
            build_payload_preview=build_payload_preview,
        )
        if metadata_summary:
            payload["metadata_summary"] = metadata_summary
        payload["handoff_consumption_status"] = handoff_consumption_status
        payload["runtime_partial_failure"] = runtime_partial_failure
        payload["runtime_metrics"] = runtime_metrics
        payload["batching"] = batching
        payload["checkpoint"] = _checkpoint_report(
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            force_reupload_confirmed=args.force_reupload_confirmed,
            skipped_upload_count=checkpoint_skipped_upload_count,
            new_upload_count=checkpoint_new_upload_count,
            total_confirmed_upload_count=len(uploaded),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": build_ok,
                "status": "completed" if build_ok else "partial_failure",
                "kb_manifest": str(output),
                "dataset_id": dataset_id,
                "document_count": len(uploaded),
                "parse_triggered": bool(parse_responses),
                "parse_waited": not args.no_parse and not args.no_wait,
                "parse_response": parse_response,
                "parse_responses": parse_responses,
                "parse_errors": parse_errors,
                "embedding_model": embedding_model,
                "embedding_model_check": embedding_model_check,
                "build_payload_preview": build_payload_preview,
                "handoff_consumption_status": handoff_consumption_status,
                "runtime_partial_failure": runtime_partial_failure,
                "runtime_metrics": runtime_metrics,
                "batching": batching,
                "checkpoint": payload["checkpoint"],
                "post_build_recommendations": _post_build_recommendations(
                    args,
                    kb_manifest_path=output,
                    retrieval_hints_path=_resolve_retrieval_hints_path(args),
                ),
            }
        )
        return 0 if build_ok else 1
    except (BuildError, ConfigError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect_handoff(args: argparse.Namespace) -> int:
    try:
        report = inspect_rich_handoff(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.handoff, args.manifest_name, *_collect_path_like_literals(report)],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_handoff_inspection_markdown(report), encoding="utf-8")
        _dump_json({"ok": True, "handoff": report})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_asset_upload_plan(args: argparse.Namespace) -> int:
    try:
        stage_start = datetime.now(timezone.utc)
        report = create_kb_asset_upload_plan(
            doc_manifest_path=args.doc_manifest,
            include_sidecars=not args.no_sidecars,
        )
        if args.package_zip:
            report["package_zip"] = write_kb_asset_upload_zip(report, output_path=args.package_zip)
        elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
        report["runtime_metrics"] = build_runtime_metrics_summary(
            "ragflow_kb_asset_upload_plan",
            stage_timings=[
                {
                    "stage": "asset_upload_plan",
                    "operation": "create_asset_upload_plan",
                    "status": "success",
                    "duration_ms": elapsed_ms,
                }
            ],
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.doc_manifest],
                output_paths=[args.report_json, args.report_md, args.redaction_report, args.package_zip],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_asset_upload_plan_markdown(report))
        _dump_json(report)
        return 0 if report.get("status") != "blocked" else 1
    except (BuildError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_image_ingestion_readiness(args: argparse.Namespace) -> int:
    try:
        report = create_kb_asset_ingestion_readiness_report(
            asset_upload_plan_path=args.asset_upload_plan,
            profile_path=args.profile,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.asset_upload_plan, args.profile],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_asset_ingestion_readiness_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BuildError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_consistency_check(args: argparse.Namespace) -> int:
    try:
        report = create_kb_artifact_consistency_report(
            retrieval_hints_path=args.retrieval_hints,
            asset_upload_plan_path=args.asset_upload_plan,
            chunk_profile_report_path=args.chunk_profile_report,
            kb_manifest_path=args.kb_manifest,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.retrieval_hints, args.asset_upload_plan, args.chunk_profile_report, args.kb_manifest],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_artifact_consistency_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BuildError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _planned_visual_assets(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_assets = plan.get("planned_visual_upload_files")
    if not isinstance(raw_assets, list):
        return []
    assets: list[dict[str, Any]] = []
    for item in raw_assets:
        if not isinstance(item, Mapping):
            continue
        source_path = item.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            continue
        assets.append(
            {
                "source_path": source_path,
                "asset_class": item.get("asset_class") if isinstance(item.get("asset_class"), str) else None,
                "sha256": item.get("sha256") if isinstance(item.get("sha256"), str) else None,
                "mime_type": item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
            }
        )
    return assets


def _resolve_asset_source_path(*, source_path: str, asset_plan_path: str | Path, asset_plan: Mapping[str, Any]) -> Path:
    source = Path(source_path)
    if source.is_absolute():
        return source
    handoff_root = asset_plan.get("handoff_root")
    base = Path(str(handoff_root)) if isinstance(handoff_root, str) and handoff_root else Path(asset_plan_path).parent
    return base / source


def _state_label_for_uploaded_visual(state: Mapping[str, Any] | None) -> str:
    if not state:
        return "missing"
    if parse_state_failed(state):
        return "failed"
    if parse_state_succeeded(state):
        return "parsed"
    return "pending"


def _poll_uploaded_visual_states(
    client: Any,
    *,
    dataset_id: str,
    document_ids: list[str],
    timeout: float,
    poll_interval: float,
) -> tuple[dict[str, dict[str, Any]], Any, int]:
    deadline = time.monotonic() + max(0.0, timeout)
    latest: dict[str, dict[str, Any]] = {}
    latest_response: Any = None
    poll_count = 0
    while True:
        latest_response = client.list_documents(dataset_id)
        poll_count += 1
        latest = extract_document_states(latest_response, document_ids=document_ids)
        states = [latest.get(document_id) for document_id in document_ids]
        if states and all(state and _state_label_for_uploaded_visual(state) in {"parsed", "failed"} for state in states):
            return latest, latest_response, poll_count
        if timeout <= 0 or time.monotonic() >= deadline:
            return latest, latest_response, poll_count
        time.sleep(max(0.0, poll_interval))


def _run_image_ingestion_execute(args: argparse.Namespace) -> int:
    try:
        _validate_optional_batch_size(args.batch_size, label="image ingestion")
        if not args.execute:
            return _error(
                "image-ingestion-execute requires --execute after reviewing image-ingestion-readiness",
                json_output=args.json,
            )
        if args.resume and not args.checkpoint:
            raise BuildError("image-ingestion-execute --resume requires --checkpoint")
        if args.force_reupload_confirmed and not args.resume:
            raise BuildError("image-ingestion-execute --force-reupload-confirmed requires --resume")

        asset_plan = _read_json_file(args.asset_upload_plan, label="asset_upload_plan")
        if not isinstance(asset_plan, Mapping):
            raise BuildError("asset_upload_plan must be a JSON object")
        if asset_plan.get("schema") != KB_ASSET_UPLOAD_PLAN_SCHEMA:
            raise BuildError(f"asset upload plan schema must be {KB_ASSET_UPLOAD_PLAN_SCHEMA}")

        planned_assets = _planned_visual_assets(asset_plan)
        planned_count = len(planned_assets)
        confirmation_errors: list[str] = []
        if args.confirm_dataset_id != args.dataset_id:
            confirmation_errors.append("--confirm-dataset-id must exactly match --dataset-id")
        if args.confirm_planned_count != planned_count:
            confirmation_errors.append(
                f"--confirm-planned-count must equal planned_visual_upload_files count ({planned_count})"
            )
        if confirmation_errors:
            return _error("; ".join(confirmation_errors), json_output=args.json)
        if planned_count <= 0:
            return _error("asset upload plan has no planned_visual_upload_files to execute", json_output=args.json)

        resolved_assets: list[dict[str, Any]] = []
        for asset in planned_assets:
            resolved_path = _resolve_asset_source_path(
                source_path=str(asset["source_path"]),
                asset_plan_path=args.asset_upload_plan,
                asset_plan=asset_plan,
            )
            if not resolved_path.exists() or not resolved_path.is_file():
                raise BuildError(f"planned visual asset not found: {asset['source_path']}")
            resolved_assets.append({**asset, "resolved_path": resolved_path})

        config = _load_config(args)
        client = RAGFlowClient(config)
        checkpoint_payload: dict[str, Any] | None = None
        checkpoint_created_at: str | None = None
        checkpoint_records: dict[str, dict[str, Any]] = {}
        confirmed_uploads: dict[str, dict[str, Any]] = {}
        checkpoint_skipped_upload_count = 0
        checkpoint_new_upload_count = 0
        if args.resume:
            checkpoint_payload = _read_ingestion_checkpoint(args.checkpoint, operation="image_ingestion_execute")
            checkpoint_created_at = str(checkpoint_payload.get("created_at") or "") or None
            checkpoint_dataset_id = _checkpoint_dataset_id(checkpoint_payload)
            if checkpoint_dataset_id != args.dataset_id:
                raise BuildError("ingestion checkpoint dataset.id does not match --dataset-id")
            confirmed_uploads = _checkpoint_uploaded_map(checkpoint_payload)
        ragflow_calls = 0
        upload_call_count = 0
        upload_records: list[dict[str, Any]] = []
        uploaded_document_ids: list[str] = []
        parse_success_document_ids: list[str] = []
        parse_items: list[dict[str, Any]] = []
        stage_latency_ms: list[float] = []
        stage_timings: list[dict[str, Any]] = []
        image_upload_duration_ms = 0.0
        parse_wait_duration_ms = 0.0
        parse_wait_image_count = 0

        for asset in resolved_assets:
            source_path = str(asset["source_path"])
            resolved_path = asset["resolved_path"]
            source_key = _checkpoint_source_key(resolved_path)
            confirmed = confirmed_uploads.get(source_key) if not args.force_reupload_confirmed else None
            if confirmed:
                document_id = str(confirmed["document_id"])
                record = {
                    **confirmed,
                    "kind": "visual",
                    "source_key": source_key,
                    "source_path": source_path,
                    "name": Path(source_path).name,
                    "asset_class": asset.get("asset_class"),
                    "sha256": asset.get("sha256"),
                    "mime_type": asset.get("mime_type"),
                    "document_id": document_id,
                    "upload_status": "uploaded",
                    "checkpoint_resumed": True,
                }
                uploaded_document_ids.append(document_id)
                upload_records.append(record)
                checkpoint_records[source_key] = dict(record)
                checkpoint_skipped_upload_count += 1
                parse_trigger_status = str(confirmed.get("parse_trigger_status") or "")
                parse_wait_status = str(confirmed.get("parse_wait_status") or "")
                if args.no_parse:
                    checkpoint_records[source_key]["parse_trigger_status"] = "skipped"
                    checkpoint_records[source_key]["parse_wait_status"] = "skipped"
                elif parse_trigger_status == "success":
                    if not args.no_wait and parse_wait_status != "success":
                        parse_success_document_ids.append(document_id)
                else:
                    parse_items.append(record)
                continue
            try:
                ragflow_calls += 1
                upload_call_count += 1
                stage_start = datetime.now(timezone.utc)
                upload_response = client.upload_document(args.dataset_id, resolved_path)
                elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                stage_latency_ms.append(elapsed_ms)
                image_upload_duration_ms += elapsed_ms
                document_id = extract_uploaded_document_id(upload_response)
                stage_timings.append(
                    {
                        "stage": "image_upload",
                        "operation": "upload_document",
                        "status": "success",
                        "duration_ms": elapsed_ms,
                        "document_id": document_id,
                        "document_count": 1,
                    }
                )
                uploaded_document_ids.append(document_id)
                record = {
                    "kind": "visual",
                    "source_key": source_key,
                    "source_path": source_path,
                    "name": Path(source_path).name,
                    "asset_class": asset.get("asset_class"),
                    "sha256": asset.get("sha256"),
                    "mime_type": asset.get("mime_type"),
                    "document_id": document_id,
                    "upload_status": "uploaded",
                    "parse_trigger_status": "skipped" if args.no_parse else "pending",
                    "parse_triggered": False,
                    "parse_wait_status": "skipped" if args.no_parse or args.no_wait else "pending",
                }
                upload_records.append(record)
                parse_items.append(record)
                checkpoint_records[source_key] = dict(record)
                checkpoint_new_upload_count += 1
                _write_ingestion_checkpoint(
                    args.checkpoint,
                    operation="image_ingestion_execute",
                    dataset_id=args.dataset_id,
                    dataset_name=None,
                    records=checkpoint_records,
                    created_at=checkpoint_created_at,
                )
            except Exception as exc:  # pragma: no cover - covered through CLI behavior with fake clients as needed
                elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                stage_latency_ms.append(elapsed_ms)
                image_upload_duration_ms += elapsed_ms
                stage_timings.append(
                    {
                        "stage": "image_upload",
                        "operation": "upload_document",
                        "status": "error",
                        "duration_ms": elapsed_ms,
                        "detail": str(exc),
                        "document_count": 1,
                    }
                )
                record = {
                    "kind": "visual",
                    "source_key": source_key,
                    "source_path": source_path,
                    "name": Path(source_path).name,
                    "asset_class": asset.get("asset_class"),
                    "sha256": asset.get("sha256"),
                    "mime_type": asset.get("mime_type"),
                    "document_id": None,
                    "upload_status": "upload_failed",
                    "error": str(exc),
                }
                upload_records.append(record)
                checkpoint_records[source_key] = dict(record)
                _write_ingestion_checkpoint(
                    args.checkpoint,
                    operation="image_ingestion_execute",
                    dataset_id=args.dataset_id,
                    dataset_name=None,
                    records=checkpoint_records,
                    created_at=checkpoint_created_at,
                )

        parse_response: Any = None
        parse_responses: list[Any] = []
        parse_errors: list[str] = []
        parse_failed_document_ids: set[str] = set()
        batch_records = _batch_records(parse_items, args.batch_size)
        parse_error: str | None = None
        parse_triggered = False
        if (parse_items or parse_success_document_ids) and not args.no_parse:
            for batch in batch_records:
                parse_batch = list(batch.get("uploaded_document_ids") or [])
                if not parse_batch:
                    _mark_batch_parse_skipped(batch)
                    continue
                stage_start = datetime.now(timezone.utc)
                parse_trigger_status = "success"
                try:
                    ragflow_calls += 1
                    response = client.trigger_parse(args.dataset_id, parse_batch)
                    parse_responses.append(response)
                    parse_success_document_ids.extend(parse_batch)
                    _mark_batch_parse_success(batch, response)
                    for record in checkpoint_records.values():
                        if record.get("document_id") in parse_batch:
                            record["parse_trigger_status"] = "success"
                            record["parse_triggered"] = True
                            if args.no_wait:
                                record["parse_wait_status"] = "skipped"
                    parse_triggered = True
                except Exception as exc:  # pragma: no cover - retained to preserve cleanup evidence after live uploads
                    parse_trigger_status = "error"
                    parse_error = str(exc)
                    parse_errors.append(parse_error)
                    parse_failed_document_ids.update(parse_batch)
                    _mark_batch_parse_failure(batch, exc)
                    for record in checkpoint_records.values():
                        if record.get("document_id") in parse_batch:
                            record["parse_trigger_status"] = "failed"
                            record["parse_triggered"] = False
                            record["parse_wait_status"] = "skipped"
                    _write_ingestion_checkpoint(
                        args.checkpoint,
                        operation="image_ingestion_execute",
                        dataset_id=args.dataset_id,
                        dataset_name=None,
                        records=checkpoint_records,
                        created_at=checkpoint_created_at,
                    )
                    break
                finally:
                    elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                    stage_latency_ms.append(elapsed_ms)
                    stage_timings.append(
                        {
                            "stage": "trigger_parse",
                            "operation": "trigger_parse",
                            "status": parse_trigger_status,
                            "duration_ms": elapsed_ms,
                            "batch_index": batch.get("batch_index"),
                            "document_count": len(parse_batch),
                        }
                    )
                    _write_ingestion_checkpoint(
                        args.checkpoint,
                        operation="image_ingestion_execute",
                        dataset_id=args.dataset_id,
                        dataset_name=None,
                        records=checkpoint_records,
                        created_at=checkpoint_created_at,
                    )
            parse_response = parse_responses[0] if len(parse_responses) == 1 else parse_responses
        else:
            for batch in batch_records:
                _mark_batch_parse_skipped(batch)
            if args.no_parse:
                for record in checkpoint_records.values():
                    record["parse_trigger_status"] = "skipped"
                    record["parse_wait_status"] = "skipped"

        observed_states: dict[str, dict[str, Any]] = {}
        document_list_response: Any = None
        poll_count = 0
        wait_error: str | None = None
        wait_performed = False
        if parse_success_document_ids and not args.no_wait:
            stage_start = datetime.now(timezone.utc)
            try:
                observed_states, document_list_response, poll_count = _poll_uploaded_visual_states(
                    client,
                    dataset_id=args.dataset_id,
                    document_ids=parse_success_document_ids,
                    timeout=float(args.parse_timeout),
                    poll_interval=float(args.poll_interval),
                )
                ragflow_calls += poll_count
                wait_performed = True
                elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                stage_latency_ms.append(elapsed_ms)
                parse_wait_duration_ms += elapsed_ms
                parse_wait_image_count += len(parse_success_document_ids)
                stage_timings.append(
                    {
                        "stage": "parse_wait",
                        "operation": "poll_uploaded_visual_states",
                        "status": "success",
                        "duration_ms": elapsed_ms,
                        "document_count": len(parse_success_document_ids),
                    }
                )
            except Exception as exc:  # pragma: no cover - retained to preserve cleanup evidence after live uploads
                wait_error = str(exc)
                elapsed_ms = (datetime.now(timezone.utc) - stage_start).total_seconds() * 1000
                stage_latency_ms.append(elapsed_ms)
                stage_timings.append(
                    {
                        "stage": "parse_wait",
                        "operation": "poll_uploaded_visual_states",
                        "status": "error",
                        "duration_ms": elapsed_ms,
                        "detail": wait_error,
                        "document_count": len(parse_success_document_ids),
                    }
                )

        runtime_items: list[dict[str, Any]] = []
        observed_documents: list[dict[str, Any]] = []
        for record in upload_records:
            document_id = record.get("document_id")
            if record.get("upload_status") != "uploaded":
                status = "upload_failed"
                state: Mapping[str, Any] | None = None
            elif document_id in parse_failed_document_ids:
                status = "parse_trigger_failed"
                state = None
            elif args.no_parse:
                status = "not_parsed"
                state = None
            elif args.no_wait:
                status = "not_checked"
                state = None
            elif wait_error:
                status = "wait_failed"
                state = observed_states.get(str(document_id)) if document_id else None
            else:
                state = observed_states.get(str(document_id)) if document_id else None
                status = _state_label_for_uploaded_visual(state)
            checkpoint_record = checkpoint_records.get(str(record.get("source_key") or ""))
            if checkpoint_record is not None:
                checkpoint_record["status"] = status
                checkpoint_record["chunk_count"] = state.get("chunk_count") if isinstance(state, Mapping) else None
                if status == "parsed":
                    checkpoint_record["parse_wait_status"] = "success"
                elif status == "not_checked":
                    checkpoint_record["parse_wait_status"] = "skipped"
                elif status == "not_parsed":
                    checkpoint_record["parse_trigger_status"] = "skipped"
                    checkpoint_record["parse_wait_status"] = "skipped"
                elif status in {"failed", "missing", "pending"}:
                    checkpoint_record["parse_wait_status"] = status
                elif status in {"upload_failed", "parse_trigger_failed", "wait_failed"}:
                    checkpoint_record["parse_wait_status"] = "failed" if status == "wait_failed" else "skipped"
            runtime_items.append({"label": record.get("name"), "status": status, "document_id": document_id})
            observed_documents.append(
                {
                    "document_id": document_id,
                    "name": record.get("name"),
                    "source_path": record.get("source_path"),
                    "status": status,
                    "chunk_count": state.get("chunk_count") if isinstance(state, Mapping) else None,
                    "progress": state.get("progress") if isinstance(state, Mapping) else None,
                    "progress_msg": state.get("progress_msg") if isinstance(state, Mapping) else None,
                }
            )

        _write_ingestion_checkpoint(
            args.checkpoint,
            operation="image_ingestion_execute",
            dataset_id=args.dataset_id,
            dataset_name=None,
            records=checkpoint_records,
            created_at=checkpoint_created_at,
        )

        runtime_partial_failure = build_runtime_partial_failure_report(
            "image_ingestion_execute",
            runtime_items,
            success_statuses=("parsed", "not_checked", "not_parsed"),
            failure_statuses=("failed", "missing", "pending", "upload_failed", "parse_trigger_failed", "wait_failed"),
            skipped_statuses=(),
            warning_statuses=(),
        )
        status_counts = runtime_partial_failure["status_counts"]
        failed_count = sum(
            int(status_counts.get(status, 0) or 0)
            for status in ("failed", "missing", "pending", "upload_failed", "parse_trigger_failed", "wait_failed")
        )
        parsed_count = int(status_counts.get("parsed", 0) or 0)
        ok = failed_count == 0
        batching = _batching_summary(
            requested_batch_size=args.batch_size,
            planned_document_count=planned_count,
            uploaded_document_count=len(uploaded_document_ids),
            parse_batch_count=len(parse_responses),
            parse_document_count=len(parse_success_document_ids),
            batches=batch_records,
        )
        runtime_metrics = build_runtime_metrics_summary(
            "image_ingestion_execute",
            counters={
                "planned_visual_upload_file_count": planned_count,
                "uploaded_visual_document_count": len(uploaded_document_ids),
                "upload_call_count": upload_call_count,
                "parse_triggered": 1 if parse_triggered else 0,
                "parse_trigger_count": len(parse_responses),
                "parse_trigger_attempt_count": sum(
                    1
                    for batch in batch_records
                    if str(batch.get("parse_trigger_status") or "") in {"success", "failed"}
                ),
                "retryable_failure_count": sum(int(batch.get("retryable_failure_count") or 0) for batch in batch_records),
                "parse_waited": 1 if wait_performed else 0,
                "document_list_poll_count": poll_count,
                "failed_visual_document_count": failed_count,
            },
            latency_samples_ms=stage_latency_ms,
            stage_timings=stage_timings,
            throughput={
                **(
                    {
                        "image_upload": throughput_summary(
                            item_count=upload_call_count,
                            duration_ms=image_upload_duration_ms,
                            unit="image",
                        )
                    }
                    if upload_call_count
                    else {}
                ),
                **(
                    {
                        "parse_wait": throughput_summary(
                            item_count=parse_wait_image_count,
                            duration_ms=parse_wait_duration_ms,
                            unit="image",
                        )
                    }
                    if parse_wait_image_count
                    else {}
                ),
            },
        )
        performance_warnings = performance_warning_report(
            [
                *stage_duration_performance_warnings(
                    stage="image_parse_wait",
                    duration_ms=parse_wait_duration_ms,
                    item_count=parse_wait_image_count,
                    visual_or_vlm=True,
                ),
                *chunk_count_performance_warnings(
                    total_chunk_count=sum(
                        int(item.get("chunk_count") or 0)
                        for item in observed_documents
                        if isinstance(item.get("chunk_count"), int)
                    ),
                    documents=observed_documents,
                ),
                *polling_performance_warnings(
                    timeout_seconds=args.parse_timeout,
                    elapsed_ms=parse_wait_duration_ms,
                    poll_count=poll_count,
                    pending_count=int(status_counts.get("pending", 0) or 0),
                    wait_performed=wait_performed,
                ),
            ]
        )
        report = {
            "ok": ok,
            "schema": KB_ASSET_INGESTION_REPORT_SCHEMA,
            "created_at": _utc_now(),
            "mode": "execute",
            "advisory_only": False,
            "offline_only": False,
            "mutation": "visual_document_upload",
            "mutation_allowed": True,
            "live_upload_enabled": True,
            "status": "completed" if ok else "partial_failure",
            "inputs": {
                "asset_upload_plan": str(args.asset_upload_plan),
                "dataset_id": args.dataset_id,
            },
            "execution": {
                "status": "completed" if ok else "partial_failure",
                "ragflow_calls": ragflow_calls,
                "upload_call_count": upload_call_count,
                "parse_triggered": parse_triggered,
                "parse_trigger_count": len(parse_responses),
                "parse_trigger_attempt_count": sum(
                    1
                    for batch in batch_records
                    if str(batch.get("parse_trigger_status") or "") in {"success", "failed"}
                ),
                "wait_performed": wait_performed,
                "document_list_poll_count": poll_count,
                "db_calls": 0,
                "redis_calls": 0,
                "docker_calls": 0,
                "system_service_calls": 0,
                "parse_error": parse_error,
                "wait_error": wait_error,
            },
            "summary": {
                "planned_visual_upload_file_count": planned_count,
                "uploaded_visual_document_count": len(uploaded_document_ids),
                "parsed_visual_document_count": parsed_count,
                "failed_visual_document_count": failed_count,
                "pending_visual_document_count": int(status_counts.get("pending", 0) or 0),
                "missing_visual_document_count": int(status_counts.get("missing", 0) or 0),
                "runtime_partial_failure_status": runtime_partial_failure["summary"]["status"],
                "performance_warning_count": performance_warnings["summary"]["warning_count"],
            },
            "uploaded_visual_documents": upload_records,
            "observed_visual_documents": observed_documents,
            "document_list_response_observed": document_list_response is not None,
            "parse_response": parse_response,
            "parse_responses": parse_responses,
            "parse_errors": parse_errors,
            "batching": batching,
            "runtime_metrics": runtime_metrics,
            "performance_warnings": performance_warnings,
            "checkpoint": _checkpoint_report(
                checkpoint_path=args.checkpoint,
                resume=args.resume,
                force_reupload_confirmed=args.force_reupload_confirmed,
                skipped_upload_count=checkpoint_skipped_upload_count,
                new_upload_count=checkpoint_new_upload_count,
                total_confirmed_upload_count=len(uploaded_document_ids),
            ),
            "runtime_partial_failure": runtime_partial_failure,
            "cleanup_readiness": {
                "required": bool(upload_records),
                "dataset_id": args.dataset_id,
                "uploaded_document_ids": uploaded_document_ids,
                "upload_attempt_count": len(upload_records),
                "document_ids_complete": len(uploaded_document_ids) == len(upload_records),
                "reason": "visual document ingestion mutates an existing RAGFlow dataset",
            },
        }
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.asset_upload_plan, args.config, args.checkpoint],
                output_paths=[args.report_json, args.redaction_report],
                extra_secret_literals=[args.api_key] if args.api_key else None,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _dump_json(report)
        return 0 if ok else 1
    except (BuildError, ConfigError, OSError, RuntimeError, ProfileError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_metadata_file(args.metadata)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(report, args, input_paths=[args.metadata])
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_merge(args: argparse.Namespace) -> int:
    try:
        report = merge_metadata_payloads(
            doc_manifest_path=args.doc_manifest,
            handoff_metadata_path=args.handoff_metadata,
            user_metadata_path=args.metadata,
            derive_from_path=not args.no_derive_from_path,
        )
        _write_json_file(args.output, report["metadata"])
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.doc_manifest, args.handoff_metadata, args.metadata],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Merge Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_metadata_template_payload(doc_manifest_path=args.doc_manifest)
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "document_count": len(payload["documents"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_suggest_request(args: argparse.Namespace) -> int:
    try:
        report = create_metadata_suggestion_request(
            doc_manifest_path=args.doc_manifest,
            handoff_metadata_path=args.handoff_metadata,
            metadata_path=args.metadata,
            include_excerpts=args.include_excerpts,
            max_excerpt_chars=args.max_excerpt_chars,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.doc_manifest, args.handoff_metadata, args.metadata],
                output_paths=[args.output, args.report_json, args.report_md, args.redaction_report],
                extra_secret_literals=_collect_secret_literals(report),
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Suggestion Request"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_suggest_review(args: argparse.Namespace) -> int:
    try:
        report = review_metadata_suggestions(
            candidate_path=args.candidate,
            request_path=args.request,
            require_advisory=not args.allow_non_advisory,
        )
        if args.redaction_report:
            context_paths = [args.candidate, args.request]
            context_secrets, context_hosts, _context_config_paths = _collect_redaction_context_from_json_paths(context_paths)
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.candidate, args.request],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
                extra_secret_literals=[*context_secrets, *_collect_secret_literals(report)],
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Suggestion Review"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_tagset_file(args.tagset)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(report, args, input_paths=[args.tagset])
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_export(args: argparse.Namespace) -> int:
    try:
        exported = export_tagset_file(args.tagset, fmt=args.format)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(exported, str):
            output.write_text(exported, encoding="utf-8")
        else:
            output.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _dump_json({"ok": True, "schema": "ragflow_tagset_export_result_v1", "format": args.format, "output": str(output)})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_report(args: argparse.Namespace) -> int:
    try:
        report = tagset_report_file(args.tagset, metadata_path=args.metadata)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.tagset, args.metadata],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_tagset_template_payload()
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "tag_count": len(payload["tags"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_benchmark_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None],
    context_json_paths: list[str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths(context_json_paths or [])
    return _sanitize_governance_report(
        report,
        args,
        input_paths=[*input_paths, *context_paths, *_collect_path_like_literals(report)],
        extra_secret_literals=context_secrets,
        extra_private_hosts=context_hosts,
    )


def _optimization_plan_request_hash(plan: Mapping[str, Any]) -> str:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    candidate_summaries = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_summaries.append(
            {
                "profile_id": candidate.get("profile_id"),
                "disposable_kb_name": candidate.get("disposable_kb_name"),
                "profile": candidate.get("profile"),
                "artifacts": candidate.get("artifacts"),
            }
        )
    return _stable_digest(
        {
            "schema": plan.get("schema"),
            "mode": plan.get("mode"),
            "run_id": plan.get("run_id"),
            "base_kb_name": plan.get("base_kb_name"),
            "mutation_allowed": plan.get("mutation_allowed"),
            "inputs": plan.get("inputs"),
            "candidates": candidate_summaries,
            "steps": plan.get("steps"),
        }
    )


def _read_optimization_plan_checkpoint(path: Path) -> dict[str, Any]:
    payload = _read_json_file(path, label="optimization plan checkpoint")
    if not isinstance(payload, Mapping):
        raise ProfileError("optimization plan checkpoint must be a JSON object")
    if payload.get("schema") != OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA:
        raise ProfileError(f"optimization plan checkpoint schema must be {OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA}")
    processed = payload.get("processed_profile_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise ProfileError("optimization plan checkpoint processed_profile_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ProfileError("optimization plan checkpoint source_hashes must be an object")
    return dict(payload)


def _validate_optimization_plan_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
    request_hash: str,
    output_path: str | None,
    artifact_dir: str | None,
) -> None:
    if dict(checkpoint.get("source_hashes") or {}) != dict(source_hashes):
        raise ProfileError("optimization plan checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("request_hash") or "") != request_hash:
        raise ProfileError("optimization plan checkpoint request hash does not match current request")
    expected_output = str(Path(output_path)) if output_path else None
    if (checkpoint.get("output") or None) != expected_output:
        raise ProfileError("optimization plan checkpoint output does not match current output")
    expected_artifact_dir = str(Path(artifact_dir)) if artifact_dir else None
    if (checkpoint.get("artifact_dir") or None) != expected_artifact_dir:
        raise ProfileError("optimization plan checkpoint artifact_dir does not match current request")


def _write_optimization_plan_checkpoint(
    *,
    checkpoint_path: str | Path,
    source_hashes: Mapping[str, str],
    request_hash: str,
    output_path: str | None,
    artifact_dir: str | None,
    processed_profile_ids: list[str],
    total_profile_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_profile_ids))
    payload = {
        "schema": OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA,
        "created_at": created_at or _utc_now(),
        "updated_at": _utc_now(),
        "source_hashes": dict(source_hashes),
        "request_hash": request_hash,
        "output": str(Path(output_path)) if output_path else None,
        "artifact_dir": str(Path(artifact_dir)) if artifact_dir else None,
        "processed_profile_ids": processed,
        "summary": {
            "processed_profile_count": len(processed),
            "total_profile_count": total_profile_count,
            "remaining_profile_count": max(total_profile_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    _write_json_file(str(checkpoint_path), payload)
    return payload


def _apply_optimization_plan_checkpoint(
    plan: dict[str, Any],
    *,
    checkpoint_path: str | None,
    resume: bool,
    batch_size: int | None,
    source_hashes: Mapping[str, str],
    output_path: str | None,
    artifact_dir: str | None,
) -> dict[str, Any]:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    candidate_ids = [str(item.get("profile_id")) for item in candidates if isinstance(item, Mapping) and item.get("profile_id")]
    request_hash = _optimization_plan_request_hash(plan)
    processed_profile_ids: list[str] = []
    checkpoint_created_at: str | None = None

    if checkpoint_path and resume:
        checkpoint = _read_optimization_plan_checkpoint(Path(checkpoint_path))
        _validate_optimization_plan_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            request_hash=request_hash,
            output_path=output_path,
            artifact_dir=artifact_dir,
        )
        processed_profile_ids = list(checkpoint.get("processed_profile_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    unknown_processed = sorted(set(processed_profile_ids) - set(candidate_ids))
    if unknown_processed:
        raise ProfileError(
            "optimization plan checkpoint contains profile ids that are not present in current candidates: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_profile_ids)
    remaining_profile_ids = [profile_id for profile_id in candidate_ids if profile_id not in processed_set]
    next_profile_ids = remaining_profile_ids if batch_size is None else remaining_profile_ids[:batch_size]
    selected_profile_ids = set(processed_profile_ids) | set(next_profile_ids)
    completed = bool(plan.get("ok")) and len(selected_profile_ids) >= len(candidate_ids)
    filtered_candidates = [
        item
        for item in candidates
        if isinstance(item, Mapping) and str(item.get("profile_id") or "") in selected_profile_ids
    ]

    checkpoint_payload = None
    if checkpoint_path and plan.get("ok"):
        ordered_processed = [profile_id for profile_id in candidate_ids if profile_id in selected_profile_ids]
        checkpoint_payload = _write_optimization_plan_checkpoint(
            checkpoint_path=checkpoint_path,
            source_hashes=source_hashes,
            request_hash=request_hash,
            output_path=output_path,
            artifact_dir=artifact_dir,
            processed_profile_ids=ordered_processed,
            total_profile_count=len(candidate_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    summary = dict(plan.get("summary") if isinstance(plan.get("summary"), Mapping) else {})
    summary.update(
        {
            "candidate_count": len(filtered_candidates),
            "planned_experiment_count": len(filtered_candidates),
            "blocked_mutation_command_count": len(filtered_candidates),
            "completed": completed,
            "checkpoint_enabled": bool(checkpoint_path),
            "checkpoint_resume": bool(resume),
            "checkpoint_new_profile_count": len(next_profile_ids),
            "checkpoint_remaining_profile_count": max(len(candidate_ids) - len(selected_profile_ids), 0),
        }
    )
    plan = dict(plan)
    plan["summary"] = summary
    plan["candidates"] = filtered_candidates
    plan["completed"] = completed
    plan["checkpoint"] = {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "batch_size": batch_size,
        "processed_profile_count": len(selected_profile_ids),
        "new_profile_count": len(next_profile_ids),
        "remaining_profile_count": max(len(candidate_ids) - len(selected_profile_ids), 0),
        "total_profile_count": len(candidate_ids),
        "completed": completed,
        "next_profile_ids": list(next_profile_ids),
    }
    if checkpoint_payload:
        plan["checkpoint_payload"] = checkpoint_payload
    return plan


def _run_benchmark_import(args: argparse.Namespace) -> int:
    try:
        report = import_benchmark_dataset(
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            source_attribution_path=args.source_attribution,
            selection_report_path=args.selection_report,
            output_dir=args.output,
            name=args.name,
            description=args.description or "",
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.source_attribution,
                    args.selection_report,
                    args.output,
                    args.checkpoint,
                ],
                context_json_paths=[
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.source_attribution,
                    args.selection_report,
                ],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Import Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_snapshot_chunks(args: argparse.Namespace) -> int:
    try:
        report = snapshot_chunks(
            input_path=args.input,
            output_path=args.output,
            name=args.name,
            description=args.description or "",
            include_content=args.include_content,
            observed_state_path=args.observed_state,
            markdown_boundary_mode=args.markdown_boundary_mode,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.input, args.output, args.observed_state],
                context_json_paths=[args.input, args.observed_state],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Chunk Snapshot Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_preflight(args: argparse.Namespace) -> int:
    try:
        report = preflight_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.manifest, args.queries, args.qrels, args.qa, args.chunk_snapshot, args.gate_config],
                context_json_paths=[args.manifest, args.queries, args.qrels, args.qa, args.chunk_snapshot, args.gate_config],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Preflight Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_sample(args: argparse.Namespace) -> int:
    try:
        report = sample_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            source_attribution_path=args.source_attribution,
            selection_report_path=args.selection_report,
            output_dir=args.output,
            sample_size=args.size,
            sample_fraction=args.fraction,
            strategy=args.strategy,
            seed=args.seed,
            name=args.name,
            description=args.description or "",
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[
                    args.manifest,
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.source_attribution,
                    args.selection_report,
                    args.output,
                ],
                context_json_paths=[
                    args.manifest,
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.source_attribution,
                    args.selection_report,
                ],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Sample Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_summarize(args: argparse.Namespace) -> int:
    try:
        report = summarize_benchmark_report(args.report)
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report],
                context_json_paths=[args.report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Summary Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_gate(args: argparse.Namespace) -> int:
    try:
        report = gate_benchmark_report(
            report_path=args.report,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.gate_config, args.baseline_report],
                context_json_paths=[args.report, args.gate_config, args.baseline_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Gate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_trend(args: argparse.Namespace) -> int:
    try:
        report = trend_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report, args.gate_config],
                context_json_paths=[args.report, args.baseline_report, args.gate_config],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Trend Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_delta(args: argparse.Namespace) -> int:
    try:
        report = delta_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report],
                context_json_paths=[args.report, args.baseline_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Delta Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_suggest(args: argparse.Namespace) -> int:
    try:
        report = suggest_benchmark_retrieval_parameters(
            report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
            retrieval_hints_path=args.retrieval_hints,
            current_top_k=args.current_top_k,
            current_similarity_threshold=args.current_similarity_threshold,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report, args.gate_config, args.retrieval_hints],
                context_json_paths=[args.report, args.baseline_report, args.gate_config, args.retrieval_hints],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Retrieval Suggestions"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_suppression_report(args: argparse.Namespace) -> int:
    try:
        report = suppression_report_file(
            args.report,
            tagset_path=args.tagset,
            max_candidates=args.max_candidates,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.tagset],
                context_json_paths=[args.report, args.tagset],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_suppression_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_validate(args: argparse.Namespace) -> int:
    try:
        report = validate_grounded_qa(
            qa_path=args.qa,
            sources_path=args.sources,
            source_dir=args.source_dir,
            require_answer=not args.allow_missing_answer,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.qa, args.sources, args.source_dir],
                context_json_paths=[args.qa, args.sources],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Validate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_generate(args: argparse.Namespace) -> int:
    try:
        report = generate_grounded_qa(
            output_path=args.output,
            sources_path=args.sources,
            source_dir=args.source_dir,
            count=args.count,
            strategy=args.strategy,
            seed=args.seed,
            min_span_chars=args.min_span_chars,
            max_span_chars=args.max_span_chars,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.sources, args.source_dir, args.output, args.checkpoint],
                context_json_paths=[args.sources],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Generate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_map_evidence(args: argparse.Namespace) -> int:
    try:
        report = map_grounded_qa_evidence(
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            output_path=args.output,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.qa, args.chunk_snapshot, args.output],
                context_json_paths=[args.qa, args.chunk_snapshot],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow QA Evidence Map Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_suggest_request(args: argparse.Namespace) -> int:
    try:
        report = create_grounded_qa_suggestion_request(
            sources_path=args.sources,
            source_dir=args.source_dir,
            target_count=args.target_count,
            question_types=args.question_type,
            include_excerpts=args.include_excerpts,
            max_excerpt_chars=args.max_excerpt_chars,
            min_evidence_chars=args.min_evidence_chars,
            max_evidence_chars=args.max_evidence_chars,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.sources, args.source_dir, args.output],
                context_json_paths=[args.sources],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Suggestion Request"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_suggest_review(args: argparse.Namespace) -> int:
    try:
        report = review_grounded_qa_suggestions(
            candidate_path=args.candidate,
            request_path=args.request,
            sources_path=args.sources,
            source_dir=args.source_dir,
            chunk_snapshot_path=args.chunk_snapshot,
            evidence_map_output_path=args.evidence_map_output,
            require_answer=not args.allow_missing_answer,
            require_advisory=not args.allow_non_advisory,
            require_generated=not args.allow_non_generated,
        )
        if args.redaction_report:
            context_paths = [args.candidate, args.request, args.sources, args.chunk_snapshot, args.evidence_map_output]
            context_secrets, context_hosts, _context_config_paths = _collect_redaction_context_from_json_paths(context_paths)
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.candidate, args.request, args.sources, args.source_dir, args.chunk_snapshot, args.evidence_map_output],
                output_paths=[args.report_json, args.report_md, args.redaction_report, *_collect_path_like_literals(report)],
                extra_secret_literals=context_secrets,
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Suggestion Review"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_apollo_validate(args: argparse.Namespace) -> int:
    try:
        report = validate_apollo_table_qa_fixture(args.fixture)
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.fixture],
                context_json_paths=[args.fixture],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_apollo_table_qa_markdown(report, title="APOLLO Table QA Fixture Validation"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ApolloQaError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_apollo_evaluate(args: argparse.Namespace) -> int:
    try:
        report = evaluate_apollo_table_qa_results(
            fixture_path=args.fixture,
            results_path=args.results,
            target=args.target,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.fixture, args.results],
                context_json_paths=[args.fixture, args.results],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_apollo_table_qa_markdown(report, title="APOLLO Table QA Evaluation"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ApolloQaError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_apollo_judge_request(args: argparse.Namespace) -> int:
    try:
        report = create_apollo_table_qa_judge_request(
            fixture_path=args.fixture,
            results_path=args.results,
            target=args.target,
            evaluation_report_path=args.evaluation_report,
            include_answer_text=not args.omit_answer_text,
            include_retrieval_previews=not args.omit_retrieval_previews,
            max_answer_chars=args.max_answer_chars,
            max_retrieval_chars=args.max_retrieval_chars,
            max_retrieval_items=args.max_retrieval_items,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.fixture, args.results, args.evaluation_report],
                context_json_paths=[args.fixture, args.results, args.evaluation_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_apollo_table_qa_markdown(report, title="APOLLO Table QA Judge Request"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ApolloQaError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_apollo_judge_review(args: argparse.Namespace) -> int:
    try:
        report = review_apollo_table_qa_judge_candidate(
            request_path=args.request,
            candidate_path=args.candidate,
            require_advisory=not args.allow_non_advisory,
            require_generated=not args.allow_non_generated,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.request, args.candidate],
                context_json_paths=[args.request, args.candidate],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_apollo_table_qa_markdown(report, title="APOLLO Table QA Judge Review"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ApolloQaError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_segment_metadata_report(args: argparse.Namespace) -> int:
    try:
        report = segment_metadata_report_file(
            chunk_snapshot_path=args.chunk_snapshot,
            metadata_path=args.metadata,
            segmentation_plan_path=args.segmentation_plan,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.chunk_snapshot, args.metadata, args.segmentation_plan],
                context_json_paths=[args.chunk_snapshot, args.metadata, args.segmentation_plan],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Segment Metadata Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize(args: argparse.Namespace) -> int:
    try:
        if args.execute and args.plan_only:
            raise ProfileError("optimize --execute cannot be combined with --plan-only")
        if not args.plan_only and not args.execute:
            raise ProfileError("optimize requires --plan-only or --execute")
        if args.validate_benchmark and not args.execute:
            raise ProfileError("optimize --validate-benchmark requires --execute")
        if args.validate_benchmark and (args.no_parse or args.no_wait):
            raise ProfileError("optimize --validate-benchmark requires parse completion; omit --no-parse and --no-wait")
        if args.execute and args.command_manifest_output:
            raise ProfileError("optimize --command-manifest-output is for --plan-only dry-run review; omit it with --execute")
        if args.resume and not args.checkpoint:
            raise ProfileError("optimize --resume requires --checkpoint")
        if args.batch_size is not None and not args.checkpoint:
            raise ProfileError("optimize --batch-size requires --checkpoint")
        if args.batch_size is not None and args.batch_size <= 0:
            raise ProfileError("optimize batch_size must be positive")
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        plan = create_optimization_plan(
            kb_name=args.kb_name,
            document_paths=[doc.path for doc in docs],
            input_path=args.input,
            doc_manifest_path=args.doc_manifest,
            profile_paths=args.profile,
            profile_dirs=args.profile_dir,
            profile_set_paths=args.profile_set,
            recommendations=args.recommendation,
            benchmark_manifest_path=args.benchmark_manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            metadata_path=args.metadata,
            tagset_path=args.tagset,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
            artifact_dir=args.artifact_dir,
            run_id=args.run_id,
            top_k=args.top_k,
            metric_cutoff=args.metric_cutoff,
        )
        source_hashes = _source_hash_map(
            [
                args.input,
                args.doc_manifest,
                *args.profile,
                *args.profile_dir,
                *args.profile_set,
                args.benchmark_manifest,
                args.queries,
                args.qrels,
                args.qa,
                args.metadata,
                args.tagset,
                args.chunk_snapshot,
                args.gate_config,
                args.baseline_report,
            ]
        )
        plan = _apply_optimization_plan_checkpoint(
            plan,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
            source_hashes=source_hashes,
            output_path=args.output,
            artifact_dir=args.artifact_dir,
        )
        execution_report = None
        if args.execute:
            _require_optimize_execute_confirmation(args, plan)
            if not plan.get("ok"):
                raise ProfileError("optimize --execute requires a valid optimization plan with ok=true")
            config = _load_config(args)
            client = RAGFlowClient(config)
            metadata_summary = summarize_metadata_for_documents(args.metadata, [doc.path for doc in docs])
            if metadata_summary and not metadata_summary.get("ok", False):
                raise BuildError("metadata lint failed; run metadata lint for details")
            results = []
            validation_results = []
            benchmark_inputs = plan.get("inputs", {}).get("benchmark", {}) if isinstance(plan.get("inputs"), Mapping) else {}
            queries_path = benchmark_inputs.get("queries") if isinstance(benchmark_inputs, Mapping) else None
            qrels_path = benchmark_inputs.get("qrels") if isinstance(benchmark_inputs, Mapping) else None
            for candidate in plan.get("candidates", []):
                if not isinstance(candidate, Mapping):
                    continue
                results.append(
                    _build_candidate_kb(
                        candidate=candidate,
                        docs=docs,
                        config=config,
                        client=client,
                        metadata_summary=metadata_summary,
                        parse_timeout=args.parse_timeout,
                        poll_interval=args.poll_interval,
                        no_parse=args.no_parse,
                        no_wait=args.no_wait,
                    )
                )
                if args.validate_benchmark:
                    validation_results.append(
                        _validate_candidate_benchmark(
                            candidate=candidate,
                            client=client,
                            queries_path=queries_path if isinstance(queries_path, str) else None,
                            qrels_path=qrels_path if isinstance(qrels_path, str) else None,
                            gate_config_path=args.gate_config,
                            baseline_report_path=args.baseline_report,
                            chunk_snapshot_path=args.chunk_snapshot,
                            metadata_summary=metadata_summary,
                            top_k=args.top_k,
                            metric_cutoff=args.metric_cutoff,
                        )
                    )
            execution_report = {
                "schema": "ragflow_optimization_execute_report_v1",
                "created_at": _utc_now(),
                "mode": "execute-build-validate" if args.validate_benchmark else "execute-build",
                "run_id": plan.get("run_id"),
                "base_kb_name": plan.get("base_kb_name"),
                "confirmation": {
                    "confirm_live_build": True,
                    "confirm_kb_name": args.confirm_kb_name,
                    "confirm_run_id": args.confirm_run_id,
                },
                "summary": {
                    "candidate_count": len(plan.get("candidates", [])) if isinstance(plan.get("candidates"), list) else 0,
                    "built_candidate_count": len(results),
                    "dataset_count": len(results),
                    "document_count": sum(int(item.get("document_count") or 0) for item in results),
                    "cleanup_required_count": sum(1 for item in results if item.get("cleanup_required")),
                    "benchmark_validation_executed": bool(args.validate_benchmark),
                    "validated_candidate_count": len(validation_results),
                    "benchmark_validation_passed_count": sum(1 for item in validation_results if item.get("ok")),
                    "cleanup_executed": False,
                },
                "results": results,
                "validation_results": validation_results,
                "next_steps": [
                    "Run optimize summarize after benchmark validation reports exist."
                    if not args.validate_benchmark
                    else "Run optimize summarize to rank candidate benchmark reports.",
                    "Run optimize cleanup-plan before deleting disposable KBs.",
                    "Delete disposable KBs only with exact dataset id and KB name confirmation.",
                ],
            }
            plan["mode"] = execution_report["mode"]
            plan["mutation_allowed"] = True
            plan["execution"] = execution_report
            plan_summary = dict(plan.get("summary") if isinstance(plan.get("summary"), Mapping) else {})
            plan_summary.update(
                {
                    "built_candidate_count": len(results),
                    "cleanup_required_count": execution_report["summary"]["cleanup_required_count"],
                    "benchmark_validation_executed": bool(args.validate_benchmark),
                    "validated_candidate_count": len(validation_results),
                    "benchmark_validation_passed_count": execution_report["summary"]["benchmark_validation_passed_count"],
                    "cleanup_executed": False,
                }
            )
            plan["summary"] = plan_summary
        command_manifest = None
        if args.command_manifest_output:
            command_manifest = _build_optimization_command_manifest(plan, output_path=args.output)
            plan["command_manifest"] = {
                "path": args.command_manifest_output,
                "schema": command_manifest["schema"],
                "command_count": command_manifest["summary"]["command_count"],
                "mutating_command_count": command_manifest["summary"]["mutating_command_count"],
                "enabled_mutating_command_count": command_manifest["summary"]["enabled_mutating_command_count"],
            }
        if args.redaction_report:
            report_payload = {"plan": plan, "command_manifest": command_manifest} if command_manifest else plan
            sanitized, redaction_report = _sanitize_governance_report(
                report_payload,
                args,
                input_paths=[
                    args.input,
                    args.doc_manifest,
                    *args.profile,
                    *args.profile_dir,
                    *args.profile_set,
                    args.benchmark_manifest,
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.metadata,
                    args.tagset,
                    args.chunk_snapshot,
                    args.gate_config,
                    args.baseline_report,
                    args.artifact_dir,
                    args.checkpoint,
                    args.command_manifest_output,
                    args.config,
                    *_collect_path_like_literals(plan),
                ],
                output_paths=[args.output, args.checkpoint, args.command_manifest_output],
                extra_secret_literals=[getattr(args, "api_key", None)],
                extra_private_hosts=configured_private_hosts_from_urls([getattr(args, "base_url", None)]),
            )
            if command_manifest:
                plan = sanitized["plan"]
                command_manifest = sanitized["command_manifest"]
            else:
                plan = sanitized
            _write_json_file(args.redaction_report, redaction_report)
        if args.command_manifest_output and command_manifest:
            _write_json_file(args.command_manifest_output, command_manifest)
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (BuildError, ManifestError, ProfileError, ValidationError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_summarize(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths(
            [args.plan, *args.report, args.cleanup_plan, args.readiness_report, args.cleanup_execution_report]
        )
        results = summarize_optimization_results(
            plan_path=args.plan,
            report_paths=args.report,
            cleanup_plan_path=args.cleanup_plan,
            readiness_report_path=args.readiness_report,
            cleanup_execution_report_path=args.cleanup_execution_report,
            score_epsilon=args.score_epsilon,
            min_score_delta=args.min_score_delta,
        )
        if args.redaction_report:
            results, redaction_report = _sanitize_governance_report(
                results,
                args,
                input_paths=[
                    args.plan,
                    *args.report,
                    args.cleanup_plan,
                    args.readiness_report,
                    args.cleanup_execution_report,
                    *context_paths,
                    *_collect_path_like_literals(results),
                ],
                output_paths=[args.output],
                extra_secret_literals=context_secrets,
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, results)
        _write_text_file(args.report_md, render_best_profile_markdown(results))
        _dump_json(results)
        return 0 if results["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_cleanup_plan(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths([args.plan])
        plan = create_optimization_cleanup_plan(
            plan_path=args.plan,
            cleanup_script=args.cleanup_script,
            config_path=args.config,
            require_manifests=args.require_manifests,
        )
        if args.redaction_report:
            plan, redaction_report = _sanitize_governance_report(
                plan,
                args,
                input_paths=[args.plan, args.cleanup_script, args.config, *context_paths, *_collect_path_like_literals(plan)],
                output_paths=[args.output],
                extra_secret_literals=context_secrets,
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_cleanup_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _readiness_config_state(args: argparse.Namespace) -> tuple[bool, bool, str | None]:
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    try:
        config = load_config(config_file=args.config, overrides=overrides)
    except ConfigError as exc:
        return False, False, str(exc)
    return bool(config.base_url), bool(config.api_key), None


def _cleanup_readiness_confirmations(args: argparse.Namespace) -> list[tuple[str, str | None]]:
    dataset_ids = list(args.confirm_cleanup_dataset_id or [])
    kb_names = list(args.confirm_cleanup_kb_name or [])
    if len(dataset_ids) != len(kb_names):
        raise BuildError("optimize readiness requires matching repeated --confirm-cleanup-dataset-id and --confirm-cleanup-kb-name values")
    return [(dataset_id, kb_name) for dataset_id, kb_name in zip(dataset_ids, kb_names, strict=True)]


def _run_optimize_readiness(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths([args.plan, args.cleanup_plan])
        base_url_configured, api_key_configured, credential_error = _readiness_config_state(args)
        report = create_optimization_live_readiness_report(
            plan_path=args.plan,
            cleanup_plan_path=args.cleanup_plan,
            config_path=args.config,
            ragflow_base_url_configured=base_url_configured,
            ragflow_api_key_configured=api_key_configured,
            credential_error=credential_error,
            confirm_live_build=args.confirm_live_build,
            confirm_kb_name=args.confirm_kb_name,
            confirm_run_id=args.confirm_run_id,
            cleanup_confirmations=_cleanup_readiness_confirmations(args),
            require_cleanup_ready=args.require_cleanup_ready,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[
                    args.plan,
                    args.cleanup_plan,
                    args.config,
                    *context_paths,
                    *_collect_path_like_literals(report),
                ],
                output_paths=[args.output, args.report_md, args.redaction_report],
                extra_secret_literals=[getattr(args, "api_key", None), *context_secrets],
                extra_private_hosts=[*context_hosts, *configured_private_hosts_from_urls([getattr(args, "base_url", None)])],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_optimization_live_readiness_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BuildError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _cleanup_target_key(dataset_id: str, dataset_name: str | None) -> tuple[str, str | None]:
    return dataset_id, dataset_name or None


def _same_cleanup_plan_path(left: str | Path, right: str | Path) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)


def _confirmed_cleanup_keys(args: argparse.Namespace) -> set[tuple[str, str | None]]:
    dataset_ids = list(args.confirm_dataset_id or [])
    kb_names = list(args.confirm_kb_name or [])
    if len(dataset_ids) != len(kb_names):
        raise BuildError("cleanup-execute requires matching repeated --confirm-dataset-id and --confirm-kb-name values")
    return {_cleanup_target_key(dataset_id, kb_name) for dataset_id, kb_name in zip(dataset_ids, kb_names, strict=True)}


def _readiness_confirmed_cleanup_keys(args: argparse.Namespace) -> set[tuple[str, str | None]]:
    if not getattr(args, "readiness_report", None):
        return set()
    readiness = _read_json_file(args.readiness_report, label="optimization live readiness report")
    if not isinstance(readiness, Mapping):
        raise BuildError("cleanup-execute readiness report must be a JSON object")
    if readiness.get("schema") != OPTIMIZATION_LIVE_READINESS_REPORT_SCHEMA:
        raise BuildError(f"cleanup-execute readiness report must have schema {OPTIMIZATION_LIVE_READINESS_REPORT_SCHEMA}")
    if readiness.get("ok") is not True:
        raise BuildError("cleanup-execute readiness report must have ok=true")
    readiness_cleanup_plan = readiness.get("cleanup_plan")
    if not isinstance(readiness_cleanup_plan, str) or not readiness_cleanup_plan:
        raise BuildError("cleanup-execute readiness report must record cleanup_plan")
    if not _same_cleanup_plan_path(readiness_cleanup_plan, args.cleanup_plan):
        raise BuildError("cleanup-execute readiness report cleanup_plan must match --cleanup-plan")
    cleanup = readiness.get("cleanup") if isinstance(readiness.get("cleanup"), Mapping) else {}
    if cleanup.get("confirmation_exact") is not True:
        raise BuildError("cleanup-execute readiness report must have cleanup.confirmation_exact=true")
    ready_targets = cleanup.get("ready_targets") if isinstance(cleanup.get("ready_targets"), list) else []
    keys = set()
    for index, target in enumerate(ready_targets):
        if not isinstance(target, Mapping):
            raise BuildError(f"cleanup-execute readiness report cleanup.ready_targets[{index}] must be an object")
        dataset_id = target.get("dataset_id")
        dataset_name = target.get("dataset_name")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise BuildError(f"cleanup-execute readiness report cleanup.ready_targets[{index}] is missing dataset_id")
        if dataset_name is not None and not isinstance(dataset_name, str):
            raise BuildError(f"cleanup-execute readiness report cleanup.ready_targets[{index}].dataset_name must be a string when present")
        keys.add(_cleanup_target_key(dataset_id, dataset_name))
    if not keys:
        raise BuildError("cleanup-execute readiness report does not contain ready cleanup confirmations")
    return keys


def _ready_cleanup_targets(cleanup_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    if cleanup_plan.get("schema") != "ragflow_optimization_cleanup_plan_v1":
        raise BuildError("cleanup-execute requires a ragflow_optimization_cleanup_plan_v1 cleanup plan")
    targets = cleanup_plan.get("targets")
    if not isinstance(targets, list):
        raise BuildError("cleanup-execute cleanup plan targets must be a list")
    ready = []
    for index, target in enumerate(targets):
        if not isinstance(target, Mapping):
            raise BuildError(f"cleanup-execute target[{index}] must be an object")
        target_payload = target.get("target") if isinstance(target.get("target"), Mapping) else {}
        dataset_id = target_payload.get("dataset_id")
        dataset_name = target_payload.get("dataset_name")
        if target.get("status") != "ready":
            continue
        if not isinstance(dataset_id, str) or not dataset_id:
            raise BuildError(f"cleanup-execute ready target[{index}] is missing target.dataset_id")
        if dataset_name is not None and not isinstance(dataset_name, str):
            raise BuildError(f"cleanup-execute ready target[{index}] target.dataset_name must be a string when present")
        ready.append(
            {
                "index": index,
                "profile_id": target.get("profile_id"),
                "disposable_kb_name": target.get("disposable_kb_name"),
                "kb_manifest": target.get("kb_manifest"),
                "cleanup_plan": target.get("cleanup_plan"),
                "target": {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                },
            }
        )
    return ready


def _require_cleanup_execute_confirmation(args: argparse.Namespace, ready_targets: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not args.execute:
        raise BuildError("cleanup-execute requires --execute")
    if not ready_targets:
        raise BuildError("cleanup-execute requires at least one ready cleanup target")
    explicit_confirmed = _confirmed_cleanup_keys(args)
    readiness_confirmed = _readiness_confirmed_cleanup_keys(args)
    expected = {
        _cleanup_target_key(
            str(target["target"]["dataset_id"]),
            target["target"].get("dataset_name") if isinstance(target.get("target"), Mapping) else None,
        )
        for target in ready_targets
    }
    confirmed = explicit_confirmed | readiness_confirmed
    if confirmed != expected:
        missing = sorted(expected - confirmed)
        extra = sorted(confirmed - expected)
        details = []
        if missing:
            details.append("missing confirmations: " + ", ".join(f"{dataset_id}:{kb_name or ''}" for dataset_id, kb_name in missing))
        if extra:
            details.append("unexpected confirmations: " + ", ".join(f"{dataset_id}:{kb_name or ''}" for dataset_id, kb_name in extra))
        raise BuildError("cleanup-execute confirmations must exactly match ready targets" + (f" ({'; '.join(details)})" if details else ""))
    if readiness_confirmed and explicit_confirmed:
        source = "explicit_and_readiness_report"
    elif readiness_confirmed:
        source = "readiness_report"
    else:
        source = "explicit"
    return {
        "source": source,
        "confirmed_target_count": len(confirmed),
        "explicit_confirmation_count": len(explicit_confirmed),
        "readiness_confirmation_count": len(readiness_confirmed),
        "readiness_report": args.readiness_report if readiness_confirmed else None,
    }


def _validate_delete_response(response: Any, *, dataset_id: str) -> None:
    if not isinstance(response, Mapping) or "code" not in response:
        return
    if response.get("code") == 0:
        return
    message = response.get("message") or response.get("msg") or response
    raise BuildError(f"cleanup-execute delete failed for dataset {dataset_id}: {message}")


def _run_optimize_cleanup_execute(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths([args.cleanup_plan])
        cleanup_plan = _read_json_file(args.cleanup_plan, label="optimization cleanup plan")
        if not isinstance(cleanup_plan, Mapping):
            raise BuildError("cleanup-execute cleanup plan must be a JSON object")
        ready_targets = _ready_cleanup_targets(cleanup_plan)
        confirmation = _require_cleanup_execute_confirmation(args, ready_targets)
        config = _load_config(args)
        client = RAGFlowClient(config)
        results = []
        for target in ready_targets:
            target_payload = target["target"]
            dataset_id = str(target_payload["dataset_id"])
            delete_response = client.delete_dataset(dataset_id)
            _validate_delete_response(delete_response, dataset_id=dataset_id)
            results.append(
                {
                    **target,
                    "status": "deleted",
                    "delete_response": delete_response,
                }
            )
        report = {
            "ok": True,
            "schema": OPTIMIZATION_CLEANUP_EXECUTION_REPORT_SCHEMA,
            "created_at": _utc_now(),
            "cleanup_plan": args.cleanup_plan,
            "execute": True,
            "dry_run": False,
            "mutation_allowed": True,
            "requires_exact_confirmation": True,
            "confirmation": confirmation,
            "summary": {
                "target_count": len(ready_targets),
                "deleted_target_count": len(results),
                "failed_target_count": 0,
                "cleanup_executed": True,
                "post_cleanup_verified": False,
            },
            "post_cleanup_verification": {
                "status": "not_checked",
                "network_checked": False,
                "reason": "cleanup-execute deletes confirmed datasets but does not perform post-delete read-back verification.",
            },
            "results": results,
        }
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.cleanup_plan, args.config, *context_paths, *_collect_path_like_literals(report)],
                output_paths=[args.output, args.redaction_report],
                extra_secret_literals=[getattr(args, "api_key", None), *context_secrets],
                extra_private_hosts=[*context_hosts, *configured_private_hosts_from_urls([getattr(args, "base_url", None)])],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _dump_json(report)
        return 0
    except (BuildError, ConfigError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_advise(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_topology_advice(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            route_config_path=args.route_config,
            future_growth=args.future_growth,
            min_documents=args.min_documents,
            min_total_chars=args.min_total_chars,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.input, args.doc_manifest, args.metadata, args.retrieval_hints, args.route_config],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_topology_advice_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_split_plan(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_split_plan(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            min_group_documents=args.min_group_documents,
            min_group_estimated_chunks=args.min_group_estimated_chunks,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.input, args.doc_manifest, args.metadata, args.retrieval_hints],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_split_plan_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_activation_plan(args: argparse.Namespace) -> int:
    try:
        report = create_kb_activation_plan(
            kb_manifest_path=args.kb_manifest,
            doc_manifest_path=args.doc_manifest,
            route_config_path=args.route_config,
            retrieval_hints_path=args.retrieval_hints,
            ingest_plan_path=args.ingest_plan,
            profile_path=args.profile,
            chunk_snapshot_path=args.chunk_snapshot,
            centroid_index_path=args.centroid_index,
            route_tests_path=args.route_tests,
            min_documents=args.min_documents,
            min_chunks=args.min_chunks,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[
                    args.kb_manifest,
                    args.doc_manifest,
                    args.route_config,
                    args.retrieval_hints,
                    args.ingest_plan,
                    args.profile,
                    args.chunk_snapshot,
                    args.centroid_index,
                    args.route_tests,
                ],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_activation_plan_markdown(report))
        _dump_json(report)
        return 0
    except (TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_parse_report(report: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.kb_manifest,
            args.documents_json,
            args.observed_state,
            args.multimodal_kb_manifest,
            *args.parse_log,
            args.profile,
            args.parser_config,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _run_parse_report(args: argparse.Namespace) -> int:
    try:
        report = create_parse_report(
            kb_manifest_path=args.kb_manifest,
            documents_json_path=args.documents_json,
            observed_state_path=args.observed_state,
            multimodal_kb_manifest_path=args.multimodal_kb_manifest,
            parse_log_paths=args.parse_log,
            profile_path=args.profile,
            parser_config_path=args.parser_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_parse_report(report, args)
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_parse_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ParseReportError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_parameter_audit(args: argparse.Namespace) -> int:
    try:
        dry_run_report = _read_json_file(args.dry_run_report, label="dry-run report")
        if not isinstance(dry_run_report, Mapping):
            raise BuildError("dry-run report must be a JSON object")
        observed_state = None
        if args.observed_state:
            observed_state = _read_json_file(args.observed_state, label="observed state")
            if not isinstance(observed_state, Mapping):
                raise BuildError("observed state must be a JSON object")
        report = create_parameter_read_back_audit(
            dry_run_report=dry_run_report,
            observed_state=observed_state,
            evidence_bundle_id=args.evidence_bundle_id,
            ragflow_contract_version=args.ragflow_contract_version,
            ragflow_contract_source=args.ragflow_contract_source,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.dry_run_report, args.observed_state],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_parameter_read_back_audit_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BuildError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_refresh_report(args: argparse.Namespace) -> int:
    try:
        kb_manifest = load_kb_manifest(args.kb_manifest)
        config = _load_config(args)
        client = RAGFlowClient(config)
        document_list_response = client.list_documents(
            kb_manifest.dataset.id,
            page=args.page,
            page_size=args.page_size,
        )
        report = create_kb_refresh_report(
            kb_manifest_path=args.kb_manifest,
            document_list_response=document_list_response,
            page=args.page,
            page_size=args.page_size,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.kb_manifest, args.config],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
                extra_secret_literals=[args.api_key] if args.api_key else None,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_refresh_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BuildError, ConfigError, ManifestError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_health_report(report: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            *args.kb_manifest,
            *args.parse_report,
            *args.observed_state,
            *args.activation_plan,
            *args.model_provider_probe,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _run_health_report(args: argparse.Namespace) -> int:
    try:
        report = create_kb_health_report(
            kb_manifest_paths=args.kb_manifest,
            parse_report_paths=args.parse_report,
            observed_state_paths=args.observed_state,
            activation_plan_paths=args.activation_plan,
            model_provider_probe_paths=args.model_provider_probe,
            min_documents=args.min_documents,
            min_chunks=args.min_chunks,
            expected_embedding_models=args.expected_embedding_model,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_health_report(report, args)
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_health_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (HealthReportError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_model_provider_report(report: dict[str, Any], args: argparse.Namespace, config: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [config.base_url, args.embedding_adapter_url, args.rerank_adapter_url]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[config.api_key, args.embedding_adapter_api_key, args.rerank_adapter_api_key],
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[args.config],
    )
    return sanitized, redaction_report


def _run_model_providers_probe(args: argparse.Namespace) -> int:
    try:
        overrides: dict[str, Any] = {}
        if args.base_url:
            overrides["base_url"] = args.base_url
        if args.api_key:
            overrides["api_key"] = args.api_key
        if args.timeout is not None:
            overrides["timeout"] = args.timeout
        config = load_config(config_file=args.config, overrides=overrides)
        client = RAGFlowClient(config)
        report = probe_model_providers(
            client,
            endpoint_paths=args.endpoint,
            expected_embedding_models=args.embedding_model,
            expected_rerank_models=args.rerank_model,
            embedding_adapter_url=args.embedding_adapter_url,
            embedding_adapter_api_key=args.embedding_adapter_api_key,
            embedding_adapter_shape=args.embedding_adapter_shape,
            rerank_adapter_url=args.rerank_adapter_url,
            rerank_adapter_api_key=args.rerank_adapter_api_key,
            rerank_adapter_shape=args.rerank_adapter_shape,
            adapter_timeout=args.adapter_timeout,
        )
        report, redaction_report = _sanitize_model_provider_report(report, args, config)
        _write_json_file(args.report_json, report)
        _write_json_file(args.redaction_report, redaction_report)
        _write_text_file(args.report_md, render_model_provider_probe_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
        return _error(str(exc), json_output=args.json)


def build_inspect_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Markdown handoff and optional rich sidecars")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--report-json", help="Optional JSON inspection report path")
    parser.add_argument("--report-md", help="Optional Markdown inspection report path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_asset_upload_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan a non-live Markdown plus local image upload package")
    parser.add_argument("--doc-manifest", required=True, help="Path to doc_manifest.json")
    parser.add_argument("--report-json", help="Optional JSON upload plan path")
    parser.add_argument("--report-md", help="Optional Markdown upload plan path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--package-zip", help="Optional local zip package to materialize from the plan")
    parser.add_argument("--no-sidecars", action="store_true", help="Do not include existing rich handoff sidecars in the package plan")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_image_ingestion_readiness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review image ingestion readiness without contacting RAGFlow")
    parser.add_argument("--asset-upload-plan", required=True, help="ragflow_kb_asset_upload_plan_v2 JSON")
    parser.add_argument("--profile", help="Optional build profile JSON/YAML for parser evidence")
    parser.add_argument("--report-json", "--output", dest="report_json", default="image_ingestion_readiness.json")
    parser.add_argument("--report-md", help="Optional image ingestion readiness Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_consistency_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review consistency across handoff, build, profile, and KB artifacts")
    parser.add_argument("--retrieval-hints", required=True, help="ragflow_retrieval_hints_v1 JSON")
    parser.add_argument("--asset-upload-plan", required=True, help="ragflow_kb_asset_upload_plan_v2 JSON")
    parser.add_argument("--chunk-profile-report", required=True, help="ragflow_chunk_profile_report_v1 JSON")
    parser.add_argument("--kb-manifest", required=True, help="kb_manifest.json to compare against planned build artifacts")
    parser.add_argument("--report-json", "--output", dest="report_json", default="kb_artifact_consistency_report.json")
    parser.add_argument("--report-md", help="Optional artifact consistency Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_image_ingestion_execute_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute gated visual-document ingestion against an existing RAGFlow dataset")
    parser.add_argument("--execute", action="store_true", help="Allow live visual-document upload after readiness review")
    parser.add_argument("--asset-upload-plan", required=True, help="ragflow_kb_asset_upload_plan_v2 JSON")
    parser.add_argument("--dataset-id", required=True, help="Existing RAGFlow dataset ID to mutate")
    parser.add_argument("--confirm-dataset-id", required=True, help="Must exactly match --dataset-id")
    parser.add_argument("--confirm-planned-count", required=True, type=int, help="Must equal planned_visual_upload_files count")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--report-json", "--output", dest="report_json", default="image_ingestion_execute.json")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--no-parse", action="store_true", help="Upload visual documents but do not trigger parsing")
    parser.add_argument("--no-wait", action="store_true", help="Do not read document states after triggering parse")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parsed or failed visual states")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between document-list polls")
    parser.add_argument("--batch-size", type=int, help="Maximum uploaded visual document IDs per parse trigger")
    parser.add_argument("--checkpoint", help="Checkpoint path for resumable visual-document ingestion")
    parser.add_argument("--resume", action="store_true", help="Resume visual-document ingestion from an existing checkpoint")
    parser.add_argument(
        "--force-reupload-confirmed",
        action="store_true",
        help="With --resume, re-upload documents already confirmed in the checkpoint",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_model_providers_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe RAGFlow model-provider registration without mutating KBs")
    subparsers = parser.add_subparsers(dest="model_providers_command", required=True)

    probe = subparsers.add_parser("probe", help="Probe read-only model-provider endpoints")
    probe.add_argument("--config", help="Runtime config file")
    probe.add_argument("--base-url", help="RAGFlow base URL")
    probe.add_argument("--api-key", help="RAGFlow API key")
    probe.add_argument("--timeout", type=float, help="HTTP timeout seconds")
    probe.add_argument("--endpoint", action="append", default=[], help="Provider endpoint path to probe; repeatable")
    probe.add_argument("--embedding-model", action="append", default=[], help="Expected embedding model name; repeatable")
    probe.add_argument("--rerank-model", action="append", default=[], help="Expected rerank model name; repeatable")
    probe.add_argument("--embedding-adapter-url", help="Explicit embedding adapter URL for empty-input request-shape probe")
    probe.add_argument("--embedding-adapter-api-key", help="Embedding adapter bearer token")
    probe.add_argument(
        "--embedding-adapter-shape",
        choices=("openai", "generic"),
        default="openai",
        help="Embedding adapter request shape",
    )
    probe.add_argument("--rerank-adapter-url", help="Explicit rerank adapter URL for empty-input request-shape probe")
    probe.add_argument("--rerank-adapter-api-key", help="Rerank adapter bearer token")
    probe.add_argument(
        "--rerank-adapter-shape",
        choices=("cohere", "generic"),
        default="cohere",
        help="Rerank adapter request shape",
    )
    probe.add_argument("--adapter-timeout", type=float, default=5.0, help="Adapter empty-input probe timeout seconds")
    probe.add_argument("--report-json", help="Optional JSON probe report path")
    probe.add_argument("--report-md", help="Optional Markdown probe report path")
    probe.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    probe.add_argument("--json", action="store_true", help="Emit JSON errors")
    probe.set_defaults(func=_run_model_providers_probe)

    return parser


def build_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, merge, and template public RAGFlow metadata")
    subparsers = parser.add_subparsers(dest="metadata_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_metadata_v1 file")
    lint.add_argument("--metadata", required=True, help="Metadata JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_metadata_lint)

    merge = subparsers.add_parser("merge", help="Merge path-derived, handoff, and user metadata")
    merge.add_argument("--doc-manifest", help="Optional doc_manifest.json")
    merge.add_argument("--handoff-metadata", help="Optional rich handoff metadata.json")
    merge.add_argument("--metadata", help="Optional user ragflow_metadata_v1 file")
    merge.add_argument("--output", required=True, help="Output merged ragflow_metadata_v1 JSON")
    merge.add_argument("--report-json", help="Optional JSON merge report path")
    merge.add_argument("--report-md", help="Optional Markdown merge report path")
    merge.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    merge.add_argument("--no-derive-from-path", action="store_true", help="Do not fill missing fields from document paths")
    merge.add_argument("--json", action="store_true", help="Emit JSON errors")
    merge.set_defaults(func=_run_metadata_merge)

    template = subparsers.add_parser("generate-template", help="Generate a user-editable metadata template")
    template.add_argument("--doc-manifest", help="Optional doc_manifest.json used to list document paths")
    template.add_argument("--output", required=True, help="Output metadata template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_metadata_generate_template)

    suggest_request = subparsers.add_parser(
        "suggest-request",
        help="Create an advisory metadata suggestion request for an external LLM",
    )
    suggest_request.add_argument("--doc-manifest", required=True, help="doc_manifest.json used to list document paths")
    suggest_request.add_argument("--handoff-metadata", help="Optional rich handoff metadata.json")
    suggest_request.add_argument("--metadata", help="Optional existing ragflow_metadata_v1 file")
    suggest_request.add_argument("--output", required=True, help="Output metadata suggestion request JSON")
    suggest_request.add_argument("--report-json", help="Optional JSON report path")
    suggest_request.add_argument("--report-md", help="Optional Markdown report path")
    suggest_request.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    suggest_request.add_argument("--include-excerpts", action="store_true", help="Include truncated Markdown excerpts for host-approved LLM context")
    suggest_request.add_argument("--max-excerpt-chars", type=int, default=1200, help="Maximum excerpt characters per document")
    suggest_request.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest_request.set_defaults(func=_run_metadata_suggest_request)

    suggest_review = subparsers.add_parser(
        "suggest-review",
        help="Review external LLM metadata suggestions before use",
    )
    suggest_review.add_argument("--candidate", required=True, help="Candidate ragflow_metadata_v1 JSON/YAML from an external LLM")
    suggest_review.add_argument("--request", help="Optional metadata suggestion request JSON used to verify document paths")
    suggest_review.add_argument("--report-json", help="Optional JSON review report path")
    suggest_review.add_argument("--report-md", help="Optional Markdown review report path")
    suggest_review.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    suggest_review.add_argument("--allow-non-advisory", action="store_true", help="Allow candidates that do not set advisory=true")
    suggest_review.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest_review.set_defaults(func=_run_metadata_suggest_review)

    return parser


def build_tagset_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, export, and report public RAGFlow tagsets")
    subparsers = parser.add_subparsers(dest="tagset_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_tagset_v1 file")
    lint.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_tagset_lint)

    export = subparsers.add_parser("export", help="Export tagset tags as JSON or CSV")
    export.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    export.add_argument("--format", choices=("json", "csv"), default="json", help="Export format")
    export.add_argument("--output", required=True, help="Output JSON or CSV path")
    export.add_argument("--json", action="store_true", help="Emit JSON errors")
    export.set_defaults(func=_run_tagset_export)

    report = subparsers.add_parser("report", help="Report tag coverage, duplicates, and orphan warnings")
    report.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    report.add_argument("--metadata", help="Optional metadata file for document coverage checks")
    report.add_argument("--report-json", help="Optional JSON report path")
    report.add_argument("--report-md", help="Optional Markdown report path")
    report.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_tagset_report)

    template = subparsers.add_parser("generate-template", help="Generate a placeholder tagset template")
    template.add_argument("--output", required=True, help="Output tagset template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_tagset_generate_template)

    return parser


def build_snapshot_chunks_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a stable chunk snapshot from local chunks or validation output")
    parser.add_argument("--input", required=True, help="Input validation/retrieval JSON report, Markdown file, or Markdown directory")
    parser.add_argument("--output", required=True, help="Output ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument(
        "--observed-state",
        "--refresh-report",
        dest="observed_state",
        help="Optional ragflow_kb_refresh_report_v1 JSON used as shared observed-state evidence",
    )
    parser.add_argument("--name", default="chunk-snapshot", help="Chunk snapshot name")
    parser.add_argument("--description", help="Optional chunk snapshot description")
    parser.add_argument("--include-content", action="store_true", help="Include full chunk content in the snapshot")
    parser.add_argument(
        "--markdown-boundary-mode",
        choices=("file", "markers", "auto"),
        default="file",
        help="Markdown-only boundary policy: compatible whole-file, forced markers, or deterministic auto",
    )
    parser.add_argument("--report-json", help="Optional snapshot report JSON path")
    parser.add_argument("--report-md", help="Optional snapshot report Markdown path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_snapshot_chunks)
    return parser


def build_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import, sample, preflight, summarize, and gate benchmark artifacts")
    subparsers = parser.add_subparsers(dest="benchmark_command", required=True)

    import_cmd = subparsers.add_parser("import", help="Normalize query/qrels files into a benchmark directory")
    import_cmd.add_argument("--queries", required=True, help="Input benchmark query set JSON")
    import_cmd.add_argument("--qrels", required=True, help="Input benchmark qrels JSON")
    import_cmd.add_argument("--qa", help="Optional grounded QA JSON")
    import_cmd.add_argument("--source-attribution", help="Optional benchmark source attribution JSON")
    import_cmd.add_argument("--selection-report", help="Optional benchmark subset selection report JSON")
    import_cmd.add_argument("--output", required=True, help="Output benchmark directory")
    import_cmd.add_argument("--name", default="benchmark", help="Benchmark name recorded in manifest")
    import_cmd.add_argument("--description", help="Optional benchmark description")
    import_cmd.add_argument("--checkpoint", help="Checkpoint path for resumable benchmark imports")
    import_cmd.add_argument("--resume", action="store_true", help="Resume from an existing benchmark import checkpoint")
    import_cmd.add_argument("--batch-size", type=int, help="Import at most this many new queries in this run")
    import_cmd.add_argument("--report-json", help="Optional import report JSON path")
    import_cmd.add_argument("--report-md", help="Optional import report Markdown path")
    import_cmd.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    import_cmd.add_argument("--json", action="store_true", help="Emit JSON errors")
    import_cmd.set_defaults(func=_run_benchmark_import)

    preflight = subparsers.add_parser("preflight", help="Check benchmark artifacts before live validation")
    preflight.add_argument("--manifest", help="Benchmark manifest.json")
    preflight.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    preflight.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    preflight.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    preflight.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 file for expected_chunks checks")
    preflight.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    preflight.add_argument("--report-json", help="Optional preflight report JSON path")
    preflight.add_argument("--report-md", help="Optional preflight report Markdown path")
    preflight.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    preflight.add_argument("--json", action="store_true", help="Emit JSON errors")
    preflight.set_defaults(func=_run_benchmark_preflight)

    sample = subparsers.add_parser("sample", help="Create a deterministic benchmark subset")
    sample.add_argument("--manifest", help="Benchmark manifest.json")
    sample.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    sample.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    sample.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    sample.add_argument(
        "--source-attribution",
        help="Optional source attribution JSON when no manifest is provided",
    )
    sample.add_argument(
        "--selection-report",
        help="Optional selection report JSON when no manifest is provided",
    )
    sample.add_argument("--output", required=True, help="Output sampled benchmark directory")
    sample.add_argument("--size", type=int, help="Number of queries to sample")
    sample.add_argument("--fraction", type=float, help="Fraction of queries to sample")
    sample.add_argument("--strategy", choices=("first", "random", "stratified"), default="stratified", help="Sampling strategy")
    sample.add_argument("--seed", type=int, default=0, help="Deterministic sampling seed")
    sample.add_argument("--name", default="benchmark-sample", help="Benchmark sample name recorded in manifest")
    sample.add_argument("--description", help="Optional benchmark sample description")
    sample.add_argument("--report-json", help="Optional sample report JSON path")
    sample.add_argument("--report-md", help="Optional sample report Markdown path")
    sample.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    sample.add_argument("--json", action="store_true", help="Emit JSON errors")
    sample.set_defaults(func=_run_benchmark_sample)

    summarize = subparsers.add_parser("summarize", help="Summarize an existing benchmark validation report")
    summarize.add_argument("--report", required=True, help="Benchmark validation report JSON")
    summarize.add_argument("--report-json", help="Optional summary report JSON path")
    summarize.add_argument("--report-md", help="Optional summary report Markdown path")
    summarize.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    summarize.add_argument("--json", action="store_true", help="Emit JSON errors")
    summarize.set_defaults(func=_run_benchmark_summarize)

    gate = subparsers.add_parser("gate", help="Apply a gate config to an existing benchmark validation report")
    gate.add_argument("--report", required=True, help="Benchmark validation report JSON")
    gate.add_argument("--gate-config", required=True, help="Benchmark gate threshold JSON")
    gate.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    gate.add_argument("--report-json", help="Optional gate report JSON path")
    gate.add_argument("--report-md", help="Optional gate report Markdown path")
    gate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    gate.add_argument("--json", action="store_true", help="Emit JSON errors")
    gate.set_defaults(func=_run_benchmark_gate)

    trend = subparsers.add_parser("trend", help="Compare current benchmark metrics with a baseline report")
    trend.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    trend.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    trend.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    trend.add_argument("--report-json", help="Optional trend report JSON path")
    trend.add_argument("--report-md", help="Optional trend report Markdown path")
    trend.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    trend.add_argument("--json", action="store_true", help="Emit JSON errors")
    trend.set_defaults(func=_run_benchmark_trend)

    delta = subparsers.add_parser("delta", help="Report metric deltas between two benchmark reports")
    delta.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    delta.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    delta.add_argument("--report-json", help="Optional delta report JSON path")
    delta.add_argument("--report-md", help="Optional delta report Markdown path")
    delta.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    delta.add_argument("--json", action="store_true", help="Emit JSON errors")
    delta.set_defaults(func=_run_benchmark_delta)

    suggest = subparsers.add_parser("suggest", help="Suggest retrieval parameter experiments from a benchmark report")
    suggest.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    suggest.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    suggest.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    suggest.add_argument("--retrieval-hints", help="Optional ragflow_retrieval_hints_v1 JSON for benchmark artifact suggestions")
    suggest.add_argument("--current-top-k", type=int, help="Current retrieval top_k, defaults to benchmark cutoff when available")
    suggest.add_argument("--current-similarity-threshold", type=float, help="Current retrieval similarity threshold")
    suggest.add_argument("--report-json", help="Optional suggestion report JSON path")
    suggest.add_argument("--report-md", help="Optional suggestion report Markdown path")
    suggest.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    suggest.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest.set_defaults(func=_run_benchmark_suggest)

    return parser


def build_suppression_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create advisory suppression candidates from an existing validation report")
    parser.add_argument("--report", required=True, help="Validation or benchmark validation report JSON")
    parser.add_argument("--tagset", help="Optional ragflow_tagset_v1 JSON/YAML for tag labels and aliases")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum candidates to include in the report")
    parser.add_argument("--report-json", help="Optional suppression report JSON path")
    parser.add_argument("--report-md", help="Optional suppression report Markdown path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_suppression_report)
    return parser


def build_qa_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and validate grounded QA artifacts before benchmark use")
    subparsers = parser.add_subparsers(dest="qa_command", required=True)

    generate = subparsers.add_parser("generate", help="Generate deterministic grounded QA from source spans")
    generate.add_argument("--sources", help="Optional source text JSON/Markdown file")
    generate.add_argument("--source-dir", help="Optional directory of source text files")
    generate.add_argument("--output", required=True, help="Output ragflow_grounded_qa_v1 JSON")
    generate.add_argument("--count", type=int, default=20, help="Maximum QA items to generate")
    generate.add_argument("--strategy", choices=("first", "random"), default="first", help="Source span selection strategy")
    generate.add_argument("--seed", type=int, default=0, help="Deterministic seed for random strategy")
    generate.add_argument("--min-span-chars", type=int, default=40, help="Minimum evidence span length")
    generate.add_argument("--max-span-chars", type=int, default=240, help="Maximum evidence span length")
    generate.add_argument("--checkpoint", help="Checkpoint path for resumable deterministic QA generation")
    generate.add_argument("--resume", action="store_true", help="Resume from an existing QA generation checkpoint")
    generate.add_argument("--batch-size", type=int, help="Generate at most this many new QA items in this run")
    generate.add_argument("--report-json", help="Optional generate report JSON path")
    generate.add_argument("--report-md", help="Optional generate report Markdown path")
    generate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    generate.add_argument("--json", action="store_true", help="Emit JSON errors")
    generate.set_defaults(func=_run_qa_generate)

    validate = subparsers.add_parser("validate", help="Validate grounded QA evidence spans")
    validate.add_argument("--qa", required=True, help="Grounded QA JSON")
    validate.add_argument("--sources", help="Optional source text JSON/Markdown file for exact evidence checks")
    validate.add_argument("--source-dir", help="Optional directory of source text files for exact evidence checks")
    validate.add_argument("--allow-missing-answer", action="store_true", help="Allow QA items without answers")
    validate.add_argument("--report-json", help="Optional validate report JSON path")
    validate.add_argument("--report-md", help="Optional validate report Markdown path")
    validate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    validate.add_argument("--json", action="store_true", help="Emit JSON errors")
    validate.set_defaults(func=_run_qa_validate)

    map_evidence = subparsers.add_parser("map-evidence", help="Map QA evidence spans onto a chunk snapshot")
    map_evidence.add_argument("--qa", required=True, help="Grounded QA JSON")
    map_evidence.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    map_evidence.add_argument("--output", required=True, help="Output ragflow_grounded_qa_evidence_map_v1 JSON")
    map_evidence.add_argument("--report-json", help="Optional map-evidence report JSON path")
    map_evidence.add_argument("--report-md", help="Optional map-evidence report Markdown path")
    map_evidence.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    map_evidence.add_argument("--json", action="store_true", help="Emit JSON errors")
    map_evidence.set_defaults(func=_run_qa_map_evidence)

    suggest_request = subparsers.add_parser(
        "suggest-request",
        help="Create an advisory grounded-QA request for an external LLM",
    )
    suggest_request.add_argument("--sources", help="Optional source text JSON/Markdown file")
    suggest_request.add_argument("--source-dir", help="Optional directory of source text files")
    suggest_request.add_argument("--output", required=True, help="Output grounded-QA suggestion request JSON")
    suggest_request.add_argument("--target-count", type=int, default=20, help="Requested candidate QA item count")
    suggest_request.add_argument(
        "--question-type",
        action="append",
        default=[],
        help="Requested question type; repeatable",
    )
    suggest_request.add_argument("--include-excerpts", action="store_true", help="Include truncated source excerpts for host-approved LLM context")
    suggest_request.add_argument("--max-excerpt-chars", type=int, default=1200, help="Maximum excerpt characters per source")
    suggest_request.add_argument("--min-evidence-chars", type=int, default=20, help="Minimum exact evidence span length")
    suggest_request.add_argument("--max-evidence-chars", type=int, default=240, help="Maximum exact evidence span length")
    suggest_request.add_argument("--report-json", help="Optional request report JSON path")
    suggest_request.add_argument("--report-md", help="Optional request report Markdown path")
    suggest_request.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    suggest_request.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest_request.set_defaults(func=_run_qa_suggest_request)

    suggest_review = subparsers.add_parser(
        "suggest-review",
        help="Review external grounded-QA suggestions before benchmark use",
    )
    suggest_review.add_argument("--candidate", required=True, help="Candidate ragflow_grounded_qa_v1 JSON from an external LLM")
    suggest_review.add_argument("--request", help="Optional grounded-QA suggestion request JSON")
    suggest_review.add_argument("--sources", help="Optional source text JSON/Markdown file for exact evidence checks")
    suggest_review.add_argument("--source-dir", help="Optional directory of source text files for exact evidence checks")
    suggest_review.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 JSON for evidence-map compatibility")
    suggest_review.add_argument("--evidence-map-output", help="Output ragflow_grounded_qa_evidence_map_v1 JSON when --chunk-snapshot is supplied")
    suggest_review.add_argument("--allow-missing-answer", action="store_true", help="Allow QA items without answers")
    suggest_review.add_argument("--allow-non-advisory", action="store_true", help="Allow candidates that do not set advisory=true")
    suggest_review.add_argument("--allow-non-generated", action="store_true", help="Allow candidates that do not set generated=true")
    suggest_review.add_argument("--report-json", help="Optional review report JSON path")
    suggest_review.add_argument("--report-md", help="Optional review report Markdown path")
    suggest_review.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    suggest_review.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest_review.set_defaults(func=_run_qa_suggest_review)

    apollo_validate = subparsers.add_parser(
        "apollo-validate",
        help="Validate a sanitized APOLLO table-QA fixture",
    )
    apollo_validate.add_argument("--fixture", required=True, help="apollo_table_qa_fixture_v1 JSON")
    apollo_validate.add_argument("--report-json", help="Optional fixture validation report JSON path")
    apollo_validate.add_argument("--report-md", help="Optional fixture validation report Markdown path")
    apollo_validate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    apollo_validate.add_argument("--json", action="store_true", help="Emit JSON errors")
    apollo_validate.set_defaults(func=_run_qa_apollo_validate)

    apollo_evaluate = subparsers.add_parser(
        "apollo-evaluate",
        help="Evaluate existing retrieval/answer JSON against an APOLLO table-QA fixture",
    )
    apollo_evaluate.add_argument("--fixture", required=True, help="apollo_table_qa_fixture_v1 JSON")
    apollo_evaluate.add_argument("--results", required=True, help="Existing retrieval/answer results JSON")
    apollo_evaluate.add_argument(
        "--target",
        choices=("auto", "answer", "retrieval", "both"),
        default="auto",
        help="Evaluation target used for case pass/fail status",
    )
    apollo_evaluate.add_argument("--report-json", help="Optional evaluation report JSON path")
    apollo_evaluate.add_argument("--report-md", help="Optional evaluation report Markdown path")
    apollo_evaluate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    apollo_evaluate.add_argument("--json", action="store_true", help="Emit JSON errors")
    apollo_evaluate.set_defaults(func=_run_qa_apollo_evaluate)

    apollo_judge_request = subparsers.add_parser(
        "apollo-judge-request",
        help="Create a no-LLM external judge request for APOLLO table-QA results",
    )
    apollo_judge_request.add_argument("--fixture", required=True, help="apollo_table_qa_fixture_v1 JSON")
    apollo_judge_request.add_argument("--results", required=True, help="Existing retrieval/answer results JSON")
    apollo_judge_request.add_argument("--output", required=True, help="Output APOLLO judge request JSON")
    apollo_judge_request.add_argument(
        "--target",
        choices=("auto", "answer", "retrieval", "both"),
        default="auto",
        help="Baseline evaluation target used for request context",
    )
    apollo_judge_request.add_argument("--evaluation-report", help="Optional existing apollo_table_qa_evaluation_report_v1 JSON")
    apollo_judge_request.add_argument("--omit-answer-text", action="store_true", help="Omit answer previews from the request")
    apollo_judge_request.add_argument(
        "--omit-retrieval-previews",
        action="store_true",
        help="Omit retrieval chunk previews from the request",
    )
    apollo_judge_request.add_argument("--max-answer-chars", type=int, default=1200, help="Maximum answer preview characters")
    apollo_judge_request.add_argument(
        "--max-retrieval-chars",
        type=int,
        default=1200,
        help="Maximum retrieval preview characters per chunk",
    )
    apollo_judge_request.add_argument(
        "--max-retrieval-items",
        type=int,
        default=5,
        help="Maximum retrieval evidence items per case",
    )
    apollo_judge_request.add_argument("--report-json", help="Optional request report JSON path")
    apollo_judge_request.add_argument("--report-md", help="Optional request report Markdown path")
    apollo_judge_request.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    apollo_judge_request.add_argument("--json", action="store_true", help="Emit JSON errors")
    apollo_judge_request.set_defaults(func=_run_qa_apollo_judge_request)

    apollo_judge_review = subparsers.add_parser(
        "apollo-judge-review",
        help="Review an external APOLLO table-QA judge candidate",
    )
    apollo_judge_review.add_argument("--request", required=True, help="apollo_table_qa_judge_request_v1 JSON")
    apollo_judge_review.add_argument("--candidate", required=True, help="External APOLLO judge candidate JSON")
    apollo_judge_review.add_argument("--allow-non-advisory", action="store_true", help="Allow candidates that do not set advisory=true")
    apollo_judge_review.add_argument("--allow-non-generated", action="store_true", help="Allow candidates that do not set generated=true")
    apollo_judge_review.add_argument("--report-json", help="Optional review report JSON path")
    apollo_judge_review.add_argument("--report-md", help="Optional review report Markdown path")
    apollo_judge_review.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    apollo_judge_review.add_argument("--json", action="store_true", help="Emit JSON errors")
    apollo_judge_review.set_defaults(func=_run_qa_apollo_judge_review)

    return parser


def build_segment_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report segment provenance metadata coverage for chunk snapshots")
    subparsers = parser.add_subparsers(dest="segment_metadata_command", required=True)

    report = subparsers.add_parser("report", help="Report segment and metadata coverage in a chunk snapshot")
    report.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    report.add_argument("--metadata", help="Optional ragflow_metadata_v1 JSON/YAML for document coverage")
    report.add_argument("--segmentation-plan", help="Optional doc_segmentation_plan_v1 JSON")
    report.add_argument("--report-json", help="Optional segment metadata report JSON path")
    report.add_argument("--report-md", help="Optional segment metadata report Markdown path")
    report.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_segment_metadata_report)

    return parser


def build_optimize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan RAGFlow profile optimization experiments")
    parser.add_argument("--plan-only", action="store_true", help="Create an offline optimization plan without mutating RAGFlow")
    parser.add_argument("--execute", action="store_true", help="Build selected disposable KBs after exact live confirmation")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="Base RAGFlow dataset name used for disposable KB naming")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    parser.add_argument("--profile", action="append", default=[], help="Candidate profile JSON/YAML path; may be repeated")
    parser.add_argument("--profile-dir", action="append", default=[], help="Directory of candidate profile JSON/YAML files; may be repeated")
    parser.add_argument("--profile-set", action="append", default=[], help="ragflow_candidate_profile_set_v1 JSON/YAML; may be repeated")
    parser.add_argument("--recommendation", action="append", default=[], help="Generated candidate as language:doc_type, e.g. en:manual")
    parser.add_argument("--benchmark-manifest", help="Benchmark manifest.json produced by benchmark import/sample")
    parser.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    parser.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    parser.add_argument("--qa", help="Optional grounded QA JSON")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file used by build/validation")
    parser.add_argument("--tagset", help="Optional tagset reference recorded in the plan")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 for strict chunk recall")
    parser.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    parser.add_argument("--baseline-report", help="Optional previous benchmark report JSON")
    parser.add_argument("--artifact-dir", default="optimization-artifacts", help="Planned experiment artifact directory")
    parser.add_argument("--run-id", help="Optional disposable KB run id; defaults to a deterministic hash")
    parser.add_argument("--top-k", type=int, default=3, help="Planned benchmark validation top_k")
    parser.add_argument("--metric-cutoff", type=int, help="Optional planned benchmark metric cutoff")
    parser.add_argument("--checkpoint", help="Checkpoint path for resumable offline optimization planning")
    parser.add_argument("--resume", action="store_true", help="Resume from an existing optimization planning checkpoint")
    parser.add_argument("--batch-size", type=int, help="Emit at most this many new optimization candidates in this run")
    parser.add_argument("--config", help="Runtime config file used only with --execute")
    parser.add_argument("--base-url", help="RAGFlow base URL used only with --execute")
    parser.add_argument("--api-key", help="RAGFlow API key used only with --execute")
    parser.add_argument("--confirm-live-build", action="store_true", help="Required with --execute to create disposable KBs")
    parser.add_argument("--confirm-kb-name", help="Required with --execute; must exactly match --kb-name")
    parser.add_argument("--confirm-run-id", help="Required with --execute; must exactly match the planned run_id")
    parser.add_argument("--validate-benchmark", action="store_true", help="With --execute, run benchmark validation for each built candidate KB")
    parser.add_argument("--no-parse", action="store_true", help="With --execute, upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="With --execute, do not wait for parse completion")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="With --execute, maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="With --execute, polling interval while waiting for parse completion")
    parser.add_argument("--output", default="optimization_plan.json", help="Output ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization plan Markdown path")
    parser.add_argument("--command-manifest-output", help="Optional dry-run command manifest for future live optimization execution")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize)
    return parser


def build_optimize_summarize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize profile optimization validation reports")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report", action="append", default=[], help="Validation report JSON; defaults to paths in the plan")
    parser.add_argument("--output", default="profile_experiment_results.json", help="Output ragflow_profile_experiment_results_v1 JSON")
    parser.add_argument("--report-md", default="best_profile_report.md", help="Output best profile Markdown report")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--cleanup-plan", help="Optional ragflow_optimization_cleanup_plan_v1 JSON for lifecycle closure")
    parser.add_argument("--readiness-report", help="Optional ragflow_optimization_live_readiness_report_v1 JSON")
    parser.add_argument("--cleanup-execution-report", help="Optional ragflow_optimization_cleanup_execution_report_v1 JSON")
    parser.add_argument("--score-epsilon", type=float, help="Score tie epsilon for co-winner decisions")
    parser.add_argument("--min-score-delta", type=float, help="Minimum score delta required for a single recommended winner")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_summarize)
    return parser


def build_optimize_cleanup_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating cleanup plan for profile optimization KBs")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--output", default="cleanup_plan.json", help="Output ragflow_optimization_cleanup_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization cleanup plan Markdown path")
    parser.add_argument("--cleanup-script", default="scripts/cleanup.py", help="Cleanup script path recorded in generated commands")
    parser.add_argument("--config", help="Optional runtime config path recorded in generated execute commands")
    parser.add_argument("--require-manifests", action="store_true", help="Fail when candidate kb_manifest files are not available yet")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_cleanup_plan)
    return parser


def build_optimize_readiness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review live disposable optimization readiness without contacting RAGFlow")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--cleanup-plan", required=True, help="ragflow_optimization_cleanup_plan_v1 JSON")
    parser.add_argument("--output", default="optimization_live_readiness_report.json", help="Output live readiness report JSON")
    parser.add_argument("--report-md", help="Optional live readiness Markdown report path")
    parser.add_argument("--config", help="Runtime config file checked for credentials without network access")
    parser.add_argument("--base-url", help="RAGFlow base URL override checked without network access")
    parser.add_argument("--api-key", help="RAGFlow API key override checked without network access")
    parser.add_argument("--confirm-live-build", action="store_true", help="Required to mark live build readiness")
    parser.add_argument("--confirm-kb-name", help="Must exactly match the optimization plan base KB name")
    parser.add_argument("--confirm-run-id", help="Must exactly match the optimization plan run_id")
    parser.add_argument("--confirm-cleanup-dataset-id", action="append", default=[], help="Ready cleanup dataset ID confirmation; repeatable")
    parser.add_argument("--confirm-cleanup-kb-name", action="append", default=[], help="Ready cleanup KB name confirmation; repeatable")
    parser.add_argument("--require-cleanup-ready", action="store_true", help="Require retained KB manifests and exact cleanup confirmations")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for live readiness reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_readiness)
    return parser


def build_optimize_cleanup_execute_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute exact-confirmation cleanup for profile optimization KBs")
    parser.add_argument("--cleanup-plan", required=True, help="ragflow_optimization_cleanup_plan_v1 JSON")
    parser.add_argument("--output", default="cleanup_execution_report.json", help="Output cleanup execution report JSON")
    parser.add_argument("--execute", action="store_true", help="Actually delete every ready target in the cleanup plan")
    parser.add_argument("--confirm-dataset-id", action="append", default=[], help="Required with --execute; repeat once per ready target")
    parser.add_argument("--confirm-kb-name", action="append", default=[], help="Required with --execute; repeat once per ready target in the same order")
    parser.add_argument("--readiness-report", help="Use exact cleanup confirmations from a reviewed live readiness report")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for cleanup execution reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_cleanup_execute)
    return parser


def build_topology_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create non-mutating KB topology advice")
    subparsers = parser.add_subparsers(dest="topology_command", required=True)

    advise = subparsers.add_parser("advise", help="Advise create, merge, split, or stage decisions")
    advise.add_argument("--input", help="Markdown file or directory")
    advise.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    advise.add_argument("--kb-name", required=True, help="Candidate RAGFlow dataset name")
    advise.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    advise.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    advise.add_argument("--route-config", help="Optional user-owned routing config for overlap checks")
    advise.add_argument(
        "--future-growth",
        choices=("low", "medium", "high"),
        default="medium",
        help="Expected future corpus growth for create-vs-merge advice",
    )
    advise.add_argument("--min-documents", type=int, default=3, help="Minimum documents for a standalone KB signal")
    advise.add_argument("--min-total-chars", type=int, default=1200, help="Minimum total Markdown chars for a standalone KB signal")
    advise.add_argument("--allow-blocked", action="store_true", help="Allow advice with a BLOCKED doc_manifest quality gate")
    advise.add_argument("--output", default="kb_topology_advice.json", help="Output kb_topology_advice_v1 JSON")
    advise.add_argument("--report-md", help="Optional topology advice Markdown path")
    advise.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    advise.add_argument("--json", action="store_true", help="Emit JSON errors")
    advise.set_defaults(func=_run_topology_advise)

    split_plan = subparsers.add_parser("split-plan", help="Plan advisory KB splits by local corpus signals")
    split_plan.add_argument("--input", help="Markdown file or directory")
    split_plan.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    split_plan.add_argument("--kb-name", required=True, help="Source or candidate RAGFlow dataset name")
    split_plan.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    split_plan.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    split_plan.add_argument("--min-group-documents", type=int, default=1, help="Minimum documents for a standalone split group")
    split_plan.add_argument(
        "--min-group-estimated-chunks",
        type=int,
        default=1,
        help="Minimum estimated chunks for a standalone split group",
    )
    split_plan.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    split_plan.add_argument("--output", default="kb_split_plan.json", help="Output kb_split_plan_v1 JSON")
    split_plan.add_argument("--report-md", help="Optional split plan Markdown path")
    split_plan.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    split_plan.add_argument("--json", action="store_true", help="Emit JSON errors")
    split_plan.set_defaults(func=_run_topology_split_plan)

    return parser


def build_activation_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating KB route activation plan")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--doc-manifest", help="Optional source doc_manifest.json for content quality checks")
    parser.add_argument("--route-config", help="Optional user-owned routing config")
    parser.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    parser.add_argument("--ingest-plan", help="Optional ragflow_ingest_plan.yaml from ragflow-doc-to-md pipeline")
    parser.add_argument("--profile", help="Optional reviewed kb-build profile used for ingestion")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument("--centroid-index", help="Optional ragflow_route_centroid_index_v1 JSON")
    parser.add_argument("--route-tests", help="Optional route-test queries JSON")
    parser.add_argument("--min-documents", type=int, default=1, help="Minimum documents before activation")
    parser.add_argument("--min-chunks", type=int, default=1, help="Minimum chunks before activation")
    parser.add_argument("--output", default="kb_activation_plan.json", help="Output kb_activation_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional activation plan Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_activation_plan)
    return parser


def build_parse_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an offline parser performance and parse-state report")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--documents-json", help="Optional user-supplied RAGFlow document list/status JSON")
    parser.add_argument(
        "--observed-state",
        "--refresh-report",
        dest="observed_state",
        help="Optional ragflow_kb_refresh_report_v1 JSON used as shared observed-state evidence",
    )
    parser.add_argument("--multimodal-kb-manifest", help="Optional ragflow_multimodal_kb_manifest_v1 JSON")
    parser.add_argument("--parse-log", action="append", default=[], help="Optional parser progress log; may be repeated")
    parser.add_argument("--profile", help="Optional chunk profile JSON/YAML to review parser settings")
    parser.add_argument("--parser-config", help="Optional parser_config JSON sidecar; overrides profile parser_config in this report")
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="parse_report.json",
        help="Output ragflow_parse_report_v1 JSON",
    )
    parser.add_argument("--report-md", help="Optional parse report Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_parse_report)
    return parser


def build_parameter_audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare dry-run KB parameters with read-back evidence without mutation")
    parser.add_argument("--dry-run-report", required=True, help="ragflow-kb-build --dry-run JSON containing payload preview")
    parser.add_argument(
        "--observed-state",
        "--refresh-report",
        dest="observed_state",
        help="Optional read-back JSON from RAGFlow dataset detail, document list, or refresh-report evidence",
    )
    parser.add_argument(
        "--evidence-bundle-id",
        help="Optional caller-generated UUID asserting that the supplied artifacts belong to one reviewed evidence bundle",
    )
    parser.add_argument(
        "--ragflow-contract-version",
        help="Optional caller-supplied RAGFlow version or contract label; requires --ragflow-contract-source",
    )
    parser.add_argument(
        "--ragflow-contract-source",
        choices=("server_reported", "openapi", "server_request_model", "operator_supplied"),
        help="Source for --ragflow-contract-version; the audit records this identity as caller-asserted",
    )
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="parameter_read_back_audit.json",
        help="Output ragflow_parameter_read_back_audit_v1 JSON",
    )
    parser.add_argument("--report-md", help="Optional parameter audit Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_parameter_audit)
    return parser


def build_refresh_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export current RAGFlow document states without mutating the KB")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--page", type=int, default=1, help="RAGFlow document-list page to read")
    parser.add_argument("--page-size", type=int, default=200, help="RAGFlow document-list page size")
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="kb_refresh_report.json",
        help=f"Output {KB_REFRESH_REPORT_SCHEMA} JSON",
    )
    parser.add_argument("--report-md", help="Optional KB refresh Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_refresh_report)
    return parser


def build_health_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an offline aggregate KB health report")
    parser.add_argument("--kb-manifest", action="append", required=True, help="Local kb_manifest.json; may be repeated")
    parser.add_argument("--parse-report", action="append", default=[], help="Optional ragflow_parse_report_v1 JSON; may be repeated")
    parser.add_argument(
        "--observed-state",
        "--refresh-report",
        dest="observed_state",
        action="append",
        default=[],
        help="Optional ragflow_kb_refresh_report_v1 JSON; may be repeated",
    )
    parser.add_argument("--activation-plan", action="append", default=[], help="Optional kb_activation_plan_v1 JSON; may be repeated")
    parser.add_argument(
        "--model-provider-probe",
        action="append",
        default=[],
        help="Optional ragflow_model_provider_probe_report_v1 JSON; may be repeated",
    )
    parser.add_argument("--min-documents", type=int, default=1, help="Minimum documents before a KB is considered non-empty")
    parser.add_argument("--min-chunks", type=int, default=1, help="Minimum declared chunks before a KB is considered non-empty")
    parser.add_argument(
        "--expected-embedding-model",
        action="append",
        default=[],
        help="Expected embedding model for built KB manifests; repeatable",
    )
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="kb_health_report.json",
        help="Output ragflow_kb_health_report_v1 JSON",
    )
    parser.add_argument("--report-md", help="Optional KB health Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_health_report)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a RAGFlow KB from Markdown")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="RAGFlow dataset name")
    parser.add_argument("--profile", required=True, help="Chunk profile JSON/YAML")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file to summarize and lint before upload")
    parser.add_argument("--retrieval-hints", help="Optional retrieval_hints.json used by dry-run readiness review")
    parser.add_argument("--ingest-plan", help="Optional ragflow_ingest_plan.yaml/json used by build payload preview")
    parser.add_argument("--output", default="kb_manifest.json", help="Output kb_manifest.json path for non-dry-run builds")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument(
        "--expected-embedding-model",
        action="append",
        default=[],
        help="Expected embedding model label for dry-run/build drift warnings; repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without touching RAGFlow or writing kb_manifest.json")
    parser.add_argument(
        "--probe-kb-name-collision",
        action="store_true",
        help="With --dry-run, use read-only dataset listing to review KB name collisions",
    )
    parser.add_argument("--no-parse", action="store_true", help="Upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for parse completion after triggering parse")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow upload when doc_manifest quality_gate.status is BLOCKED")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds while waiting for parse completion")
    parser.add_argument("--batch-size", type=int, help="Maximum uploaded Markdown document IDs per parse trigger")
    parser.add_argument("--checkpoint", help="Checkpoint path for resumable live Markdown builds")
    parser.add_argument("--resume", action="store_true", help="Resume a live Markdown build from an existing checkpoint")
    parser.add_argument(
        "--force-reupload-confirmed",
        action="store_true",
        help="With --resume, re-upload documents already confirmed in the checkpoint",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect-handoff":
            return _run_inspect_handoff(build_inspect_handoff_parser().parse_args(command_args))
        if command == "asset-upload-plan":
            return _run_asset_upload_plan(build_asset_upload_plan_parser().parse_args(command_args))
        if command == "image-ingestion-readiness":
            return _run_image_ingestion_readiness(build_image_ingestion_readiness_parser().parse_args(command_args))
        if command == "consistency-check":
            return _run_consistency_check(build_consistency_check_parser().parse_args(command_args))
        if command == "image-ingestion-execute":
            return _run_image_ingestion_execute(build_image_ingestion_execute_parser().parse_args(command_args))
        if command == "model-providers":
            model_provider_args = build_model_providers_parser().parse_args(command_args)
            return model_provider_args.func(model_provider_args)
        if command == "metadata":
            metadata_args = build_metadata_parser().parse_args(command_args)
            return metadata_args.func(metadata_args)
        if command == "tagset":
            tagset_args = build_tagset_parser().parse_args(command_args)
            return tagset_args.func(tagset_args)
        if command == "snapshot-chunks":
            snapshot_args = build_snapshot_chunks_parser().parse_args(command_args)
            return snapshot_args.func(snapshot_args)
        if command == "benchmark":
            benchmark_args = build_benchmark_parser().parse_args(command_args)
            return benchmark_args.func(benchmark_args)
        if command == "suppression-report":
            suppression_args = build_suppression_report_parser().parse_args(command_args)
            return suppression_args.func(suppression_args)
        if command == "qa":
            qa_args = build_qa_parser().parse_args(command_args)
            return qa_args.func(qa_args)
        if command == "segment-metadata":
            segment_metadata_args = build_segment_metadata_parser().parse_args(command_args)
            return segment_metadata_args.func(segment_metadata_args)
        if command == "topology":
            topology_args = build_topology_parser().parse_args(command_args)
            return topology_args.func(topology_args)
        if command == "activation-plan":
            activation_plan_args = build_activation_plan_parser().parse_args(command_args)
            return activation_plan_args.func(activation_plan_args)
        if command == "parse-report":
            parse_report_args = build_parse_report_parser().parse_args(command_args)
            return parse_report_args.func(parse_report_args)
        if command == "parameter-audit":
            parameter_audit_args = build_parameter_audit_parser().parse_args(command_args)
            return parameter_audit_args.func(parameter_audit_args)
        if command == "refresh-report":
            refresh_report_args = build_refresh_report_parser().parse_args(command_args)
            return refresh_report_args.func(refresh_report_args)
        if command == "health-report":
            health_report_args = build_health_report_parser().parse_args(command_args)
            return health_report_args.func(health_report_args)
        if command == "optimize":
            if command_args and command_args[0] == "summarize":
                optimize_summary_args = build_optimize_summarize_parser().parse_args(command_args[1:])
                return optimize_summary_args.func(optimize_summary_args)
            if command_args and command_args[0] == "cleanup-plan":
                optimize_cleanup_args = build_optimize_cleanup_plan_parser().parse_args(command_args[1:])
                return optimize_cleanup_args.func(optimize_cleanup_args)
            if command_args and command_args[0] == "readiness":
                optimize_readiness_args = build_optimize_readiness_parser().parse_args(command_args[1:])
                return optimize_readiness_args.func(optimize_readiness_args)
            if command_args and command_args[0] == "cleanup-execute":
                optimize_cleanup_execute_args = build_optimize_cleanup_execute_parser().parse_args(command_args[1:])
                return optimize_cleanup_execute_args.func(optimize_cleanup_execute_args)
            optimize_args = build_optimize_parser().parse_args(command_args)
            return optimize_args.func(optimize_args)
    args = build_parser().parse_args(actual_argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
