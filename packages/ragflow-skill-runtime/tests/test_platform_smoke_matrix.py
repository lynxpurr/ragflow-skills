from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from platform_smoke_matrix import run_smoke_matrix, selected_profiles  # noqa: E402


class PlatformSmokeMatrixTests(unittest.TestCase):
    def test_selected_profiles_rejects_unknown_id(self) -> None:
        with self.assertRaises(SystemExit):
            selected_profiles(["missing-profile"])

    def test_run_smoke_matrix_for_source_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_smoke_matrix(
                dist_dir=Path(tmp) / "dist",
                work_root=Path(tmp) / "work",
                profile_ids=["hermes-local-source"],
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["built_skills"], ["ragflow-doc-to-md", "ragflow-kb-build", "ragflow-query"])
        self.assertEqual(len(payload["profiles"]), 1)
        profile = payload["profiles"][0]
        self.assertEqual(profile["id"], "hermes-local-source")
        self.assertTrue(profile["ok"], profile)
        check_names = [item["name"] for item in profile["checks"]]
        self.assertIn("doc-to-md passthrough", check_names)
        self.assertIn("query direct and host-assisted", check_names)

    def test_run_smoke_matrix_for_saas_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_smoke_matrix(
                dist_dir=Path(tmp) / "dist",
                work_root=Path(tmp) / "work",
                profile_ids=["saas-sandbox-https"],
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(len(payload["profiles"]), 1)
        profile = payload["profiles"][0]
        self.assertEqual(profile["id"], "saas-sandbox-https")
        self.assertEqual(profile["config_mode"], "env")
        self.assertTrue(profile["ok"], profile)
        self.assertTrue(
            any(path.endswith("validation_report.md") for path in profile["artifacts"]),
            profile["artifacts"],
        )


if __name__ == "__main__":
    unittest.main()
