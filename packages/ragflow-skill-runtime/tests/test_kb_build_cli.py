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
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report_payload = json.loads(report_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], "ragflow_model_provider_probe_report_v1")
        self.assertEqual(payload["summary"]["available_endpoint_count"], 1)
        self.assertEqual(payload["summary"]["embedding_model_count"], 1)
        self.assertEqual(payload["summary"]["rerank_model_count"], 1)
        self.assertEqual(payload["summary"]["configured_adapter_count"], 2)
        self.assertEqual(payload["summary"]["handled_empty_input_adapter_count"], 2)
        self.assertTrue(all(check["found"] for check in payload["expected_model_checks"]))
        self.assertEqual(report_payload["summary"]["provider_count"], 1)
        self.assertIn("RAGFlow Model Provider Probe", markdown)

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
        self.assertIn("RAGFlow Grounded QA Validate Report", report_md_text)
        self.assertEqual(bad_result.returncode, 1, bad_result.stdout)
        self.assertIn("qa_item_missing_evidence", bad_result.stdout)
        self.assertEqual(map_result.returncode, 0, map_result.stdout)
        self.assertIn("ragflow_grounded_qa_evidence_map_report_v1", map_result.stdout)
        self.assertIn("RAGFlow QA Evidence Map Report", map_report_md_text)
        self.assertEqual(evidence_map_payload["schema"], "ragflow_grounded_qa_evidence_map_v1")
        self.assertEqual(evidence_map_payload["items"][0]["expected_chunks"], ["sha256:" + "b" * 64])
        self.assertEqual(evidence_map_payload["summary"]["evidence_mapping_coverage"], 1.0)
        self.assertEqual(evidence_map_payload["summary"]["evidence_mapping_confidence"], 1.0)

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
        self.assertTrue(payload["metadata_summary"]["ok"])
        self.assertEqual(payload["metadata_summary"]["tag_count"], 1)
        self.assertIn("q1", report_text)
        self.assertIn("Metadata Summary", report_text)

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
