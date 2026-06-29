from __future__ import annotations

import unittest

from ragflow_skill_runtime import (
    RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA,
    RUNTIME_RATE_LIMIT_REPORT_SCHEMA,
    RUNTIME_RETRY_TRACE_SCHEMA,
    RuntimeCircuitBreaker,
    RuntimeCircuitBreakerPolicy,
    RuntimeRateLimitPolicy,
    RuntimeRateLimiter,
    RuntimeRetryPolicy,
    run_with_retry,
)


class RuntimeResilienceTests(unittest.TestCase):
    def test_circuit_breaker_policy_rejects_invalid_threshold_and_recovery(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeCircuitBreakerPolicy(failure_threshold=0)
        with self.assertRaises(ValueError):
            RuntimeCircuitBreakerPolicy(failure_threshold=1, recovery_seconds=-0.1)

    def test_circuit_breaker_opens_and_short_circuits_after_threshold(self) -> None:
        breaker = RuntimeCircuitBreaker(
            policy=RuntimeCircuitBreakerPolicy(failure_threshold=2),
            clock=lambda: 10.0,
        )

        first = breaker.before_request()
        breaker.record_result("error")
        second = breaker.before_request()
        breaker.record_result("timeout")
        third = breaker.before_request()
        report = breaker.to_report()

        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertFalse(third["allowed"])
        self.assertEqual(third["state"], "open")
        self.assertEqual(report["schema"], RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA)
        self.assertTrue(report["enabled"])
        self.assertEqual(report["failure_threshold"], 2)
        self.assertEqual(report["summary"]["state"], "open")
        self.assertEqual(report["summary"]["failure_count"], 2)
        self.assertEqual(report["summary"]["open_count"], 1)
        self.assertEqual(report["summary"]["short_circuit_count"], 1)
        self.assertEqual(report["summary"]["last_failure_status"], "timeout")

    def test_circuit_breaker_recovers_through_half_open_success(self) -> None:
        now = [0.0]
        breaker = RuntimeCircuitBreaker(
            policy=RuntimeCircuitBreakerPolicy(failure_threshold=1, recovery_seconds=5.0),
            clock=lambda: now[0],
        )

        breaker.record_result("error")
        blocked = breaker.before_request()
        now[0] = 6.0
        allowed = breaker.before_request()
        breaker.record_result("reachable")
        report = breaker.to_report()

        self.assertFalse(blocked["allowed"])
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["state"], "half_open")
        self.assertEqual(report["summary"]["state"], "closed")
        self.assertEqual(report["summary"]["half_open_count"], 1)
        self.assertEqual(report["summary"]["success_count"], 1)

    def test_disabled_circuit_breaker_reports_without_counting(self) -> None:
        breaker = RuntimeCircuitBreaker()

        decision = breaker.before_request()
        breaker.record_result("error")
        report = breaker.to_report()

        self.assertTrue(decision["allowed"])
        self.assertFalse(report["enabled"])
        self.assertEqual(report["summary"]["failure_count"], 0)

    def test_rate_limit_policy_rejects_invalid_rate_and_burst(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeRateLimitPolicy(rate_per_second=0)
        with self.assertRaises(ValueError):
            RuntimeRateLimitPolicy(rate_per_second=-1)
        with self.assertRaises(ValueError):
            RuntimeRateLimitPolicy(rate_per_second=1, burst=0)

    def test_rate_limiter_uses_token_bucket_delay(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def sleeper(delay: float) -> None:
            sleeps.append(delay)
            now[0] += delay

        limiter = RuntimeRateLimiter(
            policy=RuntimeRateLimitPolicy(rate_per_second=2, burst=1),
            sleeper=sleeper,
            clock=lambda: now[0],
        )

        first = limiter.acquire()
        second = limiter.acquire()
        report = limiter.to_report()

        self.assertEqual(first["delay_ms"], 0.0)
        self.assertEqual(second["delay_ms"], 500.0)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(report["schema"], RUNTIME_RATE_LIMIT_REPORT_SCHEMA)
        self.assertTrue(report["enabled"])
        self.assertEqual(report["rate_per_second"], 2.0)
        self.assertEqual(report["burst"], 1)
        self.assertEqual(report["summary"]["acquire_count"], 2)
        self.assertEqual(report["summary"]["delayed_count"], 1)
        self.assertEqual(report["summary"]["total_delay_ms"], 500.0)

    def test_disabled_rate_limiter_reports_without_acquiring(self) -> None:
        limiter = RuntimeRateLimiter()

        result = limiter.acquire()
        report = limiter.to_report()

        self.assertEqual(result["delay_ms"], 0.0)
        self.assertFalse(report["enabled"])
        self.assertEqual(report["summary"]["acquire_count"], 0)

    def test_retry_policy_rejects_invalid_budget_and_backoff(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeRetryPolicy(retry_budget=0)
        with self.assertRaises(ValueError):
            RuntimeRetryPolicy(backoff_seconds=-0.1)

    def test_run_with_retry_stops_after_retryable_status_recovers(self) -> None:
        statuses = iter(["error", "reachable"])
        sleeps: list[float] = []

        result = run_with_retry(
            lambda: next(statuses),
            status_getter=lambda value: value,
            policy=RuntimeRetryPolicy(retry_budget=3, backoff_seconds=0.25),
            sleeper=sleeps.append,
        )

        self.assertEqual(result.result, "reachable")
        self.assertEqual(result.trace["schema"], RUNTIME_RETRY_TRACE_SCHEMA)
        self.assertEqual(result.trace["retry_budget"], 3)
        self.assertEqual(result.trace["attempt_count"], 2)
        self.assertEqual(result.trace["retry_count"], 1)
        self.assertEqual(result.trace["final_status"], "reachable")
        self.assertFalse(result.trace["budget_exhausted"])
        self.assertEqual([attempt["status"] for attempt in result.trace["attempts"]], ["error", "reachable"])
        self.assertEqual(sleeps, [0.25])

    def test_run_with_retry_does_not_retry_non_retryable_status(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            return "unauthorized"

        result = run_with_retry(
            operation,
            status_getter=lambda value: value,
            policy=RuntimeRetryPolicy(retry_budget=3),
            sleeper=None,
        )

        self.assertEqual(calls, 1)
        self.assertEqual(result.trace["attempt_count"], 1)
        self.assertEqual(result.trace["retry_count"], 0)
        self.assertEqual(result.trace["final_status"], "unauthorized")

    def test_default_policy_uses_single_attempt(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            return "error"

        result = run_with_retry(operation, status_getter=lambda value: value, sleeper=None)

        self.assertEqual(calls, 1)
        self.assertEqual(result.trace["retry_budget"], 1)
        self.assertEqual(result.trace["attempt_count"], 1)
        self.assertEqual(result.trace["retry_count"], 0)
        self.assertTrue(result.trace["budget_exhausted"])


if __name__ == "__main__":
    unittest.main()
