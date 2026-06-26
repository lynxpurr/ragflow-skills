"""Deterministic query intent classification and route decisions."""

from __future__ import annotations

import re
from typing import Any, Mapping


QUERY_INTENT_SCHEMA = "ragflow_query_intent_v1"
QUERY_ROUTE_DECISION_SCHEMA = "ragflow_query_route_decision_v1"


class QueryIntentError(ValueError):
    """Raised when query intent input cannot be classified safely."""


def normalize_query_question(value: Any) -> str:
    if not isinstance(value, str):
        raise QueryIntentError("question must be a string")
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        raise QueryIntentError("question must be non-empty")
    return normalized


def tokenize_query_text(text: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]+", text.lower())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _validate_threshold(value: float) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise QueryIntentError("low_confidence_threshold must be a number between 0 and 1") from exc
    if threshold < 0 or threshold > 1:
        raise QueryIntentError("low_confidence_threshold must be between 0 and 1")
    return threshold


def _intent_signals(question: str, tokens: list[str]) -> dict[str, Any]:
    lowered = question.lower()
    pronouns = {"it", "this", "that", "they", "them", "those", "these", "它", "这个", "那个"}
    comparison_patterns = (
        r"\bcompare\b",
        r"\bdifference\b",
        r"\bdifferences\b",
        r"\bversus\b",
        r"\bvs\.?\b",
        r"\bpros and cons\b",
        r"\btrade-?offs?\b",
        r"\bwhich is better\b",
    )
    current_external_patterns = (
        r"\bweather\b",
        r"\bstock price\b",
        r"\bsports score\b",
        r"\blatest news\b",
        r"\btoday'?s news\b",
        r"\bflight status\b",
    )
    return {
        "token_count": len(tokens),
        "short_follow_up": len(tokens) <= 4 and (bool(set(tokens) & pronouns) or lowered in {"what about it?", "how about it?"}),
        "comparison_marker": _contains_any(lowered, comparison_patterns),
        "current_external_data_marker": _contains_any(lowered, current_external_patterns),
        "contains_question_mark": bool(re.search(r"[?？]", question)),
    }


def classify_query_intent(question: str, *, low_confidence_threshold: float = 0.7) -> dict[str, Any]:
    """Classify query intent without calling external services."""

    threshold = _validate_threshold(low_confidence_threshold)
    normalized = normalize_query_question(question)
    tokens = tokenize_query_text(normalized)
    signals = _intent_signals(normalized, tokens)
    if signals["short_follow_up"]:
        intent = "clarification_needed"
        confidence = 0.72
        reasons = ["short follow-up contains unresolved pronoun"]
        recommended_action = "ask_clarifying_question"
    elif signals["current_external_data_marker"]:
        intent = "out_of_scope"
        confidence = 0.82
        reasons = ["question appears to require current external data outside saved KB evidence"]
        recommended_action = "reject_or_redirect"
    elif signals["comparison_marker"]:
        intent = "comparison"
        confidence = 0.82
        reasons = ["comparison marker detected"]
        recommended_action = "retrieve_and_compare"
    else:
        intent = "knowledge_query"
        confidence = 0.78
        reasons = ["default deterministic knowledge-query classification"]
        recommended_action = "retrieve"
    low_confidence = confidence < threshold
    disclaimer = (
        "Intent confidence is below threshold; ask for confirmation or inspect routing before retrieval."
        if low_confidence
        else None
    )
    return {
        "ok": True,
        "schema": QUERY_INTENT_SCHEMA,
        "question": normalized,
        "intent": intent,
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "low_confidence": low_confidence,
        "low_confidence_threshold": threshold,
        "low_confidence_disclaimer": disclaimer,
        "reasons": reasons,
        "signals": signals,
        "recommended_action": recommended_action,
    }


def route_query_intent(
    question: str,
    *,
    retrieval_mode: str = "auto",
    low_confidence_threshold: float = 0.7,
    intent_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic intent route decision without retrieval."""

    normalized_retrieval_mode = str(retrieval_mode or "auto").strip().lower()
    if normalized_retrieval_mode not in {"auto", "direct"}:
        raise QueryIntentError("retrieval_mode must be one of: auto, direct")
    intent = (
        dict(intent_report)
        if isinstance(intent_report, Mapping)
        else classify_query_intent(question, low_confidence_threshold=low_confidence_threshold)
    )
    intent_value = str(intent.get("intent") or "")
    if intent_value == "clarification_needed":
        status = "clarification"
        action = "ask_clarifying_question"
        should_retrieve = False
    elif intent_value == "out_of_scope":
        status = "rejected"
        action = "reject_or_redirect"
        should_retrieve = False
    elif intent_value == "comparison":
        status = "retrieval_planned"
        action = "retrieve_and_compare"
        should_retrieve = True
    else:
        status = "retrieval_planned"
        action = "retrieve"
        should_retrieve = True
    question_value = intent.get("question")
    if not isinstance(question_value, str) or not question_value.strip():
        question_value = normalize_query_question(question)
    return {
        "ok": True,
        "schema": QUERY_ROUTE_DECISION_SCHEMA,
        "question": question_value,
        "status": status,
        "action": action,
        "retrieval_mode": normalized_retrieval_mode,
        "should_retrieve": should_retrieve,
        "should_answer": should_retrieve,
        "requires_clarification": status == "clarification",
        "rejected": status == "rejected",
        "intent": intent,
        "confidence": intent.get("confidence"),
        "low_confidence": bool(intent.get("low_confidence")),
        "low_confidence_disclaimer": intent.get("low_confidence_disclaimer"),
        "guards": {
            "llm_calls": 0,
            "ragflow_mutation": "disabled",
            "live_retrieval": "not_executed_by_intent_route",
        },
    }


def render_query_intent_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown query intent report."""

    lines = [
        "# RAGFlow Query Intent",
        "",
        f"- schema: `{report.get('schema', QUERY_INTENT_SCHEMA)}`",
        f"- intent: `{report.get('intent', '')}`",
        f"- confidence: `{report.get('confidence', '')}`",
        f"- confidence_label: `{report.get('confidence_label', '')}`",
        f"- low_confidence: `{str(bool(report.get('low_confidence'))).lower()}`",
        "",
        "## Reasons",
        "",
    ]
    reasons = [str(item) for item in report.get("reasons", []) if str(item)]
    lines.extend(f"- {reason}" for reason in reasons) if reasons else lines.append("- None")
    disclaimer = report.get("low_confidence_disclaimer")
    if isinstance(disclaimer, str) and disclaimer:
        lines.extend(["", "## Disclaimer", "", disclaimer])
    return "\n".join(lines) + "\n"


def render_query_route_decision_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown query route decision report."""

    intent = report.get("intent", {}) if isinstance(report.get("intent"), Mapping) else {}
    lines = [
        "# RAGFlow Query Route Decision",
        "",
        f"- schema: `{report.get('schema', QUERY_ROUTE_DECISION_SCHEMA)}`",
        f"- status: `{report.get('status', '')}`",
        f"- action: `{report.get('action', '')}`",
        f"- retrieval_mode: `{report.get('retrieval_mode', '')}`",
        f"- should_retrieve: `{str(bool(report.get('should_retrieve'))).lower()}`",
        f"- intent: `{intent.get('intent', '')}`",
        f"- confidence: `{intent.get('confidence', '')}`",
    ]
    disclaimer = report.get("low_confidence_disclaimer")
    if isinstance(disclaimer, str) and disclaimer:
        lines.extend(["", "## Disclaimer", "", disclaimer])
    return "\n".join(lines) + "\n"
