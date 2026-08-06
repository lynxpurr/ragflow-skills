"""Offline assistant profile review helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .handoff import ASSISTANT_PROFILE_SCHEMA, ASSISTANT_TEST_PLAN_SCHEMA, RETRIEVAL_HINTS_SCHEMA


ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA = "ragflow_assistant_profile_recommendation_v1"
ASSISTANT_TEST_PLAN_REVIEW_SCHEMA = "ragflow_assistant_test_plan_review_v1"
ASSISTANT_TEST_PLAN_CANONICAL_STAGES = (
    "summary",
    "exact_numeric_fact",
    "ocr_image_fact",
    "table_structure_review",
    "logical_flow",
    "paraphrase",
    "negative_boundary",
)


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


def load_assistant_test_plan(path: str | Path) -> dict[str, Any]:
    """Load a rich-handoff assistant test plan sidecar."""

    payload = _read_json_mapping(path, label="assistant test plan")
    if payload.get("schema") != ASSISTANT_TEST_PLAN_SCHEMA:
        raise AssistantReviewError(f"assistant test plan schema must be {ASSISTANT_TEST_PLAN_SCHEMA}")
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
            "table_semantic_risk_count": 0,
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
        "table_semantic_risk_count": sum(
            len(item.get("semantic_risks", []))
            for item in retrieval_hints.get("table_artifacts", [])
            if isinstance(item, Mapping) and isinstance(item.get("semantic_risks"), list)
        )
        if isinstance(retrieval_hints.get("table_artifacts"), list)
        else 0,
        "image_artifact_count": len(retrieval_hints.get("image_artifacts", []))
        if isinstance(retrieval_hints.get("image_artifacts"), list)
        else 0,
        "quality_risk_count": len(retrieval_hints.get("quality_risks", []))
        if isinstance(retrieval_hints.get("quality_risks"), list)
        else 0,
    }


def _status_is_ready(value: Any) -> bool:
    return str(value or "").strip().upper() in {"PASS", "READY", "OK", "DONE", "SUCCESS", "COMPLETED"}


def _build_evidence_summary(
    *,
    kb_manifest: Mapping[str, Any] | None,
    parse_report: Mapping[str, Any] | None,
    activation_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    documents = kb_manifest.get("documents", []) if isinstance(kb_manifest, Mapping) else []
    documents = documents if isinstance(documents, list) else []
    status_counts: dict[str, int] = {}
    total_chunk_count = 0
    zero_chunk_document_count = 0
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        status = str(document.get("status") or document.get("run") or "unknown").lower()
        status_counts[status] = status_counts.get(status, 0) + 1
        chunk_count = _safe_int(document.get("chunk_count"), 0)
        total_chunk_count += chunk_count
        if chunk_count == 0:
            zero_chunk_document_count += 1

    dataset = kb_manifest.get("dataset", {}) if isinstance(kb_manifest, Mapping) else {}
    dataset = dataset if isinstance(dataset, Mapping) else {}
    parse_summary = parse_report.get("summary", {}) if isinstance(parse_report, Mapping) else {}
    parse_summary = parse_summary if isinstance(parse_summary, Mapping) else {}
    activation_summary = activation_plan.get("summary", {}) if isinstance(activation_plan, Mapping) else {}
    activation_summary = activation_summary if isinstance(activation_summary, Mapping) else {}
    activation_recommendation = activation_plan.get("recommendation") if isinstance(activation_plan, Mapping) else None
    if isinstance(activation_recommendation, Mapping):
        activation_action = activation_recommendation.get("action")
    else:
        activation_action = activation_summary.get("recommendation")

    return {
        "provided": bool(kb_manifest or parse_report or activation_plan),
        "kb_manifest": {
            "provided": kb_manifest is not None,
            "dataset_id": dataset.get("id"),
            "kb_name": dataset.get("name"),
            "document_count": len(documents),
            "total_chunk_count": total_chunk_count,
            "zero_chunk_document_count": zero_chunk_document_count,
            "status_counts": status_counts,
        },
        "parse_report": {
            "provided": parse_report is not None,
            "schema": parse_report.get("schema") if isinstance(parse_report, Mapping) else None,
            "status": parse_report.get("status") if isinstance(parse_report, Mapping) else None,
            "document_count": parse_summary.get("document_count"),
            "zero_chunk_document_count": parse_summary.get("zero_chunk_document_count"),
            "issue_count": len(parse_report.get("issues", []))
            if isinstance(parse_report, Mapping) and isinstance(parse_report.get("issues"), list)
            else 0,
        },
        "activation_plan": {
            "provided": activation_plan is not None,
            "schema": activation_plan.get("schema") if isinstance(activation_plan, Mapping) else None,
            "status": activation_plan.get("status") if isinstance(activation_plan, Mapping) else None,
            "recommendation": activation_action,
            "issue_count": _safe_int(
                activation_summary.get("issue_count"),
                len(activation_plan.get("issues", []))
                if isinstance(activation_plan, Mapping) and isinstance(activation_plan.get("issues"), list)
                else 0,
            ),
        },
    }


def _build_evidence_issues(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    kb_manifest = summary.get("kb_manifest", {}) if isinstance(summary.get("kb_manifest"), Mapping) else {}
    parse_report = summary.get("parse_report", {}) if isinstance(summary.get("parse_report"), Mapping) else {}
    activation_plan = summary.get("activation_plan", {}) if isinstance(summary.get("activation_plan"), Mapping) else {}
    zero_chunk_count = _safe_int(kb_manifest.get("zero_chunk_document_count"), 0)
    if kb_manifest.get("provided") and zero_chunk_count:
        issues.append(
            _issue(
                "warning",
                "build_evidence_zero_chunk_documents",
                "build evidence includes documents with zero chunks",
                path="kb_manifest.documents",
                recommendation="Review parse-report and chunk snapshots before applying assistant settings.",
            )
        )
    if parse_report.get("provided") and not _status_is_ready(parse_report.get("status")):
        issues.append(
            _issue(
                "warning",
                "build_evidence_parse_not_ready",
                "parse report status is not ready for assistant activation",
                path="parse_report.status",
                recommendation="Resolve parse-report warnings before running assistant validation.",
            )
        )
    if activation_plan.get("provided") and not _status_is_ready(activation_plan.get("status")):
        issues.append(
            _issue(
                "warning",
                "build_evidence_activation_not_ready",
                "activation plan status is not ready",
                path="activation_plan.status",
                recommendation="Review route activation warnings before applying assistant settings or tests.",
            )
        )
    return issues


def _expected_test_stages_from_hints(retrieval_hints: Mapping[str, Any] | None) -> set[str]:
    if retrieval_hints is None:
        return set(ASSISTANT_TEST_PLAN_CANONICAL_STAGES)
    hints = _hints_summary(retrieval_hints)
    sections = retrieval_hints.get("section_boundaries", [])
    sections = sections if isinstance(sections, list) else []
    expected = {"summary", "negative_boundary"}
    if hints["numeric_count"]:
        expected.add("exact_numeric_fact")
    if hints["image_artifact_count"] or any(
        isinstance(section, Mapping) and int(section.get("image_count", 0) or 0) > 0
        for section in sections
    ):
        expected.add("ocr_image_fact")
    if hints["table_semantic_risk_count"]:
        expected.add("table_structure_review")
    if hints["section_count"] >= 2:
        expected.add("logical_flow")
    if hints["question_count"] >= 2:
        expected.add("paraphrase")
    return expected


def _stage_focus(stage: str) -> str:
    return {
        "summary": "confirm the assistant summarizes only retrieved evidence",
        "exact_numeric_fact": "confirm numbers are quoted or cited exactly",
        "ocr_image_fact": "confirm visual or OCR-backed facts are not guessed",
        "table_structure_review": "confirm complex table structure is reviewed before answering",
        "logical_flow": "confirm related source sections are compared without outside assumptions",
        "paraphrase": "confirm paraphrased questions still retrieve the same source evidence",
        "negative_boundary": "confirm missing or unsafe facts trigger abstention",
    }.get(stage, "review custom assistant behavior manually")


def _review_case(case: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    stage = str(case.get("stage") or "")
    question = str(case.get("question") or "")
    expected_behavior = str(case.get("expected_behavior") or "")
    case_id = str(case.get("id") or f"case-{index:03d}")
    return {
        "id": case_id,
        "stage": stage,
        "question": question,
        "expected_behavior": expected_behavior,
        "source_document": case.get("source_document"),
        "source_heading": case.get("source_heading"),
        "review_focus": _stage_focus(stage),
        "ready_for_manual_run": bool(question and expected_behavior and stage in ASSISTANT_TEST_PLAN_CANONICAL_STAGES),
    }


def _answer_policy_mentions_missing_evidence(policy: Any) -> bool:
    lines = policy if isinstance(policy, list) else []
    text = " ".join(str(item).lower() for item in lines)
    return any(marker in text for marker in ("missing", "does not contain", "no answer", "evidence is missing"))


def review_assistant_test_plan(
    assistant_test_plan: Mapping[str, Any],
    *,
    assistant_profile: Mapping[str, Any] | None = None,
    retrieval_hints: Mapping[str, Any] | None = None,
    kb_manifest: Mapping[str, Any] | None = None,
    parse_report: Mapping[str, Any] | None = None,
    activation_plan: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Review a rich-handoff assistant test plan without running tests or mutating RAGFlow."""

    if assistant_test_plan.get("schema") != ASSISTANT_TEST_PLAN_SCHEMA:
        raise AssistantReviewError(f"assistant test plan schema must be {ASSISTANT_TEST_PLAN_SCHEMA}")
    if assistant_profile is not None and assistant_profile.get("schema") != ASSISTANT_PROFILE_SCHEMA:
        raise AssistantReviewError(f"assistant profile schema must be {ASSISTANT_PROFILE_SCHEMA}")
    if retrieval_hints is not None and retrieval_hints.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise AssistantReviewError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")

    issues: list[dict[str, str]] = []
    build_summary = _build_evidence_summary(
        kb_manifest=kb_manifest,
        parse_report=parse_report,
        activation_plan=activation_plan,
    )
    issues.extend(_build_evidence_issues(build_summary))
    raw_cases = assistant_test_plan.get("cases")
    if not isinstance(raw_cases, list):
        raw_cases = []
        issues.append(
            _issue(
                "error",
                "cases_missing",
                "assistant test plan does not include a cases list",
                path="assistant_test_plan.cases",
                recommendation="Regenerate the rich handoff package before reviewing assistant tests.",
            )
        )

    review_cases: list[dict[str, Any]] = []
    stage_counts: dict[str, int] = {}
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    valid_case_count = 0
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, Mapping):
            issues.append(
                _issue(
                    "error",
                    "case_not_object",
                    "assistant test case must be a JSON object",
                    path=f"assistant_test_plan.cases[{index - 1}]",
                    recommendation="Regenerate or edit the sidecar so every case is an object.",
                )
            )
            continue
        valid_case_count += 1
        case = _review_case(raw_case, index=index)
        case_id = str(raw_case.get("id") or "")
        stage = str(raw_case.get("stage") or "")
        question = str(raw_case.get("question") or "")
        expected_behavior = str(raw_case.get("expected_behavior") or "")
        if not case_id:
            issues.append(
                _issue(
                    "warning",
                    "case_id_missing",
                    "assistant test case does not include an id",
                    path=f"assistant_test_plan.cases[{index - 1}].id",
                    recommendation="Assign stable case IDs so review results can be compared across runs.",
                )
            )
        elif case_id in seen_ids:
            duplicate_ids.add(case_id)
        else:
            seen_ids.add(case_id)
        if not stage:
            issues.append(
                _issue(
                    "warning",
                    "case_stage_missing",
                    "assistant test case does not include a stage",
                    path=f"assistant_test_plan.cases[{index - 1}].stage",
                    recommendation="Set the stage to one of the canonical assistant test stages.",
                )
            )
        elif stage not in ASSISTANT_TEST_PLAN_CANONICAL_STAGES:
            issues.append(
                _issue(
                    "warning",
                    "case_stage_unknown",
                    f"assistant test case uses unknown stage {stage!r}",
                    path=f"assistant_test_plan.cases[{index - 1}].stage",
                    recommendation="Use a canonical stage or document why the custom stage is needed.",
                )
            )
        if not question:
            issues.append(
                _issue(
                    "warning",
                    "case_question_missing",
                    "assistant test case does not include a question",
                    path=f"assistant_test_plan.cases[{index - 1}].question",
                    recommendation="Add the user-facing question before running assistant validation.",
                )
            )
        if not expected_behavior:
            issues.append(
                _issue(
                    "warning",
                    "case_expected_behavior_missing",
                    "assistant test case does not include expected behavior",
                    path=f"assistant_test_plan.cases[{index - 1}].expected_behavior",
                    recommendation="Describe expected citation, abstention, or evidence behavior for this case.",
                )
            )
        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        review_cases.append(case)

    if duplicate_ids:
        issues.append(
            _issue(
                "warning",
                "case_id_duplicate",
                "assistant test plan contains duplicate case IDs",
                path="assistant_test_plan.cases",
                recommendation=f"Make case IDs unique: {', '.join(sorted(duplicate_ids))}.",
            )
        )
    if valid_case_count == 0:
        issues.append(
            _issue(
                "error",
                "no_reviewable_cases",
                "assistant test plan has no reviewable cases",
                path="assistant_test_plan.cases",
                recommendation="Regenerate the rich handoff package or add staged assistant test cases.",
            )
        )

    expected_stages = _expected_test_stages_from_hints(retrieval_hints)
    present_stages = set(stage_counts)
    missing_expected_stages = sorted(expected_stages - present_stages)
    for stage in missing_expected_stages:
        issues.append(
            _issue(
                "warning",
                "expected_stage_missing",
                f"assistant test plan is missing expected stage {stage!r}",
                path="assistant_test_plan.cases.stage",
                recommendation="Add a staged test case or confirm the source does not support this test type.",
            )
        )
    if retrieval_hints is None:
        issues.append(
            _issue(
                "warning",
                "retrieval_hints_not_supplied",
                "retrieval hints were not supplied for assistant test-plan review",
                path="retrieval_hints",
                recommendation="Provide retrieval_hints.json to make stage coverage checks source-aware.",
            )
        )

    plan_profile = assistant_test_plan.get("assistant_profile")
    profile_id = assistant_profile.get("profile_id") if isinstance(assistant_profile, Mapping) else None
    if profile_id and plan_profile and profile_id != plan_profile:
        issues.append(
            _issue(
                "warning",
                "assistant_profile_mismatch",
                "assistant test plan references a different assistant profile",
                path="assistant_test_plan.assistant_profile",
                recommendation="Review that the test plan and assistant profile came from the same rich handoff package.",
            )
        )

    status = _status(issues)
    stage_coverage = [
        {
            "stage": stage,
            "count": stage_counts.get(stage, 0),
            "present": stage in present_stages,
            "expected_from_hints": stage in expected_stages,
        }
        for stage in ASSISTANT_TEST_PLAN_CANONICAL_STAGES
    ]
    return {
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "schema": ASSISTANT_TEST_PLAN_REVIEW_SCHEMA,
        "created_at": _now(),
        "status": status,
        "advisory_only": True,
        "mutation": "none",
        "execution": {
            "status": "not_run",
            "llm_calls": 0,
            "ragflow_calls": 0,
            "reason": "offline review surface only",
        },
        "assistant_profile": plan_profile,
        "inputs": dict(inputs or {}),
        "source_test_plan": {
            "schema": assistant_test_plan.get("schema"),
            "status": assistant_test_plan.get("status"),
            "assistant_profile": plan_profile,
            "declared_test_count": assistant_test_plan.get("test_count"),
        },
        "retrieval_hints_summary": _hints_summary(retrieval_hints),
        "build_evidence_summary": build_summary,
        "summary": {
            "case_count": valid_case_count,
            "declared_test_count": assistant_test_plan.get("test_count"),
            "stage_count": len(present_stages),
            "expected_stage_count": len(expected_stages),
            "missing_expected_stage_count": len(missing_expected_stages),
            "duplicate_id_count": len(duplicate_ids),
            "ready_case_count": sum(1 for case in review_cases if case.get("ready_for_manual_run")),
        },
        "canonical_stages": list(ASSISTANT_TEST_PLAN_CANONICAL_STAGES),
        "expected_stages": [stage for stage in ASSISTANT_TEST_PLAN_CANONICAL_STAGES if stage in expected_stages],
        "missing_expected_stages": missing_expected_stages,
        "stage_coverage": stage_coverage,
        "review_cases": review_cases,
        "checks": {
            "test_plan_schema": {"passed": True, "expected": ASSISTANT_TEST_PLAN_SCHEMA},
            "assistant_profile_match": {
                "provided": bool(profile_id),
                "profile_id": profile_id,
                "test_plan_profile_id": plan_profile,
                "matched": not profile_id or not plan_profile or profile_id == plan_profile,
            },
            "offline_only": {"passed": True, "llm_calls": 0, "ragflow_calls": 0, "mutation": "none"},
            "build_evidence": build_summary,
        },
        "issues": issues,
        "next_steps": [
            "Review each case before running it against a live assistant.",
            "Keep assistant validation execution in a user-owned harness with explicit credentials.",
            "Compare future assistant-test-plan reports by stable case IDs and stages.",
            "Keep build evidence sidecars beside assistant review artifacts when available.",
        ],
    }


def recommend_assistant_profile(
    assistant_profile: Mapping[str, Any],
    *,
    retrieval_hints: Mapping[str, Any] | None = None,
    kb_manifest: Mapping[str, Any] | None = None,
    parse_report: Mapping[str, Any] | None = None,
    activation_plan: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend reviewable assistant retrieval settings without mutation."""

    if assistant_profile.get("schema") != ASSISTANT_PROFILE_SCHEMA:
        raise AssistantReviewError(f"assistant profile schema must be {ASSISTANT_PROFILE_SCHEMA}")
    if retrieval_hints is not None and retrieval_hints.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise AssistantReviewError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")

    issues: list[dict[str, str]] = []
    build_summary = _build_evidence_summary(
        kb_manifest=kb_manifest,
        parse_report=parse_report,
        activation_plan=activation_plan,
    )
    issues.extend(_build_evidence_issues(build_summary))
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
        "build_evidence_summary": build_summary,
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
            "build_evidence": build_summary,
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
            "Keep build evidence sidecars beside assistant review artifacts when available.",
        ],
    }


def render_assistant_profile_recommendation_markdown(report: Mapping[str, Any]) -> str:
    """Render an assistant profile recommendation report."""

    settings = report.get("recommended_settings", {})
    settings = settings if isinstance(settings, Mapping) else {}
    hints = report.get("retrieval_hints_summary", {})
    hints = hints if isinstance(hints, Mapping) else {}
    build = report.get("build_evidence_summary", {})
    build = build if isinstance(build, Mapping) else {}
    kb_build = build.get("kb_manifest", {}) if isinstance(build.get("kb_manifest"), Mapping) else {}
    parse_build = build.get("parse_report", {}) if isinstance(build.get("parse_report"), Mapping) else {}
    activation_build = build.get("activation_plan", {}) if isinstance(build.get("activation_plan"), Mapping) else {}
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
        "## Build Evidence",
        "",
        f"- provided: `{str(build.get('provided')).lower()}`",
        f"- documents: `{kb_build.get('document_count', 0)}`",
        f"- chunks: `{kb_build.get('total_chunk_count', 0)}`",
        f"- zero_chunk_documents: `{kb_build.get('zero_chunk_document_count', 0)}`",
        f"- parse_status: `{parse_build.get('status')}`",
        f"- activation_status: `{activation_build.get('status')}`",
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


def render_assistant_test_plan_review_markdown(report: Mapping[str, Any]) -> str:
    """Render an assistant test-plan review report."""

    summary = report.get("summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    stage_coverage = report.get("stage_coverage", [])
    stage_coverage = stage_coverage if isinstance(stage_coverage, list) else []
    review_cases = report.get("review_cases", [])
    review_cases = review_cases if isinstance(review_cases, list) else []
    build = report.get("build_evidence_summary", {})
    build = build if isinstance(build, Mapping) else {}
    kb_build = build.get("kb_manifest", {}) if isinstance(build.get("kb_manifest"), Mapping) else {}
    parse_build = build.get("parse_report", {}) if isinstance(build.get("parse_report"), Mapping) else {}
    activation_build = build.get("activation_plan", {}) if isinstance(build.get("activation_plan"), Mapping) else {}
    lines = [
        "# RAGFlow Assistant Test Plan Review",
        "",
        f"- Schema: `{report.get('schema')}`",
        f"- Status: `{report.get('status')}`",
        f"- Assistant profile: `{report.get('assistant_profile')}`",
        f"- Mutation: `{report.get('mutation')}`",
        f"- Execution: `{(report.get('execution') or {}).get('status') if isinstance(report.get('execution'), Mapping) else None}`",
        f"- Cases: `{summary.get('case_count', 0)}`",
        f"- Ready cases: `{summary.get('ready_case_count', 0)}`",
        f"- Missing expected stages: `{summary.get('missing_expected_stage_count', 0)}`",
        "",
        "## Stage Coverage",
        "",
    ]
    for item in stage_coverage:
        if not isinstance(item, Mapping):
            continue
        marker = "present" if item.get("present") else "missing"
        expected = "expected" if item.get("expected_from_hints") else "optional"
        lines.append(f"- `{item.get('stage')}`: {marker}, count `{item.get('count', 0)}`, {expected}")
    lines.extend(
        [
            "",
            "## Build Evidence",
            "",
            f"- provided: `{str(build.get('provided')).lower()}`",
            f"- documents: `{kb_build.get('document_count', 0)}`",
            f"- chunks: `{kb_build.get('total_chunk_count', 0)}`",
            f"- zero_chunk_documents: `{kb_build.get('zero_chunk_document_count', 0)}`",
            f"- parse_status: `{parse_build.get('status')}`",
            f"- activation_status: `{activation_build.get('status')}`",
        ]
    )
    lines.extend(["", "## Review Cases", ""])
    if not review_cases:
        lines.append("- None")
    else:
        for case in review_cases:
            if isinstance(case, Mapping):
                lines.append(
                    f"- `{case.get('id')}` `{case.get('stage')}`: {case.get('question')}"
                )
    lines.extend(["", "## Issues", ""])
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
