"""Small runtime metrics summaries for public skill reports."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping


RUNTIME_METRICS_SCHEMA = "ragflow_runtime_metrics_v1"


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


@dataclass
class RuntimeMetrics:
    """Collect a tiny, JSON-stable metrics block for one report operation."""

    operation: str
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    latency_samples_ms: list[float] = field(default_factory=list)

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

    def to_report(self) -> dict[str, Any]:
        latency = latency_summary_ms(self.latency_samples_ms)
        return {
            "schema": RUNTIME_METRICS_SCHEMA,
            "operation": self.operation,
            "summary": {
                "counter_count": len(self.counters),
                "gauge_count": len(self.gauges),
                "latency_sample_count": latency["sample_count"],
            },
            "counters": dict(sorted(self.counters.items())),
            "gauges": dict(sorted(self.gauges.items())),
            "latency_ms": latency,
        }


def build_runtime_metrics_summary(
    operation: str,
    *,
    counters: Mapping[str, int] | None = None,
    gauges: Mapping[str, float | int] | None = None,
    latency_samples_ms: Iterable[float | int] | None = None,
) -> dict[str, Any]:
    """Build a metrics report without exposing the collector object."""

    metrics = RuntimeMetrics(operation=operation)
    for name, value in (counters or {}).items():
        metrics.increment_counter(str(name), int(value))
    for name, value in (gauges or {}).items():
        metrics.set_gauge(str(name), value)
    for value in latency_samples_ms or []:
        metrics.observe_latency_ms(value)
    return metrics.to_report()
