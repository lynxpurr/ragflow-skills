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

from .manifests import DocManifest, KbDocumentEntry
from .profiles import ChunkProfile

KB_ASSET_UPLOAD_PLAN_SCHEMA = "ragflow_kb_asset_upload_plan_v1"
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"}
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
            _file_record(
                role="orphan_image",
                source_path=path,
                handoff_root=handoff_root,
                package_path=_relative_to_root(path, handoff_root),
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
    projected_files: list[dict[str, Any]] = []
    seen_projected: set[str] = set()
    referenced_image_paths: set[Path] = set()
    remote_image_count = 0
    local_image_reference_count = 0
    missing_image_count = 0
    outside_handoff_count = 0

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
                if not inside_handoff:
                    outside_handoff_count += 1
                if not exists:
                    missing_image_count += 1
                record = {
                    "source": "markdown_image_reference",
                    "document_index": index,
                    "document": raw_markdown,
                    "target": raw_target,
                    "resolved_path": _relative_to_root(resolved, handoff_root),
                    "package_path": _relative_to_root(resolved, handoff_root) if inside_handoff else None,
                    "exists": exists,
                    "inside_handoff": inside_handoff,
                    "remote": False,
                    "planned_for_package": exists and inside_handoff,
                }
                image_references.append(record)
                if exists and inside_handoff:
                    referenced_image_paths.add(resolved)
                    _add_projected_file(
                        projected_files,
                        seen_projected,
                        _file_record(
                            role="image_asset",
                            source_path=resolved,
                            handoff_root=handoff_root,
                            package_path=_relative_to_root(resolved, handoff_root),
                        ),
                    )
        for raw_asset_path in _document_asset_paths(item):
            document_record["manifest_image_asset_count"] += 1
            asset_path = Path(raw_asset_path)
            resolved = asset_path if asset_path.is_absolute() else handoff_root / asset_path
            inside_handoff = _is_relative_to(resolved, handoff_root)
            exists = resolved.is_file()
            if not inside_handoff:
                outside_handoff_count += 1
            if not exists:
                missing_image_count += 1
            record = {
                "source": "manifest_image_asset",
                "document_index": index,
                "document": raw_markdown,
                "path": raw_asset_path,
                "resolved_path": _relative_to_root(resolved, handoff_root),
                "package_path": _relative_to_root(resolved, handoff_root) if inside_handoff else None,
                "exists": exists,
                "inside_handoff": inside_handoff,
                "planned_for_package": exists and inside_handoff,
            }
            manifest_image_assets.append(record)
            if exists and inside_handoff:
                referenced_image_paths.add(resolved)
                _add_projected_file(
                    projected_files,
                    seen_projected,
                    _file_record(
                        role="image_asset",
                        source_path=resolved,
                        handoff_root=handoff_root,
                        package_path=_relative_to_root(resolved, handoff_root),
                    ),
                )
        documents.append(document_record)

    for ref in [*image_references, *manifest_image_assets]:
        if ref.get("remote"):
            continue
        if not ref.get("inside_handoff"):
            issues.append(
                _issue(
                    severity="error",
                    code="image_outside_handoff",
                    message=f"Local image reference is outside the handoff root: {ref.get('target') or ref.get('path')}",
                    recommendation="Copy image assets into the handoff and update Markdown references before upload.",
                )
            )
        elif not ref.get("exists"):
            issues.append(
                _issue(
                    severity="error",
                    code="image_missing",
                    message=f"Local image asset is missing: {ref.get('target') or ref.get('path')}",
                    recommendation="Regenerate the handoff with asset landing enabled or repair image paths.",
                )
            )

    orphan_images = _scan_orphan_images(handoff_root=handoff_root, referenced_paths=referenced_image_paths)
    if orphan_images:
        issues.append(
            _issue(
                severity="warning",
                code="orphan_images_detected",
                message="One or more handoff-local image files are not referenced by Markdown or doc_manifest assets.",
                recommendation="Review whether orphan images should be referenced, removed, or kept outside the upload package.",
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
            "discovered_image_artifact_count": len(manifest_image_assets),
            "planned_image_file_count": len([item for item in projected_files if item.get("role") == "image_asset"]),
            "missing_image_count": missing_image_count,
            "missing_image_asset_count": missing_image_count,
            "outside_handoff_image_count": outside_handoff_count,
            "orphan_image_count": len(orphan_images),
            "unreferenced_handoff_image_count": len(orphan_images),
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
        "orphan_images": orphan_images[:50],
        "sidecars": sidecars,
        "projected_upload_files": projected_files,
        "issues": issues,
        "upload_policy": {
            "current_live_upload_path": "markdown_only",
            "planned_package_mode": "zip",
            "live_mutation_requires_existing_build_gate": True,
            "notes": [
                "This report does not call RAGFlow.",
                "Only handoff-local existing Markdown, image, and sidecar files are projected into the package.",
                "Live upload of the package remains disabled until an explicit mutation gate approves it.",
            ],
        },
    }


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
    """Render a concise Markdown summary for ragflow_kb_asset_upload_plan_v1."""

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
        f"- planned image files: `{summary.get('planned_image_file_count', 0)}`",
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
) -> dict[str, Any]:
    """Create a serializable KB manifest payload."""

    return {
        "version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ragflow_base_url": base_url,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "profile": profile.to_manifest_dict(),
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
        "status": effective_status,
        "chunk_count": chunk_count,
        "progress": progress,
        "progress_msg": message,
        "raw_status": status,
        "run": run,
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
