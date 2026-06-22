"""Thin manifest dataclasses for skill handoffs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ManifestError(RuntimeError):
    """Raised when a handoff manifest is missing required fields."""


def _require_mapping(data: Any, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ManifestError(f"{name} must be a JSON object")
    return data


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"missing required string field: {key}")
    return value


def _read_json(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {manifest_path}") from exc
    return _require_mapping(data, str(manifest_path))


@dataclass(frozen=True)
class DocumentEntry:
    source_path: str
    markdown_path: str
    sha256: str | None = None
    title: str | None = None
    language: str | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentEntry":
        _require_mapping(data, "document")
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list) or not all(isinstance(x, str) for x in warnings):
            raise ManifestError("document.warnings must be a list of strings")
        return cls(
            source_path=_require_str(data, "source_path"),
            markdown_path=_require_str(data, "markdown_path"),
            sha256=data.get("sha256"),
            title=data.get("title"),
            language=data.get("language"),
            warnings=warnings,
        )


@dataclass(frozen=True)
class DocManifest:
    version: str
    created_at: str | None
    source_root: str | None
    documents: list[DocumentEntry]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocManifest":
        _require_mapping(data, "doc_manifest")
        raw_documents = data.get("documents")
        if not isinstance(raw_documents, list) or not raw_documents:
            raise ManifestError("doc_manifest.documents must be a non-empty list")
        return cls(
            version=_require_str(data, "version"),
            created_at=data.get("created_at"),
            source_root=data.get("source_root"),
            documents=[DocumentEntry.from_dict(item) for item in raw_documents],
        )


@dataclass(frozen=True)
class KbDataset:
    id: str
    name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KbDataset":
        _require_mapping(data, "dataset")
        return cls(id=_require_str(data, "id"), name=_require_str(data, "name"))


@dataclass(frozen=True)
class KbDocumentEntry:
    document_id: str
    source_path: str | None = None
    markdown_path: str | None = None
    status: str | None = None
    chunk_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KbDocumentEntry":
        _require_mapping(data, "kb_document")
        chunk_count = data.get("chunk_count")
        if chunk_count is not None and not isinstance(chunk_count, int):
            raise ManifestError("kb_document.chunk_count must be an integer when provided")
        return cls(
            document_id=_require_str(data, "document_id"),
            source_path=data.get("source_path"),
            markdown_path=data.get("markdown_path"),
            status=data.get("status"),
            chunk_count=chunk_count,
        )


@dataclass(frozen=True)
class KbManifest:
    version: str
    created_at: str | None
    ragflow_base_url: str | None
    dataset: KbDataset
    documents: list[KbDocumentEntry]
    profile: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KbManifest":
        _require_mapping(data, "kb_manifest")
        raw_documents = data.get("documents")
        if not isinstance(raw_documents, list):
            raise ManifestError("kb_manifest.documents must be a list")
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            raise ManifestError("kb_manifest.profile must be an object when provided")
        return cls(
            version=_require_str(data, "version"),
            created_at=data.get("created_at"),
            ragflow_base_url=data.get("ragflow_base_url"),
            dataset=KbDataset.from_dict(data.get("dataset", {})),
            documents=[KbDocumentEntry.from_dict(item) for item in raw_documents],
            profile=profile,
        )


def load_doc_manifest(path: str | Path) -> DocManifest:
    """Load and validate a document handoff manifest."""

    return DocManifest.from_dict(_read_json(path))


def load_kb_manifest(path: str | Path) -> KbManifest:
    """Load and validate a KB handoff manifest."""

    return KbManifest.from_dict(_read_json(path))
