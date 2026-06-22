"""Lightweight retrieval validation primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .retrieval import NormalizedChunk, normalize_retrieval_response


class ValidationError(RuntimeError):
    """Raised when validation inputs are invalid."""


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    raise ValidationError(f"{field_name} must be a string or list of strings")


@dataclass(frozen=True)
class ValidationQuery:
    id: str
    question: str
    min_chunks: int = 1
    expected_terms: list[str] = field(default_factory=list)
    expected_documents: list[str] = field(default_factory=list)
    top_k: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int) -> "ValidationQuery":
        question = data.get("question") or data.get("query")
        if not isinstance(question, str) or not question.strip():
            raise ValidationError(f"query[{index}].question is required")
        min_chunks = int(data.get("min_chunks", 1))
        if min_chunks < 0:
            raise ValidationError(f"query[{index}].min_chunks must be non-negative")
        top_k = data.get("top_k")
        if top_k is not None:
            top_k = int(top_k)
            if top_k <= 0:
                raise ValidationError(f"query[{index}].top_k must be positive")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError(f"query[{index}].metadata must be an object")
        return cls(
            id=str(data.get("id") or data.get("query_id") or f"q{index + 1}"),
            question=question.strip(),
            min_chunks=min_chunks,
            expected_terms=_string_list(
                data.get("expected_terms", data.get("must_contain")),
                field_name=f"query[{index}].expected_terms",
            ),
            expected_documents=_string_list(
                data.get("expected_documents", data.get("expected_docs")),
                field_name=f"query[{index}].expected_documents",
            ),
            top_k=top_k,
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "min_chunks": self.min_chunks,
            "expected_terms": list(self.expected_terms),
            "expected_documents": list(self.expected_documents),
            "top_k": self.top_k,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ValidationCaseResult:
    query: ValidationQuery
    passed: bool
    chunk_count: int
    term_hits: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    document_hits: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    error: str | None = None
    chunks: list[NormalizedChunk] = field(default_factory=list)

    def to_dict(self, *, max_chunks: int = 3) -> dict[str, Any]:
        return {
            "id": self.query.id,
            "question": self.query.question,
            "passed": self.passed,
            "chunk_count": self.chunk_count,
            "term_hits": list(self.term_hits),
            "missing_terms": list(self.missing_terms),
            "document_hits": list(self.document_hits),
            "missing_documents": list(self.missing_documents),
            "error": self.error,
            "top_chunks": [chunk.to_dict() for chunk in self.chunks[:max_chunks]],
            "metadata": self.query.metadata,
        }


@dataclass(frozen=True)
class ValidationReport:
    level: str
    dataset_id: str
    dataset_name: str
    cases: list[ValidationCaseResult]

    @property
    def ok(self) -> bool:
        return all(case.passed for case in self.cases)

    def metrics(self) -> dict[str, Any]:
        total = len(self.cases)
        passed = sum(1 for case in self.cases if case.passed)
        expected_terms = sum(len(case.query.expected_terms) for case in self.cases)
        term_hits = sum(len(case.term_hits) for case in self.cases)
        expected_docs = sum(len(case.query.expected_documents) for case in self.cases)
        doc_hits = sum(len(case.document_hits) for case in self.cases)
        chunk_counts = [case.chunk_count for case in self.cases]
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else 0.0,
            "empty_results": sum(1 for count in chunk_counts if count == 0),
            "average_chunks": sum(chunk_counts) / total if total else 0.0,
            "term_hit_rate": term_hits / expected_terms if expected_terms else None,
            "document_hit_rate": doc_hits / expected_docs if expected_docs else None,
        }

    def to_dict(self, *, max_chunks: int = 3) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "level": self.level,
            "dataset": {"id": self.dataset_id, "name": self.dataset_name},
            "metrics": self.metrics(),
            "cases": [case.to_dict(max_chunks=max_chunks) for case in self.cases],
        }


def load_validation_queries(path: str | Path) -> list[ValidationQuery]:
    """Load validation queries from a JSON file."""

    query_path = Path(path)
    try:
        data = json.loads(query_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"query set not found: {query_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"query set is not valid JSON: {query_path}") from exc

    raw_queries = data.get("queries") if isinstance(data, Mapping) else data
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValidationError("query set must be a non-empty list or object with queries")
    queries = []
    for index, item in enumerate(raw_queries):
        if not isinstance(item, Mapping):
            raise ValidationError(f"query[{index}] must be an object")
        queries.append(ValidationQuery.from_dict(item, index=index))
    return queries


def smoke_query(question: str | None, *, dataset_name: str) -> ValidationQuery:
    """Create the default smoke validation query."""

    return ValidationQuery(
        id="smoke",
        question=question or f"Summarize {dataset_name}",
        min_chunks=1,
    )


def _joined_chunk_text(chunks: list[NormalizedChunk]) -> str:
    values = []
    for chunk in chunks:
        values.extend(
            [
                chunk.content or "",
                chunk.document_name or "",
                chunk.document_id or "",
                " ".join(chunk.important_keywords),
            ]
        )
    return "\n".join(values).lower()


def _document_text(chunks: list[NormalizedChunk]) -> str:
    return "\n".join(
        value.lower()
        for chunk in chunks
        for value in (chunk.document_name, chunk.document_id)
        if value
    )


def evaluate_query_result(query: ValidationQuery, chunks: list[NormalizedChunk]) -> ValidationCaseResult:
    """Evaluate normalized chunks against one validation query."""

    joined_text = _joined_chunk_text(chunks)
    doc_text = _document_text(chunks)
    term_hits = [term for term in query.expected_terms if term.lower() in joined_text]
    missing_terms = [term for term in query.expected_terms if term.lower() not in joined_text]
    document_hits = [doc for doc in query.expected_documents if doc.lower() in doc_text]
    missing_documents = [doc for doc in query.expected_documents if doc.lower() not in doc_text]
    passed = (
        len(chunks) >= query.min_chunks
        and not missing_terms
        and not missing_documents
    )
    return ValidationCaseResult(
        query=query,
        passed=passed,
        chunk_count=len(chunks),
        term_hits=term_hits,
        missing_terms=missing_terms,
        document_hits=document_hits,
        missing_documents=missing_documents,
        chunks=chunks,
    )


def run_retrieval_validation(
    client: Any,
    *,
    level: str,
    dataset_id: str,
    dataset_name: str,
    queries: list[ValidationQuery],
    top_k: int = 3,
) -> ValidationReport:
    """Run retrieval validation queries against one RAGFlow dataset."""

    cases: list[ValidationCaseResult] = []
    for query in queries:
        try:
            raw = client.retrieve(
                question=query.question,
                dataset_ids=[dataset_id],
                top_k=query.top_k or top_k,
            )
            chunks = normalize_retrieval_response(raw)
            cases.append(evaluate_query_result(query, chunks))
        except Exception as exc:  # Keep multi-query validation resilient.
            cases.append(
                ValidationCaseResult(
                    query=query,
                    passed=False,
                    chunk_count=0,
                    error=str(exc),
                )
            )
    return ValidationReport(
        level=level,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        cases=cases,
    )


def render_markdown_report(report: ValidationReport) -> str:
    """Render a compact Markdown validation report."""

    metrics = report.metrics()
    lines = [
        f"# RAGFlow Validation Report",
        "",
        f"- Level: `{report.level}`",
        f"- Dataset: `{report.dataset_name}` (`{report.dataset_id}`)",
        f"- Status: `{'passed' if report.ok else 'failed'}`",
        f"- Pass rate: `{metrics['pass_rate']:.2%}`",
        "",
        "| id | status | chunks | missing terms | missing documents |",
        "|---|---:|---:|---|---|",
    ]
    for case in report.cases:
        status = "passed" if case.passed else "failed"
        missing_terms = ", ".join(case.missing_terms) or "-"
        missing_docs = ", ".join(case.missing_documents) or "-"
        lines.append(
            f"| `{case.query.id}` | {status} | {case.chunk_count} | {missing_terms} | {missing_docs} |"
        )
    lines.append("")
    return "\n".join(lines)
