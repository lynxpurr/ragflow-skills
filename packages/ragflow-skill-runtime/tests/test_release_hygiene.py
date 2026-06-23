from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from release_hygiene_check import run_hygiene_check, scan_forbidden_patterns  # noqa: E402


class ReleaseHygieneTests(unittest.TestCase):
    def test_hygiene_check_passes_for_built_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_hygiene_check(
                dist_dir=Path(tmp) / "dist",
                rebuild=True,
                scan_source=True,
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["findings"], [])

    def test_forbidden_private_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "skill" / "scripts"
            target.mkdir(parents=True)
            (target / "bad.py").write_text('BAD = "/home/private-user/private"\n', encoding="utf-8")

            findings = scan_forbidden_patterns(root, base=root)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "personal_home_path")
        self.assertEqual(findings[0].line, 1)


if __name__ == "__main__":
    unittest.main()
