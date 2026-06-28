#!/usr/bin/env python3
"""Portable RAGFlow query CLI."""

from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime, timezone
import json
import os
import re
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
    AgenticPlanError,
    AssistantReviewError,
    ConfigError,
    CentroidRoutingError,
    NormalizedChunk,
    QueryResult,
    QueryIntentError,
    QueryRewriteError,
    QuerySessionError,
    RAGFlowClient,
    RetrievalError,
    RoutingError,
    audit_citations,
    build_agentic_execution_trace,
    build_agentic_plan,
    build_centroid_index,
    build_centroid_plan,
    build_host_synthesis_contract,
    build_query_rewrite_plan,
    classify_query_intent,
    build_query_session_inspection,
    build_query_endpoint_report,
    build_query_trace,
    diagnose_query_result,
    evaluate_answer,
    configured_private_hosts_from_urls,
    evidence_from_query_payload,
    load_pollution_terms,
    load_assistant_profile,
    load_assistant_test_plan,
    load_query_fallback_test_cases,
    load_query_session,
    load_retrieval_hints,
    load_route_activation_plan,
    load_route_test_report,
    load_route_test_queries,
    load_config,
    load_centroid_index,
    load_fusion_test_cases,
    load_kb_manifest,
    load_multi_query_file,
    load_routing_config,
    normalize_retrieval_response,
    normalize_retrieval_status,
    query_fusion_report,
    query_cross_language_ab_report,
    query_pollution_report,
    query_rerank_ab_report,
    render_citation_audit_markdown,
    render_answer_evaluation_markdown,
    render_assistant_profile_recommendation_markdown,
    render_assistant_test_plan_review_markdown,
    render_agentic_plan_markdown,
    render_centroid_build_markdown,
    render_centroid_plan_markdown,
    render_query_cross_language_ab_markdown,
    render_query_fusion_markdown,
    render_query_fusion_test_markdown,
    render_query_intent_markdown,
    render_query_session_enrichment_markdown,
    render_query_session_inspection_markdown,
    render_query_diagnostic_markdown,
    render_query_endpoint_report_markdown,
    render_query_fallback_test_markdown,
    render_query_pollution_markdown,
    render_query_rerank_ab_markdown,
    render_query_rewrite_markdown,
    render_query_route_decision_markdown,
    render_query_trace_markdown,
    render_route_activation_check_markdown,
    render_route_diagnose_markdown,
    render_route_report_markdown,
    render_route_test_markdown,
    run_fusion_tests,
    run_query_fallback_tests,
    recommend_assistant_profile,
    review_assistant_test_plan,
    resolve_dataset_ids,
    route_question,
    route_query_intent,
    enrich_query_with_session,
    run_route_activation_check,
    run_route_diagnose,
    run_route_report,
    run_route_tests,
    sanitize_report_payload,
    weight_evidence,
    write_centroid_plan,
    write_centroid_report,
)


_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def _json_dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool, details: dict[str, Any] | None = None) -> int:
    payload = {"ok": False, "error": message}
    if details:
        payload.update(details)
    if json_output:
        _json_dump(payload)
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_runtime(args: argparse.Namespace):
    overrides = {}
    if getattr(args, "base_url", None):
        overrides["base_url"] = args.base_url
    if getattr(args, "api_key", None):
        overrides["api_key"] = args.api_key
    if getattr(args, "timeout", None) is not None:
        overrides["timeout"] = args.timeout
    return load_config(config_file=getattr(args, "config", None), overrides=overrides)


def _routing_config_path(args: argparse.Namespace) -> str | None:
    return getattr(args, "routing_config", None) or os.environ.get("RAGFLOW_ROUTING_CONFIG")


def _centroid_index_path(args: argparse.Namespace) -> str | None:
    return getattr(args, "centroid_index", None) or os.environ.get("RAGFLOW_CENTROID_INDEX")


def _load_routing(args: argparse.Namespace):
    path = _routing_config_path(args)
    if not path:
        raise RoutingError("routing config is required; pass --routing-config or set RAGFLOW_ROUTING_CONFIG")
    return load_routing_config(path)


def _load_centroid_index(args: argparse.Namespace) -> dict[str, Any] | None:
    path = _centroid_index_path(args)
    return load_centroid_index(path) if path else None


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _write_json(path: str | None, data: Any) -> None:
    if path:
        _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _collect_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_collect_urls(item))
        return urls
    if isinstance(value, (list, tuple)):
        urls = []
        for item in value:
            urls.extend(_collect_urls(item))
        return urls
    return []


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_query_vector(path: str | Path) -> list[float] | dict[str, Any]:
    payload = _read_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload
    raise ValueError("query vector JSON must be a vector list or object containing a vector field")


def _read_query_outputs(paths: list[str], *, label: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        raw = _read_json(path)
        items: list[Any]
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict) and isinstance(raw.get("payloads"), list):
            items = raw["payloads"]
        else:
            items = [raw]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"{label} query output must be a JSON object: {path}#{index}")
            payloads.append(item)
    return payloads


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
    evidence = weight_evidence(question, chunks)
    status_report = normalize_retrieval_status(chunks=chunks, evidence=evidence)
    return {
        "ok": True,
        "question": question,
        "source": source,
        "query_id": query_id,
        "query_kind": query_kind,
        "dataset_ids": list(dataset_ids),
        "chunks": [chunk.to_dict(include_raw=include_raw) for chunk in chunks],
        "evidence": evidence,
        "retrieval_status": status_report["status"],
        "retrieval_status_report": status_report,
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
    agentic_plan = None
    agentic_trace = None
    host_synthesis_contract = None
    retrieval_payloads: list[dict[str, Any]] = []
    agentic_active = mode == "agentic" and args.host_assisted
    rewrite_active = bool(args.multi_query or args.rewrite != "none") and not agentic_active

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
            route_result = route_question(
                routing,
                args.question,
                centroid_index=_load_centroid_index(args),
                query_vector=_read_query_vector(args.query_vector_json) if args.query_vector_json else None,
            )
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
        if agentic_active:
            agentic_plan = build_agentic_plan(
                args.question,
                retrieval_mode="direct",
                rewrite_mode=args.rewrite,
                max_subqueries=args.max_subqueries,
                reflection_budget=args.reflection_budget,
            )
            retrieval_queries = list(agentic_plan.get("retrieval_queries", []))
        else:
            multi_queries = load_multi_query_file(args.multi_query) if args.multi_query else []
            rewrite_plan = build_query_rewrite_plan(
                args.question,
                mode=args.rewrite,
                multi_queries=multi_queries,
                llm_configured=_llm_configured(config),
            )
            retrieval_queries = rewrite_plan["retrieval_queries"]
        retrieval_start = time.perf_counter()
        if retrieval_queries:
            retrieval_payloads, chunks, fusion_report, retrieval_calls = _retrieve_query_payloads(
                client=client,
                retrieval_queries=retrieval_queries,
                dataset_ids=dataset_ids,
                top_k=effective_top_k,
                similarity_threshold=effective_similarity_threshold,
                fusion=args.fusion,
                include_raw=args.include_raw,
            )
        else:
            chunks = []
            fusion_report = None
        retrieval_duration_ms = (time.perf_counter() - retrieval_start) * 1000
    except (AgenticPlanError, ConfigError, QueryRewriteError, RetrievalError, RoutingError, ValueError, OSError, RuntimeError) as exc:
        status_report = normalize_retrieval_status(error=exc)
        return _error(
            str(exc),
            json_output=args.json,
            details={
                "retrieval_status": status_report["status"],
                "retrieval_status_report": status_report,
            },
        )

    total_duration_ms = (time.perf_counter() - total_start) * 1000
    finished_at = _utc_now()
    route_payload = route_result.to_dict() if route_result else None
    evidence = weight_evidence(args.question, chunks)
    agentic_retrieval_status = None
    if agentic_plan and agentic_plan.get("status") in {"needs_clarification", "rejected"}:
        agentic_retrieval_status = str(agentic_plan["status"])
    status_report = normalize_retrieval_status(
        chunks=chunks,
        evidence=evidence,
        intent_status=agentic_retrieval_status,
    )
    if agentic_plan:
        agentic_trace = build_agentic_execution_trace(
            agentic_plan,
            retrieval_call_count=retrieval_calls,
            retrieval_latency_ms=retrieval_duration_ms,
            started_at=started_at,
            finished_at=finished_at,
        )
        host_synthesis_contract = build_host_synthesis_contract(
            agentic_plan,
            evidence,
            retrieval_status=status_report,
        )
    trace_warnings = [str(item) for item in agentic_plan.get("warnings", [])] if agentic_plan else []
    if not chunks:
        trace_warnings.append("retrieval returned zero chunks")
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
        warnings=trace_warnings,
        rewrite_plan=rewrite_plan if rewrite_active else None,
        retrieval_status=status_report,
        retrieval_call_count=retrieval_calls,
    )
    if agentic_plan:
        trace["agentic_plan"] = agentic_plan
    if agentic_trace:
        trace["agentic_trace"] = agentic_trace
    if host_synthesis_contract:
        trace["host_synthesis_contract"] = host_synthesis_contract
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
            "retrieval_status": status_report["status"],
            "retrieval_status_report": status_report,
            "chunk_count": len(chunks),
            "synthesis": "host-assisted" if args.host_assisted else "not-requested",
            "duration_ms": round(total_duration_ms, 3),
            "retrieval_ms": round(retrieval_duration_ms, 3),
            "retrieval_call_count": retrieval_calls,
            **({"rewrite_plan": rewrite_plan} if rewrite_active and rewrite_plan else {}),
            **({"agentic_plan": agentic_plan} if agentic_plan else {}),
            **({"agentic_trace": agentic_trace} if agentic_trace else {}),
            **({"host_synthesis_contract": host_synthesis_contract} if host_synthesis_contract else {}),
            "evidence_count": len(evidence),
            **({"fusion_report": fusion_report} if fusion_report else {}),
            **({"route": route_payload} if route_payload else {}),
        },
    )
    payload = {
        "ok": True,
        **result.to_dict(include_raw=args.include_raw),
        "evidence": evidence,
        "retrieval_status": status_report["status"],
        "retrieval_status_report": status_report,
    }
    if retrieval_payloads and (agentic_plan or args.multi_query or args.rewrite != "none" or args.fusion == "rrf"):
        payload["retrievals"] = retrieval_payloads
    if rewrite_active and rewrite_plan:
        payload["rewrite"] = rewrite_plan
    if agentic_plan:
        payload["agentic_plan"] = agentic_plan
    if agentic_trace:
        payload["agentic_trace"] = agentic_trace
    if host_synthesis_contract:
        payload["host_synthesis_contract"] = host_synthesis_contract
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
        result = route_question(
            routing,
            args.question,
            centroid_index=_load_centroid_index(args),
            query_vector=_read_query_vector(args.query_vector_json) if args.query_vector_json else None,
        )
    except (RoutingError, OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
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
        report = run_route_tests(routing, queries, centroid_index=_load_centroid_index(args))
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
        report = run_route_report(routing, queries, centroid_index=_load_centroid_index(args))
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_route_report_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _route_diagnose(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
        queries = load_route_test_queries(args.queries)
        report = run_route_diagnose(routing, queries, centroid_index=_load_centroid_index(args))
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_route_diagnose_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_route_activation_check_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    routing: Any,
    activation_plan: dict[str, Any],
    queries: Any,
    route_test_report: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    routing_payload = routing.to_dict() if hasattr(routing, "to_dict") else {}
    urls = [
        *_collect_urls(routing_payload),
        *_collect_urls(activation_plan),
        *_collect_urls(queries or {}),
        *_collect_urls(route_test_report or {}),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.activation_plan,
            args.routing_config,
            args.queries,
            args.route_test_report,
            args.centroid_index,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _route_activation_check(args: argparse.Namespace) -> int:
    try:
        routing = _load_routing(args)
        activation_plan = load_route_activation_plan(args.activation_plan)
        queries = load_route_test_queries(args.queries) if args.queries else None
        route_test_report = load_route_test_report(args.route_test_report) if args.route_test_report else None
        report = run_route_activation_check(
            activation_plan,
            routing,
            queries=queries,
            route_test_report=route_test_report,
            centroid_index=_load_centroid_index(args),
            inputs={
                "activation_plan": args.activation_plan,
                "route_config": args.routing_config,
                "route_tests": args.queries,
                "route_test_report": args.route_test_report,
                "centroid_index": args.centroid_index,
            },
        )
    except (RoutingError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    if args.redaction_report:
        report, redaction_report = _sanitize_route_activation_check_report(
            report,
            args,
            routing,
            activation_plan,
            queries,
            route_test_report,
        )
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_route_activation_check_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _assistant_profile_recommend(args: argparse.Namespace) -> int:
    try:
        assistant_profile = load_assistant_profile(args.assistant_profile)
        retrieval_hints = load_retrieval_hints(args.retrieval_hints) if args.retrieval_hints else None
        report = recommend_assistant_profile(
            assistant_profile,
            retrieval_hints=retrieval_hints,
            inputs={
                "assistant_profile": args.assistant_profile,
                "retrieval_hints": args.retrieval_hints,
            },
        )
    except (AssistantReviewError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_assistant_profile_recommendation_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _assistant_test_plan(args: argparse.Namespace) -> int:
    try:
        assistant_test_plan = load_assistant_test_plan(args.test_plan)
        assistant_profile = load_assistant_profile(args.assistant_profile) if args.assistant_profile else None
        retrieval_hints = load_retrieval_hints(args.retrieval_hints) if args.retrieval_hints else None
        report = review_assistant_test_plan(
            assistant_test_plan,
            assistant_profile=assistant_profile,
            retrieval_hints=retrieval_hints,
            inputs={
                "assistant_test_plan": args.test_plan,
                "assistant_profile": args.assistant_profile,
                "retrieval_hints": args.retrieval_hints,
            },
        )
    except (AssistantReviewError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=True)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_assistant_test_plan_review_markdown(report))
    _json_dump(report)
    return 0 if report["ok"] else 1


def _centroid_build(args: argparse.Namespace) -> int:
    try:
        if args.plan_only:
            report = build_centroid_plan(
                kb_manifest_paths=args.kb_manifest,
                chunk_snapshot_paths=args.chunk_snapshot,
                index_output=args.index_output,
                embedding_provider=args.embedding_provider,
                embedding_model=args.embedding_model,
                embedding_dimension=args.embedding_dimension,
                batch_size=args.batch_size,
                checkpoint_path=args.checkpoint,
                resume=args.resume,
            )
            markdown = render_centroid_plan_markdown(report)
        else:
            report = build_centroid_index(
                kb_manifest_paths=args.kb_manifest,
                chunk_snapshot_paths=args.chunk_snapshot,
                index_output=args.index_output,
                embedding_provider=args.embedding_provider,
                embedding_model=args.embedding_model,
                embedding_dimension=args.embedding_dimension,
                batch_size=args.batch_size,
                checkpoint_path=args.checkpoint,
                resume=args.resume,
            )
            markdown = render_centroid_build_markdown(report)
    except (CentroidRoutingError, OSError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    if args.report_json:
        if args.plan_only:
            write_centroid_plan(args.report_json, report)
        else:
            write_centroid_report(args.report_json, report)
    _write_text(args.report_md, markdown)
    if args.json or not args.report_json:
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


def _intent_classify(args: argparse.Namespace) -> int:
    try:
        report = classify_query_intent(
            args.question,
            low_confidence_threshold=args.low_confidence_threshold,
        )
    except QueryIntentError as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_intent_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _intent_route(args: argparse.Namespace) -> int:
    try:
        report = route_query_intent(
            args.question,
            retrieval_mode=args.retrieval_mode,
            low_confidence_threshold=args.low_confidence_threshold,
        )
    except QueryIntentError as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_route_decision_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _session_inspect(args: argparse.Namespace) -> int:
    try:
        session = load_query_session(args.session)
        report = build_query_session_inspection(
            session,
            max_turns=args.max_turns,
            max_tokens=args.max_tokens,
        )
    except (QuerySessionError, OSError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_session_inspection_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _session_enrich(args: argparse.Namespace) -> int:
    try:
        session = load_query_session(args.session)
        report = enrich_query_with_session(
            args.question,
            session,
            max_turns=args.max_turns,
            max_tokens=args.max_tokens,
        )
    except (QuerySessionError, OSError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_session_enrichment_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _agentic_plan(args: argparse.Namespace) -> int:
    try:
        report = build_agentic_plan(
            args.question,
            retrieval_mode=args.retrieval_mode,
            rewrite_mode=args.rewrite,
            max_subqueries=args.max_subqueries,
            reflection_budget=args.reflection_budget,
            require_citations=args.require_citations,
        )
    except AgenticPlanError as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_agentic_plan_markdown(report))
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


def _sanitize_answer_evaluation_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    query_payload: dict[str, Any],
    answer: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(query_payload),
        *_collect_urls(report),
        *_collect_urls(answer),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.query_output,
            args.answer_file,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _sanitize_query_diagnostic_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    query_payload: dict[str, Any],
    trace: dict[str, Any] | None,
    citation_audit: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(query_payload),
        *_collect_urls(trace or {}),
        *_collect_urls(citation_audit or {}),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.query_output,
            args.trace_json,
            args.citation_audit,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _evaluate_answer(args: argparse.Namespace) -> int:
    try:
        query_payload = _read_json(args.query_output)
        if not isinstance(query_payload, dict):
            raise ValueError("query output must be a JSON object")
        answer = args.answer
        if args.answer_file:
            answer = Path(args.answer_file).read_text(encoding="utf-8")
        report = evaluate_answer(
            query_payload,
            answer or "",
            expected_terms=args.expected_term,
            require_citation=args.require_citation,
            allow_abstain=args.allow_abstain,
            min_cited_evidence_score=args.min_cited_evidence_score,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    if args.redaction_report:
        report, redaction_report = _sanitize_answer_evaluation_report(report, args, query_payload, answer or "")
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_answer_evaluation_markdown(report))
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
    if args.redaction_report:
        report, redaction_report = _sanitize_query_diagnostic_report(
            report,
            args,
            query_payload,
            trace if isinstance(trace, dict) else None,
            citation_audit if isinstance(citation_audit, dict) else None,
        )
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_diagnostic_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_query_pollution_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    query_payload: dict[str, Any],
    trace: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(query_payload),
        *_collect_urls(trace or {}),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.query_output,
            args.trace_json,
            args.expanded_terms_json,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


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
    if args.redaction_report:
        report, redaction_report = _sanitize_query_pollution_report(
            report,
            args,
            query_payload,
            trace if isinstance(trace, dict) else None,
        )
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_pollution_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_query_rerank_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    query_payload: dict[str, Any],
    rerank_payload: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(query_payload),
        *_collect_urls(rerank_payload),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.query_output,
            args.rerank_json,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


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
    if args.redaction_report:
        report, redaction_report = _sanitize_query_rerank_report(report, args, query_payload, rerank_payload)
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_rerank_ab_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_query_cross_language_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    baseline_payloads: list[dict[str, Any]],
    candidate_payloads: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(baseline_payloads),
        *_collect_urls(candidate_payloads),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            *args.baseline_output,
            *args.candidate_output,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _cross_language_ab(args: argparse.Namespace) -> int:
    try:
        baseline_payloads = _read_query_outputs(args.baseline_output, label="baseline")
        candidate_payloads = _read_query_outputs(args.candidate_output, label="candidate")
        report = query_cross_language_ab_report(
            baseline_payloads,
            candidate_payloads,
            baseline_label=args.baseline_label,
            candidate_label=args.candidate_label,
            min_top1_stability=args.min_top1_stability,
            max_examples=args.max_examples,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    if args.redaction_report:
        report, redaction_report = _sanitize_query_cross_language_report(
            report,
            args,
            baseline_payloads,
            candidate_payloads,
        )
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_cross_language_ab_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_query_fusion_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    payloads: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        *_collect_urls(payloads),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            *args.query_output,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


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
    if args.redaction_report:
        report, redaction_report = _sanitize_query_fusion_report(report, args, payloads)
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_fusion_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _sanitize_query_fusion_test_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    cases: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    query_output_paths: list[str] = []
    for case in cases:
        outputs = case.get("query_outputs") if isinstance(case, dict) else None
        if isinstance(outputs, list):
            query_output_paths.extend(str(output) for output in outputs if isinstance(output, str))
    urls = [
        *_collect_urls(cases),
        *_collect_urls(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.cases,
            *query_output_paths,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


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
    if args.redaction_report:
        report, redaction_report = _sanitize_query_fusion_test_report(report, args, cases)
        _write_json(args.redaction_report, redaction_report)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_fusion_test_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _fallback_test(args: argparse.Namespace) -> int:
    try:
        cases = load_query_fallback_test_cases(args.cases)
        report = run_query_fallback_tests(cases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_text(args.report_md, render_query_fallback_test_markdown(report))
    if args.json or not args.report_json:
        _json_dump(report)
    return 0 if report["ok"] else 1


def _parse_endpoint_args(values: list[str]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    for index, raw in enumerate(values or [], start=1):
        value = str(raw).strip()
        if not value:
            continue
        label = f"custom_{index}"
        url = value
        if "=" in value and not value.lower().startswith(("http://", "https://")):
            candidate_label, candidate_url = value.split("=", 1)
            if candidate_url.strip():
                label = candidate_label.strip() or label
                url = candidate_url.strip()
        endpoints.append({"label": label, "kind": "custom", "url": url})
    return endpoints


def _sanitize_endpoint_report(report: dict[str, Any], args: argparse.Namespace, runtime: Any, endpoints: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [
        runtime.base_url,
        runtime.llm_base_url,
        *(endpoint.get("url") for endpoint in endpoints if isinstance(endpoint.get("url"), str)),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[runtime.api_key, runtime.llm_api_key],
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[getattr(args, "config", None)],
    )
    return sanitized, redaction_report


def _endpoint_report(args: argparse.Namespace) -> int:
    try:
        runtime = _load_runtime(args)
        timeout = args.timeout if args.timeout is not None else runtime.timeout or 5.0
        endpoints = _parse_endpoint_args(args.endpoint)
        report = build_query_endpoint_report(
            ragflow_base_url=runtime.base_url,
            ragflow_api_key=runtime.api_key,
            llm_base_url=runtime.llm_base_url,
            llm_api_key=runtime.llm_api_key,
            extra_endpoints=endpoints,
            network_check=args.network_check,
            timeout=timeout,
            verify_ssl=True if runtime.verify_ssl is None else bool(runtime.verify_ssl),
        )
        report, redaction_report = _sanitize_endpoint_report(report, args, runtime, endpoints)
    except (ConfigError, ValueError) as exc:
        return _error(str(exc), json_output=args.json)
    _write_json(args.report_json, report)
    _write_json(args.redaction_report, redaction_report)
    _write_text(args.report_md, render_query_endpoint_report_markdown(report))
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


def _add_centroid_tie_breaker_options(parser: argparse.ArgumentParser, *, include_query_vector: bool) -> None:
    parser.add_argument(
        "--centroid-index",
        help="Optional centroid index path for tie-breaking equal positive hint scores",
    )
    if include_query_vector:
        parser.add_argument(
            "--query-vector-json",
            help="JSON vector or object containing a vector field for centroid tie-breaking",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable RAGFlow query CLI")
    _add_runtime_options(parser)

    sub = parser.add_subparsers(dest="command", required=True)
    list_kbs = sub.add_parser("list-kbs", help="List KBs in a routing config")
    _add_routing_option(list_kbs)
    list_kbs.set_defaults(func=_list_kbs)

    route = sub.add_parser("route", help="Route a question to a configured KB")
    _add_routing_option(route)
    _add_centroid_tie_breaker_options(route, include_query_vector=True)
    route.add_argument("question")
    route.add_argument("--json", action="store_true")
    route.set_defaults(func=_route)

    route_test = sub.add_parser("route-test", help="Run route regression checks")
    _add_routing_option(route_test)
    _add_centroid_tie_breaker_options(route_test, include_query_vector=False)
    route_test.add_argument("--queries", required=True, help="Route-test queries JSON")
    route_test.add_argument("--report-json", help="Optional JSON report output path")
    route_test.add_argument("--report-md", help="Optional Markdown report output path")
    route_test.set_defaults(func=_route_test)

    route_report = sub.add_parser("route-report", help="Summarize route quality coverage")
    _add_routing_option(route_report)
    _add_centroid_tie_breaker_options(route_report, include_query_vector=False)
    route_report.add_argument("--queries", help="Optional route-test queries JSON")
    route_report.add_argument("--report-json", help="Optional JSON report output path")
    route_report.add_argument("--report-md", help="Optional Markdown report output path")
    route_report.set_defaults(func=_route_report)

    route_diagnose = sub.add_parser("route-diagnose", help="Classify route-test failures")
    _add_routing_option(route_diagnose)
    _add_centroid_tie_breaker_options(route_diagnose, include_query_vector=False)
    route_diagnose.add_argument("--queries", required=True, help="Route-test queries JSON")
    route_diagnose.add_argument("--report-json", help="Optional JSON report output path")
    route_diagnose.add_argument("--report-md", help="Optional Markdown report output path")
    route_diagnose.set_defaults(func=_route_diagnose)

    route_activation_check = sub.add_parser(
        "route-activation-check",
        help="Check activation-plan route readiness without mutation",
    )
    _add_routing_option(route_activation_check)
    _add_centroid_tie_breaker_options(route_activation_check, include_query_vector=False)
    route_activation_check.add_argument("--activation-plan", required=True, help="kb_activation_plan_v1 JSON")
    route_activation_check.add_argument("--queries", help="Optional route-test queries JSON")
    route_activation_check.add_argument("--route-test-report", help="Optional saved route-test report JSON")
    route_activation_check.add_argument("--report-json", help="Optional JSON report output path")
    route_activation_check.add_argument("--report-md", help="Optional Markdown report output path")
    route_activation_check.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    route_activation_check.set_defaults(func=_route_activation_check)

    assistant_profile = sub.add_parser(
        "assistant-profile",
        help="Review assistant profile sidecars offline",
    )
    assistant_profile_sub = assistant_profile.add_subparsers(dest="assistant_profile_command", required=True)
    assistant_profile_recommend = assistant_profile_sub.add_parser(
        "recommend",
        help="Recommend reviewable assistant retrieval settings",
    )
    assistant_profile_recommend.add_argument("--assistant-profile", required=True, help="assistant_profile.json")
    assistant_profile_recommend.add_argument("--retrieval-hints", help="Optional retrieval_hints.json")
    assistant_profile_recommend.add_argument("--report-json", help="Optional JSON report output path")
    assistant_profile_recommend.add_argument("--report-md", help="Optional Markdown report output path")
    assistant_profile_recommend.set_defaults(func=_assistant_profile_recommend)

    assistant_test_plan = sub.add_parser(
        "assistant-test-plan",
        help="Review assistant test plan sidecars offline",
    )
    assistant_test_plan.add_argument("--test-plan", required=True, help="assistant_test_plan.json")
    assistant_test_plan.add_argument("--assistant-profile", help="Optional assistant_profile.json")
    assistant_test_plan.add_argument("--retrieval-hints", help="Optional retrieval_hints.json")
    assistant_test_plan.add_argument("--report-json", help="Optional JSON report output path")
    assistant_test_plan.add_argument("--report-md", help="Optional Markdown report output path")
    assistant_test_plan.set_defaults(func=_assistant_test_plan)

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

    intent = sub.add_parser("intent", help="Classify and route query intent")
    intent_sub = intent.add_subparsers(dest="intent_command", required=True)
    intent_classify = intent_sub.add_parser("classify", help="Classify query intent offline")
    intent_classify.add_argument("question", help="Question to classify")
    intent_classify.add_argument("--low-confidence-threshold", type=float, default=0.7)
    intent_classify.add_argument("--report-json", help="Optional JSON report output path")
    intent_classify.add_argument("--report-md", help="Optional Markdown report output path")
    intent_classify.add_argument("--json", action="store_true", help="Emit JSON report")
    intent_classify.set_defaults(func=_intent_classify)
    intent_route = intent_sub.add_parser("route", help="Create a deterministic intent route decision")
    intent_route.add_argument("question", help="Question to route")
    intent_route.add_argument("--retrieval-mode", choices=["auto", "direct"], default="auto")
    intent_route.add_argument("--low-confidence-threshold", type=float, default=0.7)
    intent_route.add_argument("--report-json", help="Optional JSON report output path")
    intent_route.add_argument("--report-md", help="Optional Markdown report output path")
    intent_route.add_argument("--json", action="store_true", help="Emit JSON report")
    intent_route.set_defaults(func=_intent_route)

    session = sub.add_parser("session", help="Inspect and enrich bounded query session context")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_inspect = session_sub.add_parser("inspect", help="Inspect bounded session context offline")
    session_inspect.add_argument("--session", required=True, help="ragflow_query_session_v1 JSON or turns list")
    session_inspect.add_argument("--max-turns", type=int, default=8)
    session_inspect.add_argument("--max-tokens", type=int, default=400)
    session_inspect.add_argument("--report-json", help="Optional JSON report output path")
    session_inspect.add_argument("--report-md", help="Optional Markdown report output path")
    session_inspect.add_argument("--json", action="store_true", help="Emit JSON report")
    session_inspect.set_defaults(func=_session_inspect)
    session_enrich = session_sub.add_parser("enrich", help="Enrich a follow-up query with bounded context")
    session_enrich.add_argument("question", help="Question to enrich")
    session_enrich.add_argument("--session", required=True, help="ragflow_query_session_v1 JSON or turns list")
    session_enrich.add_argument("--max-turns", type=int, default=8)
    session_enrich.add_argument("--max-tokens", type=int, default=400)
    session_enrich.add_argument("--report-json", help="Optional JSON report output path")
    session_enrich.add_argument("--report-md", help="Optional Markdown report output path")
    session_enrich.add_argument("--json", action="store_true", help="Emit JSON report")
    session_enrich.set_defaults(func=_session_enrich)

    agentic_plan = sub.add_parser(
        "agentic-plan",
        help="Plan deterministic agentic query orchestration",
        description="Plan deterministic agentic query orchestration",
    )
    agentic_plan.add_argument("question", help="Question to plan")
    agentic_plan.add_argument("--retrieval-mode", choices=["auto", "direct"], default="auto")
    agentic_plan.add_argument("--rewrite", choices=["none", "simple", "translate"], default="simple")
    agentic_plan.add_argument("--max-subqueries", type=int, default=4)
    agentic_plan.add_argument("--reflection-budget", type=int, default=0)
    agentic_plan.add_argument("--no-require-citations", dest="require_citations", action="store_false")
    agentic_plan.add_argument("--report-json", help="Optional JSON report output path")
    agentic_plan.add_argument("--report-md", help="Optional Markdown report output path")
    agentic_plan.add_argument("--json", action="store_true", help="Emit JSON report")
    agentic_plan.set_defaults(func=_agentic_plan, require_citations=True)

    audit = sub.add_parser("audit-citations", help="Audit host-generated answer citations")
    audit.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    answer_group = audit.add_mutually_exclusive_group(required=True)
    answer_group.add_argument("--answer", help="Host-generated answer text")
    answer_group.add_argument("--answer-file", help="File containing host-generated answer text")
    audit.add_argument("--report-json", help="Optional JSON report output path")
    audit.add_argument("--report-md", help="Optional Markdown report output path")
    audit.add_argument("--json", action="store_true", help="Emit JSON report")
    audit.set_defaults(func=_audit_citations)

    evaluate = sub.add_parser("evaluate-answer", help="Evaluate a host-generated answer offline")
    evaluate.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    evaluate_answer_group = evaluate.add_mutually_exclusive_group(required=True)
    evaluate_answer_group.add_argument("--answer", help="Host-generated answer text")
    evaluate_answer_group.add_argument("--answer-file", help="File containing host-generated answer text")
    evaluate.add_argument("--expected-term", action="append", default=[], help="Expected term; repeatable")
    evaluate.add_argument("--require-citation", action="store_true", help="Fail when evidence exists but answer lacks citations")
    evaluate.add_argument("--allow-abstain", action="store_true", help="Allow no-evidence abstention wording")
    evaluate.add_argument("--min-cited-evidence-score", type=float, help="Warn when cited evidence scores are below this threshold")
    evaluate.add_argument("--report-json", help="Optional JSON report output path")
    evaluate.add_argument("--report-md", help="Optional Markdown report output path")
    evaluate.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    evaluate.add_argument("--json", action="store_true", help="Emit JSON report")
    evaluate.set_defaults(func=_evaluate_answer)

    diagnose = sub.add_parser("diagnose-result", help="Diagnose a saved query result")
    diagnose.add_argument("--query-output", required=True, help="JSON output from query.py ask")
    diagnose.add_argument("--trace-json", help="Optional query trace JSON from --trace-json")
    diagnose.add_argument("--citation-audit", help="Optional citation audit JSON")
    diagnose.add_argument("--expected-term", action="append", default=[], help="Expected term; repeatable")
    diagnose.add_argument("--min-similarity", type=float, default=0.15)
    diagnose.add_argument("--min-evidence-score", type=float, default=0.2)
    diagnose.add_argument("--report-json", help="Optional JSON report output path")
    diagnose.add_argument("--report-md", help="Optional Markdown report output path")
    diagnose.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
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
    pollution.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
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
    rerank.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    rerank.add_argument("--json", action="store_true", help="Emit JSON report")
    rerank.set_defaults(func=_rerank_ab)

    cross_language = sub.add_parser("cross-language-ab", help="Compare saved baseline and cross-language query outputs")
    cross_language.add_argument("--baseline-output", action="append", required=True, help="Saved baseline query output JSON; repeatable")
    cross_language.add_argument("--candidate-output", action="append", required=True, help="Saved candidate query output JSON; repeatable")
    cross_language.add_argument("--baseline-label", default="baseline", help="Label for baseline outputs")
    cross_language.add_argument("--candidate-label", default="candidate", help="Label for candidate outputs")
    cross_language.add_argument("--min-top1-stability", type=float, default=0.8)
    cross_language.add_argument("--max-examples", type=int, default=10)
    cross_language.add_argument("--report-json", help="Optional JSON report output path")
    cross_language.add_argument("--report-md", help="Optional Markdown report output path")
    cross_language.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    cross_language.add_argument("--json", action="store_true", help="Emit JSON report")
    cross_language.set_defaults(func=_cross_language_ab)

    fusion = sub.add_parser("fusion", help="Fuse saved query outputs with reciprocal rank fusion")
    fusion.add_argument("--query-output", action="append", required=True, help="JSON output from query.py ask; repeatable")
    fusion.add_argument("--top-k", type=int, default=10)
    fusion.add_argument("--rrf-k", type=int, default=60)
    fusion.add_argument("--max-per-source", type=int)
    fusion.add_argument("--report-json", help="Optional JSON report output path")
    fusion.add_argument("--report-md", help="Optional Markdown report output path")
    fusion.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    fusion.add_argument("--json", action="store_true", help="Emit JSON report")
    fusion.set_defaults(func=_fusion)

    fusion_test = sub.add_parser("fusion-test", help="Run offline fusion fixture checks")
    fusion_test.add_argument("--cases", required=True, help="Fusion test cases JSON")
    fusion_test.add_argument("--top-k", type=int, help="Default top_k for cases that omit it")
    fusion_test.add_argument("--rrf-k", type=int, help="Default rrf_k for cases that omit it")
    fusion_test.add_argument("--max-per-source", type=int, help="Default max_per_source for cases that omit it")
    fusion_test.add_argument("--report-json", help="Optional JSON report output path")
    fusion_test.add_argument("--report-md", help="Optional Markdown report output path")
    fusion_test.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    fusion_test.add_argument("--json", action="store_true", help="Emit JSON report")
    fusion_test.set_defaults(func=_fusion_test)

    fallback_test = sub.add_parser("fallback-test", help="Run offline fallback coverage fixtures")
    fallback_test.add_argument("--cases", help="Optional fallback test cases JSON; defaults to built-in coverage")
    fallback_test.add_argument("--report-json", help="Optional JSON report output path")
    fallback_test.add_argument("--report-md", help="Optional Markdown report output path")
    fallback_test.add_argument("--json", action="store_true", help="Emit JSON report")
    fallback_test.set_defaults(func=_fallback_test)

    endpoint_report = sub.add_parser("endpoint-report", help="Classify query endpoints and optional reachability")
    _add_runtime_options(endpoint_report, suppress_defaults=True)
    endpoint_report.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Extra endpoint URL or label=url to classify; repeatable",
    )
    endpoint_report.add_argument(
        "--network-check",
        action="store_true",
        help="Run redacted HEAD reachability checks; disabled by default",
    )
    endpoint_report.add_argument("--timeout", type=float, help="Reachability timeout in seconds")
    endpoint_report.add_argument("--report-json", help="Optional JSON report output path")
    endpoint_report.add_argument("--report-md", help="Optional Markdown report output path")
    endpoint_report.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    endpoint_report.add_argument("--json", action="store_true", help="Emit JSON report")
    endpoint_report.set_defaults(func=_endpoint_report)

    centroid = sub.add_parser("centroid", help="Plan or build optional centroid routing artifacts")
    centroid_sub = centroid.add_subparsers(dest="centroid_command", required=True)
    centroid_build = centroid_sub.add_parser("build", help="Plan or build centroid index construction")
    centroid_build.add_argument("--plan-only", action="store_true", help="Only write a non-mutating build plan")
    centroid_build.add_argument("--kb-manifest", action="append", default=[], help="User-owned kb_manifest.json; repeatable")
    centroid_build.add_argument("--chunk-snapshot", action="append", default=[], help="User-owned ragflow_chunk_snapshot_v1 JSON; repeatable")
    centroid_build.add_argument("--index-output", help="Centroid index output path")
    centroid_build.add_argument("--embedding-provider", help="Embedding provider label")
    centroid_build.add_argument("--embedding-model", help="Embedding model")
    centroid_build.add_argument("--embedding-dimension", type=int, help="Embedding vector dimension")
    centroid_build.add_argument("--batch-size", type=int, default=64, help="Maximum chunks to process in this run")
    centroid_build.add_argument("--checkpoint", help="Checkpoint path for bounded build execution")
    centroid_build.add_argument("--resume", action="store_true", help="Resume from an existing checkpoint")
    centroid_build.add_argument("--report-json", help="Optional JSON report output path")
    centroid_build.add_argument("--report-md", help="Optional Markdown report output path")
    centroid_build.add_argument("--json", action="store_true", help="Emit JSON report")
    centroid_build.set_defaults(func=_centroid_build)

    ask = sub.add_parser("ask", help="Ask a question against RAGFlow")
    _add_runtime_options(ask, suppress_defaults=True)
    _add_routing_option(ask)
    ask.add_argument("question", help="Question to retrieve evidence for")
    ask.add_argument("--mode", choices=["auto", "direct", "agentic"], default="auto")
    _add_centroid_tie_breaker_options(ask, include_query_vector=True)
    ask.add_argument("--dataset-id", action="append", default=[], help="RAGFlow dataset ID; repeatable")
    ask.add_argument("--kb", action="append", default=[], help="RAGFlow KB/dataset name; repeatable")
    ask.add_argument("--kb-manifest", help="Path to kb_manifest.json")
    ask.add_argument("--top-k", type=int)
    ask.add_argument("--similarity-threshold", type=float)
    ask.add_argument("--fusion", choices=["none", "rrf"], default="none", help="Fuse per-dataset retrieval results when multiple dataset IDs are selected")
    ask.add_argument("--rewrite", choices=["none", "simple", "translate", "hyde"], default="none", help="Opt-in query rewrite planning before retrieval")
    ask.add_argument("--multi-query", help="JSON file with additional host-owned query variants")
    ask.add_argument("--host-assisted", action="store_true", help="Return evidence for host agent synthesis")
    ask.add_argument("--max-subqueries", type=int, default=4, help="Maximum deterministic subqueries for --mode agentic --host-assisted")
    ask.add_argument("--reflection-budget", type=int, default=0, help="Record a strict reflection budget in the agentic plan; reflection is not executed")
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
