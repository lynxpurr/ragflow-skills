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

from export_runtime_wheel import (  # noqa: E402
    MANIFEST_NAME,
    SCHEMA,
    export_runtime_wheel,
    sha256_file,
)


class ExportRuntimeWheelTests(unittest.TestCase):
    def test_export_runtime_wheel_writes_smoke_validated_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = export_runtime_wheel(
                output_dir=root / "artifacts" / "wheels",
                work_dir=root / "work",
                overwrite=True,
                timeout=120.0,
            )

            self.assertTrue(payload["ok"], json.dumps(payload, ensure_ascii=False, indent=2))
            self.assertEqual(payload["schema"], SCHEMA)
            self.assertEqual(payload["summary"]["wheel_count"], 1)
            self.assertEqual(payload["summary"]["failed_count"], 0)
            self.assertEqual(payload["package"]["name"], "ragflow-skill-runtime")
            self.assertEqual(payload["package"]["version"], "0.1.0")
            self.assertEqual(payload["smoke"]["ok"], True)
            self.assertIn(payload["smoke"]["install_method"], {"venv", "target"})

            wheel_path = Path(payload["wheel"]["path"])
            manifest_path = Path(payload["manifest"])
            self.assertTrue(wheel_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertEqual(manifest_path.name, MANIFEST_NAME)
            self.assertEqual(payload["wheel"]["sha256"], sha256_file(wheel_path))
            self.assertIn("ragflow_skill_runtime-0.1.0", payload["wheel"]["filename"])

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], SCHEMA)
            self.assertEqual(manifest["wheel"]["sha256"], payload["wheel"]["sha256"])
            self.assertEqual(manifest["smoke"]["summary"]["failed_count"], 0)

    def test_export_runtime_wheel_reports_failed_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = export_runtime_wheel(
                package_dir=root / "missing-package",
                output_dir=root / "artifacts" / "wheels",
                work_dir=root / "work",
                overwrite=True,
            )

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["schema"], SCHEMA)
            self.assertEqual(payload["summary"]["failed_checks"], ["wheel packaging smoke"])
            self.assertIsNotNone(payload["smoke"])
            self.assertFalse(payload["smoke"]["ok"])
            self.assertIsNone(payload["wheel"])


if __name__ == "__main__":
    unittest.main()
