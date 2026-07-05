"""Offline APOLLO table-QA fixture and evaluation helpers."""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


APOLLO_TABLE_QA_FIXTURE_SCHEMA = "apollo_table_qa_fixture_v1"
APOLLO_TABLE_QA_FIXTURE_VALIDATION_REPORT_SCHEMA = "apollo_table_qa_fixture_validation_report_v1"
APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA = "apollo_table_qa_evaluation_report_v1"
APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA = "apollo_table_qa_judge_request_v1"
APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA = "apollo_table_qa_judge_candidate_v1"
APOLLO_TABLE_QA_JUDGE_REVIEW_REPORT_SCHEMA = "apollo_table_qa_judge_review_report_v1"

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


def _stable_digest(payload: Mapping[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def _private_literal_issues(payload: Mapping[str, Any], *, artifact_label: str = "artifact") -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for field, value in _walk_strings(payload):
        if _PRIVATE_LITERAL_RE.search(value):
            _append_issue(
                issues,
                severity="error",
                code="private_literal",
                message=f"{artifact_label} contains a private path, endpoint, credential hint, or live identifier",
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
    issues = _private_literal_issues(payload, artifact_label="fixture")
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


def _preview_text(value: str, *, limit: int) -> str:
    if limit <= 0:
        return ""
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def _evaluation_cases_by_id(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    return {
        str(case.get("id")): case
        for case in cases
        if isinstance(case, Mapping) and _clean_string(case.get("id"))
    }


def _judge_evidence_items(
    *,
    case_id: str,
    result: Mapping[str, Any] | None,
    include_answer_text: bool,
    include_retrieval_previews: bool,
    max_answer_chars: int,
    max_retrieval_chars: int,
    max_retrieval_items: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    answer_text = _answer_text(result or {})
    answer = {
        "available": bool(answer_text.strip()),
        "sha256": _text_digest(answer_text) if answer_text else None,
        "preview": _preview_text(answer_text, limit=max_answer_chars) if include_answer_text else None,
        "truncated": bool(include_answer_text and len(answer_text) > max_answer_chars),
        "included": include_answer_text,
    }
    evidence: list[dict[str, Any]] = []
    if answer_text and include_answer_text:
        evidence.append(
            {
                "id": f"{case_id}:answer",
                "case_id": case_id,
                "source": "answer",
                "rank": None,
                "sha256": _text_digest(answer_text),
                "preview": answer["preview"],
                "truncated": answer["truncated"],
            }
        )
    if result and include_retrieval_previews:
        chunks = _chunks_from_mapping(result)
        for index, chunk in enumerate(chunks[:max_retrieval_items], start=1):
            text = _chunk_text(chunk)
            if not text.strip():
                continue
            preview = _preview_text(text, limit=max_retrieval_chars)
            evidence.append(
                {
                    "id": f"{case_id}:retrieval:{index}",
                    "case_id": case_id,
                    "source": "retrieval",
                    "rank": index,
                    "sha256": _text_digest(text),
                    "preview": preview,
                    "truncated": len(text) > max_retrieval_chars,
                }
            )
    return answer, evidence


def _load_or_create_apollo_evaluation_report(
    *,
    fixture_path: str | Path,
    results_path: str | Path,
    target: str,
    evaluation_report_path: str | Path | None,
) -> dict[str, Any]:
    if evaluation_report_path:
        payload = _read_json(evaluation_report_path)
        if not isinstance(payload, Mapping):
            raise ApolloQaError("APOLLO table-QA evaluation report must be a JSON object")
        if payload.get("schema") != APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA:
            raise ApolloQaError(f"evaluation report schema must be {APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA}")
        return dict(payload)
    return evaluate_apollo_table_qa_results(fixture_path=fixture_path, results_path=results_path, target=target)


def create_apollo_table_qa_judge_request(
    *,
    fixture_path: str | Path,
    results_path: str | Path,
    target: str = "auto",
    evaluation_report_path: str | Path | None = None,
    include_answer_text: bool = True,
    include_retrieval_previews: bool = True,
    max_answer_chars: int = 1200,
    max_retrieval_chars: int = 1200,
    max_retrieval_items: int = 5,
) -> dict[str, Any]:
    """Create a no-LLM request artifact for external APOLLO table-QA judging."""

    if target not in {"auto", "answer", "retrieval", "both"}:
        raise ApolloQaError("target must be one of: auto, answer, retrieval, both")
    if max_answer_chars < 0 or max_retrieval_chars < 0 or max_retrieval_items < 0:
        raise ApolloQaError("max answer chars, retrieval chars, and retrieval items must be non-negative")

    fixture_payload = load_apollo_table_qa_fixture(fixture_path)
    cases, fixture_issues = _parse_fixture(fixture_payload)
    results_payload = _read_json(results_path)
    results = _result_items(results_payload)
    results_by_id = {key: item for item in results if (key := _result_key(item))}
    evaluation_report = _load_or_create_apollo_evaluation_report(
        fixture_path=fixture_path,
        results_path=results_path,
        target=target,
        evaluation_report_path=evaluation_report_path,
    )
    baselines = _evaluation_cases_by_id(evaluation_report)

    request_cases: list[dict[str, Any]] = []
    evidence_count = 0
    for case in cases:
        result = _match_result(case, results_by_id, results)
        answer, evidence = _judge_evidence_items(
            case_id=case.case_id,
            result=result,
            include_answer_text=include_answer_text,
            include_retrieval_previews=include_retrieval_previews,
            max_answer_chars=max_answer_chars,
            max_retrieval_chars=max_retrieval_chars,
            max_retrieval_items=max_retrieval_items,
        )
        evidence_count += len(evidence)
        baseline = baselines.get(case.case_id, {})
        request_cases.append(
            {
                "id": case.case_id,
                "question": case.question,
                "table_source": case.table_source,
                "difficulty": case.difficulty,
                "expected": {
                    "strict_terms": list(case.strict_terms),
                    "normalized_facts": [
                        {"id": fact.fact_id, "canonical": fact.canonical, "aliases": list(fact.aliases)}
                        for fact in case.normalized_facts
                    ],
                },
                "baseline": {
                    "schema": APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
                    "target": evaluation_report.get("target", target),
                    "status": baseline.get("status"),
                    "answer": baseline.get("answer") if isinstance(baseline.get("answer"), Mapping) else {},
                    "retrieval": baseline.get("retrieval") if isinstance(baseline.get("retrieval"), Mapping) else {},
                },
                "result": {
                    "matched": result is not None,
                    "answer": answer,
                    "retrieval_evidence_count": sum(1 for item in evidence if item.get("source") == "retrieval"),
                },
                "evidence": evidence,
            }
        )

    core = {
        "schema": APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA,
        "fixture_sha256": _file_digest(fixture_path),
        "results_sha256": _file_digest(results_path),
        "evaluation_report_sha256": _file_digest(evaluation_report_path) if evaluation_report_path else None,
        "target": target,
        "case_ids": [case["id"] for case in request_cases],
        "baseline_summary": evaluation_report.get("summary", {}),
        "include_answer_text": include_answer_text,
        "include_retrieval_previews": include_retrieval_previews,
    }
    issues = list(fixture_issues)
    baseline_issues: list[dict[str, Any]] = []
    for raw_issue in evaluation_report.get("issues", []) if isinstance(evaluation_report.get("issues"), list) else []:
        if isinstance(raw_issue, Mapping):
            baseline_issues.append(dict(raw_issue))
    baseline_issue_counts = _issue_counts(baseline_issues)

    request: dict[str, Any] = {
        "schema": APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA,
        "created_at": _now(),
        "advisory": True,
        "llm_invoked": False,
        "request_hash": _stable_digest(core),
        "fixture_sha256": core["fixture_sha256"],
        "results_sha256": core["results_sha256"],
        "evaluation_report_sha256": core["evaluation_report_sha256"],
        "target": target,
        "summary": {
            **_issue_counts(issues),
            "case_count": len(request_cases),
            "result_count": len(results),
            "evidence_count": evidence_count,
            "baseline_ok": bool(evaluation_report.get("ok")),
            "baseline_pass_count": evaluation_report.get("summary", {}).get("pass_count")
            if isinstance(evaluation_report.get("summary"), Mapping)
            else None,
            "baseline_fail_count": evaluation_report.get("summary", {}).get("fail_count")
            if isinstance(evaluation_report.get("summary"), Mapping)
            else None,
            "baseline_errors": baseline_issue_counts["errors"],
            "baseline_warnings": baseline_issue_counts["warnings"],
            "llm_invoked": False,
            "script_owned_llm_calls": 0,
            "include_answer_text": include_answer_text,
            "include_retrieval_previews": include_retrieval_previews,
        },
        "redaction": {
            "answer_text_included": include_answer_text,
            "retrieval_previews_included": include_retrieval_previews,
            "review_redaction_report_recommended": True,
            "notes": [
                "Run request and review commands with --redaction-report before sharing artifacts externally.",
                "Do not include credentials, private endpoints, private paths, or authorization material in judge candidates.",
            ],
        },
        "instructions": {
            "purpose": "Judge APOLLO table-QA answers with an external reviewer or host-approved model while this script remains no-LLM.",
            "required_output_shape": {
                "schema": APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA,
                "advisory": True,
                "generated": True,
                "case_verdicts": [
                    {
                        "id": "fixture case id",
                        "verdict": "pass|review|fail",
                        "rationale": "short rationale grounded in request evidence",
                        "evidence_refs": ["case-id:answer", "case-id:retrieval:1"],
                    }
                ],
            },
            "requirements": [
                "Return JSON only unless the host explicitly asks otherwise.",
                "Set advisory to true.",
                "Set generated to true.",
                "Judge only the listed APOLLO cases and evidence.",
                "Do not invent facts, credentials, private endpoints, private paths, or authorization material.",
                "Treat the normalized no-LLM APOLLO evaluation as the baseline; advisory output cannot override a failed deterministic baseline.",
            ],
            "review_command": "ragflow-kb-build qa apollo-judge-review --request REQUEST.json --candidate CANDIDATE.json",
        },
        "policy": {
            "adapter": "request_review",
            "script_owned_backend": "disabled",
            "script_owned_llm_calls": 0,
            "external_judge_advisory": True,
            "deterministic_baseline": APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
        },
        "fixture": {
            "schema": fixture_payload.get("schema"),
            "metadata": fixture_payload.get("metadata") if isinstance(fixture_payload.get("metadata"), Mapping) else {},
        },
        "baseline_evaluation": {
            "schema": evaluation_report.get("schema"),
            "target": evaluation_report.get("target"),
            "ok": evaluation_report.get("ok"),
            "summary": evaluation_report.get("summary", {}),
            "issue_counts": baseline_issue_counts,
        },
        "cases": request_cases,
        "issues": issues,
    }
    request["issues"].extend(_private_literal_issues(request, artifact_label="judge request"))
    request["summary"].update(_issue_counts(request["issues"]))
    request["ok"] = _issue_counts(request["issues"])["errors"] == 0
    return request


def _candidate_case_items(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("case_verdicts", "cases", "items", "verdicts"):
        value = candidate.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _case_evidence_index(request_cases: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for case in request_cases:
        case_id = _clean_string(case.get("id"))
        for item in case.get("evidence", []) if isinstance(case.get("evidence"), list) else []:
            if not isinstance(item, Mapping):
                continue
            evidence_id = _clean_string(item.get("id"))
            if evidence_id:
                index[evidence_id] = {"case_id": case_id, "source": item.get("source"), "rank": item.get("rank")}
    return index


def _validate_candidate_evidence_refs(
    *,
    raw_refs: Any,
    case_id: str,
    field: str,
    evidence_index: Mapping[str, Mapping[str, Any]],
    known_case_ids: set[str],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if raw_refs is None:
        return []
    if not isinstance(raw_refs, list):
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_evidence_refs_invalid",
            message="candidate evidence_refs must be a list when present",
            field=field,
            case_id=case_id,
        )
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw_ref in enumerate(raw_refs):
        ref_field = f"{field}[{index}]"
        ref_id: str | None = None
        ref_case_id: str | None = None
        if isinstance(raw_ref, str):
            ref_id = _clean_string(raw_ref)
        elif isinstance(raw_ref, Mapping):
            ref_id = _clean_string(raw_ref.get("id") or raw_ref.get("evidence_id") or raw_ref.get("ref"))
            ref_case_id = _clean_string(raw_ref.get("case_id") or raw_ref.get("id"))
        else:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_evidence_ref_invalid",
                message="candidate evidence reference must be a string or object",
                field=ref_field,
                case_id=case_id,
            )
            continue
        if ref_id:
            if ref_id not in evidence_index:
                _append_issue(
                    issues,
                    severity="error",
                    code="apollo_table_qa_judge_unknown_evidence_ref",
                    message="candidate evidence reference is not present in the judge request",
                    field=ref_field,
                    case_id=case_id,
                )
            else:
                indexed_case = evidence_index[ref_id].get("case_id")
                if indexed_case and indexed_case != case_id:
                    _append_issue(
                        issues,
                        severity="error",
                        code="apollo_table_qa_judge_cross_case_evidence_ref",
                        message="candidate evidence reference belongs to a different fixture case",
                        field=ref_field,
                        case_id=case_id,
                    )
                normalized.append({"id": ref_id, **dict(evidence_index.get(ref_id, {}))})
            continue
        if ref_case_id:
            if ref_case_id not in known_case_ids:
                _append_issue(
                    issues,
                    severity="error",
                    code="apollo_table_qa_judge_unknown_case_ref",
                    message="candidate evidence reference points to an unknown case id",
                    field=ref_field,
                    case_id=case_id,
                )
            elif ref_case_id != case_id:
                _append_issue(
                    issues,
                    severity="error",
                    code="apollo_table_qa_judge_cross_case_ref",
                    message="candidate evidence reference points to a different case id",
                    field=ref_field,
                    case_id=case_id,
                )
            normalized.append({"case_id": ref_case_id})
            continue
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_evidence_ref_missing_id",
            message="candidate evidence reference must include an evidence id or case id",
            field=ref_field,
            case_id=case_id,
        )
    return normalized


def review_apollo_table_qa_judge_candidate(
    *,
    request_path: str | Path,
    candidate_path: str | Path,
    require_advisory: bool = True,
    require_generated: bool = True,
) -> dict[str, Any]:
    """Review an external APOLLO table-QA judge candidate with deterministic gates."""

    raw_request = _read_json(request_path)
    raw_candidate = _read_json(candidate_path)
    issues: list[dict[str, Any]] = []
    if not isinstance(raw_request, Mapping):
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_request_invalid",
            message="judge request must be a JSON object",
            field="request",
        )
        request: Mapping[str, Any] = {}
    else:
        request = raw_request
        if request.get("schema") != APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_request_schema_invalid",
                message=f"request schema must be {APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA}",
                field="request.schema",
            )
        if request.get("llm_invoked") is not False:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_request_invoked_llm",
                message="judge request must be a no-LLM request artifact",
                field="request.llm_invoked",
            )
        issues.extend(_private_literal_issues(request, artifact_label="judge request"))

    if not isinstance(raw_candidate, Mapping):
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_candidate_invalid",
            message="judge candidate must be a JSON object",
            field="candidate",
        )
        candidate: Mapping[str, Any] = {}
    else:
        candidate = raw_candidate
        issues.extend(_private_literal_issues(candidate, artifact_label="judge candidate"))

    request_cases = request.get("cases", []) if isinstance(request.get("cases"), list) else []
    known_case_ids = {
        str(case.get("id"))
        for case in request_cases
        if isinstance(case, Mapping) and _clean_string(case.get("id"))
    }
    baseline_status_by_id = {
        str(case.get("id")): case.get("baseline", {}).get("status")
        for case in request_cases
        if isinstance(case, Mapping) and isinstance(case.get("baseline"), Mapping) and _clean_string(case.get("id"))
    }
    evidence_index = _case_evidence_index([case for case in request_cases if isinstance(case, Mapping)])

    candidate_schema = candidate.get("schema") if isinstance(candidate, Mapping) else None
    if candidate:
        if candidate_schema not in {None, APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA}:
            _append_issue(
                issues,
                severity="warning",
                code="apollo_table_qa_judge_candidate_schema_unrecognized",
                message=f"candidate schema is not {APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA}",
                field="candidate.schema",
            )
        if require_advisory and candidate.get("advisory") is not True:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_not_advisory",
                message="external APOLLO judge output must set advisory to true",
                field="candidate.advisory",
            )
        if require_generated and candidate.get("generated") is not True:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_not_generated",
                message="external APOLLO judge output must set generated to true",
                field="candidate.generated",
            )

    normalized_cases: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    candidate_items = _candidate_case_items(candidate)
    if not candidate_items:
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_cases_missing",
            message="candidate must include case_verdicts with one verdict per request case",
            field="candidate.case_verdicts",
        )
    for index, item in enumerate(candidate_items):
        field = f"candidate.case_verdicts[{index}]"
        case_id = _clean_string(item.get("id") or item.get("case_id") or item.get("query_id"))
        if not case_id:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_case_id_missing",
                message="candidate case verdict is missing id",
                field=f"{field}.id",
            )
            continue
        if case_id in seen_candidate_ids:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_duplicate_case",
                message="candidate case verdict ids must be unique",
                field=f"{field}.id",
                case_id=case_id,
            )
            continue
        seen_candidate_ids.add(case_id)
        if case_id not in known_case_ids:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_unknown_case",
                message="candidate references a case id not present in the judge request",
                field=f"{field}.id",
                case_id=case_id,
            )
        verdict = _clean_string(item.get("verdict") or item.get("judgement") or item.get("judgment"))
        verdict = verdict.lower() if verdict else None
        if verdict not in {"pass", "review", "fail"}:
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_verdict_invalid",
                message="candidate verdict must be pass, review, or fail",
                field=f"{field}.verdict",
                case_id=case_id,
            )
        baseline_status = baseline_status_by_id.get(case_id)
        if verdict == "pass" and baseline_status != "PASS":
            _append_issue(
                issues,
                severity="error",
                code="apollo_table_qa_judge_baseline_override",
                message="candidate pass cannot override a failed or missing normalized no-LLM baseline",
                field=f"{field}.verdict",
                case_id=case_id,
            )
        raw_refs = item.get("evidence_refs", item.get("references", item.get("citations")))
        evidence_refs = _validate_candidate_evidence_refs(
            raw_refs=raw_refs,
            case_id=case_id,
            field=f"{field}.evidence_refs",
            evidence_index=evidence_index,
            known_case_ids=known_case_ids,
            issues=issues,
        )
        if verdict in {"pass", "review"} and raw_refs is None:
            _append_issue(
                issues,
                severity="warning",
                code="apollo_table_qa_judge_evidence_refs_missing",
                message="pass/review verdicts should cite request evidence_refs",
                field=f"{field}.evidence_refs",
                case_id=case_id,
            )
        normalized_cases.append(
            {
                "id": case_id,
                "verdict": verdict,
                "baseline_status": baseline_status,
                "evidence_ref_count": len(evidence_refs),
                "evidence_refs": evidence_refs,
                "rationale": _clean_string(item.get("rationale") or item.get("reason")),
            }
        )

    for missing_case_id in sorted(known_case_ids - seen_candidate_ids):
        _append_issue(
            issues,
            severity="error",
            code="apollo_table_qa_judge_missing_case",
            message="candidate omits a verdict for a request case",
            field="candidate.case_verdicts",
            case_id=missing_case_id,
        )

    issue_counts = _issue_counts(issues)
    verdict_counts = {
        "pass": sum(1 for case in normalized_cases if case.get("verdict") == "pass"),
        "review": sum(1 for case in normalized_cases if case.get("verdict") == "review"),
        "fail": sum(1 for case in normalized_cases if case.get("verdict") == "fail"),
    }
    return {
        "schema": APOLLO_TABLE_QA_JUDGE_REVIEW_REPORT_SCHEMA,
        "ok": issue_counts["errors"] == 0,
        "created_at": _now(),
        "request_schema": request.get("schema"),
        "candidate_schema": candidate_schema,
        "request_hash": request.get("request_hash"),
        "summary": {
            **issue_counts,
            "request_case_count": len(known_case_ids),
            "candidate_case_count": len(seen_candidate_ids),
            "missing_case_count": len(known_case_ids - seen_candidate_ids),
            "unknown_case_count": sum(1 for case in normalized_cases if case.get("id") not in known_case_ids),
            "evidence_ref_count": sum(int(case.get("evidence_ref_count", 0)) for case in normalized_cases),
            "advisory": candidate.get("advisory") is True if isinstance(candidate, Mapping) else None,
            "generated": candidate.get("generated") is True if isinstance(candidate, Mapping) else None,
            "script_owned_llm_calls": 0,
            **verdict_counts,
        },
        "policy": {
            "external_judge_advisory": True,
            "require_advisory": require_advisory,
            "require_generated": require_generated,
            "deterministic_baseline": APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
            "baseline_pass_is_not_overridable": True,
            "script_owned_backend": "disabled",
            "script_owned_llm_calls": 0,
        },
        "cases": normalized_cases,
        "issues": issues,
        "recommendations": [
            "Treat external APOLLO judge output as advisory only.",
            "Keep normalized no-LLM APOLLO evaluation as the baseline gate.",
            "Enable script-owned judge execution only after explicit LLM config, fake-provider fixtures, redaction, and release gates exist.",
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
    if report.get("schema") == APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA:
        lines.extend(
            [
                f"- llm_invoked: `{str(bool(report.get('llm_invoked'))).lower()}`",
                f"- evidence_count: `{summary.get('evidence_count', 0)}`",
                f"- baseline_ok: `{str(bool(summary.get('baseline_ok'))).lower()}`",
                f"- script_owned_llm_calls: `{summary.get('script_owned_llm_calls', 0)}`",
            ]
        )
    if report.get("schema") == APOLLO_TABLE_QA_JUDGE_REVIEW_REPORT_SCHEMA:
        lines.extend(
            [
                f"- request_case_count: `{summary.get('request_case_count', 0)}`",
                f"- candidate_case_count: `{summary.get('candidate_case_count', 0)}`",
                f"- missing_case_count: `{summary.get('missing_case_count', 0)}`",
                f"- unknown_case_count: `{summary.get('unknown_case_count', 0)}`",
                f"- script_owned_llm_calls: `{summary.get('script_owned_llm_calls', 0)}`",
            ]
        )
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
