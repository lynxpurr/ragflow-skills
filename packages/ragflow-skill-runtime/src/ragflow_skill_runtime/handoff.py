"""Rich handoff sidecars for portable RAGFlow document packages."""

from __future__ import annotations

import difflib
import json
import hashlib
import mimetypes
import re
import unicodedata
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
ASSET_SEMANTICS_SCHEMA = "ragflow_asset_semantics_v1"
PROFILE_SUGGESTIONS_SCHEMA = "ragflow_profile_suggestions_v1"
RETRIEVAL_HINTS_SCHEMA = "ragflow_retrieval_hints_v1"
ASSISTANT_PROFILE_SCHEMA = "ragflow_assistant_profile_v1"
ASSISTANT_TEST_PLAN_SCHEMA = "ragflow_assistant_test_plan_v1"
DOC_INGEST_READINESS_SCHEMA = "ragflow_doc_ingest_readiness_v1"
FORMAL_HANDOFF_MANIFEST_SCHEMA = "ragflow_formal_handoff_manifest_v1"
HANDOFF_COMPARISON_SCHEMA = "ragflow_handoff_comparison_v1"
RAGFLOW_INGEST_PLAN_SCHEMA = "ragflow_ingest_plan_v1"
TABLE_PARENT_CHUNK_TARGET_TOKENS = 4096
TABLE_PARENT_CHUNK_REVIEW_FLOOR_TOKENS = 1024

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
NUMERIC_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:\s?[%A-Za-zμ°/-]+)?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
CJK_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
PANDOC_FENCED_DIV_LINE_RE = re.compile(r"(?m)^[ \t]*:{3,}[ \t]*(?:\{[^}\n]*\})?[ \t]*(?:\n|$)")
PANDOC_EMPTY_ANCHOR_RE = re.compile(r"\[\]\{#[^}\n]+\}")
PANDOC_HEADING_ANCHOR_TAIL_RE = re.compile(
    r"(?m)^(?P<heading>[ \t]*#{1,6}[ \t]*.*?)[ \t]+\{#[A-Za-z0-9_.:-]+(?:[ \t][^}\n]*)?\}[ \t]*$"
)
PANDOC_SPAN_STYLE_RE = re.compile(
    r"\[([^\]\n]+)\]\{[^}\n]*\bstyle\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s}]+)[^}\n]*\}"
)
HTML_STYLE_ATTR_RE = re.compile(r"\s+style\s*=\s*(\"[^\"]*\"|'[^']*')", re.IGNORECASE)
PAGE_COMMENT_RE = re.compile(
    r"<!--\s*(?:page|page_id|page-id|page_index|page-index)\s*[:=]?\s*(\d+)\s*-->",
    re.IGNORECASE,
)
PAGE_TEXT_RE = re.compile(r"^\s*(?:page|p\.|第)\s*([0-9]{1,5})\s*(?:页)?\s*$", re.IGNORECASE)
CHUNK_MARKER = "<!-- chunk -->"
CHUNK_MARKER_RE = re.compile(r"<!--\s*chunk(?:\s+[^>]*)?\s*-->", re.IGNORECASE)
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"}
TABLE_SUFFIXES = {".csv", ".tsv", ".xls", ".xlsx"}
COMPARISON_RETAINED_IGNORED_DIRS = {
    ".cache",
    "intermediate",
    "layout",
    "layout_pdf",
    "layout_pdfs",
    "mineru",
    "mineru_output",
    "origin",
    "pdf",
    "pdfs",
    "raw",
    "raw_source",
    "raw_sources",
    "source_pdf",
    "source_pdfs",
    "span",
    "span_pdf",
    "span_pdfs",
    "spans",
    "temp",
    "tmp",
}
COMPARISON_MARKDOWN_SIDECAR_NAMES = {
    "ingest_readiness_report.md",
    "package_readme.md",
    "quality_report.md",
    "readme.md",
    "runtime_report.md",
}

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


def _asset_file_semantic_fields(path: Path) -> dict[str, Any]:
    fields: dict[str, Any] = {"exists": path.is_file()}
    if path.is_file():
        stat = path.stat()
        fields["bytes"] = stat.st_size
        fields["sha256"] = sha256_file(path)
        mime_type, _encoding = mimetypes.guess_type(path.name)
        if mime_type:
            fields["mime_type"] = mime_type
    return fields


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
    markdown_table_count = 0
    html_table_count = 0
    has_cjk = False
    table_parent_chunk_estimates: list[int] = []
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_path = Path(handoff_root) / str(markdown.get("path", ""))
        if markdown_path.is_file():
            text = markdown_path.read_text(encoding="utf-8", errors="replace")
            total_chars += len(text)
            image_count += text.count("![")
            lines = text.splitlines()
            markdown_table_count += _count_table_blocks(lines)
            for block in _table_blocks(lines):
                rows = [str(row) for row in block["rows"]]
                column_count = max((row.count("|") - 1 for row in rows if "|" in row), default=0)
                table = {
                    "row_count": len(rows),
                    "column_count": column_count,
                    "cell_count": len(rows) * column_count,
                }
                fields = _table_parent_chunk_estimate_fields(table, source_text="\n".join(rows))
                table_parent_chunk_estimates.append(int(fields["estimated_parent_chunk_tokens"]))
            html_tables = parse_html_tables(text)
            html_table_count += len(html_tables)
            for table in html_tables:
                source_text = "\n".join(lines[max(int(table.line_start) - 1, 0) : int(table.line_end)])
                fields = _table_parent_chunk_estimate_fields(
                    {
                        "row_count": int(table.row_count),
                        "column_count": int(table.column_count),
                        "cell_count": int(table.cell_count),
                    },
                    source_text=source_text,
                )
                table_parent_chunk_estimates.append(int(fields["estimated_parent_chunk_tokens"]))
            has_cjk = has_cjk or any("\u4e00" <= char <= "\u9fff" for char in text[:5000])

    gate = quality_report.get("gate", {}) if isinstance(quality_report, Mapping) else {}
    quality_status = gate.get("status") if isinstance(gate, Mapping) else None
    quality_counts = _quality_content_counts(quality_report)
    markdown_table_count = max(markdown_table_count, quality_counts["markdown_table_count"])
    html_table_count = max(html_table_count, quality_counts["html_table_count"])
    table_count = max(markdown_table_count + html_table_count, quality_counts["table_count"])
    language = "zh" if has_cjk else "en"
    average_chars = int(total_chars / len(documents)) if documents else 0
    chunk_size = 512 if language == "zh" else 768
    if average_chars > 24000:
        chunk_size = 1024 if language == "en" else 768

    suggestions: list[dict[str, Any]] = [
        {
            "id": f"default-{language}-{chunk_size}",
            "language": language,
            "chunk_size": chunk_size,
            "chunk_overlap": 96 if chunk_size >= 768 else 64,
            "reason": "deterministic starter suggestion based on language and document size",
        }
    ]
    if table_count:
        suggestions.append(
            {
                "id": f"table-atomic-{language}-4096",
                "language": language,
                "chunk_method": "naive",
                "chunk_size": 4096,
                "chunk_overlap": 0,
                "postprocess_profile": "chunk-markers-dense",
                "parser_config": {
                    "chunk_token_num": 4096,
                    "delimiter": f"`{CHUNK_MARKER}`",
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "Chinese" if language == "zh" else "English",
                },
                "avoid_children_delimiter": True,
                "reason": "tables detected; preserve table blocks with chunk markers and a larger parent chunk",
            }
        )

    warnings: list[str] = []
    if quality_status == "BLOCKED":
        warnings.append("quality gate is BLOCKED; fix the handoff before building unless the user explicitly allows it")
    if image_count:
        warnings.append("image-rich Markdown detected; verify parser profile preserves image/table context as needed")
    if table_count:
        warnings.append("table-rich Markdown detected; prefer chunk-markers-dense plus delimiter-based RAGFlow parsing")
    max_table_parent_tokens = max(table_parent_chunk_estimates, default=0)
    if max_table_parent_tokens > TABLE_PARENT_CHUNK_TARGET_TOKENS:
        warnings.append(
            "at least one table may exceed the 4096-token table-atomic profile target; split or review oversized tables"
        )
    if average_chars > 32000:
        warnings.append("large average document size detected; consider segmentation before upload")

    return {
        "schema": PROFILE_SUGGESTIONS_SCHEMA,
        "created_at": _now(),
        "suggestions": suggestions,
        "signals": {
            "document_count": len(documents),
            "total_chars": total_chars,
            "average_chars": average_chars,
            "image_count": image_count,
            "table_count": table_count,
            "markdown_table_count": markdown_table_count,
            "html_table_count": html_table_count,
            "max_table_estimated_parent_chunk_tokens": max_table_parent_tokens,
            "table_atomic_target_tokens": TABLE_PARENT_CHUNK_TARGET_TOKENS if table_count else None,
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


def _is_image_like_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}


def _layout_image_signals(layout_signals: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    image_terms = (
        "image",
        "img",
        "figure",
        "fig",
        "chart",
        "diagram",
        "logo",
        "table",
        "picture",
        "图片",
        "图像",
        "图表",
        "表格",
    )
    signals: list[dict[str, Any]] = []
    for signal in layout_signals:
        if not isinstance(signal, Mapping):
            continue
        path = signal.get("path")
        block_type = str(signal.get("block_type") or "").lower()
        text = str(signal.get("text") or "")
        image_like = any(term in block_type for term in image_terms)
        if isinstance(path, str) and _is_image_like_path(path):
            image_like = True
        if not image_like:
            continue
        record = {key: value for key, value in signal.items() if value is not None}
        if text:
            record["text"] = _compact_text(text, limit=180)
        signals.append(record)
    return signals[:80]


def _paths_may_match(candidate: str | None, target: str | None) -> bool:
    if not candidate or not target:
        return False
    left = candidate.strip().replace("\\", "/").strip("/")
    right = target.strip().replace("\\", "/").strip("/")
    if not left or not right:
        return False
    if left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}"):
        return True
    left_name = Path(left).name
    right_name = Path(right).name
    return bool(left_name and left_name == right_name)


def _layout_signal_for_image(path: str, layout_image_signals: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for signal in layout_image_signals:
        signal_path = signal.get("path")
        if isinstance(signal_path, str) and _paths_may_match(signal_path, path):
            return signal
    return None


def _semantic_kind_from_text(*values: Any) -> str:
    text = " ".join(str(value).lower() for value in values if isinstance(value, str) and value.strip())
    if not text:
        return "unknown"
    if any(token in text for token in ("logo", "商标", "标识")):
        return "logo"
    if any(token in text for token in ("decorative", "background", "ornament", "装饰", "背景")):
        return "decorative"
    if any(token in text for token in ("table", "spreadsheet", "表格", "表截图")):
        return "table_image"
    if any(token in text for token in ("chart", "graph", "plot", "diagram", "curve", "图表", "曲线", "示意图")):
        return "chart"
    return "image"


def _semantic_alias_for_image(path: str, item: Mapping[str, Any]) -> str | None:
    suffix = Path(path).suffix.lower()
    if not suffix:
        return None
    label = " ".join(
        str(item.get(key) or "")
        for key in ("caption", "alt_text", "source_heading", "semantic_kind")
        if isinstance(item.get(key), str)
    )
    words = [word.lower() for word in WORD_RE.findall(label) if word.lower() not in STOPWORDS]
    if not words:
        return None
    stem = "-".join(words[:5])
    parent = Path(path).parent.as_posix()
    alias = f"{stem}{suffix}"
    return f"{parent}/{alias}" if parent and parent != "." else alias


def _enrich_image_artifacts(
    image_artifacts: list[Mapping[str, Any]],
    *,
    root: Path,
    layout_signals: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    layout_images = _layout_image_signals(layout_signals)
    enriched: list[dict[str, Any]] = []
    for artifact in image_artifacts:
        if not isinstance(artifact, Mapping):
            continue
        path = artifact.get("path")
        if not isinstance(path, str) or not path.strip() or not _safe_relative_reference(path):
            continue
        path = path.strip().replace("\\", "/")
        record = {key: value for key, value in artifact.items() if value is not None}
        record["path"] = path
        record.setdefault("kind", "image")
        semantic_sources = set(record.get("semantic_sources", [])) if isinstance(record.get("semantic_sources"), list) else set()
        if record.get("source"):
            semantic_sources.add(str(record.get("source")))
        layout_signal = _layout_signal_for_image(path, layout_images)
        if layout_signal is not None:
            semantic_sources.add(str(layout_signal.get("source") or "layout_sidecar"))
            layout_text = layout_signal.get("text")
            if isinstance(layout_text, str) and layout_text.strip():
                record["caption"] = _compact_text(layout_text, limit=160)
            page = layout_signal.get("page")
            if isinstance(page, int):
                record["page"] = page
            block_type = layout_signal.get("block_type")
            if isinstance(block_type, str) and block_type.strip():
                record["layout_block_type"] = block_type.strip()
            source = layout_signal.get("source")
            if isinstance(source, str):
                record["layout_source"] = source
        resolved = root / path
        record.update(_asset_file_semantic_fields(resolved))
        semantic_kind = _semantic_kind_from_text(
            record.get("caption"),
            record.get("alt_text"),
            record.get("context"),
            record.get("source_heading"),
            record.get("layout_block_type"),
            path,
        )
        record["semantic_kind"] = semantic_kind
        alias = _semantic_alias_for_image(path, record)
        if alias and alias != path:
            record["semantic_alias"] = alias
            record["rewrites_markdown"] = False
        if semantic_sources:
            record["semantic_sources"] = sorted(semantic_sources)
        enriched.append(record)
    return enriched[:60]


def _asset_semantics_summary(images: list[Mapping[str, Any]], aliases: list[Mapping[str, Any]]) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    missing = 0
    with_page = 0
    with_caption = 0
    for image in images:
        kind = str(image.get("semantic_kind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if image.get("exists") is False:
            missing += 1
        if isinstance(image.get("page"), int):
            with_page += 1
        if isinstance(image.get("caption"), str) and image.get("caption"):
            with_caption += 1
    return {
        "image_count": len(images),
        "semantic_alias_count": len(aliases),
        "missing_image_count": missing,
        "with_page_count": with_page,
        "with_caption_count": with_caption,
        "semantic_kind_counts": kind_counts,
    }


def make_asset_semantics_payload(
    *,
    handoff_root: str | Path,
    metadata: Mapping[str, Any],
    artifact_index: Mapping[str, Any],
    layout_sidecars: list[Mapping[str, Any]] | None = None,
    layout_signals: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create deterministic semantic metadata for local image assets."""

    root = Path(handoff_root)
    markdown_contexts: list[dict[str, Any]] = []
    documents = metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_rel = str(markdown.get("path") or document.get("markdown_path") or "")
        if not markdown_rel:
            continue
        text = _read_markdown(root / markdown_rel)
        lines = text.splitlines()
        page_by_line, _markers = _line_page_map(lines)
        sections = _section_boundaries(markdown_rel=markdown_rel, text=text)
        markdown_contexts.extend(
            _markdown_image_contexts(
                markdown_rel=markdown_rel,
                text=text,
                sections=sections,
                page_by_line=page_by_line,
                root=root,
            )
        )

    artifacts = artifact_index.get("artifacts", []) if isinstance(artifact_index, Mapping) else []
    indexed_images = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "image"]
    raw_images = _merge_artifact_contexts(
        artifacts=indexed_images,
        contexts=markdown_contexts,
        kind="image",
    )
    images = _enrich_image_artifacts(
        raw_images,
        root=root,
        layout_signals=list(layout_signals or []),
    )
    aliases = [
        {
            "path": image["path"],
            "alias": image["semantic_alias"],
            "rewrites_markdown": False,
            "semantic_kind": image.get("semantic_kind"),
        }
        for image in images
        if isinstance(image.get("semantic_alias"), str)
    ]
    return {
        "schema": ASSET_SEMANTICS_SCHEMA,
        "created_at": _now(),
        "summary": _asset_semantics_summary(images, aliases),
        "images": images,
        "semantic_aliases": aliases,
        "layout_sidecars": list(layout_sidecars or []),
    }


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
        rows = [str(row) for row in block["rows"]]
        column_count = max((row.count("|") - 1 for row in rows if "|" in row), default=0)
        source_text = "\n".join(rows)
        section = _section_for_line(sections, line_start) or {}
        context: dict[str, Any] = {
            "kind": "table",
            "document": markdown_rel,
            "line_start": line_start,
            "line_end": int(block["line_end"]),
            "source_heading": section.get("title"),
            "heading_level": section.get("level"),
            "page": _page_for_line(page_by_line, line_start),
            "row_count": len(rows),
            "column_count": column_count,
            "cell_count": max(len(rows) * column_count, 0),
            "header_preview": _table_header_preview(rows),
            "source": "markdown_table",
        }
        context.update(_table_parent_chunk_estimate_fields(context, source_text=source_text))
        contexts.append(context)
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
        source_text = "\n".join(lines[max(line_start - 1, 0) : int(table.line_end)])
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
            "cell_count": int(table.cell_count),
            "rowspan_count": int(table.rowspan_count),
            "colspan_count": int(table.colspan_count),
            "header_depth": int(table.header_depth),
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
        context.update(_table_semantic_risk_fields(context))
        context.update(_table_parent_chunk_estimate_fields(context, source_text=source_text))
        contexts.append(context)
    return contexts


def _model_label_candidates(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    labels: list[str] = []
    for match in re.findall(r"\b[A-Za-z]{1,12}[A-Za-z0-9]*-[A-Za-z0-9][A-Za-z0-9-]*\b", value):
        labels.append(match.upper())
    for match in re.findall(r"\b[A-Z]{1,4}-[A-Z0-9]{1,5}\b", value.upper()):
        labels.append(match)
    return _unique_preserve_order(labels)


def _table_model_label_candidates(table: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    header_preview = table.get("header_preview", [])
    headers = header_preview if isinstance(header_preview, list) else []
    for value in headers:
        labels.extend(_model_label_candidates(value))
    labels.extend(_model_label_candidates(table.get("caption")))
    labels.extend(_model_label_candidates(table.get("source_heading")))
    context = table.get("context")
    if isinstance(context, str):
        labels.extend(_model_label_candidates(context))
    return _unique_preserve_order(labels)


def _add_table_risk(
    risks: list[dict[str, Any]],
    *,
    code: str,
    severity: str,
    message: str,
    recommendation: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    risk: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
    }
    if details:
        risk["details"] = {key: value for key, value in details.items() if value is not None}
    risks.append(risk)


def _table_semantic_risk_fields(table: Mapping[str, Any]) -> dict[str, Any]:
    """Return review-only semantic table risk fields for retrieval hints."""

    row_count = int(table.get("row_count", 0) or 0)
    column_count = int(table.get("column_count", 0) or 0)
    cell_count = int(table.get("cell_count", 0) or 0)
    rowspan_count = int(table.get("rowspan_count", 0) or 0)
    colspan_count = int(table.get("colspan_count", 0) or 0)
    header_depth = int(table.get("header_depth", 0) or 0)
    warnings = table.get("warnings", []) if isinstance(table.get("warnings"), list) else []
    model_labels = _table_model_label_candidates(table)
    risks: list[dict[str, Any]] = []

    if header_depth > 1:
        _add_table_risk(
            risks,
            code="multi_level_header_review",
            severity="warning",
            message="table has multiple header rows; answers may need header hierarchy awareness",
            recommendation="Review table header hierarchy before relying on single-row query terms.",
            details={"header_depth": header_depth},
        )
    if rowspan_count or colspan_count:
        _add_table_risk(
            risks,
            code="merged_cells_review",
            severity="warning",
            message="table contains rowspan or colspan cells",
            recommendation="Review row/column alignment before using cell values as independent facts.",
            details={"rowspan_count": rowspan_count, "colspan_count": colspan_count},
        )
    if "column_misalignment_suspected" in warnings:
        _add_table_risk(
            risks,
            code="column_misalignment_review",
            severity="warning",
            message="table rows have inconsistent effective column widths",
            recommendation="Compare parsed header and body columns before using this table for QA.",
        )
    if column_count >= 10 or cell_count >= 120 or row_count >= 40:
        _add_table_risk(
            risks,
            code="large_table_review",
            severity="info",
            message="table is large enough to stress retrieval or chunking boundaries",
            recommendation="Use table-atomic parser profiles and review chunk boundaries for this table.",
            details={"row_count": row_count, "column_count": column_count, "cell_count": cell_count},
        )
    if not table.get("caption"):
        _add_table_risk(
            risks,
            code="caption_missing_review",
            severity="info",
            message="table has no caption; nearby headings may be required for disambiguation",
            recommendation="Use source_heading and neighboring section context when expanding queries.",
        )
    if len(model_labels) >= 2 and (header_depth > 1 or rowspan_count or colspan_count):
        _add_table_risk(
            risks,
            code="multi_model_header_review",
            severity="warning",
            message="table appears to combine multiple model labels with complex header structure",
            recommendation="Split retrieval or ask model-specific subqueries before comparing cells.",
            details={"model_labels": model_labels[:8]},
        )

    severity_score = {"info": 1, "warning": 2, "error": 3}
    score = sum(severity_score.get(str(risk.get("severity")), 1) for risk in risks)
    payload: dict[str, Any] = {
        "semantic_risk_score": score,
        "semantic_risks": risks,
        "review_required": bool(risks),
    }
    if model_labels:
        payload["model_label_candidates"] = model_labels[:12]
    return payload


def _cjk_char_count(value: str) -> int:
    return sum(1 for char in value if "\u4e00" <= char <= "\u9fff")


def _estimate_text_tokens(value: str) -> int:
    if not value:
        return 0
    compact = " ".join(value.split())
    divisor = 2 if _cjk_char_count(compact) >= max(1, len(compact) // 8) else 4
    return max(1, (len(compact) + divisor - 1) // divisor)


def _table_parent_chunk_estimate_fields(table: Mapping[str, Any], *, source_text: str) -> dict[str, Any]:
    row_count = int(table.get("row_count", 0) or 0)
    column_count = int(table.get("column_count", 0) or 0)
    cell_count = int(table.get("cell_count", 0) or 0)
    structural_tokens = max(cell_count * 4, row_count * max(column_count, 1) * 3)
    text_tokens = _estimate_text_tokens(source_text)
    estimated_tokens = max(text_tokens, structural_tokens)
    review_target = min(
        TABLE_PARENT_CHUNK_TARGET_TOKENS,
        max(TABLE_PARENT_CHUNK_REVIEW_FLOOR_TOKENS, ((estimated_tokens + 511) // 512) * 512),
    )
    fields: dict[str, Any] = {
        "source_text_chars": len(source_text),
        "estimated_parent_chunk_tokens": estimated_tokens,
        "recommended_min_parent_chunk_tokens": review_target,
        "table_atomic_target_tokens": TABLE_PARENT_CHUNK_TARGET_TOKENS,
    }
    if estimated_tokens > TABLE_PARENT_CHUNK_TARGET_TOKENS:
        fields["parent_chunk_atomicity_risk"] = "exceeds_table_atomic_target"
    return fields


def _profile_chunk_token_num(profile: Mapping[str, Any] | None) -> int | None:
    if not isinstance(profile, Mapping):
        return None
    parser_config = profile.get("parser_config") if isinstance(profile.get("parser_config"), Mapping) else {}
    for value in (
        parser_config.get("chunk_token_num") if isinstance(parser_config, Mapping) else None,
        profile.get("chunk_size"),
        profile.get("chunk_token_num"),
    ):
        if value is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _table_parent_chunk_preflight(
    *,
    retrieval_hints: Mapping[str, Any] | None,
    selected_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tables = retrieval_hints.get("table_artifacts", []) if isinstance(retrieval_hints, Mapping) else []
    table_records = [item for item in tables if isinstance(item, Mapping)]
    selected_tokens = _profile_chunk_token_num(selected_profile)
    selected_profile_id = None
    if isinstance(selected_profile, Mapping):
        value = selected_profile.get("id") or selected_profile.get("profile_id")
        selected_profile_id = str(value) if value else None

    table_checks: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for index, table in enumerate(table_records, start=1):
        estimate = int(table.get("estimated_parent_chunk_tokens", 0) or 0)
        recommended = int(table.get("recommended_min_parent_chunk_tokens", 0) or 0)
        target = int(table.get("table_atomic_target_tokens", TABLE_PARENT_CHUNK_TARGET_TOKENS) or TABLE_PARENT_CHUNK_TARGET_TOKENS)
        record: dict[str, Any] = {
            "table_index": index,
            "document": table.get("document"),
            "caption": table.get("caption"),
            "source_heading": table.get("source_heading"),
            "row_count": int(table.get("row_count", 0) or 0),
            "column_count": int(table.get("column_count", 0) or 0),
            "cell_count": int(table.get("cell_count", 0) or 0),
            "estimated_parent_chunk_tokens": estimate,
            "recommended_min_parent_chunk_tokens": recommended,
            "table_atomic_target_tokens": target,
        }
        if selected_tokens is not None:
            record["selected_profile_chunk_tokens"] = selected_tokens
            record["selected_profile_ok"] = estimate <= selected_tokens if estimate else True
        if estimate > target:
            record["risk"] = "exceeds_table_atomic_target"
        elif selected_tokens is not None and estimate > selected_tokens:
            record["risk"] = "selected_profile_too_small"
        else:
            record["risk"] = "none"
        table_checks.append(record)

    max_estimate = max((int(item.get("estimated_parent_chunk_tokens", 0) or 0) for item in table_checks), default=0)
    max_recommended = max(
        (int(item.get("recommended_min_parent_chunk_tokens", 0) or 0) for item in table_checks),
        default=0,
    )
    if selected_tokens is not None and max_estimate > selected_tokens:
        issues.append(
            {
                "severity": "warning",
                "code": "table_parent_chunk_profile_too_small",
                "message": "selected profile chunk_token_num is smaller than at least one estimated table block",
                "recommendation": (
                    "Use a table-atomic profile such as 4096 when the deployment supports it, "
                    "or split/review oversized tables before live upload."
                ),
            }
        )
    if max_estimate > TABLE_PARENT_CHUNK_TARGET_TOKENS:
        issues.append(
            {
                "severity": "warning",
                "code": "table_parent_chunk_exceeds_atomic_target",
                "message": "at least one table may exceed the 4096-token table-atomic profile target",
                "recommendation": (
                    "Delimiter-based chunk markers control boundaries, but they cannot guarantee that an oversized "
                    "table will remain atomic if the RAGFlow server applies a lower parent chunk limit."
                ),
            }
        )
    status = "review" if issues else "ready"
    return {
        "exists": bool(table_checks),
        "status": status,
        "selected_profile_id": selected_profile_id,
        "selected_profile_chunk_tokens": selected_tokens,
        "table_count": len(table_checks),
        "max_estimated_parent_chunk_tokens": max_estimate,
        "max_recommended_min_parent_chunk_tokens": max_recommended,
        "table_atomic_target_tokens": TABLE_PARENT_CHUNK_TARGET_TOKENS,
        "deployment_limit_assumption": "unknown",
        "delimiter_limitation": "delimiter controls boundaries but cannot override a lower server-side parent chunk limit",
        "tables": table_checks[:30],
        "issues": issues,
    }


_SUBSCRIPT_TRANSLATION = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "ₐ": "a",
        "ₑ": "e",
        "ₕ": "h",
        "ᵢ": "i",
        "ⱼ": "j",
        "ₖ": "k",
        "ₗ": "l",
        "ₘ": "m",
        "ₙ": "n",
        "ₒ": "o",
        "ₚ": "p",
        "ᵣ": "r",
        "ₛ": "s",
        "ₜ": "t",
        "ᵤ": "u",
        "ᵥ": "v",
        "ₓ": "x",
    }
)


def _clean_table_term_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).translate(_SUBSCRIPT_TRANSLATION)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\(?:mathrm|text|operatorname)\s*\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    text = " ".join(text.strip().split())
    return text or None


def _unique_preserve_order(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_table_term_label(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _term_alias_variants(source_label: str) -> tuple[str, list[str]]:
    label = _clean_table_term_label(source_label) or ""
    if not label:
        return "", []
    math_stripped = label.strip("$").strip()
    tex_subscript_spaced = re.sub(r"_\s*\{?([A-Za-z0-9]+)\}?", r" \1", math_stripped)
    tex_subscript_joined = re.sub(r"_\s*\{?([A-Za-z0-9]+)\}?", r"\1", math_stripped)
    tex_subscript_underscore = re.sub(r"_\s*\{?([A-Za-z0-9]+)\}?", r"_\1", math_stripped)
    ascii_tokens = re.findall(r"[A-Za-z0-9]+", tex_subscript_spaced)
    explicit_symbolic = any(marker in label for marker in ("$", "_", "\\", "{", "}"))
    if len(ascii_tokens) < 2 and not explicit_symbolic:
        return "", []
    compact = "".join(ascii_tokens)
    underscored = "_".join(ascii_tokens)
    spaced = " ".join(ascii_tokens)
    variants = _unique_preserve_order(
        [
            math_stripped,
            tex_subscript_underscore,
            tex_subscript_spaced,
            tex_subscript_joined,
            compact,
            underscored,
            spaced,
        ]
    )
    normalized = compact or re.sub(r"\W+", "", math_stripped)
    aliases = [variant for variant in variants if variant.casefold() != label.casefold()]
    aliases = [alias for alias in aliases if alias and alias.casefold() != normalized.casefold()]
    if normalized and normalized.casefold() != label.casefold():
        aliases.insert(0, normalized)
    aliases = _unique_preserve_order(aliases)
    return normalized or math_stripped, aliases


def _table_term_alias_candidates(table_artifacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for table_index, artifact in enumerate(table_artifacts, start=1):
        if not isinstance(artifact, Mapping):
            continue
        labels: list[tuple[str, str]] = []
        header_preview = artifact.get("header_preview", [])
        headers = header_preview if isinstance(header_preview, list) else []
        for label in headers:
            cleaned = _clean_table_term_label(label)
            if cleaned:
                labels.append(("header", cleaned))
        for field_name in ("caption", "source_heading"):
            cleaned = _clean_table_term_label(artifact.get(field_name))
            if cleaned:
                labels.append((field_name, cleaned))
        for field_name, source_label in labels:
            normalized_label, aliases = _term_alias_variants(source_label)
            if not normalized_label or not aliases:
                continue
            key = (str(artifact.get("document") or ""), field_name, source_label.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidate: dict[str, Any] = {
                "source_label": source_label,
                "normalized_label": normalized_label,
                "candidate_aliases": aliases[:8],
                "evidence_field": field_name,
                "document": artifact.get("document"),
                "source": artifact.get("source"),
                "table_index": table_index,
                "line_start": artifact.get("line_start"),
                "source_heading": artifact.get("source_heading"),
                "caption": artifact.get("caption"),
                "confidence": "review",
                "requires_review": True,
                "rewrites_markdown": False,
            }
            if artifact.get("page") is not None:
                candidate["page"] = artifact.get("page")
            candidates.append({key: value for key, value in candidate.items() if value is not None})
    return candidates[:80]


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
    asset_semantics = artifact_index.get("asset_semantics") if isinstance(artifact_index, Mapping) else None
    semantic_images = asset_semantics.get("images", []) if isinstance(asset_semantics, Mapping) else []
    semantic_images = [item for item in semantic_images if isinstance(item, Mapping)]
    indexed_table_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "table"]
    indexed_image_artifacts = (
        semantic_images
        if semantic_images
        else [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "image"]
    )
    layout_sidecars, layout_signals = _load_optional_layout_sidecars(root)
    table_artifacts = _merge_artifact_contexts(
        artifacts=indexed_table_artifacts,
        contexts=markdown_table_artifacts,
        kind="table",
    )
    table_term_alias_candidates = _table_term_alias_candidates(table_artifacts)
    image_contexts = [] if semantic_images else markdown_image_artifacts
    image_artifacts = _enrich_image_artifacts(
        _merge_artifact_contexts(
            artifacts=indexed_image_artifacts,
            contexts=image_contexts,
            kind="image",
        ),
        root=root,
        layout_signals=layout_signals,
    )
    asset_semantics_summary = (
        asset_semantics.get("summary")
        if isinstance(asset_semantics, Mapping) and isinstance(asset_semantics.get("summary"), Mapping)
        else _asset_semantics_summary(image_artifacts, [])
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
        "table_term_alias_candidates": table_term_alias_candidates,
        "image_artifacts": image_artifacts[:30],
        "asset_semantics": {
            "schema": ASSET_SEMANTICS_SCHEMA,
            "summary": asset_semantics_summary,
        },
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
    images = retrieval_hints.get("image_artifacts", []) if isinstance(retrieval_hints.get("image_artifacts"), list) else []
    tables = retrieval_hints.get("table_artifacts", []) if isinstance(retrieval_hints.get("table_artifacts"), list) else []
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
    visual_artifact = next((image for image in images if isinstance(image, Mapping)), None)
    visual_section = next((section for section in sections if isinstance(section, Mapping) and int(section.get("image_count", 0)) > 0), None)
    if visual_artifact or visual_section:
        visual_label = None
        if isinstance(visual_artifact, Mapping):
            visual_label = visual_artifact.get("caption") or visual_artifact.get("alt_text") or visual_artifact.get("source_heading")
        if not visual_label and isinstance(visual_section, Mapping):
            visual_label = visual_section.get("title")
        case = {
            "id": "visual-001",
            "stage": "ocr_image_fact",
            "question": f"What visual details are associated with {visual_label}?",
            "expected_behavior": "answer only if retrieved evidence contains the visual or OCR-backed detail",
            "source_document": visual_artifact.get("document") if isinstance(visual_artifact, Mapping) else visual_section.get("document"),
            "source_heading": visual_artifact.get("source_heading") if isinstance(visual_artifact, Mapping) else visual_section.get("title"),
        }
        if isinstance(visual_artifact, Mapping):
            case.update(
                {
                    "source_image": visual_artifact.get("path"),
                    "source_caption": visual_artifact.get("caption"),
                    "semantic_kind": visual_artifact.get("semantic_kind"),
                    "semantic_alias": visual_artifact.get("semantic_alias"),
                    "page": visual_artifact.get("page"),
                }
            )
        cases.append({key: value for key, value in case.items() if value is not None})
    table_case_count = 0
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        risks = table.get("semantic_risks", [])
        risks = risks if isinstance(risks, list) else []
        if not risks:
            continue
        table_case_count += 1
        label = table.get("caption") or table.get("source_heading") or f"table {table_case_count}"
        model_labels = table.get("model_label_candidates", [])
        if not isinstance(model_labels, list):
            model_labels = []
        risk_codes = [risk.get("code") for risk in risks if isinstance(risk, Mapping) and risk.get("code")]
        case = {
            "id": f"table-structure-{table_case_count:03d}",
            "stage": "table_structure_review",
            "question": f"How should the complex table structure for {label} be reviewed before answering model-specific facts?",
            "expected_behavior": "confirm header hierarchy, merged-cell alignment, and table citations before comparing values",
            "source_document": table.get("document"),
            "source_heading": table.get("source_heading"),
            "source_table_caption": table.get("caption"),
            "page": table.get("page"),
            "semantic_risk_codes": risk_codes[:8],
            "model_label_candidates": model_labels[:8],
        }
        cases.append({key: value for key, value in case.items() if value not in (None, [], "")})
        if table_case_count >= 2:
            break
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
    ingest_readiness_name: str = "ingest_readiness_report.json",
    ingest_readiness_md_name: str | None = "ingest_readiness_report.md",
    formal_handoff_manifest_name: str = "formal_handoff_manifest.json",
    quality_report_name: str | None = None,
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
        f"- `{doc_manifest_name}`: required v0.1 document-level ingestion contract consumed by `ragflow-kb-build`.",
        f"- `{formal_handoff_manifest_name}`: package-level audit manifest with sidecar hashes and downstream command suggestions.",
        f"- `{metadata_name}`: document-level source and Markdown metadata.",
        f"- `{artifact_index_name}`: hashes, kinds, and advisory image semantics for local assets under `documents/` and `artifacts/`.",
        f"- `{profile_suggestions_name}`: advisory parser/profile hints for review.",
        f"- `{retrieval_hints_name}`: section, keyword, question, and quality-risk hints for retrieval review.",
        f"- `{assistant_profile_name}`: advisory assistant retrieval and answer policy profile.",
        f"- `{assistant_test_plan_name}`: staged assistant validation questions for review.",
        f"- `{ingest_readiness_name}`: JSON-first formal-ingest readiness report for deterministic review.",
    ]
    if ingest_readiness_md_name:
        lines.append(f"- `{ingest_readiness_md_name}`: Markdown summary rendered from `{ingest_readiness_name}`.")
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


def _read_json_if_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _read_json(path)


def _read_sidecar_identity(path: Path) -> str | None:
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            payload = _read_simple_yaml(path)
        else:
            return None
    except (HandoffError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    schema = payload.get("schema")
    if isinstance(schema, str) and schema.strip():
        return schema.strip()
    version = payload.get("version")
    if isinstance(version, str) and version.strip():
        return f"version:{version.strip()}"
    return None


def _formal_sidecar_record(
    *,
    root: Path,
    name: str,
    raw_path: str | None,
    category: str,
) -> dict[str, Any]:
    if not raw_path:
        return {
            "name": name,
            "path": None,
            "category": category,
            "exists": False,
            "safe_relative_path": False,
        }
    safe_path = _safe_relative_reference(raw_path)
    record: dict[str, Any] = {
        "name": name,
        "path": raw_path if safe_path else "<unsafe>",
        "category": category,
        "exists": False,
        "safe_relative_path": safe_path,
    }
    if not safe_path:
        return record
    path = root / raw_path
    record["exists"] = path.is_file()
    if path.is_file():
        record["size_bytes"] = path.stat().st_size
        record["sha256"] = sha256_file(path)
        identity = _read_sidecar_identity(path)
        if identity:
            record["schema_identity"] = identity
    return record


def _document_markdown_records(*, root: Path, documents: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        raw_path = document.get("markdown_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            records.append(
                {
                    "document_index": index,
                    "path": None,
                    "exists": False,
                    "safe_relative_path": False,
                }
            )
            continue
        safe_path = _safe_relative_reference(raw_path)
        record: dict[str, Any] = {
            "document_index": index,
            "path": raw_path if safe_path else "<unsafe>",
            "exists": False,
            "safe_relative_path": safe_path,
        }
        if safe_path:
            path = root / raw_path
            record["exists"] = path.is_file()
            if path.is_file():
                record["size_bytes"] = path.stat().st_size
                record["sha256"] = sha256_file(path)
        records.append(record)
    return records


def _image_asset_records(*, root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for container in ("documents", "artifacts"):
        base = root / container
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _artifact_kind(path) != "image":
                continue
            records.append(_file_record(path, root=root))
    return records


def _schema_versions_from_records(records: list[Mapping[str, Any]]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for record in records:
        name = record.get("name")
        identity = record.get("schema_identity")
        if isinstance(name, str) and isinstance(identity, str) and identity:
            versions[name] = identity
    return versions


def _package_hash_payload(
    *,
    sidecars: list[Mapping[str, Any]],
    markdown_files: list[Mapping[str, Any]],
    image_assets: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for group, records in (
        ("sidecar", sidecars),
        ("markdown", markdown_files),
        ("image_asset", image_assets),
    ):
        for record in records:
            sha256 = record.get("sha256")
            path = record.get("path")
            if not isinstance(sha256, str) or not isinstance(path, str):
                continue
            entries.append(
                {
                    "group": group,
                    "path": path,
                    "sha256": sha256,
                    "size_bytes": record.get("size_bytes"),
                    "schema_identity": record.get("schema_identity"),
                }
            )
    return sorted(entries, key=lambda item: (str(item["group"]), str(item["path"])))


def _aggregate_package_hash(entries: list[Mapping[str, Any]]) -> str:
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _quality_status_from_reports(doc_manifest: Mapping[str, Any], quality_report: Mapping[str, Any] | None) -> str | None:
    manifest_gate = doc_manifest.get("quality_gate") if isinstance(doc_manifest.get("quality_gate"), Mapping) else {}
    status = manifest_gate.get("status") if isinstance(manifest_gate.get("status"), str) else None
    if isinstance(quality_report, Mapping):
        gate = quality_report.get("gate") if isinstance(quality_report.get("gate"), Mapping) else {}
        if isinstance(gate.get("status"), str):
            status = gate["status"]
    return status


def _quality_content_counts(quality_report: Mapping[str, Any] | None) -> dict[str, int]:
    counts = {
        "document_count": 0,
        "image_count": 0,
        "table_count": 0,
        "html_table_count": 0,
        "markdown_table_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }
    if not isinstance(quality_report, Mapping):
        return counts
    documents = quality_report.get("documents")
    if not isinstance(documents, list):
        return counts
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        counts["document_count"] += 1
        signals = document.get("quality_signals")
        if not isinstance(signals, Mapping):
            signals = {}
        for key in ("image_count", "table_count", "html_table_count", "markdown_table_count"):
            value = document.get(key)
            if value is None:
                value = signals.get(key)
            try:
                counts[key] += int(value or 0)
            except (TypeError, ValueError):
                pass
        issues = document.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, Mapping):
                    continue
                severity = issue.get("severity")
                if severity == "error":
                    counts["error_count"] += 1
                elif severity == "warning":
                    counts["warning_count"] += 1
    return counts


def _readiness_issue(
    *,
    check: str,
    severity: str,
    code: str,
    message: str,
    recommendation: str,
) -> dict[str, str]:
    return {
        "check": check,
        "severity": severity,
        "code": code,
        "message": message,
        "recommendation": recommendation,
    }


def _readiness_status(issues: list[Mapping[str, Any]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "blocked"
    if any(issue.get("severity") == "warning" for issue in issues):
        return "ready_with_review"
    return "ready"


def _readiness_score(issues: list[Mapping[str, Any]]) -> int:
    score = 100
    for issue in issues:
        if issue.get("severity") == "error":
            score -= 35
        elif issue.get("severity") == "warning":
            score -= 10
    return max(score, 0)


def _sidecar_readiness(root: Path, sidecar_names: Mapping[str, str | None]) -> dict[str, Any]:
    categories = {
        "metadata": "rich",
        "artifact_index": "rich",
        "profile_suggestions": "rich",
        "retrieval_hints": "rich",
        "assistant_profile": "rich",
        "assistant_test_plan": "rich",
        "package_readme": "rich",
        "quality_report": "core",
        "postprocess_report": "pipeline",
        "chunk_profile_report": "pipeline",
        "ragflow_ingest_plan": "pipeline",
    }
    sidecars: dict[str, dict[str, Any]] = {}
    missing_by_category: dict[str, list[str]] = {"core": [], "rich": [], "pipeline": []}
    unsafe_paths: list[str] = []
    for name, category in categories.items():
        raw_path = sidecar_names.get(name)
        if not raw_path:
            if category != "pipeline" or name != "chunk_profile_report":
                missing_by_category[category].append(name)
            continue
        safe_path = _safe_relative_reference(str(raw_path))
        if not safe_path:
            unsafe_paths.append(name)
        path = root / str(raw_path)
        record: dict[str, Any] = {
            "path": str(raw_path),
            "exists": path.is_file(),
            "category": category,
            "safe_relative_path": safe_path,
        }
        if path.is_file():
            record["size_bytes"] = path.stat().st_size
        else:
            missing_by_category[category].append(name)
        sidecars[name] = record
    return {
        "sidecars": sidecars,
        "missing": missing_by_category,
        "unsafe_paths": unsafe_paths,
        "rich_complete": not missing_by_category["rich"],
        "pipeline_complete": not missing_by_category["pipeline"],
        "core_complete": not missing_by_category["core"],
    }


def _retrieval_hint_summary(retrieval_hints: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval_hints, Mapping):
        return {
            "exists": False,
            "section_boundary_count": 0,
            "keyword_candidate_count": 0,
            "question_candidate_count": 0,
            "preferred_boundary_count": 0,
            "table_artifact_count": 0,
            "image_artifact_count": 0,
            "layout_signal_count": 0,
            "asset_semantic_image_count": 0,
            "table_term_alias_candidate_count": 0,
            "table_semantic_risk_count": 0,
            "quality_risk_count": 0,
        }
    asset_semantics = retrieval_hints.get("asset_semantics") if isinstance(retrieval_hints.get("asset_semantics"), Mapping) else {}
    asset_summary = asset_semantics.get("summary") if isinstance(asset_semantics.get("summary"), Mapping) else {}
    return {
        "exists": True,
        "schema": retrieval_hints.get("schema"),
        "section_boundary_count": len(retrieval_hints.get("section_boundaries", []))
        if isinstance(retrieval_hints.get("section_boundaries"), list)
        else 0,
        "keyword_candidate_count": len(retrieval_hints.get("keyword_candidates", []))
        if isinstance(retrieval_hints.get("keyword_candidates"), list)
        else 0,
        "question_candidate_count": len(retrieval_hints.get("question_candidates", []))
        if isinstance(retrieval_hints.get("question_candidates"), list)
        else 0,
        "preferred_boundary_count": len(retrieval_hints.get("preferred_boundaries", []))
        if isinstance(retrieval_hints.get("preferred_boundaries"), list)
        else 0,
        "table_artifact_count": len(retrieval_hints.get("table_artifacts", []))
        if isinstance(retrieval_hints.get("table_artifacts"), list)
        else 0,
        "table_term_alias_candidate_count": len(retrieval_hints.get("table_term_alias_candidates", []))
        if isinstance(retrieval_hints.get("table_term_alias_candidates"), list)
        else 0,
        "table_semantic_risk_count": sum(
            len(item.get("semantic_risks", []))
            for item in retrieval_hints.get("table_artifacts", [])
            if isinstance(item, Mapping) and isinstance(item.get("semantic_risks"), list)
        )
        if isinstance(retrieval_hints.get("table_artifacts"), list)
        else 0,
        "image_artifact_count": len(retrieval_hints.get("image_artifacts", []))
        if isinstance(retrieval_hints.get("image_artifacts"), list)
        else 0,
        "layout_signal_count": len(retrieval_hints.get("layout_signals", []))
        if isinstance(retrieval_hints.get("layout_signals"), list)
        else 0,
        "asset_semantic_image_count": int(asset_summary.get("image_count", 0) or 0),
        "quality_risk_count": len(retrieval_hints.get("quality_risks", []))
        if isinstance(retrieval_hints.get("quality_risks"), list)
        else 0,
    }


def summarize_retrieval_hints(retrieval_hints: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return stable counts used by build and profile review surfaces."""

    return _retrieval_hint_summary(retrieval_hints)


def _chunk_readiness_summary(
    *,
    postprocess_report: Mapping[str, Any] | None,
    chunk_profile_report: Mapping[str, Any] | None,
    sidecar_exists: bool,
    selected_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "chunk_profile_report_exists": sidecar_exists,
        "marker_count": 0,
        "warning_count": 0,
        "profile": None,
        "preferred_boundary_alignment_ratio": None,
    }
    if isinstance(selected_profile, Mapping):
        parser_config = selected_profile.get("parser_config") if isinstance(selected_profile.get("parser_config"), Mapping) else {}
        delimiter = parser_config.get("delimiter") if isinstance(parser_config, Mapping) else None
        delimiter_text = str(delimiter or "")
        has_chunk_delimiter = bool(CHUNK_MARKER_RE.search(delimiter_text))
        summary["selected_profile_id"] = str(selected_profile.get("id") or selected_profile.get("profile_id") or "")
        summary["selected_profile_has_chunk_delimiter"] = has_chunk_delimiter
        summary["selected_profile_marker_behavior"] = "honored" if has_chunk_delimiter else "ignored"
    source = chunk_profile_report
    if not isinstance(source, Mapping) and isinstance(postprocess_report, Mapping):
        embedded = postprocess_report.get("chunk_profile_report")
        if isinstance(embedded, Mapping):
            source = embedded
    if isinstance(source, Mapping):
        report_summary = source.get("summary") if isinstance(source.get("summary"), Mapping) else {}
        summary["schema"] = source.get("schema")
        summary["profile"] = source.get("profile")
        for key in ("marker_count", "warning_count"):
            try:
                summary[key] = int(report_summary.get(key, 0) or 0)
            except (TypeError, ValueError):
                summary[key] = 0
        summary["preferred_boundary_alignment_ratio"] = report_summary.get("preferred_boundary_alignment_ratio")
    return summary


def _normalize_language_hint(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unspecified"
    if text in {"zh", "zh-cn", "zh_hans", "zh-hans", "cn", "ch", "zho", "chinese"}:
        return "zh"
    if text.startswith("chinese"):
        return "zh"
    if text in {"en", "en-us", "eng", "english"}:
        return "en"
    if text.startswith("english"):
        return "en"
    return text


def _document_language_readiness(
    *,
    root: Path,
    documents: list[Mapping[str, Any]],
    selected_profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    manifest_hints = [
        _normalize_language_hint(document.get("language"))
        for document in documents
        if _normalize_language_hint(document.get("language")) != "unspecified"
    ]
    cjk_document_count = 0
    scanned_document_count = 0
    for document in documents:
        markdown_path = document.get("markdown_path")
        if not isinstance(markdown_path, str):
            continue
        path = root / markdown_path
        if not path.is_file():
            continue
        scanned_document_count += 1
        sample = path.read_text(encoding="utf-8", errors="replace")[:8000]
        if any("\u4e00" <= char <= "\u9fff" for char in sample):
            cjk_document_count += 1
    detected = "zh" if "zh" in manifest_hints or cjk_document_count else "unknown"

    selected_profile_provided = isinstance(selected_profile, Mapping)
    profile_language = "not_selected" if not selected_profile_provided else "unspecified"
    if isinstance(selected_profile, Mapping):
        parser_config = selected_profile.get("parser_config") if isinstance(selected_profile.get("parser_config"), Mapping) else {}
        for value in (
            parser_config.get("__language__") if isinstance(parser_config, Mapping) else None,
            selected_profile.get("language"),
            selected_profile.get("locale"),
        ):
            normalized = _normalize_language_hint(value)
            if normalized != "unspecified":
                profile_language = normalized
                break

    review_required = selected_profile_provided and detected == "zh" and profile_language != "zh"
    return {
        "detected_language": detected,
        "selected_profile_language": profile_language,
        "selected_profile_provided": selected_profile_provided,
        "manifest_language_hints": manifest_hints[:20],
        "cjk_document_count": cjk_document_count,
        "scanned_document_count": scanned_document_count,
        "review_required": review_required,
    }


def _ingest_plan_summary(ragflow_ingest_plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ragflow_ingest_plan, Mapping):
        return {
            "exists": False,
            "schema": None,
            "has_dry_run_command": False,
            "stores_api_credentials": None,
            "stores_ragflow_endpoint": None,
            "mutation_default": None,
        }
    safety = ragflow_ingest_plan.get("safety") if isinstance(ragflow_ingest_plan.get("safety"), Mapping) else {}
    recommended_build = (
        ragflow_ingest_plan.get("recommended_build")
        if isinstance(ragflow_ingest_plan.get("recommended_build"), Mapping)
        else {}
    )
    dry_run_command = recommended_build.get("dry_run_command")
    return {
        "exists": True,
        "schema": ragflow_ingest_plan.get("schema"),
        "has_handoff_block": isinstance(ragflow_ingest_plan.get("handoff"), Mapping),
        "has_dry_run_command": isinstance(dry_run_command, list) and "--dry-run" in [str(item) for item in dry_run_command],
        "stores_api_credentials": safety.get("stores_api_credentials"),
        "stores_ragflow_endpoint": safety.get("stores_ragflow_endpoint"),
        "stores_secret": safety.get("stores_secret"),
        "mutation_default": safety.get("mutation_default"),
    }


def _default_next_commands() -> list[dict[str, Any]]:
    return [
        {
            "name": "inspect_handoff",
            "command": [
                "ragflow-kb-build",
                "inspect-handoff",
                "--handoff",
                "<handoff>",
                "--report-json",
                "<run>/handoff_inspection.json",
                "--report-md",
                "<run>/handoff_inspection.md",
            ],
        },
        {
            "name": "dry_run",
            "command": [
                "ragflow-kb-build",
                "--doc-manifest",
                "<handoff>/doc_manifest.json",
                "--kb-name",
                "<kb-name>",
                "--profile",
                "<reviewed-profile.json>",
                "--dry-run",
                "--json",
            ],
        },
    ]


def make_doc_ingest_readiness_payload(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    sidecar_names: Mapping[str, str | None] | None = None,
    selected_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic formal-ingest readiness report for a handoff."""

    root = Path(handoff_root)
    doc_manifest = load_doc_manifest_payload(root / doc_manifest_name)
    documents = _manifest_documents(doc_manifest)
    default_sidecars: dict[str, str | None] = {
        "metadata": "metadata.json",
        "artifact_index": "artifact_index.json",
        "profile_suggestions": "profile_suggestions.json",
        "retrieval_hints": "retrieval_hints.json",
        "assistant_profile": "assistant_profile.json",
        "assistant_test_plan": "assistant_test_plan.json",
        "package_readme": "package_readme.md",
        "quality_report": doc_manifest.get("quality_report") if isinstance(doc_manifest.get("quality_report"), str) else None,
        "postprocess_report": doc_manifest.get("postprocess_report")
        if isinstance(doc_manifest.get("postprocess_report"), str)
        else "postprocess_report.json",
        "chunk_profile_report": doc_manifest.get("chunk_profile_report")
        if isinstance(doc_manifest.get("chunk_profile_report"), str)
        else None,
        "ragflow_ingest_plan": "ragflow_ingest_plan.yaml",
    }
    if sidecar_names:
        default_sidecars.update({key: value for key, value in sidecar_names.items() if key in default_sidecars})
    sidecar_summary = _sidecar_readiness(root, default_sidecars)
    sidecars = sidecar_summary["sidecars"]

    quality_report_name = default_sidecars.get("quality_report")
    quality_report = _read_json_if_file(root / quality_report_name) if quality_report_name else None
    artifact_index_name = default_sidecars.get("artifact_index")
    artifact_index = _read_json_if_file(root / artifact_index_name) if artifact_index_name else None
    retrieval_hints_name = default_sidecars.get("retrieval_hints")
    retrieval_hints = _read_json_if_file(root / retrieval_hints_name) if retrieval_hints_name else None
    postprocess_name = default_sidecars.get("postprocess_report")
    postprocess_report = _read_json_if_file(root / postprocess_name) if postprocess_name else None
    chunk_profile_name = default_sidecars.get("chunk_profile_report")
    chunk_profile_report = _read_json_if_file(root / chunk_profile_name) if chunk_profile_name else None
    ingest_plan_name = default_sidecars.get("ragflow_ingest_plan")
    ingest_plan_error: str | None = None
    try:
        ragflow_ingest_plan = (
            load_ragflow_ingest_plan(root / ingest_plan_name)
            if ingest_plan_name and (root / ingest_plan_name).is_file()
            else None
        )
    except HandoffError as exc:
        ragflow_ingest_plan = None
        ingest_plan_error = str(exc)

    quality_status = _quality_status_from_reports(doc_manifest, quality_report)
    quality_counts = _quality_content_counts(quality_report)
    image_assets = _inspect_image_assets(root=root, documents=documents)
    retrieval_summary = _retrieval_hint_summary(retrieval_hints)
    chunk_summary = _chunk_readiness_summary(
        postprocess_report=postprocess_report,
        chunk_profile_report=chunk_profile_report,
        sidecar_exists=bool(sidecars.get("chunk_profile_report", {}).get("exists")),
        selected_profile=selected_profile,
    )
    language_readiness = _document_language_readiness(
        root=root,
        documents=documents,
        selected_profile=selected_profile,
    )
    table_parent_chunk_preflight = _table_parent_chunk_preflight(
        retrieval_hints=retrieval_hints,
        selected_profile=selected_profile,
    )
    ingest_plan = _ingest_plan_summary(ragflow_ingest_plan)
    if ingest_plan_error:
        ingest_plan["exists"] = True
        ingest_plan["load_error"] = ingest_plan_error
    asset_semantics = artifact_index.get("asset_semantics") if isinstance(artifact_index, Mapping) else {}
    asset_semantics_summary = (
        asset_semantics.get("summary")
        if isinstance(asset_semantics, Mapping) and isinstance(asset_semantics.get("summary"), Mapping)
        else {}
    )

    issues: list[dict[str, str]] = []
    if quality_status == "BLOCKED":
        issues.append(
            _readiness_issue(
                check="quality_gate",
                severity="error",
                code="quality_gate_blocked",
                message="doc handoff quality gate is BLOCKED",
                recommendation="Resolve quality_report.json errors before any live build.",
            )
        )
    elif quality_status == "PASS_WITH_REVIEW":
        issues.append(
            _readiness_issue(
                check="quality_gate",
                severity="warning",
                code="quality_gate_review_required",
                message="quality gate passed with manual review required",
                recommendation="Review quality warnings before dry-run and live build.",
            )
        )
    elif quality_status != "PASS":
        issues.append(
            _readiness_issue(
                check="quality_gate",
                severity="warning",
                code="quality_gate_unknown",
                message="quality gate status is missing or unknown",
                recommendation="Run ragflow-doc-to-md conversion quality checks before formal ingestion.",
            )
        )

    if image_assets["missing_image_count"]:
        issues.append(
            _readiness_issue(
                check="local_assets",
                severity="error",
                code="image_assets_missing",
                message="one or more Markdown image references or manifest image assets are missing",
                recommendation="Regenerate the handoff with asset landing enabled or repair image paths.",
            )
        )
    if sidecar_summary["unsafe_paths"]:
        issues.append(
            _readiness_issue(
                check="redaction_safety",
                severity="error",
                code="unsafe_sidecar_path",
                message="one or more sidecar paths are absolute, remote, or parent-relative",
                recommendation="Use relative handoff-local sidecar names before sharing the package.",
            )
        )
    if sidecar_summary["missing"]["rich"]:
        issues.append(
            _readiness_issue(
                check="rich_sidecars",
                severity="warning",
                code="rich_sidecars_incomplete",
                message="one or more rich handoff sidecars are missing",
                recommendation="Run ragflow-doc-to-md pipeline or package --rich before formal ingestion review.",
            )
        )
    if sidecar_summary["missing"]["pipeline"]:
        issues.append(
            _readiness_issue(
                check="pipeline_sidecars",
                severity="warning",
                code="pipeline_sidecars_incomplete",
                message="one or more formal pipeline sidecars are missing",
                recommendation="Run ragflow-doc-to-md pipeline so postprocess, chunk profile, and ingest plan artifacts are generated together.",
            )
        )
    if chunk_summary["chunk_profile_report_exists"] and chunk_summary.get("marker_count", 0) == 0:
        issues.append(
            _readiness_issue(
                check="chunk_readiness",
                severity="warning",
                code="chunk_markers_absent",
                message="chunk profile report exists but records no chunk markers",
                recommendation="Review whether the selected postprocess profile provides enough chunk boundaries.",
            )
        )
    elif not chunk_summary["chunk_profile_report_exists"]:
        issues.append(
            _readiness_issue(
                check="chunk_readiness",
                severity="warning",
                code="chunk_profile_report_missing",
                message="chunk profile readiness sidecar is missing",
                recommendation="Use a chunk-marker postprocess profile before formal ingestion when chunk boundaries matter.",
            )
        )
    if (
        chunk_summary.get("marker_count", 0) > 0
        and chunk_summary.get("selected_profile_marker_behavior") == "ignored"
    ):
        issues.append(
            _readiness_issue(
                check="chunk_readiness",
                severity="warning",
                code="chunk_markers_ignored_by_selected_profile",
                message="chunk markers exist but the selected profile does not define the chunk delimiter",
                recommendation="Use a delimiter-aware profile with parser_config.delimiter set to `<!-- chunk -->`, or treat chunk markers as advisory comments only.",
            )
        )
    if language_readiness["review_required"]:
        issues.append(
            _readiness_issue(
                check="language_readiness",
                severity="warning",
                code="chinese_corpus_profile_language_unspecified",
                message="Chinese text was detected but the selected profile does not declare Chinese language metadata",
                recommendation="Review parser/tokenizer expectations and prefer a profile with parser_config.__language__ set to Chinese for Chinese corpora.",
            )
        )
    if not retrieval_summary["exists"]:
        issues.append(
            _readiness_issue(
                check="retrieval_hints",
                severity="warning",
                code="retrieval_hints_missing",
                message="retrieval_hints.json is missing",
                recommendation="Run ragflow-doc-to-md package --rich or pipeline before KB dry-run.",
            )
        )
    elif retrieval_summary["section_boundary_count"] == 0 or retrieval_summary["question_candidate_count"] == 0:
        issues.append(
            _readiness_issue(
                check="retrieval_hints",
                severity="warning",
                code="retrieval_hints_sparse",
                message="retrieval hints have sparse section or question coverage",
                recommendation="Review Markdown headings and package sidecars before formal ingestion.",
            )
        )
    for issue in table_parent_chunk_preflight.get("issues", []):
        if not isinstance(issue, Mapping):
            continue
        issues.append(
            _readiness_issue(
                check="table_parent_chunk_preflight",
                severity=str(issue.get("severity") or "warning"),
                code=str(issue.get("code") or "table_parent_chunk_review"),
                message=str(issue.get("message") or "table parent chunk profile needs review"),
                recommendation=str(
                    issue.get("recommendation")
                    or "Review table size, delimiter behavior, and deployment parent chunk limits before live upload."
                ),
            )
        )
    if quality_counts["image_count"] and retrieval_summary["image_artifact_count"] == 0:
        issues.append(
            _readiness_issue(
                check="artifact_coverage",
                severity="warning",
                code="image_artifact_hints_missing",
                message="quality report found images but retrieval hints contain no image artifacts",
                recommendation="Regenerate rich handoff sidecars and verify image semantics before formal ingestion.",
            )
        )
    if quality_counts["table_count"] and retrieval_summary["table_artifact_count"] == 0:
        issues.append(
            _readiness_issue(
                check="artifact_coverage",
                severity="warning",
                code="table_artifact_hints_missing",
                message="quality report found tables but retrieval hints contain no table artifacts",
                recommendation="Review table extraction and regenerate retrieval hints before formal ingestion.",
            )
        )
    if ingest_plan_error:
        issues.append(
            _readiness_issue(
                check="ragflow_ingest_plan",
                severity="error",
                code="ingest_plan_invalid",
                message="ragflow ingest plan could not be loaded or validated",
                recommendation="Regenerate ragflow_ingest_plan.yaml with ragflow-doc-to-md pipeline.",
            )
        )
    elif not ingest_plan["exists"]:
        issues.append(
            _readiness_issue(
                check="ragflow_ingest_plan",
                severity="warning",
                code="ingest_plan_missing",
                message="ragflow_ingest_plan.yaml is missing",
                recommendation="Run ragflow-doc-to-md pipeline before a formal dry-run build.",
            )
        )
    else:
        if ingest_plan["schema"] != RAGFLOW_INGEST_PLAN_SCHEMA or not ingest_plan.get("has_handoff_block"):
            issues.append(
                _readiness_issue(
                    check="ragflow_ingest_plan",
                    severity="error",
                    code="ingest_plan_invalid",
                    message="ingest plan schema or handoff block is invalid",
                    recommendation="Regenerate ragflow_ingest_plan.yaml with ragflow-doc-to-md pipeline.",
                )
            )
        if ingest_plan.get("stores_api_credentials") or ingest_plan.get("stores_ragflow_endpoint") or ingest_plan.get("stores_secret"):
            issues.append(
                _readiness_issue(
                    check="redaction_safety",
                    severity="error",
                    code="ingest_plan_stores_private_config",
                    message="ingest plan claims to store endpoint, credential, or secret material",
                    recommendation="Regenerate a non-secret ingest plan before sharing or building.",
                )
            )
        if not ingest_plan.get("has_dry_run_command") or ingest_plan.get("mutation_default") != "dry_run_first":
            issues.append(
                _readiness_issue(
                    check="ragflow_ingest_plan",
                    severity="warning",
                    code="ingest_plan_dry_run_not_explicit",
                    message="ingest plan does not clearly prefer dry-run before mutation",
                    recommendation="Review the plan and run ragflow-kb-build with --dry-run first.",
                )
            )

    status = _readiness_status(issues)
    score = _readiness_score(issues)
    checks = {
        "quality_gate": {
            "status": "pass"
            if quality_status == "PASS"
            else "review"
            if quality_status == "PASS_WITH_REVIEW"
            else "blocked"
            if quality_status == "BLOCKED"
            else "review",
            "quality_status": quality_status,
            "allows_build": quality_status in {"PASS", "PASS_WITH_REVIEW"},
            "summary": quality_counts,
        },
        "local_assets": image_assets,
        "sidecar_completeness": {
            "core_complete": sidecar_summary["core_complete"],
            "rich_complete": sidecar_summary["rich_complete"],
            "pipeline_complete": sidecar_summary["pipeline_complete"],
            "missing": sidecar_summary["missing"],
        },
        "chunk_readiness": chunk_summary,
        "language_readiness": language_readiness,
        "table_parent_chunk_preflight": table_parent_chunk_preflight,
        "retrieval_hints_richness": retrieval_summary,
        "artifact_coverage": {
            "quality_image_count": quality_counts["image_count"],
            "quality_table_count": quality_counts["table_count"],
            "hint_image_artifact_count": retrieval_summary["image_artifact_count"],
            "hint_table_artifact_count": retrieval_summary["table_artifact_count"],
            "asset_semantic_image_count": int(asset_semantics_summary.get("image_count", 0) or 0),
        },
        "ragflow_ingest_plan": ingest_plan,
        "redaction_safety": {
            "stores_private_paths": False,
            "stores_remote_urls": False,
            "unsafe_sidecar_paths": sidecar_summary["unsafe_paths"],
            "sidecar_paths_are_relative": not sidecar_summary["unsafe_paths"],
        },
    }
    return {
        "schema": DOC_INGEST_READINESS_SCHEMA,
        "created_at": _now(),
        "handoff_mode": doc_manifest.get("handoff_mode") if isinstance(doc_manifest.get("handoff_mode"), str) else None,
        "doc_manifest": doc_manifest_name,
        "status": status,
        "advisory_score": score,
        "allowed_statuses": ["ready", "ready_with_review", "blocked"],
        "summary": {
            "document_count": len(documents),
            "quality_status": quality_status,
            "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
            "issue_count": len(issues),
            "rich_sidecars_complete": sidecar_summary["rich_complete"],
            "pipeline_sidecars_complete": sidecar_summary["pipeline_complete"],
            "missing_image_count": image_assets["missing_image_count"],
            "retrieval_hint_section_count": retrieval_summary["section_boundary_count"],
            "chunk_marker_count": chunk_summary["marker_count"],
            "table_parent_chunk_preflight_status": table_parent_chunk_preflight["status"],
            "max_table_estimated_parent_chunk_tokens": table_parent_chunk_preflight[
                "max_estimated_parent_chunk_tokens"
            ],
        },
        "checks": checks,
        "sidecars": sidecars,
        "issues": issues,
        "recommended_next_commands": _default_next_commands(),
        "safety": {
            "live_ragflow_mutation": "not_performed",
            "mutation_default": "dry_run_first",
            "script_owned_llm": "not_used",
        },
    }


def render_doc_ingest_readiness_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown from a ragflow_doc_ingest_readiness_v1 JSON payload."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), Mapping) else {}
    sidecar_check = checks.get("sidecar_completeness") if isinstance(checks.get("sidecar_completeness"), Mapping) else {}
    assets = checks.get("local_assets") if isinstance(checks.get("local_assets"), Mapping) else {}
    hints = checks.get("retrieval_hints_richness") if isinstance(checks.get("retrieval_hints_richness"), Mapping) else {}
    chunk = checks.get("chunk_readiness") if isinstance(checks.get("chunk_readiness"), Mapping) else {}
    table_chunk = (
        checks.get("table_parent_chunk_preflight")
        if isinstance(checks.get("table_parent_chunk_preflight"), Mapping)
        else {}
    )
    ingest_plan = checks.get("ragflow_ingest_plan") if isinstance(checks.get("ragflow_ingest_plan"), Mapping) else {}
    lines = [
        "# RAGFlow Doc Ingest Readiness",
        "",
        f"- schema: `{report.get('schema', DOC_INGEST_READINESS_SCHEMA)}`",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- advisory_score: {report.get('advisory_score', 'unknown')}",
        f"- handoff_mode: `{report.get('handoff_mode') or 'unspecified'}`",
        f"- documents: {summary.get('document_count', 0)}",
        f"- quality_status: `{summary.get('quality_status') or 'UNKNOWN'}`",
        f"- issues: {summary.get('issue_count', 0)}",
        "",
        "## Checks",
        "",
        f"- rich_sidecars_complete: {str(bool(sidecar_check.get('rich_complete'))).lower()}",
        f"- pipeline_sidecars_complete: {str(bool(sidecar_check.get('pipeline_complete'))).lower()}",
        f"- missing_image_count: {assets.get('missing_image_count', 'unknown')}",
        f"- chunk_marker_count: {chunk.get('marker_count', 'unknown')}",
        f"- table_parent_chunk_preflight: `{table_chunk.get('status', 'unknown')}`",
        f"- max_table_estimated_parent_chunk_tokens: {table_chunk.get('max_estimated_parent_chunk_tokens', 'unknown')}",
        f"- retrieval_hint_sections: {hints.get('section_boundary_count', 'unknown')}",
        f"- image_artifacts: {hints.get('image_artifact_count', 'unknown')}",
        f"- table_artifacts: {hints.get('table_artifact_count', 'unknown')}",
        f"- ingest_plan_exists: {str(bool(ingest_plan.get('exists'))).lower()}",
        f"- ingest_plan_dry_run: {str(bool(ingest_plan.get('has_dry_run_command'))).lower()}",
        "",
    ]
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    if issues:
        lines.extend(["## Issues", ""])
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(
                f"- `{issue.get('code')}` ({issue.get('severity')} / {issue.get('check')}): {issue.get('message')}"
            )
        lines.append("")
    lines.extend(["## Recommended Next Commands", ""])
    commands = report.get("recommended_next_commands") if isinstance(report.get("recommended_next_commands"), list) else []
    for item in commands:
        if not isinstance(item, Mapping):
            continue
        command = item.get("command")
        if isinstance(command, list):
            rendered = " ".join(str(part) for part in command)
            lines.append(f"- `{item.get('name')}`: `{rendered}`")
    return "\n".join(lines).rstrip() + "\n"


def write_doc_ingest_readiness_report(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    ingest_readiness_name: str = "ingest_readiness_report.json",
    ingest_readiness_md_name: str | None = "ingest_readiness_report.md",
    sidecar_names: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Write JSON-first ingest readiness sidecars and return the JSON payload."""

    root = Path(handoff_root)
    payload = make_doc_ingest_readiness_payload(
        handoff_root=root,
        doc_manifest_name=doc_manifest_name,
        sidecar_names=sidecar_names,
    )
    json_path = root / ingest_readiness_name
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if ingest_readiness_md_name:
        md_path = root / ingest_readiness_md_name
        md_path.write_text(render_doc_ingest_readiness_markdown(payload), encoding="utf-8")
    return payload


def make_formal_handoff_manifest_payload(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    formal_handoff_manifest_name: str = "formal_handoff_manifest.json",
    sidecar_names: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Create a package-level formal handoff audit manifest without private paths."""

    root = Path(handoff_root)
    doc_manifest = load_doc_manifest_payload(root / doc_manifest_name)
    documents = _manifest_documents(doc_manifest)
    default_sidecars: dict[str, str | None] = {
        "doc_manifest": doc_manifest_name,
        "quality_report": doc_manifest.get("quality_report") if isinstance(doc_manifest.get("quality_report"), str) else None,
        "runtime_report": doc_manifest.get("runtime_report") if isinstance(doc_manifest.get("runtime_report"), str) else None,
        "postprocess_report": doc_manifest.get("postprocess_report")
        if isinstance(doc_manifest.get("postprocess_report"), str)
        else "postprocess_report.json",
        "chunk_profile_report": doc_manifest.get("chunk_profile_report")
        if isinstance(doc_manifest.get("chunk_profile_report"), str)
        else None,
        "metadata": "metadata.json",
        "artifact_index": "artifact_index.json",
        "profile_suggestions": "profile_suggestions.json",
        "retrieval_hints": "retrieval_hints.json",
        "assistant_profile": "assistant_profile.json",
        "assistant_test_plan": "assistant_test_plan.json",
        "ingest_readiness": "ingest_readiness_report.json",
        "ingest_readiness_md": "ingest_readiness_report.md",
        "package_readme": "package_readme.md",
        "ragflow_ingest_plan": "ragflow_ingest_plan.yaml",
    }
    if sidecar_names:
        default_sidecars.update({key: value for key, value in sidecar_names.items() if key in default_sidecars})
    categories = {
        "doc_manifest": "core",
        "quality_report": "core",
        "runtime_report": "core",
        "postprocess_report": "pipeline",
        "chunk_profile_report": "pipeline",
        "metadata": "rich",
        "artifact_index": "rich",
        "profile_suggestions": "rich",
        "retrieval_hints": "rich",
        "assistant_profile": "rich",
        "assistant_test_plan": "rich",
        "ingest_readiness": "rich",
        "ingest_readiness_md": "rich",
        "package_readme": "rich",
        "ragflow_ingest_plan": "pipeline",
    }
    sidecars = [
        _formal_sidecar_record(
            root=root,
            name=name,
            raw_path=path,
            category=categories.get(name, "sidecar"),
        )
        for name, path in default_sidecars.items()
        if path
    ]
    markdown_files = _document_markdown_records(root=root, documents=documents)
    image_assets = _image_asset_records(root=root)
    hash_inputs = _package_hash_payload(
        sidecars=sidecars,
        markdown_files=markdown_files,
        image_assets=image_assets,
    )
    missing_sidecars = [
        str(record.get("name"))
        for record in sidecars
        if record.get("exists") is False and record.get("category") in {"core", "rich", "pipeline"}
    ]
    unsafe_sidecars = [
        str(record.get("name"))
        for record in sidecars
        if record.get("safe_relative_path") is False
    ]
    schema_versions = _schema_versions_from_records(sidecars)
    return {
        "schema": FORMAL_HANDOFF_MANIFEST_SCHEMA,
        "created_at": _now(),
        "handoff_mode": doc_manifest.get("handoff_mode") if isinstance(doc_manifest.get("handoff_mode"), str) else None,
        "doc_manifest": doc_manifest_name,
        "formal_handoff_manifest": formal_handoff_manifest_name,
        "source_document_count": len(documents),
        "generated_sidecar_count": sum(1 for record in sidecars if record.get("exists")),
        "missing_sidecars": missing_sidecars,
        "sidecars": sidecars,
        "markdown_files": markdown_files,
        "image_assets": image_assets,
        "report_hashes": [
            {
                "name": record.get("name"),
                "path": record.get("path"),
                "sha256": record.get("sha256"),
                "schema_identity": record.get("schema_identity"),
            }
            for record in sidecars
            if isinstance(record.get("sha256"), str)
            and (
                str(record.get("name", "")).endswith("report")
                or str(record.get("path", "")).endswith((".json", ".yaml", ".yml", ".md"))
            )
        ],
        "schema_versions": schema_versions,
        "package_hash": _aggregate_package_hash(hash_inputs),
        "package_hash_algorithm": "sha256(relative_path+file_sha256+size+schema_identity)",
        "package_hash_inputs": hash_inputs,
        "downstream_command_suggestions": _default_next_commands(),
        "safety": {
            "paths": "relative_only",
            "unsafe_sidecars": unsafe_sidecars,
            "stores_ragflow_endpoint": False,
            "stores_api_credentials": False,
            "live_ragflow_mutation": "not_performed",
            "mutation_default": "dry_run_first",
        },
        "notes": [
            "doc_manifest.json remains the document-level ingestion contract.",
            "formal_handoff_manifest.json is a package-level audit manifest for review and handoff integrity.",
        ],
    }


def write_formal_handoff_manifest(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    formal_handoff_manifest_name: str = "formal_handoff_manifest.json",
    sidecar_names: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Write the package-level formal handoff manifest and return its payload."""

    root = Path(handoff_root)
    payload = make_formal_handoff_manifest_payload(
        handoff_root=root,
        doc_manifest_name=doc_manifest_name,
        formal_handoff_manifest_name=formal_handoff_manifest_name,
        sidecar_names=sidecar_names,
    )
    path = root / formal_handoff_manifest_name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _comparison_retained_effective_root(root: Path) -> tuple[Path, str]:
    ragflow_input = root / "ragflow_input"
    if root.name != "ragflow_input" and ragflow_input.is_dir():
        return ragflow_input, "ragflow_input"
    return root, "."


def _comparison_path_uses_ignored_dir(path: Path, root: Path, ignored_dirs: set[str]) -> bool:
    try:
        parts = path.relative_to(root).parts[:-1] if path.is_file() else path.relative_to(root).parts
    except ValueError:
        return True
    return any(part.lower() in ignored_dirs for part in parts)


def _comparison_count_ignored_dirs(root: Path, ignored_dirs: set[str]) -> int:
    count = 0
    if not root.is_dir():
        return count
    for path in root.rglob("*"):
        if path.is_dir() and path.name.lower() in ignored_dirs:
            count += 1
    return count


def _comparison_iter_files(root: Path, *, suffixes: set[str], ignored_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _comparison_path_uses_ignored_dir(path, root, ignored_dirs):
            continue
        if path.suffix.lower() in suffixes:
            files.append(path)
    return files


def _comparison_find_sidecar(root: Path, names: tuple[str, ...], *, ignored_dirs: set[str]) -> Path | None:
    lowered = {name.lower() for name in names}
    for name in names:
        direct = root / name
        if direct.is_file() and not _comparison_path_uses_ignored_dir(direct, root, ignored_dirs):
            return direct
    candidates = [
        path
        for path in _comparison_iter_files(root, suffixes={".json", ".yaml", ".yml", ".md"}, ignored_dirs=ignored_dirs)
        if path.name.lower() in lowered
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (len(item.relative_to(root).parts), item.relative_to(root).as_posix()))[0]


def _comparison_load_sidecar_payload(
    root: Path,
    names: tuple[str, ...],
    *,
    ignored_dirs: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    path = _comparison_find_sidecar(root, names, ignored_dirs=ignored_dirs)
    if path is None:
        return None, None
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            payload = _read_simple_yaml(path)
        else:
            return None, _relative(path, root)
    except (HandoffError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, _relative(path, root)
    if not isinstance(payload, dict):
        return None, _relative(path, root)
    return payload, _relative(path, root)


def _comparison_markdown_paths(
    *,
    root: Path,
    doc_manifest: Mapping[str, Any] | None,
    ignored_dirs: set[str],
) -> list[Path]:
    paths: list[Path] = []
    if isinstance(doc_manifest, Mapping):
        raw_documents = doc_manifest.get("documents")
        if isinstance(raw_documents, list):
            for document in raw_documents:
                if not isinstance(document, Mapping):
                    continue
                raw_path = document.get("markdown_path")
                if not isinstance(raw_path, str) or not _safe_relative_reference(raw_path):
                    continue
                path = root / raw_path
                if path.is_file() and not _comparison_path_uses_ignored_dir(path, root, ignored_dirs):
                    paths.append(path)
    if paths:
        return sorted(set(paths), key=lambda item: _relative(item, root))
    return [
        path
        for path in _comparison_iter_files(root, suffixes={".md", ".markdown"}, ignored_dirs=ignored_dirs)
        if path.name.lower() not in COMPARISON_MARKDOWN_SIDECAR_NAMES
    ]


def _comparison_file_records(paths: list[Path], *, root: Path, limit: int = 50) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths[:limit]:
        record = _file_record(path, root=root)
        records.append(record)
    return records


def _count_markdown_tables(text: str) -> int:
    lines = text.splitlines()
    count = 0
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        if MARKDOWN_TABLE_SEPARATOR_RE.match(lines[index + 1]):
            count += 1
    return count


def _comparison_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pandoc_artifact_counts(text: str) -> dict[str, int]:
    counts = {
        "fenced_div_marker_count": len(PANDOC_FENCED_DIV_LINE_RE.findall(text)),
        "empty_generated_anchor_count": len(PANDOC_EMPTY_ANCHOR_RE.findall(text)),
        "inline_style_attribute_count": len(PANDOC_SPAN_STYLE_RE.findall(text))
        + len(HTML_STYLE_ATTR_RE.findall(text)),
        "generated_heading_anchor_tail_count": len(PANDOC_HEADING_ANCHOR_TAIL_RE.findall(text)),
    }
    counts["total"] = sum(counts.values())
    return counts


def _merge_pandoc_artifact_counts(total: dict[str, int], counts: Mapping[str, int]) -> None:
    for key, value in counts.items():
        total[key] = total.get(key, 0) + int(value or 0)


def _is_missing_local_image_reference(raw: str, *, markdown_path: Path) -> bool:
    target = _image_reference_path(raw)
    if not target or _is_remote_image_reference(target):
        return False
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = markdown_path.parent / candidate
    return not candidate.exists()


def _normalize_markdown_text_for_comparison(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = CHUNK_MARKER_RE.sub("\n", normalized)
    normalized = MARKDOWN_IMAGE_RE.sub(lambda match: f"![{' '.join(match.group(1).split())}](<image>)", normalized)
    lines = [" ".join(line.split()) for line in normalized.splitlines() if line.strip()]
    return "\n".join(lines)


def _comparison_markdown_metrics(paths: list[Path], *, root: Path) -> tuple[dict[str, Any], str]:
    total_bytes = 0
    total_chars = 0
    total_lines = 0
    image_ref_count = 0
    local_image_ref_count = 0
    remote_image_ref_count = 0
    missing_local_image_ref_count = 0
    chunk_marker_count = 0
    markdown_table_count = 0
    html_table_count = 0
    pandoc_counts = {
        "fenced_div_marker_count": 0,
        "empty_generated_anchor_count": 0,
        "inline_style_attribute_count": 0,
        "generated_heading_anchor_tail_count": 0,
        "total": 0,
    }
    normalized_parts: list[str] = []
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        encoded = raw.encode("utf-8")
        total_bytes += len(encoded)
        total_chars += len(raw)
        total_lines += len(raw.splitlines())
        refs = list(MARKDOWN_IMAGE_RE.finditer(raw))
        image_ref_count += len(refs)
        for match in refs:
            target = _image_reference_path(match.group(2))
            if target and not _is_remote_image_reference(target):
                local_image_ref_count += 1
                if _is_missing_local_image_reference(target, markdown_path=path):
                    missing_local_image_ref_count += 1
            else:
                remote_image_ref_count += 1
        chunk_marker_count += len(CHUNK_MARKER_RE.findall(raw))
        markdown_table_count += _count_markdown_tables(raw)
        html_table_count += len(parse_html_tables(raw))
        _merge_pandoc_artifact_counts(pandoc_counts, _pandoc_artifact_counts(raw))
        normalized_parts.append(_normalize_markdown_text_for_comparison(raw))
    normalized_text = "\n".join(part for part in normalized_parts if part)
    return (
        {
            "markdown_file_count": len(paths),
            "markdown_bytes": total_bytes,
            "markdown_chars": total_chars,
            "markdown_lines": total_lines,
            "image_reference_count": image_ref_count,
            "local_image_reference_count": local_image_ref_count,
            "remote_image_reference_count": remote_image_ref_count,
            "missing_local_image_reference_count": missing_local_image_ref_count,
            "chunk_marker_count": chunk_marker_count,
            "markdown_table_count": markdown_table_count,
            "html_table_count": html_table_count,
            "pandoc_artifact_count": pandoc_counts["total"],
            "pandoc_artifacts": pandoc_counts,
            "normalized_text_chars": len(normalized_text),
            "normalized_text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        },
        normalized_text,
    )


def _comparison_sidecar_completeness(root: Path, *, ignored_dirs: set[str]) -> dict[str, Any]:
    expected: dict[str, tuple[str, ...]] = {
        "doc_manifest": ("doc_manifest.json",),
        "quality_report": ("quality_report.json",),
        "postprocess_report": ("postprocess_report.json",),
        "chunk_profile_report": ("chunk_profile_report.json",),
        "metadata": ("metadata.json",),
        "artifact_index": ("artifact_index.json",),
        "profile_suggestions": ("profile_suggestions.json",),
        "retrieval_hints": ("retrieval_hints.json",),
        "assistant_profile": ("assistant_profile.json",),
        "assistant_test_plan": ("assistant_test_plan.json",),
        "ingest_readiness": ("ingest_readiness_report.json",),
        "formal_handoff_manifest": ("formal_handoff_manifest.json",),
        "package_readme": ("package_readme.md",),
        "ragflow_ingest_plan": ("ragflow_ingest_plan.yaml", "ragflow_ingest_plan.yml", "ragflow_ingest_plan.json"),
        "legacy_ragflow_config": ("ragflow_config.yaml", "ragflow_config.yml", "ragflow_config.json"),
    }
    records: dict[str, dict[str, Any]] = {}
    present: list[str] = []
    missing: list[str] = []
    for name, filenames in expected.items():
        path = _comparison_find_sidecar(root, filenames, ignored_dirs=ignored_dirs)
        if path is None:
            missing.append(name)
            records[name] = {"present": False, "path": None}
            continue
        present.append(name)
        records[name] = {"present": True, "path": _relative(path, root)}
    return {
        "expected_count": len(expected),
        "present_count": len(present),
        "missing_count": len(missing),
        "completeness_ratio": round(len(present) / len(expected), 4) if expected else 1.0,
        "present": present,
        "missing": missing,
        "sidecars": records,
    }


def _comparison_quality_summary(
    root: Path,
    *,
    ignored_dirs: set[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    doc_manifest, doc_manifest_path = _comparison_load_sidecar_payload(
        root,
        ("doc_manifest.json",),
        ignored_dirs=ignored_dirs,
    )
    quality_report, quality_report_path = _comparison_load_sidecar_payload(
        root,
        ("quality_report.json",),
        ignored_dirs=ignored_dirs,
    )
    status = _quality_status_from_reports(doc_manifest or {}, quality_report) if doc_manifest or quality_report else None
    if not status and isinstance(quality_report, Mapping):
        for container_key in ("quality_gate", "gate", "summary"):
            container = quality_report.get(container_key)
            if isinstance(container, Mapping) and isinstance(container.get("status"), str):
                status = str(container["status"])
                break
        if not status and isinstance(quality_report.get("status"), str):
            status = str(quality_report["status"])
    counts = _quality_content_counts(quality_report)
    return (
        {
            "status": status or "UNKNOWN",
            "doc_manifest": doc_manifest_path,
            "quality_report": quality_report_path,
            "error_count": counts["error_count"],
            "warning_count": counts["warning_count"],
            "quality_image_count": counts["image_count"],
            "quality_table_count": counts["table_count"],
            "quality_html_table_count": counts["html_table_count"],
            "quality_markdown_table_count": counts["markdown_table_count"],
        },
        doc_manifest,
    )


def _comparison_artifact_summary(root: Path, *, ignored_dirs: set[str]) -> dict[str, Any]:
    image_files = _comparison_iter_files(root, suffixes=IMAGE_SUFFIXES, ignored_dirs=ignored_dirs)
    table_files = _comparison_iter_files(root, suffixes=TABLE_SUFFIXES, ignored_dirs=ignored_dirs)
    artifact_index, artifact_index_path = _comparison_load_sidecar_payload(
        root,
        ("artifact_index.json",),
        ignored_dirs=ignored_dirs,
    )
    indexed_images = 0
    indexed_tables = 0
    semantic_images = 0
    if isinstance(artifact_index, Mapping):
        artifacts = artifact_index.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, Mapping):
                    continue
                kind = artifact.get("kind")
                if kind == "image":
                    indexed_images += 1
                elif kind == "table":
                    indexed_tables += 1
        asset_semantics = artifact_index.get("asset_semantics")
        if isinstance(asset_semantics, Mapping):
            summary = asset_semantics.get("summary")
            if isinstance(summary, Mapping):
                try:
                    semantic_images = int(summary.get("image_count", 0) or 0)
                except (TypeError, ValueError):
                    semantic_images = 0
    return {
        "artifact_index": artifact_index_path,
        "local_image_file_count": len(image_files),
        "local_image_files_sample": _comparison_file_records(image_files, root=root, limit=25),
        "table_file_count": len(table_files),
        "table_files_sample": _comparison_file_records(table_files, root=root, limit=25),
        "artifact_index_image_count": indexed_images,
        "artifact_index_table_count": indexed_tables,
        "asset_semantic_image_count": semantic_images,
    }


def _comparison_retrieval_hints_summary(root: Path, *, ignored_dirs: set[str]) -> dict[str, Any]:
    payload, path = _comparison_load_sidecar_payload(root, ("retrieval_hints.json",), ignored_dirs=ignored_dirs)
    summary = _retrieval_hint_summary(payload)
    summary["path"] = path
    return summary


def _comparison_ingest_readiness_summary(root: Path, *, ignored_dirs: set[str]) -> dict[str, Any]:
    payload, path = _comparison_load_sidecar_payload(
        root,
        ("ingest_readiness_report.json",),
        ignored_dirs=ignored_dirs,
    )
    if not isinstance(payload, Mapping):
        return {"exists": False, "path": path, "status": None, "advisory_score": None}
    return {
        "exists": True,
        "path": path,
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "advisory_score": payload.get("advisory_score"),
    }


def _comparison_postprocess_summary(root: Path, *, ignored_dirs: set[str]) -> dict[str, Any]:
    payload, path = _comparison_load_sidecar_payload(root, ("postprocess_report.json",), ignored_dirs=ignored_dirs)
    if not isinstance(payload, Mapping):
        return {
            "exists": False,
            "path": path,
            "schema": None,
            "profile": None,
            "changed_documents": 0,
            "total_rule_applications": 0,
            "rule_counts": {},
        }
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    raw_rule_counts = summary.get("rule_counts") if isinstance(summary.get("rule_counts"), Mapping) else {}
    rule_counts = {str(key): _comparison_int(value) for key, value in raw_rule_counts.items()}
    return {
        "exists": True,
        "path": path,
        "schema": payload.get("schema"),
        "profile": payload.get("profile"),
        "changed_documents": _comparison_int(summary.get("changed_documents")),
        "total_rule_applications": _comparison_int(summary.get("total_rule_applications")),
        "rule_counts": rule_counts,
    }


def _comparison_package_summary(
    *,
    root: Path,
    role: str,
    ignored_dirs: set[str],
    effective_root_label: str,
) -> tuple[dict[str, Any], str]:
    quality, doc_manifest = _comparison_quality_summary(root, ignored_dirs=ignored_dirs)
    markdown_paths = _comparison_markdown_paths(root=root, doc_manifest=doc_manifest, ignored_dirs=ignored_dirs)
    markdown_metrics, normalized_text = _comparison_markdown_metrics(markdown_paths, root=root)
    hints = _comparison_retrieval_hints_summary(root, ignored_dirs=ignored_dirs)
    artifacts = _comparison_artifact_summary(root, ignored_dirs=ignored_dirs)
    sidecars = _comparison_sidecar_completeness(root, ignored_dirs=ignored_dirs)
    readiness = _comparison_ingest_readiness_summary(root, ignored_dirs=ignored_dirs)
    postprocess = _comparison_postprocess_summary(root, ignored_dirs=ignored_dirs)
    table_signal_count = (
        int(markdown_metrics["markdown_table_count"])
        + int(markdown_metrics["html_table_count"])
        + int(hints.get("table_artifact_count", 0) or 0)
        + int(artifacts["table_file_count"])
        + int(artifacts["artifact_index_table_count"])
    )
    image_signal_count = (
        int(markdown_metrics["image_reference_count"])
        + int(artifacts["local_image_file_count"])
        + int(hints.get("image_artifact_count", 0) or 0)
        + int(artifacts["artifact_index_image_count"])
        + int(artifacts["asset_semantic_image_count"])
    )
    summary = {
        "role": role,
        "root_label": role,
        "effective_root": effective_root_label,
        "scan": {
            "explicit_root_only": True,
            "ignored_directory_names": sorted(ignored_dirs),
            "ignored_directory_count": _comparison_count_ignored_dirs(root, ignored_dirs),
            "intermediate_dirs_excluded": bool(ignored_dirs),
        },
        "quality_gate": quality,
        "markdown": {
            **markdown_metrics,
            "markdown_files_sample": _comparison_file_records(markdown_paths, root=root, limit=25),
        },
        "images": {
            "markdown_image_reference_count": markdown_metrics["image_reference_count"],
            "local_image_reference_count": markdown_metrics["local_image_reference_count"],
            "missing_local_image_reference_count": markdown_metrics["missing_local_image_reference_count"],
            **artifacts,
        },
        "tables": {
            "markdown_table_count": markdown_metrics["markdown_table_count"],
            "html_table_count": markdown_metrics["html_table_count"],
            "retrieval_hint_table_artifact_count": hints.get("table_artifact_count", 0),
            "table_file_count": artifacts["table_file_count"],
            "artifact_index_table_count": artifacts["artifact_index_table_count"],
            "total_static_table_signal_count": table_signal_count,
        },
        "chunk_markers": {
            "marker_count": markdown_metrics["chunk_marker_count"],
        },
        "postprocess": postprocess,
        "retrieval_hints": hints,
        "ingest_readiness": readiness,
        "sidecar_completeness": sidecars,
        "summary": {
            "markdown_chars": markdown_metrics["markdown_chars"],
            "markdown_bytes": markdown_metrics["markdown_bytes"],
            "markdown_lines": markdown_metrics["markdown_lines"],
            "local_image_file_count": artifacts["local_image_file_count"],
            "missing_local_image_reference_count": markdown_metrics["missing_local_image_reference_count"],
            "pandoc_artifact_count": markdown_metrics["pandoc_artifact_count"],
            "postprocess_rule_application_count": postprocess["total_rule_applications"],
            "quality_gate_status": quality["status"],
            "chunk_marker_count": markdown_metrics["chunk_marker_count"],
            "retrieval_hint_section_count": hints.get("section_boundary_count", 0),
            "retrieval_hint_preferred_boundary_count": hints.get("preferred_boundary_count", 0),
            "retrieval_hint_keyword_count": hints.get("keyword_candidate_count", 0),
            "retrieval_hint_question_count": hints.get("question_candidate_count", 0),
            "table_signal_count": table_signal_count,
            "image_signal_count": image_signal_count,
            "sidecar_completeness_ratio": sidecars["completeness_ratio"],
        },
    }
    return summary, normalized_text


def _comparison_ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(difflib.SequenceMatcher(None, left, right).ratio(), 4)


def _comparison_delta(replacement: Mapping[str, Any], retained: Mapping[str, Any], key: str) -> int | float | None:
    left = replacement.get(key)
    right = retained.get(key)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left - right
    return None


def _comparison_summary(summary: Mapping[str, Any], key: str) -> int:
    metrics = summary.get("summary") if isinstance(summary.get("summary"), Mapping) else {}
    return _comparison_int(metrics.get(key))


def _comparison_quality_gate_status(summary: Mapping[str, Any]) -> str:
    metrics = summary.get("summary") if isinstance(summary.get("summary"), Mapping) else {}
    value = metrics.get("quality_gate_status")
    return str(value) if value else "UNKNOWN"


def _comparison_postprocess_rule_counts(summary: Mapping[str, Any]) -> dict[str, int]:
    postprocess = summary.get("postprocess") if isinstance(summary.get("postprocess"), Mapping) else {}
    rule_counts = postprocess.get("rule_counts") if isinstance(postprocess.get("rule_counts"), Mapping) else {}
    return {str(key): _comparison_int(value) for key, value in rule_counts.items()}


def _comparison_quality_metrics(
    *,
    retained_summary: Mapping[str, Any],
    replacement_summary: Mapping[str, Any],
) -> dict[str, Any]:
    retained_bytes = _comparison_summary(retained_summary, "markdown_bytes")
    replacement_bytes = _comparison_summary(replacement_summary, "markdown_bytes")
    retained_chars = _comparison_summary(retained_summary, "markdown_chars")
    replacement_chars = _comparison_summary(replacement_summary, "markdown_chars")
    retained_artifacts = _comparison_summary(retained_summary, "pandoc_artifact_count")
    replacement_artifacts = _comparison_summary(replacement_summary, "pandoc_artifact_count")
    retained_missing_images = _comparison_summary(retained_summary, "missing_local_image_reference_count")
    replacement_missing_images = _comparison_summary(replacement_summary, "missing_local_image_reference_count")
    bytes_removed = retained_bytes - replacement_bytes
    chars_removed = retained_chars - replacement_chars
    return {
        "raw_markdown": {
            "markdown_bytes": retained_bytes,
            "markdown_chars": retained_chars,
            "pandoc_artifact_count": retained_artifacts,
            "missing_local_image_reference_count": retained_missing_images,
            "quality_gate_status": _comparison_quality_gate_status(retained_summary),
        },
        "cleaned_handoff": {
            "markdown_bytes": replacement_bytes,
            "markdown_chars": replacement_chars,
            "pandoc_artifact_count": replacement_artifacts,
            "missing_local_image_reference_count": replacement_missing_images,
            "quality_gate_status": _comparison_quality_gate_status(replacement_summary),
            "postprocess_rule_counts": _comparison_postprocess_rule_counts(replacement_summary),
        },
        "deltas": {
            "markdown_bytes_removed": bytes_removed,
            "markdown_chars_removed": chars_removed,
            "text_reduction_ratio": round(bytes_removed / retained_bytes, 6) if retained_bytes else 0.0,
            "pandoc_artifacts_removed": retained_artifacts - replacement_artifacts,
            "missing_local_images_repaired": retained_missing_images - replacement_missing_images,
        },
    }


def _nested_number(payload: Mapping[str, Any], keys: tuple[str, ...]) -> int | float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        for key in keys:
            value = summary.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
    metrics = payload.get("metrics")
    if isinstance(metrics, Mapping):
        for key in keys:
            value = metrics.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
    return None


def _nested_string(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        for key in keys:
            value = summary.get(key)
            if isinstance(value, str):
                return value
    return None


def _comparison_live_evidence_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"status": "not_provided"}
    return {
        "status": "provided",
        "schema": payload.get("schema"),
        "ok": payload.get("ok") if isinstance(payload.get("ok"), bool) else None,
        "parse_status": _nested_string(payload, ("parse_status", "document_parse_status", "status")),
        "chunk_count": _nested_number(payload, ("chunk_count", "total_chunk_count", "average_chunks")),
        "smoke_pass_rate": _nested_number(payload, ("smoke_pass_rate", "pass_rate", "hit_rate")),
        "empty_result_count": _nested_number(payload, ("empty_result_count", "empty_results")),
        "direct_query_success": _nested_string(payload, ("direct_query_success", "query_success")),
        "host_assisted_query_success": _nested_string(payload, ("host_assisted_query_success",)),
        "cleanup_status": _nested_string(payload, ("cleanup_status", "cleanup_result")),
    }


def _comparison_observations(
    *,
    retained_summary: Mapping[str, Any],
    replacement_summary: Mapping[str, Any],
    paired_live_ab_status: str,
    retained_live_evidence: Mapping[str, Any] | None,
) -> tuple[str, list[dict[str, str]]]:
    observations: list[dict[str, str]] = []
    severity_rank = {"info": 0, "warning": 1, "error": 2}

    def add(severity: str, code: str, message: str) -> None:
        observations.append({"severity": severity, "code": code, "message": message})

    replacement_quality = (
        replacement_summary.get("quality_gate", {}).get("status")
        if isinstance(replacement_summary.get("quality_gate"), Mapping)
        else None
    )
    retained_quality = (
        retained_summary.get("quality_gate", {}).get("status")
        if isinstance(retained_summary.get("quality_gate"), Mapping)
        else None
    )
    if replacement_quality == "BLOCKED":
        add("error", "replacement_quality_blocked", "replacement handoff quality gate is BLOCKED")
    elif retained_quality == "PASS" and replacement_quality not in {"PASS", "PASS_WITH_REVIEW"}:
        add("warning", "replacement_quality_not_pass", "retained package reports PASS but replacement quality is not clearly passable")

    retained_metrics = retained_summary.get("summary") if isinstance(retained_summary.get("summary"), Mapping) else {}
    replacement_metrics = replacement_summary.get("summary") if isinstance(replacement_summary.get("summary"), Mapping) else {}
    retained_markers = int(retained_metrics.get("chunk_marker_count", 0) or 0)
    replacement_markers = int(replacement_metrics.get("chunk_marker_count", 0) or 0)
    if retained_markers > replacement_markers:
        add(
            "info",
            "replacement_chunk_markers_less_dense",
            "retained package has denser chunk markers; treat this as a follow-up observation unless retrieval metrics regress",
        )
    retained_sidecars = float(retained_metrics.get("sidecar_completeness_ratio", 0) or 0)
    replacement_sidecars = float(replacement_metrics.get("sidecar_completeness_ratio", 0) or 0)
    if replacement_sidecars + 0.0001 < retained_sidecars:
        add("warning", "replacement_sidecars_less_complete", "replacement handoff has fewer expected sidecars than retained package")
    if paired_live_ab_status != "executed":
        add(
            "info",
            "strict_paired_live_ab_not_run",
            "strict paired live RAGFlow A/B was not run; static retained-package comparison is not live parity evidence",
        )
    elif not isinstance(retained_live_evidence, Mapping):
        add("warning", "paired_live_ab_evidence_missing", "paired live A/B is marked executed but retained-package live evidence was not provided")

    max_severity = max((severity_rank.get(item["severity"], 0) for item in observations), default=0)
    if max_severity >= severity_rank["error"]:
        status = "blocked"
    elif max_severity >= severity_rank["warning"]:
        status = "review_required"
    else:
        status = "no_critical_static_regression_detected"
    return status, observations


def make_handoff_comparison_payload(
    *,
    retained_package: str | Path,
    replacement_handoff: str | Path,
    paired_live_ab_status: str = "not_run",
    replacement_live_evidence: Mapping[str, Any] | None = None,
    retained_live_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare a retained legacy ingestion package with a replacement handoff.

    The comparison is read-only and static by default. It deliberately excludes retained
    intermediate directories and does not create, upload to, query, or delete RAGFlow KBs.
    """

    if paired_live_ab_status not in {"not_run", "executed"}:
        raise HandoffError("paired_live_ab_status must be 'not_run' or 'executed'")
    retained_root_input = Path(retained_package)
    replacement_root = Path(replacement_handoff)
    if not retained_root_input.is_dir():
        raise HandoffError(f"retained package directory not found: {retained_root_input}")
    if not replacement_root.is_dir():
        raise HandoffError(f"replacement handoff directory not found: {replacement_root}")

    retained_root, retained_effective_label = _comparison_retained_effective_root(retained_root_input)
    retained_summary, retained_text = _comparison_package_summary(
        root=retained_root,
        role="retained_package",
        ignored_dirs=COMPARISON_RETAINED_IGNORED_DIRS,
        effective_root_label=retained_effective_label,
    )
    replacement_summary, replacement_text = _comparison_package_summary(
        root=replacement_root,
        role="replacement_pipeline_handoff",
        ignored_dirs=set(),
        effective_root_label=".",
    )
    retained_metrics = retained_summary["summary"]
    replacement_metrics = replacement_summary["summary"]
    similarity = _comparison_ratio(retained_text, replacement_text)
    deltas = {
        key: _comparison_delta(replacement_metrics, retained_metrics, key)
        for key in (
            "markdown_chars",
            "markdown_bytes",
            "markdown_lines",
            "local_image_file_count",
            "missing_local_image_reference_count",
            "pandoc_artifact_count",
            "postprocess_rule_application_count",
            "chunk_marker_count",
            "retrieval_hint_section_count",
            "retrieval_hint_preferred_boundary_count",
            "retrieval_hint_keyword_count",
            "retrieval_hint_question_count",
            "table_signal_count",
            "image_signal_count",
            "sidecar_completeness_ratio",
        )
    }
    static_status, observations = _comparison_observations(
        retained_summary=retained_summary,
        replacement_summary=replacement_summary,
        paired_live_ab_status=paired_live_ab_status,
        retained_live_evidence=retained_live_evidence,
    )
    paired_live_ab = {
        "status": paired_live_ab_status,
        "executed": paired_live_ab_status == "executed",
        "requires_explicit_live_mutation_approval": True,
        "default_behavior": "not_run",
    }
    return {
        "schema": HANDOFF_COMPARISON_SCHEMA,
        "created_at": _now(),
        "report_type": "retained_package_static_comparison",
        "comparison_boundary": {
            "retained_package_static_comparison": True,
            "replacement_path_live_evidence": isinstance(replacement_live_evidence, Mapping),
            "strict_paired_live_ab": paired_live_ab,
            "notes": [
                "Retained package metrics are static package-to-package evidence.",
                "Paired live RAGFlow A/B requires separate explicit mutation approval and is not implied by this report.",
            ],
        },
        "inputs": {
            "retained_package": {
                "label": "retained_package",
                "scope": "explicit retained ingestion package root",
                "effective_root": retained_effective_label,
            },
            "replacement_handoff": {
                "label": "replacement_pipeline_handoff",
                "scope": "explicit ragflow-doc-to-md pipeline handoff root",
                "effective_root": ".",
            },
        },
        "static_comparison": {
            "status": static_status,
            "retained_package": retained_summary,
            "replacement_handoff": replacement_summary,
            "normalized_text": {
                "similarity": similarity,
                "retained_normalized_chars": len(retained_text),
                "replacement_normalized_chars": len(replacement_text),
                "normalization_steps": [
                    "removed chunk marker comments",
                    "collapsed blank lines and whitespace",
                    "normalized Markdown image link paths to <image>",
                ],
            },
            "quality_metrics": _comparison_quality_metrics(
                retained_summary=retained_summary,
                replacement_summary=replacement_summary,
            ),
            "deltas": deltas,
            "observations": observations,
        },
        "live_evidence": {
            "replacement_path": _comparison_live_evidence_summary(replacement_live_evidence),
            "retained_paired_path": _comparison_live_evidence_summary(retained_live_evidence),
            "paired_live_ab": paired_live_ab,
        },
        "safety": {
            "read_only": True,
            "live_ragflow_mutation": "not_performed",
            "script_owned_llm": "not_used",
            "scans_explicit_roots_only": True,
            "retained_intermediate_dirs_excluded": True,
            "retained_ignored_directory_names": sorted(COMPARISON_RETAINED_IGNORED_DIRS),
            "stores_api_credentials": False,
            "stores_ragflow_endpoint": False,
            "paths": "relative_package_paths_only",
        },
    }


def render_handoff_comparison_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown from a ragflow_handoff_comparison_v1 payload."""

    static = report.get("static_comparison") if isinstance(report.get("static_comparison"), Mapping) else {}
    retained = static.get("retained_package") if isinstance(static.get("retained_package"), Mapping) else {}
    replacement = static.get("replacement_handoff") if isinstance(static.get("replacement_handoff"), Mapping) else {}
    retained_summary = retained.get("summary") if isinstance(retained.get("summary"), Mapping) else {}
    replacement_summary = replacement.get("summary") if isinstance(replacement.get("summary"), Mapping) else {}
    normalized = static.get("normalized_text") if isinstance(static.get("normalized_text"), Mapping) else {}
    live = report.get("live_evidence") if isinstance(report.get("live_evidence"), Mapping) else {}
    paired = live.get("paired_live_ab") if isinstance(live.get("paired_live_ab"), Mapping) else {}
    lines = [
        "# RAGFlow Handoff Comparison",
        "",
        f"- schema: `{report.get('schema', HANDOFF_COMPARISON_SCHEMA)}`",
        f"- report_type: `{report.get('report_type', 'retained_package_static_comparison')}`",
        f"- static_status: `{static.get('status', 'unknown')}`",
        f"- normalized_text_similarity: {normalized.get('similarity', 'unknown')}",
        f"- paired_live_ab: `{paired.get('status', 'not_run')}`",
        "",
        "## Static Metrics",
        "",
        "| Metric | Retained package | Replacement handoff | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    deltas = static.get("deltas") if isinstance(static.get("deltas"), Mapping) else {}
    metric_labels = [
        ("markdown_chars", "Markdown chars"),
        ("markdown_bytes", "Markdown bytes"),
        ("markdown_lines", "Markdown lines"),
        ("local_image_file_count", "Local image files"),
        ("missing_local_image_reference_count", "Missing local images"),
        ("pandoc_artifact_count", "Pandoc artifacts"),
        ("postprocess_rule_application_count", "Postprocess rule applications"),
        ("chunk_marker_count", "Chunk markers"),
        ("retrieval_hint_section_count", "Hint sections"),
        ("retrieval_hint_preferred_boundary_count", "Preferred boundaries"),
        ("retrieval_hint_keyword_count", "Keyword candidates"),
        ("retrieval_hint_question_count", "Question candidates"),
        ("table_signal_count", "Table signals"),
        ("image_signal_count", "Image signals"),
        ("sidecar_completeness_ratio", "Sidecar completeness"),
    ]
    for key, label in metric_labels:
        lines.append(
            f"| {label} | {retained_summary.get(key, 0)} | {replacement_summary.get(key, 0)} | {deltas.get(key, '')} |"
        )
    quality_metrics = static.get("quality_metrics") if isinstance(static.get("quality_metrics"), Mapping) else {}
    raw_metrics = quality_metrics.get("raw_markdown") if isinstance(quality_metrics.get("raw_markdown"), Mapping) else {}
    cleaned_metrics = quality_metrics.get("cleaned_handoff") if isinstance(quality_metrics.get("cleaned_handoff"), Mapping) else {}
    quality_deltas = quality_metrics.get("deltas") if isinstance(quality_metrics.get("deltas"), Mapping) else {}
    if quality_metrics:
        lines.extend(
            [
                "",
                "## Cleanup Quality Metrics",
                "",
                f"- raw_quality_gate_status: `{raw_metrics.get('quality_gate_status', 'UNKNOWN')}`",
                f"- cleaned_quality_gate_status: `{cleaned_metrics.get('quality_gate_status', 'UNKNOWN')}`",
                f"- markdown_bytes_removed: {quality_deltas.get('markdown_bytes_removed', 0)}",
                f"- text_reduction_ratio: {quality_deltas.get('text_reduction_ratio', 0)}",
                f"- pandoc_artifacts_removed: {quality_deltas.get('pandoc_artifacts_removed', 0)}",
                f"- missing_local_images_repaired: {quality_deltas.get('missing_local_images_repaired', 0)}",
            ]
        )
    lines.extend(["", "## Live Evidence", ""])
    replacement_live = live.get("replacement_path") if isinstance(live.get("replacement_path"), Mapping) else {}
    retained_live = live.get("retained_paired_path") if isinstance(live.get("retained_paired_path"), Mapping) else {}
    lines.extend(
        [
            f"- replacement_path: `{replacement_live.get('status', 'not_provided')}`",
            f"- retained_paired_path: `{retained_live.get('status', 'not_provided')}`",
            f"- strict_paired_live_ab_executed: {str(bool(paired.get('executed'))).lower()}",
            "",
        ]
    )
    observations = static.get("observations") if isinstance(static.get("observations"), list) else []
    if observations:
        lines.extend(["## Observations", ""])
        for item in observations:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"- `{item.get('code')}` ({item.get('severity')}): {item.get('message')}")
        lines.append("")
    lines.extend(
        [
            "## Safety",
            "",
            "- read_only: true",
            "- live_ragflow_mutation: `not_performed`",
            "- retained_intermediate_dirs_excluded: true",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


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
    ingest_readiness_name: str = "ingest_readiness_report.json",
    ingest_readiness_md_name: str | None = "ingest_readiness_report.md",
    formal_handoff_manifest_name: str = "formal_handoff_manifest.json",
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
    layout_sidecars, layout_signals = _load_optional_layout_sidecars(root)
    artifact_index["asset_semantics"] = make_asset_semantics_payload(
        handoff_root=root,
        metadata=metadata,
        artifact_index=artifact_index,
        layout_sidecars=layout_sidecars,
        layout_signals=layout_signals,
    )
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
        ingest_readiness_name=ingest_readiness_name,
        ingest_readiness_md_name=ingest_readiness_md_name,
        formal_handoff_manifest_name=formal_handoff_manifest_name,
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
    ingest_readiness = write_doc_ingest_readiness_report(
        handoff_root=root,
        doc_manifest_name=doc_manifest_name,
        ingest_readiness_name=ingest_readiness_name,
        ingest_readiness_md_name=ingest_readiness_md_name,
        sidecar_names={
            "metadata": metadata_name,
            "artifact_index": artifact_index_name,
            "profile_suggestions": profile_suggestions_name,
            "retrieval_hints": retrieval_hints_name,
            "assistant_profile": assistant_profile_name,
            "assistant_test_plan": assistant_test_plan_name,
            "package_readme": package_readme_name,
            "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
        },
    )
    formal_handoff_manifest = write_formal_handoff_manifest(
        handoff_root=root,
        doc_manifest_name=doc_manifest_name,
        formal_handoff_manifest_name=formal_handoff_manifest_name,
        sidecar_names={
            "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
            "metadata": metadata_name,
            "artifact_index": artifact_index_name,
            "profile_suggestions": profile_suggestions_name,
            "retrieval_hints": retrieval_hints_name,
            "assistant_profile": assistant_profile_name,
            "assistant_test_plan": assistant_test_plan_name,
            "ingest_readiness": ingest_readiness_name,
            "ingest_readiness_md": ingest_readiness_md_name,
            "package_readme": package_readme_name,
        },
    )

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
        "ingest_readiness": ingest_readiness_name,
        "ingest_readiness_md": ingest_readiness_md_name,
        "formal_handoff_manifest": formal_handoff_manifest_name,
        "package_readme": package_readme_name,
        "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
        "document_count": len(metadata["documents"]),
        "artifact_count": artifact_index["artifact_count"],
        "asset_semantic_count": artifact_index["asset_semantics"]["summary"]["image_count"],
        "ingest_readiness_status": ingest_readiness["status"],
        "ingest_readiness_score": ingest_readiness["advisory_score"],
        "formal_handoff_manifest_schema": formal_handoff_manifest["schema"],
        "formal_handoff_package_hash": formal_handoff_manifest["package_hash"],
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
        "ingest_readiness": package.get("ingest_readiness", "ingest_readiness_report.json"),
        "ingest_readiness_md": package.get("ingest_readiness_md", "ingest_readiness_report.md"),
        "formal_handoff_manifest": package.get("formal_handoff_manifest", "formal_handoff_manifest.json"),
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
        "ingest_readiness_report": ("ingest_readiness_report.json", "rich"),
        "ingest_readiness_report_md": ("ingest_readiness_report.md", "rich"),
        "formal_handoff_manifest": ("formal_handoff_manifest.json", "rich"),
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
    recomputed_readiness = make_doc_ingest_readiness_payload(handoff_root=root, doc_manifest_name=doc_manifest_name)
    readiness_report_path = root / "ingest_readiness_report.json"
    stored_readiness = _read_json_if_file(readiness_report_path)
    stored_status = stored_readiness.get("status") if isinstance(stored_readiness, Mapping) else None
    readiness_status = str(recomputed_readiness.get("status") or "ready_with_review")
    readiness_issues = (
        recomputed_readiness.get("issues")
        if isinstance(recomputed_readiness.get("issues"), list)
        else []
    )
    readiness_checks = (
        recomputed_readiness.get("checks")
        if isinstance(recomputed_readiness.get("checks"), Mapping)
        else {}
    )
    formal_manifest_path = root / "formal_handoff_manifest.json"
    formal_manifest = _read_json_if_file(formal_manifest_path)

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
        "ingest_readiness_report": {
            "path": "ingest_readiness_report.json",
            "exists": readiness_report_path.is_file(),
            "schema": stored_readiness.get("schema") if isinstance(stored_readiness, Mapping) else None,
            "declared_status": stored_status,
            "recomputed_status": readiness_status,
            "matches_recomputed_status": stored_status == readiness_status if stored_status else False,
        },
        "formal_handoff_manifest": {
            "path": "formal_handoff_manifest.json",
            "exists": formal_manifest_path.is_file(),
            "schema": formal_manifest.get("schema") if isinstance(formal_manifest, Mapping) else None,
            "package_hash": formal_manifest.get("package_hash") if isinstance(formal_manifest, Mapping) else None,
            "generated_sidecar_count": formal_manifest.get("generated_sidecar_count")
            if isinstance(formal_manifest, Mapping)
            else None,
        },
        "ingestion_readiness": {
            "status": readiness_status,
            "quality_gate_allows_build": (
                readiness_checks.get("quality_gate", {}).get("allows_build")
                if isinstance(readiness_checks.get("quality_gate"), Mapping)
                else quality_status in {"PASS", "PASS_WITH_REVIEW"}
            ),
            "image_assets_ok": (
                readiness_checks.get("local_assets", {}).get("ok")
                if isinstance(readiness_checks.get("local_assets"), Mapping)
                else image_assets["ok"]
            ),
            "rich_sidecars_complete": (
                readiness_checks.get("sidecar_completeness", {}).get("rich_complete")
                if isinstance(readiness_checks.get("sidecar_completeness"), Mapping)
                else not missing_rich_sidecars
            ),
            "pipeline_sidecars_complete": (
                readiness_checks.get("sidecar_completeness", {}).get("pipeline_complete")
                if isinstance(readiness_checks.get("sidecar_completeness"), Mapping)
                else not missing_pipeline_sidecars
            ),
            "advisory_score": recomputed_readiness.get("advisory_score"),
            "report_matches_recomputed_status": stored_status == readiness_status if stored_status else False,
            "issues": readiness_issues,
            "checks": readiness_checks,
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
    readiness = report.get("ingestion_readiness", {}) if isinstance(report.get("ingestion_readiness"), Mapping) else {}
    readiness_report = (
        report.get("ingest_readiness_report")
        if isinstance(report.get("ingest_readiness_report"), Mapping)
        else {}
    )
    formal_manifest = (
        report.get("formal_handoff_manifest")
        if isinstance(report.get("formal_handoff_manifest"), Mapping)
        else {}
    )
    lines.extend(
        [
            f"- Readiness report exists: {str(bool(readiness_report.get('exists'))).lower()}",
            f"- Readiness report status matches review: {str(bool(readiness_report.get('matches_recomputed_status'))).lower()}",
            f"- Formal handoff manifest exists: {str(bool(formal_manifest.get('exists'))).lower()}",
            f"- Formal handoff package hash: `{formal_manifest.get('package_hash') or 'unknown'}`",
            f"- Advisory score: {readiness.get('advisory_score', 'unknown')}",
            f"- Rich sidecars complete: {str(bool(sidecar_summary.get('rich_complete'))).lower()}",
            f"- Pipeline sidecars complete: {str(bool(sidecar_summary.get('pipeline_complete'))).lower()}",
            f"- Missing image assets: {images.get('missing_image_count', 'unknown')}",
            "",
        ]
    )
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
