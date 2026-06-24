#!/usr/bin/env python3
"""Build a RAGFlow knowledge base from Markdown inputs."""

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
    BuildError,
    HandoffError,
    RAGFlowClient,
    discover_markdown_documents,
    inspect_rich_handoff,
    load_config,
    load_doc_manifest,
    load_profile,
    lint_metadata_file,
    lint_tagset_file,
    make_kb_manifest_payload,
    make_metadata_template_payload,
    make_tagset_template_payload,
    merge_metadata_payloads,
    render_handoff_inspection_markdown,
    render_governance_markdown,
    gate_benchmark_report,
    import_benchmark_dataset,
    preflight_benchmark_dataset,
    render_benchmark_governance_markdown,
    sample_benchmark_dataset,
    snapshot_chunks,
    summarize_benchmark_report,
    trend_benchmark_reports,
    delta_benchmark_reports,
    summarize_metadata_for_documents,
    export_tagset_file,
    tagset_report_file,
    wait_for_document_states,
)
from ragflow_skill_runtime.benchmark_governance import BenchmarkGovernanceError  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.kb_build import extract_dataset_id, extract_uploaded_document_id  # noqa: E402
from ragflow_skill_runtime.metadata_governance import MetadataGovernanceError  # noqa: E402
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402


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


def _guard_quality_gate(doc_manifest, *, allow_blocked: bool) -> None:
    if not doc_manifest or allow_blocked:
        return
    gate = getattr(doc_manifest, "quality_gate", {}) or {}
    status = gate.get("status") if isinstance(gate, dict) else None
    if status == "BLOCKED":
        raise BuildError(
            "doc_manifest quality gate is BLOCKED; inspect the quality report or pass "
            "--allow-blocked to upload anyway"
        )


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text_file(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        metadata_summary = summarize_metadata_for_documents(args.metadata, [doc.path for doc in docs])
        if metadata_summary and not metadata_summary.get("ok", False):
            raise BuildError("metadata lint failed; run metadata lint for details")
        if args.dry_run:
            _dump_json(
                {
                    "ok": True,
                    "dry_run": True,
                    "kb_name": args.kb_name,
                    "profile": profile.to_manifest_dict(),
                    "documents": [str(doc.path) for doc in docs],
                    "metadata_summary": metadata_summary,
                }
            )
            return 0

        config = _load_config(args)
        client = RAGFlowClient(config)
        dataset_response = client.create_dataset(args.kb_name, profile=profile.to_dataset_payload())
        dataset_id = extract_dataset_id(dataset_response)

        uploaded = []
        document_ids: list[str] = []
        for doc in docs:
            response = client.upload_document(dataset_id, doc.path)
            document_id = extract_uploaded_document_id(response)
            document_ids.append(document_id)
            uploaded.append((doc, document_id, "uploaded", None))

        parse_response = None
        live_states = {}
        if document_ids and not args.no_parse:
            parse_response = client.trigger_parse(dataset_id, document_ids)
            if not args.no_wait:
                live_states = wait_for_document_states(
                    client,
                    dataset_id=dataset_id,
                    document_ids=document_ids,
                    timeout=args.parse_timeout,
                    poll_interval=args.poll_interval,
                )
                uploaded = [
                    (
                        doc,
                        document_id,
                        live_states.get(document_id, {}).get("status", status),
                        live_states.get(document_id, {}).get("chunk_count", chunk_count),
                    )
                    for doc, document_id, status, chunk_count in uploaded
                ]

        payload = make_kb_manifest_payload(
            base_url=config.base_url,
            dataset_id=dataset_id,
            dataset_name=args.kb_name,
            profile=profile,
            documents=uploaded,
        )
        if metadata_summary:
            payload["metadata_summary"] = metadata_summary
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": True,
                "kb_manifest": str(output),
                "dataset_id": dataset_id,
                "document_count": len(uploaded),
                "parse_triggered": not args.no_parse,
                "parse_waited": not args.no_parse and not args.no_wait,
                "parse_response": parse_response,
            }
        )
        return 0
    except (BuildError, ConfigError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect_handoff(args: argparse.Namespace) -> int:
    try:
        report = inspect_rich_handoff(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
        )
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_handoff_inspection_markdown(report), encoding="utf-8")
        _dump_json({"ok": True, "handoff": report})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_metadata_file(args.metadata)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_merge(args: argparse.Namespace) -> int:
    try:
        report = merge_metadata_payloads(
            doc_manifest_path=args.doc_manifest,
            handoff_metadata_path=args.handoff_metadata,
            user_metadata_path=args.metadata,
            derive_from_path=not args.no_derive_from_path,
        )
        _write_json_file(args.output, report["metadata"])
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Merge Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_metadata_template_payload(doc_manifest_path=args.doc_manifest)
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "document_count": len(payload["documents"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_tagset_file(args.tagset)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_export(args: argparse.Namespace) -> int:
    try:
        exported = export_tagset_file(args.tagset, fmt=args.format)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(exported, str):
            output.write_text(exported, encoding="utf-8")
        else:
            output.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _dump_json({"ok": True, "schema": "ragflow_tagset_export_result_v1", "format": args.format, "output": str(output)})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_report(args: argparse.Namespace) -> int:
    try:
        report = tagset_report_file(args.tagset, metadata_path=args.metadata)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_tagset_template_payload()
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "tag_count": len(payload["tags"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_import(args: argparse.Namespace) -> int:
    try:
        report = import_benchmark_dataset(
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            output_dir=args.output,
            name=args.name,
            description=args.description or "",
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Import Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_snapshot_chunks(args: argparse.Namespace) -> int:
    try:
        report = snapshot_chunks(
            input_path=args.input,
            output_path=args.output,
            name=args.name,
            description=args.description or "",
            include_content=args.include_content,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Chunk Snapshot Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_preflight(args: argparse.Namespace) -> int:
    try:
        report = preflight_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Preflight Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_sample(args: argparse.Namespace) -> int:
    try:
        report = sample_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            output_dir=args.output,
            sample_size=args.size,
            sample_fraction=args.fraction,
            strategy=args.strategy,
            seed=args.seed,
            name=args.name,
            description=args.description or "",
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Sample Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_summarize(args: argparse.Namespace) -> int:
    try:
        report = summarize_benchmark_report(args.report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Summary Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_gate(args: argparse.Namespace) -> int:
    try:
        report = gate_benchmark_report(
            report_path=args.report,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Gate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_trend(args: argparse.Namespace) -> int:
    try:
        report = trend_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Trend Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_delta(args: argparse.Namespace) -> int:
    try:
        report = delta_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Delta Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def build_inspect_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Markdown handoff and optional rich sidecars")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--report-json", help="Optional JSON inspection report path")
    parser.add_argument("--report-md", help="Optional Markdown inspection report path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, merge, and template public RAGFlow metadata")
    subparsers = parser.add_subparsers(dest="metadata_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_metadata_v1 file")
    lint.add_argument("--metadata", required=True, help="Metadata JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_metadata_lint)

    merge = subparsers.add_parser("merge", help="Merge path-derived, handoff, and user metadata")
    merge.add_argument("--doc-manifest", help="Optional doc_manifest.json")
    merge.add_argument("--handoff-metadata", help="Optional rich handoff metadata.json")
    merge.add_argument("--metadata", help="Optional user ragflow_metadata_v1 file")
    merge.add_argument("--output", required=True, help="Output merged ragflow_metadata_v1 JSON")
    merge.add_argument("--report-json", help="Optional JSON merge report path")
    merge.add_argument("--report-md", help="Optional Markdown merge report path")
    merge.add_argument("--no-derive-from-path", action="store_true", help="Do not fill missing fields from document paths")
    merge.add_argument("--json", action="store_true", help="Emit JSON errors")
    merge.set_defaults(func=_run_metadata_merge)

    template = subparsers.add_parser("generate-template", help="Generate a user-editable metadata template")
    template.add_argument("--doc-manifest", help="Optional doc_manifest.json used to list document paths")
    template.add_argument("--output", required=True, help="Output metadata template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_metadata_generate_template)

    return parser


def build_tagset_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, export, and report public RAGFlow tagsets")
    subparsers = parser.add_subparsers(dest="tagset_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_tagset_v1 file")
    lint.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_tagset_lint)

    export = subparsers.add_parser("export", help="Export tagset tags as JSON or CSV")
    export.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    export.add_argument("--format", choices=("json", "csv"), default="json", help="Export format")
    export.add_argument("--output", required=True, help="Output JSON or CSV path")
    export.add_argument("--json", action="store_true", help="Emit JSON errors")
    export.set_defaults(func=_run_tagset_export)

    report = subparsers.add_parser("report", help="Report tag coverage, duplicates, and orphan warnings")
    report.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    report.add_argument("--metadata", help="Optional metadata file for document coverage checks")
    report.add_argument("--report-json", help="Optional JSON report path")
    report.add_argument("--report-md", help="Optional Markdown report path")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_tagset_report)

    template = subparsers.add_parser("generate-template", help="Generate a placeholder tagset template")
    template.add_argument("--output", required=True, help="Output tagset template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_tagset_generate_template)

    return parser


def build_snapshot_chunks_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a stable chunk snapshot from local chunks or validation output")
    parser.add_argument("--input", required=True, help="Input validation/retrieval JSON report, Markdown file, or Markdown directory")
    parser.add_argument("--output", required=True, help="Output ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument("--name", default="chunk-snapshot", help="Chunk snapshot name")
    parser.add_argument("--description", help="Optional chunk snapshot description")
    parser.add_argument("--include-content", action="store_true", help="Include full chunk content in the snapshot")
    parser.add_argument("--report-json", help="Optional snapshot report JSON path")
    parser.add_argument("--report-md", help="Optional snapshot report Markdown path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_snapshot_chunks)
    return parser


def build_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import, sample, preflight, summarize, and gate benchmark artifacts")
    subparsers = parser.add_subparsers(dest="benchmark_command", required=True)

    import_cmd = subparsers.add_parser("import", help="Normalize query/qrels files into a benchmark directory")
    import_cmd.add_argument("--queries", required=True, help="Input benchmark query set JSON")
    import_cmd.add_argument("--qrels", required=True, help="Input benchmark qrels JSON")
    import_cmd.add_argument("--qa", help="Optional grounded QA JSON")
    import_cmd.add_argument("--output", required=True, help="Output benchmark directory")
    import_cmd.add_argument("--name", default="benchmark", help="Benchmark name recorded in manifest")
    import_cmd.add_argument("--description", help="Optional benchmark description")
    import_cmd.add_argument("--report-json", help="Optional import report JSON path")
    import_cmd.add_argument("--report-md", help="Optional import report Markdown path")
    import_cmd.add_argument("--json", action="store_true", help="Emit JSON errors")
    import_cmd.set_defaults(func=_run_benchmark_import)

    preflight = subparsers.add_parser("preflight", help="Check benchmark artifacts before live validation")
    preflight.add_argument("--manifest", help="Benchmark manifest.json")
    preflight.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    preflight.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    preflight.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    preflight.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 file for expected_chunks checks")
    preflight.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    preflight.add_argument("--report-json", help="Optional preflight report JSON path")
    preflight.add_argument("--report-md", help="Optional preflight report Markdown path")
    preflight.add_argument("--json", action="store_true", help="Emit JSON errors")
    preflight.set_defaults(func=_run_benchmark_preflight)

    sample = subparsers.add_parser("sample", help="Create a deterministic benchmark subset")
    sample.add_argument("--manifest", help="Benchmark manifest.json")
    sample.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    sample.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    sample.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    sample.add_argument("--output", required=True, help="Output sampled benchmark directory")
    sample.add_argument("--size", type=int, help="Number of queries to sample")
    sample.add_argument("--fraction", type=float, help="Fraction of queries to sample")
    sample.add_argument("--strategy", choices=("first", "random", "stratified"), default="stratified", help="Sampling strategy")
    sample.add_argument("--seed", type=int, default=0, help="Deterministic sampling seed")
    sample.add_argument("--name", default="benchmark-sample", help="Benchmark sample name recorded in manifest")
    sample.add_argument("--description", help="Optional benchmark sample description")
    sample.add_argument("--report-json", help="Optional sample report JSON path")
    sample.add_argument("--report-md", help="Optional sample report Markdown path")
    sample.add_argument("--json", action="store_true", help="Emit JSON errors")
    sample.set_defaults(func=_run_benchmark_sample)

    summarize = subparsers.add_parser("summarize", help="Summarize an existing benchmark validation report")
    summarize.add_argument("--report", required=True, help="Benchmark validation report JSON")
    summarize.add_argument("--report-json", help="Optional summary report JSON path")
    summarize.add_argument("--report-md", help="Optional summary report Markdown path")
    summarize.add_argument("--json", action="store_true", help="Emit JSON errors")
    summarize.set_defaults(func=_run_benchmark_summarize)

    gate = subparsers.add_parser("gate", help="Apply a gate config to an existing benchmark validation report")
    gate.add_argument("--report", required=True, help="Benchmark validation report JSON")
    gate.add_argument("--gate-config", required=True, help="Benchmark gate threshold JSON")
    gate.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    gate.add_argument("--report-json", help="Optional gate report JSON path")
    gate.add_argument("--report-md", help="Optional gate report Markdown path")
    gate.add_argument("--json", action="store_true", help="Emit JSON errors")
    gate.set_defaults(func=_run_benchmark_gate)

    trend = subparsers.add_parser("trend", help="Compare current benchmark metrics with a baseline report")
    trend.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    trend.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    trend.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    trend.add_argument("--report-json", help="Optional trend report JSON path")
    trend.add_argument("--report-md", help="Optional trend report Markdown path")
    trend.add_argument("--json", action="store_true", help="Emit JSON errors")
    trend.set_defaults(func=_run_benchmark_trend)

    delta = subparsers.add_parser("delta", help="Report metric deltas between two benchmark reports")
    delta.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    delta.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    delta.add_argument("--report-json", help="Optional delta report JSON path")
    delta.add_argument("--report-md", help="Optional delta report Markdown path")
    delta.add_argument("--json", action="store_true", help="Emit JSON errors")
    delta.set_defaults(func=_run_benchmark_delta)

    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a RAGFlow KB from Markdown")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="RAGFlow dataset name")
    parser.add_argument("--profile", required=True, help="Chunk profile JSON/YAML")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file to summarize and lint before upload")
    parser.add_argument("--output", default="kb_manifest.json", help="Output kb_manifest.json path for non-dry-run builds")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without touching RAGFlow or writing kb_manifest.json")
    parser.add_argument("--no-parse", action="store_true", help="Upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for parse completion after triggering parse")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow upload when doc_manifest quality_gate.status is BLOCKED")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds while waiting for parse completion")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect-handoff":
            return _run_inspect_handoff(build_inspect_handoff_parser().parse_args(command_args))
        if command == "metadata":
            metadata_args = build_metadata_parser().parse_args(command_args)
            return metadata_args.func(metadata_args)
        if command == "tagset":
            tagset_args = build_tagset_parser().parse_args(command_args)
            return tagset_args.func(tagset_args)
        if command == "snapshot-chunks":
            snapshot_args = build_snapshot_chunks_parser().parse_args(command_args)
            return snapshot_args.func(snapshot_args)
        if command == "benchmark":
            benchmark_args = build_benchmark_parser().parse_args(command_args)
            return benchmark_args.func(benchmark_args)
    args = build_parser().parse_args(actual_argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
