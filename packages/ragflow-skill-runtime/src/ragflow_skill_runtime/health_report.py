"""Offline KB health telemetry reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .kb_build import parse_state_failed, parse_state_succeeded
from .manifests import KbManifest, ManifestError, load_kb_manifest
from .parse_report import PARSE_REPORT_SCHEMA
from .topology import KB_ACTIVATION_PLAN_SCHEMA


HEALTH_REPORT_SCHEMA = "ragflow_kb_health_report_v1"


class HealthReportError(RuntimeError):
    """Raised when health-report inputs cannot be loaded."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HealthReportError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise HealthReportError(f"file is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise HealthReportError(f"file must contain a JSON object: {source}")
    return payload


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _issue(
    *,
    severity: str,
    code: str,
    message: str,
    dataset_id: str | None = None,
    kb_name: str | None = None,
    recommendation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if dataset_id:
        payload["dataset_id"] = dataset_id
    if kb_name:
        payload["kb_name"] = kb_name
    if recommendation:
        payload["recommendation"] = recommendation
    return payload


def _load_kb_manifest(path: str | Path) -> KbManifest:
    try:
        return load_kb_manifest(path)
    except ManifestError as exc:
        raise HealthReportError(str(exc)) from exc


def _load_schema_sidecars(paths: Iterable[str | Path], *, expected_schema: str, label: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        payload = _read_json_mapping(path)
        if payload.get("schema") != expected_schema:
            raise HealthReportError(f"{label} schema must be {expected_schema}: {path}")
        payload["_source_path"] = str(path)
        payloads.append(payload)
    return payloads


def _dataset_id_from_payload(payload: Mapping[str, Any]) -> str:
    value = payload.get("dataset_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    dataset = payload.get("dataset")
    if isinstance(dataset, Mapping):
        value = dataset.get("id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _index_by_dataset_id(payloads: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        dataset_id = _dataset_id_from_payload(payload)
        if dataset_id:
            indexed[dataset_id] = dict(payload)
    return indexed


def _manifest_chunk_total(kb_manifest: KbManifest) -> int:
    total = 0
    for document in kb_manifest.documents:
        if isinstance(document.chunk_count, int):
            total += document.chunk_count
    return total


def _manifest_parse_counts(kb_manifest: KbManifest) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for document in kb_manifest.documents:
        state = {"status": document.status or "", "chunk_count": document.chunk_count}
        if parse_state_failed(state):
            counts["failed"] += 1
        elif parse_state_succeeded(state):
            counts["succeeded"] += 1
        elif document.status:
            counts["pending"] += 1
        else:
            counts["unknown"] += 1
    return dict(counts)


def _embedding_model(kb_manifest: KbManifest) -> str:
    value = kb_manifest.profile.get("embedding_model") if isinstance(kb_manifest.profile, Mapping) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _normalize_expected_models(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            models.append(text)
    return models


def _embedding_model_check(embedding_model: str, expected_embedding_models: list[str]) -> dict[str, Any]:
    if not expected_embedding_models:
        return {
            "status": "not_configured",
            "expected_models": [],
            "matches_expected": None,
            "rebuild_or_reparse_required": False,
        }
    if embedding_model == "unknown":
        return {
            "status": "unknown",
            "expected_models": list(expected_embedding_models),
            "matches_expected": None,
            "rebuild_or_reparse_required": False,
        }
    expected_keys = {model.casefold() for model in expected_embedding_models}
    matches = embedding_model.casefold() in expected_keys
    return {
        "status": "match" if matches else "mismatch",
        "expected_models": list(expected_embedding_models),
        "matches_expected": matches,
        "rebuild_or_reparse_required": not matches,
    }


def _parse_summary(parse_report: Mapping[str, Any] | None, kb_manifest: KbManifest) -> dict[str, Any]:
    manifest_counts = _manifest_parse_counts(kb_manifest)
    if not parse_report:
        return {
            "available": False,
            "status": "not_available",
            "failed_document_count": manifest_counts.get("failed", 0),
            "pending_document_count": manifest_counts.get("pending", 0) + manifest_counts.get("unknown", 0),
            "zero_chunk_document_count": sum(1 for document in kb_manifest.documents if document.chunk_count == 0),
            "chunk_mismatch_count": 0,
            "expensive_setting_count": 0,
            "parse_log_error_count": 0,
            "visual_document_count": 0,
            "thumbnail_document_count": 0,
            "vlm_observed_document_count": 0,
            "visual_chunk_count": 0,
            "multimodal_manifest": None,
            "source": None,
        }

    summary = parse_report.get("summary", {}) if isinstance(parse_report.get("summary"), Mapping) else {}
    chunk_consistency = (
        parse_report.get("chunk_consistency", {}) if isinstance(parse_report.get("chunk_consistency"), Mapping) else {}
    )
    parser_settings = (
        parse_report.get("parser_settings", {}) if isinstance(parse_report.get("parser_settings"), Mapping) else {}
    )
    parse_logs = (
        parse_report.get("parse_log_summary", {}) if isinstance(parse_report.get("parse_log_summary"), Mapping) else {}
    )
    return {
        "available": True,
        "status": parse_report.get("status", "UNKNOWN"),
        "failed_document_count": _as_int(summary.get("failed_document_count")) or 0,
        "pending_document_count": _as_int(summary.get("pending_document_count")) or 0,
        "zero_chunk_document_count": _as_int(summary.get("zero_chunk_document_count")) or 0,
        "chunk_mismatch_count": _as_int(summary.get("chunk_mismatch_count")) or 0,
        "chunk_consistency_mismatch_count": _as_int(chunk_consistency.get("mismatch_count")) or 0,
        "expensive_setting_count": _as_int(parser_settings.get("expensive_setting_count")) or 0,
        "parse_log_error_count": _as_int(parse_logs.get("error_count")) or 0,
        "visual_document_count": _as_int(summary.get("visual_document_count")) or 0,
        "thumbnail_document_count": _as_int(summary.get("thumbnail_document_count")) or 0,
        "vlm_observed_document_count": _as_int(summary.get("vlm_observed_document_count")) or 0,
        "visual_chunk_count": _as_int(summary.get("visual_chunk_count")) or 0,
        "multimodal_manifest": parse_report.get("multimodal_manifest")
        if isinstance(parse_report.get("multimodal_manifest"), Mapping)
        else None,
        "source": parse_report.get("_source_path"),
    }


def _activation_summary(activation_plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if not activation_plan:
        return {
            "available": False,
            "status": "not_available",
            "blocked_check_count": 0,
            "review_check_count": 0,
            "recommendation": "provide_activation_plan",
            "source": None,
        }
    summary = activation_plan.get("summary", {}) if isinstance(activation_plan.get("summary"), Mapping) else {}
    blocked = _as_int(summary.get("blocked_check_count")) or 0
    review = _as_int(summary.get("review_check_count")) or 0
    status = "blocked" if blocked else "review" if review else "ready"
    return {
        "available": True,
        "status": status,
        "blocked_check_count": blocked,
        "review_check_count": review,
        "recommendation": summary.get("recommendation") or "review_activation_plan",
        "source": activation_plan.get("_source_path"),
    }


def _kb_health_item(
    *,
    kb_manifest_path: str | Path,
    kb_manifest: KbManifest,
    parse_report: Mapping[str, Any] | None,
    activation_plan: Mapping[str, Any] | None,
    min_documents: int,
    min_chunks: int,
    expected_embedding_models: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset_id = kb_manifest.dataset.id
    kb_name = kb_manifest.dataset.name
    document_count = len(kb_manifest.documents)
    chunk_total = _manifest_chunk_total(kb_manifest)
    embedding_model = _embedding_model(kb_manifest)
    embedding_check = _embedding_model_check(embedding_model, expected_embedding_models)
    parse = _parse_summary(parse_report, kb_manifest)
    activation = _activation_summary(activation_plan)

    risks: list[dict[str, Any]] = []
    if document_count < min_documents:
        risks.append(
            _issue(
                severity="warning",
                code="zero_or_thin_document_kb",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=f"KB has {document_count} document(s), below the minimum of {min_documents}.",
                recommendation="Confirm the build completed and upload additional documents through normal RAGFlow/API flow.",
            )
        )
    if chunk_total < min_chunks:
        risks.append(
            _issue(
                severity="warning",
                code="zero_or_thin_chunk_kb",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=f"KB has {chunk_total} declared chunk(s), below the minimum of {min_chunks}.",
                recommendation="Review parser settings and parse status; do not repair DB/Redis from this public command.",
            )
        )
    if embedding_model == "unknown":
        risks.append(
            _issue(
                severity="info",
                code="embedding_model_unknown",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message="KB manifest profile does not record an embedding model.",
                recommendation="Record embedding_model in the build profile or manifest for cross-KB health comparisons.",
            )
        )
    if embedding_check["rebuild_or_reparse_required"]:
        expected = ", ".join(expected_embedding_models)
        risks.append(
            _issue(
                severity="warning",
                code="embedding_model_rebuild_required",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=(
                    f"KB manifest records embedding model {embedding_model!r}, "
                    f"but the expected embedding model is {expected!r}."
                ),
                recommendation=(
                    "Rebuild or re-parse this KB through normal RAGFlow/API flow after changing "
                    "embedding models; do not mix vector spaces in route or fusion evaluation."
                ),
            )
        )
    if not parse["available"]:
        risks.append(
            _issue(
                severity="info",
                code="parse_report_missing",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message="No parse-report sidecar was supplied for this KB.",
                recommendation="Run ragflow-kb-build parse-report with exported document status/log sidecars for deeper analysis.",
            )
        )
    if parse["failed_document_count"] > 0 or parse["pending_document_count"] > 0:
        risks.append(
            _issue(
                severity="warning",
                code="stale_or_failed_parse_state",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=(
                    f"Parse health has {parse['failed_document_count']} failed and "
                    f"{parse['pending_document_count']} pending/unknown document(s)."
                ),
                recommendation="Refresh document status via RAGFlow UI/API and rerun parse-report before activating routes.",
            )
        )
    if parse["zero_chunk_document_count"] > 0:
        risks.append(
            _issue(
                severity="warning",
                code="zero_chunk_documents",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=f"{parse['zero_chunk_document_count']} document(s) report zero chunks.",
                recommendation="Check Markdown content and parser profile; keep remediation at API/config level.",
            )
        )
    if parse.get("chunk_consistency_mismatch_count", 0) > 0 or parse.get("chunk_mismatch_count", 0) > 0:
        risks.append(
            _issue(
                severity="warning",
                code="stale_count_fields",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message="Parse report found chunk-count mismatches or stale detail/list count fields.",
                recommendation="Export fresh manifest/detail/list sidecars before using counts for benchmarking.",
            )
        )
    if parse["expensive_setting_count"] > 0 or parse["parse_log_error_count"] > 0:
        risks.append(
            _issue(
                severity="warning",
                code="parser_performance_review",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message="Parse report indicates expensive parser settings or parse-log errors.",
                recommendation="Tune parser_config/profile settings and rerun benchmarks; no private repair is performed.",
            )
        )
    if not activation["available"]:
        risks.append(
            _issue(
                severity="info",
                code="activation_plan_missing",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message="No activation-plan sidecar was supplied for route readiness.",
                recommendation="Run ragflow-kb-build activation-plan before treating this KB as route-ready.",
            )
        )
    elif activation["status"] != "ready":
        risks.append(
            _issue(
                severity="warning",
                code="route_activation_not_ready",
                dataset_id=dataset_id,
                kb_name=kb_name,
                message=f"Activation plan status is {activation['status']}.",
                recommendation="Resolve activation-plan blockers or review items in user-owned config before route activation.",
            )
        )

    status = "REVIEW" if risks else "PASS"
    return (
        {
            "dataset_id": dataset_id,
            "kb_name": kb_name,
            "kb_manifest": str(kb_manifest_path),
            "status": status,
            "document_count": document_count,
            "declared_chunk_count": chunk_total,
            "embedding_model": embedding_model,
            "embedding_model_check": embedding_check,
            "parse": parse,
            "route_activation": activation,
            "risk_count": len(risks),
            "risks": risks,
        },
        risks,
    )


def _embedding_distribution(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        model = str(item.get("embedding_model") or "unknown")
        grouped[model].append(str(item.get("dataset_id") or ""))
    return [
        {"model": model, "kb_count": len(dataset_ids), "dataset_ids": sorted(dataset_ids)}
        for model, dataset_ids in sorted(grouped.items())
    ]


def _global_recommendations(issues: Iterable[Mapping[str, Any]]) -> list[str]:
    codes = {str(issue.get("code") or "") for issue in issues}
    recommendations: list[str] = []
    if "embedding_model_unknown" in codes or len([code for code in codes if code == "mixed_embedding_models"]) > 0:
        recommendations.append("Keep embedding_model recorded in build profiles before comparing or fusing KBs.")
    if "embedding_model_rebuild_required" in codes:
        recommendations.append(
            "After changing embedding models, rebuild or re-parse affected KBs before relying on vector search metrics."
        )
    if "stale_or_failed_parse_state" in codes or "zero_chunk_documents" in codes:
        recommendations.append("Refresh read-only document status sidecars and rerun parse-report before route activation.")
    if "parser_performance_review" in codes:
        recommendations.append("Prefer parser_config/profile tuning and benchmark comparison over private queue or database repair.")
    if "activation_plan_missing" in codes or "route_activation_not_ready" in codes:
        recommendations.append("Use activation-plan and route tests as sidecars before editing user-owned routing config.")
    if "stale_count_fields" in codes:
        recommendations.append("Treat mismatched count fields as stale until fresh manifest/detail/list sidecars agree.")
    if not recommendations:
        recommendations.append("Keep this health report beside parse-report, activation-plan, and validation artifacts.")
    return recommendations


def create_kb_health_report(
    *,
    kb_manifest_paths: Iterable[str | Path],
    parse_report_paths: Iterable[str | Path] | None = None,
    activation_plan_paths: Iterable[str | Path] | None = None,
    min_documents: int = 1,
    min_chunks: int = 1,
    expected_embedding_models: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Create an offline aggregate KB health report from local sidecars."""

    manifest_path_list = list(kb_manifest_paths)
    if not manifest_path_list:
        raise HealthReportError("at least one --kb-manifest is required")
    if min_documents < 0:
        raise HealthReportError("--min-documents must be non-negative")
    if min_chunks < 0:
        raise HealthReportError("--min-chunks must be non-negative")

    expected_models = _normalize_expected_models(expected_embedding_models)
    parse_reports = _load_schema_sidecars(parse_report_paths or [], expected_schema=PARSE_REPORT_SCHEMA, label="parse report")
    activation_plans = _load_schema_sidecars(
        activation_plan_paths or [],
        expected_schema=KB_ACTIVATION_PLAN_SCHEMA,
        label="activation plan",
    )
    parse_by_dataset = _index_by_dataset_id(parse_reports)
    activation_by_dataset = _index_by_dataset_id(activation_plans)

    kb_items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for manifest_path in manifest_path_list:
        kb_manifest = _load_kb_manifest(manifest_path)
        item, item_issues = _kb_health_item(
            kb_manifest_path=manifest_path,
            kb_manifest=kb_manifest,
            parse_report=parse_by_dataset.get(kb_manifest.dataset.id),
            activation_plan=activation_by_dataset.get(kb_manifest.dataset.id),
            min_documents=min_documents,
            min_chunks=min_chunks,
            expected_embedding_models=expected_models,
        )
        kb_items.append(item)
        issues.extend(item_issues)

    embedding_distribution = _embedding_distribution(kb_items)
    known_models = [item for item in embedding_distribution if item["model"] != "unknown"]
    if len(known_models) > 1:
        issues.append(
            _issue(
                severity="info",
                code="mixed_embedding_models",
                message="Selected KBs use more than one embedding model.",
                recommendation="Confirm cross-KB fusion/routing expectations before comparing scores across models.",
            )
        )

    route_counts = Counter(str(item.get("route_activation", {}).get("status") or "unknown") for item in kb_items)
    issue_counts = Counter(str(issue.get("severity") or "info") for issue in issues)
    status = "FAIL" if issue_counts.get("error", 0) else "REVIEW" if issues else "PASS"
    return {
        "ok": not issue_counts.get("error", 0),
        "schema": HEALTH_REPORT_SCHEMA,
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
        "inputs": {
            "kb_manifests": [str(path) for path in manifest_path_list],
            "parse_reports": [str(path) for path in (parse_report_paths or [])],
            "activation_plans": [str(path) for path in (activation_plan_paths or [])],
            "min_documents": min_documents,
            "min_chunks": min_chunks,
            "expected_embedding_models": expected_models,
        },
        "summary": {
            "kb_count": len(kb_items),
            "document_count": sum(_as_int(item.get("document_count")) or 0 for item in kb_items),
            "declared_chunk_count": sum(_as_int(item.get("declared_chunk_count")) or 0 for item in kb_items),
            "visual_document_count": sum(_as_int(item.get("parse", {}).get("visual_document_count")) or 0 for item in kb_items),
            "visual_chunk_count": sum(_as_int(item.get("parse", {}).get("visual_chunk_count")) or 0 for item in kb_items),
            "thumbnail_document_count": sum(
                _as_int(item.get("parse", {}).get("thumbnail_document_count")) or 0 for item in kb_items
            ),
            "vlm_observed_document_count": sum(
                _as_int(item.get("parse", {}).get("vlm_observed_document_count")) or 0 for item in kb_items
            ),
            "zero_document_kb_count": sum(1 for item in kb_items if (_as_int(item.get("document_count")) or 0) == 0),
            "zero_chunk_kb_count": sum(1 for item in kb_items if (_as_int(item.get("declared_chunk_count")) or 0) == 0),
            "stale_parse_kb_count": sum(
                1
                for item in kb_items
                if item.get("parse", {}).get("failed_document_count", 0)
                or item.get("parse", {}).get("pending_document_count", 0)
            ),
            "route_activation": dict(sorted(route_counts.items())),
            "embedding_model_count": len(known_models),
            "unknown_embedding_model_count": sum(1 for item in kb_items if item.get("embedding_model") == "unknown"),
            "embedding_model_rebuild_required_kb_count": sum(
                1
                for item in kb_items
                if item.get("embedding_model_check", {}).get("rebuild_or_reparse_required")
            ),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "embedding_model_distribution": embedding_distribution,
        "knowledge_bases": kb_items,
        "issues": issues,
        "recommendations": _global_recommendations(issues),
    }


def _md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_kb_health_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary for a KB health report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    distribution = report.get("embedding_model_distribution", [])
    knowledge_bases = report.get("knowledge_bases", [])
    issues = report.get("issues", [])
    recommendations = report.get("recommendations", [])
    inputs = report.get("inputs", {}) if isinstance(report.get("inputs"), Mapping) else {}
    expected_models = inputs.get("expected_embedding_models", [])

    lines = [
        "# RAGFlow KB Health Report",
        "",
        f"- Schema: `{report.get('schema', HEALTH_REPORT_SCHEMA)}`",
        f"- Status: `{report.get('status', 'UNKNOWN')}`",
        f"- KBs: {summary.get('kb_count', 0)}",
        f"- Documents: {summary.get('document_count', 0)}",
        f"- Declared chunks: {summary.get('declared_chunk_count', 0)}",
        f"- Visual documents: {summary.get('visual_document_count', 0)}",
        f"- Visual chunks: {summary.get('visual_chunk_count', 0)}",
        f"- Visual thumbnails: {summary.get('thumbnail_document_count', 0)}",
        f"- VLM-observed documents: {summary.get('vlm_observed_document_count', 0)}",
        f"- Mutation: `{report.get('mutation', 'none')}`",
        "",
        "## Knowledge Bases",
        "",
        "| KB | Dataset | Status | Docs | Chunks | Embedding | Route | Risks |",
        "| --- | --- | --- | ---: | ---: | --- | --- | ---: |",
    ]
    if isinstance(knowledge_bases, list):
        for item in knowledge_bases:
            if not isinstance(item, Mapping):
                continue
            route = item.get("route_activation", {}) if isinstance(item.get("route_activation"), Mapping) else {}
            lines.append(
                "| "
                f"{_md_escape(item.get('kb_name'))} | "
                f"{_md_escape(item.get('dataset_id'))} | "
                f"{_md_escape(item.get('status'))} | "
                f"{_md_escape(item.get('document_count'))} | "
                f"{_md_escape(item.get('declared_chunk_count'))} | "
                f"{_md_escape(item.get('embedding_model'))} | "
                f"{_md_escape(route.get('status'))} | "
                f"{_md_escape(item.get('risk_count'))} |"
            )

    lines.extend(["", "## Embedding Models", ""])
    if isinstance(expected_models, list) and expected_models:
        lines.append(f"- Expected: {', '.join(f'`{model}`' for model in expected_models)}")
        lines.append(f"- Rebuild/reparse required: {summary.get('embedding_model_rebuild_required_kb_count', 0)} KB(s)")
    if isinstance(distribution, list) and distribution:
        for item in distribution:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- `{item.get('model')}`: {item.get('kb_count')} KB(s) "
                f"({', '.join(str(value) for value in item.get('dataset_ids', []) if value)})"
            )
    else:
        lines.append("- No embedding model data.")

    lines.extend(["", "## Issues", ""])
    if isinstance(issues, list) and issues:
        for issue in issues[:35]:
            if not isinstance(issue, Mapping):
                continue
            target = f" `{issue.get('kb_name') or issue.get('dataset_id')}`" if issue.get("kb_name") or issue.get("dataset_id") else ""
            lines.append(
                f"- `{issue.get('severity', 'info')}` `{issue.get('code', 'issue')}`{target}: "
                f"{issue.get('message', '')}"
            )
        if len(issues) > 35:
            lines.append(f"- ... {len(issues) - 35} additional issues omitted.")
    else:
        lines.append("- No issues found.")

    lines.extend(["", "## Recommendations", ""])
    if isinstance(recommendations, list):
        for item in recommendations:
            lines.append(f"- {item}")

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
