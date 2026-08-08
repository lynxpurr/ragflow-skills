#!/usr/bin/env python3
"""Read-only structural audit for extracted or canonical RAG Markdown."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Sequence
from urllib.parse import unquote, urlsplit


SCHEMA = "ragflow_canonical_markdown_audit_v1"
CHUNK_RE = re.compile(r"(?im)^\s*<!--\s*chunk\s*-->\s*$")
CHUNK_LINE_RE = re.compile(r"^\s*<!--\s*chunk\s*-->\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
INLINE_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<plain>[^)\r\n]+))\s*\)"
)
REFERENCE_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\[(?P<label>[^\]]*)\]")
REFERENCE_DEF_RE = re.compile(
    r"^\s*\[(?P<label>[^\]]+)\]:\s*(?:<(?P<angled>[^>]+)>|(?P<plain>\S+))",
    re.MULTILINE,
)
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?:\"(?P<double>[^\"]+)\"|'(?P<single>[^']+)'|(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_DELIMITER_RE = re.compile(r"^:?-{3,}:?$")
HTML_TABLE_RE = re.compile(r"</?(?:table|thead|tbody|tr|th|td)\b", re.IGNORECASE)
GENERIC_IMAGE_RE = re.compile(
    r"^(?:image|img|figure|fig|screenshot|screen[-_ ]?shot|picture|photo|"
    r"\u56fe\u7247|\u622a\u56fe|\u622a\u5c4f)[-_ ]?\d*$",
    re.IGNORECASE,
)
HASH_NAME_RE = re.compile(r"^[0-9a-f]{20,}$", re.IGNORECASE)
IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
DEFAULT_PLACEHOLDERS = {
    "none",
    "n/a",
    "not applicable",
    "no content",
    "\u65e0",
    "\u6682\u65e0",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    **context: Any,
) -> None:
    issue: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    issue.update({key: value for key, value in context.items() if value is not None})
    issues.append(issue)


def split_table_row(line: str) -> list[str]:
    value = line.strip().strip("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value:
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def is_delimiter_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(
        TABLE_DELIMITER_RE.fullmatch(cell.replace(" ", "")) for cell in cells
    )


def reference_definitions(text: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for match in REFERENCE_DEF_RE.finditer(text):
        target = match.group("angled") or match.group("plain") or ""
        definitions[match.group("label").strip().casefold()] = target
    return definitions


def image_references(text: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for match in INLINE_IMAGE_RE.finditer(text):
        target = match.group("angled") or match.group("plain") or ""
        titled = re.match(r"^(.*?)(?:\s+[\"'].*[\"'])$", target.strip())
        references.append(
            {
                "offset": match.start(),
                "alt": match.group("alt").strip(),
                "target": (titled.group(1) if titled else target).strip(),
            }
        )
    definitions = reference_definitions(text)
    for match in REFERENCE_IMAGE_RE.finditer(text):
        label = (match.group("label") or match.group("alt")).strip().casefold()
        if label in definitions:
            references.append(
                {
                    "offset": match.start(),
                    "alt": match.group("alt").strip(),
                    "target": definitions[label],
                }
            )
    for match in HTML_IMAGE_RE.finditer(text):
        references.append(
            {
                "offset": match.start(),
                "alt": "",
                "target": match.group("double")
                or match.group("single")
                or match.group("bare")
                or "",
            }
        )
    return sorted(references, key=lambda item: item["offset"])


def resolve_local(markdown: Path, target: str) -> Path | None:
    value = target.strip().replace("\\ ", " ").replace("\\(", "(").replace("\\)", ")")
    parsed = urlsplit(value)
    if parsed.scheme.casefold() in {"data", "http", "https"} or value.startswith("//"):
        return None
    if not parsed.path or parsed.path.startswith("#"):
        return None
    decoded = unquote(parsed.path).replace("/", os.sep).replace("\\", os.sep)
    return (markdown.parent / decoded).resolve(strict=False)


def strip_chunk_scaffolding(chunk: str, *, remove_images: bool) -> str:
    retained: list[str] = []
    for line in chunk.splitlines():
        stripped = line.strip()
        if not stripped or HEADING_RE.match(stripped) or REFERENCE_DEF_RE.match(stripped):
            continue
        if remove_images:
            stripped = INLINE_IMAGE_RE.sub("", stripped)
            stripped = REFERENCE_IMAGE_RE.sub("", stripped)
            stripped = HTML_IMAGE_RE.sub("", stripped).strip()
            if not stripped:
                continue
        retained.append(stripped)
    return "\n".join(retained).strip()


def audit(args: argparse.Namespace) -> dict[str, Any]:
    markdown = args.markdown.resolve()
    if not markdown.is_file():
        raise FileNotFoundError(f"Markdown file not found: {markdown}")
    text = markdown.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    issues: list[dict[str, Any]] = []

    if args.source:
        source_path = args.source.resolve()
        if source_path.is_file():
            source: dict[str, Any] = {
                "status": "available_identity_recorded",
                "name": source_path.name,
                "sha256": sha256_file(source_path),
                "semantic_comparison": "not_performed_by_this_script",
            }
        else:
            source = {"status": "missing", "name": source_path.name}
            add_issue(issues, "error", "source_missing", "The supplied source file does not exist.")
    else:
        source = {
            "status": "not_provided",
            "semantic_comparison": "not_performed_by_this_script",
        }
        add_issue(
            issues,
            "error" if args.require_source else "warning",
            "needs_source_verification",
            "No original source was supplied; only structural findings are valid.",
        )

    headings: list[dict[str, Any]] = []
    heading_positions: list[tuple[int, int, str]] = []
    previous_level: int | None = None
    in_fence = False
    fence_char = ""
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        fence = re.match(r"^(```+|~~~+)", stripped)
        if fence:
            marker = fence.group(1)[0]
            if not in_fence:
                in_fence, fence_char = True, marker
            elif marker == fence_char:
                in_fence, fence_char = False, ""
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(stripped)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        headings.append({"line": number, "level": level, "title": title})
        heading_positions.append((number - 1, level, title))
        if previous_level is not None and level > previous_level + 1:
            add_issue(
                issues,
                "warning",
                "heading_level_jump",
                f"Heading jumps from H{previous_level} to H{level}: {title}",
                line=number,
            )
        previous_level = level

    placeholders = {value.casefold() for value in (args.placeholder or DEFAULT_PLACEHOLDERS)}
    placeholder_sections: list[dict[str, Any]] = []
    for index, (start, level, title) in enumerate(heading_positions):
        end = len(lines)
        for next_start, next_level, _ in heading_positions[index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        body = [
            line.strip()
            for line in lines[start + 1 : end]
            if line.strip() and not CHUNK_LINE_RE.match(line)
        ]
        if len(body) == 1 and body[0].casefold() in placeholders:
            placeholder_sections.append({"line": start + 1, "title": title, "value": body[0]})
    if placeholder_sections:
        add_issue(
            issues,
            "warning",
            "placeholder_only_sections",
            f"Found {len(placeholder_sections)} placeholder-only sections; review omission from retrieval content.",
            sections=placeholder_sections,
        )

    tables: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(lines):
        if not TABLE_ROW_RE.match(lines[cursor]):
            cursor += 1
            continue
        start = cursor
        block: list[str] = []
        while cursor < len(lines) and TABLE_ROW_RE.match(lines[cursor]):
            block.append(lines[cursor])
            cursor += 1
        delimiter_indexes = [index for index, row in enumerate(block) if is_delimiter_row(row)]
        if not delimiter_indexes:
            continue
        widths = [len(split_table_row(row)) for row in block]
        valid = delimiter_indexes == [1] and len(set(widths)) == 1
        tables.append(
            {
                "start_line": start + 1,
                "end_line": start + len(block),
                "row_count": len(block),
                "column_counts": widths,
                "valid": valid,
            }
        )
        if delimiter_indexes != [1]:
            add_issue(
                issues,
                "error",
                "invalid_table_delimiter",
                "Markdown table must contain one delimiter row immediately after its header.",
                line=start + 1,
            )
        if len(set(widths)) != 1:
            add_issue(
                issues,
                "error",
                "inconsistent_table_columns",
                f"Markdown table rows have inconsistent column counts: {widths}",
                line=start + 1,
            )

    html_table_tags = len(HTML_TABLE_RE.findall(text))
    if html_table_tags:
        add_issue(
            issues,
            "warning",
            "html_table_residue",
            f"Found {html_table_tags} HTML table tags; review whether normalization is required.",
        )

    marker_matches = list(CHUNK_RE.finditer(text))
    chunks = CHUNK_RE.split(text)
    knowledge_chunks = chunks[1:] if marker_matches else chunks
    empty_chunks = 0
    heading_only_chunks = 0
    image_only_chunks = 0
    for chunk in knowledge_chunks:
        if not chunk.strip():
            empty_chunks += 1
            continue
        with_images = strip_chunk_scaffolding(chunk, remove_images=False)
        without_images = strip_chunk_scaffolding(chunk, remove_images=True)
        if not with_images:
            heading_only_chunks += 1
        elif image_references(chunk) and not without_images:
            image_only_chunks += 1
    consecutive_markers = len(
        re.findall(r"(?ims)^\s*<!--\s*chunk\s*-->\s*^\s*<!--\s*chunk\s*-->\s*$", text)
    )
    split_tables = len(
        re.findall(
            r"(?im)^\s*\|.*\|\s*$\s*^\s*<!--\s*chunk\s*-->\s*$\s*^\s*\|.*\|\s*$",
            text,
        )
    )
    for code, count, message in (
        ("empty_chunks", empty_chunks, "empty chunks"),
        ("heading_only_chunks", heading_only_chunks, "heading-only chunks"),
        ("image_only_chunks", image_only_chunks, "image-only chunks"),
        ("consecutive_chunk_markers", consecutive_markers, "consecutive chunk-marker pairs"),
        ("split_table_chunks", split_tables, "chunk boundaries inside Markdown tables"),
    ):
        if count:
            add_issue(issues, "warning", code, f"Found {count} {message}.")

    image_root = args.image_root.resolve() if args.image_root else markdown.parent.resolve()
    asset_scope = image_root
    if args.asset_scope:
        asset_scope = (
            args.asset_scope.resolve()
            if args.asset_scope.is_absolute()
            else (image_root / args.asset_scope).resolve()
        )
        if not asset_scope.is_relative_to(image_root):
            raise ValueError(f"Asset scope must be inside image root: {asset_scope}")

    reference_records: list[dict[str, Any]] = []
    resolved_references: set[Path] = set()
    missing: set[str] = set()
    generic_names: set[str] = set()
    generic_alt_count = 0
    generic_alt_values = {
        "image",
        "img",
        "figure",
        "picture",
        "photo",
        "\u56fe\u7247",
        "\u622a\u56fe",
        "\u622a\u5c4f",
    }
    for reference in image_references(text):
        alt = reference["alt"]
        target = reference["target"]
        record: dict[str, Any] = {
            "line": text.count("\n", 0, reference["offset"]) + 1,
            "alt": alt,
            "target": target,
        }
        resolved = resolve_local(markdown, target)
        record["local"] = resolved is not None
        if not alt or alt.casefold() in generic_alt_values:
            generic_alt_count += 1
        if resolved is not None:
            record["exists"] = resolved.is_file()
            if resolved.is_file():
                resolved_references.add(resolved)
            else:
                missing.add(target)
            stem = Path(urlsplit(target).path).stem
            if GENERIC_IMAGE_RE.fullmatch(stem) or HASH_NAME_RE.fullmatch(stem):
                generic_names.add(Path(urlsplit(target).path).name)
        reference_records.append(record)

    if missing:
        add_issue(
            issues,
            "error",
            "missing_image_references",
            f"Found {len(missing)} missing local image targets.",
            targets=sorted(missing),
        )
    if generic_alt_count:
        add_issue(
            issues,
            "warning",
            "generic_or_empty_alt_text",
            f"Found {generic_alt_count} image references with empty or generic alt text.",
        )
    if generic_names:
        add_issue(
            issues,
            "warning",
            "generic_or_hash_image_names",
            f"Found {len(generic_names)} generic or hash-like image basenames.",
            names=sorted(generic_names),
        )

    assets: list[Path] = []
    unreferenced: list[str] = []
    collisions: dict[str, list[str]] = {}
    if not image_root.is_dir():
        add_issue(issues, "error", "image_root_missing", f"Image root does not exist: {image_root}")
    elif not asset_scope.is_dir():
        add_issue(issues, "error", "asset_scope_missing", f"Asset scope does not exist: {asset_scope}")
    else:
        collision_assets = sorted(
            path.resolve()
            for path in image_root.rglob("*")
            if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
        )
        assets = sorted(
            path.resolve()
            for path in asset_scope.rglob("*")
            if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
        )
        unreferenced = [
            path.relative_to(image_root).as_posix()
            for path in assets
            if path not in resolved_references
        ]
        by_basename: dict[str, list[Path]] = {}
        for asset in collision_assets:
            by_basename.setdefault(asset.name.casefold(), []).append(asset)
        collisions = {
            name: [path.relative_to(image_root).as_posix() for path in paths]
            for name, paths in by_basename.items()
            if len(paths) > 1
        }
        if unreferenced:
            add_issue(
                issues,
                "warning",
                "unreferenced_assets",
                f"Found {len(unreferenced)} unreferenced assets within scope; review before deletion.",
                assets=unreferenced,
            )
        if collisions:
            add_issue(
                issues,
                "error" if args.flat_asset_namespace else "warning",
                "case_insensitive_basename_collisions",
                "Image basenames collide case-insensitively across the image root.",
                collisions=collisions,
            )

    severity = {
        level: sum(issue["severity"] == level for issue in issues)
        for level in ("error", "warning")
    }
    status = "fail" if severity["error"] else "review_required" if severity["warning"] else "static_pass"
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "scope": "read_only_structural_audit",
        "source_fidelity_proven": False,
        "markdown": {
            "path": str(markdown),
            "sha256": sha256_file(markdown),
            "line_count": len(lines),
        },
        "source": source,
        "image_root": str(image_root),
        "asset_scope": str(asset_scope),
        "summary": {
            "heading_count": len(headings),
            "chunk_marker_count": len(marker_matches),
            "knowledge_chunk_count": len(knowledge_chunks),
            "markdown_table_count": len(tables),
            "valid_markdown_table_count": sum(table["valid"] for table in tables),
            "image_reference_count": len(reference_records),
            "unique_local_image_reference_count": len(resolved_references),
            "asset_count": len(assets),
            "unreferenced_asset_count": len(unreferenced),
            **severity,
        },
        "chunk_audit": {
            "empty_chunk_count": empty_chunks,
            "heading_only_chunk_count": heading_only_chunks,
            "image_only_chunk_count": image_only_chunks,
            "consecutive_marker_count": consecutive_markers,
            "split_table_boundary_count": split_tables,
            "placeholder_only_section_count": len(placeholder_sections),
        },
        "headings": headings,
        "tables": tables,
        "images": reference_records,
        "issues": issues,
        "acceptance_note": (
            "A static pass does not prove source fidelity, RAGFlow parser behavior, "
            "retrieval quality, answer grounding, or front-end asset delivery."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--image-root", type=Path, help="Asset root; defaults to the Markdown parent.")
    parser.add_argument(
        "--asset-scope",
        type=Path,
        help="Document asset directory inside --image-root for scoped unreferenced counts.",
    )
    parser.add_argument("--source", type=Path, help="Exact immutable original source file.")
    parser.add_argument("--require-source", action="store_true")
    parser.add_argument(
        "--placeholder",
        action="append",
        help="Placeholder-only section value; repeat to replace built-in defaults.",
    )
    parser.add_argument(
        "--flat-asset-namespace",
        action="store_true",
        help="Treat case-insensitive basename collisions as errors instead of warnings.",
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if args.json_out:
        output = args.json_out.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(f"Status: {report['status']}")
    print(f"Source fidelity proven: {report['source_fidelity_proven']}")
    print(
        "Headings: {heading_count}; chunks: {knowledge_chunk_count}; "
        "tables: {valid_markdown_table_count}/{markdown_table_count} valid; "
        "images: {image_reference_count} references, {asset_count} assets in scope".format(**summary)
    )
    print(f"Issues: {summary['error']} errors, {summary['warning']} warnings")
    for issue in report["issues"]:
        location = f" line {issue['line']}" if issue.get("line") else ""
        print(f"- {issue['severity'].upper()} {issue['code']}{location}: {issue['message']}")
    print(report["acceptance_note"])
    return 1 if summary["error"] or (args.fail_on_warning and summary["warning"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
