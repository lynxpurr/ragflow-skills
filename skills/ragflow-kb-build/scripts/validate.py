#!/usr/bin/env python3
"""Validate a RAGFlow KB manifest."""

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
    RAGFlowClient,
    attach_benchmark_evaluation,
    load_benchmark_baseline,
    load_benchmark_gate,
    load_benchmark_qrels,
    load_chunk_snapshot,
    load_config,
    load_kb_manifest,
    load_validation_queries,
    render_markdown_report,
    run_retrieval_validation,
    smoke_query,
    summarize_metadata_for_documents,
)
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.manifests import ManifestError  # noqa: E402
from ragflow_skill_runtime.validation import ValidationError  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _render_markdown_with_metadata(report, metadata_summary: dict[str, Any] | None) -> str:
    markdown = render_markdown_report(report)
    if not metadata_summary:
        return markdown
    lines = [
        markdown.rstrip(),
        "",
        "## Metadata Summary",
        "",
        f"- ok: `{str(bool(metadata_summary.get('ok'))).lower()}`",
        f"- documents: `{metadata_summary.get('document_count', 0)}`",
        f"- matched build documents: `{metadata_summary.get('matched_build_documents', 0)}`",
        f"- fields: `{', '.join(metadata_summary.get('fields', []))}`",
        f"- tags: `{', '.join(metadata_summary.get('tags', []))}`",
        "",
    ]
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    try:
        manifest = load_kb_manifest(args.kb_manifest)
        metadata_summary = summarize_metadata_for_documents(
            args.metadata,
            [
                document.markdown_path or document.source_path or document.document_id
                for document in manifest.documents
            ],
        )
        if metadata_summary and not metadata_summary.get("ok", False):
            raise ValidationError("metadata lint failed; run metadata lint for details")
        if args.level == "smoke":
            queries = [smoke_query(args.query, dataset_name=manifest.dataset.name)]
        else:
            if not args.queries:
                raise ValidationError(f"{args.level} validation requires --queries")
            if args.level == "benchmark" and not args.qrels:
                raise ValidationError("benchmark validation requires --qrels")
            queries = load_validation_queries(args.queries)

        config = _load_config(args)
        client = RAGFlowClient(config)
        report = run_retrieval_validation(
            client,
            level=args.level,
            dataset_id=manifest.dataset.id,
            dataset_name=manifest.dataset.name,
            queries=queries,
            top_k=args.top_k,
        )
        if args.level == "benchmark":
            qrels = load_benchmark_qrels(args.qrels)
            gate = load_benchmark_gate(args.gate_config) if args.gate_config else None
            baseline = load_benchmark_baseline(args.baseline_report) if args.baseline_report else None
            chunk_snapshot = load_chunk_snapshot(args.chunk_snapshot) if args.chunk_snapshot else None
            report = attach_benchmark_evaluation(
                report,
                qrels=qrels,
                cutoff=args.metric_cutoff or args.top_k,
                gate=gate,
                baseline_metrics=baseline,
                baseline_path=args.baseline_report,
                chunk_snapshot=chunk_snapshot,
            )
        payload = report.to_dict(max_chunks=args.max_report_chunks)
        if metadata_summary:
            payload["metadata_summary"] = metadata_summary
        rendered_json = json.dumps(payload, ensure_ascii=False, indent=2)
        _write_text(args.report_json, rendered_json + "\n")
        _write_text(args.report_md, _render_markdown_with_metadata(report, metadata_summary))
        print(rendered_json)
        return 0 if report.ok else 1
    except (ConfigError, ManifestError, ValidationError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a RAGFlow KB")
    parser.add_argument("--kb-manifest", required=True)
    parser.add_argument("--level", choices=["smoke", "regression", "benchmark"], default="smoke")
    parser.add_argument("--query", help="Smoke-test query")
    parser.add_argument("--queries", help="JSON query set for regression or benchmark validation")
    parser.add_argument("--qrels", help="JSON relevance judgments for benchmark validation")
    parser.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    parser.add_argument("--baseline-report", help="Optional previous benchmark report JSON")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 file for strict chunk recall")
    parser.add_argument("--metric-cutoff", type=int, help="Metric cutoff for benchmark reports")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-report-chunks", type=int, default=3)
    parser.add_argument("--report-json", help="Optional JSON report output path")
    parser.add_argument("--report-md", help="Optional Markdown report output path")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file to summarize and lint before validation")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
