from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
APPEND_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "append.py"
BUILD_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "build.py"
CLEANUP_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "cleanup.py"
DIAGNOSE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "diagnose.py"
INSPECT_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "inspect_kb.py"
PROBE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "probe.py"
PROFILE_SCRIPT = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "profile.py"
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


class FakePartialValidationClient(FakeValidationClient):
    def retrieve(self, *, question, dataset_ids, top_k=3):
        if "Timeout" in question:
            raise TimeoutError("timed out retrieving chunks")
        return super().retrieve(question=question, dataset_ids=dataset_ids, top_k=top_k)


class ModelProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/llm/factories":
            payload = {
                "data": {
                    "factories": [
                        {
                            "id": "builtin",
                            "display_name": "Built In",
                            "models": [
                                {"name": "bge-m3", "type": "embedding"},
                                {"name": "bge-reranker", "type": "rerank"},
                            ],
                        }
                    ]
                }
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/embeddings":
            body = json.dumps({"error": {"message": "empty input rejected"}}).encode("utf-8")
            self.send_response(422)
        elif self.path == "/rerank":
            body = json.dumps({"results": []}).encode("utf-8")
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def model_provider_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class DiagnosticProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/v1/datasets"):
            body = json.dumps({"data": {"datasets": [{"id": "short", "name": "kb:diagnostic"}]}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/api/v1/retrieval":
            body = json.dumps(
                {
                    "data": {
                        "chunks": [
                            {
                                "content_with_weight": "Known includes known term",
                                "docnm_kwd": "source-token=diagnostic-secret.md",
                                "similarity": 0.91,
                            }
                        ]
                    }
                }
            ).encode("utf-8")
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def diagnostic_probe_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), DiagnosticProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class InspectKbLiveHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/v1/datasets/ds-live/documents"):
            body = json.dumps(
                {
                    "data": {
                        "documents": [
                            {"id": "doc-ok", "status": "1", "chunk_count": 3},
                            {"id": "doc-fail", "status": "failed", "progress_msg": "parse failed"},
                            {"id": "doc-pending", "status": "running", "progress": 0.5},
                        ]
                    }
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def inspect_kb_live_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), InspectKbLiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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

    def test_model_providers_probe_via_subprocess_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, model_provider_server() as base_url:
            root = Path(tmp)
            report_json = root / "model_providers.json"
            report_md = root / "model_providers.md"
            redaction_json = root / "model_provider_redaction.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "model-providers",
                    "probe",
                    "--base-url",
                    base_url,
                    "--api-key",
                    "test-key",
                    "--embedding-model",
                    "bge-m3",
                    "--rerank-model",
                    "bge-reranker",
                    "--embedding-adapter-url",
                    f"{base_url}/embeddings",
                    "--rerank-adapter-url",
                    f"{base_url}/rerank",
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report_payload = json.loads(report_json.read_text(encoding="utf-8"))
            redaction_payload = json.loads(redaction_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], "ragflow_model_provider_probe_report_v1")
        self.assertEqual(payload["summary"]["available_endpoint_count"], 1)
        self.assertEqual(payload["summary"]["embedding_model_count"], 1)
        self.assertEqual(payload["summary"]["rerank_model_count"], 1)
        self.assertEqual(payload["summary"]["configured_adapter_count"], 2)
        self.assertEqual(payload["summary"]["handled_empty_input_adapter_count"], 2)
        self.assertEqual(payload["summary"]["runtime_partial_failure_status"], "partial")
        self.assertEqual(payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["success_count"], 3)
        self.assertGreaterEqual(payload["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertTrue(all(check["found"] for check in payload["expected_model_checks"]))
        self.assertEqual(report_payload["summary"]["provider_count"], 1)
        self.assertEqual(report_payload["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["target_counts"]["explicit_secrets"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["private_hosts"], 1)
        self.assertIn("RAGFlow Model Provider Probe", markdown)
        self.assertIn("runtime_partial_failure_status: `partial`", markdown)

    def test_inspect_handoff_via_build_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            docs_dir = handoff / "documents"
            docs_dir.mkdir(parents=True)
            (docs_dir / "sample.md").write_text("# Sample\n\nBody\n", encoding="utf-8")
            (handoff / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "quality_report": "quality_report.json",
                        "documents": [{"source_path": "sample.md", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            (handoff / "metadata.json").write_text(json.dumps({"schema": "ragflow_document_metadata_v1"}), encoding="utf-8")
            (handoff / "artifact_index.json").write_text(
                json.dumps({"schema": "ragflow_artifact_index_v1", "artifact_count": 0}),
                encoding="utf-8",
            )
            (handoff / "retrieval_hints.json").write_text(
                json.dumps({"schema": "ragflow_retrieval_hints_v1", "section_boundaries": [{"title": "Sample"}]}),
                encoding="utf-8",
            )
            (handoff / "assistant_profile.json").write_text(
                json.dumps({"schema": "ragflow_assistant_profile_v1", "profile_id": "handoff-review-default"}),
                encoding="utf-8",
            )
            (handoff / "assistant_test_plan.json").write_text(
                json.dumps({"schema": "ragflow_assistant_test_plan_v1", "test_count": 1, "cases": []}),
                encoding="utf-8",
            )
            report_md = Path(tmp) / "handoff_inspection.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "inspect-handoff",
                    "--handoff",
                    str(handoff),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["handoff"]["document_count"], 1)
        self.assertTrue(payload["handoff"]["sidecars"]["metadata"]["exists"])
        self.assertEqual(payload["handoff"]["retrieval_hint_count"], 1)
        self.assertEqual(payload["handoff"]["assistant_test_count"], 1)
        self.assertIn("RAGFlow Handoff Inspection", report_md_text)

    def test_metadata_governance_subcommands_via_build_script(self) -> None:
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
                        "documents": [
                            {
                                "source_path": "source/sample.pdf",
                                "markdown_path": "documents/sample.md",
                                "title": "Sample",
                                "sha256": "1" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            handoff_metadata = handoff / "metadata.json"
            handoff_metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_document_metadata_v1",
                        "documents": [
                            {
                                "markdown": {"path": "documents/sample.md"},
                                "title": "Handoff Sample",
                                "locale": "en",
                                "source_sha256": "2" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            template = root / "metadata.template.json"
            merged = root / "metadata.merged.json"
            lint_md = root / "metadata_lint.md"
            merge_md = root / "metadata_merge.md"

            generate_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "metadata",
                    "generate-template",
                    "--doc-manifest",
                    str(doc_manifest),
                    "--output",
                    str(template),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "metadata",
                    "lint",
                    "--metadata",
                    str(template),
                    "--report-md",
                    str(lint_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            merge_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "metadata",
                    "merge",
                    "--doc-manifest",
                    str(doc_manifest),
                    "--handoff-metadata",
                    str(handoff_metadata),
                    "--metadata",
                    str(template),
                    "--output",
                    str(merged),
                    "--report-md",
                    str(merge_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            build_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "--doc-manifest",
                    str(doc_manifest),
                    "--metadata",
                    str(merged),
                    "--kb-name",
                    "kb:test",
                    "--profile",
                    str(PROFILE_PATH),
                    "--dry-run",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            merged_payload = json.loads(merged.read_text(encoding="utf-8"))
            template_exists = template.exists()
            lint_md_text = lint_md.read_text(encoding="utf-8") if lint_md.exists() else ""
            merge_md_text = merge_md.read_text(encoding="utf-8") if merge_md.exists() else ""
            build_payload = json.loads(build_result.stdout) if build_result.stdout else {}

        self.assertEqual(generate_result.returncode, 0, generate_result.stderr)
        self.assertTrue(template_exists)
        self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
        self.assertIn("RAGFlow Metadata Lint Report", lint_md_text)
        self.assertEqual(merge_result.returncode, 0, merge_result.stdout)
        self.assertIn("RAGFlow Metadata Merge Report", merge_md_text)
        self.assertEqual(merged_payload["schema"], "ragflow_metadata_v1")
        self.assertEqual(build_result.returncode, 0, build_result.stdout)
        self.assertTrue(build_payload["metadata_summary"]["ok"])

    def test_tagset_governance_subcommands_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tagset = root / "tagset.json"
            lint_md = root / "tagset_lint.md"
            report_md = root / "tagset_report.md"
            export_csv = root / "tagset.csv"

            generate_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "generate-template",
                    "--output",
                    str(tagset),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "lint",
                    "--tagset",
                    str(tagset),
                    "--report-md",
                    str(lint_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            export_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "export",
                    "--tagset",
                    str(tagset),
                    "--format",
                    "csv",
                    "--output",
                    str(export_csv),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "report",
                    "--tagset",
                    str(tagset),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            lint_md_text = lint_md.read_text(encoding="utf-8") if lint_md.exists() else ""
            export_csv_text = export_csv.read_text(encoding="utf-8") if export_csv.exists() else ""
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(generate_result.returncode, 0, generate_result.stderr)
        self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
        self.assertIn("RAGFlow Tagset Lint Report", lint_md_text)
        self.assertEqual(export_result.returncode, 0, export_result.stdout)
        self.assertIn("example-tag", export_csv_text)
        self.assertEqual(report_result.returncode, 0, report_result.stdout)
        self.assertIn("RAGFlow Tagset Report", report_md_text)

    def test_metadata_governance_writes_redaction_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / "metadata.local-token=metadata-secret.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": "documents/metadata.local-token=metadata-secret.md",
                                "metadata": {"topic": "Metadata redaction"},
                                "tags": ["example-tag"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            lint_json = root / "metadata_lint.json"
            lint_md = root / "metadata_lint.md"
            lint_redaction = root / "metadata_lint_redaction.json"
            merged = root / "metadata_merged.json"
            merge_json = root / "metadata_merge.json"
            merge_md = root / "metadata_merge.md"
            merge_redaction = root / "metadata_merge_redaction.json"

            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "metadata",
                    "lint",
                    "--metadata",
                    str(metadata),
                    "--report-json",
                    str(lint_json),
                    "--report-md",
                    str(lint_md),
                    "--redaction-report",
                    str(lint_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            merge_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "metadata",
                    "merge",
                    "--metadata",
                    str(metadata),
                    "--output",
                    str(merged),
                    "--no-derive-from-path",
                    "--report-json",
                    str(merge_json),
                    "--report-md",
                    str(merge_md),
                    "--redaction-report",
                    str(merge_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            combined = "\n".join(
                [
                    lint_result.stdout,
                    merge_result.stdout,
                    lint_json.read_text(encoding="utf-8"),
                    lint_md.read_text(encoding="utf-8"),
                    lint_redaction.read_text(encoding="utf-8"),
                    merge_json.read_text(encoding="utf-8"),
                    merge_md.read_text(encoding="utf-8"),
                    merge_redaction.read_text(encoding="utf-8"),
                ]
            )
            lint_redaction_payload = json.loads(lint_redaction.read_text(encoding="utf-8"))
            merge_redaction_payload = json.loads(merge_redaction.read_text(encoding="utf-8"))
            merged_text = merged.read_text(encoding="utf-8")

        self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
        self.assertEqual(merge_result.returncode, 0, merge_result.stdout)
        self.assertEqual(lint_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertEqual(merge_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(lint_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertGreaterEqual(merge_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertNotIn("metadata-secret", combined)
        self.assertIn("[REDACTED]", combined)
        self.assertIn("metadata-secret", merged_text)

    def test_tagset_governance_writes_redaction_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tagset = root / "tagset.local-token=tagset-secret.json"
            tagset.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_tagset_v1",
                        "tags": [{"name": "example-tag", "label": "Example"}],
                        "assignments": [
                            {
                                "path": "documents/tagset.local-token=tagset-secret.md",
                                "tags": ["example-tag"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            lint_json = root / "tagset_lint.json"
            lint_md = root / "tagset_lint.md"
            lint_redaction = root / "tagset_lint_redaction.json"
            report_json = root / "tagset_report.json"
            report_md = root / "tagset_report.md"
            report_redaction = root / "tagset_report_redaction.json"

            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "lint",
                    "--tagset",
                    str(tagset),
                    "--report-json",
                    str(lint_json),
                    "--report-md",
                    str(lint_md),
                    "--redaction-report",
                    str(lint_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "tagset",
                    "report",
                    "--tagset",
                    str(tagset),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(report_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            combined = "\n".join(
                [
                    lint_result.stdout,
                    report_result.stdout,
                    lint_json.read_text(encoding="utf-8"),
                    lint_md.read_text(encoding="utf-8"),
                    lint_redaction.read_text(encoding="utf-8"),
                    report_json.read_text(encoding="utf-8"),
                    report_md.read_text(encoding="utf-8"),
                    report_redaction.read_text(encoding="utf-8"),
                ]
            )
            lint_redaction_payload = json.loads(lint_redaction.read_text(encoding="utf-8"))
            report_redaction_payload = json.loads(report_redaction.read_text(encoding="utf-8"))

        self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
        self.assertEqual(report_result.returncode, 0, report_result.stdout)
        self.assertEqual(lint_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertEqual(report_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(lint_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertGreaterEqual(report_redaction_payload["target_counts"]["config_paths"], 1)
        self.assertNotIn("tagset-secret", combined)
        self.assertIn("[REDACTED]", combined)

    def test_benchmark_governance_subcommands_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            gate = root / "gate.json"
            report = root / "benchmark_report.json"
            chunk_report = root / "chunk_report.json"
            chunk_snapshot = root / "chunk_snapshot.json"
            baseline_report = root / "baseline_report.json"
            benchmark_dir = root / "benchmark"
            benchmark_sample_dir = root / "benchmark_sample"
            snapshot_md = root / "chunk_snapshot.md"
            import_md = root / "benchmark_import.md"
            preflight_md = root / "benchmark_preflight.md"
            sample_md = root / "benchmark_sample.md"
            summary_md = root / "benchmark_summary.md"
            gate_md = root / "benchmark_gate.md"
            trend_md = root / "benchmark_trend.md"
            delta_md = root / "benchmark_delta.md"
            suggest_md = root / "benchmark_suggest.md"
            queries.write_text(
                json.dumps({"queries": [{"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}}]}),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            chunk_report.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "q1",
                                "top_chunks": [
                                    {
                                        "content": "Expected evidence body",
                                        "document_name": "source.md",
                                        "chunk_id": "chunk-a",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            gate.write_text(json.dumps({"thresholds": {"min_hit_rate": 1.0, "max_empty_result_rate": 0.0}}), encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            },
                            "query_type_breakdown": {"fact": {"query_count": 1, "hit_rate": 1.0}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            baseline_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 0.8,
                                "precision_at_k": 0.4,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.8,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            import_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "import",
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--output",
                    str(benchmark_dir),
                    "--report-md",
                    str(import_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            snapshot_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "snapshot-chunks",
                    "--input",
                    str(chunk_report),
                    "--output",
                    str(chunk_snapshot),
                    "--report-md",
                    str(snapshot_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            preflight_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "preflight",
                    "--manifest",
                    str(benchmark_dir / "manifest.json"),
                    "--chunk-snapshot",
                    str(chunk_snapshot),
                    "--gate-config",
                    str(gate),
                    "--report-md",
                    str(preflight_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            sample_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "sample",
                    "--manifest",
                    str(benchmark_dir / "manifest.json"),
                    "--output",
                    str(benchmark_sample_dir),
                    "--size",
                    "1",
                    "--seed",
                    "7",
                    "--report-md",
                    str(sample_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            summarize_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "summarize",
                    "--report",
                    str(report),
                    "--report-md",
                    str(summary_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            gate_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "gate",
                    "--report",
                    str(report),
                    "--gate-config",
                    str(gate),
                    "--report-md",
                    str(gate_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            trend_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "trend",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--gate-config",
                    str(gate),
                    "--report-md",
                    str(trend_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            delta_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "delta",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--report-md",
                    str(delta_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            suggest_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "suggest",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--gate-config",
                    str(gate),
                    "--current-top-k",
                    "3",
                    "--current-similarity-threshold",
                    "0.25",
                    "--report-md",
                    str(suggest_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            snapshot_md_text = snapshot_md.read_text(encoding="utf-8") if snapshot_md.exists() else ""
            preflight_md_text = preflight_md.read_text(encoding="utf-8") if preflight_md.exists() else ""
            sample_md_text = sample_md.read_text(encoding="utf-8") if sample_md.exists() else ""
            gate_md_text = gate_md.read_text(encoding="utf-8") if gate_md.exists() else ""
            trend_md_text = trend_md.read_text(encoding="utf-8") if trend_md.exists() else ""
            delta_md_text = delta_md.read_text(encoding="utf-8") if delta_md.exists() else ""
            suggest_md_text = suggest_md.read_text(encoding="utf-8") if suggest_md.exists() else ""

        self.assertEqual(import_result.returncode, 0, import_result.stdout)
        self.assertIn('"schema": "ragflow_benchmark_import_report_v1"', import_result.stdout)
        self.assertEqual(snapshot_result.returncode, 0, snapshot_result.stdout)
        self.assertIn("ragflow_chunk_snapshot_report_v1", snapshot_result.stdout)
        self.assertIn("RAGFlow Chunk Snapshot Report", snapshot_md_text)
        self.assertEqual(preflight_result.returncode, 0, preflight_result.stdout)
        self.assertIn("RAGFlow Benchmark Preflight Report", preflight_md_text)
        self.assertEqual(sample_result.returncode, 0, sample_result.stdout)
        self.assertIn("ragflow_benchmark_sample_report_v1", sample_result.stdout)
        self.assertIn("RAGFlow Benchmark Sample Report", sample_md_text)
        self.assertEqual(summarize_result.returncode, 0, summarize_result.stdout)
        self.assertIn("ragflow_benchmark_summary_report_v1", summarize_result.stdout)
        self.assertEqual(gate_result.returncode, 0, gate_result.stdout)
        self.assertIn("RAGFlow Benchmark Gate Report", gate_md_text)
        self.assertEqual(trend_result.returncode, 0, trend_result.stdout)
        self.assertIn("ragflow_benchmark_trend_report_v1", trend_result.stdout)
        self.assertIn("RAGFlow Benchmark Trend Report", trend_md_text)
        self.assertEqual(delta_result.returncode, 0, delta_result.stdout)
        self.assertIn("ragflow_benchmark_delta_report_v1", delta_result.stdout)
        self.assertIn("RAGFlow Benchmark Delta Report", delta_md_text)
        self.assertEqual(suggest_result.returncode, 0, suggest_result.stdout)
        self.assertIn("ragflow_benchmark_retrieval_suggestion_report_v1", suggest_result.stdout)
        self.assertIn("RAGFlow Benchmark Retrieval Suggestions", suggest_md_text)

    def test_benchmark_import_checkpoint_resume_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            benchmark_dir = root / "benchmark"
            checkpoint = root / "benchmark-import.checkpoint.json"
            first_report = root / "first_import.json"
            second_report = root / "second_import.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}},
                            {"id": "q2", "question": "What resumes?", "metadata": {"type": "workflow"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}, "q2": {"resume.md": 1}}), encoding="utf-8")
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {"id": "qa1", "query_id": "q1", "question": "What is supported?", "answer": "Import."},
                            {"id": "qa2", "query_id": "q2", "question": "What resumes?", "answer": "Checkpoint."},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            first = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "import",
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--qa",
                    str(qa),
                    "--output",
                    str(benchmark_dir),
                    "--checkpoint",
                    str(checkpoint),
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(first_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            partial_queries = json.loads((benchmark_dir / "queries.json").read_text(encoding="utf-8"))

            second = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "import",
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--qa",
                    str(qa),
                    "--output",
                    str(benchmark_dir),
                    "--checkpoint",
                    str(checkpoint),
                    "--resume",
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(second_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            second_payload = json.loads(second_report.read_text(encoding="utf-8"))
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            final_queries = json.loads((benchmark_dir / "queries.json").read_text(encoding="utf-8"))
            final_qa = json.loads((benchmark_dir / "qa.json").read_text(encoding="utf-8"))

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual([item["id"] for item in partial_queries["queries"]], ["q1"])
        self.assertTrue(second_payload["completed"])
        self.assertEqual(second_payload["checkpoint"]["resume"], True)
        self.assertEqual(second_payload["checkpoint"]["processed_query_count"], 2)
        self.assertEqual(checkpoint_payload["schema"], "ragflow_benchmark_import_checkpoint_v1")
        self.assertEqual(checkpoint_payload["processed_query_ids"], ["q1", "q2"])
        self.assertEqual([item["id"] for item in final_queries["queries"]], ["q1", "q2"])
        self.assertEqual([item["id"] for item in final_qa["items"]], ["qa1", "qa2"])

    def test_benchmark_report_surfaces_emit_redaction_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_host = "benchmark.internal.local"
            fake_secret = "benchmark-secret"
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            gate = root / "gate.json"
            report = root / "benchmark_report.json"
            baseline_report = root / "baseline_report.json"
            benchmark_dir = root / "benchmark"
            sample_dir = root / "benchmark_sample"
            outputs = {
                "import": (root / "benchmark_import.json", root / "benchmark_import.md", root / "benchmark_import_redaction.json"),
                "preflight": (root / "benchmark_preflight.json", root / "benchmark_preflight.md", root / "benchmark_preflight_redaction.json"),
                "sample": (root / "benchmark_sample.json", root / "benchmark_sample.md", root / "benchmark_sample_redaction.json"),
                "summarize": (root / "benchmark_summary.json", root / "benchmark_summary.md", root / "benchmark_summary_redaction.json"),
                "gate": (root / "benchmark_gate.json", root / "benchmark_gate.md", root / "benchmark_gate_redaction.json"),
                "trend": (root / "benchmark_trend.json", root / "benchmark_trend.md", root / "benchmark_trend_redaction.json"),
                "delta": (root / "benchmark_delta.json", root / "benchmark_delta.md", root / "benchmark_delta_redaction.json"),
                "suggest": (root / "benchmark_suggest.json", root / "benchmark_suggest.md", root / "benchmark_suggest_redaction.json"),
            }
            queries.write_text(
                json.dumps({"queries": [{"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}}]}),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            gate.write_text(json.dumps({"thresholds": {"min_hit_rate": 1.0, "max_empty_result_rate": 0.0}}), encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {
                            "id": "ds-benchmark",
                            "name": f"kb:http://{fake_host}:9380?token={fake_secret}",
                        },
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            },
                            "query_type_breakdown": {"fact": {"query_count": 1, "hit_rate": 1.0}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            baseline_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {
                            "id": "ds-benchmark-baseline",
                            "name": f"kb:http://{fake_host}:9380?token={fake_secret}",
                        },
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 0.8,
                                "precision_at_k": 0.4,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.8,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            import_json, import_md, import_redaction = outputs["import"]
            import_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "import",
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--output",
                    str(benchmark_dir),
                    "--name",
                    f"benchmark:http://{fake_host}:9380?token={fake_secret}",
                    "--report-json",
                    str(import_json),
                    "--report-md",
                    str(import_md),
                    "--redaction-report",
                    str(import_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            preflight_json, preflight_md, preflight_redaction = outputs["preflight"]
            preflight_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "preflight",
                    "--manifest",
                    str(benchmark_dir / "manifest.json"),
                    "--gate-config",
                    str(gate),
                    "--report-json",
                    str(preflight_json),
                    "--report-md",
                    str(preflight_md),
                    "--redaction-report",
                    str(preflight_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            sample_json, sample_md, sample_redaction = outputs["sample"]
            sample_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "sample",
                    "--manifest",
                    str(benchmark_dir / "manifest.json"),
                    "--output",
                    str(sample_dir),
                    "--size",
                    "1",
                    "--seed",
                    "11",
                    "--name",
                    f"sample:http://{fake_host}:9380?token={fake_secret}",
                    "--report-json",
                    str(sample_json),
                    "--report-md",
                    str(sample_md),
                    "--redaction-report",
                    str(sample_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            summarize_json, summarize_md, summarize_redaction = outputs["summarize"]
            summarize_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "summarize",
                    "--report",
                    str(report),
                    "--report-json",
                    str(summarize_json),
                    "--report-md",
                    str(summarize_md),
                    "--redaction-report",
                    str(summarize_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            gate_json, gate_md, gate_redaction = outputs["gate"]
            gate_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "gate",
                    "--report",
                    str(report),
                    "--gate-config",
                    str(gate),
                    "--baseline-report",
                    str(baseline_report),
                    "--report-json",
                    str(gate_json),
                    "--report-md",
                    str(gate_md),
                    "--redaction-report",
                    str(gate_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            trend_json, trend_md, trend_redaction = outputs["trend"]
            trend_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "trend",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--gate-config",
                    str(gate),
                    "--report-json",
                    str(trend_json),
                    "--report-md",
                    str(trend_md),
                    "--redaction-report",
                    str(trend_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            delta_json, delta_md, delta_redaction = outputs["delta"]
            delta_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "delta",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--report-json",
                    str(delta_json),
                    "--report-md",
                    str(delta_md),
                    "--redaction-report",
                    str(delta_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            suggest_json, suggest_md, suggest_redaction = outputs["suggest"]
            suggest_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "benchmark",
                    "suggest",
                    "--report",
                    str(report),
                    "--baseline-report",
                    str(baseline_report),
                    "--gate-config",
                    str(gate),
                    "--current-top-k",
                    "3",
                    "--current-similarity-threshold",
                    "0.25",
                    "--report-json",
                    str(suggest_json),
                    "--report-md",
                    str(suggest_md),
                    "--redaction-report",
                    str(suggest_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            results = [
                import_result,
                preflight_result,
                sample_result,
                summarize_result,
                gate_result,
                trend_result,
                delta_result,
                suggest_result,
            ]
            sidecars = [json.loads(paths[2].read_text(encoding="utf-8")) for paths in outputs.values()]
            combined_parts = []
            for result in results:
                combined_parts.append(result.stdout)
            for report_json, report_md, redaction in outputs.values():
                combined_parts.append(report_json.read_text(encoding="utf-8"))
                combined_parts.append(report_md.read_text(encoding="utf-8"))
                combined_parts.append(redaction.read_text(encoding="utf-8"))
            combined = "\n".join(combined_parts)
            raw_manifest = (benchmark_dir / "manifest.json").read_text(encoding="utf-8")

        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout)
        for sidecar in sidecars:
            self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(sidecar["summary"]["redaction_count"], 1)
        self.assertIn("ragflow_benchmark_import_report_v1", import_result.stdout)
        self.assertIn("ragflow_benchmark_sample_report_v1", sample_result.stdout)
        self.assertIn("ragflow_benchmark_retrieval_suggestion_report_v1", suggest_result.stdout)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(root), combined)
        self.assertNotIn(str(report), combined)
        self.assertNotIn(str(baseline_report), combined)
        self.assertNotIn(str(gate), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)
        self.assertIn(fake_secret, raw_manifest)

    def test_suppression_report_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validation_report = root / "validation_report.json"
            report_json = root / "suppression_report.json"
            report_md = root / "suppression_report.md"
            validation_report.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "level": "benchmark",
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "cases": [
                            {
                                "id": "q1",
                                "question": "What is the payroll retention policy?",
                                "passed": False,
                                "document_hits": ["expected.md"],
                                "metadata": {"type": "fact", "allowed_tags": ["policy"]},
                                "top_chunks": [
                                    {
                                        "content": "Payroll bridge term appears in a finance benefits source.",
                                        "document_name": "finance.md",
                                        "document_id": "doc-finance",
                                        "chunk_id": "wrong-1",
                                        "raw": {
                                            "content_with_weight": "Payroll bridge term appears in a finance benefits source.",
                                            "docnm_kwd": "finance.md",
                                            "doc_id": "doc-finance",
                                            "id": "wrong-1",
                                            "tags": ["policy", "finance"],
                                        },
                                    }
                                ],
                            }
                        ],
                        "benchmark": {
                            "metrics": {"wrong_document_rate": 1.0, "tag_pollution_rate": 1.0},
                            "per_query": [{"id": "q1", "wrong_document_count": 1, "unexpected_tag_count": 1}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "suppression-report",
                    "--report",
                    str(validation_report),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(report_json.read_text(encoding="utf-8")) if report_json.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_suppression_report_v1", result.stdout)
        self.assertEqual(payload["schema"], "ragflow_suppression_report_v1")
        self.assertGreaterEqual(payload["summary"]["candidate_count"], 4)
        self.assertIn("RAGFlow Suppression Report", report_md_text)
        self.assertIn("Bridge Terms", report_md_text)

    def test_qa_validate_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "source.md").write_text(
                "The answer is grounded in this source sentence.\n",
                encoding="utf-8",
            )
            qa = root / "qa.json"
            bad_qa = root / "bad_qa.json"
            generated_qa = root / "generated_qa.json"
            chunk_snapshot = root / "chunk_snapshot.json"
            evidence_map = root / "qa_evidence_map.json"
            generate_report_md = root / "qa_generate.md"
            report_md = root / "qa_validate.md"
            map_report_md = root / "qa_evidence_map.md"
            qa.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "Where is the answer grounded?",
                                "answer": "In the source sentence.",
                                "evidence": [
                                    {
                                        "document": "source.md",
                                        "text": "The answer is grounded in this source sentence.",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bad_qa.write_text(
                json.dumps({"items": [{"id": "qa-2", "question": "What is missing?", "answer": "Evidence."}]}),
                encoding="utf-8",
            )
            chunk_snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "b" * 64,
                                "content": "The answer is grounded in this source sentence.",
                                "document_name": "source.md",
                                "chunk_id": "chunk-a",
                                "aliases": ["chunk-a"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            generate_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "generate",
                    "--source-dir",
                    str(source_dir),
                    "--output",
                    str(generated_qa),
                    "--count",
                    "1",
                    "--min-span-chars",
                    "20",
                    "--report-md",
                    str(generate_report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "validate",
                    "--qa",
                    str(qa),
                    "--source-dir",
                    str(source_dir),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            bad_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "validate",
                    "--qa",
                    str(bad_qa),
                    "--source-dir",
                    str(source_dir),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            map_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "map-evidence",
                    "--qa",
                    str(qa),
                    "--chunk-snapshot",
                    str(chunk_snapshot),
                    "--output",
                    str(evidence_map),
                    "--report-md",
                    str(map_report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            generated_payload = json.loads(generated_qa.read_text(encoding="utf-8")) if generated_qa.exists() else {}
            validate_payload = json.loads(result.stdout)
            bad_validate_payload = json.loads(bad_result.stdout)
            map_payload = json.loads(map_result.stdout)
            generate_report_md_text = generate_report_md.read_text(encoding="utf-8") if generate_report_md.exists() else ""
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            map_report_md_text = map_report_md.read_text(encoding="utf-8") if map_report_md.exists() else ""
            evidence_map_payload = json.loads(evidence_map.read_text(encoding="utf-8")) if evidence_map.exists() else {}

        self.assertEqual(generate_result.returncode, 0, generate_result.stdout)
        self.assertIn("ragflow_grounded_qa_generate_report_v1", generate_result.stdout)
        self.assertIn("RAGFlow Grounded QA Generate Report", generate_report_md_text)
        self.assertEqual(generated_payload["schema"], "ragflow_grounded_qa_v1")
        self.assertEqual(len(generated_payload["items"]), 1)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_grounded_qa_validate_report_v1", result.stdout)
        self.assertEqual(validate_payload["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(validate_payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertIn("RAGFlow Grounded QA Validate Report", report_md_text)
        self.assertIn("runtime_partial_failure_status: `completed`", report_md_text)
        self.assertEqual(bad_result.returncode, 1, bad_result.stdout)
        self.assertIn("qa_item_missing_evidence", bad_result.stdout)
        self.assertEqual(bad_validate_payload["runtime_partial_failure"]["summary"]["status"], "failed")
        self.assertEqual(map_result.returncode, 0, map_result.stdout)
        self.assertIn("ragflow_grounded_qa_evidence_map_report_v1", map_result.stdout)
        self.assertEqual(map_payload["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(map_payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertIn("RAGFlow QA Evidence Map Report", map_report_md_text)
        self.assertIn("runtime_partial_failure_status: `completed`", map_report_md_text)
        self.assertEqual(evidence_map_payload["schema"], "ragflow_grounded_qa_evidence_map_v1")
        self.assertEqual(evidence_map_payload["items"][0]["expected_chunks"], ["sha256:" + "b" * 64])
        self.assertEqual(evidence_map_payload["summary"]["evidence_mapping_coverage"], 1.0)
        self.assertEqual(evidence_map_payload["summary"]["evidence_mapping_confidence"], 1.0)

    def test_qa_generate_checkpoint_resume_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "source.md").write_text(
                "\n".join(
                    [
                        "Alpha guidance keeps deterministic QA generation grounded in one source sentence.",
                        "Beta resume checkpoint lets deterministic QA generation continue without duplicates.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            output = root / "generated_qa.json"
            checkpoint = root / "qa-generate.checkpoint.json"
            first_report = root / "first_generate.json"
            second_report = root / "second_generate.json"

            first = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "generate",
                    "--source-dir",
                    str(source_dir),
                    "--output",
                    str(output),
                    "--count",
                    "2",
                    "--min-span-chars",
                    "20",
                    "--checkpoint",
                    str(checkpoint),
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(first_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            partial_payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}

            second = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "generate",
                    "--source-dir",
                    str(source_dir),
                    "--output",
                    str(output),
                    "--count",
                    "2",
                    "--min-span-chars",
                    "20",
                    "--checkpoint",
                    str(checkpoint),
                    "--resume",
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(second_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            final_payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            first_payload = json.loads(first_report.read_text(encoding="utf-8"))
            second_payload = json.loads(second_report.read_text(encoding="utf-8"))
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual([item["id"] for item in partial_payload["items"]], ["qa-0001"])
        self.assertEqual([item["id"] for item in final_payload["items"]], ["qa-0001", "qa-0002"])
        self.assertFalse(first_payload["completed"])
        self.assertTrue(second_payload["completed"])
        self.assertEqual(second_payload["checkpoint"]["resume"], True)
        self.assertEqual(second_payload["checkpoint"]["processed_item_count"], 2)
        self.assertEqual(second_payload["checkpoint"]["new_item_count"], 1)
        self.assertEqual(checkpoint_payload["schema"], "ragflow_grounded_qa_generate_checkpoint_v1")
        self.assertEqual(checkpoint_payload["processed_item_ids"], ["qa-0001", "qa-0002"])
        self.assertTrue(checkpoint_payload["summary"]["completed"])

    def test_segment_metadata_report_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            metadata = root / "metadata.json"
            segmentation_plan = root / "segmentation_plan.json"
            report_md = root / "segment_metadata.md"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "c" * 64,
                                "document_name": "long.part-001.md",
                                "document_id": "doc-1",
                                "content_preview": "Segment one content.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {"path": "segments/long.part-001.md", "metadata": {"topic": "Segment Topic"}}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            segmentation_plan.write_text(
                json.dumps(
                    {
                        "schema": "doc_segmentation_plan_v1",
                        "segments": [{"index": 1, "suggested_markdown_path": "segments/long.part-001.md"}],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "segment-metadata",
                    "report",
                    "--chunk-snapshot",
                    str(snapshot),
                    "--metadata",
                    str(metadata),
                    "--segmentation-plan",
                    str(segmentation_plan),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_segment_metadata_report_v1", result.stdout)
        self.assertIn("RAGFlow Segment Metadata Report", report_md_text)

    def test_snapshot_qa_segment_and_suppression_surfaces_emit_redaction_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_host = "snapshot.internal.local"
            fake_secret = "snapshot-secret"
            source_dir = root / "sources"
            source_dir.mkdir()
            source_text = (
                f"Evidence from http://{fake_host}:9380/docs/source.md?token={fake_secret} "
                "states that offline grounded QA evidence mapping stays deterministic."
            )
            (source_dir / "source-token=snapshot-secret.md").write_text(source_text + "\n", encoding="utf-8")
            chunk_input = root / "chunks-token=snapshot-secret.json"
            chunk_input.write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "content": source_text,
                                "document_name": f"http://{fake_host}:9380/docs/source.md?token={fake_secret}",
                                "document_id": str(root / "docs" / "source.md"),
                                "chunk_id": f"chunk-token={fake_secret}",
                            },
                            {
                                "content": source_text,
                                "document_name": f"http://{fake_host}:9380/docs/source.md?token={fake_secret}",
                                "document_id": str(root / "docs" / "source.md"),
                                "chunk_id": f"chunk-token={fake_secret}",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": f"http://{fake_host}:9380/docs/source.md?token={fake_secret}",
                                "metadata": {"topic": "Offline Evidence Mapping"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            segmentation_plan = root / "segmentation_plan.json"
            segmentation_plan.write_text(
                json.dumps(
                    {
                        "schema": "doc_segmentation_plan_v1",
                        "segments": [
                            {
                                "index": 1,
                                "suggested_markdown_path": f"http://{fake_host}:9380/docs/source.md?token={fake_secret}",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            suppression_input = root / "suppression_input.json"
            suppression_input.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "level": "benchmark",
                        "dataset": {"id": "ds-1", "name": f"kb:http://{fake_host}:9380?token={fake_secret}"},
                        "cases": [
                            {
                                "id": "q1",
                                "question": f"What mentions api_key={fake_secret}?",
                                "passed": False,
                                "document_hits": ["expected.md"],
                                "metadata": {"type": "fact", "allowed_tags": ["policy"]},
                                "top_chunks": [
                                    {
                                        "content": "Bridge term appears in a finance source.",
                                        "document_name": f"http://{fake_host}:9380/finance.md?token={fake_secret}",
                                        "document_id": "doc-finance",
                                        "chunk_id": "wrong-1",
                                        "raw": {
                                            "content_with_weight": "Bridge term appears in a finance source.",
                                            "docnm_kwd": f"http://{fake_host}:9380/finance.md?token={fake_secret}",
                                            "doc_id": "doc-finance",
                                            "id": "wrong-1",
                                            "tags": ["policy", "finance"],
                                        },
                                    }
                                ],
                            }
                        ],
                        "benchmark": {
                            "metrics": {"wrong_document_rate": 1.0, "tag_pollution_rate": 1.0},
                            "per_query": [{"id": "q1", "wrong_document_count": 1, "unexpected_tag_count": 1}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            outputs = {
                "snapshot": (root / "snapshot_report.json", root / "snapshot_report.md", root / "snapshot_redaction.json"),
                "qa_generate": (root / "qa_generate.json", root / "qa_generate.md", root / "qa_generate_redaction.json"),
                "qa_validate": (root / "qa_validate.json", root / "qa_validate.md", root / "qa_validate_redaction.json"),
                "qa_map": (root / "qa_map.json", root / "qa_map.md", root / "qa_map_redaction.json"),
                "segment": (root / "segment_metadata.json", root / "segment_metadata.md", root / "segment_metadata_redaction.json"),
                "suppression": (root / "suppression_report.json", root / "suppression_report.md", root / "suppression_redaction.json"),
            }
            chunk_snapshot = root / "chunk_snapshot.json"
            generated_qa = root / "qa.generated.json"
            evidence_map = root / "qa_evidence_map.json"
            commands = [
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "snapshot-chunks",
                    "--input",
                    str(chunk_input),
                    "--output",
                    str(chunk_snapshot),
                    "--report-json",
                    str(outputs["snapshot"][0]),
                    "--report-md",
                    str(outputs["snapshot"][1]),
                    "--redaction-report",
                    str(outputs["snapshot"][2]),
                    "--json",
                ],
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "generate",
                    "--source-dir",
                    str(source_dir),
                    "--output",
                    str(generated_qa),
                    "--count",
                    "1",
                    "--min-span-chars",
                    "20",
                    "--report-json",
                    str(outputs["qa_generate"][0]),
                    "--report-md",
                    str(outputs["qa_generate"][1]),
                    "--redaction-report",
                    str(outputs["qa_generate"][2]),
                    "--json",
                ],
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "validate",
                    "--qa",
                    str(generated_qa),
                    "--source-dir",
                    str(source_dir),
                    "--report-json",
                    str(outputs["qa_validate"][0]),
                    "--report-md",
                    str(outputs["qa_validate"][1]),
                    "--redaction-report",
                    str(outputs["qa_validate"][2]),
                    "--json",
                ],
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "qa",
                    "map-evidence",
                    "--qa",
                    str(generated_qa),
                    "--chunk-snapshot",
                    str(chunk_snapshot),
                    "--output",
                    str(evidence_map),
                    "--report-json",
                    str(outputs["qa_map"][0]),
                    "--report-md",
                    str(outputs["qa_map"][1]),
                    "--redaction-report",
                    str(outputs["qa_map"][2]),
                    "--json",
                ],
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "segment-metadata",
                    "report",
                    "--chunk-snapshot",
                    str(chunk_snapshot),
                    "--metadata",
                    str(metadata),
                    "--segmentation-plan",
                    str(segmentation_plan),
                    "--report-json",
                    str(outputs["segment"][0]),
                    "--report-md",
                    str(outputs["segment"][1]),
                    "--redaction-report",
                    str(outputs["segment"][2]),
                    "--json",
                ],
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "suppression-report",
                    "--report",
                    str(suppression_input),
                    "--report-json",
                    str(outputs["suppression"][0]),
                    "--report-md",
                    str(outputs["suppression"][1]),
                    "--redaction-report",
                    str(outputs["suppression"][2]),
                    "--json",
                ],
            ]
            results = [
                subprocess.run(command, text=True, capture_output=True, check=False, env=_env())
                for command in commands
            ]
            sidecars = [json.loads(paths[2].read_text(encoding="utf-8")) for paths in outputs.values()]
            snapshot_payload = json.loads(outputs["snapshot"][0].read_text(encoding="utf-8"))
            qa_validate_payload = json.loads(outputs["qa_validate"][0].read_text(encoding="utf-8"))
            qa_map_payload = json.loads(outputs["qa_map"][0].read_text(encoding="utf-8"))
            combined_parts = [result.stdout for result in results]
            for report_json, report_md, redaction in outputs.values():
                combined_parts.append(report_json.read_text(encoding="utf-8"))
                combined_parts.append(report_md.read_text(encoding="utf-8"))
                combined_parts.append(redaction.read_text(encoding="utf-8"))
            combined = "\n".join(combined_parts)
            raw_snapshot = chunk_snapshot.read_text(encoding="utf-8")
            raw_qa = generated_qa.read_text(encoding="utf-8")
            raw_evidence_map = evidence_map.read_text(encoding="utf-8")

        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for sidecar in sidecars:
            self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(sidecar["summary"]["redaction_count"], 1)
        self.assertIn("ragflow_chunk_snapshot_report_v1", results[0].stdout)
        self.assertEqual(snapshot_payload["summary"]["runtime_partial_failure_status"], "partial")
        self.assertEqual(snapshot_payload["runtime_partial_failure"]["summary"]["skipped_count"], 1)
        self.assertIn("runtime_partial_failure_status: `partial`", combined)
        self.assertIn("ragflow_grounded_qa_generate_report_v1", results[1].stdout)
        self.assertIn("ragflow_grounded_qa_validate_report_v1", results[2].stdout)
        self.assertEqual(qa_validate_payload["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(qa_validate_payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertIn("runtime_partial_failure_status: `completed`", combined)
        self.assertIn("ragflow_grounded_qa_evidence_map_report_v1", results[3].stdout)
        self.assertEqual(qa_map_payload["summary"]["runtime_partial_failure_status"], "completed_with_warnings")
        self.assertEqual(qa_map_payload["runtime_partial_failure"]["summary"]["warning_count"], 1)
        self.assertIn("runtime_partial_failure_status: `completed_with_warnings`", combined)
        self.assertIn("ragflow_segment_metadata_report_v1", results[4].stdout)
        self.assertIn("ragflow_suppression_report_v1", results[5].stdout)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(root), combined)
        self.assertNotIn(str(chunk_input), combined)
        self.assertNotIn(str(suppression_input), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)
        self.assertIn(fake_host, raw_snapshot)
        self.assertIn(fake_secret, raw_snapshot)
        self.assertIn(fake_host, raw_qa)
        self.assertIn(fake_secret, raw_qa)
        self.assertIn(fake_host, raw_evidence_map)
        self.assertIn(fake_secret, raw_evidence_map)

    def test_topology_advise_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            payroll = docs / "payroll.md"
            payroll.write_text(
                "# Payroll Policy\n\n" + "Payroll benefits onboarding policy. " * 45,
                encoding="utf-8",
            )
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "source/payroll.pdf",
                                "markdown_path": "documents/payroll.md",
                                "title": "Payroll Policy",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": str(payroll),
                                "metadata": {"domain": "hr", "topic": "Payroll Policy"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints = handoff / "retrieval_hints.json"
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [{"term": "payroll policy"}],
                        "question_candidates": [
                            {
                                "question": "What is the payroll policy?",
                                "type": "section_summary",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            route_config = root / "routing.json"
            route_config.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {"name": "kb:general", "dataset_id": "ds-general", "hints": ["general", "onboarding"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "kb_topology_advice.json"
            report_md = root / "kb_topology_advice.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "topology",
                    "advise",
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    "kb:payroll",
                    "--metadata",
                    str(metadata),
                    "--retrieval-hints",
                    str(retrieval_hints),
                    "--route-config",
                    str(route_config),
                    "--future-growth",
                    "high",
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("kb_topology_advice_v1", result.stdout)
        self.assertEqual(payload["schema"], "kb_topology_advice_v1")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertGreaterEqual(len(payload["anchor_query_pairs"]), 1)
        self.assertIn("RAGFlow KB Topology Advice", report_md_text)

    def test_topology_split_plan_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            payroll = docs / "payroll.md"
            finance = docs / "finance.md"
            payroll.write_text(
                "# Payroll Policy\n\n" + "Payroll benefits onboarding policy. " * 45,
                encoding="utf-8",
            )
            finance.write_text(
                "# Finance Policy\n\n" + "Invoice tax revenue finance policy. " * 45,
                encoding="utf-8",
            )
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "source/payroll.pdf",
                                "markdown_path": "documents/payroll.md",
                                "title": "Payroll Policy",
                            },
                            {
                                "source_path": "source/finance.pdf",
                                "markdown_path": "documents/finance.md",
                                "title": "Finance Policy",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": str(payroll),
                                "metadata": {"domain": "hr", "topic": "Payroll Policy"},
                            },
                            {
                                "path": str(finance),
                                "metadata": {"domain": "finance", "topic": "Finance Policy"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints = handoff / "retrieval_hints.json"
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "question_candidates": [
                            {
                                "question": "What is the payroll policy?",
                                "type": "section_summary",
                                "source_document": str(payroll),
                            },
                            {
                                "question": "What is the finance policy?",
                                "type": "section_summary",
                                "source_document": str(finance),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "kb_split_plan.json"
            report_md = root / "kb_split_plan.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "topology",
                    "split-plan",
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    "kb:ops",
                    "--metadata",
                    str(metadata),
                    "--retrieval-hints",
                    str(retrieval_hints),
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("kb_split_plan_v1", result.stdout)
        self.assertEqual(payload["schema"], "kb_split_plan_v1")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["summary"]["split_group_count"], 2)
        self.assertGreaterEqual(len(payload["boundary_queries"]), 1)
        self.assertIn("RAGFlow KB Split Plan", report_md_text)

    def test_activation_plan_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            doc_manifest = root / "doc_manifest.json"
            chunk_snapshot = root / "chunk_snapshot.json"
            route_config = root / "routing.json"
            retrieval_hints = root / "retrieval_hints.json"
            route_tests = root / "route_tests.json"
            output = root / "kb_activation_plan.json"
            report_md = root / "kb_activation_plan.md"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-activation-cli", "name": "kb:activation-cli"},
                        "documents": [
                            {
                                "document_id": "doc-activation-cli",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            doc_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "documents": [
                            {
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                            }
                        ],
                        "quality_gate": {"status": "PASS"},
                    }
                ),
                encoding="utf-8",
            )
            chunk_snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "dataset_id": "ds-activation-cli",
                                "document_id": "doc-activation-cli",
                                "chunk_id": "chunk-1",
                                "content": "Activation CLI smoke evidence.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            route_config.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": "kb:activation-cli",
                                "dataset_id": "ds-activation-cli",
                                "hints": ["activation cli", "smoke"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [{"term": "activation cli"}],
                    }
                ),
                encoding="utf-8",
            )
            route_tests.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "activation-cli-1",
                                "question": "How does activation CLI smoke work?",
                                "expected_kb": "kb:activation-cli",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "activation-plan",
                    "--kb-manifest",
                    str(kb_manifest),
                    "--doc-manifest",
                    str(doc_manifest),
                    "--route-config",
                    str(route_config),
                    "--retrieval-hints",
                    str(retrieval_hints),
                    "--chunk-snapshot",
                    str(chunk_snapshot),
                    "--route-tests",
                    str(route_tests),
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("kb_activation_plan_v1", result.stdout)
        self.assertEqual(payload["schema"], "kb_activation_plan_v1")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["checks"]["route_test_readiness"]["passed_target_query_count"], 1)
        self.assertIn("RAGFlow KB Activation Plan", report_md_text)

    def test_topology_and_activation_write_redaction_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            topology_doc = docs / "topology.local-token=topology-secret.md"
            topology_doc.write_text(
                "# Topology Redaction\n\n" + "Topology redaction routing review. " * 35,
                encoding="utf-8",
            )
            manifest = handoff / "doc_manifest.local-token=topology-secret.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "source/topology.local-token=topology-secret.pdf",
                                "markdown_path": f"documents/{topology_doc.name}",
                                "title": "Topology Redaction",
                            }
                        ],
                        "quality_gate": {"status": "PASS"},
                    }
                ),
                encoding="utf-8",
            )
            metadata = root / "metadata.local-token=topology-secret.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": str(topology_doc),
                                "metadata": {"domain": "routing", "topic": "Topology Redaction"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            retrieval_hints = handoff / "retrieval_hints.local-token=topology-secret.json"
            retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [{"term": "topology redaction"}],
                        "question_candidates": [{"question": "How does topology redaction work?"}],
                    }
                ),
                encoding="utf-8",
            )
            route_config = root / "routing.local-token=topology-secret.json"
            route_config.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {"name": "kb:general", "dataset_id": "ds-general", "hints": ["general"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            topology_json = root / "kb_topology_advice.json"
            topology_md = root / "kb_topology_advice.md"
            topology_redaction = root / "kb_topology_advice_redaction.json"
            split_json = root / "kb_split_plan.json"
            split_md = root / "kb_split_plan.md"
            split_redaction = root / "kb_split_plan_redaction.json"

            topology_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "topology",
                    "advise",
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    "kb:http://topology.internal.local:9380?token=topology-secret",
                    "--metadata",
                    str(metadata),
                    "--retrieval-hints",
                    str(retrieval_hints),
                    "--route-config",
                    str(route_config),
                    "--output",
                    str(topology_json),
                    "--report-md",
                    str(topology_md),
                    "--redaction-report",
                    str(topology_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            split_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "topology",
                    "split-plan",
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    "kb:http://topology.internal.local:9380?token=topology-secret",
                    "--metadata",
                    str(metadata),
                    "--retrieval-hints",
                    str(retrieval_hints),
                    "--output",
                    str(split_json),
                    "--report-md",
                    str(split_md),
                    "--redaction-report",
                    str(split_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            activation_secret = "activation-secret"
            activation_kb_manifest = root / "activation.local-token=activation-secret.kb_manifest.json"
            activation_doc_manifest = root / "activation.local-token=activation-secret.doc_manifest.json"
            activation_route_config = root / "activation.local-token=activation-secret.routing.json"
            activation_retrieval_hints = root / "activation.local-token=activation-secret.retrieval_hints.json"
            activation_chunk_snapshot = root / "activation.local-token=activation-secret.chunk_snapshot.json"
            activation_route_tests = root / "activation.local-token=activation-secret.route_tests.json"
            activation_output = root / "kb_activation_plan.json"
            activation_md = root / "kb_activation_plan.md"
            activation_redaction = root / "kb_activation_plan_redaction.json"
            activation_kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "ds-activation-redaction",
                            "name": f"kb:http://activation.internal.local:9380?token={activation_secret}",
                        },
                        "documents": [
                            {
                                "document_id": "doc-activation-redaction",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            activation_doc_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "documents": [{"source_path": "source.md", "markdown_path": "documents/source.md"}],
                        "quality_gate": {"status": "PASS"},
                    }
                ),
                encoding="utf-8",
            )
            activation_route_config.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": f"kb:http://activation.internal.local:9380?token={activation_secret}",
                                "dataset_id": "ds-activation-redaction",
                                "hints": ["activation redaction"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            activation_retrieval_hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [{"term": "activation redaction"}],
                    }
                ),
                encoding="utf-8",
            )
            activation_chunk_snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "dataset_id": "ds-activation-redaction",
                                "document_id": "doc-activation-redaction",
                                "chunk_id": "chunk-activation-redaction-1",
                                "content": "Activation redaction evidence.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            activation_route_tests.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "activation-redaction-1",
                                "question": "How does activation redaction work?",
                                "expected_kb": f"kb:http://activation.internal.local:9380?token={activation_secret}",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            activation_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "activation-plan",
                    "--kb-manifest",
                    str(activation_kb_manifest),
                    "--doc-manifest",
                    str(activation_doc_manifest),
                    "--route-config",
                    str(activation_route_config),
                    "--retrieval-hints",
                    str(activation_retrieval_hints),
                    "--chunk-snapshot",
                    str(activation_chunk_snapshot),
                    "--route-tests",
                    str(activation_route_tests),
                    "--output",
                    str(activation_output),
                    "--report-md",
                    str(activation_md),
                    "--redaction-report",
                    str(activation_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            combined = "\n".join(
                [
                    topology_result.stdout,
                    split_result.stdout,
                    activation_result.stdout,
                    topology_json.read_text(encoding="utf-8"),
                    topology_md.read_text(encoding="utf-8"),
                    topology_redaction.read_text(encoding="utf-8"),
                    split_json.read_text(encoding="utf-8"),
                    split_md.read_text(encoding="utf-8"),
                    split_redaction.read_text(encoding="utf-8"),
                    activation_output.read_text(encoding="utf-8"),
                    activation_md.read_text(encoding="utf-8"),
                    activation_redaction.read_text(encoding="utf-8"),
                ]
            )
            redaction_payloads = [
                json.loads(topology_redaction.read_text(encoding="utf-8")),
                json.loads(split_redaction.read_text(encoding="utf-8")),
                json.loads(activation_redaction.read_text(encoding="utf-8")),
            ]

        self.assertEqual(topology_result.returncode, 0, topology_result.stdout)
        self.assertEqual(split_result.returncode, 0, split_result.stdout)
        self.assertEqual(activation_result.returncode, 0, activation_result.stdout)
        for redaction_payload in redaction_payloads:
            self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 1)
        self.assertNotIn("topology-secret", combined)
        self.assertNotIn("activation-secret", combined)
        self.assertNotIn("topology.internal.local", combined)
        self.assertNotIn("activation.internal.local", combined)

    def test_parse_report_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            documents_json = root / "documents.json"
            parse_log = root / "parse.log"
            profile = root / "profile.json"
            parser_config_dir = root / "private-home" / ".ragflow"
            parser_config_dir.mkdir(parents=True)
            parser_config = parser_config_dir / "parser_config.local.json"
            output = root / "parse_report.json"
            report_md = root / "parse_report.md"
            redaction_json = root / "parse_report.redaction.json"
            fake_host = "parse.internal.local"
            fake_secret = "fake-parse-report-secret"
            fake_url = f"http://{fake_host}:9380/parser?token={fake_secret}"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "ragflow_base_url": fake_url,
                        "dataset": {"id": "ds-parse-cli", "name": f"kb:{fake_url}"},
                        "documents": [
                            {
                                "document_id": f"doc-{fake_host}",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            documents_json.write_text(
                json.dumps(
                    {
                        "data": {
                            "doc_count": 1,
                            "chunk_count": 1,
                            "docs": [
                                {
                                    "id": f"doc-{fake_host}",
                                    "name": "source.md",
                                    "run": "1",
                                    "progress": 1,
                                    "chunk_count": 1,
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            parse_log.write_text("parse phase completed in 1.2s\nchunk phase completed in 80ms\n", encoding="utf-8")
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "parse-cli-profile",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            parser_config.write_text(
                json.dumps(
                    {
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "parse-report",
                    "--kb-manifest",
                    str(kb_manifest),
                    "--documents-json",
                    str(documents_json),
                    "--parse-log",
                    str(parse_log),
                    "--profile",
                    str(profile),
                    "--parser-config",
                    str(parser_config),
                    "--report-json",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_payload = json.loads(redaction_json.read_text(encoding="utf-8")) if redaction_json.exists() else {}

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_parse_report_v1", result.stdout)
        self.assertEqual(payload["schema"], "ragflow_parse_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 3)
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["execution"]["ragflow_calls"], 0)
        self.assertEqual(payload["summary"]["failed_document_count"], 0)
        self.assertEqual(payload["parse_log_summary"]["slowest_phase"]["phase"], "parse")
        self.assertIn("RAGFlow Parse Report", report_md_text)
        combined = json.dumps(payload, ensure_ascii=False) + report_md_text + result.stdout
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(parser_config), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:config-path>", combined)

    def test_health_report_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            parse_report = root / "parse_report.json"
            activation_plan = root / "activation_plan.json"
            output = root / "kb_health_report.json"
            report_md = root / "kb_health_report.md"
            redaction_json = root / "kb_health_report.redaction.json"
            fake_host = "health.internal.local"
            fake_secret = "fake-health-report-secret"
            fake_url = f"http://{fake_host}:9380/health?token={fake_secret}"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "ragflow_base_url": fake_url,
                        "dataset": {"id": "ds-health-cli", "name": f"kb:{fake_url}"},
                        "profile": {"id": "health-cli-profile", "embedding_model": "bge-m3"},
                        "documents": [
                            {
                                "document_id": "doc-health-cli",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            parse_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "ragflow_parse_report_v1",
                        "status": "PASS",
                        "dataset": {"id": "ds-health-cli", "name": f"kb:{fake_url}"},
                        "summary": {
                            "failed_document_count": 0,
                            "pending_document_count": 0,
                            "zero_chunk_document_count": 0,
                            "chunk_mismatch_count": 0,
                        },
                        "chunk_consistency": {"mismatch_count": 0, "status": "PASS"},
                        "parser_settings": {"expensive_setting_count": 0},
                        "parse_log_summary": {"error_count": 0},
                    }
                ),
                encoding="utf-8",
            )
            activation_plan.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "kb_activation_plan_v1",
                        "kb_name": f"kb:{fake_url}",
                        "dataset_id": "ds-health-cli",
                        "summary": {
                            "blocked_check_count": 0,
                            "review_check_count": 0,
                            "recommendation": "activate",
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "health-report",
                    "--kb-manifest",
                    str(kb_manifest),
                    "--parse-report",
                    str(parse_report),
                    "--activation-plan",
                    str(activation_plan),
                    "--expected-embedding-model",
                    "bge-m3",
                    "--report-json",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            redaction_payload = json.loads(redaction_json.read_text(encoding="utf-8")) if redaction_json.exists() else {}

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_kb_health_report_v1", result.stdout)
        self.assertEqual(payload["schema"], "ragflow_kb_health_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 3)
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mutation"], "none")
        self.assertEqual(payload["execution"]["ragflow_calls"], 0)
        self.assertEqual(payload["summary"]["embedding_model_count"], 1)
        self.assertEqual(payload["summary"]["embedding_model_rebuild_required_kb_count"], 0)
        self.assertEqual(payload["inputs"]["expected_embedding_models"], ["bge-m3"])
        self.assertEqual(payload["summary"]["route_activation"]["ready"], 1)
        self.assertIn("RAGFlow KB Health Report", report_md_text)
        combined = json.dumps(payload, ensure_ascii=False) + report_md_text + result.stdout
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(kb_manifest), combined)
        self.assertNotIn(str(parse_report), combined)
        self.assertNotIn(str(activation_plan), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:config-path>", combined)

    def test_optimize_plan_only_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "sample.md").write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "candidate-a",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            benchmark_manifest = root / "benchmark_manifest.json"
            artifact_dir = root / "opt-artifacts"
            output = root / "optimization_plan.json"
            report_md = root / "optimization_plan.md"
            results_json = root / "profile_experiment_results.json"
            best_md = root / "best_profile_report.md"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            benchmark_manifest.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_benchmark_manifest_v1",
                        "artifacts": {"queries": "queries.json", "qrels": "qrels.json"},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    "kb:optimize",
                    "--profile",
                    str(profile),
                    "--recommendation",
                    "en:manual",
                    "--benchmark-manifest",
                    str(benchmark_manifest),
                    "--run-id",
                    "testrun",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            report_md_text = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
            for index, candidate in enumerate(payload.get("candidates", [])):
                validation_report = Path(candidate["artifacts"]["validation_report"])
                validation_report.parent.mkdir(parents=True, exist_ok=True)
                if index == 0:
                    kb_manifest = Path(candidate["artifacts"]["kb_manifest"])
                    kb_manifest.write_text(
                        json.dumps(
                            {
                                "version": "0.1",
                                "dataset": {"id": "0123456789abcdef", "name": candidate["disposable_kb_name"]},
                                "documents": [{"document_id": "doc-0123456789abcdef", "status": "done", "chunk_count": 0}],
                            }
                        ),
                        encoding="utf-8",
                    )
                    validation_report.write_text(
                        json.dumps(
                            {
                                "ok": False,
                                "level": "benchmark",
                                "metrics": {"pass_rate": 0.0, "empty_results": 1},
                                "cases": [{"id": "q1", "passed": False, "chunk_count": 0}],
                                "benchmark": {
                                    "metrics": {
                                        "hit_rate": 0.0,
                                        "mrr": 0.0,
                                        "precision_at_k": 0.0,
                                        "recall_at_k": 0.0,
                                        "ndcg_at_k": 0.0,
                                        "map_at_k": 0.0,
                                        "strict_chunk_recall_at_k": 0.0,
                                        "expected_chunk_hit_rate": 0.0,
                                        "empty_result_rate": 1.0,
                                    }
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                    continue
                score = 1.0 if index == 1 else 0.6
                validation_report.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "level": "benchmark",
                            "metrics": {"pass_rate": score},
                            "benchmark": {
                                "metrics": {
                                    "hit_rate": score,
                                    "mrr": score,
                                    "precision_at_k": score,
                                    "recall_at_k": score,
                                    "ndcg_at_k": score,
                                    "map_at_k": score,
                                    "strict_chunk_recall_at_k": score,
                                    "expected_chunk_hit_rate": score,
                                    "empty_result_rate": 0.0,
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            summary_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "summarize",
                    "--plan",
                    str(output),
                    "--output",
                    str(results_json),
                    "--report-md",
                    str(best_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            results_payload = json.loads(results_json.read_text(encoding="utf-8")) if results_json.exists() else {}
            best_md_text = best_md.read_text(encoding="utf-8") if best_md.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ragflow_optimization_plan_v1", result.stdout)
        self.assertEqual(payload["summary"]["candidate_count"], 2)
        self.assertFalse(payload["mutation_allowed"])
        self.assertFalse(payload["mutation_guard"]["mutation_commands_enabled"])
        self.assertIsNone(payload["candidates"][0]["commands"]["build"])
        self.assertFalse(payload["candidates"][0]["mutation_commands"]["build"]["enabled"])
        self.assertIn("RAGFlow Optimization Plan", report_md_text)
        self.assertEqual(summary_result.returncode, 0, summary_result.stdout)
        self.assertIn("ragflow_profile_experiment_results_v1", summary_result.stdout)
        self.assertEqual(results_payload["summary"]["result_count"], 2)
        self.assertEqual(results_payload["summary"]["diagnostic_required_count"], 1)
        self.assertEqual(results_payload["summary"]["diagnostic_report_count"], 1)
        self.assertIn("document_zero_chunks", results_payload["diagnostics"][0]["summary"]["issue_types"])
        self.assertIn("RAGFlow Best Profile Report", best_md_text)
        self.assertIn("## Diagnostics", best_md_text)

    def test_optimize_plan_only_checkpoint_resume_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "sample.md").write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "candidate-a",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            benchmark_manifest = root / "benchmark_manifest.json"
            output = root / "optimization_plan.json"
            report_md = root / "optimization_plan.md"
            checkpoint = root / "optimization_plan.checkpoint.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            benchmark_manifest.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_benchmark_manifest_v1",
                        "artifacts": {"queries": "queries.json", "qrels": "qrels.json"},
                    }
                ),
                encoding="utf-8",
            )

            first = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    "kb:optimize-checkpoint",
                    "--profile",
                    str(profile),
                    "--recommendation",
                    "en:manual",
                    "--benchmark-manifest",
                    str(benchmark_manifest),
                    "--run-id",
                    "testrun",
                    "--artifact-dir",
                    str(root / "opt-artifacts"),
                    "--checkpoint",
                    str(checkpoint),
                    "--batch-size",
                    "1",
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            partial_payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            second = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    "kb:optimize-checkpoint",
                    "--profile",
                    str(profile),
                    "--recommendation",
                    "en:manual",
                    "--benchmark-manifest",
                    str(benchmark_manifest),
                    "--run-id",
                    "testrun",
                    "--artifact-dir",
                    str(root / "opt-artifacts"),
                    "--checkpoint",
                    str(checkpoint),
                    "--resume",
                    "--output",
                    str(output),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            final_payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            second_payload = json.loads(second.stdout)
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(partial_payload["summary"]["candidate_count"], 1)
        self.assertEqual(final_payload["summary"]["candidate_count"], 2)
        self.assertFalse(partial_payload["completed"])
        self.assertTrue(final_payload["completed"])
        self.assertTrue(second_payload["checkpoint"]["resume"])
        self.assertEqual(second_payload["checkpoint"]["processed_profile_count"], 2)
        self.assertEqual(second_payload["checkpoint"]["new_profile_count"], 1)
        self.assertEqual(checkpoint_payload["schema"], "ragflow_optimization_plan_checkpoint_v1")
        self.assertEqual(checkpoint_payload["summary"]["processed_profile_count"], 2)
        self.assertTrue(checkpoint_payload["summary"]["completed"])

    def test_optimize_plan_only_writes_command_manifest_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_host = "optimize-command.local"
            fake_secret = "optimize-command-secret"
            docs = root / "docs"
            docs.mkdir()
            (docs / "sample.md").write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "candidate-a",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            output = root / "optimization_plan.json"
            command_manifest = root / "optimization_command_manifest.json"
            redaction_report = root / "optimization_command_manifest_redaction.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    f"kb:http://{fake_host}:9380?token={fake_secret}",
                    "--profile",
                    str(profile),
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--run-id",
                    "command-manifest",
                    "--artifact-dir",
                    str(root / "opt-artifacts"),
                    "--output",
                    str(output),
                    "--command-manifest-output",
                    str(command_manifest),
                    "--redaction-report",
                    str(redaction_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            plan_payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            manifest_payload = json.loads(command_manifest.read_text(encoding="utf-8")) if command_manifest.exists() else {}
            redaction_payload = json.loads(redaction_report.read_text(encoding="utf-8")) if redaction_report.exists() else {}
            combined = (
                json.dumps(plan_payload, ensure_ascii=False)
                + json.dumps(manifest_payload, ensure_ascii=False)
                + json.dumps(redaction_payload, ensure_ascii=False)
                + result.stdout
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(manifest_payload["schema"], "ragflow_optimization_command_manifest_v1")
        self.assertEqual(manifest_payload["mode"], "dry_run")
        self.assertEqual(manifest_payload["summary"]["candidate_count"], 1)
        self.assertEqual(manifest_payload["summary"]["mutating_command_count"], 1)
        self.assertEqual(manifest_payload["summary"]["enabled_mutating_command_count"], 0)
        self.assertFalse(manifest_payload["mutation_guard"]["mutation_allowed"])
        self.assertTrue(manifest_payload["mutation_guard"]["cleanup_confirmation_required"])
        build_command = next(command for command in manifest_payload["commands"] if command["id"].endswith(":build-disposable-kb"))
        self.assertTrue(build_command["mutates_ragflow"])
        self.assertFalse(build_command["enabled"])
        self.assertTrue(build_command["requires_execute"])
        self.assertIn("<artifact-dir>/candidate-a/kb_manifest.json", json.dumps(build_command, ensure_ascii=False))
        self.assertEqual(plan_payload["command_manifest"]["schema"], "ragflow_optimization_command_manifest_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 1)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(root), combined)

    def test_optimize_cleanup_plan_subcommand_via_build_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "sample.md").write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "cleanup-profile",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            optimization_plan = root / "optimization_plan.json"
            cleanup_plan = root / "cleanup_plan.json"
            cleanup_md = root / "cleanup_plan.md"
            artifact_dir = root / "opt-artifacts"

            plan_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    "kb:optimize-cleanup",
                    "--profile",
                    str(profile),
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--run-id",
                    "cleanup",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--output",
                    str(optimization_plan),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            plan_payload = json.loads(optimization_plan.read_text(encoding="utf-8")) if optimization_plan.exists() else {}
            candidate = plan_payload["candidates"][0]
            kb_manifest = Path(candidate["artifacts"]["kb_manifest"])
            kb_manifest.parent.mkdir(parents=True, exist_ok=True)
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": candidate["disposable_kb_name"]},
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )

            cleanup_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "cleanup-plan",
                    "--plan",
                    str(optimization_plan),
                    "--output",
                    str(cleanup_plan),
                    "--report-md",
                    str(cleanup_md),
                    "--config",
                    str(root / "ragflow.yaml"),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            cleanup_payload = json.loads(cleanup_plan.read_text(encoding="utf-8")) if cleanup_plan.exists() else {}
            cleanup_md_text = cleanup_md.read_text(encoding="utf-8") if cleanup_md.exists() else ""

        self.assertEqual(plan_result.returncode, 0, plan_result.stdout)
        self.assertEqual(cleanup_result.returncode, 0, cleanup_result.stdout)
        self.assertIn("ragflow_optimization_cleanup_plan_v1", cleanup_result.stdout)
        self.assertEqual(cleanup_payload["summary"]["ready_target_count"], 1)
        self.assertIn("--confirm-dataset-id", cleanup_payload["targets"][0]["commands"]["execute"])
        self.assertIn("RAGFlow Optimization Cleanup Plan", cleanup_md_text)

    def test_optimize_report_surfaces_emit_redaction_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_host = "optimize.internal.local"
            fake_secret = "optimize-secret"
            docs = root / "docs"
            docs.mkdir()
            (docs / "source.md").write_text("# Source\n\nKnown optimize answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "profile_id": "candidate-a",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "parser_config": {
                            "chunk_token_num": 512,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                        },
                    }
                ),
                encoding="utf-8",
            )
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            raw_plan = root / "raw_optimization_plan.json"
            raw_artifact_dir = root / "raw-artifacts"
            redacted_plan = root / "optimization_plan.json"
            redacted_plan_md = root / "optimization_plan.md"
            redacted_plan_sidecar = root / "optimization_plan_redaction.json"
            redacted_cleanup = root / "optimization_cleanup_plan.json"
            redacted_cleanup_md = root / "optimization_cleanup_plan.md"
            redacted_cleanup_sidecar = root / "optimization_cleanup_plan_redaction.json"
            redacted_summary = root / "profile_experiment_results.json"
            redacted_summary_md = root / "best_profile_report.md"
            redacted_summary_sidecar = root / "best_profile_report_redaction.json"
            private_config = root / "ragflow.local.yaml"

            raw_plan_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    f"kb:http://{fake_host}:9380?token={fake_secret}",
                    "--profile",
                    str(profile),
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--run-id",
                    "redaction",
                    "--artifact-dir",
                    str(raw_artifact_dir),
                    "--output",
                    str(raw_plan),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            raw_payload = json.loads(raw_plan.read_text(encoding="utf-8")) if raw_plan.exists() else {}
            candidate = raw_payload["candidates"][0]
            kb_manifest = Path(candidate["artifacts"]["kb_manifest"])
            kb_manifest.parent.mkdir(parents=True, exist_ok=True)
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": candidate["disposable_kb_name"]},
                        "documents": [{"document_id": "doc-0123456789abcdef", "status": "done", "chunk_count": 1}],
                    }
                ),
                encoding="utf-8",
            )
            validation_report = Path(candidate["artifacts"]["validation_report"])
            validation_report.parent.mkdir(parents=True, exist_ok=True)
            validation_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "level": "benchmark",
                        "dataset": {
                            "id": "ds-optimize",
                            "name": f"kb:http://{fake_host}:9380?token={fake_secret}",
                        },
                        "metrics": {"pass_rate": 1.0},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 1.0,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "strict_chunk_recall_at_k": 1.0,
                                "expected_chunk_hit_rate": 1.0,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            redacted_plan_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "--plan-only",
                    "--input",
                    str(docs),
                    "--kb-name",
                    f"kb:http://{fake_host}:9380?token={fake_secret}",
                    "--profile",
                    str(profile),
                    "--queries",
                    str(queries),
                    "--qrels",
                    str(qrels),
                    "--run-id",
                    "redaction",
                    "--artifact-dir",
                    str(root / "redacted-artifacts"),
                    "--output",
                    str(redacted_plan),
                    "--report-md",
                    str(redacted_plan_md),
                    "--redaction-report",
                    str(redacted_plan_sidecar),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            cleanup_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "cleanup-plan",
                    "--plan",
                    str(raw_plan),
                    "--output",
                    str(redacted_cleanup),
                    "--report-md",
                    str(redacted_cleanup_md),
                    "--config",
                    str(private_config),
                    "--redaction-report",
                    str(redacted_cleanup_sidecar),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            summary_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "optimize",
                    "summarize",
                    "--plan",
                    str(raw_plan),
                    "--report",
                    str(validation_report),
                    "--output",
                    str(redacted_summary),
                    "--report-md",
                    str(redacted_summary_md),
                    "--redaction-report",
                    str(redacted_summary_sidecar),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            plan_payload = json.loads(redacted_plan.read_text(encoding="utf-8")) if redacted_plan.exists() else {}
            cleanup_payload = json.loads(redacted_cleanup.read_text(encoding="utf-8")) if redacted_cleanup.exists() else {}
            summary_payload = json.loads(redacted_summary.read_text(encoding="utf-8")) if redacted_summary.exists() else {}
            sidecars = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (redacted_plan_sidecar, redacted_cleanup_sidecar, redacted_summary_sidecar)
            ]
            combined = (
                json.dumps(plan_payload, ensure_ascii=False)
                + redacted_plan_md.read_text(encoding="utf-8")
                + redacted_plan_result.stdout
                + json.dumps(cleanup_payload, ensure_ascii=False)
                + redacted_cleanup_md.read_text(encoding="utf-8")
                + cleanup_result.stdout
                + json.dumps(summary_payload, ensure_ascii=False)
                + redacted_summary_md.read_text(encoding="utf-8")
                + summary_result.stdout
                + json.dumps(sidecars, ensure_ascii=False)
            )

        self.assertEqual(raw_plan_result.returncode, 0, raw_plan_result.stdout)
        self.assertEqual(redacted_plan_result.returncode, 0, redacted_plan_result.stdout)
        self.assertEqual(cleanup_result.returncode, 0, cleanup_result.stdout)
        self.assertEqual(summary_result.returncode, 0, summary_result.stdout)
        self.assertEqual(plan_payload["schema"], "ragflow_optimization_plan_v1")
        self.assertEqual(cleanup_payload["schema"], "ragflow_optimization_cleanup_plan_v1")
        self.assertEqual(summary_payload["schema"], "ragflow_profile_experiment_results_v1")
        for sidecar in sidecars:
            self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(sidecar["summary"]["redaction_count"], 1)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(root), combined)
        self.assertNotIn(str(raw_plan), combined)
        self.assertNotIn(str(kb_manifest), combined)
        self.assertNotIn(str(validation_report), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)

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
        self.assertEqual(payload["summary"]["runtime_partial_failure_status"], "skipped")
        self.assertEqual(payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["skipped_count"], 1)

    def test_inspect_manifest_live_partial_failure_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, inspect_kb_live_server() as base_url:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-live", "name": "kb:live"},
                        "documents": [
                            {"document_id": "doc-ok", "status": "uploaded"},
                            {"document_id": "doc-fail", "status": "uploaded"},
                            {"document_id": "doc-pending", "status": "uploaded"},
                            {"document_id": "doc-missing", "status": "uploaded"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSPECT_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--live",
                    "--base-url",
                    base_url,
                    "--api-key",
                    "fake-inspect-key",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["live_document_count"], 3)
        self.assertEqual(payload["summary"]["runtime_partial_failure_status"], "partial")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["warning_count"], 2)
        self.assertEqual(payload["runtime_partial_failure"]["status_counts"]["parsed"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["status_counts"]["failed"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["status_counts"]["in_progress"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["status_counts"]["missing"], 1)

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

    def test_validation_diagnostic_surfaces_emit_redaction_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, diagnostic_probe_server() as base_url:
            root = Path(tmp)
            fake_host = "diagnostic.internal.local"
            fake_secret = "diagnostic-secret"
            manifest = root / "kb_manifest.json"
            source = root / f"source-token={fake_secret}.md"
            markdown = root / "documents" / f"source-token={fake_secret}.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            markdown.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# Source\n", encoding="utf-8")
            markdown.write_text("# Source\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "short",
                            "name": f"kb:http://{fake_host}:9380?token={fake_secret}",
                        },
                        "documents": [
                            {
                                "document_id": "doc-1",
                                "source_path": str(source),
                                "markdown_path": str(markdown),
                                "status": "running",
                                "chunk_count": 0,
                            }
                        ],
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
                                "question": f"Known token={fake_secret} http://{fake_host}/retrieval",
                                "expected_terms": ["known term"],
                                "expected_documents": [f"source-token={fake_secret}.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            handoff = root / "handoff"
            docs_dir = handoff / "documents"
            docs_dir.mkdir(parents=True)
            (docs_dir / "sample.md").write_text("# Sample\n", encoding="utf-8")
            manifest_name = f"doc_manifest-token={fake_secret}.json"
            (handoff / manifest_name).write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": str(root),
                        "quality_report": f"quality-token={fake_secret}.json",
                        "documents": [{"source_path": str(source), "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / f"quality-token={fake_secret}.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )

            outputs = {
                "inspect_handoff": (
                    root / "handoff_inspection.json",
                    root / "handoff_inspection.md",
                    root / "handoff_inspection_redaction.json",
                ),
                "diagnose": (
                    root / "diagnostic.json",
                    root / "diagnostic.md",
                    root / "diagnostic_redaction.json",
                ),
                "inspect_kb": (
                    None,
                    None,
                    root / "inspect_kb_redaction.json",
                ),
                "probe": (
                    root / "probe.json",
                    root / "probe.md",
                    root / "probe_redaction.json",
                ),
                "validate": (
                    root / "validation.json",
                    root / "validation.md",
                    root / "validation_redaction.json",
                ),
            }
            inspect_handoff_json, inspect_handoff_md, inspect_handoff_redaction = outputs["inspect_handoff"]
            inspect_handoff_result = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "inspect-handoff",
                    "--handoff",
                    str(handoff),
                    "--manifest-name",
                    manifest_name,
                    "--report-json",
                    str(inspect_handoff_json),
                    "--report-md",
                    str(inspect_handoff_md),
                    "--redaction-report",
                    str(inspect_handoff_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            diagnose_json, diagnose_md, diagnose_redaction = outputs["diagnose"]
            diagnose_result = subprocess.run(
                [
                    sys.executable,
                    str(DIAGNOSE_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--report-json",
                    str(diagnose_json),
                    "--report-md",
                    str(diagnose_md),
                    "--redaction-report",
                    str(diagnose_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            inspect_redaction = outputs["inspect_kb"][2]
            inspect_result = subprocess.run(
                [
                    sys.executable,
                    str(INSPECT_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--redaction-report",
                    str(inspect_redaction),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            probe_json, probe_md, probe_redaction = outputs["probe"]
            probe_result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE_SCRIPT),
                    "--base-url",
                    base_url,
                    "--api-key",
                    fake_secret,
                    "--report-json",
                    str(probe_json),
                    "--report-md",
                    str(probe_md),
                    "--redaction-report",
                    str(probe_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            validate_json, validate_md, validate_redaction = outputs["validate"]
            validate_result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    "--kb-manifest",
                    str(manifest),
                    "--level",
                    "regression",
                    "--queries",
                    str(queries),
                    "--base-url",
                    base_url,
                    "--api-key",
                    fake_secret,
                    "--report-json",
                    str(validate_json),
                    "--report-md",
                    str(validate_md),
                    "--redaction-report",
                    str(validate_redaction),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            results = [inspect_handoff_result, diagnose_result, inspect_result, probe_result, validate_result]
            sidecars = [json.loads(paths[2].read_text(encoding="utf-8")) for paths in outputs.values()]
            combined_parts = [result.stdout for result in results]
            for report_json, report_md, redaction in outputs.values():
                if report_json:
                    combined_parts.append(report_json.read_text(encoding="utf-8"))
                if report_md:
                    combined_parts.append(report_md.read_text(encoding="utf-8"))
                combined_parts.append(redaction.read_text(encoding="utf-8"))
            probe_payload = json.loads(probe_json.read_text(encoding="utf-8"))
            probe_markdown = probe_md.read_text(encoding="utf-8")
            combined = "\n".join(combined_parts)

        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for sidecar in sidecars:
            self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(sidecar["summary"]["redaction_count"], 1)
        self.assertIn("ragflow_handoff_inspection_v1", inspect_handoff_result.stdout)
        self.assertIn("ragflow_kb_diagnostic_report_v1", diagnose_result.stdout)
        self.assertIn("ragflow_kb_diagnostic_report_v1", probe_result.stdout)
        self.assertEqual(probe_payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(probe_payload["summary"]["runtime_partial_failure_status"], "completed_with_warnings")
        self.assertIn("runtime_partial_failure_status: `completed_with_warnings`", probe_markdown)
        self.assertIn("RAGFlow Validation Report", combined)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn("127.0.0.1", combined)
        self.assertNotIn(str(root), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)

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
        self.assertIn("--redaction-report", result.stdout)

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

    def test_append_and_cleanup_plan_redaction_sidecars(self) -> None:
        append_secret = "append-secret"
        append_host = "append.internal.local"
        cleanup_secret = "cleanup-secret"
        cleanup_host = "cleanup.internal.local"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / f"append-token={append_secret}"
            input_dir.mkdir()
            (input_dir / f"source-token={append_secret}.md").write_text("# Append\n", encoding="utf-8")
            append_manifest = root / f"kb-token={append_secret}.json"
            append_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "0123456789abcdef",
                            "name": f"kb:http://{append_host}:9380?token={append_secret}",
                        },
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            append_output = root / "append_plan.json"
            append_redaction = root / "append_redaction.json"
            append_result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--kb-manifest",
                    str(append_manifest),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(append_output),
                    "--redaction-report",
                    str(append_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            cleanup_manifest = root / f"cleanup-token={cleanup_secret}.json"
            cleanup_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "fedcba9876543210",
                            "name": f"kb:http://{cleanup_host}:9380?token={cleanup_secret}",
                        },
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            cleanup_output = root / "cleanup_plan.json"
            cleanup_redaction = root / "cleanup_redaction.json"
            cleanup_result = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP_SCRIPT),
                    "--kb-manifest",
                    str(cleanup_manifest),
                    "--output",
                    str(cleanup_output),
                    "--redaction-report",
                    str(cleanup_redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            append_payload = json.loads(append_output.read_text(encoding="utf-8")) if append_output.exists() else {}
            cleanup_payload = json.loads(cleanup_output.read_text(encoding="utf-8")) if cleanup_output.exists() else {}
            append_sidecar = json.loads(append_redaction.read_text(encoding="utf-8")) if append_redaction.exists() else {}
            cleanup_sidecar = json.loads(cleanup_redaction.read_text(encoding="utf-8")) if cleanup_redaction.exists() else {}
            combined = "\n".join(
                [
                    append_result.stdout,
                    cleanup_result.stdout,
                    append_output.read_text(encoding="utf-8") if append_output.exists() else "",
                    cleanup_output.read_text(encoding="utf-8") if cleanup_output.exists() else "",
                    append_redaction.read_text(encoding="utf-8") if append_redaction.exists() else "",
                    cleanup_redaction.read_text(encoding="utf-8") if cleanup_redaction.exists() else "",
                ]
            )

        self.assertEqual(append_result.returncode, 0, append_result.stderr)
        self.assertEqual(cleanup_result.returncode, 0, cleanup_result.stderr)
        self.assertEqual(append_payload["schema"], "ragflow_append_plan_v1")
        self.assertEqual(cleanup_payload["schema"], "ragflow_cleanup_plan_v1")
        self.assertEqual(append_sidecar["schema"], "ragflow_report_redaction_report_v1")
        self.assertEqual(cleanup_sidecar["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(append_sidecar["summary"]["redaction_count"], 1)
        self.assertGreaterEqual(cleanup_sidecar["summary"]["redaction_count"], 1)
        self.assertNotIn(append_secret, combined)
        self.assertNotIn(cleanup_secret, combined)
        self.assertNotIn(append_host, combined)
        self.assertNotIn(cleanup_host, combined)
        self.assertNotIn(str(root), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)

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
        self.assertIn("--redaction-report", result.stdout)

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

    def test_profile_help_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROFILE_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Lint, explain, recommend", result.stdout)

    def test_profile_lint_and_recommend_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_md = root / "profile_lint.md"
            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "lint",
                    "--profile",
                    str(PROFILE_PATH),
                    "--report-md",
                    str(report_md),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            output_profile = root / "recommended.json"
            recommend_result = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "recommend",
                    "--language",
                    "en",
                    "--doc-type",
                    "manual",
                    "--output",
                    str(output_profile),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            lint_report_text = report_md.read_text(encoding="utf-8")
            recommended_payload = json.loads(output_profile.read_text(encoding="utf-8"))

        self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
        self.assertIn("profile_lint_report_v1", lint_result.stdout)
        self.assertIn("default-en-768", lint_report_text)
        self.assertEqual(recommend_result.returncode, 0, recommend_result.stdout)
        self.assertEqual(recommended_payload["chunk_size"], 768)

    def test_profile_compare_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.json"
            second = root / "second.json"
            out_md = root / "compare.md"
            first.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "metrics": {"pass_rate": 0.8},
                        "benchmark": {"metrics": {"hit_rate": 0.5, "mrr": 0.4, "ndcg_at_k": 0.4}},
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "metrics": {"pass_rate": 1.0},
                        "benchmark": {"metrics": {"hit_rate": 1.0, "mrr": 0.8, "ndcg_at_k": 0.8}},
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "compare",
                    "--report",
                    str(first),
                    "--report",
                    str(second),
                    "--report-md",
                    str(out_md),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            compare_report_text = out_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["winner"]["path"], str(second))
        self.assertIn("Profile Compare", compare_report_text)

    def test_profile_experiment_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            candidate_set = root / "candidate_profile_set.json"
            report_json = root / "experiment_report.json"
            report_md = root / "experiment_report.md"
            matrix.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_enrichment_experiment_matrix_v1",
                        "name": "phase27-smoke",
                        "fixed": {"retrieval.top_k": 3},
                        "dimensions": {
                            "auto_keywords": [0, 3],
                            "auto_questions": [0],
                            "retrieval.similarity_threshold": [0.01],
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "experiment",
                    "--base-profile",
                    str(PROFILE_PATH),
                    "--matrix",
                    str(matrix),
                    "--candidate-set",
                    str(candidate_set),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            candidate_payload = json.loads(candidate_set.read_text(encoding="utf-8"))
            report_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(payload["schema"], "ragflow_enrichment_experiment_report_v1")
        self.assertEqual(payload["summary"]["candidate_profile_count"], 2)
        self.assertEqual(candidate_payload["schema"], "ragflow_candidate_profile_set_v1")
        self.assertIn("llm_backed_enrichment_enabled", {issue["code"] for issue in payload["issues"]})
        self.assertIn("RAGFlow Enrichment Experiment Matrix", report_text)

    def test_profile_experiment_checkpoint_resume_via_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            candidate_set = root / "candidate_profile_set.json"
            checkpoint = root / "profile_experiment.checkpoint.json"
            first_report = root / "first_experiment.json"
            second_report = root / "second_experiment.json"
            matrix.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_enrichment_experiment_matrix_v1",
                        "name": "phase31-resume-smoke",
                        "dimensions": {
                            "auto_keywords": [0, 3],
                            "auto_questions": [0],
                        },
                    }
                ),
                encoding="utf-8",
            )

            first = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "experiment",
                    "--base-profile",
                    str(PROFILE_PATH),
                    "--matrix",
                    str(matrix),
                    "--candidate-set",
                    str(candidate_set),
                    "--checkpoint",
                    str(checkpoint),
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(first_report),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            partial_candidate_set = json.loads(candidate_set.read_text(encoding="utf-8"))

            second = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "experiment",
                    "--base-profile",
                    str(PROFILE_PATH),
                    "--matrix",
                    str(matrix),
                    "--candidate-set",
                    str(candidate_set),
                    "--checkpoint",
                    str(checkpoint),
                    "--resume",
                    "--batch-size",
                    "1",
                    "--report-json",
                    str(second_report),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            final_candidate_set = json.loads(candidate_set.read_text(encoding="utf-8"))
            first_payload = json.loads(first_report.read_text(encoding="utf-8"))
            second_payload = json.loads(second_report.read_text(encoding="utf-8"))
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(len(partial_candidate_set["profiles"]), 1)
        self.assertEqual(len(final_candidate_set["profiles"]), 2)
        self.assertFalse(first_payload["completed"])
        self.assertTrue(second_payload["completed"])
        self.assertEqual(second_payload["checkpoint"]["resume"], True)
        self.assertEqual(second_payload["checkpoint"]["processed_profile_count"], 2)
        self.assertEqual(second_payload["checkpoint"]["new_profile_count"], 1)
        self.assertEqual(checkpoint_payload["schema"], "ragflow_enrichment_experiment_checkpoint_v1")
        self.assertEqual(len(checkpoint_payload["processed_profile_ids"]), 2)
        self.assertTrue(checkpoint_payload["summary"]["completed"])

    def test_profile_surfaces_emit_redaction_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_host = "profile.internal.local"
            fake_secret = "profile-secret"
            profile_path = root / "profile-api_key=profile-secret.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "profile_id": "profile-redaction",
                        "chunk_method": "naive",
                        "chunk_size": 768,
                        "chunk_overlap": 96,
                        "embedding_model": f"http://{fake_host}:9380/embed?token={fake_secret}",
                        "parser_config": {
                            "chunk_token_num": 768,
                            "auto_keywords": 0,
                            "auto_questions": 0,
                            "__language__": "English",
                            "local_path": str(root / "private" / "profile-token=profile-secret.json"),
                            "secret_note": f"api_key={fake_secret}",
                        },
                    }
                ),
                encoding="utf-8",
            )
            first_report = root / "first-validation.json"
            second_report = root / "second-validation.json"
            first_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "level": "benchmark",
                        "dataset": {"id": "ds-1", "name": f"kb:http://{fake_host}:9380?token={fake_secret}"},
                        "metrics": {"pass_rate": 0.6, "query_latency_ms": 220.0},
                        "benchmark": {"metrics": {"hit_rate": 0.4, "mrr": 0.3, "ndcg_at_k": 0.3}},
                    }
                ),
                encoding="utf-8",
            )
            second_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "level": "benchmark",
                        "dataset": {"id": "ds-2", "name": f"kb:{root}:api_key={fake_secret}"},
                        "metrics": {"pass_rate": 1.0, "query_latency_ms": 110.0},
                        "benchmark": {"metrics": {"hit_rate": 0.9, "mrr": 0.8, "ndcg_at_k": 0.8}},
                    }
                ),
                encoding="utf-8",
            )
            matrix = root / "matrix.json"
            matrix.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_enrichment_experiment_matrix_v1",
                        "name": f"profile-matrix-token={fake_secret}",
                        "dimensions": {
                            "auto_questions": [0, 1],
                            "retrieval.endpoint": [f"http://{fake_host}:9380/v1?token={fake_secret}"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            outputs = {
                "lint": (root / "lint.json", root / "lint.md", root / "lint_redaction.json"),
                "explain": (root / "explain.json", None, root / "explain_redaction.json"),
                "recommend": (root / "recommend.json", None, root / "recommend_redaction.json"),
                "compare": (root / "compare.json", root / "compare.md", root / "compare_redaction.json"),
                "experiment": (root / "experiment.json", root / "experiment.md", root / "experiment_redaction.json"),
            }
            recommended_profile = root / "recommended_profile.json"
            candidate_set = root / "candidate_profile_set.json"
            commands = [
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "lint",
                    "--profile",
                    str(profile_path),
                    "--report-json",
                    str(outputs["lint"][0]),
                    "--report-md",
                    str(outputs["lint"][1]),
                    "--redaction-report",
                    str(outputs["lint"][2]),
                ],
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "explain",
                    "--profile",
                    str(profile_path),
                    "--report-json",
                    str(outputs["explain"][0]),
                    "--redaction-report",
                    str(outputs["explain"][2]),
                ],
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "recommend",
                    "--language",
                    "en",
                    "--doc-type",
                    "manual",
                    "--profile-id",
                    f"recommended-http://{fake_host}:9380?token={fake_secret}",
                    "--output",
                    str(recommended_profile),
                    "--report-json",
                    str(outputs["recommend"][0]),
                    "--redaction-report",
                    str(outputs["recommend"][2]),
                ],
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "compare",
                    "--report",
                    str(first_report),
                    "--report",
                    str(second_report),
                    "--report-json",
                    str(outputs["compare"][0]),
                    "--report-md",
                    str(outputs["compare"][1]),
                    "--redaction-report",
                    str(outputs["compare"][2]),
                ],
                [
                    sys.executable,
                    str(PROFILE_SCRIPT),
                    "experiment",
                    "--base-profile",
                    str(profile_path),
                    "--matrix",
                    str(matrix),
                    "--candidate-set",
                    str(candidate_set),
                    "--report-json",
                    str(outputs["experiment"][0]),
                    "--report-md",
                    str(outputs["experiment"][1]),
                    "--redaction-report",
                    str(outputs["experiment"][2]),
                ],
            ]
            results = [
                subprocess.run(command, text=True, capture_output=True, check=False, env=_env())
                for command in commands
            ]
            sidecars = [json.loads(paths[2].read_text(encoding="utf-8")) for paths in outputs.values()]
            combined_parts = [result.stdout for result in results]
            for report_json, report_md, redaction in outputs.values():
                combined_parts.append(report_json.read_text(encoding="utf-8"))
                if report_md:
                    combined_parts.append(report_md.read_text(encoding="utf-8"))
                combined_parts.append(redaction.read_text(encoding="utf-8"))
            combined = "\n".join(combined_parts)
            raw_recommendation = recommended_profile.read_text(encoding="utf-8")
            raw_candidate_set = candidate_set.read_text(encoding="utf-8")

        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for sidecar in sidecars:
            self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")
            self.assertGreaterEqual(sidecar["summary"]["redaction_count"], 1)
        self.assertIn("ragflow_profile_lint_report_v1", results[0].stdout)
        self.assertIn("ragflow_profile_explanation_v1", results[1].stdout)
        self.assertIn("ragflow_profile_recommendation_v1", results[2].stdout)
        self.assertIn("ragflow_profile_compare_report_v1", results[3].stdout)
        self.assertIn("ragflow_enrichment_experiment_report_v1", results[4].stdout)
        self.assertNotIn(fake_host, combined)
        self.assertNotIn(fake_secret, combined)
        self.assertNotIn(str(root), combined)
        self.assertNotIn(str(profile_path), combined)
        self.assertNotIn(str(first_report), combined)
        self.assertNotIn(str(second_report), combined)
        self.assertIn("<redacted:private-host>", combined)
        self.assertIn("<redacted:secret>", combined)
        self.assertIn("<redacted:config-path>", combined)
        self.assertIn(fake_host, raw_recommendation)
        self.assertIn(fake_secret, raw_recommendation)
        self.assertIn(fake_host, raw_candidate_set)
        self.assertIn(fake_secret, raw_candidate_set)

    def test_validate_regression_requires_queries_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "kb_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "documents": [
                            {
                                "document_id": "doc-1",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                            }
                        ],
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
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {
                                "path": "documents/source.md",
                                "metadata": {"domain": "example-domain", "topic": "Example"},
                                "tags": ["example-tag"],
                            }
                        ],
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
                        "--metadata",
                        str(metadata),
                        "--report-md",
                        str(report_md),
                    ]
                )
            report_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["metrics"]["pass_rate"], 1.0)
        self.assertEqual(payload["metrics"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertTrue(payload["metadata_summary"]["ok"])
        self.assertEqual(payload["metadata_summary"]["tag_count"], 1)
        self.assertIn("q1", report_text)
        self.assertIn("runtime_partial_failure_status: `completed`", report_text)
        self.assertIn("Metadata Summary", report_text)

    def test_validate_regression_reports_partial_runtime_failures_via_fake_client(self) -> None:
        module = load_validate_module()
        module.RAGFlowClient = FakePartialValidationClient
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
                                "id": "q-ok",
                                "question": "Known",
                                "expected_terms": ["known term"],
                                "expected_documents": ["source.md"],
                            },
                            {
                                "id": "q-timeout",
                                "question": "Timeout please",
                                "expected_terms": [],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report_md = root / "report.md"
            redaction_report = root / "redaction.json"
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
                        "--redaction-report",
                        str(redaction_report),
                    ]
                )
            report_text = report_md.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_report.read_text(encoding="utf-8"))

        self.assertEqual(code, 1, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["timeout_count"], 1)
        self.assertEqual(payload["metrics"]["runtime_timeout_count"], 1)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertIn("runtime_partial_failure_status: `partial`", report_text)
        self.assertIn("runtime_partial_failure_timeouts: `1`", report_text)

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
            expected_hash = "sha256:" + hashlib.sha256("Known includes known term".encode("utf-8")).hexdigest()
            qrels.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {
                                "query_id": "q1",
                                "expected_documents": ["source.md"],
                                "expected_chunks": [expected_hash],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            chunk_snapshot = root / "chunk_snapshot.json"
            chunk_snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "stable_hash": expected_hash,
                                "document_name": "source.md",
                                "aliases": [expected_hash],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gate = root / "gate.json"
            gate.write_text(
                json.dumps({"thresholds": {"min_hit_rate": 1.0, "min_mrr": 1.0, "min_strict_chunk_recall_at_k": 1.0}}),
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
                        "--chunk-snapshot",
                        str(chunk_snapshot),
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
        self.assertEqual(payload["benchmark"]["metrics"]["strict_chunk_recall_at_k"], 1.0)
        self.assertEqual(payload["benchmark"]["query_type_breakdown"]["fact"]["query_count"], 1)
        self.assertTrue(payload["benchmark"]["gate"]["ok"])
        self.assertEqual(payload["benchmark"]["baseline"]["delta"]["mrr"], 0.5)
        self.assertIn("## Benchmark", report_text)


if __name__ == "__main__":
    unittest.main()
