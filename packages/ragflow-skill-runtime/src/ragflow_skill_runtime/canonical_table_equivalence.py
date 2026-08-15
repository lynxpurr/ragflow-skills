"""Deterministic cell-matrix checks for canonical Markdown and advisory table evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import unicodedata


CANONICAL_TABLE_EQUIVALENCE_SCHEMA = "ragflow_canonical_table_equivalence_v1"
CANONICAL_TABLE_VLM_REQUEST_SCHEMA = "ragflow_canonical_table_vlm_request_v1"
CANONICAL_TABLE_VLM_CANDIDATE_SCHEMA = "ragflow_canonical_table_vlm_candidate_v1"
CANONICAL_TABLE_VLM_REVIEW_SCHEMA = "ragflow_canonical_table_vlm_review_v1"

_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")
_MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MARKDOWN_DELIMITER_RE = re.compile(r"^:?-{3,}:?$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PRIVATE_LITERAL_RE = re.compile(
    r"(?:/home/|/Users/|[A-Za-z]:\\|https?://|api[_-]?key|bearer|token|dataset_id|document_id|kb:)",
    re.IGNORECASE,
)


class CanonicalTableEquivalenceError(RuntimeError):
    """Raised when table-equivalence inputs cannot be validated safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_cell(value: Any) -> str:
    text = unescape(str(value or "")).replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = _HTML_TAG_RE.sub(" ", text).replace("\\|", "|")
    return " ".join(unicodedata.normalize("NFC", text).split())


def _split_markdown_row(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.strip().strip("|"):
        if character == "|" and not escaped:
            cells.append(_normalize_cell("".join(current)))
            current = []
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append(_normalize_cell("".join(current)))
    return cells


def _is_delimiter(line: str) -> bool:
    cells = _split_markdown_row(line)
    return bool(cells) and all(_MARKDOWN_DELIMITER_RE.fullmatch(cell.replace(" ", "")) for cell in cells)


def _mask_fenced_lines(text: str) -> list[str]:
    masked: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        match = _FENCE_RE.match(line)
        if fence_character is not None:
            masked.append("")
            if match:
                fence = match.group("fence")
                if fence[0] == fence_character and len(fence) >= fence_length:
                    fence_character = None
                    fence_length = 0
            continue
        if match:
            fence = match.group("fence")
            fence_character = fence[0]
            fence_length = len(fence)
            masked.append("")
        else:
            masked.append(line)
    return masked


def _matrix_payload(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> dict[str, Any]:
    normalized_headers = [_normalize_cell(item) for item in headers]
    normalized_rows = [[_normalize_cell(item) for item in row] for row in rows]
    width = len(normalized_headers)
    if not normalized_headers:
        raise CanonicalTableEquivalenceError("normalized table matrix requires at least one header")
    if any(len(row) != width for row in normalized_rows):
        raise CanonicalTableEquivalenceError("normalized table matrix rows must match header width")
    blank_positions = [
        {"row": row_index + 1, "column": column_index + 1}
        for row_index, row in enumerate(normalized_rows)
        for column_index, value in enumerate(row)
        if value == ""
    ]
    core = {"headers": normalized_headers, "rows": normalized_rows}
    return {
        **core,
        "row_count": len(normalized_rows),
        "column_count": width,
        "blank_positions": blank_positions,
        "matrix_sha256": _stable_sha256(core),
    }


def parse_markdown_table_matrices(text: str) -> list[dict[str, Any]]:
    """Parse pipe tables outside fenced code into normalized header/data matrices."""

    raw_lines = text.splitlines()
    masked_lines = _mask_fenced_lines(text)
    matrices: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(masked_lines):
        if not _MARKDOWN_TABLE_ROW_RE.match(masked_lines[cursor]):
            cursor += 1
            continue
        start = cursor
        while cursor < len(masked_lines) and _MARKDOWN_TABLE_ROW_RE.match(masked_lines[cursor]):
            cursor += 1
        if cursor - start < 2 or not _is_delimiter(masked_lines[start + 1]):
            continue
        headers = _split_markdown_row(raw_lines[start])
        rows = [_split_markdown_row(line) for line in raw_lines[start + 2 : cursor]]
        matrix = _matrix_payload(headers, rows)
        fragment = "\n".join(raw_lines[start:cursor])
        matrix.update(
            {
                "table_index": len(matrices) + 1,
                "line_start": start + 1,
                "line_end": cursor,
                "fragment_sha256": hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
                "merge_evidence": {"merged_cell_count": 0, "spans": []},
            }
        )
        matrices.append(matrix)
    return matrices


@dataclass
class _HtmlCell:
    header: bool
    rowspan: int
    colspan: int
    text: list[str] = field(default_factory=list)


@dataclass
class _HtmlRow:
    in_thead: bool
    cells: list[_HtmlCell] = field(default_factory=list)


@dataclass
class _HtmlTable:
    rows: list[_HtmlRow] = field(default_factory=list)
    current_row: _HtmlRow | None = None
    current_cell: _HtmlCell | None = None
    thead_depth: int = 0


def _span(attrs: Sequence[tuple[str, str | None]], name: str) -> int:
    raw = next((value for key, value in attrs if key.casefold() == name), None)
    try:
        return max(1, min(int(raw or 1), 100))
    except ValueError:
        return 1


class _HtmlMatrixParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_HtmlTable] = []
        self.tables: list[_HtmlTable] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name == "table":
            self.stack.append(_HtmlTable())
            return
        if not self.stack:
            return
        table = self.stack[-1]
        if name == "thead":
            table.thead_depth += 1
        elif name == "tr":
            table.current_row = _HtmlRow(in_thead=table.thead_depth > 0)
        elif name in {"th", "td"}:
            if table.current_row is None:
                table.current_row = _HtmlRow(in_thead=table.thead_depth > 0)
            table.current_cell = _HtmlCell(
                header=name == "th" or table.thead_depth > 0,
                rowspan=_span(attrs, "rowspan"),
                colspan=_span(attrs, "colspan"),
            )
        elif name == "br" and table.current_cell is not None:
            table.current_cell.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if not self.stack:
            return
        table = self.stack[-1]
        if name in {"th", "td"}:
            self._close_cell(table)
        elif name == "tr":
            self._close_row(table)
        elif name == "thead":
            table.thead_depth = max(0, table.thead_depth - 1)
        elif name == "table":
            self._close_row(table)
            self.tables.append(self.stack.pop())

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1].current_cell is not None:
            self.stack[-1].current_cell.text.append(data)

    def _close_cell(self, table: _HtmlTable) -> None:
        if table.current_row is not None and table.current_cell is not None:
            table.current_row.cells.append(table.current_cell)
        table.current_cell = None

    def _close_row(self, table: _HtmlTable) -> None:
        self._close_cell(table)
        if table.current_row is not None and table.current_row.cells:
            table.rows.append(table.current_row)
        table.current_row = None


def _html_table_matrix(table: _HtmlTable, *, table_index: int) -> dict[str, Any]:
    grid: list[list[str | None]] = []
    header_grid: list[list[bool]] = []
    spans: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows):
        while len(grid) <= row_index:
            grid.append([])
            header_grid.append([])
        column = 0
        for cell in row.cells:
            while column < len(grid[row_index]) and grid[row_index][column] is not None:
                column += 1
            value = _normalize_cell("".join(cell.text))
            if cell.rowspan > 1 or cell.colspan > 1:
                spans.append(
                    {
                        "row": row_index + 1,
                        "column": column + 1,
                        "rowspan": cell.rowspan,
                        "colspan": cell.colspan,
                        "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    }
                )
            for row_offset in range(cell.rowspan):
                target_row = row_index + row_offset
                while len(grid) <= target_row:
                    grid.append([])
                    header_grid.append([])
                width = column + cell.colspan
                if len(grid[target_row]) < width:
                    grid[target_row].extend([None] * (width - len(grid[target_row])))
                    header_grid[target_row].extend([False] * (width - len(header_grid[target_row])))
                for column_offset in range(cell.colspan):
                    target_column = column + column_offset
                    grid[target_row][target_column] = value
                    header_grid[target_row][target_column] = cell.header or row.in_thead
            column += cell.colspan
    width = max((len(row) for row in grid), default=0)
    if width == 0:
        raise CanonicalTableEquivalenceError(f"derived HTML table {table_index} is empty")
    for row, flags in zip(grid, header_grid):
        row.extend([None] * (width - len(row)))
        flags.extend([False] * (width - len(flags)))
    header_depth = 0
    for row, flags in zip(grid, header_grid):
        if any(flags) and all(flag or value in {None, ""} for value, flag in zip(row, flags)):
            header_depth += 1
        else:
            break
    if header_depth == 0:
        header_depth = 1
    headers: list[str] = []
    for column in range(width):
        parts: list[str] = []
        for row_index in range(min(header_depth, len(grid))):
            value = _normalize_cell(grid[row_index][column])
            if value and (not parts or parts[-1] != value):
                parts.append(value)
        headers.append(" / ".join(parts))
    rows = [[_normalize_cell(value) for value in row] for row in grid[header_depth:]]
    matrix = _matrix_payload(headers, rows)
    matrix.update(
        {
            "table_index": table_index,
            "merge_evidence": {
                "merged_cell_count": len(spans),
                "spans": spans,
                "normalization": "rowspan_expanded_and_multilevel_headers_flattened",
            },
        }
    )
    return matrix


def parse_html_table_matrices(text: str) -> list[dict[str, Any]]:
    """Parse HTML tables and normalize spans into standalone row/column facts."""

    parser = _HtmlMatrixParser()
    parser.feed(text)
    parser.close()
    if parser.stack:
        raise CanonicalTableEquivalenceError("derived HTML contains an unclosed table")
    return [_html_table_matrix(table, table_index=index) for index, table in enumerate(parser.tables, start=1)]


def _matrix_findings(
    canonical: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    table_id: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    canonical_headers = canonical.get("headers", [])
    candidate_headers = candidate.get("headers", [])
    canonical_rows = canonical.get("rows", [])
    candidate_rows = candidate.get("rows", [])
    if len(canonical_headers) != len(candidate_headers) or len(canonical_rows) != len(candidate_rows):
        findings.append(
            {
                "severity": "error",
                "code": "matrix_dimension_mismatch",
                "table_id": table_id,
                "message": "Table row or column dimensions differ after normalization.",
            }
        )
    for column, expected in enumerate(canonical_headers):
        actual = candidate_headers[column] if column < len(candidate_headers) else None
        if actual != expected:
            findings.append(
                {
                    "severity": "error",
                    "code": "header_value_mismatch",
                    "table_id": table_id,
                    "column": column + 1,
                    "message": "Normalized table header differs from canonical Markdown.",
                }
            )
    for row_index, expected_row in enumerate(canonical_rows):
        actual_row = candidate_rows[row_index] if row_index < len(candidate_rows) else []
        for column, expected in enumerate(expected_row):
            actual = actual_row[column] if column < len(actual_row) else None
            if actual != expected:
                findings.append(
                    {
                        "severity": "error",
                        "code": "cell_value_mismatch",
                        "table_id": table_id,
                        "row": row_index + 1,
                        "column": column + 1,
                        "message": "Normalized table cell differs from canonical Markdown.",
                    }
                )
    return findings


def compare_canonical_markdown_to_html(
    *,
    canonical_markdown_path: str | Path,
    derived_html_path: str | Path,
) -> dict[str, Any]:
    """Compare canonical Markdown tables to derived HTML tables in document order."""

    markdown_path = Path(canonical_markdown_path)
    html_path = Path(derived_html_path)
    canonical = parse_markdown_table_matrices(markdown_path.read_text(encoding="utf-8-sig"))
    derived = parse_html_table_matrices(html_path.read_text(encoding="utf-8-sig"))
    findings: list[dict[str, Any]] = []
    if not canonical:
        findings.append(
            {
                "severity": "error",
                "code": "canonical_table_missing",
                "message": "Canonical Markdown contains no table to validate.",
            }
        )
    if not derived:
        findings.append(
            {
                "severity": "error",
                "code": "derived_table_missing",
                "message": "Derived HTML contains no table to validate.",
            }
        )
    if len(canonical) != len(derived):
        findings.append(
            {
                "severity": "error",
                "code": "table_count_mismatch",
                "message": "Canonical Markdown and derived HTML table counts differ.",
            }
        )
    tables: list[dict[str, Any]] = []
    for index in range(max(len(canonical), len(derived))):
        table_id = f"table-{index + 1:03d}"
        if index >= len(canonical) or index >= len(derived):
            tables.append({"table_id": table_id, "equivalent": False})
            continue
        table_findings = _matrix_findings(canonical[index], derived[index], table_id=table_id)
        findings.extend(table_findings)
        tables.append(
            {
                "table_id": table_id,
                "equivalent": not table_findings,
                "canonical_matrix": canonical[index],
                "derived_matrix": derived[index],
                "derived_merge_evidence": derived[index]["merge_evidence"],
                "merge_relation_comparison": {
                    "status": "normalized_equivalent" if not table_findings else "blocked",
                    "canonical_representation": "flattened_headers_and_expanded_rows",
                    "derived_merged_cell_count": derived[index]["merge_evidence"]["merged_cell_count"],
                },
                "finding_count": len(table_findings),
            }
        )
    equivalent_count = sum(bool(item.get("equivalent")) for item in tables)
    ok = not findings and len(canonical) == len(derived)
    return {
        "schema": CANONICAL_TABLE_EQUIVALENCE_SCHEMA,
        "created_at": _now(),
        "ok": ok,
        "status": "equivalent" if ok else "blocked",
        "offline_only": True,
        "advisory_only": False,
        "inputs": {
            "canonical_markdown": {"name": markdown_path.name, "sha256": _file_sha256(markdown_path)},
            "derived_html": {"name": html_path.name, "sha256": _file_sha256(html_path)},
        },
        "summary": {
            "canonical_table_count": len(canonical),
            "derived_table_count": len(derived),
            "equivalent_table_count": equivalent_count,
            "blocked_table_count": len(tables) - equivalent_count,
            "finding_count": len(findings),
            "script_owned_llm_calls": 0,
        },
        "tables": tables,
        "findings": findings,
        "policy": {
            "canonical_truth": "source_reviewed_markdown",
            "derived_html_is_production_truth": False,
            "candidate_can_overwrite_canonical": False,
        },
    }


def _canonical_table(path: Path, table_index: int) -> dict[str, Any]:
    tables = parse_markdown_table_matrices(path.read_text(encoding="utf-8-sig"))
    if table_index < 1 or table_index > len(tables):
        raise CanonicalTableEquivalenceError("canonical table index is out of range")
    return tables[table_index - 1]


def create_table_vlm_request(
    *,
    canonical_markdown_path: str | Path,
    canonical_table_index: int,
    source_crop_path: str | Path,
    source_reference: str,
    table_id: str,
) -> dict[str, Any]:
    """Create a no-LLM request for one exact source crop and canonical table."""

    markdown_path = Path(canonical_markdown_path)
    crop_path = Path(source_crop_path)
    if not crop_path.is_file() or crop_path.is_symlink():
        raise CanonicalTableEquivalenceError("source crop must be an ordinary file")
    if not source_reference.strip() or not table_id.strip():
        raise CanonicalTableEquivalenceError("source reference and table id are required")
    table = _canonical_table(markdown_path, canonical_table_index)
    crop_mime, _encoding = mimetypes.guess_type(crop_path.name)
    core = {
        "canonical_markdown_sha256": _file_sha256(markdown_path),
        "canonical_table_index": canonical_table_index,
        "canonical_table_fragment_sha256": table["fragment_sha256"],
        "canonical_matrix_sha256": table["matrix_sha256"],
        "source_crop_sha256": _file_sha256(crop_path),
        "source_reference": source_reference.strip(),
        "table_id": table_id.strip(),
    }
    return {
        "schema": CANONICAL_TABLE_VLM_REQUEST_SCHEMA,
        "created_at": _now(),
        "ok": True,
        "advisory": True,
        "llm_invoked": False,
        "request_hash": _stable_sha256(core),
        "table_id": core["table_id"],
        "source_reference": core["source_reference"],
        "source_crop": {
            "name": crop_path.name,
            "sha256": core["source_crop_sha256"],
            "size_bytes": crop_path.stat().st_size,
            "mime_type": crop_mime,
        },
        "canonical": {
            "markdown_name": markdown_path.name,
            "markdown_sha256": core["canonical_markdown_sha256"],
            "table_index": canonical_table_index,
            "table_fragment_sha256": core["canonical_table_fragment_sha256"],
            "matrix_sha256": core["canonical_matrix_sha256"],
        },
        "summary": {"script_owned_llm_calls": 0, "source_crop_count": 1, "table_count": 1},
        "instructions": {
            "required_output_schema": CANONICAL_TABLE_VLM_CANDIDATE_SCHEMA,
            "required_flags": {"advisory": True, "generated": True},
            "required_matrix_fields": ["headers", "rows", "merged_cells"],
            "requirements": [
                "Extract only the exact supplied source crop.",
                "Preserve headers, rows, merged relationships, values, units, footnotes, and blanks.",
                "Return advisory generated evidence; do not rewrite canonical Markdown.",
                "Bind the candidate to the exact request file SHA-256 and source crop SHA-256.",
            ],
        },
        "policy": {
            "adapter": "request_review",
            "script_owned_backend": "disabled",
            "script_owned_llm_calls": 0,
            "candidate_can_overwrite_canonical": False,
        },
    }


def _load_json_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalTableEquivalenceError(f"{label} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise CanonicalTableEquivalenceError(f"{label} must be a JSON object")
    return payload


def _private_provenance_findings(provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, str) and _PRIVATE_LITERAL_RE.search(value):
            findings.append(
                {
                    "severity": "error",
                    "code": "private_literal",
                    "field": path,
                    "message": "Candidate provenance contains a private path, endpoint, credential hint, or live identifier.",
                }
            )

    visit(provenance, "candidate.provenance")
    return findings


def review_table_vlm_candidate(
    *,
    request_path: str | Path,
    candidate_path: str | Path,
    canonical_markdown_path: str | Path,
) -> dict[str, Any]:
    """Review an advisory external table matrix against deterministic canonical evidence."""

    request = _load_json_mapping(request_path, label="VLM request")
    candidate = _load_json_mapping(candidate_path, label="VLM candidate")
    markdown_path = Path(canonical_markdown_path)
    findings: list[dict[str, Any]] = []

    def error(code: str, message: str, field: str | None = None) -> None:
        item = {"severity": "error", "code": code, "message": message}
        if field:
            item["field"] = field
        findings.append(item)

    if (
        request.get("schema") != CANONICAL_TABLE_VLM_REQUEST_SCHEMA
        or request.get("llm_invoked") is not False
        or request.get("advisory") is not True
    ):
        error("invalid_vlm_request", "VLM request must be a no-LLM canonical request artifact.")
    canonical_identity = request.get("canonical") if isinstance(request.get("canonical"), Mapping) else {}
    source_crop = request.get("source_crop") if isinstance(request.get("source_crop"), Mapping) else {}
    table_index = canonical_identity.get("table_index")
    if not isinstance(table_index, int) or isinstance(table_index, bool):
        error("invalid_vlm_request", "VLM request canonical table index is invalid.")
        table_index = 0
    request_core = {
        "canonical_markdown_sha256": canonical_identity.get("markdown_sha256"),
        "canonical_table_index": table_index,
        "canonical_table_fragment_sha256": canonical_identity.get("table_fragment_sha256"),
        "canonical_matrix_sha256": canonical_identity.get("matrix_sha256"),
        "source_crop_sha256": source_crop.get("sha256"),
        "source_reference": request.get("source_reference"),
        "table_id": request.get("table_id"),
    }
    required_request_hashes = (
        request_core["canonical_markdown_sha256"],
        request_core["canonical_table_fragment_sha256"],
        request_core["canonical_matrix_sha256"],
        request_core["source_crop_sha256"],
        request.get("request_hash"),
    )
    request_binding_valid = (
        table_index > 0
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in required_request_hashes)
        and isinstance(request_core["source_reference"], str)
        and bool(request_core["source_reference"].strip())
        and isinstance(request_core["table_id"], str)
        and bool(request_core["table_id"].strip())
    )
    if not request_binding_valid:
        error("invalid_vlm_request_binding", "VLM request binding fields are incomplete or invalid.")
    elif _stable_sha256(request_core) != request.get("request_hash"):
        error("vlm_request_hash_mismatch", "VLM request fields no longer match its request hash.")
    if _file_sha256(markdown_path) != canonical_identity.get("markdown_sha256"):
        error("stale_canonical_markdown", "Canonical Markdown no longer matches the VLM request.")
    canonical_table: dict[str, Any] | None = None
    try:
        canonical_table = _canonical_table(markdown_path, table_index)
    except CanonicalTableEquivalenceError as exc:
        error("invalid_canonical_table", str(exc))
    if canonical_table is not None:
        if canonical_table.get("fragment_sha256") != canonical_identity.get("table_fragment_sha256"):
            error("stale_canonical_fragment", "Canonical table fragment no longer matches the VLM request.")
        if canonical_table.get("matrix_sha256") != canonical_identity.get("matrix_sha256"):
            error("stale_canonical_matrix", "Canonical table matrix no longer matches the VLM request.")

    if candidate.get("schema") != CANONICAL_TABLE_VLM_CANDIDATE_SCHEMA:
        error("candidate_schema_invalid", f"Candidate schema must be {CANONICAL_TABLE_VLM_CANDIDATE_SCHEMA}.")
    if candidate.get("advisory") is not True:
        error("candidate_not_advisory", "VLM candidate must set advisory=true.")
    if candidate.get("generated") is not True:
        error("candidate_not_generated", "VLM candidate must set generated=true.")
    if candidate.get("request_sha256") != _file_sha256(request_path):
        error("candidate_request_hash_mismatch", "VLM candidate does not bind the exact request file.")
    if candidate.get("table_id") != request.get("table_id"):
        error("candidate_table_id_mismatch", "VLM candidate table id does not match the request.")
    if candidate.get("source_crop_sha256") != source_crop.get("sha256"):
        error("candidate_source_crop_hash_mismatch", "VLM candidate does not bind the exact source crop.")
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), Mapping) else {}
    for field_name in ("provider_label", "model_label", "operation"):
        if not str(provenance.get(field_name) or "").strip():
            error("candidate_provenance_incomplete", "VLM candidate provenance is incomplete.", f"candidate.provenance.{field_name}")
    findings.extend(_private_provenance_findings(provenance))

    candidate_matrix: dict[str, Any] | None = None
    candidate_merged_cells: list[Any] = []
    raw_matrix = candidate.get("matrix")
    if isinstance(raw_matrix, Mapping):
        headers = raw_matrix.get("headers")
        rows = raw_matrix.get("rows")
        merged_cells = raw_matrix.get("merged_cells")
        if not isinstance(merged_cells, list):
            error("candidate_merge_evidence_invalid", "VLM candidate matrix must include a merged_cells list.")
        else:
            candidate_merged_cells = merged_cells
            for index, item in enumerate(merged_cells, start=1):
                if not isinstance(item, Mapping) or any(
                    not isinstance(item.get(field_name), int)
                    or isinstance(item.get(field_name), bool)
                    or int(item[field_name]) < 1
                    for field_name in ("row", "column", "rowspan", "colspan")
                ):
                    error(
                        "candidate_merge_evidence_invalid",
                        f"VLM candidate merged_cells[{index}] has invalid coordinates or spans.",
                    )
                elif item["rowspan"] == 1 and item["colspan"] == 1:
                    error(
                        "candidate_merge_evidence_invalid",
                        f"VLM candidate merged_cells[{index}] does not describe a merged cell.",
                    )
        if (
            isinstance(headers, list)
            and all(isinstance(item, str) for item in headers)
            and isinstance(rows, list)
            and all(
                isinstance(row, list) and all(isinstance(item, str) for item in row)
                for row in rows
            )
        ):
            try:
                candidate_matrix = _matrix_payload(headers, rows)
            except CanonicalTableEquivalenceError as exc:
                error("candidate_matrix_invalid", str(exc))
        else:
            error("candidate_matrix_invalid", "VLM candidate matrix headers and rows are invalid.")
    else:
        error("candidate_matrix_invalid", "VLM candidate matrix is missing.")

    matrix_findings: list[dict[str, Any]] = []
    if canonical_table is not None and candidate_matrix is not None:
        matrix_findings = _matrix_findings(
            canonical_table,
            candidate_matrix,
            table_id=str(request.get("table_id") or "table"),
        )
        if matrix_findings:
            error("candidate_matrix_mismatch", "Advisory VLM matrix differs from canonical Markdown and requires source-backed human resolution.")
    findings.extend(matrix_findings)
    ok = not any(item.get("severity") == "error" for item in findings)
    return {
        "schema": CANONICAL_TABLE_VLM_REVIEW_SCHEMA,
        "created_at": _now(),
        "ok": ok,
        "status": "accepted_advisory" if ok else "blocked",
        "offline_only": True,
        "request": {
            "schema": request.get("schema"),
            "sha256": _file_sha256(request_path),
            "table_id": request.get("table_id"),
            "source_crop_sha256": source_crop.get("sha256"),
        },
        "candidate": {
            "schema": candidate.get("schema"),
            "sha256": _file_sha256(candidate_path),
            "advisory": candidate.get("advisory"),
            "generated": candidate.get("generated"),
            "matrix_sha256": candidate_matrix.get("matrix_sha256") if candidate_matrix else None,
            "merged_cell_count": len(candidate_merged_cells),
            "provenance": dict(provenance),
        },
        "canonical": {
            "markdown_sha256": _file_sha256(markdown_path),
            "matrix_sha256": canonical_table.get("matrix_sha256") if canonical_table else None,
        },
        "summary": {
            "finding_count": len(findings),
            "error_count": sum(item.get("severity") == "error" for item in findings),
            "matrix_equivalent": not matrix_findings and candidate_matrix is not None,
            "merge_relations_retained_for_source_review": isinstance(candidate.get("matrix"), Mapping)
            and isinstance(candidate.get("matrix", {}).get("merged_cells"), list),
            "script_owned_llm_calls": 0,
        },
        "findings": findings,
        "policy": {
            "canonical_truth": "source_reviewed_markdown",
            "candidate_is_advisory": True,
            "candidate_can_overwrite_canonical": False,
            "human_source_resolution_required_on_difference": True,
        },
    }


def render_canonical_table_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a sanitized concise summary for any canonical table report mode."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Canonical Table Evidence",
        "",
        f"- schema: `{report.get('schema', 'unknown')}`",
        f"- status: `{report.get('status', 'request_ready')}`",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
        f"- findings: `{summary.get('finding_count', 0)}`",
        f"- script-owned LLM calls: `{summary.get('script_owned_llm_calls', 0)}`",
    ]
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    if findings:
        lines.extend(["", "## Findings", ""])
        for item in findings[:20]:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('severity')}` `{item.get('code')}`: {item.get('message')}")
    return "\n".join(lines) + "\n"
