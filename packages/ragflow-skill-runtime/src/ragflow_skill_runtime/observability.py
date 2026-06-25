"""Query observability helpers for public RAGFlow skills."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .retrieval import NormalizedChunk


TRACE_SCHEMA = "ragflow_query_trace_v1"
CITATION_AUDIT_SCHEMA = "ragflow_citation_audit_v1"
QUERY_DIAGNOSTIC_SCHEMA = "ragflow_query_diagnostic_report_v1"
QUERY_POLLUTION_REPORT_SCHEMA = "ragflow_query_pollution_report_v1"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "use",
    "what",
    "when",
    "where",
    "which",
    "with",
    "without",
}
_POLLUTION_STOPWORDS = _STOPWORDS | {
    "answer",
    "chunk",
    "chunks",
    "content",
    "document",
    "documents",
    "evidence",
    "query",
    "question",
    "result",
    "results",
    "retrieval",
    "source",
    "sources",
}


@dataclass(frozen=True)
class EvidenceWeight:
    """Deterministic host-agent evidence ranking details."""

    rank: int
    citation_id: str
    score: float
    similarity: float | None
    term_coverage: float
    matched_terms: list[str]
    matched_keywords: list[str]
    document_name: str | None
    document_id: str | None
    dataset_id: str | None
    chunk_id: str | None
    content_preview: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "citation_id": self.citation_id,
            "score": self.score,
            "similarity": self.similarity,
            "term_coverage": self.term_coverage,
            "matched_terms": self.matched_terms,
            "matched_keywords": self.matched_keywords,
            "document_name": self.document_name,
            "document_id": self.document_id,
            "dataset_id": self.dataset_id,
            "chunk_id": self.chunk_id,
            "content_preview": self.content_preview,
            "reasons": self.reasons,
        }


def _tokenize(text: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", text.lower())
        if token and token not in _STOPWORDS
    }
    return tokens


def _pollution_tokenize(text: str) -> set[str]:
    return {token for token in _tokenize(text) if token not in _POLLUTION_STOPWORDS}


def _clamp_similarity(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _preview(text: str, *, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _json_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Mapping):
        values: list[str] = []
        for key in (
            "term",
            "terms",
            "keyword",
            "keywords",
            "expanded_terms",
            "translated_terms",
            "generated_terms",
            "rewrite_terms",
            "query_terms",
            "value",
        ):
            if key in value:
                values.extend(_json_string_values(value[key]))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_json_string_values(item))
        return values
    return []


def load_pollution_terms(path: str | Path) -> list[str]:
    """Load optional expanded/translated query terms from a JSON file."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _json_string_values(raw)


def weight_evidence(question: str, chunks: Sequence[NormalizedChunk]) -> list[dict[str, Any]]:
    """Return deterministic evidence weights for retrieved chunks."""

    question_terms = _tokenize(question)
    evidence: list[EvidenceWeight] = []
    for index, chunk in enumerate(chunks, start=1):
        content_terms = _tokenize(chunk.content)
        matched_terms = sorted(question_terms.intersection(content_terms))
        keyword_terms = {
            token
            for keyword in chunk.important_keywords
            for token in _tokenize(keyword)
        }
        matched_keywords = sorted(question_terms.intersection(keyword_terms))
        term_coverage = len(matched_terms) / len(question_terms) if question_terms else 0.0
        keyword_score = len(matched_keywords) / len(question_terms) if question_terms else 0.0
        rank_boost = 1.0 / index
        similarity = _clamp_similarity(chunk.similarity)
        score = round(
            similarity * 0.65
            + min(term_coverage, 1.0) * 0.25
            + min(keyword_score, 1.0) * 0.05
            + rank_boost * 0.05,
            4,
        )
        reasons = []
        if chunk.similarity is not None:
            reasons.append("similarity")
        if matched_terms:
            reasons.append("question-term-overlap")
        if matched_keywords:
            reasons.append("important-keyword-overlap")
        if index == 1:
            reasons.append("top-ranked")
        evidence.append(
            EvidenceWeight(
                rank=index,
                citation_id=f"[{index}]",
                score=score,
                similarity=chunk.similarity,
                term_coverage=round(term_coverage, 4),
                matched_terms=matched_terms,
                matched_keywords=matched_keywords,
                document_name=chunk.document_name,
                document_id=chunk.document_id,
                dataset_id=chunk.dataset_id,
                chunk_id=chunk.chunk_id,
                content_preview=_preview(chunk.content),
                reasons=reasons,
            )
        )
    return [item.to_dict() for item in evidence]


def build_query_trace(
    *,
    question: str,
    requested_mode: str,
    effective_mode: str,
    dataset_ids: Sequence[str],
    top_k: int,
    similarity_threshold: float | None,
    host_assisted: bool,
    chunk_count: int,
    evidence: Sequence[Mapping[str, Any]],
    route: Mapping[str, Any] | None = None,
    timings_ms: Mapping[str, float] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a redaction-safe query trace payload."""

    return {
        "schema": TRACE_SCHEMA,
        "question": question,
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
            "host_assisted": host_assisted,
        },
        "dataset_ids": list(dataset_ids),
        "retrieval": {
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "chunk_count": chunk_count,
        },
        "route": route,
        "timings_ms": dict(timings_ms or {}),
        "cost": {
            "ragflow_retrieval_calls": 1,
            "llm_calls": 0,
            "script_owned_synthesis": False,
        },
        "evidence": [dict(item) for item in evidence],
        "warnings": list(warnings or []),
        "started_at": started_at,
        "finished_at": finished_at,
    }


def render_query_trace_markdown(trace: Mapping[str, Any]) -> str:
    """Render a compact Markdown query trace report."""

    mode = trace.get("mode", {}) if isinstance(trace.get("mode"), Mapping) else {}
    retrieval = trace.get("retrieval", {}) if isinstance(trace.get("retrieval"), Mapping) else {}
    lines = [
        "# RAGFlow Query Trace",
        "",
        f"- schema: `{trace.get('schema', TRACE_SCHEMA)}`",
        f"- requested_mode: `{mode.get('requested', '')}`",
        f"- effective_mode: `{mode.get('effective', '')}`",
        f"- host_assisted: `{str(mode.get('host_assisted', False)).lower()}`",
        f"- dataset_ids: `{', '.join(str(item) for item in trace.get('dataset_ids', []))}`",
        f"- top_k: `{retrieval.get('top_k', '')}`",
        f"- chunk_count: `{retrieval.get('chunk_count', '')}`",
        "",
        "## Evidence",
        "",
        "| Rank | Score | Similarity | Document | Reasons |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for item in trace.get("evidence", []):
        if not isinstance(item, Mapping):
            continue
        reasons = ", ".join(str(reason) for reason in item.get("reasons", []))
        similarity = item.get("similarity")
        similarity_text = "" if similarity is None else f"{float(similarity):.4f}"
        lines.append(
            "| {rank} | {score:.4f} | {similarity} | {doc} | {reasons} |".format(
                rank=item.get("rank", ""),
                score=float(item.get("score") or 0.0),
                similarity=similarity_text,
                doc=item.get("document_name") or item.get("document_id") or "",
                reasons=reasons,
            )
        )
    warnings = [str(item) for item in trace.get("warnings", []) if str(item)]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def evidence_from_query_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract or derive evidence weights from a `query.py ask --json` payload."""

    raw_evidence = payload.get("evidence")
    if isinstance(raw_evidence, list) and all(isinstance(item, Mapping) for item in raw_evidence):
        return [dict(item) for item in raw_evidence]
    chunks = []
    for item in payload.get("chunks", []):
        if not isinstance(item, Mapping):
            continue
        chunks.append(
            NormalizedChunk(
                content=str(item.get("content") or ""),
                similarity=item.get("similarity") if isinstance(item.get("similarity"), (int, float)) else None,
                document_name=item.get("document_name") if isinstance(item.get("document_name"), str) else None,
                document_id=item.get("document_id") if isinstance(item.get("document_id"), str) else None,
                dataset_id=item.get("dataset_id") if isinstance(item.get("dataset_id"), str) else None,
                chunk_id=item.get("chunk_id") if isinstance(item.get("chunk_id"), str) else None,
                important_keywords=[
                    str(keyword)
                    for keyword in item.get("important_keywords", [])
                    if str(keyword)
                ]
                if isinstance(item.get("important_keywords"), list)
                else [],
            )
        )
    return weight_evidence(str(payload.get("question") or ""), chunks)


def _query_chunks(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [chunk for chunk in payload.get("chunks", []) if isinstance(chunk, Mapping)]


def _chunk_text(chunk: Mapping[str, Any]) -> str:
    parts = []
    for key in ("content", "content_preview", "text", "page_content"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for key in ("document_name", "document_id", "chunk_id"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    keywords = chunk.get("important_keywords")
    if isinstance(keywords, list):
        parts.extend(str(item) for item in keywords if str(item))
    raw = chunk.get("raw")
    if isinstance(raw, Mapping):
        for key in ("content_with_weight", "content", "docnm_kwd", "document_name", "important_keywords"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value if str(item))
    return "\n".join(parts)


def _evidence_by_rank(evidence: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    by_rank: dict[int, Mapping[str, Any]] = {}
    for item in evidence:
        rank = item.get("rank")
        if isinstance(rank, int):
            by_rank[rank] = item
    return by_rank


def _rate(count: int | float, total: int | float) -> float:
    return round(float(count) / float(total), 4) if total else 0.0


def query_pollution_report(
    query_payload: Mapping[str, Any],
    *,
    trace: Mapping[str, Any] | None = None,
    expanded_terms: Sequence[str] | None = None,
    max_examples: int = 5,
    low_query_coverage_threshold: float = 0.25,
) -> dict[str, Any]:
    """Detect likely query expansion or BM25 bridge-term pollution in saved query output."""

    question = str(query_payload.get("question") or "")
    original_terms = _pollution_tokenize(question)
    expanded_term_set = {
        term
        for raw in expanded_terms or []
        for term in _pollution_tokenize(str(raw))
        if term and term not in original_terms
    }
    trace_payload = trace or {}
    if isinstance(trace_payload, Mapping):
        for key in ("expanded_terms", "translated_terms", "generated_terms", "rewrite_terms"):
            expanded_term_set.update(
                term
                for raw in _json_string_values(trace_payload.get(key))
                for term in _pollution_tokenize(raw)
                if term and term not in original_terms
            )

    chunks = _query_chunks(query_payload)
    evidence = evidence_from_query_payload(query_payload)
    evidence_rank = _evidence_by_rank(evidence)
    issues: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    bridge_counts: dict[str, int] = {}
    document_counts: dict[str, int] = {}
    expansion_only_hits = 0
    low_original_coverage_hits = 0

    for index, chunk in enumerate(chunks, start=1):
        text = _chunk_text(chunk)
        chunk_terms = _pollution_tokenize(text)
        original_hits = sorted(original_terms.intersection(chunk_terms))
        expansion_hits = sorted(expanded_term_set.intersection(chunk_terms))
        original_coverage = _rate(len(original_hits), len(original_terms))
        expansion_only = bool(expansion_hits and not original_hits)
        low_original_coverage = bool(expansion_hits and original_coverage < low_query_coverage_threshold)
        doc = (
            chunk.get("document_name")
            if isinstance(chunk.get("document_name"), str)
            else chunk.get("document_id")
            if isinstance(chunk.get("document_id"), str)
            else None
        )
        if doc:
            document_counts[str(doc)] = document_counts.get(str(doc), 0) + 1
        if expansion_only:
            expansion_only_hits += 1
        if low_original_coverage:
            low_original_coverage_hits += 1
        for term in expansion_hits:
            bridge_counts[term] = bridge_counts.get(term, 0) + 1
        if (expansion_only or low_original_coverage) and len(examples) < max_examples:
            evidence_item = evidence_rank.get(index, {})
            examples.append(
                {
                    "rank": index,
                    "document_name": chunk.get("document_name"),
                    "document_id": chunk.get("document_id"),
                    "chunk_id": chunk.get("chunk_id"),
                    "score": evidence_item.get("score") if isinstance(evidence_item, Mapping) else None,
                    "similarity": chunk.get("similarity"),
                    "original_coverage": original_coverage,
                    "original_hits": original_hits,
                    "expansion_hits": expansion_hits,
                    "symptoms": [
                        symptom
                        for symptom, present in (
                            ("expansion_only_match", expansion_only),
                            ("low_original_query_coverage", low_original_coverage),
                        )
                        if present
                    ],
                    "content_preview": _preview(str(chunk.get("content") or "")),
                }
            )

    if expansion_only_hits:
        issues.append(
            {
                "severity": "warning",
                "code": "expansion_only_matches",
                "message": "retrieved chunks matched expanded or translated terms without original query-term support",
                "count": expansion_only_hits,
            }
        )
    if low_original_coverage_hits:
        issues.append(
            {
                "severity": "warning",
                "code": "low_original_query_coverage",
                "message": "retrieved chunks have weak original query-term coverage and expansion-term overlap",
                "count": low_original_coverage_hits,
            }
        )
    dominant_sources = [
        {"document": document, "chunk_count": count, "share": _rate(count, len(chunks))}
        for document, count in sorted(document_counts.items(), key=lambda item: (-item[1], item[0]))
        if len(chunks) >= 3 and count / len(chunks) >= 0.5
    ]
    if dominant_sources:
        issues.append(
            {
                "severity": "info",
                "code": "source_dominance",
                "message": "one source contributes a large share of retrieved chunks",
                "sources": dominant_sources[:5],
            }
        )

    status = "PASS"
    if any(issue["severity"] == "warning" for issue in issues):
        status = "REVIEW"
    bridge_terms = [
        {"term": term, "chunk_count": count}
        for term, count in sorted(bridge_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "ok": True,
        "schema": QUERY_POLLUTION_REPORT_SCHEMA,
        "status": status,
        "question": question,
        "dataset_ids": list(query_payload.get("dataset_ids", [])) if isinstance(query_payload.get("dataset_ids"), list) else [],
        "summary": {
            "chunk_count": len(chunks),
            "evidence_count": len(evidence),
            "original_term_count": len(original_terms),
            "expanded_term_count": len(expanded_term_set),
            "expansion_only_match_count": expansion_only_hits,
            "low_original_coverage_count": low_original_coverage_hits,
            "bridge_term_count": len(bridge_terms),
            "issue_count": len(issues),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "terms": {
            "original": sorted(original_terms),
            "expanded": sorted(expanded_term_set),
            "bridge_terms": bridge_terms[:20],
        },
        "source_dominance": dominant_sources[:10],
        "examples": examples,
        "issues": issues,
        "recommendations": [
            "Review expanded or translated query terms before increasing recall-oriented retrieval parameters."
            if expanded_term_set
            else "Provide expanded or translated terms to distinguish expansion pollution from ordinary low relevance.",
            "Use suppression-report or benchmark qrels when repeated bridge terms or sources appear across many queries.",
        ],
    }


def render_query_pollution_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown query pollution report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Query Pollution Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- chunk_count: `{summary.get('chunk_count', 0)}`",
        f"- expansion_only_match_count: `{summary.get('expansion_only_match_count', 0)}`",
        f"- low_original_coverage_count: `{summary.get('low_original_coverage_count', 0)}`",
        "",
        "## Bridge Terms",
        "",
    ]
    terms = report.get("terms", {}) if isinstance(report.get("terms"), Mapping) else {}
    bridge_terms = terms.get("bridge_terms", []) if isinstance(terms.get("bridge_terms"), list) else []
    if not bridge_terms:
        lines.append("- None")
    else:
        for item in bridge_terms[:10]:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('term')}`: `{item.get('chunk_count')}` chunks")
    lines.extend(["", "## Examples", ""])
    examples = report.get("examples", []) if isinstance(report.get("examples"), list) else []
    if not examples:
        lines.append("- None")
    else:
        lines.extend(["| rank | document | symptoms | expansion hits | preview |", "| ---: | --- | --- | --- | --- |"])
        for item in examples:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| {rank} | {doc} | {symptoms} | {hits} | {preview} |".format(
                    rank=item.get("rank", ""),
                    doc=(item.get("document_name") or item.get("document_id") or ""),
                    symptoms=", ".join(str(value) for value in item.get("symptoms", [])),
                    hits=", ".join(str(value) for value in item.get("expansion_hits", [])),
                    preview=str(item.get("content_preview", "")).replace("|", "\\|"),
                )
            )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def _sentence_candidates(answer: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？.!?])\s+", answer.strip())
        if len(sentence.strip()) >= 20
    ]


def audit_citations(answer: str, evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit simple numeric citations in a host-generated answer."""

    numeric_citations = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    valid_ranks = {
        int(item["rank"])
        for item in evidence
        if isinstance(item, Mapping) and isinstance(item.get("rank"), int)
    }
    invalid = sorted({rank for rank in numeric_citations if rank not in valid_ranks})
    cited = sorted({rank for rank in numeric_citations if rank in valid_ranks})
    issues: list[dict[str, Any]] = []
    if invalid:
        issues.append(
            {
                "severity": "error",
                "code": "invalid_citation",
                "message": f"answer references unavailable citation ranks: {invalid}",
            }
        )
    if evidence and not numeric_citations:
        issues.append(
            {
                "severity": "warning",
                "code": "missing_citations",
                "message": "answer contains no numeric citations such as [1]",
            }
        )

    evidence_terms = []
    for item in evidence:
        preview = str(item.get("content_preview") or "") if isinstance(item, Mapping) else ""
        evidence_terms.append(_tokenize(preview))
    unsupported = []
    for sentence in _sentence_candidates(answer):
        if re.search(r"\[\d+\]", sentence):
            continue
        sentence_terms = _tokenize(sentence)
        best_overlap = max(
            (len(sentence_terms.intersection(terms)) for terms in evidence_terms),
            default=0,
        )
        if sentence_terms and best_overlap == 0:
            unsupported.append(sentence)
    if unsupported:
        issues.append(
            {
                "severity": "warning",
                "code": "unsupported_uncited_statement",
                "message": f"{len(unsupported)} answer sentence(s) have no citation and no lexical evidence overlap",
                "examples": unsupported[:3],
            }
        )

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "ok": errors == 0,
        "schema": CITATION_AUDIT_SCHEMA,
        "metrics": {
            "evidence_count": len(evidence),
            "citation_count": len(numeric_citations),
            "cited_evidence_count": len(cited),
            "invalid_citation_count": len(invalid),
            "unsupported_uncited_statement_count": len(unsupported),
            "errors": errors,
            "warnings": warnings,
        },
        "citations": {
            "numeric": numeric_citations,
            "valid_ranks": sorted(valid_ranks),
            "cited_ranks": cited,
            "invalid_ranks": invalid,
        },
        "issues": issues,
    }


def render_citation_audit_markdown(report: Mapping[str, Any]) -> str:
    """Render a Markdown citation audit report."""

    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), Mapping) else {}
    lines = [
        "# RAGFlow Citation Audit",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- evidence_count: `{metrics.get('evidence_count', 0)}`",
        f"- citation_count: `{metrics.get('citation_count', 0)}`",
        f"- invalid_citation_count: `{metrics.get('invalid_citation_count', 0)}`",
        f"- warnings: `{metrics.get('warnings', 0)}`",
        "",
        "## Issues",
        "",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def _severity_status(issues: Sequence[Mapping[str, Any]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "FAIL"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "REVIEW"
    return "PASS"


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
) -> None:
    item = {"severity": severity, "code": code, "message": message}
    if detail:
        item["detail"] = dict(detail)
    issues.append(item)


def diagnose_query_result(
    query_payload: Mapping[str, Any],
    *,
    trace: Mapping[str, Any] | None = None,
    citation_audit: Mapping[str, Any] | None = None,
    expected_terms: Sequence[str] | None = None,
    min_similarity: float = 0.15,
    min_evidence_score: float = 0.2,
) -> dict[str, Any]:
    """Diagnose weak retrieval, routing, evidence, and citation symptoms offline."""

    chunks = [item for item in query_payload.get("chunks", []) if isinstance(item, Mapping)]
    evidence = evidence_from_query_payload(query_payload)
    issues: list[dict[str, Any]] = []
    if not chunks:
        _append_issue(
            issues,
            severity="error",
            code="zero_chunks",
            message="query returned zero chunks",
        )
    if not evidence and chunks:
        _append_issue(
            issues,
            severity="warning",
            code="missing_evidence_weights",
            message="query output has chunks but no evidence weights could be derived",
        )

    top_similarity = _as_float(chunks[0].get("similarity")) if chunks else None
    if top_similarity is not None and top_similarity < min_similarity:
        _append_issue(
            issues,
            severity="warning",
            code="low_top_similarity",
            message="top retrieval similarity is below threshold",
            detail={"top_similarity": top_similarity, "min_similarity": min_similarity},
        )

    top_evidence_score = _as_float(evidence[0].get("score")) if evidence else None
    if top_evidence_score is not None and top_evidence_score < min_evidence_score:
        _append_issue(
            issues,
            severity="warning",
            code="low_evidence_score",
            message="top evidence score is below threshold",
            detail={"top_evidence_score": top_evidence_score, "min_evidence_score": min_evidence_score},
        )

    expected = [term for term in (expected_terms or []) if str(term).strip()]
    if expected:
        combined = "\n".join(str(chunk.get("content") or "") for chunk in chunks).lower()
        missing = [term for term in expected if term.lower() not in combined]
        if missing:
            _append_issue(
                issues,
                severity="warning",
                code="missing_expected_terms",
                message="retrieved chunks do not contain all expected terms",
                detail={"missing_terms": missing},
            )

    if trace:
        trace_warnings = [str(item) for item in trace.get("warnings", []) if str(item)]
        for warning in trace_warnings:
            _append_issue(
                issues,
                severity="warning",
                code="trace_warning",
                message=warning,
            )
        route = trace.get("route")
        if isinstance(route, Mapping):
            selected = route.get("selected")
            if isinstance(selected, Mapping) and selected.get("reason") == "default":
                _append_issue(
                    issues,
                    severity="warning",
                    code="route_default_used",
                    message="auto routing used the default KB instead of a hint match",
                    detail={"kb": selected.get("name"), "dataset_id": selected.get("dataset_id")},
                )

    if citation_audit:
        metrics = citation_audit.get("metrics", {}) if isinstance(citation_audit.get("metrics"), Mapping) else {}
        if metrics.get("invalid_citation_count", 0):
            _append_issue(
                issues,
                severity="error",
                code="invalid_citations",
                message="citation audit found invalid citation references",
                detail={"invalid_citation_count": metrics.get("invalid_citation_count")},
            )
        if metrics.get("warnings", 0):
            _append_issue(
                issues,
                severity="warning",
                code="citation_audit_warnings",
                message="citation audit reported warnings",
                detail={"warnings": metrics.get("warnings")},
            )

    document_names = [
        str(chunk.get("document_name"))
        for chunk in chunks
        if isinstance(chunk.get("document_name"), str) and chunk.get("document_name")
    ]
    duplicate_documents = sorted({name for name in document_names if document_names.count(name) > 1})
    if duplicate_documents:
        _append_issue(
            issues,
            severity="info",
            code="duplicate_source_documents",
            message="multiple retrieved chunks came from the same document",
            detail={"documents": duplicate_documents},
        )

    status = _severity_status(issues)
    return {
        "ok": status != "FAIL",
        "schema": QUERY_DIAGNOSTIC_SCHEMA,
        "status": status,
        "summary": {
            "chunk_count": len(chunks),
            "evidence_count": len(evidence),
            "top_similarity": top_similarity,
            "top_evidence_score": top_evidence_score,
            "issue_count": len(issues),
            "errors": sum(1 for issue in issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "question": query_payload.get("question"),
        "mode": query_payload.get("mode"),
        "dataset_ids": query_payload.get("dataset_ids", []),
        "thresholds": {
            "min_similarity": min_similarity,
            "min_evidence_score": min_evidence_score,
        },
        "issues": issues,
    }


def render_query_diagnostic_markdown(report: Mapping[str, Any]) -> str:
    """Render a Markdown query diagnostic report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Query Diagnostic",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- chunk_count: `{summary.get('chunk_count', 0)}`",
        f"- evidence_count: `{summary.get('evidence_count', 0)}`",
        f"- top_similarity: `{summary.get('top_similarity', '')}`",
        f"- top_evidence_score: `{summary.get('top_evidence_score', '')}`",
        "",
        "## Issues",
        "",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"
