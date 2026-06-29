from __future__ import annotations

import unittest

from ragflow_skill_runtime import (
    RUNTIME_RETRY_TRACE_SCHEMA,
    RuntimeRetryPolicy,
    run_with_retry,
)


class RuntimeResilienceTests(unittest.TestCase):
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
