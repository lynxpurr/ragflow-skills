"""Markdown segmentation helpers for long document handoffs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEGMENTATION_SCHEMA = "doc_segmentation_plan_v1"
SEGMENTATION_STRATEGY = "heading_boundary_v1"
DEFAULT_SOFT_MAX_CHARS = 24_000
DEFAULT_HARD_MAX_CHARS = 32_000
DEFAULT_MIN_SEGMENT_CHARS = 4_000
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHUNK_MARKER_RE = re.compile(r"^<!--\s*chunk\s*-->\s*$", re.IGNORECASE)
IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")


class DocSegmentError(RuntimeError):
    """Raised when a Markdown document cannot be segmented."""


@dataclass(frozen=True)
class DocumentSegment:
    index: int
    title: str
    start_line: int
    end_line: int
    char_count: int
    image_count: int
    chunk_marker_count: int
    suggested_markdown_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "char_count": self.char_count,
            "image_count": self.image_count,
            "chunk_marker_count": self.chunk_marker_count,
            "suggested_markdown_path": self.suggested_markdown_path,
        }


@dataclass(frozen=True)
class SegmentationPlan:
    markdown_path: Path
    document_name: str
    total_chars: int
    total_lines: int
    total_images: int
    total_chunk_markers: int
    recommended: bool
    reason: str
    segments: list[DocumentSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SEGMENTATION_SCHEMA,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy": SEGMENTATION_STRATEGY,
            "markdown_path": str(self.markdown_path),
            "document_name": self.document_name,
            "recommended": self.recommended,
            "reason": self.reason,
            "totals": {
                "chars": self.total_chars,
                "lines": self.total_lines,
                "images": self.total_images,
                "chunk_markers": self.total_chunk_markers,
            },
            "segments": [segment.to_dict() for segment in self.segments],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MaterializedSegments:
    plan: SegmentationPlan
    output_dir: Path
    segment_paths: list[Path]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "segmentation_plan": self.plan.to_dict(),
            "output_dir": str(self.output_dir),
            "segment_paths": [str(path) for path in self.segment_paths],
            "segment_count": len(self.segment_paths),
        }


def _validate_thresholds(soft_max_chars: int, hard_max_chars: int, min_segment_chars: int) -> None:
    if min_segment_chars <= 0:
        raise DocSegmentError("min_segment_chars must be greater than zero")
    if soft_max_chars <= min_segment_chars:
        raise DocSegmentError("soft_max_chars must be greater than min_segment_chars")
    if hard_max_chars < soft_max_chars:
        raise DocSegmentError("hard_max_chars must be greater than or equal to soft_max_chars")


def _count_images(text: str) -> int:
    return len(IMAGE_RE.findall(text))


def _count_chunk_markers(text: str) -> int:
    return sum(1 for line in text.splitlines() if CHUNK_MARKER_RE.match(line.strip()))


def _line_ranges(
    lines: list[str],
    *,
    soft_max_chars: int,
    hard_max_chars: int,
    min_segment_chars: int,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    current_chars = 0
    last_boundary: int | None = None
    chars_at_boundary = 0

    for index, line in enumerate(lines):
        stripped = line.strip()
        is_boundary = bool(HEADING_RE.match(stripped) or CHUNK_MARKER_RE.match(stripped))
        if index > start and is_boundary and current_chars >= min_segment_chars:
            last_boundary = index
            chars_at_boundary = current_chars

        current_chars += len(line)

        if current_chars >= hard_max_chars:
            if last_boundary is not None and chars_at_boundary >= min_segment_chars:
                end = last_boundary
            else:
                end = index + 1
            ranges.append((start, end))
            start = end
            current_chars = sum(len(item) for item in lines[start:index + 1])
            last_boundary = None
            chars_at_boundary = 0
        elif current_chars >= soft_max_chars and last_boundary is not None:
            ranges.append((start, last_boundary))
            start = last_boundary
            current_chars = sum(len(item) for item in lines[start:index + 1])
            last_boundary = None
            chars_at_boundary = 0

    if start < len(lines):
        ranges.append((start, len(lines)))
    return [(start, end) for start, end in ranges if end > start] or [(0, len(lines))]


def _segment_title(text: str, document_name: str, index: int) -> str:
    for line in text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            return match.group(2).strip()[:120] or f"{document_name} part {index}"
    return f"{document_name} part {index}"


def _recommendation_reason(total_chars: int, segment_count: int, *, soft_max_chars: int) -> str:
    if segment_count > 1:
        return f"document split into {segment_count} segments by size and heading boundaries"
    if total_chars > soft_max_chars:
        return "document exceeds soft threshold but no safe split boundary was found"
    return "document is below segmentation threshold"


def plan_markdown_segmentation(
    markdown_path: str | Path,
    *,
    soft_max_chars: int = DEFAULT_SOFT_MAX_CHARS,
    hard_max_chars: int = DEFAULT_HARD_MAX_CHARS,
    min_segment_chars: int = DEFAULT_MIN_SEGMENT_CHARS,
) -> SegmentationPlan:
    """Create a segmentation plan for one Markdown file without writing segments."""

    _validate_thresholds(soft_max_chars, hard_max_chars, min_segment_chars)
    path = Path(markdown_path)
    if not path.exists() or not path.is_file():
        raise DocSegmentError(f"markdown file not found: {path}")
    if path.suffix.lower() not in {".md", ".markdown", ".mdown", ".mkd"}:
        raise DocSegmentError(f"segmentation expects a Markdown file: {path}")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True) or [""]
    ranges = _line_ranges(
        lines,
        soft_max_chars=soft_max_chars,
        hard_max_chars=hard_max_chars,
        min_segment_chars=min_segment_chars,
    )
    stem = path.stem or "document"
    segments = []
    for index, (start, end) in enumerate(ranges, start=1):
        text = "".join(lines[start:end])
        segments.append(
            DocumentSegment(
                index=index,
                title=_segment_title(text, stem, index),
                start_line=start + 1,
                end_line=end,
                char_count=len(text),
                image_count=_count_images(text),
                chunk_marker_count=_count_chunk_markers(text),
                suggested_markdown_path=f"segments/{stem}.part-{index:03d}.md",
            )
        )
    total_chars = len(content)
    warnings = []
    if total_chars > soft_max_chars and len(segments) == 1:
        warnings.append("document exceeds soft threshold, but no safe boundary was found")
    return SegmentationPlan(
        markdown_path=path,
        document_name=stem,
        total_chars=total_chars,
        total_lines=len(content.splitlines()) if content else 0,
        total_images=_count_images(content),
        total_chunk_markers=_count_chunk_markers(content),
        recommended=total_chars > soft_max_chars or len(segments) > 1,
        reason=_recommendation_reason(total_chars, len(segments), soft_max_chars=soft_max_chars),
        segments=segments,
        warnings=warnings,
    )


def materialize_segments(
    markdown_path: str | Path,
    *,
    output_dir: str | Path,
    plan_output: str | Path | None = None,
    soft_max_chars: int = DEFAULT_SOFT_MAX_CHARS,
    hard_max_chars: int = DEFAULT_HARD_MAX_CHARS,
    min_segment_chars: int = DEFAULT_MIN_SEGMENT_CHARS,
    force: bool = False,
) -> MaterializedSegments:
    """Write segment Markdown files for one Markdown document."""

    plan = plan_markdown_segmentation(
        markdown_path,
        soft_max_chars=soft_max_chars,
        hard_max_chars=hard_max_chars,
        min_segment_chars=min_segment_chars,
    )
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()) and not force:
        raise DocSegmentError(f"segment output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source_lines = plan.markdown_path.read_text(encoding="utf-8").splitlines(keepends=True) or [""]
    segment_paths: list[Path] = []
    for segment in plan.segments:
        target = output / Path(segment.suggested_markdown_path).name
        text = "".join(source_lines[segment.start_line - 1:segment.end_line])
        target.write_text(text, encoding="utf-8")
        segment_paths.append(target)
    if plan_output:
        Path(plan_output).write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return MaterializedSegments(plan=plan, output_dir=output, segment_paths=segment_paths)
