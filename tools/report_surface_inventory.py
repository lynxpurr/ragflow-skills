#!/usr/bin/env python3
"""Inventory public commands that emit report-like artifacts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
SCHEMA = "ragflow_report_surface_inventory_v1"
VALID_STATUSES = {"covered", "not_applicable", "needs_redaction"}

OUTPUT_OPTION_NAMES = {
    "--artifact-index-name",
    "--assistant-profile-name",
    "--assistant-test-plan-name",
    "--candidate-set",
    "--checkpoint",
    "--index-output",
    "--manifest-name",
    "--metadata-name",
    "--output",
    "--output-markdown",
    "--package-readme-name",
    "--plan-output",
    "--profile-suggestions-name",
    "--quality-report-md",
    "--quality-report-name",
    "--redaction-report",
    "--report-json",
    "--report-md",
    "--retrieval-hints-name",
    "--runtime-report-md",
    "--runtime-report-name",
    "--trace-json",
    "--trace-md",
}
INPUT_REPORT_OPTION_NAMES = {
    "--baseline-report",
    "--parse-report",
    "--query-output",
    "--report",
    "--route-test-report",
}
REPORT_OPTION_HINTS = OUTPUT_OPTION_NAMES | INPUT_REPORT_OPTION_NAMES | {"--include-trace", "--max-report-chunks"}
SIDECAR_NAME_OPTIONS = {
    "--artifact-index-name",
    "--assistant-profile-name",
    "--assistant-test-plan-name",
    "--metadata-name",
    "--package-readme-name",
    "--profile-suggestions-name",
    "--retrieval-hints-name",
}


@dataclass(frozen=True)
class Classification:
    status: str
    rationale: str
    next_action: str = ""


@dataclass(frozen=True)
class DiscoveredCommand:
    command: str
    skill: str
    script: str
    option_strings: tuple[str, ...]
    help: str


QUERY_COVERED_COMMANDS = (
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
QUERY_NOT_APPLICABLE_COMMANDS = (
    "ragflow-query ask",
    "ragflow-query bootstrap-smoke",
    "ragflow-query list-kbs",
    "ragflow-query route",
)
DOC_COVERED_COMMANDS = (
    "ragflow-doc-to-md",
    "ragflow-doc-to-md adaptive",
    "ragflow-doc-to-md backend probe",
    "ragflow-doc-to-md compare-retained-package",
    "ragflow-doc-to-md compare-adaptive-summaries",
    "ragflow-doc-to-md backend warmup",
    "ragflow-doc-to-md inspect",
    "ragflow-doc-to-md inspect-source",
    "ragflow-doc-to-md postprocess",
    "ragflow-doc-to-md segment-plan",
    "ragflow-doc-to-md split",
)
DOC_NOT_APPLICABLE_COMMANDS = ("ragflow-doc-to-md package",)
KB_COVERED_COMMANDS = (
    "ragflow-kb-build activation-plan",
    "ragflow-kb-build append",
    "ragflow-kb-build benchmark delta",
    "ragflow-kb-build benchmark gate",
    "ragflow-kb-build benchmark import",
    "ragflow-kb-build benchmark preflight",
    "ragflow-kb-build benchmark sample",
    "ragflow-kb-build benchmark suggest",
    "ragflow-kb-build benchmark summarize",
    "ragflow-kb-build benchmark trend",
    "ragflow-kb-build cleanup",
    "ragflow-kb-build consistency-check",
    "ragflow-kb-build diagnose",
    "ragflow-kb-build health-report",
    "ragflow-kb-build image-ingestion-execute",
    "ragflow-kb-build image-ingestion-readiness",
    "ragflow-kb-build inspect-handoff",
    "ragflow-kb-build inspect-kb",
    "ragflow-kb-build metadata lint",
    "ragflow-kb-build metadata merge",
    "ragflow-kb-build metadata suggest-request",
    "ragflow-kb-build metadata suggest-review",
    "ragflow-kb-build model-providers probe",
    "ragflow-kb-build optimize",
    "ragflow-kb-build optimize cleanup-plan",
    "ragflow-kb-build optimize readiness",
    "ragflow-kb-build optimize summarize",
    "ragflow-kb-build parse-report",
    "ragflow-kb-build probe",
    "ragflow-kb-build profile compare",
    "ragflow-kb-build profile decision",
    "ragflow-kb-build profile experiment",
    "ragflow-kb-build profile explain",
    "ragflow-kb-build profile lint",
    "ragflow-kb-build profile recommend",
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
)
KB_NEEDS_REDACTION_COMMANDS: tuple[str, ...] = ()
KB_NOT_APPLICABLE_COMMANDS = (
    "ragflow-kb-build",
    "ragflow-kb-build metadata generate-template",
    "ragflow-kb-build tagset export",
    "ragflow-kb-build tagset generate-template",
)


def _classification_map() -> dict[str, Classification]:
    covered = Classification(
        status="covered",
        rationale="Supports a report redaction sidecar and renders Markdown from the sanitized payload when redaction is enabled.",
        next_action="Keep covered by redaction sidecar tests.",
    )
    query_not_applicable = Classification(
        status="not_applicable",
        rationale="Does not produce a shareable generated report file; output is live/user-owned command output or a bootstrap smoke payload.",
        next_action="No redaction sidecar needed for Phase 36 report closure.",
    )
    doc_not_applicable = Classification(
        status="not_applicable",
        rationale="Writes user-owned rich handoff sidecars rather than generated diagnostic reports.",
        next_action="Keep release hygiene scanning examples and generated fixtures.",
    )
    kb_covered = Classification(
        status="covered",
        rationale="KB command sanitizes report payloads and can emit ragflow_report_redaction_report_v1.",
        next_action="Keep fake endpoint and fake secret coverage in CLI tests.",
    )
    kb_needs = Classification(
        status="needs_redaction",
        rationale="KB reports or advisory plans can echo host-supplied manifests, report paths, parser configs, parse logs, endpoints, or live response details.",
        next_action="Add focused --redaction-report coverage before these reports are shared externally.",
    )
    kb_not_applicable = Classification(
        status="not_applicable",
        rationale="Writes canonical user-owned artifacts such as manifests, templates, exports, or benchmark subsets rather than shareable diagnostic reports.",
        next_action="No Phase 36 redaction sidecar required unless the command later gains a generated report output.",
    )
    mapping: dict[str, Classification] = {}
    for command in QUERY_COVERED_COMMANDS:
        mapping[command] = covered
    for command in QUERY_NOT_APPLICABLE_COMMANDS:
        mapping[command] = query_not_applicable
    for command in DOC_COVERED_COMMANDS:
        mapping[command] = covered
    for command in DOC_NOT_APPLICABLE_COMMANDS:
        mapping[command] = doc_not_applicable
    for command in KB_COVERED_COMMANDS:
        mapping[command] = kb_covered
    for command in KB_NEEDS_REDACTION_COMMANDS:
        mapping[command] = kb_needs
    for command in KB_NOT_APPLICABLE_COMMANDS:
        mapping[command] = kb_not_applicable
    return mapping


CLASSIFICATIONS = _classification_map()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_module(name: str, path: Path) -> Any:
    if str(RUNTIME_SRC) not in sys.path:
        sys.path.insert(0, str(RUNTIME_SRC))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iter_leaf_parsers(parser: argparse.ArgumentParser, prefix: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    subparser_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not subparser_actions:
        yield prefix, parser
        return
    for action in subparser_actions:
        for name, subparser in sorted(action.choices.items()):
            yield from _iter_leaf_parsers(subparser, (*prefix, name))


def _option_strings(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    values: set[str] = set()
    for action in parser._actions:
        for option in action.option_strings:
            if option in REPORT_OPTION_HINTS:
                values.add(option)
    return tuple(sorted(values))


def _record_parsers(
    *,
    commands: list[DiscoveredCommand],
    skill: str,
    script: str,
    prefix: tuple[str, ...],
    parser: argparse.ArgumentParser,
) -> None:
    for command_parts, leaf_parser in _iter_leaf_parsers(parser, prefix):
        commands.append(
            DiscoveredCommand(
                command=" ".join(command_parts),
                skill=skill,
                script=script,
                option_strings=_option_strings(leaf_parser),
                help=str(leaf_parser.description or ""),
            )
        )


def discover_public_commands(root: Path = ROOT) -> list[DiscoveredCommand]:
    """Return public command leaves from shipped skill scripts."""

    doc = _load_module("ragflow_doc_to_md_public_cli", root / "skills/ragflow-doc-to-md/scripts/convert.py")
    kb = _load_module("ragflow_kb_build_public_cli", root / "skills/ragflow-kb-build/scripts/build.py")
    profile = _load_module("ragflow_kb_profile_public_cli", root / "skills/ragflow-kb-build/scripts/profile.py")
    validate = _load_module("ragflow_kb_validate_public_cli", root / "skills/ragflow-kb-build/scripts/validate.py")
    append = _load_module("ragflow_kb_append_public_cli", root / "skills/ragflow-kb-build/scripts/append.py")
    cleanup = _load_module("ragflow_kb_cleanup_public_cli", root / "skills/ragflow-kb-build/scripts/cleanup.py")
    diagnose = _load_module("ragflow_kb_diagnose_public_cli", root / "skills/ragflow-kb-build/scripts/diagnose.py")
    inspect_kb = _load_module("ragflow_kb_inspect_public_cli", root / "skills/ragflow-kb-build/scripts/inspect_kb.py")
    probe = _load_module("ragflow_kb_probe_public_cli", root / "skills/ragflow-kb-build/scripts/probe.py")
    query = _load_module("ragflow_query_public_cli", root / "skills/ragflow-query/scripts/query.py")

    commands: list[DiscoveredCommand] = []
    _record_parsers(
        commands=commands,
        skill="ragflow-doc-to-md",
        script="skills/ragflow-doc-to-md/scripts/convert.py",
        prefix=("ragflow-doc-to-md",),
        parser=doc.build_parser(),
    )
    for prefix, builder in (
        (("ragflow-doc-to-md", "inspect-source"), doc.build_inspect_source_parser),
        (("ragflow-doc-to-md", "inspect"), doc.build_inspect_parser),
        (("ragflow-doc-to-md", "segment-plan"), doc.build_segment_plan_parser),
        (("ragflow-doc-to-md", "split"), doc.build_split_parser),
        (("ragflow-doc-to-md", "package"), doc.build_package_parser),
        (("ragflow-doc-to-md", "postprocess"), doc.build_postprocess_parser),
        (("ragflow-doc-to-md", "adaptive"), doc.build_adaptive_parser),
        (("ragflow-doc-to-md", "compare-adaptive-summaries"), doc.build_compare_adaptive_summaries_parser),
        (("ragflow-doc-to-md", "compare-retained-package"), doc.build_compare_retained_package_parser),
        (("ragflow-doc-to-md", "backend"), doc.build_backend_parser),
    ):
        _record_parsers(
            commands=commands,
            skill="ragflow-doc-to-md",
            script="skills/ragflow-doc-to-md/scripts/convert.py",
            prefix=prefix,
            parser=builder(),
        )

    _record_parsers(
        commands=commands,
        skill="ragflow-kb-build",
        script="skills/ragflow-kb-build/scripts/build.py",
        prefix=("ragflow-kb-build",),
        parser=kb.build_parser(),
    )
    for prefix, builder in (
        (("ragflow-kb-build", "inspect-handoff"), kb.build_inspect_handoff_parser),
        (("ragflow-kb-build", "model-providers"), kb.build_model_providers_parser),
        (("ragflow-kb-build", "metadata"), kb.build_metadata_parser),
        (("ragflow-kb-build", "tagset"), kb.build_tagset_parser),
        (("ragflow-kb-build", "snapshot-chunks"), kb.build_snapshot_chunks_parser),
        (("ragflow-kb-build", "benchmark"), kb.build_benchmark_parser),
        (("ragflow-kb-build", "suppression-report"), kb.build_suppression_report_parser),
        (("ragflow-kb-build", "qa"), kb.build_qa_parser),
        (("ragflow-kb-build", "segment-metadata"), kb.build_segment_metadata_parser),
        (("ragflow-kb-build", "optimize"), kb.build_optimize_parser),
        (("ragflow-kb-build", "optimize", "summarize"), kb.build_optimize_summarize_parser),
        (("ragflow-kb-build", "optimize", "cleanup-plan"), kb.build_optimize_cleanup_plan_parser),
        (("ragflow-kb-build", "optimize", "readiness"), kb.build_optimize_readiness_parser),
        (("ragflow-kb-build", "topology"), kb.build_topology_parser),
        (("ragflow-kb-build", "activation-plan"), kb.build_activation_plan_parser),
        (("ragflow-kb-build", "image-ingestion-execute"), kb.build_image_ingestion_execute_parser),
        (("ragflow-kb-build", "image-ingestion-readiness"), kb.build_image_ingestion_readiness_parser),
        (("ragflow-kb-build", "consistency-check"), kb.build_consistency_check_parser),
        (("ragflow-kb-build", "parse-report"), kb.build_parse_report_parser),
        (("ragflow-kb-build", "health-report"), kb.build_health_report_parser),
    ):
        _record_parsers(
            commands=commands,
            skill="ragflow-kb-build",
            script="skills/ragflow-kb-build/scripts/build.py",
            prefix=prefix,
            parser=builder(),
        )
    for command, module, script in (
        ("append", append, "skills/ragflow-kb-build/scripts/append.py"),
        ("cleanup", cleanup, "skills/ragflow-kb-build/scripts/cleanup.py"),
        ("diagnose", diagnose, "skills/ragflow-kb-build/scripts/diagnose.py"),
        ("inspect-kb", inspect_kb, "skills/ragflow-kb-build/scripts/inspect_kb.py"),
        ("probe", probe, "skills/ragflow-kb-build/scripts/probe.py"),
        ("profile", profile, "skills/ragflow-kb-build/scripts/profile.py"),
        ("validate", validate, "skills/ragflow-kb-build/scripts/validate.py"),
    ):
        _record_parsers(
            commands=commands,
            skill="ragflow-kb-build",
            script=script,
            prefix=("ragflow-kb-build", command),
            parser=module.build_parser(),
        )

    _record_parsers(
        commands=commands,
        skill="ragflow-query",
        script="skills/ragflow-query/scripts/query.py",
        prefix=("ragflow-query",),
        parser=query.build_parser(),
    )
    commands.append(
        DiscoveredCommand(
            command="ragflow-query bootstrap-smoke",
            skill="ragflow-query",
            script="skills/ragflow-query/scripts/bootstrap_smoke.py",
            option_strings=(),
            help="Smoke test vendored runtime loading.",
        )
    )
    by_command = {command.command: command for command in commands}
    return [by_command[key] for key in sorted(by_command)]


def _output_options(command: str, options: tuple[str, ...]) -> list[str]:
    outputs = [option for option in options if option in OUTPUT_OPTION_NAMES]
    if command != "ragflow-query ask":
        outputs = [option for option in outputs if option not in {"--trace-json", "--trace-md"}]
    return sorted(outputs)


def _input_report_options(command: str, options: tuple[str, ...]) -> list[str]:
    inputs = [option for option in options if option in INPUT_REPORT_OPTION_NAMES]
    if command != "ragflow-query ask" and "--trace-json" in options:
        inputs.append("--trace-json")
    return sorted(set(inputs))


def _output_categories(command: str, outputs: list[str]) -> list[str]:
    categories: set[str] = set()
    if "--redaction-report" in outputs:
        categories.add("redaction_sidecar")
    if "--report-json" in outputs:
        categories.add("json_report")
    if "--report-md" in outputs:
        categories.add("markdown_report")
    if "--quality-report-name" in outputs or "--quality-report-md" in outputs:
        categories.add("quality_report")
    if "--runtime-report-name" in outputs or "--runtime-report-md" in outputs:
        categories.add("runtime_report")
    if SIDECAR_NAME_OPTIONS.intersection(outputs):
        categories.add("handoff_sidecar")
    if "--output-markdown" in outputs:
        categories.add("content_markdown")
    if "--trace-json" in outputs:
        categories.add("trace_json")
    if "--trace-md" in outputs:
        categories.add("trace_markdown")
    if "--manifest-name" in outputs:
        categories.add("manifest_json")
    if "--checkpoint" in outputs:
        categories.add("checkpoint_json")
    if "--candidate-set" in outputs:
        categories.add("candidate_set_json")
    if "--index-output" in outputs:
        categories.add("index_json")
    if "--plan-output" in outputs:
        categories.add("plan_json")
    if "--output" in outputs:
        if command in {"ragflow-doc-to-md", "ragflow-kb-build"}:
            categories.add("manifest_json")
        elif command in {"ragflow-kb-build health-report", "ragflow-kb-build parse-report"}:
            categories.add("json_report")
        elif "template" in command or "tagset export" in command:
            categories.add("artifact_json")
        elif any(token in command for token in ("plan", "optimize", "topology", "append", "cleanup", "segment-plan")):
            categories.add("plan_json")
        elif command in {"ragflow-kb-build benchmark import", "ragflow-kb-build benchmark sample"}:
            categories.add("artifact_directory")
        else:
            categories.add("artifact_json")
    if not categories and command in {"ragflow-query list-kbs", "ragflow-query bootstrap-smoke", "ragflow-kb-build inspect-kb"}:
        categories.add("stdout_json")
    if not categories and command in {"ragflow-query ask", "ragflow-query route"}:
        categories.add("stdout_or_live_payload")
    return sorted(categories)


def _finding(check: str, command: str, message: str) -> dict[str, str]:
    return {"check": check, "command": command, "message": message}


def run_report_surface_inventory(root: Path = ROOT) -> dict[str, Any]:
    discovered = discover_public_commands(root)
    discovered_by_command = {command.command: command for command in discovered}
    findings: list[dict[str, str]] = []

    for command in sorted(discovered_by_command):
        if command not in CLASSIFICATIONS:
            findings.append(_finding("uncatalogued_public_command", command, "public command has no report-surface classification"))
    for command in sorted(CLASSIFICATIONS):
        if command not in discovered_by_command:
            findings.append(_finding("stale_report_surface_classification", command, "classification references a command that is no longer public"))
    for command, classification in sorted(CLASSIFICATIONS.items()):
        if classification.status not in VALID_STATUSES:
            findings.append(_finding("invalid_report_surface_status", command, f"unsupported status: {classification.status}"))

    entries = []
    for command in discovered:
        classification = CLASSIFICATIONS.get(
            command.command,
            Classification(
                status="needs_redaction",
                rationale="Uncatalogued public command; review report outputs before sharing generated artifacts.",
                next_action="Add an explicit Phase 36 classification.",
            ),
        )
        outputs = _output_options(command.command, command.option_strings)
        inputs = _input_report_options(command.command, command.option_strings)
        entries.append(
            {
                "command": command.command,
                "skill": command.skill,
                "script": command.script,
                "status": classification.status,
                "output_categories": _output_categories(command.command, outputs),
                "output_options": outputs,
                "input_report_options": inputs,
                "redaction_sidecar": "--redaction-report" in outputs,
                "rationale": classification.rationale,
                "next_action": classification.next_action,
            }
        )

    status_counts = {status: 0 for status in sorted(VALID_STATUSES)}
    for entry in entries:
        status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1
    skill_counts: dict[str, dict[str, int]] = {}
    for entry in entries:
        skill = str(entry["skill"])
        skill_counts.setdefault(skill, {status: 0 for status in sorted(VALID_STATUSES)})
        skill_counts[skill][str(entry["status"])] += 1

    return {
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "ok": not findings,
        "summary": {
            "command_count": len(entries),
            "status_counts": status_counts,
            "skill_counts": skill_counts,
            "finding_count": len(findings),
        },
        "findings": findings,
        "commands": entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    status_counts = summary.get("status_counts", {}) if isinstance(summary.get("status_counts"), dict) else {}
    lines = [
        "# RAGFlow Report Surface Inventory",
        "",
        f"- schema: `{report.get('schema', SCHEMA)}`",
        f"- public commands: `{summary.get('command_count', 0)}`",
        f"- covered: `{status_counts.get('covered', 0)}`",
        f"- not applicable: `{status_counts.get('not_applicable', 0)}`",
        f"- needs redaction: `{status_counts.get('needs_redaction', 0)}`",
        f"- findings: `{summary.get('finding_count', 0)}`",
        "",
        "| Command | Status | Outputs | Redaction | Next Action |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in report.get("commands", []):
        if not isinstance(entry, dict):
            continue
        outputs = ", ".join(entry.get("output_categories") or ["none"])
        redaction = "yes" if entry.get("redaction_sidecar") else "no"
        lines.append(
            "| `{}` | `{}` | {} | {} | {} |".format(
                entry.get("command", ""),
                entry.get("status", ""),
                outputs,
                redaction,
                str(entry.get("next_action") or "").replace("|", "\\|"),
            )
        )
    if report.get("findings"):
        lines.extend(["", "## Findings", ""])
        for finding in report["findings"]:
            lines.append(f"- `{finding.get('check')}` `{finding.get('command')}`: {finding.get('message')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory public report-producing command surfaces")
    parser.add_argument("--report-json", help="Optional JSON inventory output path")
    parser.add_argument("--report-md", help="Optional Markdown inventory output path")
    parser.add_argument("--fail-on-needs-redaction", action="store_true", help="Return non-zero when any command needs redaction")
    args = parser.parse_args(argv)
    report = run_report_surface_inventory()
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
    if not report["ok"]:
        return 1
    if args.fail_on_needs_redaction and report["summary"]["status_counts"].get("needs_redaction", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
