"""Deterministic Markdown post-processing for document handoffs."""

from __future__ import annotations

import json
import re
import shutil
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_quality import load_doc_manifest_payload
from .html_tables import parse_html_tables


POSTPROCESS_REPORT_SCHEMA = "doc_postprocess_report_v1"
CHUNK_PROFILE_REPORT_SCHEMA = "ragflow_chunk_profile_report_v1"
POSTPROCESS_PROFILES = {
    "none",
    "safe",
    "ocr",
    "chunk-markers",
    "chunk-markers-conservative",
    "chunk-markers-dense",
    "chunk-markers-ragflux-like",
}

HEADING_WITHOUT_SPACE_RE = re.compile(r"^(#{1,6})([^#\s].*)$")
MARKDOWN_IMAGE_TARGET_RE = re.compile(r"(!\[[^\]]*]\()([^)]+)(\))")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
HTML_TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
HTML_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
HTML_TABLE_CLOSE_RE = re.compile(r"</table\s*>", re.IGNORECASE)
PAGE_COMMENT_RE = re.compile(
    r"<!--\s*(?:page|page_id|page-id|page_index|page-index)\s*[:=]?\s*\d+\s*-->",
    re.IGNORECASE,
)
PAGE_TEXT_RE = re.compile(r"^\s*(?:page|p\.|第)\s*[0-9]{1,5}\s*(?:页)?\s*$", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
CHUNK_MARKER_RE = re.compile(r"^\s*<!--\s*chunk\s*-->\s*$", re.IGNORECASE)
CJK_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"

CHUNK_MARKER_BOUNDARY_TYPES = ("heading", "page", "table", "image", "list")
CHUNK_MARKER_PROFILE_CONFIG: dict[str, dict[str, Any]] = {
    "chunk-markers": {
        "canonical": "chunk-markers-conservative",
        "heading_max_level": 3,
        "boundary_types": {"heading"},
    },
    "chunk-markers-conservative": {
        "canonical": "chunk-markers-conservative",
        "heading_max_level": 3,
        "boundary_types": {"heading"},
    },
    "chunk-markers-dense": {
        "canonical": "chunk-markers-dense",
        "heading_max_level": 4,
        "boundary_types": {"heading", "page", "table", "image"},
    },
    "chunk-markers-ragflux-like": {
        "canonical": "chunk-markers-ragflux-like",
        "heading_max_level": 6,
        "boundary_types": {"heading", "page", "table", "image", "list"},
    },
}


class DocPostprocessError(RuntimeError):
    """Raised when Markdown post-processing cannot proceed."""


@dataclass(frozen=True)
class PostprocessRuleResult:
    rule_id: str
    description: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "count": self.count,
        }


@dataclass(frozen=True)
class PostprocessDocumentResult:
    markdown_path: str
    output_path: str
    profile: str
    changed: bool
    line_count_before: int
    line_count_after: int
    rule_results: list[PostprocessRuleResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chunk_profile: dict[str, Any] | None = None
    table_integrity: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "markdown_path": self.markdown_path,
            "output_path": self.output_path,
            "profile": self.profile,
            "changed": self.changed,
            "line_count_before": self.line_count_before,
            "line_count_after": self.line_count_after,
            "rules": [result.to_dict() for result in self.rule_results if result.count],
            "warnings": list(self.warnings),
        }
        if self.chunk_profile is not None:
            payload["chunk_profile"] = self.chunk_profile
        if self.table_integrity is not None:
            payload["table_integrity"] = self.table_integrity
        return payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_profile(profile: str) -> str:
    normalized = profile.strip().lower()
    if normalized not in POSTPROCESS_PROFILES:
        allowed = ", ".join(sorted(POSTPROCESS_PROFILES))
        raise DocPostprocessError(f"postprocess profile must be one of: {allowed}")
    return normalized


def _line_counts(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _ensure_trailing_newline(text: str) -> tuple[str, int]:
    if text and not text.endswith("\n"):
        return text + "\n", 1
    return text, 0


def _normalize_line_endings(text: str) -> tuple[str, int]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, 1 if normalized != text else 0


def _strip_trailing_spaces(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    changed = 0
    output = []
    for line in lines:
        newline = ""
        body = line
        if line.endswith("\n"):
            newline = "\n"
            body = line[:-1]
        stripped = body.rstrip(" \t")
        if stripped != body:
            changed += 1
        output.append(stripped + newline)
    return "".join(output), changed


def _collapse_blank_lines(text: str) -> tuple[str, int]:
    collapsed = re.sub(r"\n{3,}", "\n\n", text)
    if collapsed == text:
        return text, 0
    return collapsed, 1


def _repair_heading_spacing(text: str) -> tuple[str, int]:
    changed = 0
    output = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        if body.strip().startswith("```") or body.strip().startswith("~~~"):
            in_fence = not in_fence
        if not in_fence:
            match = HEADING_WITHOUT_SPACE_RE.match(body)
            if match:
                body = f"{match.group(1)} {match.group(2).strip()}"
                changed += 1
        output.append(body + ("\n" if line.endswith("\n") else ""))
    return "".join(output), changed


def _normalize_markdown_image_targets(text: str) -> tuple[str, int]:
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        prefix, raw, suffix = match.groups()
        value = raw.strip()
        if value.lower().startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        if value.startswith("<") and ">" in value:
            target, rest = value[1:].split(">", 1)
            angle = True
        else:
            parts = value.split(maxsplit=1)
            target = parts[0] if parts else value
            rest = f" {parts[1]}" if len(parts) == 2 else ""
            angle = False
        normalized = target.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        absolute_like = normalized.startswith(("/", "~/")) or bool(re.match(r"^[A-Za-z]:/", normalized))
        if absolute_like and "/images/" in normalized:
            normalized = f"images/{normalized.rsplit('/images/', 1)[1]}"
        if " " in normalized and not angle:
            replacement = f"<{normalized}>{rest}"
        else:
            replacement = f"<{normalized}>{rest}" if angle else f"{normalized}{rest}"
        if replacement != raw:
            changed += 1
        return f"{prefix}{replacement}{suffix}"

    return MARKDOWN_IMAGE_TARGET_RE.sub(replace, text), changed


def _remove_cjk_inner_spaces(text: str) -> tuple[str, int]:
    pattern = re.compile(fr"([{CJK_RE}])\s+([{CJK_RE}])")
    changed = 0
    previous = text
    while True:
        current, count = pattern.subn(r"\1\2", previous)
        changed += count
        if current == previous:
            return current, changed
        previous = current


def _fix_ocr_punctuation_spacing(text: str) -> tuple[str, int]:
    replacements = [
        (re.compile(r"\s+([,.;:!?，。；：！？、])"), r"\1"),
        (re.compile(r"([，。；：！？、])\s+"), r"\1"),
        (re.compile(r"([（([{])\s+"), r"\1"),
        (re.compile(r"\s+([）)\]}])"), r"\1"),
    ]
    changed = 0
    current = text
    for pattern, replacement in replacements:
        current, count = pattern.subn(replacement, current)
        changed += count
    return current, changed


def _normalize_ocr_ligatures(text: str) -> tuple[str, int]:
    replacements = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
    }
    changed = 0
    current = text
    for old, new in replacements.items():
        count = current.count(old)
        if count:
            current = current.replace(old, new)
            changed += count
    return current, changed


def _markdown_table_spans(text: str) -> list[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(lines) - 1:
        if "|" not in lines[index] or not MARKDOWN_TABLE_SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        start = offsets[index]
        end_index = index + 2
        while end_index < len(lines):
            stripped = lines[end_index].strip()
            if not stripped or "|" not in stripped:
                break
            end_index += 1
        end = offsets[end_index] if end_index < len(lines) else len(text)
        spans.append((start, end))
        index = end_index
    return spans


def _table_protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in HTML_TABLE_BLOCK_RE.finditer(text)]
    spans.extend(_markdown_table_spans(text))
    if not spans:
        return []
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _apply_outside_table_blocks(text: str, func) -> tuple[str, int]:
    spans = _table_protected_spans(text)
    if not spans:
        return func(text)
    output: list[str] = []
    changed = 0
    cursor = 0
    for start, end in spans:
        if cursor < start:
            processed, count = func(text[cursor:start])
            output.append(processed)
            changed += count
        output.append(text[start:end])
        cursor = end
    if cursor < len(text):
        processed, count = func(text[cursor:])
        output.append(processed)
        changed += count
    return "".join(output), changed


def _html_table_blocks(text: str) -> list[str]:
    return [match.group(0) for match in HTML_TABLE_BLOCK_RE.finditer(text)]


def _html_table_fingerprint(block: str) -> str:
    normalized = block.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _table_integrity_summary(before: str, after: str) -> dict[str, Any]:
    before_blocks = _html_table_blocks(before)
    after_blocks = _html_table_blocks(after)
    before_hashes = [_html_table_fingerprint(block) for block in before_blocks]
    after_hashes = [_html_table_fingerprint(block) for block in after_blocks]
    before_cell_count = sum(table.cell_count for table in parse_html_tables(before))
    after_cell_count = sum(table.cell_count for table in parse_html_tables(after))
    marker_inside_count = sum(block.count("<!-- chunk -->") for block in after_blocks)
    before_open = len(HTML_TABLE_OPEN_RE.findall(before))
    before_close = len(HTML_TABLE_CLOSE_RE.findall(before))
    after_open = len(HTML_TABLE_OPEN_RE.findall(after))
    after_close = len(HTML_TABLE_CLOSE_RE.findall(after))
    hashes_unchanged = before_hashes == after_hashes
    return {
        "html_table_count_before": len(before_blocks),
        "html_table_count_after": len(after_blocks),
        "html_table_fingerprints_before": before_hashes,
        "html_table_fingerprints_after": after_hashes,
        "html_table_fingerprints_unchanged": hashes_unchanged,
        "postprocess_table_delta": {
            "html_table_count_before": len(before_blocks),
            "html_table_count_after": len(after_blocks),
            "html_table_count_changed": len(before_blocks) != len(after_blocks),
            "html_table_fingerprints_changed": not hashes_unchanged,
            "html_table_cell_count_before": before_cell_count,
            "html_table_cell_count_after": after_cell_count,
            "html_table_cell_count_changed": before_cell_count != after_cell_count,
        },
        "chunk_marker_inside_html_table_count": marker_inside_count,
        "unbalanced_html_table_before": before_open != before_close,
        "unbalanced_html_table_after": after_open != after_close,
        "ok": (
            len(before_blocks) == len(after_blocks)
            and hashes_unchanged
            and marker_inside_count == 0
            and before_open == before_close
            and after_open == after_close
        ),
    }


def _is_chunk_marker(line: str) -> bool:
    return bool(CHUNK_MARKER_RE.match(line.strip()))


def _is_fence(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _chunk_marker_profile_config(profile: str) -> dict[str, Any] | None:
    return CHUNK_MARKER_PROFILE_CONFIG.get(profile)


def _heading_level(line: str) -> int | None:
    match = re.match(r"^(#{1,6})\s+\S", line.strip())
    return len(match.group(1)) if match else None


def _markdown_table_starts(lines: list[str]) -> set[int]:
    starts: set[int] = set()
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        if MARKDOWN_TABLE_SEPARATOR_RE.match(lines[index + 1]):
            starts.add(index + 1)
    return starts


def _html_table_starts(lines: list[str]) -> set[int]:
    starts: set[int] = set()
    for index, line in enumerate(lines, start=1):
        if "<table" in line.lower():
            starts.add(index)
    return starts


def _list_starts(lines: list[str]) -> set[int]:
    starts: set[int] = set()
    previous_list = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        current_list = bool(LIST_ITEM_RE.match(line))
        if current_list and not previous_list:
            starts.add(index)
        if stripped:
            previous_list = current_list
    return starts


def _page_marker_line(line: str) -> bool:
    return bool(PAGE_COMMENT_RE.search(line) or PAGE_TEXT_RE.match(line) or line == "\f")


def _boundary_type_for_line(
    *,
    lines: list[str],
    index: int,
    profile_config: Mapping[str, Any],
    markdown_table_starts: set[int],
    html_table_starts: set[int],
    list_starts: set[int],
) -> str | None:
    line = lines[index - 1]
    stripped = line.strip()
    if not stripped or _is_chunk_marker(stripped):
        return None
    allowed = profile_config.get("boundary_types")
    boundary_types = allowed if isinstance(allowed, set) else set()
    if "page" in boundary_types and _page_marker_line(line):
        return "page"
    if "heading" in boundary_types:
        level = _heading_level(line)
        if level is not None and level <= int(profile_config.get("heading_max_level", 3)):
            return "heading"
    if "table" in boundary_types and (index in markdown_table_starts or index in html_table_starts):
        return "table"
    if "image" in boundary_types and MARKDOWN_IMAGE_RE.search(line):
        return "image"
    if "list" in boundary_types and index in list_starts:
        return "list"
    return None


def _previous_non_empty_is_marker(output: list[str]) -> bool:
    for line in reversed(output):
        stripped = line.strip()
        if not stripped:
            continue
        return _is_chunk_marker(stripped)
    return False


def _insert_chunk_markers_for_profile(profile: str):
    profile_config = _chunk_marker_profile_config(profile)

    def insert(text: str) -> tuple[str, int]:
        if profile_config is None:
            return text, 0
        lines = text.splitlines()
        if not lines:
            return text, 0
        output: list[str] = []
        changed = 0
        in_fence = False
        seen_content = False
        markdown_table_starts = _markdown_table_starts(lines)
        html_table_starts = _html_table_starts(lines)
        list_starts = _list_starts(lines)
        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if _is_fence(line):
                in_fence = not in_fence
            boundary_type = None if in_fence else _boundary_type_for_line(
                lines=lines,
                index=index,
                profile_config=profile_config,
                markdown_table_starts=markdown_table_starts,
                html_table_starts=html_table_starts,
                list_starts=list_starts,
            )
            if boundary_type and seen_content and not _previous_non_empty_is_marker(output):
                if output and output[-1].strip():
                    output.append("")
                output.append("<!-- chunk -->")
                changed += 1
            output.append(line)
            if stripped and not _is_chunk_marker(stripped):
                seen_content = True
        return "\n".join(output) + ("\n" if text.endswith("\n") else ""), changed

    return insert


def _insert_chunk_markers(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines:
        return text, 0
    output: list[str] = []
    changed = 0
    in_fence = False
    seen_content = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        is_heading = bool(re.match(r"^#{1,3}\s+\S", stripped))
        previous = output[-1].strip().lower() if output else ""
        if (
            is_heading
            and not in_fence
            and seen_content
            and previous != "<!-- chunk -->"
        ):
            if output and output[-1].strip():
                output.append("")
            output.append("<!-- chunk -->")
            changed += 1
        output.append(line)
        if stripped and stripped != "<!-- chunk -->":
            seen_content = True
    return "\n".join(output) + ("\n" if text.endswith("\n") else ""), changed


def _chunk_marker_lines(text: str) -> list[int]:
    return [index for index, line in enumerate(text.splitlines(), start=1) if _is_chunk_marker(line)]


def _preferred_boundary_candidates(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    markdown_table_starts = _markdown_table_starts(lines)
    html_table_starts = _html_table_starts(lines)
    list_starts = _list_starts(lines)
    candidates: list[dict[str, Any]] = []
    in_fence = False
    for index, line in enumerate(lines, start=1):
        if _is_fence(line):
            in_fence = not in_fence
        if in_fence:
            continue
        level = _heading_level(line)
        if level is not None:
            candidates.append({"line": index, "type": "heading", "level": level})
        if _page_marker_line(line):
            candidates.append({"line": index, "type": "page"})
        if index in markdown_table_starts or index in html_table_starts:
            candidates.append({"line": index, "type": "table"})
        if MARKDOWN_IMAGE_RE.search(line):
            candidates.append({"line": index, "type": "image"})
        if index in list_starts:
            candidates.append({"line": index, "type": "list"})
    return candidates


def _next_non_empty_line(lines: list[str], marker_line: int) -> tuple[int | None, str | None]:
    for index in range(marker_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index + 1, stripped
    return None, None


def _marker_type_counts(text: str) -> dict[str, int]:
    lines = text.splitlines()
    candidates = _preferred_boundary_candidates(text)
    candidates_by_line: dict[int, str] = {}
    for candidate in candidates:
        line = candidate.get("line")
        boundary_type = candidate.get("type")
        if isinstance(line, int) and isinstance(boundary_type, str):
            candidates_by_line.setdefault(line, boundary_type)
    counts: Counter[str] = Counter()
    for marker_line in _chunk_marker_lines(text):
        next_line, _stripped = _next_non_empty_line(lines, marker_line)
        boundary_type = candidates_by_line.get(next_line or -1, "manual")
        counts[boundary_type] += 1
    return {key: int(counts.get(key, 0)) for key in (*CHUNK_MARKER_BOUNDARY_TYPES, "manual")}


def _marker_density_warnings(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    markers = set(_chunk_marker_lines(text))
    non_empty = [index for index, line in enumerate(lines, start=1) if line.strip()]
    marker_count = len(markers)
    warnings: list[dict[str, Any]] = []
    if not non_empty:
        return warnings
    density = round(marker_count / max(len(non_empty), 1), 4)
    if marker_count == 0 and len(non_empty) >= 12:
        warnings.append({"code": "marker_density_too_sparse", "severity": "warning", "density": density})
    if density > 0.3:
        warnings.append({"code": "marker_density_too_dense", "severity": "warning", "density": density})
    consecutive_count = 0
    empty_section_count = 0
    for marker_line in sorted(markers):
        next_line, stripped = _next_non_empty_line(lines, marker_line)
        if next_line is None:
            empty_section_count += 1
        elif _is_chunk_marker(stripped or ""):
            consecutive_count += 1
            empty_section_count += 1
    if consecutive_count:
        warnings.append(
            {
                "code": "consecutive_chunk_markers",
                "severity": "warning",
                "count": consecutive_count,
            }
        )
    if empty_section_count:
        warnings.append(
            {
                "code": "empty_chunk_section",
                "severity": "warning",
                "count": empty_section_count,
            }
        )
    return warnings


def _chunk_profile_document_summary(
    *,
    markdown_path: str,
    output_path: str,
    profile: str,
    before: str,
    after: str,
) -> dict[str, Any] | None:
    if _chunk_marker_profile_config(profile) is None:
        return None
    marker_lines = _chunk_marker_lines(after)
    candidates = _preferred_boundary_candidates(after)
    candidate_lines = {int(item["line"]) for item in candidates if isinstance(item.get("line"), int)}
    aligned_count = 0
    for marker_line in marker_lines:
        next_line, _stripped = _next_non_empty_line(after.splitlines(), marker_line)
        if next_line in candidate_lines:
            aligned_count += 1
    non_empty_line_count = sum(1 for line in after.splitlines() if line.strip())
    marker_count = len(marker_lines)
    return {
        "markdown_path": markdown_path,
        "output_path": output_path,
        "profile": profile,
        "canonical_profile": _chunk_marker_profile_config(profile).get("canonical"),
        "line_count": _line_counts(after),
        "non_empty_line_count": non_empty_line_count,
        "source_manual_marker_count": len(_chunk_marker_lines(before)),
        "marker_count": marker_count,
        "marker_density": round(marker_count / max(non_empty_line_count, 1), 4),
        "marker_type_counts": _marker_type_counts(after),
        "preferred_boundary_count": len(candidates),
        "preferred_boundary_alignment": {
            "aligned_marker_count": aligned_count,
            "preferred_boundary_count": len(candidates),
            "alignment_ratio": round(aligned_count / max(marker_count, 1), 4),
        },
        "warnings": _marker_density_warnings(after),
    }


def postprocess_markdown_text(text: str, *, profile: str) -> tuple[str, list[PostprocessRuleResult]]:
    """Post-process Markdown content and return applied rule counts."""

    profile = _validate_profile(profile)
    rule_results: list[PostprocessRuleResult] = []

    def apply(rule_id: str, description: str, func) -> None:
        nonlocal text
        text, count = func(text)
        rule_results.append(PostprocessRuleResult(rule_id=rule_id, description=description, count=count))

    if profile == "none":
        return text, []

    apply("safe.line_endings", "Normalize CRLF/CR line endings to LF", _normalize_line_endings)
    apply("safe.trailing_space", "Strip trailing spaces and tabs", _strip_trailing_spaces)
    apply("safe.blank_lines", "Collapse three or more blank lines to two", _collapse_blank_lines)
    apply("safe.heading_spacing", "Repair obvious Markdown heading spacing", _repair_heading_spacing)
    apply("safe.image_paths", "Normalize simple local Markdown image paths", _normalize_markdown_image_targets)
    apply("safe.trailing_newline", "Ensure a final newline", _ensure_trailing_newline)

    if profile in {"ocr", "chunk-markers"}:
        apply(
            "ocr.cjk_spaces",
            "Remove spaces inserted between adjacent CJK characters outside table blocks",
            lambda value: _apply_outside_table_blocks(value, _remove_cjk_inner_spaces),
        )
        apply(
            "ocr.punctuation_spacing",
            "Remove OCR spaces before punctuation or closing brackets outside table blocks",
            lambda value: _apply_outside_table_blocks(value, _fix_ocr_punctuation_spacing),
        )
        apply(
            "ocr.ligatures",
            "Normalize common OCR ligatures outside table blocks",
            lambda value: _apply_outside_table_blocks(value, _normalize_ocr_ligatures),
        )

    if _chunk_marker_profile_config(profile) is not None:
        canonical = _chunk_marker_profile_config(profile).get("canonical")
        rule_id = "chunk_markers.heading_boundaries" if canonical == "chunk-markers-conservative" else f"chunk_markers.{canonical}"
        apply(
            rule_id,
            f"Insert chunk markers using the {canonical} boundary profile",
            _insert_chunk_markers_for_profile(profile),
        )

    return text, rule_results


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def postprocess_markdown_file(
    markdown_path: str | Path,
    *,
    profile: str,
    output_path: str | Path | None = None,
    write: bool = False,
    root_for_report: str | Path | None = None,
    source_root_for_report: str | Path | None = None,
    output_root_for_report: str | Path | None = None,
) -> PostprocessDocumentResult:
    """Post-process one Markdown file."""

    source = Path(markdown_path)
    if not source.is_file():
        raise DocPostprocessError(f"markdown file not found: {source}")
    if source.suffix.lower() not in {".md", ".markdown", ".mdown", ".mkd"}:
        raise DocPostprocessError(f"postprocess expects a Markdown file: {source}")
    if write and output_path:
        raise DocPostprocessError("use either --write or --output, not both")
    if not write and not output_path:
        raise DocPostprocessError("postprocess requires --output unless --write is used")

    before = source.read_text(encoding="utf-8")
    after, rules = postprocess_markdown_text(before, profile=profile)
    target = source if write else Path(output_path)  # type: ignore[arg-type]
    if target.exists() and target.is_dir():
        target = target / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after, encoding="utf-8")

    fallback_root = Path(root_for_report) if root_for_report else target.parent
    source_root = Path(source_root_for_report) if source_root_for_report else fallback_root
    output_root = Path(output_root_for_report) if output_root_for_report else fallback_root
    markdown_rel = _relative(source, source_root)
    output_rel = _relative(target, output_root)
    return PostprocessDocumentResult(
        markdown_path=markdown_rel,
        output_path=output_rel,
        profile=_validate_profile(profile),
        changed=before != after,
        line_count_before=_line_counts(before),
        line_count_after=_line_counts(after),
        rule_results=rules,
        chunk_profile=_chunk_profile_document_summary(
            markdown_path=markdown_rel,
            output_path=output_rel,
            profile=_validate_profile(profile),
            before=before,
            after=after,
        ),
        table_integrity=_table_integrity_summary(before, after),
    )


def _manifest_markdown_paths(manifest: Mapping[str, Any], *, manifest_path: Path) -> list[tuple[Mapping[str, Any], Path]]:
    source_root = Path(str(manifest.get("source_root") or "."))
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise DocPostprocessError("doc_manifest.documents must be a non-empty list")
    output: list[tuple[Mapping[str, Any], Path]] = []
    for index, item in enumerate(documents):
        if not isinstance(item, Mapping):
            raise DocPostprocessError(f"documents[{index}] must be an object")
        markdown_path = item.get("markdown_path")
        if not isinstance(markdown_path, str) or not markdown_path:
            raise DocPostprocessError(f"documents[{index}].markdown_path is required")
        path = Path(markdown_path)
        if not path.is_absolute():
            path = source_root / path
        output.append((item, path))
    return output


def _manifest_source_root(manifest: Mapping[str, Any], *, manifest_path: Path) -> Path:
    source_root = Path(str(manifest.get("source_root") or "."))
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root
    return source_root


def _copy_handoff_assets(*, source_root: Path, output_root: Path) -> None:
    for container in ("documents", "artifacts"):
        base = source_root / container
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() in {".md", ".markdown", ".mdown", ".mkd"}:
                continue
            rel = path.relative_to(source_root)
            destination = output_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(path, destination)


def _report_payload(*, profile: str, mode: str, documents: list[PostprocessDocumentResult]) -> dict[str, Any]:
    changed = sum(1 for document in documents if document.changed)
    rule_counts: dict[str, int] = {}
    for document in documents:
        for rule in document.rule_results:
            rule_counts[rule.rule_id] = rule_counts.get(rule.rule_id, 0) + rule.count
    payload = {
        "schema": POSTPROCESS_REPORT_SCHEMA,
        "created_at": _now(),
        "profile": _validate_profile(profile),
        "mode": mode,
        "summary": {
            "documents": len(documents),
            "changed_documents": changed,
            "total_rule_applications": sum(rule_counts.values()),
            "rule_counts": rule_counts,
            "table_integrity": {
                "documents_with_html_tables": sum(
                    1
                    for document in documents
                    if document.table_integrity
                    and int(document.table_integrity.get("html_table_count_before", 0) or 0) > 0
                ),
                "documents_with_table_integrity_issues": sum(
                    1 for document in documents if document.table_integrity and not document.table_integrity.get("ok")
                ),
                "chunk_marker_inside_html_table_count": sum(
                    int(document.table_integrity.get("chunk_marker_inside_html_table_count", 0) or 0)
                    for document in documents
                    if document.table_integrity
                ),
            },
        },
        "documents": [document.to_dict() for document in documents],
    }
    chunk_profile_report = _chunk_profile_report_payload(profile=profile, mode=mode, documents=documents)
    if chunk_profile_report is not None:
        payload["chunk_profile_report"] = chunk_profile_report
    return payload


def _chunk_profile_report_payload(
    *,
    profile: str,
    mode: str,
    documents: list[PostprocessDocumentResult],
) -> dict[str, Any] | None:
    if _chunk_marker_profile_config(_validate_profile(profile)) is None:
        return None
    raw_documents = [document.chunk_profile for document in documents if document.chunk_profile is not None]
    marker_type_counts: Counter[str] = Counter()
    warning_count = 0
    for document in raw_documents:
        counts = document.get("marker_type_counts")
        if isinstance(counts, Mapping):
            for key, value in counts.items():
                marker_type_counts[str(key)] += int(value or 0)
        warnings = document.get("warnings")
        warning_count += len(warnings) if isinstance(warnings, list) else 0
    marker_count = sum(int(document.get("marker_count", 0) or 0) for document in raw_documents)
    preferred_boundary_count = sum(int(document.get("preferred_boundary_count", 0) or 0) for document in raw_documents)
    aligned_marker_count = 0
    for document in raw_documents:
        alignment = document.get("preferred_boundary_alignment")
        if isinstance(alignment, Mapping):
            aligned_marker_count += int(alignment.get("aligned_marker_count", 0) or 0)
    return {
        "schema": CHUNK_PROFILE_REPORT_SCHEMA,
        "created_at": _now(),
        "profile": _validate_profile(profile),
        "canonical_profile": _chunk_marker_profile_config(_validate_profile(profile)).get("canonical"),
        "mode": mode,
        "summary": {
            "documents": len(raw_documents),
            "marker_count": marker_count,
            "marker_type_counts": {key: int(marker_type_counts.get(key, 0)) for key in (*CHUNK_MARKER_BOUNDARY_TYPES, "manual")},
            "preferred_boundary_count": preferred_boundary_count,
            "preferred_boundary_aligned_marker_count": aligned_marker_count,
            "preferred_boundary_alignment_ratio": round(aligned_marker_count / max(marker_count, 1), 4),
            "warning_count": warning_count,
            "warnings": sorted(
                {
                    str(warning.get("code"))
                    for document in raw_documents
                    for warning in document.get("warnings", [])
                    if isinstance(warning, Mapping) and warning.get("code")
                }
            ),
        },
        "ragflow_profile_advice": {
            "parser": "review chunk parser settings after dry-run; this report is advisory and does not mutate RAGFlow",
            "profile_hint": _chunk_marker_profile_config(_validate_profile(profile)).get("canonical"),
        },
        "documents": raw_documents,
    }


def _write_chunk_profile_report(report: Mapping[str, Any], path: str | Path | None) -> None:
    chunk_report = report.get("chunk_profile_report")
    if not isinstance(chunk_report, Mapping) or not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(chunk_report, ensure_ascii=False, indent=2), encoding="utf-8")


def postprocess_handoff(
    doc_manifest_path: str | Path,
    *,
    profile: str,
    output_dir: str | Path | None = None,
    write: bool = False,
    report_json: str | Path | None = None,
    chunk_profile_report_json: str | Path | None = None,
) -> dict[str, Any]:
    """Post-process all Markdown documents referenced by a doc_manifest."""

    manifest_path = Path(doc_manifest_path)
    manifest = load_doc_manifest_payload(manifest_path)
    if write and output_dir:
        raise DocPostprocessError("use either --write or --output, not both")
    if not write and not output_dir:
        raise DocPostprocessError("handoff postprocess requires --output unless --write is used")

    output_root = Path(output_dir) if output_dir else manifest_path.parent
    source_root = _manifest_source_root(manifest, manifest_path=manifest_path)
    results: list[PostprocessDocumentResult] = []
    for item, markdown_path in _manifest_markdown_paths(manifest, manifest_path=manifest_path):
        raw_rel = Path(str(item.get("markdown_path")))
        target = markdown_path if write else output_root / raw_rel
        results.append(
            postprocess_markdown_file(
                markdown_path,
                profile=profile,
                output_path=None if write else target,
                write=write,
                source_root_for_report=source_root,
                output_root_for_report=source_root if write else output_root,
            )
        )

    if not write:
        _copy_handoff_assets(source_root=source_root, output_root=output_root)
        copied_manifest = dict(manifest)
        copied_manifest["source_root"] = "."
        copied_manifest["postprocess_report"] = "postprocess_report.json"
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / manifest_path.name).write_text(json.dumps(copied_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        for sidecar_name in ("quality_report", "quality_report_md"):
            sidecar = manifest.get(sidecar_name)
            if isinstance(sidecar, str) and (manifest_path.parent / sidecar).is_file():
                destination = output_root / sidecar
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_path.parent / sidecar, destination)

    report = _report_payload(profile=profile, mode="handoff", documents=results)
    report_path = Path(report_json) if report_json else (output_root / "postprocess_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if chunk_profile_report_json:
        _write_chunk_profile_report(report, chunk_profile_report_json)
    return report


def postprocess_single_markdown(
    markdown_path: str | Path,
    *,
    profile: str,
    output_path: str | Path | None = None,
    write: bool = False,
    report_json: str | Path | None = None,
    chunk_profile_report_json: str | Path | None = None,
) -> dict[str, Any]:
    """Post-process one Markdown file and write a report."""

    result = postprocess_markdown_file(
        markdown_path,
        profile=profile,
        output_path=output_path,
        write=write,
        root_for_report=Path(output_path).parent if output_path else Path(markdown_path).parent,
    )
    report = _report_payload(profile=profile, mode="markdown", documents=[result])
    if report_json:
        report_path = Path(report_json)
    elif output_path:
        output = Path(output_path)
        report_path = (output if output.exists() and output.is_dir() else output.parent) / "postprocess_report.json"
    else:
        report_path = Path(markdown_path).parent / "postprocess_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if chunk_profile_report_json:
        _write_chunk_profile_report(report, chunk_profile_report_json)
    return report
