#!/usr/bin/env python3
"""Inventory public commands against Phase 31 runtime-resilience coverage."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from report_surface_inventory import ROOT, discover_public_commands


SCHEMA = "ragflow_runtime_resilience_inventory_v1"
VALID_STATUSES = {"covered", "candidate", "deferred", "not_applicable"}


@dataclass(frozen=True)
class RuntimeClassification:
    status: str
    features: tuple[str, ...]
    rationale: str
    next_action: str = ""


_COVERED = {
    "ragflow-doc-to-md": RuntimeClassification(
        status="covered",
        features=("process_cleanup_report",),
        rationale="Top-level conversion reports local process attempts, cleanup attempts, timeouts, and leftovers.",
        next_action="Keep runtime-report and redaction coverage in release gates.",
    ),
    "ragflow-doc-to-md backend probe": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Backend readiness probes emit ragflow_runtime_partial_failure_report_v1 without changing default no-network behavior.",
        next_action="Keep fake backend readiness coverage for available, missing, wrong-protocol, timeout, and not-configured statuses.",
    ),
    "ragflow-doc-to-md backend warmup": RuntimeClassification(
        status="covered",
        features=("process_cleanup_report",),
        rationale="Warmup reports process-backed conversion attempts and cleanup state for tiny approved fixtures.",
        next_action="Keep no-daemon fake CLI fixtures in acceptance and smoke checks.",
    ),
    "ragflow-doc-to-md split": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume",),
        rationale="Large offline Markdown split jobs can batch segment materialization with checkpoints and resume without touching RAGFlow.",
        next_action="Keep split checkpoint/resume covered in CLI, acceptance, and platform smoke checks.",
    ),
    "ragflow-kb-build model-providers probe": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Model-provider endpoint and explicit adapter probes emit ragflow_runtime_partial_failure_report_v1.",
        next_action="Keep fake endpoint and empty-input adapter probes covered.",
    ),
    "ragflow-kb-build probe": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Read-only RAGFlow diagnostics report completed, warning-only, failed, skipped, and timeout dataset-list outcomes.",
        next_action="Keep fake diagnostic probes covered without adding mutation.",
    ),
    "ragflow-kb-build inspect-kb": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Optional live KB inspection emits partial-failure reports for parsed, failed, in-progress, missing, and not-checked document rows.",
        next_action="Keep inspection read-only; evaluate pagination only if large live KBs need broader status coverage.",
    ),
    "ragflow-kb-build snapshot-chunks": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Offline chunk snapshot reports summarize snapshotted, duplicate-skipped, and missing-content chunk profiles.",
        next_action="Evaluate checkpoint/resume later if large snapshot inputs need resumable batching.",
    ),
    "ragflow-kb-build validate": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Retrieval validation emits partial-failure reports for passed, semantic-warning, error, and timeout query outcomes.",
        next_action="Evaluate checkpoint/resume later for very large benchmark validation runs.",
    ),
    "ragflow-kb-build qa validate": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Offline grounded-QA validation emits partial-failure reports for validated, invalid, warning, and skipped source-check rows.",
        next_action="Keep validation local and deterministic; consider evidence-map partial-failure coverage next.",
    ),
    "ragflow-kb-build qa map-evidence": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Offline grounded-QA evidence mapping emits partial-failure reports for mapped, unmapped, partially mapped, invalid, and warning rows.",
        next_action="Evaluate checkpoint/resume later if large evidence-map inputs need resumable batching.",
    ),
    "ragflow-kb-build benchmark import": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume",),
        rationale="Offline benchmark imports can batch query normalization with checkpoints and resume without touching RAGFlow.",
        next_action="Keep import checkpoint coverage deterministic and local; do not extend this to live KB mutation.",
    ),
    "ragflow-kb-build qa generate": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume",),
        rationale="Deterministic, script-owned QA generation over snapshots can batch source-span generation with checkpoints and resume without LLM calls.",
        next_action="Keep generation deterministic; do not add script-owned LLM QA.",
    ),
    "ragflow-kb-build profile experiment": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume", "partial_failure"),
        rationale="Offline profile experiment matrices can batch candidate-profile planning with checkpoints and partial-run summaries without touching RAGFlow.",
        next_action="Keep profile experiments fixture-driven and non-mutating.",
    ),
    "ragflow-kb-build optimize": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume", "partial_failure"),
        rationale="Plan-only optimization can batch candidate-profile plans with checkpoint/resume and partial-run summaries without enabling live disposable KB creation.",
        next_action="Keep optimize --execute behind readiness, exact confirmation, and cleanup artifact gates.",
    ),
    "ragflow-query cache-report": RuntimeClassification(
        status="covered",
        features=("query_output_cache",),
        rationale="Saved query-output cache keys, dry-run invalidation, active writes, and cache stats have deterministic reports.",
        next_action="Keep cache reports host-owned and redacted.",
    ),
    "ragflow-query centroid build": RuntimeClassification(
        status="covered",
        features=("checkpoint_resume",),
        rationale="Bounded offline centroid builds can write checkpoints and resume without duplicating completed chunks.",
        next_action="Use as the concrete checkpoint/resume precedent before broadening helpers.",
    ),
    "ragflow-query endpoint-report": RuntimeClassification(
        status="covered",
        features=("cache", "circuit_breaker", "metrics", "partial_failure", "rate_limit", "retry"),
        rationale="Read-only endpoint reports pilot shared runtime metrics, retry, cache, rate-limit, circuit-breaker, and partial-failure helpers.",
        next_action="Keep the helper pilot stable before broadening to live query or build flows.",
    ),
    "ragflow-query fallback-test": RuntimeClassification(
        status="covered",
        features=("partial_failure",),
        rationale="Offline fallback profiles emit ragflow_runtime_partial_failure_report_v1 for timeout, malformed, skipped, and partial cases.",
        next_action="Keep fallback fixtures deterministic and offline.",
    ),
}

_CANDIDATES: dict[str, RuntimeClassification] = {}

_DEFERRED = {
    "ragflow-kb-build": RuntimeClassification(
        status="deferred",
        features=("checkpoint_resume", "partial_failure", "retry"),
        rationale="Live KB build is mutating and should wait until offline/read-only helpers are stable and explicitly gated.",
        next_action="Do not add new mutation behavior while closing Phase 31 governance.",
    ),
    "ragflow-query ask": RuntimeClassification(
        status="deferred",
        features=("partial_failure", "retry"),
        rationale="Live query execution can use runtime helpers later, but endpoint-report and fallback-test are safer pilot surfaces.",
        next_action="Defer broad live query resilience until read-only coverage is committed.",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _classification_for(command: str) -> RuntimeClassification:
    if command in _COVERED:
        return _COVERED[command]
    if command in _CANDIDATES:
        return _CANDIDATES[command]
    if command in _DEFERRED:
        return _DEFERRED[command]
    return RuntimeClassification(
        status="not_applicable",
        features=(),
        rationale="No Phase 31 runtime-resilience helper target is currently identified for this command surface.",
        next_action="Reclassify only if the command gains live batching, retries, cache state, or partial runtime outcomes.",
    )


def _finding(check: str, command: str, message: str) -> dict[str, str]:
    return {"check": check, "command": command, "message": message}


def run_runtime_resilience_inventory(root: Path = ROOT) -> dict[str, Any]:
    discovered = discover_public_commands(root)
    discovered_commands = {command.command for command in discovered}
    explicit_commands = set(_COVERED) | set(_CANDIDATES) | set(_DEFERRED)
    findings: list[dict[str, str]] = []

    for command in sorted(explicit_commands - discovered_commands):
        findings.append(_finding("stale_runtime_resilience_classification", command, "classification references a command that is no longer public"))

    entries = []
    for command in discovered:
        classification = _classification_for(command.command)
        if classification.status not in VALID_STATUSES:
            findings.append(_finding("invalid_runtime_resilience_status", command.command, f"unsupported status: {classification.status}"))
        entries.append(
            {
                "command": command.command,
                "skill": command.skill,
                "script": command.script,
                "status": classification.status,
                "features": sorted(classification.features),
                "rationale": classification.rationale,
                "next_action": classification.next_action,
            }
        )

    status_counts = {status: 0 for status in sorted(VALID_STATUSES)}
    feature_counts: dict[str, int] = {}
    skill_counts: dict[str, dict[str, int]] = {}
    for entry in entries:
        status = str(entry["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        skill = str(entry["skill"])
        skill_counts.setdefault(skill, {status: 0 for status in sorted(VALID_STATUSES)})
        skill_counts[skill][status] += 1
        for feature in entry["features"]:
            feature_counts[feature] = feature_counts.get(feature, 0) + 1

    return {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "ok": not findings,
        "summary": {
            "command_count": len(entries),
            "status_counts": status_counts,
            "feature_counts": dict(sorted(feature_counts.items())),
            "skill_counts": skill_counts,
            "finding_count": len(findings),
        },
        "findings": findings,
        "commands": entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    status_counts = summary.get("status_counts", {}) if isinstance(summary.get("status_counts"), dict) else {}
    feature_counts = summary.get("feature_counts", {}) if isinstance(summary.get("feature_counts"), dict) else {}
    lines = [
        "# RAGFlow Runtime Resilience Inventory",
        "",
        f"- schema: `{report.get('schema', SCHEMA)}`",
        f"- public commands: `{summary.get('command_count', 0)}`",
        f"- covered: `{status_counts.get('covered', 0)}`",
        f"- candidate: `{status_counts.get('candidate', 0)}`",
        f"- deferred: `{status_counts.get('deferred', 0)}`",
        f"- not applicable: `{status_counts.get('not_applicable', 0)}`",
        f"- findings: `{summary.get('finding_count', 0)}`",
        "",
        "## Feature Counts",
        "",
    ]
    if feature_counts:
        for feature, count in sorted(feature_counts.items()):
            lines.append(f"- `{feature}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "| Command | Status | Features | Next Action |",
            "| --- | --- | --- | --- |",
        ]
    )
    for entry in report.get("commands", []):
        if not isinstance(entry, dict):
            continue
        features = ", ".join(f"`{feature}`" for feature in entry.get("features") or []) or "none"
        lines.append(
            "| `{}` | `{}` | {} | {} |".format(
                entry.get("command", ""),
                entry.get("status", ""),
                features,
                str(entry.get("next_action") or "").replace("|", "\\|"),
            )
        )
    if report.get("findings"):
        lines.extend(["", "## Findings", ""])
        for finding in report["findings"]:
            lines.append(f"- `{finding.get('check')}` `{finding.get('command')}`: {finding.get('message')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory public runtime-resilience coverage and candidates")
    parser.add_argument("--report-json", help="Optional JSON inventory output path")
    parser.add_argument("--report-md", help="Optional Markdown inventory output path")
    args = parser.parse_args(argv)
    report = run_runtime_resilience_inventory()
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_json:
        path = Path(args.report_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered_json, encoding="utf-8")
    if args.report_md:
        path = Path(args.report_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")
    print(rendered_json, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
