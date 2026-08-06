from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from forward_test_prompt_check import PROMPT_PATH, SCHEMA, run_forward_test_prompt_check  # noqa: E402


def _template(host: str, work_dir: str) -> str:
    return f"""```text
Use the public RAGFlow skill release artifacts in release-artifacts/ to validate
installed artifacts as {host}. Work only under {work_dir}.
Do not edit the repository, dist/, or release-artifacts/. Do not use network
access, real credentials, RAGFlow endpoints, dataset creation, uploads, or any
live mutation.

Steps:
1. Inspect release-artifacts/release-manifest.json and confirm it lists
   ragflow-doc-to-md.tar.gz, ragflow-kb-build.tar.gz, and ragflow-query.tar.gz.
2. Recreate {work_dir}, copy or read the archives from release-artifacts/, and
   unpack all three archives under that work directory.
3. Create a tiny Markdown file under ./input-docs.
4. Run:
   python3 ragflow-doc-to-md/scripts/convert.py --input ./input-docs --output ./handoff --mode passthrough --json
5. Run:
   python3 ragflow-kb-build/scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name forward-test --profile ./ragflow-kb-build/templates/default-en-768.json --dry-run --json
6. Run:
   python3 ragflow-query/scripts/query.py --help
   python3 ragflow-query/scripts/query.py ask --help
7. Report exact commands, success or failure, friction, and produced files. Confirm
   handoff/doc_manifest.json exists and the host-assisted query interface is visible.
```"""


def _prompt_doc(*, openclaw_template: str | None = None, extra_requirements: str = "") -> str:
    return f"""# Release Archive Forward-Test Prompts

## Requirements

- Validate installed artifacts from release-artifacts/, not the source tree.
- Inspect release-manifest.json and unpack ragflow-doc-to-md.tar.gz,
  ragflow-kb-build.tar.gz, and ragflow-query.tar.gz.
- Use python3.
- Do not edit the repository or run live mutation.
{extra_requirements}

## Hermes Template

{_template("Hermes", "/tmp/ragflow-forward-test-hermes")}

## OpenClaw Template

{openclaw_template or _template("OpenClaw", "/tmp/ragflow-forward-test-openclaw")}

## Expected Report

- the release manifest path and archive names checked;
- exact commands, pass/fail status, friction, and produced files;
- whether handoff/doc_manifest.json exists;
- whether ragflow-query exposed the host-assisted query interface.
"""


class ForwardTestPromptCheckTests(unittest.TestCase):
    def test_wave3_prompt_reference_uses_normalized_path(self) -> None:
        self.assertEqual(PROMPT_PATH, Path("docs/reference/release-archive-forward-test-prompts.md"))

    def test_forward_test_prompt_check_passes_for_public_suite(self) -> None:
        report = run_forward_test_prompt_check()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["summary"]["failed_prompts"], [])
        self.assertEqual(report["sections"]["missing_sections"], [])

    def test_forward_test_prompt_check_reports_missing_template_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / PROMPT_PATH).parent.mkdir(parents=True, exist_ok=True)
            broken_openclaw = _template("OpenClaw", "/tmp/ragflow-forward-test-openclaw").replace(
                "--dry-run ",
                "",
            )
            (root / PROMPT_PATH).write_text(
                _prompt_doc(openclaw_template=broken_openclaw),
                encoding="utf-8",
            )

            report = run_forward_test_prompt_check(root=root)

        self.assertFalse(report["ok"], report)
        self.assertEqual(report["summary"]["failed_prompts"], ["OpenClaw"])
        checks = {finding["check"] for finding in report["findings"]}
        self.assertIn("prompt_template_coverage", checks)

    def test_forward_test_prompt_check_reports_forbidden_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / PROMPT_PATH).parent.mkdir(parents=True, exist_ok=True)
            (root / PROMPT_PATH).write_text(
                _prompt_doc(extra_requirements="- Never use /home/private-user/config.yaml.\n"),
                encoding="utf-8",
            )

            report = run_forward_test_prompt_check(root=root)

        self.assertFalse(report["ok"], report)
        checks = {finding["check"] for finding in report["findings"]}
        self.assertIn("personal_home_path", checks)


if __name__ == "__main__":
    unittest.main()
