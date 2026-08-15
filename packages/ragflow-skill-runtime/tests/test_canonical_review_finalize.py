from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from ragflow_skill_runtime.canonical_review import (
    CANONICAL_REVIEW_SCHEMA,
    finalize_canonical_review,
    materialize_canonical_review_output,
    validate_canonical_review_build_binding,
    validate_canonical_review_record,
)


ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FINALIZE_CLI = _load_module(
    "canonical_review_finalize_test",
    "skills/ragflow-canonical-review/scripts/finalize_review.py",
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


class CanonicalReviewFixture:
    candidate_table = (
        "<table>\n"
        "<tr><th>Item</th><th>Value</th></tr>\n"
        "<tr><td>A</td><td>B</td></tr>\n"
        "</table>"
    )
    accepted_table = (
        "| Item | Value |\n"
        "| --- | --- |\n"
        "| A | B |"
    )

    def __init__(self, root: Path) -> None:
        self.root = root
        self.handoff = root / "original-handoff"
        self.candidate = self.handoff / "documents" / "document.md"
        self.manifest = self.handoff / "doc_manifest.json"
        self.review_root = root / "review-workspace"
        self.reviewed = self.review_root / "document.md"
        self.asset = self.review_root / "images" / "figure.png"
        self.source = root / "source.pdf"
        self.coverage = root / "source-coverage.json"
        self.markdown_audit = root / "markdown-audit.json"
        self.asset_audit = root / "asset-audit.json"
        self.decisions = root / "table-decisions.json"
        self.asset_identities = root / "asset-identities.json"

        self.candidate.parent.mkdir(parents=True)
        self.reviewed.parent.mkdir(parents=True)
        self.asset.parent.mkdir(parents=True)
        self.source.write_bytes(b"exact source bytes")
        self.asset.write_bytes(b"reviewed figure bytes")
        self.candidate.write_text(
            f"# Document\n\n{self.candidate_table}\n\n"
            "![Figure](images/figure.png)\n",
            encoding="utf-8",
        )
        self.reviewed.write_text(
            f"# Document\n\n{self.accepted_table}\n\n"
            "![Figure](images/figure.png)\n",
            encoding="utf-8",
        )
        self.manifest.write_text(
            json.dumps(
                {
                    "version": "0.1",
                    "documents": [
                        {
                            "source_path": "document.pdf",
                            "markdown_path": "documents/document.md",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.write_inputs()

    def write_inputs(
        self,
        *,
        coverage_status: str = "complete",
        uncovered_units: list[str] | None = None,
        decisions: list[dict[str, str]] | None = None,
        unresolved_items: list[dict[str, str]] | None = None,
    ) -> None:
        source_hash = _sha_file(self.source)
        reviewed_text = self.reviewed.read_text(encoding="utf-8")
        has_html = "<table" in reviewed_text.casefold()
        self.coverage.write_text(
            json.dumps(
                {
                    "status": coverage_status,
                    "source_sha256": source_hash,
                    "covered_units": ["page:1"],
                    "uncovered_units": uncovered_units or [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.markdown_audit.write_text(
            json.dumps(
                {
                    "schema": "ragflow_canonical_markdown_audit_v1",
                    "status": "review_required" if has_html else "static_pass",
                    "markdown": {
                        "path": str(self.reviewed),
                        "sha256": _sha_file(self.reviewed),
                    },
                    "source": {
                        "status": "available_identity_recorded",
                        "name": self.source.name,
                        "sha256": source_hash,
                    },
                    "summary": {
                        "error": 0,
                        "warning": 1 if has_html else 0,
                    },
                    "issues": (
                        [
                            {
                                "severity": "warning",
                                "code": "html_table_residue",
                                "message": "HTML table review required.",
                            }
                        ]
                        if has_html
                        else []
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.asset_audit.write_text(
            json.dumps(
                {
                    "schema": "ragflow_canonical_asset_audit_v1",
                    "root": str(self.review_root),
                    "allowlist": str(self.root / "active-paths.txt"),
                    "summary": {
                        "missing_reference_count": 0,
                        "markdown_not_in_active_allowlist_count": 0,
                    },
                    "missing_references": [],
                    "images": [
                        {
                            "path": "images/figure.png",
                            "reference_count": 1,
                            "sha256": _sha_file(self.asset),
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        default_decisions = [
            {
                "table_id": "table-001",
                "action": "converted_to_markdown",
                "source_reference": "page:1",
                "before_sha256": _sha_text(self.candidate_table),
                "after_sha256": _sha_text(self.accepted_table),
                "reason": "Rows and columns were verified against the exact source.",
            }
        ]
        self.decisions.write_text(
            json.dumps(
                {
                    "decisions": default_decisions if decisions is None else decisions,
                    "unresolved_items": unresolved_items or [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def finalize(self, *, source: Path | None | object = ...) -> dict[str, object]:
        source_path = self.source if source is ... else source
        return finalize_canonical_review(
            source_path=source_path,
            candidate_markdown_path=self.candidate,
            reviewed_markdown_path=self.reviewed,
            markdown_audit_path=self.markdown_audit,
            asset_audit_path=self.asset_audit,
            source_coverage_path=self.coverage,
            table_decisions_path=self.decisions,
            asset_root=self.review_root,
        )

    def write_asset_identities(
        self,
        *,
        canonical_name: str = "verified-system-diagram.png",
        context_sha256: str | None = None,
        ingestion_intent: str = "context_bound",
    ) -> None:
        context_hash = context_sha256 or _sha_text("# Document")
        self.asset_identities.write_text(
            json.dumps(
                {
                    "assets": [
                        {
                            "path": "images/figure.png",
                            "role": "diagram",
                            "canonical_name": canonical_name,
                            "source_reference": "page:1 figure:1",
                            "context_selector": "line:1-1",
                            "context_sha256": context_hash,
                            "ingestion_intent": ingestion_intent,
                        }
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def finalize_with_asset_identities(self) -> dict[str, object]:
        return finalize_canonical_review(
            source_path=self.source,
            candidate_markdown_path=self.candidate,
            reviewed_markdown_path=self.reviewed,
            markdown_audit_path=self.markdown_audit,
            asset_audit_path=self.asset_audit,
            source_coverage_path=self.coverage,
            table_decisions_path=self.decisions,
            asset_identity_path=self.asset_identities,
            asset_root=self.review_root,
        )


class CanonicalReviewRuntimeTests(unittest.TestCase):
    def test_finalized_record_is_valid_build_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            record = fixture.finalize()
            record_path = fixture.root / "ragflow_canonical_review.json"
            record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            expected_hash = _sha_file(record_path)

            record_hash = validate_canonical_review_build_binding(
                review_record_path=record_path,
                source_path=fixture.source,
                accepted_markdown_path=fixture.reviewed,
                markdown_audit_path=fixture.markdown_audit,
                asset_audit_path=fixture.asset_audit,
            )

        self.assertEqual(record_hash, expected_hash)

    def test_accepted_review_binds_hashes_decisions_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))

            report = fixture.finalize()
            source_hash = _sha_file(fixture.source)
            candidate_hash = _sha_file(fixture.candidate)
            reviewed_hash = _sha_file(fixture.reviewed)

            self.assertEqual(report["schema"], CANONICAL_REVIEW_SCHEMA)
            self.assertEqual(report["status"], "accepted")
            self.assertTrue(report["ok"])
            self.assertEqual(report["source"]["sha256"], source_hash)
            self.assertEqual(report["markdown"]["candidate"]["sha256"], candidate_hash)
            self.assertEqual(report["markdown"]["accepted"]["sha256"], reviewed_hash)
            self.assertEqual(report["source_coverage"]["uncovered_unit_count"], 0)
            self.assertEqual(report["summary"]["converted_to_markdown_count"], 1)
            self.assertEqual(report["selected_assets"][0]["path"], "images/figure.png")
            self.assertEqual(report["summary"]["unresolved_item_count"], 0)

    def test_explicit_unresolved_item_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_inputs(
                unresolved_items=[
                    {
                        "code": "ambiguous_unit",
                        "source_reference": "page:1",
                        "reason": "The visible unit is ambiguous.",
                    }
                ]
            )

            report = fixture.finalize()

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["unresolved_item_count"], 1)

    def test_missing_source_needs_source_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))

            report = fixture.finalize(source=None)

        self.assertEqual(report["status"], "needs_source_verification")
        self.assertFalse(report["ok"])
        self.assertIn("source_not_available", {item["code"] for item in report["findings"]})

    def test_incomplete_source_coverage_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_inputs(
                coverage_status="incomplete",
                uncovered_units=["page:2"],
            )

            report = fixture.finalize()

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["source_coverage"]["uncovered_unit_count"], 1)
        self.assertIn("incomplete_source_coverage", {item["code"] for item in report["findings"]})

    def test_missing_selected_asset_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.asset.unlink()

            report = fixture.finalize()

        self.assertEqual(report["status"], "blocked")
        self.assertIn("missing_selected_asset", {item["code"] for item in report["findings"]})

    def test_stale_markdown_audit_hash_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.reviewed.write_text(
                fixture.reviewed.read_text(encoding="utf-8") + "\nChanged after audit.\n",
                encoding="utf-8",
            )

            report = fixture.finalize()

        self.assertEqual(report["status"], "blocked")
        self.assertIn("stale_markdown_audit", {item["code"] for item in report["findings"]})

    def test_unreviewed_html_table_blocks_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.reviewed.write_bytes(fixture.candidate.read_bytes())
            fixture.write_inputs(decisions=[])

            report = fixture.finalize()

        self.assertEqual(report["status"], "blocked")
        self.assertIn("unreviewed_html_table", {item["code"] for item in report["findings"]})

    def test_explicit_retained_html_exception_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.reviewed.write_bytes(fixture.candidate.read_bytes())
            html_hash = _sha_text(fixture.candidate_table)
            fixture.write_inputs(
                decisions=[
                    {
                        "table_id": "table-001",
                        "action": "retained_html_by_exception",
                        "source_reference": "page:1 visual table",
                        "before_sha256": html_hash,
                        "after_sha256": html_hash,
                        "reason": "Merged visual headers cannot be represented faithfully in Markdown.",
                    }
                ]
            )

            report = fixture.finalize()

        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["summary"]["retained_html_by_exception_count"], 1)
        self.assertNotIn("unreviewed_html_table", {item["code"] for item in report["findings"]})

    def test_asset_identity_rewrites_only_new_accepted_output_and_remains_build_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_asset_identities()
            reviewed_before = fixture.reviewed.read_bytes()
            asset_before = fixture.asset.read_bytes()

            record = fixture.finalize_with_asset_identities()
            output = fixture.root / "accepted-output"
            record_path = materialize_canonical_review_output(
                record,
                reviewed_markdown_path=fixture.reviewed,
                asset_root=fixture.review_root,
                output_root=output,
            )
            accepted_markdown = output / "document.md"
            accepted_asset = output / "images" / "verified-system-diagram.png"
            record_hash = validate_canonical_review_build_binding(
                review_record_path=record_path,
                source_path=fixture.source,
                accepted_markdown_path=accepted_markdown,
                markdown_audit_path=fixture.markdown_audit,
                asset_audit_path=fixture.asset_audit,
            )
            accepted_text = accepted_markdown.read_text(encoding="utf-8")

            self.assertEqual(record["status"], "accepted")
            self.assertEqual(record["markdown"]["reviewed"]["sha256"], _sha_bytes(reviewed_before))
            self.assertEqual(record["markdown"]["accepted"]["sha256"], _sha_file(accepted_markdown))
            self.assertIn("images/verified-system-diagram.png", accepted_text)
            self.assertNotIn("images/figure.png", accepted_text)
            self.assertEqual(accepted_asset.read_bytes(), asset_before)
            self.assertEqual(fixture.reviewed.read_bytes(), reviewed_before)
            self.assertEqual(fixture.asset.read_bytes(), asset_before)
            self.assertEqual(record["selected_assets"][0]["ingestion_intent"], "context_bound")
            self.assertEqual(record_hash, _sha_file(record_path))

    def test_asset_identity_rejects_unsafe_canonical_name_and_stale_context(self) -> None:
        cases = (
            ("../escaped.png", None, "unsafe_asset_canonical_name"),
            ("safe-name.png", "f" * 64, "stale_asset_context_hash"),
        )
        for canonical_name, context_sha256, expected_code in cases:
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as tmp:
                fixture = CanonicalReviewFixture(Path(tmp))
                fixture.write_asset_identities(
                    canonical_name=canonical_name,
                    context_sha256=context_sha256,
                )

                report = fixture.finalize_with_asset_identities()

            self.assertEqual(report["status"], "blocked")
            self.assertIn(expected_code, {item["code"] for item in report["findings"]})

    def test_asset_identity_record_requires_complete_nonblank_semantic_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_asset_identities()
            record = fixture.finalize_with_asset_identities()

            record["selected_assets"][0]["source_reference"] = ""
            with self.assertRaisesRegex(RuntimeError, "source reference is missing"):
                validate_canonical_review_record(record)

            del record["selected_assets"][0]["source_reference"]
            with self.assertRaisesRegex(RuntimeError, "semantic identity is incomplete"):
                validate_canonical_review_record(record)


class CanonicalReviewCliTests(unittest.TestCase):
    def test_cli_materializes_accepted_outputs_without_changing_original_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_asset_identities()
            payload = json.loads(fixture.decisions.read_text(encoding="utf-8"))
            payload["decisions"][0]["reason"] = str(Path.home() / "private" / "review-note")
            fixture.decisions.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            output = fixture.root / "accepted-output"
            redaction = output / "canonical_review.redaction.json"
            candidate_before = fixture.candidate.read_bytes()
            manifest_before = fixture.manifest.read_bytes()
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = FINALIZE_CLI.main(
                    [
                        "--source",
                        str(fixture.source),
                        "--candidate-markdown",
                        str(fixture.candidate),
                        "--reviewed-markdown",
                        str(fixture.reviewed),
                        "--markdown-audit",
                        str(fixture.markdown_audit),
                        "--asset-audit",
                        str(fixture.asset_audit),
                        "--source-coverage",
                        str(fixture.coverage),
                        "--table-decisions",
                        str(fixture.decisions),
                        "--asset-identities",
                        str(fixture.asset_identities),
                        "--asset-root",
                        str(fixture.review_root),
                        "--output",
                        str(output),
                        "--redaction-report",
                        str(redaction),
                        "--json",
                    ]
                )

            record = json.loads((output / "ragflow_canonical_review.json").read_text(encoding="utf-8"))
            sidecar = json.loads(redaction.read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "accepted")
            self.assertEqual(fixture.candidate.read_bytes(), candidate_before)
            self.assertEqual(fixture.manifest.read_bytes(), manifest_before)
            self.assertIn(
                "images/verified-system-diagram.png",
                (output / "document.md").read_text(encoding="utf-8"),
            )
            self.assertEqual((output / "images" / "verified-system-diagram.png").read_bytes(), b"reviewed figure bytes")
            self.assertNotIn(str(Path.home()), json.dumps(record))
            self.assertGreater(sidecar["summary"]["redaction_count"], 0)

    def test_cli_writes_blocked_record_without_materializing_accepted_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalReviewFixture(Path(tmp))
            fixture.write_inputs(decisions=[])
            output = fixture.root / "blocked-output"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = FINALIZE_CLI.main(
                    [
                        "--source",
                        str(fixture.source),
                        "--candidate-markdown",
                        str(fixture.candidate),
                        "--reviewed-markdown",
                        str(fixture.reviewed),
                        "--markdown-audit",
                        str(fixture.markdown_audit),
                        "--asset-audit",
                        str(fixture.asset_audit),
                        "--source-coverage",
                        str(fixture.coverage),
                        "--table-decisions",
                        str(fixture.decisions),
                        "--asset-root",
                        str(fixture.review_root),
                        "--output",
                        str(output),
                        "--json",
                    ]
                )
            record = json.loads((output / "ragflow_canonical_review.json").read_text(encoding="utf-8"))

            self.assertEqual(code, 1)
            self.assertEqual(record["status"], "blocked")
            self.assertFalse((output / "document.md").exists())
            self.assertFalse((output / "images" / "figure.png").exists())


if __name__ == "__main__":
    unittest.main()
