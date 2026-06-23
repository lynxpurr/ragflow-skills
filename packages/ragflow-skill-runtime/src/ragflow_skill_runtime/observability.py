"""Query observability helpers for public RAGFlow skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .retrieval import NormalizedChunk


TRACE_SCHEMA = "ragflow_query_trace_v1"
CITATION_AUDIT_SCHEMA = "ragflow_citation_audit_v1"

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


def _clamp_similarity(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _preview(text: str, *, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


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
