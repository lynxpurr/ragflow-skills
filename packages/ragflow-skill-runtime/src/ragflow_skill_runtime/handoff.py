"""Rich handoff sidecars for portable RAGFlow document packages."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_convert import sha256_file
from .doc_quality import DocQualityError, load_doc_manifest_payload
from .html_tables import parse_html_tables


HANDOFF_PACKAGE_SCHEMA = "ragflow_handoff_package_v1"
DOCUMENT_METADATA_SCHEMA = "ragflow_document_metadata_v1"
ARTIFACT_INDEX_SCHEMA = "ragflow_artifact_index_v1"
PROFILE_SUGGESTIONS_SCHEMA = "ragflow_profile_suggestions_v1"
RETRIEVAL_HINTS_SCHEMA = "ragflow_retrieval_hints_v1"
ASSISTANT_PROFILE_SCHEMA = "ragflow_assistant_profile_v1"
ASSISTANT_TEST_PLAN_SCHEMA = "ragflow_assistant_test_plan_v1"
RAGFLOW_INGEST_PLAN_SCHEMA = "ragflow_ingest_plan_v1"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
NUMERIC_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:\s?[%A-Za-zμ°/-]+)?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
CJK_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
PAGE_COMMENT_RE = re.compile(
    r"<!--\s*(?:page|page_id|page-id|page_index|page-index)\s*[:=]?\s*(\d+)\s*-->",
    re.IGNORECASE,
)
PAGE_TEXT_RE = re.compile(r"^\s*(?:page|p\.|第)\s*([0-9]{1,5})\s*(?:页)?\s*$", re.IGNORECASE)
CHUNK_MARKER = "<!-- chunk -->"

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


def _parse_yaml_scalar(value: str) -> Any:
    if value == "":
        return None
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip().strip("\"'")


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            raise HandoffError(f"tabs are not supported in handoff YAML: {path}")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((len(line) - len(line.lstrip(" ")), stripped))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        current_indent, current = lines[index]
        if current_indent < indent:
            return {}, index
        if current_indent != indent:
            raise HandoffError(f"unsupported YAML indentation in {path}: {current!r}")
        if current.startswith("-"):
            items: list[Any] = []
            while index < len(lines):
                item_indent, item = lines[index]
                if item_indent < indent:
                    break
                if item_indent != indent or not item.startswith("-"):
                    raise HandoffError(f"unsupported YAML list item in {path}: {item!r}")
                rest = item[1:].strip()
                if rest:
                    items.append(_parse_yaml_scalar(rest))
                    index += 1
                else:
                    child, index = parse_block(index + 1, indent + 2)
                    items.append(child)
            return items, index

        mapping: dict[str, Any] = {}
        while index < len(lines):
            item_indent, item = lines[index]
            if item_indent < indent:
                break
            if item_indent != indent or item.startswith("-"):
                raise HandoffError(f"unsupported YAML mapping entry in {path}: {item!r}")
            if ":" not in item:
                raise HandoffError(f"unsupported YAML line in {path}: {item!r}")
            key, raw_value = item.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if not key:
                raise HandoffError(f"empty YAML key in {path}")
            if raw_value:
                mapping[key] = _parse_yaml_scalar(raw_value)
                index += 1
            else:
                child, index = parse_block(index + 1, indent + 2)
                mapping[key] = child
        return mapping, index

    if not lines:
        return {}
    payload, index = parse_block(0, lines[0][0])
    if index != len(lines):
        raise HandoffError(f"unsupported trailing YAML content in {path}")
    if not isinstance(payload, dict):
        raise HandoffError(f"handoff YAML must contain a mapping: {path}")
    return payload


def load_ragflow_ingest_plan(path: str | Path) -> dict[str, Any]:
    """Load a ragflow_ingest_plan_v1 sidecar from JSON or simple generated YAML."""

    source = Path(path)
    try:
        if source.suffix.lower() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
        elif source.suffix.lower() in {".yaml", ".yml"}:
            payload = _read_simple_yaml(source)
        else:
            raise HandoffError(f"unsupported ingest plan extension: {source.suffix}")
    except FileNotFoundError as exc:
        raise HandoffError(f"ingest plan not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffError(f"ingest plan is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise HandoffError(f"ingest plan must contain an object: {source}")
    if payload.get("schema") != RAGFLOW_INGEST_PLAN_SCHEMA:
        raise HandoffError(f"ingest plan schema must be {RAGFLOW_INGEST_PLAN_SCHEMA}")
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


def _is_remote_image_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
        or lowered.startswith("#")
        or lowered.startswith("mailto:")
    )


def _image_reference_path(raw: str) -> str:
    value = raw.strip().strip("<>")
    if " " in value and not value.startswith(("./", "../", "/")):
        value = value.split(" ", 1)[0]
    return value.split("#", 1)[0].split("?", 1)[0]


def _document_image_asset_paths(document: Mapping[str, Any]) -> list[str]:
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
        path = item.get("path")
        if isinstance(path, str) and path.strip():
            paths.append(path.strip())
    return paths


def _inspect_image_assets(*, root: Path, documents: list[Mapping[str, Any]]) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    manifest_assets: list[dict[str, Any]] = []
    for document in documents:
        markdown_raw = document.get("markdown_path")
        markdown_path = _resolve_handoff_path(root, str(markdown_raw)) if isinstance(markdown_raw, str) else None
        if markdown_path is None or not markdown_path.is_file():
            if isinstance(markdown_raw, str):
                missing.append(
                    {
                        "type": "markdown",
                        "document": markdown_raw,
                        "path": markdown_raw,
                        "reason": "markdown_missing",
                    }
                )
            continue
        text = markdown_path.read_text(encoding="utf-8")
        for match in IMAGE_RE.finditer(text):
            raw = _image_reference_path(match.group(1))
            if not raw or _is_remote_image_reference(raw):
                continue
            image_path = Path(raw)
            resolved = image_path if image_path.is_absolute() else markdown_path.parent / image_path
            record = {
                "type": "markdown_reference",
                "document": _relative(markdown_path, root),
                "path": raw,
                "resolved_path": _relative(resolved, root),
                "exists": resolved.is_file(),
            }
            references.append(record)
            if not resolved.is_file():
                missing.append(record)
        for raw in _document_image_asset_paths(document):
            resolved = _resolve_handoff_path(root, raw)
            record = {
                "type": "manifest_asset",
                "document": _relative(markdown_path, root),
                "path": raw,
                "resolved_path": _relative(resolved, root),
                "exists": resolved.is_file(),
            }
            manifest_assets.append(record)
            if not resolved.is_file():
                missing.append(record)
    return {
        "markdown_reference_count": len(references),
        "manifest_image_count": len(manifest_assets),
        "missing_image_count": len(missing),
        "missing_images": missing[:25],
        "ok": not missing,
    }


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


def _source_inventory_record(
    *,
    source_path: str,
    source_file: Path | None,
    manifest_item: Mapping[str, Any],
) -> dict[str, Any]:
    mime_type, _encoding = mimetypes.guess_type(source_path)
    exists = bool(source_file and source_file.is_file())
    record: dict[str, Any] = {
        "source_path": source_path,
        "source_format": Path(source_path).suffix.lower().lstrip(".") if source_path else None,
        "mime_hint": mime_type,
        "size_bytes": source_file.stat().st_size if exists and source_file else None,
        "sha256": manifest_item.get("sha256") or (sha256_file(source_file) if exists and source_file else None),
        "language_hint": manifest_item.get("language"),
        "exists_in_handoff": exists,
    }
    return record


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
            "source_inventory": _source_inventory_record(
                source_path=source_path,
                source_file=source_file,
                manifest_item=item,
            ),
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


def _read_markdown(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _count_table_blocks(lines: list[str]) -> int:
    count = 0
    in_table = False
    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.count("|") >= 2 and not stripped.startswith("```")
        if is_table_line and not in_table:
            count += 1
        in_table = is_table_line
    return count


def _compact_text(value: str, *, limit: int = 180) -> str:
    compacted = " ".join(value.strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(limit - 1, 0)].rstrip() + "..."


def _line_page_map(lines: list[str]) -> tuple[dict[int, int], list[dict[str, Any]]]:
    page_by_line: dict[int, int] = {}
    markers: list[dict[str, Any]] = []
    current_page: int | None = None
    for index, line in enumerate(lines, start=1):
        page: int | None = None
        comment_match = PAGE_COMMENT_RE.search(line)
        if comment_match:
            page = int(comment_match.group(1))
        elif line == "\f":
            page = 1 if current_page is None else current_page + 1
        else:
            text_match = PAGE_TEXT_RE.match(line)
            if text_match:
                page = int(text_match.group(1))
        if page is not None:
            current_page = page
            markers.append({"line": index, "page": page})
        if current_page is not None:
            page_by_line[index] = current_page
    return page_by_line, markers


def _page_for_line(page_by_line: Mapping[int, int], line: int) -> int | None:
    page = page_by_line.get(line)
    return int(page) if isinstance(page, int) else None


def _section_for_line(sections: list[Mapping[str, Any]], line: int) -> Mapping[str, Any] | None:
    for section in sections:
        if int(section.get("line_start", 0)) <= line <= int(section.get("line_end", 0)):
            return section
    return None


def _context_snippet(lines: list[str], *, line: int, radius: int = 2) -> str | None:
    start = max(line - radius - 1, 0)
    end = min(line + radius, len(lines))
    candidates: list[str] = []
    for candidate in lines[start:end]:
        stripped = candidate.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        if MARKDOWN_IMAGE_RE.search(stripped):
            continue
        if stripped.count("|") >= 2:
            continue
        lowered = stripped.lower()
        if any(marker in lowered for marker in ("<table", "<thead", "<tbody", "<tr", "<th", "<td")):
            continue
        candidates.append(stripped)
    if not candidates:
        return None
    return _compact_text(" ".join(candidates), limit=240)


def _table_blocks(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    start: int | None = None
    rows: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_table_line = stripped.count("|") >= 2 and not stripped.startswith("```")
        if is_table_line:
            if start is None:
                start = index
            rows.append(stripped)
            continue
        if start is not None:
            blocks.append({"line_start": start, "line_end": index - 1, "rows": rows})
            start = None
            rows = []
    if start is not None:
        blocks.append({"line_start": start, "line_end": len(lines), "rows": rows})
    return blocks


def _table_header_preview(rows: list[str]) -> list[str]:
    if not rows:
        return []
    header = rows[0].strip().strip("|")
    return [_compact_text(cell, limit=40) for cell in header.split("|") if cell.strip()][:8]


def _safe_relative_reference(value: str) -> bool:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith(("/", "~")):
        return False
    if ":" in normalized.split("/", 1)[0]:
        return False
    return ".." not in [part for part in normalized.split("/") if part]


def _public_local_asset_path(raw: str, *, root: Path, base: Path) -> str | None:
    target = _image_reference_path(raw)
    if not target or _is_remote_image_reference(target):
        return None
    if not _safe_relative_reference(target):
        return None
    resolved = (base / target).resolve(strict=False)
    try:
        return resolved.relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return None


def _markdown_image_contexts(
    *,
    markdown_rel: str,
    text: str,
    sections: list[Mapping[str, Any]],
    page_by_line: Mapping[int, int],
    root: Path,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    lines = text.splitlines()
    markdown_parent = (root / markdown_rel).parent
    for index, line in enumerate(lines, start=1):
        for match in MARKDOWN_IMAGE_RE.finditer(line):
            raw_target = _image_reference_path(match.group(2))
            public_path = _public_local_asset_path(raw_target, root=root, base=markdown_parent)
            if public_path is None:
                continue
            resolved = root / public_path
            section = _section_for_line(sections, index) or {}
            alt_text = _compact_text(match.group(1), limit=120)
            context: dict[str, Any] = {
                "kind": "image",
                "path": public_path,
                "markdown_target": raw_target if _safe_relative_reference(raw_target) else public_path,
                "document": markdown_rel,
                "line": index,
                "source_heading": section.get("title"),
                "heading_level": section.get("level"),
                "page": _page_for_line(page_by_line, index),
                "exists": resolved.is_file(),
                "source": "markdown_image_reference",
            }
            if alt_text:
                context["alt_text"] = alt_text
                context["caption"] = alt_text
            snippet = _context_snippet(lines, line=index)
            if snippet:
                context["context"] = snippet
            contexts.append(context)
    return contexts


def _markdown_table_contexts(
    *,
    markdown_rel: str,
    text: str,
    sections: list[Mapping[str, Any]],
    page_by_line: Mapping[int, int],
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for block in _table_blocks(text.splitlines()):
        line_start = int(block["line_start"])
        section = _section_for_line(sections, line_start) or {}
        contexts.append(
            {
                "kind": "table",
                "document": markdown_rel,
                "line_start": line_start,
                "line_end": int(block["line_end"]),
                "source_heading": section.get("title"),
                "heading_level": section.get("level"),
                "page": _page_for_line(page_by_line, line_start),
                "row_count": len(block["rows"]),
                "header_preview": _table_header_preview(block["rows"]),
                "source": "markdown_table",
            }
        )
    return contexts


def _html_table_contexts(
    *,
    markdown_rel: str,
    text: str,
    sections: list[Mapping[str, Any]],
    page_by_line: Mapping[int, int],
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    lines = text.splitlines()
    for table in parse_html_tables(text):
        line_start = int(table.line_start)
        section = _section_for_line(sections, line_start) or {}
        context: dict[str, Any] = {
            "kind": "table",
            "document": markdown_rel,
            "line_start": line_start,
            "line_end": int(table.line_end),
            "source_heading": section.get("title"),
            "heading_level": section.get("level"),
            "page": _page_for_line(page_by_line, line_start),
            "row_count": int(table.row_count),
            "column_count": int(table.column_count),
            "header_preview": list(table.header_preview),
            "source": "html_table",
        }
        if table.caption:
            context["caption"] = table.caption
        snippet = _context_snippet(lines, line=line_start)
        if snippet:
            context["context"] = snippet
        if table.warnings:
            context["warnings"] = list(table.warnings)
        contexts.append(context)
    return contexts


def _section_stats(lines: list[str], *, line_start: int, line_end: int) -> dict[str, int]:
    section_lines = lines[max(line_start - 1, 0) : max(line_end, line_start - 1)]
    section_text = "\n".join(section_lines)
    markdown_table_count = _count_table_blocks(section_lines)
    html_table_count = len(parse_html_tables(section_text))
    return {
        "image_count": len(IMAGE_RE.findall(section_text)),
        "table_count": markdown_table_count + html_table_count,
        "markdown_table_count": markdown_table_count,
        "html_table_count": html_table_count,
        "list_item_count": sum(1 for line in section_lines if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)),
        "chunk_marker_count": sum(1 for line in section_lines if CHUNK_MARKER in line),
    }


def _section_boundaries(*, markdown_rel: str, text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    page_by_line, _markers = _line_page_map(lines)
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line)
        if match:
            headings.append(
                {
                    "document": markdown_rel,
                    "title": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "line_start": index,
                }
            )
    if not headings and lines:
        headings.append(
            {
                "document": markdown_rel,
                "title": Path(markdown_rel).stem,
                "level": 0,
                "line_start": 1,
            }
        )
    for position, heading in enumerate(headings):
        next_start = headings[position + 1]["line_start"] if position + 1 < len(headings) else len(lines) + 1
        heading["line_end"] = max(int(next_start) - 1, int(heading["line_start"]))
        page_start = _page_for_line(page_by_line, int(heading["line_start"]))
        page_end = _page_for_line(page_by_line, int(heading["line_end"]))
        if page_start is not None:
            heading["page_start"] = page_start
        if page_end is not None:
            heading["page_end"] = page_end
        heading.update(_section_stats(lines, line_start=int(heading["line_start"]), line_end=int(heading["line_end"])))
    return headings


def _add_keyword_candidate(candidates: dict[str, dict[str, Any]], *, term: str, source: str, weight: float) -> None:
    normalized = " ".join(term.strip(" #`*_:-").split())
    if not normalized:
        return
    key = normalized.lower()
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in normalized)
    if (len(key) < 3 and not has_cjk) or key in STOPWORDS:
        return
    if key not in candidates:
        candidates[key] = {"term": normalized, "source": source, "weight": weight}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


DOC_TYPE_TEMPLATES: dict[str, dict[str, Any]] = {
    "zh_product_catalog": {
        "keywords": ["产品", "产品目录", "型号", "规格", "技术参数", "性能", "精度", "尺寸", "配置", "选型", "应用"],
        "questions": [
            ("product_spec_lookup", "有哪些型号、规格或技术参数可用于选型？"),
            ("product_dimension_lookup", "产品的尺寸、精度或性能参数是什么？"),
        ],
    },
    "zh_industrial_manual": {
        "keywords": ["安装", "维护", "操作", "安全", "调试", "故障", "保养", "注意事项", "设备"],
        "questions": [
            ("manual_procedure_lookup", "安装、操作或维护步骤有哪些关键要求？"),
            ("safety_requirement_lookup", "文档中列出了哪些安全注意事项或故障处理要求？"),
        ],
    },
    "zh_paper": {
        "keywords": ["摘要", "关键词", "研究", "方法", "实验", "结果", "结论", "参考文献"],
        "questions": [
            ("paper_summary_lookup", "论文的研究问题、方法和结论是什么？"),
            ("paper_evidence_lookup", "实验结果或关键数据支持了哪些结论？"),
        ],
    },
    "en_product_catalog": {
        "keywords": ["product", "catalog", "model", "specification", "parameter", "accuracy", "dimension", "configuration"],
        "questions": [
            ("product_spec_lookup", "Which models, specifications, or technical parameters are listed for selection?"),
            ("product_dimension_lookup", "What dimensions, accuracy, or performance parameters does the source state?"),
        ],
    },
    "en_manual": {
        "keywords": ["installation", "maintenance", "operation", "safety", "troubleshooting", "equipment"],
        "questions": [
            ("manual_procedure_lookup", "What installation, operation, or maintenance requirements are stated?"),
            ("safety_requirement_lookup", "What safety notes or troubleshooting requirements are listed?"),
        ],
    },
    "en_paper": {
        "keywords": ["abstract", "method", "experiment", "result", "conclusion", "reference"],
        "questions": [
            ("paper_summary_lookup", "What research question, method, and conclusion does the paper present?"),
            ("paper_evidence_lookup", "Which results or numeric evidence support the conclusion?"),
        ],
    },
}


DOC_TYPE_SIGNALS: dict[str, list[str]] = {
    "zh_product_catalog": ["产品目录", "产品", "型号", "规格", "技术参数", "性能", "精度", "尺寸", "配置", "选型", "应用"],
    "zh_industrial_manual": ["安装", "维护", "操作", "安全", "调试", "故障", "保养", "注意事项", "设备"],
    "zh_paper": ["摘要", "关键词", "研究", "方法", "实验", "结果", "结论", "参考文献"],
    "en_product_catalog": ["product", "catalog", "model", "specification", "parameter", "accuracy", "dimension", "configuration"],
    "en_manual": ["installation", "maintenance", "operation", "safety", "troubleshooting", "equipment"],
    "en_paper": ["abstract", "method", "experiment", "result", "conclusion", "reference"],
}


def _document_type_signal(*, markdown_rel: str, text: str, sections: list[Mapping[str, Any]]) -> dict[str, Any]:
    haystack = "\n".join(
        [
            text[:12000],
            "\n".join(str(section.get("title") or "") for section in sections),
        ]
    )
    haystack_lower = haystack.lower()
    scored: list[tuple[str, list[str]]] = []
    for doc_type, signals in DOC_TYPE_SIGNALS.items():
        matches: list[str] = []
        for signal in signals:
            if (_has_cjk(signal) and signal in haystack) or (not _has_cjk(signal) and signal.lower() in haystack_lower):
                matches.append(signal)
        if matches:
            scored.append((doc_type, matches))
    if not scored:
        return {
            "document": markdown_rel,
            "document_type": "general_zh" if _has_cjk(haystack) else "general",
            "confidence": 0.2,
            "matched_signals": [],
        }
    scored.sort(key=lambda item: (len(item[1]), item[0]), reverse=True)
    doc_type, matches = scored[0]
    confidence = min(0.95, 0.35 + 0.1 * len(matches))
    return {
        "document": markdown_rel,
        "document_type": doc_type,
        "confidence": round(confidence, 2),
        "matched_signals": matches[:12],
    }


def _apply_template_keywords(
    candidates: dict[str, dict[str, Any]],
    *,
    document_type_signals: list[Mapping[str, Any]],
) -> None:
    for signal in document_type_signals:
        doc_type = signal.get("document_type")
        template = DOC_TYPE_TEMPLATES.get(str(doc_type))
        if not template:
            continue
        for term in template.get("keywords", []):
            if isinstance(term, str):
                _add_keyword_candidate(candidates, term=term, source=f"deterministic_template:{doc_type}", weight=0.65)


def _keyword_candidates(
    *,
    sections: list[Mapping[str, Any]],
    documents: list[Mapping[str, Any]],
    document_type_signals: list[Mapping[str, Any]] | None = None,
    image_artifacts: list[Mapping[str, Any]] | None = None,
    table_artifacts: list[Mapping[str, Any]] | None = None,
    layout_signals: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for document in documents:
        title = document.get("title")
        if isinstance(title, str):
            _add_keyword_candidate(candidates, term=title, source="document_title", weight=1.0)
    for section in sections:
        title = section.get("title")
        if not isinstance(title, str):
            continue
        _add_keyword_candidate(candidates, term=title, source="heading", weight=0.9)
        for word in WORD_RE.findall(title):
            _add_keyword_candidate(candidates, term=word, source="heading_word", weight=0.5)
        for phrase in CJK_PHRASE_RE.findall(title):
            _add_keyword_candidate(candidates, term=phrase, source="heading_phrase", weight=0.7)
    _apply_template_keywords(candidates, document_type_signals=list(document_type_signals or []))
    for artifact in list(image_artifacts or []) + list(table_artifacts or []):
        for key in ("caption", "alt_text", "source_heading"):
            value = artifact.get(key)
            if isinstance(value, str):
                _add_keyword_candidate(candidates, term=value, source=f"{artifact.get('kind', 'artifact')}_{key}", weight=0.45)
    for signal in list(layout_signals or []):
        text = signal.get("text") or signal.get("caption")
        if isinstance(text, str):
            for phrase in CJK_PHRASE_RE.findall(text[:120]):
                _add_keyword_candidate(candidates, term=phrase, source="layout_signal_phrase", weight=0.35)
    return sorted(candidates.values(), key=lambda item: (-float(item.get("weight", 0)), str(item.get("term", ""))))[:60]


def _question_candidates(
    *,
    sections: list[Mapping[str, Any]],
    numeric_candidates: list[Mapping[str, Any]],
    document_type_signals: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for section in sections[:12]:
        title = section.get("title")
        if not isinstance(title, str) or not title:
            continue
        question = f"请概述“{title}”的关键信息。" if _has_cjk(title) else f"What key facts are covered in {title}?"
        questions.append(
            {
                "question": question,
                "type": "section_summary",
                "source_document": section.get("document"),
                "source_heading": title,
                "line_start": section.get("line_start"),
            }
        )
        if section.get("table_count"):
            questions.append(
                {
                    "question": f"Which table-backed facts are listed under {title}?",
                    "type": "table_fact",
                    "source_document": section.get("document"),
                    "source_heading": title,
                    "line_start": section.get("line_start"),
                }
            )
        if section.get("image_count"):
            questions.append(
                {
                    "question": f"Which visual or image-backed details are associated with {title}?",
                    "type": "visual_fact",
                    "source_document": section.get("document"),
                    "source_heading": title,
                    "line_start": section.get("line_start"),
                }
            )
    seen_template_questions: set[tuple[str, str | None]] = set()
    for signal in list(document_type_signals or []):
        doc_type = str(signal.get("document_type") or "")
        template = DOC_TYPE_TEMPLATES.get(doc_type)
        if not template:
            continue
        for question_type, question in template.get("questions", []):
            key = (question_type, signal.get("document") if isinstance(signal.get("document"), str) else None)
            if key in seen_template_questions:
                continue
            seen_template_questions.add(key)
            questions.append(
                {
                    "question": question,
                    "type": question_type,
                    "source_document": signal.get("document"),
                    "document_type": doc_type,
                    "source": "deterministic_template",
                }
            )
    for candidate in numeric_candidates[:5]:
        questions.append(
            {
                "question": f"Where is the numeric value {candidate.get('value')} stated?",
                "type": "exact_numeric_fact",
                "source_document": candidate.get("document"),
                "source_heading": candidate.get("source_heading"),
                "line_start": candidate.get("line"),
                "page": candidate.get("page"),
            }
        )
    return questions[:30]


def _numeric_candidates(*, markdown_rel: str, text: str, sections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    section_by_line = sorted(sections, key=lambda item: int(item.get("line_start", 0)))
    page_by_line, _markers = _line_page_map(text.splitlines())
    for index, line in enumerate(text.splitlines(), start=1):
        if PAGE_COMMENT_RE.search(line) or PAGE_TEXT_RE.match(line) or CHUNK_MARKER in line:
            continue
        for match in NUMERIC_RE.finditer(line):
            heading = None
            for section in section_by_line:
                if int(section.get("line_start", 0)) <= index <= int(section.get("line_end", 0)):
                    heading = section.get("title")
                    break
            output.append(
                {
                    "value": match.group(0).strip(),
                    "document": markdown_rel,
                    "line": index,
                    "source_heading": heading,
                    "page": _page_for_line(page_by_line, index),
                }
            )
            if len(output) >= 20:
                return output
    return output


SIDECAR_CANDIDATES = (
    "content_list.json",
    "middle_json.json",
    "middle.json",
    "mineru_content_list.json",
    "mineru_middle_json.json",
)


def _safe_sidecar_record(path: Path, *, root: Path) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
    }


def _load_optional_layout_sidecars(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sidecars: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    def visit(value: Any, *, source: str, depth: int = 0) -> None:
        if depth > 4 or len(signals) >= 120:
            return
        if isinstance(value, Mapping):
            page = value.get("page") or value.get("page_idx") or value.get("page_id") or value.get("page_no")
            text = value.get("text") or value.get("content") or value.get("caption") or value.get("title")
            block_type = value.get("type") or value.get("kind") or value.get("category")
            image_path = value.get("image_path") or value.get("img_path") or value.get("path")
            level = value.get("level") or value.get("heading_level")
            record: dict[str, Any] = {"source": source}
            if isinstance(page, int):
                record["page"] = page
            elif isinstance(page, str) and page.isdigit():
                record["page"] = int(page)
            if isinstance(block_type, str):
                record["block_type"] = block_type
            if isinstance(text, str) and text.strip():
                record["text"] = _compact_text(text, limit=220)
            if isinstance(image_path, str) and _safe_relative_reference(image_path):
                record["path"] = image_path.strip().replace("\\", "/")
            if isinstance(level, int):
                record["level"] = level
            elif isinstance(level, str) and level.isdigit():
                record["level"] = int(level)
            if len(record) > 1:
                signals.append(record)
            for item in value.values():
                if isinstance(item, (Mapping, list)):
                    visit(item, source=source, depth=depth + 1)
        elif isinstance(value, list):
            for item in value[:200]:
                visit(item, source=source, depth=depth + 1)

    for relative_name in SIDECAR_CANDIDATES:
        path = root / relative_name
        if not path.is_file():
            continue
        record = _safe_sidecar_record(path, root=root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            record["status"] = "invalid_json"
        else:
            record["status"] = "loaded"
            visit(payload, source=relative_name)
        sidecars.append(record)
    return sidecars, signals


def _merge_artifact_contexts(
    *,
    artifacts: list[Mapping[str, Any]],
    contexts: list[Mapping[str, Any]],
    kind: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def key_for(item: Mapping[str, Any], fallback_index: int) -> str:
        path = item.get("path")
        if isinstance(path, str) and path:
            return path
        document = item.get("document")
        line = item.get("line") or item.get("line_start")
        return f"{document}:{line}:{fallback_index}"

    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            continue
        key = key_for(item, index)
        if key not in merged:
            order.append(key)
        merged[key] = dict(item)
        merged[key].setdefault("kind", kind)
    for index, item in enumerate(contexts, start=len(order)):
        if not isinstance(item, Mapping):
            continue
        key = key_for(item, index)
        if key not in merged:
            order.append(key)
            merged[key] = {}
        merged[key].update({key_name: value for key_name, value in item.items() if value is not None})
        merged[key].setdefault("kind", kind)
    return [merged[key] for key in order][:60]


def _preferred_boundaries(
    *,
    sections: list[Mapping[str, Any]],
    page_markers: list[Mapping[str, Any]],
    chunk_markers: list[Mapping[str, Any]],
    table_artifacts: list[Mapping[str, Any]] | None = None,
    image_artifacts: list[Mapping[str, Any]] | None = None,
    list_markers: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    boundaries: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int, str]] = set()

    def add(boundary: dict[str, Any]) -> None:
        line_start = boundary.get("line_start")
        if not isinstance(line_start, int):
            return
        key = (
            boundary.get("document") if isinstance(boundary.get("document"), str) else None,
            line_start,
            str(boundary.get("reason") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        boundaries.append({key_name: value for key_name, value in boundary.items() if value is not None})

    for section in sections:
        if int(section.get("level", 0)) <= 3:
            add(
                {
                    "document": section.get("document"),
                    "line_start": section.get("line_start"),
                    "line_end": section.get("line_end"),
                    "reason": "heading_boundary",
                    "title": section.get("title"),
                    "level": section.get("level"),
                    "page": section.get("page_start"),
                }
            )
    for marker in page_markers:
        add(
            {
                "document": marker.get("document"),
                "line_start": marker.get("line"),
                "line_end": marker.get("line"),
                "reason": "page_boundary",
                "page": marker.get("page"),
            }
        )
    for marker in chunk_markers:
        add(
            {
                "document": marker.get("document"),
                "line_start": marker.get("line"),
                "line_end": marker.get("line"),
                "reason": "chunk_marker_boundary",
                "page": marker.get("page"),
            }
        )
    for artifact in list(table_artifacts or []):
        add(
            {
                "document": artifact.get("document"),
                "line_start": artifact.get("line_start"),
                "line_end": artifact.get("line_end") or artifact.get("line_start"),
                "reason": "table_boundary",
                "title": artifact.get("caption") or artifact.get("source_heading"),
                "page": artifact.get("page"),
            }
        )
    for artifact in list(image_artifacts or []):
        line = artifact.get("line") or artifact.get("line_start")
        add(
            {
                "document": artifact.get("document"),
                "line_start": line,
                "line_end": line,
                "reason": "image_boundary",
                "title": artifact.get("caption") or artifact.get("alt_text") or artifact.get("source_heading"),
                "page": artifact.get("page"),
            }
        )
    for marker in list(list_markers or []):
        add(
            {
                "document": marker.get("document"),
                "line_start": marker.get("line"),
                "line_end": marker.get("line"),
                "reason": "list_boundary",
                "page": marker.get("page"),
            }
        )
    return boundaries[:100]


def _chunk_markers(*, markdown_rel: str, lines: list[str], page_by_line: Mapping[int, int]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if CHUNK_MARKER in line:
            markers.append(
                {
                    "document": markdown_rel,
                    "line": index,
                    "page": _page_for_line(page_by_line, index),
                }
            )
    return markers


def _list_boundaries(*, markdown_rel: str, lines: list[str], page_by_line: Mapping[int, int]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    previous_list = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_list = bool(re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", line))
        if is_list and not previous_list:
            markers.append(
                {
                    "document": markdown_rel,
                    "line": index,
                    "page": _page_for_line(page_by_line, index),
                }
            )
        if stripped:
            previous_list = is_list
    return markers


def _quality_risks(*, metadata: Mapping[str, Any], quality_report: Mapping[str, Any] | None, sections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    gate = quality_report.get("gate", {}) if isinstance(quality_report, Mapping) else {}
    status = gate.get("status") if isinstance(gate, Mapping) else None
    if status and status != "PASS":
        risks.append({"severity": "warning", "code": "quality_gate", "message": f"quality gate status is {status}"})
    documents = quality_report.get("documents", []) if isinstance(quality_report, Mapping) else []
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            for issue in document.get("issues", []) if isinstance(document.get("issues"), list) else []:
                if isinstance(issue, Mapping):
                    risks.append(
                        {
                            "severity": issue.get("severity") or "warning",
                            "code": issue.get("issue_type") or "quality_issue",
                            "message": issue.get("message") or "quality issue",
                            "path": issue.get("path"),
                        }
                    )
    for document in metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []:
        if not isinstance(document, Mapping):
            continue
        for warning in document.get("warnings", []) if isinstance(document.get("warnings"), list) else []:
            risks.append({"severity": "warning", "code": "conversion_warning", "message": str(warning)})
    if sum(int(section.get("image_count", 0)) for section in sections) > 10:
        risks.append({"severity": "info", "code": "image_rich", "message": "image-rich handoff; validate visual context retrieval"})
    return risks[:40]


def make_retrieval_hints_payload(
    *,
    handoff_root: str | Path,
    metadata: Mapping[str, Any],
    artifact_index: Mapping[str, Any] | None = None,
    quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic retrieval hints from Markdown headings and sidecars."""

    root = Path(handoff_root)
    documents = metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []
    sections: list[dict[str, Any]] = []
    numeric_candidates: list[dict[str, Any]] = []
    document_summaries: list[dict[str, Any]] = []
    markdown_image_artifacts: list[dict[str, Any]] = []
    markdown_table_artifacts: list[dict[str, Any]] = []
    document_type_signals: list[dict[str, Any]] = []
    page_markers: list[dict[str, Any]] = []
    chunk_markers: list[dict[str, Any]] = []
    list_markers: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_rel = str(markdown.get("path") or document.get("markdown_path") or "")
        if not markdown_rel:
            continue
        text = _read_markdown(root / markdown_rel)
        lines = text.splitlines()
        page_by_line, markers = _line_page_map(lines)
        for marker in markers:
            page_markers.append({"document": markdown_rel, **marker})
        document_sections = _section_boundaries(markdown_rel=markdown_rel, text=text)
        markdown_table_count = _count_table_blocks(lines)
        html_table_count = len(parse_html_tables(text))
        sections.extend(document_sections)
        numeric_candidates.extend(_numeric_candidates(markdown_rel=markdown_rel, text=text, sections=document_sections))
        markdown_image_artifacts.extend(
            _markdown_image_contexts(
                markdown_rel=markdown_rel,
                text=text,
                sections=document_sections,
                page_by_line=page_by_line,
                root=root,
            )
        )
        markdown_table_artifacts.extend(
            _markdown_table_contexts(
                markdown_rel=markdown_rel,
                text=text,
                sections=document_sections,
                page_by_line=page_by_line,
            )
        )
        markdown_table_artifacts.extend(
            _html_table_contexts(
                markdown_rel=markdown_rel,
                text=text,
                sections=document_sections,
                page_by_line=page_by_line,
            )
        )
        document_type_signals.append(_document_type_signal(markdown_rel=markdown_rel, text=text, sections=document_sections))
        chunk_markers.extend(_chunk_markers(markdown_rel=markdown_rel, lines=lines, page_by_line=page_by_line))
        list_markers.extend(_list_boundaries(markdown_rel=markdown_rel, lines=lines, page_by_line=page_by_line))
        document_summaries.append(
            {
                "markdown_path": markdown_rel,
                "title": document.get("title"),
                "section_count": len(document_sections),
                "line_count": len(lines),
                "image_count": text.count("!["),
                "table_count": markdown_table_count + html_table_count,
                "markdown_table_count": markdown_table_count,
                "html_table_count": html_table_count,
                "page_count": len({marker["page"] for marker in markers}),
                "chunk_marker_count": len([line for line in lines if CHUNK_MARKER in line]),
            }
        )

    artifacts = artifact_index.get("artifacts", []) if isinstance(artifact_index, Mapping) else []
    indexed_table_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "table"]
    indexed_image_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "image"]
    layout_sidecars, layout_signals = _load_optional_layout_sidecars(root)
    table_artifacts = _merge_artifact_contexts(
        artifacts=indexed_table_artifacts,
        contexts=markdown_table_artifacts,
        kind="table",
    )
    image_artifacts = _merge_artifact_contexts(
        artifacts=indexed_image_artifacts,
        contexts=markdown_image_artifacts,
        kind="image",
    )
    quality_risks = _quality_risks(metadata=metadata, quality_report=quality_report, sections=sections)
    keywords = _keyword_candidates(
        sections=sections,
        documents=[item for item in documents if isinstance(item, Mapping)],
        document_type_signals=document_type_signals,
        image_artifacts=image_artifacts,
        table_artifacts=table_artifacts,
        layout_signals=layout_signals,
    )
    questions = _question_candidates(
        sections=sections,
        numeric_candidates=numeric_candidates,
        document_type_signals=document_type_signals,
    )

    return {
        "schema": RETRIEVAL_HINTS_SCHEMA,
        "created_at": _now(),
        "document_count": len(document_summaries),
        "documents": document_summaries,
        "section_boundaries": sections,
        "table_artifacts": table_artifacts[:30],
        "image_artifacts": image_artifacts[:30],
        "keyword_candidates": keywords,
        "question_candidates": questions,
        "numeric_candidates": numeric_candidates[:20],
        "document_type_signals": document_type_signals,
        "layout_sidecars": layout_sidecars,
        "layout_signals": layout_signals[:60],
        "quality_risks": quality_risks,
        "preferred_boundaries": _preferred_boundaries(
            sections=sections,
            page_markers=page_markers,
            chunk_markers=chunk_markers,
            table_artifacts=table_artifacts,
            image_artifacts=image_artifacts,
            list_markers=list_markers,
        ),
    }


def make_assistant_profile_payload(
    *,
    retrieval_hints: Mapping[str, Any],
    profile_suggestions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a reviewable assistant retrieval profile without mutating RAGFlow."""

    sections = retrieval_hints.get("section_boundaries", [])
    sections = sections if isinstance(sections, list) else []
    section_count = len(sections)
    keyword_count = len(retrieval_hints.get("keyword_candidates", [])) if isinstance(retrieval_hints.get("keyword_candidates"), list) else 0
    has_visuals = bool(retrieval_hints.get("image_artifacts")) or any(
        isinstance(section, Mapping) and int(section.get("image_count", 0)) > 0
        for section in sections
    )
    top_k = 8 if section_count > 8 or has_visuals else 5
    similarity_threshold = 0.18 if has_visuals else 0.2
    suggestions = profile_suggestions.get("suggestions", []) if isinstance(profile_suggestions, Mapping) else []

    return {
        "schema": ASSISTANT_PROFILE_SCHEMA,
        "created_at": _now(),
        "profile_id": "handoff-review-default",
        "status": "review_required",
        "source_sidecars": {
            "retrieval_hints": "retrieval_hints.json",
            "profile_suggestions": "profile_suggestions.json",
        },
        "retrieval": {
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "vector_weight": 0.7,
            "bm25_weight": 0.3 if keyword_count else 0.0,
            "require_evidence": True,
            "quote_numeric_facts": True,
            "citation_format": "[n]",
        },
        "parser_profile_hint": suggestions[0] if suggestions and isinstance(suggestions[0], Mapping) else None,
        "answer_policy": [
            "Answer only from retrieved evidence.",
            "Cite or quote evidence for numbers, tables, images, and named entities.",
            "Say that the source does not contain the answer when evidence is missing.",
        ],
        "review_notes": [
            "This profile is advisory and does not modify RAGFlow assistant settings.",
            "Review retrieval thresholds after live smoke or benchmark validation.",
        ],
    }


def make_assistant_test_plan_payload(
    *,
    retrieval_hints: Mapping[str, Any],
    assistant_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Create staged assistant tests from retrieval hints."""

    questions = retrieval_hints.get("question_candidates", []) if isinstance(retrieval_hints.get("question_candidates"), list) else []
    sections = retrieval_hints.get("section_boundaries", []) if isinstance(retrieval_hints.get("section_boundaries"), list) else []
    numeric = retrieval_hints.get("numeric_candidates", []) if isinstance(retrieval_hints.get("numeric_candidates"), list) else []
    cases: list[dict[str, Any]] = []

    if questions:
        first = questions[0]
        if isinstance(first, Mapping):
            cases.append(
                {
                    "id": "summary-001",
                    "stage": "summary",
                    "question": first.get("question"),
                    "expected_behavior": "answer from cited retrieved evidence",
                    "source_document": first.get("source_document"),
                    "source_heading": first.get("source_heading"),
                }
            )
    if numeric:
        first_numeric = numeric[0]
        if isinstance(first_numeric, Mapping):
            cases.append(
                {
                    "id": "numeric-001",
                    "stage": "exact_numeric_fact",
                    "question": f"What does the source say about {first_numeric.get('value')}?",
                    "expected_behavior": "return the numeric fact with a citation",
                    "source_document": first_numeric.get("document"),
                    "source_heading": first_numeric.get("source_heading"),
                }
            )
    visual_section = next((section for section in sections if isinstance(section, Mapping) and int(section.get("image_count", 0)) > 0), None)
    if visual_section:
        cases.append(
            {
                "id": "visual-001",
                "stage": "ocr_image_fact",
                "question": f"What visual details are associated with {visual_section.get('title')}?",
                "expected_behavior": "answer only if retrieved evidence contains the visual or OCR-backed detail",
                "source_document": visual_section.get("document"),
                "source_heading": visual_section.get("title"),
            }
        )
    if len(sections) >= 2 and isinstance(sections[0], Mapping) and isinstance(sections[1], Mapping):
        cases.append(
            {
                "id": "flow-001",
                "stage": "logical_flow",
                "question": f"How are {sections[0].get('title')} and {sections[1].get('title')} related in the source?",
                "expected_behavior": "compare only the retrieved source sections and avoid outside assumptions",
                "source_document": sections[0].get("document"),
            }
        )
    for index, question in enumerate(questions[1:4], start=1):
        if isinstance(question, Mapping):
            cases.append(
                {
                    "id": f"paraphrase-{index:03d}",
                    "stage": "paraphrase",
                    "question": question.get("question"),
                    "expected_behavior": "retrieve the same source section even when phrasing differs",
                    "source_document": question.get("source_document"),
                    "source_heading": question.get("source_heading"),
                }
            )
    cases.append(
        {
            "id": "negative-001",
            "stage": "negative_boundary",
            "question": "What private API key or deployment secret is used by this source?",
            "expected_behavior": "abstain because the public handoff must not contain secrets",
        }
    )

    return {
        "schema": ASSISTANT_TEST_PLAN_SCHEMA,
        "created_at": _now(),
        "assistant_profile": assistant_profile.get("profile_id"),
        "status": "review_required",
        "test_count": len(cases),
        "cases": cases,
    }


def make_package_readme(
    *,
    doc_manifest_name: str,
    metadata_name: str,
    artifact_index_name: str,
    profile_suggestions_name: str,
    retrieval_hints_name: str,
    assistant_profile_name: str,
    assistant_test_plan_name: str,
    quality_report_name: str | None,
    handoff_mode: str | None = None,
) -> str:
    """Render a compact README for a rich handoff package."""

    lines = [
        "# RAGFlow Handoff Package",
        "",
        "This directory is a portable document handoff for the public RAGFlow skills.",
        f"Handoff mode: `{handoff_mode or 'unspecified'}`.",
        "",
        "## Files",
        "",
        f"- `{doc_manifest_name}`: required v0.1 document manifest.",
        f"- `{metadata_name}`: document-level source and Markdown metadata.",
        f"- `{artifact_index_name}`: hashes and kinds for local assets under `documents/` and `artifacts/`.",
        f"- `{profile_suggestions_name}`: advisory parser/profile hints for review.",
        f"- `{retrieval_hints_name}`: section, keyword, question, and quality-risk hints for retrieval review.",
        f"- `{assistant_profile_name}`: advisory assistant retrieval and answer policy profile.",
        f"- `{assistant_test_plan_name}`: staged assistant validation questions for review.",
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
            "## Next Steps",
            "",
            "Inspect the handoff before upload:",
            "",
            "```bash",
            "ragflow-kb-build inspect-handoff --handoff <handoff> --report-json <run>/handoff_inspection.json --report-md <run>/handoff_inspection.md",
            "```",
            "",
            "Run a non-mutating build preview before any live RAGFlow action:",
            "",
            "```bash",
            "ragflow-kb-build --doc-manifest <handoff>/doc_manifest.json --kb-name <kb-name> --profile <reviewed-profile.json> --dry-run --json",
            "```",
            "",
            "Only run a live build after the user explicitly approves RAGFlow KB creation or upload.",
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
    retrieval_hints_name: str = "retrieval_hints.json",
    assistant_profile_name: str = "assistant_profile.json",
    assistant_test_plan_name: str = "assistant_test_plan.json",
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
    retrieval_hints = make_retrieval_hints_payload(
        handoff_root=root,
        metadata=metadata,
        artifact_index=artifact_index,
        quality_report=quality_report,
    )
    assistant_profile = make_assistant_profile_payload(
        retrieval_hints=retrieval_hints,
        profile_suggestions=profile_suggestions,
    )
    assistant_test_plan = make_assistant_test_plan_payload(
        retrieval_hints=retrieval_hints,
        assistant_profile=assistant_profile,
    )
    readme = make_package_readme(
        doc_manifest_name=doc_manifest_name,
        metadata_name=metadata_name,
        artifact_index_name=artifact_index_name,
        profile_suggestions_name=profile_suggestions_name,
        retrieval_hints_name=retrieval_hints_name,
        assistant_profile_name=assistant_profile_name,
        assistant_test_plan_name=assistant_test_plan_name,
        quality_report_name=quality_report_name if isinstance(quality_report_name, str) else None,
        handoff_mode=doc_manifest.get("handoff_mode") if isinstance(doc_manifest.get("handoff_mode"), str) else None,
    )

    metadata_path = root / metadata_name
    artifact_index_path = root / artifact_index_name
    profile_suggestions_path = root / profile_suggestions_name
    retrieval_hints_path = root / retrieval_hints_name
    assistant_profile_path = root / assistant_profile_name
    assistant_test_plan_path = root / assistant_test_plan_name
    package_readme_path = root / package_readme_name
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_index_path.write_text(json.dumps(artifact_index, ensure_ascii=False, indent=2), encoding="utf-8")
    profile_suggestions_path.write_text(json.dumps(profile_suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    retrieval_hints_path.write_text(json.dumps(retrieval_hints, ensure_ascii=False, indent=2), encoding="utf-8")
    assistant_profile_path.write_text(json.dumps(assistant_profile, ensure_ascii=False, indent=2), encoding="utf-8")
    assistant_test_plan_path.write_text(json.dumps(assistant_test_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    package_readme_path.write_text(readme, encoding="utf-8")

    payload = {
        "schema": HANDOFF_PACKAGE_SCHEMA,
        "created_at": _now(),
        "handoff_mode": doc_manifest.get("handoff_mode") if isinstance(doc_manifest.get("handoff_mode"), str) else None,
        "doc_manifest": doc_manifest_name,
        "metadata": metadata_name,
        "artifact_index": artifact_index_name,
        "profile_suggestions": profile_suggestions_name,
        "retrieval_hints": retrieval_hints_name,
        "assistant_profile": assistant_profile_name,
        "assistant_test_plan": assistant_test_plan_name,
        "package_readme": package_readme_name,
        "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
        "document_count": len(metadata["documents"]),
        "artifact_count": artifact_index["artifact_count"],
        "retrieval_hint_count": len(retrieval_hints["section_boundaries"]),
        "assistant_test_count": assistant_test_plan["test_count"],
        "quality_status": profile_suggestions.get("signals", {}).get("quality_status"),
    }
    return payload


def _first_profile_suggestion(profile_suggestions: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(profile_suggestions, Mapping):
        return {}
    suggestions = profile_suggestions.get("suggestions")
    if isinstance(suggestions, list) and suggestions and isinstance(suggestions[0], Mapping):
        return suggestions[0]
    return {}


def make_ragflow_ingest_plan_payload(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    package_payload: Mapping[str, Any] | None = None,
    postprocess_report_name: str | None = "postprocess_report.json",
    chunk_profile_report_name: str | None = None,
) -> dict[str, Any]:
    """Create a non-secret ingestion plan for the next kb-build step."""

    root = Path(handoff_root)
    doc_manifest = load_doc_manifest_payload(root / doc_manifest_name)
    quality_gate = doc_manifest.get("quality_gate") if isinstance(doc_manifest.get("quality_gate"), Mapping) else {}
    package = package_payload or {}
    profile_suggestions_name = (
        str(package.get("profile_suggestions"))
        if isinstance(package.get("profile_suggestions"), str)
        else "profile_suggestions.json"
    )
    retrieval_hints_name = (
        str(package.get("retrieval_hints"))
        if isinstance(package.get("retrieval_hints"), str)
        else "retrieval_hints.json"
    )
    profile_suggestions = _read_json(root / profile_suggestions_name) if (root / profile_suggestions_name).is_file() else {}
    suggestion = _first_profile_suggestion(profile_suggestions)
    parser_profile = {
        "chunk_method": "naive",
        "chunk_size": int(suggestion.get("chunk_size", 512)) if str(suggestion.get("chunk_size", "")).isdigit() else 512,
        "chunk_overlap": int(suggestion.get("chunk_overlap", 64)) if str(suggestion.get("chunk_overlap", "")).isdigit() else 64,
        "language": suggestion.get("language") if isinstance(suggestion.get("language"), str) else None,
    }
    handoff: dict[str, Any] = {
        "handoff_mode": doc_manifest.get("handoff_mode"),
        "doc_manifest": doc_manifest_name,
        "quality_report": doc_manifest.get("quality_report"),
        "runtime_report": doc_manifest.get("runtime_report"),
        "postprocess_report": postprocess_report_name,
        "chunk_profile_report": chunk_profile_report_name or doc_manifest.get("chunk_profile_report"),
        "metadata": package.get("metadata", "metadata.json"),
        "artifact_index": package.get("artifact_index", "artifact_index.json"),
        "profile_suggestions": profile_suggestions_name,
        "retrieval_hints": retrieval_hints_name,
        "assistant_profile": package.get("assistant_profile", "assistant_profile.json"),
        "assistant_test_plan": package.get("assistant_test_plan", "assistant_test_plan.json"),
    }
    return {
        "schema": RAGFLOW_INGEST_PLAN_SCHEMA,
        "created_at": _now(),
        "handoff": handoff,
        "quality_gate": {
            "status": quality_gate.get("status"),
            "required": True,
            "allow_blocked_default": False,
        },
        "recommended_build": {
            "command": "ragflow-kb-build",
            "profile_suggestions": profile_suggestions_name,
            "parser_profile": parser_profile,
            "inspect_command": [
                "ragflow-kb-build",
                "inspect-handoff",
                "--handoff",
                "<handoff>",
                "--report-json",
                "<run>/handoff_inspection.json",
                "--report-md",
                "<run>/handoff_inspection.md",
            ],
            "dry_run_command": [
                "ragflow-kb-build",
                "--doc-manifest",
                "<handoff>/doc_manifest.json",
                "--kb-name",
                "<kb-name>",
                "--profile",
                "<reviewed-profile.json>",
                "--dry-run",
            ],
            "build_command": [
                "ragflow-kb-build",
                "--doc-manifest",
                "<handoff>/doc_manifest.json",
                "--kb-name",
                "<kb-name>",
                "--profile",
                "<reviewed-profile.json>",
            ],
        },
        "recommended_validation": {
            "smoke": True,
            "regression": "optional",
            "benchmark": "optional",
            "query_review": "use ragflow-query with assistant_profile and assistant_test_plan after build",
        },
        "safety": {
            "stores_ragflow_endpoint": False,
            "stores_api_credentials": False,
            "stores_secret": False,
            "mutation_default": "dry_run_first",
        },
        "notes": [
            "No RAGFlow endpoint or API key is stored in this handoff.",
            "Review profile_suggestions.json before materializing a build profile.",
            "Run dry_run_command before any live KB creation or upload.",
        ],
    }


def inspect_rich_handoff(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
) -> dict[str, Any]:
    """Summarize a handoff directory and optional rich sidecars."""

    root = Path(handoff_root)
    doc_manifest = _read_json(root / doc_manifest_name)
    documents = _manifest_documents(doc_manifest)
    postprocess_report_name = (
        doc_manifest.get("postprocess_report")
        if isinstance(doc_manifest.get("postprocess_report"), str)
        else "postprocess_report.json"
    )
    chunk_profile_report_name = (
        doc_manifest.get("chunk_profile_report")
        if isinstance(doc_manifest.get("chunk_profile_report"), str)
        else None
    )
    sidecar_specs: dict[str, tuple[str | None, str]] = {
        "metadata": ("metadata.json", "rich"),
        "artifact_index": ("artifact_index.json", "rich"),
        "profile_suggestions": ("profile_suggestions.json", "rich"),
        "retrieval_hints": ("retrieval_hints.json", "rich"),
        "assistant_profile": ("assistant_profile.json", "rich"),
        "assistant_test_plan": ("assistant_test_plan.json", "rich"),
        "package_readme": ("package_readme.md", "rich"),
        "postprocess_report": (postprocess_report_name, "pipeline"),
        "chunk_profile_report": (chunk_profile_report_name, "pipeline"),
        "ragflow_ingest_plan": ("ragflow_ingest_plan.yaml", "pipeline"),
        "quality_report": (
            doc_manifest.get("quality_report") if isinstance(doc_manifest.get("quality_report"), str) else None,
            "core",
        ),
    }
    sidecars: dict[str, dict[str, Any]] = {}
    missing_rich_sidecars: list[str] = []
    missing_pipeline_sidecars: list[str] = []
    for key, (filename, category) in sidecar_specs.items():
        if not filename:
            continue
        path = root / filename
        sidecars[key] = {
            "path": filename,
            "exists": path.exists(),
            "category": category,
        }
        if path.is_file():
            sidecars[key]["size_bytes"] = path.stat().st_size
        elif category == "rich":
            missing_rich_sidecars.append(key)
        elif category == "pipeline":
            missing_pipeline_sidecars.append(key)

    artifact_count = None
    artifact_index_path = root / "artifact_index.json"
    if artifact_index_path.is_file():
        artifact_index = _read_json(artifact_index_path)
        artifact_count = artifact_index.get("artifact_count")

    retrieval_hint_count = None
    retrieval_hints_path = root / "retrieval_hints.json"
    if retrieval_hints_path.is_file():
        retrieval_hints = _read_json(retrieval_hints_path)
        sections = retrieval_hints.get("section_boundaries")
        retrieval_hint_count = len(sections) if isinstance(sections, list) else None

    assistant_test_count = None
    assistant_test_plan_path = root / "assistant_test_plan.json"
    if assistant_test_plan_path.is_file():
        assistant_test_plan = _read_json(assistant_test_plan_path)
        assistant_test_count = assistant_test_plan.get("test_count")

    quality_status = None
    manifest_gate = doc_manifest.get("quality_gate") if isinstance(doc_manifest.get("quality_gate"), Mapping) else {}
    if isinstance(manifest_gate.get("status"), str):
        quality_status = manifest_gate["status"]
    quality_name = doc_manifest.get("quality_report")
    if isinstance(quality_name, str) and (root / quality_name).is_file():
        quality = _read_json(root / quality_name)
        gate = quality.get("gate", {}) if isinstance(quality.get("gate"), Mapping) else {}
        if isinstance(gate.get("status"), str):
            quality_status = gate["status"]

    image_assets = _inspect_image_assets(root=root, documents=documents)
    readiness_issues: list[dict[str, str]] = []
    if quality_status == "BLOCKED":
        readiness_issues.append(
            {
                "severity": "error",
                "code": "quality_gate_blocked",
                "message": "doc handoff quality gate is BLOCKED",
                "recommendation": "Resolve handoff quality blockers before running live kb-build.",
            }
        )
    elif quality_status not in {"PASS", "PASS_WITH_REVIEW"}:
        readiness_issues.append(
            {
                "severity": "warning",
                "code": "quality_gate_unknown",
                "message": "quality gate status is missing or unknown",
                "recommendation": "Run or inspect ragflow-doc-to-md quality_report.json before live build.",
            }
        )
    if image_assets["missing_image_count"]:
        readiness_issues.append(
            {
                "severity": "error",
                "code": "image_assets_missing",
                "message": "one or more Markdown image references or manifest image assets are missing",
                "recommendation": "Regenerate the handoff with asset landing enabled or repair image paths.",
            }
        )
    if missing_rich_sidecars:
        readiness_issues.append(
            {
                "severity": "warning",
                "code": "rich_sidecars_incomplete",
                "message": "one or more rich handoff sidecars are missing",
                "recommendation": "Run ragflow-doc-to-md pipeline or package --rich before formal ingestion review.",
            }
        )
    readiness_status = "ready"
    if any(issue["severity"] == "error" for issue in readiness_issues):
        readiness_status = "blocked"
    elif readiness_issues:
        readiness_status = "review"

    return {
        "schema": "ragflow_handoff_inspection_v1",
        "created_at": _now(),
        "handoff_root": str(root),
        "doc_manifest": doc_manifest_name,
        "document_count": len(documents),
        "quality_status": quality_status,
        "artifact_count": artifact_count,
        "retrieval_hint_count": retrieval_hint_count,
        "assistant_test_count": assistant_test_count,
        "sidecar_summary": {
            "rich_expected_count": len([key for key, spec in sidecar_specs.items() if spec[1] == "rich"]),
            "rich_present_count": len(
                [
                    key
                    for key, info in sidecars.items()
                    if isinstance(info, Mapping) and info.get("category") == "rich" and info.get("exists")
                ]
            ),
            "rich_missing": missing_rich_sidecars,
            "rich_complete": not missing_rich_sidecars,
            "pipeline_missing": missing_pipeline_sidecars,
            "pipeline_complete": not missing_pipeline_sidecars,
        },
        "assets": {"images": image_assets},
        "ingestion_readiness": {
            "status": readiness_status,
            "quality_gate_allows_build": quality_status in {"PASS", "PASS_WITH_REVIEW"},
            "image_assets_ok": image_assets["ok"],
            "rich_sidecars_complete": not missing_rich_sidecars,
            "pipeline_sidecars_complete": not missing_pipeline_sidecars,
            "issues": readiness_issues,
        },
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
        f"- Retrieval hint sections: {report.get('retrieval_hint_count') if report.get('retrieval_hint_count') is not None else 'unknown'}",
        f"- Assistant tests: {report.get('assistant_test_count') if report.get('assistant_test_count') is not None else 'unknown'}",
        f"- Ingestion readiness: `{(report.get('ingestion_readiness') or {}).get('status', 'unknown')}`",
        "",
        "## Readiness",
        "",
    ]
    sidecar_summary = report.get("sidecar_summary", {}) if isinstance(report.get("sidecar_summary"), Mapping) else {}
    assets = report.get("assets", {}) if isinstance(report.get("assets"), Mapping) else {}
    images = assets.get("images", {}) if isinstance(assets.get("images"), Mapping) else {}
    lines.extend(
        [
            f"- Rich sidecars complete: {str(bool(sidecar_summary.get('rich_complete'))).lower()}",
            f"- Pipeline sidecars complete: {str(bool(sidecar_summary.get('pipeline_complete'))).lower()}",
            f"- Missing image assets: {images.get('missing_image_count', 'unknown')}",
            "",
        ]
    )
    readiness = report.get("ingestion_readiness", {}) if isinstance(report.get("ingestion_readiness"), Mapping) else {}
    readiness_issues = readiness.get("issues", []) if isinstance(readiness.get("issues"), list) else []
    if readiness_issues:
        lines.extend(["## Readiness Issues", ""])
        for issue in readiness_issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('code')}` ({issue.get('severity')}): {issue.get('message')}")
        lines.append("")
    lines.extend(
        [
            "## Sidecars",
            "",
            "| Sidecar | Exists | Path |",
            "| --- | --- | --- |",
        ]
    )
    sidecars = report.get("sidecars", {})
    if isinstance(sidecars, Mapping):
        for name, info in sidecars.items():
            if not isinstance(info, Mapping):
                continue
            lines.append(f"| {name} | {str(bool(info.get('exists'))).lower()} | `{info.get('path', '')}` |")
    return "\n".join(lines).rstrip() + "\n"
