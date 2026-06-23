from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from build_release import PUBLIC_SKILLS, build_release


class ReleaseBuildTests(unittest.TestCase):
    def test_build_release_vendors_core_into_each_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist_dir = Path(tmp) / "dist"
            built = build_release(dist_dir)

            self.assertEqual(sorted(path.name for path in built), sorted(PUBLIC_SKILLS))
            for skill_name in PUBLIC_SKILLS:
                skill_root = dist_dir / skill_name
                self.assertTrue((skill_root / "SKILL.md").exists())
                self.assertTrue((skill_root / "scripts" / "_vendor" / "ragflow_skill_runtime" / "__init__.py").exists())
                self.assertFalse((skill_root / "agents").exists())
                self.assertFalse((skill_root / "references").exists())

            self.assertTrue((dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py").exists())
            self.assertTrue((dist_dir / "ragflow-kb-build" / "scripts" / "inspect_kb.py").exists())
            self.assertTrue((dist_dir / "ragflow-query" / "scripts" / "query.py").exists())
            copied = sorted(p.name for p in dist_dir.iterdir())
            self.assertEqual(copied, sorted(PUBLIC_SKILLS))


if __name__ == "__main__":
    unittest.main()
