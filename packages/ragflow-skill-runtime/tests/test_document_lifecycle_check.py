from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
    roadmap_path = "docs/roadmap.md"
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
    _write_doc(
        root,
        roadmap_path,
        doc_type="roadmap",
        topic="current-roadmap",
        status="active",
        canonical=True,
        body="# Roadmap\n",
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
        _entry(
            roadmap_path,
            doc_type="roadmap",
            topic="current-roadmap",
            status="active",
            canonical=True,
            baseline_class="active_owner",
        ),
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
        self.assertEqual(report["summary"]["document_count"], 4)  # type: ignore[index]

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

    def test_registry_document_paths_must_be_normalized_under_docs(self) -> None:
        invalid_paths = (
            "/outside.md",
            "../outside.md",
            "docs/../outside.md",
            "docs//README.md",
            "notes/example.md",
            "docs/example.txt",
        )
        for invalid_path in invalid_paths:
            with self.subTest(path=invalid_path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                entries[0]["path"] = invalid_path
                _write_registry(root, entries)
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_document_path", self._checks(report))

    def test_symlinked_markdown_is_rejected_without_reading_target(self) -> None:
        sensitive_value = "ghp_" + "B" * 24
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "repo"
            entries = _valid_fixture(root)
            outside = workspace / "outside.md"
            _write_doc(
                workspace,
                "outside.md",
                doc_type="reference",
                topic="outside",
                status="reference",
                canonical=False,
                body=f"# Outside\n\n{sensitive_value}\n",
            )
            path = "docs/external.md"
            link = root / path
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            entries.append(
                _entry(
                    path,
                    doc_type="reference",
                    topic="outside",
                    status="reference",
                    canonical=False,
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("document_symlink", self._checks(report))
        self.assertNotIn(sensitive_value, json.dumps(report))
        self.assertNotIn(str(outside), report["documents"])

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
            registry["baseline"]["document_count"] = 999
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("baseline_mismatch", self._checks(report))

    def test_registry_adopted_must_be_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            registry_path = root / "docs" / "document-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["adopted"] = "false"
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("invalid_adopted", self._checks(report))

    def test_governing_spec_must_be_registered_existing_canonical_approved_spec(self) -> None:
        cases = {
            "unregistered": {"governing_spec": "docs/specs/missing.md"},
            "missing": {"remove_file": True},
            "noncanonical": {"canonical": False},
            "wrong_status": {"status": "proposed"},
            "wrong_type": {"doc_type": "reference"},
        }
        for name, mutation in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                registry_path = root / "docs" / "document-registry.json"
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                if "governing_spec" in mutation:
                    registry["governing_spec"] = mutation["governing_spec"]
                else:
                    spec_entry = next(item for item in entries if item["path"] == "docs/specs/example.md")
                    for key in ("canonical", "status", "doc_type"):
                        if key in mutation:
                            spec_entry[key] = mutation[key]
                    _write_registry(root, entries)
                    if mutation.get("remove_file"):
                        (root / "docs" / "specs" / "example.md").unlink()
                if "governing_spec" in mutation:
                    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_governing_spec", self._checks(report))

    def test_registry_related_must_be_registered_string_paths(self) -> None:
        cases: list[list[object]] = [[123], ["docs/missing.md"]]
        for related in cases:
            with self.subTest(related=related), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                entries[0]["related"] = related
                _write_registry(root, entries)
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_related", self._checks(report))

    def test_new_evidence_owner_must_be_registered_spec_or_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/evidence/example.md"
            owner = "docs/README.md"
            _write_doc(
                root,
                path,
                doc_type="evidence",
                topic="example-evidence",
                status="implemented",
                canonical=False,
                owner_spec=owner,
                body="# Example Evidence\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="evidence",
                    topic="example-evidence",
                    status="implemented",
                    canonical=False,
                    owner=owner,
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("invalid_owner", self._checks(report))

    def test_metadata_governance_fields_require_valid_types_and_references(self) -> None:
        cases = {
            "related_type": ("related: []", "related: docs/specs/example.md"),
            "related_reference": ("related: []", 'related: ["docs/missing.md"]'),
            "supersedes_type": ("supersedes: []", "supersedes: docs/specs/example.md"),
            "supersedes_reference": ("supersedes: []", 'supersedes: ["docs/missing.md"]'),
            "superseded_by_type": ("superseded_by: null", "superseded_by: []"),
            "superseded_by_reference": ("superseded_by: null", "superseded_by: docs/missing.md"),
        }
        for name, (before, after) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _valid_fixture(root)
                path = root / "docs" / "README.md"
                path.write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
                report = run_document_lifecycle_check(root=root)

            self.assertTrue(
                {"invalid_metadata_type", "invalid_metadata_reference"} & self._checks(report),
                report,
            )

    def test_metadata_related_must_match_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            path = root / "docs" / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "related: []",
                    'related: ["docs/specs/example.md"]',
                ),
                encoding="utf-8",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("metadata_mismatch", self._checks(report))

    def test_metadata_dates_must_be_iso_calendar_dates(self) -> None:
        cases = (
            ("created: 2026-08-03", "created: 2026-02-30"),
            ("updated: 2026-08-03", "updated: []"),
        )
        for before, after in cases:
            with self.subTest(value=after), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _valid_fixture(root)
                path = root / "docs" / "README.md"
                path.write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_metadata_date", self._checks(report))

    def test_metadata_owner_must_match_registry_in_both_directions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            path = root / "docs" / "README.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "supersedes: []",
                    "owner_spec: docs/specs/example.md\nsupersedes: []",
                ),
                encoding="utf-8",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("metadata_mismatch", self._checks(report))

    def test_implementation_authority_requires_approved_spec_or_plan(self) -> None:
        cases = (
            ("docs/README.md", "index", "active"),
            ("docs/plans/example.md", "plan", "proposed"),
        )
        for path, doc_type, status in cases:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                entry = next(item for item in entries if item["path"] == path)
                self.assertEqual(entry["doc_type"], doc_type)
                self.assertEqual(entry["status"], status)
                entry["implementation_authority"] = True
                document = root / path
                document.write_text(
                    document.read_text(encoding="utf-8").replace(
                        "implementation_authority: false",
                        "implementation_authority: true",
                    ),
                    encoding="utf-8",
                )
                _write_registry(root, entries)
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_authority", self._checks(report))

    def test_archive_metadata_requires_iso_date_and_reason_enum(self) -> None:
        cases = (
            ("archived: 2026-08-03", "archived: 2026-02-30"),
            ("historical_reason: completed", "historical_reason: arbitrary"),
        )
        for before, after in cases:
            with self.subTest(value=after), tempfile.TemporaryDirectory() as tmp:
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
                    archive_fields=True,
                    body="# Old Plan\n\nHistorical and non-authoritative.\n",
                )
                document = root / path
                document.write_text(document.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
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

    def test_legacy_metadata_fields_are_validated_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/legacy-with-metadata.md"
            _write_doc(
                root,
                path,
                doc_type="reference",
                topic="legacy-with-metadata",
                status="reference",
                canonical=False,
                body="# Legacy With Metadata\n",
            )
            legacy_path = root / path
            legacy_path.write_text(
                legacy_path.read_text(encoding="utf-8").replace(
                    "related: []",
                    "related: docs/specs/example.md",
                ),
                encoding="utf-8",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="reference",
                    topic="legacy-with-metadata",
                    status="reference",
                    canonical=False,
                    legacy_metadata=True,
                    baseline_class="reference_candidate",
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("invalid_metadata_type", self._checks(report))

    def test_registry_legacy_flags_must_be_boolean(self) -> None:
        for key in ("legacy_metadata", "legacy_path"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                entries[0][key] = "true"
                _write_registry(root, entries)
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_legacy_flag", self._checks(report))

    def test_new_paths_cannot_claim_legacy_exemptions(self) -> None:
        cases = (
            ("docs/new-legacy.md", True, False),
            ("docs/superpowers/plans/new-legacy.md", False, True),
        )
        for path, legacy_metadata, legacy_path in cases:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                entries = _valid_fixture(root)
                _write_doc(
                    root,
                    path,
                    doc_type="reference",
                    topic="new-legacy",
                    status="reference",
                    canonical=False,
                    body="# New Legacy Claim\n",
                )
                entries.append(
                    _entry(
                        path,
                        doc_type="reference",
                        topic="new-legacy",
                        status="reference",
                        canonical=False,
                        legacy_metadata=legacy_metadata,
                        legacy_path=legacy_path,
                    )
                )
                _write_registry(root, entries, adopted=True)
                report = run_document_lifecycle_check(root=root)

            self.assertIn("invalid_legacy_exemption", self._checks(report))

    def test_roadmap_checkbox_counts_must_match_registry_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            roadmap = root / "docs" / "roadmap.md"
            roadmap.write_text(roadmap.read_text(encoding="utf-8") + "\n- [x] Completed\n", encoding="utf-8")
            report = run_document_lifecycle_check(root=root)

        self.assertIn("roadmap_count_mismatch", self._checks(report))

    def test_registry_requires_one_canonical_active_roadmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/second-roadmap.md"
            _write_doc(
                root,
                path,
                doc_type="roadmap",
                topic="second-roadmap",
                status="active",
                canonical=True,
                body="# Second Roadmap\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="roadmap",
                    topic="second-roadmap",
                    status="active",
                    canonical=True,
                    baseline_class="active_owner",
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertIn("roadmap_governance", self._checks(report))

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

    def test_missing_markdown_image_is_reported(self) -> None:
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
                body="# Documentation\n\n![Missing image](missing.png)\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("broken_markdown_link", self._checks(report))

    def test_inline_code_link_syntax_is_not_checked(self) -> None:
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
                body="# Documentation\n\nExample: `![...](images/missing.png)`.\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)

    def test_reference_style_link_target_is_checked(self) -> None:
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
                body="# Documentation\n\n[Missing][guide]\n\n[guide]: missing.md\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("broken_markdown_link", self._checks(report))

    def test_undefined_reference_style_link_is_reported(self) -> None:
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
                body="# Documentation\n\n[Missing][undefined-guide]\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("broken_markdown_reference", self._checks(report))

    def test_markdown_link_resolving_outside_repository_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "repo"
            _valid_fixture(root)
            (workspace / "outside.md").write_text("# Outside\n", encoding="utf-8")
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body="# Documentation\n\n[Outside](../../outside.md)\n",
            )
            report = run_document_lifecycle_check(root=root)

        self.assertIn("markdown_link_outside_repository", self._checks(report))

    def test_angle_wrapped_markdown_link_with_spaces_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/My File.md"
            _write_doc(
                root,
                path,
                doc_type="reference",
                topic="space-path",
                status="reference",
                canonical=False,
                body="# Spaced File\n",
            )
            entries.append(
                _entry(
                    path,
                    doc_type="reference",
                    topic="space-path",
                    status="reference",
                    canonical=False,
                )
            )
            _write_doc(
                root,
                "docs/README.md",
                doc_type="index",
                topic="document-index",
                status="active",
                canonical=True,
                body="# Documentation\n\n[Label](<My File.md>)\n",
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)

    def test_external_and_anchor_markdown_links_are_skipped(self) -> None:
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
                    "[HTTPS](https://example.invalid/path)\n"
                    "[Mail](mailto:owner@example.invalid)\n"
                    "[Data](data:text/plain,example)\n"
                    "[Anchor](#documentation)\n"
                ),
            )
            report = run_document_lifecycle_check(root=root)

        self.assertTrue(report["ok"], report)

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

    def test_registered_legacy_document_with_invalid_utf8_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = _valid_fixture(root)
            path = "docs/legacy.md"
            legacy_path = root / path
            legacy_path.write_bytes(b"# Legacy\n\xff\xfe")
            entries.append(
                _entry(
                    path,
                    doc_type="reference",
                    topic="legacy",
                    status="reference",
                    canonical=False,
                    legacy_metadata=True,
                    baseline_class="reference_candidate",
                )
            )
            _write_registry(root, entries)
            report = run_document_lifecycle_check(root=root)

        self.assertFalse(report["ok"], report)
        self.assertIn("document_read", self._checks(report))
        self.assertNotIn("ff", json.dumps(report["findings"]).lower())

    def test_registered_document_os_read_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _valid_fixture(root)
            unreadable = root / "docs" / "README.md"
            real_markdown_files = sorted((root / "docs").rglob("*.md"))
            original_read_text = Path.read_text

            def failing_read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path == unreadable:
                    raise OSError("synthetic private detail")
                return original_read_text(path, *args, **kwargs)

            with patch("pathlib.Path.read_text", new=failing_read_text), patch(
                "document_lifecycle_check._markdown_files",
                return_value=real_markdown_files,
            ):
                report = run_document_lifecycle_check(root=root)

        self.assertFalse(report["ok"], report)
        self.assertIn("document_read", self._checks(report))
        self.assertNotIn("synthetic private detail", json.dumps(report["findings"]))

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
