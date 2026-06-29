"""Offline fallback coverage fixtures for ragflow-query."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .runtime_resilience import build_runtime_partial_failure_report


QUERY_FALLBACK_TEST_REPORT_SCHEMA = "ragflow_query_fallback_test_report_v1"
FALLBACK_FAILURE_MODES = (
    "llm_unavailable",
    "malformed_llm_json",
    "network_timeout",
    "partial_failure",
    "direct_retrieval_fallback",
)
FALLBACK_SUCCESS_STATUSES = ("success", "partial")
FALLBACK_RUNTIME_SUCCESS_STATUSES = ("success", "partial")
FALLBACK_RUNTIME_FAILURE_STATUSES = ("error", "malformed_json", "unavailable")
FALLBACK_RUNTIME_SKIPPED_STATUSES = ("skipped",)

DEFAULT_FALLBACK_TEST_CASES = (
    {
        "id": "llm-unavailable-direct-retrieval",
        "description": "LLM helper is unavailable, so host falls back to direct retrieval evidence.",
        "failure_mode": "llm_unavailable",
        "primary_status": "unavailable",
        "fallback_strategy": "direct_retrieval",
        "fallback_status": "success",
        "direct_retrieval_chunk_count": 2,
    },
    {
        "id": "malformed-llm-json-direct-retrieval",
        "description": "LLM helper returns malformed JSON, so host ignores it and uses direct retrieval.",
        "failure_mode": "malformed_llm_json",
        "primary_status": "malformed_json",
        "fallback_strategy": "direct_retrieval",
        "fallback_status": "success",
        "direct_retrieval_chunk_count": 1,
    },
    {
        "id": "network-timeout-direct-retrieval",
        "description": "LLM or helper network call times out within budget and direct retrieval still returns evidence.",
        "failure_mode": "network_timeout",
        "primary_status": "timeout",
        "fallback_strategy": "direct_retrieval",
        "fallback_status": "success",
        "direct_retrieval_chunk_count": 1,
        "timeout_ms": 1500,
    },
    {
        "id": "partial-failure-preserves-evidence",
        "description": "One branch fails, but partial evidence is preserved and reported as partial success.",
        "failure_mode": "partial_failure",
        "primary_status": "partial_failure",
        "fallback_strategy": "direct_retrieval",
        "fallback_status": "partial",
        "direct_retrieval_chunk_count": 1,
        "partial_failure_count": 1,
    },
    {
        "id": "direct-retrieval-fallback",
        "description": "Host bypasses synthesis and returns direct retrieval evidence when fallback is requested.",
        "failure_mode": "direct_retrieval_fallback",
        "primary_status": "fallback_requested",
        "fallback_strategy": "direct_retrieval",
        "fallback_status": "success",
        "direct_retrieval_chunk_count": 3,
    },
)


def load_query_fallback_test_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load fallback-test cases, or return built-in offline cases."""

    if not path:
        return [dict(case) for case in DEFAULT_FALLBACK_TEST_CASES]
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, Mapping) else payload
    if not isinstance(cases, list):
        raise ValueError("fallback test cases JSON must be a list or an object with a cases list")
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, Mapping):
            raise ValueError(f"fallback test case {index} must be an object")
        normalized.append(dict(case))
    if not normalized:
        raise ValueError("fallback test cases must be non-empty")
    return normalized


def _bool_value(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"boolean fallback fixture value must be true or false: {value!r}")


def _int_value(value: Any, *, default: int = 0, minimum: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"integer fallback fixture value is invalid: {value!r}") from exc
    if parsed < minimum:
        raise ValueError(f"integer fallback fixture value must be >= {minimum}: {value!r}")
    return parsed


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    if detail:
        issue["detail"] = dict(detail)
    issues.append(issue)


def _evaluate_fallback_case(case: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    case_id = str(case.get("id") or f"fallback-case-{index + 1}")
    failure_mode = str(case.get("failure_mode") or "").strip()
    primary_status = str(case.get("primary_status") or failure_mode or "unknown")
    fallback_strategy = str(case.get("fallback_strategy") or "direct_retrieval")
    fallback_status = str(case.get("fallback_status") or "success")
    fallback_used = _bool_value(case.get("fallback_used"), default=True)
    expect_fallback = _bool_value(case.get("expect_fallback"), default=True)
    expect_success = _bool_value(case.get("expect_success"), default=True)
    direct_chunk_count = _int_value(case.get("direct_retrieval_chunk_count"), default=1)
    partial_failure_count = _int_value(
        case.get("partial_failure_count"),
        default=1 if failure_mode == "partial_failure" else 0,
    )
    timeout_ms = _int_value(case.get("timeout_ms"), default=0)
    fallback_success = (
        fallback_used
        and fallback_strategy == "direct_retrieval"
        and fallback_status in FALLBACK_SUCCESS_STATUSES
        and direct_chunk_count > 0
    )

    issues: list[dict[str, Any]] = []
    if failure_mode not in FALLBACK_FAILURE_MODES:
        _append_issue(
            issues,
            severity="error",
            code="unknown_failure_mode",
            message="fallback fixture uses an unknown failure_mode",
            detail={"failure_mode": failure_mode},
        )
    if fallback_used != expect_fallback:
        _append_issue(
            issues,
            severity="error",
            code="fallback_expectation_mismatch",
            message="fallback usage did not match expectation",
            detail={"fallback_used": fallback_used, "expect_fallback": expect_fallback},
        )
    if expect_success and not fallback_success:
        _append_issue(
            issues,
            severity="error",
            code="fallback_not_successful",
            message="fallback did not produce usable direct retrieval evidence",
            detail={
                "fallback_status": fallback_status,
                "fallback_strategy": fallback_strategy,
                "direct_retrieval_chunk_count": direct_chunk_count,
            },
        )
    if failure_mode == "network_timeout" and timeout_ms <= 0:
        _append_issue(
            issues,
            severity="warning",
            code="timeout_budget_missing",
            message="network timeout fallback case should record a timeout budget",
        )
    if failure_mode == "partial_failure" and partial_failure_count <= 0:
        _append_issue(
            issues,
            severity="warning",
            code="partial_failure_count_missing",
            message="partial failure case should record at least one failed branch",
        )

    passed = not any(issue["severity"] == "error" for issue in issues)
    return {
        "id": case_id,
        "description": case.get("description"),
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "failure_mode": failure_mode,
        "primary": {
            "status": primary_status,
            "timed_out": failure_mode == "network_timeout",
            "malformed_json": failure_mode == "malformed_llm_json",
            "partial_failure": failure_mode == "partial_failure",
            "timeout_ms": timeout_ms,
            "partial_failure_count": partial_failure_count,
        },
        "fallback": {
            "used": fallback_used,
            "strategy": fallback_strategy,
            "status": fallback_status,
            "success": fallback_success,
            "direct_retrieval_chunk_count": direct_chunk_count,
            "reason": case.get("fallback_reason") or f"{failure_mode} handled by {fallback_strategy}",
        },
        "expected": {
            "fallback_used": expect_fallback,
            "fallback_success": expect_success,
        },
        "metrics": {
            "fallback_attempt": 1 if fallback_used else 0,
            "fallback_success": 1 if fallback_success else 0,
            "direct_retrieval_fallback": 1 if fallback_strategy == "direct_retrieval" and fallback_used else 0,
            "timeout": 1 if failure_mode == "network_timeout" else 0,
            "malformed_llm_json": 1 if failure_mode == "malformed_llm_json" else 0,
            "llm_unavailable": 1 if failure_mode == "llm_unavailable" else 0,
            "partial_failure": 1 if failure_mode == "partial_failure" else 0,
        },
        "issues": issues,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _runtime_status_for_case(case: Mapping[str, Any]) -> str:
    if not case.get("passed"):
        return "error"
    failure_mode = str(case.get("failure_mode") or "")
    metrics = case.get("metrics") if isinstance(case.get("metrics"), Mapping) else {}
    if int(metrics.get("timeout", 0) or 0) > 0:
        return "timeout"
    if int(metrics.get("partial_failure", 0) or 0) > 0:
        return "partial"
    if failure_mode == "malformed_llm_json":
        return "malformed_json"
    if failure_mode in {"llm_unavailable", "direct_retrieval_fallback"}:
        return "skipped"
    fallback = case.get("fallback") if isinstance(case.get("fallback"), Mapping) else {}
    if fallback.get("success"):
        status = str(fallback.get("status") or "success")
        return status if status in FALLBACK_RUNTIME_SUCCESS_STATUSES else "success"
    return "error"


def _fallback_runtime_partial_failure_report(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    runtime_items = [
        {
            "label": case.get("id") or f"fallback_case_{index}",
            "status": _runtime_status_for_case(case),
        }
        for index, case in enumerate(case_results, start=1)
        if isinstance(case, Mapping)
    ]
    return build_runtime_partial_failure_report(
        QUERY_FALLBACK_TEST_REPORT_SCHEMA,
        runtime_items,
        success_statuses=FALLBACK_RUNTIME_SUCCESS_STATUSES,
        warning_statuses=(),
        failure_statuses=FALLBACK_RUNTIME_FAILURE_STATUSES,
        skipped_statuses=FALLBACK_RUNTIME_SKIPPED_STATUSES,
    )


def run_query_fallback_tests(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run offline fallback fixture coverage checks."""

    if not cases:
        raise ValueError("fallback test cases must be non-empty")
    case_results = [_evaluate_fallback_case(case, index=index) for index, case in enumerate(cases)]
    issues: list[dict[str, Any]] = []
    for case in case_results:
        for issue in case.get("issues", []):
            if isinstance(issue, Mapping):
                issue_with_case = dict(issue)
                issue_with_case["case_id"] = case.get("id")
                issues.append(issue_with_case)

    failure_mode_counts = {mode: 0 for mode in FALLBACK_FAILURE_MODES}
    fallback_attempts = 0
    fallback_successes = 0
    direct_retrieval_fallbacks = 0
    timeout_count = 0
    malformed_count = 0
    partial_count = 0
    llm_unavailable_count = 0
    for case in case_results:
        mode = str(case.get("failure_mode") or "")
        failure_mode_counts[mode] = failure_mode_counts.get(mode, 0) + 1
        metrics = case.get("metrics", {}) if isinstance(case.get("metrics"), Mapping) else {}
        fallback_attempts += int(metrics.get("fallback_attempt", 0))
        fallback_successes += int(metrics.get("fallback_success", 0))
        direct_retrieval_fallbacks += int(metrics.get("direct_retrieval_fallback", 0))
        timeout_count += int(metrics.get("timeout", 0))
        malformed_count += int(metrics.get("malformed_llm_json", 0))
        partial_count += int(metrics.get("partial_failure", 0))
        llm_unavailable_count += int(metrics.get("llm_unavailable", 0))

    missing_modes = [mode for mode in FALLBACK_FAILURE_MODES if failure_mode_counts.get(mode, 0) == 0]
    for mode in missing_modes:
        _append_issue(
            issues,
            severity="error",
            code="missing_fallback_coverage",
            message="fallback test suite does not cover a required failure mode",
            detail={"failure_mode": mode},
        )

    passed = sum(1 for case in case_results if case.get("passed"))
    total = len(case_results)
    failed = total - passed
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    runtime_partial_failure = _fallback_runtime_partial_failure_report(case_results)
    runtime_partial_summary = runtime_partial_failure["summary"]
    return {
        "ok": error_count == 0,
        "schema": QUERY_FALLBACK_TEST_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if error_count == 0 else "FAIL",
        "required_failure_modes": list(FALLBACK_FAILURE_MODES),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": _rate(passed, total),
            "fallback_attempt_count": fallback_attempts,
            "fallback_success_count": fallback_successes,
            "fallback_success_rate": _rate(fallback_successes, fallback_attempts),
            "direct_retrieval_fallback_count": direct_retrieval_fallbacks,
            "timeout_count": timeout_count,
            "malformed_llm_json_count": malformed_count,
            "partial_failure_count": partial_count,
            "llm_unavailable_count": llm_unavailable_count,
            "required_mode_count": len(FALLBACK_FAILURE_MODES),
            "covered_required_mode_count": len(FALLBACK_FAILURE_MODES) - len(missing_modes),
            "issue_count": len(issues),
            "errors": error_count,
            "warnings": warning_count,
            "runtime_partial_failure_status": runtime_partial_summary["status"],
            "runtime_failure_count": runtime_partial_summary["failure_count"],
            "runtime_timeout_count": runtime_partial_summary["timeout_count"],
            "runtime_skipped_count": runtime_partial_summary["skipped_count"],
        },
        "failure_mode_counts": failure_mode_counts,
        "runtime_partial_failure": runtime_partial_failure,
        "coverage": {
            "missing_required_failure_modes": missing_modes,
            "covered_required_failure_modes": [
                mode for mode in FALLBACK_FAILURE_MODES if failure_mode_counts.get(mode, 0) > 0
            ],
        },
        "cases": case_results,
        "issues": issues,
        "recommendations": [
            "Keep fallback-test fixtures offline so host agents can run them without live RAGFlow or LLM services.",
            "Treat fallback success as evidence readiness, not answer generation; host-owned synthesis still needs citation audits.",
            "Add service-level retry and circuit-breaker traces before enabling live fallback orchestration.",
        ],
    }


def render_query_fallback_test_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown fallback coverage report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    runtime_partial = (
        report.get("runtime_partial_failure")
        if isinstance(report.get("runtime_partial_failure"), Mapping)
        else {}
    )
    runtime_partial_summary = (
        runtime_partial.get("summary")
        if isinstance(runtime_partial.get("summary"), Mapping)
        else {}
    )
    lines = [
        "# RAGFlow Query Fallback Test Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- total: `{summary.get('total', 0)}`",
        f"- passed: `{summary.get('passed', 0)}`",
        f"- failed: `{summary.get('failed', 0)}`",
        f"- fallback_success_rate: `{summary.get('fallback_success_rate', 0)}`",
        f"- covered_required_modes: `{summary.get('covered_required_mode_count', 0)}` / `{summary.get('required_mode_count', 0)}`",
    ]
    if runtime_partial:
        lines.extend(
            [
                f"- runtime_partial_failure_status: `{runtime_partial_summary.get('status', 'unknown')}`",
                f"- runtime_partial_failure_partial: `{str(runtime_partial_summary.get('partial', False)).lower()}`",
                f"- runtime_failures: `{runtime_partial_summary.get('failure_count', 0)}`",
                f"- runtime_timeouts: `{runtime_partial_summary.get('timeout_count', 0)}`",
                f"- runtime_skipped: `{runtime_partial_summary.get('skipped_count', 0)}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| id | failure mode | fallback | status | chunks |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for case in report.get("cases", []) if isinstance(report.get("cases"), list) else []:
        if not isinstance(case, Mapping):
            continue
        fallback = case.get("fallback") if isinstance(case.get("fallback"), Mapping) else {}
        lines.append(
            f"| `{case.get('id', '')}` | `{case.get('failure_mode', '')}` | "
            f"`{fallback.get('strategy', '')}` | `{case.get('status', '')}` | "
            f"{fallback.get('direct_retrieval_chunk_count', 0)} |"
        )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines.extend(["", "## Issues", ""])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(
                    f"- `{issue.get('case_id', '')}` `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}"
                )
    return "\n".join(lines).rstrip() + "\n"
