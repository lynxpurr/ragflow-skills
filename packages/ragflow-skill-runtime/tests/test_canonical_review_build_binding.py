from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BUILD_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "build.py"
PROFILE_PATH = ROOT / "skills" / "ragflow-kb-build" / "templates" / "default-en-768.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_build_module():
    spec = importlib.util.spec_from_file_location("ragflow_canonical_kb_build_cli", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCanonicalBuildClient:
    instances: list["FakeCanonicalBuildClient"] = []

    def __init__(self, config):
        self.config = config
        self.created: list[tuple[str, dict[str, object]]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.uploaded: list[tuple[str, str]] = []
        FakeCanonicalBuildClient.instances.append(self)

    def create_dataset(self, name, *, profile=None):
        self.created.append((str(name), dict(profile or {})))
        return {"data": {"id": "dataset-canonical"}}

    def update_dataset(self, dataset_id, updates):
        self.updated.append((str(dataset_id), dict(updates)))
        return {"data": {"id": str(dataset_id)}}

    def upload_document(self, dataset_id, file_path):
        self.uploaded.append((str(dataset_id), str(file_path)))
        return {"data": [{"id": "document-canonical"}]}


class CanonicalBuildFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "source.pdf"
        self.handoff_documents = root / "handoff" / "documents"
        self.markdown = self.handoff_documents / "document.md"
        self.asset = self.handoff_documents / "images" / "figure.png"
        self.markdown_audit = root / "markdown-audit.json"
        self.asset_audit = root / "asset-audit.json"
        self.review = root / "ragflow_canonical_review.json"
        self.checkpoint = root / "kb-build.checkpoint.json"
        self.manifest = root / "kb_manifest.json"
        self.source.write_bytes(b"exact source bytes")
        self.asset.parent.mkdir(parents=True)
        self.markdown.write_text(
            "# Accepted\n\nVerified content.\n\n![Figure](images/figure.png)\n",
            encoding="utf-8",
        )
        self.asset.write_bytes(b"selected image bytes")
        self._write_evidence()

    def _write_evidence(self) -> None:
        source_hash = _sha256(self.source)
        markdown_hash = _sha256(self.markdown)
        asset_hash = _sha256(self.asset)
        self.markdown_audit.write_text(
            json.dumps(
                {
                    "schema": "ragflow_canonical_markdown_audit_v1",
                    "markdown": {"sha256": markdown_hash},
                    "source": {"sha256": source_hash},
                    "summary": {"error": 0},
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
                    "summary": {"missing_reference_count": 0},
                    "images": [{"path": "images/figure.png", "sha256": asset_hash}],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        record = {
            "schema": "ragflow_canonical_review_v1",
            "created_at": "2026-08-14T00:00:00Z",
            "status": "accepted",
            "ok": True,
            "source": {
                "available": True,
                "name": self.source.name,
                "sha256": source_hash,
            },
            "markdown": {
                "candidate": {"name": "candidate.md", "sha256": "1" * 64},
                "accepted": {"path": "document.md", "sha256": markdown_hash},
            },
            "source_coverage": {
                "status": "complete",
                "source_sha256": source_hash,
                "covered_unit_count": 1,
                "uncovered_unit_count": 0,
                "covered_units": ["page:1"],
                "uncovered_units": [],
                "record_sha256": "2" * 64,
            },
            "audit_reports": {
                "markdown_structure": {
                    "schema": "ragflow_canonical_markdown_audit_v1",
                    "report_sha256": _sha256(self.markdown_audit),
                },
                "canonical_assets": {
                    "schema": "ragflow_canonical_asset_audit_v1",
                    "report_sha256": _sha256(self.asset_audit),
                },
            },
            "table_review": {
                "record_sha256": "3" * 64,
                "decisions": [],
                "unresolved_items": [],
            },
            "selected_assets": [
                {"path": "images/figure.png", "sha256": asset_hash}
            ],
            "summary": {
                "table_decision_count": 0,
                "converted_to_markdown_count": 0,
                "retained_html_by_exception_count": 0,
                "selected_asset_count": 1,
                "unresolved_item_count": 0,
                "finding_count": 0,
            },
            "findings": [],
            "safety": {
                "candidate_markdown_modified": False,
                "original_handoff_modified": False,
                "network_put_performed": False,
                "script_owned_llm_calls": 0,
            },
        }
        self.review.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def record(self) -> dict[str, object]:
        return json.loads(self.review.read_text(encoding="utf-8"))

    def write_record(self, payload: dict[str, object]) -> None:
        self.review.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def build_args(self, *, review: Path | None = None, dry_run: bool = False) -> list[str]:
        args = [
            "--input",
            str(self.handoff_documents),
            "--kb-name",
            "kb:canonical-test",
            "--profile",
            str(PROFILE_PATH),
            "--canonical-review",
            str(review or self.review),
            "--canonical-source",
            str(self.source),
            "--canonical-markdown-audit",
            str(self.markdown_audit),
            "--canonical-asset-audit",
            str(self.asset_audit),
            "--json",
        ]
        if dry_run:
            args.append("--dry-run")
        else:
            args.extend(
                [
                    "--base-url",
                    "https://ragflow.example.test",
                    "--api-key",
                    "test-key",
                    "--output",
                    str(self.manifest),
                    "--checkpoint",
                    str(self.checkpoint),
                    "--no-parse",
                ]
            )
        return args


class CanonicalReviewBuildBindingTests(unittest.TestCase):
    def _run(self, fixture: CanonicalBuildFixture, args: list[str]) -> tuple[int, dict[str, object]]:
        module = _load_build_module()
        FakeCanonicalBuildClient.instances = []
        module.RAGFlowClient = FakeCanonicalBuildClient
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = module.main(args)
        return code, json.loads(stdout.getvalue())

    def test_missing_review_fails_before_client_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalBuildFixture(Path(tmp))
            code, payload = self._run(
                fixture,
                fixture.build_args(review=fixture.root / "missing-review.json"),
            )

        self.assertEqual(code, 2)
        self.assertIn("canonical review not found", str(payload["error"]))
        self.assertEqual(FakeCanonicalBuildClient.instances, [])

    def test_wrong_schema_fails_before_client_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalBuildFixture(Path(tmp))
            record = fixture.record()
            record["schema"] = "ragflow_canonical_review_v0"
            fixture.write_record(record)

            code, payload = self._run(fixture, fixture.build_args())

        self.assertEqual(code, 2)
        self.assertIn("canonical review schema", str(payload["error"]))
        self.assertEqual(FakeCanonicalBuildClient.instances, [])

    def test_blocked_and_source_unverified_records_fail_before_client_creation(self) -> None:
        for status in ("blocked", "needs_source_verification"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                fixture = CanonicalBuildFixture(Path(tmp))
                record = fixture.record()
                record["status"] = status
                record["ok"] = False
                fixture.write_record(record)

                code, payload = self._run(fixture, fixture.build_args())

                self.assertEqual(code, 2)
                self.assertIn("must be accepted", str(payload["error"]))
                self.assertEqual(FakeCanonicalBuildClient.instances, [])

    def test_unresolved_record_fails_before_client_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalBuildFixture(Path(tmp))
            record = fixture.record()
            record["summary"]["unresolved_item_count"] = 1
            record["table_review"]["unresolved_items"] = [{"reason": "ambiguous table"}]
            fixture.write_record(record)

            code, payload = self._run(fixture, fixture.build_args())

        self.assertEqual(code, 2)
        self.assertIn("unresolved", str(payload["error"]))
        self.assertEqual(FakeCanonicalBuildClient.instances, [])

    def test_stale_evidence_fails_before_client_creation(self) -> None:
        mutations = {
            "source": lambda item: item.source.write_bytes(b"changed source bytes"),
            "markdown": lambda item: item.markdown.write_text("# Changed\n", encoding="utf-8"),
            "markdown_audit": lambda item: item.markdown_audit.write_text(
                item.markdown_audit.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            ),
            "asset_audit": lambda item: item.asset_audit.write_text(
                item.asset_audit.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            ),
            "selected_asset": lambda item: item.asset.write_bytes(b"changed image bytes"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                fixture = CanonicalBuildFixture(Path(tmp))
                mutate(fixture)

                code, payload = self._run(fixture, fixture.build_args())

                self.assertEqual(code, 2)
                self.assertIn("hash", str(payload["error"]))
                self.assertEqual(FakeCanonicalBuildClient.instances, [])

    def test_accepted_review_validates_dry_run_and_binds_live_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalBuildFixture(Path(tmp))
            expected_review_hash = _sha256(fixture.review)

            dry_code, dry_payload = self._run(fixture, fixture.build_args(dry_run=True))
            self.assertEqual(FakeCanonicalBuildClient.instances, [])

            live_code, live_payload = self._run(fixture, fixture.build_args())
            checkpoint = json.loads(fixture.checkpoint.read_text(encoding="utf-8"))
            manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))

        self.assertEqual(dry_code, 0, dry_payload)
        self.assertEqual(dry_payload["canonical_review_sha256"], expected_review_hash)
        self.assertEqual(live_code, 0, live_payload)
        self.assertEqual(len(FakeCanonicalBuildClient.instances), 1)
        self.assertEqual(
            checkpoint["bindings"]["canonical_review_sha256"],
            expected_review_hash,
        )
        self.assertEqual(manifest["canonical_review_sha256"], expected_review_hash)
        self.assertNotIn("canonical_review", manifest)
        self.assertNotIn("canonical_review_path", checkpoint["bindings"])

    def test_generic_dry_run_remains_compatible_without_canonical_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CanonicalBuildFixture(Path(tmp))
            args = [
                "--input",
                str(fixture.handoff_documents),
                "--kb-name",
                "kb:generic-test",
                "--profile",
                str(PROFILE_PATH),
                "--dry-run",
                "--json",
            ]

            code, payload = self._run(fixture, args)

        self.assertEqual(code, 0, payload)
        self.assertNotIn("canonical_review_sha256", payload)
        self.assertEqual(FakeCanonicalBuildClient.instances, [])


if __name__ == "__main__":
    unittest.main()
