"""Small runtime resilience helpers for public skill reports."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import math
import time
from typing import Any


RUNTIME_RETRY_TRACE_SCHEMA = "ragflow_runtime_retry_trace_v1"
RUNTIME_RATE_LIMIT_REPORT_SCHEMA = "ragflow_runtime_rate_limit_report_v1"
RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA = "ragflow_runtime_circuit_breaker_report_v1"
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


@dataclass(frozen=True)
class RuntimeRateLimitPolicy:
    """Describe an optional token-bucket rate limit for read-only operations."""

    rate_per_second: float | None = None
    burst: int = 1

    def __post_init__(self) -> None:
        if int(self.burst) < 1:
            raise ValueError("rate limit burst must be at least 1")
        if self.rate_per_second is None:
            return
        try:
            rate = float(self.rate_per_second)
        except (TypeError, ValueError) as exc:
            raise ValueError("rate limit per second must be a number") from exc
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("rate limit per second must be finite and greater than zero")

    @property
    def enabled(self) -> bool:
        return self.rate_per_second is not None

    def to_report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rate_per_second": _rounded(float(self.rate_per_second)) if self.rate_per_second is not None else None,
            "burst": int(self.burst),
        }


@dataclass
class RuntimeRateLimiter:
    """Deterministic token-bucket limiter with a JSON-stable report."""

    policy: RuntimeRateLimitPolicy = field(default_factory=RuntimeRateLimitPolicy)
    sleeper: Callable[[float], None] | None = time.sleep
    clock: Callable[[], float] = time.monotonic
    acquire_count: int = 0
    delayed_count: int = 0
    total_delay_seconds: float = 0.0
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(int(self.policy.burst))
        self._last_refill = float(self.clock())

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def _refill(self) -> None:
        if not self.policy.enabled:
            return
        now = float(self.clock())
        elapsed = max(0.0, now - self._last_refill)
        rate = float(self.policy.rate_per_second or 0.0)
        if elapsed > 0 and rate > 0:
            self._tokens = min(float(int(self.policy.burst)), self._tokens + elapsed * rate)
            self._last_refill = now

    def acquire(self) -> dict[str, Any]:
        """Consume one token, sleeping only when the policy is enabled and empty."""

        if not self.policy.enabled:
            return {"delayed": False, "delay_ms": 0.0}
        self.acquire_count += 1
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return {"delayed": False, "delay_ms": 0.0}

        rate = float(self.policy.rate_per_second or 0.0)
        delay = max(0.0, (1.0 - self._tokens) / rate)
        self.delayed_count += 1
        self.total_delay_seconds += delay
        if delay > 0 and self.sleeper is not None:
            self.sleeper(delay)
        self._last_refill = float(self.clock())
        self._tokens = 0.0
        return {"delayed": delay > 0, "delay_ms": _rounded(delay * 1000)}

    def to_report(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_RATE_LIMIT_REPORT_SCHEMA,
            **self.policy.to_report(),
            "summary": {
                "acquire_count": self.acquire_count,
                "delayed_count": self.delayed_count,
                "total_delay_ms": _rounded(self.total_delay_seconds * 1000),
                "available_tokens": _rounded(self._tokens),
            },
        }


@dataclass(frozen=True)
class RuntimeCircuitBreakerPolicy:
    """Describe an optional per-run circuit breaker for read-only operations."""

    failure_threshold: int | None = None
    recovery_seconds: float | None = None
    failure_statuses: Sequence[str] = DEFAULT_RETRYABLE_STATUSES

    def __post_init__(self) -> None:
        if self.failure_threshold is not None and int(self.failure_threshold) < 1:
            raise ValueError("circuit breaker failure threshold must be at least 1")
        if self.recovery_seconds is None:
            return
        try:
            recovery = float(self.recovery_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("circuit breaker recovery seconds must be a number") from exc
        if not math.isfinite(recovery) or recovery < 0:
            raise ValueError("circuit breaker recovery seconds must be finite and non-negative")

    @property
    def enabled(self) -> bool:
        return self.failure_threshold is not None

    def is_failure(self, status: str) -> bool:
        return str(status) in {str(value) for value in self.failure_statuses}

    def to_report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "failure_threshold": int(self.failure_threshold) if self.failure_threshold is not None else None,
            "recovery_seconds": _rounded(float(self.recovery_seconds))
            if self.recovery_seconds is not None
            else None,
            "failure_statuses": [str(value) for value in self.failure_statuses],
        }


@dataclass
class RuntimeCircuitBreaker:
    """Per-run circuit breaker with a JSON-stable report."""

    policy: RuntimeCircuitBreakerPolicy = field(default_factory=RuntimeCircuitBreakerPolicy)
    clock: Callable[[], float] = time.monotonic
    state: str = "closed"
    failure_count: int = 0
    success_count: int = 0
    consecutive_failure_count: int = 0
    open_count: int = 0
    short_circuit_count: int = 0
    half_open_count: int = 0
    last_failure_status: str | None = None
    opened_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def _maybe_recover(self) -> None:
        if (
            self.policy.enabled
            and self.state == "open"
            and self.opened_at is not None
            and self.policy.recovery_seconds is not None
            and float(self.clock()) - self.opened_at >= float(self.policy.recovery_seconds)
        ):
            self.state = "half_open"
            self.half_open_count += 1

    def before_request(self) -> dict[str, Any]:
        """Return whether the operation may run under the current circuit state."""

        if not self.policy.enabled:
            return {"allowed": True, "state": self.state, "reason": "circuit breaker disabled"}
        self._maybe_recover()
        if self.state == "open":
            self.short_circuit_count += 1
            return {
                "allowed": False,
                "state": self.state,
                "reason": "circuit breaker is open after repeated failures",
            }
        return {"allowed": True, "state": self.state, "reason": "circuit breaker allows request"}

    def record_result(self, status: str) -> None:
        """Update breaker state from a final operation status."""

        if not self.policy.enabled:
            return
        status_text = str(status)
        if self.policy.is_failure(status_text):
            self.failure_count += 1
            self.consecutive_failure_count += 1
            self.last_failure_status = status_text
            if self.consecutive_failure_count >= int(self.policy.failure_threshold or 1):
                if self.state != "open":
                    self.open_count += 1
                self.state = "open"
                self.opened_at = float(self.clock())
            return

        self.success_count += 1
        self.consecutive_failure_count = 0
        if self.state == "half_open":
            self.state = "closed"
            self.opened_at = None

    def to_report(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA,
            **self.policy.to_report(),
            "summary": {
                "state": self.state,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "consecutive_failure_count": self.consecutive_failure_count,
                "open_count": self.open_count,
                "short_circuit_count": self.short_circuit_count,
                "half_open_count": self.half_open_count,
                "last_failure_status": self.last_failure_status,
            },
        }


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
