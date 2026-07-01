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

from wheel_packaging_smoke import (  # noqa: E402
    SCHEMA,
    WheelPackagingSmokeError,
    run_wheel_packaging_smoke,
)


class WheelPackagingSmokeTests(unittest.TestCase):
    def test_wheel_packaging_smoke_builds_installs_and_imports_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_wheel_packaging_smoke(
                work_dir=root / "work",
                keep_artifacts=True,
                timeout=120.0,
            )

            self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False, indent=2))
            self.assertEqual(report["schema"], SCHEMA)
            self.assertTrue(report["artifacts_retained"])
            self.assertEqual(report["package"]["name"], "ragflow-skill-runtime")
            self.assertEqual(report["package"]["version"], "0.1.0")
            self.assertEqual(report["package"]["dependencies"], [])
            self.assertTrue(report["network"]["no_index"])
            self.assertTrue(report["network"]["no_deps"])
            self.assertTrue(report["network"]["no_build_isolation"])

            checks = {check["name"]: check for check in report["checks"]}
            for name in (
                "package directory exists",
                "pyproject metadata present",
                "runtime dependencies empty",
                "build runtime wheel",
                "exactly one wheel produced",
                "prepare isolated install environment",
                "install wheel without index",
                "import installed runtime",
            ):
                self.assertIn(name, checks)
                self.assertTrue(checks[name]["ok"], checks[name])
            self.assertIn(report["install_environment"]["method"], {"venv", "target"})

            self.assertIsNotNone(report["wheel"])
            wheel_path = Path(report["wheel"]["path"])
            self.assertTrue(wheel_path.exists())
            self.assertEqual(wheel_path.parent, root / "work" / "wheelhouse")
            self.assertIn("ragflow_skill_runtime-0.1.0", report["wheel"]["filename"])

            import_smoke = report["import_smoke"]
            self.assertEqual(import_smoke["distribution_version"], "0.1.0")
            self.assertEqual(import_smoke["runtime_version"], "0.1.0")
            self.assertIn(str(root / "work"), import_smoke["module_file"])
            self.assertIn("ragflow_skill_runtime", import_smoke["module_file"])

    def test_wheel_packaging_smoke_refuses_nonempty_work_dir_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "work"
            work_dir.mkdir()
            (work_dir / "existing.txt").write_text("keep", encoding="utf-8")

            with self.assertRaises(WheelPackagingSmokeError):
                run_wheel_packaging_smoke(work_dir=work_dir)


if __name__ == "__main__":
    unittest.main()
