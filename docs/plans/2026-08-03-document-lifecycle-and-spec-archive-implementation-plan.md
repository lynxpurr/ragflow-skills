---
doc_type: plan
topic: document-lifecycle-and-spec-archive
status: proposed
created: 2026-08-03
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Document Lifecycle And Spec Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Wave 1 of the approved document-governance design: the canonical index, metadata templates, complete registry, deterministic lifecycle/link checker, focused tests, and release-hygiene integration.

**Architecture:** `docs/document-registry.json` records every current Markdown document and its approved `28/12/13` baseline class. `docs/README.md` becomes the sole default entrypoint, while a standard-library checker validates registry coverage, metadata, ownership, canonical topics, repository-relative Markdown links, archive rules, safety literals, and post-adoption tool-specific paths. Fences suppress link and historical-command semantics only; sensitive-literal scanning covers frontmatter, prose, and fenced content.

**Tech Stack:** Markdown, JSON, Python 3.10+ standard library, `unittest`, `rg`, and repository-local release hygiene.

---

## Governance Binding

| Field | Value |
| --- | --- |
| Execution state | `NOT_STARTED` |
| Authorized executable scope | Wave 1, Tasks 0-3 only, after owner approval of this exact plan SHA-256 |
| Governing spec | `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` |
| Governing spec SHA-256 | `e18d80b60b4a89ee3319c0eac74d44852a744d4b4a0909e677f7af936cb777fd` |
| Governing state | `status=approved`, `gate_0=closed`, `implementation_authority=false` |
| Baseline classification | 53 Markdown documents: 28 historical candidates, 12 durable-reference candidates, 13 active/gated/proposed owners |
| Roadmap baseline | 586 checked, 15 unchecked |

This plan links exactly one approved spec and does not implement the separate proposed
skill-surface simplification design. Plan approval may authorize Wave 1 only. It does not
authorize Waves 2-5, external maintainer-file edits, private handoff changes, staging,
commit, push, network access, live operations, L3, Stage 8C, or L4.

## Wave 1 File Map

**Create:**

- `docs/README.md` - sole default documentation entrypoint.
- `docs/document-registry.json` - complete 60-document Wave 1 registry: 53 baseline documents, this plan, and six governance Markdown files.
- `docs/specs/README.md` - spec authority and lifecycle guide.
- `docs/specs/TEMPLATE.md` - compliant spec template.
- `docs/plans/README.md` - implementation-plan authority and execution guide.
- `docs/plans/TEMPLATE.md` - compliant plan template.
- `docs/archive/README.md` - non-authoritative archive index with an empty migration table.
- `tools/document_lifecycle_check.py` - deterministic lifecycle/link/safety checker.
- `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py` - focused checker tests.

**Modify:**

- `AGENTS.md` - route documentation discovery through `docs/README.md` and add the checker command.
- `README.md` - route readers through `docs/README.md` and list the checker in validation.
- `tools/release_hygiene_check.py` - run the document checker as a default maintainer-only nested gate.
- `packages/ragflow-skill-runtime/tests/test_release_hygiene.py` - verify the nested gate and failure propagation.

No other repository file may change in Wave 1. In particular, Wave 1 does not move,
archive, rewrite, or add frontmatter to any of the 53 baseline documents.

## Wave 1 Stop Conditions

Stop before or during Wave 1 when any condition is true:

1. The governing spec SHA differs, `status` is no longer `approved`, or `gate_0` is not `closed`.
2. The owner has not approved this exact plan SHA and explicitly authorized Wave 1.
3. The dirty worktree differs from the owner-approved baseline.
4. The baseline is not exactly 53 classified Markdown documents plus this plan before implementation.
5. Roadmap counts differ from 586 checked and 15 unchecked.
6. Any Wave 1 path outside the file map would need modification.
7. The complete registry does not reconcile exactly with the post-Wave-1 Markdown inventory.
8. Focused tests, full tests, lifecycle validation, diff checks, safety review, or release hygiene fail.
9. Any command would require network access, credentials, live RAGFlow/MinerU, dataset operations, L3, Stage 8C, or L4.

## Wave 1 Rollback

Before edits, create a temporary backup of the four existing files Wave 1 may modify:

```bash
WAVE1_BACKUP_ROOT="$(mktemp -d)"
mkdir -p "$WAVE1_BACKUP_ROOT/AGENTS" "$WAVE1_BACKUP_ROOT/tools" \
  "$WAVE1_BACKUP_ROOT/packages/ragflow-skill-runtime/tests"
cp --preserve=mode,timestamps AGENTS.md "$WAVE1_BACKUP_ROOT/AGENTS.md"
cp --preserve=mode,timestamps README.md "$WAVE1_BACKUP_ROOT/README.md"
cp --preserve=mode,timestamps tools/release_hygiene_check.py \
  "$WAVE1_BACKUP_ROOT/tools/release_hygiene_check.py"
cp --preserve=mode,timestamps packages/ragflow-skill-runtime/tests/test_release_hygiene.py \
  "$WAVE1_BACKUP_ROOT/packages/ragflow-skill-runtime/tests/test_release_hygiene.py"
```

If Wave 1 fails, move the nine newly created files into
`$WAVE1_BACKUP_ROOT/failed-new-files/`, restore only the four backed-up files with `cp`,
then rerun status, counts, `git diff --check`, and the failing validation. Do not use
`git checkout`, `git reset`, `git clean`, `git stash`, or a repository-wide restore.

### Task 0: Bind Authority And Verify The Baseline

**Files:**

- Read: `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md`
- Read: `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md`
- Read: every current dirty path
- Create outside repository: `$WAVE1_BACKUP_ROOT`

- [ ] **Step 1: Verify exact authority inputs**

```bash
sha256sum docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
sha256sum docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md
sed -n '1,16p' docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
git branch --show-current
git status --short --branch
```

Expected: the spec SHA matches Governance Binding; spec metadata says `approved` and
`gate_0: closed`; branch and dirty paths match the owner authorization; the plan SHA is
the exact SHA named by the owner.

- [ ] **Step 2: Verify counts and the 53-document baseline**

```bash
find docs -type f -name '*.md' \
  ! -path 'docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md' \
  -print | sort | wc -l
find docs -type f -name '*.md' -print | sort | wc -l
rg -- '- \[x\]' docs/03-development-plan.md | wc -l
rg -- '- \[ \]' docs/03-development-plan.md | wc -l
```

Expected output: `53`, `54`, `586`, `15`.

- [ ] **Step 3: Create the Wave 1 backup**

Run the exact commands in Wave 1 Rollback. Confirm the backup contains only the four
existing Wave 1 files and no repository path was modified.

- [ ] **Step 4: Reconfirm scope before writing tests**

```bash
git status --short --branch
git diff --check
```

Expected: status is unchanged from Step 1 and diff check exits 0. Stop unless the owner
has explicitly authorized Wave 1.

### Task 1: Implement The Lifecycle Checker With TDD

**Files:**

- Create: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`
- Create: `tools/document_lifecycle_check.py`

- [ ] **Step 1: Create the complete failing test file**

Create `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py` with this
exact content:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from document_lifecycle_check import parse_frontmatter, run_document_lifecycle_check  # noqa: E402


def _write_doc(
    root: Path,
    relative_path: str,
    *,
    doc_type: str,
    topic: str,
    status: str,
    canonical: bool,
    body: str,
    owner_spec: str | None = None,
    archive_fields: bool = False,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    owner_line = f"owner_spec: {owner_spec}\n" if owner_spec else ""
    archive_lines = "archived: 2026-08-03\nhistorical_reason: completed\n" if archive_fields else ""
    path.write_text(
        "---\n"
        f"doc_type: {doc_type}\n"
        f"topic: {topic}\n"
        f"status: {status}\n"
        "created: 2026-08-03\n"
        "updated: 2026-08-03\n"
        f"canonical: {'true' if canonical else 'false'}\n"
        "implementation_authority: false\n"
        f"{owner_line}"
        "supersedes: []\n"
        "superseded_by: null\n"
        "related: []\n"
        f"{archive_lines}"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )


def _entry(
    path: str,
    *,
    doc_type: str,
    topic: str,
    status: str,
    canonical: bool,
    owner: str | None = None,
    legacy_metadata: bool = False,
    legacy_path: bool = False,
    baseline_class: str = "wave1_governance",
) -> dict[str, object]:
    return {
        "path": path,
        "doc_type": doc_type,
        "topic": topic,
        "status": status,
        "canonical": canonical,
        "implementation_authority": False,
        "owner": owner,
        "related": [],
        "legacy_metadata": legacy_metadata,
        "legacy_path": legacy_path,
        "baseline_class": baseline_class,
    }


def _write_registry(root: Path, entries: list[dict[str, object]], *, adopted: bool = False) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    baseline_counts = {
        "historical_count": sum(item["baseline_class"] == "historical_candidate" for item in entries),
        "reference_count": sum(item["baseline_class"] == "reference_candidate" for item in entries),
        "active_owner_count": sum(item["baseline_class"] == "active_owner" for item in entries),
    }
    payload = {
        "schema": "ragflow_document_registry_v1",
        "adopted": adopted,
        "governing_spec": "docs/specs/example.md",
        "baseline": {
            "document_count": sum(baseline_counts.values()),
            **baseline_counts,
            "roadmap_checked": 0,
            "roadmap_open": 0,
        },
        "documents": sorted(entries, key=lambda item: str(item["path"])),
        "migrations": [],
    }
    (docs / "document-registry.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _valid_fixture(root: Path) -> list[dict[str, object]]:
    spec_path = "docs/specs/example.md"
    plan_path = "docs/plans/example.md"
    index_path = "docs/README.md"
    _write_doc(
        root,
        spec_path,
        doc_type="spec",
        topic="example",
        status="approved",
        canonical=True,
        body="# Example Spec\n\n## Context\n\nApproved design.\n",
    )
    _write_doc(
        root,
        plan_path,
        doc_type="plan",
        topic="example",
        status="proposed",
        canonical=False,
        owner_spec=spec_path,
        body="# Example Plan\n\nNo implementation authority.\n",
    )
    _write_doc(
        root,
        index_path,
        doc_type="index",
        topic="document-index",
        status="active",
        canonical=True,
        body="# Documentation\n\n[Spec](specs/example.md)\n",
    )
    entries = [
        _entry(spec_path, doc_type="spec", topic="example", status="approved", canonical=True),
        _entry(
            plan_path,
            doc_type="plan",
            topic="example",
            status="proposed",
            canonical=False,
            owner=spec_path,
        ),
        _entry(index_path, doc_type="index", topic="document-index", status="active", canonical=True),
    ]
    _write_registry(root, entries)
    return entries


class DocumentLifecycleCheckTests(unittest.TestCase):
    def _checks(self, report: dict[str, object]) -> set[str]:
        return {str(item["check"]) for item in report["findings"]}  # type: ignore[index]

    def test_valid_registry_and_documents_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["document_count"], 3)  # type: ignore[index]

    def test_current_financebench_multiline_related_frontmatter_parses(self) -> None:
        path = ROOT / "docs" / "specs" / "2026-08-02-financebench-new-minimal-l3-design.md"
        metadata, _body = parse_frontmatter(path)

        self.assertEqual(
            metadata["related"],
            [
                "docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md",
                "docs/40-marker-aware-evidence-validation-and-promotion-plan.md",
                "docs/42-financebench-marker-aware-l3-disposable-validation.md",
                "docs/43-agent-session-handoff-lessons.md",
            ],
        )

    def test_unregistered_markdown_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            (root / "docs" / "unregistered.md").write_text("# Unregistered\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("unregistered_document", self._checks(report))

    def test_duplicate_active_canonical_topic_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/specs/example-copy.md"
            _write_doc(
                root,
                path,
                doc_type="spec",
                topic="example",
                status="approved",
                canonical=True,
                body="# Duplicate Spec\n",
            )
            entries.append(_entry(path, doc_type="spec", topic="example", status="approved", canonical=True))
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("duplicate_canonical_topic", self._checks(report))

    def test_registry_baseline_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            registry_path = root / "docs" / "document-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["baseline"]["document_count"] = 1
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("baseline_mismatch", self._checks(report))

    def test_gated_document_without_named_gate_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/plans/gated.md"
            _write_doc(
                root,
                path,
                doc_type="plan",
                topic="gated-example",
                status="gated",
                canonical=True,
                owner_spec="docs/specs/example.md",
                body="# Gated Plan\n\nWork is deferred.\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="plan",
                    topic="gated-example",
                    status="gated",
                    canonical=True,
                    owner="docs/specs/example.md",
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("missing_named_gate", self._checks(report))

    def test_plan_without_approved_or_active_spec_owner_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            entries[0]["status"] = "proposed"
            _write_doc(
                root,
                "docs/specs/example.md",
                doc_type="spec",
                topic="example",
                status="proposed",
                canonical=True,
                body="# Proposed Spec\n",
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("invalid_plan_owner", self._checks(report))

    def test_new_evidence_without_registered_owner_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/evidence/example.md"
            _write_doc(
                root,
                path,
                doc_type="evidence",
                topic="example-evidence",
                status="implemented",
                canonical=False,
                body="# Example Evidence\n\nSanitized result.\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="evidence",
                    topic="example-evidence",
                    status="implemented",
                    canonical=False,
                    owner=None,
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("invalid_owner", self._checks(report))

    def test_missing_markdown_link_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body="# Documentation\n\n[Missing](missing.md)\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("broken_markdown_link", self._checks(report))

    def test_archive_requires_historical_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/archive/2026/plans/old.md"
            _write_doc(
                root,
                path,
                doc_type="plan",
                topic="old-plan",
                status="historical",
                canonical=False,
                owner_spec="docs/specs/example.md",
                body="# Old Plan\n\nHistorical and non-authoritative.\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="plan",
                    topic="old-plan",
                    status="historical",
                    canonical=False,
                    owner="docs/specs/example.md",
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("archive_metadata", self._checks(report))

    def test_unregistered_post_adoption_superpowers_document_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            _write_registry(root, entries, adopted=True)
            path = root / "docs" / "superpowers" / "plans" / "new.md"
            path.parent.mkdir(parents=True)
            path.write_text("# New Tool-Specific Plan\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("post_adoption_tool_path", self._checks(report))

    def test_private_literal_is_reported_without_echoing_value(self) -> None:
        private_value = ".".join(["192", "168", "10", "20"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body=f"# Documentation\n\nPrivate endpoint: {private_value}\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("private_ipv4_literal", self._checks(report))
        self.assertNotIn(private_value, json.dumps(report["findings"]))

    def test_nested_short_fence_inside_long_fence_does_not_check_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body=(
                    "# Documentation\n\n"
                    "````markdown\n"
                    "```text\n"
                    "[Missing](missing.md)\n"
                    + "```\n"
                    + "````\n"
                ),
            )
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)

    def test_sensitive_literal_inside_fence_is_reported_without_echoing_value(self) -> None:
        sensitive_value = "ghp_" + "A" * 24
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body=f"# Documentation\n\n```text\n{sensitive_value}\n```\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("secret_token_literal", self._checks(report))
        self.assertNotIn(sensitive_value, json.dumps(report["findings"]))

    def test_non_index_archived_section_does_not_trigger_index_authority_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/plans/example.md",
                doc_type="plan",
                topic="example",
                status="proposed",
                canonical=False,
                owner_spec="docs/specs/example.md",
                body=(
                    "# Example Plan\n\n"
                    "## Archived Maintenance Notes\n\n"
                    "Release validation should continue before future candidates.\n"
                ),
            )
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)

    def test_active_index_cannot_present_history_as_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body="# Documentation\n\n## Historical\n\n- Run the archived implementation now.\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("historical_authority_leak", self._checks(report))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify fail-before-implementation behavior**

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_document_lifecycle_check.py' -v
```

Expected: FAIL because `document_lifecycle_check` does not exist.

- [ ] **Step 3: Create the complete checker implementation**

Create `tools/document_lifecycle_check.py` with this exact content:

```python
#!/usr/bin/env python3
"""Validate repository documentation lifecycle, ownership, links, and safety."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
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
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
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
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


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


def parse_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = _read_text(path)
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


def load_registry(root: Path, registry_path: Path = REGISTRY_PATH) -> dict[str, object]:
    path = registry_path if registry_path.is_absolute() else root / registry_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("document registry is missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("document registry must be a JSON object")
    return payload


def _markdown_files(root: Path) -> list[Path]:
    docs_root = root / "docs"
    if not docs_root.exists():
        return []
    return sorted(path for path in docs_root.rglob("*.md") if path.is_file())


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
    target = raw_target.strip().strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
        return None
    target = target.split(maxsplit=1)[0].split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    candidate = (root / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
    return candidate.resolve()


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
        if not isinstance(entry.get("related"), list):
            findings.append(Finding("invalid_related", path, "related must be a list"))
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
        owner = entry.get("owner")
        if owner is not None and (not isinstance(owner, str) or owner not in entry_by_path):
            findings.append(Finding("invalid_owner", path, "owner must reference a registered document"))
        if entry.get("doc_type") == "evidence" and entry.get("legacy_metadata") is not True and owner is None:
            findings.append(Finding("invalid_owner", path, "new evidence must reference its governing spec or plan"))

    actual_paths = [_relative(path, root) for path in _markdown_files(root)]
    for path in sorted(set(actual_paths) - set(entry_by_path)):
        findings.append(Finding("unregistered_document", path, "Markdown document is not registered"))
    for path in sorted(set(entry_by_path) - set(actual_paths)):
        findings.append(Finding("missing_registered_document", path, "registered Markdown document is missing"))

    canonical_topics: dict[str, list[str]] = {}
    adopted = registry.get("adopted") is True
    for path in actual_paths:
        entry = entry_by_path.get(path)
        file_path = root / path
        if entry is None:
            if adopted and path.startswith("docs/superpowers/"):
                findings.append(Finding("post_adoption_tool_path", path, "post-adoption tool-specific document path is forbidden"))
            continue
        document_text = _read_text(file_path)
        try:
            metadata, body = parse_frontmatter(file_path)
        except ValueError as exc:
            findings.append(Finding("frontmatter", path, str(exc)))
            metadata, body = {}, document_text

        legacy_metadata = entry.get("legacy_metadata") is True
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
            if entry.get("owner") is not None and metadata.get("owner_spec") != entry.get("owner"):
                findings.append(Finding("metadata_mismatch", path, "owner_spec disagrees with registry owner"))

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
            if status != "historical" or not metadata.get("archived") or not metadata.get("historical_reason"):
                findings.append(Finding("archive_metadata", path, "archived document requires historical status and archive metadata"))
        if status == "historical" and not path.startswith("docs/archive/"):
            findings.append(Finding("historical_location", path, "historical document must be under docs/archive"))

        if adopted and path.startswith("docs/superpowers/") and entry.get("legacy_path") is not True:
            findings.append(Finding("post_adoption_tool_path", path, "post-adoption tool-specific document path is forbidden"))

        historical_section = False
        for line_no, line in _outside_fence_lines(body):
            stripped = line.strip()
            if stripped.startswith("## "):
                heading = stripped[3:].strip().lower()
                historical_section = heading.startswith(("historical", "archive"))
            for raw_target in MARKDOWN_LINK_RE.findall(line):
                target = _link_target(file_path, raw_target, root)
                if target is not None and not target.exists():
                    findings.append(Finding("broken_markdown_link", path, "repository-relative Markdown link does not resolve", line_no))
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
```

- [ ] **Step 4: Run focused tests and syntax validation**

```bash
python3 -m py_compile tools/document_lifecycle_check.py
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_document_lifecycle_check.py' -v
```

Expected: syntax exits 0 and all 16 focused tests pass.

### Task 2: Create The Complete Registry And Governance Documents

**Files:**

- Create: `docs/README.md`
- Create: `docs/document-registry.json`
- Create: `docs/specs/README.md`
- Create: `docs/specs/TEMPLATE.md`
- Create: `docs/plans/README.md`
- Create: `docs/plans/TEMPLATE.md`
- Create: `docs/archive/README.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Create the complete registry**

Create `docs/document-registry.json` with this exact content:

```json
{
  "schema": "ragflow_document_registry_v1",
  "adopted": false,
  "governing_spec": "docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md",
  "baseline": {
    "document_count": 53,
    "historical_count": 28,
    "reference_count": 12,
    "active_owner_count": 13,
    "roadmap_checked": 586,
    "roadmap_open": 15
  },
  "documents": [
    {"path":"docs/01-folder-plan.md","doc_type":"plan","topic":"folder-plan","status":"superseded","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/02-architecture-design.md","doc_type":"reference","topic":"suite-architecture","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/03-development-plan.md","doc_type":"roadmap","topic":"current-development","status":"active","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/04-validation-inventory.md","doc_type":"reference","topic":"validation-inventory","status":"superseded","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/05-cross-platform-smoke.md","doc_type":"reference","topic":"cross-platform-smoke","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/06-release-hardening.md","doc_type":"reference","topic":"release-hardening","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/07-first-release.md","doc_type":"evidence","topic":"first-release","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/08-cli-agent-integration.md","doc_type":"reference","topic":"cli-agent-integration","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/09-high-value-feature-roadmap.md","doc_type":"roadmap","topic":"high-value-feature-roadmap","status":"superseded","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/10-legacy-feature-gap-closure-design.md","doc_type":"spec","topic":"legacy-feature-gap-closure","status":"superseded","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/11-public-rename-policy.md","doc_type":"reference","topic":"public-rename-policy","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/12-release-archive-forward-test-prompts.md","doc_type":"reference","topic":"release-forward-test-prompts","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/13-post-cli-adapter-planning.md","doc_type":"plan","topic":"post-cli-adapters","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/14-optional-llm-backend-planning.md","doc_type":"plan","topic":"optional-llm-backends","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/15-field-trial-observation-plan.md","doc_type":"plan","topic":"field-trial-observation","status":"active","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/16-system-closeout-report.md","doc_type":"reference","topic":"system-closeout","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/17-mineru-fastapi-backend-design.md","doc_type":"spec","topic":"mineru-fastapi-backend","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/18-mineru-sync-production-issues.md","doc_type":"plan","topic":"mineru-sync-production-issues","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/19-ragflux-capability-parity-plan.md","doc_type":"plan","topic":"ragflux-capability-parity","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/20-ragflow-doc-to-md-ingest-quality-plan.md","doc_type":"plan","topic":"doc-to-md-ingest-quality","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/21-ragflow-doc-to-md-table-quality-design.md","doc_type":"spec","topic":"doc-to-md-table-quality","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/22-apollo-table-qa-rectification-plan.md","doc_type":"plan","topic":"apollo-table-qa","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/23-adaptive-pipeline-proposal.md","doc_type":"reference","topic":"adaptive-pipeline","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/24-adaptive-pipeline-quality-fix-plan.md","doc_type":"plan","topic":"adaptive-pipeline-quality-fix","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/25-current-suite-regression-follow-up-plan.md","doc_type":"plan","topic":"current-suite-regression-follow-up","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/26-mineru-v4-platform-backend-design.md","doc_type":"spec","topic":"mineru-v4-platform-backend","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/27-current-skills-quality-improvement-checklist.md","doc_type":"plan","topic":"current-skills-quality-improvement","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/28-retrieval-optimization-quality-improvement-plan.md","doc_type":"plan","topic":"retrieval-optimization-quality","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/29-kb-build-strict-regression-quality-plan.md","doc_type":"plan","topic":"kb-build-strict-regression","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/30-hermes-e2e-test-plan.md","doc_type":"reference","topic":"hermes-e2e-test","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/31-hermes-e2e-improvement-follow-up-plan.md","doc_type":"plan","topic":"hermes-e2e-follow-up","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/32-retirement-transition-action-plan.md","doc_type":"plan","topic":"retirement-transition","status":"active","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/33-dedao-pandoc-epub-quality-improvement-plan.md","doc_type":"plan","topic":"dedao-pandoc-epub-quality","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/34-pipeline-consumption-gap-quality-improvement-plan.md","doc_type":"plan","topic":"pipeline-consumption-gap","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/35-standard-benchmark-dataset-integration-plan.md","doc_type":"plan","topic":"standard-benchmark-datasets","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/36-ragflow-kb-parameter-materialization-plan.md","doc_type":"plan","topic":"kb-parameter-materialization","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md","doc_type":"reference","topic":"kb-parameter-contract-audit","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md","doc_type":"plan","topic":"benchmark-evidence-strengthening","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/39-benchmark-evidence-strengthening-hermes-test.md","doc_type":"evidence","topic":"benchmark-evidence-hermes-l0","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/40-marker-aware-evidence-validation-and-promotion-plan.md","doc_type":"plan","topic":"marker-aware-evidence-promotion","status":"gated","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/41-marker-aware-candidate-snapshot-hermes-l0.md","doc_type":"evidence","topic":"marker-aware-snapshot-hermes-l0","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/42-financebench-marker-aware-l3-disposable-validation.md","doc_type":"evidence","topic":"financebench-marker-aware-l3","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/43-agent-session-handoff-lessons.md","doc_type":"reference","topic":"agent-session-handoff-lessons","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/README.md","doc_type":"index","topic":"document-index","status":"active","canonical":true,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/archive/README.md","doc_type":"index","topic":"document-archive","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/branching-policy.md","doc_type":"reference","topic":"branching-policy","status":"reference","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"reference_candidate"},
    {"path":"docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md","doc_type":"plan","topic":"document-lifecycle-and-spec-archive","status":"proposed","canonical":false,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/plans/README.md","doc_type":"reference","topic":"plan-authoring-guide","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/plans/TEMPLATE.md","doc_type":"template","topic":"plan-template","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/plans/README.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","doc_type":"spec","topic":"document-lifecycle-and-spec-archive","status":"approved","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"active_owner"},
    {"path":"docs/specs/2026-08-02-financebench-new-minimal-l3-design.md","doc_type":"spec","topic":"financebench-new-minimal-l3","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":false,"baseline_class":"historical_candidate"},
    {"path":"docs/specs/README.md","doc_type":"reference","topic":"spec-authoring-guide","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/specs/TEMPLATE.md","doc_type":"template","topic":"spec-template","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/specs/README.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"},
    {"path":"docs/superpowers/plans/2026-07-10-kb-parameter-stage-8a.md","doc_type":"plan","topic":"kb-parameter-stage-8a","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/plans/2026-07-10-kb-parameter-stage-8b-contract-audit.md","doc_type":"plan","topic":"kb-parameter-stage-8b-contract-audit","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md","doc_type":"plan","topic":"benchmark-evidence-strengthening-implementation","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md","doc_type":"plan","topic":"marker-aware-candidate-snapshot-implementation","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md","doc_type":"spec","topic":"kb-parameter-stage-8b-contract-audit-design","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md","doc_type":"spec","topic":"marker-aware-candidate-snapshot-design","status":"implemented","canonical":false,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"historical_candidate"},
    {"path":"docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md","doc_type":"spec","topic":"skill-surface-simplification","status":"proposed","canonical":true,"implementation_authority":false,"owner":null,"related":[],"legacy_metadata":true,"legacy_path":true,"baseline_class":"active_owner"}
  ],
  "migrations": []
}
```

- [ ] **Step 2: Create `docs/README.md`**

````markdown
---
doc_type: index
topic: document-index
status: active
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Documentation

This file is the sole default entrypoint for repository documentation. Documents classify
and explain work; they do not independently authorize network access, credentials, live
operations, mutation, staging, commit, push, L3, Stage 8C, or L4.

## Current Roadmap

- [Development roadmap](03-development-plan.md) - current priorities and gated backlog.

## Controlling Governance Work

- [Document lifecycle spec](specs/2026-08-02-document-lifecycle-and-spec-archive-design.md) - approved design; Gate 0 is closed.
- [Wave 1 implementation plan](plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md) - proposed until owner approval; `implementation_authority=false`.
- `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md` - separate proposed track; not part of document-governance Wave 1.

## Active And Gated Owners

The registry records 13 active, gated, or proposed owners at stable paths. Load an owner
only when the current task names its topic. Unchecked evidence or adapter rows do not
create live or implementation authority.

## Durable References

The 12 approved reference candidates remain at their current paths during Wave 1. They
are non-authoritative guidance and are not moved until a separately approved Wave 3 plan.

## Historical Candidates

The 28 approved historical candidates remain at their current paths during Wave 1. They
must not be executed as current instructions. Archive moves require a separately approved
Wave 2 plan with inbound-reference inventory, reversible batches, and body preservation.

## Authoring

- Specs: `docs/specs/README.md` and `docs/specs/TEMPLATE.md`.
- Plans: `docs/plans/README.md` and `docs/plans/TEMPLATE.md`.
- Archive index: `docs/archive/README.md`.
- Machine-readable registry: `docs/document-registry.json`.

## Validation

Run from the repository root:

```bash
python3 tools/document_lifecycle_check.py
git diff --check
python3 tools/release_hygiene_check.py
```

The lifecycle checker is local and deterministic. It is a maintainer/release gate, not a
public skill command or a source of operational authority.
````

- [ ] **Step 3: Create `docs/specs/README.md` and `docs/specs/TEMPLATE.md`**

`docs/specs/README.md`:

```markdown
---
doc_type: reference
topic: spec-authoring-guide
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Spec Authoring Guide

A spec owns one coherent problem and defines intended behavior, constraints, migration,
rollback, validation, acceptance criteria, and decisions. It does not contain an
implementation checklist or grant live authority.

New specs use `docs/specs/TEMPLATE.md`. A spec starts as `proposed`; owner approval is
required before an implementation plan may be prepared. Only an approved or active spec
plus its linked plan can participate in implementation authorization.

Do not place credentials, private endpoints, private paths, live identifiers, raw
responses, or raw chunks in metadata or public body text.
```

`docs/specs/TEMPLATE.md`:

````markdown
---
doc_type: template
topic: spec-template
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/README.md
supersedes: []
superseded_by: null
related: []
---

# Spec Template

Create a new file under `docs/specs/` with the following structure. Replace the example
topic and dates with reviewed values before requesting approval.

```yaml
---
doc_type: spec
topic: short-stable-topic-id
status: proposed
created: YYYY-MM-DD
updated: YYYY-MM-DD
canonical: true
implementation_authority: false
supersedes: []
superseded_by: null
related: []
---
```

```markdown
# Literal Feature Or System Name

## Context

## Objective

## Non-Goals

## Requirements And Invariants

## Design

## Compatibility And Migration

## Failure Handling And Rollback

## Validation Strategy

## Acceptance Criteria

## Decision Log
```

A spec normally stays below 400 lines. Crossing 500 lines requires a decomposition note
or a decision-log justification.
````

- [ ] **Step 4: Create `docs/plans/README.md` and `docs/plans/TEMPLATE.md`**

`docs/plans/README.md`:

```markdown
---
doc_type: reference
topic: plan-authoring-guide
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Plan Authoring Guide

An implementation plan links exactly one approved spec and contains exact files, ordered
tasks, complete code or document content, focused tests, validation, rollback, and stop
conditions. A plan must not silently expand its owning spec.

New plans use `docs/plans/TEMPLATE.md`. Plan approval and execution authority are separate:
`implementation_authority=false` remains the safe default, and staging, commit, push,
network, credentials, or live operations require explicit owner authority.
```

`docs/plans/TEMPLATE.md`:

````markdown
---
doc_type: template
topic: plan-template
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/plans/README.md
supersedes: []
superseded_by: null
related: []
---

# Implementation Plan Template

Create a new file under `docs/plans/` with compliant frontmatter followed by the required
implementation-plan header.

```yaml
---
doc_type: plan
topic: short-stable-topic-id
status: proposed
created: YYYY-MM-DD
updated: YYYY-MM-DD
canonical: false
implementation_authority: false
owner_spec: docs/specs/YYYY-MM-DD-approved-topic-design.md
supersedes: []
superseded_by: null
related: []
---
```

```markdown
# Literal Feature Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One externally observable outcome.

**Architecture:** Two or three sentences describing boundaries and data flow.

**Tech Stack:** Exact languages, libraries, and test framework.

---

### Task 1: Literal Component Name

**Files:**

- Create: `exact/path`
- Modify: `exact/path`
- Test: `exact/path`

- [ ] **Step 1: Write the complete failing test**
- [ ] **Step 2: Run the exact test and verify the expected failure**
- [ ] **Step 3: Write the complete minimal implementation**
- [ ] **Step 4: Run focused and broader validation**
- [ ] **Step 5: Stop at the named owner checkpoint**

## Rollback

## Stop Conditions
```

Do not leave unresolved design choices or placeholder implementation steps in an approved
plan.
````

- [ ] **Step 5: Create `docs/archive/README.md`**

```markdown
---
doc_type: index
topic: document-archive
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Documentation Archive

Documents under this directory are immutable historical context. They create no current
task, implementation, operational, network, credential, mutation, or live authority.

Wave 1 creates this index but moves no document. Every later move requires a separately
approved plan, an exact inbound-reference inventory, archive metadata, atomic live-link
updates, body-preservation evidence, and a reversible migration batch.

## Migration Map

| old_path | new_path | archived | historical_reason | original_sha256 |
| --- | --- | --- | --- | --- |
```

- [ ] **Step 6: Apply the exact `AGENTS.md` patch**

```diff
@@
-Repository-wide build and validation utilities live in `tools/`, while architecture, plans, and release guidance live in `docs/`.
+Repository-wide build and validation utilities live in `tools/`. Start documentation discovery at `docs/README.md`; governed specs, plans, references, evidence, and archive material live under `docs/`.
@@
 - `python3 tools/release_hygiene_check.py` checks packaging, public/private boundaries, schemas, and generated-report safety.
+- `python3 tools/document_lifecycle_check.py` checks documentation classification, metadata, ownership, links, archive rules, and public safety.
```

- [ ] **Step 7: Apply the exact root `README.md` patch**

```diff
@@
-docs/                             # architecture and development plans
+docs/README.md                    # canonical documentation entrypoint
@@
 python3 tools/platform_smoke_matrix.py
+python3 tools/document_lifecycle_check.py
 python3 tools/release_hygiene_check.py
@@
-See `docs/08-cli-agent-integration.md` for CLI agent configuration and invocation patterns.
-See `docs/09-high-value-feature-roadmap.md` for completed v0.2+ high-value features and the remaining optional synthesis backlog.
+Start at `docs/README.md` for the current roadmap, controlling specs and plans, durable references, and historical-document boundaries.
```

- [ ] **Step 8: Validate the registry and governance documents**

```bash
python3 -m json.tool docs/document-registry.json >/dev/null
python3 tools/document_lifecycle_check.py
find docs -type f -name '*.md' -print | sort | wc -l
rg -- '- \[x\]' docs/03-development-plan.md | wc -l
rg -- '- \[ \]' docs/03-development-plan.md | wc -l
```

Expected: JSON parse succeeds; lifecycle report has `ok=true`, `document_count=60`,
`registry_count=60`, and zero findings; outputs are `60`, `586`, `15`.

### Task 3: Integrate Wave 1 Into Release Hygiene And Verify Final Bytes

**Files:**

- Modify: `tools/release_hygiene_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_release_hygiene.py`
- Test: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

- [ ] **Step 1: Apply the exact release-hygiene implementation patch**

```diff
@@
 from build_release import DIST_DIR, PUBLIC_SKILLS, ROOT, build_release
+from document_lifecycle_check import run_document_lifecycle_check
@@
 def run_hygiene_check(
@@
     runtime_resilience_inventory: bool = True,
+    document_lifecycle: bool = True,
 ) -> dict[str, Any]:
@@
     if runtime_resilience_inventory:
         runtime_resilience_payload = run_runtime_resilience_inventory(root=ROOT)
         payload["runtime_resilience_inventory"] = runtime_resilience_payload
         payload["ok"] = bool(payload["ok"] and runtime_resilience_payload["ok"])
+    if document_lifecycle:
+        document_lifecycle_payload = run_document_lifecycle_check(root=ROOT)
+        payload["document_lifecycle"] = document_lifecycle_payload
+        payload["ok"] = bool(payload["ok"] and document_lifecycle_payload["ok"])
     return payload
@@
     parser.add_argument("--skip-runtime-resilience-inventory", action="store_true", help="Skip static runtime-resilience inventory checks")
+    parser.add_argument("--skip-document-lifecycle", action="store_true", help="Skip documentation lifecycle and link checks")
@@
         runtime_resilience_inventory=not args.skip_runtime_resilience_inventory,
+        document_lifecycle=not args.skip_document_lifecycle,
     )
```

- [ ] **Step 2: Apply the exact release-hygiene test patch**

```diff
@@
 import tempfile
 import unittest
+from unittest.mock import patch
@@
         self.assertTrue(payload["runtime_resilience_inventory"]["ok"])
         self.assertEqual(payload["runtime_resilience_inventory"]["schema"], "ragflow_runtime_resilience_inventory_v1")
+        self.assertTrue(payload["document_lifecycle"]["ok"])
+        self.assertEqual(payload["document_lifecycle"]["schema"], "ragflow_document_lifecycle_check_v1")
+
+    def test_hygiene_check_fails_when_document_lifecycle_fails(self) -> None:
+        lifecycle_payload = {
+            "ok": False,
+            "schema": "ragflow_document_lifecycle_check_v1",
+            "findings": [{"check": "private_ipv4_literal", "path": "docs/example.md", "message": "sanitized"}],
+        }
+        with tempfile.TemporaryDirectory() as tmp:
+            with patch("release_hygiene_check.run_document_lifecycle_check", return_value=lifecycle_payload):
+                payload = run_hygiene_check(
+                    dist_dir=Path(tmp) / "dist",
+                    rebuild=True,
+                    scan_source=False,
+                    schema_identity=False,
+                    manifest_schema=False,
+                    rename_governance=False,
+                    forward_test_prompts=False,
+                    version_date_drift=False,
+                    generated_report_safety=False,
+                    runtime_resilience_inventory=False,
+                )
+
+        self.assertFalse(payload["ok"], payload)
+        self.assertEqual(payload["document_lifecycle"], lifecycle_payload)
```

- [ ] **Step 3: Run focused syntax and unit tests**

```bash
python3 -m py_compile tools/document_lifecycle_check.py tools/release_hygiene_check.py
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_document_lifecycle_check.py' -v
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_release_hygiene.py' -v
```

Expected: syntax passes; all focused lifecycle and release-hygiene tests pass.

- [ ] **Step 4: Run the complete no-network unit suite**

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v
```

Expected: zero failures and zero errors.

- [ ] **Step 5: Run lifecycle, diff, count, and safety validation on final Wave 1 bytes**

```bash
python3 tools/document_lifecycle_check.py
git diff --check
rg -- '- \[x\]' docs/03-development-plan.md | wc -l
rg -- '- \[ \]' docs/03-development-plan.md | wc -l
rg -n '/home/|192\.168|127\.0\.0\.1|api[_-]?key|bearer|token|dataset_id|document_id|kb:' \
  docs/README.md docs/specs/README.md docs/specs/TEMPLATE.md \
  docs/plans/README.md docs/plans/TEMPLATE.md docs/archive/README.md || true
git status --short --branch
git ls-files --others --exclude-standard
```

Expected: lifecycle `ok=true` with zero findings; diff check passes; roadmap remains
`586/15`; every safety hit is a reviewed policy/example term rather than a private value;
the worktree contains exactly the approved Wave 1 slice plus pre-existing owner changes.

- [ ] **Step 6: Run release hygiene without changing repository-generated products**

```bash
WAVE1_RELEASE_ROOT="$(mktemp -d)"
python3 tools/build_release.py --dist "$WAVE1_RELEASE_ROOT/dist" --check
python3 tools/release_hygiene_check.py \
  --dist "$WAVE1_RELEASE_ROOT/dist" --no-build \
  >"$WAVE1_RELEASE_ROOT/release-hygiene.json"
python3 -c 'import json,sys; p=json.load(open(sys.argv[1], encoding="utf-8")); print(p["ok"], len(p["findings"]), p["document_lifecycle"]["ok"], p["document_lifecycle"]["summary"]["finding_count"])' \
  "$WAVE1_RELEASE_ROOT/release-hygiene.json"
```

Expected: `True 0 True 0`.

- [ ] **Step 7: Stop at the Wave 1 owner checkpoint**

Report exact changed files, lifecycle summary, test totals, roadmap counts, safety-review
results, release-hygiene result, and residual risks. Do not change the spec or plan to
`implemented`; do not set registry `adopted=true`; do not stage, commit, push, contact a
remote, edit external maintainer files, change private handoffs, or begin Wave 2.

## Owner-Gated Milestones: Not Executable Under This Plan Approval

The milestones below preserve the approved spec's future shape and exact classification,
but contain no implementation checkbox and grant no authority. Each milestone requires a
new, complete, owner-reviewed execution plan before files change.

### Wave 2 Milestone: Archive 28 Historical Candidates

Create a successor plan that establishes bounded batches, exact inbound-reference
inventories, archive metadata, body-preservation hashes, atomic live-link updates,
per-batch rollback, and owner stop points. The approved candidate set is:

```text
docs/01-folder-plan.md
docs/04-validation-inventory.md
docs/07-first-release.md
docs/09-high-value-feature-roadmap.md
docs/10-legacy-feature-gap-closure-design.md
docs/17-mineru-fastapi-backend-design.md
docs/18-mineru-sync-production-issues.md
docs/19-ragflux-capability-parity-plan.md
docs/20-ragflow-doc-to-md-ingest-quality-plan.md
docs/21-ragflow-doc-to-md-table-quality-design.md
docs/22-apollo-table-qa-rectification-plan.md
docs/24-adaptive-pipeline-quality-fix-plan.md
docs/25-current-suite-regression-follow-up-plan.md
docs/26-mineru-v4-platform-backend-design.md
docs/27-current-skills-quality-improvement-checklist.md
docs/28-retrieval-optimization-quality-improvement-plan.md
docs/33-dedao-pandoc-epub-quality-improvement-plan.md
docs/34-pipeline-consumption-gap-quality-improvement-plan.md
docs/39-benchmark-evidence-strengthening-hermes-test.md
docs/41-marker-aware-candidate-snapshot-hermes-l0.md
docs/42-financebench-marker-aware-l3-disposable-validation.md
docs/specs/2026-08-02-financebench-new-minimal-l3-design.md
docs/superpowers/plans/2026-07-10-kb-parameter-stage-8a.md
docs/superpowers/plans/2026-07-10-kb-parameter-stage-8b-contract-audit.md
docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md
docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md
docs/superpowers/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md
docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md
```

Wave 2D remains blocked until the owner closes or refreshes ACTIVE private handoffs.
External maintainer references require separate owner authority and cannot be silently
edited by a repository plan.

### Wave 3 Milestone: Normalize 12 Durable References

Create a successor plan that reviews current commands and duplicate ownership before
moving any path. Default targets remain under `docs/reference/`; a stale or duplicate
candidate stays at its current path until owner review. The approved set is:

```text
docs/02-architecture-design.md
docs/05-cross-platform-smoke.md
docs/06-release-hardening.md
docs/08-cli-agent-integration.md
docs/11-public-rename-policy.md
docs/12-release-archive-forward-test-prompts.md
docs/16-system-closeout-report.md
docs/23-adaptive-pipeline-proposal.md
docs/30-hermes-e2e-test-plan.md
docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md
docs/43-agent-session-handoff-lessons.md
docs/branching-policy.md
```

`docs/43-agent-session-handoff-lessons.md` remains classified as durable reference,
`implementation_authority=false`. Tool-owned hardcoded paths and focused tests must move
atomically with their reference.

### Wave 4 Milestone: Calibrate 13 Stable Owners

Create a successor plan that adds structured metadata without moving paths, changing
bodies, changing checkboxes, reopening gates, or splitting documents. The approved stable
set is:

```text
docs/03-development-plan.md
docs/13-post-cli-adapter-planning.md
docs/14-optional-llm-backend-planning.md
docs/15-field-trial-observation-plan.md
docs/29-kb-build-strict-regression-quality-plan.md
docs/31-hermes-e2e-improvement-follow-up-plan.md
docs/32-retirement-transition-action-plan.md
docs/35-standard-benchmark-dataset-integration-plan.md
docs/36-ragflow-kb-parameter-materialization-plan.md
docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md
docs/40-marker-aware-evidence-validation-and-promotion-plan.md
docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md
```

Roadmap counts must remain `586/15`.

### Wave 5 Milestone: Adopt And Close The Scheme

Create a successor plan only after Waves 2-4 are owner-approved and verified. Its
closeout order must be:

1. Run all focused tests, the full unit suite, lifecycle/link checks, body/checklist
   preservation checks, `git diff --check`, roadmap counts, safety review, and release
   hygiene on pre-closeout bytes.
2. If and only if all validation passes, set registry `adopted=true` and transition the
   governance spec and controlling plan to their verified terminal lifecycle states.
3. Re-run lifecycle/link validation, `git diff --check`, roadmap counts, changed-doc
   safety review, and release hygiene on the final post-transition bytes.
4. Claim closeout only when the second validation pass also has zero findings.

No milestone authorizes staging, commit, push, network access, live operations, archive
deletion, L3, Stage 8C, L4, external maintainer edits, or private handoff changes.

## Owner Decisions After Revision Review

1. Approve or reject this revised exact-SHA plan.
2. If approved, authorize Wave 1 only.
3. Keep external maintainer edits, Wave 2D handoff handling, staging, commit, push, and
   network access unauthorized.

`implementation=NOT_STARTED`
