#!/usr/bin/env python3
"""Read-only audit of canonical Markdown, image assets, allowlists, and directories."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence
from urllib.parse import unquote, urlsplit


SCHEMA = "ragflow_canonical_asset_audit_v1"
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
DEFAULT_CONTROL_BASENAMES = {"agents.md", "session_handoff.md"}
INLINE_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<plain>[^)\s]+))",
    re.MULTILINE,
)
REFERENCE_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\[(?P<label>[^\]]*)\]", re.MULTILINE)
REFERENCE_DEF_RE = re.compile(
    r"^\s*\[(?P<label>[^\]]+)\]:\s*(?:<(?P<angled>[^>]+)>|(?P<plain>\S+))",
    re.MULTILINE,
)
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?:\"(?P<double>[^\"]+)\"|'(?P<single>[^']+)'|(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Canonical domain, document, or portfolio root.")
    parser.add_argument(
        "--allowlist",
        type=Path,
        help="Optional TXT, JSON, or YAML file containing approved Markdown paths.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Base for relative allowlist paths; defaults to the allowlist parent.",
    )
    parser.add_argument(
        "--active-status",
        default="active",
        help="Status accepted from document-record allowlists; default: active.",
    )
    parser.add_argument(
        "--control-basename",
        action="append",
        default=[],
        help="Additional control basename to report case-insensitively; repeat as needed.",
    )
    parser.add_argument(
        "--no-default-controls",
        action="store_true",
        help="Do not include AGENTS.md and SESSION_HANDOFF.md defaults.",
    )
    parser.add_argument("--skip-hashes", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument("--json-out", type=Path, help="Write the same JSON report to a file.")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def link_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if is_reparse_point(path):
        return "reparse_point"
    return "ordinary"


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return str(path)


def walk_tree(root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    files: list[Path] = []
    directories: dict[Path, dict[str, Any]] = {}
    for current_text, child_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_text)
        directories[current] = {
            "path": relative(current, root),
            "link_status": link_kind(current),
            "direct_file_count": len(file_names),
            "recursive_file_count": 0,
            "child_directory_count": len(child_names),
            "empty_ordinary": False,
        }
        retained: list[str] = []
        for name in child_names:
            child = current / name
            kind = link_kind(child)
            if kind == "ordinary":
                retained.append(name)
            else:
                directories[child] = {
                    "path": relative(child, root),
                    "link_status": kind,
                    "direct_file_count": None,
                    "recursive_file_count": None,
                    "child_directory_count": None,
                    "empty_ordinary": False,
                }
        child_names[:] = retained
        for name in file_names:
            path = current / name
            files.append(path)
            ancestor = current
            while True:
                directories[ancestor]["recursive_file_count"] += 1
                if ancestor == root:
                    break
                ancestor = ancestor.parent
    for path, record in directories.items():
        record["empty_ordinary"] = bool(
            path != root
            and record["link_status"] == "ordinary"
            and record["direct_file_count"] == 0
            and record["child_directory_count"] == 0
        )
    ordered = sorted(directories, key=lambda item: relative(item, root).casefold())
    return sorted(files), [directories[path] for path in ordered]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def reference_definitions(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in REFERENCE_DEF_RE.finditer(text):
        result[match.group("label").strip().casefold()] = (
            match.group("angled") or match.group("plain") or ""
        )
    return result


def image_destinations(text: str) -> list[str]:
    destinations = [
        match.group("angled") or match.group("plain") or ""
        for match in INLINE_IMAGE_RE.finditer(text)
    ]
    definitions = reference_definitions(text)
    for match in REFERENCE_IMAGE_RE.finditer(text):
        label = (match.group("label") or match.group("alt")).strip().casefold()
        if label in definitions:
            destinations.append(definitions[label])
    for match in HTML_IMAGE_RE.finditer(text):
        destinations.append(
            match.group("double") or match.group("single") or match.group("bare") or ""
        )
    return destinations


def resolve_local(markdown: Path, destination: str) -> Path | None:
    value = destination.strip().replace("\\ ", " ").replace("\\(", "(").replace("\\)", ")")
    parsed = urlsplit(value)
    if parsed.scheme.casefold() in {"data", "http", "https"} or value.startswith("//"):
        return None
    if not parsed.path or parsed.path.startswith("#"):
        return None
    decoded = unquote(parsed.path).replace("/", os.sep).replace("\\", os.sep)
    return (markdown.parent / decoded).resolve(strict=False)


def load_serialized(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for YAML allowlists.") from exc
        return yaml.safe_load(text)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def extract_allowlist_paths(data: Any, active_status: str) -> list[str]:
    if isinstance(data, list):
        paths: list[str] = []
        for item in data:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict) and item.get("path"):
                if not item.get("status") or str(item.get("status")) == active_status:
                    paths.append(str(item["path"]))
        return paths
    if not isinstance(data, dict):
        raise ValueError("Allowlist must be a list or mapping.")
    for key in ("active_paths", "paths", "allowlist"):
        if key in data:
            return extract_allowlist_paths(data[key], active_status)
    if "documents" in data:
        return extract_allowlist_paths(data["documents"], active_status)
    raise ValueError("Allowlist mapping must contain active_paths, paths, allowlist, or documents.")


def load_allowlist(path: Path, project_root: Path | None, active_status: str) -> set[Path]:
    data = load_serialized(path)
    raw_paths = extract_allowlist_paths(data, active_status)
    base = project_root.resolve() if project_root else path.parent.resolve()
    return {
        Path(raw).resolve(strict=False)
        if Path(raw).is_absolute()
        else (base / raw).resolve(strict=False)
        for raw in raw_paths
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    if not root.is_dir():
        raise ValueError(f"Audit root is not a directory: {root}")
    files, directories = walk_tree(root)
    markdown_files = [path for path in files if path.suffix.casefold() == ".md"]
    image_files = [path for path in files if path.suffix.casefold() in IMAGE_EXTENSIONS]
    image_by_key = {str(path.resolve(strict=False)).casefold(): path for path in image_files}

    active_paths: set[Path] | None = None
    if args.allowlist:
        active_paths = load_allowlist(args.allowlist.resolve(), args.project_root, args.active_status)
    controls = set() if args.no_default_controls else set(DEFAULT_CONTROL_BASENAMES)
    controls.update(name.casefold() for name in args.control_basename)

    references: list[dict[str, Any]] = []
    reference_counts: dict[str, int] = defaultdict(int)
    for markdown in markdown_files:
        text = markdown.read_text(encoding="utf-8-sig")
        for destination in image_destinations(text):
            resolved = resolve_local(markdown, destination)
            if resolved is None:
                continue
            key = str(resolved).casefold()
            reference_counts[key] += 1
            references.append(
                {
                    "markdown": relative(markdown, root),
                    "destination": destination,
                    "resolved": relative(resolved, root),
                    "exists": key in image_by_key and image_by_key[key].is_file(),
                }
            )

    images: list[dict[str, Any]] = []
    hashes: dict[str, list[str]] = defaultdict(list)
    for image in image_files:
        key = str(image.resolve(strict=False)).casefold()
        digest = None if args.skip_hashes else sha256(image)
        record = {
            "path": relative(image, root),
            "reference_count": reference_counts.get(key, 0),
            "sha256": digest,
        }
        images.append(record)
        if digest:
            hashes[digest].append(record["path"])

    control_files = [relative(path, root) for path in files if path.name.casefold() in controls]
    non_active_markdown = None
    if active_paths is not None:
        non_active_markdown = [
            relative(path, root)
            for path in markdown_files
            if path.resolve(strict=False) not in active_paths
        ]
    missing = [item for item in references if not item["exists"]]
    unreferenced = [item for item in images if item["reference_count"] == 0]
    duplicate_hashes = [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(hashes.items())
        if len(paths) > 1
    ]
    empty_directories = [item["path"] for item in directories if item["empty_ordinary"]]
    return {
        "schema": SCHEMA,
        "scope": "read_only_asset_and_boundary_audit",
        "root": str(root),
        "allowlist": str(args.allowlist.resolve()) if args.allowlist else None,
        "summary": {
            "markdown_file_count": len(markdown_files),
            "image_file_count": len(image_files),
            "image_reference_occurrence_count": len(references),
            "unique_local_image_target_count": len(reference_counts),
            "missing_reference_count": len(missing),
            "unreferenced_asset_count": len(unreferenced),
            "duplicate_image_hash_group_count": len(duplicate_hashes),
            "control_file_count": len(control_files),
            "markdown_not_in_active_allowlist_count": (
                None if non_active_markdown is None else len(non_active_markdown)
            ),
            "directory_count": len(directories),
            "empty_ordinary_directory_count": len(empty_directories),
        },
        "control_files": control_files,
        "markdown_not_in_active_allowlist": non_active_markdown,
        "missing_references": missing,
        "unreferenced_assets": unreferenced,
        "duplicate_image_hashes": duplicate_hashes,
        "images": images,
        "directories": directories,
        "acceptance_note": "The audit reports evidence only and never authorizes deletion or ingestion.",
    }


def print_text(report: dict[str, Any]) -> None:
    print(f"Canonical asset audit: {report['root']}")
    for key, value in report["summary"].items():
        print(f"  {key}: {value}")
    for key in (
        "control_files",
        "markdown_not_in_active_allowlist",
        "missing_references",
        "unreferenced_assets",
        "duplicate_image_hashes",
    ):
        value = report[key]
        if value:
            print(f"\n{key}:")
            for item in value:
                print(f"  - {json.dumps(item, ensure_ascii=False)}")
    print("\ndirectories:")
    for item in report["directories"]:
        print(
            "  - "
            f"{item['path']}: files={item['direct_file_count']}, "
            f"recursive_files={item['recursive_file_count']}, "
            f"children={item['child_directory_count']}, "
            f"link={item['link_status']}, empty_ordinary={item['empty_ordinary']}"
        )
    print(f"\n{report['acceptance_note']}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args)
    except (OSError, UnicodeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json or args.json_out:
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.json:
            print(payload, end="")
        if args.json_out:
            output = args.json_out.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
