"""Offline query-output cache key and invalidation reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Any

from .runtime_cache import CACHE_KEY_ALGORITHM, runtime_cache_digest, runtime_cache_secret_digest


QUERY_OUTPUT_CACHE_ENTRY_SCHEMA = "ragflow_query_output_cache_entry_v1"
QUERY_OUTPUT_CACHE_REPORT_SCHEMA = "ragflow_query_output_cache_report_v1"
QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA = "ragflow_query_output_cache_store_report_v1"
QUERY_OUTPUT_CACHE_OPERATION = "ragflow_query_output"
DEFAULT_QUERY_OUTPUT_CACHE_TTL_SECONDS = 3600.0


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


def _rounded(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _sanitize_namespace(value: str | None) -> str:
    namespace = str(value or "query-output").strip() or "query-output"
    namespace = "".join(char if char.isalnum() or char in "._-" else "_" for char in namespace)
    return namespace or "query-output"


def _cache_entry_path(cache_dir: str | Path, namespace: str, cache_key: str) -> Path:
    digest = cache_key.replace(":", "-")
    return Path(cache_dir) / namespace / f"{digest}.json"


def _cache_path_digest(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return runtime_cache_secret_digest(str(Path(path).expanduser()))


def _positive_ttl(value: float | int | str | None) -> float:
    if value is None:
        return DEFAULT_QUERY_OUTPUT_CACHE_TTL_SECONDS
    try:
        ttl = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("cache ttl seconds must be a number") from exc
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError("cache ttl seconds must be finite and greater than zero")
    return ttl


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


def _query_output_cache_entry(
    *,
    cache_key: str,
    field_fingerprints: Mapping[str, str],
    key_parts: Mapping[str, Any],
    query_output_digest: str,
    ttl_seconds: float,
    now_epoch: float,
) -> dict[str, Any]:
    return {
        "schema": QUERY_OUTPUT_CACHE_ENTRY_SCHEMA,
        "operation": QUERY_OUTPUT_CACHE_OPERATION,
        "cache_key": cache_key,
        "created_at_epoch": float(now_epoch),
        "ttl_seconds": float(ttl_seconds),
        "cache_key_algorithm": CACHE_KEY_ALGORITHM,
        "query_output_digest": query_output_digest,
        "field_fingerprints": dict(field_fingerprints),
        "key_parts": dict(key_parts),
    }


def _read_cache_entry(path: Path) -> tuple[Mapping[str, Any] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, "read_error"
    except json.JSONDecodeError:
        return None, "read_error"
    if not isinstance(payload, Mapping):
        return None, "invalid_entry"
    return payload, ""


def _write_cache_entry(path: Path, entry: Mapping[str, Any]) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return "write_error"
    return "stored"


def _delete_cache_entry(path: Path) -> str:
    try:
        path.unlink()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "invalidate_error"
    return "invalidated"


def _entry_lookup(
    *,
    path: Path,
    cache_key: str,
    ttl_seconds: float,
    now_epoch: float,
    field_fingerprints: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    counters = {
        "lookup_count": 1,
        "hit_count": 0,
        "miss_count": 0,
        "stale_count": 0,
        "invalid_entry_count": 0,
        "read_error_count": 0,
        "mismatch_count": 0,
    }
    lookup = {
        "cache_key": cache_key,
        "path_digest": _cache_path_digest(path),
        "status": "miss",
        "age_seconds": None,
        "changed_fields": [],
        "changed_field_count": 0,
    }
    if not path.exists():
        counters["miss_count"] = 1
        return lookup, counters
    entry, error = _read_cache_entry(path)
    if error:
        lookup["status"] = error
        counters["read_error_count" if error == "read_error" else "invalid_entry_count"] = 1
        return lookup, counters
    if entry is None or entry.get("schema") != QUERY_OUTPUT_CACHE_ENTRY_SCHEMA or entry.get("cache_key") != cache_key:
        lookup["status"] = "invalid_entry"
        counters["invalid_entry_count"] = 1
        return lookup, counters
    created_at_epoch = entry.get("created_at_epoch")
    if isinstance(created_at_epoch, bool) or not isinstance(created_at_epoch, (int, float)):
        lookup["status"] = "invalid_entry"
        counters["invalid_entry_count"] = 1
        return lookup, counters
    age_seconds = max(0.0, float(now_epoch) - float(created_at_epoch))
    lookup["age_seconds"] = _rounded(age_seconds)
    if age_seconds > ttl_seconds:
        lookup["status"] = "stale"
        counters["stale_count"] = 1
        return lookup, counters
    if field_fingerprints is not None:
        entry_fingerprints = _mapping(entry.get("field_fingerprints"))
        changed_fields = [
            field
            for field, fingerprint in sorted(field_fingerprints.items())
            if str(entry_fingerprints.get(field) or "") != str(fingerprint)
        ]
        if changed_fields:
            lookup["status"] = "mismatch"
            lookup["changed_fields"] = changed_fields
            lookup["changed_field_count"] = len(changed_fields)
            counters["mismatch_count"] = 1
            return lookup, counters
    lookup["status"] = "hit"
    counters["hit_count"] = 1
    return lookup, counters


def _empty_store_summary() -> dict[str, int]:
    return {
        "lookup_count": 0,
        "hit_count": 0,
        "miss_count": 0,
        "stale_count": 0,
        "invalid_entry_count": 0,
        "read_error_count": 0,
        "mismatch_count": 0,
        "would_write_count": 0,
        "write_count": 0,
        "write_error_count": 0,
        "would_invalidate_count": 0,
        "invalidate_count": 0,
        "invalidate_error_count": 0,
    }


def _query_output_cache_store_report(
    *,
    cache_key: str,
    field_fingerprints: Mapping[str, str],
    key_parts: Mapping[str, Any],
    query_output_digest: str,
    invalidation: Mapping[str, Any],
    baseline_report: Mapping[str, Any] | None,
    cache_dir: str | Path | None,
    cache_ttl_seconds: float | int | str | None,
    cache_namespace: str | None,
    dry_run: bool,
    cache_write: bool,
    cache_invalidate: bool,
    now_epoch: float,
) -> dict[str, Any]:
    ttl_seconds = _positive_ttl(cache_ttl_seconds)
    namespace = _sanitize_namespace(cache_namespace)
    summary = _empty_store_summary()
    if cache_dir is None:
        return {
            "ok": not (cache_write or cache_invalidate),
            "schema": QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA,
            "enabled": False,
            "dry_run": True,
            "namespace": namespace,
            "ttl_seconds": _rounded(ttl_seconds),
            "cache_key_algorithm": CACHE_KEY_ALGORITHM,
            "cache_dir_digest": None,
            "entry": {"status": "disabled", "cache_key": cache_key, "path_digest": None, "age_seconds": None},
            "baseline_entry": None,
            "write": {"status": "disabled", "reason": "cache directory not provided"},
            "invalidation": {
                "status": invalidation.get("status", "not_evaluated"),
                "changed_fields": list(invalidation.get("changed_fields", [])),
                "would_invalidate": False,
                "execution_status": "disabled",
            },
            "summary": summary,
        }

    cache_root = Path(cache_dir)
    entry_path = _cache_entry_path(cache_root, namespace, cache_key)
    entry, counters = _entry_lookup(
        path=entry_path,
        cache_key=cache_key,
        ttl_seconds=ttl_seconds,
        now_epoch=now_epoch,
        field_fingerprints=field_fingerprints,
    )
    for key, value in counters.items():
        summary[key] = summary.get(key, 0) + value

    needs_write = entry["status"] in {"miss", "stale", "invalid_entry", "read_error", "mismatch"}
    baseline_entry: dict[str, Any] | None = None
    would_invalidate = False
    baseline_path: Path | None = None
    baseline_cache_key = baseline_report.get("cache_key") if isinstance(baseline_report, Mapping) else None
    if baseline_cache_key and baseline_cache_key != cache_key and invalidation.get("status") == "invalidate":
        baseline_path = _cache_entry_path(cache_root, namespace, str(baseline_cache_key))
        baseline_entry, baseline_counters = _entry_lookup(
            path=baseline_path,
            cache_key=str(baseline_cache_key),
            ttl_seconds=ttl_seconds,
            now_epoch=now_epoch,
            field_fingerprints=None,
        )
        for key, value in baseline_counters.items():
            summary[key] = summary.get(key, 0) + value
        would_invalidate = baseline_entry["status"] in {"hit", "stale", "mismatch", "invalid_entry", "read_error"}
        if would_invalidate and dry_run:
            summary["would_invalidate_count"] = 1

    entry_payload = _query_output_cache_entry(
        cache_key=cache_key,
        field_fingerprints=field_fingerprints,
        key_parts=key_parts,
        query_output_digest=query_output_digest,
        ttl_seconds=ttl_seconds,
        now_epoch=now_epoch,
    )
    entry_digest = _digest(entry_payload, field="cache_entry")
    ok = True
    invalidate_execution_status = "not_needed"
    if would_invalidate:
        if dry_run:
            invalidate_execution_status = "would_invalidate"
        elif cache_invalidate and baseline_path is not None:
            invalidate_execution_status = _delete_cache_entry(baseline_path)
            if invalidate_execution_status == "invalidated":
                summary["invalidate_count"] = 1
            elif invalidate_execution_status == "invalidate_error":
                summary["invalidate_error_count"] = 1
                ok = False
        else:
            invalidate_execution_status = "not_requested"
            summary["would_invalidate_count"] = 1

    if needs_write and dry_run:
        summary["would_write_count"] = 1
    write_status = "would_store" if needs_write and dry_run else "not_needed"
    write_reason = "entry absent or stale" if needs_write else "fresh entry already present"
    if needs_write and not dry_run:
        if cache_write:
            write_status = _write_cache_entry(entry_path, entry_payload)
            if write_status == "stored":
                summary["write_count"] = 1
                write_reason = "metadata ledger entry stored"
            else:
                summary["write_error_count"] = 1
                write_reason = "metadata ledger entry could not be written"
                ok = False
        else:
            write_status = "not_requested"
            write_reason = "entry absent or stale but cache write was not requested"
            summary["would_write_count"] = 1
    return {
        "ok": ok,
        "schema": QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA,
        "enabled": True,
        "dry_run": dry_run,
        "namespace": namespace,
        "ttl_seconds": _rounded(ttl_seconds),
        "cache_key_algorithm": CACHE_KEY_ALGORITHM,
        "cache_dir_digest": _cache_path_digest(cache_root),
        "entry": entry,
        "baseline_entry": baseline_entry,
        "write": {
            "status": write_status,
            "reason": write_reason,
            "entry_schema": QUERY_OUTPUT_CACHE_ENTRY_SCHEMA,
            "entry_digest": entry_digest,
        },
        "invalidation": {
            "status": invalidation.get("status", "not_evaluated"),
            "changed_fields": list(invalidation.get("changed_fields", [])),
            "would_invalidate": would_invalidate,
            "execution_status": invalidate_execution_status,
            "baseline_cache_key": baseline_cache_key,
        },
        "summary": summary,
    }


def build_query_output_cache_report(
    query_payload: Mapping[str, Any],
    *,
    baseline_report: Mapping[str, Any] | None = None,
    config_version: str | None = None,
    route_config_version: str | None = None,
    cache_dir: str | Path | None = None,
    cache_ttl_seconds: float | int | str | None = None,
    cache_namespace: str | None = None,
    cache_dry_run: bool = True,
    cache_write: bool = False,
    cache_invalidate: bool = False,
    now_epoch: float | None = None,
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
    query_output_digest = _digest(query_payload, field="query_output")
    dry_run = False if cache_write or cache_invalidate else cache_dry_run
    store_report = _query_output_cache_store_report(
        cache_key=cache_key,
        field_fingerprints=fingerprints,
        key_parts=key_parts,
        query_output_digest=query_output_digest,
        invalidation=invalidation,
        baseline_report=baseline_report,
        cache_dir=cache_dir,
        cache_ttl_seconds=cache_ttl_seconds,
        cache_namespace=cache_namespace,
        dry_run=dry_run,
        cache_write=cache_write,
        cache_invalidate=cache_invalidate,
        now_epoch=float(time.time() if now_epoch is None else now_epoch),
    )
    ok = ok and bool(store_report.get("ok", True))
    return {
        "ok": ok,
        "schema": QUERY_OUTPUT_CACHE_REPORT_SCHEMA,
        "created_at": _utc_now(),
        "operation": QUERY_OUTPUT_CACHE_OPERATION,
        "cache_key_algorithm": CACHE_KEY_ALGORITHM,
        "cache_key": cache_key,
        "query_output_digest": query_output_digest,
        "key_parts": key_parts,
        "field_fingerprints": fingerprints,
        "invalidation": invalidation,
        "cache_store": store_report,
        "summary": {
            "dataset_count": len(key_parts["dataset_ids"]),
            "retrieval_query_count": key_parts["rewrite"]["retrieval_query_count"],
            "invalidation_status": invalidation["status"],
            "changed_field_count": invalidation["changed_field_count"],
            "cache_store_status": store_report["entry"]["status"],
            "cache_store_would_write_count": store_report["summary"]["would_write_count"],
            "cache_store_would_invalidate_count": store_report["summary"]["would_invalidate_count"],
            "cache_store_write_count": store_report["summary"]["write_count"],
            "cache_store_invalidate_count": store_report["summary"]["invalidate_count"],
        },
    }


def render_query_output_cache_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown query-output cache report."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    key_parts = report.get("key_parts") if isinstance(report.get("key_parts"), Mapping) else {}
    retrieval = key_parts.get("retrieval") if isinstance(key_parts.get("retrieval"), Mapping) else {}
    rewrite = key_parts.get("rewrite") if isinstance(key_parts.get("rewrite"), Mapping) else {}
    invalidation = report.get("invalidation") if isinstance(report.get("invalidation"), Mapping) else {}
    cache_store = report.get("cache_store") if isinstance(report.get("cache_store"), Mapping) else {}
    cache_store_summary = cache_store.get("summary") if isinstance(cache_store.get("summary"), Mapping) else {}
    cache_store_entry = cache_store.get("entry") if isinstance(cache_store.get("entry"), Mapping) else {}
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
        f"- cache_store_enabled: `{str(cache_store.get('enabled', False)).lower()}`",
        f"- cache_store_dry_run: `{str(cache_store.get('dry_run', True)).lower()}`",
        f"- cache_store_status: `{cache_store_entry.get('status', 'disabled')}`",
        f"- cache_store_would_write_count: `{cache_store_summary.get('would_write_count', 0)}`",
        f"- cache_store_would_invalidate_count: `{cache_store_summary.get('would_invalidate_count', 0)}`",
        f"- cache_store_write_count: `{cache_store_summary.get('write_count', 0)}`",
        f"- cache_store_invalidate_count: `{cache_store_summary.get('invalidate_count', 0)}`",
    ]
    if changed_fields:
        lines.extend(["", "## Changed Fields", ""])
        for field in changed_fields:
            lines.append(f"- `{field}`")
    return "\n".join(lines).rstrip() + "\n"
