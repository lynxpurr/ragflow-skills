"""Deterministic planning helpers for experimental agentic query flows."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .observability import audit_citations, evaluate_answer, evidence_from_query_payload
from .query_intent import (
    QueryIntentError,
    classify_query_intent,
    normalize_query_question,
    tokenize_query_text,
)


AGENTIC_PLAN_SCHEMA = "ragflow_agentic_plan_v1"
AGENTIC_TRACE_SCHEMA = "ragflow_agentic_trace_v1"
HOST_SYNTHESIS_CONTRACT_SCHEMA = "ragflow_host_synthesis_contract_v1"
AGENTIC_ANSWER_REQUEST_SCHEMA = "ragflow_agentic_answer_request_v1"
AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA = "ragflow_agentic_answer_review_report_v1"


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _preview_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _issue_counts(issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "errors": sum(1 for issue in issues if issue.get("severity") == "error"),
        "warnings": sum(1 for issue in issues if issue.get("severity") == "warning"),
        "infos": sum(1 for issue in issues if issue.get("severity") == "info"),
    }


def _issues_ok(issues: Sequence[Mapping[str, Any]]) -> bool:
    return not any(issue.get("severity") == "error" for issue in issues)


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    field: str | None = None,
    recommendation: str | None = None,
) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    if field:
        issue["field"] = field
    if recommendation:
        issue["recommendation"] = recommendation
    issues.append(issue)


def _query_payload_hash(query_payload: Mapping[str, Any]) -> str:
    hash_input = {
        "question": query_payload.get("question"),
        "dataset_ids": query_payload.get("dataset_ids"),
        "retrieval_status": query_payload.get("retrieval_status"),
        "agentic_plan": query_payload.get("agentic_plan"),
        "agentic_trace": query_payload.get("agentic_trace"),
        "host_synthesis_contract": query_payload.get("host_synthesis_contract"),
        "evidence": evidence_from_query_payload(query_payload),
    }
    return _stable_digest(hash_input)


def _agentic_context_from_query_payload(query_payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = query_payload.get("metadata") if isinstance(query_payload.get("metadata"), Mapping) else {}
    trace = query_payload.get("trace") if isinstance(query_payload.get("trace"), Mapping) else {}
    return {
        "agentic_plan": query_payload.get("agentic_plan") or metadata.get("agentic_plan") or trace.get("agentic_plan"),
        "agentic_trace": query_payload.get("agentic_trace") or metadata.get("agentic_trace") or trace.get("agentic_trace"),
        "host_synthesis_contract": (
            query_payload.get("host_synthesis_contract")
            or metadata.get("host_synthesis_contract")
            or trace.get("host_synthesis_contract")
        ),
        "retrieval_status_report": query_payload.get("retrieval_status_report")
        or metadata.get("retrieval_status_report")
        or trace.get("retrieval", {}).get("status_report")
        if isinstance(trace.get("retrieval"), Mapping)
        else query_payload.get("retrieval_status_report") or metadata.get("retrieval_status_report"),
    }


def _answer_text_from_candidate(candidate: Mapping[str, Any]) -> str | None:
    raw_answer = candidate.get("answer")
    if isinstance(raw_answer, str):
        return raw_answer
    if isinstance(raw_answer, Mapping):
        for key in ("text", "content", "message"):
            value = _clean_string(raw_answer.get(key))
            if value:
                return value
    for key in ("text", "content", "message", "response", "output"):
        value = _clean_string(candidate.get(key))
        if value:
            return value
    return None


def _answer_review_issue_from_report(*, prefix: str, raw_issue: Mapping[str, Any]) -> dict[str, Any]:
    issue = {
        "severity": str(raw_issue.get("severity") or "warning"),
        "code": f"{prefix}_{raw_issue.get('code', 'issue')}",
        "message": str(raw_issue.get("message") or ""),
    }
    field = raw_issue.get("field")
    if isinstance(field, str):
        issue["field"] = field
    detail = raw_issue.get("detail")
    if isinstance(detail, Mapping):
        issue["detail"] = dict(detail)
    return issue


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


def create_agentic_answer_request(
    query_payload: Mapping[str, Any],
    *,
    model_label: str | None = None,
    provider_label: str | None = None,
    include_evidence_previews: bool = True,
    max_evidence_chars: int = 1200,
    require_citations: bool = True,
    allow_abstain: bool = True,
) -> dict[str, Any]:
    """Create a no-LLM request artifact for external agentic answer synthesis."""

    if not isinstance(query_payload, Mapping):
        raise AgenticPlanError("query payload must be a JSON object")
    if max_evidence_chars < 0:
        raise AgenticPlanError("max_evidence_chars must be non-negative")
    evidence = evidence_from_query_payload(query_payload)
    context = _agentic_context_from_query_payload(query_payload)
    issues: list[dict[str, Any]] = []
    if not evidence:
        _append_issue(
            issues,
            severity="warning",
            code="agentic_answer_request_no_evidence",
            message="query payload does not contain retrievable evidence; external answer should abstain",
            field="evidence",
        )
    contract = context.get("host_synthesis_contract")
    if isinstance(contract, Mapping):
        policy = contract.get("citation_policy") if isinstance(contract.get("citation_policy"), Mapping) else {}
        if require_citations and policy.get("required") is False and evidence:
            _append_issue(
                issues,
                severity="warning",
                code="agentic_answer_request_citation_policy_relaxed",
                message="request requires citations but host synthesis contract does not mark citations required",
                field="host_synthesis_contract.citation_policy.required",
            )
    else:
        _append_issue(
            issues,
            severity="warning",
            code="agentic_answer_request_contract_missing",
            message="query payload does not contain ragflow_host_synthesis_contract_v1; request will include a conservative citation policy",
            field="host_synthesis_contract",
        )

    evidence_items: list[dict[str, Any]] = []
    for item in evidence:
        evidence_item = {
            "rank": item.get("rank"),
            "citation_id": item.get("citation_id"),
            "score": item.get("score"),
            "document_name": item.get("document_name"),
            "document_id": item.get("document_id"),
            "dataset_id": item.get("dataset_id"),
            "chunk_id": item.get("chunk_id"),
        }
        if include_evidence_previews:
            evidence_item["content_preview"] = _preview_text(item.get("content_preview"), limit=max_evidence_chars)
            evidence_item["preview_truncated"] = len(str(item.get("content_preview") or "")) > max_evidence_chars
            evidence_item["max_evidence_chars"] = max_evidence_chars
        evidence_items.append(evidence_item)

    request_core = {
        "schema": AGENTIC_ANSWER_REQUEST_SCHEMA,
        "question": query_payload.get("question"),
        "query_payload_hash": _query_payload_hash(query_payload),
        "model_label": model_label,
        "provider_label": provider_label,
        "evidence": evidence_items,
        "require_citations": require_citations,
        "allow_abstain": allow_abstain,
    }
    return {
        "ok": _issues_ok(issues),
        "schema": AGENTIC_ANSWER_REQUEST_SCHEMA,
        "created_at": _now(),
        "advisory": True,
        "llm_invoked": False,
        "request_hash": _stable_digest(request_core),
        "query_payload_hash": request_core["query_payload_hash"],
        "question": query_payload.get("question"),
        "model": {
            "provider_label": provider_label,
            "model_label": model_label,
            "script_owned_llm_calls": 0,
        },
        "summary": {
            **_issue_counts(issues),
            "evidence_count": len(evidence_items),
            "include_evidence_previews": include_evidence_previews,
            "max_evidence_chars": max_evidence_chars,
            "require_citations": require_citations,
            "allow_abstain": allow_abstain,
            "llm_invoked": False,
        },
        "redaction": {
            "evidence_previews_included": include_evidence_previews,
            "document_ids_included": True,
            "dataset_ids_included": True,
            "review_redaction_report_recommended": True,
            "notes": [
                "Run review commands with --redaction-report before sharing request, review, or Markdown outputs externally.",
                "Do not include credentials, private endpoints, or authorization material in external answer candidates.",
            ],
        },
        "instructions": {
            "purpose": "Synthesize an advisory answer grounded only in the listed retrieved evidence.",
            "required_output_shape": {
                "schema": "ragflow_agentic_answer_candidate_v1",
                "advisory": True,
                "generated": True,
                "answer": "string with numeric citations such as [1]",
            },
            "requirements": [
                "Return JSON only unless the host explicitly requests plain text.",
                "Set advisory to true when returning JSON.",
                "Set generated to true when returning JSON.",
                "Use only evidence items listed in this request.",
                "Use numeric bracket citations that match available evidence ranks.",
                "Do not invent facts, credentials, private endpoints, or authorization material.",
                "Abstain or ask for clarification when evidence is missing or insufficient.",
                "Generated answers are advisory and must pass ragflow-query agentic-answer review before acceptance.",
            ],
            "review_command": "ragflow-query agentic-answer review --query-output QUERY.json --candidate CANDIDATE.json",
        },
        "citation_policy": {
            "compatible_with": "audit-citations",
            "format": "numeric_bracket",
            "pattern": r"\[\d+\]",
            "required": bool(require_citations and evidence_items),
            "valid_ranks": [item.get("rank") for item in evidence_items if isinstance(item.get("rank"), int)],
            "valid_citation_ids": [
                item.get("citation_id") for item in evidence_items if isinstance(item.get("citation_id"), str)
            ],
            "no_evidence_behavior": "abstain_or_ask_clarification",
        },
        "answer_policy": {
            "source": "retrieved_evidence_only",
            "allow_external_facts": False,
            "allow_uncited_claims": False,
            "allow_abstain": allow_abstain,
        },
        "agentic_context": {
            key: value
            for key, value in context.items()
            if isinstance(value, Mapping)
        },
        "evidence": evidence_items,
        "issues": issues,
    }


def review_agentic_answer(
    query_payload: Mapping[str, Any],
    answer: str,
    *,
    candidate: Mapping[str, Any] | None = None,
    request: Mapping[str, Any] | None = None,
    expected_terms: Sequence[str] | None = None,
    require_citation: bool = True,
    allow_abstain: bool = True,
    min_cited_evidence_score: float | None = None,
    require_advisory: bool = True,
    require_generated: bool = True,
) -> dict[str, Any]:
    """Review an externally synthesized agentic answer with deterministic gates."""

    if not isinstance(query_payload, Mapping):
        raise AgenticPlanError("query payload must be a JSON object")
    answer_text = str(answer or "")
    issues: list[dict[str, Any]] = []
    candidate_schema = candidate.get("schema") if isinstance(candidate, Mapping) else None
    if candidate is not None:
        if not isinstance(candidate, Mapping):
            _append_issue(
                issues,
                severity="error",
                code="agentic_answer_candidate_invalid",
                message="candidate answer must be a JSON object when supplied",
                field="candidate",
            )
        else:
            if candidate_schema not in {None, "ragflow_agentic_answer_candidate_v1"}:
                _append_issue(
                    issues,
                    severity="warning",
                    code="agentic_answer_candidate_schema_unrecognized",
                    message="candidate schema is not ragflow_agentic_answer_candidate_v1",
                    field="candidate.schema",
                )
            if require_advisory and candidate.get("advisory") is not True:
                _append_issue(
                    issues,
                    severity="error",
                    code="agentic_answer_not_advisory",
                    message="external agentic answers must set advisory to true",
                    field="candidate.advisory",
                )
            if require_generated and candidate.get("generated") is not True:
                _append_issue(
                    issues,
                    severity="error",
                    code="agentic_answer_not_generated",
                    message="external agentic answers must set generated to true",
                    field="candidate.generated",
                )

    request_hash = None
    if request is not None:
        if not isinstance(request, Mapping):
            _append_issue(
                issues,
                severity="error",
                code="agentic_answer_request_invalid",
                message="agentic answer request must be a JSON object",
                field="request",
            )
        elif request.get("schema") != AGENTIC_ANSWER_REQUEST_SCHEMA:
            _append_issue(
                issues,
                severity="error",
                code="agentic_answer_request_schema_invalid",
                message=f"request schema must be {AGENTIC_ANSWER_REQUEST_SCHEMA}",
                field="request.schema",
            )
        else:
            request_hash = _clean_string(request.get("request_hash"))
            query_hash = _query_payload_hash(query_payload)
            request_query_hash = _clean_string(request.get("query_payload_hash"))
            if request_query_hash and request_query_hash != query_hash:
                _append_issue(
                    issues,
                    severity="error",
                    code="agentic_answer_request_query_mismatch",
                    message="request was built from a different query output",
                    field="request.query_payload_hash",
                )
            request_policy = request.get("citation_policy")
            if isinstance(request_policy, Mapping) and request_policy.get("required") is False and require_citation:
                _append_issue(
                    issues,
                    severity="warning",
                    code="agentic_answer_review_citation_policy_stricter_than_request",
                    message="review requires citations while the original request did not",
                    field="request.citation_policy.required",
                )

    evidence = evidence_from_query_payload(query_payload)
    citation_audit = audit_citations(answer_text, evidence)
    evaluation_report = evaluate_answer(
        query_payload,
        answer_text,
        expected_terms=expected_terms,
        require_citation=require_citation,
        allow_abstain=allow_abstain,
        min_cited_evidence_score=min_cited_evidence_score,
        citation_audit=citation_audit,
    )
    for raw_issue in citation_audit.get("issues", []):
        if isinstance(raw_issue, Mapping):
            issues.append(_answer_review_issue_from_report(prefix="citation_audit", raw_issue=raw_issue))
    for raw_issue in evaluation_report.get("issues", []):
        if isinstance(raw_issue, Mapping):
            prefixed = _answer_review_issue_from_report(prefix="answer_evaluation", raw_issue=raw_issue)
            if prefixed not in issues:
                issues.append(prefixed)

    summary = evaluation_report.get("summary") if isinstance(evaluation_report.get("summary"), Mapping) else {}
    return {
        "ok": _issues_ok(issues),
        "schema": AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA,
        "created_at": _now(),
        "candidate_schema": candidate_schema,
        "request_schema": AGENTIC_ANSWER_REQUEST_SCHEMA if request is not None else None,
        "request_hash": request_hash,
        "query_payload_hash": _query_payload_hash(query_payload),
        "summary": {
            **_issue_counts(issues),
            "evidence_count": len(evidence),
            "citation_count": int(summary.get("citation_count") or 0),
            "invalid_citation_count": int(summary.get("invalid_citation_count") or 0),
            "unsupported_uncited_statement_count": int(summary.get("unsupported_uncited_statement_count") or 0),
            "expected_term_count": int(summary.get("expected_term_count") or 0),
            "missing_expected_term_count": int(summary.get("missing_expected_term_count") or 0),
            "abstained": bool(summary.get("abstained")),
            "answer_evaluation_ok": bool(evaluation_report.get("ok")),
            "citation_audit_ok": bool(citation_audit.get("ok")),
            "advisory": candidate.get("advisory") is True if isinstance(candidate, Mapping) else None,
            "generated": candidate.get("generated") is True if isinstance(candidate, Mapping) else None,
            "script_owned_llm_calls": 0,
        },
        "answer": {
            "chars": len(answer_text),
            "preview": _preview_text(answer_text, limit=220),
        },
        "policy": {
            "require_citation": require_citation,
            "allow_abstain": allow_abstain,
            "min_cited_evidence_score": min_cited_evidence_score,
            "require_advisory": require_advisory,
            "require_generated": require_generated,
            "script_owned_llm_calls": 0,
        },
        "issues": issues,
        "citation_audit": citation_audit,
        "answer_evaluation": evaluation_report,
        "candidate_preview": (
            {
                "schema": candidate.get("schema"),
                "advisory": candidate.get("advisory"),
                "generated": candidate.get("generated"),
                "answer_chars": len(answer_text),
            }
            if isinstance(candidate, Mapping)
            else None
        ),
        "recommendations": [
            "Accept external agentic answers only after this review passes without errors.",
            "Keep answer synthesis host-owned until explicit LLM configuration and release gates are added.",
            "Use ragflow-query audit-citations or evaluate-answer for additional manual review when warnings remain.",
        ],
    }


def render_agentic_answer_request_markdown(request: Mapping[str, Any]) -> str:
    """Render a compact Markdown agentic-answer request."""

    summary = request.get("summary", {}) if isinstance(request.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Agentic Answer Request",
        "",
        f"- schema: `{request.get('schema', AGENTIC_ANSWER_REQUEST_SCHEMA)}`",
        f"- llm_invoked: `{str(bool(request.get('llm_invoked'))).lower()}`",
        f"- evidence_count: `{summary.get('evidence_count', 0)}`",
        f"- require_citations: `{str(bool(summary.get('require_citations'))).lower()}`",
        "",
        "## Evidence",
        "",
    ]
    evidence = request.get("evidence", []) if isinstance(request.get("evidence"), list) else []
    if evidence:
        lines.extend(["| Rank | Citation | Document | Preview |", "| ---: | --- | --- | --- |"])
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            preview = str(item.get("content_preview") or "").replace("|", "\\|")
            document = str(item.get("document_name") or item.get("document_id") or "").replace("|", "\\|")
            lines.append(f"| {item.get('rank', '')} | `{item.get('citation_id', '')}` | {document} | {preview} |")
    else:
        lines.append("- None")
    issues = request.get("issues", []) if isinstance(request.get("issues"), list) else []
    if issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def render_agentic_answer_review_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown agentic-answer review report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    answer = report.get("answer", {}) if isinstance(report.get("answer"), Mapping) else {}
    lines = [
        "# RAGFlow Agentic Answer Review",
        "",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
        f"- schema: `{report.get('schema', AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA)}`",
        f"- evidence_count: `{summary.get('evidence_count', 0)}`",
        f"- citation_count: `{summary.get('citation_count', 0)}`",
        f"- invalid_citation_count: `{summary.get('invalid_citation_count', 0)}`",
        f"- errors: `{summary.get('errors', 0)}`",
        f"- warnings: `{summary.get('warnings', 0)}`",
        "",
        "## Issues",
        "",
    ]
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    preview = answer.get("preview")
    if isinstance(preview, str) and preview:
        lines.extend(["", "## Answer Preview", "", preview])
    return "\n".join(lines) + "\n"


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
