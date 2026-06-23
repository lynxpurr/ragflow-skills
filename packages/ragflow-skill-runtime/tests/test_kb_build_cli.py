from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
APPEND_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "append.py"
BUILD_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "build.py"
CLEANUP_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "cleanup.py"
DIAGNOSE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "diagnose.py"
INSPECT_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "inspect_kb.py"
PROBE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "probe.py"
VALIDATE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "validate.py"
PROFILE_PATH = ROOT / "skills" / "ragflow-kb-build" / "templates" / "default-en-768.json"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["RAGFLOW_SKILL_RUNTIME_PATH"] = str(RUNTIME_SRC)
    return env


def load_validate_module():
    spec = importlib.util.spec_from_file_location("ragflow_kb_validate_cli", VALIDATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeValidationClient:
    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=3):
        return {
            "data": {
                "chunks": [
                    {
                        "content_with_weight": f"{question} includes known term",
                        "docnm_kwd": "source.md",
                        "similarity": 0.91,
                    }
                ]
            }
        }


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

    def test_build_blocks_doc_manifest_with_blocked_quality_gate(self) -> None:
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
                        "quality_gate": {"status": "BLOCKED"},
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

            blocked = subprocess.run(
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
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            allowed = subprocess.run(
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
                    "--allow-blocked",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        self.assertIn("quality gate is BLOCKED", json.loads(blocked.stdout)["error"])
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertTrue(json.loads(allowed.stdout)["ok"])

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

    def test_diagnose_manifest_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            report_md = root / "diagnostic.md"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "short", "name": "kb:test(1)"},
                        "documents": [{"document_id": "doc-1", "status": "running", "chunk_count": 0}],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(DIAGNOSE_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("dataset_id_short", {issue["issue_type"] for issue in payload["issues"]})
        self.assertIn("RAGFlow Diagnostic Report", report_text)

    def test_append_dry_run_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "append"
            input_dir.mkdir()
            (input_dir / "a.md").write_text("# A\n", encoding="utf-8")
            (input_dir / "b.md").write_text("# B\n", encoding="utf-8")
            manifest = root / "kb_manifest.json"
            output = root / "append_plan.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": "kb:test"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            file_payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["planned_upload_count"], 2)
        self.assertEqual(file_payload["schema"], "ragflow_append_plan_v1")

    def test_append_blocks_doc_manifest_with_blocked_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs_dir = handoff / "documents"
            docs_dir.mkdir(parents=True)
            (docs_dir / "sample.md").write_text("# Sample\n", encoding="utf-8")
            doc_manifest = handoff / "doc_manifest.json"
            doc_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_gate": {"status": "BLOCKED"},
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
            kb_manifest = root / "kb_manifest.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": "kb:test"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--kb-manifest",
                    str(kb_manifest),
                    "--doc-manifest",
                    str(doc_manifest),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("quality gate is BLOCKED", json.loads(result.stdout)["error"])

    def test_append_help_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(APPEND_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Append Markdown documents", result.stdout)
        self.assertIn("--execute", result.stdout)

    def test_cleanup_preview_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            output = root / "cleanup_plan.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": "kb:disposable"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--output",
                    str(output),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            file_payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["schema"], "ragflow_cleanup_plan_v1")
        self.assertEqual(file_payload["required_confirmation"]["confirm_dataset_id"], "0123456789abcdef")

    def test_cleanup_execute_requires_confirmation_before_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": "kb:disposable"},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--execute",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("confirm-dataset-id", json.loads(result.stdout)["error"])

    def test_cleanup_help_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLEANUP_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preview or execute cleanup", result.stdout)
        self.assertIn("--confirm-dataset-id", result.stdout)

    def test_probe_help_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROBE_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Probe RAGFlow API compatibility", result.stdout)

    def test_validate_regression_requires_queries_without_network(self) -> None:
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
        self.assertIn("requires --queries", payload["error"])

    def test_validate_regression_with_query_set_via_fake_client(self) -> None:
        module = load_validate_module()
        module.RAGFlowClient = FakeValidationClient
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
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
            queries = root / "queries.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "Known",
                                "expected_terms": ["known term"],
                                "expected_documents": ["source.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report_md = root / "report.md"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "--kb-manifest",
                        str(manifest),
                        "--level",
                        "regression",
                        "--queries",
                        str(queries),
                        "--base-url",
                        "https://ragflow.example.test",
                        "--report-md",
                        str(report_md),
                    ]
                )
            report_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["metrics"]["pass_rate"], 1.0)
        self.assertIn("q1", report_text)

    def test_validate_benchmark_with_qrels_and_gate_via_fake_client(self) -> None:
        module = load_validate_module()
        module.RAGFlowClient = FakeValidationClient
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
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
            queries = root / "queries.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "Known",
                                "expected_terms": ["known term"],
                                "expected_documents": ["source.md"],
                                "metadata": {"type": "fact"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels = root / "qrels.json"
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            gate = root / "gate.json"
            gate.write_text(
                json.dumps({"thresholds": {"min_hit_rate": 1.0, "min_mrr": 1.0}}),
                encoding="utf-8",
            )
            baseline = root / "baseline.json"
            baseline.write_text(
                json.dumps({"benchmark": {"metrics": {"mrr": 0.5, "hit_rate": 1.0}}}),
                encoding="utf-8",
            )
            report_md = root / "benchmark.md"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "--kb-manifest",
                        str(manifest),
                        "--level",
                        "benchmark",
                        "--queries",
                        str(queries),
                        "--qrels",
                        str(qrels),
                        "--gate-config",
                        str(gate),
                        "--baseline-report",
                        str(baseline),
                        "--base-url",
                        "https://ragflow.example.test",
                        "--report-md",
                        str(report_md),
                    ]
                )
            report_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["benchmark"]["metrics"]["hit_rate"], 1.0)
        self.assertEqual(payload["benchmark"]["query_type_breakdown"]["fact"]["query_count"], 1)
        self.assertTrue(payload["benchmark"]["gate"]["ok"])
        self.assertEqual(payload["benchmark"]["baseline"]["delta"]["mrr"], 0.5)
        self.assertIn("## Benchmark", report_text)


if __name__ == "__main__":
    unittest.main()
