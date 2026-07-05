"""Lightweight source inspection for adaptive document conversion."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .doc_convert import (
    BUILTIN_EXTENSIONS,
    HTML_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MARKDOWN_EXTENSIONS,
    MINERU_AUTO_EXTENSIONS,
    PANDOC_AUTO_EXTENSIONS,
    TEXT_EXTENSIONS,
    DocConvertError,
    discover_source_documents,
    sha256_file,
)
from .html_tables import parse_html_tables


DOCUMENT_FEATURES_SCHEMA = "ragflow_document_features_v1"

FORMAL_SOURCE_EXTENSIONS = MINERU_AUTO_EXTENSIONS | PANDOC_AUTO_EXTENSIONS | {".pdf"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf"}
PDF_EXTENSIONS = {".pdf"}

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*?\bsrc=[\"'][^\"']+[\"']", re.IGNORECASE)
MATH_OR_UNIT_RE = re.compile(r"[%℃°μµ]|(?:\b(?:mm|cm|kg|g|nm|um|μm|v|kw|rpm|nm)\b)", re.IGNORECASE)
MOJIBAKE_RE = re.compile(r"[ÃÂÊËÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_text_sample(path: Path, *, max_chars: int) -> tuple[str, str | None]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars], None
    except OSError as exc:
        return "", str(exc)


def _binary_pdf_features(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        data = path.read_bytes()[:max_bytes]
    except OSError as exc:
        return {"pdf_probe_error": str(exc), "page_count_estimate": None, "sample_text": ""}
    text = data.decode("latin-1", errors="ignore")
    page_count = len(re.findall(r"/Type\s*/Page\b", text))
    # This is intentionally conservative; real text extraction belongs to conversion.
    candidates = re.findall(r"\(([^()\x00-\x08\x0b\x0c\x0e-\x1f]{4,})\)", text)
    sample = " ".join(item.strip() for item in candidates if item.strip())[:4000]
    # Heuristic: if the PDF is large enough to be more than a trivial text doc and
    # extracted stream text is mostly short or non-UTF8, treat as scanned/low-text.
    sample_bytes_len = len(sample.encode("utf-8", errors="ignore"))
    data_len = len(data)
    density = sample_bytes_len / max(data_len, 1)
    printable_count = sum(1 for char in sample if char.isprintable() or char.isspace())
    printable_ratio = printable_count / max(len(sample), 1)
    mojibake_count = len(MOJIBAKE_RE.findall(sample))
    mojibake_ratio = mojibake_count / max(len(sample), 1)
    likely_scanned = (
        data_len >= 4096
        and (sample_bytes_len < 80 or density < 0.005)
    )
    if sample_bytes_len < 80:
        sample_quality = "low_text"
    elif density < 0.005 or printable_ratio < 0.9 or mojibake_ratio >= 0.08:
        sample_quality = "binary_garbage"
    else:
        sample_quality = "extractable_text"
    return {
        "page_count_estimate": page_count or None,
        "sample_text": sample,
        "pdf_text_density": round(density, 6),
        "pdf_text_sample_quality": sample_quality,
        "pdf_text_printable_ratio": round(printable_ratio, 6),
        "pdf_text_mojibake_ratio": round(mojibake_ratio, 6),
        "likely_scanned": bool(likely_scanned),
    }


def _count_markdown_tables(lines: list[str]) -> int:
    count = 0
    in_table = False
    for line in lines:
        stripped = line.strip()
        is_table = stripped.count("|") >= 2 and not stripped.startswith("```")
        if is_table and not in_table:
            count += 1
        in_table = is_table
    return count


def _infer_language_from_filename(path: Path) -> str | None:
    """Heuristic language detection from filename hints."""
    name = path.stem.lower()
    if re.search(r"(?:^|[^a-z0-9])(?:cn|zh|zho|chinese|ch)(?:[^a-z0-9]|$)", name) or "中文" in name:
        return "zh"
    if re.search(r"(?:^|[^a-z0-9])(?:en|eng|english)(?:[^a-z0-9]|$)", name):
        return "en"
    return None


def _language_summary(
    text: str,
    *,
    filename_hint: str | None = None,
    sample_reliable: bool = True,
) -> dict[str, Any]:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in text if ("a" <= char.lower() <= "z"))
    total = max(len(text), 1)
    language_source = "sample_text"
    if cjk_count >= max(8, latin_count // 2):
        language = "zh"
    elif latin_count and sample_reliable:
        language = "en"
    elif filename_hint:
        language = filename_hint
        language_source = "filename_hint"
    else:
        language = "unknown"
        language_source = "unknown_low_confidence"
    if (
        language in {"unknown", "en"}
        and filename_hint
        and (len(text.strip()) < 200 or not sample_reliable)
    ):
        language = filename_hint
        language_source = "filename_hint"
    elif language == "en" and not sample_reliable:
        language = "unknown"
        language_source = "unknown_low_confidence"
    return {
        "language": language,
        "language_source": language_source,
        "language_confidence": "high" if language_source == "sample_text" and sample_reliable else "review",
        "cjk_char_count": cjk_count,
        "latin_char_count": latin_count,
        "sample_char_count": len(text),
        "cjk_ratio": round(cjk_count / total, 6),
    }


def _source_kind(suffix: str) -> str:
    if suffix in MARKDOWN_EXTENSIONS:
        return "markdown"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in OFFICE_EXTENSIONS:
        return "office"
    if suffix in PANDOC_AUTO_EXTENSIONS:
        return "structured_document"
    return "other"


def _document_record(source: Any, *, max_text_chars: int, max_binary_bytes: int) -> dict[str, Any]:
    path = Path(source.path)
    suffix = path.suffix.lower()
    kind = _source_kind(suffix)
    sample_text = ""
    read_warning: str | None = None
    page_count: int | None = None

    if suffix in BUILTIN_EXTENSIONS:
        sample_text, read_warning = _safe_text_sample(path, max_chars=max_text_chars)
    elif suffix in PDF_EXTENSIONS:
        pdf = _binary_pdf_features(path, max_bytes=max_binary_bytes)
        sample_text = str(pdf.get("sample_text") or "")
        page_count = pdf.get("page_count_estimate") if isinstance(pdf.get("page_count_estimate"), int) else None
        read_warning = pdf.get("pdf_probe_error") if isinstance(pdf.get("pdf_probe_error"), str) else None
    else:
        pdf = {}

    lines = sample_text.splitlines()
    html_tables = parse_html_tables(sample_text) if sample_text else []
    markdown_table_count = _count_markdown_tables(lines)
    html_table_count = len(html_tables)
    image_ref_count = len(MARKDOWN_IMAGE_RE.findall(sample_text)) + len(HTML_IMAGE_RE.findall(sample_text))
    table_count = markdown_table_count + html_table_count
    filename_hint = _infer_language_from_filename(path)
    binary_pdf_features = pdf if suffix in PDF_EXTENSIONS else {}
    sample_reliable = str(binary_pdf_features.get("pdf_text_sample_quality") or "extractable_text") == "extractable_text"
    lang = _language_summary(sample_text, filename_hint=filename_hint, sample_reliable=sample_reliable)
    stat = path.stat()
    scanned_risk = bool(
        suffix in PDF_EXTENSIONS
        and (
            len(sample_text.strip()) < 80
            or binary_pdf_features.get("likely_scanned", False)
            or binary_pdf_features.get("pdf_text_sample_quality") in {"low_text", "binary_garbage"}
        )
    )
    table_char_count = sum(len(line) for line in lines if line.count("|") >= 2)
    table_density = round(table_char_count / max(len(sample_text), 1), 6) if sample_text else 0.0
    numeric_unit_hits = len(MATH_OR_UNIT_RE.findall(sample_text))

    record: dict[str, Any] = {
        "source_path": str(source.source_path),
        "source_kind": kind,
        "suffix": suffix,
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
        "formal_ingest_candidate": suffix in FORMAL_SOURCE_EXTENSIONS or kind in {"pdf", "image", "office"},
        "builtin_preview_available": suffix in BUILTIN_EXTENSIONS,
        "page_count_estimate": page_count,
        "sample": {
            **lang,
            "line_count": len(lines),
            "heading_count": sum(1 for line in lines if line.lstrip().startswith("#")),
            "image_ref_count": image_ref_count,
            "markdown_table_count": markdown_table_count,
            "html_table_count": html_table_count,
            "table_count": table_count,
            "table_density": table_density,
            "numeric_or_unit_signal_count": numeric_unit_hits,
        },
        "language_hint": filename_hint,
        "risks": {
            "scanned_or_low_text_pdf": scanned_risk,
            "image_source_requires_ocr": kind == "image",
            "table_signals_from_sample_only": suffix not in BUILTIN_EXTENSIONS,
        },
        **binary_pdf_features,
    }
    if read_warning:
        record["warnings"] = [{"code": "source_sample_read_warning", "message": read_warning}]
    return record


def _aggregate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(records)
    suffix_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    total_size = 0
    total_tables = 0
    total_html_tables = 0
    total_markdown_tables = 0
    total_images = 0
    formal_candidates = 0
    scanned_risk_count = 0
    image_source_count = 0
    max_page_count = 0
    max_table_density = 0.0
    numeric_signal_count = 0
    language_source_counts: dict[str, int] = {}

    for item in items:
        suffix = str(item.get("suffix") or "")
        kind = str(item.get("source_kind") or "other")
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        total_size += int(item.get("size_bytes", 0) or 0)
        if item.get("formal_ingest_candidate"):
            formal_candidates += 1
        risks = item.get("risks") if isinstance(item.get("risks"), dict) else {}
        if risks.get("scanned_or_low_text_pdf"):
            scanned_risk_count += 1
        if risks.get("image_source_requires_ocr"):
            image_source_count += 1
        sample = item.get("sample") if isinstance(item.get("sample"), dict) else {}
        language = str(sample.get("language") or "unknown")
        language_counts[language] = language_counts.get(language, 0) + 1
        language_source = str(sample.get("language_source") or "unknown")
        language_source_counts[language_source] = language_source_counts.get(language_source, 0) + 1
        total_tables += int(sample.get("table_count", 0) or 0)
        total_html_tables += int(sample.get("html_table_count", 0) or 0)
        total_markdown_tables += int(sample.get("markdown_table_count", 0) or 0)
        total_images += int(sample.get("image_ref_count", 0) or 0)
        numeric_signal_count += int(sample.get("numeric_or_unit_signal_count", 0) or 0)
        max_table_density = max(max_table_density, float(sample.get("table_density", 0.0) or 0.0))
        page_count = item.get("page_count_estimate")
        if isinstance(page_count, int):
            max_page_count = max(max_page_count, page_count)

    primary_language = "unknown"
    if language_counts:
        primary_language = sorted(language_counts.items(), key=lambda entry: (-entry[1], entry[0]))[0][0]
    table_heavy = total_tables >= 2 or max_table_density >= 0.05
    image_rich = total_images >= 3 or image_source_count > 0
    long_document = max_page_count >= 80 or total_size >= 20 * 1024 * 1024
    formal = formal_candidates > 0
    complexity_score = 0
    complexity_score += 2 if table_heavy else 0
    complexity_score += 1 if image_rich else 0
    complexity_score += 1 if scanned_risk_count else 0
    complexity_score += 1 if long_document else 0
    complexity_score += 1 if numeric_signal_count >= 6 else 0
    # Scanned/low-text PDFs usually require OCR and deserve at least medium complexity.
    if scanned_risk_count and complexity_score < 2:
        complexity_score = 2
    complexity = "high" if complexity_score >= 4 else "medium" if complexity_score >= 2 else "low"

    return {
        "document_count": len(items),
        "total_size_bytes": total_size,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "source_kind_counts": dict(sorted(kind_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "language_source_counts": dict(sorted(language_source_counts.items())),
        "primary_language": primary_language,
        "formal_ingest_candidate_count": formal_candidates,
        "has_formal_ingest_candidates": formal,
        "sample_table_count": total_tables,
        "sample_html_table_count": total_html_tables,
        "sample_markdown_table_count": total_markdown_tables,
        "sample_image_ref_count": total_images,
        "scanned_or_low_text_pdf_count": scanned_risk_count,
        "image_source_count": image_source_count,
        "max_page_count_estimate": max_page_count or None,
        "max_table_density": round(max_table_density, 6),
        "numeric_or_unit_signal_count": numeric_signal_count,
        "table_heavy": table_heavy,
        "image_rich": image_rich,
        "long_document": long_document,
        "estimated_complexity": complexity,
        "complexity_score": complexity_score,
    }


def inspect_source_document(
    input_path: str | Path,
    *,
    recursive: bool = True,
    max_text_chars: int = 20000,
    max_binary_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    """Inspect source files without running document conversion."""

    if max_text_chars <= 0:
        raise DocConvertError("max_text_chars must be greater than zero")
    if max_binary_bytes <= 0:
        raise DocConvertError("max_binary_bytes must be greater than zero")

    sources = discover_source_documents(input_path, recursive=recursive)
    documents = [
        _document_record(source, max_text_chars=max_text_chars, max_binary_bytes=max_binary_bytes)
        for source in sources
    ]
    return {
        "schema": DOCUMENT_FEATURES_SCHEMA,
        "created_at": _utc_now(),
        "input": {
            "path": str(Path(input_path).expanduser()),
            "recursive": bool(recursive),
            "max_text_chars": max_text_chars,
            "max_binary_bytes": max_binary_bytes,
        },
        "summary": _aggregate(documents),
        "documents": documents,
    }


def render_document_features_markdown(report: dict[str, Any]) -> str:
    """Render a concise source-inspection report."""

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Document Source Features",
        "",
        f"- schema: `{report.get('schema', DOCUMENT_FEATURES_SCHEMA)}`",
        f"- document count: `{summary.get('document_count', 0)}`",
        f"- primary language: `{summary.get('primary_language', 'unknown')}`",
        f"- estimated complexity: `{summary.get('estimated_complexity', 'unknown')}`",
        f"- table heavy: `{summary.get('table_heavy', False)}`",
        f"- image rich: `{summary.get('image_rich', False)}`",
        f"- long document: `{summary.get('long_document', False)}`",
        f"- scanned/low-text PDFs: `{summary.get('scanned_or_low_text_pdf_count', 0)}`",
        "",
        "## Signals",
        "",
        f"- sample tables: `{summary.get('sample_table_count', 0)}`",
        f"- HTML tables: `{summary.get('sample_html_table_count', 0)}`",
        f"- Markdown tables: `{summary.get('sample_markdown_table_count', 0)}`",
        f"- image refs: `{summary.get('sample_image_ref_count', 0)}`",
        f"- numeric/unit signals: `{summary.get('numeric_or_unit_signal_count', 0)}`",
        "",
        "## Documents",
        "",
        "| Source | Kind | Size | Language | Tables | Images | Risks |",
        "| --- | --- | ---: | --- | ---: | ---: | --- |",
    ]
    for item in report.get("documents", []):
        if not isinstance(item, dict):
            continue
        sample = item.get("sample") if isinstance(item.get("sample"), dict) else {}
        risks = item.get("risks") if isinstance(item.get("risks"), dict) else {}
        risk_codes = [key for key, value in sorted(risks.items()) if value]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("source_path") or ""),
                    str(item.get("source_kind") or ""),
                    str(item.get("size_bytes") or 0),
                    str(sample.get("language") or "unknown"),
                    str(sample.get("table_count") or 0),
                    str(sample.get("image_ref_count") or 0),
                    ", ".join(risk_codes) if risk_codes else "none",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)
