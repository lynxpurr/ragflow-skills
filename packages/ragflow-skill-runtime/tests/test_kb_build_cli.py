from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
BUILD_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "build.py"
INSPECT_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "inspect_kb.py"
VALIDATE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "validate.py"
PROFILE_PATH = ROOT / "skills" / "ragflow-kb-build" / "templates" / "default-en-768.json"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["RAGFLOW_SKILL_RUNTIME_PATH"] = str(RUNTIME_SRC)
    return env


class KbBuildCliTests(unittest.TestCase):
    def test_build_dry_run_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "docs"
            input_dir.mkdir()
            (input_dir / "sample.md").write_text("# Title\n\nBody\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--kb-name",
                    "kb:test",
                    "--profile",
                    str(PROFILE_PATH),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["kb_name"], "kb:test")
        self.assertEqual(len(payload["documents"]), 1)

    def test_build_dry_run_accepts_doc_manifest_paths_relative_to_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            docs_dir = handoff / "documents"
            docs_dir.mkdir(parents=True)
            (docs_dir / "sample.md").write_text("# Title\n\nBody\n", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "source.pdf",
                                "markdown_path": "documents/sample.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    "kb:test",
                    "--profile",
                    str(PROFILE_PATH),
                    "--dry-run",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["documents"], [str(docs_dir / "sample.md")])

    def test_build_help_exposes_wait_options(self) -> None:
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-wait", result.stdout)
        self.assertIn("--parse-timeout", result.stdout)

    def test_inspect_manifest_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "documents": [{"document_id": "doc-1", "status": "uploaded"}],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(INSPECT_SCRIPT), "--kb-manifest", str(manifest)],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dataset"]["id"], "ds-1")
        self.assertEqual(payload["document_count"], 1)

    def test_validate_regression_reports_mvp_gap_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--level",
                    "regression",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 2, result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["implemented_levels"], ["smoke"])


if __name__ == "__main__":
    unittest.main()
