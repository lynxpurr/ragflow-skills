"""Deterministic planning helpers for experimental agentic query flows."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .query_intent import (
    QueryIntentError,
    classify_query_intent,
    normalize_query_question,
    tokenize_query_text,
)


AGENTIC_PLAN_SCHEMA = "ragflow_agentic_plan_v1"
AGENTIC_TRACE_SCHEMA = "ragflow_agentic_trace_v1"
HOST_SYNTHESIS_CONTRACT_SCHEMA = "ragflow_host_synthesis_contract_v1"


class AgenticPlanError(ValueError):
    """Raised when an agentic plan cannot be built safely."""


def _classify_complexity(question: str, tokens: list[str], intent: str) -> dict[str, Any]:
    lowered = question.lower()
    marker_count = sum(
        1
        for pattern in (
            r"\band\b",
            r"\bthen\b",
            r"\balso\b",
            r"\bcompare\b",
            r"\bversus\b",
            r"\bvs\.?\b",
            r"\btrade-?offs?\b",
            r"\bsteps?\b",
            r"\barchitecture\b",
        )
        if re.search(pattern, lowered)
    )
    question_marks = len(re.findall(r"[?？]", question))
    if intent in {"clarification_needed", "out_of_scope"}:
        complexity = "simple"
        reasons = [f"intent is {intent}; no retrieval decomposition planned"]
    elif len(tokens) > 28 or marker_count >= 3 or question_marks > 1:
        complexity = "complex"
        reasons = ["long or multi-part query detected"]
    elif intent == "comparison" or len(tokens) > 12 or marker_count:
        complexity = "moderate"
        reasons = ["query has comparison, length, or coordination markers"]
    else:
        complexity = "simple"
        reasons = ["short single-part query"]
    return {
        "complexity": complexity,
        "token_count": len(tokens),
        "marker_count": marker_count,
        "question_mark_count": question_marks,
        "reasons": reasons,
    }


def _clause_to_query(clause: str) -> str:
    clause = re.sub(r"^(compare|explain|describe|summarize|analyze)\s+", "", clause.strip(), flags=re.I)
    clause = clause.strip(" ,.;:!?")
    if not clause:
        return ""
    if re.match(r"^(what|how|why|when|where|which|who)\b", clause, flags=re.I):
        return clause[0].upper() + clause[1:]
    return clause[0].upper() + clause[1:]


def _dedupe_queries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        query = str(item.get("query") or "").strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        deduped.append({**item, "query": query})
    return deduped


def _safe_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_non_negative_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _retrieval_query_token_count(retrieval_queries: Any) -> int:
    if not isinstance(retrieval_queries, list):
        return 0
    total = 0
    for item in retrieval_queries:
        if isinstance(item, Mapping):
            total += len(tokenize_query_text(str(item.get("query") or "")))
    return total


def _evidence_citation_ids(evidence: Sequence[Mapping[str, Any]]) -> list[str]:
    citation_ids: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        citation_id = str(item.get("citation_id") or "").strip()
        if not re.fullmatch(r"\[\d+\]", citation_id) or citation_id in seen:
            continue
        seen.add(citation_id)
        citation_ids.append(citation_id)
    return citation_ids


def _evidence_ranks(evidence: Sequence[Mapping[str, Any]]) -> list[int]:
    ranks: list[int] = []
    seen: set[int] = set()
    for item in evidence:
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank <= 0 or rank in seen:
            continue
        seen.add(rank)
        ranks.append(rank)
    return ranks


def _subqueries(question: str, *, intent: str, complexity: str, max_subqueries: int) -> list[dict[str, Any]]:
    if max_subqueries <= 0 or complexity == "simple" or intent in {"clarification_needed", "out_of_scope"}:
        return []
    lowered = question.lower()
    raw_parts = re.split(r"\b(?:and|then|also|versus|vs)\b|[;；]", question, flags=re.I)
    candidates = [_clause_to_query(part) for part in raw_parts]
    candidates = [item for item in candidates if len(tokenize_query_text(item)) >= 2]
    if intent == "comparison" and len(candidates) < 2:
        candidates.extend([f"{question.rstrip('?.!')} key criteria", f"{question.rstrip('?.!')} differences"])
    if "pros and cons" in lowered and not any("pros" in item.lower() for item in candidates):
        candidates.extend([f"{question.rstrip('?.!')} advantages", f"{question.rstrip('?.!')} disadvantages"])
    deduped = _dedupe_queries(
        [
            {
                "id": f"subquery-{index}",
                "query": query,
                "source": "agentic_decomposition",
                "kind": "subquery",
            }
            for index, query in enumerate(candidates, start=1)
        ]
    )
    return deduped[:max_subqueries]


def build_agentic_plan(
    question: str,
    *,
    retrieval_mode: str = "auto",
    rewrite_mode: str = "simple",
    max_subqueries: int = 4,
    reflection_budget: int = 0,
    require_citations: bool = True,
) -> dict[str, Any]:
    """Build a deterministic, non-executing agentic query plan."""

    try:
        original_query = normalize_query_question(question)
    except QueryIntentError as exc:
        raise AgenticPlanError(str(exc)) from exc
    normalized_retrieval_mode = str(retrieval_mode or "auto").strip().lower()
    if normalized_retrieval_mode not in {"auto", "direct"}:
        raise AgenticPlanError("retrieval_mode must be one of: auto, direct")
    normalized_rewrite_mode = str(rewrite_mode or "none").strip().lower()
    if normalized_rewrite_mode not in {"none", "simple", "translate"}:
        raise AgenticPlanError("rewrite_mode must be one of: none, simple, translate")
    if not isinstance(max_subqueries, int) or max_subqueries < 0 or max_subqueries > 8:
        raise AgenticPlanError("max_subqueries must be an integer between 0 and 8")
    if not isinstance(reflection_budget, int) or reflection_budget < 0 or reflection_budget > 3:
        raise AgenticPlanError("reflection_budget must be an integer between 0 and 3")

    token_values = tokenize_query_text(original_query)
    intent = classify_query_intent(original_query)
    complexity = _classify_complexity(original_query, token_values, str(intent["intent"]))
    subqueries = _subqueries(
        original_query,
        intent=str(intent["intent"]),
        complexity=str(complexity["complexity"]),
        max_subqueries=max_subqueries,
    )
    should_retrieve = intent["intent"] not in {"clarification_needed", "out_of_scope"}
    retrieval_queries = []
    if should_retrieve:
        retrieval_queries.append(
            {
                "id": "original",
                "query": original_query,
                "source": "original",
                "kind": "original",
            }
        )
        retrieval_queries.extend(subqueries)
    retrieval_queries = _dedupe_queries(retrieval_queries)
    retrieval_query_tokens = _retrieval_query_token_count(retrieval_queries)

    if intent["intent"] == "clarification_needed":
        status = "needs_clarification"
    elif intent["intent"] == "out_of_scope":
        status = "rejected"
    else:
        status = "planned"

    steps: list[dict[str, Any]] = [
        {
            "id": "classify",
            "kind": "classification",
            "status": "planned",
            "intent": intent["intent"],
            "complexity": complexity["complexity"],
        }
    ]
    if status == "needs_clarification":
        steps.append(
            {
                "id": "clarify",
                "kind": "clarification",
                "status": "planned",
                "action": "ask_clarifying_question",
            }
        )
    elif status == "rejected":
        steps.append(
            {
                "id": "reject",
                "kind": "scope_guard",
                "status": "planned",
                "action": "reject_or_redirect_without_retrieval",
            }
        )
    else:
        if normalized_rewrite_mode != "none":
            steps.append(
                {
                    "id": "rewrite",
                    "kind": "rewrite_plan",
                    "status": "planned",
                    "mode": normalized_rewrite_mode,
                }
            )
        for item in retrieval_queries:
            steps.append(
                {
                    "id": f"retrieve-{item['id']}",
                    "kind": "retrieval",
                    "status": "planned",
                    "query_id": item["id"],
                    "retrieval_mode": normalized_retrieval_mode,
                }
            )
        if reflection_budget:
            steps.append(
                {
                    "id": "reflect",
                    "kind": "reflection",
                    "status": "planned",
                    "max_iterations": reflection_budget,
                }
            )
        steps.append(
            {
                "id": "synthesize",
                "kind": "host_synthesis",
                "status": "deferred_to_host",
                "citation_policy": "numeric_required" if require_citations else "numeric_recommended",
            }
        )

    warnings = []
    if status == "needs_clarification":
        warnings.append("plan requires clarification before retrieval")
    if status == "rejected":
        warnings.append("plan rejects retrieval because the question appears outside saved KB evidence")
    intent_reasons = [str(item) for item in intent.get("reasons", []) if str(item)]
    complexity_reasons = [str(item) for item in complexity.get("reasons", []) if str(item)]
    return {
        "ok": True,
        "schema": AGENTIC_PLAN_SCHEMA,
        "status": status,
        "question": original_query,
        "classification": {
            "intent": intent["intent"],
            "confidence": intent["confidence"],
            "intent_reasons": intent_reasons,
            "complexity": complexity["complexity"],
            "token_count": complexity["token_count"],
            "marker_count": complexity["marker_count"],
            "question_mark_count": complexity["question_mark_count"],
            "complexity_reasons": complexity_reasons,
            "reasons": [*intent_reasons, *complexity_reasons],
        },
        "parameters": {
            "retrieval_mode": normalized_retrieval_mode,
            "rewrite_mode": normalized_rewrite_mode,
            "max_subqueries": max_subqueries,
            "reflection_budget": reflection_budget,
            "require_citations": bool(require_citations),
        },
        "retrieval_queries": retrieval_queries,
        "steps": steps,
        "trace_template": {
            "schema": AGENTIC_TRACE_SCHEMA,
            "status": "not_executed",
            "llm_calls": 0,
            "retrieval_calls": 0,
            "planned_retrieval_call_count": len(retrieval_queries),
            "reflection_iterations": 0,
            "latency_ms": None,
            "model": None,
            "estimated_tokens": 0,
            "estimated_cost_usd": 0.0,
            "token_estimate": {
                "question_tokens": len(token_values),
                "retrieval_query_tokens": retrieval_query_tokens,
                "script_llm_input_tokens": 0,
                "script_llm_output_tokens": 0,
                "script_llm_total_tokens": 0,
            },
            "cost_trace": {
                "currency": "USD",
                "model": None,
                "estimated_total_usd": 0.0,
                "script_owned_llm_estimated_usd": 0.0,
                "retrieval_estimated_usd": None,
                "notes": [
                    "agentic plan does not execute script-owned LLM calls",
                    "RAGFlow retrieval billing is provider-owned and not estimated",
                ],
            },
        },
        "guards": {
            "llm_generation": "disabled",
            "ragflow_mutation": "disabled",
            "live_retrieval": "not_executed_by_plan",
            "answer_generation": "host_owned",
        },
        "summary": {
            "intent": intent["intent"],
            "complexity": complexity["complexity"],
            "retrieval_query_count": len(retrieval_queries),
            "generated_subquery_count": len([item for item in retrieval_queries if item.get("kind") == "subquery"]),
            "step_count": len(steps),
            "llm_calls": 0,
            "retrieval_calls": 0,
            "planned_retrieval_call_count": len(retrieval_queries),
            "reflection_budget": reflection_budget,
        },
        "warnings": warnings,
    }


def build_agentic_execution_trace(
    plan: Mapping[str, Any],
    *,
    retrieval_call_count: int = 0,
    retrieval_latency_ms: float | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    llm_call_count: int = 0,
    reflection_iterations: int = 0,
    model: str | None = None,
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Build an execution trace for a deterministic agentic retrieval run."""

    if not isinstance(plan, Mapping) or plan.get("schema") != AGENTIC_PLAN_SCHEMA:
        raise AgenticPlanError("agentic plan must be a ragflow_agentic_plan_v1 object")
    retrieval_queries = plan.get("retrieval_queries", [])
    planned_retrieval_call_count = len(retrieval_queries) if isinstance(retrieval_queries, list) else 0
    actual_retrieval_calls = _safe_non_negative_int(retrieval_call_count)
    actual_llm_calls = _safe_non_negative_int(llm_call_count)
    actual_reflections = _safe_non_negative_int(reflection_iterations)
    latency_ms = round(_safe_non_negative_float(retrieval_latency_ms), 3) if retrieval_latency_ms is not None else None
    query_token_count = len(tokenize_query_text(str(plan.get("question") or "")))
    retrieval_query_tokens = _retrieval_query_token_count(retrieval_queries)
    plan_status = str(plan.get("status") or "")
    if plan_status in {"needs_clarification", "rejected"}:
        status = plan_status
    elif actual_retrieval_calls:
        status = "retrieval_executed"
    else:
        status = "not_executed"
    script_llm_total_tokens = 0
    cost_usd = round(_safe_non_negative_float(estimated_cost_usd), 8)
    parameters = plan.get("parameters", {}) if isinstance(plan.get("parameters"), Mapping) else {}
    return {
        "schema": AGENTIC_TRACE_SCHEMA,
        "status": status,
        "plan_schema": plan.get("schema"),
        "plan_status": plan_status,
        "llm_calls": actual_llm_calls,
        "retrieval_calls": actual_retrieval_calls,
        "planned_retrieval_call_count": planned_retrieval_call_count,
        "reflection_iterations": actual_reflections,
        "reflection_budget": _safe_non_negative_int(parameters.get("reflection_budget", 0)),
        "latency_ms": latency_ms,
        "timings_ms": {
            "retrieval": latency_ms,
        },
        "model": model,
        "estimated_tokens": script_llm_total_tokens,
        "estimated_cost_usd": cost_usd,
        "token_estimate": {
            "question_tokens": query_token_count,
            "retrieval_query_tokens": retrieval_query_tokens,
            "script_llm_input_tokens": 0,
            "script_llm_output_tokens": 0,
            "script_llm_total_tokens": script_llm_total_tokens,
        },
        "cost_trace": {
            "currency": "USD",
            "model": model,
            "estimated_total_usd": cost_usd,
            "script_owned_llm_estimated_usd": cost_usd,
            "retrieval_estimated_usd": None,
            "notes": [
                "no script-owned LLM calls were made",
                "RAGFlow retrieval billing is provider-owned and not estimated",
            ],
        },
        "started_at": started_at,
        "finished_at": finished_at,
        "script_owned_synthesis": False,
    }


def build_host_synthesis_contract(
    plan: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    *,
    retrieval_status: Mapping[str, Any] | None = None,
    require_citations: bool | None = None,
) -> dict[str, Any]:
    """Build a host-owned answer synthesis contract from retrieved evidence."""

    if not isinstance(plan, Mapping) or plan.get("schema") != AGENTIC_PLAN_SCHEMA:
        raise AgenticPlanError("agentic plan must be a ragflow_agentic_plan_v1 object")
    evidence_items = [dict(item) for item in evidence if isinstance(item, Mapping)]
    citation_ids = _evidence_citation_ids(evidence_items)
    ranks = _evidence_ranks(evidence_items)
    parameters = plan.get("parameters", {}) if isinstance(plan.get("parameters"), Mapping) else {}
    citations_required = bool(parameters.get("require_citations", True)) if require_citations is None else bool(require_citations)
    status_name = str(retrieval_status.get("status")) if isinstance(retrieval_status, Mapping) else ""
    blocked_statuses = {"clarification", "rejected", "error", "timeout"}
    ready = bool(evidence_items) and status_name not in blocked_statuses
    contract_status = status_name if status_name in blocked_statuses else ("ready" if ready else "no_evidence")
    return {
        "ok": True,
        "schema": HOST_SYNTHESIS_CONTRACT_SCHEMA,
        "status": contract_status,
        "plan_schema": plan.get("schema"),
        "plan_status": plan.get("status"),
        "retrieval_status": status_name or None,
        "answer_generation": "host_owned",
        "script_owned_synthesis": False,
        "citation_policy": {
            "compatible_with": "audit-citations",
            "format": "numeric_bracket",
            "pattern": r"\[\d+\]",
            "required": citations_required and bool(evidence_items),
            "valid_citation_ids": citation_ids,
            "valid_ranks": ranks,
            "evidence_count": len(evidence_items),
            "no_evidence_behavior": "abstain_or_ask_clarification",
        },
        "evidence_policy": {
            "source": "retrieved_evidence_only",
            "allow_external_facts": False,
            "allow_uncited_claims": False,
            "minimum_supported_answer_citations": 1 if citations_required and evidence_items else 0,
        },
        "audit": {
            "command": "ragflow-query audit-citations",
            "query_output_field": "evidence",
            "answer_citation_format": "[n]",
        },
        "guards": {
            "llm_generation": "host_owned",
            "script_llm_calls": 0,
            "ragflow_mutation": "disabled",
        },
    }


def render_agentic_plan_markdown(plan: Mapping[str, Any]) -> str:
    """Render a compact Markdown agentic plan."""

    summary = plan.get("summary", {}) if isinstance(plan.get("summary"), Mapping) else {}
    classification = plan.get("classification", {}) if isinstance(plan.get("classification"), Mapping) else {}
    lines = [
        "# RAGFlow Agentic Plan",
        "",
        f"- schema: `{plan.get('schema', AGENTIC_PLAN_SCHEMA)}`",
        f"- status: `{plan.get('status', '')}`",
        f"- intent: `{summary.get('intent', classification.get('intent', ''))}`",
        f"- complexity: `{summary.get('complexity', classification.get('complexity', ''))}`",
        f"- retrieval_query_count: `{summary.get('retrieval_query_count', 0)}`",
        f"- llm_calls: `{summary.get('llm_calls', 0)}`",
        "",
        "## Retrieval Queries",
        "",
    ]
    retrieval_queries = plan.get("retrieval_queries", [])
    if isinstance(retrieval_queries, list) and retrieval_queries:
        lines.extend(["| id | kind | source | query |", "| --- | --- | --- | --- |"])
        for item in retrieval_queries:
            if not isinstance(item, Mapping):
                continue
            query = str(item.get("query", "")).replace("|", "\\|")
            lines.append(
                f"| `{item.get('id', '')}` | `{item.get('kind', '')}` | `{item.get('source', '')}` | {query} |"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Steps", ""])
    for step in plan.get("steps", []):
        if isinstance(step, Mapping):
            lines.append(f"- `{step.get('id')}` `{step.get('kind')}`: `{step.get('status')}`")
    warnings = [str(item) for item in plan.get("warnings", []) if str(item)]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"
