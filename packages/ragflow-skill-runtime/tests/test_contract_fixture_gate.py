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

from contract_fixture_gate import SCHEMA, run_contract_fixture_gate  # noqa: E402


class ContractFixtureGateTests(unittest.TestCase):
    def test_contract_fixture_gate_accepts_plain_and_rich_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_contract_fixture_gate(
                dist_dir=root / "dist",
                work_dir=root / "work",
                rebuild=True,
                keep_artifacts=True,
            )

            self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
            self.assertEqual(report["schema"], SCHEMA)
            self.assertTrue(report["artifacts_retained"])

            checks = {check["name"]: check for check in report["checks"]}
            for name in (
                "doc-to-md plain handoff",
                "doc-to-md rich handoff source",
                "doc-to-md rich handoff package",
                "kb-build plain handoff dry-run",
                "kb-build rich handoff dry-run",
                "kb-build inspect rich handoff",
            ):
                self.assertIn(name, checks)
                self.assertTrue(checks[name]["ok"], checks[name])

            plain_dry_run = checks["kb-build plain handoff dry-run"]["stdout_json"]
            rich_dry_run = checks["kb-build rich handoff dry-run"]["stdout_json"]
            self.assertTrue(plain_dry_run["dry_run"])
            self.assertTrue(rich_dry_run["dry_run"])
            self.assertEqual(plain_dry_run["kb_name"], "kb:contract-fixture-plain")
            self.assertEqual(rich_dry_run["kb_name"], "kb:contract-fixture-rich")
            self.assertEqual(len(plain_dry_run["documents"]), 1)
            self.assertEqual(len(rich_dry_run["documents"]), 1)

            work = root / "work"
            self.assertTrue((work / "plain-handoff" / "doc_manifest.json").exists())
            self.assertTrue((work / "rich-handoff" / "metadata.json").exists())
            self.assertTrue((work / "rich-handoff" / "artifact_index.json").exists())
            self.assertTrue((work / "rich_handoff_inspection.json").exists())

    def test_contract_fixture_gate_reports_missing_dist_when_no_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_contract_fixture_gate(
                dist_dir=root / "missing-dist",
                work_dir=root / "work",
                rebuild=False,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["schema"], SCHEMA)
            self.assertGreaterEqual(report["summary"]["failed_count"], 1)
            failed = {check["name"] for check in report["checks"] if not check["ok"]}
            self.assertIn("dist doc-to-md convert script", failed)
            self.assertIn("dist kb-build script", failed)


if __name__ == "__main__":
    unittest.main()
