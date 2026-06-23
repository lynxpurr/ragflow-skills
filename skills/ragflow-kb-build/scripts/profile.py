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
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    compare_validation_reports,
    explain_profile,
    lint_profile,
    load_profile,
    recommend_profile,
    render_profile_compare_markdown,
    render_profile_lint_markdown,
)
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402


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


def _cmd_lint(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    report = lint_profile(profile)
    payload = report.to_dict()
    _write_json(args.report_json, payload)
    _write_text(args.report_md, render_profile_lint_markdown(report))
    _dump_json(payload)
    if not report.ok:
        return 1
    if args.fail_on_warning and payload["summary"]["warnings"]:
        return 1
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    payload = explain_profile(load_profile(args.profile))
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
    _write_json(args.report_json, payload)
    _dump_json(payload)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    payload = compare_validation_reports(args.report)
    _write_json(args.report_json, payload)
    _write_text(args.report_md, render_profile_compare_markdown(payload))
    _dump_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, explain, recommend, and compare RAGFlow chunk profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a chunk profile")
    lint.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    lint.add_argument("--fail-on-warning", action="store_true")
    lint.add_argument("--report-json", help="Optional JSON report output path")
    lint.add_argument("--report-md", help="Optional Markdown report output path")
    lint.set_defaults(func=_cmd_lint)

    explain = subparsers.add_parser("explain", help="Explain a chunk profile")
    explain.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    explain.add_argument("--report-json", help="Optional JSON report output path")
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
    recommend.set_defaults(func=_cmd_recommend)

    compare = subparsers.add_parser("compare", help="Compare validation reports from profile experiments")
    compare.add_argument("--report", action="append", required=True, help="Validation report JSON path")
    compare.add_argument("--report-json", help="Optional JSON report output path")
    compare.add_argument("--report-md", help="Optional Markdown report output path")
    compare.set_defaults(func=_cmd_compare)
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
