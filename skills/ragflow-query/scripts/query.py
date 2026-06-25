#!/usr/bin/env python3
"""Portable RAGFlow query CLI."""

from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import time
from typing import Any


def bootstrap_core() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_core()

from ragflow_skill_runtime import (  # noqa: E402
    ConfigError,
    NormalizedChunk,
    QueryResult,
    QueryRewriteError,
    RAGFlowClient,
    RetrievalError,
    RoutingError,
    audit_citations,
    build_query_rewrite_plan,
    build_query_trace,
    diagnose_query_result,
    evidence_from_query_payload,
    load_pollution_terms,
    load_route_test_queries,
    load_config,
    load_fusion_test_cases,
    load_kb_manifest,
    load_multi_query_file,
    load_routing_config,
    normalize_retrieval_response,
    query_fusion_report,
    query_pollution_report,
    query_rerank_ab_report,
    render_citation_audit_markdown,
    render_query_fusion_markdown,
    render_query_fusion_test_markdown,
    render_query_diagnostic_markdown,
    render_query_pollution_markdown,
    render_query_rerank_ab_markdown,
    render_query_rewrite_markdown,
    render_query_trace_markdown,
    render_route_report_markdown,
    render_route_test_markdown,
    run_fusion_tests,
    resolve_dataset_ids,
    route_question,
    run_route_report,
    run_route_tests,
    weight_evidence,
)


def _json_dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    payload = {"ok": False, "error": message}
    if json_output:
        _json_dump(payload)
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_runtime(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _routing_config_path(args: argparse.Namespace) -> str | None:
    return getattr(args, "routing_config", None) or os.environ.get("RAGFLOW_ROUTING_CONFIG")


def _load_routing(args: argparse.Namespace):
    path = _routing_config_path(args)
    if not path:
        raise RoutingError("routing config is required; pass --routing-config or set RAGFLOW_ROUTING_CONFIG")
    return load_routing_config(path)


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _write_json(path: str | None, data: Any) -> None:
    if path:
        _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fused_chunks(report: dict[str, Any]) -> list[NormalizedChunk]:
    chunks: list[NormalizedChunk] = []
    for item in report.get("results", []):
        if not isinstance(item, dict):
            continue
        components = item.get("score_components")
        first_component = components[0] if isinstance(components, list) and components and isinstance(components[0], dict) else {}
        dataset_ids = first_component.get("dataset_ids") if isinstance(first_component, dict) else []
        chunks.append(
            NormalizedChunk(
                content=str(item.get("content") or item.get("content_preview") or ""),
                similarity=float(item.get("rrf_score") or 0.0),
                document_name=item.get("document_name") if isinstance(item.get("document_name"), str) else None,
                document_id=item.get("document_id") if isinstance(item.get("document_id"), str) else None,
                dataset_id=str(dataset_ids[0]) if isinstance(dataset_ids, list) and dataset_ids else None,
                chunk_id=item.get("chunk_id") if isinstance(item.get("chunk_id"), str) else None,
                raw=dict(item),
            )
        )
    return chunks


def _llm_configured(config: Any) -> bool:
    return bool(getattr(config, "llm_base_url", None) and getattr(config, "llm_api_key", None))


def _build_retrieval_payload(
    *,
    question: str,
    source: str,
    query_id: str,
    query_kind: str,
    dataset_ids: list[str],
    chunks: list[NormalizedChunk],
    include_raw: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "question": question,
        "source": source,
        "query_id": query_id,
        "query_kind": query_kind,
        "dataset_ids": list(dataset_ids),
        "chunks": [chunk.to_dict(include_raw=include_raw) for chunk in chunks],
        "evidence": weight_evidence(question, chunks),
    }


def _retrieve_query_payloads(
    *,
    client: RAGFlowClient,
    retrieval_queries: list[dict[str, Any]],
    dataset_ids: list[str],
    top_k: int,
    similarity_threshold: float | None,
    fusion: str,
    include_raw: bool,
) -> tuple[list[dict[str, Any]], list[NormalizedChunk], dict[str, Any] | None, int]:
    payloads: list[dict[str, Any]] = []
    normalized_by_payload: list[list[NormalizedChunk]] = []
    retrieval_calls = 0
    for query_item in retrieval_queries:
        query = str(query_item["query"])
        query_id = str(query_item.get("id") or "query")
        query_kind = str(query_item.get("kind") or "")
        source_prefix = str(query_item.get("source") or query_id)
        if fusion == "rrf" and len(dataset_ids) > 1:
            for dataset_id in dataset_ids:
                raw = client.retrieve(
                    question=query,
                    dataset_ids=[dataset_id],
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                )
                retrieval_calls += 1
                chunks = normalize_retrieval_response(raw)
                normalized_by_payload.append(chunks)
                payloads.append(
                    _build_retrieval_payload(
                        question=query,
                        source=f"{source_prefix}:{query_id}:{dataset_id}",
                        query_id=query_id,
                        query_kind=query_kind,
                        dataset_ids=[dataset_id],
                        chunks=chunks,
                        include_raw=include_raw,
                    )
                )
        else:
            raw = client.retrieve(
                question=query,
                dataset_ids=dataset_ids,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )
            retrieval_calls += 1
            chunks = normalize_retrieval_response(raw)
            normalized_by_payload.append(chunks)
            payloads.append(
                _build_retrieval_payload(
                    question=query,
                    source=f"{source_prefix}:{query_id}",
                    query_id=query_id,
                    query_kind=query_kind,
                    dataset_ids=dataset_ids,
                    chunks=chunks,
                    include_raw=include_raw,
                )
            )
    if len(payloads) == 1 and not (fusion == "rrf" and len(dataset_ids) > 1):
        return payloads, normalized_by_payload[0], None, retrieval_calls
    fusion_report = query_fusion_report(payloads, top_k=top_k)
    return payloads, _fused_chunks(fusion_report), fusion_report, retrieval_calls


def _ask(args: argparse.Namespace) -> int:
    mode = args.mode
    route_result = None
    routed_params: dict[str, Any] = {}
    explicit_dataset_inputs = bool(args.dataset_id or args.kb or args.kb_manifest)
    started_at = _utc_now()
    total_start = time.perf_counter()
    retrieval_duration_ms = 0.0
    retrieval_calls = 0
    rewrite_plan = None
    retrieval_payloads: list[dict[str, Any]] = []
    rewrite_active = bool(args.multi_query or args.rewrite != "none")

    if mode == "agentic" and not args.host_assisted:
        return _error(
            "agentic mode is not implemented in this MVP; use --host-assisted or --mode direct",
            json_output=args.json,
        )

    try:
        kb_manifest = load_kb_manifest(args.kb_manifest) if args.kb_manifest else None
        config = _load_runtime(args)
        client = RAGFlowClient(config)
        if mode == "auto" and not explicit_dataset_inputs and _routing_config_path(args):
            routing = _load_routing(args)
            route_result = route_question(routing, args.question)
            if not route_result.selected:
                raise RoutingError("auto routing found no matching KB; pass explicit --dataset-id/--kb or add route hints")
            dataset_ids = [route_result.selected.kb.dataset_id]
            routed_params = route_result.selected.kb.params
            mode = "direct"
        else:
            if mode == "auto":
                mode = "direct"
            dataset_ids = resolve_dataset_ids(
                client=client,
                dataset_ids=args.dataset_id,
                dataset_names=args.kb,
                kb_manifest=kb_manifest,
            )
        effective_top_k = args.top_k or int(routed_params.get("top_k") or 5)
        effective_similarity_threshold = (
            args.similarity_threshold
            if args.similarity_threshold is not None
            else routed_params.get("similarity_threshold")
        )
        multi_queries = load_multi_query_file(args.multi_query) if args.multi_query else []
        rewrite_plan = build_query_rewrite_plan(
            args.question,
            mode=args.rewrite,
            multi_queries=multi_queries,
            llm_configured=_llm_configured(config),
        )
        retrieval_start = time.perf_counter()
        retrieval_payloads, chunks, fusion_report, retrieval_calls = _retrieve_query_payloads(
            client=client,
            retrieval_queries=rewrite_plan["retrieval_queries"],
            dataset_ids=dataset_ids,
            top_k=effective_top_k,
            similarity_threshold=effective_similarity_threshold,
            fusion=args.fusion,
            include_raw=args.include_raw,
        )
        retrieval_duration_ms = (time.perf_counter() - retrieval_start) * 1000
    except (ConfigError, QueryRewriteError, RetrievalError, RoutingError, ValueError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)

    total_duration_ms = (time.perf_counter() - total_start) * 1000
    finished_at = _utc_now()
    route_payload = route_result.to_dict() if route_result else None
    evidence = weight_evidence(args.question, chunks)
    trace = build_query_trace(
        question=args.question,
        requested_mode=args.mode,
        effective_mode=mode,
        dataset_ids=dataset_ids,
        top_k=effective_top_k,
        similarity_threshold=effective_similarity_threshold,
        host_assisted=args.host_assisted,
        chunk_count=len(chunks),
        evidence=evidence,
        route=route_payload,
        timings_ms={
            "total": round(total_duration_ms, 3),
            "retrieval": round(retrieval_duration_ms, 3),
        },
        started_at=started_at,
        finished_at=finished_at,
        warnings=[] if chunks else ["retrieval returned zero chunks"],
        rewrite_plan=rewrite_plan if rewrite_active else None,
        retrieval_call_count=retrieval_calls,
    )
    if fusion_report:
        trace["fusion"] = fusion_report
    _write_json(args.trace_json, trace)
    _write_text(args.trace_md, render_query_trace_markdown(trace))
    result = QueryResult(
        question=args.question,
        mode=mode,
        dataset_ids=dataset_ids,
        chunks=chunks,
        answer=None,
        host_assisted=args.host_assisted,
        metadata={
            "requested_mode": args.mode,
            "top_k": effective_top_k,
            "similarity_threshold": effective_similarity_threshold,
            "fusion": "rrf" if fusion_report else args.fusion,
            "rewrite": args.rewrite,
            "chunk_count": len(chunks),
            "synthesis": "host-assisted" if args.host_assisted else "not-requested",
            "duration_ms": round(total_duration_ms, 3),
            "retrieval_ms": round(retrieval_duration_ms, 3),
            "retrieval_call_count": retrieval_calls,
            **({"rewrite_plan": rewrite_plan} if rewrite_active and rewrite_plan else {}),
            "evidence_count": len(evidence),
            **({"fusion_report": fusion_report} if fusion_report else {}),
            **({"route": route_payload} if route_payload else {}),
        },
    )
    payload = {
        "ok": True,
        **result.to_dict(include_raw=args.include_raw),
        "evidence": evidence,
    }
    if retrieval_payloads and (args.multi_query or args.rewrite != "none" or args.fusion == "rrf"):
        payload["retrievals"] = retrieval_payloads
    if rewrite_active and rewrite_plan:
        payload["rewrite"] = rewrite_plan
    if fusion_report:
        payload["fusion"] = fusion_report
    if args.include_trace:
        payload["trace"] = trace
    if args.json or args.host_assisted:
        _json_dump(payload)
    else:
        for idx, chunk in enumerate(chunks, 1):
            doc = chunk.document_name or chunk.document_id or "unknown document"
            sim = f"{chunk.similarity:.4f}" if chunk.similarity is not None else "n/a"
            print(f"[{idx}] {doc} sim={sim}\n{chunk.content}\n")
    return 0


def _list_kbs(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    payload = {
        "ok": True,
        "schema": "ragflow_route_kb_list_v1",
        "count": len(routing.knowledge_bases),
        "routing_config": routing.to_dict(),
    }
    _json_dump(payload)
    return 0


def _route(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
        result = route_question(routing, args.question)
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)
    payload = result.to_dict()
    if args.json:
        _json_dump(payload)
    elif result.selected:
        selected = result.selected
        print(f"{selected.kb.name}\t{selected.kb.dataset_id}\tscore={selected.score:.2f}")
    else:
        print("no route matched", file=sys.stderr)
    return 0 if result.selected else 1


def _route_test(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
        queries = load_route_test_queries(args.queries)
        report = run_route_tests(routing, queries)
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_route_test_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _route_report(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
        queries = load_route_test_queries(args.queries) if args.queries else None
        report = run_route_report(routing, queries)
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_route_report_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _rewrite(args: argparse.Namespace) -> int:
    try:
        config = _load_runtime(args) if args.rewrite == "hyde" else None
        multi_queries = load_multi_query_file(args.multi_query) if args.multi_query else []
        report = build_query_rewrite_plan(
            args.question,
            mode=args.rewrite,
            multi_queries=multi_queries,
            llm_configured=_llm_configured(config) if config is not None else False,
        )
    except (ConfigError, QueryRewriteError, OSError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_rewrite_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _audit_citations(args: argparse.Namespace) -> int:
    try:
        query_payload = _read_json(args.query_output)
        if not isinstance(query_payload, dict):
            raise ValueError("query output must be a JSON object")
        answer = args.answer
        if args.answer_file:
            answer = Path(args.answer_file).read_text(encoding="utf-8")
        if not answer or not answer.strip():
            raise ValueError("answer text is required")
        evidence = evidence_from_query_payload(query_payload)
        report = audit_citations(answer, evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_citation_audit_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _diagnose_result(args: argparse.Namespace) -> int:
    try:
        query_payload = _read_json(args.query_output)
        if not isinstance(query_payload, dict):
            raise ValueError("query output must be a JSON object")
        trace = _read_json(args.trace_json) if args.trace_json else None
        if trace is not None and not isinstance(trace, dict):
            raise ValueError("trace JSON must be an object")
        citation_audit = _read_json(args.citation_audit) if args.citation_audit else None
        if citation_audit is not None and not isinstance(citation_audit, dict):
            raise ValueError("citation audit JSON must be an object")
        report = diagnose_query_result(
            query_payload,
            trace=trace,
            citation_audit=citation_audit,
            expected_terms=args.expected_term,
            min_similarity=args.min_similarity,
            min_evidence_score=args.min_evidence_score,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_diagnostic_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _pollution_report(args: argparse.Namespace) -> int:
    try:
        query_payload = _read_json(args.query_output)
        if not isinstance(query_payload, dict):
            raise ValueError("query output must be a JSON object")
        trace = _read_json(args.trace_json) if args.trace_json else None
        if trace is not None and not isinstance(trace, dict):
            raise ValueError("trace JSON must be an object")
        expanded_terms: list[str] = []
        for term in args.expanded_term:
            expanded_terms.append(term)
        if args.expanded_terms_json:
            expanded_terms.extend(load_pollution_terms(args.expanded_terms_json))
        report = query_pollution_report(
            query_payload,
            trace=trace,
            expanded_terms=expanded_terms,
            max_examples=args.max_examples,
            low_query_coverage_threshold=args.low_query_coverage_threshold,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_pollution_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _rerank_ab(args: argparse.Namespace) -> int:
    try:
        query_payload = _read_json(args.query_output)
        if not isinstance(query_payload, dict):
            raise ValueError("query output must be a JSON object")
        rerank_payload = _read_json(args.rerank_json) if args.rerank_json else None
        report = query_rerank_ab_report(
            query_payload,
            rerank_payload=rerank_payload,
            expected_terms=args.expected_term,
            expected_chunks=args.expected_chunk,
            top_k=args.top_k,
            max_examples=args.max_examples,
            min_top_k_overlap=args.min_top_k_overlap,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_rerank_ab_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _fusion(args: argparse.Namespace) -> int:
    try:
        payloads = []
        for path in args.query_output:
            payload = _read_json(path)
            if not isinstance(payload, dict):
                raise ValueError(f"query output must be a JSON object: {path}")
            payloads.append(payload)
        report = query_fusion_report(
            payloads,
            top_k=args.top_k,
            rrf_k=args.rrf_k,
            max_per_source=args.max_per_source,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_fusion_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _fusion_test(args: argparse.Namespace) -> int:
    try:
        cases = load_fusion_test_cases(args.cases)
        report = run_fusion_tests(
            cases,
            top_k=args.top_k,
            rrf_k=args.rrf_k,
            max_per_source=args.max_per_source,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_fusion_test_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _add_runtime_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--config", default=default, help="Path to JSON or simple YAML config")
    parser.add_argument("--base-url", default=default, help="RAGFlow base URL; overrides RAGFLOW_BASE_URL")
    parser.add_argument("--api-key", default=default, help="RAGFlow API key; overrides RAGFLOW_API_KEY")


def _add_routing_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--routing-config", help="Routing config path; defaults to RAGFLOW_ROUTING_CONFIG")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable RAGFlow query CLI")
    _add_runtime_options(parser)

    sub = parser.add_subparsers(dest="command", required=True)
    list_kbs = sub.add_parser("list-kbs", help="List KBs in a routing config")
    _add_routing_option(list_kbs)
    list_kbs.set_defaults(func=_list_kbs)

    route = sub.add_parser("route", help="Route a question to a configured KB")
    _add_routing_option(route)
    route.add_argument("question")
    route.add_argument("--json", action="store_true")
    route.set_defaults(func=_route)

    route_test = sub.add_parser("route-test", help="Run route regression checks")
    _add_routing_option(route_test)
    route_test.add_argument("--queries", required=True, help="Route-test queries JSON")
    route_test.add_argument("--report-json", help="Optional JSON report output path")
    route_test.add_argument("--report-md", help="Optional Markdown report output path")
    route_test.set_defaults(func=_route_test)

    route_report = sub.add_parser("route-report", help="Summarize route quality coverage")
    _add_routing_option(route_report)
    route_report.add_argument("--queries", help="Optional route-test queries JSON")
    route_report.add_argument("--report-json", help="Optional JSON report output path")
    route_report.add_argument("--report-md", help="Optional Markdown report output path")
    route_report.set_defaults(func=_route_report)

    rewrite = sub.add_parser(
        "rewrite",
        help="Plan deterministic query rewrite variants",
        description="Plan deterministic query rewrite variants",
    )
    _add_runtime_options(rewrite, suppress_defaults=True)
    rewrite.add_argument("question", help="Original query")
    rewrite.add_argument("--rewrite", choices=["none", "simple", "translate", "hyde"], default="simple")
    rewrite.add_argument("--multi-query", help="Optional JSON list of host-owned query variants")
    rewrite.add_argument("--report-json", help="Optional JSON report output path")
    rewrite.add_argument("--report-md", help="Optional Markdown report output path")
    rewrite.add_argument("--json", action="store_true", help="Emit JSON report")
    rewrite.set_defaults(func=_rewrite)

    audit = sub.add_parser("audit-citations", help="Audit host-generated answer citations")
    audit.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    answer_group = audit.add_mutually_exclusive_group(required=True)
    answer_group.add_argument("--answer", help="Host-generated answer text")
    answer_group.add_argument("--answer-file", help="File containing host-generated answer text")
    audit.add_argument("--report-json", help="Optional JSON report output path")
    audit.add_argument("--report-md", help="Optional Markdown report output path")
    audit.add_argument("--json", action="store_true", help="Emit JSON report")
    audit.set_defaults(func=_audit_citations)

    diagnose = sub.add_parser("diagnose-result", help="Diagnose a saved query result")
    diagnose.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    diagnose.add_argument("--trace-json", help="Optional query trace JSON from --trace-json")
    diagnose.add_argument("--citation-audit", help="Optional citation audit JSON")
    diagnose.add_argument("--expected-term", action="append", default=[], help="Expected term; repeatable")
    diagnose.add_argument("--min-similarity", type=float, default=0.15)
    diagnose.add_argument("--min-evidence-score", type=float, default=0.2)
    diagnose.add_argument("--report-json", help="Optional JSON report output path")
    diagnose.add_argument("--report-md", help="Optional Markdown report output path")
    diagnose.add_argument("--json", action="store_true", help="Emit JSON report")
    diagnose.set_defaults(func=_diagnose_result)

    pollution = sub.add_parser("pollution-report", help="Diagnose likely query expansion or BM25 pollution")
    pollution.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    pollution.add_argument("--trace-json", help="Optional query trace JSON from --trace-json")
    pollution.add_argument("--expanded-term", action="append", default=[], help="Expanded or translated term; repeatable")
    pollution.add_argument("--expanded-terms-json", help="Optional JSON file containing expanded/translated terms")
    pollution.add_argument("--low-query-coverage-threshold", type=float, default=0.25)
    pollution.add_argument("--max-examples", type=int, default=5)
    pollution.add_argument("--report-json", help="Optional JSON report output path")
    pollution.add_argument("--report-md", help="Optional Markdown report output path")
    pollution.add_argument("--json", action="store_true", help="Emit JSON report")
    pollution.set_defaults(func=_pollution_report)

    rerank = sub.add_parser("rerank-ab", help="Compare RAGFlow ordering with an offline rerank candidate")
    rerank.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    rerank.add_argument("--rerank-json", help="Optional external rerank output JSON")
    rerank.add_argument("--expected-term", action="append", default=[], help="Expected evidence term; repeatable")
    rerank.add_argument("--expected-chunk", action="append", default=[], help="Expected chunk id or stable hash; repeatable")
    rerank.add_argument("--top-k", type=int, default=5)
    rerank.add_argument("--min-top-k-overlap", type=float, default=0.5)
    rerank.add_argument("--max-examples", type=int, default=10)
    rerank.add_argument("--report-json", help="Optional JSON report output path")
    rerank.add_argument("--report-md", help="Optional Markdown report output path")
    rerank.add_argument("--json", action="store_true", help="Emit JSON report")
    rerank.set_defaults(func=_rerank_ab)

    fusion = sub.add_parser("fusion", help="Fuse saved query outputs with reciprocal rank fusion")
    fusion.add_argument("--query-output", action="append", required=True, help="JSON output from query.py ask; repeatable")
    fusion.add_argument("--top-k", type=int, default=10)
    fusion.add_argument("--rrf-k", type=int, default=60)
    fusion.add_argument("--max-per-source", type=int)
    fusion.add_argument("--report-json", help="Optional JSON report output path")
    fusion.add_argument("--report-md", help="Optional Markdown report output path")
    fusion.add_argument("--json", action="store_true", help="Emit JSON report")
    fusion.set_defaults(func=_fusion)

    fusion_test = sub.add_parser("fusion-test", help="Run offline fusion fixture checks")
    fusion_test.add_argument("--cases", required=True, help="Fusion test cases JSON")
    fusion_test.add_argument("--top-k", type=int, help="Default top_k for cases that omit it")
    fusion_test.add_argument("--rrf-k", type=int, help="Default rrf_k for cases that omit it")
    fusion_test.add_argument("--max-per-source", type=int, help="Default max_per_source for cases that omit it")
    fusion_test.add_argument("--report-json", help="Optional JSON report output path")
    fusion_test.add_argument("--report-md", help="Optional Markdown report output path")
    fusion_test.add_argument("--json", action="store_true", help="Emit JSON report")
    fusion_test.set_defaults(func=_fusion_test)

    ask = sub.add_parser("ask", help="Ask a question against RAGFlow")
    _add_runtime_options(ask, suppress_defaults=True)
    _add_routing_option(ask)
    ask.add_argument("question", help="Question to retrieve evidence for")
    ask.add_argument("--mode", choices=["auto", "direct", "agentic"], default="auto")
    ask.add_argument("--dataset-id", action="append", default=[], help="RAGFlow dataset ID; repeatable")
    ask.add_argument("--kb", action="append", default=[], help="RAGFlow KB/dataset name; repeatable")
    ask.add_argument("--kb-manifest", help="Path to kb_manifest.json")
    ask.add_argument("--top-k", type=int)
    ask.add_argument("--similarity-threshold", type=float)
    ask.add_argument("--fusion", choices=["none", "rrf"], default="none", help="Fuse per-dataset retrieval results when multiple dataset IDs are selected")
    ask.add_argument("--rewrite", choices=["none", "simple", "translate", "hyde"], default="none", help="Opt-in query rewrite planning before retrieval")
    ask.add_argument("--multi-query", help="JSON file with additional host-owned query variants")
    ask.add_argument("--host-assisted", action="store_true", help="Return evidence for host agent synthesis")
    ask.add_argument("--json", action="store_true", help="Emit JSON")
    ask.add_argument("--include-raw", action="store_true", help="Include raw RAGFlow chunks in JSON")
    ask.add_argument("--include-trace", action="store_true", help="Include full query trace in JSON output")
    ask.add_argument("--trace-json", help="Optional query trace JSON output path")
    ask.add_argument("--trace-md", help="Optional query trace Markdown output path")
    ask.set_defaults(func=_ask)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
