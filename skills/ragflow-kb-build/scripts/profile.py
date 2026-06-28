#!/usr/bin/env python3
"""Profile lint, explain, recommend, and compare utilities."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys
from typing import Any


def bootstrap_runtime() -> None:
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parents[3] / "packages/ragflow-skill-runtime/src",
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
    compare_validation_reports,
    explain_profile,
    lint_profile,
    load_enrichment_experiment_matrix,
    load_profile,
    plan_enrichment_experiments,
    recommend_profile,
    render_enrichment_experiment_markdown,
    render_profile_compare_markdown,
    render_profile_lint_markdown,
)
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402
from _report_redaction import sanitize_cli_report  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _write_json(path: str | None, data: Any) -> None:
    if not path:
        return
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _render_profile_lint_markdown_from_payload(payload: dict[str, Any]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Profile Lint Report",
        "",
        f"- Profile: `{profile.get('id', profile.get('profile_id', ''))}`",
        f"- Status: `{'passed' if payload.get('ok') else 'failed'}`",
        f"- Errors: `{_as_int(summary.get('errors'))}`",
        f"- Warnings: `{_as_int(summary.get('warnings'))}`",
        f"- Infos: `{_as_int(summary.get('infos'))}`",
        "",
        "| severity | code | field | message |",
        "|---|---|---|---|",
    ]
    for issue in payload.get("issues", []) if isinstance(payload.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        lines.append(
            f"| {issue.get('severity', '')} | `{issue.get('code', '')}` | "
            f"{issue.get('field') or '-'} | {issue.get('message', '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_profile_compare_markdown_from_payload(payload: dict[str, Any]) -> str:
    lines = [
        "# RAGFlow Profile Compare Report",
        "",
        "| rank | path | score | pass_rate | hit_rate | mrr | ndcg@k | empty_rate | latency_ms | parse_ms |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    candidates = payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        lines.append(
            f"| {index} | `{item.get('path', '')}` | {_as_float(item.get('score')):.4f} | "
            f"{_as_float(metrics.get('pass_rate')):.4f} | {_as_float(metrics.get('hit_rate')):.4f} | "
            f"{_as_float(metrics.get('mrr')):.4f} | {_as_float(metrics.get('ndcg_at_k')):.4f} | "
            f"{_as_float(metrics.get('empty_result_rate')):.4f} | {_as_float(metrics.get('query_latency_ms')):.1f} | "
            f"{_as_float(metrics.get('parse_time_ms')):.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_enrichment_experiment_markdown_from_payload(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Enrichment Experiment Matrix",
        "",
        f"- Status: `{'passed' if payload.get('ok') else 'failed'}`",
        f"- Mutates RAGFlow: `false`",
        f"- Dimensions: `{_as_int(summary.get('dimension_count'))}`",
        f"- Candidate profiles: `{_as_int(summary.get('candidate_profile_count'))}`",
        f"- Warnings: `{_as_int(summary.get('warnings'))}`",
        "",
        "## Experiments",
        "",
        "| index | profile | settings | warnings |",
        "|---:|---|---|---:|",
    ]
    experiments = payload.get("experiments", []) if isinstance(payload.get("experiments"), list) else []
    for item in experiments:
        if not isinstance(item, dict):
            continue
        settings = json.dumps(item.get("settings", {}), ensure_ascii=False, sort_keys=True)
        risk_issues = item.get("risk_issues") if isinstance(item.get("risk_issues"), list) else []
        lines.append(f"| {item.get('index')} | `{item.get('profile_id', '')}` | `{settings}` | {len(risk_issues)} |")
    if payload.get("issues"):
        lines.extend(["", "## Issues", "", "| severity | code | field | message |", "|---|---|---|---|"])
        for issue in payload.get("issues", []) if isinstance(payload.get("issues"), list) else []:
            if isinstance(issue, dict):
                lines.append(
                    f"| {issue.get('severity', '')} | `{issue.get('code', '')}` | "
                    f"{issue.get('field', '-')} | {issue.get('message', '')} |"
                )
    lines.append("")
    return "\n".join(lines)


def _sanitize_profile_report(
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None] | None = None,
    output_paths: list[str | None] | None = None,
    context_json_paths: list[str | None] | None = None,
) -> dict[str, Any]:
    if not getattr(args, "redaction_report", None):
        return payload
    sanitized, redaction_report = sanitize_cli_report(
        payload,
        args,
        input_paths=input_paths,
        output_paths=output_paths,
        context_json_paths=context_json_paths,
    )
    _write_json(args.redaction_report, redaction_report)
    return sanitized


def _cmd_lint(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    report = lint_profile(profile)
    payload = report.to_dict()
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.profile],
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=[args.profile],
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_profile_lint_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_profile_lint_markdown(report))
    _dump_json(payload)
    if not report.ok:
        return 1
    if args.fail_on_warning and payload["summary"]["warnings"]:
        return 1
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    payload = explain_profile(load_profile(args.profile))
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.profile],
        output_paths=[args.report_json, args.redaction_report],
        context_json_paths=[args.profile],
    )
    _write_json(args.report_json, payload)
    _dump_json(payload)
    return 0 if payload["ok"] else 1


def _cmd_recommend(args: argparse.Namespace) -> int:
    recommendation = recommend_profile(
        language=args.language,
        doc_type=args.doc_type,
        profile_id=args.profile_id,
    )
    payload = recommendation.to_dict()
    _write_json(args.output, payload["profile"])
    payload = _sanitize_profile_report(
        payload,
        args,
        output_paths=[args.report_json, args.redaction_report],
    )
    _write_json(args.report_json, payload)
    _dump_json(payload)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    payload = compare_validation_reports(args.report)
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=list(args.report),
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=list(args.report),
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_profile_compare_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_profile_compare_markdown(payload))
    _dump_json(payload)
    return 0


def _parse_cli_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_set_spec(value: str) -> tuple[str, list[Any]]:
    if "=" not in value:
        raise ProfileError("--set values must use key=value1,value2 syntax")
    key, raw_values = value.split("=", 1)
    key = key.strip()
    if not key:
        raise ProfileError("--set key must not be empty")
    raw_values = raw_values.strip()
    if raw_values.startswith("["):
        parsed = _parse_cli_value(raw_values)
        if not isinstance(parsed, list):
            raise ProfileError("--set JSON value must be a list when it starts with [")
        return key, parsed
    return key, [_parse_cli_value(part.strip()) for part in raw_values.split(",") if part.strip()]


def _cmd_experiment(args: argparse.Namespace) -> int:
    matrix = (
        load_enrichment_experiment_matrix(args.matrix)
        if args.matrix
        else {"schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA, "dimensions": {}}
    )
    if args.name:
        matrix["name"] = args.name
    dimensions = matrix.setdefault("dimensions", {})
    if not isinstance(dimensions, dict):
        raise ProfileError("experiment matrix dimensions must be an object")
    for spec in args.set or []:
        key, values = _parse_set_spec(spec)
        dimensions[key] = values

    payload = plan_enrichment_experiments(
        base_profile=load_profile(args.base_profile),
        matrix=matrix,
        profile_id_prefix=args.profile_id_prefix,
        max_experiments=args.max_experiments,
    )
    _write_json(args.candidate_set, payload["candidate_profile_set"])
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.base_profile, args.matrix],
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=[args.base_profile, args.matrix],
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_enrichment_experiment_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_enrichment_experiment_markdown(payload))
    _dump_json(payload)
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, explain, recommend, compare, and plan RAGFlow chunk profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a chunk profile")
    lint.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    lint.add_argument("--fail-on-warning", action="store_true")
    lint.add_argument("--report-json", help="Optional JSON report output path")
    lint.add_argument("--report-md", help="Optional Markdown report output path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.set_defaults(func=_cmd_lint)

    explain = subparsers.add_parser("explain", help="Explain a chunk profile")
    explain.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    explain.add_argument("--report-json", help="Optional JSON report output path")
    explain.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    explain.set_defaults(func=_cmd_explain)

    recommend = subparsers.add_parser("recommend", help="Recommend a neutral starter profile")
    recommend.add_argument("--language", default="auto", help="auto, zh/ch/cn/zho, or en/eng")
    recommend.add_argument(
        "--doc-type",
        default="general",
        choices=["general", "book", "manual", "paper", "notes", "mixed"],
    )
    recommend.add_argument("--profile-id", help="Override generated profile_id")
    recommend.add_argument("--output", help="Optional profile JSON output path")
    recommend.add_argument("--report-json", help="Optional recommendation report output path")
    recommend.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    recommend.set_defaults(func=_cmd_recommend)

    compare = subparsers.add_parser("compare", help="Compare validation reports from profile experiments")
    compare.add_argument("--report", action="append", required=True, help="Validation report JSON path")
    compare.add_argument("--report-json", help="Optional JSON report output path")
    compare.add_argument("--report-md", help="Optional Markdown report output path")
    compare.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    compare.set_defaults(func=_cmd_compare)

    experiment = subparsers.add_parser("experiment", help="Plan offline enrichment experiment profiles")
    experiment.add_argument("--base-profile", required=True, help="Base profile JSON/YAML path")
    experiment.add_argument("--matrix", help="ragflow_enrichment_experiment_matrix_v1 JSON/YAML")
    experiment.add_argument("--set", action="append", default=[], help="Add/override a dimension as key=value1,value2; may be repeated")
    experiment.add_argument("--name", help="Optional experiment matrix name")
    experiment.add_argument("--profile-id-prefix", help="Prefix for generated candidate profile ids")
    experiment.add_argument("--max-experiments", type=int, default=64, help="Maximum matrix expansion size")
    experiment.add_argument("--candidate-set", help="Optional ragflow_candidate_profile_set_v1 output path")
    experiment.add_argument("--report-json", help="Optional experiment report JSON output path")
    experiment.add_argument("--report-md", help="Optional experiment report Markdown path")
    experiment.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    experiment.set_defaults(func=_cmd_experiment)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ProfileError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
