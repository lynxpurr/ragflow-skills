#!/usr/bin/env python3
"""Check host-agent forward-test prompts for release archive validation."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ragflow_forward_test_prompt_check_v1"
PROMPT_PATH = Path("docs/12-release-archive-forward-test-prompts.md")
REQUIRED_SECTIONS = (
    "## Requirements",
    "## Hermes Template",
    "## OpenClaw Template",
    "## Expected Report",
)
COMMON_REQUIRED_TERMS = (
    "release-artifacts/",
    "release-manifest.json",
    "ragflow-doc-to-md.tar.gz",
    "ragflow-kb-build.tar.gz",
    "ragflow-query.tar.gz",
    "python3",
    "Do not edit the repository",
    "network",
    "real credentials",
    "live mutation",
    "ragflow-doc-to-md/scripts/convert.py",
    "--mode passthrough",
    "handoff/doc_manifest.json",
    "ragflow-kb-build/scripts/build.py",
    "--dry-run",
    "ragflow-query/scripts/query.py --help",
    "ragflow-query/scripts/query.py ask --help",
    "host-assisted",
    "Report exact commands",
)
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "personal_home_path",
        re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+(?:/|$)"),
        "prompt must not contain personal host paths",
    ),
    (
        "private_ipv4_literal",
        re.compile(
            r"\b(?:10(?:\.[0-9]{1,3}){3}|"
            r"192"
            r"\."
            r"168(?:\.[0-9]{1,3}){2}|"
            r"172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})\b"
        ),
        "prompt must not contain private IP literals",
    ),
    (
        "secret_token_literal",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{20,}|"
            r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35})\b"
        ),
        "prompt must not contain secret-like tokens",
    ),
    (
        "network_url_literal",
        re.compile(r"https?://", re.IGNORECASE),
        "forward-test prompts must stay no-network and avoid endpoint URLs",
    ),
    (
        "ragflow_localhost_default",
        re.compile(r"localhost:9380|127\.0\.0\.1:9380"),  # release-hygiene: allow
        "prompt must not normalize localhost RAGFlow defaults",
    ),
    (
        "live_config_variable",
        re.compile(r"\bRAGFLOW_(?:BASE_URL|API_KEY|DATASET_ID)\b"),
        "prompt must not request live RAGFlow configuration",
    ),
)


@dataclass(frozen=True)
class PromptSpec:
    name: str
    section: str
    host_terms: tuple[str, ...]


DEFAULT_PROMPTS = (
    PromptSpec(
        name="Hermes",
        section="## Hermes Template",
        host_terms=("Hermes", "/tmp/ragflow-forward-test-hermes"),
    ),
    PromptSpec(
        name="OpenClaw",
        section="## OpenClaw Template",
        host_terms=("OpenClaw", "/tmp/ragflow-forward-test-openclaw"),
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _section_text(text: str, heading: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("## ") and not line.startswith("### "):
            end = index
            break
    return "\n".join(lines[start:end])


def _check_required_sections(text: str) -> dict[str, Any]:
    matched = [section for section in REQUIRED_SECTIONS if section in text]
    missing = [section for section in REQUIRED_SECTIONS if section not in matched]
    return {
        "ok": not missing,
        "required_sections": list(REQUIRED_SECTIONS),
        "matched_sections": matched,
        "missing_sections": missing,
    }


def _forbidden_findings(*, text: str, path: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern, message in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                findings.append(
                    {
                        "check": label,
                        "path": path,
                        "line": line_no,
                        "message": message,
                    }
                )
    return findings


def _check_prompt(text: str, spec: PromptSpec) -> dict[str, Any]:
    section = _section_text(text, spec.section)
    required_terms = COMMON_REQUIRED_TERMS + spec.host_terms
    matched = [term for term in required_terms if term in section]
    missing = [term for term in required_terms if term not in matched]
    code_fence_ok = "```text" in section and "```" in section.replace("```text", "", 1)
    return {
        "name": spec.name,
        "section": spec.section,
        "ok": bool(section and not missing and code_fence_ok),
        "found": bool(section),
        "code_fence_ok": code_fence_ok,
        "required_terms": list(required_terms),
        "matched_terms": matched,
        "missing_terms": missing,
        "error": "" if section and not missing and code_fence_ok else "prompt is missing required archive validation coverage",
    }


def run_forward_test_prompt_check(
    *,
    root: Path = ROOT,
    prompt_path: Path = PROMPT_PATH,
    prompt_specs: tuple[PromptSpec, ...] = DEFAULT_PROMPTS,
) -> dict[str, Any]:
    """Run static checks over release archive forward-test prompt templates."""

    root = root.resolve()
    path = (root / prompt_path).resolve() if not prompt_path.is_absolute() else prompt_path.resolve()
    relative_path = _relative(path, root)
    exists = path.exists()
    text = _read_text(path) if exists else ""
    sections = _check_required_sections(text)
    prompts = [_check_prompt(text, spec) for spec in prompt_specs]
    findings = [] if exists else [{"check": "missing_prompt_doc", "path": relative_path, "message": "prompt document is missing"}]
    findings.extend(_forbidden_findings(text=text, path=relative_path))
    for prompt in prompts:
        if not prompt["ok"]:
            findings.append(
                {
                    "check": "prompt_template_coverage",
                    "path": relative_path,
                    "message": f"{prompt['name']} template is missing required coverage",
                    "missing_terms": prompt["missing_terms"],
                }
            )
    if not sections["ok"]:
        findings.append(
            {
                "check": "prompt_doc_sections",
                "path": relative_path,
                "message": "prompt document is missing required sections",
                "missing_sections": sections["missing_sections"],
            }
        )

    failed_prompts = [prompt["name"] for prompt in prompts if not prompt["ok"]]
    return {
        "ok": bool(exists and sections["ok"] and not findings),
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "root": str(root),
        "prompt_path": relative_path,
        "sections": sections,
        "prompts": prompts,
        "findings": findings,
        "summary": {
            "prompt_count": len(prompts),
            "failed_count": len(failed_prompts) + len([finding for finding in findings if finding["check"] != "prompt_template_coverage"]),
            "failed_prompts": failed_prompts,
            "finding_count": len(findings),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run static checks for host-agent forward-test prompts")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--prompt-path", default=str(PROMPT_PATH), help="Prompt document path relative to root")
    parser.add_argument("--report-json", help="Optional path to write the prompt check report")
    args = parser.parse_args(argv)

    report = run_forward_test_prompt_check(root=Path(args.root), prompt_path=Path(args.prompt_path))
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
