#!/usr/bin/env python3
"""Check public rename policy, compatibility facades, and naming drift."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ragflow_rename_governance_check_v1"

TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "htmlcov",
    "release-artifacts",
}
ALLOW_MARKERS = ("rename-governance: allow", "release-hygiene: allow")
ALLOWED_LEGACY_REFERENCE_TOKENS = ("chunk-markers-ragflux-like",)


@dataclass(frozen=True)
class CompatibilityAlias:
    kind: str
    alias: str
    canonical: str
    source_patterns: tuple[str, ...]
    coverage_patterns: tuple[str, ...]
    docs_patterns: tuple[str, ...]
    status: str = "active"
    notes: str = ""


@dataclass(frozen=True)
class RenameDriftPattern:
    label: str
    pattern: re.Pattern[str]
    message: str


RENAME_POLICY_PATH = Path("docs/11-public-rename-policy.md")
REQUIRED_POLICY_SECTIONS = (
    "## CLI Aliases",
    "## Schema Migration",
    "## Documentation Updates",
    "## Downstream Gates",
    "## Release Notes",
    "## Rollback Plan",
)
DEFAULT_COMPATIBILITY_ALIASES = (
    CompatibilityAlias(
        kind="platform_profile",
        alias="saas-sandbox-https",
        canonical="strict-vendor-env",
        source_patterns=("saas-sandbox-https", "strict-vendor-env"),
        coverage_patterns=("saas-sandbox-https", "strict-vendor-env"),
        docs_patterns=("saas-sandbox-https", "strict-vendor-env"),
        notes="Legacy cross-platform smoke profile alias retained for older scripts.",
    ),
    CompatibilityAlias(
        kind="platform_profile",
        alias="manus-artifact-cli",
        canonical="artifact-runner-cli",
        source_patterns=("manus-artifact-cli", "artifact-runner-cli"),
        coverage_patterns=("manus-artifact-cli", "artifact-runner-cli"),
        docs_patterns=("manus-artifact-cli", "artifact-runner-cli"),
        notes="Legacy cross-platform smoke profile alias retained for older scripts.",
    ),
)
DEFAULT_DRIFT_ROOTS = (
    Path("skills"),
    Path("packages/ragflow-skill-runtime/src"),
    Path("tools"),
)
DEFAULT_COMPATIBILITY_SOURCE_ROOTS = (Path("tools/platform_smoke_matrix.py"),)
DEFAULT_COMPATIBILITY_COVERAGE_ROOTS = (Path("packages/ragflow-skill-runtime/tests"),)
DEFAULT_COMPATIBILITY_DOC_ROOTS = (Path("docs/05-cross-platform-smoke.md"),)
DEFAULT_EXCLUDED_RELATIVE_PATHS = {
    "tools/release_hygiene_check.py",
    "tools/rename_governance_check.py",
}
RENAME_DRIFT_PATTERNS = (
    RenameDriftPattern(
        label="legacy_ragflux_name",
        pattern=re.compile(r"\bragflux\b", re.IGNORECASE),
        message="legacy ragflux name must not appear on the public release surface",
    ),
    RenameDriftPattern(
        label="legacy_ragflow_saas_name",
        pattern=re.compile(r"\bragflow-saas\b", re.IGNORECASE),
        message="legacy ragflow-saas name must not appear on the public release surface",
    ),
    RenameDriftPattern(
        label="legacy_kb_ops_name",
        pattern=re.compile(r"\b(?:ragflow-kb-ops|kb ops)\b", re.IGNORECASE),
        message="legacy KB Ops naming must not appear on the public release surface",
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _resolve_paths(root: Path, paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple((root / path).resolve() if not path.is_absolute() else path.resolve() for path in paths)


def _iter_text_files(
    paths: Iterable[Path],
    *,
    root: Path,
    excluded_relative_paths: set[str] | None = None,
) -> Iterable[Path]:
    excluded = excluded_relative_paths or set()
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in TEXT_SUFFIXES and _relative(path, root) not in excluded:
                yield path
            continue
        if not path.exists():
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or candidate.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if any(part in IGNORED_DIRS for part in candidate.parts):
                continue
            if _relative(candidate, root) in excluded:
                continue
            yield candidate


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _pattern_evidence(
    *,
    root: Path,
    paths: Iterable[Path],
    patterns: tuple[str, ...],
    require_all: bool,
) -> dict[str, Any]:
    occurrences: dict[str, list[dict[str, Any]]] = {pattern: [] for pattern in patterns}
    for path in _iter_text_files(paths, root=root):
        text = _read_text(path)
        if not text:
            continue
        lines = text.splitlines()
        for pattern in patterns:
            if pattern not in text:
                continue
            matches = [
                {"path": _relative(path, root), "line": line_no}
                for line_no, line in enumerate(lines, start=1)
                if pattern in line
            ]
            occurrences[pattern].extend(matches[:5])

    matched = sorted(pattern for pattern, items in occurrences.items() if items)
    ok = len(matched) == len(patterns) if require_all else bool(matched)
    return {
        "candidate_patterns": list(patterns),
        "matched_patterns": matched,
        "unmatched_patterns": [pattern for pattern in patterns if pattern not in matched],
        "occurrences": {pattern: items for pattern, items in occurrences.items() if items},
        "ok": ok,
    }


def _check_policy(*, root: Path, policy_path: Path = RENAME_POLICY_PATH) -> dict[str, Any]:
    path = (root / policy_path).resolve() if not policy_path.is_absolute() else policy_path.resolve()
    exists = path.exists()
    text = _read_text(path) if exists else ""
    matched = [section for section in REQUIRED_POLICY_SECTIONS if section in text]
    missing = [section for section in REQUIRED_POLICY_SECTIONS if section not in matched]
    return {
        "ok": exists and not missing,
        "path": _relative(path, root),
        "required_sections": list(REQUIRED_POLICY_SECTIONS),
        "matched_sections": matched,
        "missing_sections": missing,
        "error": "" if exists and not missing else "rename policy document is missing required sections",
    }


def _check_alias(
    alias: CompatibilityAlias,
    *,
    root: Path,
    source_paths: Iterable[Path],
    coverage_paths: Iterable[Path],
    docs_paths: Iterable[Path],
) -> dict[str, Any]:
    source = _pattern_evidence(root=root, paths=source_paths, patterns=alias.source_patterns, require_all=True)
    coverage = _pattern_evidence(root=root, paths=coverage_paths, patterns=alias.coverage_patterns, require_all=True)
    docs = _pattern_evidence(root=root, paths=docs_paths, patterns=alias.docs_patterns, require_all=True)
    ok = bool(source["ok"] and coverage["ok"] and docs["ok"])
    return {
        "kind": alias.kind,
        "alias": alias.alias,
        "canonical": alias.canonical,
        "status": alias.status,
        "notes": alias.notes,
        "ok": ok,
        "source": source,
        "coverage": coverage,
        "docs": docs,
        "error": "" if ok else "compatibility alias is missing source, coverage, or docs evidence",
    }


def _check_compatibility_aliases(
    *,
    root: Path,
    aliases: tuple[CompatibilityAlias, ...],
    source_roots: tuple[Path, ...],
    coverage_roots: tuple[Path, ...],
    doc_roots: tuple[Path, ...],
) -> dict[str, Any]:
    source_paths = _resolve_paths(root, source_roots)
    coverage_paths = _resolve_paths(root, coverage_roots)
    docs_paths = _resolve_paths(root, doc_roots)
    checks = [
        _check_alias(
            alias,
            root=root,
            source_paths=source_paths,
            coverage_paths=coverage_paths,
            docs_paths=docs_paths,
        )
        for alias in aliases
    ]
    failed = [f"{check['kind']}:{check['alias']}" for check in checks if not check["ok"]]
    command_alias_count = sum(1 for alias in aliases if alias.kind == "command")
    schema_alias_count = sum(1 for alias in aliases if alias.kind == "schema")
    return {
        "ok": not failed,
        "source_roots": [_relative(path, root) for path in source_paths],
        "coverage_roots": [_relative(path, root) for path in coverage_paths],
        "doc_roots": [_relative(path, root) for path in docs_paths],
        "checks": checks,
        "summary": {
            "alias_count": len(aliases),
            "command_alias_count": command_alias_count,
            "schema_alias_count": schema_alias_count,
            "command_schema_alias_status": "covered" if command_alias_count or schema_alias_count else "not_applicable",
            "failed_count": len(failed),
            "failed_aliases": failed,
        },
    }


def _scan_naming_drift(
    *,
    root: Path,
    drift_roots: tuple[Path, ...],
    excluded_relative_paths: set[str],
) -> dict[str, Any]:
    paths = _resolve_paths(root, drift_roots)
    findings: list[dict[str, Any]] = []
    checked_files: set[str] = set()

    def scan_line_for(drift: RenameDriftPattern, line: str) -> str:
        if drift.label != "legacy_ragflux_name":
            return line
        sanitized = line
        for token in ALLOWED_LEGACY_REFERENCE_TOKENS:
            sanitized = re.sub(re.escape(token), "", sanitized, flags=re.IGNORECASE)
        return sanitized

    for path in _iter_text_files(paths, root=root, excluded_relative_paths=excluded_relative_paths):
        relative = _relative(path, root)
        checked_files.add(relative)
        text = _read_text(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in ALLOW_MARKERS):
                continue
            for drift in RENAME_DRIFT_PATTERNS:
                if drift.pattern.search(scan_line_for(drift, line)):
                    findings.append(
                        {
                            "check": drift.label,
                            "path": relative,
                            "line": line_no,
                            "message": drift.message,
                        }
                    )
    return {
        "ok": not findings,
        "roots": [_relative(path, root) for path in paths],
        "excluded_relative_paths": sorted(excluded_relative_paths),
        "allowed_legacy_reference_tokens": list(ALLOWED_LEGACY_REFERENCE_TOKENS),
        "checked_file_count": len(checked_files),
        "patterns": [drift.label for drift in RENAME_DRIFT_PATTERNS],
        "findings": findings,
        "summary": {
            "finding_count": len(findings),
        },
    }


def run_rename_governance_check(
    *,
    root: Path = ROOT,
    policy_path: Path = RENAME_POLICY_PATH,
    compatibility_aliases: tuple[CompatibilityAlias, ...] = DEFAULT_COMPATIBILITY_ALIASES,
    compatibility_source_roots: tuple[Path, ...] = DEFAULT_COMPATIBILITY_SOURCE_ROOTS,
    compatibility_coverage_roots: tuple[Path, ...] = DEFAULT_COMPATIBILITY_COVERAGE_ROOTS,
    compatibility_doc_roots: tuple[Path, ...] = DEFAULT_COMPATIBILITY_DOC_ROOTS,
    drift_roots: tuple[Path, ...] = DEFAULT_DRIFT_ROOTS,
    excluded_relative_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Run static rename governance checks and return a JSON-serializable report."""

    root = root.resolve()
    excluded = set(DEFAULT_EXCLUDED_RELATIVE_PATHS)
    if excluded_relative_paths:
        excluded.update(excluded_relative_paths)
    policy = _check_policy(root=root, policy_path=policy_path)
    compatibility = _check_compatibility_aliases(
        root=root,
        aliases=compatibility_aliases,
        source_roots=compatibility_source_roots,
        coverage_roots=compatibility_coverage_roots,
        doc_roots=compatibility_doc_roots,
    )
    naming_drift = _scan_naming_drift(root=root, drift_roots=drift_roots, excluded_relative_paths=excluded)
    return {
        "ok": bool(policy["ok"] and compatibility["ok"] and naming_drift["ok"]),
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "root": str(root),
        "policy": policy,
        "compatibility": compatibility,
        "naming_drift": naming_drift,
        "summary": {
            "policy_ok": policy["ok"],
            "compatibility_ok": compatibility["ok"],
            "naming_drift_ok": naming_drift["ok"],
            "alias_count": compatibility["summary"]["alias_count"],
            "drift_finding_count": naming_drift["summary"]["finding_count"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run static rename governance checks for public RAGFlow skills")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--report-json", help="Optional path to write the rename governance report")
    args = parser.parse_args(argv)

    report = run_rename_governance_check(root=Path(args.root))
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
