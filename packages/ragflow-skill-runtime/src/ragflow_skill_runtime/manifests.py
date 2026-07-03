"""Thin manifest dataclasses for skill handoffs."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


DOC_MANIFEST_JSON_SCHEMA_ID = "https://github.com/lynxpurr/ragflow-skills/schemas/doc_manifest-0.1.schema.json"
KB_MANIFEST_JSON_SCHEMA_ID = "https://github.com/lynxpurr/ragflow-skills/schemas/kb_manifest-0.1.schema.json"

DOC_MANIFEST_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": DOC_MANIFEST_JSON_SCHEMA_ID,
    "title": "RAGFlow document handoff manifest",
    "type": "object",
    "required": ["version", "documents"],
    "additionalProperties": True,
    "properties": {
        "version": {"type": "string", "const": "0.1"},
        "created_at": {"type": ["string", "null"]},
        "source_root": {"type": ["string", "null"]},
        "handoff_mode": {"type": ["string", "null"], "enum": ["thin_preview", "formal_ingest", None]},
        "handoff_advisory": {
            "type": ["array", "null"],
            "items": {"type": "object", "additionalProperties": True},
        },
        "formal_ingest": {"type": ["object", "null"], "additionalProperties": True},
        "quality_report": {"type": ["string", "null"]},
        "quality_gate": {"type": ["object", "null"], "additionalProperties": True},
        "documents": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["source_path", "markdown_path"],
                "additionalProperties": True,
                "properties": {
                    "source_path": {"type": "string", "minLength": 1},
                    "markdown_path": {"type": "string", "minLength": 1},
                    "sha256": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "language": {"type": ["string", "null"]},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "assets": {
                        "type": ["object", "null"],
                        "additionalProperties": True,
                        "properties": {
                            "images": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["path"],
                                    "additionalProperties": True,
                                    "properties": {
                                        "path": {"type": "string", "minLength": 1},
                                        "sha256": {"type": ["string", "null"]},
                                        "bytes": {"type": ["integer", "null"], "minimum": 0},
                                    },
                                },
                            }
                        },
                    },
                },
            },
        },
    },
}

KB_MANIFEST_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": KB_MANIFEST_JSON_SCHEMA_ID,
    "title": "RAGFlow KB handoff manifest",
    "type": "object",
    "required": ["version", "dataset", "documents"],
    "additionalProperties": True,
    "properties": {
        "version": {"type": "string", "const": "0.1"},
        "created_at": {"type": ["string", "null"]},
        "ragflow_base_url": {"type": ["string", "null"]},
        "dataset": {
            "type": "object",
            "required": ["id", "name"],
            "additionalProperties": True,
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
            },
        },
        "profile": {"type": "object", "additionalProperties": True},
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["document_id"],
                "additionalProperties": True,
                "properties": {
                    "document_id": {"type": "string", "minLength": 1},
                    "source_path": {"type": ["string", "null"]},
                    "markdown_path": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                    "chunk_count": {"type": ["integer", "null"], "minimum": 0},
                },
            },
        },
    },
}


class ManifestError(RuntimeError):
    """Raised when a handoff manifest is missing required fields."""


def manifest_json_schemas() -> dict[str, dict[str, Any]]:
    """Return the public JSON Schema contracts for primary handoff manifests."""

    return {
        "doc_manifest": deepcopy(DOC_MANIFEST_JSON_SCHEMA),
        "kb_manifest": deepcopy(KB_MANIFEST_JSON_SCHEMA),
    }


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return False


def validate_payload_with_json_schema(
    payload: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "$",
) -> None:
    """Validate payloads against the JSON Schema subset used by public manifests."""

    expected = schema.get("type")
    expected_types: list[str]
    if isinstance(expected, str):
        expected_types = [expected]
    elif isinstance(expected, list) and all(isinstance(item, str) for item in expected):
        expected_types = list(expected)
    else:
        expected_types = []
    if expected_types and not any(_json_type_matches(payload, item) for item in expected_types):
        raise ManifestError(f"{path} must be one of: {', '.join(expected_types)}")

    if "const" in schema and payload != schema["const"]:
        raise ManifestError(f"{path} must equal {schema['const']!r}")

    if isinstance(payload, str) and "minLength" in schema and len(payload) < int(schema["minLength"]):
        raise ManifestError(f"{path} must contain at least {schema['minLength']} characters")

    if isinstance(payload, int) and not isinstance(payload, bool) and "minimum" in schema:
        if payload < int(schema["minimum"]):
            raise ManifestError(f"{path} must be greater than or equal to {schema['minimum']}")

    if isinstance(payload, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ManifestError(f"{path}.required must be a list")
        for key in required:
            if not isinstance(key, str):
                raise ManifestError(f"{path}.required entries must be strings")
            if key not in payload:
                raise ManifestError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ManifestError(f"{path}.properties must be an object")
        additional_properties = schema.get("additionalProperties", True)
        for key, value in payload.items():
            if key in properties:
                child_schema = properties[key]
                if not isinstance(child_schema, Mapping):
                    raise ManifestError(f"{path}.{key} schema must be an object")
                validate_payload_with_json_schema(value, child_schema, path=f"{path}.{key}")
            elif additional_properties is False:
                raise ManifestError(f"{path}.{key} is not allowed")

    if isinstance(payload, list):
        if "minItems" in schema and len(payload) < int(schema["minItems"]):
            raise ManifestError(f"{path} must contain at least {schema['minItems']} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(payload):
                validate_payload_with_json_schema(item, item_schema, path=f"{path}[{index}]")


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
    quality_report: str | None = None
    quality_gate: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocManifest":
        _require_mapping(data, "doc_manifest")
        raw_documents = data.get("documents")
        if not isinstance(raw_documents, list) or not raw_documents:
            raise ManifestError("doc_manifest.documents must be a non-empty list")
        quality_gate = data.get("quality_gate", {})
        if quality_gate is None:
            quality_gate = {}
        if not isinstance(quality_gate, dict):
            raise ManifestError("doc_manifest.quality_gate must be an object when provided")
        quality_report = data.get("quality_report")
        if quality_report is not None and not isinstance(quality_report, str):
            raise ManifestError("doc_manifest.quality_report must be a string when provided")
        return cls(
            version=_require_str(data, "version"),
            created_at=data.get("created_at"),
            source_root=data.get("source_root"),
            documents=[DocumentEntry.from_dict(item) for item in raw_documents],
            quality_report=quality_report,
            quality_gate=quality_gate,
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
