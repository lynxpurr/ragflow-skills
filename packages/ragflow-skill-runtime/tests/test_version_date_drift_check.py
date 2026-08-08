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

from version_date_drift_check import DOC_VERSION_PATHS, SCHEMA, run_version_date_drift_check  # noqa: E402


PUBLIC_SKILLS = (
    "ragflow-doc-to-md",
    "ragflow-canonical-review",
    "ragflow-kb-build",
    "ragflow-query",
)


def _write_minimal_repo(root: Path) -> None:
    runtime_pkg = root / "packages" / "ragflow-skill-runtime"
    runtime_src = runtime_pkg / "src" / "ragflow_skill_runtime"
    runtime_src.mkdir(parents=True)
    (runtime_pkg / "pyproject.toml").write_text(
        '[project]\nname = "ragflow-skill-runtime"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (runtime_src / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    tools = root / "tools"
    tools.mkdir()
    (tools / "build_release.py").write_text('manifest = {"version": "0.1"}\n', encoding="utf-8")
    (tools / "export_release_archives.py").write_text(
        'DEFAULT_MTIME = 1767225600\nmanifest = {"version": "0.1"}\n',
        encoding="utf-8",
    )

    release_artifacts = root / "release-artifacts"
    release_artifacts.mkdir()
    (release_artifacts / "release-manifest.json").write_text(
        json.dumps({"version": "0.1", "created_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    docs = root / "docs"
    docs.mkdir()
    (docs / "03-development-plan.md").write_text("Stable release is `v0.1.0`.\n", encoding="utf-8")

    for skill_name in PUBLIC_SKILLS:
        skill_root = root / "skills" / skill_name
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: fixture skill\n---\n",
            encoding="utf-8",
        )


class VersionDateDriftCheckTests(unittest.TestCase):
    def test_wave3_release_references_use_normalized_paths(self) -> None:
        expected = {
            Path("docs/reference/release-hardening.md"),
            Path("docs/reference/cli-agent-integration.md"),
            Path("docs/reference/release-archive-forward-test-prompts.md"),
        }
        self.assertTrue(expected.issubset(DOC_VERSION_PATHS))
        self.assertFalse(
            {
                Path("docs/06-release-hardening.md"),
                Path("docs/08-cli-agent-integration.md"),
                Path("docs/12-release-archive-forward-test-prompts.md"),
            }
            & set(DOC_VERSION_PATHS)
        )

    def test_first_release_uses_archived_static_path(self) -> None:
        self.assertIn(Path("docs/archive/2026/evidence/07-first-release.md"), DOC_VERSION_PATHS)
        self.assertNotIn(Path("docs/07-first-release.md"), DOC_VERSION_PATHS)

    def test_version_date_drift_check_passes_for_public_repo(self) -> None:
        report = run_version_date_drift_check()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["expected"]["package_version"], "0.1.0")
        self.assertEqual(report["expected"]["release_version"], "0.1")
        self.assertEqual(report["summary"]["finding_count"], 0)

    def test_version_date_drift_check_reports_static_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_repo(root)
            (root / "packages" / "ragflow-skill-runtime" / "src" / "ragflow_skill_runtime" / "__init__.py").write_text(
                '__version__ = "0.2.0"\n',
                encoding="utf-8",
            )
            (root / "tools" / "build_release.py").write_text('manifest = {"version": "0.2"}\n', encoding="utf-8")
            (root / "release-artifacts" / "release-manifest.json").write_text(
                json.dumps({"version": "0.2", "created_at": "2026-01-02T00:00:00+00:00"}),
                encoding="utf-8",
            )
            (root / "docs" / "03-development-plan.md").write_text("Stable release is `v0.2.0`.\n", encoding="utf-8")
            (root / "skills" / "ragflow-query" / "SKILL.md").write_text(
                "---\nname: ragflow-query\ndescription: fixture skill\nversion: 0.2.0\ndate: 2026-01-02\n---\n",
                encoding="utf-8",
            )

            report = run_version_date_drift_check(root=root, public_skills=PUBLIC_SKILLS)

        checks = {finding["check"] for finding in report["findings"]}
        self.assertFalse(report["ok"], report)
        self.assertIn("runtime_version_matches_package", checks)
        self.assertIn("build_release_version_matches_package_major_minor", checks)
        self.assertIn("release_manifest_version_matches_package_major_minor", checks)
        self.assertIn("release_manifest_created_at_matches_export_default", checks)
        self.assertIn("docs_stable_versions_match_package", checks)
        self.assertIn("skill_metadata_version_matches_package", checks)
        self.assertIn("skill_metadata_date_matches_release_manifest", checks)

    def test_external_product_version_does_not_count_as_stable_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_repo(root)
            (root / "docs" / "03-development-plan.md").write_text(
                "Stable release is `v0.1.0`.\n"
                "The reviewed RAGFlow `v0.25.5` source is pinned for contract evidence.\n",
                encoding="utf-8",
            )

            report = run_version_date_drift_check(root=root, public_skills=PUBLIC_SKILLS)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["observed"]["doc_versions"], {"docs/03-development-plan.md": ["0.1.0"]})


if __name__ == "__main__":
    unittest.main()
