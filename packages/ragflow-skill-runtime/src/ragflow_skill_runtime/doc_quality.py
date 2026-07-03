"""Document handoff quality reports for doc-to-md outputs."""

from __future__ import annotations

import json
import re
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
PAGE_MARKER_RE = re.compile(r"(?im)<!--\s*page\b|^\s*(?:page|p\.)\s+\d+\s*$|\f")
MATH_MARKER_RE = re.compile(r"(?<!\\)(?:\$\$|\$)|\\\(|\\\)|\\\[|\\\]")
PDF_SOURCE_EXTENSIONS = {".pdf"}
TABULAR_SOURCE_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx"}
PAGE_SIGNAL_LOW_CHAR_THRESHOLD = 24
GARBLED_REPLACEMENT_RATIO_THRESHOLD = 0.05
GARBLED_CONTROL_RATIO_THRESHOLD = 0.02


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
    html_table_count = len(html_tables)
    html_table_review_warning_count = sum(1 for table in html_tables if table.warnings)
    table_count = markdown_table_count + html_table_count
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
