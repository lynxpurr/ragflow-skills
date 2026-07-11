"""Deterministic HTML table extraction for Markdown handoff reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


@dataclass(frozen=True)
class HtmlTableArtifact:
    line_start: int
    line_end: int
    row_count: int
    column_count: int
    cell_count: int
    rowspan_count: int
    colspan_count: int
    header_depth: int
    header_preview: list[str]
    caption: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "line_start": self.line_start,
            "line_end": self.line_end,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "cell_count": self.cell_count,
            "rowspan_count": self.rowspan_count,
            "colspan_count": self.colspan_count,
            "header_depth": self.header_depth,
            "header_preview": self.header_preview,
        }
        if self.caption:
            payload["caption"] = self.caption
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class HtmlTableAnalysis:
    tables: tuple[HtmlTableArtifact, ...]
    balanced: bool
    unclosed_table_count: int
    unexpected_close_count: int
    fenced_line_numbers: tuple[int, ...]


@dataclass
class _Cell:
    is_header: bool
    rowspan: int
    colspan: int
    line_start: int
    text_parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())


@dataclass
class _Row:
    line_start: int
    in_thead: bool
    cells: list[_Cell] = field(default_factory=list)
    current_cell: _Cell | None = None
    line_end: int | None = None


@dataclass
class _TableDraft:
    line_start: int
    rows: list[_Row] = field(default_factory=list)
    current_row: _Row | None = None
    caption_parts: list[str] = field(default_factory=list)
    in_caption: bool = False
    thead_depth: int = 0


def _masked_fenced_code_with_lines(text: str) -> tuple[str, tuple[int, ...]]:
    masked: list[str] = []
    fenced_lines: list[int] = []
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            masked.append("")
            fenced_lines.append(line_number)
            in_fence = not in_fence
            continue
        if in_fence:
            masked.append("")
            fenced_lines.append(line_number)
        else:
            masked.append(line)
    return "\n".join(masked), tuple(fenced_lines)


def _masked_fenced_code(text: str) -> str:
    masked, _fenced_lines = _masked_fenced_code_with_lines(text)
    return masked


def _compact_text(value: str, *, limit: int = 40) -> str:
    compacted = " ".join(value.strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(limit - 1, 0)].rstrip() + "..."


def _safe_span(attrs: list[tuple[str, str | None]], name: str) -> int:
    values = {name.lower(): value for name, value in attrs if name}
    raw = values.get(name)
    if not raw:
        return 1
    try:
        return max(1, min(int(raw), 100))
    except ValueError:
        return 1


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[_TableDraft] = []
        self.tables: list[HtmlTableArtifact] = []
        self.unexpected_table_close_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        line, _offset = self.getpos()
        if name == "table":
            self._stack.append(_TableDraft(line_start=line))
            return
        if not self._stack:
            return
        table = self._stack[-1]
        if name == "thead":
            table.thead_depth += 1
        elif name == "caption":
            table.in_caption = True
        elif name == "tr":
            table.current_row = _Row(line_start=line, in_thead=table.thead_depth > 0)
        elif name in {"th", "td"}:
            if table.current_row is None:
                table.current_row = _Row(line_start=line, in_thead=table.thead_depth > 0)
            table.current_row.current_cell = _Cell(
                is_header=name == "th" or table.thead_depth > 0,
                rowspan=_safe_span(attrs, "rowspan"),
                colspan=_safe_span(attrs, "colspan"),
                line_start=line,
            )
        elif name == "br":
            self._append_text(" ")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "table" and not self._stack:
            self.unexpected_table_close_count += 1
            return
        if not self._stack:
            return
        table = self._stack[-1]
        line, _offset = self.getpos()
        if name in {"th", "td"}:
            self._close_cell(table)
        elif name == "tr":
            self._close_row(table, line_end=line)
        elif name == "caption":
            table.in_caption = False
        elif name == "thead":
            table.thead_depth = max(0, table.thead_depth - 1)
        elif name == "table":
            self._close_row(table, line_end=line)
            self._stack.pop()
            self.tables.append(_finalize_table(table, line_end=line))

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def finish(self, *, final_line: int) -> None:
        while self._stack:
            table = self._stack.pop()
            self._close_row(table, line_end=final_line)
            self.tables.append(_finalize_table(table, line_end=final_line))

    def _append_text(self, data: str) -> None:
        if not self._stack or not data:
            return
        table = self._stack[-1]
        if table.in_caption:
            table.caption_parts.append(data)
        row = table.current_row
        if row is not None and row.current_cell is not None:
            row.current_cell.text_parts.append(data)

    def _close_cell(self, table: _TableDraft) -> None:
        row = table.current_row
        if row is None or row.current_cell is None:
            return
        row.cells.append(row.current_cell)
        row.current_cell = None

    def _close_row(self, table: _TableDraft, *, line_end: int) -> None:
        row = table.current_row
        if row is None:
            return
        self._close_cell(table)
        row.line_end = line_end
        if row.cells:
            table.rows.append(row)
        table.current_row = None


def _finalize_table(table: _TableDraft, *, line_end: int) -> HtmlTableArtifact:
    row_widths = [sum(cell.colspan for cell in row.cells) for row in table.rows if row.cells]
    column_count = max(row_widths) if row_widths else 0
    cells = [cell for row in table.rows for cell in row.cells]
    cell_count = len(cells)
    rowspan_count = sum(1 for cell in cells if cell.rowspan > 1)
    colspan_count = sum(1 for cell in cells if cell.colspan > 1)
    header_depth = sum(1 for row in table.rows if row.in_thead or any(cell.is_header for cell in row.cells))
    header_row = next(
        (
            row
            for row in table.rows
            if row.in_thead or any(cell.is_header for cell in row.cells)
        ),
        None,
    )
    header_missing = header_row is None
    if header_row is None and table.rows:
        header_row = table.rows[0]
    header_preview = [_compact_text(cell.text) for cell in (header_row.cells if header_row else []) if cell.text][:8]
    caption = _compact_text(" ".join(table.caption_parts), limit=120) if table.caption_parts else None
    warnings: list[str] = []
    if not table.rows or column_count == 0:
        warnings.append("empty_table")
    if header_missing:
        warnings.append("header_missing")
    non_empty_widths = {width for width in row_widths if width > 0}
    if len(non_empty_widths) > 1:
        warnings.append("column_misalignment_suspected")
    if len(table.rows) > 50 or column_count > 12:
        warnings.append("large_table")
    return HtmlTableArtifact(
        line_start=max(table.line_start, 1),
        line_end=max(line_end, table.line_start),
        row_count=len(table.rows),
        column_count=column_count,
        cell_count=cell_count,
        rowspan_count=rowspan_count,
        colspan_count=colspan_count,
        header_depth=header_depth,
        header_preview=header_preview,
        caption=caption,
        warnings=tuple(warnings),
    )


def analyze_html_table_structure(text: str) -> HtmlTableAnalysis:
    """Return parsed tables plus balanced-structure and fenced-line diagnostics."""

    masked, fenced_line_numbers = _masked_fenced_code_with_lines(text)
    parser = _HtmlTableParser()
    unclosed_table_count = 0
    try:
        parser.feed(masked)
        parser.close()
        unclosed_table_count = len(parser._stack)
    finally:
        parser.finish(final_line=max(1, len(masked.splitlines())))
    unexpected_close_count = parser.unexpected_table_close_count
    return HtmlTableAnalysis(
        tables=tuple(sorted(parser.tables, key=lambda item: (item.line_start, item.line_end))),
        balanced=unclosed_table_count == 0 and unexpected_close_count == 0,
        unclosed_table_count=unclosed_table_count,
        unexpected_close_count=unexpected_close_count,
        fenced_line_numbers=fenced_line_numbers,
    )


def parse_html_tables(text: str) -> list[HtmlTableArtifact]:
    """Parse HTML table artifacts embedded in Markdown text."""

    if "<table" not in text.lower():
        return []
    return list(analyze_html_table_structure(text).tables)
