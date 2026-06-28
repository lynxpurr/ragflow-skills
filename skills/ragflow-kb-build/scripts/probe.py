#!/usr/bin/env python3
"""Probe safe RAGFlow API surfaces without mutating server state."""

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
    RAGFlowClient,
    load_config,
    probe_ragflow_client,
    render_diagnostic_markdown,
)
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from _report_redaction import sanitize_cli_report  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _write_reports(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.report_json:
        output = Path(args.report_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.report_md:
        output = Path(args.report_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_diagnostic_markdown(report), encoding="utf-8")


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    try:
        config = _load_config(args)
        client = RAGFlowClient(config)
        report = probe_ragflow_client(client, page_size=args.page_size)
        if args.redaction_report:
            report, redaction_report = sanitize_cli_report(
                report,
                args,
                input_paths=[args.config],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
                context_json_paths=[args.config],
                config=config,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_reports(args, report)
        _dump_json(report)
        if args.fail_on_error and not report.get("ok", False):
            return 1
        return 0
    except (ConfigError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe RAGFlow API compatibility without mutation")
    parser.add_argument("--page-size", type=int, default=50, help="Dataset list page size")
    parser.add_argument("--report-json", help="Optional diagnostic report JSON output path")
    parser.add_argument("--report-md", help="Optional diagnostic report Markdown output path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--fail-on-error", action="store_true", help="Return exit code 1 when diagnostics contain errors")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
