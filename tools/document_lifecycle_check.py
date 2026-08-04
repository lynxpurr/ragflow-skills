#!/usr/bin/env python3
"""Validate repository documentation lifecycle, ownership, links, and safety."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ragflow_document_lifecycle_check_v1"
REGISTRY_PATH = Path("docs/document-registry.json")
ALLOWED_DOC_TYPES = {"index", "roadmap", "spec", "plan", "reference", "evidence", "template"}
ALLOWED_STATUSES = {
    "draft",
    "proposed",
    "approved",
    "active",
    "gated",
    "implemented",
    "superseded",
    "historical",
    "reference",
}
CANONICAL_STATUSES = {"proposed", "approved", "active", "gated", "reference"}
REQUIRED_ENTRY_KEYS = {
    "path",
    "doc_type",
    "topic",
    "status",
    "canonical",
    "implementation_authority",
    "owner",
    "related",
    "legacy_metadata",
    "legacy_path",
    "baseline_class",
}
REQUIRED_METADATA_KEYS = {
    "doc_type",
    "topic",
    "status",
    "created",
    "updated",
    "canonical",
    "implementation_authority",
    "supersedes",
    "superseded_by",
    "related",
}
BASELINE_CLASS_TO_COUNT_KEY = {
    "historical_candidate": "historical_count",
    "reference_candidate": "reference_count",
    "active_owner": "active_owner_count",
}
ALLOWED_BASELINE_CLASSES = set(BASELINE_CLASS_TO_COUNT_KEY) | {"wave1_governance"}
ARCHIVE_REASONS = {"completed", "superseded", "rejected", "evidence_only"}
WAVE1_LEGACY_METADATA_PATHS = frozenset(
    {
        "docs/03-development-plan.md",
        "docs/10-legacy-feature-gap-closure-design.md",
        "docs/13-post-cli-adapter-planning.md",
        "docs/14-optional-llm-backend-planning.md",
        "docs/15-field-trial-observation-plan.md",
        "docs/16-system-closeout-report.md",
        "docs/19-ragflux-capability-parity-plan.md",  # release-hygiene: allow - frozen Wave 1 legacy path
        "docs/20-ragflow-doc-to-md-ingest-quality-plan.md",
        "docs/29-kb-build-strict-regression-quality-plan.md",
        "docs/31-hermes-e2e-improvement-follow-up-plan.md",
        "docs/32-retirement-transition-action-plan.md",
        "docs/35-standard-benchmark-dataset-integration-plan.md",
        "docs/36-ragflow-kb-parameter-materialization-plan.md",
        "docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md",
        "docs/39-benchmark-evidence-strengthening-hermes-test.md",
        "docs/40-marker-aware-evidence-validation-and-promotion-plan.md",
        "docs/41-marker-aware-candidate-snapshot-hermes-l0.md",
        "docs/42-financebench-marker-aware-l3-disposable-validation.md",
        "docs/43-agent-session-handoff-lessons.md",
        "docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md",
        "docs/specs/2026-08-02-financebench-new-minimal-l3-design.md",
        "docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md",
        "docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md",
        "docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md",
        "docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md",
    }
)
WAVE1_LEGACY_PATHS = frozenset(path for path in WAVE1_LEGACY_METADATA_PATHS if path.startswith("docs/superpowers/"))
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"!?\[([^\]]+)\]\[([^\]]*)\]")
REFERENCE_DEFINITION_RE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)")
INLINE_CODE_RE = re.compile(r"(`+).*?\1")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
EXTERNAL_LINK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
CHECKED_TASK_RE = re.compile(r"- \[x\]")
OPEN_TASK_RE = re.compile(r"- \[ \]")
GATE_RE = re.compile(r"(?im)^\s*(?:gate|blocked on|blocking condition)\s*:")
HISTORICAL_IMPERATIVE_RE = re.compile(
    r"\b(?:run|execute|implement|continue|resume|deploy|mutate|delete)\b",
    re.IGNORECASE,
)
NON_AUTHORITY_RE = re.compile(r"\b(?:do not|must not|no current|non-authoritative|historical only)\b", re.IGNORECASE)
PRIVATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("personal_home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+(?:/|$)")),
    (
        "private_ipv4_literal",
        re.compile(
            r"\b(?:10(?:\.[0-9]{1,3}){3}|192\.168(?:\.[0-9]{1,3}){2}|"
            r"172\.(?:1[6-9]|2[0-9]|3[01])(?:\.[0-9]{1,3}){2})\b"
        ),
    ),
    (
        "secret_token_literal",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
            r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35})\b"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "check": self.check,
            "path": self.path,
            "message": self.message,
        }
        if self.line is not None:
            payload["line"] = self.line
        return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("frontmatter list must use JSON-compatible syntax") from exc
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_frontmatter_text(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    lines = text.splitlines(keepends=True)
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ValueError("frontmatter is not closed")
    metadata: dict[str, object] = {}
    pending_list_key: str | None = None
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            if pending_list_key is None or not stripped.startswith("- "):
                raise ValueError("frontmatter supports only top-level scalars and lists")
            item = stripped[2:].strip()
            if not item:
                raise ValueError("frontmatter list items must be non-empty")
            current = metadata[pending_list_key]
            if current is None:
                current = []
                metadata[pending_list_key] = current
            if not isinstance(current, list):
                raise ValueError("frontmatter list key must contain only list items")
            current.append(_parse_scalar(item))
            continue
        if ":" not in line:
            raise ValueError("frontmatter line must contain a colon")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in metadata:
            raise ValueError("frontmatter keys must be unique and non-empty")
        if value.strip():
            metadata[key] = _parse_scalar(value)
            pending_list_key = None
        else:
            metadata[key] = None
            pending_list_key = key
    return metadata, "".join(lines[end_index + 1 :])


def parse_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    return _parse_frontmatter_text(_read_text(path))


def load_registry(root: Path, registry_path: Path = REGISTRY_PATH) -> dict[str, object]:
    path = registry_path if registry_path.is_absolute() else root / registry_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("document registry is missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("document registry must be a JSON object")
    return payload


def _markdown_files(root: Path) -> list[Path]:
    docs_root = root / "docs"
    if not docs_root.exists():
        return []
    return sorted(path for path in docs_root.rglob("*.md") if path.is_file() or path.is_symlink())


def _is_normalized_document_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and len(path.parts) >= 2
        and path.parts[0] == "docs"
        and ".." not in path.parts
        and value == path.as_posix()
        and path.suffix == ".md"
    )


def _outside_fence_lines(body: str) -> Iterable[tuple[int, str]]:
    fence_character: str | None = None
    fence_length = 0
    for line_no, line in enumerate(body.splitlines(), start=1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is None:
            yield line_no, line


def _link_target(path: Path, raw_target: str, root: Path) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<"):
        closing = target.find(">", 1)
        target = target[1:closing] if closing >= 0 else target[1:]
    else:
        target = target.split(maxsplit=1)[0]
    if not target or target.startswith("#") or EXTERNAL_LINK_RE.match(target):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    candidate = (root / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
    return candidate.resolve()


def _reference_label(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _link_finding(
    *,
    document_path: str,
    file_path: Path,
    raw_target: str,
    root: Path,
    line_no: int,
) -> Finding | None:
    target = _link_target(file_path, raw_target, root)
    if target is None:
        return None
    try:
        target.relative_to(root)
    except ValueError:
        return Finding(
            "markdown_link_outside_repository",
            document_path,
            "repository-relative Markdown link resolves outside the repository",
            line_no,
        )
    if not target.exists():
        return Finding(
            "broken_markdown_link",
            document_path,
            "repository-relative Markdown link does not resolve",
            line_no,
        )
    return None


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item) for item in value)


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or ISO_DATE_RE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _roadmap_checkbox_counts(text: str) -> tuple[int, int]:
    lines = text.splitlines()
    checked = sum(bool(CHECKED_TASK_RE.search(line)) for line in lines)
    open_count = sum(bool(OPEN_TASK_RE.search(line)) for line in lines)
    return checked, open_count


def _failure_payload(root: Path, registry_path: Path, finding: Finding) -> dict[str, object]:
    return {
        "ok": False,
        "schema": SCHEMA,
        "root": str(root),
        "registry_path": str(registry_path),
        "summary": {"document_count": 0, "registry_count": 0, "finding_count": 1},
        "documents": [],
        "findings": [finding.to_dict()],
    }


def run_document_lifecycle_check(
    *,
    root: Path = ROOT,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, object]:
    root = root.resolve()
    relative_registry = registry_path if not registry_path.is_absolute() else Path(_relative(registry_path, root))
    try:
        registry = load_registry(root, registry_path)
    except ValueError as exc:
        return _failure_payload(
            root,
            relative_registry,
            Finding("registry_load", str(relative_registry), str(exc)),
        )

    findings: list[Finding] = []
    if registry.get("schema") != "ragflow_document_registry_v1":
        findings.append(Finding("registry_schema", str(relative_registry), "unexpected registry schema"))
    if type(registry.get("adopted")) is not bool:
        findings.append(Finding("invalid_adopted", str(relative_registry), "adopted must be boolean"))
    entries_value = registry.get("documents")
    entries = entries_value if isinstance(entries_value, list) else []
    if not isinstance(entries_value, list):
        findings.append(Finding("registry_shape", str(relative_registry), "documents must be a list"))

    entry_by_path: dict[str, dict[str, object]] = {}
    entry_paths: list[str] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            findings.append(Finding("registry_entry", str(relative_registry), "document entry must be an object"))
            continue
        missing_keys = REQUIRED_ENTRY_KEYS - set(raw_entry)
        path_value = raw_entry.get("path")
        path = str(path_value) if isinstance(path_value, str) else str(relative_registry)
        if missing_keys:
            findings.append(
                Finding(
                    "registry_entry",
                    path,
                    f"missing registry keys: {', '.join(sorted(missing_keys))}",
                )
            )
            continue
        if path in entry_by_path:
            findings.append(Finding("duplicate_registry_path", path, "path is registered more than once"))
            continue
        entry = dict(raw_entry)
        entry_by_path[path] = entry
        entry_paths.append(path)
        if not _is_normalized_document_path(path_value):
            findings.append(Finding("invalid_document_path", path, "document path must be normalized under docs and end in .md"))
        if entry.get("doc_type") not in ALLOWED_DOC_TYPES:
            findings.append(Finding("invalid_doc_type", path, "unrecognized document type"))
        if entry.get("status") not in ALLOWED_STATUSES:
            findings.append(Finding("invalid_status", path, "unrecognized lifecycle status"))
        if not isinstance(entry.get("topic"), str) or not str(entry.get("topic")).strip():
            findings.append(Finding("invalid_topic", path, "topic must be a non-empty string"))
        if not isinstance(entry.get("canonical"), bool):
            findings.append(Finding("invalid_canonical", path, "canonical must be boolean"))
        if not isinstance(entry.get("implementation_authority"), bool):
            findings.append(Finding("invalid_authority", path, "implementation_authority must be boolean"))
        elif entry.get("implementation_authority") is True and (
            entry.get("doc_type") not in {"spec", "plan"}
            or entry.get("status") not in {"approved", "active"}
        ):
            findings.append(
                Finding(
                    "invalid_authority",
                    path,
                    "implementation authority requires an approved or active spec or plan",
                )
            )
        for key in ("legacy_metadata", "legacy_path"):
            if not isinstance(entry.get(key), bool):
                findings.append(Finding("invalid_legacy_flag", path, f"{key} must be boolean"))
        if entry.get("legacy_metadata") is True and path not in WAVE1_LEGACY_METADATA_PATHS:
            findings.append(Finding("invalid_legacy_exemption", path, "legacy metadata exemption is not in the reviewed baseline"))
        if entry.get("legacy_path") is True and path not in WAVE1_LEGACY_PATHS:
            findings.append(Finding("invalid_legacy_exemption", path, "legacy path exemption is not in the reviewed baseline"))
        if not _is_string_list(entry.get("related")):
            findings.append(Finding("invalid_related", path, "related must be a list of registered document paths"))
        if entry.get("baseline_class") not in ALLOWED_BASELINE_CLASSES:
            findings.append(Finding("invalid_baseline_class", path, "unrecognized baseline class"))

    if entry_paths != sorted(entry_paths):
        findings.append(Finding("registry_order", str(relative_registry), "document entries must be sorted by path"))

    baseline = registry.get("baseline")
    if not isinstance(baseline, dict):
        findings.append(Finding("baseline_mismatch", str(relative_registry), "baseline must be an object"))
    else:
        expected_counts = {
            count_key: sum(entry.get("baseline_class") == class_name for entry in entry_by_path.values())
            for class_name, count_key in BASELINE_CLASS_TO_COUNT_KEY.items()
        }
        expected_counts["document_count"] = sum(expected_counts.values())
        for key, expected in expected_counts.items():
            if type(baseline.get(key)) is not int or baseline.get(key) != expected:
                findings.append(Finding("baseline_mismatch", str(relative_registry), f"baseline {key} must equal {expected}"))
        for key in ("roadmap_checked", "roadmap_open"):
            if type(baseline.get(key)) is not int or int(baseline[key]) < 0:
                findings.append(Finding("baseline_mismatch", str(relative_registry), f"baseline {key} must be a non-negative integer"))

    for path, entry in entry_by_path.items():
        related = entry.get("related")
        if _is_string_list(related) and any(item not in entry_by_path for item in related):
            findings.append(Finding("invalid_related", path, "related must reference registered documents"))
        owner = entry.get("owner")
        owner_entry = entry_by_path.get(owner) if isinstance(owner, str) else None
        if owner is not None and owner_entry is None:
            findings.append(Finding("invalid_owner", path, "owner must reference a registered document"))
        if entry.get("doc_type") == "evidence" and entry.get("legacy_metadata") is not True:
            if owner is None or (owner_entry is not None and owner_entry.get("doc_type") not in {"spec", "plan"}):
                findings.append(Finding("invalid_owner", path, "new evidence owner must be a registered spec or plan"))

    actual_paths: list[str] = []
    unsafe_document_paths: set[str] = set()
    for file_path in _markdown_files(root):
        try:
            path = file_path.relative_to(root).as_posix()
        except ValueError:
            continue
        actual_paths.append(path)
        try:
            file_path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            unsafe_document_paths.add(path)
            findings.append(Finding("document_symlink", path, "Markdown document must not be a symlink or resolve outside the repository"))
            continue
        if file_path.is_symlink():
            unsafe_document_paths.add(path)
            findings.append(Finding("document_symlink", path, "Markdown document must not be a symlink or resolve outside the repository"))
    actual_path_set = set(actual_paths)
    for path in sorted(set(actual_paths) - set(entry_by_path)):
        findings.append(Finding("unregistered_document", path, "Markdown document is not registered"))
    for path in sorted(set(entry_by_path) - set(actual_paths)):
        findings.append(Finding("missing_registered_document", path, "registered Markdown document is missing"))

    governing_spec = registry.get("governing_spec")
    governing_entry = entry_by_path.get(governing_spec) if isinstance(governing_spec, str) else None
    if (
        governing_entry is None
        or governing_spec not in actual_path_set
        or governing_entry.get("doc_type") != "spec"
        or governing_entry.get("canonical") is not True
        or governing_entry.get("status") not in {"approved", "active"}
    ):
        findings.append(
            Finding(
                "invalid_governing_spec",
                str(relative_registry),
                "governing_spec must be an existing registered canonical approved or active spec",
            )
        )

    roadmap_paths = [
        path
        for path, entry in entry_by_path.items()
        if entry.get("doc_type") == "roadmap"
        and entry.get("canonical") is True
        and entry.get("status") == "active"
    ]
    if len(roadmap_paths) != 1:
        findings.append(
            Finding(
                "roadmap_governance",
                str(relative_registry),
                "registry must define exactly one canonical active roadmap",
            )
        )

    canonical_topics: dict[str, list[str]] = {}
    adopted = registry.get("adopted") is True
    document_text_by_path: dict[str, str] = {}
    for path in actual_paths:
        entry = entry_by_path.get(path)
        file_path = root / path
        if path in unsafe_document_paths:
            continue
        if entry is None:
            if adopted and path.startswith("docs/superpowers/"):
                findings.append(Finding("post_adoption_tool_path", path, "post-adoption tool-specific document path is forbidden"))
            continue
        try:
            document_text = _read_text(file_path)
        except (OSError, UnicodeDecodeError):
            findings.append(Finding("document_read", path, "document could not be read as UTF-8"))
            continue
        document_text_by_path[path] = document_text
        try:
            metadata, body = _parse_frontmatter_text(document_text)
        except ValueError as exc:
            findings.append(Finding("frontmatter", path, str(exc)))
            metadata, body = {}, document_text

        legacy_metadata = entry.get("legacy_metadata") is True
        related = metadata.get("related")
        supersedes = metadata.get("supersedes")
        superseded_by = metadata.get("superseded_by")
        for key, value in (("related", related), ("supersedes", supersedes)):
            if key not in metadata:
                continue
            if not _is_string_list(value):
                findings.append(Finding("invalid_metadata_type", path, f"metadata {key} must be a string list"))
            elif any(item not in entry_by_path for item in value):
                findings.append(
                    Finding("invalid_metadata_reference", path, f"metadata {key} must reference registered documents")
                )
        if "superseded_by" in metadata:
            if superseded_by is not None and not isinstance(superseded_by, str):
                findings.append(
                    Finding("invalid_metadata_type", path, "metadata superseded_by must be null or a document path")
                )
            elif isinstance(superseded_by, str) and superseded_by not in entry_by_path:
                findings.append(
                    Finding("invalid_metadata_reference", path, "metadata superseded_by must reference a registered document")
                )
        if not legacy_metadata:
            missing_metadata = REQUIRED_METADATA_KEYS - set(metadata)
            if missing_metadata:
                findings.append(
                    Finding(
                        "metadata_missing",
                        path,
                        f"missing metadata keys: {', '.join(sorted(missing_metadata))}",
                    )
                )
            for key in ("doc_type", "topic", "status", "canonical", "implementation_authority"):
                if key in metadata and metadata[key] != entry.get(key):
                    findings.append(Finding("metadata_mismatch", path, f"metadata disagrees with registry for {key}"))
            for key in ("created", "updated"):
                if key in metadata and not _is_iso_date(metadata[key]):
                    findings.append(
                        Finding(
                            "invalid_metadata_date",
                            path,
                            f"metadata {key} must be a YYYY-MM-DD calendar date",
                        )
                    )
            if metadata.get("owner_spec") != entry.get("owner"):
                findings.append(Finding("metadata_mismatch", path, "owner_spec disagrees with registry owner"))
            if _is_string_list(related) and related != entry.get("related"):
                findings.append(Finding("metadata_mismatch", path, "metadata disagrees with registry for related"))

        status = str(entry.get("status"))
        topic = str(entry.get("topic"))
        if entry.get("canonical") is True and status in CANONICAL_STATUSES:
            canonical_topics.setdefault(topic, []).append(path)
        if status == "gated" and not legacy_metadata and not GATE_RE.search(body):
            findings.append(Finding("missing_named_gate", path, "gated document must name its blocking condition"))

        if entry.get("doc_type") == "plan" and not legacy_metadata:
            owner = entry.get("owner")
            owner_entry = entry_by_path.get(str(owner)) if isinstance(owner, str) else None
            if (
                owner_entry is None
                or owner_entry.get("doc_type") != "spec"
                or owner_entry.get("status") not in {"approved", "active"}
            ):
                findings.append(Finding("invalid_plan_owner", path, "plan owner must be an approved or active spec"))

        if path.startswith("docs/archive/") and entry.get("doc_type") != "index":
            if (
                status != "historical"
                or not _is_iso_date(metadata.get("archived"))
                or metadata.get("historical_reason") not in ARCHIVE_REASONS
            ):
                findings.append(Finding("archive_metadata", path, "archived document requires historical status and archive metadata"))
        if status == "historical" and not path.startswith("docs/archive/"):
            findings.append(Finding("historical_location", path, "historical document must be under docs/archive"))

        if adopted and path.startswith("docs/superpowers/") and entry.get("legacy_path") is not True:
            findings.append(Finding("post_adoption_tool_path", path, "post-adoption tool-specific document path is forbidden"))

        outside_lines = list(_outside_fence_lines(body))
        reference_definitions: dict[str, tuple[str, int]] = {}
        for line_no, line in outside_lines:
            definition = REFERENCE_DEFINITION_RE.match(INLINE_CODE_RE.sub("", line))
            if definition is None:
                continue
            label = _reference_label(definition.group(1))
            reference_definitions.setdefault(label, (definition.group(2), line_no))
            finding = _link_finding(
                document_path=path,
                file_path=file_path,
                raw_target=definition.group(2),
                root=root,
                line_no=line_no,
            )
            if finding is not None:
                findings.append(finding)

        historical_section = False
        for line_no, line in outside_lines:
            stripped = line.strip()
            link_line = INLINE_CODE_RE.sub("", line)
            if stripped.startswith("## "):
                heading = stripped[3:].strip().lower()
                historical_section = heading.startswith(("historical", "archive"))
            for raw_target in INLINE_LINK_RE.findall(link_line):
                finding = _link_finding(
                    document_path=path,
                    file_path=file_path,
                    raw_target=raw_target,
                    root=root,
                    line_no=line_no,
                )
                if finding is not None:
                    findings.append(finding)
            for reference in REFERENCE_LINK_RE.finditer(link_line):
                label = _reference_label(reference.group(2) or reference.group(1))
                if label not in reference_definitions:
                    findings.append(
                        Finding(
                            "broken_markdown_reference",
                            path,
                            "Markdown reference link has no definition",
                            line_no,
                        )
                    )
            if (
                entry.get("doc_type") == "index"
                and historical_section
                and HISTORICAL_IMPERATIVE_RE.search(line)
                and not NON_AUTHORITY_RE.search(line)
            ):
                findings.append(Finding("historical_authority_leak", path, "historical index text must not present executable authority", line_no))

        for line_no, line in enumerate(document_text.splitlines(), start=1):
            for label, pattern in PRIVATE_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(label, path, "public document contains a prohibited sensitive literal", line_no))

    if len(roadmap_paths) == 1 and isinstance(baseline, dict):
        roadmap_path = roadmap_paths[0]
        roadmap_text = document_text_by_path.get(roadmap_path)
        if roadmap_text is not None:
            checked, open_count = _roadmap_checkbox_counts(roadmap_text)
            for key, actual in (("roadmap_checked", checked), ("roadmap_open", open_count)):
                if type(baseline.get(key)) is int and baseline.get(key) != actual:
                    findings.append(
                        Finding(
                            "roadmap_count_mismatch",
                            roadmap_path,
                            f"registry baseline {key} must match the canonical active roadmap count",
                        )
                    )

    for topic, paths in sorted(canonical_topics.items()):
        if len(paths) > 1:
            findings.append(
                Finding(
                    "duplicate_canonical_topic",
                    paths[0],
                    f"canonical topic is claimed by multiple documents: {topic}",
                )
            )

    findings = sorted(findings, key=lambda item: (item.path, item.line or 0, item.check, item.message))
    return {
        "ok": not findings,
        "schema": SCHEMA,
        "root": str(root),
        "registry_path": str(relative_registry),
        "summary": {
            "document_count": len(actual_paths),
            "registry_count": len(entry_by_path),
            "finding_count": len(findings),
        },
        "documents": actual_paths,
        "findings": [finding.to_dict() for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check documentation lifecycle, ownership, links, and safety")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--registry", default=str(REGISTRY_PATH), help="Registry path relative to root")
    parser.add_argument("--report-json", help="Optional JSON report output path")
    args = parser.parse_args(argv)

    report = run_document_lifecycle_check(root=Path(args.root), registry_path=Path(args.registry))
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
