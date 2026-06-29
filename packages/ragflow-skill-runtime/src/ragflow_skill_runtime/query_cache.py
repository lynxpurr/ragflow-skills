"""Offline query-output cache key and invalidation reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .runtime_cache import CACHE_KEY_ALGORITHM, runtime_cache_digest, runtime_cache_secret_digest


QUERY_OUTPUT_CACHE_REPORT_SCHEMA = "ragflow_query_output_cache_report_v1"
QUERY_OUTPUT_CACHE_OPERATION = "ragflow_query_output"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        return float(text) if text else None
    except ValueError:
        return None


def _digest(value: Any, *, field: str) -> str:
    return runtime_cache_digest(f"{QUERY_OUTPUT_CACHE_OPERATION}:{field}", {"value": value})


def _query_text(payload: Mapping[str, Any]) -> str:
    return str(payload.get("question") or payload.get("query") or "")


def _metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(payload.get("metadata"))


def _retrieval_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(payload)
    trace = _mapping(payload.get("trace"))
    trace_retrieval = _mapping(trace.get("retrieval"))
    return {
        "requested_mode": _string_or_none(metadata.get("requested_mode") or payload.get("mode")),
        "effective_mode": _string_or_none(payload.get("mode") or metadata.get("effective_mode")),
        "top_k": _int_or_none(metadata.get("top_k", trace_retrieval.get("top_k"))),
        "similarity_threshold": _float_or_none(
            metadata.get("similarity_threshold", trace_retrieval.get("similarity_threshold"))
        ),
    }


def _route_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = _metadata(payload)
    route = metadata.get("route")
    if isinstance(route, Mapping):
        return route
    route = payload.get("route")
    if isinstance(route, Mapping):
        return route
    trace = _mapping(payload.get("trace"))
    route = trace.get("route")
    return route if isinstance(route, Mapping) else {}


def _route_material(payload: Mapping[str, Any], *, route_config_version: str | None) -> dict[str, Any]:
    route = _route_payload(payload)
    selected = _mapping(route.get("selected"))
    return {
        "selected_dataset_id": _string_or_none(selected.get("dataset_id")),
        "selected_name": _string_or_none(selected.get("name")),
        "reason": _string_or_none(selected.get("reason")),
        "params": dict(_mapping(selected.get("params"))),
        "route_config_version": route_config_version,
    }


def _retrieval_queries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for item in payload.get("retrievals", []) if isinstance(payload.get("retrievals"), list) else []:
        if not isinstance(item, Mapping):
            continue
        query = _string_or_none(item.get("question") or item.get("query"))
        if query:
            queries.append(
                {
                    "id": _string_or_none(item.get("query_id") or item.get("id")),
                    "kind": _string_or_none(item.get("query_kind") or item.get("kind")),
                    "source": _string_or_none(item.get("source")),
                    "query": query,
                }
            )
    for plan_key in ("rewrite_plan", "agentic_plan"):
        plan = _mapping(payload.get(plan_key))
        for item in plan.get("retrieval_queries", []) if isinstance(plan.get("retrieval_queries"), list) else []:
            if not isinstance(item, Mapping):
                continue
            query = _string_or_none(item.get("query"))
            if query:
                queries.append(
                    {
                        "id": _string_or_none(item.get("id")),
                        "kind": _string_or_none(item.get("kind")),
                        "source": _string_or_none(item.get("source")),
                        "query": query,
                    }
                )
    return queries


def _rewrite_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(payload)
    rewrite_mode = _string_or_none(metadata.get("rewrite"))
    queries = _retrieval_queries(payload)
    return {
        "mode": rewrite_mode,
        "retrieval_queries": queries,
    }


def _fusion_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(payload)
    fusion_payload = _mapping(payload.get("fusion"))
    return {
        "mode": _string_or_none(metadata.get("fusion") or fusion_payload.get("mode")),
        "rrf_k": _int_or_none(metadata.get("rrf_k", fusion_payload.get("rrf_k"))),
        "max_per_source": _int_or_none(metadata.get("max_per_source", fusion_payload.get("max_per_source"))),
    }


def _key_material(
    payload: Mapping[str, Any],
    *,
    config_version: str | None,
    route_config_version: str | None,
) -> dict[str, Any]:
    return {
        "schema": QUERY_OUTPUT_CACHE_REPORT_SCHEMA,
        "question": _query_text(payload),
        "dataset_ids": _string_list(payload.get("dataset_ids")),
        "retrieval": _retrieval_material(payload),
        "route": _route_material(payload, route_config_version=route_config_version),
        "rewrite": _rewrite_material(payload),
        "fusion": _fusion_material(payload),
        "config": {"config_version": config_version},
    }


def _safe_key_parts(material: Mapping[str, Any]) -> dict[str, Any]:
    question = str(material.get("question") or "")
    dataset_ids = _string_list(material.get("dataset_ids"))
    route = _mapping(material.get("route"))
    rewrite = _mapping(material.get("rewrite"))
    rewrite_queries = rewrite.get("retrieval_queries") if isinstance(rewrite.get("retrieval_queries"), list) else []
    rewrite_query_text = "\n".join(str(item.get("query") or "") for item in rewrite_queries if isinstance(item, Mapping))
    route_name = _string_or_none(route.get("selected_name"))
    route_reason = _string_or_none(route.get("reason"))
    return {
        "question": {
            "present": bool(question),
            "char_count": len(question),
            "digest": runtime_cache_secret_digest(question),
        },
        "dataset_ids": dataset_ids,
        "dataset_ids_digest": _digest(dataset_ids, field="dataset_ids"),
        "retrieval": dict(_mapping(material.get("retrieval"))),
        "route": {
            "selected_dataset_id": _string_or_none(route.get("selected_dataset_id")),
            "selected_name_digest": runtime_cache_secret_digest(route_name),
            "reason": {
                "present": bool(route_reason),
                "char_count": len(route_reason or ""),
                "digest": runtime_cache_secret_digest(route_reason),
            },
            "params_digest": _digest(route.get("params"), field="route_params"),
            "route_config_version": _string_or_none(route.get("route_config_version")),
        },
        "rewrite": {
            "mode": _string_or_none(rewrite.get("mode")),
            "retrieval_query_count": len(rewrite_queries),
            "retrieval_query_digest": runtime_cache_secret_digest(rewrite_query_text),
        },
        "fusion": dict(_mapping(material.get("fusion"))),
        "config": dict(_mapping(material.get("config"))),
    }


def _field_fingerprints(material: Mapping[str, Any]) -> dict[str, str]:
    return {
        "question": _digest(material.get("question"), field="question"),
        "dataset_ids": _digest(material.get("dataset_ids"), field="dataset_ids"),
        "retrieval": _digest(material.get("retrieval"), field="retrieval"),
        "route": _digest(material.get("route"), field="route"),
        "rewrite": _digest(material.get("rewrite"), field="rewrite"),
        "fusion": _digest(material.get("fusion"), field="fusion"),
        "config": _digest(material.get("config"), field="config"),
    }


def _invalidation_report(cache_key: str, fingerprints: Mapping[str, str], baseline_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if baseline_report is None:
        return {
            "status": "not_evaluated",
            "baseline_provided": False,
            "baseline_cache_key": None,
            "changed_fields": [],
            "changed_field_count": 0,
            "reason": "no baseline report provided",
        }
    if baseline_report.get("schema") != QUERY_OUTPUT_CACHE_REPORT_SCHEMA:
        return {
            "status": "invalid_baseline",
            "baseline_provided": True,
            "baseline_cache_key": baseline_report.get("cache_key"),
            "changed_fields": [],
            "changed_field_count": 0,
            "reason": "baseline report schema is not ragflow_query_output_cache_report_v1",
        }
    baseline_fingerprints = _mapping(baseline_report.get("field_fingerprints"))
    changed_fields = [
        field
        for field, fingerprint in sorted(fingerprints.items())
        if str(baseline_fingerprints.get(field) or "") != str(fingerprint)
    ]
    baseline_cache_key = baseline_report.get("cache_key")
    status = "fresh" if baseline_cache_key == cache_key and not changed_fields else "invalidate"
    reason = "cache key matches baseline" if status == "fresh" else "cache key or key material changed"
    return {
        "status": status,
        "baseline_provided": True,
        "baseline_cache_key": baseline_cache_key,
        "changed_fields": changed_fields,
        "changed_field_count": len(changed_fields),
        "reason": reason,
    }


def build_query_output_cache_report(
    query_payload: Mapping[str, Any],
    *,
    baseline_report: Mapping[str, Any] | None = None,
    config_version: str | None = None,
    route_config_version: str | None = None,
) -> dict[str, Any]:
    """Build an offline cache-key and invalidation report for saved query output."""

    material = _key_material(
        query_payload,
        config_version=config_version,
        route_config_version=route_config_version,
    )
    cache_key = runtime_cache_digest(QUERY_OUTPUT_CACHE_OPERATION, material)
    fingerprints = _field_fingerprints(material)
    invalidation = _invalidation_report(cache_key, fingerprints, baseline_report)
    ok = invalidation["status"] != "invalid_baseline"
    key_parts = _safe_key_parts(material)
    return {
        "ok": ok,
        "schema": QUERY_OUTPUT_CACHE_REPORT_SCHEMA,
        "created_at": _utc_now(),
        "operation": QUERY_OUTPUT_CACHE_OPERATION,
        "cache_key_algorithm": CACHE_KEY_ALGORITHM,
        "cache_key": cache_key,
        "key_parts": key_parts,
        "field_fingerprints": fingerprints,
        "invalidation": invalidation,
        "summary": {
            "dataset_count": len(key_parts["dataset_ids"]),
            "retrieval_query_count": key_parts["rewrite"]["retrieval_query_count"],
            "invalidation_status": invalidation["status"],
            "changed_field_count": invalidation["changed_field_count"],
        },
    }


def render_query_output_cache_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown query-output cache report."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    key_parts = report.get("key_parts") if isinstance(report.get("key_parts"), Mapping) else {}
    retrieval = key_parts.get("retrieval") if isinstance(key_parts.get("retrieval"), Mapping) else {}
    rewrite = key_parts.get("rewrite") if isinstance(key_parts.get("rewrite"), Mapping) else {}
    invalidation = report.get("invalidation") if isinstance(report.get("invalidation"), Mapping) else {}
    changed_fields = invalidation.get("changed_fields") if isinstance(invalidation.get("changed_fields"), list) else []
    lines = [
        "# RAGFlow Query Output Cache Report",
        "",
        f"- schema: `{report.get('schema', QUERY_OUTPUT_CACHE_REPORT_SCHEMA)}`",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- cache_key: `{report.get('cache_key', '')}`",
        f"- invalidation_status: `{summary.get('invalidation_status', 'not_evaluated')}`",
        f"- changed_field_count: `{summary.get('changed_field_count', 0)}`",
        f"- dataset_count: `{summary.get('dataset_count', 0)}`",
        f"- requested_mode: `{retrieval.get('requested_mode', '')}`",
        f"- top_k: `{retrieval.get('top_k', '')}`",
        f"- similarity_threshold: `{retrieval.get('similarity_threshold', '')}`",
        f"- retrieval_query_count: `{rewrite.get('retrieval_query_count', 0)}`",
    ]
    if changed_fields:
        lines.extend(["", "## Changed Fields", ""])
        for field in changed_fields:
            lines.append(f"- `{field}`")
    return "\n".join(lines).rstrip() + "\n"
