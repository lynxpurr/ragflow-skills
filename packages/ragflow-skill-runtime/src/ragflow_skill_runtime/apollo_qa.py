"""Offline APOLLO table-QA fixture and evaluation helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


APOLLO_TABLE_QA_FIXTURE_SCHEMA = "apollo_table_qa_fixture_v1"
APOLLO_TABLE_QA_FIXTURE_VALIDATION_REPORT_SCHEMA = "apollo_table_qa_fixture_validation_report_v1"
APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA = "apollo_table_qa_evaluation_report_v1"

_PRIVATE_LITERAL_RE = re.compile(
    r"(?i)(?:/home/|/users/|/tmp/|192\.168\.|127\.0\.0\.1|api[_-]?key|bearer|token|dataset_id|document_id|kb:)"
)
_TAG_RE = re.compile(r"<[^>]+>")


class ApolloQaError(ValueError):
    """Raised when an APOLLO table-QA artifact cannot be read or evaluated."""


@dataclass(frozen=True)
class _Fact:
    fact_id: str
    canonical: str
    aliases: tuple[str, ...]

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.canonical, *self.aliases)


@dataclass(frozen=True)
class _FixtureCase:
    case_id: str
    question: str
    strict_terms: tuple[str, ...]
    normalized_facts: tuple[_Fact, ...]
    table_source: str | None
    difficulty: str | None
    metadata: Mapping[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApolloQaError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ApolloQaError(f"file is not valid JSON: {source}") from exc


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    items: list[str] = []
    for item in value:
        stripped = _clean_string(item)
        if stripped:
            items.append(stripped)
    return items


def _unique_strings(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        stripped = item.strip()
        key = stripped.casefold()
        if not stripped or key in seen:
            continue
        seen.add(key)
        output.append(stripped)
    return tuple(output)


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _TAG_RE.sub(" ", text)
    text = text.replace("℃", "°C")
    text = text.casefold()
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category[0] in {"L", "N"}:
            kept.append(char)
    return "".join(kept)


def _contains_strict(text: str, term: str) -> bool:
    return term in text


def _contains_normalized(text: str, fact: _Fact) -> bool:
    normalized_text = _normalized_text(text)
    return any(_normalized_text(term) in normalized_text for term in fact.terms if _normalized_text(term))


def _issue_counts(issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "errors": sum(1 for issue in issues if issue.get("severity") == "error"),
        "warnings": sum(1 for issue in issues if issue.get("severity") == "warning"),
        "infos": sum(1 for issue in issues if issue.get("severity") == "info"),
    }


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    field: str | None = None,
    case_id: str | None = None,
) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    if field:
        issue["field"] = field
    if case_id:
        issue["case_id"] = case_id
    issues.append(issue)


def _walk_strings(value: Any, *, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for index, item in enumerate(value):
            yield from _walk_strings(item, path=f"{path}[{index}]")


def _private_literal_issues(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for field, value in _walk_strings(payload):
        if _PRIVATE_LITERAL_RE.search(value):
            _append_issue(
                issues,
                severity="error",
                code="private_literal",
                message="fixture contains a private path, endpoint, credential hint, or live identifier",
                field=field,
            )
    return issues


def _normalized_facts_from_item(item: Mapping[str, Any], *, fallback_terms: Sequence[str]) -> tuple[_Fact, ...]:
    raw_facts: Any = item.get("normalized_facts")
    evaluation = item.get("evaluation") if isinstance(item.get("evaluation"), Mapping) else {}
    normalized_eval = (
        evaluation.get("normalized_contains")
        if isinstance(evaluation.get("normalized_contains"), Mapping)
        else evaluation.get("normalized")
    )
    if not raw_facts and isinstance(normalized_eval, Mapping):
        raw_facts = normalized_eval.get("facts") or normalized_eval.get("terms")
    if not raw_facts:
        raw_facts = item.get("acceptable_answers") or item.get("expected_facts")

    facts: list[_Fact] = []
    if isinstance(raw_facts, Mapping):
        raw_facts = [raw_facts]
    if isinstance(raw_facts, Sequence) and not isinstance(raw_facts, (str, bytes, bytearray)):
        for index, raw in enumerate(raw_facts):
            if isinstance(raw, str):
                canonical = raw.strip()
                aliases: list[str] = []
            elif isinstance(raw, Mapping):
                canonical = _clean_string(raw.get("canonical") or raw.get("term") or raw.get("text") or raw.get("answer"))
                aliases = _string_list(raw.get("aliases") or raw.get("acceptable") or raw.get("variants"))
            else:
                continue
            if canonical:
                fact_id = _clean_string(raw.get("id")) if isinstance(raw, Mapping) else None
                facts.append(
                    _Fact(
                        fact_id=fact_id or f"fact-{index + 1}",
                        canonical=canonical,
                        aliases=_unique_strings(aliases),
                    )
                )

    if not facts:
        facts = [
            _Fact(fact_id=f"fact-{index + 1}", canonical=term, aliases=())
            for index, term in enumerate(_unique_strings(fallback_terms))
        ]
    return tuple(facts)


def _strict_terms_from_item(item: Mapping[str, Any]) -> tuple[str, ...]:
    evaluation = item.get("evaluation") if isinstance(item.get("evaluation"), Mapping) else {}
    strict_eval = evaluation.get("strict_contains") if isinstance(evaluation.get("strict_contains"), Mapping) else {}
    terms = (
        _string_list(item.get("strict_terms"))
        or _string_list(strict_eval.get("terms") if isinstance(strict_eval, Mapping) else None)
        or _string_list(item.get("expected_terms"))
        or _string_list(item.get("expected_facts"))
    )
    return _unique_strings(terms)


def _parse_fixture(payload: Mapping[str, Any]) -> tuple[list[_FixtureCase], list[dict[str, Any]]]:
    issues = _private_literal_issues(payload)
    if payload.get("schema") != APOLLO_TABLE_QA_FIXTURE_SCHEMA:
        _append_issue(
            issues,
            severity="error",
            code="invalid_schema",
            message=f"fixture schema must be {APOLLO_TABLE_QA_FIXTURE_SCHEMA}",
            field="schema",
        )

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        _append_issue(
            issues,
            severity="error",
            code="missing_items",
            message="fixture must contain a non-empty items list",
            field="items",
        )
        return [], issues

    cases: list[_FixtureCase] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        field = f"items[{index}]"
        if not isinstance(raw_item, Mapping):
            _append_issue(
                issues,
                severity="error",
                code="invalid_item",
                message="fixture item must be a JSON object",
                field=field,
            )
            continue
        case_id = _clean_string(raw_item.get("id") or raw_item.get("case_id") or raw_item.get("query_id"))
        question = _clean_string(raw_item.get("question") or raw_item.get("query"))
        if not case_id:
            _append_issue(issues, severity="error", code="missing_case_id", message="fixture item is missing id", field=f"{field}.id")
            continue
        if case_id in seen_ids:
            _append_issue(
                issues,
                severity="error",
                code="duplicate_case_id",
                message="fixture item id must be unique",
                field=f"{field}.id",
                case_id=case_id,
            )
            continue
        seen_ids.add(case_id)
        if not question:
            _append_issue(
                issues,
                severity="error",
                code="missing_question",
                message="fixture item is missing question",
                field=f"{field}.question",
                case_id=case_id,
            )
            continue
        strict_terms = _strict_terms_from_item(raw_item)
        normalized_facts = _normalized_facts_from_item(raw_item, fallback_terms=strict_terms)
        if not strict_terms and not normalized_facts:
            _append_issue(
                issues,
                severity="error",
                code="missing_expected_facts",
                message="fixture item needs strict_terms, normalized_facts, acceptable_answers, or expected_facts",
                field=field,
                case_id=case_id,
            )
            continue
        metadata = raw_item.get("metadata") if isinstance(raw_item.get("metadata"), Mapping) else {}
        cases.append(
            _FixtureCase(
                case_id=case_id,
                question=question,
                strict_terms=strict_terms,
                normalized_facts=normalized_facts,
                table_source=_clean_string(raw_item.get("table_source") or raw_item.get("source_table")),
                difficulty=_clean_string(raw_item.get("difficulty")),
                metadata=dict(metadata),
            )
        )
    return cases, issues


def load_apollo_table_qa_fixture(path: str | Path) -> dict[str, Any]:
    """Load an APOLLO table-QA fixture JSON object."""

    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise ApolloQaError("APOLLO table-QA fixture must be a JSON object")
    return dict(payload)


def validate_apollo_table_qa_fixture(fixture_path: str | Path) -> dict[str, Any]:
    """Validate the APOLLO table-QA fixture schema without network or model calls."""

    payload = load_apollo_table_qa_fixture(fixture_path)
    cases, issues = _parse_fixture(payload)
    counts = _issue_counts(issues)
    strict_count = sum(len(case.strict_terms) for case in cases)
    normalized_count = sum(len(case.normalized_facts) for case in cases)
    return {
        "schema": APOLLO_TABLE_QA_FIXTURE_VALIDATION_REPORT_SCHEMA,
        "ok": counts["errors"] == 0,
        "generated_at": _now(),
        "fixture": {
            "schema": payload.get("schema"),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        },
        "summary": {
            "item_count": len(cases),
            "strict_term_count": strict_count,
            "normalized_fact_count": normalized_count,
            **counts,
        },
        "issues": issues,
        "recommendations": [
            "Keep APOLLO QA fixtures sanitized: no local paths, private endpoints, credentials, dataset IDs, document IDs, or KB names.",
            "Use normalized_facts aliases for table-header symbols and formatting variants instead of rewriting Markdown.",
            "Evaluate retrieval and answer results separately so recall failures and answer-reading failures stay visible.",
        ],
    }


def _result_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("results", "cases", "items", "evaluations", "answers", "queries"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return [payload]


def _result_key(item: Mapping[str, Any]) -> str | None:
    for key in ("id", "case_id", "query_id", "item_id"):
        value = _clean_string(item.get(key))
        if value:
            return value
    return None


def _answer_text(item: Mapping[str, Any]) -> str:
    for key in ("answer", "response", "output", "text", "message"):
        value = item.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            nested = _clean_string(value.get("text") or value.get("content") or value.get("message"))
            if nested:
                return nested
    return ""


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if not isinstance(chunk, Mapping):
        return ""
    for key in (
        "content",
        "content_with_weight",
        "content_preview",
        "text",
        "body",
        "markdown",
        "document",
    ):
        value = chunk.get(key)
        if isinstance(value, str):
            return value
    return ""


def _chunks_from_mapping(item: Mapping[str, Any]) -> list[Any]:
    chunks: list[Any] = []
    for key in ("chunks", "top_chunks", "evidence", "retrieval_results", "contexts"):
        value = item.get(key)
        if isinstance(value, list):
            chunks.extend(value)
    data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
    if isinstance(data.get("chunks"), list):
        chunks.extend(data["chunks"])
    retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), Mapping) else {}
    if isinstance(retrieval.get("chunks"), list):
        chunks.extend(retrieval["chunks"])
    query_output = item.get("query_output") if isinstance(item.get("query_output"), Mapping) else {}
    if query_output:
        chunks.extend(_chunks_from_mapping(query_output))
    return chunks


def _retrieval_text(item: Mapping[str, Any]) -> str:
    chunks = _chunks_from_mapping(item)
    return "\n".join(text for text in (_chunk_text(chunk) for chunk in chunks) if text)


def _match_result(case: _FixtureCase, results_by_id: Mapping[str, Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    keyed = results_by_id.get(case.case_id)
    if keyed is not None:
        return keyed
    normalized_question = _normalized_text(case.question)
    for item in results:
        question = _clean_string(item.get("question") or item.get("query"))
        if question and _normalized_text(question) == normalized_question:
            return item
    return None


def _evaluate_terms(text: str, *, strict_terms: Sequence[str], normalized_facts: Sequence[_Fact]) -> dict[str, Any]:
    strict_hits = [term for term in strict_terms if _contains_strict(text, term)]
    missing_strict = [term for term in strict_terms if term not in strict_hits]
    normalized_hits = [fact.fact_id for fact in normalized_facts if _contains_normalized(text, fact)]
    missing_normalized = [fact.fact_id for fact in normalized_facts if fact.fact_id not in normalized_hits]
    return {
        "available": bool(text.strip()),
        "strict": {
            "required": list(strict_terms),
            "hits": strict_hits,
            "missing": missing_strict,
            "passed": not missing_strict if strict_terms else True,
        },
        "normalized": {
            "required": [
                {"id": fact.fact_id, "canonical": fact.canonical, "aliases": list(fact.aliases)}
                for fact in normalized_facts
            ],
            "hits": normalized_hits,
            "missing": missing_normalized,
            "passed": not missing_normalized if normalized_facts else True,
        },
    }


def _case_status(
    *,
    target: str,
    answer_eval: Mapping[str, Any],
    retrieval_eval: Mapping[str, Any],
    result_available: bool,
) -> str:
    if not result_available:
        return "FAIL"
    answer_available = bool(answer_eval.get("available"))
    retrieval_available = bool(retrieval_eval.get("available"))
    answer_passed = bool(answer_eval.get("normalized", {}).get("passed")) if answer_available else False
    retrieval_passed = bool(retrieval_eval.get("normalized", {}).get("passed")) if retrieval_available else False
    if target == "answer":
        return "PASS" if answer_available and answer_passed else "FAIL"
    if target == "retrieval":
        return "PASS" if retrieval_available and retrieval_passed else "FAIL"
    if target == "both":
        return "PASS" if answer_available and retrieval_available and answer_passed and retrieval_passed else "FAIL"
    if answer_available:
        return "PASS" if answer_passed else "FAIL"
    if retrieval_available:
        return "PASS" if retrieval_passed else "FAIL"
    return "FAIL"


def evaluate_apollo_table_qa_results(
    *,
    fixture_path: str | Path,
    results_path: str | Path,
    target: str = "auto",
) -> dict[str, Any]:
    """Evaluate existing retrieval/answer JSON against an APOLLO table-QA fixture."""

    if target not in {"auto", "answer", "retrieval", "both"}:
        raise ApolloQaError("target must be one of: auto, answer, retrieval, both")

    fixture_payload = load_apollo_table_qa_fixture(fixture_path)
    cases, fixture_issues = _parse_fixture(fixture_payload)
    if any(issue.get("severity") == "error" for issue in fixture_issues):
        counts = _issue_counts(fixture_issues)
        return {
            "schema": APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
            "ok": False,
            "generated_at": _now(),
            "target": target,
            "summary": {"case_count": len(cases), "result_count": 0, **counts},
            "cases": [],
            "issues": fixture_issues,
        }

    results_payload = _read_json(results_path)
    results = _result_items(results_payload)
    results_by_id = {key: item for item in results if (key := _result_key(item))}

    report_cases: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for case in cases:
        result = _match_result(case, results_by_id, results)
        if result is None:
            answer_eval = _evaluate_terms("", strict_terms=case.strict_terms, normalized_facts=case.normalized_facts)
            retrieval_eval = _evaluate_terms("", strict_terms=case.strict_terms, normalized_facts=case.normalized_facts)
            status = "FAIL"
            _append_issue(
                issues,
                severity="error",
                code="missing_result",
                message="no result matched fixture case id or question",
                case_id=case.case_id,
            )
        else:
            answer_eval = _evaluate_terms(
                _answer_text(result),
                strict_terms=case.strict_terms,
                normalized_facts=case.normalized_facts,
            )
            retrieval_eval = _evaluate_terms(
                _retrieval_text(result),
                strict_terms=case.strict_terms,
                normalized_facts=case.normalized_facts,
            )
            status = _case_status(
                target=target,
                answer_eval=answer_eval,
                retrieval_eval=retrieval_eval,
                result_available=True,
            )
            if status == "FAIL":
                _append_issue(
                    issues,
                    severity="error",
                    code="case_failed",
                    message="case failed normalized contains evaluation for the selected target",
                    case_id=case.case_id,
                )
        report_cases.append(
            {
                "id": case.case_id,
                "question": case.question,
                "status": status,
                "table_source": case.table_source,
                "difficulty": case.difficulty,
                "answer": answer_eval,
                "retrieval": retrieval_eval,
            }
        )

    answer_cases = [case for case in report_cases if case["answer"]["available"]]
    retrieval_cases = [case for case in report_cases if case["retrieval"]["available"]]
    normalized_answer_passes = sum(1 for case in answer_cases if case["answer"]["normalized"]["passed"])
    strict_answer_passes = sum(1 for case in answer_cases if case["answer"]["strict"]["passed"])
    normalized_retrieval_passes = sum(1 for case in retrieval_cases if case["retrieval"]["normalized"]["passed"])
    strict_retrieval_passes = sum(1 for case in retrieval_cases if case["retrieval"]["strict"]["passed"])
    normalized_only_answer_corrections = sum(
        1
        for case in answer_cases
        if case["answer"]["normalized"]["passed"] and not case["answer"]["strict"]["passed"]
    )
    status_counts = {
        "pass": sum(1 for case in report_cases if case["status"] == "PASS"),
        "fail": sum(1 for case in report_cases if case["status"] == "FAIL"),
    }
    issue_counts = _issue_counts(issues)
    return {
        "schema": APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
        "ok": issue_counts["errors"] == 0,
        "generated_at": _now(),
        "target": target,
        "fixture": {
            "schema": fixture_payload.get("schema"),
            "metadata": fixture_payload.get("metadata") if isinstance(fixture_payload.get("metadata"), Mapping) else {},
        },
        "summary": {
            "case_count": len(cases),
            "result_count": len(results),
            "answer_case_count": len(answer_cases),
            "retrieval_case_count": len(retrieval_cases),
            "pass_count": status_counts["pass"],
            "fail_count": status_counts["fail"],
            "strict_answer_pass_count": strict_answer_passes,
            "normalized_answer_pass_count": normalized_answer_passes,
            "strict_retrieval_pass_count": strict_retrieval_passes,
            "normalized_retrieval_pass_count": normalized_retrieval_passes,
            "normalized_only_answer_correction_count": normalized_only_answer_corrections,
            **issue_counts,
        },
        "cases": report_cases,
        "issues": issues,
        "recommendations": [
            "Treat strict contains and normalized contains separately; normalized-only passes usually point to formatting or alias drift.",
            "When retrieval passes but answer fails, keep the case in the answer-reading bucket instead of changing chunking first.",
            "Use fixture aliases for APOLLO-specific table terms; do not hardcode domain replacements in Markdown post-processing.",
        ],
    }


def render_apollo_table_qa_markdown(report: Mapping[str, Any], *, title: str = "APOLLO Table QA Report") -> str:
    """Render a compact Markdown summary for APOLLO table-QA validation/evaluation."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        f"# {title}",
        "",
        f"- schema: `{report.get('schema', '')}`",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
        f"- case_count: `{summary.get('case_count', summary.get('item_count', 0))}`",
        f"- errors: `{summary.get('errors', 0)}`",
        f"- warnings: `{summary.get('warnings', 0)}`",
    ]
    if "normalized_answer_pass_count" in summary:
        lines.extend(
            [
                f"- target: `{report.get('target', 'auto')}`",
                f"- normalized_answer_pass_count: `{summary.get('normalized_answer_pass_count', 0)}`",
                f"- strict_answer_pass_count: `{summary.get('strict_answer_pass_count', 0)}`",
                f"- normalized_retrieval_pass_count: `{summary.get('normalized_retrieval_pass_count', 0)}`",
                f"- strict_retrieval_pass_count: `{summary.get('strict_retrieval_pass_count', 0)}`",
                f"- normalized_only_answer_correction_count: `{summary.get('normalized_only_answer_correction_count', 0)}`",
            ]
        )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines.extend(["", "## Issues", ""])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                case_id = f" `{issue.get('case_id')}`" if issue.get("case_id") else ""
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`{case_id}: {issue.get('message')}")
    cases = report.get("cases", []) if isinstance(report.get("cases"), list) else []
    if cases:
        lines.extend(["", "## Cases", ""])
        for case in cases[:20]:
            if isinstance(case, Mapping):
                lines.append(f"- `{case.get('id')}` `{case.get('status')}`: {case.get('question')}")
    return "\n".join(lines) + "\n"
