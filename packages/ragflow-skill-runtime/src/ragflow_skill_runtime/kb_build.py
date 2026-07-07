"""Helpers for Markdown-to-RAGFlow build scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Mapping
import zipfile

from .manifests import DocManifest, KbDocumentEntry, KbManifest, ManifestError, load_kb_manifest
from .profiles import ChunkProfile, ProfileError, load_profile

KB_ASSET_UPLOAD_PLAN_SCHEMA = "ragflow_kb_asset_upload_plan_v2"
KB_ASSET_INGESTION_REPORT_SCHEMA = "ragflow_kb_asset_ingestion_report_v1"
KB_ARTIFACT_CONSISTENCY_REPORT_SCHEMA = "ragflow_kb_artifact_consistency_report_v1"
KB_REFRESH_REPORT_SCHEMA = "ragflow_kb_refresh_report_v1"
MULTIMODAL_KB_MANIFEST_SCHEMA = "ragflow_multimodal_kb_manifest_v1"
RETRIEVAL_HINTS_SCHEMA = "ragflow_retrieval_hints_v1"
CHUNK_PROFILE_REPORT_SCHEMA = "ragflow_chunk_profile_report_v1"
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"}
ASSET_UPLOAD_PLAN_IMAGE_CLASSES = (
    "markdown_referenced",
    "manifest_listed",
    "sidecar_referenced",
    "residual_unreferenced",
    "outside_handoff",
    "missing",
)
HASH_NAMED_IMAGE_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
RESIDUAL_IMAGE_LARGE_BYTES = 5 * 1024 * 1024
RESIDUAL_IMAGE_NUMEROUS_THRESHOLD = 5
DEFAULT_UPLOAD_PLAN_SIDECARS = (
    ("doc_manifest", "doc_manifest.json"),
    ("quality_report", "quality_report.json"),
    ("metadata", "metadata.json"),
    ("artifact_index", "artifact_index.json"),
    ("profile_suggestions", "profile_suggestions.json"),
    ("retrieval_hints", "retrieval_hints.json"),
    ("assistant_profile", "assistant_profile.json"),
    ("assistant_test_plan", "assistant_test_plan.json"),
    ("postprocess_report", "postprocess_report.json"),
    ("chunk_profile_report", "chunk_profile_report.json"),
    ("ragflow_ingest_plan", "ragflow_ingest_plan.yaml"),
    ("ingest_readiness", "ingest_readiness_report.json"),
    ("ingest_readiness_markdown", "ingest_readiness_report.md"),
    ("formal_handoff_manifest", "formal_handoff_manifest.json"),
    ("package_readme", "package_readme.md"),
)


class BuildError(RuntimeError):
    """Raised when build inputs are invalid."""


@dataclass(frozen=True)
class BuildDocument:
    path: Path
    manifest_source_path: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise BuildError(f"{label} must be a JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_embedding_model_expectations(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Return de-duplicated expected embedding model labels for report checks."""

    seen: set[str] = set()
    models: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        models.append(text)
    return models


def describe_embedding_model(profile: ChunkProfile | Mapping[str, Any] | None) -> dict[str, Any]:
    """Describe the embedding model captured by a build profile."""

    value: Any = None
    if isinstance(profile, ChunkProfile):
        value = profile.embedding_model
    elif isinstance(profile, Mapping):
        value = profile.get("embedding_model")

    if isinstance(value, str) and value.strip():
        return {
            "model": value.strip(),
            "status": "known",
            "source": "profile.embedding_model",
            "reason": None,
        }
    return {
        "model": "unknown",
        "status": "unknown",
        "source": "profile.embedding_model",
        "reason": "profile_embedding_model_missing",
    }


def check_embedding_model_drift(
    embedding_model: Mapping[str, Any] | str,
    expected_embedding_models: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    """Compare observed embedding model evidence with expected model labels."""

    expected_models = normalize_embedding_model_expectations(expected_embedding_models)
    if isinstance(embedding_model, Mapping):
        observed_model = str(embedding_model.get("model") or "unknown").strip() or "unknown"
        reason = embedding_model.get("reason")
    else:
        observed_model = str(embedding_model or "unknown").strip() or "unknown"
        reason = "profile_embedding_model_missing" if observed_model == "unknown" else None

    if not expected_models:
        return {
            "status": "not_configured",
            "observed_model": observed_model,
            "expected_models": [],
            "matches_expected": None,
            "rebuild_or_reparse_required": False,
            "reason": reason,
        }
    if observed_model == "unknown":
        return {
            "status": "unknown",
            "observed_model": observed_model,
            "expected_models": expected_models,
            "matches_expected": None,
            "rebuild_or_reparse_required": False,
            "reason": reason,
        }

    expected_keys = {model.casefold() for model in expected_models}
    matches = observed_model.casefold() in expected_keys
    return {
        "status": "match" if matches else "mismatch",
        "observed_model": observed_model,
        "expected_models": expected_models,
        "matches_expected": matches,
        "rebuild_or_reparse_required": not matches,
        "reason": None if matches else "embedding_model_expected_mismatch",
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def _is_remote_asset_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "data:", "#", "mailto:"))


def _image_reference_path(raw: str) -> str:
    value = raw.strip().strip("<>")
    if " " in value and not value.startswith(("./", "../", "/")):
        value = value.split(" ", 1)[0]
    return value.split("#", 1)[0].split("?", 1)[0]


def _source_root_from_manifest(payload: Mapping[str, Any], *, manifest_path: Path) -> Path:
    raw = payload.get("source_root") or "."
    root = Path(str(raw))
    if not root.is_absolute():
        root = manifest_path.parent / root
    return root


def _document_asset_paths(document: Mapping[str, Any]) -> list[str]:
    assets = document.get("assets")
    if not isinstance(assets, Mapping):
        return []
    images = assets.get("images")
    if not isinstance(images, list):
        return []
    paths: list[str] = []
    for item in images:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("path")
        if isinstance(raw, str) and raw.strip():
            paths.append(raw.strip())
    return paths


def _file_record(
    *,
    role: str,
    source_path: Path,
    handoff_root: Path,
    package_path: str | None = None,
    exists: bool | None = None,
) -> dict[str, Any]:
    present = source_path.is_file() if exists is None else exists
    record: dict[str, Any] = {
        "role": role,
        "source_path": _relative_to_root(source_path, handoff_root),
        "package_path": package_path or _relative_to_root(source_path, handoff_root),
        "exists": present,
        "inside_handoff": _is_relative_to(source_path, handoff_root),
    }
    if present:
        record["size_bytes"] = source_path.stat().st_size
        record["sha256"] = _sha256_file(source_path)
        mime_type, _encoding = mimetypes.guess_type(source_path.name)
        if mime_type:
            record["mime_type"] = mime_type
    return record


def _issue(*, severity: str, code: str, message: str, recommendation: str) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "recommendation": recommendation,
    }


def _clean_artifact_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().strip("<>").replace("\\", "/")
    if not text or _is_remote_asset_reference(text):
        return None
    text = text.split("#", 1)[0].split("?", 1)[0].strip()
    while text.startswith("./"):
        text = text[2:]
    return text or None


def _path_basename(value: str) -> str:
    return Path(value.replace("\\", "/")).name


def _path_matches(candidate: str, observed: set[str]) -> bool:
    if candidate in observed:
        return True
    candidate_name = _path_basename(candidate)
    return any(_path_basename(item) == candidate_name for item in observed)


def _record_paths(records: Any, keys: tuple[str, ...]) -> set[str]:
    paths: set[str] = set()
    if not isinstance(records, list):
        return paths
    for record in records:
        if not isinstance(record, Mapping):
            continue
        for key in keys:
            cleaned = _clean_artifact_path(record.get(key))
            if cleaned:
                paths.add(cleaned)
    return paths


def _hint_image_paths(retrieval_hints: Mapping[str, Any]) -> set[str]:
    return _record_paths(
        retrieval_hints.get("image_artifacts"),
        ("path", "source_path", "raw_path", "target", "asset_path", "resolved_path", "package_path"),
    )


def _hint_table_documents(retrieval_hints: Mapping[str, Any]) -> set[str]:
    return _record_paths(retrieval_hints.get("table_artifacts"), ("document", "markdown_path", "source_path", "path"))


def _asset_plan_image_paths(asset_plan: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    for key in (
        "planned_visual_upload_files",
        "discovered_image_artifacts",
        "image_references",
        "manifest_image_assets",
        "sidecar_image_assets",
        "residual_images",
        "orphan_images",
    ):
        paths.update(
            _record_paths(
                asset_plan.get(key),
                ("source_path", "package_path", "raw_path", "target", "resolved_path", "path"),
            )
        )
    return paths


def _asset_plan_markdown_paths(asset_plan: Mapping[str, Any]) -> set[str]:
    return _record_paths(asset_plan.get("documents"), ("markdown_path", "package_path", "resolved_markdown_path", "source_path"))


def _kb_manifest_document_paths(kb_manifest: Mapping[str, Any]) -> set[str]:
    return _record_paths(kb_manifest.get("documents"), ("markdown_path", "source_path", "path", "name", "filename"))


def _kb_manifest_image_paths(kb_manifest: Mapping[str, Any]) -> set[str]:
    paths = _record_paths(kb_manifest.get("documents"), ("source_path", "markdown_path", "path", "name", "filename"))
    return {path for path in paths if Path(path).suffix.lower() in IMAGE_SUFFIXES}


def _status_from_missing(missing: list[str]) -> str:
    return "review" if missing else "ready"


def _safe_package_path_for_handoff_file(path: Path, *, handoff_root: Path, fallback_dir: str, index: int) -> str:
    if _is_relative_to(path, handoff_root):
        return _relative_to_root(path, handoff_root)
    name = path.name or f"file-{index}"
    return f"{fallback_dir}/{index:03d}-{name}"


def _add_projected_file(files: list[dict[str, Any]], seen: set[str], record: dict[str, Any]) -> None:
    package_path = str(record.get("package_path") or "")
    if not package_path or package_path in seen:
        return
    seen.add(package_path)
    files.append(record)


def _image_artifact_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def _is_image_path_value(value: str) -> bool:
    if _is_remote_asset_reference(value):
        return False
    return Path(_image_reference_path(value)).suffix.lower() in IMAGE_SUFFIXES


def _iter_image_path_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_image_reference_path(value)] if _is_image_path_value(value) else []
    if isinstance(value, Mapping):
        found: list[str] = []
        for nested in value.values():
            found.extend(_iter_image_path_values(nested))
        return found
    if isinstance(value, list):
        found = []
        for nested in value:
            found.extend(_iter_image_path_values(nested))
        return found
    return []


def _image_artifact_record(
    *,
    asset_class: str,
    source: str,
    raw_path: str,
    resolved: Path,
    handoff_root: Path,
    document_index: int | None = None,
    document: str | None = None,
    planned_for_visual_upload: bool = False,
) -> dict[str, Any]:
    exists = resolved.is_file()
    inside_handoff = _is_relative_to(resolved, handoff_root)
    record: dict[str, Any] = {
        "asset_class": asset_class,
        "role": "image_asset",
        "source": source,
        "raw_path": raw_path,
        "source_path": _relative_to_root(resolved, handoff_root),
        "package_path": _relative_to_root(resolved, handoff_root) if inside_handoff else None,
        "exists": exists,
        "inside_handoff": inside_handoff,
        "planned_for_visual_upload": planned_for_visual_upload,
        "planned_for_package": planned_for_visual_upload,
    }
    if document_index is not None:
        record["document_index"] = document_index
    if document:
        record["document"] = document
    if exists:
        record["size_bytes"] = resolved.stat().st_size
        record["sha256"] = _sha256_file(resolved)
        mime_type, _encoding = mimetypes.guess_type(resolved.name)
        if mime_type:
            record["mime_type"] = mime_type
    return record


def _add_image_artifact(
    *,
    artifacts: list[dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    asset_class: str,
    source: str,
    raw_path: str,
    resolved: Path,
    handoff_root: Path,
    document_index: int | None = None,
    document: str | None = None,
    planned_for_visual_upload: bool = False,
) -> dict[str, Any]:
    key = _image_artifact_key(resolved)
    source_record = {"source": source, "raw_path": raw_path}
    if document_index is not None:
        source_record["document_index"] = document_index
    existing = by_key.get(key)
    if existing is not None:
        existing.setdefault("sources", []).append(source_record)
        existing["planned_for_visual_upload"] = bool(existing.get("planned_for_visual_upload")) or planned_for_visual_upload
        existing["planned_for_package"] = bool(existing.get("planned_for_package")) or planned_for_visual_upload
        return existing
    record = _image_artifact_record(
        asset_class=asset_class,
        source=source,
        raw_path=raw_path,
        resolved=resolved,
        handoff_root=handoff_root,
        document_index=document_index,
        document=document,
        planned_for_visual_upload=planned_for_visual_upload,
    )
    record["sources"] = [source_record]
    by_key[key] = record
    artifacts.append(record)
    return record


def _collect_sidecar_image_references(*, handoff_root: Path) -> list[tuple[str, str, Path]]:
    references: list[tuple[str, str, Path]] = []
    for role, sidecar_name in DEFAULT_UPLOAD_PLAN_SIDECARS:
        if role == "doc_manifest":
            continue
        path = handoff_root / sidecar_name
        if not path.is_file() or path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        if path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        seen: set[str] = set()
        for raw in _iter_image_path_values(payload):
            if raw in seen:
                continue
            seen.add(raw)
            candidate = Path(raw)
            resolved = candidate if candidate.is_absolute() else handoff_root / candidate
            references.append((sidecar_name, raw, resolved))
    return references


def _collect_sidecar_records(
    *,
    manifest_payload: Mapping[str, Any],
    manifest_path: Path,
    handoff_root: Path,
) -> list[dict[str, Any]]:
    sidecar_names: dict[str, str] = {name: path for name, path in DEFAULT_UPLOAD_PLAN_SIDECARS}
    sidecar_names["doc_manifest"] = manifest_path.name
    for key in ("quality_report", "postprocess_report", "chunk_profile_report"):
        value = manifest_payload.get(key)
        if isinstance(value, str) and value.strip():
            sidecar_names[key] = value.strip()

    records: list[dict[str, Any]] = []
    for role, raw_path in sidecar_names.items():
        path = Path(raw_path)
        if path.is_absolute():
            resolved = path
        else:
            resolved = handoff_root / path
        if not resolved.is_file():
            continue
        records.append(
            _file_record(
                role=f"sidecar:{role}",
                source_path=resolved,
                handoff_root=handoff_root,
                package_path=_safe_package_path_for_handoff_file(
                    resolved,
                    handoff_root=handoff_root,
                    fallback_dir="sidecars",
                    index=len(records) + 1,
                ),
            )
        )
    return records


def _scan_orphan_images(*, handoff_root: Path, referenced_paths: set[Path]) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for name in ("documents", "artifacts", "images"):
        root = handoff_root / name
        if not root.is_dir():
            continue
        candidates.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    normalized_referenced = {path.resolve(strict=False) for path in referenced_paths}
    records = []
    for path in sorted({candidate.resolve(strict=False) for candidate in candidates}):
        if path in normalized_referenced:
            continue
        records.append(
            _image_artifact_record(
                asset_class="residual_unreferenced",
                source="handoff_image_scan",
                raw_path=_relative_to_root(path, handoff_root),
                resolved=path,
                handoff_root=handoff_root,
            )
        )
    return records


def create_kb_asset_upload_plan(
    *,
    doc_manifest_path: str | Path,
    include_sidecars: bool = True,
) -> dict[str, Any]:
    """Create a non-mutating upload package plan for Markdown and local image assets."""

    manifest_path = Path(doc_manifest_path)
    handoff_root = manifest_path.parent
    manifest_payload = _read_json_mapping(manifest_path, label="doc_manifest")
    raw_documents = manifest_payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise BuildError("doc_manifest.documents must be a non-empty list")
    source_root = _source_root_from_manifest(manifest_payload, manifest_path=manifest_path)

    issues: list[dict[str, str]] = []
    documents: list[dict[str, Any]] = []
    image_references: list[dict[str, Any]] = []
    manifest_image_assets: list[dict[str, Any]] = []
    discovered_image_artifacts: list[dict[str, Any]] = []
    discovered_image_artifacts_by_key: dict[str, dict[str, Any]] = {}
    projected_files: list[dict[str, Any]] = []
    seen_projected: set[str] = set()
    known_handoff_image_paths: set[Path] = set()
    remote_image_count = 0
    local_image_reference_count = 0

    for index, item in enumerate(raw_documents, start=1):
        if not isinstance(item, Mapping):
            issues.append(
                _issue(
                    severity="error",
                    code="invalid_document_entry",
                    message=f"doc_manifest.documents[{index}] is not an object",
                    recommendation="Regenerate doc_manifest.json before planning asset upload.",
                )
            )
            continue
        raw_markdown = item.get("markdown_path")
        if not isinstance(raw_markdown, str) or not raw_markdown.strip():
            issues.append(
                _issue(
                    severity="error",
                    code="missing_markdown_path",
                    message=f"doc_manifest.documents[{index}] has no markdown_path",
                    recommendation="Regenerate doc_manifest.json before planning asset upload.",
                )
            )
            continue
        markdown_path = Path(raw_markdown)
        if not markdown_path.is_absolute():
            markdown_path = source_root / markdown_path
        markdown_package_path = _safe_package_path_for_handoff_file(
            markdown_path,
            handoff_root=handoff_root,
            fallback_dir="documents",
            index=index,
        )
        markdown_exists = markdown_path.is_file()
        markdown_inside_handoff = _is_relative_to(markdown_path, handoff_root)
        markdown_record = _file_record(
            role="markdown",
            source_path=markdown_path,
            handoff_root=handoff_root,
            package_path=markdown_package_path,
            exists=markdown_exists,
        )
        if not markdown_exists:
            issues.append(
                _issue(
                    severity="error",
                    code="markdown_missing",
                    message=f"Markdown document is missing: {raw_markdown}",
                    recommendation="Repair doc_manifest.json or regenerate the handoff before upload.",
                )
            )
        else:
            _add_projected_file(projected_files, seen_projected, markdown_record)
        if not markdown_inside_handoff:
            issues.append(
                _issue(
                    severity="warning",
                    code="markdown_outside_handoff",
                    message=f"Markdown document is outside the handoff root: {raw_markdown}",
                    recommendation="Prefer handoff-local Markdown paths before sharing or packaging.",
                )
            )

        document_record: dict[str, Any] = {
            "document_index": index,
            "source_path": item.get("source_path") if isinstance(item.get("source_path"), str) else None,
            "markdown_path": raw_markdown,
            "resolved_markdown_path": _relative_to_root(markdown_path, handoff_root),
            "package_path": markdown_package_path,
            "exists": markdown_exists,
            "inside_handoff": markdown_inside_handoff,
            "image_reference_count": 0,
            "manifest_image_asset_count": 0,
        }
        if markdown_exists:
            text = markdown_path.read_text(encoding="utf-8", errors="replace")
            for match in MARKDOWN_IMAGE_RE.finditer(text):
                raw_target = _image_reference_path(match.group(2))
                if not raw_target:
                    continue
                if _is_remote_asset_reference(raw_target):
                    remote_image_count += 1
                    image_references.append(
                        {
                            "source": "markdown_image_reference",
                            "document_index": index,
                            "document": raw_markdown,
                            "target": raw_target,
                            "remote": True,
                            "planned_for_package": False,
                        }
                    )
                    continue
                local_image_reference_count += 1
                document_record["image_reference_count"] += 1
                target_path = Path(raw_target)
                resolved = target_path if target_path.is_absolute() else markdown_path.parent / target_path
                inside_handoff = _is_relative_to(resolved, handoff_root)
                exists = resolved.is_file()
                asset_class = "missing" if not exists else "outside_handoff" if not inside_handoff else "markdown_referenced"
                planned_for_visual_upload = asset_class == "markdown_referenced"
                record = {
                    "source": "markdown_image_reference",
                    "asset_class": asset_class,
                    "document_index": index,
                    "document": raw_markdown,
                    "target": raw_target,
                    "resolved_path": _relative_to_root(resolved, handoff_root),
                    "package_path": _relative_to_root(resolved, handoff_root) if inside_handoff else None,
                    "exists": exists,
                    "inside_handoff": inside_handoff,
                    "remote": False,
                    "planned_for_visual_upload": planned_for_visual_upload,
                    "planned_for_package": planned_for_visual_upload,
                }
                image_references.append(record)
                artifact = _add_image_artifact(
                    artifacts=discovered_image_artifacts,
                    by_key=discovered_image_artifacts_by_key,
                    asset_class=asset_class,
                    source="markdown_image_reference",
                    raw_path=raw_target,
                    resolved=resolved,
                    handoff_root=handoff_root,
                    document_index=index,
                    document=raw_markdown,
                    planned_for_visual_upload=planned_for_visual_upload,
                )
                if artifact.get("exists") and artifact.get("inside_handoff"):
                    known_handoff_image_paths.add(resolved)
        for raw_asset_path in _document_asset_paths(item):
            document_record["manifest_image_asset_count"] += 1
            asset_path = Path(raw_asset_path)
            resolved = asset_path if asset_path.is_absolute() else handoff_root / asset_path
            inside_handoff = _is_relative_to(resolved, handoff_root)
            exists = resolved.is_file()
            asset_class = "missing" if not exists else "outside_handoff" if not inside_handoff else "manifest_listed"
            record = {
                "source": "manifest_image_asset",
                "asset_class": asset_class,
                "document_index": index,
                "document": raw_markdown,
                "path": raw_asset_path,
                "resolved_path": _relative_to_root(resolved, handoff_root),
                "package_path": _relative_to_root(resolved, handoff_root) if inside_handoff else None,
                "exists": exists,
                "inside_handoff": inside_handoff,
                "planned_for_visual_upload": False,
                "planned_for_package": False,
            }
            manifest_image_assets.append(record)
            artifact = _add_image_artifact(
                artifacts=discovered_image_artifacts,
                by_key=discovered_image_artifacts_by_key,
                asset_class=asset_class,
                source="manifest_image_asset",
                raw_path=raw_asset_path,
                resolved=resolved,
                handoff_root=handoff_root,
                document_index=index,
                document=raw_markdown,
                planned_for_visual_upload=False,
            )
            if artifact.get("exists") and artifact.get("inside_handoff"):
                known_handoff_image_paths.add(resolved)
        documents.append(document_record)

    sidecar_image_assets: list[dict[str, Any]] = []
    for sidecar_name, raw_path, resolved in _collect_sidecar_image_references(handoff_root=handoff_root):
        inside_handoff = _is_relative_to(resolved, handoff_root)
        exists = resolved.is_file()
        asset_class = "missing" if not exists else "outside_handoff" if not inside_handoff else "sidecar_referenced"
        artifact = _add_image_artifact(
            artifacts=discovered_image_artifacts,
            by_key=discovered_image_artifacts_by_key,
            asset_class=asset_class,
            source=f"sidecar:{sidecar_name}",
            raw_path=raw_path,
            resolved=resolved,
            handoff_root=handoff_root,
            planned_for_visual_upload=False,
        )
        sidecar_image_assets.append(artifact)
        if artifact.get("exists") and artifact.get("inside_handoff"):
            known_handoff_image_paths.add(resolved)

    orphan_images = _scan_orphan_images(handoff_root=handoff_root, referenced_paths=known_handoff_image_paths)
    for orphan in orphan_images:
        key = _image_artifact_key(handoff_root / str(orphan["source_path"]))
        if key not in discovered_image_artifacts_by_key:
            discovered_image_artifacts_by_key[key] = orphan
            discovered_image_artifacts.append(orphan)

    for artifact in discovered_image_artifacts:
        asset_class = artifact.get("asset_class")
        if asset_class == "outside_handoff":
            issues.append(
                _issue(
                    severity="error",
                    code="image_outside_handoff",
                    message=f"Local image reference is outside the handoff root: {artifact.get('raw_path')}",
                    recommendation="Copy image assets into the handoff and update Markdown references before upload.",
                )
            )
        elif asset_class == "missing":
            issues.append(
                _issue(
                    severity="error",
                    code="image_missing",
                    message=f"Local image asset is missing: {artifact.get('raw_path')}",
                    recommendation="Regenerate the handoff with asset landing enabled or repair image paths.",
                )
            )

    residual_images = [item for item in discovered_image_artifacts if item.get("asset_class") == "residual_unreferenced"]
    if residual_images:
        issues.append(
            _issue(
                severity="warning",
                code="orphan_images_detected",
                message="One or more handoff-local image files are not referenced by Markdown or doc_manifest assets.",
                recommendation="Review whether orphan images should be referenced, removed, or kept outside the upload package.",
            )
        )
        issues.append(
            _issue(
                severity="warning",
                code="residual_images_detected",
                message="One or more handoff-local image files are residual and not part of the default visual upload set.",
                recommendation="Upload only markdown_referenced images by default; review residual files before broadening the asset policy.",
            )
        )
    if len(residual_images) >= RESIDUAL_IMAGE_NUMEROUS_THRESHOLD:
        issues.append(
            _issue(
                severity="warning",
                code="residual_images_numerous",
                message="Residual handoff images are numerous enough to require review before upload.",
                recommendation="Check whether these files are parser leftovers or intentional visual documents.",
            )
        )
    if any(int(item.get("size_bytes", 0) or 0) >= RESIDUAL_IMAGE_LARGE_BYTES for item in residual_images):
        issues.append(
            _issue(
                severity="warning",
                code="residual_images_large",
                message="At least one residual handoff image is large.",
                recommendation="Avoid uploading large residual images unless they are intentionally selected as visual documents.",
            )
        )
    if any(HASH_NAMED_IMAGE_RE.match(Path(str(item.get("source_path") or "")).stem) for item in residual_images):
        issues.append(
            _issue(
                severity="warning",
                code="residual_images_likely_hash_named",
                message="At least one residual image has a hash-like filename.",
                recommendation="Treat hash-named residual files as parser leftovers unless handoff evidence says otherwise.",
            )
        )
    planned_visual_upload_files = [
        item
        for item in discovered_image_artifacts
        if item.get("asset_class") == "markdown_referenced"
        and item.get("exists") is True
        and item.get("inside_handoff") is True
    ]
    planned_hashes = {item.get("sha256") for item in planned_visual_upload_files if item.get("sha256")}
    if planned_hashes and any(item.get("sha256") in planned_hashes for item in residual_images):
        issues.append(
            _issue(
                severity="warning",
                code="residual_images_likely_duplicates",
                message="At least one residual image has the same content hash as a planned Markdown-referenced image.",
                recommendation="Do not upload duplicate residual files as separate visual documents.",
            )
        )
    if remote_image_count:
        issues.append(
            _issue(
                severity="warning",
                code="remote_images_not_packaged",
                message="Remote or data URI image references are not included in the local upload package.",
                recommendation="Land remote images locally before KB upload if RAGFlow must preserve them.",
            )
        )

    sidecars: list[dict[str, Any]] = []
    if include_sidecars:
        sidecars = _collect_sidecar_records(
            manifest_payload=manifest_payload,
            manifest_path=manifest_path,
            handoff_root=handoff_root,
        )
        for record in sidecars:
            _add_projected_file(projected_files, seen_projected, record)

    for item in planned_visual_upload_files:
        source_path = item.get("source_path")
        package_path = item.get("package_path")
        if not isinstance(source_path, str) or not source_path:
            continue
        source = Path(source_path)
        if not source.is_absolute():
            source = handoff_root / source
        _add_projected_file(
            projected_files,
            seen_projected,
            _file_record(
                role="image_asset",
                source_path=source,
                handoff_root=handoff_root,
                package_path=str(package_path or source_path),
                exists=item.get("exists") is True,
            ),
        )

    asset_class_counts = {
        asset_class: sum(1 for item in discovered_image_artifacts if item.get("asset_class") == asset_class)
        for asset_class in ASSET_UPLOAD_PLAN_IMAGE_CLASSES
    }
    package_size_bytes = sum(int(item.get("size_bytes", 0) or 0) for item in projected_files if item.get("exists"))
    error_count = sum(1 for item in issues if item["severity"] == "error")
    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    status = "blocked" if error_count else "ready_with_review" if warning_count else "ready"
    return {
        "schema": KB_ASSET_UPLOAD_PLAN_SCHEMA,
        "created_at": _now(),
        "doc_manifest": manifest_path.name,
        "handoff_root": str(handoff_root),
        "offline_only": True,
        "live_upload_enabled": False,
        "llm_calls": 0,
        "ragflow_calls": 0,
        "status": status,
        "summary": {
            "document_count": len(documents),
            "markdown_file_count": len([item for item in projected_files if item.get("role") == "markdown"]),
            "local_image_reference_count": local_image_reference_count,
            "markdown_image_reference_count": local_image_reference_count,
            "remote_image_reference_count": remote_image_count,
            "manifest_image_asset_count": len(manifest_image_assets),
            "markdown_referenced_image_count": asset_class_counts["markdown_referenced"],
            "manifest_listed_image_count": asset_class_counts["manifest_listed"],
            "sidecar_referenced_image_count": asset_class_counts["sidecar_referenced"],
            "residual_unreferenced_image_count": asset_class_counts["residual_unreferenced"],
            "discovered_image_artifact_count": len(discovered_image_artifacts),
            "planned_visual_upload_file_count": len(planned_visual_upload_files),
            "planned_image_file_count": len(planned_visual_upload_files),
            "missing_image_count": asset_class_counts["missing"],
            "missing_image_asset_count": asset_class_counts["missing"],
            "outside_handoff_image_count": asset_class_counts["outside_handoff"],
            "orphan_image_count": len(residual_images),
            "unreferenced_handoff_image_count": len(residual_images),
            "sidecar_file_count": len(sidecars),
            "projected_upload_file_count": len(projected_files),
            "package_size_bytes": package_size_bytes,
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "documents": documents,
        "image_references": image_references,
        "manifest_image_assets": manifest_image_assets,
        "sidecar_image_assets": sidecar_image_assets[:50],
        "orphan_images": residual_images[:50],
        "residual_images": residual_images[:50],
        "discovered_image_artifacts": discovered_image_artifacts[:200],
        "planned_visual_upload_files": planned_visual_upload_files,
        "asset_class_counts": asset_class_counts,
        "sidecars": sidecars,
        "projected_upload_files": projected_files,
        "issues": issues,
        "upload_policy": {
            "current_live_upload_path": "markdown_only",
            "default_visual_upload_class": "markdown_referenced",
            "planned_package_mode": "zip",
            "live_mutation_requires_existing_build_gate": True,
            "notes": [
                "This report does not call RAGFlow.",
                "Only markdown_referenced image assets enter the default visual upload plan.",
                "Manifest-listed, sidecar-referenced, and residual images are discovered for review but excluded from the default visual upload set.",
                "Only handoff-local existing Markdown, planned image, and sidecar files are projected into the local package.",
                "Live upload of the package remains disabled until an explicit mutation gate approves it.",
            ],
        },
    }


def create_kb_asset_ingestion_readiness_report(
    *,
    asset_upload_plan_path: str | Path,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a non-mutating readiness report for future gated visual ingestion."""

    plan = _read_json_mapping(Path(asset_upload_plan_path), label="asset_upload_plan")
    issues: list[dict[str, str]] = []
    if plan.get("schema") != KB_ASSET_UPLOAD_PLAN_SCHEMA:
        issues.append(
            _issue(
                severity="error",
                code="asset_upload_plan_schema_mismatch",
                message=f"asset upload plan schema must be {KB_ASSET_UPLOAD_PLAN_SCHEMA}",
                recommendation="Regenerate the plan with ragflow-kb-build asset-upload-plan before image ingestion readiness.",
            )
        )

    summary = plan.get("summary", {}) if isinstance(plan.get("summary"), Mapping) else {}
    planned_count = _as_int(summary.get("planned_visual_upload_file_count"))
    if planned_count is None:
        planned_count = _as_int(summary.get("planned_image_file_count")) or 0
    missing_count = _as_int(summary.get("missing_image_asset_count")) or _as_int(summary.get("missing_image_count")) or 0
    outside_count = _as_int(summary.get("outside_handoff_image_count")) or 0
    residual_count = _as_int(summary.get("residual_unreferenced_image_count")) or _as_int(summary.get("orphan_image_count")) or 0

    if planned_count <= 0:
        issues.append(
            _issue(
                severity="warning",
                code="no_planned_visual_assets",
                message="Asset upload plan has no planned visual upload files.",
                recommendation="Use Markdown-only build unless visual documents are intentionally needed.",
            )
        )
    if missing_count or outside_count:
        issues.append(
            _issue(
                severity="error",
                code="visual_assets_missing_or_outside_handoff",
                message=f"Asset plan has {missing_count} missing and {outside_count} outside-handoff visual asset(s).",
                recommendation="Repair or regenerate handoff assets before enabling visual document ingestion.",
            )
        )
    if residual_count:
        issues.append(
            _issue(
                severity="warning",
                code="residual_visual_assets_require_review",
                message=f"Asset plan has {residual_count} residual image asset(s) outside the default upload set.",
                recommendation="Keep residual images excluded unless a user explicitly broadens the visual upload policy.",
            )
        )

    profile_payload: dict[str, Any] | None = None
    profile_source = str(profile_path) if profile_path else None
    if profile_path:
        try:
            profile = load_profile(profile_path)
            profile_payload = profile.to_manifest_dict()
        except (ProfileError, OSError) as exc:
            issues.append(
                _issue(
                    severity="error",
                    code="profile_load_failed",
                    message=str(exc),
                    recommendation="Provide a valid build profile before image ingestion readiness.",
                )
            )

    parser_config = profile_payload.get("parser_config", {}) if isinstance(profile_payload, Mapping) else {}
    chunk_token_num = _as_int(parser_config.get("chunk_token_num")) if isinstance(parser_config, Mapping) else None
    visual_profile_hints = [
        key
        for key, value in sorted(parser_config.items())
        if any(part in str(key).lower() for part in ("layout", "visual", "image", "vision", "ocr"))
        and bool(value)
    ] if isinstance(parser_config, Mapping) else []

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "blocked" if error_count else "ready_with_review" if warning_count else "ready"
    return {
        "ok": error_count == 0,
        "schema": KB_ASSET_INGESTION_REPORT_SCHEMA,
        "created_at": _now(),
        "mode": "readiness",
        "advisory_only": True,
        "offline_only": True,
        "mutation": "none",
        "mutation_allowed": False,
        "live_upload_enabled": False,
        "execution": {
            "status": "not_run",
            "ragflow_calls": 0,
            "db_calls": 0,
            "redis_calls": 0,
            "docker_calls": 0,
            "system_service_calls": 0,
        },
        "inputs": {
            "asset_upload_plan": str(asset_upload_plan_path),
            "profile": profile_source,
        },
        "status": status,
        "summary": {
            "planned_visual_upload_file_count": planned_count,
            "missing_image_asset_count": missing_count,
            "outside_handoff_image_count": outside_count,
            "residual_unreferenced_image_count": residual_count,
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "profile": profile_payload,
        "profile_review": {
            "source": profile_source,
            "chunk_token_num": chunk_token_num,
            "visual_profile_hint_keys": visual_profile_hints,
        },
        "checks": {
            "asset_plan_schema": {"status": "PASS" if plan.get("schema") == KB_ASSET_UPLOAD_PLAN_SCHEMA else "FAIL"},
            "planned_visual_upload_set": {"status": "PASS" if planned_count > 0 else "REVIEW", "count": planned_count},
            "asset_path_readiness": {
                "status": "PASS" if not missing_count and not outside_count else "FAIL",
                "missing_image_asset_count": missing_count,
                "outside_handoff_image_count": outside_count,
            },
            "residual_asset_review": {"status": "REVIEW" if residual_count else "PASS", "count": residual_count},
            "profile_evidence": {"status": "PASS" if profile_payload else "REVIEW", "source": profile_source},
        },
        "issues": issues,
        "next_steps": [
            "Review planned_visual_upload_files before any live image ingestion execution.",
            "Require explicit live execution flags and exact confirmation before uploading visual documents.",
            "Keep residual_unreferenced images excluded unless the user intentionally broadens the policy.",
        ],
    }


def render_kb_asset_ingestion_readiness_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown summary for image-ingestion readiness."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    profile = report.get("profile", {}) if isinstance(report.get("profile"), Mapping) else {}
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines = [
        "# RAGFlow Image Ingestion Readiness",
        "",
        f"- schema: `{report.get('schema', KB_ASSET_INGESTION_REPORT_SCHEMA)}`",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- mutation: `{report.get('mutation', 'none')}`",
        f"- planned visual upload files: `{summary.get('planned_visual_upload_file_count', 0)}`",
        f"- missing image assets: `{summary.get('missing_image_asset_count', 0)}`",
        f"- outside-handoff images: `{summary.get('outside_handoff_image_count', 0)}`",
        f"- residual images: `{summary.get('residual_unreferenced_image_count', 0)}`",
        f"- profile: `{profile.get('id', 'not_supplied')}`",
        "",
        "## Issues",
        "",
    ]
    if issues:
        for issue in issues[:20]:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    else:
        lines.append("- No issues found.")
    return "\n".join(lines) + "\n"


def create_kb_artifact_consistency_report(
    *,
    retrieval_hints_path: str | Path,
    asset_upload_plan_path: str | Path,
    chunk_profile_report_path: str | Path,
    kb_manifest_path: str | Path,
) -> dict[str, Any]:
    """Check consistency across handoff, asset, profile, and KB evidence artifacts."""

    retrieval_hints = _read_json_mapping(Path(retrieval_hints_path), label="retrieval_hints")
    asset_plan = _read_json_mapping(Path(asset_upload_plan_path), label="asset_upload_plan")
    chunk_profile = _read_json_mapping(Path(chunk_profile_report_path), label="chunk_profile_report")
    kb_manifest = _read_json_mapping(Path(kb_manifest_path), label="kb_manifest")

    issues: list[dict[str, str]] = []
    if retrieval_hints.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        issues.append(
            _issue(
                severity="error",
                code="retrieval_hints_schema_mismatch",
                message=f"retrieval_hints schema must be {RETRIEVAL_HINTS_SCHEMA}",
                recommendation="Regenerate retrieval_hints.json from the formal handoff before consistency review.",
            )
        )
    if asset_plan.get("schema") != KB_ASSET_UPLOAD_PLAN_SCHEMA:
        issues.append(
            _issue(
                severity="error",
                code="asset_upload_plan_schema_mismatch",
                message=f"asset upload plan schema must be {KB_ASSET_UPLOAD_PLAN_SCHEMA}",
                recommendation="Regenerate the plan with ragflow-kb-build asset-upload-plan.",
            )
        )
    if chunk_profile.get("schema") != CHUNK_PROFILE_REPORT_SCHEMA:
        issues.append(
            _issue(
                severity="error",
                code="chunk_profile_report_schema_mismatch",
                message=f"chunk profile report schema must be {CHUNK_PROFILE_REPORT_SCHEMA}",
                recommendation="Regenerate chunk_profile_report.json from a chunk-marker postprocess profile.",
            )
        )
    if kb_manifest.get("version") != "0.1":
        issues.append(
            _issue(
                severity="error",
                code="kb_manifest_version_mismatch",
                message="kb_manifest version must be 0.1",
                recommendation="Provide the current kb_manifest.json from ragflow-kb-build.",
            )
        )

    hint_images = sorted(_hint_image_paths(retrieval_hints))
    hint_table_documents = sorted(_hint_table_documents(retrieval_hints))
    asset_images = _asset_plan_image_paths(asset_plan)
    asset_markdown = _asset_plan_markdown_paths(asset_plan)
    kb_documents = _kb_manifest_document_paths(kb_manifest)
    kb_images = _kb_manifest_image_paths(kb_manifest)

    missing_image_hints = sorted(path for path in hint_images if not _path_matches(path, asset_images))
    missing_table_documents = sorted(path for path in hint_table_documents if not _path_matches(path, asset_markdown))
    if missing_image_hints:
        issues.append(
            _issue(
                severity="warning",
                code="retrieval_hint_images_missing_from_asset_plan",
                message="One or more image hints are not represented in the asset upload plan.",
                recommendation="Regenerate asset-upload-plan from the same handoff or repair retrieval_hints image paths.",
            )
        )
    if missing_table_documents:
        issues.append(
            _issue(
                severity="warning",
                code="retrieval_hint_tables_missing_from_asset_plan",
                message="One or more table hints reference documents not found in the asset upload plan.",
                recommendation="Regenerate retrieval hints and asset-upload-plan from the same doc_manifest.json.",
            )
        )

    marker_summary = chunk_profile.get("summary") if isinstance(chunk_profile.get("summary"), Mapping) else {}
    marker_type_counts = marker_summary.get("marker_type_counts") if isinstance(marker_summary.get("marker_type_counts"), Mapping) else {}
    table_marker_count = _as_int(marker_type_counts.get("table")) or 0
    table_hint_count = len(retrieval_hints.get("table_artifacts", [])) if isinstance(retrieval_hints.get("table_artifacts"), list) else 0
    table_marker_gap = table_hint_count > 0 and table_marker_count <= 0
    if table_marker_gap:
        issues.append(
            _issue(
                severity="warning",
                code="table_hints_without_chunk_markers",
                message="retrieval_hints.json has table artifacts but chunk_profile_report.json has no table markers.",
                recommendation="Review postprocess profile output before relying on table parent chunk retrieval.",
            )
        )

    missing_kb_markdown_documents = sorted(path for path in asset_markdown if not _path_matches(path, kb_documents))
    planned_visual_paths = _record_paths(asset_plan.get("planned_visual_upload_files"), ("source_path", "package_path", "raw_path", "path"))
    missing_kb_visual_documents = sorted(path for path in planned_visual_paths if not _path_matches(path, kb_images))
    if missing_kb_markdown_documents:
        issues.append(
            _issue(
                severity="warning",
                code="asset_plan_markdown_missing_from_kb_manifest",
                message="One or more asset-plan Markdown documents are not represented in kb_manifest.json.",
                recommendation="Refresh kb_manifest.json after build or verify the plan and build used the same handoff.",
            )
        )
    if missing_kb_visual_documents:
        issues.append(
            _issue(
                severity="warning",
                code="planned_visual_assets_missing_from_kb_manifest",
                message="One or more planned visual assets are not represented in kb_manifest.json.",
                recommendation="Run the gated image-ingestion flow or keep the KB classified as Markdown-only.",
            )
        )

    schema_issue_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "blocked" if schema_issue_count else "review" if warning_count else "ready"
    checks = {
        "schema_compatibility": {
            "status": "blocked" if schema_issue_count else "ready",
            "error_count": schema_issue_count,
        },
        "retrieval_hints_vs_asset_plan": {
            "status": "review" if missing_image_hints or missing_table_documents else "ready",
            "hint_image_count": len(hint_images),
            "asset_plan_image_path_count": len(asset_images),
            "missing_image_hints": missing_image_hints,
            "hint_table_document_count": len(hint_table_documents),
            "asset_plan_markdown_document_count": len(asset_markdown),
            "missing_table_documents": missing_table_documents,
        },
        "retrieval_hints_vs_chunk_profile": {
            "status": "review" if table_marker_gap else "ready",
            "table_hint_count": table_hint_count,
            "table_marker_count": table_marker_count,
            "marker_count": _as_int(marker_summary.get("marker_count")) or 0,
        },
        "asset_plan_vs_kb_manifest": {
            "status": "review" if missing_kb_markdown_documents or missing_kb_visual_documents else "ready",
            "asset_plan_markdown_document_count": len(asset_markdown),
            "kb_manifest_document_path_count": len(kb_documents),
            "missing_markdown_documents": missing_kb_markdown_documents,
            "planned_visual_upload_file_count": len(planned_visual_paths),
            "kb_manifest_visual_document_count": len(kb_images),
            "missing_visual_documents": missing_kb_visual_documents,
        },
    }
    return {
        "ok": schema_issue_count == 0,
        "schema": KB_ARTIFACT_CONSISTENCY_REPORT_SCHEMA,
        "created_at": _now(),
        "advisory_only": True,
        "offline_only": True,
        "mutation": "none",
        "ragflow_calls": 0,
        "llm_calls": 0,
        "inputs": {
            "retrieval_hints": str(retrieval_hints_path),
            "asset_upload_plan": str(asset_upload_plan_path),
            "chunk_profile_report": str(chunk_profile_report_path),
            "kb_manifest": str(kb_manifest_path),
        },
        "status": status,
        "summary": {
            "check_count": len(checks),
            "issue_count": len(issues),
            "error_count": schema_issue_count,
            "warning_count": warning_count,
            "hint_image_count": len(hint_images),
            "hint_table_count": table_hint_count,
            "planned_visual_upload_file_count": len(planned_visual_paths),
            "kb_manifest_document_count": len(kb_documents),
        },
        "checks": checks,
        "issues": issues,
        "next_steps": [
            "Regenerate stale artifacts from the same formal handoff before comparing build quality.",
            "Use image-ingestion-readiness before live visual ingestion when planned visual assets are missing from kb_manifest.json.",
            "Use validation-suggestions and benchmark validation after the artifact chain is consistent.",
        ],
    }


def render_kb_artifact_consistency_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown summary for artifact consistency review."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    checks = report.get("checks", {}) if isinstance(report.get("checks"), Mapping) else {}
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines = [
        "# RAGFlow KB Artifact Consistency Report",
        "",
        f"- schema: `{report.get('schema', KB_ARTIFACT_CONSISTENCY_REPORT_SCHEMA)}`",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- mutation: `{report.get('mutation', 'none')}`",
        f"- checks: `{summary.get('check_count', 0)}`",
        f"- warnings: `{summary.get('warning_count', 0)}`",
        f"- errors: `{summary.get('error_count', 0)}`",
        "",
        "## Checks",
        "",
    ]
    for name, check in checks.items():
        if not isinstance(check, Mapping):
            continue
        lines.append(f"- `{name}`: `{check.get('status', 'unknown')}`")
    lines.extend(["", "## Issues", ""])
    if issues:
        for issue in issues[:30]:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    else:
        lines.append("- No issues found.")
    return "\n".join(lines) + "\n"


def write_kb_asset_upload_zip(report: Mapping[str, Any], *, output_path: str | Path) -> dict[str, Any]:
    """Materialize the projected package files into a local zip archive."""

    files = report.get("projected_upload_files")
    if not isinstance(files, list):
        raise BuildError("asset upload plan has no projected_upload_files list")
    handoff_root = Path(str(report.get("handoff_root") or "."))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            if not isinstance(item, Mapping) or item.get("exists") is not True:
                continue
            package_path = item.get("package_path")
            source_path = item.get("source_path")
            if not isinstance(package_path, str) or not package_path:
                continue
            if not isinstance(source_path, str) or not source_path:
                continue
            source = Path(source_path)
            if not source.is_absolute():
                source = handoff_root / source
            if not source.is_file():
                continue
            archive.write(source, package_path)
            written += 1
    return {
        "path": str(output),
        "file_count": written,
        "size_bytes": output.stat().st_size if output.exists() else 0,
        "sha256": _sha256_file(output) if output.exists() else None,
    }


def render_kb_asset_upload_plan_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown summary for ragflow_kb_asset_upload_plan_v2."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow KB Asset Upload Plan",
        "",
        f"- schema: `{report.get('schema', KB_ASSET_UPLOAD_PLAN_SCHEMA)}`",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- offline_only: `{str(report.get('offline_only', True)).lower()}`",
        f"- live_upload_enabled: `{str(report.get('live_upload_enabled', False)).lower()}`",
        f"- documents: `{summary.get('document_count', 0)}`",
        f"- projected_upload_files: `{summary.get('projected_upload_file_count', 0)}`",
        f"- discovered image artifacts: `{summary.get('discovered_image_artifact_count', summary.get('manifest_image_asset_count', 0))}`",
        f"- Markdown image references: `{summary.get('markdown_image_reference_count', summary.get('local_image_reference_count', 0))}`",
        f"- markdown_referenced images: `{summary.get('markdown_referenced_image_count', 0)}`",
        f"- manifest_listed images: `{summary.get('manifest_listed_image_count', 0)}`",
        f"- sidecar_referenced images: `{summary.get('sidecar_referenced_image_count', 0)}`",
        f"- residual_unreferenced images: `{summary.get('residual_unreferenced_image_count', summary.get('unreferenced_handoff_image_count', 0))}`",
        f"- planned visual upload files: `{summary.get('planned_visual_upload_file_count', summary.get('planned_image_file_count', 0))}`",
        f"- missing image assets: `{summary.get('missing_image_asset_count', summary.get('missing_image_count', 0))}`",
        f"- unreferenced handoff images: `{summary.get('unreferenced_handoff_image_count', summary.get('orphan_image_count', 0))}`",
        f"- sidecars: `{summary.get('sidecar_file_count', 0)}`",
    ]
    package_zip = report.get("package_zip")
    if isinstance(package_zip, Mapping):
        lines.extend(
            [
                f"- package_zip: `{package_zip.get('path')}`",
                f"- package_zip_files: `{package_zip.get('file_count', 0)}`",
            ]
        )
    issues = report.get("issues")
    if isinstance(issues, list) and issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues[:20]:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def discover_markdown_documents(
    *,
    input_path: str | Path | None = None,
    doc_manifest: DocManifest | None = None,
    manifest_base_path: str | Path | None = None,
) -> list[BuildDocument]:
    """Discover Markdown documents from a directory, file, or doc manifest."""

    docs: list[BuildDocument] = []
    if doc_manifest:
        manifest_root = Path(manifest_base_path).parent if manifest_base_path else Path(".")
        base = Path(doc_manifest.source_root) if doc_manifest.source_root else manifest_root
        if not base.is_absolute():
            base = manifest_root / base
        for entry in doc_manifest.documents:
            md_path = Path(entry.markdown_path)
            if not md_path.is_absolute():
                md_path = base / md_path
            docs.append(BuildDocument(path=md_path, manifest_source_path=entry.source_path))
    elif input_path:
        path = Path(input_path)
        if path.is_file():
            docs = [BuildDocument(path=path)]
        elif path.is_dir():
            docs = [BuildDocument(path=p) for p in sorted(path.rglob("*.md"))]
        else:
            raise BuildError(f"input path not found: {path}")
    else:
        raise BuildError("provide --input or --doc-manifest")

    missing = [str(doc.path) for doc in docs if not doc.path.exists()]
    if missing:
        raise BuildError(f"markdown documents not found: {', '.join(missing[:5])}")
    docs = [doc for doc in docs if doc.path.suffix.lower() == ".md"]
    if not docs:
        raise BuildError("no Markdown documents found")
    return docs


def extract_dataset_id(response: Any) -> str:
    """Extract a dataset ID from common RAGFlow response shapes."""

    candidates = []
    if isinstance(response, Mapping):
        data = response.get("data", response)
        if isinstance(data, Mapping):
            candidates.extend([data.get("id"), data.get("dataset_id")])
        candidates.extend([response.get("id"), response.get("dataset_id")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    raise BuildError("could not extract dataset id from RAGFlow response")


def extract_uploaded_document_id(response: Any) -> str:
    """Extract an uploaded document ID from common RAGFlow response shapes."""

    data = response.get("data", response) if isinstance(response, Mapping) else response
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, Mapping):
            value = first.get("id") or first.get("document_id")
            if isinstance(value, str) and value:
                return value
    if isinstance(data, Mapping):
        value = data.get("id") or data.get("document_id")
        if isinstance(value, str) and value:
            return value
    raise BuildError("could not extract document id from upload response")


def make_kb_manifest_payload(
    *,
    base_url: str | None,
    dataset_id: str,
    dataset_name: str,
    profile: ChunkProfile,
    documents: list[tuple[BuildDocument, str, str | None, int | None]],
    expected_embedding_models: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Create a serializable KB manifest payload."""

    embedding_model = describe_embedding_model(profile)
    return {
        "version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ragflow_base_url": base_url,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "profile": profile.to_manifest_dict(),
        "embedding_model": embedding_model,
        "embedding_model_check": check_embedding_model_drift(embedding_model, expected_embedding_models),
        "documents": [
            {
                "document_id": document_id,
                "source_path": doc.manifest_source_path,
                "markdown_path": str(doc.path),
                "status": status,
                "chunk_count": chunk_count,
            }
            for doc, document_id, status, chunk_count in documents
        ],
    }


def document_entries_from_manifest(payload: Mapping[str, Any]) -> list[KbDocumentEntry]:
    """Return typed document entries from a KB manifest payload."""

    docs = payload.get("documents", [])
    if not isinstance(docs, list):
        raise BuildError("kb manifest documents must be a list")
    return [KbDocumentEntry.from_dict(item) for item in docs]


def _extract_document_items(response: Any) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping):
        return []
    data = response.get("data", response)
    if isinstance(data, Mapping):
        for key in ("docs", "documents", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def extract_document_items(response: Any) -> list[Mapping[str, Any]]:
    """Extract document objects from common RAGFlow list-document response shapes."""

    return _extract_document_items(response)


def extract_document_name(document: Mapping[str, Any]) -> str:
    """Extract a display/document name from common RAGFlow document shapes."""

    for key in ("name", "document_name", "docnm_kwd", "filename", "file_name"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_document_id(document: Mapping[str, Any]) -> str:
    """Extract a document ID from common RAGFlow document shapes."""

    for key in ("id", "document_id"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_string(document: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _document_mime_type(document: Mapping[str, Any], *, name: str) -> str:
    explicit = _first_string(document, ("mime_type", "content_type", "type", "file_type"))
    if explicit:
        return explicit
    guessed, _encoding = mimetypes.guess_type(name)
    return guessed or ""


def _document_kind(*, name: str, mime_type: str) -> str:
    suffix = Path(name).suffix.lower()
    lowered_mime = mime_type.lower()
    if lowered_mime.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in {".md", ".markdown"} or lowered_mime in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if lowered_mime.startswith("text/"):
        return "text"
    return "other"


def _document_thumbnail(document: Mapping[str, Any]) -> dict[str, Any]:
    url = _first_string(document, ("thumbnail_url", "thumb_url", "thumbnail", "thumbnail_path"))
    return {"url": url or None, "observed": bool(url)}


def _document_vlm_status(document: Mapping[str, Any]) -> str | None:
    value = _first_string(document, ("vlm_status", "vision_status", "image_parse_status", "vlm_run", "image_status"))
    return value or None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_parse_status(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _message_indicates_failure(message: str) -> bool:
    lower = message.lower()
    return "[error]" in lower or "exception" in lower or "fail" in lower


def normalize_document_state(document: Mapping[str, Any], *, document_id: str = "") -> dict[str, Any]:
    """Normalize one live document status entry returned by RAGFlow."""

    doc_id = str(document.get("id") or document.get("document_id") or document_id)
    name = extract_document_name(document)
    mime_type = _document_mime_type(document, name=name)
    thumbnail = _document_thumbnail(document)
    vlm_status = _document_vlm_status(document)
    run = _normalize_parse_status(document.get("run"))
    status = _normalize_parse_status(document.get("status"))
    progress = _as_float(document.get("progress"))
    progress_text = _normalize_parse_status(document.get("progress"))
    message = str(document.get("progress_msg") or document.get("message") or document.get("error") or "")
    chunk_count = document.get("chunk_count")
    if chunk_count is not None:
        try:
            chunk_count = int(chunk_count)
        except (TypeError, ValueError):
            chunk_count = None

    if run:
        effective_status = run
    elif progress is not None and progress >= 1:
        effective_status = "1"
    elif progress is not None and progress < 0:
        effective_status = "-1"
    elif _message_indicates_failure(message):
        effective_status = "failed"
    else:
        effective_status = status or progress_text or "pending"

    return {
        "document_id": doc_id,
        "name": name,
        "mime_type": mime_type,
        "document_kind": _document_kind(name=name, mime_type=mime_type),
        "status": effective_status,
        "chunk_count": chunk_count,
        "progress": progress,
        "progress_msg": message,
        "raw_status": status,
        "run": run,
        "thumbnail": thumbnail,
        "vlm_status": vlm_status,
    }


def extract_document_states(response: Any, *, document_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Extract normalized live document states from a RAGFlow list-documents response."""

    wanted = set(document_ids or [])
    states: dict[str, dict[str, Any]] = {}
    for item in _extract_document_items(response):
        state = normalize_document_state(item)
        document_id = state["document_id"]
        if not document_id:
            continue
        if wanted and document_id not in wanted:
            continue
        states[document_id] = state
    return states


def parse_state_succeeded(state: Mapping[str, Any]) -> bool:
    status = str(state.get("status", ""))
    return not parse_state_failed(state) and status in {
        "done",
        "success",
        "completed",
        "parsed",
        "finish",
        "finished",
        "1",
    }


def parse_state_failed(state: Mapping[str, Any]) -> bool:
    status = str(state.get("status", ""))
    progress = state.get("progress")
    return (
        status in {"fail", "failed", "error", "cancelled", "canceled", "-1"}
        or (isinstance(progress, (int, float)) and progress < 0)
        or _message_indicates_failure(str(state.get("progress_msg", "")))
    )


def _refresh_match_keys(document: KbDocumentEntry) -> list[str]:
    keys: list[str] = []
    for value in (document.document_id, document.markdown_path, document.source_path):
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        keys.append(text)
        name = Path(text).name
        if name and name != text:
            keys.append(name)
    return [key.casefold() for key in keys if key]


def _observed_state_lookup(states: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    for document_id, state in states.items():
        for value in (document_id, state.get("document_id"), state.get("name")):
            if not isinstance(value, str) or not value.strip():
                continue
            lookup.setdefault(value.strip().casefold(), state)
            name = Path(value.strip()).name
            if name:
                lookup.setdefault(name.casefold(), state)
    return lookup


def _refresh_state_label(state: Mapping[str, Any]) -> str:
    if parse_state_failed(state):
        return "failed"
    if parse_state_succeeded(state):
        return "succeeded"
    status = str(state.get("status") or "").strip()
    return "in_progress" if status else "unknown"


def _refresh_next_steps(issues: list[Mapping[str, Any]]) -> list[str]:
    codes = {str(issue.get("code") or "") for issue in issues}
    steps: list[str] = []
    if "manifest_document_missing_observed_state" in codes:
        steps.append("Export a fresh refresh report before using the manifest for parse, health, or benchmark decisions.")
    if "document_chunk_count_mismatch" in codes:
        steps.append("Treat manifest chunk counts as stale until a refreshed manifest or parse report agrees with server-observed counts.")
    if {"observed_document_parse_failed", "observed_document_in_progress"} & codes:
        steps.append("Review failed or still-running documents before marking this KB production-ready.")
    if "observed_document_not_in_manifest" in codes:
        steps.append("Decide whether unlinked observed documents should be added to the manifest chain or cleaned up.")
    if not steps:
        steps.append("Keep this read-only refresh report with the KB evidence chain for later parse, health, and benchmark checks.")
    return steps


def load_kb_refresh_report(path: str | Path) -> dict[str, Any]:
    """Load and validate a read-only KB refresh report sidecar."""

    source = Path(path)
    payload = _read_json_mapping(source, label="KB refresh report")
    if payload.get("schema") != KB_REFRESH_REPORT_SCHEMA:
        raise BuildError(f"KB refresh report schema must be {KB_REFRESH_REPORT_SCHEMA}: {source}")
    payload["_source_path"] = str(source)
    return payload


def kb_refresh_report_document_status_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a refresh report into a document-list shape parse-report can consume."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    observed_documents = [
        dict(item)
        for item in report.get("observed_documents", [])
        if isinstance(item, Mapping)
    ]
    return {
        "schema": KB_REFRESH_REPORT_SCHEMA,
        "dataset": dict(report.get("dataset", {})) if isinstance(report.get("dataset"), Mapping) else {},
        "data": {
            "docs": observed_documents,
            "doc_count": _as_int(summary.get("observed_document_count")),
            "chunk_count": _as_int(summary.get("observed_chunk_total")),
        },
    }


def summarize_kb_refresh_observed_state(
    report: Mapping[str, Any],
    *,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    """Return a compact common observed-state block for downstream reports."""

    dataset = dict(report.get("dataset", {})) if isinstance(report.get("dataset"), Mapping) else {}
    observed_dataset_id = str(dataset.get("id") or "")
    dataset_matches = None if not dataset_id else observed_dataset_id == str(dataset_id)
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    issues = [dict(item) for item in report.get("issues", []) if isinstance(item, Mapping)]
    compact_summary = {
        "observed_document_count": _as_int(summary.get("observed_document_count")) or 0,
        "matched_document_count": _as_int(summary.get("matched_document_count")) or 0,
        "missing_manifest_document_count": _as_int(summary.get("missing_manifest_document_count")) or 0,
        "extra_observed_document_count": _as_int(summary.get("extra_observed_document_count")) or 0,
        "observed_chunk_total": _as_int(summary.get("observed_chunk_total")),
        "observed_chunk_document_count": _as_int(summary.get("observed_chunk_document_count")) or 0,
        "chunk_mismatch_count": _as_int(summary.get("chunk_mismatch_count")) or 0,
        "failed_document_count": _as_int(summary.get("failed_document_count")) or 0,
        "in_progress_document_count": _as_int(summary.get("in_progress_document_count")) or 0,
        "warning_count": _as_int(summary.get("warning_count")) or 0,
        "error_count": _as_int(summary.get("error_count")) or 0,
    }
    return {
        "available": True,
        "schema": KB_REFRESH_REPORT_SCHEMA,
        "source": str(report.get("_source_path") or ""),
        "status": report.get("status", "UNKNOWN"),
        "ok": bool(report.get("ok", True)),
        "dataset": dataset,
        "dataset_matches": dataset_matches,
        "summary": compact_summary,
        "issue_codes": sorted({str(issue.get("code") or "") for issue in issues if issue.get("code")}),
    }


def create_kb_refresh_report(
    *,
    kb_manifest_path: str | Path,
    document_list_response: Any,
    page: int = 1,
    page_size: int = 200,
) -> dict[str, Any]:
    """Create a read-only report of current RAGFlow document and chunk state."""

    try:
        kb_manifest = load_kb_manifest(kb_manifest_path)
    except ManifestError as exc:
        raise BuildError(str(exc)) from exc

    observed_states = extract_document_states(document_list_response)
    observed_lookup = _observed_state_lookup(observed_states)
    matched_observed_ids: set[str] = set()
    manifest_documents: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    manifest_chunk_total = 0
    observed_chunk_total = 0
    observed_chunk_document_count = 0
    chunk_mismatch_count = 0
    matched_document_count = 0

    for document in kb_manifest.documents:
        manifest_chunks = _as_int(document.chunk_count)
        if manifest_chunks is not None:
            manifest_chunk_total += manifest_chunks
        observed: Mapping[str, Any] | None = None
        for key in _refresh_match_keys(document):
            candidate = observed_lookup.get(key)
            if candidate:
                observed = candidate
                break
        if observed:
            matched_document_count += 1
            observed_id = observed.get("document_id")
            if isinstance(observed_id, str) and observed_id:
                matched_observed_ids.add(observed_id)
        observed_chunks = _as_int(observed.get("chunk_count")) if observed else None
        document_issue_codes: list[str] = []
        if not observed:
            document_issue_codes.append("manifest_document_missing_observed_state")
            issues.append(
                _issue(
                    severity="warning",
                    code="manifest_document_missing_observed_state",
                    message=f"Manifest document {document.document_id} was not found in the read-only RAGFlow document list.",
                    recommendation="Run refresh-report again after confirming the dataset ID, or regenerate the manifest from current server state.",
                )
            )
        elif manifest_chunks is not None and observed_chunks is not None and manifest_chunks != observed_chunks:
            chunk_mismatch_count += 1
            document_issue_codes.append("document_chunk_count_mismatch")
            issues.append(
                _issue(
                    severity="warning",
                    code="document_chunk_count_mismatch",
                    message=(
                        f"Manifest document {document.document_id} chunk_count={manifest_chunks} differs "
                        f"from observed chunk_count={observed_chunks}."
                    ),
                    recommendation="Refresh downstream parse, health, and benchmark sidecars before trusting chunk totals.",
                )
            )

        manifest_documents.append(
            {
                "document_id": document.document_id,
                "source_path": document.source_path,
                "markdown_path": document.markdown_path,
                "manifest_status": document.status,
                "manifest_chunk_count": manifest_chunks,
                "observed_status": observed.get("status") if observed else None,
                "observed_chunk_count": observed_chunks,
                "observed_state": _compact_observed_state(observed) if observed else None,
                "issues": document_issue_codes,
            }
        )

    observed_documents = list(observed_states.values())
    status_counts: dict[str, int] = {}
    refresh_state_counts = {"succeeded": 0, "failed": 0, "in_progress": 0, "unknown": 0}
    extra_observed_documents: list[dict[str, Any]] = []
    for state in observed_documents:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        refresh_label = _refresh_state_label(state)
        refresh_state_counts[refresh_label] = refresh_state_counts.get(refresh_label, 0) + 1
        chunks = _as_int(state.get("chunk_count"))
        if chunks is not None:
            observed_chunk_document_count += 1
            observed_chunk_total += chunks
        document_id = str(state.get("document_id") or "")
        if document_id and document_id not in matched_observed_ids:
            extra_observed_documents.append(_compact_observed_state(state) or dict(state))
            issues.append(
                _issue(
                    severity="warning",
                    code="observed_document_not_in_manifest",
                    message=f"Observed document {document_id} is not linked from the KB manifest.",
                    recommendation="Review whether this document is an intentional visual/manual upload or stale server-side residue.",
                )
            )
        if refresh_label == "failed":
            issues.append(
                _issue(
                    severity="warning",
                    code="observed_document_parse_failed",
                    message=f"Observed document {document_id or state.get('name') or 'unknown'} is in a failed parse state.",
                    recommendation="Inspect RAGFlow progress details before retrying parse or refreshing the manifest.",
                )
            )
        elif refresh_label in {"in_progress", "unknown"}:
            issues.append(
                _issue(
                    severity="warning",
                    code="observed_document_in_progress",
                    message=f"Observed document {document_id or state.get('name') or 'unknown'} is not completed yet.",
                    recommendation="Wait for parse completion or rerun refresh-report before production activation.",
                )
            )

    missing_manifest_count = len(kb_manifest.documents) - matched_document_count
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    status = "FAIL" if error_count else "REVIEW" if warning_count else "PASS"

    return {
        "ok": error_count == 0,
        "schema": KB_REFRESH_REPORT_SCHEMA,
        "created_at": _now(),
        "status": status,
        "advisory_only": True,
        "mutation": "none",
        "execution": {
            "status": "completed",
            "ragflow_calls": 1,
            "list_documents_call_count": 1,
            "document_list_page": page,
            "document_list_page_size": page_size,
            "db_calls": 0,
            "redis_calls": 0,
            "docker_calls": 0,
            "system_service_calls": 0,
        },
        "inputs": {
            "kb_manifest": str(kb_manifest_path),
            "document_list_source": "ragflow_client.list_documents",
            "page": page,
            "page_size": page_size,
        },
        "dataset": {
            "id": kb_manifest.dataset.id,
            "name": kb_manifest.dataset.name,
            "ragflow_base_url": kb_manifest.ragflow_base_url,
        },
        "summary": {
            "manifest_document_count": len(kb_manifest.documents),
            "observed_document_count": len(observed_documents),
            "matched_document_count": matched_document_count,
            "missing_manifest_document_count": missing_manifest_count,
            "extra_observed_document_count": len(extra_observed_documents),
            "manifest_chunk_total": manifest_chunk_total,
            "observed_chunk_total": observed_chunk_total if observed_chunk_document_count or observed_documents else None,
            "observed_chunk_document_count": observed_chunk_document_count,
            "chunk_mismatch_count": chunk_mismatch_count,
            "succeeded_document_count": refresh_state_counts.get("succeeded", 0),
            "failed_document_count": refresh_state_counts.get("failed", 0),
            "in_progress_document_count": refresh_state_counts.get("in_progress", 0) + refresh_state_counts.get("unknown", 0),
            "status_counts": dict(sorted(status_counts.items())),
            "issue_count": len(issues),
            "warning_count": warning_count,
            "error_count": error_count,
        },
        "manifest_documents": manifest_documents,
        "observed_documents": [_compact_observed_state(state) or dict(state) for state in observed_documents],
        "extra_observed_documents": extra_observed_documents,
        "issues": issues,
        "next_steps": _refresh_next_steps(issues),
    }


def render_kb_refresh_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown summary for a read-only KB refresh report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    dataset = report.get("dataset", {}) if isinstance(report.get("dataset"), Mapping) else {}
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    missing = [
        item
        for item in report.get("manifest_documents", [])
        if isinstance(item, Mapping) and "manifest_document_missing_observed_state" in (item.get("issues") or [])
    ]
    lines = [
        "# RAGFlow KB Refresh Report",
        "",
        f"- schema: `{report.get('schema', KB_REFRESH_REPORT_SCHEMA)}`",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- mutation: `{report.get('mutation', 'none')}`",
        f"- dataset: `{dataset.get('name', '')}` (`{dataset.get('id', '')}`)",
        f"- manifest documents: `{summary.get('manifest_document_count', 0)}`",
        f"- observed documents: `{summary.get('observed_document_count', 0)}`",
        f"- matched documents: `{summary.get('matched_document_count', 0)}`",
        f"- missing manifest documents: `{summary.get('missing_manifest_document_count', 0)}`",
        f"- extra observed documents: `{summary.get('extra_observed_document_count', 0)}`",
        f"- chunk mismatches: `{summary.get('chunk_mismatch_count', 0)}`",
        f"- failed documents: `{summary.get('failed_document_count', 0)}`",
        f"- in-progress documents: `{summary.get('in_progress_document_count', 0)}`",
        "",
        "## Missing manifest documents",
        "",
    ]
    if missing:
        for item in missing[:20]:
            lines.append(f"- `{item.get('document_id', '')}` `{item.get('markdown_path', '')}`")
    else:
        lines.append("- None.")
    lines.extend(["", "## Issues", ""])
    if issues:
        for issue in issues[:30]:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    else:
        lines.append("- No issues found.")
    next_steps = report.get("next_steps") if isinstance(report.get("next_steps"), list) else []
    if next_steps:
        lines.extend(["", "## Next Steps", ""])
        for step in next_steps:
            lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def _profile_manifest_dict(profile: ChunkProfile | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(profile, ChunkProfile):
        return profile.to_manifest_dict()
    return dict(profile)


def _visual_assets_from_upload_plan(asset_upload_plan: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(asset_upload_plan, Mapping):
        return []
    raw_files = asset_upload_plan.get("planned_visual_upload_files")
    if not isinstance(raw_files, list):
        return []
    assets: list[dict[str, Any]] = []
    for item in raw_files:
        if not isinstance(item, Mapping):
            continue
        source_path = item.get("source_path")
        package_path = item.get("package_path")
        if not isinstance(source_path, str) or not source_path:
            continue
        assets.append(
            {
                "source_path": source_path,
                "package_path": package_path if isinstance(package_path, str) and package_path else source_path,
                "asset_class": item.get("asset_class") if isinstance(item.get("asset_class"), str) else None,
                "sha256": item.get("sha256") if isinstance(item.get("sha256"), str) else None,
                "mime_type": item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
                "name": Path(source_path).name,
            }
        )
    return assets


def _state_by_name(states: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_name: dict[str, Mapping[str, Any]] = {}
    for state in states.values():
        name = state.get("name")
        if isinstance(name, str) and name:
            by_name.setdefault(Path(name).name, state)
    return by_name


def _compact_observed_state(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not state:
        return None
    return {
        "document_id": state.get("document_id"),
        "name": state.get("name"),
        "document_kind": state.get("document_kind"),
        "status": state.get("status"),
        "chunk_count": state.get("chunk_count"),
        "progress": state.get("progress"),
        "progress_msg": state.get("progress_msg"),
        "mime_type": state.get("mime_type"),
        "thumbnail": state.get("thumbnail"),
        "vlm_status": state.get("vlm_status"),
    }


def make_multimodal_kb_manifest_payload(
    *,
    base_url: str | None,
    dataset_id: str,
    dataset_name: str,
    profile: ChunkProfile | Mapping[str, Any],
    markdown_documents: list[tuple[BuildDocument, str, str | None, int | None]],
    asset_upload_plan: Mapping[str, Any] | None = None,
    document_list_response: Any | None = None,
) -> dict[str, Any]:
    """Create a multimodal KB manifest from build inputs and read-only document state."""

    observed_states = extract_document_states(document_list_response) if document_list_response is not None else {}
    observed_by_name = _state_by_name(observed_states)

    markdown_records: list[dict[str, Any]] = []
    matched_observed_ids: set[str] = set()
    for doc, document_id, status, chunk_count in markdown_documents:
        observed = observed_states.get(document_id)
        if observed:
            matched_observed_ids.add(document_id)
        record = {
            "document_id": document_id,
            "source_path": doc.manifest_source_path,
            "markdown_path": str(doc.path),
            "status": str(observed.get("status") if observed else status or "").lower(),
            "chunk_count": observed.get("chunk_count") if observed else chunk_count,
            "observed_state": _compact_observed_state(observed),
        }
        markdown_records.append(record)

    visual_records: list[dict[str, Any]] = []
    for asset in _visual_assets_from_upload_plan(asset_upload_plan):
        observed = observed_by_name.get(Path(str(asset["source_path"])).name)
        if observed and isinstance(observed.get("document_id"), str):
            matched_observed_ids.add(str(observed["document_id"]))
        thumbnail = observed.get("thumbnail") if isinstance(observed, Mapping) else None
        record = {
            "document_id": observed.get("document_id") if observed else None,
            "name": observed.get("name") if observed else asset["name"],
            "source_path": asset["source_path"],
            "package_path": asset["package_path"],
            "asset_class": asset["asset_class"],
            "sha256": asset["sha256"],
            "mime_type": observed.get("mime_type") if observed and observed.get("mime_type") else asset["mime_type"],
            "status": observed.get("status") if observed else "not_observed",
            "chunk_count": observed.get("chunk_count") if observed else None,
            "thumbnail": thumbnail if isinstance(thumbnail, Mapping) else {"url": None, "observed": False},
            "vlm_status": observed.get("vlm_status") if observed else None,
            "observed_state": _compact_observed_state(observed),
        }
        visual_records.append(record)

    for document_id, state in observed_states.items():
        if document_id in matched_observed_ids or state.get("document_kind") != "image":
            continue
        visual_records.append(
            {
                "document_id": document_id,
                "name": state.get("name"),
                "source_path": None,
                "package_path": None,
                "asset_class": "observed_unlinked",
                "sha256": None,
                "mime_type": state.get("mime_type"),
                "status": state.get("status"),
                "chunk_count": state.get("chunk_count"),
                "thumbnail": state.get("thumbnail"),
                "vlm_status": state.get("vlm_status"),
                "observed_state": _compact_observed_state(state),
            }
        )

    manifest_documents = [*markdown_records, *visual_records]
    parsed_count = sum(1 for item in manifest_documents if parse_state_succeeded(item))
    failed_count = sum(1 for item in manifest_documents if parse_state_failed(item))
    chunk_total = sum(int(item.get("chunk_count") or 0) for item in manifest_documents)
    thumbnail_count = sum(1 for item in visual_records if isinstance(item.get("thumbnail"), Mapping) and item["thumbnail"].get("url"))
    vlm_count = sum(1 for item in visual_records if item.get("vlm_status"))

    return {
        "schema": MULTIMODAL_KB_MANIFEST_SCHEMA,
        "created_at": _now(),
        "ragflow_base_url": base_url,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "profile": _profile_manifest_dict(profile),
        "summary": {
            "document_count": len(manifest_documents),
            "markdown_document_count": len(markdown_records),
            "visual_document_count": len(visual_records),
            "observed_document_count": len(observed_states),
            "parsed_document_count": parsed_count,
            "failed_document_count": failed_count,
            "chunk_count": chunk_total,
            "thumbnail_document_count": thumbnail_count,
            "vlm_observed_document_count": vlm_count,
        },
        "markdown_documents": markdown_records,
        "visual_documents": visual_records,
        "observed_documents": list(observed_states.values()),
    }


def wait_for_document_states(
    client: Any,
    *,
    dataset_id: str,
    document_ids: list[str],
    timeout: float = 300.0,
    poll_interval: float = 2.0,
) -> dict[str, dict[str, Any]]:
    """Poll live document status until all requested documents are parsed or fail."""

    deadline = time.time() + timeout
    latest: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        response = client.list_documents(dataset_id)
        latest = extract_document_states(response, document_ids=document_ids)
        if latest and all(document_id in latest for document_id in document_ids):
            states = [latest[document_id] for document_id in document_ids]
            if all(parse_state_succeeded(state) for state in states):
                return latest
            failed = [state for state in states if parse_state_failed(state)]
            if failed:
                message = "; ".join(
                    f"{state.get('document_id')}: status={state.get('status')} message={state.get('progress_msg', '')}"
                    for state in failed[:3]
                )
                raise BuildError(f"RAGFlow parsing failed: {message}")
        time.sleep(poll_interval)

    raise BuildError(
        "timed out waiting for RAGFlow parsing: "
        + ", ".join(document_ids[:5])
        + ("..." if len(document_ids) > 5 else "")
    )
