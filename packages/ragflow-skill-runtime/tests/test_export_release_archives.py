from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from build_release import PUBLIC_SKILLS, ignore_filter  # noqa: E402
from export_release_archives import export_release_archives, sha256_file  # noqa: E402


class ExportReleaseArchivesTests(unittest.TestCase):
    def test_release_build_ignores_skill_local_doc_inputs(self) -> None:
        ignored = ignore_filter("skills/ragflow-doc-to-md", ["SKILL.md", "doc", "references"])

        self.assertIn("doc", ignored)
        self.assertNotIn("SKILL.md", ignored)
        self.assertNotIn("references", ignored)

    def test_export_release_archives_creates_manifest_and_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = export_release_archives(
                dist_dir=root / "dist",
                output_dir=root / "artifacts",
                rebuild=True,
                hygiene=True,
            )

            self.assertTrue(payload["ok"], payload)
            self.assertEqual([item["name"] for item in payload["archives"]], PUBLIC_SKILLS)
            manifest_path = Path(payload["manifest"])
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["archives"]), 4)
            self.assertEqual(manifest["dist"], "dist")
            self.assertEqual(manifest["output_dir"], "artifacts")
            for item in manifest["archives"]:
                self.assertEqual(Path(item["archive"]).name, item["archive"])
                archive = root / "artifacts" / item["archive"]
                self.assertTrue(archive.exists(), item)
                self.assertEqual(item["sha256"], sha256_file(archive))

    def test_exported_archive_contains_vendored_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = export_release_archives(
                dist_dir=root / "dist",
                output_dir=root / "artifacts",
                rebuild=True,
                hygiene=True,
            )
            query_archive = next(
                root / "artifacts" / item["archive"]
                for item in payload["archives"]
                if item["name"] == "ragflow-query"
            )
            with tarfile.open(query_archive, mode="r:gz") as tar:
                names = set(tar.getnames())

        self.assertIn(
            "ragflow-query/scripts/_vendor/ragflow_skill_runtime/__init__.py",
            names,
        )


if __name__ == "__main__":
    unittest.main()
