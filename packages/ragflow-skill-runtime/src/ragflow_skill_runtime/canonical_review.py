"""Hash-bound canonical review acceptance records and local output materialization."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlsplit


CANONICAL_REVIEW_SCHEMA = "ragflow_canonical_review_v1"
CANONICAL_MARKDOWN_AUDIT_SCHEMA = "ragflow_canonical_markdown_audit_v1"
CANONICAL_ASSET_AUDIT_SCHEMA = "ragflow_canonical_asset_audit_v1"
CANONICAL_REVIEW_STATUSES = {
    "accepted",
    "blocked",
    "needs_source_verification",
}
TABLE_ACTIONS = {
    "converted_to_markdown",
    "retained_html_by_exception",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FENCE_OPEN_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*$")
_MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MARKDOWN_TABLE_DELIMITER_RE = re.compile(r"^:?-{3,}:?$")
_INLINE_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<plain>[^)\r\n]+))\s*\)"
)
_REFERENCE_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\[(?P<label>[^\]]*)\]")
_REFERENCE_DEF_RE = re.compile(
    r"^\s*\[(?P<label>[^\]]+)\]:\s*(?:<(?P<angled>[^>]+)>|(?P<plain>\S+))",
    re.MULTILINE,
)
_HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?:\"(?P<double>[^\"]+)\"|'(?P<single>[^']+)'|(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)


class CanonicalReviewError(RuntimeError):
    """Raised when canonical review inputs cannot be read or materialized safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_file_sha256(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of exact file bytes."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fragment_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_normalized_markdown(path: Path) -> str:
    raw = path.read_bytes().decode("utf-8-sig")
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _load_json_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CanonicalReviewError(f"{label} not found: {candidate}") from exc
    except json.JSONDecodeError as exc:
        raise CanonicalReviewError(f"{label} is not valid JSON: {candidate}") from exc
    if not isinstance(payload, dict):
        raise CanonicalReviewError(f"{label} must be a JSON object: {candidate}")
    return payload


def _normalize_sha256(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if _SHA256_RE.fullmatch(normalized) else None


def _finding(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message, "blocking": True}
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload


def _mask_fenced_code(text: str) -> str:
    masked: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        newline = line[len(content) :]
        if fence_character is not None:
            masked.append(" " * len(content) + newline)
            closing = _FENCE_CLOSE_RE.match(content)
            if closing:
                fence = closing.group("fence")
                if fence[0] == fence_character and len(fence) >= fence_length:
                    fence_character = None
                    fence_length = 0
            continue
        opening = _FENCE_OPEN_RE.match(content)
        if opening:
            fence = opening.group("fence")
            fence_character = fence[0]
            fence_length = len(fence)
            masked.append(" " * len(content) + newline)
            continue
        masked.append(line)
    return "".join(masked)


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    offsets.extend(match.end() for match in re.finditer("\n", text))
    return offsets


class _HtmlTableBlockParser(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.text = text
        self.offsets = _line_offsets(text)
        self.stack: list[int] = []
        self.blocks: list[str] = []
        self.unexpected_close_count = 0

    def _offset(self) -> int:
        line, column = self.getpos()
        base = self.offsets[min(max(line - 1, 0), len(self.offsets) - 1)]
        return base + column

    def _tag_end(self, start: int) -> int:
        end = self.text.find(">", start)
        return len(self.text) if end < 0 else end + 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "table":
            self.stack.append(self._offset())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "table":
            start = self._offset()
            self.blocks.append(self.text[start : self._tag_end(start)])

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "table":
            return
        if not self.stack:
            self.unexpected_close_count += 1
            return
        start = self.stack.pop()
        end = self._tag_end(self._offset())
        self.blocks.append(self.text[start:end])


def _html_table_fragments(text: str) -> tuple[list[str], bool]:
    masked = _mask_fenced_code(text)
    parser = _HtmlTableBlockParser(masked)
    parser.feed(masked)
    parser.close()
    return parser.blocks, not parser.stack and parser.unexpected_close_count == 0


def _split_markdown_row(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.strip().strip("|"):
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def _is_markdown_delimiter(line: str) -> bool:
    cells = _split_markdown_row(line)
    return bool(cells) and all(
        _MARKDOWN_TABLE_DELIMITER_RE.fullmatch(cell.replace(" ", ""))
        for cell in cells
    )


def _markdown_table_fragments(text: str) -> list[str]:
    raw_lines = text.splitlines()
    masked_lines = _mask_fenced_code(text).splitlines()
    fragments: list[str] = []
    cursor = 0
    while cursor < len(masked_lines):
        if not _MARKDOWN_TABLE_ROW_RE.match(masked_lines[cursor]):
            cursor += 1
            continue
        start = cursor
        while cursor < len(masked_lines) and _MARKDOWN_TABLE_ROW_RE.match(masked_lines[cursor]):
            cursor += 1
        if cursor - start >= 2 and _is_markdown_delimiter(masked_lines[start + 1]):
            fragments.append("\n".join(raw_lines[start:cursor]))
    return fragments


def _safe_relative_path(value: Any) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    return path.as_posix()


def _image_target(value: str) -> str:
    raw = value.strip().replace("\\ ", " ").replace("\\(", "(").replace("\\)", ")")
    titled = re.match(r"^(.*?)(?:\s+[\"'].*[\"'])$", raw)
    return (titled.group(1) if titled else raw).strip()


def _local_image_paths(text: str, *, markdown: Path, asset_root: Path) -> tuple[set[str], list[dict[str, Any]]]:
    targets: list[str] = []
    for match in _INLINE_IMAGE_RE.finditer(text):
        targets.append(_image_target(match.group("angled") or match.group("plain") or ""))
    definitions = {
        match.group("label").strip().casefold(): match.group("angled") or match.group("plain") or ""
        for match in _REFERENCE_DEF_RE.finditer(text)
    }
    for match in _REFERENCE_IMAGE_RE.finditer(text):
        label = (match.group("label") or match.group("alt")).strip().casefold()
        if label in definitions:
            targets.append(_image_target(definitions[label]))
    for match in _HTML_IMAGE_RE.finditer(text):
        targets.append(match.group("double") or match.group("single") or match.group("bare") or "")

    selected: set[str] = set()
    findings: list[dict[str, Any]] = []
    for target in targets:
        parsed = urlsplit(target)
        if parsed.scheme.casefold() in {"data", "http", "https"} or target.startswith("//"):
            continue
        decoded = unquote(parsed.path).replace("\\", os.sep).replace("/", os.sep)
        if not decoded or decoded.startswith("#"):
            continue
        resolved = (markdown.parent / decoded).resolve(strict=False)
        try:
            relative = resolved.relative_to(asset_root).as_posix()
        except ValueError:
            findings.append(
                _finding(
                    "unsafe_image_reference",
                    "Accepted Markdown contains a local image reference outside the audited asset root.",
                    target=target,
                )
            )
            continue
        selected.add(relative)
    return selected, findings


def _validate_source_coverage(
    payload: Mapping[str, Any],
    *,
    source_sha256: str | None,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip()
    covered = payload.get("covered_units")
    uncovered = payload.get("uncovered_units")
    if status not in {"complete", "incomplete"}:
        findings.append(_finding("invalid_source_coverage", "Source coverage status must be complete or incomplete."))
    if not isinstance(covered, list) or any(not isinstance(item, str) or not item.strip() for item in covered):
        findings.append(_finding("invalid_source_coverage", "covered_units must contain non-empty strings."))
        covered = []
    if not isinstance(uncovered, list) or any(not isinstance(item, str) or not item.strip() for item in uncovered):
        findings.append(_finding("invalid_source_coverage", "uncovered_units must contain non-empty strings."))
        uncovered = []
    coverage_source_hash = _normalize_sha256(payload.get("source_sha256"))
    if source_sha256 is not None and coverage_source_hash != source_sha256:
        findings.append(
            _finding(
                "source_coverage_hash_mismatch",
                "Source coverage does not bind the exact supplied source bytes.",
                expected_sha256=source_sha256,
                actual_sha256=coverage_source_hash,
            )
        )
    if status != "complete" or uncovered:
        findings.append(
            _finding(
                "incomplete_source_coverage",
                "Accepted canonical review requires complete coverage and no uncovered source units.",
                uncovered_unit_count=len(uncovered),
            )
        )
    return {
        "status": status or "invalid",
        "source_sha256": coverage_source_hash,
        "covered_unit_count": len(covered),
        "uncovered_unit_count": len(uncovered),
        "covered_units": list(covered),
        "uncovered_units": list(uncovered),
    }


def _normalize_table_decisions(
    payload: Mapping[str, Any],
    *,
    candidate_text: str,
    accepted_text: str,
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    raw_decisions = payload.get("decisions")
    raw_unresolved = payload.get("unresolved_items", [])
    if not isinstance(raw_decisions, list):
        findings.append(_finding("invalid_table_decisions", "table decisions must be a list."))
        raw_decisions = []
    if not isinstance(raw_unresolved, list):
        findings.append(_finding("invalid_table_decisions", "unresolved_items must be a list."))
        raw_unresolved = []
    unresolved = [dict(item) if isinstance(item, Mapping) else {"reason": str(item)} for item in raw_unresolved]

    candidate_html, candidate_balanced = _html_table_fragments(candidate_text)
    accepted_html, accepted_balanced = _html_table_fragments(accepted_text)
    accepted_markdown = _markdown_table_fragments(accepted_text)
    if not candidate_balanced or not accepted_balanced:
        findings.append(_finding("malformed_html_table", "Candidate and accepted HTML tables must be structurally balanced."))

    candidate_hashes = Counter(_fragment_sha256(item) for item in candidate_html)
    accepted_html_hashes = Counter(_fragment_sha256(item) for item in accepted_html)
    accepted_markdown_hashes = Counter(_fragment_sha256(item) for item in accepted_markdown)
    decision_before: Counter[str] = Counter()
    retained_after: Counter[str] = Counter()
    converted_after: Counter[str] = Counter()
    normalized: list[dict[str, str]] = []
    ids: set[str] = set()

    for index, item in enumerate(raw_decisions, start=1):
        if not isinstance(item, Mapping):
            findings.append(_finding("invalid_table_decision", f"Table decision {index} must be an object."))
            continue
        table_id = str(item.get("table_id") or "").strip()
        action = str(item.get("action") or "").strip()
        source_reference = str(item.get("source_reference") or "").strip()
        reason = str(item.get("reason") or "").strip()
        before_hash = _normalize_sha256(item.get("before_sha256"))
        after_hash = _normalize_sha256(item.get("after_sha256"))
        if not table_id or table_id in ids:
            findings.append(_finding("invalid_table_decision", f"Table decision {index} has a missing or duplicate table_id."))
        else:
            ids.add(table_id)
        if action not in TABLE_ACTIONS:
            findings.append(_finding("invalid_table_decision", f"Table decision {index} has an unsupported action."))
        if not source_reference or not reason:
            findings.append(_finding("invalid_table_decision", f"Table decision {index} needs a source reference and reason."))
        if before_hash is None or after_hash is None:
            findings.append(_finding("invalid_table_decision", f"Table decision {index} needs valid before/after SHA-256 values."))
            continue
        decision_before[before_hash] += 1
        if action == "retained_html_by_exception":
            retained_after[after_hash] += 1
        elif action == "converted_to_markdown":
            converted_after[after_hash] += 1
        normalized.append(
            {
                "table_id": table_id,
                "action": action,
                "source_reference": source_reference,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "reason": reason,
            }
        )

    unreviewed_candidate = candidate_hashes - decision_before
    stale_before = decision_before - candidate_hashes
    unreviewed_accepted = accepted_html_hashes - retained_after
    stale_retained = retained_after - accepted_html_hashes
    stale_converted = converted_after - accepted_markdown_hashes
    if unreviewed_candidate or unreviewed_accepted:
        findings.append(
            _finding(
                "unreviewed_html_table",
                "Every candidate and accepted HTML table requires one explicit source-backed decision.",
                candidate_unreviewed_count=sum(unreviewed_candidate.values()),
                accepted_unreviewed_count=sum(unreviewed_accepted.values()),
            )
        )
    if stale_before:
        findings.append(_finding("stale_table_before_hash", "A table decision does not match a candidate HTML table."))
    if stale_retained:
        findings.append(_finding("stale_retained_html_hash", "A retained-HTML decision does not match accepted Markdown."))
    if stale_converted:
        findings.append(_finding("stale_converted_table_hash", "A converted-table decision does not match a Markdown table."))
    if unresolved:
        findings.append(
            _finding(
                "unresolved_review_items",
                "Canonical acceptance cannot proceed while explicit review items remain unresolved.",
                unresolved_item_count=len(unresolved),
            )
        )
    return normalized, unresolved


def _selected_asset_records(
    asset_audit: Mapping[str, Any],
    *,
    accepted_text: str,
    reviewed_markdown: Path,
    asset_root: Path,
    findings: list[dict[str, Any]],
) -> list[dict[str, str]]:
    audit_root = Path(str(asset_audit.get("root") or "")).resolve(strict=False)
    if audit_root != asset_root:
        findings.append(_finding("asset_audit_root_mismatch", "Asset audit root does not match the reviewed asset root."))
    if not asset_audit.get("allowlist"):
        findings.append(_finding("asset_allowlist_missing", "Canonical asset acceptance requires a positive Markdown allowlist."))
    summary = asset_audit.get("summary")
    if not isinstance(summary, Mapping):
        findings.append(_finding("invalid_asset_audit", "Asset audit summary is missing."))
        summary = {}
    if int(summary.get("missing_reference_count") or 0) != 0:
        findings.append(_finding("asset_audit_missing_reference", "Asset audit contains missing local references."))
    if summary.get("markdown_not_in_active_allowlist_count") not in {0, None}:
        findings.append(_finding("asset_allowlist_incomplete", "Asset audit includes Markdown outside the active allowlist."))

    selected_paths, reference_findings = _local_image_paths(
        accepted_text,
        markdown=reviewed_markdown,
        asset_root=asset_root,
    )
    findings.extend(reference_findings)
    raw_images = asset_audit.get("images")
    images_by_path: dict[str, Mapping[str, Any]] = {}
    if not isinstance(raw_images, list):
        findings.append(_finding("invalid_asset_audit", "Asset audit images must be a list."))
        raw_images = []
    for item in raw_images:
        if not isinstance(item, Mapping):
            continue
        relative = _safe_relative_path(item.get("path"))
        if relative is not None:
            images_by_path[relative] = item

    records: list[dict[str, str]] = []
    for relative in sorted(selected_paths):
        audit_item = images_by_path.get(relative)
        if audit_item is None or int(audit_item.get("reference_count") or 0) <= 0:
            findings.append(
                _finding(
                    "selected_asset_not_audited",
                    "A selected Markdown image is absent from the positive asset audit.",
                    path=relative,
                )
            )
            continue
        expected_hash = _normalize_sha256(audit_item.get("sha256"))
        asset_path = asset_root / Path(relative)
        resolved = asset_path.resolve(strict=False)
        try:
            resolved.relative_to(asset_root)
        except ValueError:
            findings.append(_finding("unsafe_selected_asset", "A selected asset escapes the audited asset root.", path=relative))
            continue
        if asset_path.is_symlink() or not asset_path.is_file():
            findings.append(_finding("missing_selected_asset", "A selected asset is missing or not an ordinary file.", path=relative))
            continue
        actual_hash = canonical_file_sha256(asset_path)
        if expected_hash is None or expected_hash != actual_hash:
            findings.append(
                _finding(
                    "stale_asset_hash",
                    "A selected asset no longer matches the asset audit hash.",
                    path=relative,
                    expected_sha256=expected_hash,
                    actual_sha256=actual_hash,
                )
            )
            continue
        records.append({"path": relative, "sha256": actual_hash})
    return records


def validate_canonical_review_record(payload: Mapping[str, Any]) -> None:
    """Validate the stable shape and acceptance invariants of one review record."""

    if payload.get("schema") != CANONICAL_REVIEW_SCHEMA:
        raise CanonicalReviewError(f"canonical review schema must be {CANONICAL_REVIEW_SCHEMA}")
    status = payload.get("status")
    if status not in CANONICAL_REVIEW_STATUSES:
        raise CanonicalReviewError("canonical review status is invalid")
    if payload.get("ok") is not (status == "accepted"):
        raise CanonicalReviewError("canonical review ok flag does not match status")
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise CanonicalReviewError("canonical review summary is missing")
    unresolved_count = summary.get("unresolved_item_count")
    if not isinstance(unresolved_count, int) or unresolved_count < 0:
        raise CanonicalReviewError("canonical review unresolved count is invalid")
    if status == "accepted" and unresolved_count != 0:
        raise CanonicalReviewError("accepted canonical review cannot contain unresolved items")
    markdown = payload.get("markdown")
    if not isinstance(markdown, Mapping):
        raise CanonicalReviewError("canonical review markdown identity is missing")
    for label in ("candidate", "accepted"):
        identity = markdown.get(label)
        if not isinstance(identity, Mapping) or _normalize_sha256(identity.get("sha256")) is None:
            raise CanonicalReviewError(f"canonical review {label} Markdown hash is invalid")


def _require_record_mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise CanonicalReviewError(f"canonical review {field} is missing")
    return value


def _require_record_sha256(payload: Mapping[str, Any], field: str) -> str:
    value = _normalize_sha256(payload.get(field))
    if value is None:
        raise CanonicalReviewError(f"canonical review {field} hash is invalid")
    return value


def _validate_bound_audit(
    record: Mapping[str, Any],
    *,
    record_key: str,
    path: Path,
    label: str,
    schema: str,
) -> dict[str, Any]:
    audits = _require_record_mapping(record, "audit_reports")
    identity = audits.get(record_key)
    if not isinstance(identity, Mapping):
        raise CanonicalReviewError(f"canonical review {label} identity is missing")
    if identity.get("schema") != schema:
        raise CanonicalReviewError(f"canonical review {label} schema must be {schema}")
    expected_hash = _require_record_sha256(identity, "report_sha256")
    if not path.is_file():
        raise CanonicalReviewError(f"canonical review {label} not found: {path}")
    actual_hash = canonical_file_sha256(path)
    if actual_hash != expected_hash:
        raise CanonicalReviewError(f"canonical review {label} hash does not match the review record")
    payload = _load_json_mapping(path, label=label)
    if payload.get("schema") != schema:
        raise CanonicalReviewError(f"canonical review {label} payload schema must be {schema}")
    return payload


def validate_canonical_review_build_binding(
    *,
    review_record_path: str | Path,
    source_path: str | Path,
    accepted_markdown_path: str | Path,
    markdown_audit_path: str | Path,
    asset_audit_path: str | Path,
) -> str:
    """Validate canonical evidence for one build and return the exact record hash."""

    review_path = Path(review_record_path)
    try:
        review_bytes = review_path.read_bytes()
    except FileNotFoundError as exc:
        raise CanonicalReviewError(f"canonical review not found: {review_path}") from exc
    try:
        record = json.loads(review_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalReviewError(f"canonical review is not valid JSON: {review_path}") from exc
    if not isinstance(record, dict):
        raise CanonicalReviewError(f"canonical review must be a JSON object: {review_path}")
    validate_canonical_review_record(record)
    if record.get("status") != "accepted":
        raise CanonicalReviewError("canonical review status must be accepted before build")

    summary = _require_record_mapping(record, "summary")
    if summary.get("unresolved_item_count") != 0:
        raise CanonicalReviewError("canonical review contains unresolved items")
    findings = record.get("findings")
    if not isinstance(findings, list) or findings or summary.get("finding_count") != 0:
        raise CanonicalReviewError("canonical review contains unresolved findings")

    source = _require_record_mapping(record, "source")
    if source.get("available") is not True:
        raise CanonicalReviewError("canonical review exact source is not verified")
    expected_source_hash = _require_record_sha256(source, "sha256")
    supplied_source = Path(source_path)
    if not supplied_source.is_file():
        raise CanonicalReviewError(f"canonical review source not found: {supplied_source}")
    actual_source_hash = canonical_file_sha256(supplied_source)
    if actual_source_hash != expected_source_hash:
        raise CanonicalReviewError("canonical review source hash does not match the review record")

    coverage = _require_record_mapping(record, "source_coverage")
    if coverage.get("status") != "complete":
        raise CanonicalReviewError("canonical review source coverage is incomplete")
    if coverage.get("uncovered_unit_count") != 0 or coverage.get("uncovered_units") != []:
        raise CanonicalReviewError("canonical review contains uncovered source units")
    if _require_record_sha256(coverage, "source_sha256") != actual_source_hash:
        raise CanonicalReviewError("canonical review source coverage hash does not match the supplied source")
    _require_record_sha256(coverage, "record_sha256")

    markdown = _require_record_mapping(record, "markdown")
    accepted_identity = markdown.get("accepted")
    if not isinstance(accepted_identity, Mapping):
        raise CanonicalReviewError("canonical review accepted Markdown identity is missing")
    accepted_relative = _safe_relative_path(accepted_identity.get("path"))
    if accepted_relative is None:
        raise CanonicalReviewError("canonical review accepted Markdown path is unsafe")
    expected_markdown_hash = _require_record_sha256(accepted_identity, "sha256")
    accepted_markdown = Path(accepted_markdown_path)
    if not accepted_markdown.is_file():
        raise CanonicalReviewError(f"canonical review accepted Markdown not found: {accepted_markdown}")
    actual_markdown_hash = canonical_file_sha256(accepted_markdown)
    if actual_markdown_hash != expected_markdown_hash:
        raise CanonicalReviewError("canonical review accepted Markdown hash does not match the build input")

    markdown_audit = _validate_bound_audit(
        record,
        record_key="markdown_structure",
        path=Path(markdown_audit_path),
        label="Markdown audit",
        schema=CANONICAL_MARKDOWN_AUDIT_SCHEMA,
    )
    audit_markdown = markdown_audit.get("markdown")
    if not isinstance(audit_markdown, Mapping) or _normalize_sha256(audit_markdown.get("sha256")) != actual_markdown_hash:
        raise CanonicalReviewError("canonical review Markdown audit hash does not match the build input")
    audit_source = markdown_audit.get("source")
    if not isinstance(audit_source, Mapping) or _normalize_sha256(audit_source.get("sha256")) != actual_source_hash:
        raise CanonicalReviewError("canonical review Markdown audit source hash does not match the supplied source")

    _validate_bound_audit(
        record,
        record_key="canonical_assets",
        path=Path(asset_audit_path),
        label="asset audit",
        schema=CANONICAL_ASSET_AUDIT_SCHEMA,
    )

    table_review = _require_record_mapping(record, "table_review")
    _require_record_sha256(table_review, "record_sha256")
    decisions = table_review.get("decisions")
    unresolved_items = table_review.get("unresolved_items")
    if not isinstance(decisions, list):
        raise CanonicalReviewError("canonical review table decisions must be a list")
    if unresolved_items != []:
        raise CanonicalReviewError("canonical review table review contains unresolved items")
    for index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, Mapping):
            raise CanonicalReviewError(f"canonical review table decision {index} is invalid")
        if decision.get("action") not in TABLE_ACTIONS:
            raise CanonicalReviewError(f"canonical review table decision {index} action is invalid")
        if not str(decision.get("table_id") or "").strip():
            raise CanonicalReviewError(f"canonical review table decision {index} id is missing")
        if not str(decision.get("source_reference") or "").strip() or not str(decision.get("reason") or "").strip():
            raise CanonicalReviewError(f"canonical review table decision {index} source evidence is missing")
        _require_record_sha256(decision, "before_sha256")
        _require_record_sha256(decision, "after_sha256")

    selected_assets = record.get("selected_assets")
    if not isinstance(selected_assets, list):
        raise CanonicalReviewError("canonical review selected assets must be a list")
    if summary.get("selected_asset_count") != len(selected_assets):
        raise CanonicalReviewError("canonical review selected asset count is inconsistent")
    seen_assets: set[str] = set()
    accepted_parts = Path(accepted_relative).parts
    resolved_markdown = accepted_markdown.resolve(strict=False)
    if tuple(resolved_markdown.parts[-len(accepted_parts) :]) != accepted_parts:
        raise CanonicalReviewError("canonical review accepted Markdown path does not match the build input")
    asset_root = resolved_markdown
    for _part in accepted_parts:
        asset_root = asset_root.parent
    for item in selected_assets:
        if not isinstance(item, Mapping):
            raise CanonicalReviewError("canonical review selected asset identity is invalid")
        relative = _safe_relative_path(item.get("path"))
        if relative is None or relative in seen_assets:
            raise CanonicalReviewError("canonical review selected asset path is unsafe or duplicated")
        seen_assets.add(relative)
        expected_asset_hash = _require_record_sha256(item, "sha256")
        asset_path = asset_root / Path(relative)
        resolved_asset = asset_path.resolve(strict=False)
        try:
            resolved_asset.relative_to(asset_root)
        except ValueError as exc:
            raise CanonicalReviewError(f"canonical review selected asset escapes the build input: {relative}") from exc
        if asset_path.is_symlink() or not asset_path.is_file():
            raise CanonicalReviewError(f"canonical review selected asset not found: {relative}")
        if canonical_file_sha256(asset_path) != expected_asset_hash:
            raise CanonicalReviewError(f"canonical review selected asset hash does not match the build input: {relative}")

    return hashlib.sha256(review_bytes).hexdigest()


def finalize_canonical_review(
    *,
    source_path: str | Path | None,
    candidate_markdown_path: str | Path,
    reviewed_markdown_path: str | Path,
    markdown_audit_path: str | Path,
    asset_audit_path: str | Path,
    source_coverage_path: str | Path,
    table_decisions_path: str | Path,
    asset_root: str | Path,
) -> dict[str, Any]:
    """Validate review evidence and return one canonical acceptance record."""

    candidate = Path(candidate_markdown_path).resolve(strict=False)
    reviewed = Path(reviewed_markdown_path).resolve(strict=False)
    assets = Path(asset_root).resolve(strict=False)
    if not candidate.is_file():
        raise CanonicalReviewError(f"candidate Markdown not found: {candidate}")
    if not reviewed.is_file():
        raise CanonicalReviewError(f"reviewed Markdown not found: {reviewed}")
    if not assets.is_dir():
        raise CanonicalReviewError(f"asset root not found: {assets}")
    try:
        accepted_relative = reviewed.relative_to(assets).as_posix()
    except ValueError as exc:
        raise CanonicalReviewError("reviewed Markdown must be inside the audited asset root") from exc

    markdown_audit_file = Path(markdown_audit_path)
    asset_audit_file = Path(asset_audit_path)
    coverage_file = Path(source_coverage_path)
    decisions_file = Path(table_decisions_path)
    markdown_audit = _load_json_mapping(markdown_audit_file, label="Markdown audit")
    asset_audit = _load_json_mapping(asset_audit_file, label="asset audit")
    coverage = _load_json_mapping(coverage_file, label="source coverage")
    decision_payload = _load_json_mapping(decisions_file, label="table decisions")
    findings: list[dict[str, Any]] = []

    source: dict[str, Any]
    source_hash: str | None = None
    if source_path is None:
        source = {"available": False, "name": None, "sha256": None}
        findings.append(_finding("source_not_available", "Exact source bytes are required for canonical acceptance."))
    else:
        source_file = Path(source_path).resolve(strict=False)
        if source_file.is_file():
            source_hash = canonical_file_sha256(source_file)
            source = {"available": True, "name": source_file.name, "sha256": source_hash}
        else:
            source = {"available": False, "name": source_file.name, "sha256": None}
            findings.append(_finding("source_not_available", "Exact source bytes are required for canonical acceptance."))

    candidate_hash = canonical_file_sha256(candidate)
    accepted_hash = canonical_file_sha256(reviewed)
    coverage_record = _validate_source_coverage(
        coverage,
        source_sha256=source_hash,
        findings=findings,
    )
    coverage_record["record_sha256"] = canonical_file_sha256(coverage_file)

    if markdown_audit.get("schema") != CANONICAL_MARKDOWN_AUDIT_SCHEMA:
        findings.append(_finding("invalid_markdown_audit_schema", "Markdown audit schema identity is invalid."))
    audit_markdown = markdown_audit.get("markdown")
    audit_markdown_hash = (
        _normalize_sha256(audit_markdown.get("sha256"))
        if isinstance(audit_markdown, Mapping)
        else None
    )
    if audit_markdown_hash != accepted_hash:
        findings.append(
            _finding(
                "stale_markdown_audit",
                "Markdown audit does not match the reviewed Markdown bytes.",
                expected_sha256=accepted_hash,
                actual_sha256=audit_markdown_hash,
            )
        )
    audit_source = markdown_audit.get("source")
    audit_source_hash = (
        _normalize_sha256(audit_source.get("sha256"))
        if isinstance(audit_source, Mapping)
        else None
    )
    if source_hash is not None and audit_source_hash != source_hash:
        findings.append(_finding("stale_source_audit", "Markdown audit does not match the exact source bytes."))
    audit_summary = markdown_audit.get("summary")
    error_count = int(audit_summary.get("error") or 0) if isinstance(audit_summary, Mapping) else 0
    if error_count:
        findings.append(
            _finding(
                "markdown_audit_errors",
                "Markdown structural audit contains blocking errors.",
                error_count=error_count,
            )
        )

    if asset_audit.get("schema") != CANONICAL_ASSET_AUDIT_SCHEMA:
        findings.append(_finding("invalid_asset_audit_schema", "Asset audit schema identity is invalid."))
    candidate_text = _read_normalized_markdown(candidate)
    accepted_text = _read_normalized_markdown(reviewed)
    table_decisions, unresolved_items = _normalize_table_decisions(
        decision_payload,
        candidate_text=candidate_text,
        accepted_text=accepted_text,
        findings=findings,
    )
    selected_assets = _selected_asset_records(
        asset_audit,
        accepted_text=accepted_text,
        reviewed_markdown=reviewed,
        asset_root=assets,
        findings=findings,
    )

    source_missing = not source["available"]
    non_source_blockers = [item for item in findings if item["code"] != "source_not_available"]
    if non_source_blockers or unresolved_items:
        status = "blocked"
    elif source_missing:
        status = "needs_source_verification"
    else:
        status = "accepted"
    unresolved_count = len(unresolved_items) + sum(
        item["code"] != "unresolved_review_items" for item in findings
    )
    converted_count = sum(item["action"] == "converted_to_markdown" for item in table_decisions)
    retained_count = sum(item["action"] == "retained_html_by_exception" for item in table_decisions)
    record = {
        "schema": CANONICAL_REVIEW_SCHEMA,
        "created_at": _utc_now(),
        "status": status,
        "ok": status == "accepted",
        "source": source,
        "markdown": {
            "candidate": {"name": candidate.name, "sha256": candidate_hash},
            "accepted": {"path": accepted_relative, "sha256": accepted_hash},
        },
        "source_coverage": coverage_record,
        "audit_reports": {
            "markdown_structure": {
                "schema": CANONICAL_MARKDOWN_AUDIT_SCHEMA,
                "report_sha256": canonical_file_sha256(markdown_audit_file),
            },
            "canonical_assets": {
                "schema": CANONICAL_ASSET_AUDIT_SCHEMA,
                "report_sha256": canonical_file_sha256(asset_audit_file),
            },
        },
        "table_review": {
            "record_sha256": canonical_file_sha256(decisions_file),
            "decisions": table_decisions,
            "unresolved_items": unresolved_items,
        },
        "selected_assets": selected_assets,
        "summary": {
            "table_decision_count": len(table_decisions),
            "converted_to_markdown_count": converted_count,
            "retained_html_by_exception_count": retained_count,
            "selected_asset_count": len(selected_assets),
            "unresolved_item_count": unresolved_count,
            "finding_count": len(findings),
        },
        "findings": findings,
        "safety": {
            "candidate_markdown_modified": False,
            "original_handoff_modified": False,
            "network_put_performed": False,
            "script_owned_llm_calls": 0,
        },
    }
    validate_canonical_review_record(record)
    return record


def materialize_canonical_review_output(
    record: Mapping[str, Any],
    *,
    reviewed_markdown_path: str | Path,
    asset_root: str | Path,
    output_root: str | Path,
    extra_json_files: Mapping[str, Mapping[str, Any]] | None = None,
) -> Path:
    """Write the record and accepted local files under one new output root."""

    validate_canonical_review_record(record)
    reviewed = Path(reviewed_markdown_path).resolve(strict=True)
    assets = Path(asset_root).resolve(strict=True)
    output = Path(output_root).resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise CanonicalReviewError(f"canonical review output already exists: {output}")
    try:
        output.relative_to(assets)
    except ValueError:
        pass
    else:
        raise CanonicalReviewError("canonical review output must be outside the audited asset root")
    try:
        assets.relative_to(output)
    except ValueError:
        pass
    else:
        raise CanonicalReviewError("canonical review output must not contain the audited asset root")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        if record.get("status") == "accepted":
            markdown_identity = record["markdown"]["accepted"]
            markdown_relative = _safe_relative_path(markdown_identity.get("path"))
            if markdown_relative is None:
                raise CanonicalReviewError("accepted Markdown output path is unsafe")
            markdown_output = temporary / Path(markdown_relative)
            markdown_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reviewed, markdown_output)
            if canonical_file_sha256(markdown_output) != markdown_identity.get("sha256"):
                raise CanonicalReviewError("materialized accepted Markdown hash does not match review record")
            for item in record.get("selected_assets", []):
                if not isinstance(item, Mapping):
                    raise CanonicalReviewError("selected asset record is invalid")
                relative = _safe_relative_path(item.get("path"))
                if relative is None:
                    raise CanonicalReviewError("selected asset output path is unsafe")
                source = assets / Path(relative)
                destination = temporary / Path(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if canonical_file_sha256(destination) != item.get("sha256"):
                    raise CanonicalReviewError(f"materialized selected asset hash mismatch: {relative}")

        record_path = temporary / "ragflow_canonical_review.json"
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for relative, payload in (extra_json_files or {}).items():
            safe_relative = _safe_relative_path(relative)
            if safe_relative is None:
                raise CanonicalReviewError(f"extra canonical review output path is unsafe: {relative}")
            path = temporary / Path(safe_relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output / "ragflow_canonical_review.json"
