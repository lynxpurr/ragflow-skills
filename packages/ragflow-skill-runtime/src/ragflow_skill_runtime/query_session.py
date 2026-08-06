"""Deterministic query session inspection and enrichment helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .query_intent import classify_query_intent, normalize_query_question, route_query_intent, tokenize_query_text


QUERY_SESSION_SCHEMA = "ragflow_query_session_v1"
QUERY_SESSION_INSPECTION_SCHEMA = "ragflow_query_session_inspection_v1"
QUERY_SESSION_ENRICHMENT_SCHEMA = "ragflow_query_session_enrichment_v1"
DEFAULT_SESSION_MAX_TURNS = 8
DEFAULT_SESSION_MAX_TOKENS = 400


class QuerySessionError(ValueError):
    """Raised when query session input cannot be inspected safely."""


def _validate_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QuerySessionError(f"{field_name} must be a positive integer")
    return value


def _content_from_turn(turn: Mapping[str, Any]) -> str:
    for key in ("content", "text", "question", "answer"):
        value = turn.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value).strip()
    raise QuerySessionError("session turn content must be a non-empty string")


def _turns_from_payload(payload: Any) -> tuple[str | None, list[Any]]:
    if isinstance(payload, list):
        return None, payload
    if not isinstance(payload, Mapping):
        raise QuerySessionError("session must be a JSON object or list of turns")
    session_id = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
    for key in ("turns", "messages", "history"):
        value = payload.get(key)
        if isinstance(value, list):
            return session_id, value
    raise QuerySessionError("session must contain a turns, messages, or history list")


def estimate_session_tokens(text: str) -> int:
    """Estimate deterministic session-token cost without external tokenizers."""

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_tokens = [token for token in tokenize_query_text(text) if not re.search(r"[\u4e00-\u9fff]", token)]
    return cjk_chars + len(latin_tokens)


def normalize_query_session(payload: Any, *, session_id: str | None = None) -> dict[str, Any]:
    """Normalize user-owned session JSON to ragflow_query_session_v1."""

    payload_session_id, raw_turns = _turns_from_payload(payload)
    normalized_turns: list[dict[str, Any]] = []
    for index, raw_turn in enumerate(raw_turns, start=1):
        if not isinstance(raw_turn, Mapping):
            raise QuerySessionError(f"session turn {index} must be an object")
        content = _content_from_turn(raw_turn)
        role = str(raw_turn.get("role") or "user").strip().lower() or "user"
        normalized_turns.append(
            {
                "index": index,
                "role": role,
                "content": content,
                "token_estimate": estimate_session_tokens(content),
                **({"turn_id": raw_turn.get("id")} if isinstance(raw_turn.get("id"), str) else {}),
                **({"created_at": raw_turn.get("created_at")} if isinstance(raw_turn.get("created_at"), str) else {}),
            }
        )
    return {
        "schema": QUERY_SESSION_SCHEMA,
        "session_id": session_id or payload_session_id,
        "turn_count": len(normalized_turns),
        "turns": normalized_turns,
    }


def load_query_session(path: str | Path) -> dict[str, Any]:
    """Load and normalize a query session JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return normalize_query_session(payload)


def _bounded_turns(
    turns: Sequence[Mapping[str, Any]],
    *,
    max_turns: int,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limited_by_turns = list(turns)[-max_turns:]
    selected_reversed: list[dict[str, Any]] = []
    token_count = 0
    truncated_by_tokens = False
    for turn in reversed(limited_by_turns):
        cost = int(turn.get("token_estimate") or estimate_session_tokens(str(turn.get("content") or "")))
        if selected_reversed and token_count + cost > max_tokens:
            truncated_by_tokens = True
            break
        if not selected_reversed and cost > max_tokens:
            truncated_by_tokens = True
            break
        selected_reversed.append(dict(turn))
        token_count += cost
    selected = list(reversed(selected_reversed))
    return selected, {
        "max_turns": max_turns,
        "max_tokens": max_tokens,
        "selected_turn_count": len(selected),
        "selected_token_estimate": token_count,
        "truncated_by_turns": len(turns) > max_turns,
        "truncated_by_tokens": truncated_by_tokens,
    }


def detect_follow_up_reference(question: str) -> dict[str, Any]:
    """Detect whether a question needs recent session context."""

    normalized = normalize_query_question(question)
    lowered = normalized.lower()
    tokens = tokenize_query_text(normalized)
    token_set = set(tokens)
    pronouns = {"it", "this", "that", "they", "them", "those", "these", "above", "previous", "earlier", "它", "这个", "那个", "上述"}
    starter_patterns = (
        r"^(what|how) about\b",
        r"^(and|also|then)\b",
        r"^(那|那么|还有|另外)",
    )
    pronoun_match = bool(token_set & pronouns) or any(marker in lowered for marker in ("above", "previous", "earlier"))
    starter_match = any(re.search(pattern, lowered) for pattern in starter_patterns)
    short_follow_up = len(tokens) <= 6 and (pronoun_match or starter_match)
    omitted_subject = starter_match and len(tokens) <= 8
    needs_context = short_follow_up or omitted_subject
    reasons: list[str] = []
    if short_follow_up:
        reasons.append("short follow-up marker detected")
    if omitted_subject:
        reasons.append("follow-up starter may omit the subject")
    return {
        "question": normalized,
        "token_count": len(tokens),
        "pronoun_reference": pronoun_match,
        "follow_up_starter": starter_match,
        "short_follow_up": short_follow_up,
        "omitted_subject": omitted_subject,
        "needs_context": needs_context,
        "reasons": reasons,
    }


def _last_turn(turns: Sequence[Mapping[str, Any]], *, role: str | None = None) -> dict[str, Any] | None:
    for turn in reversed(turns):
        if role is None or turn.get("role") == role:
            return dict(turn)
    return None


def _anchor_turn(turns: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    user_turn = _last_turn(turns, role="user")
    if user_turn:
        return user_turn
    return _last_turn(turns)


def build_query_session_inspection(
    session_payload: Any,
    *,
    max_turns: int = DEFAULT_SESSION_MAX_TURNS,
    max_tokens: int = DEFAULT_SESSION_MAX_TOKENS,
) -> dict[str, Any]:
    """Inspect a query session with bounded deterministic context."""

    max_turns = _validate_positive_int(max_turns, field_name="max_turns")
    max_tokens = _validate_positive_int(max_tokens, field_name="max_tokens")
    session = normalize_query_session(session_payload)
    selected_turns, limits = _bounded_turns(session["turns"], max_turns=max_turns, max_tokens=max_tokens)
    current_user_turn = _last_turn(selected_turns, role="user")
    previous_turns = selected_turns[:-1] if selected_turns and current_user_turn == selected_turns[-1] else selected_turns
    anchor = _anchor_turn(previous_turns)
    follow_up = detect_follow_up_reference(current_user_turn["content"]) if current_user_turn else None
    warnings: list[str] = []
    if limits["truncated_by_turns"]:
        warnings.append("session context was truncated by max_turns")
    if limits["truncated_by_tokens"]:
        warnings.append("session context was truncated by max_tokens")
    if follow_up and follow_up["needs_context"] and not anchor:
        warnings.append("latest user turn appears to need context, but no anchor turn is available")
    return {
        "ok": True,
        "schema": QUERY_SESSION_INSPECTION_SCHEMA,
        "session_schema": QUERY_SESSION_SCHEMA,
        "session_id": session.get("session_id"),
        "turn_count": session["turn_count"],
        "limits": limits,
        "bounded_context": {"turns": selected_turns},
        "latest_user_turn": current_user_turn,
        "anchor_turn": anchor,
        "latest_user_follow_up": follow_up,
        "warnings": warnings,
        "guards": {
            "llm_calls": 0,
            "ragflow_mutation": "disabled",
            "live_retrieval": "not_executed_by_session_inspect",
        },
    }


def enrich_query_with_session(
    question: str,
    session_payload: Any,
    *,
    max_turns: int = DEFAULT_SESSION_MAX_TURNS,
    max_tokens: int = DEFAULT_SESSION_MAX_TOKENS,
) -> dict[str, Any]:
    """Enrich a query with bounded recent session context when needed."""

    normalized_question = normalize_query_question(question)
    inspection = build_query_session_inspection(session_payload, max_turns=max_turns, max_tokens=max_tokens)
    selected_turns = inspection["bounded_context"]["turns"]
    anchor = _anchor_turn(selected_turns)
    follow_up = detect_follow_up_reference(normalized_question)
    context_applied = bool(follow_up["needs_context"] and anchor)
    requires_clarification = bool(follow_up["needs_context"] and not anchor)
    warnings = list(inspection.get("warnings", []))
    if requires_clarification:
        warnings.append("question appears to need prior context, but no bounded anchor turn is available")
    enriched_question = normalized_question
    if context_applied and anchor:
        enriched_question = f"{normalized_question} Context: {anchor['content']}"
    intent_report = classify_query_intent(enriched_question)
    route_decision = route_query_intent(enriched_question, intent_report=intent_report)
    if requires_clarification:
        route_decision = route_query_intent(normalized_question)
    return {
        "ok": True,
        "schema": QUERY_SESSION_ENRICHMENT_SCHEMA,
        "session_schema": QUERY_SESSION_SCHEMA,
        "question": normalized_question,
        "enriched_question": enriched_question,
        "context_applied": context_applied,
        "requires_clarification": requires_clarification,
        "follow_up": follow_up,
        "anchor_turn": anchor,
        "inspection": inspection,
        "intent": intent_report,
        "route_decision": route_decision,
        "warnings": warnings,
        "guards": {
            "llm_calls": 0,
            "ragflow_mutation": "disabled",
            "live_retrieval": "not_executed_by_session_enrich",
        },
    }


def render_query_session_inspection_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown session inspection report."""

    limits = report.get("limits", {}) if isinstance(report.get("limits"), Mapping) else {}
    latest = report.get("latest_user_turn", {}) if isinstance(report.get("latest_user_turn"), Mapping) else {}
    anchor = report.get("anchor_turn", {}) if isinstance(report.get("anchor_turn"), Mapping) else {}
    lines = [
        "# RAGFlow Query Session Inspection",
        "",
        f"- schema: `{report.get('schema', QUERY_SESSION_INSPECTION_SCHEMA)}`",
        f"- session_schema: `{report.get('session_schema', QUERY_SESSION_SCHEMA)}`",
        f"- turn_count: `{report.get('turn_count', 0)}`",
        f"- selected_turn_count: `{limits.get('selected_turn_count', 0)}`",
        f"- selected_token_estimate: `{limits.get('selected_token_estimate', 0)}`",
        f"- latest_user_turn: `{latest.get('content', '')}`",
        f"- anchor_turn: `{anchor.get('content', '')}`",
    ]
    warnings = [str(item) for item in report.get("warnings", []) if str(item)]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"


def render_query_session_enrichment_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown session enrichment report."""

    anchor = report.get("anchor_turn", {}) if isinstance(report.get("anchor_turn"), Mapping) else {}
    lines = [
        "# RAGFlow Query Session Enrichment",
        "",
        f"- schema: `{report.get('schema', QUERY_SESSION_ENRICHMENT_SCHEMA)}`",
        f"- context_applied: `{str(bool(report.get('context_applied'))).lower()}`",
        f"- requires_clarification: `{str(bool(report.get('requires_clarification'))).lower()}`",
        f"- question: `{report.get('question', '')}`",
        f"- enriched_question: `{report.get('enriched_question', '')}`",
        f"- anchor_turn: `{anchor.get('content', '')}`",
    ]
    warnings = [str(item) for item in report.get("warnings", []) if str(item)]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"
