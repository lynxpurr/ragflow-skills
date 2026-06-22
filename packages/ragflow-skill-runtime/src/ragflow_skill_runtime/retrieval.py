"""Retrieval normalization and dataset resolution helpers."""

from __future__ import annotations

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
