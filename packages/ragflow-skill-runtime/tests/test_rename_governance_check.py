from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rename_governance_check import (  # noqa: E402
    DEFAULT_COMPATIBILITY_DOC_ROOTS,
    RENAME_POLICY_PATH,
    SCHEMA,
    CompatibilityAlias,
    run_rename_governance_check,
)


class RenameGovernanceCheckTests(unittest.TestCase):
    def test_wave3_rename_references_use_normalized_paths(self) -> None:
        self.assertEqual(RENAME_POLICY_PATH, Path("docs/reference/public-rename-policy.md"))
        self.assertEqual(
            DEFAULT_COMPATIBILITY_DOC_ROOTS,
            (Path("docs/reference/cross-platform-smoke.md"),),
        )

    def test_rename_governance_passes_for_public_suite(self) -> None:
        report = run_rename_governance_check()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertTrue(report["policy"]["ok"])
        self.assertTrue(report["compatibility"]["ok"])
        self.assertTrue(report["naming_drift"]["ok"])
        self.assertEqual(report["compatibility"]["summary"]["command_schema_alias_status"], "not_applicable")
        self.assertEqual(report["summary"]["drift_finding_count"], 0)

    def test_rename_governance_reports_policy_and_drift_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RENAME_POLICY_PATH).parent.mkdir(parents=True, exist_ok=True)
            (root / RENAME_POLICY_PATH).write_text("# Incomplete\n", encoding="utf-8")
            skill_root = root / "skills" / "ragflow-query"
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text("Do not publish ragflux names.\n", encoding="utf-8")

            report = run_rename_governance_check(
                root=root,
                compatibility_aliases=(),
                drift_roots=(Path("skills"),),
            )

        self.assertFalse(report["ok"], report)
        self.assertFalse(report["policy"]["ok"])
        self.assertFalse(report["naming_drift"]["ok"])
        self.assertEqual(report["naming_drift"]["summary"]["finding_count"], 1)

    def test_chunk_marker_profile_token_is_allowed_without_general_legacy_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RENAME_POLICY_PATH).parent.mkdir(parents=True, exist_ok=True)
            (root / RENAME_POLICY_PATH).write_text(
                "\n".join(
                    [
                        "## CLI Aliases",
                        "## Schema Migration",
                        "## Documentation Updates",
                        "## Downstream Gates",
                        "## Release Notes",
                        "## Rollback Plan",
                    ]
                ),
                encoding="utf-8",
            )
            skill_root = root / "skills" / "ragflow-doc-to-md"
            skill_root.mkdir(parents=True)
            skill_file = skill_root / "SKILL.md"
            skill_file.write_text("Use profile chunk-markers-ragflux-like for boundary comparison.\n", encoding="utf-8")

            allowed = run_rename_governance_check(
                root=root,
                compatibility_aliases=(),
                drift_roots=(Path("skills"),),
            )
            skill_file.write_text(
                "Use profile chunk-markers-ragflux-like.\nDo not publish ragflux package names.\n",
                encoding="utf-8",
            )
            blocked = run_rename_governance_check(
                root=root,
                compatibility_aliases=(),
                drift_roots=(Path("skills"),),
            )

        self.assertTrue(allowed["naming_drift"]["ok"], allowed)
        self.assertFalse(blocked["naming_drift"]["ok"], blocked)
        self.assertEqual(blocked["naming_drift"]["summary"]["finding_count"], 1)

    def test_skill_doc_directory_is_ignored_as_local_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RENAME_POLICY_PATH).parent.mkdir(parents=True, exist_ok=True)
            (root / RENAME_POLICY_PATH).write_text(
                "\n".join(
                    [
                        "## CLI Aliases",
                        "## Schema Migration",
                        "## Documentation Updates",
                        "## Downstream Gates",
                        "## Release Notes",
                        "## Rollback Plan",
                    ]
                ),
                encoding="utf-8",
            )
            skill_doc = root / "skills" / "ragflow-doc-to-md" / "doc"
            skill_doc.mkdir(parents=True)
            (skill_doc / "private-input.md").write_text("ragflux kb ops local notes\n", encoding="utf-8")

            report = run_rename_governance_check(
                root=root,
                compatibility_aliases=(),
                drift_roots=(Path("skills"),),
            )

        self.assertTrue(report["naming_drift"]["ok"], report)
        self.assertEqual(report["naming_drift"]["summary"]["finding_count"], 0)

    def test_compatibility_alias_requires_facade_evidence(self) -> None:
        alias = CompatibilityAlias(
            kind="command",
            alias="old-command",
            canonical="new-command",
            source_patterns=("old-command", "new-command"),
            coverage_patterns=("old-command", "new-command"),
            docs_patterns=("old-command", "new-command"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            coverage = root / "tests"
            docs = root / "docs"
            source.mkdir()
            coverage.mkdir()
            docs.mkdir()
            (source / "cli.py").write_text('ALIASES = {"old-command": "new-command"}\n', encoding="utf-8")
            (docs / "rename.md").write_text("old-command maps to new-command\n", encoding="utf-8")
            (root / RENAME_POLICY_PATH).parent.mkdir(parents=True, exist_ok=True)
            (root / RENAME_POLICY_PATH).write_text(
                "\n".join(
                    [
                        "## CLI Aliases",
                        "## Schema Migration",
                        "## Documentation Updates",
                        "## Downstream Gates",
                        "## Release Notes",
                        "## Rollback Plan",
                    ]
                ),
                encoding="utf-8",
            )

            report = run_rename_governance_check(
                root=root,
                compatibility_aliases=(alias,),
                compatibility_source_roots=(Path("src"),),
                compatibility_coverage_roots=(Path("tests"),),
                compatibility_doc_roots=(Path("docs/rename.md"),),
                drift_roots=(Path("src"),),
            )

        self.assertFalse(report["ok"], report)
        self.assertFalse(report["compatibility"]["ok"])
        self.assertEqual(report["compatibility"]["summary"]["failed_aliases"], ["command:old-command"])


if __name__ == "__main__":
    unittest.main()
