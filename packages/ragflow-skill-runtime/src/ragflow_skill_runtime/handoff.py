"""Rich handoff sidecars for portable RAGFlow document packages."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_convert import sha256_file
from .doc_quality import DocQualityError, load_doc_manifest_payload


HANDOFF_PACKAGE_SCHEMA = "ragflow_handoff_package_v1"
DOCUMENT_METADATA_SCHEMA = "ragflow_document_metadata_v1"
ARTIFACT_INDEX_SCHEMA = "ragflow_artifact_index_v1"
PROFILE_SUGGESTIONS_SCHEMA = "ragflow_profile_suggestions_v1"


class HandoffError(RuntimeError):
    """Raised when a rich handoff package cannot be produced or inspected."""


@dataclass(frozen=True)
class HandoffPaths:
    root: Path
    doc_manifest: Path
    metadata: Path
    artifact_index: Path
    profile_suggestions: Path
    package_readme: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "doc_manifest": str(self.doc_manifest),
            "metadata": str(self.metadata),
            "artifact_index": str(self.artifact_index),
            "profile_suggestions": str(self.profile_suggestions),
            "package_readme": str(self.package_readme),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffError(f"required handoff file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffError(f"handoff file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HandoffError(f"handoff file must contain a JSON object: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _resolve_handoff_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def _source_root(manifest: Mapping[str, Any], *, root: Path) -> Path:
    raw = manifest.get("source_root") or "."
    base = Path(str(raw))
    if not base.is_absolute():
        base = root / base
    return base


def _manifest_documents(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_documents = manifest.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise HandoffError("doc_manifest.documents must be a non-empty list")
    documents = [item for item in raw_documents if isinstance(item, Mapping)]
    if len(documents) != len(raw_documents):
        raise HandoffError("doc_manifest.documents must contain only objects")
    return documents


def _file_record(path: Path, *, root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": _relative(path, root),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["size_bytes"] = path.stat().st_size
        record["sha256"] = sha256_file(path)
        mime_type, _encoding = mimetypes.guess_type(path.name)
        if mime_type:
            record["mime_type"] = mime_type
    return record


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}:
        return "image"
    if suffix in {".csv", ".tsv", ".xlsx", ".xls"}:
        return "table"
    if suffix in {".json", ".yaml", ".yml", ".txt", ".log"}:
        return "raw"
    return "artifact"


def make_document_metadata_payload(
    *,
    handoff_root: str | Path,
    doc_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Create document-level source and Markdown metadata for a handoff."""

    root = Path(handoff_root)
    source_base = _source_root(doc_manifest, root=root)
    documents = []
    for item in _manifest_documents(doc_manifest):
        source_path = str(item.get("source_path") or "")
        markdown_path = str(item.get("markdown_path") or "")
        markdown_file = _resolve_handoff_path(source_base, markdown_path)
        source_file = _resolve_handoff_path(source_base, source_path) if source_path else None
        document: dict[str, Any] = {
            "source_path": source_path,
            "source_format": Path(source_path).suffix.lower().lstrip(".") if source_path else None,
            "source_sha256": item.get("sha256"),
            "markdown_path": _relative(markdown_file, root),
            "title": item.get("title"),
            "language": item.get("language"),
            "locale": item.get("language"),
            "warnings": list(item.get("warnings", [])) if isinstance(item.get("warnings", []), list) else [],
            "markdown": _file_record(markdown_file, root=root),
        }
        if source_file:
            document["source"] = _file_record(source_file, root=root)
        documents.append(document)

    return {
        "schema": DOCUMENT_METADATA_SCHEMA,
        "created_at": _now(),
        "document_count": len(documents),
        "documents": documents,
    }


def make_artifact_index_payload(*, handoff_root: str | Path) -> dict[str, Any]:
    """Index local package artifacts without including source documents as artifacts."""

    root = Path(handoff_root)
    artifacts = []
    for container in ("documents", "artifacts"):
        base = root / container
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if container == "documents" and path.suffix.lower() == ".md":
                continue
            artifacts.append(
                {
                    **_file_record(path, root=root),
                    "kind": _artifact_kind(path),
                }
            )
    return {
        "schema": ARTIFACT_INDEX_SCHEMA,
        "created_at": _now(),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def make_profile_suggestions_payload(
    *,
    handoff_root: str | Path,
    metadata: Mapping[str, Any],
    quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic advisory profile hints from handoff metadata."""

    documents = metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []
    total_chars = 0
    image_count = 0
    has_cjk = False
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_path = Path(handoff_root) / str(markdown.get("path", ""))
        if markdown_path.is_file():
            text = markdown_path.read_text(encoding="utf-8", errors="replace")
            total_chars += len(text)
            image_count += text.count("![")
            has_cjk = has_cjk or any("\u4e00" <= char <= "\u9fff" for char in text[:5000])

    gate = quality_report.get("gate", {}) if isinstance(quality_report, Mapping) else {}
    quality_status = gate.get("status") if isinstance(gate, Mapping) else None
    language = "zh" if has_cjk else "en"
    average_chars = int(total_chars / len(documents)) if documents else 0
    chunk_size = 512 if language == "zh" else 768
    if average_chars > 24000:
        chunk_size = 1024 if language == "en" else 768

    warnings: list[str] = []
    if quality_status == "BLOCKED":
        warnings.append("quality gate is BLOCKED; fix the handoff before building unless the user explicitly allows it")
    if image_count:
        warnings.append("image-rich Markdown detected; verify parser profile preserves image/table context as needed")
    if average_chars > 32000:
        warnings.append("large average document size detected; consider segmentation before upload")

    return {
        "schema": PROFILE_SUGGESTIONS_SCHEMA,
        "created_at": _now(),
        "suggestions": [
            {
                "id": f"default-{language}-{chunk_size}",
                "language": language,
                "chunk_size": chunk_size,
                "chunk_overlap": 96 if chunk_size >= 768 else 64,
                "reason": "deterministic starter suggestion based on language and document size",
            }
        ],
        "signals": {
            "document_count": len(documents),
            "total_chars": total_chars,
            "average_chars": average_chars,
            "image_count": image_count,
            "quality_status": quality_status,
        },
        "warnings": warnings,
    }


def make_package_readme(
    *,
    doc_manifest_name: str,
    metadata_name: str,
    artifact_index_name: str,
    profile_suggestions_name: str,
    quality_report_name: str | None,
) -> str:
    """Render a compact README for a rich handoff package."""

    lines = [
        "# RAGFlow Handoff Package",
        "",
        "This directory is a portable document handoff for the public RAGFlow skills.",
        "",
        "## Files",
        "",
        f"- `{doc_manifest_name}`: required v0.1 document manifest.",
        f"- `{metadata_name}`: document-level source and Markdown metadata.",
        f"- `{artifact_index_name}`: hashes and kinds for local assets under `documents/` and `artifacts/`.",
        f"- `{profile_suggestions_name}`: advisory parser/profile hints for review.",
    ]
    if quality_report_name:
        lines.append(f"- `{quality_report_name}`: document quality gate report.")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Treat sidecars as advisory public metadata.",
            "- Do not add API keys, private config files, vault paths, or personal endpoints to this package.",
            "- `ragflow-kb-build` consumes `doc_manifest.json` first; rich sidecars remain optional.",
            "",
        ]
    )
    return "\n".join(lines)


def create_rich_handoff_package(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    metadata_name: str = "metadata.json",
    artifact_index_name: str = "artifact_index.json",
    profile_suggestions_name: str = "profile_suggestions.json",
    package_readme_name: str = "package_readme.md",
) -> dict[str, Any]:
    """Create optional rich sidecars beside an existing doc manifest."""

    root = Path(handoff_root)
    doc_manifest_path = root / doc_manifest_name
    try:
        doc_manifest = load_doc_manifest_payload(doc_manifest_path)
    except DocQualityError as exc:
        raise HandoffError(str(exc)) from exc

    quality_report_name = doc_manifest.get("quality_report")
    quality_report = None
    if isinstance(quality_report_name, str) and quality_report_name:
        quality_path = root / quality_report_name
        if quality_path.exists():
            quality_report = _read_json(quality_path)

    metadata = make_document_metadata_payload(handoff_root=root, doc_manifest=doc_manifest)
    artifact_index = make_artifact_index_payload(handoff_root=root)
    profile_suggestions = make_profile_suggestions_payload(
        handoff_root=root,
        metadata=metadata,
        quality_report=quality_report,
    )
    readme = make_package_readme(
        doc_manifest_name=doc_manifest_name,
        metadata_name=metadata_name,
        artifact_index_name=artifact_index_name,
        profile_suggestions_name=profile_suggestions_name,
        quality_report_name=quality_report_name if isinstance(quality_report_name, str) else None,
    )

    metadata_path = root / metadata_name
    artifact_index_path = root / artifact_index_name
    profile_suggestions_path = root / profile_suggestions_name
    package_readme_path = root / package_readme_name
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_index_path.write_text(json.dumps(artifact_index, ensure_ascii=False, indent=2), encoding="utf-8")
    profile_suggestions_path.write_text(json.dumps(profile_suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    package_readme_path.write_text(readme, encoding="utf-8")

    payload = {
        "schema": HANDOFF_PACKAGE_SCHEMA,
        "created_at": _now(),
        "doc_manifest": doc_manifest_name,
        "metadata": metadata_name,
        "artifact_index": artifact_index_name,
        "profile_suggestions": profile_suggestions_name,
        "package_readme": package_readme_name,
        "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
        "document_count": len(metadata["documents"]),
        "artifact_count": artifact_index["artifact_count"],
        "quality_status": profile_suggestions.get("signals", {}).get("quality_status"),
    }
    return payload


def inspect_rich_handoff(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
) -> dict[str, Any]:
    """Summarize a handoff directory and optional rich sidecars."""

    root = Path(handoff_root)
    doc_manifest = _read_json(root / doc_manifest_name)
    documents = _manifest_documents(doc_manifest)
    sidecars = {}
    for key, filename in {
        "metadata": "metadata.json",
        "artifact_index": "artifact_index.json",
        "profile_suggestions": "profile_suggestions.json",
        "package_readme": "package_readme.md",
        "quality_report": doc_manifest.get("quality_report") if isinstance(doc_manifest.get("quality_report"), str) else None,
    }.items():
        if not filename:
            continue
        path = root / filename
        sidecars[key] = {
            "path": filename,
            "exists": path.exists(),
        }
        if path.is_file():
            sidecars[key]["size_bytes"] = path.stat().st_size

    artifact_count = None
    artifact_index_path = root / "artifact_index.json"
    if artifact_index_path.is_file():
        artifact_index = _read_json(artifact_index_path)
        artifact_count = artifact_index.get("artifact_count")

    quality_status = None
    quality_name = doc_manifest.get("quality_report")
    if isinstance(quality_name, str) and (root / quality_name).is_file():
        quality = _read_json(root / quality_name)
        gate = quality.get("gate", {}) if isinstance(quality.get("gate"), Mapping) else {}
        quality_status = gate.get("status")

    return {
        "schema": "ragflow_handoff_inspection_v1",
        "created_at": _now(),
        "handoff_root": str(root),
        "doc_manifest": doc_manifest_name,
        "document_count": len(documents),
        "quality_status": quality_status,
        "artifact_count": artifact_count,
        "sidecars": sidecars,
    }


def render_handoff_inspection_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown handoff inspection report."""

    lines = [
        "# RAGFlow Handoff Inspection",
        "",
        f"- Documents: {report.get('document_count', 0)}",
        f"- Quality status: `{report.get('quality_status') or 'UNKNOWN'}`",
        f"- Artifact count: {report.get('artifact_count') if report.get('artifact_count') is not None else 'unknown'}",
        "",
        "## Sidecars",
        "",
        "| Sidecar | Exists | Path |",
        "| --- | --- | --- |",
    ]
    sidecars = report.get("sidecars", {})
    if isinstance(sidecars, Mapping):
        for name, info in sidecars.items():
            if not isinstance(info, Mapping):
                continue
            lines.append(f"| {name} | {str(bool(info.get('exists'))).lower()} | `{info.get('path', '')}` |")
    return "\n".join(lines).rstrip() + "\n"
