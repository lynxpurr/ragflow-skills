"""Small runtime metrics summaries for public skill reports."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping


RUNTIME_METRICS_SCHEMA = "ragflow_runtime_metrics_v1"

_STAGE_ALIASES: dict[str, tuple[str, str]] = {
    "conversion": ("conversion", "conversion"),
    "convert": ("conversion", "conversion"),
    "document_conversion": ("conversion", "conversion"),
    "mineru_conversion": ("conversion", "conversion"),
    "backend_conversion": ("conversion", "conversion"),
    "postprocess": ("postprocess", "conversion"),
    "post_process": ("postprocess", "conversion"),
    "postprocessing": ("postprocess", "conversion"),
    "package": ("packaging", "conversion"),
    "packaging": ("packaging", "conversion"),
    "rich_handoff_package": ("packaging", "conversion"),
    "formal_handoff_manifest": ("packaging", "conversion"),
    "hints": ("hint_generation", "conversion"),
    "hint_generation": ("hint_generation", "conversion"),
    "retrieval_hints": ("hint_generation", "conversion"),
    "asset": ("asset_planning", "conversion"),
    "asset_upload_plan": ("asset_planning", "kb_build"),
    "asset_planning": ("asset_planning", "kb_build"),
    "ingest_plan": ("asset_planning", "kb_build"),
    "local_asset_copy": ("asset_planning", "conversion"),
    "remote_asset_materialization": ("asset_planning", "conversion"),
    "dataset_create": ("dataset_create", "kb_build"),
    "create_dataset": ("dataset_create", "kb_build"),
    "markdown_upload": ("markdown_upload", "kb_build"),
    "upload_markdown": ("markdown_upload", "kb_build"),
    "image_upload": ("image_upload", "kb_build"),
    "visual_upload": ("image_upload", "kb_build"),
    "trigger_parse": ("parse_trigger", "kb_build"),
    "parse_trigger": ("parse_trigger", "kb_build"),
    "wait_parse": ("parse_wait", "kb_build"),
    "parse_wait": ("parse_wait", "kb_build"),
    "image_parse_wait": ("parse_wait", "kb_build"),
    "validation": ("validation", "validation"),
    "validate": ("validation", "validation"),
    "benchmark_validation": ("validation", "validation"),
    "query": ("query", "query"),
    "ask": ("query", "query"),
    "retrieval": ("retrieval", "query"),
    "retrieve": ("retrieval", "query"),
    "cleanup": ("cleanup", "cleanup"),
    "cleanup_plan": ("cleanup", "cleanup"),
    "preview_cleanup_plan": ("cleanup", "cleanup"),
    "delete_dataset": ("cleanup", "cleanup"),
}


def _rounded(value: float | int) -> float:
    return round(float(value), 3)


def _numeric_samples(values: Iterable[float | int]) -> list[float]:
    samples: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            sample = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(sample) and sample >= 0:
            samples.append(sample)
    return samples


def latency_summary_ms(samples: Iterable[float | int]) -> dict[str, Any]:
    """Return a deterministic nearest-rank latency summary in milliseconds."""

    values = sorted(_numeric_samples(samples))
    if not values:
        return {
            "sample_count": 0,
            "min": None,
            "max": None,
            "average": None,
            "p50": None,
            "p95": None,
            "p99": None,
        }

    def percentile(percent: float) -> float:
        rank = math.ceil((percent / 100.0) * len(values))
        index = max(0, min(len(values) - 1, rank - 1))
        return _rounded(values[index])

    return {
        "sample_count": len(values),
        "min": _rounded(values[0]),
        "max": _rounded(values[-1]),
        "average": _rounded(sum(values) / len(values)),
        "p50": percentile(50.0),
        "p95": percentile(95.0),
        "p99": percentile(99.0),
    }


def throughput_summary(*, item_count: int, duration_ms: float | int, unit: str) -> dict[str, Any]:
    """Return a JSON-stable throughput summary for a bounded operation stage."""

    try:
        count = int(item_count)
    except (TypeError, ValueError):
        count = 0
    count = max(0, count)
    duration_samples = _numeric_samples([duration_ms])
    duration_value = _rounded(duration_samples[0]) if duration_samples else 0.0
    unit_label = str(unit).strip() or "item"
    items_per_second: float | None = None
    ms_per_item: float | None = None
    if count > 0 and duration_value > 0:
        items_per_second = _rounded(count / (duration_value / 1000.0))
        ms_per_item = _rounded(duration_value / count)
    return {
        "unit": unit_label,
        "item_count": count,
        "duration_ms": duration_value,
        "items_per_second": items_per_second,
        "ms_per_item": ms_per_item,
    }


def _normalize_throughput_stage(summary: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(summary, Mapping):
        return None
    return throughput_summary(
        item_count=summary.get("item_count", 0),
        duration_ms=summary.get("duration_ms", 0),
        unit=str(summary.get("unit") or "item"),
    )


def _stage_alias(stage: str, operation: str | None = None) -> tuple[str, str]:
    for candidate in (stage, operation or ""):
        key = str(candidate or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key in _STAGE_ALIASES:
            return _STAGE_ALIASES[key]
    key = str(stage or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return ("unspecified", "other")
    return (key, "other")


def _coerce_duration_ms(value: Any) -> float | None:
    samples = _numeric_samples([value])
    if not samples:
        return None
    return _rounded(samples[0])


def normalize_stage_timing(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one operation timing while preserving the producer's stage label."""

    stage = str(item.get("stage") or "unspecified").strip() or "unspecified"
    operation = str(item.get("operation") or stage).strip() or stage
    standard_stage, category = _stage_alias(stage, operation)
    included_in_stage = item.get("included_in_stage")
    if standard_stage == "retrieval" and str(included_in_stage or "").strip() == "query":
        standard_stage = "query"
    duration_ms = _coerce_duration_ms(item.get("duration_ms"))
    timing_source = str(item.get("timing_source") or "monotonic_clock").strip() or "monotonic_clock"
    normalized: dict[str, Any] = {
        "stage": stage,
        "standard_stage": standard_stage,
        "category": category,
        "operation": operation,
        "status": str(item.get("status") or "unknown"),
        "duration_ms": duration_ms,
        "timing_source": timing_source,
        "counts_toward_total": bool(item.get("counts_toward_total"))
        if "counts_toward_total" in item
        else duration_ms is not None,
    }
    for key in (
        "backend",
        "source_path",
        "detail",
        "included_in_stage",
        "failure_class",
        "document_id",
        "document_count",
        "item_count",
        "batch_index",
    ):
        value = item.get(key)
        if value not in (None, ""):
            normalized[key] = value
    if item.get("derived_from_attempt"):
        normalized["derived_from_attempt"] = True
    return normalized


def _normalize_stage_timings(items: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    timings: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, Mapping):
            timings.append(normalize_stage_timing(item))
    return timings


def _stage_timing_summary(stage_timings: list[Mapping[str, Any]]) -> dict[str, Any]:
    timed_count = sum(1 for item in stage_timings if item.get("duration_ms") is not None)
    known_duration_ms = _rounded(
        sum(
            float(item["duration_ms"])
            for item in stage_timings
            if item.get("duration_ms") is not None and item.get("counts_toward_total", True)
        )
    )
    by_standard_stage: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for item in stage_timings:
        standard_stage = str(item.get("standard_stage") or "unspecified")
        category = str(item.get("category") or "other")
        by_standard_stage[standard_stage] = by_standard_stage.get(standard_stage, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "stage_timing_count": len(stage_timings),
        "stage_timing_timed_count": timed_count,
        "stage_timing_not_measured_count": len(stage_timings) - timed_count,
        "stage_timing_known_duration_ms": known_duration_ms,
        "stage_timing_counts_by_standard_stage": dict(sorted(by_standard_stage.items())),
        "stage_timing_counts_by_category": dict(sorted(by_category.items())),
    }


@dataclass
class RuntimeMetrics:
    """Collect a tiny, JSON-stable metrics block for one report operation."""

    operation: str
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    latency_samples_ms: list[float] = field(default_factory=list)
    throughput: dict[str, dict[str, Any]] = field(default_factory=dict)
    stage_timings: list[dict[str, Any]] = field(default_factory=list)

    def increment_counter(self, name: str, value: int = 1) -> None:
        key = str(name).strip()
        if not key:
            return
        self.counters[key] = self.counters.get(key, 0) + int(value)

    def set_gauge(self, name: str, value: float | int) -> None:
        key = str(name).strip()
        if not key or isinstance(value, bool):
            return
        try:
            gauge = float(value)
        except (TypeError, ValueError):
            return
        if math.isfinite(gauge):
            self.gauges[key] = _rounded(gauge)

    def observe_latency_ms(self, value: float | int) -> None:
        for sample in _numeric_samples([value]):
            self.latency_samples_ms.append(sample)

    def set_throughput(self, name: str, summary: Mapping[str, Any]) -> None:
        key = str(name).strip()
        if not key:
            return
        normalized = _normalize_throughput_stage(summary)
        if normalized is not None:
            self.throughput[key] = normalized

    def record_stage_timing(self, item: Mapping[str, Any]) -> None:
        self.stage_timings.append(normalize_stage_timing(item))

    def to_report(self) -> dict[str, Any]:
        latency = latency_summary_ms(self.latency_samples_ms)
        summary = {
            "counter_count": len(self.counters),
            "gauge_count": len(self.gauges),
            "latency_sample_count": latency["sample_count"],
            "throughput_stage_count": len(self.throughput),
            **_stage_timing_summary(self.stage_timings),
        }
        report = {
            "schema": RUNTIME_METRICS_SCHEMA,
            "operation": self.operation,
            "summary": summary,
            "counters": dict(sorted(self.counters.items())),
            "gauges": dict(sorted(self.gauges.items())),
            "latency_ms": latency,
        }
        if self.throughput:
            report["throughput"] = dict(sorted(self.throughput.items()))
        if self.stage_timings:
            report["stage_timings"] = list(self.stage_timings)
        return report


def build_runtime_metrics_summary(
    operation: str,
    *,
    counters: Mapping[str, int] | None = None,
    gauges: Mapping[str, float | int] | None = None,
    latency_samples_ms: Iterable[float | int] | None = None,
    throughput: Mapping[str, Mapping[str, Any]] | None = None,
    stage_timings: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a metrics report without exposing the collector object."""

    metrics = RuntimeMetrics(operation=operation)
    for name, value in (counters or {}).items():
        metrics.increment_counter(str(name), int(value))
    for name, value in (gauges or {}).items():
        metrics.set_gauge(str(name), value)
    for value in latency_samples_ms or []:
        metrics.observe_latency_ms(value)
    for name, summary in (throughput or {}).items():
        metrics.set_throughput(str(name), summary)
    for item in _normalize_stage_timings(stage_timings):
        metrics.stage_timings.append(item)
    return metrics.to_report()


def attach_stage_timings_to_runtime_metrics(
    report: Mapping[str, Any],
    stage_timings: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a metrics report with normalized stage timings added to an existing report."""

    payload = dict(report)
    existing = payload.get("stage_timings")
    combined: list[Mapping[str, Any]] = []
    if isinstance(existing, list):
        combined.extend(item for item in existing if isinstance(item, Mapping))
    combined.extend(item for item in stage_timings if isinstance(item, Mapping))
    normalized = _normalize_stage_timings(combined)
    if normalized:
        payload["stage_timings"] = normalized
    summary = dict(payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {})
    summary.update(_stage_timing_summary(normalized))
    payload["summary"] = summary
    return payload
