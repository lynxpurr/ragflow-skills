from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from consumer_acceptance import _github_env, run_consumer_acceptance  # noqa: E402
from export_release_archives import export_release_archives  # noqa: E402


class ConsumerAcceptanceTests(unittest.TestCase):
    def test_github_env_preserves_auth_context(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "HOME": "/tmp/test-home",
                "GH_TOKEN": "token",
                "GITHUB_TOKEN": "github-token",
            },
            clear=True,
        ):
            env = _github_env()

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["HOME"], "/tmp/test-home")
        self.assertEqual(env["GH_TOKEN"], "token")
        self.assertEqual(env["GITHUB_TOKEN"], "github-token")
        self.assertEqual(env["GH_PROMPT_DISABLED"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_rejects_artifacts_inside_overwritten_work_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "artifacts directory"):
                run_consumer_acceptance(
                    artifacts_dir=root / "work" / "downloads",
                    work_root=root / "work",
                    overwrite=True,
                )

    def test_run_consumer_acceptance_from_local_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_payload = export_release_archives(
                dist_dir=root / "dist",
                output_dir=root / "release-artifacts",
                rebuild=True,
                hygiene=True,
            )
            self.assertTrue(export_payload["ok"], export_payload)

            payload = run_consumer_acceptance(
                artifacts_dir=root / "release-artifacts",
                work_root=root / "consumer",
                live_build=True,
                env={},
            )
            report_json = Path(payload["reports"]["json"])
            report_md = Path(payload["reports"]["markdown"])
            self.assertTrue(report_json.exists(), payload)
            self.assertTrue(report_md.exists(), payload)

        self.assertTrue(payload["ok"], payload)
        check_names = [check["name"] for check in payload["checks"]]
        self.assertIn("vendored runtime present", check_names)
        self.assertIn("doc-to-md passthrough", check_names)
        self.assertIn("kb-build dry-run", check_names)
        self.assertIn("query host-assisted help", check_names)
        self.assertIn("query missing config guard", check_names)
        self.assertIn("live build skipped", check_names)
        self.assertTrue(payload["reports"]["json"].endswith("consumer-acceptance-report.json"))


if __name__ == "__main__":
    unittest.main()
