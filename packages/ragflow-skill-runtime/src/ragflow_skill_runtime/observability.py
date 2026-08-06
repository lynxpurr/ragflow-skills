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
ANSWER_EVALUATION_REPORT_SCHEMA = "ragflow_answer_evaluation_report_v1"
QUERY_DIAGNOSTIC_SCHEMA = "ragflow_query_diagnostic_report_v1"
QUERY_POLLUTION_REPORT_SCHEMA = "ragflow_query_pollution_report_v1"
QUERY_RERANK_AB_REPORT_SCHEMA = "ragflow_query_rerank_ab_report_v1"
QUERY_CROSS_LANGUAGE_AB_REPORT_SCHEMA = "ragflow_cross_language_ab_report_v1"
FUSION_REPORT_SCHEMA = "ragflow_fusion_report_v1"
FUSION_TEST_REPORT_SCHEMA = "ragflow_fusion_test_report_v1"
QUERY_DIAGNOSTIC_NEXT_COMMANDS = {
    "no_result": [
        "ragflow-kb-build parse-report --kb-manifest <kb_manifest.json>",
        "ragflow-kb-build snapshot-chunks --dataset-id <dataset_id> --output <chunk_snapshot.json>",
    ],
    "wrong_modality": [
        "ragflow-kb-build health-report --multimodal-manifest <multimodal_kb_manifest.json>",
        "ragflow-kb-build validate --level benchmark --qrels <qrels.json>",
    ],
    "table_fragment": [
        "ragflow-kb-build snapshot-chunks --dataset-id <dataset_id> --output <chunk_snapshot.json>",
        "ragflow-query table-strategy --retrieval-hints <retrieval_hints.json>",
    ],
    "image_evidence": [
        "ragflow-kb-build asset-upload-plan --handoff-dir <handoff_dir>",
        "ragflow-kb-build image-ingestion-readiness --asset-upload-plan <asset_upload_plan.json>",
    ],
    "pollution": [
        "ragflow-query pollution-report --query-output <query.json> --expanded-term <term>",
    ],
    "route_mismatch": [
        "ragflow-query route-diagnose --routing <routing.json> --queries <route-test-queries.json>",
    ],
    "low_similarity": [
        "ragflow-kb-build validate --level benchmark --queries <queries.json> --qrels <qrels.json>",
        "ragflow-kb-build profile decision --reports <validation_reports...>",
    ],
}
QUERY_DIAGNOSTIC_CLASS_ORDER = tuple(QUERY_DIAGNOSTIC_NEXT_COMMANDS)

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


def _strict_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError(f"{field_name} must be a string or list of strings")


def _positive_int_value(
    value: Any,
    *,
    field_name: str,
    default: int | None = None,
    minimum: int = 1,
) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be an integer")
    if parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return parsed


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
    rewrite_plan: Mapping[str, Any] | None = None,
    retrieval_status: Mapping[str, Any] | None = None,
    retrieval_call_count: int = 1,
    llm_call_count: int = 0,
) -> dict[str, Any]:
    """Build a redaction-safe query trace payload."""

    retrieval_section: dict[str, Any] = {
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "chunk_count": chunk_count,
    }
    if retrieval_status:
        retrieval_section["status"] = retrieval_status.get("status")
        retrieval_section["status_reasons"] = list(retrieval_status.get("reasons", []))
        retrieval_section["status_report"] = dict(retrieval_status)

    trace = {
        "schema": TRACE_SCHEMA,
        "question": question,
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
            "host_assisted": host_assisted,
        },
        "dataset_ids": list(dataset_ids),
        "retrieval": retrieval_section,
        "route": route,
        "timings_ms": dict(timings_ms or {}),
        "cost": {
            "ragflow_retrieval_calls": max(0, int(retrieval_call_count)),
            "llm_calls": max(0, int(llm_call_count)),
            "script_owned_synthesis": False,
        },
        "evidence": [dict(item) for item in evidence],
        "warnings": list(warnings or []),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if rewrite_plan:
        trace["rewrite"] = dict(rewrite_plan)
    return trace


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
        f"- retrieval_status: `{retrieval.get('status', '')}`",
    ]
    rewrite = trace.get("rewrite") if isinstance(trace.get("rewrite"), Mapping) else None
    if rewrite:
        summary = rewrite.get("summary", {}) if isinstance(rewrite.get("summary"), Mapping) else {}
        lines.extend(
            [
                f"- rewrite_mode: `{rewrite.get('mode', '')}`",
                f"- generated_query_count: `{summary.get('generated_query_count', 0)}`",
                f"- retrieval_query_count: `{summary.get('retrieval_query_count', 0)}`",
            ]
        )
        queries = rewrite.get("retrieval_queries", []) if isinstance(rewrite.get("retrieval_queries"), list) else []
        if queries:
            lines.extend(["", "## Retrieval Queries", "", "| id | kind | source | query |", "| --- | --- | --- | --- |"])
            for item in queries:
                if not isinstance(item, Mapping):
                    continue
                query = str(item.get("query", "")).replace("|", "\\|")
                lines.append(
                    f"| `{item.get('id', '')}` | `{item.get('kind', '')}` | `{item.get('source', '')}` | {query} |"
                )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            "| Rank | Score | Similarity | Document | Reasons |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
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


def _answer_abstained(answer: str) -> bool:
    normalized = answer.strip().lower()
    if not normalized:
        return False
    patterns = (
        "cannot answer",
        "can't answer",
        "not enough information",
        "insufficient information",
        "no retrieved evidence",
        "no evidence",
        "i don't know",
        "unable to determine",
        "无法回答",
        "不能回答",
        "没有足够",
        "未检索到",
        "不知道",
    )
    return any(pattern in normalized for pattern in patterns)


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
    diagnostic_class: str | None = None,
    next_commands: Sequence[str] | None = None,
) -> None:
    item = {"severity": severity, "code": code, "message": message}
    if detail:
        item["detail"] = dict(detail)
    if diagnostic_class:
        item["diagnostic_class"] = diagnostic_class
    if next_commands:
        item["next_commands"] = list(next_commands)
    issues.append(item)


def evaluate_answer(
    query_payload: Mapping[str, Any],
    answer: str,
    *,
    expected_terms: Sequence[str] | None = None,
    require_citation: bool = False,
    allow_abstain: bool = False,
    min_cited_evidence_score: float | None = None,
    citation_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a host-generated answer with deterministic offline checks."""

    answer_text = str(answer or "")
    answer_stripped = answer_text.strip()
    expected_input: Any = expected_terms
    if expected_input is not None and not isinstance(expected_input, (str, list)):
        expected_input = list(expected_input)
    expected = _strict_string_list(expected_input, field_name="expected_terms")
    evidence = evidence_from_query_payload(query_payload)
    audit = dict(citation_audit) if isinstance(citation_audit, Mapping) else audit_citations(answer_text, evidence)
    abstained = _answer_abstained(answer_text)
    issues: list[dict[str, Any]] = []

    if not answer_stripped:
        _append_issue(
            issues,
            severity="error",
            code="empty_answer",
            message="answer text is empty",
        )

    audit_issues = audit.get("issues", []) if isinstance(audit.get("issues"), list) else []
    for issue in audit_issues:
        if not isinstance(issue, Mapping):
            continue
        severity = str(issue.get("severity") or "warning")
        code = str(issue.get("code") or "citation_audit_issue")
        if code == "unsupported_uncited_statement" and not evidence and abstained and allow_abstain:
            continue
        if require_citation and code == "missing_citations":
            severity = "error"
        _append_issue(
            issues,
            severity=severity,
            code=code,
            message=str(issue.get("message") or code),
            detail={key: value for key, value in issue.items() if key not in {"severity", "code", "message"}},
        )

    audit_metrics = audit.get("metrics", {}) if isinstance(audit.get("metrics"), Mapping) else {}
    citation_count = int(audit_metrics.get("citation_count", 0) or 0)
    if require_citation and evidence and citation_count == 0 and not any(
        issue.get("code") == "missing_citations" for issue in issues
    ):
        _append_issue(
            issues,
            severity="error",
            code="missing_citations",
            message="answer contains no numeric citations such as [1]",
        )

    if not evidence and answer_stripped and not abstained:
        _append_issue(
            issues,
            severity="error",
            code="answer_without_evidence",
            message="answer provides substantive text even though query output has no evidence",
        )
    if not evidence and allow_abstain and answer_stripped and not abstained:
        _append_issue(
            issues,
            severity="warning",
            code="missing_abstention",
            message="answer did not use an abstention/no-evidence phrasing despite empty evidence",
        )
    if evidence and abstained and not allow_abstain:
        _append_issue(
            issues,
            severity="warning",
            code="unnecessary_abstention",
            message="answer appears to abstain even though retrieved evidence is available",
        )

    answer_lower = answer_text.lower()
    evidence_text = "\n".join(
        [str(item.get("content_preview") or "") for item in evidence if isinstance(item, Mapping)]
        + [_chunk_text(chunk) for chunk in _query_chunks(query_payload)]
    ).lower()
    answer_hits = [term for term in expected if term.lower() in answer_lower]
    evidence_hits = [term for term in expected if term.lower() in evidence_text]
    missing_from_answer = [term for term in expected if term not in answer_hits]
    missing_from_evidence = [term for term in expected if term not in evidence_hits]
    missing_from_both = [term for term in expected if term in missing_from_answer and term in missing_from_evidence]
    if missing_from_answer:
        _append_issue(
            issues,
            severity="warning",
            code="expected_terms_missing_from_answer",
            message="answer is missing expected terms",
            detail={"terms": missing_from_answer},
        )
    if missing_from_both:
        _append_issue(
            issues,
            severity="warning",
            code="expected_terms_missing_from_evidence",
            message="expected terms are absent from both answer and retrieved evidence",
            detail={"terms": missing_from_both},
        )

    cited_ranks = []
    citations = audit.get("citations") if isinstance(audit.get("citations"), Mapping) else {}
    if isinstance(citations.get("cited_ranks"), list):
        cited_ranks = [rank for rank in citations["cited_ranks"] if isinstance(rank, int)]
    evidence_by_rank = _evidence_by_rank(evidence)
    cited_scores = [
        float(evidence_by_rank[rank].get("score"))
        for rank in cited_ranks
        if rank in evidence_by_rank and isinstance(evidence_by_rank[rank].get("score"), (int, float))
    ]
    if min_cited_evidence_score is not None and cited_scores and max(cited_scores) < min_cited_evidence_score:
        _append_issue(
            issues,
            severity="warning",
            code="low_cited_evidence_score",
            message="all cited evidence scores are below the configured threshold",
            detail={"max_cited_evidence_score": max(cited_scores), "min_cited_evidence_score": min_cited_evidence_score},
        )

    status = _severity_status(issues)
    return {
        "ok": status != "FAIL",
        "schema": ANSWER_EVALUATION_REPORT_SCHEMA,
        "status": status,
        "question": query_payload.get("question"),
        "answer": {
            "chars": len(answer_text),
            "preview": _preview(answer_text),
            "abstained": abstained,
        },
        "summary": {
            "evidence_count": len(evidence),
            "citation_count": citation_count,
            "invalid_citation_count": int(audit_metrics.get("invalid_citation_count", 0) or 0),
            "unsupported_uncited_statement_count": int(audit_metrics.get("unsupported_uncited_statement_count", 0) or 0),
            "expected_term_count": len(expected),
            "answer_expected_term_hit_count": len(answer_hits),
            "evidence_expected_term_hit_count": len(evidence_hits),
            "missing_expected_term_count": len(missing_from_answer),
            "cited_evidence_count": len(cited_ranks),
            "max_cited_evidence_score": round(max(cited_scores), 4) if cited_scores else None,
            "abstained": abstained,
            "issue_count": len(issues),
            "errors": sum(1 for issue in issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "expected_terms": {
            "requested": expected,
            "answer_hits": answer_hits,
            "evidence_hits": evidence_hits,
            "missing_from_answer": missing_from_answer,
            "missing_from_evidence": missing_from_evidence,
        },
        "citation_audit": audit,
        "issues": issues,
        "recommendations": [
            "Require numeric citations when host synthesis is expected to quote or summarize retrieved evidence.",
            "Use abstention wording when retrieval returns no evidence or low-quality evidence.",
            "Review unsupported uncited statements before exposing generated answers to end users.",
        ],
    }


def render_answer_evaluation_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown answer evaluation report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    answer = report.get("answer", {}) if isinstance(report.get("answer"), Mapping) else {}
    lines = [
        "# RAGFlow Answer Evaluation",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- evidence_count: `{summary.get('evidence_count', 0)}`",
        f"- citation_count: `{summary.get('citation_count', 0)}`",
        f"- invalid_citation_count: `{summary.get('invalid_citation_count', 0)}`",
        f"- unsupported_uncited_statement_count: `{summary.get('unsupported_uncited_statement_count', 0)}`",
        f"- missing_expected_term_count: `{summary.get('missing_expected_term_count', 0)}`",
        f"- abstained: `{str(bool(answer.get('abstained'))).lower()}`",
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
    expected_terms = report.get("expected_terms", {}) if isinstance(report.get("expected_terms"), Mapping) else {}
    requested = expected_terms.get("requested", []) if isinstance(expected_terms.get("requested"), list) else []
    if requested:
        lines.extend(["", "## Expected Terms", ""])
        lines.append("- requested: " + ", ".join(f"`{term}`" for term in requested))
        lines.append(
            "- answer_hits: "
            + (", ".join(f"`{term}`" for term in expected_terms.get("answer_hits", [])) or "`none`")
        )
    preview = answer.get("preview")
    if isinstance(preview, str) and preview:
        lines.extend(["", "## Answer Preview", "", preview])
    return "\n".join(lines) + "\n"


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


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _payload_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = payload.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _payload_latency_ms(payload: Mapping[str, Any]) -> float | None:
    metadata = _payload_metadata(payload)
    trace = payload.get("trace") if isinstance(payload.get("trace"), Mapping) else {}
    timings = trace.get("timings_ms") if isinstance(trace.get("timings_ms"), Mapping) else {}
    for mapping in (metadata, timings, payload):
        if not isinstance(mapping, Mapping):
            continue
        for key in ("retrieval_ms", "duration_ms", "latency_ms", "total"):
            value = _as_float(mapping.get(key))
            if value is not None:
                return value
    return None


def _top_chunk_summary(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    chunks = _query_chunks(payload)
    if not chunks:
        return None
    chunk = chunks[0]
    return {
        "identity": _chunk_identity(chunk),
        "stable_hash": stable_chunk_hash(chunk),
        "document_name": chunk.get("document_name"),
        "document_id": chunk.get("document_id"),
        "chunk_id": _chunk_field(chunk, ("chunk_id", "id", "source_chunk_id")),
        "similarity": _as_float(chunk.get("similarity")),
        "content_preview": _preview(_chunk_text(chunk)),
    }


def _query_output_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    chunks = _query_chunks(payload)
    top_chunk = _top_chunk_summary(payload)
    metadata = _payload_metadata(payload)
    return {
        "question": payload.get("question"),
        "dataset_ids": payload.get("dataset_ids", []),
        "mode": payload.get("mode"),
        "rewrite": metadata.get("rewrite"),
        "fusion": metadata.get("fusion"),
        "chunk_count": len(chunks),
        "zero_result": len(chunks) == 0,
        "top_chunk": top_chunk,
        "top_similarity": top_chunk.get("similarity") if isinstance(top_chunk, Mapping) else None,
        "latency_ms": _payload_latency_ms(payload),
    }


def _paired_query_outputs(
    baseline_payloads: Sequence[Mapping[str, Any]],
    candidate_payloads: Sequence[Mapping[str, Any]],
    issues: list[dict[str, Any]],
) -> list[tuple[int, Mapping[str, Any], Mapping[str, Any]]]:
    pair_count = min(len(baseline_payloads), len(candidate_payloads))
    if len(baseline_payloads) != len(candidate_payloads):
        _append_issue(
            issues,
            severity="warning",
            code="query_output_count_mismatch",
            message="baseline and candidate output counts differ; extra outputs are ignored",
            detail={"baseline_count": len(baseline_payloads), "candidate_count": len(candidate_payloads)},
        )
    if pair_count == 0:
        _append_issue(
            issues,
            severity="error",
            code="query_outputs_missing",
            message="at least one baseline and one candidate query output are required",
        )
        return []
    return [(index, baseline_payloads[index], candidate_payloads[index]) for index in range(pair_count)]


def query_cross_language_ab_report(
    baseline_payloads: Sequence[Mapping[str, Any]],
    candidate_payloads: Sequence[Mapping[str, Any]],
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
    min_top1_stability: float = 0.8,
    max_examples: int = 10,
) -> dict[str, Any]:
    """Compare saved baseline and cross-language query outputs without live retrieval."""

    issues: list[dict[str, Any]] = []
    if not 0.0 <= min_top1_stability <= 1.0:
        _append_issue(
            issues,
            severity="error",
            code="min_top1_stability_invalid",
            message="min_top1_stability must be between 0 and 1",
        )
    if max_examples <= 0:
        _append_issue(
            issues,
            severity="error",
            code="max_examples_invalid",
            message="max_examples must be positive",
        )
        max_examples = 1

    pairs = _paired_query_outputs(baseline_payloads, candidate_payloads, issues)
    cases: list[dict[str, Any]] = []
    chunk_deltas: list[float] = []
    similarity_deltas: list[float] = []
    latency_deltas: list[float] = []
    comparable_top1 = 0
    stable_top1 = 0

    for index, baseline_payload, candidate_payload in pairs:
        baseline = _query_output_summary(baseline_payload)
        candidate = _query_output_summary(candidate_payload)
        baseline_question = str(baseline.get("question") or "")
        candidate_question = str(candidate.get("question") or "")
        if baseline_question and candidate_question and baseline_question != candidate_question:
            _append_issue(
                issues,
                severity="info",
                code="question_text_changed",
                message="baseline and candidate question text differ",
                detail={"case_index": index, "baseline_question": baseline_question, "candidate_question": candidate_question},
            )
        baseline_top = baseline.get("top_chunk") if isinstance(baseline.get("top_chunk"), Mapping) else None
        candidate_top = candidate.get("top_chunk") if isinstance(candidate.get("top_chunk"), Mapping) else None
        top1_stable = None
        if baseline_top and candidate_top:
            comparable_top1 += 1
            top1_stable = baseline_top.get("identity") == candidate_top.get("identity")
            if top1_stable:
                stable_top1 += 1
        chunk_delta = int(candidate["chunk_count"]) - int(baseline["chunk_count"])
        chunk_deltas.append(float(chunk_delta))
        baseline_similarity = baseline.get("top_similarity")
        candidate_similarity = candidate.get("top_similarity")
        similarity_delta = None
        if isinstance(baseline_similarity, (int, float)) and isinstance(candidate_similarity, (int, float)):
            similarity_delta = round(float(candidate_similarity) - float(baseline_similarity), 4)
            similarity_deltas.append(similarity_delta)
        baseline_latency = baseline.get("latency_ms")
        candidate_latency = candidate.get("latency_ms")
        latency_delta = None
        if isinstance(baseline_latency, (int, float)) and isinstance(candidate_latency, (int, float)):
            latency_delta = round(float(candidate_latency) - float(baseline_latency), 4)
            latency_deltas.append(latency_delta)
        if not baseline["zero_result"] and candidate["zero_result"]:
            _append_issue(
                issues,
                severity="warning",
                code="candidate_zero_result_regression",
                message="candidate output returned zero chunks where baseline had evidence",
                detail={"case_index": index, "question": baseline_question or candidate_question},
            )
        elif baseline["zero_result"] and not candidate["zero_result"]:
            _append_issue(
                issues,
                severity="info",
                code="candidate_zero_result_improvement",
                message="candidate output recovered chunks where baseline returned none",
                detail={"case_index": index, "question": baseline_question or candidate_question},
            )
        cases.append(
            {
                "id": f"case-{index + 1}",
                "question": baseline_question or candidate_question,
                "baseline": baseline,
                "candidate": candidate,
                "delta": {
                    "chunk_count": chunk_delta,
                    "top_similarity": similarity_delta,
                    "latency_ms": latency_delta,
                },
                "top1_stable": top1_stable,
            }
        )

    case_count = len(cases)
    baseline_zero_count = sum(1 for case in cases if case["baseline"]["zero_result"])
    candidate_zero_count = sum(1 for case in cases if case["candidate"]["zero_result"])
    baseline_chunk_counts = [float(case["baseline"]["chunk_count"]) for case in cases]
    candidate_chunk_counts = [float(case["candidate"]["chunk_count"]) for case in cases]
    baseline_similarities = [
        float(case["baseline"]["top_similarity"])
        for case in cases
        if isinstance(case["baseline"].get("top_similarity"), (int, float))
    ]
    candidate_similarities = [
        float(case["candidate"]["top_similarity"])
        for case in cases
        if isinstance(case["candidate"].get("top_similarity"), (int, float))
    ]
    baseline_latencies = [
        float(case["baseline"]["latency_ms"])
        for case in cases
        if isinstance(case["baseline"].get("latency_ms"), (int, float))
    ]
    candidate_latencies = [
        float(case["candidate"]["latency_ms"])
        for case in cases
        if isinstance(case["candidate"].get("latency_ms"), (int, float))
    ]
    top1_stability_rate = _rate(stable_top1, comparable_top1)
    baseline_zero_rate = _rate(baseline_zero_count, case_count)
    candidate_zero_rate = _rate(candidate_zero_count, case_count)
    avg_baseline_chunks = _mean(baseline_chunk_counts)
    avg_candidate_chunks = _mean(candidate_chunk_counts)
    avg_baseline_similarity = _mean(baseline_similarities)
    avg_candidate_similarity = _mean(candidate_similarities)
    avg_baseline_latency = _mean(baseline_latencies)
    avg_candidate_latency = _mean(candidate_latencies)

    if comparable_top1 and top1_stability_rate < min_top1_stability:
        _append_issue(
            issues,
            severity="warning",
            code="top1_stability_below_threshold",
            message="candidate top-1 evidence changed more often than the configured threshold allows",
            detail={"top1_stability_rate": top1_stability_rate, "min_top1_stability": min_top1_stability},
        )
    if candidate_zero_rate > baseline_zero_rate:
        _append_issue(
            issues,
            severity="warning",
            code="zero_result_rate_regression",
            message="candidate zero-result rate is higher than baseline",
            detail={"baseline_zero_result_rate": baseline_zero_rate, "candidate_zero_result_rate": candidate_zero_rate},
        )
    if avg_candidate_chunks + 0.5 < avg_baseline_chunks:
        _append_issue(
            issues,
            severity="warning",
            code="average_chunk_count_drop",
            message="candidate average chunk count dropped versus baseline",
            detail={"baseline_average_chunk_count": avg_baseline_chunks, "candidate_average_chunk_count": avg_candidate_chunks},
        )
    if similarity_deltas and _mean(similarity_deltas) < -0.05:
        _append_issue(
            issues,
            severity="warning",
            code="top_similarity_regression",
            message="candidate top similarity decreased versus baseline",
            detail={"average_top_similarity_delta": _mean(similarity_deltas)},
        )
    if latency_deltas and _mean(latency_deltas) > 0:
        _append_issue(
            issues,
            severity="info",
            code="latency_increase",
            message="candidate average latency increased versus baseline",
            detail={"average_latency_delta_ms": _mean(latency_deltas)},
        )

    examples = [
        case
        for case in cases
        if case.get("top1_stable") is False
        or case["delta"].get("chunk_count")
        or (isinstance(case["delta"].get("top_similarity"), (int, float)) and abs(float(case["delta"]["top_similarity"])) >= 0.05)
    ][:max_examples]
    status = _severity_status(issues)
    return {
        "ok": status != "FAIL",
        "schema": QUERY_CROSS_LANGUAGE_AB_REPORT_SCHEMA,
        "status": status,
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "summary": {
            "case_count": case_count,
            "baseline_zero_result_rate": baseline_zero_rate,
            "candidate_zero_result_rate": candidate_zero_rate,
            "zero_result_rate_delta": round(candidate_zero_rate - baseline_zero_rate, 4),
            "baseline_average_chunk_count": avg_baseline_chunks,
            "candidate_average_chunk_count": avg_candidate_chunks,
            "average_chunk_count_delta": round(avg_candidate_chunks - avg_baseline_chunks, 4),
            "top1_comparable_count": comparable_top1,
            "top1_stable_count": stable_top1,
            "top1_stability_rate": top1_stability_rate,
            "baseline_average_top_similarity": avg_baseline_similarity,
            "candidate_average_top_similarity": avg_candidate_similarity,
            "average_top_similarity_delta": _mean(similarity_deltas),
            "baseline_average_latency_ms": avg_baseline_latency,
            "candidate_average_latency_ms": avg_candidate_latency,
            "average_latency_delta_ms": _mean(latency_deltas),
            "issue_count": len(issues),
            "errors": sum(1 for issue in issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "cases": cases,
        "examples": examples,
        "issues": issues,
        "recommendations": [
            "Reject cross-language or retrieval-setting changes that increase zero-result rate without a benchmark-backed reason.",
            "Investigate top-1 changes before enabling translated or expanded queries by default.",
            "Use benchmark gates when moving from saved-output A/B reports to live retrieval settings.",
        ],
    }


def render_query_cross_language_ab_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for saved-output cross-language A/B checks."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Cross-Language A/B Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- baseline: `{report.get('baseline_label', 'baseline')}`",
        f"- candidate: `{report.get('candidate_label', 'candidate')}`",
        f"- cases: `{summary.get('case_count', 0)}`",
        f"- zero_result_rate_delta: `{summary.get('zero_result_rate_delta', 0)}`",
        f"- average_chunk_count_delta: `{summary.get('average_chunk_count_delta', 0)}`",
        f"- top1_stability_rate: `{summary.get('top1_stability_rate', 0)}`",
        f"- average_top_similarity_delta: `{summary.get('average_top_similarity_delta', 0)}`",
        f"- average_latency_delta_ms: `{summary.get('average_latency_delta_ms', 0)}`",
        "",
        "## Examples",
        "",
    ]
    examples = report.get("examples", []) if isinstance(report.get("examples"), list) else []
    if not examples:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| case | chunks delta | top-1 stable | similarity delta | latency delta ms | question |",
                "| --- | ---: | --- | ---: | ---: | --- |",
            ]
        )
        for case in examples:
            if not isinstance(case, Mapping):
                continue
            delta = case.get("delta") if isinstance(case.get("delta"), Mapping) else {}
            question = str(case.get("question", "")).replace("|", "\\|")
            lines.append(
                "| {case_id} | `{chunk_delta}` | `{stable}` | `{similarity_delta}` | `{latency_delta}` | {question} |".format(
                    case_id=case.get("id", ""),
                    chunk_delta=delta.get("chunk_count", ""),
                    stable=case.get("top1_stable"),
                    similarity_delta=delta.get("top_similarity", ""),
                    latency_delta=delta.get("latency_ms", ""),
                    question=question,
                )
            )
    lines.extend(["", "## Issues", ""])
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


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


def _resolve_relative_path(path: str, *, base_dir: Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return str(candidate)


def load_fusion_test_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load offline fusion fixture cases and resolve query output paths."""

    case_path = Path(path)
    try:
        data = json.loads(case_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"fusion test cases file not found: {case_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"fusion test cases file is not valid JSON: {case_path}") from exc

    raw_cases = data.get("cases") if isinstance(data, Mapping) else data
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("fusion test cases must be a non-empty list or object with cases")

    cases: list[dict[str, Any]] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, Mapping):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = str(item.get("id") or f"case-{index + 1}").strip()
        query_outputs = _strict_string_list(
            item.get("query_outputs", item.get("query_output")),
            field_name=f"cases[{index}].query_outputs",
        )
        if not query_outputs:
            raise ValueError(f"cases[{index}].query_outputs is required")
        case: dict[str, Any] = {
            "id": case_id,
            "query_outputs": [
                _resolve_relative_path(output, base_dir=case_path.parent)
                for output in query_outputs
            ],
            "expected_terms": _strict_string_list(
                item.get("expected_terms", item.get("expected_term")),
                field_name=f"cases[{index}].expected_terms",
            ),
            "expected_chunks": _strict_string_list(
                item.get("expected_chunks", item.get("expected_chunk")),
                field_name=f"cases[{index}].expected_chunks",
            ),
        }
        for key in ("question", "expected_top_chunk", "description"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                case[key] = value.strip()
        for key in ("top_k", "rrf_k", "max_per_source", "min_source_count", "min_result_count"):
            if key in item:
                case[key] = _positive_int_value(
                    item.get(key),
                    field_name=f"cases[{index}].{key}",
                    minimum=0 if key == "max_per_source" else 1,
                )
        metadata = item.get("metadata")
        if isinstance(metadata, Mapping):
            case["metadata"] = dict(metadata)
        elif metadata is not None:
            raise ValueError(f"cases[{index}].metadata must be an object")
        cases.append(case)
    return cases


def _read_query_output_payload(path: str | Path) -> dict[str, Any]:
    payload_path = Path(path)
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"query output file not found: {payload_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"query output file is not valid JSON: {payload_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"query output must be a JSON object: {payload_path}")
    return payload


def _fusion_result_aliases(result: Mapping[str, Any]) -> set[str]:
    aliases = _chunk_aliases(result)
    aliases.update(_reference_variants(result.get("identity")))
    return aliases


def _case_query_payloads(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    payloads = case.get("query_payloads")
    if isinstance(payloads, list):
        if not all(isinstance(payload, Mapping) for payload in payloads):
            raise ValueError(f"fusion test case {case.get('id', '')} query_payloads must contain objects")
        return [dict(payload) for payload in payloads]

    query_outputs = _strict_string_list(
        case.get("query_outputs", case.get("query_output")),
        field_name=f"fusion test case {case.get('id', '')} query_outputs",
    )
    if not query_outputs:
        raise ValueError(f"fusion test case {case.get('id', '')} requires query_outputs")
    return [_read_query_output_payload(path) for path in query_outputs]


def run_fusion_tests(
    cases: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 10,
    rrf_k: int = 60,
    max_per_source: int | None = None,
) -> dict[str, Any]:
    """Run offline reciprocal-rank-fusion fixture checks."""

    if not cases:
        raise ValueError("fusion test cases must be non-empty")
    default_top_k = _positive_int_value(top_k, field_name="top_k") or 10
    default_rrf_k = _positive_int_value(rrf_k, field_name="rrf_k") or 60
    default_max_per_source = (
        _positive_int_value(max_per_source, field_name="max_per_source", minimum=0)
        if max_per_source is not None
        else None
    )

    case_results: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    passed = 0
    review_count = 0

    for index, case in enumerate(cases):
        case_id = str(case.get("id") or f"case-{index + 1}")
        case_top_k = _positive_int_value(
            case.get("top_k"),
            field_name=f"{case_id}.top_k",
            default=default_top_k,
        ) or default_top_k
        case_rrf_k = _positive_int_value(
            case.get("rrf_k"),
            field_name=f"{case_id}.rrf_k",
            default=default_rrf_k,
        ) or default_rrf_k
        case_max_per_source = (
            _positive_int_value(
                case.get("max_per_source"),
                field_name=f"{case_id}.max_per_source",
                minimum=0,
            )
            if case.get("max_per_source") is not None
            else default_max_per_source
        )
        payloads = _case_query_payloads(case)
        fusion = query_fusion_report(
            payloads,
            top_k=case_top_k,
            rrf_k=case_rrf_k,
            max_per_source=case_max_per_source,
        )
        results = [item for item in fusion.get("results", []) if isinstance(item, Mapping)]
        result_indices = list(range(len(results)))
        aliases_by_index = [_fusion_result_aliases(result) for result in results]
        texts_by_index = [_chunk_text(result) for result in results]
        expected_terms = _strict_string_list(
            case.get("expected_terms"),
            field_name=f"{case_id}.expected_terms",
        )
        expected_chunks = _strict_string_list(
            case.get("expected_chunks"),
            field_name=f"{case_id}.expected_chunks",
        )
        expected_top_chunk = case.get("expected_top_chunk")
        min_source_count = _positive_int_value(
            case.get("min_source_count"),
            field_name=f"{case_id}.min_source_count",
            default=None,
        )
        min_result_count = _positive_int_value(
            case.get("min_result_count"),
            field_name=f"{case_id}.min_result_count",
            default=None,
        )
        term_hits = _expected_term_hits_for_indices(result_indices, texts_by_index, expected_terms)
        chunk_hits = _expected_chunk_hits_for_indices(result_indices, aliases_by_index, expected_chunks)
        top_chunk_hits = (
            _expected_chunk_hits_for_indices([0], aliases_by_index, [str(expected_top_chunk)])
            if expected_top_chunk and results
            else []
        )
        missing_terms = [term for term in expected_terms if term not in term_hits]
        missing_chunks = [chunk for chunk in expected_chunks if chunk not in chunk_hits]
        top_result = results[0] if results else {}
        top_source_count = (
            int(top_result.get("source_count", 0))
            if isinstance(top_result.get("source_count", 0), int)
            else 0
        )

        case_issues: list[dict[str, Any]] = []
        if not fusion.get("ok", False):
            _append_issue(
                case_issues,
                severity="error",
                code="fusion_report_failed",
                message="fusion report did not pass",
                detail={"status": fusion.get("status")},
            )
        if expected_top_chunk and not top_chunk_hits:
            _append_issue(
                case_issues,
                severity="error",
                code="top_chunk_mismatch",
                message="top fused result did not match expected_top_chunk",
                detail={
                    "expected_top_chunk": expected_top_chunk,
                    "actual_top_identity": top_result.get("identity") if isinstance(top_result, Mapping) else None,
                },
            )
        if missing_chunks:
            _append_issue(
                case_issues,
                severity="error",
                code="missing_expected_chunks",
                message="fused top-k results do not contain all expected chunks",
                detail={"missing_chunks": missing_chunks},
            )
        if missing_terms:
            _append_issue(
                case_issues,
                severity="error",
                code="missing_expected_terms",
                message="fused top-k results do not contain all expected terms",
                detail={"missing_terms": missing_terms},
            )
        if min_source_count is not None and top_source_count < min_source_count:
            _append_issue(
                case_issues,
                severity="error",
                code="low_top_source_count",
                message="top fused result has fewer source contributions than required",
                detail={"top_source_count": top_source_count, "min_source_count": min_source_count},
            )
        if min_result_count is not None and len(results) < min_result_count:
            _append_issue(
                case_issues,
                severity="error",
                code="low_result_count",
                message="fusion produced fewer results than required",
                detail={"result_count": len(results), "min_result_count": min_result_count},
            )

        case_passed = not any(issue["severity"] == "error" for issue in case_issues)
        if case_passed:
            passed += 1
        if fusion.get("status") == "REVIEW":
            review_count += 1
        for issue in case_issues:
            issue_with_case = dict(issue)
            issue_with_case["case_id"] = case_id
            all_issues.append(issue_with_case)
        case_results.append(
            {
                "id": case_id,
                "description": case.get("description"),
                "passed": case_passed,
                "status": "FAIL" if not case_passed else fusion.get("status", "PASS"),
                "question": case.get("question") or fusion.get("question"),
                "query_outputs": list(case.get("query_outputs", [])) if isinstance(case.get("query_outputs"), list) else [],
                "parameters": {
                    "top_k": case_top_k,
                    "rrf_k": case_rrf_k,
                    "max_per_source": case_max_per_source,
                },
                "expected": {
                    "top_chunk": expected_top_chunk,
                    "chunks": expected_chunks,
                    "terms": expected_terms,
                    "min_source_count": min_source_count,
                    "min_result_count": min_result_count,
                },
                "hits": {
                    "top_chunk": top_chunk_hits,
                    "chunks": chunk_hits,
                    "terms": term_hits,
                    "missing_chunks": missing_chunks,
                    "missing_terms": missing_terms,
                },
                "summary": {
                    "source_count": fusion.get("summary", {}).get("source_count", 0)
                    if isinstance(fusion.get("summary"), Mapping)
                    else 0,
                    "result_count": len(results),
                    "top_identity": top_result.get("identity") if isinstance(top_result, Mapping) else None,
                    "top_chunk_id": top_result.get("chunk_id") if isinstance(top_result, Mapping) else None,
                    "top_source_count": top_source_count,
                    "deduplicated_chunk_count": fusion.get("summary", {}).get("deduplicated_chunk_count", 0)
                    if isinstance(fusion.get("summary"), Mapping)
                    else 0,
                },
                "issues": case_issues,
                "fusion": fusion,
            }
        )

    total = len(case_results)
    failed = total - passed
    status = "FAIL" if failed else "REVIEW" if review_count else "PASS"
    return {
        "ok": failed == 0,
        "schema": FUSION_TEST_REPORT_SCHEMA,
        "status": status,
        "parameters": {
            "top_k": default_top_k,
            "rrf_k": default_rrf_k,
            "max_per_source": default_max_per_source,
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": _rate(passed, total),
            "review_count": review_count,
            "issue_count": len(all_issues),
            "errors": sum(1 for issue in all_issues if issue["severity"] == "error"),
            "warnings": sum(1 for issue in all_issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in all_issues if issue["severity"] == "info"),
        },
        "cases": case_results,
        "issues": all_issues,
        "recommendations": [
            "Keep fusion-test fixtures offline and version their saved query outputs with the cases file.",
            "Add benchmark gates before using fusion defaults for production KB routing changes.",
        ],
    }


def render_query_fusion_test_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for offline fusion fixture tests."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Fusion Test Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- status: `{report.get('status', '')}`",
        f"- total: `{summary.get('total', 0)}`",
        f"- passed: `{summary.get('passed', 0)}`",
        f"- failed: `{summary.get('failed', 0)}`",
        f"- pass_rate: `{summary.get('pass_rate', 0)}`",
        "",
        "## Cases",
        "",
    ]
    cases = report.get("cases", []) if isinstance(report.get("cases"), list) else []
    if not cases:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| id | status | top result | source count | missing chunks | missing terms |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for case in cases:
            if not isinstance(case, Mapping):
                continue
            case_summary = case.get("summary", {}) if isinstance(case.get("summary"), Mapping) else {}
            hits = case.get("hits", {}) if isinstance(case.get("hits"), Mapping) else {}
            lines.append(
                "| `{id}` | {status} | `{top}` | {sources} | {chunks} | {terms} |".format(
                    id=case.get("id", ""),
                    status="passed" if case.get("passed") else "failed",
                    top=case_summary.get("top_identity") or "-",
                    sources=case_summary.get("top_source_count", 0),
                    chunks=", ".join(str(item) for item in hits.get("missing_chunks", []))
                    if isinstance(hits.get("missing_chunks"), list)
                    else "",
                    terms=", ".join(str(item) for item in hits.get("missing_terms", []))
                    if isinstance(hits.get("missing_terms"), list)
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
                lines.append(
                    f"- `{issue.get('case_id', '')}` `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}"
                )
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


def _normalized_query_label(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_") or None


def _normalized_query_labels(values: Sequence[str] | None) -> set[str]:
    labels: set[str] = set()
    for value in values or []:
        label = _normalized_query_label(value)
        if label:
            labels.add(label)
    return labels


def _modality_label(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().casefold()
    normalized = _normalized_query_label(text) or ""
    if "mixed" in normalized or "multimodal" in normalized:
        return "mixed"
    if text.startswith("image/") or any(token in normalized for token in ("image", "visual", "figure", "diagram", "screenshot")):
        return "image"
    if "table" in normalized:
        return "table"
    if text.startswith("text/") or normalized in {"text", "markdown", "md", "txt", "document"}:
        return "text"
    return normalized if normalized in {"image", "table", "text", "mixed"} else None


def _expected_modality_labels(values: Sequence[str] | None) -> set[str]:
    labels: set[str] = set()
    for value in values or []:
        modality = _modality_label(value)
        if modality == "mixed":
            labels.update({"mixed", "table", "image"})
        elif modality:
            labels.add(modality)
    return labels


def _chunk_mapping_values(chunk: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    values = [chunk[key] for key in keys if key in chunk]
    raw = chunk.get("raw")
    if isinstance(raw, Mapping):
        values.extend(raw[key] for key in keys if key in raw)
    metadata = chunk.get("metadata")
    if isinstance(metadata, Mapping):
        values.extend(metadata[key] for key in keys if key in metadata)
    if isinstance(raw, Mapping):
        raw_metadata = raw.get("metadata")
        if isinstance(raw_metadata, Mapping):
            values.extend(raw_metadata[key] for key in keys if key in raw_metadata)
    return values


def _diagnostic_chunk_modality(chunk: Mapping[str, Any]) -> str:
    for value in _chunk_mapping_values(
        chunk,
        (
            "modality",
            "chunk_modality",
            "document_modality",
            "media_type",
            "asset_type",
            "document_type",
            "doc_type",
            "mime_type",
            "content_type",
            "type",
        ),
    ):
        modality = _modality_label(value)
        if modality:
            return modality
    document_name = str(chunk.get("document_name") or chunk.get("docnm_kwd") or "").casefold()
    if document_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")):
        return "image"
    if "<table" in str(chunk.get("content") or chunk.get("text") or "").casefold():
        return "table"
    if document_name.endswith((".md", ".markdown", ".txt")):
        return "text"
    return "unknown"


def _diagnostic_modality_distribution(chunks: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        modality = _diagnostic_chunk_modality(chunk)
        counts[modality] = counts.get(modality, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _diagnostic_chunk_tags(chunk: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    for value in _chunk_mapping_values(chunk, ("tags", "tag", "tag_names", "tag_name", "tag_ids", "tag_id")):
        if isinstance(value, str):
            label = _normalized_query_label(value)
            if label:
                tags.add(label)
        elif isinstance(value, Mapping):
            for key in ("name", "label", "value", "id"):
                label = _normalized_query_label(value.get(key))
                if label:
                    tags.add(label)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, str):
                    label = _normalized_query_label(item)
                    if label:
                        tags.add(label)
                elif isinstance(item, Mapping):
                    for key in ("name", "label", "value", "id"):
                        label = _normalized_query_label(item.get(key))
                        if label:
                            tags.add(label)
    return tags


def _document_matches(chunks: Sequence[Mapping[str, Any]], expected_documents: Sequence[str] | None) -> tuple[set[str], set[str]]:
    expected = {str(item).strip().casefold() for item in expected_documents or [] if str(item).strip()}
    if not expected:
        return set(), set()
    document_values = {
        str(chunk.get(key)).strip().casefold()
        for chunk in chunks
        for key in ("document_name", "document_id", "docnm_kwd", "doc_id")
        if isinstance(chunk.get(key), str) and str(chunk.get(key)).strip()
    }
    matched = {
        expected_document
        for expected_document in expected
        if any(expected_document == value or expected_document in value for value in document_values)
    }
    return matched, expected - matched


def _diagnostic_issue_classes(issues: Sequence[Mapping[str, Any]]) -> list[str]:
    classes = {
        str(issue.get("diagnostic_class"))
        for issue in issues
        if isinstance(issue.get("diagnostic_class"), str) and issue.get("diagnostic_class")
    }
    return [item for item in QUERY_DIAGNOSTIC_CLASS_ORDER if item in classes] + sorted(
        classes - set(QUERY_DIAGNOSTIC_CLASS_ORDER)
    )


def _diagnostic_next_commands(classes: Sequence[str]) -> list[dict[str, Any]]:
    items = []
    for diagnostic_class in classes:
        commands = QUERY_DIAGNOSTIC_NEXT_COMMANDS.get(diagnostic_class)
        if commands:
            items.append({"diagnostic_class": diagnostic_class, "commands": list(commands)})
    return items


def diagnose_query_result(
    query_payload: Mapping[str, Any],
    *,
    trace: Mapping[str, Any] | None = None,
    citation_audit: Mapping[str, Any] | None = None,
    expected_terms: Sequence[str] | None = None,
    expected_modalities: Sequence[str] | None = None,
    expected_documents: Sequence[str] | None = None,
    expected_dataset_ids: Sequence[str] | None = None,
    expected_tags: Sequence[str] | None = None,
    allowed_tags: Sequence[str] | None = None,
    min_similarity: float = 0.15,
    min_evidence_score: float = 0.2,
) -> dict[str, Any]:
    """Diagnose weak retrieval, routing, evidence, and citation symptoms offline."""

    chunks = [item for item in query_payload.get("chunks", []) if isinstance(item, Mapping)]
    evidence = evidence_from_query_payload(query_payload)
    expected_modality_set = _expected_modality_labels(expected_modalities)
    issues: list[dict[str, Any]] = []
    if not chunks:
        _append_issue(
            issues,
            severity="error",
            code="zero_chunks",
            message="query returned zero chunks",
            diagnostic_class="no_result",
            next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["no_result"],
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
            diagnostic_class="low_similarity",
            next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["low_similarity"],
        )

    top_evidence_score = _as_float(evidence[0].get("score")) if evidence else None
    if top_evidence_score is not None and top_evidence_score < min_evidence_score:
        _append_issue(
            issues,
            severity="warning",
            code="low_evidence_score",
            message="top evidence score is below threshold",
            detail={"top_evidence_score": top_evidence_score, "min_evidence_score": min_evidence_score},
            diagnostic_class="low_similarity",
            next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["low_similarity"],
        )

    expected = [term for term in (expected_terms or []) if str(term).strip()]
    if expected:
        combined = "\n".join(str(chunk.get("content") or "") for chunk in chunks).lower()
        missing = [term for term in expected if term.lower() not in combined]
        if missing:
            diagnostic_class = "table_fragment" if "table" in expected_modality_set else None
            _append_issue(
                issues,
                severity="warning",
                code="missing_expected_terms",
                message="retrieved chunks do not contain all expected terms",
                detail={"missing_terms": missing},
                diagnostic_class=diagnostic_class,
                next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS.get(diagnostic_class or "", ()),
            )

    if chunks and expected_modality_set:
        modality_distribution = _diagnostic_modality_distribution(chunks)
        retrieved_modalities = set(modality_distribution)
        expected_without_mixed = expected_modality_set - {"mixed"}
        if expected_without_mixed and not (retrieved_modalities & expected_without_mixed):
            _append_issue(
                issues,
                severity="warning",
                code="wrong_modality",
                message="retrieved chunks do not include the expected evidence modality",
                detail={
                    "expected_modalities": sorted(expected_modality_set),
                    "retrieved_modalities": modality_distribution,
                },
                diagnostic_class="wrong_modality",
                next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["wrong_modality"],
            )
        if "image" in expected_modality_set and modality_distribution.get("image", 0) == 0:
            _append_issue(
                issues,
                severity="warning",
                code="missing_image_evidence",
                message="expected visual evidence but retrieved chunks contain no image modality",
                detail={"retrieved_modalities": modality_distribution},
                diagnostic_class="image_evidence",
                next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["image_evidence"],
            )

    matched_documents, missing_documents = _document_matches(chunks, expected_documents)
    if missing_documents:
        diagnostic_class = "image_evidence" if "image" in expected_modality_set else "table_fragment" if "table" in expected_modality_set else None
        _append_issue(
            issues,
            severity="warning",
            code="missing_expected_documents",
            message="retrieved chunks do not include all expected documents",
            detail={
                "matched_documents": sorted(matched_documents),
                "missing_documents": sorted(missing_documents),
            },
            diagnostic_class=diagnostic_class,
            next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS.get(diagnostic_class or "", ()),
        )

    expected_dataset_set = {str(item).strip() for item in expected_dataset_ids or [] if str(item).strip()}
    payload_dataset_set = {
        str(item).strip()
        for item in query_payload.get("dataset_ids", [])
        if str(item).strip()
    } if isinstance(query_payload.get("dataset_ids", []), list) else set()
    if expected_dataset_set and not (payload_dataset_set & expected_dataset_set):
        _append_issue(
            issues,
            severity="warning",
            code="route_mismatch",
            message="query output dataset IDs do not include the expected route dataset",
            detail={
                "expected_dataset_ids": sorted(expected_dataset_set),
                "actual_dataset_ids": sorted(payload_dataset_set),
            },
            diagnostic_class="route_mismatch",
            next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["route_mismatch"],
        )

    allowed_tag_set = _normalized_query_labels(allowed_tags)
    expected_tag_set = _normalized_query_labels(expected_tags)
    allowed_tag_set.update(expected_tag_set)
    if chunks and allowed_tag_set:
        retrieved_tags = set().union(*[_diagnostic_chunk_tags(chunk) for chunk in chunks])
        unexpected_tags = retrieved_tags - allowed_tag_set
        if unexpected_tags:
            _append_issue(
                issues,
                severity="warning",
                code="retrieval_pollution",
                message="retrieved chunks include tags outside the expected or allowed scope",
                detail={
                    "allowed_tags": sorted(allowed_tag_set),
                    "unexpected_tags": sorted(unexpected_tags),
                },
                diagnostic_class="pollution",
                next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["pollution"],
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
                    diagnostic_class="route_mismatch",
                    next_commands=QUERY_DIAGNOSTIC_NEXT_COMMANDS["route_mismatch"],
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

    issue_classes = _diagnostic_issue_classes(issues)
    next_commands = _diagnostic_next_commands(issue_classes)
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
            "diagnostic_class_count": len(issue_classes),
        },
        "question": query_payload.get("question"),
        "mode": query_payload.get("mode"),
        "dataset_ids": query_payload.get("dataset_ids", []),
        "thresholds": {
            "min_similarity": min_similarity,
            "min_evidence_score": min_evidence_score,
        },
        "issue_classes": issue_classes,
        "next_commands": next_commands,
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
            diagnostic_class = issue.get("diagnostic_class")
            class_text = f" `{diagnostic_class}`" if diagnostic_class else ""
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`{class_text}: {issue.get('message')}")
    next_commands = report.get("next_commands", [])
    if isinstance(next_commands, list):
        lines.extend(["", "## Next Commands", ""])
        if not next_commands:
            lines.append("- None")
        else:
            for item in next_commands:
                if not isinstance(item, Mapping):
                    continue
                diagnostic_class = item.get("diagnostic_class", "")
                commands = item.get("commands", [])
                if not isinstance(commands, list):
                    continue
                for command in commands:
                    lines.append(f"- `{diagnostic_class}`: `{command}`")
    return "\n".join(lines) + "\n"
