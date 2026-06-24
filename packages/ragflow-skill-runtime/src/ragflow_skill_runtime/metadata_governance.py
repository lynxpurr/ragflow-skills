"""Public metadata and tagset governance helpers for RAGFlow skills."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import ConfigError, read_config_file
from .doc_segment import SEGMENTATION_SCHEMA
from .manifests import load_doc_manifest
from .validation import ValidationError, load_chunk_snapshot


RAGFLOW_METADATA_SCHEMA = "ragflow_metadata_v1"
RAGFLOW_TAGSET_SCHEMA = "ragflow_tagset_v1"
METADATA_LINT_REPORT_SCHEMA = "ragflow_metadata_lint_report_v1"
METADATA_MERGE_REPORT_SCHEMA = "ragflow_metadata_merge_report_v1"
TAGSET_LINT_REPORT_SCHEMA = "ragflow_tagset_lint_report_v1"
TAGSET_REPORT_SCHEMA = "ragflow_tagset_report_v1"
TAGSET_EXPORT_SCHEMA = "ragflow_tagset_export_v1"
SEGMENT_METADATA_REPORT_SCHEMA = "ragflow_segment_metadata_report_v1"

SAFE_METADATA_FIELDS = {
    "domain",
    "topic",
    "module",
    "doc_type",
    "audience",
    "question_types",
    "entities",
    "summary",
    "locale",
    "status",
    "source_uri",
    "source_hash",
}
LIST_METADATA_FIELDS = {"question_types", "entities"}
STRING_METADATA_FIELDS = SAFE_METADATA_FIELDS - LIST_METADATA_FIELDS
DOCUMENT_STRUCTURAL_FIELDS = {"path", "markdown_path", "source_path", "metadata", "metadata_sources", "tags"}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(api[_-]?key|token|secret|authorization)\s*[:=]\s*\S+"),
)
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
SEGMENT_PATH_RE = re.compile(r"(?:^|[\\/])?[^\\/]+\.part-\d{3,}\.md$", re.IGNORECASE)


class MetadataGovernanceError(RuntimeError):
    """Raised when metadata or tagset governance inputs are invalid."""


@dataclass(frozen=True)
class GovernanceIssue:
    severity: str
    code: str
    message: str
    field: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MetadataGovernanceError(f"file not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise MetadataGovernanceError(f"file is not valid JSON: {source}") from exc
    else:
        try:
            data = read_config_file(source)
        except ConfigError as exc:
            raise MetadataGovernanceError(str(exc)) from exc
    if not isinstance(data, dict):
        raise MetadataGovernanceError(f"file must contain a JSON object: {source}")
    return data


def _issue_counts(issues: Iterable[GovernanceIssue]) -> dict[str, int]:
    items = list(issues)
    return {
        "errors": sum(1 for issue in items if issue.severity == "error"),
        "warnings": sum(1 for issue in items if issue.severity == "warning"),
        "infos": sum(1 for issue in items if issue.severity == "info"),
    }


def _ok(issues: Iterable[GovernanceIssue]) -> bool:
    return not any(issue.severity == "error" for issue in issues)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_secret(item) for item in value.values())
    return False


def _coerce_string_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return None


def _normalize_safe_metadata(raw: Mapping[str, Any], *, field_prefix: str, issues: list[GovernanceIssue]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in raw.items():
        field = f"{field_prefix}.{key}" if field_prefix else key
        if key not in SAFE_METADATA_FIELDS:
            issues.append(
                GovernanceIssue(
                    severity="warning",
                    code="metadata_field_not_public",
                    field=field,
                    message="metadata field is not in the public safe-field allowlist and will be ignored",
                    recommendation="Use a safe field such as domain, topic, module, doc_type, audience, entities, or source_hash.",
                )
            )
            if _contains_secret(value):
                issues.append(
                    GovernanceIssue(
                        severity="error",
                        code="metadata_value_looks_secret",
                        field=field,
                        message="metadata value appears to contain a secret",
                        recommendation="Move secrets to the host agent secret store or environment variables.",
                    )
                )
            continue
        if key in LIST_METADATA_FIELDS:
            coerced = _coerce_string_list(value)
            if coerced is None:
                issues.append(
                    GovernanceIssue(
                        severity="error",
                        code="metadata_list_field_invalid",
                        field=field,
                        message=f"{key} must be a string or list of strings",
                    )
                )
                continue
            metadata[key] = coerced
        else:
            if value in (None, ""):
                continue
            if not isinstance(value, str):
                issues.append(
                    GovernanceIssue(
                        severity="error",
                        code="metadata_string_field_invalid",
                        field=field,
                        message=f"{key} must be a string",
                    )
                )
                continue
            metadata[key] = value.strip()
            if key == "source_hash" and metadata[key] and not SHA256_RE.match(metadata[key]):
                issues.append(
                    GovernanceIssue(
                        severity="warning",
                        code="source_hash_not_sha256",
                        field=field,
                        message="source_hash does not look like a SHA-256 hex digest",
                    )
                )
        if _contains_secret(value):
            issues.append(
                GovernanceIssue(
                    severity="error",
                    code="metadata_value_looks_secret",
                    field=field,
                    message="metadata value appears to contain a secret",
                    recommendation="Remove the secret from metadata and use private config or environment variables.",
                )
            )
    return metadata


def _metadata_path(document: Mapping[str, Any]) -> str:
    for key in ("path", "markdown_path", "source_path"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_documents(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    documents = payload.get("documents", [])
    if documents is None:
        return []
    if not isinstance(documents, list):
        raise MetadataGovernanceError("metadata.documents must be a list")
    return [item for item in documents if isinstance(item, Mapping)]


def _normalize_metadata_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[GovernanceIssue]]:
    issues: list[GovernanceIssue] = []
    schema = payload.get("schema")
    if schema not in {None, RAGFLOW_METADATA_SCHEMA}:
        issues.append(
            GovernanceIssue(
                severity="error",
                code="metadata_schema_invalid",
                field="schema",
                message=f"metadata schema must be {RAGFLOW_METADATA_SCHEMA}",
            )
        )
    defaults_raw = payload.get("defaults", {})
    if defaults_raw is None:
        defaults_raw = {}
    if not isinstance(defaults_raw, Mapping):
        issues.append(GovernanceIssue("error", "metadata_defaults_invalid", "defaults must be an object", "defaults"))
        defaults_raw = {}
    defaults = _normalize_safe_metadata(defaults_raw, field_prefix="defaults", issues=issues)

    documents = []
    seen_paths: set[str] = set()
    for index, item in enumerate(_metadata_documents(payload)):
        path = _metadata_path(item)
        field_prefix = f"documents[{index}]"
        if not path:
            issues.append(
                GovernanceIssue(
                    severity="error",
                    code="metadata_document_path_missing",
                    field=field_prefix,
                    message="metadata document requires path, markdown_path, or source_path",
                )
            )
            continue
        if path in seen_paths:
            issues.append(
                GovernanceIssue(
                    severity="warning",
                    code="metadata_document_duplicate_path",
                    field=f"{field_prefix}.path",
                    message="metadata contains duplicate document paths; later entries should be merged explicitly",
                )
            )
        seen_paths.add(path)
        nested = item.get("metadata", {})
        if nested is None:
            nested = {}
        if not isinstance(nested, Mapping):
            issues.append(
                GovernanceIssue(
                    severity="error",
                    code="metadata_document_metadata_invalid",
                    field=f"{field_prefix}.metadata",
                    message="document metadata must be an object",
                )
            )
            nested = {}
        direct = {key: item[key] for key in SAFE_METADATA_FIELDS if key in item}
        structural_unknown = set(item) - DOCUMENT_STRUCTURAL_FIELDS - SAFE_METADATA_FIELDS
        for key in sorted(structural_unknown):
            issues.append(
                GovernanceIssue(
                    severity="warning",
                    code="metadata_document_field_ignored",
                    field=f"{field_prefix}.{key}",
                    message="document field is not part of the public metadata schema and will be ignored",
                )
            )
        metadata = {
            **defaults,
            **_normalize_safe_metadata(direct, field_prefix=field_prefix, issues=issues),
            **_normalize_safe_metadata(nested, field_prefix=f"{field_prefix}.metadata", issues=issues),
        }
        tags = _coerce_string_list(item.get("tags", []))
        if tags is None:
            issues.append(
                GovernanceIssue(
                    severity="error",
                    code="metadata_document_tags_invalid",
                    field=f"{field_prefix}.tags",
                    message="tags must be a string or list of strings",
                )
            )
            tags = []
        documents.append({"path": path, "metadata": metadata, "tags": tags})

    normalized = {
        "schema": RAGFLOW_METADATA_SCHEMA,
        "created_at": str(payload.get("created_at") or _now()),
        "document_count": len(documents),
        "defaults": defaults,
        "documents": documents,
        "advisory": True,
    }
    return normalized, issues


def load_metadata(path: str | Path) -> dict[str, Any]:
    """Load and normalize public RAGFlow metadata."""

    normalized, issues = _normalize_metadata_payload(_read_mapping(path))
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise MetadataGovernanceError("; ".join(issue.message for issue in errors[:3]))
    return normalized


def lint_metadata_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Lint public metadata and return a JSON-first report."""

    normalized, issues = _normalize_metadata_payload(payload)
    return {
        "ok": _ok(issues),
        "schema": METADATA_LINT_REPORT_SCHEMA,
        "metadata_schema": normalized["schema"],
        "summary": {
            **_issue_counts(issues),
            "document_count": normalized["document_count"],
            "safe_fields": sorted(SAFE_METADATA_FIELDS),
        },
        "issues": [issue.to_dict() for issue in issues],
        "normalized_preview": _redact(normalized),
    }


def lint_metadata_file(path: str | Path) -> dict[str, Any]:
    """Load and lint a metadata file."""

    return lint_metadata_payload(_read_mapping(path))


def _doc_manifest_entries(doc_manifest_path: str | Path | None) -> list[dict[str, str]]:
    if not doc_manifest_path:
        return []
    manifest = load_doc_manifest(doc_manifest_path)
    return [
        {
            "path": entry.markdown_path,
            "source_path": entry.source_path,
            "title": entry.title or "",
            "language": entry.language or "",
            "sha256": entry.sha256 or "",
        }
        for entry in manifest.documents
    ]


def _derive_metadata_from_path(path: str) -> dict[str, Any]:
    clean = Path(path)
    parts = [part for part in clean.with_suffix("").parts if part not in {".", "documents"}]
    metadata: dict[str, Any] = {"doc_type": "markdown", "module": clean.stem}
    if len(parts) >= 2:
        metadata["topic"] = parts[-2]
    if len(parts) >= 3:
        metadata["domain"] = parts[0]
    return metadata


def _metadata_from_handoff_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("schema") != "ragflow_document_metadata_v1":
        return {}
    results: dict[str, dict[str, Any]] = {}
    documents = payload.get("documents", [])
    if not isinstance(documents, list):
        return results
    for item in documents:
        if not isinstance(item, Mapping):
            continue
        path = ""
        markdown = item.get("markdown", {})
        if isinstance(markdown, Mapping) and isinstance(markdown.get("path"), str):
            path = markdown["path"]
        if not path and isinstance(item.get("markdown_path"), str):
            path = item["markdown_path"]
        if not path:
            continue
        metadata: dict[str, Any] = {}
        if isinstance(item.get("title"), str) and item["title"].strip():
            metadata["topic"] = item["title"].strip()
        if isinstance(item.get("locale"), str) and item["locale"].strip():
            metadata["locale"] = item["locale"].strip()
        source_format = item.get("source_format")
        if isinstance(source_format, str) and source_format.strip():
            metadata["doc_type"] = source_format.strip()
        source_hash = item.get("source_sha256")
        if isinstance(source_hash, str) and source_hash.strip():
            metadata["source_hash"] = source_hash.strip()
        results[path] = metadata
    return results


def _metadata_index(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    normalized, _issues = _normalize_metadata_payload(payload)
    return {
        str(document["path"]): dict(document.get("metadata", {}))
        for document in normalized.get("documents", [])
        if isinstance(document, Mapping)
    }


def make_metadata_template_payload(*, doc_manifest_path: str | Path | None = None) -> dict[str, Any]:
    """Create a placeholder-only user-editable metadata template."""

    entries = _doc_manifest_entries(doc_manifest_path)
    if not entries:
        entries = [{"path": "documents/example.md", "source_path": "source/example.pdf", "title": "", "language": "", "sha256": ""}]
    documents = []
    for entry in entries:
        path = entry["path"]
        documents.append(
            {
                "path": path,
                "metadata": {
                    "domain": "example-domain",
                    "topic": entry["title"] or "example-topic",
                    "module": Path(path).stem or "example-module",
                    "doc_type": "manual",
                    "audience": "example-audience",
                    "question_types": ["fact"],
                    "entities": ["ExampleEntity"],
                    "summary": "Replace this placeholder summary before use.",
                    "locale": entry["language"] or "en",
                    "status": "draft",
                    "source_uri": "https://example.com/source",
                    "source_hash": entry["sha256"] or "0" * 64,
                },
                "tags": ["example-tag"],
            }
        )
    return {
        "schema": RAGFLOW_METADATA_SCHEMA,
        "created_at": _now(),
        "defaults": {},
        "documents": documents,
        "advisory": True,
    }


def merge_metadata_payloads(
    *,
    doc_manifest_path: str | Path | None = None,
    handoff_metadata_path: str | Path | None = None,
    user_metadata_path: str | Path | None = None,
    derive_from_path: bool = True,
) -> dict[str, Any]:
    """Merge path-derived, rich-handoff, and user metadata into a public schema."""

    entries = _doc_manifest_entries(doc_manifest_path)
    if not entries and user_metadata_path:
        user_payload = _read_mapping(user_metadata_path)
        entries = [{"path": path, "source_path": "", "title": "", "language": "", "sha256": ""} for path in _metadata_index(user_payload)]
    handoff_index = _metadata_from_handoff_payload(_read_mapping(handoff_metadata_path)) if handoff_metadata_path else {}
    user_index = _metadata_index(_read_mapping(user_metadata_path)) if user_metadata_path else {}

    all_paths = []
    for path in [entry["path"] for entry in entries] + list(handoff_index) + list(user_index):
        if path and path not in all_paths:
            all_paths.append(path)
    if not all_paths:
        raise MetadataGovernanceError("no documents found to merge; provide --doc-manifest or --metadata")

    conflicts: list[dict[str, Any]] = []
    documents = []
    for path in all_paths:
        layers: list[tuple[str, dict[str, Any]]] = []
        if derive_from_path:
            layers.append(("path", _derive_metadata_from_path(path)))
        if path in handoff_index:
            layers.append(("handoff", handoff_index[path]))
        if path in user_index:
            layers.append(("user", user_index[path]))

        merged: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for source, metadata in layers:
            for field, value in metadata.items():
                if field in merged and merged[field] != value:
                    conflicts.append(
                        {
                            "path": path,
                            "field": field,
                            "kept_source": source,
                            "previous_source": sources.get(field),
                            "previous_value": _redact(merged[field]),
                            "kept_value": _redact(value),
                        }
                    )
                merged[field] = value
                sources[field] = source
        documents.append({"path": path, "metadata": merged, "metadata_sources": sources})

    payload = {
        "schema": RAGFLOW_METADATA_SCHEMA,
        "created_at": _now(),
        "document_count": len(documents),
        "defaults": {},
        "documents": documents,
        "advisory": True,
    }
    lint_report = lint_metadata_payload(payload)
    return {
        "ok": lint_report["ok"],
        "schema": METADATA_MERGE_REPORT_SCHEMA,
        "metadata": payload,
        "summary": {
            "document_count": len(documents),
            "conflict_count": len(conflicts),
            "errors": lint_report["summary"]["errors"],
            "warnings": lint_report["summary"]["warnings"],
        },
        "conflicts": conflicts,
        "issues": lint_report["issues"],
    }


def summarize_metadata_for_documents(metadata_path: str | Path | None, documents: Iterable[str | Path]) -> dict[str, Any] | None:
    """Return a small metadata summary for build/validation reports."""

    if not metadata_path:
        return None
    report = lint_metadata_file(metadata_path)
    normalized = report.get("normalized_preview", {})
    metadata_docs = normalized.get("documents", []) if isinstance(normalized, Mapping) else []
    by_path = {str(item.get("path")): item for item in metadata_docs if isinstance(item, Mapping)}
    doc_paths = [str(path) for path in documents]
    matched = sum(1 for path in doc_paths if path in by_path or Path(path).as_posix() in by_path)
    fields: set[str] = set()
    tags: set[str] = set()
    for item in metadata_docs:
        if not isinstance(item, Mapping):
            continue
        metadata = item.get("metadata", {})
        if isinstance(metadata, Mapping):
            fields.update(str(key) for key in metadata)
        for tag in item.get("tags", []) if isinstance(item.get("tags"), list) else []:
            tags.add(str(tag))
    return {
        "schema": "ragflow_metadata_summary_v1",
        "ok": report["ok"],
        "metadata_path": str(metadata_path),
        "document_count": len(metadata_docs),
        "matched_build_documents": matched,
        "field_count": len(fields),
        "fields": sorted(fields),
        "tag_count": len(tags),
        "tags": sorted(tags),
        "issues": report["summary"],
    }


def make_tagset_template_payload() -> dict[str, Any]:
    """Create a placeholder-only tagset template."""

    return {
        "schema": RAGFLOW_TAGSET_SCHEMA,
        "created_at": _now(),
        "tags": [
            {
                "name": "example-tag",
                "label": "Example Tag",
                "description": "Replace this placeholder tag before use.",
                "aliases": ["example"],
                "metadata_defaults": {"domain": "example-domain"},
            }
        ],
        "assignments": [{"path": "documents/example.md", "tags": ["example-tag"]}],
    }


def _normalize_tagset(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[GovernanceIssue]]:
    issues: list[GovernanceIssue] = []
    schema = payload.get("schema")
    if schema not in {None, RAGFLOW_TAGSET_SCHEMA}:
        issues.append(GovernanceIssue("error", "tagset_schema_invalid", f"tagset schema must be {RAGFLOW_TAGSET_SCHEMA}", "schema"))
    raw_tags = payload.get("tags", [])
    raw_assignments = payload.get("assignments", [])
    if not isinstance(raw_tags, list):
        issues.append(GovernanceIssue("error", "tagset_tags_invalid", "tags must be a list", "tags"))
        raw_tags = []
    if not isinstance(raw_assignments, list):
        issues.append(GovernanceIssue("error", "tagset_assignments_invalid", "assignments must be a list", "assignments"))
        raw_assignments = []

    tags = []
    seen: dict[str, int] = {}
    for index, item in enumerate(raw_tags):
        field_prefix = f"tags[{index}]"
        if not isinstance(item, Mapping):
            issues.append(GovernanceIssue("error", "tag_invalid", "tag entries must be objects", field_prefix))
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            issues.append(GovernanceIssue("error", "tag_name_missing", "tag requires a name", f"{field_prefix}.name"))
            continue
        canonical = name.lower()
        if canonical in seen:
            issues.append(GovernanceIssue("warning", "tag_duplicate_name", "tag name is duplicated case-insensitively", f"{field_prefix}.name"))
        seen[canonical] = index
        if not TAG_NAME_RE.match(name):
            issues.append(GovernanceIssue("error", "tag_name_invalid", "tag name must be 1-64 chars using letters, digits, _, ., :, or -", f"{field_prefix}.name"))
        aliases = _coerce_string_list(item.get("aliases", []))
        if aliases is None:
            issues.append(GovernanceIssue("error", "tag_aliases_invalid", "aliases must be a string or list of strings", f"{field_prefix}.aliases"))
            aliases = []
        defaults_raw = item.get("metadata_defaults", {})
        if defaults_raw is None:
            defaults_raw = {}
        if not isinstance(defaults_raw, Mapping):
            issues.append(GovernanceIssue("error", "tag_metadata_defaults_invalid", "metadata_defaults must be an object", f"{field_prefix}.metadata_defaults"))
            defaults_raw = {}
        metadata_defaults = _normalize_safe_metadata(defaults_raw, field_prefix=f"{field_prefix}.metadata_defaults", issues=issues)
        description = item.get("description", "")
        label = item.get("label", name)
        tags.append(
            {
                "name": name,
                "label": str(label).strip() if label is not None else name,
                "description": str(description).strip() if description is not None else "",
                "aliases": aliases,
                "metadata_defaults": metadata_defaults,
            }
        )

    tag_names = {tag["name"] for tag in tags}
    assignments = []
    for index, item in enumerate(raw_assignments):
        field_prefix = f"assignments[{index}]"
        if not isinstance(item, Mapping):
            issues.append(GovernanceIssue("error", "assignment_invalid", "assignment entries must be objects", field_prefix))
            continue
        path = str(item.get("path", "")).strip()
        assigned = _coerce_string_list(item.get("tags", []))
        if not path:
            issues.append(GovernanceIssue("error", "assignment_path_missing", "assignment requires a path", f"{field_prefix}.path"))
        if assigned is None:
            issues.append(GovernanceIssue("error", "assignment_tags_invalid", "assignment tags must be a string or list of strings", f"{field_prefix}.tags"))
            assigned = []
        for tag in assigned:
            if tag not in tag_names:
                issues.append(GovernanceIssue("warning", "assignment_orphan_tag", "assignment references a tag not present in tagset.tags", f"{field_prefix}.tags"))
        if path:
            assignments.append({"path": path, "tags": assigned})

    normalized = {
        "schema": RAGFLOW_TAGSET_SCHEMA,
        "created_at": str(payload.get("created_at") or _now()),
        "tag_count": len(tags),
        "assignment_count": len(assignments),
        "tags": tags,
        "assignments": assignments,
    }
    return normalized, issues


def lint_tagset_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Lint a public tagset payload."""

    normalized, issues = _normalize_tagset(payload)
    return {
        "ok": _ok(issues),
        "schema": TAGSET_LINT_REPORT_SCHEMA,
        "tagset_schema": normalized["schema"],
        "summary": {
            **_issue_counts(issues),
            "tag_count": normalized["tag_count"],
            "assignment_count": normalized["assignment_count"],
        },
        "issues": [issue.to_dict() for issue in issues],
        "normalized_preview": _redact(normalized),
    }


def lint_tagset_file(path: str | Path) -> dict[str, Any]:
    """Load and lint a tagset file."""

    return lint_tagset_payload(_read_mapping(path))


def tagset_report_payload(payload: Mapping[str, Any], *, metadata_path: str | Path | None = None) -> dict[str, Any]:
    """Create a coverage, duplicate, and orphan warning report for a tagset."""

    lint_report = lint_tagset_payload(payload)
    normalized = lint_report["normalized_preview"]
    tags = normalized.get("tags", []) if isinstance(normalized, Mapping) else []
    assignments = normalized.get("assignments", []) if isinstance(normalized, Mapping) else []
    assigned_docs = {assignment["path"] for assignment in assignments if isinstance(assignment, Mapping)}
    assigned_tags = {
        tag
        for assignment in assignments
        if isinstance(assignment, Mapping)
        for tag in assignment.get("tags", [])
        if isinstance(tag, str)
    }
    tag_names = {tag["name"] for tag in tags if isinstance(tag, Mapping)}
    metadata_docs: set[str] = set()
    if metadata_path:
        metadata = load_metadata(metadata_path)
        metadata_docs = {str(item["path"]) for item in metadata.get("documents", []) if isinstance(item, Mapping)}
    return {
        "ok": lint_report["ok"],
        "schema": TAGSET_REPORT_SCHEMA,
        "summary": {
            **lint_report["summary"],
            "assigned_document_count": len(assigned_docs),
            "assigned_tag_count": len(assigned_tags),
            "unused_tag_count": len(tag_names - assigned_tags),
            "orphan_tag_count": len(assigned_tags - tag_names),
            "metadata_document_count": len(metadata_docs),
            "unassigned_metadata_document_count": len(metadata_docs - assigned_docs) if metadata_docs else 0,
        },
        "unused_tags": sorted(tag_names - assigned_tags),
        "orphan_tags": sorted(assigned_tags - tag_names),
        "unassigned_metadata_documents": sorted(metadata_docs - assigned_docs) if metadata_docs else [],
        "issues": lint_report["issues"],
    }


def tagset_report_file(path: str | Path, *, metadata_path: str | Path | None = None) -> dict[str, Any]:
    """Load a tagset and return its report."""

    return tagset_report_payload(_read_mapping(path), metadata_path=metadata_path)


def _coverage_rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _path_match_keys(value: Any) -> set[str]:
    if not isinstance(value, str) or not value.strip():
        return set()
    clean = value.replace("\\", "/").strip()
    keys = {clean.lower()}
    name = Path(clean).name
    if name:
        keys.add(name.lower())
    return {key for key in keys if key}


def _chunk_document_keys(chunk: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("document", "document_name", "document_id", "source", "source_path", "path", "file", "filename"):
        keys.update(_path_match_keys(chunk.get(field)))
    return keys


def _chunk_has_segment_hint(chunk: Mapping[str, Any]) -> bool:
    for field in ("segment_id", "segment_index", "segment_title", "segment_path", "source_segment"):
        value = chunk.get(field)
        if value not in (None, ""):
            return True
    return any(SEGMENT_PATH_RE.search(key) for key in _chunk_document_keys(chunk))


def _metadata_document_index(metadata_path: str | Path | None, issues: list[GovernanceIssue]) -> tuple[set[str], int]:
    if not metadata_path:
        return set(), 0
    report = lint_metadata_file(metadata_path)
    for raw_issue in report.get("issues", []):
        if not isinstance(raw_issue, Mapping):
            continue
        issues.append(
            GovernanceIssue(
                severity=str(raw_issue.get("severity", "warning")),
                code=f"metadata_{raw_issue.get('code', 'issue')}",
                message=str(raw_issue.get("message", "")),
                field=raw_issue.get("field") if isinstance(raw_issue.get("field"), str) else None,
                recommendation=raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
            )
        )
    normalized = report.get("normalized_preview", {})
    documents = normalized.get("documents", []) if isinstance(normalized, Mapping) else []
    keys: set[str] = set()
    count = 0
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        count += 1
        for field in ("path", "markdown_path", "source_path"):
            keys.update(_path_match_keys(document.get(field)))
    return keys, count


def _segmentation_plan_index(
    segmentation_plan_path: str | Path | None,
    issues: list[GovernanceIssue],
) -> tuple[set[str], dict[str, set[str]], int]:
    if not segmentation_plan_path:
        return set(), {}, 0
    raw = _read_mapping(segmentation_plan_path)
    plan = raw.get("segmentation_plan") if isinstance(raw.get("segmentation_plan"), Mapping) else raw
    if plan.get("schema") != SEGMENTATION_SCHEMA:
        issues.append(
            GovernanceIssue(
                "error",
                "segmentation_plan_schema_invalid",
                f"segmentation plan schema must be {SEGMENTATION_SCHEMA}",
                "segmentation_plan.schema",
            )
        )
        return set(), {}, 0
    raw_segments = plan.get("segments", [])
    if not isinstance(raw_segments, list):
        issues.append(GovernanceIssue("error", "segmentation_plan_segments_invalid", "segments must be a list", "segments"))
        return set(), {}, 0
    segment_index: dict[str, set[str]] = {}
    all_keys: set[str] = set()
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, Mapping):
            issues.append(GovernanceIssue("error", "segmentation_plan_segment_invalid", "segment must be an object", f"segments[{index}]"))
            continue
        segment_id = str(segment.get("index") or index + 1)
        keys = set()
        keys.update(_path_match_keys(segment.get("suggested_markdown_path")))
        keys.update(_path_match_keys(segment.get("path")))
        keys.update(_path_match_keys(segment.get("markdown_path")))
        for key in keys:
            segment_index.setdefault(key, set()).add(segment_id)
        all_keys.update(keys)
    return all_keys, segment_index, len(raw_segments)


def segment_metadata_report_file(
    *,
    chunk_snapshot_path: str | Path,
    metadata_path: str | Path | None = None,
    segmentation_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    """Report segment provenance and metadata coverage for chunk snapshots."""

    issues: list[GovernanceIssue] = []
    try:
        snapshot = load_chunk_snapshot(chunk_snapshot_path)
    except ValidationError as exc:
        raise MetadataGovernanceError(str(exc)) from exc

    metadata_keys, metadata_document_count = _metadata_document_index(metadata_path, issues)
    segment_keys, segment_index, segment_count = _segmentation_plan_index(segmentation_plan_path, issues)
    raw_chunks = snapshot.get("chunks")
    chunks = [chunk for chunk in raw_chunks if isinstance(chunk, Mapping)] if isinstance(raw_chunks, list) else []
    if not chunks:
        issues.append(GovernanceIssue("error", "chunk_snapshot_empty", "chunk snapshot does not contain any chunks", "chunk_snapshot"))

    chunk_reports: list[dict[str, Any]] = []
    chunks_with_document_name = 0
    chunks_with_document_id = 0
    chunks_with_metadata = 0
    chunks_with_segment_hint = 0
    chunks_matching_plan = 0
    matched_segments: set[str] = set()

    for index, chunk in enumerate(chunks):
        field_prefix = f"chunks[{index}]"
        document_name = chunk.get("document_name")
        document_id = chunk.get("document_id")
        if isinstance(document_name, str) and document_name.strip():
            chunks_with_document_name += 1
        else:
            issues.append(
                GovernanceIssue(
                    "warning",
                    "chunk_missing_document_name",
                    "chunk snapshot entry lacks document_name, reducing provenance coverage",
                    f"{field_prefix}.document_name",
                )
            )
        if isinstance(document_id, str) and document_id.strip():
            chunks_with_document_id += 1
        document_keys = _chunk_document_keys(chunk)
        metadata_matched = bool(metadata_keys and document_keys.intersection(metadata_keys))
        if metadata_matched:
            chunks_with_metadata += 1
        elif metadata_path:
            issues.append(
                GovernanceIssue(
                    "warning",
                    "chunk_metadata_missing",
                    "chunk document does not match any metadata document path",
                    field_prefix,
                    "Add metadata for the segment path or preserve source document path metadata through splitting.",
                )
            )
        has_segment_hint = _chunk_has_segment_hint(chunk)
        if has_segment_hint:
            chunks_with_segment_hint += 1
        elif segmentation_plan_path:
            issues.append(
                GovernanceIssue(
                    "warning",
                    "chunk_segment_hint_missing",
                    "chunk does not expose segment provenance fields or a segment-like document path",
                    field_prefix,
                )
            )
        segment_ids: set[str] = set()
        for key in document_keys:
            segment_ids.update(segment_index.get(key, set()))
        if segment_ids:
            chunks_matching_plan += 1
            matched_segments.update(segment_ids)
        elif segmentation_plan_path:
            issues.append(
                GovernanceIssue(
                    "warning",
                    "chunk_segment_plan_unmatched",
                    "chunk document does not match any segment from the segmentation plan",
                    field_prefix,
                )
            )
        chunk_reports.append(
            {
                "index": index,
                "snapshot_id": chunk.get("id"),
                "document_name": document_name,
                "document_id": document_id,
                "stable_hash": chunk.get("stable_hash"),
                "metadata_matched": metadata_matched,
                "segment_hint": has_segment_hint,
                "segment_ids": sorted(segment_ids),
            }
        )

    reported_missing_segments: set[str] = set()
    for key in sorted(segment_keys):
        ids = segment_index.get(key, set())
        missing_ids = sorted(ids - matched_segments - reported_missing_segments)
        for segment_id in missing_ids:
            issues.append(
                GovernanceIssue(
                    "warning",
                    "segment_without_chunk",
                    "segmentation plan segment was not observed in the chunk snapshot",
                    f"segments.{segment_id}",
                )
            )
            reported_missing_segments.add(segment_id)

    chunk_count = len(chunks)
    summary = {
        **_issue_counts(issues),
        "chunk_count": chunk_count,
        "metadata_document_count": metadata_document_count,
        "segment_count": segment_count,
        "chunks_with_document_name": chunks_with_document_name,
        "chunks_with_document_id": chunks_with_document_id,
        "chunks_with_metadata": chunks_with_metadata,
        "chunks_with_segment_hint": chunks_with_segment_hint,
        "chunks_matching_segmentation_plan": chunks_matching_plan,
        "matched_segment_count": len(matched_segments),
        "document_name_coverage": _coverage_rate(chunks_with_document_name, chunk_count),
        "document_id_coverage": _coverage_rate(chunks_with_document_id, chunk_count),
        "metadata_document_coverage": _coverage_rate(chunks_with_metadata, chunk_count),
        "segment_hint_coverage": _coverage_rate(chunks_with_segment_hint, chunk_count),
        "segmentation_plan_coverage": _coverage_rate(len(matched_segments), segment_count),
    }
    return {
        "ok": _ok(issues),
        "schema": SEGMENT_METADATA_REPORT_SCHEMA,
        "artifacts": {
            "chunk_snapshot": str(chunk_snapshot_path),
            "metadata": str(metadata_path) if metadata_path else None,
            "segmentation_plan": str(segmentation_plan_path) if segmentation_plan_path else None,
        },
        "summary": summary,
        "chunks": chunk_reports,
        "issues": [issue.to_dict() for issue in issues],
    }


def export_tagset_payload(payload: Mapping[str, Any], *, fmt: str) -> str | dict[str, Any]:
    """Export a tagset in a RAGFlow-friendly JSON or CSV shape."""

    lint_report = lint_tagset_payload(payload)
    if not lint_report["ok"]:
        raise MetadataGovernanceError("tagset has lint errors; fix them before export")
    normalized = lint_report["normalized_preview"]
    if fmt == "json":
        return {
            "schema": TAGSET_EXPORT_SCHEMA,
            "format": "json",
            "tags": normalized.get("tags", []),
        }
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["name", "label", "description", "aliases"])
        writer.writeheader()
        for tag in normalized.get("tags", []):
            writer.writerow(
                {
                    "name": tag.get("name", ""),
                    "label": tag.get("label", ""),
                    "description": tag.get("description", ""),
                    "aliases": "|".join(tag.get("aliases", [])),
                }
            )
        return buffer.getvalue()
    raise MetadataGovernanceError("tagset export format must be json or csv")


def export_tagset_file(path: str | Path, *, fmt: str) -> str | dict[str, Any]:
    """Load and export a tagset file."""

    return export_tagset_payload(_read_mapping(path), fmt=fmt)


def render_governance_markdown(report: Mapping[str, Any], *, title: str = "RAGFlow Governance Report") -> str:
    """Render a compact Markdown summary for metadata/tagset governance reports."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        f"# {title}",
        "",
        f"- schema: `{report.get('schema', 'unknown')}`",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
    ]
    for key in sorted(summary):
        lines.append(f"- {key}: `{summary[key]}`")
    issues = report.get("issues", [])
    if isinstance(issues, list) and issues:
        lines.extend(["", "## Issues", "", "| Severity | Code | Field | Message |", "| --- | --- | --- | --- |"])
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(
                "| {severity} | {code} | {field} | {message} |".format(
                    severity=issue.get("severity", ""),
                    code=issue.get("code", ""),
                    field=issue.get("field", ""),
                    message=str(issue.get("message", "")).replace("|", "\\|"),
                )
            )
    conflicts = report.get("conflicts", [])
    if isinstance(conflicts, list) and conflicts:
        lines.extend(["", "## Merge Conflicts", "", "| Path | Field | Previous | Kept |", "| --- | --- | --- | --- |"])
        for conflict in conflicts:
            if not isinstance(conflict, Mapping):
                continue
            lines.append(
                "| {path} | {field} | {previous} | {kept} |".format(
                    path=str(conflict.get("path", "")).replace("|", "\\|"),
                    field=conflict.get("field", ""),
                    previous=conflict.get("previous_source", ""),
                    kept=conflict.get("kept_source", ""),
                )
            )
    return "\n".join(lines) + "\n"
