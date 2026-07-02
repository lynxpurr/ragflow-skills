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
        "field_trial_records": {
            "record_count": 0,
        },
    }

    for root in roots:
        if not root.exists():
            findings.append({"check": "missing_run_root", "path": str(root), "message": "run root does not exist"})
        elif not (root.is_dir() or root.is_file()):
            findings.append({"check": "invalid_run_root", "path": str(root), "message": "run root must be a directory or JSON file"})

    for path in _iter_json_paths(roots):
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

        report_entry = {
            "path": relative_path,
            "schema": schema or None,
            "classes": sorted(classes),
            "ok": payload.get("ok") if isinstance(payload.get("ok"), bool) else None,
        }
        reports.append(report_entry)

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
        "",
        "## Gated Triggers",
        "",
    ]
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
