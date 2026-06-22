#!/usr/bin/env python3
"""Run a clean vendored-import smoke test in a temporary skill layout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src" / "ragflow_skill_runtime"
SMOKE_SRC = ROOT / "skills" / "ragflow-query" / "scripts" / "bootstrap_smoke.py"


def main() -> int:
    if not RUNTIME_SRC.exists():
        print(f"missing skill runtime source: {RUNTIME_SRC}", file=sys.stderr)
        return 2
    if not SMOKE_SRC.exists():
        print(f"missing smoke script: {SMOKE_SRC}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="ragflow-skill-runtime-vendor-smoke-") as tmp:
        scripts_dir = Path(tmp) / "skill" / "scripts"
        vendor_dir = scripts_dir / "_vendor"
        vendor_dir.mkdir(parents=True)
        shutil.copytree(RUNTIME_SRC, vendor_dir / "ragflow_skill_runtime")
        shutil.copy2(SMOKE_SRC, scripts_dir / "bootstrap_smoke.py")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONNOUSERSITE": "1",
        }
        result = subprocess.run(
            [sys.executable, str(scripts_dir / "bootstrap_smoke.py")],
            cwd=Path(tmp),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
