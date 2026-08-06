"""Document handoff quality reports for doc-to-md outputs."""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .html_tables import parse_html_tables


QUALITY_REPORT_SCHEMA = "doc_quality_report_v1"
PASS = "PASS"
PASS_WITH_REVIEW = "PASS_WITH_REVIEW"
BLOCKED = "BLOCKED"

IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
HTML_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
HTML_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
HTML_TABLE_CLOSE_RE = re.compile(r"</table\s*>", re.IGNORECASE)
CHUNK_MARKER_RE = re.compile(r"<!--\s*chunk\s*-->", re.IGNORECASE)
PAGE_MARKER_RE = re.compile(r"(?im)<!--\s*page\b|^\s*(?:page|p\.)\s+\d+\s*$|\f")
MATH_MARKER_RE = re.compile(r"(?<!\\)(?:\$\$|\$)|\\\(|\\\)|\\\[|\\\]")
PDF_SOURCE_EXTENSIONS = {".pdf"}
TABULAR_SOURCE_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx"}
PAGE_SIGNAL_LOW_CHAR_THRESHOLD = 24
GARBLED_REPLACEMENT_RATIO_THRESHOLD = 0.05
GARBLED_CONTROL_RATIO_THRESHOLD = 0.02
TABLE_HEAVY_TABLE_COUNT_THRESHOLD = 3
TABLE_HEAVY_CELL_COUNT_THRESHOLD = 50
TABLE_HEAVY_CHAR_RATIO_THRESHOLD = 0.25


class DocQualityError(RuntimeError):
    """Raised when a quality report cannot be produced."""


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    issue_type: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": self.severity,
            "issue_type": self.issue_type,
            "message": self.message,
        }
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class QualityDocument:
    source_path: str
    markdown_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityDocumentReport:
    source_path: str
    markdown_path: str
    status: str
    issues: list[QualityIssue]
    char_count: int = 0
    image_count: int = 0
    line_count: int = 0
    non_empty_line_count: int = 0
    heading_count: int = 0
    table_count: int = 0
    markdown_table_count: int = 0
    html_table_count: int = 0
    html_table_review_warning_count: int = 0
    formula_marker_count: int = 0
    page_marker_count: int = 0
    replacement_char_count: int = 0
    control_char_count: int = 0
    replacement_char_ratio: float = 0.0
    control_char_ratio: float = 0.0
    table_source_counts: dict[str, int] = field(default_factory=dict)
    table_fingerprints: list[dict[str, Any]] = field(default_factory=list)
    chunk_marker_table_atomicity: dict[str, Any] = field(default_factory=dict)
    table_heavy_document: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "markdown_path": self.markdown_path,
            "status": self.status,
            "char_count": self.char_count,
            "image_count": self.image_count,
            "quality_signals": {
                "line_count": self.line_count,
                "non_empty_line_count": self.non_empty_line_count,
                "heading_count": self.heading_count,
                "table_count": self.table_count,
                "markdown_table_count": self.markdown_table_count,
                "html_table_count": self.html_table_count,
                "html_table_review_warning_count": self.html_table_review_warning_count,
                "formula_marker_count": self.formula_marker_count,
                "page_marker_count": self.page_marker_count,
                "replacement_char_count": self.replacement_char_count,
                "control_char_count": self.control_char_count,
                "replacement_char_ratio": self.replacement_char_ratio,
                "control_char_ratio": self.control_char_ratio,
                "table_source_counts": self.table_source_counts,
                "table_fingerprints": self.table_fingerprints,
                "chunk_marker_table_atomicity": self.chunk_marker_table_atomicity,
                "table_heavy_document": self.table_heavy_document,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_remote_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
        or lowered.startswith("#")
    )


def _image_reference_path(raw: str) -> str:
    value = raw.strip().strip("<>")
    if " " in value and not value.startswith(("./", "../", "/")):
        value = value.split(" ", 1)[0]
    return value


def _document_status(issues: list[QualityIssue]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return BLOCKED
    if any(issue.severity == "warning" for issue in issues):
        return PASS_WITH_REVIEW
    return PASS


def _report_status(reports: list[QualityDocumentReport]) -> str:
    if any(report.status == BLOCKED for report in reports):
        return BLOCKED
    if any(report.status == PASS_WITH_REVIEW for report in reports):
        return PASS_WITH_REVIEW
    return PASS


def _source_suffix(source_path: str) -> str:
    return Path(str(source_path)).suffix.lower()


def _count_tables(lines: list[str]) -> int:
    count = 0
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        if TABLE_SEPARATOR_RE.match(lines[index + 1]):
            count += 1
    return count


def _html_table_blocks(text: str) -> list[str]:
    return [match.group(0) for match in HTML_TABLE_BLOCK_RE.finditer(text)]


def _html_table_fingerprint(block: str) -> str:
    normalized = block.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _table_char_ratio(text: str, blocks: list[str]) -> float:
    denominator = max(len(text), 1)
    return round(sum(len(block) for block in blocks) / denominator, 6)


def _chunk_marker_table_atomicity(text: str) -> dict[str, Any]:
    markers = CHUNK_MARKER_RE.findall(text)
    fragments = CHUNK_MARKER_RE.split(text)
    marker_inside_table_count = sum(len(CHUNK_MARKER_RE.findall(block)) for block in _html_table_blocks(text))
    unbalanced_fragments: list[dict[str, int]] = []
    for index, fragment in enumerate(fragments):
        open_count = len(HTML_TABLE_OPEN_RE.findall(fragment))
        close_count = len(HTML_TABLE_CLOSE_RE.findall(fragment))
        if open_count != close_count:
            unbalanced_fragments.append(
                {
                    "fragment_index": index,
                    "html_table_open_count": open_count,
                    "html_table_close_count": close_count,
                }
            )
    return {
        "delimiter": "`<!-- chunk -->`",
        "chunk_marker_count": len(markers),
        "marker_inside_table_count": marker_inside_table_count,
        "fragment_count": len(fragments),
        "unbalanced_fragment_count": len(unbalanced_fragments),
        "unbalanced_fragments": unbalanced_fragments[:20],
        "ok": marker_inside_table_count == 0 and not unbalanced_fragments,
    }


def _content_list_table_count(*, markdown_path: Path, output_root: Path) -> int:
    candidates = []
    for base in (output_root, markdown_path.parent, markdown_path.parent.parent):
        candidates.extend((base / "content_list.json", base / "mineru_content_list.json"))
    seen: set[Path] = set()
    count = 0
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        count += _count_table_like_content_items(payload)
    return count


def _count_table_like_content_items(value: Any) -> int:
    if isinstance(value, list):
        return sum(_count_table_like_content_items(item) for item in value)
    if not isinstance(value, Mapping):
        return 0
    type_text = " ".join(
        str(value.get(key) or "")
        for key in ("type", "category", "kind", "semantic_kind")
    ).lower()
    count = 1 if "table" in type_text else 0
    for key in ("children", "items", "content"):
        count += _count_table_like_content_items(value.get(key))
    return count


def _table_fingerprint_records(text: str, html_tables: list[Any]) -> list[dict[str, Any]]:
    blocks = _html_table_blocks(text)
    records: list[dict[str, Any]] = []
    for index, table in enumerate(html_tables, start=1):
        block = blocks[index - 1] if index <= len(blocks) else ""
        record = {
            "index": index,
            "sha256": _html_table_fingerprint(block) if block else None,
            "line_start": table.line_start,
            "line_end": table.line_end,
            "row_count": table.row_count,
            "column_count": table.column_count,
            "cell_count": table.cell_count,
            "rowspan_count": table.rowspan_count,
            "colspan_count": table.colspan_count,
            "caption_preview": table.caption,
            "header_preview": table.header_preview,
            "warnings": list(table.warnings),
        }
        records.append(record)
    return records


def _count_control_chars(text: str) -> int:
    allowed = {"\n", "\r", "\t"}
    return sum(1 for char in text if ord(char) < 32 and char not in allowed)


def _math_delimiters_unbalanced(text: str) -> bool:
    unescaped_dollars = len(re.findall(r"(?<!\\)\$", text))
    return (
        unescaped_dollars % 2 == 1
        or text.count(r"\(") != text.count(r"\)")
        or text.count(r"\[") != text.count(r"\]")
    )


def inspect_quality_document(document: QualityDocument, *, output_root: str | Path) -> QualityDocumentReport:
    """Inspect one converted Markdown document for handoff quality."""

    output_root_path = Path(output_root)
    markdown_path = Path(document.markdown_path)
    issues = [
        QualityIssue(
            severity="warning",
            issue_type="conversion_warning",
            message=warning,
            path=_relative(markdown_path, output_root_path),
        )
        for warning in document.warnings
        if warning
    ]
    char_count = 0
    image_count = 0
    line_count = 0
    non_empty_line_count = 0
    heading_count = 0
    table_count = 0
    markdown_table_count = 0
    html_table_count = 0
    html_table_review_warning_count = 0
    formula_marker_count = 0
    page_marker_count = 0
    replacement_char_count = 0
    control_char_count = 0
    replacement_char_ratio = 0.0
    control_char_ratio = 0.0
    table_source_counts: dict[str, int] = {
        "markdown_table_count": 0,
        "html_table_count": 0,
        "content_list_table_count": 0,
        "total_source_table_count": 0,
    }
    table_fingerprints: list[dict[str, Any]] = []
    chunk_marker_table_atomicity: dict[str, Any] = {
        "delimiter": "`<!-- chunk -->`",
        "chunk_marker_count": 0,
        "marker_inside_table_count": 0,
        "fragment_count": 1,
        "unbalanced_fragment_count": 0,
        "unbalanced_fragments": [],
        "ok": True,
    }
    table_heavy_document = False

    if not markdown_path.exists():
        issues.append(
            QualityIssue(
                severity="error",
                issue_type="markdown_missing",
                message=f"markdown file is missing: {markdown_path}",
                path=_relative(markdown_path, output_root_path),
            )
        )
        return QualityDocumentReport(
            source_path=document.source_path,
            markdown_path=_relative(markdown_path, output_root_path),
            status=BLOCKED,
            issues=issues,
        )

    if not markdown_path.is_file():
        issues.append(
            QualityIssue(
                severity="error",
                issue_type="markdown_not_file",
                message=f"markdown path is not a file: {markdown_path}",
                path=_relative(markdown_path, output_root_path),
            )
        )
        return QualityDocumentReport(
            source_path=document.source_path,
            markdown_path=_relative(markdown_path, output_root_path),
            status=BLOCKED,
            issues=issues,
        )

    try:
        text = markdown_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = markdown_path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        issues.append(
            QualityIssue(
                severity="warning",
                issue_type="markdown_encoding",
                message="markdown was not valid UTF-8 and was decoded with replacement characters",
                path=_relative(markdown_path, output_root_path),
            )
        )

    char_count = len(text.strip())
    lines = text.splitlines()
    line_count = len(lines)
    non_empty_line_count = sum(1 for line in lines if line.strip())
    heading_count = sum(1 for line in lines if line.lstrip().startswith("#"))
    markdown_table_count = _count_tables(lines)
    html_tables = parse_html_tables(text)
    html_table_blocks = _html_table_blocks(text)
    html_table_count = len(html_tables)
    html_table_review_warning_count = sum(1 for table in html_tables if table.warnings)
    content_list_table_count = _content_list_table_count(markdown_path=markdown_path, output_root=output_root_path)
    table_count = markdown_table_count + html_table_count
    table_source_counts = {
        "markdown_table_count": markdown_table_count,
        "html_table_count": html_table_count,
        "content_list_table_count": content_list_table_count,
        "total_source_table_count": markdown_table_count + html_table_count + content_list_table_count,
    }
    table_fingerprints = _table_fingerprint_records(text, html_tables)
    chunk_marker_table_atomicity = _chunk_marker_table_atomicity(text)
    max_html_cell_count = max((int(record.get("cell_count") or 0) for record in table_fingerprints), default=0)
    table_heavy_document = (
        table_count >= TABLE_HEAVY_TABLE_COUNT_THRESHOLD
        or max_html_cell_count >= TABLE_HEAVY_CELL_COUNT_THRESHOLD
        or _table_char_ratio(text, html_table_blocks) >= TABLE_HEAVY_CHAR_RATIO_THRESHOLD
    )
    formula_marker_count = len(MATH_MARKER_RE.findall(text))
    page_marker_count = len(PAGE_MARKER_RE.findall(text))
    replacement_char_count = text.count("\ufffd")
    control_char_count = _count_control_chars(text)
    denominator = max(len(text), 1)
    replacement_char_ratio = round(replacement_char_count / denominator, 6)
    control_char_ratio = round(control_char_count / denominator, 6)

    if char_count == 0:
        issues.append(
            QualityIssue(
                severity="error",
                issue_type="markdown_empty",
                message="markdown content is empty",
                path=_relative(markdown_path, output_root_path),
            )
        )
    else:
        source_suffix = _source_suffix(document.source_path)
        if (
            source_suffix in PDF_SOURCE_EXTENSIONS
            and char_count < PAGE_SIGNAL_LOW_CHAR_THRESHOLD
            and page_marker_count == 0
        ):
            issues.append(
                QualityIssue(
                    severity="warning",
                    issue_type="page_signal_low",
                    message="converted PDF Markdown has very little content and no page markers; verify page coverage",
                    path=_relative(markdown_path, output_root_path),
                )
            )
        if (
            replacement_char_ratio >= GARBLED_REPLACEMENT_RATIO_THRESHOLD
            or control_char_ratio >= GARBLED_CONTROL_RATIO_THRESHOLD
        ):
            issues.append(
                QualityIssue(
                    severity="error",
                    issue_type="garbled_text_high_ratio",
                    message="markdown contains a high ratio of replacement or control characters",
                    path=_relative(markdown_path, output_root_path),
                )
            )
        if source_suffix in TABULAR_SOURCE_EXTENSIONS and table_count == 0:
            issues.append(
                QualityIssue(
                    severity="warning",
                    issue_type="table_structure_missing",
                    message="tabular source converted without Markdown table structure; verify table extraction",
                    path=_relative(markdown_path, output_root_path),
                )
            )
        for table_index, table in enumerate(html_tables, start=1):
            for warning in table.warnings:
                issues.append(
                    QualityIssue(
                        severity="warning",
                        issue_type=f"html_table_{warning}",
                        message=(
                            f"HTML table {table_index} has review warning {warning}; "
                            "verify table extraction before formal ingestion"
                        ),
                        path=_relative(markdown_path, output_root_path),
                    )
                )
        if int(chunk_marker_table_atomicity.get("marker_inside_table_count", 0) or 0) > 0:
            issues.append(
                QualityIssue(
                    severity="warning",
                    issue_type="chunk_marker_inside_html_table",
                    message="chunk marker appears inside an HTML table; verify table atomicity before formal ingestion",
                    path=_relative(markdown_path, output_root_path),
                )
            )
        if int(chunk_marker_table_atomicity.get("unbalanced_fragment_count", 0) or 0) > 0:
            issues.append(
                QualityIssue(
                    severity="warning",
                    issue_type="chunk_marker_unbalanced_html_table_fragment",
                    message="chunk markers split HTML table open/close tags across fragments; verify table reconstruction",
                    path=_relative(markdown_path, output_root_path),
                )
            )
        if _math_delimiters_unbalanced(text):
            issues.append(
                QualityIssue(
                    severity="warning",
                    issue_type="formula_suspicious_unbalanced_delimiter",
                    message="markdown contains unbalanced math delimiters; verify formula extraction",
                    path=_relative(markdown_path, output_root_path),
                )
            )

    for match in IMAGE_RE.finditer(text):
        raw_ref = _image_reference_path(match.group(1))
        if not raw_ref:
            continue
        image_count += 1
        if _is_remote_reference(raw_ref):
            continue
        image_path = Path(raw_ref)
        if not image_path.is_absolute():
            image_path = markdown_path.parent / image_path
        if not image_path.exists():
            issues.append(
                QualityIssue(
                    severity="error",
                    issue_type="image_missing",
                    message=f"local image is missing: {raw_ref}",
                    path=_relative(markdown_path, output_root_path),
                )
            )

    return QualityDocumentReport(
        source_path=document.source_path,
        markdown_path=_relative(markdown_path, output_root_path),
        status=_document_status(issues),
        issues=issues,
        char_count=char_count,
        image_count=image_count,
        line_count=line_count,
        non_empty_line_count=non_empty_line_count,
        heading_count=heading_count,
        table_count=table_count,
        markdown_table_count=markdown_table_count,
        html_table_count=html_table_count,
        html_table_review_warning_count=html_table_review_warning_count,
        formula_marker_count=formula_marker_count,
        page_marker_count=page_marker_count,
        replacement_char_count=replacement_char_count,
        control_char_count=control_char_count,
        replacement_char_ratio=replacement_char_ratio,
        control_char_ratio=control_char_ratio,
        table_source_counts=table_source_counts,
        table_fingerprints=table_fingerprints,
        chunk_marker_table_atomicity=chunk_marker_table_atomicity,
        table_heavy_document=table_heavy_document,
    )


def make_quality_report_payload(
    *,
    output_root: str | Path,
    documents: list[QualityDocument],
) -> dict[str, Any]:
    """Create a quality report payload for a converted handoff."""

    reports = [inspect_quality_document(document, output_root=output_root) for document in documents]
    issue_counts = {"error": 0, "warning": 0, "info": 0}
    for report in reports:
        for issue in report.issues:
            issue_counts[issue.severity] = issue_counts.get(issue.severity, 0) + 1
    status = _report_status(reports)
    return {
        "schema": QUALITY_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate": {
            "status": status,
            "manual_review_required": status in {PASS_WITH_REVIEW, BLOCKED},
            "summary": {
                "documents": len(reports),
                "errors": issue_counts.get("error", 0),
                "warnings": issue_counts.get("warning", 0),
                "infos": issue_counts.get("info", 0),
            },
        },
        "documents": [report.to_dict() for report in reports],
    }


def quality_documents_from_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str | Path,
) -> tuple[Path, list[QualityDocument]]:
    """Build quality inputs from a doc_manifest payload."""

    manifest_file = Path(manifest_path)
    manifest_root = manifest_file.parent
    source_root = manifest.get("source_root") or "."
    base = Path(str(source_root))
    if not base.is_absolute():
        base = manifest_root / base
    raw_documents = manifest.get("documents", [])
    if not isinstance(raw_documents, list) or not raw_documents:
        raise DocQualityError("doc manifest must include a non-empty documents list")
    documents: list[QualityDocument] = []
    for index, item in enumerate(raw_documents):
        if not isinstance(item, Mapping):
            raise DocQualityError(f"documents[{index}] must be an object")
        markdown_path = item.get("markdown_path")
        source_path = item.get("source_path")
        if not isinstance(markdown_path, str) or not markdown_path:
            raise DocQualityError(f"documents[{index}].markdown_path is required")
        path = Path(markdown_path)
        if not path.is_absolute():
            path = base / path
        warnings = item.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        documents.append(
            QualityDocument(
                source_path=str(source_path or markdown_path),
                markdown_path=path,
                warnings=[str(warning) for warning in warnings if str(warning)],
            )
        )
    return base, documents


def load_doc_manifest_payload(path: str | Path) -> dict[str, Any]:
    """Load a doc manifest JSON object for quality inspection."""

    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DocQualityError(f"doc manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise DocQualityError(f"doc manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(data, dict):
        raise DocQualityError("doc manifest must be a JSON object")
    return data


def render_quality_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown quality report."""

    gate = report.get("gate", {}) if isinstance(report.get("gate"), Mapping) else {}
    summary = gate.get("summary", {}) if isinstance(gate.get("summary"), Mapping) else {}
    lines = [
        "# Document Quality Report",
        "",
        f"- Status: `{gate.get('status', 'UNKNOWN')}`",
        f"- Documents: {summary.get('documents', 0)}",
        f"- Errors: {summary.get('errors', 0)}",
        f"- Warnings: {summary.get('warnings', 0)}",
        "",
    ]
    for document in report.get("documents", []) if isinstance(report.get("documents"), list) else []:
        if not isinstance(document, Mapping):
            continue
        lines.extend(
            [
                f"## {document.get('markdown_path', 'document')}",
                "",
                f"- Status: `{document.get('status', 'UNKNOWN')}`",
                f"- Source: `{document.get('source_path', '')}`",
                f"- Characters: {document.get('char_count', 0)}",
                f"- Images: {document.get('image_count', 0)}",
                "",
            ]
        )
        signals = document.get("quality_signals", {})
        if isinstance(signals, Mapping):
            lines.extend(
                [
                    f"- Tables: {signals.get('table_count', 0)}",
                    f"- Markdown tables: {signals.get('markdown_table_count', signals.get('table_count', 0))}",
                    f"- HTML tables: {signals.get('html_table_count', 0)}",
                    f"- Table heavy document: `{signals.get('table_heavy_document', False)}`",
                    "- Chunk marker table atomicity: "
                    f"`{(signals.get('chunk_marker_table_atomicity') or {}).get('ok', True)}`",
                    f"- Formula markers: {signals.get('formula_marker_count', 0)}",
                    f"- Page markers: {signals.get('page_marker_count', 0)}",
                    f"- Replacement char ratio: {signals.get('replacement_char_ratio', 0)}",
                    "",
                ]
            )
        issues = document.get("issues", [])
        if isinstance(issues, list) and issues:
            for issue in issues:
                if isinstance(issue, Mapping):
                    lines.append(
                        f"- `{issue.get('severity', 'info')}` `{issue.get('issue_type', 'issue')}`: "
                        f"{issue.get('message', '')}"
                    )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
