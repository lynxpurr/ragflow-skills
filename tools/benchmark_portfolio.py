#!/usr/bin/env python3
"""Build a public-safe benchmark evidence portfolio from explicit inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import configured_private_hosts_from_urls, sanitize_report_payload  # noqa: E402
from ragflow_skill_runtime.benchmark_governance import (  # noqa: E402
    BENCHMARK_MANIFEST_SCHEMA,
    BENCHMARK_PREFLIGHT_REPORT_SCHEMA,
    BENCHMARK_SELECTION_REPORT_SCHEMA,
    BENCHMARK_SOURCE_ATTRIBUTION_SCHEMA,
)
from ragflow_skill_runtime.validation import (  # noqa: E402
    ValidationError,
    load_benchmark_qrels,
    load_validation_queries,
)


CONFIG_SCHEMA = "ragflow_benchmark_portfolio_config_v1"
REPORT_SCHEMA = "ragflow_benchmark_portfolio_v1"
DECISION_TIERS = {"smoke", "exploratory", "promotion_candidate", "regression_baseline"}
ASSESSMENTS = {"ready", "ready_with_review", "blocked"}
_OPTIONAL_REPORT_KEYS = (
    "preflight_report",
    "validation_report",
    "retention_report",
    "citation_report",
    "field_trial_report",
)
_OBSERVED_METRICS = (
    "empty_result_rate",
    "wrong_document_rate",
    "tag_pollution_rate",
    "strict_chunk_recall_at_k",
    "expected_term_recall_at_k",
    "table_term_recall_at_k",
    "citation_support_rate",
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class BenchmarkPortfolioError(ValueError):
    """Raised when an explicit portfolio input contract is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkPortfolioError(f"{label} file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkPortfolioError(f"{label} is not valid JSON: {path.name}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _required_string(payload: Mapping[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkPortfolioError(f"{label} {key} must be a non-empty string")
    return value.strip()


def _string_list(payload: Mapping[str, Any], key: str, *, label: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise BenchmarkPortfolioError(f"{label} {key} must be a non-empty list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BenchmarkPortfolioError(f"{label} {key} must contain only non-empty strings")
        items.append(item.strip())
    return sorted(dict.fromkeys(items))


def _resolve_path(base: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkPortfolioError(f"{label} path must be a non-empty string")
    path = Path(value.strip())
    return path if path.is_absolute() else base / path


def _manifest_artifact_path(manifest_path: Path, manifest: Mapping[str, Any], key: str) -> Path | None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise BenchmarkPortfolioError("manifest artifacts must be an object")
    value = artifacts.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    return path if path.is_absolute() else manifest_path.parent / path


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _collect_urls(value: Any) -> list[str]:
    urls: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, str):
            urls.update(_URL_RE.findall(item))
        elif isinstance(item, Mapping):
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)
    return sorted(urls)


def _query_type(metadata: Mapping[str, Any]) -> str:
    value = metadata.get("type") or metadata.get("query_type") or "default"
    return str(value).strip() or "default"


def _metadata_modalities(metadata: Mapping[str, Any]) -> set[str]:
    modalities: set[str] = set()
    for key in ("expected_modalities", "modalities", "expected_modality", "modality", "source_modality"):
        value = metadata.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and item.strip():
                modalities.add(item.strip().casefold())
    return modalities


def _is_table_numeric(query_type: str, modalities: set[str]) -> bool:
    normalized = query_type.casefold()
    return "table" in normalized or "numeric" in normalized or "table" in modalities


def _is_negative_unanswerable(metadata: Mapping[str, Any], query_type: str) -> bool:
    if metadata.get("negative_case") is True or metadata.get("unanswerable") is True:
        return True
    normalized = query_type.casefold()
    return any(marker in normalized for marker in ("negative", "unanswerable", "no_match", "distractor"))


def _qa_count(path: Path | None) -> int:
    if not path or not path.exists():
        return 0
    payload = _read_json(path, label="qa")
    if not isinstance(payload, Mapping):
        return 0
    items = payload.get("items")
    return len(items) if isinstance(items, list) else 0


def _validation_metrics(payload: Mapping[str, Any] | None) -> dict[str, float]:
    if not isinstance(payload, Mapping):
        return {}
    benchmark = payload.get("benchmark")
    if not isinstance(benchmark, Mapping):
        return {}
    metrics = benchmark.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    output: dict[str, float] = {}
    for key in _OBSERVED_METRICS:
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            output[key] = float(value)
    return output


def _digest_entry(path: Path, *, label: str) -> dict[str, str]:
    return {"artifact": label, "name": path.name, "sha256": _sha256(path)}


def _build_subset(
    config_dir: Path,
    raw_subset: Mapping[str, Any],
    *,
    index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    label = f"subset[{index}]"
    subset_id = _required_string(raw_subset, "id", label=label)
    dataset = _required_string(raw_subset, "dataset", label=label)
    license_label = _required_string(raw_subset, "license", label=label)
    decision_tier = _required_string(raw_subset, "decision_tier", label=label)
    if decision_tier not in DECISION_TIERS:
        raise BenchmarkPortfolioError(
            f"{label} decision_tier must be one of " + ", ".join(sorted(DECISION_TIERS))
        )
    sample_types = _string_list(raw_subset, "sample_types", label=label)
    manifest_path = _resolve_path(config_dir, raw_subset.get("manifest"), label=f"{label}.manifest")
    attribution_path = _resolve_path(
        config_dir, raw_subset.get("source_attribution"), label=f"{label}.source_attribution"
    )
    selection_path = _resolve_path(
        config_dir, raw_subset.get("selection_report"), label=f"{label}.selection_report"
    )
    manifest = _read_json(manifest_path, label=f"{label}.manifest")
    attribution = _read_json(attribution_path, label=f"{label}.source_attribution")
    selection = _read_json(selection_path, label=f"{label}.selection_report")
    if not isinstance(manifest, Mapping) or manifest.get("schema") != BENCHMARK_MANIFEST_SCHEMA:
        raise BenchmarkPortfolioError(f"{label} manifest schema must be {BENCHMARK_MANIFEST_SCHEMA}")
    if not isinstance(attribution, Mapping) or attribution.get("schema") != BENCHMARK_SOURCE_ATTRIBUTION_SCHEMA:
        raise BenchmarkPortfolioError(
            f"{label} source_attribution schema must be {BENCHMARK_SOURCE_ATTRIBUTION_SCHEMA}"
        )
    if not isinstance(selection, Mapping) or selection.get("schema") != BENCHMARK_SELECTION_REPORT_SCHEMA:
        raise BenchmarkPortfolioError(
            f"{label} selection_report schema must be {BENCHMARK_SELECTION_REPORT_SCHEMA}"
        )
    for key, explicit_path in (
        ("source_attribution", attribution_path),
        ("selection_report", selection_path),
    ):
        manifest_path_value = _manifest_artifact_path(manifest_path, manifest, key)
        if not manifest_path_value or not _same_path(manifest_path_value, explicit_path):
            raise BenchmarkPortfolioError(f"{label} manifest {key} does not match explicit {key}")
    if attribution.get("dataset_name") != dataset:
        raise BenchmarkPortfolioError(f"{label} dataset does not match source_attribution dataset_name")
    if attribution.get("license") != license_label:
        raise BenchmarkPortfolioError(f"{label} license does not match source_attribution license")
    if selection.get("subset_id") != subset_id:
        raise BenchmarkPortfolioError(f"{label} id does not match selection_report subset_id")
    if selection.get("decision_tier") != decision_tier:
        raise BenchmarkPortfolioError(f"{label} decision_tier does not match selection_report decision_tier")

    all_paths = [manifest_path, attribution_path, selection_path]
    input_payloads: list[Any] = [manifest, attribution, selection]
    optional_reports: dict[str, Mapping[str, Any]] = {}
    for key in _OPTIONAL_REPORT_KEYS:
        if key not in raw_subset:
            continue
        path = _resolve_path(config_dir, raw_subset.get(key), label=f"{label}.{key}")
        payload = _read_json(path, label=f"{label}.{key}")
        if not isinstance(payload, Mapping):
            raise BenchmarkPortfolioError(f"{label}.{key} must be a JSON object")
        optional_reports[key] = payload
        all_paths.append(path)
        input_payloads.append(payload)

    queries_path = _manifest_artifact_path(manifest_path, manifest, "queries")
    qrels_path = _manifest_artifact_path(manifest_path, manifest, "qrels")
    qa_path = _manifest_artifact_path(manifest_path, manifest, "qa")
    for path in (queries_path, qrels_path, qa_path):
        if path and path.exists():
            all_paths.append(path)

    blocking_reasons: list[str] = []
    review_reasons: list[str] = []
    queries = []
    qrels: dict[str, list[Any]] = {}
    if not queries_path or not queries_path.exists():
        blocking_reasons.append("missing_queries")
    else:
        try:
            queries = load_validation_queries(queries_path)
        except (ValidationError, OSError):
            blocking_reasons.append("invalid_queries")
    if not qrels_path or not qrels_path.exists():
        blocking_reasons.append("missing_qrels")
    else:
        try:
            qrels = load_benchmark_qrels(qrels_path)
        except (ValidationError, OSError):
            blocking_reasons.append("invalid_qrels")

    preflight = optional_reports.get("preflight_report")
    if preflight is None:
        review_reasons.append("missing_preflight")
    else:
        if preflight.get("schema") != BENCHMARK_PREFLIGHT_REPORT_SCHEMA:
            raise BenchmarkPortfolioError(
                f"{label}.preflight_report schema must be {BENCHMARK_PREFLIGHT_REPORT_SCHEMA}"
            )
        if preflight.get("ok") is not True:
            blocking_reasons.append("failed_preflight")
    validation = optional_reports.get("validation_report")
    if validation is None:
        review_reasons.append("missing_observed_validation")

    query_type_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()
    expected_term_query_count = 0
    expected_chunk_query_count = 0
    table_numeric_query_count = 0
    negative_unanswerable_query_count = 0
    for query in queries:
        query_type = _query_type(query.metadata)
        modalities = _metadata_modalities(query.metadata)
        query_type_counts[query_type] += 1
        modality_counts.update(modalities)
        if query.expected_terms:
            expected_term_query_count += 1
        if any(item.field == "expected_chunk" for item in qrels.get(query.id, [])):
            expected_chunk_query_count += 1
        if _is_table_numeric(query_type, modalities):
            table_numeric_query_count += 1
        if _is_negative_unanswerable(query.metadata, query_type):
            negative_unanswerable_query_count += 1

    source_hashes = attribution.get("source_hashes")
    approved_hashes = sorted(
        value for value in source_hashes if isinstance(value, str)
    ) if isinstance(source_hashes, list) else []
    artifact_digests = []
    seen_paths: set[Path] = set()
    for path in all_paths:
        resolved = path.resolve(strict=False)
        if resolved in seen_paths or not path.exists():
            continue
        seen_paths.add(resolved)
        artifact_digests.append(_digest_entry(path, label=path.name))
    artifact_digests.sort(key=lambda item: (item["artifact"], item["sha256"]))
    strength_status = None
    if isinstance(preflight, Mapping):
        strength = preflight.get("benchmark_strength")
        if isinstance(strength, Mapping) and isinstance(strength.get("status"), str):
            strength_status = strength["status"]
    subset_report = {
        "id": subset_id,
        "dataset": dataset,
        "license": license_label,
        "decision_tier": decision_tier,
        "sample_types": sample_types,
        "artifact_basenames": {
            "manifest": manifest_path.name,
            "source_attribution": attribution_path.name,
            "selection_report": selection_path.name,
            **{key: Path(str(raw_subset[key])).name for key in _OPTIONAL_REPORT_KEYS if key in raw_subset},
        },
        "input_digests": artifact_digests,
        "approved_source_hashes": approved_hashes,
        "counts": {
            "query_count": len(queries),
            "judged_query_count": len(qrels),
            "qrel_count": sum(len(items) for items in qrels.values()),
            "qa_count": _qa_count(qa_path),
        },
        "coverage": {
            "query_type_counts": dict(sorted(query_type_counts.items())),
            "modality_counts": dict(sorted(modality_counts.items())),
            "expected_term_query_count": expected_term_query_count,
            "expected_chunk_query_count": expected_chunk_query_count,
            "table_numeric_query_count": table_numeric_query_count,
            "negative_unanswerable_query_count": negative_unanswerable_query_count,
        },
        "preflight": {
            "provided": preflight is not None,
            "ok": preflight.get("ok") if isinstance(preflight, Mapping) else None,
            "benchmark_strength_status": strength_status,
        },
        "observed_metrics": _validation_metrics(validation),
        "blocking_reasons": sorted(set(blocking_reasons)),
        "review_reasons": sorted(set(review_reasons)),
    }
    context = {
        "paths": all_paths,
        "urls": sorted({url for payload in input_payloads for url in _collect_urls(payload)}),
    }
    return subset_report, context


def _aggregate_metrics(subsets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    subset_items = list(subsets)
    for metric in _OBSERVED_METRICS:
        values = {
            str(item.get("id")): float(item["observed_metrics"][metric])
            for item in subset_items
            if isinstance(item.get("observed_metrics"), Mapping) and metric in item["observed_metrics"]
        }
        if not values:
            continue
        output[metric] = {
            "available_subset_count": len(values),
            "average": round(sum(values.values()) / len(values), 6),
            "values_by_subset": dict(sorted(values.items())),
        }
    return output


def _build_benchmark_portfolio(config_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config_file = Path(config_path)
    config = _read_json(config_file, label="portfolio config")
    if not isinstance(config, Mapping):
        raise BenchmarkPortfolioError("portfolio config must be a JSON object")
    if config.get("schema") != CONFIG_SCHEMA:
        raise BenchmarkPortfolioError(f"portfolio config schema must be {CONFIG_SCHEMA}")
    portfolio_id = _required_string(config, "portfolio_id", label="portfolio config")
    raw_subsets = config.get("subsets")
    if not isinstance(raw_subsets, list) or not raw_subsets:
        raise BenchmarkPortfolioError("portfolio config subsets must be a non-empty list")
    subsets: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_subset in enumerate(raw_subsets):
        if not isinstance(raw_subset, Mapping):
            raise BenchmarkPortfolioError(f"subset[{index}] must be a JSON object")
        subset_id = _required_string(raw_subset, "id", label=f"subset[{index}]")
        if subset_id in seen_ids:
            raise BenchmarkPortfolioError(f"duplicate subset id: {subset_id}")
        seen_ids.add(subset_id)
        subset, context = _build_subset(config_file.parent, raw_subset, index=index)
        subsets.append(subset)
        contexts.append(context)

    blocking_reasons = sorted(
        {reason for subset in subsets for reason in subset.get("blocking_reasons", [])}
    )
    review_reasons = sorted(
        {reason for subset in subsets for reason in subset.get("review_reasons", [])}
    )
    if blocking_reasons:
        status = "blocked"
        reasons = blocking_reasons
    elif review_reasons:
        status = "ready_with_review"
        reasons = review_reasons
    else:
        status = "ready"
        reasons = []
    assert status in ASSESSMENTS

    query_type_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()
    decision_tier_counts: Counter[str] = Counter()
    sample_type_counts: Counter[str] = Counter()
    for subset in subsets:
        coverage = subset["coverage"]
        query_type_counts.update(coverage["query_type_counts"])
        modality_counts.update(coverage["modality_counts"])
        decision_tier_counts[str(subset["decision_tier"])] += 1
        sample_type_counts.update(subset["sample_types"])

    report = {
        "schema": REPORT_SCHEMA,
        "config_schema": CONFIG_SCHEMA,
        "created_at": _utc_now(),
        "ok": status != "blocked",
        "portfolio_id": portfolio_id,
        "summary": {
            "subset_count": len(subsets),
            "dataset_count": len({str(item["dataset"]) for item in subsets}),
            "query_count": sum(item["counts"]["query_count"] for item in subsets),
            "judged_query_count": sum(item["counts"]["judged_query_count"] for item in subsets),
            "qrel_count": sum(item["counts"]["qrel_count"] for item in subsets),
            "qa_count": sum(item["counts"]["qa_count"] for item in subsets),
            "decision_tier_counts": dict(sorted(decision_tier_counts.items())),
        },
        "coverage": {
            "query_type_counts": dict(sorted(query_type_counts.items())),
            "modality_counts": dict(sorted(modality_counts.items())),
            "sample_type_counts": dict(sorted(sample_type_counts.items())),
            "expected_term_query_count": sum(
                item["coverage"]["expected_term_query_count"] for item in subsets
            ),
            "expected_chunk_query_count": sum(
                item["coverage"]["expected_chunk_query_count"] for item in subsets
            ),
            "table_numeric_query_count": sum(
                item["coverage"]["table_numeric_query_count"] for item in subsets
            ),
            "negative_unanswerable_query_count": sum(
                item["coverage"]["negative_unanswerable_query_count"] for item in subsets
            ),
        },
        "metrics": _aggregate_metrics(subsets),
        "assessment": {
            "status": status,
            "reasons": reasons,
            "blocking_reasons": blocking_reasons,
            "review_reasons": review_reasons,
        },
        "safety": {
            "ragflow_calls": 0,
            "writes_live_ragflow": False,
            "script_owned_llm_calls": 0,
            "directory_discovery": False,
        },
        "subsets": subsets,
    }
    context = {
        "paths": [config_file, *[path for item in contexts for path in item["paths"]]],
        "urls": sorted({url for item in contexts for url in item["urls"]}),
    }
    return report, context


def build_benchmark_portfolio(config_path: str | Path) -> dict[str, Any]:
    """Build one portfolio from the explicit config without directory discovery."""

    report, _context = _build_benchmark_portfolio(config_path)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    assessment = report.get("assessment") if isinstance(report.get("assessment"), Mapping) else {}
    lines = [
        "# RAGFlow Benchmark Portfolio",
        "",
        f"- schema: `{report.get('schema', REPORT_SCHEMA)}`",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
        f"- portfolio: `{report.get('portfolio_id', '')}`",
        f"- assessment: `{assessment.get('status', 'unknown')}`",
        f"- subsets: `{summary.get('subset_count', 0)}`",
        f"- datasets: `{summary.get('dataset_count', 0)}`",
        f"- queries: `{summary.get('query_count', 0)}`",
        f"- judged queries: `{summary.get('judged_query_count', 0)}`",
        f"- qrels: `{summary.get('qrel_count', 0)}`",
        f"- grounded QA items: `{summary.get('qa_count', 0)}`",
        f"- expected-term queries: `{coverage.get('expected_term_query_count', 0)}`",
        f"- expected-chunk queries: `{coverage.get('expected_chunk_query_count', 0)}`",
        f"- table/numeric queries: `{coverage.get('table_numeric_query_count', 0)}`",
        f"- negative/unanswerable queries: `{coverage.get('negative_unanswerable_query_count', 0)}`",
    ]
    reasons = assessment.get("reasons") if isinstance(assessment.get("reasons"), list) else []
    lines.extend(["", "## Assessment Reasons", ""])
    lines.extend([f"- `{reason}`" for reason in reasons] or ["- none"])
    lines.extend(
        [
            "",
            "## Subsets",
            "",
            "| Subset | Dataset | Tier | Queries | Qrels | QA | Preflight |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for subset in report.get("subsets", []):
        if not isinstance(subset, Mapping):
            continue
        counts = subset.get("counts") if isinstance(subset.get("counts"), Mapping) else {}
        preflight = subset.get("preflight") if isinstance(subset.get("preflight"), Mapping) else {}
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                subset.get("id", ""),
                subset.get("dataset", ""),
                subset.get("decision_tier", ""),
                counts.get("query_count", 0),
                counts.get("qrel_count", 0),
                counts.get("qa_count", 0),
                preflight.get("benchmark_strength_status") or ("passed" if preflight.get("ok") else "missing"),
            )
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an explicit-input benchmark evidence portfolio")
    parser.add_argument("--config", required=True, help="Portfolio config JSON")
    parser.add_argument("--report-json", required=True, help="Public-safe portfolio JSON output")
    parser.add_argument("--report-md", required=True, help="Public-safe portfolio Markdown output")
    parser.add_argument("--redaction-report", required=True, help="Redaction sidecar output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report, context = _build_benchmark_portfolio(args.config)
        output_paths = [args.report_json, args.report_md, args.redaction_report]
        sanitized, redaction = sanitize_report_payload(
            report,
            private_hosts=configured_private_hosts_from_urls(context["urls"]),
            home_paths=[str(path) for path in context["paths"]],
            config_paths=[args.config, *output_paths],
        )
        _write_json(Path(args.report_json), sanitized)
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text(render_markdown(sanitized), encoding="utf-8")
        _write_json(Path(args.redaction_report), redaction)
        print(json.dumps(sanitized, ensure_ascii=False, indent=2))
        return 0 if sanitized.get("ok") else 1
    except (BenchmarkPortfolioError, OSError, ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
