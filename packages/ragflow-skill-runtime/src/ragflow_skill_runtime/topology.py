"""Advisory KB topology helpers for non-mutating build workflows."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .handoff import HandoffError, RAGFLOW_INGEST_PLAN_SCHEMA, load_ragflow_ingest_plan
from .kb_build import BuildDocument
from .manifests import KbManifest, ManifestError, load_doc_manifest, load_kb_manifest
from .metadata_governance import MetadataGovernanceError, load_metadata
from .profiles import ChunkProfile, ProfileError, load_profile
from .routing import (
    RoutingConfig,
    RoutingError,
    load_centroid_index,
    load_route_test_queries,
    load_routing_config,
    run_route_tests,
)
from .validation import ValidationError, load_chunk_snapshot


KB_TOPOLOGY_ADVICE_SCHEMA = "kb_topology_advice_v1"
KB_SPLIT_PLAN_SCHEMA = "kb_split_plan_v1"
KB_ACTIVATION_PLAN_SCHEMA = "kb_activation_plan_v1"

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,12}")
SLUG_RE = re.compile(r"[^a-z0-9]+")
STOPWORDS = {
    "about",
    "after",
    "and",
    "are",
    "body",
    "can",
    "for",
    "from",
    "how",
    "into",
    "the",
    "this",
    "under",
    "what",
    "when",
    "where",
    "which",
    "with",
}
AMBIGUOUS_TERMS = {
    "api",
    "config",
    "guide",
    "key",
    "manual",
    "model",
    "policy",
    "profile",
    "runtime",
    "service",
    "setup",
    "token",
}


class TopologyError(RuntimeError):
    """Raised when topology advice inputs cannot be loaded."""


@dataclass(frozen=True)
class TopologyDocument:
    path: str
    title: str
    chars: int
    token_count: int
    estimated_chunks: int
    domain: str
    topic: str
    terms: set[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "chars": self.chars,
            "token_count": self.token_count,
            "estimated_chunks": self.estimated_chunks,
            "domain": self.domain,
            "topic": self.topic,
            "top_terms": sorted(self.terms)[:20],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TopologyError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise TopologyError(f"file is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise TopologyError(f"file must contain a JSON object: {source}")
    return payload


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(text)
        if len(token.strip()) >= 2 and token.lower() not in STOPWORDS
    }


def _title_from_markdown(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return path.stem


def _metadata_index(metadata_path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not metadata_path:
        return {}
    try:
        metadata = load_metadata(metadata_path)
    except MetadataGovernanceError as exc:
        raise TopologyError(str(exc)) from exc
    index: dict[str, dict[str, Any]] = {}
    for item in metadata.get("documents", []):
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "")
        values = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), Mapping) else {}
        tags = item.get("tags")
        if isinstance(tags, list):
            values["tags"] = [tag for tag in tags if isinstance(tag, str)]
        if path:
            index[path] = values
    return index


def _metadata_for_path(path: Path, metadata: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    path_text = str(path)
    candidates = [
        path_text,
        path.as_posix(),
        path.name,
        f"documents/{path.name}",
    ]
    for candidate in candidates:
        item = metadata.get(candidate)
        if isinstance(item, Mapping):
            return item
    for key, item in metadata.items():
        if path_text.endswith(key) or key.endswith(path.name):
            return item
    return {}


def _domain_from_path(path: Path) -> str:
    parts = [part for part in path.with_suffix("").parts if part not in {"", ".", "documents"}]
    if len(parts) >= 2:
        return parts[-2]
    return "unknown"


def _topic_from_path(path: Path) -> str:
    return path.stem or "unknown"


def _as_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _read_document(path: Path, metadata: Mapping[str, Mapping[str, Any]]) -> TopologyDocument:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    values = _metadata_for_path(path, metadata)
    title = _as_string(values.get("topic")) or _title_from_markdown(text, path)
    domain = _as_string(values.get("domain")) or _domain_from_path(path)
    topic = _as_string(values.get("topic")) or _topic_from_path(path)
    metadata_terms = " ".join(
        str(value)
        for key in ("domain", "topic", "module", "doc_type", "audience", "summary")
        for value in [values.get(key)]
        if isinstance(value, str)
    )
    tag_terms = " ".join(values.get("tags", [])) if isinstance(values.get("tags"), list) else ""
    terms = _tokenize(f"{title}\n{text}\n{metadata_terms}\n{tag_terms}")
    chars = len(text)
    return TopologyDocument(
        path=str(path),
        title=title,
        chars=chars,
        token_count=len(terms),
        estimated_chunks=max(1, math.ceil(chars / 3000)) if chars else 1,
        domain=domain,
        topic=topic,
        terms=terms,
    )


def _load_retrieval_hints(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = _read_json_mapping(path)
    if payload.get("schema") != "ragflow_retrieval_hints_v1":
        raise TopologyError("retrieval hints schema must be ragflow_retrieval_hints_v1")
    return payload


def _list_count(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    return len(value) if isinstance(value, list) else 0


def _retrieval_hints_summary(path: str | Path | None, payload: Mapping[str, Any]) -> dict[str, Any]:
    counts = {
        "section_boundary_count": _list_count(payload, "section_boundaries"),
        "keyword_count": _list_count(payload, "keyword_candidates"),
        "question_count": _list_count(payload, "question_candidates"),
        "numeric_count": _list_count(payload, "numeric_candidates"),
        "table_artifact_count": _list_count(payload, "table_artifacts"),
        "image_artifact_count": _list_count(payload, "image_artifacts"),
        "preferred_boundary_count": _list_count(payload, "preferred_boundaries"),
        "quality_risk_count": _list_count(payload, "quality_risks"),
    }
    signal_count = sum(counts.values())
    return {
        "provided": bool(path),
        "path": str(path) if path else None,
        "schema": payload.get("schema") if isinstance(payload.get("schema"), str) else None,
        "empty": bool(path) and signal_count == 0,
        "signal_count": signal_count,
        **counts,
    }


def _hint_terms(retrieval_hints: Mapping[str, Any]) -> set[str]:
    terms: set[str] = set()
    for item in retrieval_hints.get("keyword_candidates", []) if isinstance(retrieval_hints.get("keyword_candidates"), list) else []:
        if isinstance(item, Mapping):
            terms.update(_tokenize(str(item.get("term") or "")))
    for item in retrieval_hints.get("section_boundaries", []) if isinstance(retrieval_hints.get("section_boundaries"), list) else []:
        if isinstance(item, Mapping):
            terms.update(_tokenize(str(item.get("title") or "")))
    return terms


def _question_candidates(retrieval_hints: Mapping[str, Any], *, limit: int = 6) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in retrieval_hints.get("question_candidates", []) if isinstance(retrieval_hints.get("question_candidates"), list) else []:
        if not isinstance(item, Mapping):
            continue
        question = item.get("question")
        if isinstance(question, str) and question.strip():
            output.append(
                {
                    "question": question.strip(),
                    "type": item.get("type") or "starter",
                    "source_document": item.get("source_document"),
                    "source_heading": item.get("source_heading"),
                }
            )
        if len(output) >= limit:
            break
    return output


def _route_config(path: str | Path | None) -> RoutingConfig | None:
    if not path:
        return None
    try:
        return load_routing_config(path)
    except RoutingError as exc:
        raise TopologyError(str(exc)) from exc


def _kb_terms(config: RoutingConfig | None) -> list[dict[str, Any]]:
    if not config:
        return []
    output = []
    for kb in config.knowledge_bases:
        text = " ".join([kb.name, kb.description, *kb.hints])
        output.append(
            {
                "name": kb.name,
                "dataset_id": kb.dataset_id,
                "terms": _tokenize(text),
                "hint_count": len(kb.hints),
            }
        )
    return output


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return round(len(left & right) / len(union), 4) if union else 0.0


def _semantic_overlap(candidate_terms: set[str], route_terms: list[dict[str, Any]]) -> dict[str, Any]:
    overlaps = []
    for kb in route_terms:
        terms = kb["terms"]
        shared = sorted(candidate_terms & terms)
        score = _jaccard(candidate_terms, terms)
        overlaps.append(
            {
                "kb": kb["name"],
                "dataset_id": kb["dataset_id"],
                "score": score,
                "shared_terms": shared[:12],
                "hint_count": kb["hint_count"],
            }
        )
    overlaps.sort(key=lambda item: (-float(item["score"]), item["kb"]))
    max_score = float(overlaps[0]["score"]) if overlaps else 0.0
    return {
        "status": "not_available" if not route_terms else ("high_overlap" if max_score >= 0.28 else "low_overlap"),
        "max_overlap_score": max_score,
        "candidates": overlaps[:5],
    }


def _terminology_independence(overlap: Mapping[str, Any]) -> dict[str, Any]:
    if overlap.get("status") == "not_available":
        return {
            "status": "unknown",
            "score": None,
            "reason": "no route config supplied for existing-KB comparison",
        }
    score = round(1.0 - float(overlap.get("max_overlap_score") or 0.0), 4)
    status = "independent" if score >= 0.75 else ("overlapping" if score < 0.6 else "mixed")
    return {
        "status": status,
        "score": score,
        "reason": "higher score means fewer candidate terms overlap existing route hints",
    }


def _minimum_corpus(documents: list[TopologyDocument], *, min_documents: int, min_total_chars: int) -> dict[str, Any]:
    total_chars = sum(doc.chars for doc in documents)
    sufficient = len(documents) >= min_documents or total_chars >= min_total_chars
    return {
        "status": "sufficient" if sufficient else "thin",
        "document_count": len(documents),
        "total_chars": total_chars,
        "min_documents": min_documents,
        "min_total_chars": min_total_chars,
        "reason": "small corpora usually need merge/stage review before creating a standalone KB",
    }


def _future_growth_signal(value: str) -> dict[str, Any]:
    normalized = value.strip().lower() if value else "medium"
    if normalized not in {"low", "medium", "high"}:
        raise TopologyError("--future-growth must be low, medium, or high")
    return {
        "level": normalized,
        "supports_new_kb": normalized in {"medium", "high"},
        "reason": "future growth can justify a dedicated KB even when the first corpus is small",
    }


def _domain_summary(documents: list[TopologyDocument]) -> dict[str, Any]:
    chunks_by_domain: Counter[str] = Counter()
    chars_by_domain: Counter[str] = Counter()
    for document in documents:
        chunks_by_domain[document.domain] += document.estimated_chunks
        chars_by_domain[document.domain] += document.chars
    total_chunks = sum(chunks_by_domain.values())
    total_chars = sum(chars_by_domain.values())
    top_domain, top_chunks = chunks_by_domain.most_common(1)[0] if chunks_by_domain else ("unknown", 0)
    return {
        "domain_count": len(chunks_by_domain),
        "chunks_by_domain": dict(sorted(chunks_by_domain.items())),
        "chars_by_domain": dict(sorted(chars_by_domain.items())),
        "top_domain": top_domain,
        "top_domain_chunk_share": round(top_chunks / total_chunks, 4) if total_chunks else 0.0,
        "top_domain_char_share": round(chars_by_domain[top_domain] / total_chars, 4) if total_chars else 0.0,
    }


def _ambiguous_term_signal(documents: list[TopologyDocument]) -> dict[str, Any]:
    terms_by_domain: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        terms_by_domain[document.domain].update(document.terms)
    term_domains: dict[str, set[str]] = defaultdict(set)
    for domain, terms in terms_by_domain.items():
        for term in terms:
            term_domains[term].add(domain)
    repeated = sorted(term for term, domains in term_domains.items() if len(domains) >= 2)
    intrinsic = sorted(term for term in term_domains if term in AMBIGUOUS_TERMS)
    ambiguous = sorted(set(repeated + intrinsic))
    all_terms = set(term_domains)
    score = round(len(ambiguous) / len(all_terms), 4) if all_terms else 0.0
    return {
        "score": score,
        "status": "high" if score >= 0.18 else ("medium" if score >= 0.08 else "low"),
        "terms": ambiguous[:20],
        "cross_domain_terms": repeated[:20],
    }


def _split_signals(documents: list[TopologyDocument]) -> dict[str, Any]:
    domain = _domain_summary(documents)
    top_domain = domain["top_domain"]
    cross_domain_chunk_count = sum(
        doc.estimated_chunks
        for doc in documents
        if doc.domain != top_domain
    )
    total_chars = sum(doc.chars for doc in documents)
    max_doc = max(documents, key=lambda doc: doc.chars) if documents else None
    dominant_share = round(max_doc.chars / total_chars, 4) if max_doc and total_chars else 0.0
    ambiguous = _ambiguous_term_signal(documents)
    warnings: list[dict[str, Any]] = []
    if domain["domain_count"] > 1 and domain["top_domain_chunk_share"] < 0.75:
        warnings.append(
            {
                "code": "mixed_domain_corpus",
                "message": "multiple domains have enough estimated chunks to review a split before upload",
            }
        )
    if ambiguous["status"] in {"medium", "high"}:
        warnings.append(
            {
                "code": "ambiguous_terms",
                "message": "ambiguous or cross-domain terms may blur route hints and retrieval tests",
            }
        )
    if dominant_share >= 0.8 and len(documents) > 1:
        warnings.append(
            {
                "code": "dominant_document",
                "message": "one document dominates the corpus and may deserve separate validation",
            }
        )
    return {
        "cross_domain_chunk_count": cross_domain_chunk_count,
        "ambiguous_term_score": ambiguous["score"],
        "ambiguous_term_status": ambiguous["status"],
        "ambiguous_terms": ambiguous["terms"],
        "dominant_document_share": dominant_share,
        "dominant_document": max_doc.path if max_doc else None,
        "domain_purity": domain,
        "domain_purity_warnings": warnings,
        "split_review_recommended": bool(warnings and (domain["domain_count"] > 1 or ambiguous["status"] == "high")),
    }


def _slug(value: str) -> str:
    normalized = SLUG_RE.sub("-", value.lower()).strip("-")
    return normalized or "unknown"


def _top_terms(documents: list[TopologyDocument], *, limit: int = 12) -> list[str]:
    counter: Counter[str] = Counter()
    for document in documents:
        counter.update(document.terms)
    return [term for term, _count in counter.most_common(limit)]


def _suggested_split_kb_name(kb_name: str, group_name: str) -> str:
    suffix = _slug(group_name)
    if kb_name.endswith(f":{suffix}") or kb_name.endswith(f"-{suffix}"):
        return kb_name
    separator = "-" if ":" in kb_name else ":"
    return f"{kb_name}{separator}{suffix}"


def _questions_for_group(
    questions: list[dict[str, Any]],
    *,
    documents: list[TopologyDocument],
    top_terms: list[str],
    limit: int = 4,
) -> list[dict[str, Any]]:
    paths = {doc.path for doc in documents}
    names = {Path(doc.path).name for doc in documents}
    terms = set(top_terms)
    selected: list[dict[str, Any]] = []
    for item in questions:
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        source = str(item.get("source_document") or "")
        source_match = bool(source and any(path.endswith(source) for path in paths | names))
        term_match = bool(_tokenize(question) & terms)
        if source_match or term_match:
            selected.append(
                {
                    "question": question.strip(),
                    "type": item.get("type") or "starter",
                    "source_document": item.get("source_document"),
                    "assigned_by": "source_document" if source_match else "term_overlap",
                }
            )
        if len(selected) >= limit:
            break
    if not selected:
        for term in top_terms[: min(2, limit)]:
            selected.append(
                {
                    "question": f"What are the key facts about {term}?",
                    "type": "keyword_anchor",
                    "source_document": None,
                    "assigned_by": "fallback_term",
                }
            )
    return selected[:limit]


def _split_groups(
    *,
    kb_name: str,
    documents: list[TopologyDocument],
    questions: list[dict[str, Any]],
    min_group_documents: int,
    min_group_estimated_chunks: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[TopologyDocument]] = defaultdict(list)
    for document in documents:
        grouped[document.domain or "unknown"].append(document)
    groups: list[dict[str, Any]] = []
    for index, group_name in enumerate(sorted(grouped), start=1):
        group_docs = sorted(grouped[group_name], key=lambda doc: doc.path)
        estimated_chunks = sum(doc.estimated_chunks for doc in group_docs)
        total_chars = sum(doc.chars for doc in group_docs)
        top_terms = _top_terms(group_docs)
        action = (
            "standalone_kb_candidate"
            if len(group_docs) >= min_group_documents or estimated_chunks >= min_group_estimated_chunks
            else "merge_or_stage_review"
        )
        warnings: list[dict[str, Any]] = []
        if action != "standalone_kb_candidate":
            warnings.append(
                {
                    "code": "thin_split_candidate",
                    "message": "this split group is small and should be reviewed before creating a separate KB",
                }
            )
        groups.append(
            {
                "id": f"split-{index:03d}-{_slug(group_name)}",
                "group_name": group_name,
                "suggested_kb_name": _suggested_split_kb_name(kb_name, group_name),
                "action": action,
                "document_count": len(group_docs),
                "estimated_chunk_count": estimated_chunks,
                "total_chars": total_chars,
                "document_paths": [doc.path for doc in group_docs],
                "route_hint_candidates": top_terms[:8],
                "starter_questions": _questions_for_group(
                    questions,
                    documents=group_docs,
                    top_terms=top_terms,
                ),
                "warnings": warnings,
            }
        )
    return groups


def _boundary_queries(groups: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    if len(groups) < 2:
        return queries
    for left_index, left in enumerate(groups):
        for right in groups[left_index + 1 :]:
            left_terms = left.get("route_hint_candidates") if isinstance(left.get("route_hint_candidates"), list) else []
            right_terms = right.get("route_hint_candidates") if isinstance(right.get("route_hint_candidates"), list) else []
            left_term = str(left_terms[0]) if left_terms else str(left.get("group_name") or "this group")
            right_term = str(right_terms[0]) if right_terms else str(right.get("group_name") or "that group")
            queries.append(
                {
                    "id": f"boundary-{len(queries) + 1:03d}",
                    "primary_group_id": left.get("id"),
                    "contrast_group_id": right.get("id"),
                    "query": (
                        f"Should a question about {left_term} route to {left.get('suggested_kb_name')} "
                        f"rather than {right.get('suggested_kb_name')}?"
                    ),
                    "contrast_query": (
                        f"Should a question about {right_term} route to {right.get('suggested_kb_name')} "
                        f"rather than {left.get('suggested_kb_name')}?"
                    ),
                    "purpose": "validate split boundaries before editing route configuration",
                }
            )
            if len(queries) >= limit:
                return queries
    return queries


def _split_plan_recommendation(groups: list[dict[str, Any]], split: Mapping[str, Any]) -> dict[str, Any]:
    if len(groups) <= 1:
        return {
            "action": "keep_together",
            "confidence": "high",
            "reasons": ["only one domain group was detected"],
            "advisory_only": True,
        }
    standalone_count = sum(1 for group in groups if group.get("action") == "standalone_kb_candidate")
    reasons: list[str] = []
    if split.get("split_review_recommended"):
        action = "split_before_upload"
        confidence = "high" if standalone_count == len(groups) else "medium"
        reasons.append("split signals indicate mixed domains, ambiguity, or a dominant document")
    else:
        action = "review_split"
        confidence = "medium"
        reasons.append("multiple domain groups were detected but split signals are not decisive")
    if standalone_count < len(groups):
        reasons.append("one or more groups are thin and need merge/stage review")
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "advisory_only": True,
    }


def _activation_issue(
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


def _activation_status(issues: list[dict[str, str]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "blocked"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "review"
    return "ready"


def _load_activation_kb_manifest(path: str | Path) -> KbManifest:
    try:
        return load_kb_manifest(path)
    except ManifestError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_doc_manifest(path: str | Path | None) -> Any | None:
    if not path:
        return None
    try:
        return load_doc_manifest(path)
    except ManifestError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_chunk_snapshot(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return load_chunk_snapshot(path)
    except ValidationError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_centroid_index(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return load_centroid_index(path)
    except RoutingError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_route_tests(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        return load_route_test_queries(path)
    except RoutingError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_profile(path: str | Path | None) -> ChunkProfile | None:
    if not path:
        return None
    try:
        return load_profile(path)
    except ProfileError as exc:
        raise TopologyError(str(exc)) from exc


def _load_activation_ingest_plan(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return load_ragflow_ingest_plan(path)
    except HandoffError as exc:
        raise TopologyError(str(exc)) from exc


def _resolve_ingest_sidecar(ingest_plan_path: str | Path | None, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if path.is_absolute() or ingest_plan_path is None:
        return path
    return Path(ingest_plan_path).parent / path


def _same_file_reference(left: str | Path | None, right: str | Path | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)
    except OSError:
        return Path(left) == Path(right)


def _profile_value(profile: ChunkProfile, key: str) -> Any:
    if key == "chunk_method":
        return profile.chunk_method
    if key == "chunk_size":
        return profile.chunk_size
    if key == "chunk_overlap":
        return profile.chunk_overlap
    return profile.parser_config.get(key)


def _ingest_plan_consistency_check(
    *,
    ingest_plan: Mapping[str, Any] | None,
    ingest_plan_path: str | Path | None,
    doc_manifest_path: str | Path | None,
    retrieval_hints_path: str | Path | None,
    profile_path: str | Path | None,
    profile: ChunkProfile | None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if ingest_plan is None:
        return {
            "status": "not_configured",
            "optional": True,
            "ingest_plan": None,
            "schema": None,
            "doc_manifest_matches": None,
            "retrieval_hints_matches": None,
            "profile_supplied": bool(profile_path),
            "profile_matches_recommendation": None,
            "issues": [
                _activation_issue(
                    "info",
                    "ingest_plan_not_supplied",
                    "no ragflow_ingest_plan sidecar was supplied",
                    path="ingest_plan",
                    recommendation="Supply ragflow_ingest_plan.yaml from ragflow-doc-to-md pipeline for formal handoff checks.",
                )
            ],
        }

    handoff = ingest_plan.get("handoff") if isinstance(ingest_plan.get("handoff"), Mapping) else {}
    expected_doc_manifest = _resolve_ingest_sidecar(ingest_plan_path, handoff.get("doc_manifest"))
    expected_retrieval_hints = _resolve_ingest_sidecar(ingest_plan_path, handoff.get("retrieval_hints"))
    doc_matches = _same_file_reference(expected_doc_manifest, doc_manifest_path)
    hints_matches = _same_file_reference(expected_retrieval_hints, retrieval_hints_path)
    if expected_doc_manifest and not doc_manifest_path:
        issues.append(
            _activation_issue(
                "warning",
                "ingest_doc_manifest_not_supplied",
                "ingest plan references a doc_manifest but activation-plan did not receive one",
                path="doc_manifest",
                recommendation="Pass --doc-manifest from the same pipeline handoff before activation review.",
            )
        )
    elif expected_doc_manifest and not doc_matches:
        issues.append(
            _activation_issue(
                "warning",
                "ingest_doc_manifest_mismatch",
                "activation doc_manifest path differs from ragflow_ingest_plan",
                path="ingest_plan.handoff.doc_manifest",
                recommendation="Confirm the activation plan is using the same handoff that was built.",
            )
        )
    if expected_retrieval_hints and not retrieval_hints_path:
        issues.append(
            _activation_issue(
                "warning",
                "ingest_retrieval_hints_not_supplied",
                "ingest plan references retrieval_hints but activation-plan did not receive one",
                path="retrieval_hints",
                recommendation="Pass --retrieval-hints from the same pipeline handoff for route hint checks.",
            )
        )
    elif expected_retrieval_hints and not hints_matches:
        issues.append(
            _activation_issue(
                "warning",
                "ingest_retrieval_hints_mismatch",
                "activation retrieval_hints path differs from ragflow_ingest_plan",
                path="ingest_plan.handoff.retrieval_hints",
                recommendation="Confirm retrieval hints came from the same pipeline handoff.",
            )
        )

    recommended = ingest_plan.get("recommended_build") if isinstance(ingest_plan.get("recommended_build"), Mapping) else {}
    parser_profile = recommended.get("parser_profile") if isinstance(recommended.get("parser_profile"), Mapping) else {}
    profile_matches = None
    profile_differences: list[dict[str, Any]] = []
    if parser_profile:
        if profile is None:
            issues.append(
                _activation_issue(
                    "warning",
                    "build_profile_not_supplied",
                    "ingest plan includes a recommended parser profile but activation-plan did not receive --profile",
                    path="profile",
                    recommendation="Pass the reviewed kb-build profile used for ingestion so activation review can compare it.",
                )
            )
        else:
            for key in ("chunk_method", "chunk_size", "chunk_overlap"):
                expected = parser_profile.get(key)
                actual = _profile_value(profile, key)
                if expected is not None and str(expected) != str(actual):
                    profile_differences.append({"field": key, "expected": expected, "actual": actual})
            profile_matches = not profile_differences
            if profile_differences:
                issues.append(
                    _activation_issue(
                        "warning",
                        "build_profile_differs_from_ingest_plan",
                        "provided build profile differs from ragflow_ingest_plan parser recommendation",
                        path="recommended_build.parser_profile",
                        recommendation="Confirm the profile change was intentional before activation.",
                    )
                )

    return {
        "status": _activation_status(issues),
        "ingest_plan": str(ingest_plan_path) if ingest_plan_path else None,
        "schema": ingest_plan.get("schema"),
        "expected_schema": RAGFLOW_INGEST_PLAN_SCHEMA,
        "doc_manifest": str(doc_manifest_path) if doc_manifest_path else None,
        "expected_doc_manifest": str(expected_doc_manifest) if expected_doc_manifest else None,
        "doc_manifest_matches": doc_matches if expected_doc_manifest else None,
        "retrieval_hints": str(retrieval_hints_path) if retrieval_hints_path else None,
        "expected_retrieval_hints": str(expected_retrieval_hints) if expected_retrieval_hints else None,
        "retrieval_hints_matches": hints_matches if expected_retrieval_hints else None,
        "profile": str(profile_path) if profile_path else None,
        "profile_supplied": bool(profile_path),
        "profile_matches_recommendation": profile_matches,
        "profile_differences": profile_differences,
        "issues": issues,
    }


def _content_completeness_check(
    kb_manifest: KbManifest,
    *,
    doc_manifest: Any | None,
    min_documents: int,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    documents = kb_manifest.documents
    missing_ids = [index for index, document in enumerate(documents) if not document.document_id]
    failed_statuses = {"fail", "failed", "error", "cancelled", "canceled"}
    failed_documents = [
        document.document_id
        for document in documents
        if isinstance(document.status, str) and document.status.strip().lower() in failed_statuses
    ]
    if len(documents) < min_documents:
        issues.append(
            _activation_issue(
                "error",
                "document_count_below_minimum",
                "KB manifest has fewer documents than the activation minimum",
                path="kb_manifest.documents",
                recommendation="Build or append enough parsed documents before route activation.",
            )
        )
    if missing_ids:
        issues.append(
            _activation_issue(
                "error",
                "missing_document_ids",
                "one or more KB manifest documents are missing document_id",
                path="kb_manifest.documents",
                recommendation="Use a completed kb_manifest from build.py before planning activation.",
            )
        )
    if failed_documents:
        issues.append(
            _activation_issue(
                "error",
                "failed_document_status",
                "one or more KB manifest documents report failed status",
                path="kb_manifest.documents.status",
                recommendation="Repair or rebuild failed documents before route activation.",
            )
        )
    quality_gate = getattr(doc_manifest, "quality_gate", {}) if doc_manifest else {}
    quality_status = quality_gate.get("status") if isinstance(quality_gate, Mapping) else None
    if quality_status == "BLOCKED":
        issues.append(
            _activation_issue(
                "error",
                "blocked_doc_manifest_quality_gate",
                "doc_manifest quality gate is BLOCKED",
                path="doc_manifest.quality_gate.status",
                recommendation="Resolve handoff quality blockers before route activation.",
            )
        )
    if doc_manifest and len(getattr(doc_manifest, "documents", [])) != len(documents):
        issues.append(
            _activation_issue(
                "warning",
                "doc_manifest_count_mismatch",
                "doc_manifest document count differs from kb_manifest document count",
                path="doc_manifest.documents",
                recommendation="Confirm the activation plan references the same handoff used for KB build.",
            )
        )
    return {
        "status": _activation_status(issues),
        "document_count": len(documents),
        "min_documents": min_documents,
        "quality_gate_status": quality_status,
        "failed_document_ids": failed_documents,
        "issues": issues,
    }


def _chunk_dataset_id(chunk: Mapping[str, Any]) -> str:
    for key in ("dataset_id", "kb_id", "datasetId"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _chunk_document_id(chunk: Mapping[str, Any]) -> str:
    for key in ("document_id", "doc_id", "documentId"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _chunks_for_kb(snapshot: Mapping[str, Any] | None, kb_manifest: KbManifest) -> list[Mapping[str, Any]]:
    if not snapshot:
        return []
    chunks = [item for item in snapshot.get("chunks", []) if isinstance(item, Mapping)]
    dataset_id = kb_manifest.dataset.id
    document_ids = {document.document_id for document in kb_manifest.documents if document.document_id}
    matched = [
        chunk
        for chunk in chunks
        if _chunk_dataset_id(chunk) == dataset_id or (_chunk_document_id(chunk) and _chunk_document_id(chunk) in document_ids)
    ]
    if matched:
        return matched
    if chunks and not any(_chunk_dataset_id(chunk) or _chunk_document_id(chunk) for chunk in chunks):
        return chunks
    return []


def _chunk_readiness_check(
    kb_manifest: KbManifest,
    *,
    chunk_snapshot: Mapping[str, Any] | None,
    min_chunks: int,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    declared_chunks = sum(document.chunk_count or 0 for document in kb_manifest.documents)
    unknown_chunk_documents = [document.document_id for document in kb_manifest.documents if document.chunk_count is None]
    zero_chunk_documents = [
        document.document_id for document in kb_manifest.documents if document.chunk_count is not None and document.chunk_count <= 0
    ]
    matched_chunks = _chunks_for_kb(chunk_snapshot, kb_manifest)
    matched_chunk_count = len(matched_chunks)
    if chunk_snapshot:
        effective_chunks = matched_chunk_count
        if matched_chunk_count < min_chunks:
            issues.append(
                _activation_issue(
                    "error",
                    "chunk_snapshot_has_too_few_chunks",
                    "chunk snapshot does not contain enough chunks for this KB",
                    path="chunk_snapshot.chunks",
                    recommendation="Create a fresh snapshot-chunks sidecar for this dataset before activation.",
                )
            )
    else:
        effective_chunks = declared_chunks
        if declared_chunks < min_chunks:
            issues.append(
                _activation_issue(
                    "warning",
                    "declared_chunk_count_below_minimum",
                    "kb_manifest declares too few chunks and no chunk snapshot was supplied",
                    path="kb_manifest.documents[].chunk_count",
                    recommendation="Run snapshot-chunks or wait for parsing to confirm chunks before activation.",
                )
            )
    if zero_chunk_documents:
        issues.append(
            _activation_issue(
                "warning",
                "zero_chunk_documents",
                "one or more KB manifest documents declare zero chunks",
                path="kb_manifest.documents[].chunk_count",
                recommendation="Confirm parsing completed and rerun activation-plan with a chunk snapshot.",
            )
        )
    return {
        "status": _activation_status(issues),
        "declared_chunk_count": declared_chunks,
        "matched_snapshot_chunk_count": matched_chunk_count,
        "effective_chunk_count": effective_chunks,
        "min_chunks": min_chunks,
        "unknown_chunk_document_ids": unknown_chunk_documents,
        "zero_chunk_document_ids": zero_chunk_documents,
        "snapshot_available": bool(chunk_snapshot),
        "issues": issues,
    }


def _registered_kb(config: RoutingConfig | None, kb_manifest: KbManifest) -> Any | None:
    if not config:
        return None
    refs = {kb_manifest.dataset.id, kb_manifest.dataset.name}
    return next((kb for kb in config.knowledge_bases if kb.name in refs or kb.dataset_id in refs), None)


def _route_registration_check(
    kb_manifest: KbManifest,
    *,
    route_config: RoutingConfig | None,
    route_config_path: str | Path | None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    registered = _registered_kb(route_config, kb_manifest)
    if not route_config_path:
        issues.append(
            _activation_issue(
                "error",
                "route_config_missing",
                "no user-owned route config was supplied",
                path="route_config",
                recommendation="Review the route_entry_suggestion and add it to a user-owned route config explicitly.",
            )
        )
    elif not registered:
        issues.append(
            _activation_issue(
                "error",
                "kb_not_registered",
                "KB dataset is not registered in the supplied route config",
                path="route_config.knowledge_bases",
                recommendation="Add this KB by name or dataset_id before running route-test.",
            )
        )
    elif not registered.hints:
        issues.append(
            _activation_issue(
                "warning",
                "registered_kb_has_no_hints",
                "registered KB has no route hints",
                path="route_config.knowledge_bases[].hints",
                recommendation="Add public user-owned route hints before activation.",
            )
        )
    return {
        "status": _activation_status(issues),
        "route_config": str(route_config_path) if route_config_path else None,
        "registered": registered is not None,
        "registered_kb": registered.to_dict() if registered else None,
        "issues": issues,
    }


def _route_entry_suggestion(kb_manifest: KbManifest, retrieval_hints: Mapping[str, Any]) -> dict[str, Any]:
    terms = sorted(_hint_terms(retrieval_hints))
    if not terms:
        terms = sorted(_tokenize(kb_manifest.dataset.name))
    return {
        "name": kb_manifest.dataset.name,
        "dataset_id": kb_manifest.dataset.id,
        "hints": terms[:8],
        "params": {
            "top_k": 5,
            "similarity_threshold": 0.2,
        },
        "advisory_only": True,
    }


def _hint_coverage_check(
    *,
    registered_kb: Any | None,
    retrieval_hints: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    route_hints = list(registered_kb.hints) if registered_kb else []
    hint_terms = _hint_terms(retrieval_hints)
    route_terms = _tokenize(" ".join(route_hints))
    overlap = sorted(hint_terms & route_terms)
    coverage = round(len(overlap) / len(hint_terms), 4) if hint_terms else None
    keyword_count = len(retrieval_hints.get("keyword_candidates", [])) if isinstance(retrieval_hints.get("keyword_candidates"), list) else 0
    question_count = len(retrieval_hints.get("question_candidates", [])) if isinstance(retrieval_hints.get("question_candidates"), list) else 0
    if not route_hints:
        issues.append(
            _activation_issue(
                "error",
                "route_hints_missing",
                "no route hints are available for the KB",
                path="route_config.knowledge_bases[].hints",
                recommendation="Add route hints before activation and rerun route-test.",
            )
        )
    elif hint_terms and not overlap:
        issues.append(
            _activation_issue(
                "warning",
                "retrieval_hint_overlap_missing",
                "route hints do not overlap rich-handoff keyword or section terms",
                path="retrieval_hints.keyword_candidates",
                recommendation="Review whether route hints cover the handoff retrieval vocabulary.",
            )
        )
    return {
        "status": _activation_status(issues),
        "route_hint_count": len(route_hints),
        "retrieval_keyword_count": keyword_count,
        "retrieval_question_count": question_count,
        "coverage": coverage,
        "overlap_terms": overlap[:12],
        "issues": issues,
    }


def _centroid_availability_check(
    kb_manifest: KbManifest,
    *,
    centroid_index: Mapping[str, Any] | None,
    centroid_index_path: str | Path | None,
) -> dict[str, Any]:
    if not centroid_index_path:
        return {
            "status": "not_configured",
            "optional": True,
            "centroid_index": None,
            "matched": False,
            "ready": None,
            "issues": [
                _activation_issue(
                    "info",
                    "centroid_index_not_supplied",
                    "no centroid index was supplied; route activation can still use explicit hints",
                    path="centroid_index",
                    recommendation="Add a centroid index only when tie-breaking or semantic fallback is needed.",
                )
            ],
        }
    centroids = centroid_index.get("centroids", []) if isinstance(centroid_index, Mapping) else []
    matched = [
        item
        for item in centroids
        if isinstance(item, Mapping) and item.get("dataset_id") == kb_manifest.dataset.id
    ]
    ready = [item for item in matched if str(item.get("status") or "ready") == "ready"]
    issues: list[dict[str, str]] = []
    if not matched:
        issues.append(
            _activation_issue(
                "warning",
                "centroid_missing_for_dataset",
                "centroid index does not contain this dataset",
                path="centroid_index.centroids",
                recommendation="Rebuild the centroid index after adding this KB if centroid tie-breaking is desired.",
            )
        )
    elif not ready:
        issues.append(
            _activation_issue(
                "warning",
                "centroid_not_ready",
                "centroid exists for this dataset but is not ready",
                path="centroid_index.centroids[].status",
                recommendation="Complete the centroid build before relying on centroid tie-breaking.",
            )
        )
    return {
        "status": _activation_status(issues),
        "optional": True,
        "centroid_index": str(centroid_index_path),
        "matched": bool(matched),
        "ready": bool(ready),
        "matched_centroids": [dict(item) for item in matched[:3]],
        "issues": issues,
    }


def _query_targets_kb(query: Mapping[str, Any], kb_manifest: KbManifest) -> bool:
    refs = {kb_manifest.dataset.name, kb_manifest.dataset.id}
    expected = query.get("expected")
    if isinstance(expected, str) and expected in refs:
        return True
    for key in ("acceptable_kbs", "acceptable_dataset_ids", "allowed_kbs", "allowed_dataset_ids"):
        values = query.get(key)
        if isinstance(values, list) and any(isinstance(item, str) and item in refs for item in values):
            return True
    return False


def _route_test_readiness_check(
    kb_manifest: KbManifest,
    *,
    route_config: RoutingConfig | None,
    route_tests: list[dict[str, Any]],
    route_tests_path: str | Path | None,
    centroid_index: Mapping[str, Any] | None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not route_tests_path:
        issues.append(
            _activation_issue(
                "error",
                "route_tests_missing",
                "no route-test query file was supplied",
                path="route_tests",
                recommendation="Create route-test queries for this KB before activation.",
            )
        )
        return {
            "status": _activation_status(issues),
            "route_tests": None,
            "query_count": 0,
            "target_query_count": 0,
            "passed_target_query_count": 0,
            "failed_target_query_count": 0,
            "route_test_report": None,
            "issues": issues,
        }
    target_queries = [query for query in route_tests if _query_targets_kb(query, kb_manifest)]
    if not target_queries:
        issues.append(
            _activation_issue(
                "error",
                "route_tests_do_not_target_kb",
                "route-test file does not include queries expecting this KB",
                path="route_tests.queries",
                recommendation="Add positive route-test cases for this KB name or dataset_id.",
            )
        )
    route_report = None
    passed_target = 0
    failed_target = 0
    if route_config:
        try:
            route_report = run_route_tests(route_config, route_tests, centroid_index=centroid_index)
        except RoutingError as exc:
            raise TopologyError(str(exc)) from exc
        cases = route_report.get("cases", []) if isinstance(route_report, Mapping) else []
        for case in cases:
            if isinstance(case, Mapping) and case.get("id") in {query["id"] for query in target_queries}:
                if case.get("passed"):
                    passed_target += 1
                else:
                    failed_target += 1
        if target_queries and failed_target:
            issues.append(
                _activation_issue(
                    "error",
                    "target_route_tests_failed",
                    "one or more route-test cases for this KB failed",
                    path="route_tests.queries",
                    recommendation="Adjust route hints or expected KBs before activation.",
                )
            )
    else:
        issues.append(
            _activation_issue(
                "error",
                "route_tests_need_route_config",
                "route tests cannot be run without a route config",
                path="route_config",
                recommendation="Supply user-owned route config and rerun activation-plan.",
            )
        )
    return {
        "status": _activation_status(issues),
        "route_tests": str(route_tests_path),
        "query_count": len(route_tests),
        "target_query_count": len(target_queries),
        "passed_target_query_count": passed_target,
        "failed_target_query_count": failed_target,
        "route_test_report": route_report,
        "issues": issues,
    }


def _activation_recommendation(checks: Mapping[str, Any]) -> dict[str, Any]:
    blocking = [
        name
        for name, check in checks.items()
        if isinstance(check, Mapping) and not check.get("optional") and check.get("status") == "blocked"
    ]
    review = [
        name
        for name, check in checks.items()
        if isinstance(check, Mapping) and not check.get("optional") and check.get("status") == "review"
    ]
    if blocking:
        return {
            "action": "complete_activation_prerequisites",
            "confidence": "high",
            "reasons": [f"blocked checks: {', '.join(blocking)}"],
            "advisory_only": True,
        }
    if review:
        return {
            "action": "review_before_activation",
            "confidence": "medium",
            "reasons": [f"checks need review: {', '.join(review)}"],
            "advisory_only": True,
        }
    return {
        "action": "ready_for_activation_review",
        "confidence": "high",
        "reasons": ["all required offline activation checks are ready"],
        "advisory_only": True,
    }


def _anchor_query_pairs(
    *,
    kb_name: str,
    candidate_terms: set[str],
    questions: list[dict[str, Any]],
    overlap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    overlap_candidates = [
        item for item in overlap.get("candidates", []) if isinstance(item, Mapping) and item.get("kb")
    ]
    fallback_questions = [
        {"question": f"What are the key facts about {term}?", "type": "keyword_anchor"}
        for term in sorted(candidate_terms)[:3]
    ]
    source_questions = questions or fallback_questions
    for index, question in enumerate(source_questions[:5], start=1):
        existing = overlap_candidates[0] if overlap_candidates else {}
        shared_terms = existing.get("shared_terms") if isinstance(existing.get("shared_terms"), list) else []
        contrast_term = shared_terms[0] if shared_terms else (sorted(candidate_terms)[0] if candidate_terms else kb_name)
        pairs.append(
            {
                "id": f"anchor-{index:03d}",
                "candidate_kb": kb_name,
                "candidate_query": question["question"],
                "candidate_query_type": question.get("type", "starter"),
                "contrast_existing_kb": existing.get("kb"),
                "contrast_query": f"Should this route to {kb_name} rather than {existing.get('kb') or 'an existing KB'} for {contrast_term}?",
                "purpose": "distinguish create-vs-merge and route activation behavior",
            }
        )
    return pairs


def _recommendation(
    *,
    corpus: Mapping[str, Any],
    growth: Mapping[str, Any],
    independence: Mapping[str, Any],
    overlap: Mapping[str, Any],
    split: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    action = "create_new_kb"
    confidence = "medium"
    if split.get("split_review_recommended"):
        action = "split_before_upload"
        confidence = "medium"
        reasons.append("split signals show mixed domains, ambiguity, or a dominant document")
    elif overlap.get("status") == "high_overlap" and corpus.get("status") == "thin":
        action = "merge_with_existing"
        confidence = "medium"
        reasons.append("candidate terms overlap existing route hints and the corpus is still thin")
    elif corpus.get("status") == "thin" and not growth.get("supports_new_kb"):
        action = "stage_until_larger"
        confidence = "low"
        reasons.append("corpus is thin and future-growth hint is low")
    elif independence.get("status") == "independent" and corpus.get("status") == "sufficient":
        action = "create_new_kb"
        confidence = "high"
        reasons.append("candidate terminology is independent and corpus size is sufficient")
    else:
        reasons.append("signals are mixed; review route-test anchors before mutating config")
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "advisory_only": True,
    }


def create_kb_topology_advice(
    *,
    kb_name: str,
    documents: Iterable[BuildDocument | str | Path],
    metadata_path: str | Path | None = None,
    retrieval_hints_path: str | Path | None = None,
    route_config_path: str | Path | None = None,
    future_growth: str = "medium",
    min_documents: int = 3,
    min_total_chars: int = 1200,
) -> dict[str, Any]:
    """Create non-mutating KB topology advice from local handoff artifacts."""

    paths = [Path(item.path if isinstance(item, BuildDocument) else item) for item in documents]
    if not paths:
        raise TopologyError("topology advice requires at least one Markdown document")
    metadata = _metadata_index(metadata_path)
    doc_summaries = [_read_document(path, metadata) for path in paths]
    retrieval_hints = _load_retrieval_hints(retrieval_hints_path)
    retrieval_hints_info = _retrieval_hints_summary(retrieval_hints_path, retrieval_hints)
    route_config = _route_config(route_config_path)
    route_terms = _kb_terms(route_config)
    candidate_terms = set().union(*(doc.terms for doc in doc_summaries)) | _hint_terms(retrieval_hints)
    candidate_terms = {term for term in candidate_terms if term not in STOPWORDS}
    overlap = _semantic_overlap(candidate_terms, route_terms)
    independence = _terminology_independence(overlap)
    corpus = _minimum_corpus(doc_summaries, min_documents=min_documents, min_total_chars=min_total_chars)
    growth = _future_growth_signal(future_growth)
    split = _split_signals(doc_summaries)
    questions = _question_candidates(retrieval_hints)
    anchor_pairs = _anchor_query_pairs(
        kb_name=kb_name,
        candidate_terms=candidate_terms,
        questions=questions,
        overlap=overlap,
    )
    recommendation = _recommendation(
        corpus=corpus,
        growth=growth,
        independence=independence,
        overlap=overlap,
        split=split,
    )
    return {
        "ok": True,
        "schema": KB_TOPOLOGY_ADVICE_SCHEMA,
        "created_at": _now(),
        "kb_name": kb_name,
        "advisory_only": True,
        "mutation": "none",
        "inputs": {
            "metadata": str(metadata_path) if metadata_path else None,
            "retrieval_hints": str(retrieval_hints_path) if retrieval_hints_path else None,
            "retrieval_hints_summary": retrieval_hints_info,
            "route_config": str(route_config_path) if route_config_path else None,
            "future_growth": growth["level"],
            "min_documents": min_documents,
            "min_total_chars": min_total_chars,
        },
        "summary": {
            "document_count": len(doc_summaries),
            "estimated_chunk_count": sum(doc.estimated_chunks for doc in doc_summaries),
            "candidate_term_count": len(candidate_terms),
            "retrieval_hints_provided": retrieval_hints_info["provided"],
            "retrieval_hints_empty": retrieval_hints_info["empty"],
            "recommendation": recommendation["action"],
            "confidence": recommendation["confidence"],
        },
        "recommendation": recommendation,
        "signals": {
            "terminology_independence": independence,
            "minimum_useful_corpus_size": corpus,
            "future_growth": growth,
            "semantic_overlap": overlap,
            "split": split,
            "retrieval_hints": retrieval_hints_info,
        },
        "anchor_query_pairs": anchor_pairs,
        "route_test_starters": questions,
        "documents": [doc.to_dict() for doc in doc_summaries],
        "next_steps": [
            "Review the recommendation before creating, merging, splitting, or registering any KB.",
            "Run route-test with the anchor query pairs before editing user-owned routing config.",
            "Keep this report as a sidecar; it does not mutate RAGFlow or routing files.",
        ],
    }


def create_kb_split_plan(
    *,
    kb_name: str,
    documents: Iterable[BuildDocument | str | Path],
    metadata_path: str | Path | None = None,
    retrieval_hints_path: str | Path | None = None,
    min_group_documents: int = 1,
    min_group_estimated_chunks: int = 1,
) -> dict[str, Any]:
    """Create a non-mutating split plan from local handoff artifacts."""

    if min_group_documents < 1:
        raise TopologyError("--min-group-documents must be at least 1")
    if min_group_estimated_chunks < 1:
        raise TopologyError("--min-group-estimated-chunks must be at least 1")
    paths = [Path(item.path if isinstance(item, BuildDocument) else item) for item in documents]
    if not paths:
        raise TopologyError("split plan requires at least one Markdown document")
    metadata = _metadata_index(metadata_path)
    doc_summaries = [_read_document(path, metadata) for path in paths]
    retrieval_hints = _load_retrieval_hints(retrieval_hints_path)
    questions = _question_candidates(retrieval_hints, limit=12)
    split = _split_signals(doc_summaries)
    groups = _split_groups(
        kb_name=kb_name,
        documents=doc_summaries,
        questions=questions,
        min_group_documents=min_group_documents,
        min_group_estimated_chunks=min_group_estimated_chunks,
    )
    recommendation = _split_plan_recommendation(groups, split)
    boundaries = _boundary_queries(groups)
    return {
        "ok": True,
        "schema": KB_SPLIT_PLAN_SCHEMA,
        "created_at": _now(),
        "kb_name": kb_name,
        "advisory_only": True,
        "mutation": "none",
        "inputs": {
            "metadata": str(metadata_path) if metadata_path else None,
            "retrieval_hints": str(retrieval_hints_path) if retrieval_hints_path else None,
            "min_group_documents": min_group_documents,
            "min_group_estimated_chunks": min_group_estimated_chunks,
        },
        "summary": {
            "document_count": len(doc_summaries),
            "estimated_chunk_count": sum(doc.estimated_chunks for doc in doc_summaries),
            "split_group_count": len(groups),
            "recommendation": recommendation["action"],
            "confidence": recommendation["confidence"],
        },
        "recommendation": recommendation,
        "signals": {
            "split": split,
        },
        "split_groups": groups,
        "boundary_queries": boundaries,
        "documents": [doc.to_dict() for doc in doc_summaries],
        "next_steps": [
            "Review split groups before creating separate KBs or changing route configuration.",
            "Use suggested KB names and route hints as planning notes only.",
            "Run route-test with boundary queries after any explicit user-owned route edit.",
            "Keep this plan as a sidecar; it does not mutate RAGFlow or routing files.",
        ],
    }


def create_kb_activation_plan(
    *,
    kb_manifest_path: str | Path,
    doc_manifest_path: str | Path | None = None,
    route_config_path: str | Path | None = None,
    retrieval_hints_path: str | Path | None = None,
    ingest_plan_path: str | Path | None = None,
    profile_path: str | Path | None = None,
    chunk_snapshot_path: str | Path | None = None,
    centroid_index_path: str | Path | None = None,
    route_tests_path: str | Path | None = None,
    min_documents: int = 1,
    min_chunks: int = 1,
) -> dict[str, Any]:
    """Create a non-mutating route activation plan from local sidecars."""

    if min_documents < 1:
        raise TopologyError("--min-documents must be at least 1")
    if min_chunks < 1:
        raise TopologyError("--min-chunks must be at least 1")
    kb_manifest = _load_activation_kb_manifest(kb_manifest_path)
    doc_manifest = _load_activation_doc_manifest(doc_manifest_path)
    retrieval_hints = _load_retrieval_hints(retrieval_hints_path)
    ingest_plan = _load_activation_ingest_plan(ingest_plan_path)
    profile = _load_activation_profile(profile_path)
    chunk_snapshot = _load_activation_chunk_snapshot(chunk_snapshot_path)
    route_config = _route_config(route_config_path)
    centroid_index = _load_activation_centroid_index(centroid_index_path)
    route_tests = _load_activation_route_tests(route_tests_path)
    registered = _registered_kb(route_config, kb_manifest)
    checks = {
        "content_completeness": _content_completeness_check(
            kb_manifest,
            doc_manifest=doc_manifest,
            min_documents=min_documents,
        ),
        "chunk_readiness": _chunk_readiness_check(
            kb_manifest,
            chunk_snapshot=chunk_snapshot,
            min_chunks=min_chunks,
        ),
        "route_config_registration": _route_registration_check(
            kb_manifest,
            route_config=route_config,
            route_config_path=route_config_path,
        ),
        "hint_coverage": _hint_coverage_check(
            registered_kb=registered,
            retrieval_hints=retrieval_hints,
        ),
        "ingest_plan_consistency": _ingest_plan_consistency_check(
            ingest_plan=ingest_plan,
            ingest_plan_path=ingest_plan_path,
            doc_manifest_path=doc_manifest_path,
            retrieval_hints_path=retrieval_hints_path,
            profile_path=profile_path,
            profile=profile,
        ),
        "centroid_availability": _centroid_availability_check(
            kb_manifest,
            centroid_index=centroid_index,
            centroid_index_path=centroid_index_path,
        ),
        "route_test_readiness": _route_test_readiness_check(
            kb_manifest,
            route_config=route_config,
            route_tests=route_tests,
            route_tests_path=route_tests_path,
            centroid_index=centroid_index,
        ),
    }
    recommendation = _activation_recommendation(checks)
    required_checks = [name for name, check in checks.items() if isinstance(check, Mapping) and not check.get("optional")]
    blocked = [name for name in required_checks if checks[name].get("status") == "blocked"]
    review = [name for name in required_checks if checks[name].get("status") == "review"]
    return {
        "ok": True,
        "schema": KB_ACTIVATION_PLAN_SCHEMA,
        "created_at": _now(),
        "kb_name": kb_manifest.dataset.name,
        "dataset_id": kb_manifest.dataset.id,
        "advisory_only": True,
        "mutation": "none",
        "inputs": {
            "kb_manifest": str(kb_manifest_path),
            "doc_manifest": str(doc_manifest_path) if doc_manifest_path else None,
            "route_config": str(route_config_path) if route_config_path else None,
            "retrieval_hints": str(retrieval_hints_path) if retrieval_hints_path else None,
            "ingest_plan": str(ingest_plan_path) if ingest_plan_path else None,
            "profile": str(profile_path) if profile_path else None,
            "chunk_snapshot": str(chunk_snapshot_path) if chunk_snapshot_path else None,
            "centroid_index": str(centroid_index_path) if centroid_index_path else None,
            "route_tests": str(route_tests_path) if route_tests_path else None,
            "min_documents": min_documents,
            "min_chunks": min_chunks,
        },
        "summary": {
            "document_count": len(kb_manifest.documents),
            "declared_chunk_count": checks["chunk_readiness"]["declared_chunk_count"],
            "effective_chunk_count": checks["chunk_readiness"]["effective_chunk_count"],
            "retrieval_hints_provided": bool(retrieval_hints_path),
            "retrieval_hints_empty": _retrieval_hints_summary(retrieval_hints_path, retrieval_hints)["empty"],
            "ingest_plan_provided": bool(ingest_plan_path),
            "required_check_count": len(required_checks),
            "blocked_check_count": len(blocked),
            "review_check_count": len(review),
            "recommendation": recommendation["action"],
            "confidence": recommendation["confidence"],
        },
        "recommendation": recommendation,
        "checks": checks,
        "route_entry_suggestion": _route_entry_suggestion(kb_manifest, retrieval_hints),
        "next_steps": [
            "Review this activation plan before editing any user-owned routing config.",
            "Add or update route config entries explicitly outside this command when ready.",
            "Run route-test after route config changes and keep the report beside this sidecar.",
            "Keep this plan as a sidecar; it does not mutate RAGFlow or routing files.",
        ],
    }


def render_topology_advice_markdown(report: Mapping[str, Any]) -> str:
    """Render topology advice as a compact review note."""

    recommendation = report.get("recommendation", {}) if isinstance(report.get("recommendation"), Mapping) else {}
    signals = report.get("signals", {}) if isinstance(report.get("signals"), Mapping) else {}
    split = signals.get("split", {}) if isinstance(signals.get("split"), Mapping) else {}
    overlap = signals.get("semantic_overlap", {}) if isinstance(signals.get("semantic_overlap"), Mapping) else {}
    hints = signals.get("retrieval_hints", {}) if isinstance(signals.get("retrieval_hints"), Mapping) else {}
    lines = [
        "# RAGFlow KB Topology Advice",
        "",
        f"- Schema: `{report.get('schema')}`",
        f"- KB: `{report.get('kb_name')}`",
        f"- Recommendation: `{recommendation.get('action')}` ({recommendation.get('confidence')})",
        f"- Advisory only: `{report.get('advisory_only')}`",
        "",
        "## Signals",
        "",
        f"- Minimum corpus: `{signals.get('minimum_useful_corpus_size', {}).get('status') if isinstance(signals.get('minimum_useful_corpus_size'), Mapping) else 'unknown'}`",
        f"- Terminology independence: `{signals.get('terminology_independence', {}).get('status') if isinstance(signals.get('terminology_independence'), Mapping) else 'unknown'}`",
        f"- Semantic overlap: `{overlap.get('status')}` max `{overlap.get('max_overlap_score')}`",
        f"- Retrieval hints: provided `{hints.get('provided', False)}`, empty `{hints.get('empty', False)}`, signals `{hints.get('signal_count', 0)}`",
        f"- Split review recommended: `{split.get('split_review_recommended')}`",
        f"- Ambiguous-term score: `{split.get('ambiguous_term_score')}`",
        f"- Dominant-document share: `{split.get('dominant_document_share')}`",
        "",
        "## Anchor Queries",
        "",
    ]
    anchors = report.get("anchor_query_pairs", [])
    if isinstance(anchors, list) and anchors:
        for item in anchors[:8]:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('id')}` {item.get('candidate_query')}")
    else:
        lines.append("- No anchor queries generated.")
    lines.extend(["", "## Next Steps", ""])
    for step in report.get("next_steps", []) if isinstance(report.get("next_steps"), list) else []:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def render_activation_plan_markdown(report: Mapping[str, Any]) -> str:
    """Render an activation plan as a compact review note."""

    recommendation = report.get("recommendation", {}) if isinstance(report.get("recommendation"), Mapping) else {}
    checks = report.get("checks", {}) if isinstance(report.get("checks"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow KB Activation Plan",
        "",
        f"- Schema: `{report.get('schema')}`",
        f"- KB: `{report.get('kb_name')}`",
        f"- Dataset: `{report.get('dataset_id')}`",
        f"- Recommendation: `{recommendation.get('action')}` ({recommendation.get('confidence')})",
        f"- Advisory only: `{report.get('advisory_only')}`",
        f"- Ingest plan provided: `{summary.get('ingest_plan_provided', False)}`",
        f"- Retrieval hints: provided `{summary.get('retrieval_hints_provided', False)}`, empty `{summary.get('retrieval_hints_empty', False)}`",
        "",
        "## Checks",
        "",
    ]
    for name in (
        "content_completeness",
        "chunk_readiness",
        "route_config_registration",
        "hint_coverage",
        "ingest_plan_consistency",
        "centroid_availability",
        "route_test_readiness",
    ):
        check = checks.get(name) if isinstance(checks.get(name), Mapping) else {}
        lines.append(f"- `{name}`: `{check.get('status', 'unknown')}`")
    suggestion = report.get("route_entry_suggestion", {})
    if isinstance(suggestion, Mapping):
        lines.extend(
            [
                "",
                "## Route Entry Suggestion",
                "",
                f"- name: `{suggestion.get('name')}`",
                f"- dataset_id: `{suggestion.get('dataset_id')}`",
                f"- hints: `{', '.join(suggestion.get('hints', [])) if isinstance(suggestion.get('hints'), list) else ''}`",
            ]
        )
    lines.extend(["", "## Next Steps", ""])
    for step in report.get("next_steps", []) if isinstance(report.get("next_steps"), list) else []:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def render_split_plan_markdown(report: Mapping[str, Any]) -> str:
    """Render a split plan as a compact review note."""

    recommendation = report.get("recommendation", {}) if isinstance(report.get("recommendation"), Mapping) else {}
    lines = [
        "# RAGFlow KB Split Plan",
        "",
        f"- Schema: `{report.get('schema')}`",
        f"- Source KB: `{report.get('kb_name')}`",
        f"- Recommendation: `{recommendation.get('action')}` ({recommendation.get('confidence')})",
        f"- Advisory only: `{report.get('advisory_only')}`",
        "",
        "## Split Groups",
        "",
    ]
    groups = report.get("split_groups", [])
    if isinstance(groups, list) and groups:
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            lines.append(
                "- "
                f"`{group.get('id')}` -> `{group.get('suggested_kb_name')}`; "
                f"docs `{group.get('document_count')}`, chunks `{group.get('estimated_chunk_count')}`, "
                f"action `{group.get('action')}`"
            )
    else:
        lines.append("- No split groups generated.")
    lines.extend(["", "## Boundary Queries", ""])
    boundaries = report.get("boundary_queries", [])
    if isinstance(boundaries, list) and boundaries:
        for item in boundaries[:8]:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('id')}` {item.get('query')}")
    else:
        lines.append("- No boundary queries generated.")
    lines.extend(["", "## Next Steps", ""])
    for step in report.get("next_steps", []) if isinstance(report.get("next_steps"), list) else []:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"
