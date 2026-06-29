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
from _report_redaction import sanitize_cli_report  # noqa: E402


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


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _render_markdown_from_payload(payload: dict[str, Any]) -> str:
    dataset = payload.get("dataset", {}) if isinstance(payload.get("dataset"), dict) else {}
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
    runtime_partial = (
        payload.get("runtime_partial_failure")
        if isinstance(payload.get("runtime_partial_failure"), dict)
        else {}
    )
    runtime_partial_summary = (
        runtime_partial.get("summary")
        if isinstance(runtime_partial.get("summary"), dict)
        else {}
    )
    lines = [
        "# RAGFlow Validation Report",
        "",
        f"- Level: `{payload.get('level', '')}`",
        f"- Dataset: `{dataset.get('name', '')}` (`{dataset.get('id', '')}`)",
        f"- Status: `{'passed' if payload.get('ok') else 'failed'}`",
        f"- Pass rate: `{_as_float(metrics.get('pass_rate')):.2%}`",
        f"- runtime_partial_failure_status: `{runtime_partial_summary.get('status', 'unknown')}`",
        f"- runtime_partial_failure_partial: `{str(runtime_partial_summary.get('partial', False)).lower()}`",
        f"- runtime_partial_failure_failures: `{runtime_partial_summary.get('failure_count', 0)}`",
        f"- runtime_partial_failure_timeouts: `{runtime_partial_summary.get('timeout_count', 0)}`",
        f"- runtime_partial_failure_warnings: `{runtime_partial_summary.get('warning_count', 0)}`",
        "",
        "| id | status | chunks | missing terms | missing documents |",
        "|---|---:|---:|---|---|",
    ]
    for case in payload.get("cases", []) if isinstance(payload.get("cases"), list) else []:
        if not isinstance(case, dict):
            continue
        status = "passed" if case.get("passed") else "failed"
        missing_terms = ", ".join(str(item) for item in case.get("missing_terms", []) or []) or "-"
        missing_docs = ", ".join(str(item) for item in case.get("missing_documents", []) or []) or "-"
        lines.append(f"| `{case.get('id', '')}` | {status} | {case.get('chunk_count', 0)} | {missing_terms} | {missing_docs} |")

    benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), dict) else None
    if benchmark:
        bench_metrics = benchmark.get("metrics", {}) if isinstance(benchmark.get("metrics"), dict) else {}
        lines.extend(
            [
                "",
                "## Benchmark",
                "",
                f"- Cutoff: `{benchmark.get('cutoff', '')}`",
                f"- Hit rate: `{_as_float(bench_metrics.get('hit_rate')):.2%}`",
                f"- MRR: `{_as_float(bench_metrics.get('mrr')):.4f}`",
                f"- Precision@k: `{_as_float(bench_metrics.get('precision_at_k')):.4f}`",
                f"- Recall@k: `{_as_float(bench_metrics.get('recall_at_k')):.4f}`",
                f"- nDCG@k: `{_as_float(bench_metrics.get('ndcg_at_k')):.4f}`",
                f"- MAP@k: `{_as_float(bench_metrics.get('map_at_k')):.4f}`",
                f"- Empty result rate: `{_as_float(bench_metrics.get('empty_result_rate')):.2%}`",
            ]
        )
        if "wrong_document_rate" in bench_metrics:
            lines.append(f"- Wrong-document rate: `{_as_float(bench_metrics.get('wrong_document_rate')):.2%}`")
        if "tag_pollution_rate" in bench_metrics:
            lines.append(f"- Tag pollution rate: `{_as_float(bench_metrics.get('tag_pollution_rate')):.2%}`")
        if "expected_tag_hit_rate" in bench_metrics:
            lines.append(f"- Expected tag hit rate: `{_as_float(bench_metrics.get('expected_tag_hit_rate')):.2%}`")
        if "unexpected_tag_hit_rate" in bench_metrics:
            lines.append(f"- Unexpected tag hit rate: `{_as_float(bench_metrics.get('unexpected_tag_hit_rate')):.2%}`")
        if "strict_chunk_recall_at_k" in bench_metrics:
            lines.extend(
                [
                    f"- Strict chunk recall@k: `{_as_float(bench_metrics.get('strict_chunk_recall_at_k')):.4f}`",
                    f"- Expected chunk hit rate: `{_as_float(bench_metrics.get('expected_chunk_hit_rate')):.2%}`",
                    f"- Expected evidence rank: `{_as_float(bench_metrics.get('expected_evidence_rank')):.4f}`",
                ]
            )
        lines.extend(
            [
                "",
                "| id | type | hit | mrr | precision@k | recall@k | ndcg@k | map@k |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in benchmark.get("per_query", []) if isinstance(benchmark.get("per_query"), list) else []:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| `{item.get('id', '')}` | {item.get('query_type', '')} | "
                f"{_as_float(item.get('hit_rate')):.0%} | {_as_float(item.get('mrr')):.4f} | "
                f"{_as_float(item.get('precision_at_k')):.4f} | {_as_float(item.get('recall_at_k')):.4f} | "
                f"{_as_float(item.get('ndcg_at_k')):.4f} | {_as_float(item.get('map_at_k')):.4f} |"
            )
        gate = benchmark.get("gate") if isinstance(benchmark.get("gate"), dict) else None
        if gate:
            lines.extend(["", "## Gate", ""])
            lines.append(f"- Status: `{'passed' if gate.get('ok') else 'failed'}`")
            lines.extend(["", "| metric | actual | operator | threshold | status |", "|---|---:|---|---:|---|"])
            for check in gate.get("checks", []) if isinstance(gate.get("checks"), list) else []:
                if not isinstance(check, dict):
                    continue
                lines.append(
                    f"| `{check.get('metric', '')}` | `{_as_float(check.get('actual')):.4f}` | "
                    f"`{check.get('operator', '')}` | `{_as_float(check.get('threshold')):.4f}` | "
                    f"{'passed' if check.get('passed') else 'failed'} |"
                )

    metadata_summary = payload.get("metadata_summary") if isinstance(payload.get("metadata_summary"), dict) else None
    if metadata_summary:
        lines.extend(
            [
                "",
                "## Metadata Summary",
                "",
                f"- ok: `{str(bool(metadata_summary.get('ok'))).lower()}`",
                f"- documents: `{metadata_summary.get('document_count', 0)}`",
                f"- matched build documents: `{metadata_summary.get('matched_build_documents', 0)}`",
                f"- fields: `{', '.join(str(item) for item in metadata_summary.get('fields', []))}`",
                f"- tags: `{', '.join(str(item) for item in metadata_summary.get('tags', []))}`",
                "",
            ]
        )
    lines.append("")
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
        payload = report.to_dict(max_chunks=args.max_report_chunks, include_raw=args.include_raw)
        if metadata_summary:
            payload["metadata_summary"] = metadata_summary
        markdown = _render_markdown_with_metadata(report, metadata_summary)
        if args.redaction_report:
            payload, redaction_report = sanitize_cli_report(
                payload,
                args,
                input_paths=[
                    args.kb_manifest,
                    args.queries,
                    args.qrels,
                    args.gate_config,
                    args.baseline_report,
                    args.chunk_snapshot,
                    args.metadata,
                    args.config,
                ],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
                context_json_paths=[
                    args.kb_manifest,
                    args.queries,
                    args.qrels,
                    args.gate_config,
                    args.baseline_report,
                    args.chunk_snapshot,
                    args.metadata,
                    args.config,
                ],
                config=config,
            )
            _write_json_file(args.redaction_report, redaction_report)
            markdown = _render_markdown_from_payload(payload)
        rendered_json = json.dumps(payload, ensure_ascii=False, indent=2)
        _write_text(args.report_json, rendered_json + "\n")
        _write_text(args.report_md, markdown)
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
    parser.add_argument("--include-raw", action="store_true", help="Include raw chunk payloads in top_chunks for downstream diagnostics")
    parser.add_argument("--report-json", help="Optional JSON report output path")
    parser.add_argument("--report-md", help="Optional Markdown report output path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file to summarize and lint before validation")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
