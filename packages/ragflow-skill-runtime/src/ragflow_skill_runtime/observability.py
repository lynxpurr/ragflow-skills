"""Query observability helpers for public RAGFlow skills."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .retrieval import NormalizedChunk, stable_chunk_hash


TRACE_SCHEMA = "ragflow_query_trace_v1"
CITATION_AUDIT_SCHEMA = "ragflow_citation_audit_v1"
QUERY_DIAGNOSTIC_SCHEMA = "ragflow_query_diagnostic_report_v1"
QUERY_POLLUTION_REPORT_SCHEMA = "ragflow_query_pollution_report_v1"
QUERY_RERANK_AB_REPORT_SCHEMA = "ragflow_query_rerank_ab_report_v1"
FUSION_REPORT_SCHEMA = "ragflow_fusion_report_v1"

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


def _reference_variants(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    normalized = value.strip().lower()
    if not normalized:
        return set()
    variants = {normalized}
    if normalized.startswith("sha256:"):
        variants.add(normalized.removeprefix("sha256:"))
    elif len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized):
        variants.add(f"sha256:{normalized}")
    return variants


def _chunk_field(chunk: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = chunk.get("raw")
    if isinstance(raw, Mapping):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _chunk_aliases(chunk: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("chunk_id", "id", "source_chunk_id", "stable_hash", "content_sha256"):
        aliases.update(_reference_variants(chunk.get(key)))
    raw = chunk.get("raw")
    if isinstance(raw, Mapping):
        for key in ("chunk_id", "id", "source_chunk_id", "stable_hash", "content_sha256"):
            aliases.update(_reference_variants(raw.get(key)))
    stable_hash = stable_chunk_hash(chunk)
    aliases.update(_reference_variants(stable_hash))
    aliases.update(_reference_variants(stable_hash.removeprefix("sha256:")))
    return aliases


def _chunk_identity(chunk: Mapping[str, Any]) -> str:
    for keys in (
        ("chunk_id", "id", "source_chunk_id"),
        ("stable_hash", "content_sha256"),
    ):
        value = _chunk_field(chunk, keys)
        if value:
            if keys == ("stable_hash", "content_sha256") and len(value) == 64:
                return f"sha256:{value}"
            return value
    return stable_chunk_hash(chunk)


def _rerank_score(item: Any) -> float | None:
    if not isinstance(item, Mapping):
        return None
    for key in ("rerank_score", "score", "relevance_score", "similarity"):
        score = _as_float(item.get(key))
        if score is not None:
            return score
    return None


def _rerank_rank(item: Any) -> int | None:
    if not isinstance(item, Mapping):
        return None
    rank = item.get("rank")
    if isinstance(rank, int) and rank > 0:
        return rank
    if isinstance(rank, str) and rank.isdigit() and int(rank) > 0:
        return int(rank)
    return None


def _rerank_original_rank(item: Any) -> int | None:
    if not isinstance(item, Mapping):
        return None
    for key in ("original_rank", "source_rank", "ragflow_rank"):
        value = item.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    citation_id = item.get("citation_id")
    if isinstance(citation_id, str):
        match = re.fullmatch(r"\[(\d+)\]", citation_id.strip())
        if match:
            return int(match.group(1))
    return None


def _rerank_item_aliases(item: Any) -> set[str]:
    aliases: set[str] = set()
    if isinstance(item, str):
        aliases.update(_reference_variants(item))
        return aliases
    if not isinstance(item, Mapping):
        return aliases
    for key in (
        "chunk_id",
        "id",
        "source_chunk_id",
        "stable_hash",
        "content_sha256",
        "hash",
        "identifier",
        "target",
    ):
        aliases.update(_reference_variants(item.get(key)))
    for key in ("content", "content_preview", "text", "page_content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            aliases.update(_reference_variants(stable_chunk_hash({"content": value})))
    raw = item.get("raw")
    if isinstance(raw, Mapping):
        aliases.update(_rerank_item_aliases(raw))
    return aliases


def _rerank_item_label(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        for key in ("chunk_id", "id", "stable_hash", "content_sha256", "identifier", "target"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        rank = _rerank_original_rank(item)
        if rank:
            return f"original_rank:{rank}"
    return str(item)[:80]


def _rerank_items_from_mapping(payload: Mapping[str, Any]) -> list[Any]:
    scores = payload.get("scores") if isinstance(payload.get("scores"), Mapping) else payload.get("rerank_scores")
    if isinstance(scores, Mapping):
        scored_items = [
            {"chunk_id": str(identifier), "score": score}
            for identifier, score in scores.items()
        ]
        return sorted(
            scored_items,
            key=lambda item: (
                _as_float(item.get("score")) is None,
                -(_as_float(item.get("score")) or 0.0),
                str(item.get("chunk_id") or ""),
            ),
        )
    for key in ("reranked_chunks", "rerank", "ranking", "results", "chunks", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
        if isinstance(value, Mapping):
            nested = _rerank_items_from_mapping(value)
            if nested:
                return nested
    if _rerank_item_aliases(payload) or _rerank_original_rank(payload):
        return [payload]
    return []


def _extract_rerank_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, Mapping):
        items = _rerank_items_from_mapping(payload)
    else:
        items = []
    ranked = [(item, _rerank_rank(item)) for item in items]
    if ranked and all(rank is not None for _, rank in ranked):
        return [item for item, _ in sorted(ranked, key=lambda pair: int(pair[1] or 0))]
    return items


def _expected_chunk_hits_for_indices(
    indices: Sequence[int],
    aliases_by_index: Sequence[set[str]],
    expected_chunks: Sequence[str],
) -> list[str]:
    hits: list[str] = []
    for expected in expected_chunks:
        variants = _reference_variants(str(expected))
        if not variants:
            continue
        if any(aliases_by_index[index].intersection(variants) for index in indices):
            hits.append(str(expected))
    return hits


def _expected_term_hits_for_indices(
    indices: Sequence[int],
    texts_by_index: Sequence[str],
    expected_terms: Sequence[str],
) -> list[str]:
    hits: list[str] = []
    for expected in expected_terms:
        term = str(expected).strip()
        if not term:
            continue
        lowered = term.lower()
        if any(lowered in texts_by_index[index].lower() for index in indices):
            hits.append(term)
    return hits


def _source_label(payload: Mapping[str, Any], *, index: int) -> str:
    for key in ("source", "source_id", "kb_name", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    dataset_ids = payload.get("dataset_ids")
    if isinstance(dataset_ids, list) and dataset_ids:
        return ",".join(str(item) for item in dataset_ids if str(item)) or f"source-{index}"
    route = payload.get("route")
    if isinstance(route, Mapping):
        selected = route.get("selected")
        if isinstance(selected, Mapping):
            name = selected.get("name") or selected.get("dataset_id")
            if isinstance(name, str) and name.strip():
                return name.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        route = metadata.get("route")
        if isinstance(route, Mapping):
            selected = route.get("selected")
            if isinstance(selected, Mapping):
                name = selected.get("name") or selected.get("dataset_id")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return f"source-{index}"


def _dataset_ids(payload: Mapping[str, Any]) -> list[str]:
    dataset_ids = payload.get("dataset_ids")
    if isinstance(dataset_ids, list):
        return [str(item) for item in dataset_ids if str(item)]
    return []


def _normalized_similarity(chunk: Mapping[str, Any]) -> float | None:
    score = _as_float(chunk.get("similarity"))
    if score is None:
        score = _as_float(chunk.get("score"))
    return score


def _near_duplicate_key(chunk: Mapping[str, Any]) -> str:
    identity = _chunk_identity(chunk)
    if identity and not identity.startswith("sha256:"):
        return f"id:{identity.lower()}"
    text = _chunk_text(chunk) or str(chunk.get("content") or "")
    tokens = sorted(_pollution_tokenize(text))
    if len(tokens) >= 6:
        return "tokens:" + " ".join(tokens[:24])
    document = chunk.get("document_name") or chunk.get("document_id") or ""
    preview = _preview(str(chunk.get("content") or ""), limit=140).lower()
    return f"text:{document}:{preview}"


def _score_range(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return min(values), max(values)


def query_fusion_report(
    query_payloads: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 10,
    rrf_k: int = 60,
    max_per_source: int | None = None,
) -> dict[str, Any]:
    """Fuse saved query outputs with reciprocal rank fusion and explainable contributions."""

    issues: list[dict[str, Any]] = []
    if not query_payloads:
        _append_issue(
            issues,
            severity="error",
            code="no_query_outputs",
            message="fusion requires at least one query output",
        )
    if rrf_k <= 0:
        _append_issue(
            issues,
            severity="error",
            code="invalid_rrf_k",
            message="rrf_k must be greater than zero",
            detail={"rrf_k": rrf_k},
        )
    if top_k <= 0:
        _append_issue(
            issues,
            severity="error",
            code="invalid_top_k",
            message="top_k must be greater than zero",
            detail={"top_k": top_k},
        )
    if any(issue["severity"] == "error" for issue in issues):
        status = _severity_status(issues)
        return {
            "ok": False,
            "schema": FUSION_REPORT_SCHEMA,
            "status": status,
            "algorithm": "rrf",
            "parameters": {"top_k": top_k, "rrf_k": rrf_k, "max_per_source": max_per_source},
            "summary": {
                "source_count": len(query_payloads),
                "input_chunk_count": 0,
                "unique_chunk_count": 0,
                "deduplicated_chunk_count": 0,
                "result_count": 0,
                "issue_count": len(issues),
                "errors": sum(1 for issue in issues if issue["severity"] == "error"),
                "warnings": 0,
                "infos": 0,
            },
            "sources": [],
            "results": [],
            "issues": issues,
        }

    sources: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, Any]] = {}
    input_chunk_count = 0
    question = ""

    for source_index, payload in enumerate(query_payloads, start=1):
        if not question and isinstance(payload.get("question"), str):
            question = str(payload.get("question"))
        chunks = _query_chunks(payload)
        evidence = evidence_from_query_payload(payload)
        evidence_by_rank = _evidence_by_rank(evidence)
        label = _source_label(payload, index=source_index)
        dataset_ids = _dataset_ids(payload)
        similarities = [
            value
            for value in (_normalized_similarity(chunk) for chunk in chunks)
            if value is not None
        ]
        min_score, max_score = _score_range(similarities)
        if not chunks:
            _append_issue(
                issues,
                severity="warning",
                code="empty_source",
                message="one fusion source contains zero chunks",
                detail={"source": label},
            )
        sources.append(
            {
                "index": source_index,
                "source": label,
                "dataset_ids": dataset_ids,
                "chunk_count": len(chunks),
                "score_min": min_score if similarities else None,
                "score_max": max_score if similarities else None,
            }
        )
        source_limit = len(chunks) if max_per_source is None else max(0, min(max_per_source, len(chunks)))
        for rank, chunk in enumerate(chunks[:source_limit], start=1):
            input_chunk_count += 1
            similarity = _normalized_similarity(chunk)
            if similarity is not None and max_score > min_score:
                normalized_score = round((similarity - min_score) / (max_score - min_score), 4)
            elif similarity is not None:
                normalized_score = 1.0
            else:
                normalized_score = None
            contribution = round(1.0 / (rrf_k + rank), 6)
            key = _near_duplicate_key(chunk)
            evidence_item = evidence_by_rank.get(rank, {})
            entry = grouped.get(key)
            if entry is None:
                entry = {
                    "identity": _chunk_identity(chunk),
                    "dedupe_key": key,
                    "document_name": chunk.get("document_name"),
                    "document_id": chunk.get("document_id"),
                    "chunk_id": _chunk_field(chunk, ("chunk_id", "id", "source_chunk_id")),
                    "stable_hash": stable_chunk_hash(chunk),
                    "content": str(chunk.get("content") or ""),
                    "content_preview": _preview(str(chunk.get("content") or "")),
                    "best_original_rank": rank,
                    "best_similarity": similarity,
                    "best_evidence_score": _as_float(evidence_item.get("score")) if isinstance(evidence_item, Mapping) else None,
                    "source_count": 0,
                    "sources": [],
                    "score_components": [],
                    "rrf_score": 0.0,
                }
                grouped[key] = entry
            entry["rrf_score"] = round(float(entry["rrf_score"]) + contribution, 6)
            entry["best_original_rank"] = min(int(entry["best_original_rank"]), rank)
            if similarity is not None and (
                entry.get("best_similarity") is None or similarity > float(entry.get("best_similarity") or 0.0)
            ):
                entry["best_similarity"] = similarity
            evidence_score = _as_float(evidence_item.get("score")) if isinstance(evidence_item, Mapping) else None
            if evidence_score is not None and (
                entry.get("best_evidence_score") is None or evidence_score > float(entry.get("best_evidence_score") or 0.0)
            ):
                entry["best_evidence_score"] = evidence_score
            if label not in entry["sources"]:
                entry["sources"].append(label)
                entry["source_count"] = len(entry["sources"])
            entry["score_components"].append(
                {
                    "source": label,
                    "dataset_ids": dataset_ids,
                    "rank": rank,
                    "rrf_contribution": contribution,
                    "similarity": similarity,
                    "normalized_similarity": normalized_score,
                    "evidence_score": evidence_score,
                }
            )

    results = sorted(
        grouped.values(),
        key=lambda item: (-float(item["rrf_score"]), int(item["best_original_rank"]), str(item.get("identity") or "")),
    )
    for fused_rank, item in enumerate(results, start=1):
        item["fused_rank"] = fused_rank
        item["rrf_score"] = round(float(item["rrf_score"]), 6)
        item["sources"] = sorted(item["sources"])
    deduplicated_chunk_count = input_chunk_count - len(results)
    if deduplicated_chunk_count:
        _append_issue(
            issues,
            severity="info",
            code="deduplicated_chunks",
            message="fusion collapsed duplicate or near-identical chunks across sources",
            detail={"deduplicated_chunk_count": deduplicated_chunk_count},
        )
    status = _severity_status(issues)
    return {
        "ok": status != "FAIL",
        "schema": FUSION_REPORT_SCHEMA,
        "status": status,
        "algorithm": "rrf",
        "question": question,
        "parameters": {"top_k": top_k, "rrf_k": rrf_k, "max_per_source": max_per_source},
        "summary": {
            "source_count": len(sources),
            "input_chunk_count": input_chunk_count,
            "unique_chunk_count": len(results),
            "deduplicated_chunk_count": deduplicated_chunk_count,
            "result_count": min(top_k, len(results)),
            "issue_count": len(issues),
            "errors": sum(1 for issue in issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "sources": sources,
        "results": results[:top_k],
        "issues": issues,
        "recommendations": [
            "Review source contributions before using fusion as a default retrieval strategy.",
            "Use benchmark gates to compare fused output against single-KB retrieval before increasing top_k.",
        ],
    }


def render_query_fusion_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown fusion report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Fusion Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- algorithm: `{report.get('algorithm', '')}`",
        f"- source_count: `{summary.get('source_count', 0)}`",
        f"- input_chunk_count: `{summary.get('input_chunk_count', 0)}`",
        f"- unique_chunk_count: `{summary.get('unique_chunk_count', 0)}`",
        f"- deduplicated_chunk_count: `{summary.get('deduplicated_chunk_count', 0)}`",
        "",
        "## Results",
        "",
    ]
    results = report.get("results", []) if isinstance(report.get("results"), list) else []
    if not results:
        lines.append("- None")
    else:
        lines.extend(["| rank | score | sources | document | preview |", "| ---: | ---: | --- | --- | --- |"])
        for item in results:
            if not isinstance(item, Mapping):
                continue
            sources = item.get("sources", [])
            source_text = ", ".join(str(source) for source in sources) if isinstance(sources, list) else ""
            preview = str(item.get("content_preview", "")).replace("|", "\\|")
            lines.append(
                "| {rank} | {score:.6f} | {sources} | {doc} | {preview} |".format(
                    rank=item.get("fused_rank", ""),
                    score=float(item.get("rrf_score") or 0.0),
                    sources=source_text,
                    doc=(item.get("document_name") or item.get("document_id") or item.get("identity") or ""),
                    preview=preview,
                )
            )
    sources = report.get("sources", []) if isinstance(report.get("sources"), list) else []
    if sources:
        lines.extend(["", "## Sources", ""])
        for source in sources:
            if isinstance(source, Mapping):
                lines.append(
                    "- `{source}`: `{chunks}` chunks, datasets `{datasets}`".format(
                        source=source.get("source", ""),
                        chunks=source.get("chunk_count", 0),
                        datasets=", ".join(str(item) for item in source.get("dataset_ids", []))
                        if isinstance(source.get("dataset_ids"), list)
                        else "",
                    )
                )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines.extend(["", "## Issues", ""])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def query_rerank_ab_report(
    query_payload: Mapping[str, Any],
    *,
    rerank_payload: Any | None = None,
    expected_terms: Sequence[str] | None = None,
    expected_chunks: Sequence[str] | None = None,
    top_k: int = 5,
    max_examples: int = 10,
    min_top_k_overlap: float = 0.5,
) -> dict[str, Any]:
    """Compare saved RAGFlow ordering with an offline candidate rerank ordering."""

    chunks = _query_chunks(query_payload)
    evidence = evidence_from_query_payload(query_payload)
    evidence_by_rank = _evidence_by_rank(evidence)
    issues: list[dict[str, Any]] = []
    if not chunks:
        _append_issue(
            issues,
            severity="error",
            code="zero_chunks",
            message="query output contains no chunks to rerank",
        )

    aliases_by_index = [_chunk_aliases(chunk) for chunk in chunks]
    texts_by_index = [_chunk_text(chunk) for chunk in chunks]
    alias_to_indices: dict[str, list[int]] = {}
    for index, aliases in enumerate(aliases_by_index):
        for alias in aliases:
            alias_to_indices.setdefault(alias, []).append(index)

    candidate_source = "evidence_score"
    candidate_scores: dict[int, float | None] = {}
    unmatched_external: list[dict[str, Any]] = []
    used_indices: set[int] = set()
    candidate_order: list[int] = []
    rerank_items = _extract_rerank_items(rerank_payload) if rerank_payload is not None else []

    if rerank_payload is not None:
        candidate_source = "external_rerank"
        if not rerank_items:
            _append_issue(
                issues,
                severity="warning",
                code="no_rerank_items",
                message="external rerank JSON did not contain recognizable ranked items",
            )
            candidate_order = list(range(len(chunks)))
        for position, item in enumerate(rerank_items, start=1):
            matched_index = None
            original_rank = _rerank_original_rank(item)
            if original_rank is not None and 1 <= original_rank <= len(chunks) and original_rank - 1 not in used_indices:
                matched_index = original_rank - 1
            if matched_index is None:
                for alias in _rerank_item_aliases(item):
                    for candidate_index in alias_to_indices.get(alias, []):
                        if candidate_index not in used_indices:
                            matched_index = candidate_index
                            break
                    if matched_index is not None:
                        break
            if matched_index is None:
                unmatched_external.append(
                    {
                        "position": position,
                        "identifier": _rerank_item_label(item),
                        "score": _rerank_score(item),
                    }
                )
                continue
            used_indices.add(matched_index)
            candidate_order.append(matched_index)
            candidate_scores[matched_index] = _rerank_score(item)
        appended = [index for index in range(len(chunks)) if index not in used_indices]
        candidate_order.extend(appended)
        if unmatched_external:
            _append_issue(
                issues,
                severity="warning",
                code="unmatched_rerank_items",
                message="external rerank output referenced chunks that were not found in the query output",
                detail={"count": len(unmatched_external), "examples": unmatched_external[:max_examples]},
            )
        if appended and rerank_items:
            _append_issue(
                issues,
                severity="info",
                code="partial_rerank_output",
                message="external rerank output did not cover all original chunks; missing chunks were appended in original order",
                detail={"appended_count": len(appended)},
            )
    else:
        candidate_scores = {
            index: _as_float(evidence_by_rank.get(index + 1, {}).get("score"))
            for index in range(len(chunks))
        }
        candidate_order = sorted(
            range(len(chunks)),
            key=lambda index: (
                -(candidate_scores.get(index) if candidate_scores.get(index) is not None else -1.0),
                index,
            ),
        )
        if chunks:
            _append_issue(
                issues,
                severity="info",
                code="local_evidence_score_candidate",
                message="no external rerank JSON was provided; candidate order uses deterministic evidence scores",
            )

    if len(candidate_order) < len(chunks):
        candidate_order.extend(index for index in range(len(chunks)) if index not in set(candidate_order))
    candidate_rank_by_index = {index: rank for rank, index in enumerate(candidate_order, start=1)}
    effective_top_k = max(1, min(int(top_k or 1), len(chunks))) if chunks else 0
    original_top_k = list(range(effective_top_k))
    candidate_top_k = candidate_order[:effective_top_k]
    top_k_overlap = len(set(original_top_k).intersection(candidate_top_k)) if effective_top_k else 0
    top_k_overlap_rate = _rate(top_k_overlap, effective_top_k)

    expected_term_values = [str(term).strip() for term in (expected_terms or []) if str(term).strip()]
    expected_chunk_values = [str(chunk).strip() for chunk in (expected_chunks or []) if str(chunk).strip()]
    original_term_hits = _expected_term_hits_for_indices(original_top_k, texts_by_index, expected_term_values)
    candidate_term_hits = _expected_term_hits_for_indices(candidate_top_k, texts_by_index, expected_term_values)
    original_chunk_hits = _expected_chunk_hits_for_indices(original_top_k, aliases_by_index, expected_chunk_values)
    candidate_chunk_hits = _expected_chunk_hits_for_indices(candidate_top_k, aliases_by_index, expected_chunk_values)

    rankings: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        original_rank = index + 1
        candidate_rank = candidate_rank_by_index.get(index, original_rank)
        rank_delta = original_rank - candidate_rank
        chunk_expected_terms = _expected_term_hits_for_indices([index], texts_by_index, expected_term_values)
        chunk_expected_chunks = _expected_chunk_hits_for_indices([index], aliases_by_index, expected_chunk_values)
        evidence_item = evidence_by_rank.get(original_rank, {})
        rankings.append(
            {
                "identity": _chunk_identity(chunk),
                "original_rank": original_rank,
                "candidate_rank": candidate_rank,
                "rank_delta": rank_delta,
                "direction": "promoted" if rank_delta > 0 else "demoted" if rank_delta < 0 else "unchanged",
                "document_name": chunk.get("document_name"),
                "document_id": chunk.get("document_id"),
                "chunk_id": _chunk_field(chunk, ("chunk_id", "id", "source_chunk_id")),
                "stable_hash": stable_chunk_hash(chunk),
                "similarity": _as_float(chunk.get("similarity")),
                "evidence_score": _as_float(evidence_item.get("score")) if isinstance(evidence_item, Mapping) else None,
                "candidate_score": candidate_scores.get(index),
                "expected_term_hits": chunk_expected_terms,
                "expected_chunk_hits": chunk_expected_chunks,
                "content_preview": _preview(str(chunk.get("content") or "")),
            }
        )

    rankings_by_candidate = sorted(rankings, key=lambda item: int(item["candidate_rank"]))
    movements = sorted(
        [item for item in rankings if int(item["rank_delta"]) != 0],
        key=lambda item: (-abs(int(item["rank_delta"])), int(item["candidate_rank"])),
    )[:max_examples]
    changed_rank_count = sum(1 for item in rankings if item["rank_delta"] != 0)
    promoted_count = sum(1 for item in rankings if item["rank_delta"] > 0)
    demoted_count = sum(1 for item in rankings if item["rank_delta"] < 0)
    mean_abs_rank_delta = _rate(sum(abs(int(item["rank_delta"])) for item in rankings), len(rankings))

    if effective_top_k and top_k_overlap_rate < min_top_k_overlap:
        _append_issue(
            issues,
            severity="warning",
            code="low_top_k_overlap",
            message="candidate rerank changes more than the configured share of top-k results",
            detail={"top_k_overlap_rate": top_k_overlap_rate, "min_top_k_overlap": min_top_k_overlap},
        )
    if chunks and candidate_order and candidate_order[0] != 0:
        _append_issue(
            issues,
            severity="info",
            code="top_rank_changed",
            message="candidate rerank changes the top-ranked chunk",
            detail={"original_top_identity": rankings[0]["identity"], "candidate_top_identity": rankings_by_candidate[0]["identity"]},
        )
    if len(candidate_term_hits) < len(original_term_hits):
        _append_issue(
            issues,
            severity="warning",
            code="rerank_reduces_expected_term_hits",
            message="candidate rerank reduces expected-term coverage in top-k",
            detail={"original_hits": original_term_hits, "candidate_hits": candidate_term_hits},
        )
    elif len(candidate_term_hits) > len(original_term_hits):
        _append_issue(
            issues,
            severity="info",
            code="rerank_improves_expected_term_hits",
            message="candidate rerank improves expected-term coverage in top-k",
            detail={"original_hits": original_term_hits, "candidate_hits": candidate_term_hits},
        )
    if len(candidate_chunk_hits) < len(original_chunk_hits):
        _append_issue(
            issues,
            severity="warning",
            code="rerank_reduces_expected_chunk_hits",
            message="candidate rerank reduces expected-chunk coverage in top-k",
            detail={"original_hits": original_chunk_hits, "candidate_hits": candidate_chunk_hits},
        )
    elif len(candidate_chunk_hits) > len(original_chunk_hits):
        _append_issue(
            issues,
            severity="info",
            code="rerank_improves_expected_chunk_hits",
            message="candidate rerank improves expected-chunk coverage in top-k",
            detail={"original_hits": original_chunk_hits, "candidate_hits": candidate_chunk_hits},
        )

    status = _severity_status(issues)
    return {
        "ok": status != "FAIL",
        "schema": QUERY_RERANK_AB_REPORT_SCHEMA,
        "status": status,
        "question": query_payload.get("question"),
        "dataset_ids": query_payload.get("dataset_ids", []),
        "candidate_source": candidate_source,
        "summary": {
            "chunk_count": len(chunks),
            "evidence_count": len(evidence),
            "rerank_item_count": len(rerank_items),
            "unmatched_rerank_item_count": len(unmatched_external),
            "top_k": effective_top_k,
            "top_k_overlap": top_k_overlap,
            "top_k_overlap_rate": top_k_overlap_rate,
            "changed_rank_count": changed_rank_count,
            "promoted_count": promoted_count,
            "demoted_count": demoted_count,
            "mean_abs_rank_delta": mean_abs_rank_delta,
            "original_expected_term_hit_count": len(original_term_hits),
            "candidate_expected_term_hit_count": len(candidate_term_hits),
            "original_expected_chunk_hit_count": len(original_chunk_hits),
            "candidate_expected_chunk_hit_count": len(candidate_chunk_hits),
            "issue_count": len(issues),
            "errors": sum(1 for issue in issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "expected": {
            "terms": expected_term_values,
            "chunks": expected_chunk_values,
            "original_top_k_term_hits": original_term_hits,
            "candidate_top_k_term_hits": candidate_term_hits,
            "original_top_k_chunk_hits": original_chunk_hits,
            "candidate_top_k_chunk_hits": candidate_chunk_hits,
        },
        "top_k": {
            "original": [rankings[index] for index in original_top_k],
            "candidate": rankings_by_candidate[:effective_top_k],
        },
        "movements": movements,
        "rankings": rankings_by_candidate,
        "unmatched_rerank_items": unmatched_external[:max_examples],
        "issues": issues,
        "recommendations": [
            "Treat rerank deltas as review evidence until benchmark gates confirm quality improvements.",
            "Compare expected terms or expected_chunks when judging whether a reranker improves evidence order.",
        ],
    }


def render_query_rerank_ab_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown rerank A/B report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Query Rerank A/B Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- candidate_source: `{report.get('candidate_source', '')}`",
        f"- chunk_count: `{summary.get('chunk_count', 0)}`",
        f"- top_k: `{summary.get('top_k', 0)}`",
        f"- top_k_overlap_rate: `{summary.get('top_k_overlap_rate', 0)}`",
        f"- changed_rank_count: `{summary.get('changed_rank_count', 0)}`",
        "",
        "## Candidate Top K",
        "",
    ]
    top_k = report.get("top_k", {}) if isinstance(report.get("top_k"), Mapping) else {}
    candidate = top_k.get("candidate", []) if isinstance(top_k.get("candidate"), list) else []
    if not candidate:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| candidate rank | original rank | delta | document | score | preview |",
                "| ---: | ---: | ---: | --- | ---: | --- |",
            ]
        )
        for item in candidate:
            if not isinstance(item, Mapping):
                continue
            score = item.get("candidate_score")
            score_text = "" if score is None else f"{float(score):.4f}"
            preview = str(item.get("content_preview", "")).replace("|", "\\|")
            lines.append(
                "| {candidate_rank} | {original_rank} | {delta} | {doc} | {score} | {preview} |".format(
                    candidate_rank=item.get("candidate_rank", ""),
                    original_rank=item.get("original_rank", ""),
                    delta=item.get("rank_delta", ""),
                    doc=(item.get("document_name") or item.get("document_id") or item.get("identity") or ""),
                    score=score_text,
                    preview=preview,
                )
            )
    movements = report.get("movements", []) if isinstance(report.get("movements"), list) else []
    lines.extend(["", "## Rank Movements", ""])
    if not movements:
        lines.append("- None")
    else:
        lines.extend(["| chunk | original | candidate | delta | direction |", "| --- | ---: | ---: | ---: | --- |"])
        for item in movements:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| {chunk} | {original} | {candidate} | {delta} | {direction} |".format(
                    chunk=(item.get("document_name") or item.get("chunk_id") or item.get("identity") or ""),
                    original=item.get("original_rank", ""),
                    candidate=item.get("candidate_rank", ""),
                    delta=item.get("rank_delta", ""),
                    direction=item.get("direction", ""),
                )
            )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines.extend(["", "## Issues", ""])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


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
