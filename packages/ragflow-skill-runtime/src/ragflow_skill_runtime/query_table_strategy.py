"""No-LLM table query expansion and retrieval strategy reports."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .apollo_qa import (
    ApolloQaError,
    evaluate_apollo_table_qa_results,
    load_apollo_table_qa_fixture,
    validate_apollo_table_qa_fixture,
)
from .handoff import RETRIEVAL_HINTS_SCHEMA


TABLE_QUERY_STRATEGY_REPORT_SCHEMA = "ragflow_table_query_strategy_report_v1"

_MODEL_LABEL_RE = re.compile(r"\b[A-Za-z]{1,12}[A-Za-z0-9]*-[A-Za-z0-9][A-Za-z0-9-]*\b")
_CROSS_TABLE_MARKERS = (
    "compare",
    "comparison",
    "versus",
    " vs ",
    "difference",
    "higher",
    "lower",
    "which",
    "between",
    "跨表",
    "多表",
    "比较",
    "对比",
    "差异",
    "哪个",
    "哪一个",
    "更高",
    "更低",
    "分别",
)


class TableQueryStrategyError(ValueError):
    """Raised when table query strategy inputs cannot be planned safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TableQueryStrategyError(f"{label} not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise TableQueryStrategyError(f"{label} is not valid JSON: {source}") from exc
    if not isinstance(payload, Mapping):
        raise TableQueryStrategyError(f"{label} must be a JSON object")
    return dict(payload)


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = " ".join(value.split())
    return stripped or None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    items: list[str] = []
    for item in _as_list(value):
        cleaned = _clean_string(item)
        if cleaned:
            items.append(cleaned)
    return _unique(items)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category[0] in {"L", "N"}:
            kept.append(char)
    return "".join(kept)


def _contains_label(text: str, label: str) -> bool:
    normalized_label = _normalize(label)
    return bool(normalized_label and normalized_label in text)


def _fixture_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    output: list[dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, Mapping):
            continue
        question = _clean_string(raw.get("question") or raw.get("query"))
        if not question:
            continue
        item_id = _clean_string(raw.get("id") or raw.get("case_id") or raw.get("query_id")) or f"case-{index:03d}"
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        output.append(
            {
                "id": item_id,
                "question": question,
                "table_source": _clean_string(raw.get("table_source") or raw.get("source_table")),
                "difficulty": _clean_string(raw.get("difficulty")),
                "metadata": dict(metadata),
                "expected_tables": _expected_table_labels(raw, metadata),
            }
        )
    return output


def _expected_table_labels(item: Mapping[str, Any], metadata: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    for source in (item, metadata):
        for key in (
            "tables",
            "table_labels",
            "source_tables",
            "expected_tables",
            "comparison_tables",
            "target_tables",
            "models",
            "model_labels",
        ):
            labels.extend(_string_list(source.get(key)))
    table_source = _clean_string(item.get("table_source") or item.get("source_table"))
    if table_source:
        labels.append(table_source)
    return _unique(labels)


def _load_retrieval_hints(path: str | Path) -> dict[str, Any]:
    payload = _read_json_mapping(path, label="retrieval hints")
    if payload.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise TableQueryStrategyError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")
    return payload


def _alias_candidates_by_table(retrieval_hints: Mapping[str, Any]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    candidates = retrieval_hints.get("table_term_alias_candidates", [])
    if not isinstance(candidates, list):
        return grouped
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        table_index = candidate.get("table_index")
        if not isinstance(table_index, int):
            continue
        key = (str(candidate.get("document") or ""), table_index)
        grouped.setdefault(key, []).append(dict(candidate))
    return grouped


def _table_records(retrieval_hints: Mapping[str, Any]) -> list[dict[str, Any]]:
    tables = retrieval_hints.get("table_artifacts", [])
    aliases_by_table = _alias_candidates_by_table(retrieval_hints)
    if not isinstance(tables, list):
        return []
    output: list[dict[str, Any]] = []
    for index, table in enumerate(tables, start=1):
        if not isinstance(table, Mapping):
            continue
        document = str(table.get("document") or "")
        alias_candidates = aliases_by_table.get((document, index), [])
        alias_terms: list[str] = []
        for candidate in alias_candidates:
            alias_terms.extend(_string_list(candidate.get("source_label")))
            alias_terms.extend(_string_list(candidate.get("normalized_label")))
            alias_terms.extend(_string_list(candidate.get("candidate_aliases")))
        risks = table.get("semantic_risks", [])
        risk_codes = [
            str(risk.get("code"))
            for risk in risks
            if isinstance(risk, Mapping) and _clean_string(risk.get("code"))
        ] if isinstance(risks, list) else []
        model_labels = _string_list(table.get("model_label_candidates"))
        output.append(
            {
                "table_index": index,
                "document": table.get("document"),
                "caption": _clean_string(table.get("caption")),
                "source_heading": _clean_string(table.get("source_heading")),
                "page": table.get("page"),
                "source": table.get("source"),
                "model_label_candidates": model_labels,
                "term_aliases": _unique(alias_terms),
                "semantic_risk_score": int(table.get("semantic_risk_score", 0) or 0),
                "semantic_risk_codes": _unique(risk_codes),
                "review_required": bool(table.get("review_required")),
                "rowspan_count": int(table.get("rowspan_count", 0) or 0),
                "colspan_count": int(table.get("colspan_count", 0) or 0),
                "header_depth": int(table.get("header_depth", 0) or 0),
            }
        )
    return output


def _case_is_cross_table(case: Mapping[str, Any]) -> tuple[bool, list[str]]:
    question = str(case.get("question") or "")
    metadata = case.get("metadata") if isinstance(case.get("metadata"), Mapping) else {}
    haystack = " ".join(
        str(value or "")
        for value in (
            question,
            case.get("difficulty"),
            case.get("table_source"),
            metadata.get("query_type"),
            metadata.get("scope"),
            metadata.get("strategy"),
        )
    )
    lowered = f" {haystack.casefold()} "
    labels_in_question = _unique([match.upper() for match in _MODEL_LABEL_RE.findall(question)])
    reasons: list[str] = []
    if len(case.get("expected_tables", [])) >= 2:
        reasons.append("fixture declares multiple expected tables or model labels")
    if len(labels_in_question) >= 2:
        reasons.append("question mentions multiple model-like labels")
    if any(marker in lowered for marker in _CROSS_TABLE_MARKERS):
        reasons.append("question or metadata contains comparison markers")
    return bool(reasons), reasons


def _score_table_for_case(case: Mapping[str, Any], table: Mapping[str, Any]) -> tuple[int, list[str]]:
    question_norm = _normalize(case.get("question"))
    expected = _string_list(case.get("expected_tables"))
    table_labels = _unique(
        [
            *(_string_list(table.get("caption"))),
            *(_string_list(table.get("source_heading"))),
            *(_string_list(table.get("model_label_candidates"))),
            *(_string_list(table.get("term_aliases"))),
        ]
    )
    table_norm = _normalize(" ".join(table_labels))
    score = 0
    reasons: list[str] = []
    for label in expected:
        if _contains_label(table_norm, label):
            score += 5
            reasons.append(f"fixture/table label match: {label}")
    for label in table.get("model_label_candidates", []) if isinstance(table.get("model_label_candidates"), list) else []:
        if _contains_label(question_norm, str(label)):
            score += 4
            reasons.append(f"model label in question: {label}")
    for label in table.get("term_aliases", []) if isinstance(table.get("term_aliases"), list) else []:
        if _contains_label(question_norm, str(label)):
            score += 3
            reasons.append(f"term alias in question: {label}")
    for label in (table.get("caption"), table.get("source_heading")):
        cleaned = _clean_string(label)
        if cleaned and _contains_label(question_norm, cleaned):
            score += 2
            reasons.append(f"context label in question: {cleaned}")
    if table.get("semantic_risk_codes"):
        score += 1
        reasons.append("table has semantic review risks")
    return score, _unique(reasons)


def _select_tables_for_case(
    case: Mapping[str, Any],
    tables: list[Mapping[str, Any]],
    *,
    max_tables_per_case: int,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for table in tables:
        score, reasons = _score_table_for_case(case, table)
        if score > 0:
            scored.append({**dict(table), "match_score": score, "match_reasons": reasons})
    scored.sort(
        key=lambda item: (
            -int(item.get("match_score", 0)),
            -int(item.get("semantic_risk_score", 0)),
            int(item.get("table_index", 0)),
        )
    )
    if scored:
        return scored[:max_tables_per_case]
    is_cross, _reasons = _case_is_cross_table(case)
    if is_cross:
        fallback = [
            {**dict(table), "match_score": int(table.get("semantic_risk_score", 0) or 0), "match_reasons": ["fallback to highest-risk table hints"]}
            for table in tables
            if table.get("review_required") or int(table.get("semantic_risk_score", 0) or 0) > 0
        ]
        fallback.sort(key=lambda item: (-int(item.get("semantic_risk_score", 0)), int(item.get("table_index", 0))))
        return fallback[:max_tables_per_case]
    return []


def _query_with_terms(question: str, terms: list[str], *, skip_normalized_existing: bool = True) -> str:
    normalized_question = " ".join(question.split())
    suffix_terms = []
    question_norm = _normalize(normalized_question)
    for term in terms:
        if not term:
            continue
        if skip_normalized_existing and _contains_label(question_norm, term):
            continue
        suffix_terms.append(term)
    suffix_terms = _unique(suffix_terms)
    return normalized_question if not suffix_terms else f"{normalized_question} {' '.join(suffix_terms[:8])}"


def _table_scope_terms(table: Mapping[str, Any]) -> list[str]:
    return _unique(
        [
            *(_string_list(table.get("caption"))),
            *(_string_list(table.get("source_heading"))),
            *(_string_list(table.get("model_label_candidates"))),
        ]
    )


def _alias_terms_for_question(question: str, tables: list[Mapping[str, Any]]) -> list[str]:
    question_norm = _normalize(question)
    terms: list[str] = []
    for table in tables:
        aliases = _string_list(table.get("term_aliases"))
        if any(_contains_label(question_norm, alias) for alias in aliases):
            terms.extend(aliases)
    return _unique(terms)


def _planned_queries_for_case(
    case: Mapping[str, Any],
    selected_tables: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    case_id = str(case.get("id"))
    question = str(case.get("question"))
    planned: list[dict[str, Any]] = [
        {
            "id": f"{case_id}-direct",
            "query": question,
            "kind": "direct",
            "source": "original_question",
            "uses_retrieval_hints": False,
        }
    ]
    for index, table in enumerate(selected_tables, start=1):
        terms = _table_scope_terms(table)
        query = _query_with_terms(question, terms)
        if query != question:
            planned.append(
                {
                    "id": f"{case_id}-table-{index:03d}",
                    "query": query,
                    "kind": "table_hint",
                    "source": "retrieval_hints.table_artifacts",
                    "uses_retrieval_hints": True,
                    "table_index": table.get("table_index"),
                }
            )
    alias_terms = _alias_terms_for_question(question, selected_tables)
    alias_query = _query_with_terms(question, alias_terms, skip_normalized_existing=False)
    if alias_query != question:
        planned.append(
            {
                "id": f"{case_id}-alias-001",
                "query": alias_query,
                "kind": "term_alias_hint",
                "source": "retrieval_hints.table_term_alias_candidates",
                "uses_retrieval_hints": True,
                "terms": alias_terms[:8],
            }
        )
    combined_terms: list[str] = []
    for table in selected_tables:
        combined_terms.extend(_table_scope_terms(table))
    combined_query = _query_with_terms(question, combined_terms)
    cross_table, _reasons = _case_is_cross_table(case)
    if cross_table and combined_query != question:
        planned.append(
            {
                "id": f"{case_id}-cross-table-001",
                "query": combined_query,
                "kind": "cross_table_hint",
                "source": "retrieval_hints.table_artifacts",
                "uses_retrieval_hints": True,
                "table_indices": [table.get("table_index") for table in selected_tables],
            }
        )
    deduped: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    for item in planned:
        query = str(item.get("query") or "")
        key = query.casefold()
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped.append(item)
    return deduped


def _strategies_for_case(case: Mapping[str, Any], planned_queries: list[Mapping[str, Any]], *, top_k: int, rrf_k: int) -> list[dict[str, Any]]:
    query_ids = [str(item.get("id")) for item in planned_queries]
    hint_query_ids = [str(item.get("id")) for item in planned_queries if item.get("uses_retrieval_hints")]
    strategies = [
        {
            "id": "direct_top_k",
            "kind": "direct",
            "query_ids": query_ids[:1],
            "top_k": top_k,
            "llm_calls": 0,
            "ragflow_calls_in_report": 0,
            "purpose": "baseline single-query retrieval",
        }
    ]
    if hint_query_ids:
        strategies.append(
            {
                "id": "hint_multi_query",
                "kind": "multi_query",
                "query_ids": query_ids,
                "top_k": top_k,
                "llm_calls": 0,
                "ragflow_calls_in_report": 0,
                "purpose": "run original and retrieval-hint-expanded queries, then evaluate saved outputs offline",
            }
        )
    cross_table, _reasons = _case_is_cross_table(case)
    if cross_table and len(query_ids) > 1:
        strategies.append(
            {
                "id": "rrf_fusion",
                "kind": "fusion_rrf",
                "query_ids": query_ids,
                "top_k": top_k,
                "rrf_k": rrf_k,
                "llm_calls": 0,
                "ragflow_calls_in_report": 0,
                "purpose": "compare direct retrieval with multi-query outputs fused by reciprocal rank fusion",
            }
        )
    return strategies


def _case_report(case: Mapping[str, Any], tables: list[Mapping[str, Any]], *, max_tables_per_case: int, top_k: int, rrf_k: int) -> dict[str, Any]:
    cross_table, cross_reasons = _case_is_cross_table(case)
    selected_tables = _select_tables_for_case(case, tables, max_tables_per_case=max_tables_per_case)
    planned_queries = _planned_queries_for_case(case, selected_tables)
    strategies = _strategies_for_case(case, planned_queries, top_k=top_k, rrf_k=rrf_k)
    risk_codes = _unique(
        [
            code
            for table in selected_tables
            for code in _string_list(table.get("semantic_risk_codes"))
        ]
    )
    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "difficulty": case.get("difficulty"),
        "table_source": case.get("table_source"),
        "classification": {
            "cross_table": cross_table,
            "reasons": cross_reasons,
        },
        "review_hints_used": {
            "selected_table_count": len(selected_tables),
            "semantic_risk_codes": risk_codes,
            "term_alias_hint_used": any(item.get("kind") == "term_alias_hint" for item in planned_queries),
            "table_structure_hint_used": bool(risk_codes),
        },
        "selected_tables": [
            {
                "table_index": table.get("table_index"),
                "caption": table.get("caption"),
                "source_heading": table.get("source_heading"),
                "page": table.get("page"),
                "model_label_candidates": table.get("model_label_candidates", []),
                "semantic_risk_score": table.get("semantic_risk_score", 0),
                "semantic_risk_codes": table.get("semantic_risk_codes", []),
                "match_score": table.get("match_score", 0),
                "match_reasons": table.get("match_reasons", []),
            }
            for table in selected_tables
        ],
        "planned_queries": planned_queries,
        "strategies": strategies,
    }


def _strategy_evaluations(
    *,
    fixture_path: str | Path,
    strategy_result_paths: Mapping[str, str | Path] | None,
    evaluation_target: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluations: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for strategy, result_path in (strategy_result_paths or {}).items():
        try:
            report = evaluate_apollo_table_qa_results(
                fixture_path=fixture_path,
                results_path=result_path,
                target=evaluation_target,
            )
        except (ApolloQaError, OSError, json.JSONDecodeError) as exc:
            issues.append(
                {
                    "severity": "error",
                    "code": "strategy_result_evaluation_failed",
                    "message": str(exc),
                    "strategy": strategy,
                }
            )
            continue
        evaluations.append(
            {
                "strategy": strategy,
                "schema": report.get("schema"),
                "ok": bool(report.get("ok")),
                "target": report.get("target"),
                "summary": report.get("summary", {}),
                "case_statuses": [
                    {
                        "id": case.get("id"),
                        "status": case.get("status"),
                    }
                    for case in report.get("cases", [])
                    if isinstance(case, Mapping)
                ],
            }
        )
    return evaluations, issues


def build_table_query_strategy_report(
    *,
    fixture_path: str | Path,
    retrieval_hints_path: str | Path,
    strategy_result_paths: Mapping[str, str | Path] | None = None,
    evaluation_target: str = "retrieval",
    top_k: int = 8,
    rrf_k: int = 60,
    max_tables_per_case: int = 2,
) -> dict[str, Any]:
    """Build a no-network table query expansion and cross-table strategy report."""

    if top_k <= 0:
        raise TableQueryStrategyError("top_k must be greater than zero")
    if rrf_k <= 0:
        raise TableQueryStrategyError("rrf_k must be greater than zero")
    if max_tables_per_case <= 0:
        raise TableQueryStrategyError("max_tables_per_case must be greater than zero")
    if evaluation_target not in {"auto", "answer", "retrieval", "both"}:
        raise TableQueryStrategyError("evaluation_target must be one of: auto, answer, retrieval, both")

    fixture_payload = load_apollo_table_qa_fixture(fixture_path)
    validation = validate_apollo_table_qa_fixture(fixture_path)
    retrieval_hints = _load_retrieval_hints(retrieval_hints_path)
    tables = _table_records(retrieval_hints)
    fixture_cases = _fixture_items(fixture_payload)
    cases = [
        _case_report(
            case,
            tables,
            max_tables_per_case=max_tables_per_case,
            top_k=top_k,
            rrf_k=rrf_k,
        )
        for case in fixture_cases
    ]
    evaluations, evaluation_issues = _strategy_evaluations(
        fixture_path=fixture_path,
        strategy_result_paths=strategy_result_paths,
        evaluation_target=evaluation_target,
    )

    issues: list[dict[str, Any]] = []
    if not validation.get("ok"):
        issues.append(
            {
                "severity": "error",
                "code": "fixture_validation_failed",
                "message": "APOLLO table-QA fixture did not pass validation",
                "summary": validation.get("summary", {}),
            }
        )
    if not tables:
        issues.append(
            {
                "severity": "warning",
                "code": "retrieval_hints_missing_tables",
                "message": "retrieval hints contain no table_artifacts, so hint expansion is limited",
            }
        )
    if not any(case["classification"]["cross_table"] for case in cases):
        issues.append(
            {
                "severity": "info",
                "code": "no_cross_table_cases_detected",
                "message": "no fixture case looked like a cross-table comparison",
            }
        )
    for evaluation in evaluations:
        summary = evaluation.get("summary", {}) if isinstance(evaluation.get("summary"), Mapping) else {}
        if int(summary.get("fail_count", 0) or 0) > 0:
            issues.append(
                {
                    "severity": "info",
                    "code": "strategy_evaluation_has_failures",
                    "message": "one saved strategy result still has failed APOLLO cases",
                    "strategy": evaluation.get("strategy"),
                    "summary": summary,
                }
            )
    issues.extend(evaluation_issues)

    errors = sum(1 for issue in issues if issue.get("severity") == "error")
    warnings = sum(1 for issue in issues if issue.get("severity") == "warning")
    infos = sum(1 for issue in issues if issue.get("severity") == "info")
    status = "FAIL" if errors else "REVIEW" if warnings or infos else "PASS"
    planned_query_count = sum(len(case.get("planned_queries", [])) for case in cases)
    hint_query_count = sum(
        1
        for case in cases
        for query in case.get("planned_queries", [])
        if isinstance(query, Mapping) and query.get("uses_retrieval_hints")
    )
    fusion_case_count = sum(
        1
        for case in cases
        if any(strategy.get("kind") == "fusion_rrf" for strategy in case.get("strategies", []) if isinstance(strategy, Mapping))
    )
    return {
        "schema": TABLE_QUERY_STRATEGY_REPORT_SCHEMA,
        "ok": status != "FAIL",
        "status": status,
        "generated_at": _now(),
        "offline_only": True,
        "llm_calls": 0,
        "ragflow_calls": 0,
        "inputs": {
            "fixture_schema": fixture_payload.get("schema"),
            "retrieval_hints_schema": retrieval_hints.get("schema"),
            "strategy_result_labels": sorted(str(key) for key in (strategy_result_paths or {}).keys()),
        },
        "parameters": {
            "top_k": top_k,
            "rrf_k": rrf_k,
            "max_tables_per_case": max_tables_per_case,
            "evaluation_target": evaluation_target,
        },
        "summary": {
            "case_count": len(cases),
            "cross_table_case_count": sum(1 for case in cases if case["classification"]["cross_table"]),
            "table_artifact_count": len(tables),
            "table_semantic_risk_count": sum(len(table.get("semantic_risk_codes", [])) for table in tables),
            "planned_query_count": planned_query_count,
            "hint_expanded_query_count": hint_query_count,
            "fusion_strategy_case_count": fusion_case_count,
            "strategy_evaluation_count": len(evaluations),
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
        },
        "cases": cases,
        "strategy_evaluations": evaluations,
        "issues": issues,
        "recommendations": [
            "Run direct_top_k first as a baseline, then compare hint_multi_query and rrf_fusion saved outputs with this report.",
            "Use table captions, source headings, model labels, and reviewed term aliases as query expansion hints; do not rewrite Markdown.",
            "When retrieval passes but answer evaluation fails, treat the problem as table-reading or answer synthesis instead of chunking first.",
        ],
    }


def render_table_query_strategy_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown table query strategy report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Table Query Strategy Report",
        "",
        f"- schema: `{report.get('schema', TABLE_QUERY_STRATEGY_REPORT_SCHEMA)}`",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- offline_only: `{str(report.get('offline_only', True)).lower()}`",
        f"- llm_calls: `{report.get('llm_calls', 0)}`",
        f"- ragflow_calls: `{report.get('ragflow_calls', 0)}`",
        f"- case_count: `{summary.get('case_count', 0)}`",
        f"- cross_table_case_count: `{summary.get('cross_table_case_count', 0)}`",
        f"- planned_query_count: `{summary.get('planned_query_count', 0)}`",
        f"- hint_expanded_query_count: `{summary.get('hint_expanded_query_count', 0)}`",
        f"- fusion_strategy_case_count: `{summary.get('fusion_strategy_case_count', 0)}`",
        "",
        "## Cases",
        "",
        "| id | cross_table | selected_tables | planned_queries | strategies |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for case in report.get("cases", []) if isinstance(report.get("cases"), list) else []:
        if not isinstance(case, Mapping):
            continue
        classification = case.get("classification") if isinstance(case.get("classification"), Mapping) else {}
        strategies = [
            str(strategy.get("id"))
            for strategy in case.get("strategies", [])
            if isinstance(strategy, Mapping) and strategy.get("id")
        ]
        lines.append(
            "| "
            f"`{case.get('id', '')}` | "
            f"`{str(classification.get('cross_table', False)).lower()}` | "
            f"`{len(case.get('selected_tables', [])) if isinstance(case.get('selected_tables'), list) else 0}` | "
            f"`{len(case.get('planned_queries', [])) if isinstance(case.get('planned_queries'), list) else 0}` | "
            f"{', '.join(f'`{item}`' for item in strategies)} |"
        )
    evaluations = report.get("strategy_evaluations", [])
    if isinstance(evaluations, list) and evaluations:
        lines.extend(["", "## Strategy Evaluations", "", "| strategy | ok | pass | fail |", "| --- | --- | ---: | ---: |"])
        for evaluation in evaluations:
            if not isinstance(evaluation, Mapping):
                continue
            eval_summary = evaluation.get("summary", {}) if isinstance(evaluation.get("summary"), Mapping) else {}
            lines.append(
                f"| `{evaluation.get('strategy', '')}` | `{str(evaluation.get('ok', False)).lower()}` | "
                f"`{eval_summary.get('pass_count', 0)}` | `{eval_summary.get('fail_count', 0)}` |"
            )
    issues = report.get("issues", [])
    if isinstance(issues, list) and issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity', '')}` `{issue.get('code', '')}`: {issue.get('message', '')}")
    return "\n".join(lines) + "\n"
