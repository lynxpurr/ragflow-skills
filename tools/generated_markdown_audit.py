#!/usr/bin/env python3
"""Audit generated Markdown report redaction coverage."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from report_surface_inventory import ROOT, run_report_surface_inventory


SCHEMA = "ragflow_generated_markdown_audit_v1"
MARKDOWN_REPORT_CATEGORIES = (
    "markdown_report",
    "quality_report",
    "runtime_report",
    "trace_markdown",
)
SANITIZED_MARKDOWN_VERIFIED_COMMANDS = (
    "ragflow-doc-to-md",
    "ragflow-doc-to-md adaptive",
    "ragflow-doc-to-md backend probe",
    "ragflow-doc-to-md backend warmup",
    "ragflow-doc-to-md compare-adaptive-summaries",
    "ragflow-doc-to-md compare-retained-package",
    "ragflow-doc-to-md inspect",
    "ragflow-doc-to-md inspect-source",
    "ragflow-kb-build activation-plan",
    "ragflow-kb-build benchmark delta",
    "ragflow-kb-build benchmark gate",
    "ragflow-kb-build benchmark import",
    "ragflow-kb-build benchmark preflight",
    "ragflow-kb-build benchmark sample",
    "ragflow-kb-build benchmark suggest",
    "ragflow-kb-build benchmark summarize",
    "ragflow-kb-build benchmark trend",
    "ragflow-kb-build consistency-check",
    "ragflow-kb-build diagnose",
    "ragflow-kb-build health-report",
    "ragflow-kb-build image-ingestion-readiness",
    "ragflow-kb-build inspect-handoff",
    "ragflow-kb-build metadata lint",
    "ragflow-kb-build metadata merge",
    "ragflow-kb-build metadata suggest-request",
    "ragflow-kb-build metadata suggest-review",
    "ragflow-kb-build model-providers probe",
    "ragflow-kb-build optimize",
    "ragflow-kb-build optimize cleanup-plan",
    "ragflow-kb-build optimize readiness",
    "ragflow-kb-build optimize summarize",
    "ragflow-kb-build parameter-audit",
    "ragflow-kb-build parse-report",
    "ragflow-kb-build refresh-report",
    "ragflow-kb-build probe",
    "ragflow-kb-build profile compare",
    "ragflow-kb-build profile decision",
    "ragflow-kb-build profile experiment",
    "ragflow-kb-build profile lint",
    "ragflow-kb-build qa apollo-evaluate",
    "ragflow-kb-build qa apollo-judge-request",
    "ragflow-kb-build qa apollo-judge-review",
    "ragflow-kb-build qa apollo-validate",
    "ragflow-kb-build qa generate",
    "ragflow-kb-build qa map-evidence",
    "ragflow-kb-build qa suggest-request",
    "ragflow-kb-build qa suggest-review",
    "ragflow-kb-build qa validate",
    "ragflow-kb-build segment-metadata report",
    "ragflow-kb-build snapshot-chunks",
    "ragflow-kb-build suppression-report",
    "ragflow-kb-build tagset lint",
    "ragflow-kb-build tagset report",
    "ragflow-kb-build topology advise",
    "ragflow-kb-build topology split-plan",
    "ragflow-kb-build validate",
    "ragflow-query agentic-answer request",
    "ragflow-query agentic-answer review",
    "ragflow-query agentic-plan",
    "ragflow-query assistant-profile recommend",
    "ragflow-query assistant-test-plan",
    "ragflow-query audit-citations",
    "ragflow-query cache-report",
    "ragflow-query centroid build",
    "ragflow-query cross-language-ab",
    "ragflow-query diagnose-result",
    "ragflow-query endpoint-report",
    "ragflow-query evaluate-answer",
    "ragflow-query evaluator request",
    "ragflow-query evaluator review",
    "ragflow-query fallback-test",
    "ragflow-query fusion",
    "ragflow-query fusion-test",
    "ragflow-query intent classify",
    "ragflow-query intent route",
    "ragflow-query pollution-report",
    "ragflow-query rerank-ab",
    "ragflow-query rewrite",
    "ragflow-query route-activation-check",
    "ragflow-query route-diagnose",
    "ragflow-query route-report",
    "ragflow-query route-test",
    "ragflow-query session enrich",
    "ragflow-query session inspect",
    "ragflow-query table-strategy",
    "ragflow-query validation-suggestions",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _finding(check: str, command: str, message: str) -> dict[str, str]:
    return {"check": check, "command": command, "message": message}


def _markdown_categories(entry: dict[str, Any]) -> list[str]:
    categories = entry.get("output_categories") if isinstance(entry.get("output_categories"), list) else []
    return sorted(str(category) for category in categories if str(category) in MARKDOWN_REPORT_CATEGORIES)


def _is_markdown_candidate(entry: dict[str, Any]) -> bool:
    return (
        entry.get("status") == "covered"
        and entry.get("redaction_sidecar") is True
        and bool(_markdown_categories(entry))
    )


def _iter_markdown_candidates(inventory: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for entry in inventory.get("commands", []):
        if isinstance(entry, dict) and _is_markdown_candidate(entry):
            yield entry


def _evidence_for_command(command: str) -> list[str]:
    if command.startswith("ragflow-doc-to-md"):
        return [
            "packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py",
            "tools/consumer_acceptance.py",
            "tools/platform_smoke_matrix.py",
        ]
    if command.startswith("ragflow-kb-build"):
        return [
            "packages/ragflow-skill-runtime/tests/test_kb_build_cli.py",
            "tools/consumer_acceptance.py",
            "tools/platform_smoke_matrix.py",
        ]
    if command.startswith("ragflow-query"):
        return [
            "packages/ragflow-skill-runtime/tests/test_query_cli.py",
            "tools/consumer_acceptance.py",
            "tools/platform_smoke_matrix.py",
        ]
    return []


def run_generated_markdown_audit(
    root: Path = ROOT,
    *,
    verified_commands: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Verify every covered Markdown report surface has explicit sanitized-rendering evidence."""

    inventory = run_report_surface_inventory(root=root)
    candidates = list(_iter_markdown_candidates(inventory))
    candidate_commands = {str(entry.get("command")) for entry in candidates}
    verified_set = set(verified_commands or SANITIZED_MARKDOWN_VERIFIED_COMMANDS)
    findings: list[dict[str, str]] = []

    if not inventory.get("ok"):
        findings.append(
            _finding(
                "generated_markdown_inventory_not_ok",
                "inventory",
                "report surface inventory has findings; generated Markdown audit cannot be trusted",
            )
        )
    for command in sorted(candidate_commands - verified_set):
        findings.append(
            _finding(
                "generated_markdown_missing_audit",
                command,
                "covered Markdown report surface lacks explicit sanitized Markdown audit evidence",
            )
        )
    for command in sorted(verified_set - candidate_commands):
        findings.append(
            _finding(
                "generated_markdown_stale_audit",
                command,
                "sanitized Markdown audit entry no longer maps to a covered Markdown report surface",
            )
        )

    entries = []
    for entry in candidates:
        command = str(entry.get("command"))
        status = "verified" if command in verified_set else "missing"
        entries.append(
            {
                "command": command,
                "skill": entry.get("skill"),
                "status": status,
                "output_categories": _markdown_categories(entry),
                "evidence": _evidence_for_command(command) if status == "verified" else [],
                "assertion": (
                    "Markdown report rendering is exercised from the sanitized report payload "
                    "when --redaction-report is enabled."
                )
                if status == "verified"
                else "",
            }
        )

    verified_count = sum(1 for entry in entries if entry["status"] == "verified")
    return {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "ok": not findings,
        "inventory_schema": inventory.get("schema"),
        "summary": {
            "markdown_candidate_count": len(candidates),
            "verified_count": verified_count,
            "missing_count": len(candidates) - verified_count,
            "stale_count": len(verified_set - candidate_commands),
            "finding_count": len(findings),
        },
        "markdown_categories": list(MARKDOWN_REPORT_CATEGORIES),
        "commands": entries,
        "findings": findings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Generated Markdown Audit",
        "",
        f"- schema: `{report.get('schema', SCHEMA)}`",
        f"- markdown candidates: `{summary.get('markdown_candidate_count', 0)}`",
        f"- verified: `{summary.get('verified_count', 0)}`",
        f"- missing: `{summary.get('missing_count', 0)}`",
        f"- stale: `{summary.get('stale_count', 0)}`",
        f"- findings: `{summary.get('finding_count', 0)}`",
        "",
        "| Command | Status | Markdown Outputs | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for entry in report.get("commands", []):
        if not isinstance(entry, dict):
            continue
        outputs = ", ".join(entry.get("output_categories") or ["none"])
        evidence = ", ".join(entry.get("evidence") or ["none"])
        lines.append(
            "| `{}` | `{}` | {} | {} |".format(
                entry.get("command", ""),
                entry.get("status", ""),
                outputs,
                evidence,
            )
        )
    if report.get("findings"):
        lines.extend(["", "## Findings", ""])
        for finding in report["findings"]:
            if isinstance(finding, dict):
                lines.append(f"- `{finding.get('check')}` `{finding.get('command')}`: {finding.get('message')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit sanitized Markdown report rendering coverage")
    parser.add_argument("--report-json", help="Optional JSON audit output path")
    parser.add_argument("--report-md", help="Optional Markdown audit output path")
    args = parser.parse_args(argv)
    report = run_generated_markdown_audit()
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
