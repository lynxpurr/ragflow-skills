"""Small runtime resilience helpers for public skill reports."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import math
import time
from typing import Any


RUNTIME_RETRY_TRACE_SCHEMA = "ragflow_runtime_retry_trace_v1"
DEFAULT_RETRYABLE_STATUSES = ("timeout", "unreachable", "error")


def _rounded(value: float | int) -> float:
    return round(float(value), 3)


@dataclass(frozen=True)
class RuntimeRetryPolicy:
    """Describe a bounded retry policy for a single read-only operation."""

    retry_budget: int = 1
    backoff_seconds: float = 0.0
    retryable_statuses: Sequence[str] = DEFAULT_RETRYABLE_STATUSES

    def __post_init__(self) -> None:
        if int(self.retry_budget) < 1:
            raise ValueError("retry budget must be at least 1")
        try:
            backoff = float(self.backoff_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("retry backoff seconds must be a number") from exc
        if not math.isfinite(backoff) or backoff < 0:
            raise ValueError("retry backoff seconds must be finite and non-negative")

    def is_retryable(self, status: str) -> bool:
        return str(status) in {str(value) for value in self.retryable_statuses}

    def delay_seconds(self, attempt: int) -> float:
        if attempt < 1:
            return 0.0
        return float(self.backoff_seconds) * (2 ** (attempt - 1))

    def to_report(self) -> dict[str, Any]:
        return {
            "retry_budget": int(self.retry_budget),
            "backoff_seconds": _rounded(float(self.backoff_seconds)),
            "retryable_statuses": [str(value) for value in self.retryable_statuses],
        }


@dataclass(frozen=True)
class RuntimeRetryResult:
    """Result and JSON-stable retry trace for one bounded operation."""

    result: Any
    trace: dict[str, Any]


def run_with_retry(
    operation: Callable[[], Any],
    *,
    status_getter: Callable[[Any], str],
    policy: RuntimeRetryPolicy | None = None,
    sleeper: Callable[[float], None] | None = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> RuntimeRetryResult:
    """Run an operation with a bounded retry budget and return its retry trace."""

    retry_policy = policy or RuntimeRetryPolicy()
    attempts: list[dict[str, Any]] = []
    result: Any = None
    final_status = "unknown"

    for attempt in range(1, int(retry_policy.retry_budget) + 1):
        started = clock()
        result = operation()
        latency_ms = max(0.0, (clock() - started) * 1000)
        final_status = str(status_getter(result))
        retryable = retry_policy.is_retryable(final_status)
        should_retry = retryable and attempt < int(retry_policy.retry_budget)
        attempt_report: dict[str, Any] = {
            "attempt": attempt,
            "status": final_status,
            "retryable": retryable,
            "latency_ms": _rounded(latency_ms),
        }
        if should_retry:
            delay = retry_policy.delay_seconds(attempt)
            attempt_report["next_delay_ms"] = _rounded(delay * 1000)
        attempts.append(attempt_report)
        if not should_retry:
            break
        delay = retry_policy.delay_seconds(attempt)
        if delay > 0 and sleeper is not None:
            sleeper(delay)

    trace = {
        "schema": RUNTIME_RETRY_TRACE_SCHEMA,
        **retry_policy.to_report(),
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "final_status": final_status,
        "budget_exhausted": bool(
            attempts
            and retry_policy.is_retryable(final_status)
            and len(attempts) >= int(retry_policy.retry_budget)
        ),
        "attempts": attempts,
    }
    return RuntimeRetryResult(result=result, trace=trace)
