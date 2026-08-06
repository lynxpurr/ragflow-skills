#!/usr/bin/env python3
"""Check release version and date metadata drift across public artifacts."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ragflow_version_date_drift_check_v1"
PUBLIC_SKILLS = ("ragflow-doc-to-md", "ragflow-kb-build", "ragflow-query")
DOC_VERSION_PATHS = (
    Path("docs/03-development-plan.md"),
    Path("docs/reference/release-hardening.md"),
    Path("docs/archive/2026/evidence/07-first-release.md"),
    Path("docs/reference/cli-agent-integration.md"),
    Path("docs/reference/release-archive-forward-test-prompts.md"),
)
VERSION_RE = re.compile(r"\bv(?P<version>\d+\.\d+\.\d+)(?:-rc\d+)?\b")
STABLE_RELEASE_RE = re.compile(r"\bstable\b", flags=re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    message: str
    expected: Any = None
    observed: Any = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "check": self.check,
            "path": self.path,
            "message": self.message,
        }
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.observed is not None:
            payload["observed"] = self.observed
        return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _regex_value(path: Path, pattern: str) -> str:
    match = re.search(pattern, _read_text(path), flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _project_version(root: Path) -> str:
    return _regex_value(
        root / "packages" / "ragflow-skill-runtime" / "pyproject.toml",
        r'^\s*version\s*=\s*"([^"]+)"',
    )


def _runtime_version(root: Path) -> str:
    return _regex_value(
        root / "packages" / "ragflow-skill-runtime" / "src" / "ragflow_skill_runtime" / "__init__.py",
        r'^__version__\s*=\s*"([^"]+)"',
    )


def _tool_manifest_version(path: Path) -> str:
    return _regex_value(path, r'"version"\s*:\s*"([^"]+)"')


def _major_minor(version: str) -> str:
    parts = version.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return version


def _export_created_at(root: Path) -> str:
    path = root / "tools" / "export_release_archives.py"
    text = _read_text(path)
    match = re.search(r"^DEFAULT_MTIME\s*=\s*(\d+)", text, flags=re.MULTILINE)
    if not match:
        return ""
    timestamp = int(match.group(1))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _release_manifest(root: Path) -> dict[str, Any]:
    path = root / "release-artifacts" / "release-manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _frontmatter_values(path: Path) -> dict[str, str]:
    text = _read_text(path)
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
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _skill_metadata(root: Path, public_skills: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for skill_name in public_skills:
        path = root / "skills" / skill_name / "SKILL.md"
        values = _frontmatter_values(path)
        items.append(
            {
                "name": skill_name,
                "path": _relative(path, root),
                "version": values.get("version") or values.get("release_version"),
                "date": values.get("date") or values.get("created_at") or values.get("updated_at"),
                "declared_keys": sorted(key for key in values if key in {"version", "release_version", "date", "created_at", "updated_at"}),
            }
        )
    return items


def _doc_versions(root: Path, doc_paths: Iterable[Path]) -> dict[str, list[str]]:
    versions: dict[str, list[str]] = {}
    for relative_path in doc_paths:
        path = root / relative_path
        text = _read_text(path)
        if not text:
            continue
        stable_release_lines = (line for line in text.splitlines() if STABLE_RELEASE_RE.search(line))
        matches = sorted(
            {
                match.group("version")
                for line in stable_release_lines
                for match in VERSION_RE.finditer(line)
            }
        )
        if matches:
            versions[_relative(path, root)] = matches
    return versions


def _check_equal(
    findings: list[Finding],
    *,
    check: str,
    path: str,
    expected: Any,
    observed: Any,
    message: str,
) -> dict[str, Any]:
    ok = observed == expected
    if not ok:
        findings.append(Finding(check=check, path=path, message=message, expected=expected, observed=observed))
    return {
        "name": check,
        "ok": ok,
        "path": path,
        "expected": expected,
        "observed": observed,
    }


def run_version_date_drift_check(
    *,
    root: Path = ROOT,
    public_skills: tuple[str, ...] = PUBLIC_SKILLS,
    doc_version_paths: tuple[Path, ...] = DOC_VERSION_PATHS,
) -> dict[str, Any]:
    """Run static release version/date drift checks."""

    root = root.resolve()
    findings: list[Finding] = []
    checks: list[dict[str, Any]] = []

    package_version = _project_version(root)
    runtime_version = _runtime_version(root)
    expected_release_version = _major_minor(package_version)
    build_release_version = _tool_manifest_version(root / "tools" / "build_release.py")
    export_release_version = _tool_manifest_version(root / "tools" / "export_release_archives.py")
    export_created_at = _export_created_at(root)
    manifest = _release_manifest(root)
    manifest_version = str(manifest.get("version") or "")
    manifest_created_at = str(manifest.get("created_at") or "")
    docs = _doc_versions(root, doc_version_paths)
    doc_versions = sorted({version for versions in docs.values() for version in versions})
    skills = _skill_metadata(root, public_skills)

    checks.append(
        _check_equal(
            findings,
            check="runtime_version_matches_package",
            path="packages/ragflow-skill-runtime/src/ragflow_skill_runtime/__init__.py",
            expected=package_version,
            observed=runtime_version,
            message="runtime __version__ must match package pyproject version",
        )
    )
    for check, path, observed in (
        ("build_release_version_matches_package_major_minor", "tools/build_release.py", build_release_version),
        ("export_release_version_matches_package_major_minor", "tools/export_release_archives.py", export_release_version),
        ("release_manifest_version_matches_package_major_minor", "release-artifacts/release-manifest.json", manifest_version),
    ):
        checks.append(
            _check_equal(
                findings,
                check=check,
                path=path,
                expected=expected_release_version,
                observed=observed,
                message="release manifest version must match package major.minor version",
            )
        )

    checks.append(
        _check_equal(
            findings,
            check="release_manifest_created_at_matches_export_default",
            path="release-artifacts/release-manifest.json",
            expected=export_created_at,
            observed=manifest_created_at,
            message="release manifest created_at must match deterministic archive mtime",
        )
    )
    checks.append(
        _check_equal(
            findings,
            check="docs_stable_versions_match_package",
            path="docs",
            expected=[package_version],
            observed=doc_versions,
            message="documented stable release versions must match package version",
        )
    )

    skill_checks: list[dict[str, Any]] = []
    for item in skills:
        version = item.get("version")
        date = item.get("date")
        version_ok = not version or version == package_version
        date_ok = not date or date in {export_created_at, export_created_at.split("T", 1)[0]}
        if not version_ok:
            findings.append(
                Finding(
                    check="skill_metadata_version_matches_package",
                    path=str(item["path"]),
                    message="public skill metadata version must match package version when declared",
                    expected=package_version,
                    observed=version,
                )
            )
        if not date_ok:
            findings.append(
                Finding(
                    check="skill_metadata_date_matches_release_manifest",
                    path=str(item["path"]),
                    message="public skill metadata date must match release manifest date when declared",
                    expected=export_created_at,
                    observed=date,
                )
            )
        skill_checks.append({**item, "ok": version_ok and date_ok})

    checks.append(
        {
            "name": "skill_metadata_version_date_when_declared",
            "ok": all(item["ok"] for item in skill_checks),
            "skills": skill_checks,
        }
    )

    return {
        "ok": not findings,
        "schema": SCHEMA,
        "root": str(root),
        "expected": {
            "package_version": package_version,
            "release_version": expected_release_version,
            "release_created_at": export_created_at,
        },
        "observed": {
            "runtime_version": runtime_version,
            "build_release_version": build_release_version,
            "export_release_version": export_release_version,
            "release_manifest_version": manifest_version,
            "release_manifest_created_at": manifest_created_at,
            "doc_versions": docs,
            "skill_metadata": skills,
        },
        "checks": checks,
        "findings": [finding.to_dict() for finding in findings],
        "summary": {
            "check_count": len(checks),
            "finding_count": len(findings),
            "doc_file_count": len(docs),
            "skill_count": len(skills),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check release version/date drift")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    args = parser.parse_args(argv)
    payload = run_version_date_drift_check(root=Path(args.root).resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
