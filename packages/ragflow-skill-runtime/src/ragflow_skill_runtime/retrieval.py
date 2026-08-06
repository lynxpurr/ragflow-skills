"""Retrieval normalization and dataset resolution helpers."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .manifests import KbManifest


class RetrievalError(RuntimeError):
    """Raised when query inputs or retrieval responses are invalid."""


@dataclass(frozen=True)
class NormalizedChunk:
    """Platform-neutral representation of one retrieved chunk."""

    content: str
    similarity: float | None = None
    document_name: str | None = None
    document_id: str | None = None
    dataset_id: str | None = None
    chunk_id: str | None = None
    important_keywords: list[str] = field(default_factory=list)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_raw:
            data.pop("raw", None)
        return data


@dataclass(frozen=True)
class QueryResult:
    """Normalized query result returned by public skill scripts."""

    question: str
    mode: str
    dataset_ids: list[str]
    chunks: list[NormalizedChunk]
    answer: str | None = None
    host_assisted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        return {
            "question": self.question,
            "mode": self.mode,
            "dataset_ids": self.dataset_ids,
            "chunks": [chunk.to_dict(include_raw=include_raw) for chunk in self.chunks],
            "answer": self.answer,
            "host_assisted": self.host_assisted,
            "metadata": self.metadata,
        }


CHUNK_HASH_ALGORITHM = "sha256:normalized-content-v1"
RETRIEVAL_STATUS_SCHEMA = "ragflow_retrieval_status_v1"
RETRIEVAL_STATUS_VALUES = (
    "success",
    "empty",
    "low_quality",
    "needs_refinement",
    "clarification",
    "rejected",
    "error",
    "timeout",
    "partial",
)
DEFAULT_MIN_RETRIEVAL_SIMILARITY = 0.15
DEFAULT_MIN_EVIDENCE_SCORE = 0.2


def normalize_chunk_content_for_hash(content: str | None) -> str:
    """Normalize chunk text before calculating stable content hashes."""

    return " ".join((content or "").split())


def stable_content_hash(content: str | None) -> str:
    """Return a stable content hash for chunk text."""

    normalized = normalize_chunk_content_for_hash(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def stable_chunk_hash(chunk: NormalizedChunk | Mapping[str, Any]) -> str:
    """Return the public stable-hash identifier for a normalized or raw chunk."""

    if isinstance(chunk, NormalizedChunk):
        content = chunk.content
    else:
        content = _first_str(chunk, ["content_with_weight", "content", "text", "page_content"]) or ""
    return f"sha256:{stable_content_hash(content)}"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_str(data: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _extract_chunks(response: Any) -> list[Mapping[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, Mapping)]
    if not isinstance(response, Mapping):
        raise RetrievalError("RAGFlow retrieval response must be an object or list")

    data = response.get("data", response)
    if isinstance(data, Mapping):
        chunks = data.get("chunks") or data.get("docs") or data.get("results")
    else:
        chunks = data

    if chunks is None:
        return []
    if not isinstance(chunks, list):
        raise RetrievalError("RAGFlow retrieval chunks must be a list")
    return [item for item in chunks if isinstance(item, Mapping)]


def normalize_chunk(chunk: Mapping[str, Any]) -> NormalizedChunk:
    """Normalize one RAGFlow chunk across field-name variants."""

    content = _first_str(chunk, ["content_with_weight", "content", "text", "page_content"]) or ""
    return NormalizedChunk(
        content=content,
        similarity=_as_float(chunk.get("similarity") or chunk.get("score")),
        document_name=_first_str(chunk, ["docnm_kwd", "document_name", "document_keyword", "doc_name"]),
        document_id=_first_str(chunk, ["doc_id", "document_id"]),
        dataset_id=_first_str(chunk, ["kb_id", "dataset_id"]),
        chunk_id=_first_str(chunk, ["id", "chunk_id"]),
        important_keywords=_keywords(chunk.get("important_keywords") or chunk.get("important_kwd")),
        raw=dict(chunk),
    )


def normalize_retrieval_response(response: Any) -> list[NormalizedChunk]:
    """Normalize a RAGFlow retrieval response into chunks."""

    return [normalize_chunk(chunk) for chunk in _extract_chunks(response)]


def _looks_like_timeout(error: BaseException | str | None) -> bool:
    if error is None:
        return False
    if isinstance(error, TimeoutError):
        return True
    text = str(error).lower()
    return "timed out" in text or "timeout" in text


def _top_similarity(chunks: Sequence[NormalizedChunk | Mapping[str, Any]]) -> float | None:
    values: list[float] = []
    for chunk in chunks:
        value = chunk.similarity if isinstance(chunk, NormalizedChunk) else chunk.get("similarity")
        parsed = _as_float(value)
        if parsed is not None:
            values.append(parsed)
    return max(values) if values else None


def _top_evidence_score(evidence: Sequence[Mapping[str, Any]] | None) -> float | None:
    values: list[float] = []
    for item in evidence or []:
        value = _as_float(item.get("score"))
        if value is not None:
            values.append(value)
    return max(values) if values else None


def _intent_status(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"clarification", "clarification_needed", "needs_clarification"}:
        return "clarification"
    if normalized in {"rejected", "reject", "out_of_scope"}:
        return "rejected"
    return None


def normalize_retrieval_status(
    *,
    chunks: Sequence[NormalizedChunk | Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    intent_status: str | None = None,
    error: BaseException | str | None = None,
    timed_out: bool = False,
    partial: bool = False,
    min_similarity: float = DEFAULT_MIN_RETRIEVAL_SIMILARITY,
    min_evidence_score: float = DEFAULT_MIN_EVIDENCE_SCORE,
) -> dict[str, Any]:
    """Return a normalized retrieval status report for orchestration layers."""

    chunk_items = list(chunks or [])
    evidence_items = [dict(item) for item in (evidence or []) if isinstance(item, Mapping)]
    top_similarity = _top_similarity(chunk_items)
    top_evidence_score = _top_evidence_score(evidence_items)
    mapped_intent_status = _intent_status(intent_status)
    reasons: list[str] = []

    if mapped_intent_status:
        status = mapped_intent_status
        reasons.append(f"intent route requested {mapped_intent_status}")
    elif timed_out or _looks_like_timeout(error):
        status = "timeout"
        reasons.append("retrieval timed out")
    elif error is not None:
        status = "error"
        reasons.append("retrieval raised an error")
    elif partial:
        status = "partial"
        reasons.append("only a subset of planned retrievals completed")
    elif not chunk_items:
        status = "empty"
        reasons.append("retrieval returned zero chunks")
    elif top_similarity is not None and top_similarity < min_similarity and (
        top_evidence_score is None or top_evidence_score < min_evidence_score
    ):
        status = "low_quality"
        reasons.append("top similarity is below the low-quality threshold")
    elif top_evidence_score is not None and top_evidence_score < min_evidence_score:
        status = "needs_refinement"
        reasons.append("top evidence score is below the refinement threshold")
    else:
        status = "success"
        reasons.append("retrieval returned usable evidence")

    return {
        "ok": status not in {"error", "timeout"},
        "schema": RETRIEVAL_STATUS_SCHEMA,
        "status": status,
        "allowed_statuses": list(RETRIEVAL_STATUS_VALUES),
        "reasons": reasons,
        "summary": {
            "chunk_count": len(chunk_items),
            "evidence_count": len(evidence_items),
            "top_similarity": top_similarity,
            "top_evidence_score": top_evidence_score,
            "partial": bool(partial),
            "timed_out": bool(timed_out) or _looks_like_timeout(error),
        },
        "thresholds": {
            "min_similarity": min_similarity,
            "min_evidence_score": min_evidence_score,
        },
    }


def dataset_ids_from_manifest(manifest: KbManifest) -> list[str]:
    """Return dataset IDs represented by a KB manifest."""

    return [manifest.dataset.id]


def _extract_dataset_items(response: Any) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping):
        return []
    data = response.get("data", response)
    if isinstance(data, Mapping):
        for key in ("docs", "datasets", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def resolve_dataset_ids(
    *,
    client: Any | None = None,
    dataset_ids: Iterable[str] | None = None,
    dataset_names: Iterable[str] | None = None,
    kb_manifest: KbManifest | None = None,
) -> list[str]:
    """Resolve dataset IDs from explicit IDs, names, or a KB manifest."""

    resolved: list[str] = []
    if dataset_ids:
        resolved.extend(str(item) for item in dataset_ids if str(item))
    if kb_manifest:
        resolved.extend(dataset_ids_from_manifest(kb_manifest))

    names = [str(item) for item in (dataset_names or []) if str(item)]
    if names:
        if client is None:
            raise RetrievalError("dataset name resolution requires a RAGFlow client")
        for name in names:
            response = client.list_datasets(name=name)
            matches = [
                item
                for item in _extract_dataset_items(response)
                if item.get("name") == name or item.get("name") == name.removeprefix("kb:")
            ]
            if not matches:
                raise RetrievalError(f"dataset not found by name: {name}")
            if len(matches) > 1:
                exact = [item for item in matches if item.get("name") == name]
                matches = exact or matches
            dataset_id = matches[0].get("id")
            if not isinstance(dataset_id, str) or not dataset_id:
                raise RetrievalError(f"dataset has no id: {name}")
            resolved.append(dataset_id)

    deduped: list[str] = []
    for dataset_id in resolved:
        if dataset_id not in deduped:
            deduped.append(dataset_id)
    if not deduped:
        raise RetrievalError("no dataset IDs provided; use --dataset-id, --kb, or --kb-manifest")
    return deduped
