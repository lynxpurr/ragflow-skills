#!/usr/bin/env python3
"""Check public RAGFlow skill release artifacts for packaging hygiene."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from build_release import DIST_DIR, PUBLIC_SKILLS, ROOT, build_release
from forward_test_prompt_check import run_forward_test_prompt_check
from generated_markdown_audit import run_generated_markdown_audit
from manifest_schema_check import run_manifest_schema_check
from rename_governance_check import run_rename_governance_check
from runtime_resilience_inventory import run_runtime_resilience_inventory
from schema_identity_check import run_schema_identity_check
from version_date_drift_check import run_version_date_drift_check


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
SUITE_REVIEW_SCHEMA = "ragflow_skill_suite_review_v1"
GENERATED_REPORT_SAFETY_SCHEMA = "ragflow_generated_report_safety_check_v1"
REQUIRED_REFERENCE_FILES = (
    "host-agent-setup.md",
    "user-onboarding-prompt.md",
)
DEFAULT_GENERATED_REPORT_ROOTS = (
    Path("skills"),
    Path("tools/fixtures/generated-reports"),
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
REDACTION_PLACEHOLDER_RE = re.compile(r"<redacted:[^>]+>")
DESCRIPTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "into",
    "needs",
    "of",
    "or",
    "the",
    "to",
    "use",
    "when",
    "with",
}
STALE_REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("skill_suite_stale_reference", re.compile(r"\b(?:ragflux|ragflow-saas|kb ops)\b", re.IGNORECASE)),
    ("skill_suite_private_reference", re.compile(r"dedao|得到|薛兆丰|opc-bridge|shared-infra", re.IGNORECASE)),  # release-hygiene: allow
)
ALLOWED_STALE_REFERENCE_TOKENS = ("chunk-markers-ragflux-like",)
REPEATED_WARNING_PATTERN = re.compile(
    r"\b(?:do not|don't|never|must not|without|does not|no real|real keys|real api keys|secret|"
    r"api key|mutate|mutation|llm)\b",
    re.IGNORECASE,
)
WARNING_REFERENCE_POINTERS = (
    "references/host-agent-setup.md",
    "references/user-onboarding-prompt.md",
)

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


def _skill_frontmatter_values(skill_root: Path) -> dict[str, str]:
    skill_md = skill_root / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _suite_markdown_files(skill_root: Path) -> list[Path]:
    files = [skill_root / "SKILL.md"]
    references_dir = skill_root / "references"
    if references_dir.exists():
        files.extend(sorted(path for path in references_dir.glob("*.md") if path.is_file()))
    return files


def _clean_markdown_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    elif " " in target:
        target = target.split(None, 1)[0]
    target = target.strip("<>")
    target = target.split("#", 1)[0].split("?", 1)[0]
    return target.strip()


def _is_external_or_anchor_link(target: str) -> bool:
    if not target or target.startswith("#"):
        return True
    if target.startswith(("http://", "https://", "mailto:")):
        return True
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target))


def scan_markdown_links(skill_root: Path, *, base: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _suite_markdown_files(skill_root):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK_RE.finditer(line):
                target = _clean_markdown_link_target(match.group(1))
                if _is_external_or_anchor_link(target):
                    continue
                if target.startswith("/"):
                    findings.append(
                        Finding(
                            check="skill_suite_absolute_link",
                            path=_relative(path, base),
                            line=line_no,
                            message="SKILL.md and references must use relative links, anchors, or external URLs",
                        )
                    )
                    continue
                resolved = (path.parent / target).resolve()
                try:
                    resolved.relative_to(skill_root.resolve())
                except ValueError:
                    findings.append(
                        Finding(
                            check="skill_suite_link_escapes_skill",
                            path=_relative(path, base),
                            line=line_no,
                            message=f"relative link escapes the skill directory: {target}",
                        )
                    )
                    continue
                if not resolved.exists():
                    findings.append(
                        Finding(
                            check="skill_suite_broken_link",
                            path=_relative(path, base),
                            line=line_no,
                            message=f"broken relative link: {target}",
                        )
                    )
    return findings


def scan_stale_skill_references(skill_root: Path, *, base: Path) -> list[Finding]:
    findings: list[Finding] = []

    def scan_line_for(label: str, line: str) -> str:
        if label != "skill_suite_stale_reference":
            return line
        sanitized = line
        for token in ALLOWED_STALE_REFERENCE_TOKENS:
            sanitized = re.sub(re.escape(token), "", sanitized, flags=re.IGNORECASE)
        return sanitized

    for path in _suite_markdown_files(skill_root):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in STALE_REFERENCE_PATTERNS:
                if pattern.search(scan_line_for(label, line)):
                    findings.append(
                        Finding(
                            check=label,
                            path=_relative(path, base),
                            line=line_no,
                            message="stale, private, or removed skill reference found",
                        )
                    )
    return findings


def validate_required_references(
    skill_root: Path,
    *,
    base: Path,
    required_reference_files: tuple[str, ...] = REQUIRED_REFERENCE_FILES,
) -> list[Finding]:
    findings: list[Finding] = []
    references_dir = skill_root / "references"
    for filename in required_reference_files:
        path = references_dir / filename
        if not path.exists():
            findings.append(
                Finding(
                    check="skill_suite_missing_reference",
                    path=_relative(path, base),
                    message=f"missing shared reference file: {filename}",
                )
            )
    return findings


def validate_shared_reference_hashes(
    skills_root: Path,
    *,
    base: Path,
    public_skills: tuple[str, ...],
    required_reference_files: tuple[str, ...] = REQUIRED_REFERENCE_FILES,
) -> list[Finding]:
    findings: list[Finding] = []
    for filename in required_reference_files:
        digests: dict[str, list[str]] = {}
        for skill_name in public_skills:
            path = skills_root / skill_name / "references" / filename
            if not path.exists():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digests.setdefault(digest, []).append(skill_name)
        if len(digests) > 1:
            findings.append(
                Finding(
                    check="skill_suite_reference_drift",
                    path=_relative(skills_root, base),
                    message=f"shared reference file differs across skills: {filename}",
                )
            )
    return findings


def _description_tokens(description: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", description.lower())
        if len(token) > 2 and token not in DESCRIPTION_STOPWORDS
    }


def detect_description_overlap(
    skills_root: Path,
    *,
    base: Path,
    public_skills: tuple[str, ...],
    threshold: float = 0.78,
) -> list[Finding]:
    findings: list[Finding] = []
    descriptions: dict[str, str] = {}
    for skill_name in public_skills:
        values = _skill_frontmatter_values(skills_root / skill_name)
        description = values.get("description", "")
        if description:
            descriptions[skill_name] = description
    names = sorted(descriptions)
    for left_index, left_name in enumerate(names):
        left_tokens = _description_tokens(descriptions[left_name])
        if not left_tokens:
            continue
        for right_name in names[left_index + 1 :]:
            right_tokens = _description_tokens(descriptions[right_name])
            if not right_tokens:
                continue
            union = left_tokens | right_tokens
            score = len(left_tokens & right_tokens) / len(union) if union else 0.0
            if descriptions[left_name] == descriptions[right_name] or score >= threshold:
                findings.append(
                    Finding(
                        check="skill_suite_description_overlap",
                        path=_relative(skills_root / left_name / "SKILL.md", base),
                        message=(
                            f"description overlaps with {right_name}/SKILL.md "
                            f"(jaccard={score:.2f})"
                        ),
                    )
                )
    return findings


def _normalize_warning_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line.strip())
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip().lower()


def _is_centralized_warning_pointer(line: str) -> bool:
    lowered = line.lower()
    return any(pointer in lowered for pointer in WARNING_REFERENCE_POINTERS)


def _is_required_reference_file(path: Path, skill_root: Path) -> bool:
    references_dir = skill_root / "references"
    try:
        relative = path.relative_to(references_dir)
    except ValueError:
        return False
    return len(relative.parts) == 1 and relative.name in REQUIRED_REFERENCE_FILES


def detect_repeated_warnings(
    skills_root: Path,
    *,
    base: Path,
    public_skills: tuple[str, ...],
    min_skill_count: int = 2,
) -> list[Finding]:
    occurrences: dict[str, list[dict[str, Any]]] = {}
    for skill_name in public_skills:
        skill_root = skills_root / skill_name
        for path in _suite_markdown_files(skill_root):
            if not path.exists() or _is_required_reference_file(path, skill_root):
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                normalized = _normalize_warning_line(line)
                if (
                    not normalized
                    or _is_centralized_warning_pointer(normalized)
                    or not REPEATED_WARNING_PATTERN.search(normalized)
                ):
                    continue
                occurrences.setdefault(normalized, []).append(
                    {
                        "skill": skill_name,
                        "path": path,
                        "line": line_no,
                    }
                )

    findings: list[Finding] = []
    for warning, warning_occurrences in sorted(occurrences.items()):
        skill_names = sorted({str(item["skill"]) for item in warning_occurrences})
        if len(skill_names) < min_skill_count:
            continue
        first = sorted(warning_occurrences, key=lambda item: (_relative(item["path"], base), item["line"]))[0]
        findings.append(
            Finding(
                check="skill_suite_repeated_warning",
                path=_relative(first["path"], base),
                line=int(first["line"]),
                message=(
                    f"warning text is repeated across {len(skill_names)} skills "
                    f"({', '.join(skill_names)}); centralize detailed guidance in "
                    "references/host-agent-setup.md and link to it"
                ),
            )
        )
    return findings


def _is_redaction_sidecar(path: Path) -> bool:
    return path.name.endswith((".redaction.json", "_redaction.json"))


def _candidate_redaction_sidecars(path: Path) -> tuple[Path, ...]:
    if _is_redaction_sidecar(path):
        return ()
    return (
        path.with_name(f"{path.stem}.redaction.json"),
        path.with_name(f"{path.stem}_redaction.json"),
    )


def _valid_redaction_sidecar(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return (
        payload.get("schema") == "ragflow_report_redaction_report_v1"
        and payload.get("ok") is True
        and int(summary.get("redaction_count") or 0) > 0
    )


def _iter_generated_report_candidates(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in iter_files(root):
        if path.suffix.lower() in {".json", ".md", ".yaml", ".yml"}:
            yield path


def run_generated_report_safety_check(
    *,
    root: Path = ROOT,
    report_roots: tuple[Path, ...] = DEFAULT_GENERATED_REPORT_ROOTS,
) -> dict[str, Any]:
    """Scan public generated reports/examples for raw sensitive literals and redaction sidecars."""

    root = root.resolve()
    findings: list[Finding] = []
    checked_files: list[str] = []
    placeholder_files: list[str] = []
    sidecar_files: list[str] = []
    for relative_root in report_roots:
        report_root = (root / relative_root).resolve() if not relative_root.is_absolute() else relative_root.resolve()
        for path in _iter_generated_report_candidates(report_root):
            text = _read_text(path)
            if text is None:
                continue
            relative_path = _relative(path, root)
            checked_files.append(relative_path)
            if _is_redaction_sidecar(path):
                sidecar_files.append(relative_path)
                if not _valid_redaction_sidecar(path):
                    findings.append(
                        Finding(
                            check="generated_report_redaction_sidecar",
                            path=relative_path,
                            message="redaction sidecar must use ragflow_report_redaction_report_v1 with redaction_count > 0",
                        )
                    )
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if ALLOW_MARKER in line:
                    continue
                for label, pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            Finding(
                                check="generated_report_sensitive_literal",
                                path=relative_path,
                                line=line_no,
                                message=f"generated report or example contains unredacted sensitive literal: {label}",
                            )
                        )
            if REDACTION_PLACEHOLDER_RE.search(text):
                placeholder_files.append(relative_path)
                if not any(_valid_redaction_sidecar(sidecar) for sidecar in _candidate_redaction_sidecars(path)):
                    findings.append(
                        Finding(
                            check="generated_report_missing_redaction_sidecar",
                            path=relative_path,
                            message="generated report with redaction placeholders must have a valid adjacent redaction sidecar",
                        )
                    )

    return {
        "ok": not findings,
        "schema": GENERATED_REPORT_SAFETY_SCHEMA,
        "root": str(root),
        "report_roots": [_relative((root / path).resolve() if not path.is_absolute() else path.resolve(), root) for path in report_roots],
        "summary": {
            "checked_file_count": len(checked_files),
            "placeholder_file_count": len(placeholder_files),
            "sidecar_file_count": len(sidecar_files),
            "finding_count": len(findings),
        },
        "checked_files": sorted(checked_files),
        "placeholder_files": sorted(placeholder_files),
        "sidecar_files": sorted(sidecar_files),
        "findings": [finding.to_dict() for finding in findings],
    }


def run_suite_review(
    *,
    skills_root: Path = ROOT / "skills",
    public_skills: tuple[str, ...] = PUBLIC_SKILLS,
) -> dict[str, Any]:
    """Run static suite-drift checks over the public skill set."""

    skills_root = skills_root.resolve()
    findings: list[Finding] = []
    checked_files: list[str] = []
    for skill_name in public_skills:
        skill_root = skills_root / skill_name
        if not skill_root.exists():
            findings.append(
                Finding(
                    check="skill_suite_missing_skill",
                    path=_relative(skill_root, skills_root),
                    message="public skill directory is missing",
                )
            )
            continue
        findings.extend(validate_skill_frontmatter(skill_root, base=skills_root))
        findings.extend(validate_required_references(skill_root, base=skills_root))
        findings.extend(scan_markdown_links(skill_root, base=skills_root))
        findings.extend(scan_stale_skill_references(skill_root, base=skills_root))
        checked_files.extend(_relative(path, skills_root) for path in _suite_markdown_files(skill_root) if path.exists())

    findings.extend(
        validate_shared_reference_hashes(
            skills_root,
            base=skills_root,
            public_skills=public_skills,
        )
    )
    findings.extend(detect_description_overlap(skills_root, base=skills_root, public_skills=public_skills))
    findings.extend(detect_repeated_warnings(skills_root, base=skills_root, public_skills=public_skills))
    return {
        "ok": not findings,
        "schema": SUITE_REVIEW_SCHEMA,
        "skills_root": str(skills_root),
        "public_skills": list(public_skills),
        "required_reference_files": list(REQUIRED_REFERENCE_FILES),
        "summary": {
            "skill_count": len(public_skills),
            "checked_file_count": len(checked_files),
            "finding_count": len(findings),
            "repeated_warning_count": sum(1 for finding in findings if finding.check == "skill_suite_repeated_warning"),
        },
        "checked_files": sorted(checked_files),
        "findings": [finding.to_dict() for finding in findings],
    }


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
    suite_review: bool = False,
    schema_identity: bool = True,
    manifest_schema: bool = True,
    rename_governance: bool = True,
    forward_test_prompts: bool = True,
    version_date_drift: bool = True,
    generated_report_safety: bool = True,
    runtime_resilience_inventory: bool = True,
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

    payload: dict[str, Any] = {
        "ok": not findings,
        "dist": str(dist_dir),
        "rebuilt": rebuild,
        "scanned_source": scan_source,
        "source_roots": [str(path) for path in source_roots],
        "public_skills": list(PUBLIC_SKILLS),
        "findings": [finding.to_dict() for finding in findings],
    }
    if suite_review:
        suite_payload = run_suite_review(skills_root=ROOT / "skills", public_skills=PUBLIC_SKILLS)
        payload["suite_review"] = suite_payload
        payload["ok"] = bool(payload["ok"] and suite_payload["ok"])
    if schema_identity:
        schema_identity_payload = run_schema_identity_check(root=ROOT)
        payload["schema_identity"] = schema_identity_payload
        payload["ok"] = bool(payload["ok"] and schema_identity_payload["ok"])
    if manifest_schema:
        manifest_schema_payload = run_manifest_schema_check(root=ROOT)
        payload["manifest_schema"] = manifest_schema_payload
        payload["ok"] = bool(payload["ok"] and manifest_schema_payload["ok"])
    if rename_governance:
        rename_governance_payload = run_rename_governance_check(root=ROOT)
        payload["rename_governance"] = rename_governance_payload
        payload["ok"] = bool(payload["ok"] and rename_governance_payload["ok"])
    if forward_test_prompts:
        forward_test_prompt_payload = run_forward_test_prompt_check(root=ROOT)
        payload["forward_test_prompts"] = forward_test_prompt_payload
        payload["ok"] = bool(payload["ok"] and forward_test_prompt_payload["ok"])
    if version_date_drift:
        version_date_drift_payload = run_version_date_drift_check(root=ROOT)
        payload["version_date_drift"] = version_date_drift_payload
        payload["ok"] = bool(payload["ok"] and version_date_drift_payload["ok"])
    if generated_report_safety:
        generated_report_payload = run_generated_report_safety_check(root=ROOT)
        payload["generated_report_safety"] = generated_report_payload
        payload["ok"] = bool(payload["ok"] and generated_report_payload["ok"])
        generated_markdown_payload = run_generated_markdown_audit(root=ROOT)
        payload["generated_markdown_audit"] = generated_markdown_payload
        payload["ok"] = bool(payload["ok"] and generated_markdown_payload["ok"])
    if runtime_resilience_inventory:
        runtime_resilience_payload = run_runtime_resilience_inventory(root=ROOT)
        payload["runtime_resilience_inventory"] = runtime_resilience_payload
        payload["ok"] = bool(payload["ok"] and runtime_resilience_payload["ok"])
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check public RAGFlow skill release hygiene")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release artifact directory")
    parser.add_argument("--no-build", action="store_true", help="Check an existing dist directory")
    parser.add_argument("--dist-only", action="store_true", help="Skip public source checks")
    parser.add_argument("--suite-review", action="store_true", help="Run static public skill suite drift checks")
    parser.add_argument("--skip-schema-identity", action="store_true", help="Skip static schema identity checks")
    parser.add_argument("--skip-manifest-schema", action="store_true", help="Skip public manifest JSON Schema checks")
    parser.add_argument("--skip-rename-governance", action="store_true", help="Skip static rename governance checks")
    parser.add_argument("--skip-forward-test-prompts", action="store_true", help="Skip host-agent forward-test prompt checks")
    parser.add_argument("--skip-version-date-drift", action="store_true", help="Skip static version/date drift checks")
    parser.add_argument("--skip-generated-report-safety", action="store_true", help="Skip generated report/example safety checks")
    parser.add_argument("--skip-runtime-resilience-inventory", action="store_true", help="Skip static runtime-resilience inventory checks")
    args = parser.parse_args(argv)

    payload = run_hygiene_check(
        dist_dir=Path(args.dist).resolve(),
        rebuild=not args.no_build,
        scan_source=not args.dist_only,
        suite_review=args.suite_review,
        schema_identity=not args.skip_schema_identity,
        manifest_schema=not args.skip_manifest_schema,
        rename_governance=not args.skip_rename_governance,
        forward_test_prompts=not args.skip_forward_test_prompts,
        version_date_drift=not args.skip_version_date_drift,
        generated_report_safety=not args.skip_generated_report_safety,
        runtime_resilience_inventory=not args.skip_runtime_resilience_inventory,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
