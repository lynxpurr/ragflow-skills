#!/usr/bin/env python3
"""Finalize a hash-bound canonical review into a new local output directory."""

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
    CanonicalReviewError,
    finalize_canonical_review,
    materialize_canonical_review_output,
    sanitize_report_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Exact immutable original source file.")
    parser.add_argument("--candidate-markdown", required=True, type=Path)
    parser.add_argument("--reviewed-markdown", required=True, type=Path)
    parser.add_argument("--markdown-audit", required=True, type=Path)
    parser.add_argument("--asset-audit", required=True, type=Path)
    parser.add_argument("--source-coverage", required=True, type=Path)
    parser.add_argument("--table-decisions", required=True, type=Path)
    parser.add_argument(
        "--asset-identities",
        type=Path,
        help="Optional reviewed asset identity/context JSON for semantic accepted-output names.",
    )
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New output directory for the review record and accepted local files.",
    )
    parser.add_argument(
        "--redaction-report",
        type=Path,
        help="Optional redaction sidecar path inside --output.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the review record to stdout.")
    return parser


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve(strict=False)
    try:
        record = finalize_canonical_review(
            source_path=args.source,
            candidate_markdown_path=args.candidate_markdown,
            reviewed_markdown_path=args.reviewed_markdown,
            markdown_audit_path=args.markdown_audit,
            asset_audit_path=args.asset_audit,
            source_coverage_path=args.source_coverage,
            table_decisions_path=args.table_decisions,
            asset_root=args.asset_root,
            asset_identity_path=args.asset_identities,
        )
        extra_json_files = {}
        if args.redaction_report:
            redaction_path = args.redaction_report.resolve(strict=False)
            try:
                redaction_relative = redaction_path.relative_to(output).as_posix()
            except ValueError as exc:
                raise CanonicalReviewError("--redaction-report must be inside --output") from exc
            record, redaction_report = sanitize_report_payload(
                record,
                home_paths=[
                    str(args.source) if args.source else None,
                    str(args.candidate_markdown),
                    str(args.reviewed_markdown),
                    str(args.asset_root),
                ],
                config_paths=[
                    str(args.markdown_audit),
                    str(args.asset_audit),
                    str(args.source_coverage),
                    str(args.table_decisions),
                    str(args.asset_identities) if args.asset_identities else None,
                    str(output),
                    str(redaction_path),
                ],
            )
            extra_json_files[redaction_relative] = redaction_report
        materialize_canonical_review_output(
            record,
            reviewed_markdown_path=args.reviewed_markdown,
            asset_root=args.asset_root,
            output_root=output,
            extra_json_files=extra_json_files,
        )
    except (CanonicalReviewError, OSError, UnicodeError) as exc:
        return _error(str(exc), json_output=args.json)

    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(f"Status: {record['status']}")
        print(f"Review record: {output / 'ragflow_canonical_review.json'}")
    return 0 if record["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
