from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MARKDOWN_AUDIT = _load_module(
    "canonical_markdown_audit_test",
    "skills/ragflow-canonical-review/scripts/audit_markdown_structure.py",
)
ASSET_AUDIT = _load_module(
    "canonical_asset_audit_test",
    "skills/ragflow-canonical-review/scripts/audit_canonical_assets.py",
)


class CanonicalReviewTests(unittest.TestCase):
    def test_markdown_audit_reports_static_pass_with_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            (assets / "workflow.png").write_bytes(b"workflow image")
            markdown = root / "document.md"
            markdown.write_text(
                "# Document\n\n"
                "Reviewed content.\n\n"
                "| Item | Value |\n"
                "| --- | --- |\n"
                "| A | B |\n\n"
                "![Workflow](assets/workflow.png)\n",
                encoding="utf-8",
            )
            source = root / "document.pdf"
            source.write_bytes(b"source bytes")
            args = MARKDOWN_AUDIT.build_parser().parse_args(
                [
                    "--markdown",
                    str(markdown),
                    "--image-root",
                    str(root),
                    "--asset-scope",
                    "assets",
                    "--source",
                    str(source),
                ]
            )

            report = MARKDOWN_AUDIT.audit(args)

        self.assertEqual(report["schema"], "ragflow_canonical_markdown_audit_v1")
        self.assertEqual(report["status"], "static_pass")
        self.assertFalse(report["source_fidelity_proven"])
        self.assertEqual(report["summary"]["valid_markdown_table_count"], 1)
        self.assertEqual(report["summary"]["image_reference_count"], 1)
        self.assertEqual(report["summary"]["unreferenced_asset_count"], 0)

    def test_markdown_audit_marks_source_unavailable_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "document.md"
            markdown.write_text("# Document\n\nContent.\n", encoding="utf-8")
            args = MARKDOWN_AUDIT.build_parser().parse_args(["--markdown", str(markdown)])

            report = MARKDOWN_AUDIT.audit(args)

        self.assertEqual(report["status"], "review_required")
        self.assertIn("needs_source_verification", {item["code"] for item in report["issues"]})

    def test_asset_audit_reports_allowlist_and_asset_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            canonical = project / "canonical"
            images = canonical / "images"
            empty = canonical / "empty"
            images.mkdir(parents=True)
            empty.mkdir()
            (images / "active.png").write_bytes(b"active")
            (images / "duplicate-a.png").write_bytes(b"duplicate")
            (images / "duplicate-b.png").write_bytes(b"duplicate")
            (canonical / "active.md").write_text(
                "# Active\n\n![Active](images/active.png)\n",
                encoding="utf-8",
            )
            (canonical / "inactive.md").write_text("# Inactive\n", encoding="utf-8")
            (canonical / "AGENTS.md").write_text("# Control\n", encoding="utf-8")
            allowlist = project / "allowlist.txt"
            allowlist.write_text("canonical/active.md\n", encoding="utf-8")
            args = ASSET_AUDIT.build_parser().parse_args(
                [
                    str(canonical),
                    "--allowlist",
                    str(allowlist),
                    "--project-root",
                    str(project),
                ]
            )

            report = ASSET_AUDIT.build_report(args)

        self.assertEqual(report["schema"], "ragflow_canonical_asset_audit_v1")
        self.assertEqual(report["summary"]["missing_reference_count"], 0)
        self.assertEqual(report["summary"]["unreferenced_asset_count"], 2)
        self.assertEqual(report["summary"]["duplicate_image_hash_group_count"], 1)
        self.assertEqual(report["summary"]["control_file_count"], 1)
        self.assertEqual(report["summary"]["markdown_not_in_active_allowlist_count"], 2)
        self.assertEqual(report["summary"]["empty_ordinary_directory_count"], 1)


if __name__ == "__main__":
    unittest.main()
