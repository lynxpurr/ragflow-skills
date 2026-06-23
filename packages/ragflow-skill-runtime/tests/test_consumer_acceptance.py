from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from consumer_acceptance import run_consumer_acceptance  # noqa: E402
from export_release_archives import export_release_archives  # noqa: E402


class ConsumerAcceptanceTests(unittest.TestCase):
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
        self.assertTrue(payload["reports"]["json"].endswith("consumer-acceptance-report.json"))


if __name__ == "__main__":
    unittest.main()
