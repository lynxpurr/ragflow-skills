#!/usr/bin/env python3
"""Check public RAGFlow skill release artifacts for packaging hygiene."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from build_release import DIST_DIR, PUBLIC_SKILLS, ROOT, build_release


TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "htmlcov",
    "venv",
}

PRIVATE_FILE_NAMES = {
    ".env",
    "auth.json",
    "vault.json",
}

ALLOW_MARKER = "release-hygiene: allow"

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("personal_home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+(?:/|$)")),
    (
        "private_ipv4_literal",
        re.compile(
            r"\b(?:10(?:\.[0-9]{1,3}){3}|"
            r"192"
            r"\."
            r"168(?:\.[0-9]{1,3}){2}|"
            r"172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})\b"
        ),
    ),
    (
        "secret_token_literal",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{20,}|"
            r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35})\b"
        ),
    ),
    ("opc_bridge_path", re.compile(r"opc-bridge|shared-infra", re.IGNORECASE)),  # release-hygiene: allow
    ("private_dedao_reference", re.compile(r"dedao|得到|薛兆丰", re.IGNORECASE)),  # release-hygiene: allow
    ("ragflow_localhost_default", re.compile(r"localhost:9380|127\.0\.0\.1:9380")),  # release-hygiene: allow
)


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "check": self.check,
            "path": self.path,
            "message": self.message,
        }
        if self.line is not None:
            payload["line"] = self.line
        return payload


def _is_hidden_local_file(path: Path) -> bool:
    name = path.name
    return (
        name in PRIVATE_FILE_NAMES
        or name.endswith(".local.json")
        or name.endswith(".local.yaml")
        or name.endswith(".local.yml")
        or name.endswith(".pyc")
        or name.endswith(".pyo")
    )


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in relative_parts):
            continue
        if path.is_file():
            yield path


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def scan_private_files(root: Path, *, base: Path) -> list[Finding]:
    findings = []
    for path in iter_files(root):
        if _is_hidden_local_file(path):
            findings.append(
                Finding(
                    check="private_file",
                    path=_relative(path, base),
                    message=f"private or generated file must not be released: {path.name}",
                )
            )
    return findings


def scan_forbidden_patterns(root: Path, *, base: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        text = _read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        Finding(
                            check=label,
                            path=_relative(path, base),
                            line=line_no,
                            message="private or non-portable reference found",
                        )
                    )
    return findings


def validate_skill_frontmatter(skill_root: Path, *, base: Path) -> list[Finding]:
    skill_md = skill_root / "SKILL.md"
    if not skill_md.exists():
        return [
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message="missing SKILL.md",
            )
        ]
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return [
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message="SKILL.md must start with YAML frontmatter",
            )
        ]
    end = text.find("\n---", 4)
    if end == -1:
        return [
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message="SKILL.md frontmatter is not closed",
            )
        ]

    keys = []
    values: dict[str, str] = {}
    for line_no, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip():
            continue
        if ":" not in line:
            return [
                Finding(
                    check="skill_frontmatter",
                    path=_relative(skill_md, base),
                    line=line_no,
                    message="frontmatter line must be a key-value pair",
                )
            ]
        key, value = line.split(":", 1)
        keys.append(key.strip())
        values[key.strip()] = value.strip()

    required = {"name", "description"}
    extra = set(keys) - required
    missing = required - set(keys)
    findings = []
    if missing:
        findings.append(
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message=f"missing required frontmatter keys: {', '.join(sorted(missing))}",
            )
        )
    if extra:
        findings.append(
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message=f"frontmatter has unsupported keys: {', '.join(sorted(extra))}",
            )
        )
    for key in sorted(required):
        if key in values and not values[key]:
            findings.append(
                Finding(
                    check="skill_frontmatter",
                    path=_relative(skill_md, base),
                    message=f"frontmatter key is empty: {key}",
                )
            )
    if values.get("name") and values["name"] != skill_root.name:
        findings.append(
            Finding(
                check="skill_frontmatter",
                path=_relative(skill_md, base),
                message=f"frontmatter name must match folder name {skill_root.name!r}",
            )
        )
    return findings


def validate_release_shape(dist_dir: Path) -> list[Finding]:
    findings = []
    if not dist_dir.exists():
        return [
            Finding(
                check="release_shape",
                path=str(dist_dir),
                message="release dist directory does not exist",
            )
        ]

    skill_dirs = sorted(path.name for path in dist_dir.iterdir() if path.is_dir())
    expected = sorted(PUBLIC_SKILLS)
    if skill_dirs != expected:
        findings.append(
            Finding(
                check="release_shape",
                path=str(dist_dir),
                message=f"dist skill set mismatch: expected {expected}, got {skill_dirs}",
            )
        )

    for skill_name in PUBLIC_SKILLS:
        skill_root = dist_dir / skill_name
        if not skill_root.exists():
            continue
        vendor_init = skill_root / "scripts" / "_vendor" / "ragflow_skill_runtime" / "__init__.py"
        if not vendor_init.exists():
            findings.append(
                Finding(
                    check="release_shape",
                    path=_relative(vendor_init, dist_dir),
                    message="missing vendored ragflow_skill_runtime",
                )
            )
        findings.extend(validate_skill_frontmatter(skill_root, base=dist_dir))
    return findings


def run_hygiene_check(
    *,
    dist_dir: Path = DIST_DIR,
    rebuild: bool = True,
    scan_source: bool = True,
) -> dict[str, Any]:
    if rebuild:
        build_release(dist_dir)

    findings: list[Finding] = []
    findings.extend(validate_release_shape(dist_dir))
    findings.extend(scan_private_files(dist_dir, base=dist_dir))
    findings.extend(scan_forbidden_patterns(dist_dir, base=dist_dir))

    source_roots = []
    if scan_source:
        source_roots = [
            ROOT / "skills",
            ROOT / "packages" / "ragflow-skill-runtime" / "src",
            ROOT / "tools",
        ]
        for root in source_roots:
            findings.extend(scan_private_files(root, base=ROOT))
            findings.extend(scan_forbidden_patterns(root, base=ROOT))
        for skill_name in PUBLIC_SKILLS:
            findings.extend(validate_skill_frontmatter(ROOT / "skills" / skill_name, base=ROOT))

    return {
        "ok": not findings,
        "dist": str(dist_dir),
        "rebuilt": rebuild,
        "scanned_source": scan_source,
        "source_roots": [str(path) for path in source_roots],
        "public_skills": list(PUBLIC_SKILLS),
        "findings": [finding.to_dict() for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check public RAGFlow skill release hygiene")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release artifact directory")
    parser.add_argument("--no-build", action="store_true", help="Check an existing dist directory")
    parser.add_argument("--dist-only", action="store_true", help="Skip public source checks")
    args = parser.parse_args(argv)

    payload = run_hygiene_check(
        dist_dir=Path(args.dist).resolve(),
        rebuild=not args.no_build,
        scan_source=not args.dist_only,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
