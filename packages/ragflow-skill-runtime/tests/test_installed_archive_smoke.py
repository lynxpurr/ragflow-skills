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

from build_release import PUBLIC_SKILLS  # noqa: E402
from installed_archive_smoke import SCHEMA, run_installed_archive_smoke  # noqa: E402


class InstalledArchiveSmokeTests(unittest.TestCase):
    def test_installed_archive_smoke_checks_each_exported_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_installed_archive_smoke(
                artifacts_dir=root / "release-artifacts",
                dist_dir=root / "dist",
                work_dir=root / "work",
                export_archives=True,
                hygiene=True,
                keep_artifacts=True,
            )

            self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
            self.assertEqual(report["schema"], SCHEMA)
            self.assertTrue(report["release_manifest"]["found"])
            self.assertEqual([archive["name"] for archive in report["archives"]], PUBLIC_SKILLS)
            self.assertEqual(report["summary"]["archive_count"], len(PUBLIC_SKILLS))
            self.assertGreaterEqual(report["summary"]["check_count"], 12)

            checks_by_skill = {
                archive["name"]: {check["name"]: check for check in archive["checks"]}
                for archive in report["archives"]
            }
            self.assertTrue(checks_by_skill["ragflow-doc-to-md"]["doc-to-md convert help"]["ok"])
            self.assertTrue(
                checks_by_skill["ragflow-canonical-review"]["canonical-review markdown audit help"]["ok"]
            )
            self.assertTrue(
                checks_by_skill["ragflow-canonical-review"]["canonical-review asset audit help"]["ok"]
            )
            self.assertTrue(checks_by_skill["ragflow-kb-build"]["kb-build build help"]["ok"])
            self.assertTrue(checks_by_skill["ragflow-query"]["query bootstrap smoke"]["ok"])
            self.assertTrue(checks_by_skill["ragflow-query"]["query CLI help"]["ok"])
            for skill_name in PUBLIC_SKILLS:
                self.assertTrue((root / "work" / "archives" / skill_name / "unpacked" / skill_name / "SKILL.md").exists())
                self.assertTrue(
                    (
                        root
                        / "work"
                        / "archives"
                        / skill_name
                        / "unpacked"
                        / skill_name
                        / "scripts"
                        / "_vendor"
                        / "ragflow_skill_runtime"
                        / "__init__.py"
                    ).exists()
                )

    def test_installed_archive_smoke_reports_missing_archives_without_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_installed_archive_smoke(
                artifacts_dir=root / "missing-artifacts",
                dist_dir=root / "dist",
                work_dir=root / "work",
                export_archives=False,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["schema"], SCHEMA)
            self.assertEqual(report["summary"]["archive_count"], len(PUBLIC_SKILLS))
            failed = report["summary"]["failed_checks"]
            self.assertIn("ragflow-doc-to-md: archive exists", failed)
            self.assertIn("ragflow-canonical-review: archive exists", failed)
            self.assertIn("ragflow-kb-build: archive exists", failed)
            self.assertIn("ragflow-query: archive exists", failed)


if __name__ == "__main__":
    unittest.main()
