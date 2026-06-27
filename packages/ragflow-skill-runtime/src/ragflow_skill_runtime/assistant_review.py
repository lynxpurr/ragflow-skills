"""Offline assistant profile review helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .handoff import ASSISTANT_PROFILE_SCHEMA, RETRIEVAL_HINTS_SCHEMA


ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA = "ragflow_assistant_profile_recommendation_v1"


class AssistantReviewError(RuntimeError):
    """Raised when assistant review sidecars are invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssistantReviewError(f"{label} not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise AssistantReviewError(f"{label} is not valid JSON: {source}") from exc
    if not isinstance(payload, Mapping):
        raise AssistantReviewError(f"{label} must be a JSON object")
    return dict(payload)


def load_assistant_profile(path: str | Path) -> dict[str, Any]:
    """Load a rich-handoff assistant profile sidecar."""

    payload = _read_json_mapping(path, label="assistant profile")
    if payload.get("schema") != ASSISTANT_PROFILE_SCHEMA:
        raise AssistantReviewError(f"assistant profile schema must be {ASSISTANT_PROFILE_SCHEMA}")
    return payload


def load_retrieval_hints(path: str | Path) -> dict[str, Any]:
    """Load a rich-handoff retrieval hints sidecar."""

    payload = _read_json_mapping(path, label="retrieval hints")
    if payload.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise AssistantReviewError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")
    return payload


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    path: str,
    recommendation: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
        "recommendation": recommendation,
    }


def _status(issues: list[dict[str, str]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "FAIL"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "REVIEW"
    return "PASS"


def _safe_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _hints_summary(retrieval_hints: Mapping[str, Any] | None) -> dict[str, Any]:
    if retrieval_hints is None:
        return {
            "provided": False,
            "document_count": None,
            "section_count": 0,
            "keyword_count": 0,
            "question_count": 0,
            "numeric_count": 0,
            "table_artifact_count": 0,
            "image_artifact_count": 0,
            "quality_risk_count": 0,
        }
    sections = retrieval_hints.get("section_boundaries", [])
    sections = sections if isinstance(sections, list) else []
    return {
        "provided": True,
        "document_count": retrieval_hints.get("document_count"),
        "section_count": len(sections),
        "keyword_count": len(retrieval_hints.get("keyword_candidates", []))
        if isinstance(retrieval_hints.get("keyword_candidates"), list)
        else 0,
        "question_count": len(retrieval_hints.get("question_candidates", []))
        if isinstance(retrieval_hints.get("question_candidates"), list)
        else 0,
        "numeric_count": len(retrieval_hints.get("numeric_candidates", []))
        if isinstance(retrieval_hints.get("numeric_candidates"), list)
        else 0,
        "table_artifact_count": len(retrieval_hints.get("table_artifacts", []))
        if isinstance(retrieval_hints.get("table_artifacts"), list)
        else 0,
        "image_artifact_count": len(retrieval_hints.get("image_artifacts", []))
        if isinstance(retrieval_hints.get("image_artifacts"), list)
        else 0,
        "quality_risk_count": len(retrieval_hints.get("quality_risks", []))
        if isinstance(retrieval_hints.get("quality_risks"), list)
        else 0,
    }


def _answer_policy_mentions_missing_evidence(policy: Any) -> bool:
    lines = policy if isinstance(policy, list) else []
    text = " ".join(str(item).lower() for item in lines)
    return any(marker in text for marker in ("missing", "does not contain", "no answer", "evidence is missing"))


def recommend_assistant_profile(
    assistant_profile: Mapping[str, Any],
    *,
    retrieval_hints: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend reviewable assistant retrieval settings without mutation."""

    if assistant_profile.get("schema") != ASSISTANT_PROFILE_SCHEMA:
        raise AssistantReviewError(f"assistant profile schema must be {ASSISTANT_PROFILE_SCHEMA}")
    if retrieval_hints is not None and retrieval_hints.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise AssistantReviewError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")

    issues: list[dict[str, str]] = []
    retrieval = assistant_profile.get("retrieval")
    if not isinstance(retrieval, Mapping):
        retrieval = {}
        issues.append(
            _issue(
                "warning",
                "retrieval_settings_missing",
                "assistant profile does not include retrieval settings",
                path="assistant_profile.retrieval",
                recommendation="Regenerate the rich handoff package or review defaults before applying settings.",
            )
        )
    hints = _hints_summary(retrieval_hints)
    top_k = _safe_int(retrieval.get("top_k"), 5)
    similarity_threshold = _safe_float(retrieval.get("similarity_threshold"), 0.2)
    vector_weight = _safe_float(retrieval.get("vector_weight"), 0.7)
    bm25_weight = _safe_float(retrieval.get("bm25_weight"), 0.3 if hints["keyword_count"] else 0.0)
    has_visual_or_table = bool(hints["image_artifact_count"] or hints["table_artifact_count"])
    if hints["section_count"] > 8 or has_visual_or_table:
        top_k = max(top_k, 8)
    if has_visual_or_table:
        similarity_threshold = min(similarity_threshold, 0.18)
    if hints["keyword_count"]:
        bm25_weight = max(bm25_weight, 0.3)
    require_evidence = _safe_bool(retrieval.get("require_evidence"), True)
    quote_numeric_facts = _safe_bool(retrieval.get("quote_numeric_facts"), bool(hints["numeric_count"]))
    citation_format = str(retrieval.get("citation_format") or "[n]")
    require_citations = citation_format.strip() == "[n]" or quote_numeric_facts
    no_answer_policy = (
        "abstain_when_evidence_missing"
        if _answer_policy_mentions_missing_evidence(assistant_profile.get("answer_policy"))
        else "review_required"
    )
    if not require_evidence:
        issues.append(
            _issue(
                "warning",
                "require_evidence_disabled",
                "assistant profile does not require retrieved evidence",
                path="assistant_profile.retrieval.require_evidence",
                recommendation="Require evidence before applying assistant settings.",
            )
        )
    if no_answer_policy == "review_required":
        issues.append(
            _issue(
                "warning",
                "no_answer_policy_missing",
                "assistant profile does not clearly define missing-evidence behavior",
                path="assistant_profile.answer_policy",
                recommendation="Add an abstain/no-answer policy before applying assistant settings.",
            )
        )
    if retrieval_hints is None:
        issues.append(
            _issue(
                "warning",
                "retrieval_hints_not_supplied",
                "retrieval hints were not supplied for profile recommendation",
                path="retrieval_hints",
                recommendation="Provide retrieval_hints.json to review section, keyword, table, image, and numeric signals.",
            )
        )
    recommended_settings = {
        "top_k": top_k,
        "similarity_threshold": round(similarity_threshold, 4),
        "vector_weight": round(vector_weight, 4),
        "bm25_weight": round(bm25_weight, 4),
        "require_evidence": require_evidence,
        "require_citations": require_citations,
        "quote_numeric_facts": quote_numeric_facts,
        "citation_format": citation_format,
        "no_answer_policy": no_answer_policy,
    }
    status = _status(issues)
    return {
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "schema": ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA,
        "created_at": _now(),
        "status": status,
        "advisory_only": True,
        "mutation": "none",
        "profile_id": assistant_profile.get("profile_id"),
        "inputs": dict(inputs or {}),
        "source_profile": {
            "schema": assistant_profile.get("schema"),
            "profile_id": assistant_profile.get("profile_id"),
            "status": assistant_profile.get("status"),
        },
        "retrieval_hints_summary": hints,
        "recommended_settings": recommended_settings,
        "recommendation": {
            "action": "review_before_applying",
            "confidence": "medium" if issues else "high",
            "rationale": [
                "settings are derived from reviewable rich-handoff assistant_profile.json",
                "retrieval_hints.json can raise top_k or BM25 weight for broad, visual, table, or keyword-rich handoffs",
                "this report does not apply RAGFlow assistant settings",
            ],
        },
        "checks": {
            "profile_schema": {"passed": True, "expected": ASSISTANT_PROFILE_SCHEMA},
            "retrieval_hints": hints,
            "evidence_policy": {
                "require_evidence": require_evidence,
                "require_citations": require_citations,
                "quote_numeric_facts": quote_numeric_facts,
                "no_answer_policy": no_answer_policy,
            },
        },
        "issues": issues,
        "next_steps": [
            "Review recommended settings before changing any RAGFlow assistant configuration.",
            "Run offline assistant-test-plan review before live assistant validation.",
            "Keep this report beside assistant_profile.json and retrieval_hints.json.",
        ],
    }


def render_assistant_profile_recommendation_markdown(report: Mapping[str, Any]) -> str:
    """Render an assistant profile recommendation report."""

    settings = report.get("recommended_settings", {})
    settings = settings if isinstance(settings, Mapping) else {}
    hints = report.get("retrieval_hints_summary", {})
    hints = hints if isinstance(hints, Mapping) else {}
    lines = [
        "# RAGFlow Assistant Profile Recommendation",
        "",
        f"- Schema: `{report.get('schema')}`",
        f"- Status: `{report.get('status')}`",
        f"- Profile: `{report.get('profile_id')}`",
        f"- Mutation: `{report.get('mutation')}`",
        f"- top_k: `{settings.get('top_k')}`",
        f"- similarity_threshold: `{settings.get('similarity_threshold')}`",
        f"- vector_weight: `{settings.get('vector_weight')}`",
        f"- bm25_weight: `{settings.get('bm25_weight')}`",
        f"- no_answer_policy: `{settings.get('no_answer_policy')}`",
        "",
        "## Retrieval Hints",
        "",
        f"- provided: `{str(hints.get('provided')).lower()}`",
        f"- sections: `{hints.get('section_count', 0)}`",
        f"- keywords: `{hints.get('keyword_count', 0)}`",
        f"- numeric candidates: `{hints.get('numeric_count', 0)}`",
        f"- table artifacts: `{hints.get('table_artifact_count', 0)}`",
        f"- image artifacts: `{hints.get('image_artifact_count', 0)}`",
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
    lines.extend(["", "## Next Steps", ""])
    for step in report.get("next_steps", []) if isinstance(report.get("next_steps"), list) else []:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"
