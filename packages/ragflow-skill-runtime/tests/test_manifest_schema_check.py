from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from manifest_schema_check import SCHEMA, run_manifest_schema_check  # noqa: E402


class ManifestSchemaCheckTests(unittest.TestCase):
    def test_manifest_schema_check_passes_for_public_suite(self) -> None:
        report = run_manifest_schema_check()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["summary"]["schema_count"], 3)
        checked = {check["name"] for check in report["checks"]}
        self.assertEqual(checked, {"doc_manifest", "kb_manifest", "formal_handoff_manifest"})
        for check in report["checks"]:
            self.assertTrue(check["template_matches_runtime"], check)
            self.assertTrue(check["example_valid"], check)
