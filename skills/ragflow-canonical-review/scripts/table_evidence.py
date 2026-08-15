#!/usr/bin/env python3
"""Compare canonical table matrices or create/review advisory VLM table evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence


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
    CanonicalTableEquivalenceError,
    compare_canonical_markdown_to_html,
    create_table_vlm_request,
    render_canonical_table_report_markdown,
    review_table_vlm_candidate,
    sanitize_report_payload,
)


MODES = ("compare", "vlm-request", "vlm-review")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--canonical-markdown", required=True, type=Path)
    parser.add_argument("--derived-html", type=Path, help="Derived HTML for compare mode.")
    parser.add_argument("--source-crop", type=Path, help="Exact source page/table crop for vlm-request mode.")
    parser.add_argument("--source-reference", help="Reviewed source reference for vlm-request mode.")
    parser.add_argument("--table-id", help="Stable reviewed table id for vlm-request mode.")
    parser.add_argument("--canonical-table-index", type=int, help="One-based Markdown table index for vlm-request mode.")
    parser.add_argument("--request", type=Path, help="Exact request JSON for vlm-review mode.")
    parser.add_argument("--candidate", type=Path, help="External advisory/generated candidate JSON for vlm-review mode.")
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--redaction-report", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit the report or structured errors to stdout.")
    return parser


def _require(args: argparse.Namespace, *names: str) -> None:
    missing = [name for name in names if getattr(args, name) in {None, ""}]
    if missing:
        flags = ", ".join("--" + name.replace("_", "-") for name in missing)
        raise CanonicalTableEquivalenceError(f"{args.mode} mode requires {flags}")


def _create_report(args: argparse.Namespace) -> dict[str, object]:
    if args.mode == "compare":
        _require(args, "derived_html")
        return compare_canonical_markdown_to_html(
            canonical_markdown_path=args.canonical_markdown,
            derived_html_path=args.derived_html,
        )
    if args.mode == "vlm-request":
        _require(args, "source_crop", "source_reference", "table_id", "canonical_table_index")
        return create_table_vlm_request(
            canonical_markdown_path=args.canonical_markdown,
            canonical_table_index=args.canonical_table_index,
            source_crop_path=args.source_crop,
            source_reference=args.source_reference,
            table_id=args.table_id,
        )
    _require(args, "request", "candidate")
    return review_table_vlm_candidate(
        request_path=args.request,
        candidate_path=args.candidate,
        canonical_markdown_path=args.canonical_markdown,
    )


def _write_text(path: Path | None, text: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = _create_report(args)
        if args.redaction_report:
            report, redaction = sanitize_report_payload(
                report,
                home_paths=[
                    str(args.canonical_markdown),
                    str(args.derived_html) if args.derived_html else None,
                    str(args.source_crop) if args.source_crop else None,
                    str(args.request) if args.request else None,
                    str(args.candidate) if args.candidate else None,
                ],
                config_paths=[
                    str(args.report_json) if args.report_json else None,
                    str(args.report_md) if args.report_md else None,
                    str(args.redaction_report),
                ],
            )
            _write_text(args.redaction_report, json.dumps(redaction, ensure_ascii=False, indent=2) + "\n")
        if args.report_json:
            _write_text(args.report_json, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        if args.report_md:
            _write_text(args.report_md, render_canonical_table_report_markdown(report))
    except (CanonicalTableEquivalenceError, OSError, UnicodeError, ValueError) as exc:
        return _error(str(exc), json_output=args.json)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.report_json:
        print(f"Report: {args.report_json}")
    else:
        print(f"Status: {report.get('status', 'request_ready')}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
