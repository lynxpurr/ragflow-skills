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
    create_optimization_cleanup_plan,
    create_optimization_plan,
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
    map_grounded_qa_evidence,
    merge_metadata_payloads,
    probe_model_providers,
    configured_private_hosts_from_urls,
    create_kb_activation_plan,
    create_kb_split_plan,
    create_kb_topology_advice,
    render_handoff_inspection_markdown,
    render_governance_markdown,
    render_model_provider_probe_markdown,
    gate_benchmark_report,
    import_benchmark_dataset,
    preflight_benchmark_dataset,
    render_best_profile_markdown,
    render_benchmark_governance_markdown,
    render_optimization_cleanup_plan_markdown,
    render_suppression_report_markdown,
    sample_benchmark_dataset,
    segment_metadata_report_file,
    render_activation_plan_markdown,
    render_split_plan_markdown,
    render_topology_advice_markdown,
    render_optimization_plan_markdown,
    snapshot_chunks,
    suggest_benchmark_retrieval_parameters,
    summarize_optimization_results,
    summarize_benchmark_report,
    suppression_report_file,
    trend_benchmark_reports,
    delta_benchmark_reports,
    summarize_metadata_for_documents,
    export_tagset_file,
    tagset_report_file,
    generate_grounded_qa,
    validate_grounded_qa,
    wait_for_document_states,
    sanitize_report_payload,
)
from ragflow_skill_runtime.benchmark_governance import BenchmarkGovernanceError  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.kb_build import extract_dataset_id, extract_uploaded_document_id  # noqa: E402
from ragflow_skill_runtime.metadata_governance import MetadataGovernanceError  # noqa: E402
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402
from ragflow_skill_runtime.topology import TopologyError  # noqa: E402


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


def _run_benchmark_suggest(args: argparse.Namespace) -> int:
    try:
        report = suggest_benchmark_retrieval_parameters(
            report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
            current_top_k=args.current_top_k,
            current_similarity_threshold=args.current_similarity_threshold,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Retrieval Suggestions"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_suppression_report(args: argparse.Namespace) -> int:
    try:
        report = suppression_report_file(
            args.report,
            tagset_path=args.tagset,
            max_candidates=args.max_candidates,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_suppression_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_validate(args: argparse.Namespace) -> int:
    try:
        report = validate_grounded_qa(
            qa_path=args.qa,
            sources_path=args.sources,
            source_dir=args.source_dir,
            require_answer=not args.allow_missing_answer,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Validate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_generate(args: argparse.Namespace) -> int:
    try:
        report = generate_grounded_qa(
            output_path=args.output,
            sources_path=args.sources,
            source_dir=args.source_dir,
            count=args.count,
            strategy=args.strategy,
            seed=args.seed,
            min_span_chars=args.min_span_chars,
            max_span_chars=args.max_span_chars,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Generate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_map_evidence(args: argparse.Namespace) -> int:
    try:
        report = map_grounded_qa_evidence(
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            output_path=args.output,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow QA Evidence Map Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_segment_metadata_report(args: argparse.Namespace) -> int:
    try:
        report = segment_metadata_report_file(
            chunk_snapshot_path=args.chunk_snapshot,
            metadata_path=args.metadata,
            segmentation_plan_path=args.segmentation_plan,
        )
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Segment Metadata Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize(args: argparse.Namespace) -> int:
    try:
        if args.execute:
            raise ProfileError("optimize --execute is not implemented yet; use --plan-only for offline planning")
        if not args.plan_only:
            raise ProfileError("optimize currently requires --plan-only")
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        plan = create_optimization_plan(
            kb_name=args.kb_name,
            document_paths=[doc.path for doc in docs],
            input_path=args.input,
            doc_manifest_path=args.doc_manifest,
            profile_paths=args.profile,
            profile_dirs=args.profile_dir,
            profile_set_paths=args.profile_set,
            recommendations=args.recommendation,
            benchmark_manifest_path=args.benchmark_manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            metadata_path=args.metadata,
            tagset_path=args.tagset,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
            artifact_dir=args.artifact_dir,
            run_id=args.run_id,
            top_k=args.top_k,
            metric_cutoff=args.metric_cutoff,
        )
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (BuildError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_summarize(args: argparse.Namespace) -> int:
    try:
        results = summarize_optimization_results(
            plan_path=args.plan,
            report_paths=args.report,
        )
        _write_json_file(args.output, results)
        _write_text_file(args.report_md, render_best_profile_markdown(results))
        _dump_json(results)
        return 0 if results["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_cleanup_plan(args: argparse.Namespace) -> int:
    try:
        plan = create_optimization_cleanup_plan(
            plan_path=args.plan,
            cleanup_script=args.cleanup_script,
            config_path=args.config,
            require_manifests=args.require_manifests,
        )
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_cleanup_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_advise(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_topology_advice(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            route_config_path=args.route_config,
            future_growth=args.future_growth,
            min_documents=args.min_documents,
            min_total_chars=args.min_total_chars,
        )
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_topology_advice_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_split_plan(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_split_plan(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            min_group_documents=args.min_group_documents,
            min_group_estimated_chunks=args.min_group_estimated_chunks,
        )
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_split_plan_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_activation_plan(args: argparse.Namespace) -> int:
    try:
        report = create_kb_activation_plan(
            kb_manifest_path=args.kb_manifest,
            doc_manifest_path=args.doc_manifest,
            route_config_path=args.route_config,
            retrieval_hints_path=args.retrieval_hints,
            chunk_snapshot_path=args.chunk_snapshot,
            centroid_index_path=args.centroid_index,
            route_tests_path=args.route_tests,
            min_documents=args.min_documents,
            min_chunks=args.min_chunks,
        )
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_activation_plan_markdown(report))
        _dump_json(report)
        return 0
    except (TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_model_provider_report(report: dict[str, Any], args: argparse.Namespace, config: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [config.base_url, args.embedding_adapter_url, args.rerank_adapter_url]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[config.api_key, args.embedding_adapter_api_key, args.rerank_adapter_api_key],
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[args.config],
    )
    return sanitized, redaction_report


def _run_model_providers_probe(args: argparse.Namespace) -> int:
    try:
        overrides: dict[str, Any] = {}
        if args.base_url:
            overrides["base_url"] = args.base_url
        if args.api_key:
            overrides["api_key"] = args.api_key
        if args.timeout is not None:
            overrides["timeout"] = args.timeout
        config = load_config(config_file=args.config, overrides=overrides)
        client = RAGFlowClient(config)
        report = probe_model_providers(
            client,
            endpoint_paths=args.endpoint,
            expected_embedding_models=args.embedding_model,
            expected_rerank_models=args.rerank_model,
            embedding_adapter_url=args.embedding_adapter_url,
            embedding_adapter_api_key=args.embedding_adapter_api_key,
            embedding_adapter_shape=args.embedding_adapter_shape,
            rerank_adapter_url=args.rerank_adapter_url,
            rerank_adapter_api_key=args.rerank_adapter_api_key,
            rerank_adapter_shape=args.rerank_adapter_shape,
            adapter_timeout=args.adapter_timeout,
        )
        report, redaction_report = _sanitize_model_provider_report(report, args, config)
        _write_json_file(args.report_json, report)
        _write_json_file(args.redaction_report, redaction_report)
        _write_text_file(args.report_md, render_model_provider_probe_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
        return _error(str(exc), json_output=args.json)


def build_inspect_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Markdown handoff and optional rich sidecars")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--report-json", help="Optional JSON inspection report path")
    parser.add_argument("--report-md", help="Optional Markdown inspection report path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_model_providers_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe RAGFlow model-provider registration without mutating KBs")
    subparsers = parser.add_subparsers(dest="model_providers_command", required=True)

    probe = subparsers.add_parser("probe", help="Probe read-only model-provider endpoints")
    probe.add_argument("--config", help="Runtime config file")
    probe.add_argument("--base-url", help="RAGFlow base URL")
    probe.add_argument("--api-key", help="RAGFlow API key")
    probe.add_argument("--timeout", type=float, help="HTTP timeout seconds")
    probe.add_argument("--endpoint", action="append", default=[], help="Provider endpoint path to probe; repeatable")
    probe.add_argument("--embedding-model", action="append", default=[], help="Expected embedding model name; repeatable")
    probe.add_argument("--rerank-model", action="append", default=[], help="Expected rerank model name; repeatable")
    probe.add_argument("--embedding-adapter-url", help="Explicit embedding adapter URL for empty-input request-shape probe")
    probe.add_argument("--embedding-adapter-api-key", help="Embedding adapter bearer token")
    probe.add_argument(
        "--embedding-adapter-shape",
        choices=("openai", "generic"),
        default="openai",
        help="Embedding adapter request shape",
    )
    probe.add_argument("--rerank-adapter-url", help="Explicit rerank adapter URL for empty-input request-shape probe")
    probe.add_argument("--rerank-adapter-api-key", help="Rerank adapter bearer token")
    probe.add_argument(
        "--rerank-adapter-shape",
        choices=("cohere", "generic"),
        default="cohere",
        help="Rerank adapter request shape",
    )
    probe.add_argument("--adapter-timeout", type=float, default=5.0, help="Adapter empty-input probe timeout seconds")
    probe.add_argument("--report-json", help="Optional JSON probe report path")
    probe.add_argument("--report-md", help="Optional Markdown probe report path")
    probe.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    probe.add_argument("--json", action="store_true", help="Emit JSON errors")
    probe.set_defaults(func=_run_model_providers_probe)

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

    suggest = subparsers.add_parser("suggest", help="Suggest retrieval parameter experiments from a benchmark report")
    suggest.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    suggest.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    suggest.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    suggest.add_argument("--current-top-k", type=int, help="Current retrieval top_k, defaults to benchmark cutoff when available")
    suggest.add_argument("--current-similarity-threshold", type=float, help="Current retrieval similarity threshold")
    suggest.add_argument("--report-json", help="Optional suggestion report JSON path")
    suggest.add_argument("--report-md", help="Optional suggestion report Markdown path")
    suggest.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest.set_defaults(func=_run_benchmark_suggest)

    return parser


def build_suppression_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create advisory suppression candidates from an existing validation report")
    parser.add_argument("--report", required=True, help="Validation or benchmark validation report JSON")
    parser.add_argument("--tagset", help="Optional ragflow_tagset_v1 JSON/YAML for tag labels and aliases")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum candidates to include in the report")
    parser.add_argument("--report-json", help="Optional suppression report JSON path")
    parser.add_argument("--report-md", help="Optional suppression report Markdown path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_suppression_report)
    return parser


def build_qa_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and validate grounded QA artifacts before benchmark use")
    subparsers = parser.add_subparsers(dest="qa_command", required=True)

    generate = subparsers.add_parser("generate", help="Generate deterministic grounded QA from source spans")
    generate.add_argument("--sources", help="Optional source text JSON/Markdown file")
    generate.add_argument("--source-dir", help="Optional directory of source text files")
    generate.add_argument("--output", required=True, help="Output ragflow_grounded_qa_v1 JSON")
    generate.add_argument("--count", type=int, default=20, help="Maximum QA items to generate")
    generate.add_argument("--strategy", choices=("first", "random"), default="first", help="Source span selection strategy")
    generate.add_argument("--seed", type=int, default=0, help="Deterministic seed for random strategy")
    generate.add_argument("--min-span-chars", type=int, default=40, help="Minimum evidence span length")
    generate.add_argument("--max-span-chars", type=int, default=240, help="Maximum evidence span length")
    generate.add_argument("--report-json", help="Optional generate report JSON path")
    generate.add_argument("--report-md", help="Optional generate report Markdown path")
    generate.add_argument("--json", action="store_true", help="Emit JSON errors")
    generate.set_defaults(func=_run_qa_generate)

    validate = subparsers.add_parser("validate", help="Validate grounded QA evidence spans")
    validate.add_argument("--qa", required=True, help="Grounded QA JSON")
    validate.add_argument("--sources", help="Optional source text JSON/Markdown file for exact evidence checks")
    validate.add_argument("--source-dir", help="Optional directory of source text files for exact evidence checks")
    validate.add_argument("--allow-missing-answer", action="store_true", help="Allow QA items without answers")
    validate.add_argument("--report-json", help="Optional validate report JSON path")
    validate.add_argument("--report-md", help="Optional validate report Markdown path")
    validate.add_argument("--json", action="store_true", help="Emit JSON errors")
    validate.set_defaults(func=_run_qa_validate)

    map_evidence = subparsers.add_parser("map-evidence", help="Map QA evidence spans onto a chunk snapshot")
    map_evidence.add_argument("--qa", required=True, help="Grounded QA JSON")
    map_evidence.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    map_evidence.add_argument("--output", required=True, help="Output ragflow_grounded_qa_evidence_map_v1 JSON")
    map_evidence.add_argument("--report-json", help="Optional map-evidence report JSON path")
    map_evidence.add_argument("--report-md", help="Optional map-evidence report Markdown path")
    map_evidence.add_argument("--json", action="store_true", help="Emit JSON errors")
    map_evidence.set_defaults(func=_run_qa_map_evidence)

    return parser


def build_segment_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report segment provenance metadata coverage for chunk snapshots")
    subparsers = parser.add_subparsers(dest="segment_metadata_command", required=True)

    report = subparsers.add_parser("report", help="Report segment and metadata coverage in a chunk snapshot")
    report.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    report.add_argument("--metadata", help="Optional ragflow_metadata_v1 JSON/YAML for document coverage")
    report.add_argument("--segmentation-plan", help="Optional doc_segmentation_plan_v1 JSON")
    report.add_argument("--report-json", help="Optional segment metadata report JSON path")
    report.add_argument("--report-md", help="Optional segment metadata report Markdown path")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_segment_metadata_report)

    return parser


def build_optimize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan RAGFlow profile optimization experiments")
    parser.add_argument("--plan-only", action="store_true", help="Create an offline optimization plan without mutating RAGFlow")
    parser.add_argument("--execute", action="store_true", help="Reserved for future live optimization execution")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="Base RAGFlow dataset name used for disposable KB naming")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    parser.add_argument("--profile", action="append", default=[], help="Candidate profile JSON/YAML path; may be repeated")
    parser.add_argument("--profile-dir", action="append", default=[], help="Directory of candidate profile JSON/YAML files; may be repeated")
    parser.add_argument("--profile-set", action="append", default=[], help="ragflow_candidate_profile_set_v1 JSON/YAML; may be repeated")
    parser.add_argument("--recommendation", action="append", default=[], help="Generated candidate as language:doc_type, e.g. en:manual")
    parser.add_argument("--benchmark-manifest", help="Benchmark manifest.json produced by benchmark import/sample")
    parser.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    parser.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    parser.add_argument("--qa", help="Optional grounded QA JSON")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file used by build/validation")
    parser.add_argument("--tagset", help="Optional tagset reference recorded in the plan")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 for strict chunk recall")
    parser.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    parser.add_argument("--baseline-report", help="Optional previous benchmark report JSON")
    parser.add_argument("--artifact-dir", default="optimization-artifacts", help="Planned experiment artifact directory")
    parser.add_argument("--run-id", help="Optional disposable KB run id; defaults to a deterministic hash")
    parser.add_argument("--top-k", type=int, default=3, help="Planned benchmark validation top_k")
    parser.add_argument("--metric-cutoff", type=int, help="Optional planned benchmark metric cutoff")
    parser.add_argument("--output", default="optimization_plan.json", help="Output ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization plan Markdown path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize)
    return parser


def build_optimize_summarize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize profile optimization validation reports")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report", action="append", default=[], help="Validation report JSON; defaults to paths in the plan")
    parser.add_argument("--output", default="profile_experiment_results.json", help="Output ragflow_profile_experiment_results_v1 JSON")
    parser.add_argument("--report-md", default="best_profile_report.md", help="Output best profile Markdown report")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_summarize)
    return parser


def build_optimize_cleanup_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating cleanup plan for profile optimization KBs")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--output", default="cleanup_plan.json", help="Output ragflow_optimization_cleanup_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization cleanup plan Markdown path")
    parser.add_argument("--cleanup-script", default="scripts/cleanup.py", help="Cleanup script path recorded in generated commands")
    parser.add_argument("--config", help="Optional runtime config path recorded in generated execute commands")
    parser.add_argument("--require-manifests", action="store_true", help="Fail when candidate kb_manifest files are not available yet")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_cleanup_plan)
    return parser


def build_topology_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create non-mutating KB topology advice")
    subparsers = parser.add_subparsers(dest="topology_command", required=True)

    advise = subparsers.add_parser("advise", help="Advise create, merge, split, or stage decisions")
    advise.add_argument("--input", help="Markdown file or directory")
    advise.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    advise.add_argument("--kb-name", required=True, help="Candidate RAGFlow dataset name")
    advise.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    advise.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    advise.add_argument("--route-config", help="Optional user-owned routing config for overlap checks")
    advise.add_argument(
        "--future-growth",
        choices=("low", "medium", "high"),
        default="medium",
        help="Expected future corpus growth for create-vs-merge advice",
    )
    advise.add_argument("--min-documents", type=int, default=3, help="Minimum documents for a standalone KB signal")
    advise.add_argument("--min-total-chars", type=int, default=1200, help="Minimum total Markdown chars for a standalone KB signal")
    advise.add_argument("--allow-blocked", action="store_true", help="Allow advice with a BLOCKED doc_manifest quality gate")
    advise.add_argument("--output", default="kb_topology_advice.json", help="Output kb_topology_advice_v1 JSON")
    advise.add_argument("--report-md", help="Optional topology advice Markdown path")
    advise.add_argument("--json", action="store_true", help="Emit JSON errors")
    advise.set_defaults(func=_run_topology_advise)

    split_plan = subparsers.add_parser("split-plan", help="Plan advisory KB splits by local corpus signals")
    split_plan.add_argument("--input", help="Markdown file or directory")
    split_plan.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    split_plan.add_argument("--kb-name", required=True, help="Source or candidate RAGFlow dataset name")
    split_plan.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    split_plan.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    split_plan.add_argument("--min-group-documents", type=int, default=1, help="Minimum documents for a standalone split group")
    split_plan.add_argument(
        "--min-group-estimated-chunks",
        type=int,
        default=1,
        help="Minimum estimated chunks for a standalone split group",
    )
    split_plan.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    split_plan.add_argument("--output", default="kb_split_plan.json", help="Output kb_split_plan_v1 JSON")
    split_plan.add_argument("--report-md", help="Optional split plan Markdown path")
    split_plan.add_argument("--json", action="store_true", help="Emit JSON errors")
    split_plan.set_defaults(func=_run_topology_split_plan)

    return parser


def build_activation_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating KB route activation plan")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--doc-manifest", help="Optional source doc_manifest.json for content quality checks")
    parser.add_argument("--route-config", help="Optional user-owned routing config")
    parser.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument("--centroid-index", help="Optional ragflow_route_centroid_index_v1 JSON")
    parser.add_argument("--route-tests", help="Optional route-test queries JSON")
    parser.add_argument("--min-documents", type=int, default=1, help="Minimum documents before activation")
    parser.add_argument("--min-chunks", type=int, default=1, help="Minimum chunks before activation")
    parser.add_argument("--output", default="kb_activation_plan.json", help="Output kb_activation_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional activation plan Markdown path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_activation_plan)
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
        if command == "model-providers":
            model_provider_args = build_model_providers_parser().parse_args(command_args)
            return model_provider_args.func(model_provider_args)
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
        if command == "suppression-report":
            suppression_args = build_suppression_report_parser().parse_args(command_args)
            return suppression_args.func(suppression_args)
        if command == "qa":
            qa_args = build_qa_parser().parse_args(command_args)
            return qa_args.func(qa_args)
        if command == "segment-metadata":
            segment_metadata_args = build_segment_metadata_parser().parse_args(command_args)
            return segment_metadata_args.func(segment_metadata_args)
        if command == "topology":
            topology_args = build_topology_parser().parse_args(command_args)
            return topology_args.func(topology_args)
        if command == "activation-plan":
            activation_plan_args = build_activation_plan_parser().parse_args(command_args)
            return activation_plan_args.func(activation_plan_args)
        if command == "optimize":
            if command_args and command_args[0] == "summarize":
                optimize_summary_args = build_optimize_summarize_parser().parse_args(command_args[1:])
                return optimize_summary_args.func(optimize_summary_args)
            if command_args and command_args[0] == "cleanup-plan":
                optimize_cleanup_args = build_optimize_cleanup_plan_parser().parse_args(command_args[1:])
                return optimize_cleanup_args.func(optimize_cleanup_args)
            optimize_args = build_optimize_parser().parse_args(command_args)
            return optimize_args.func(optimize_args)
    args = build_parser().parse_args(actual_argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
