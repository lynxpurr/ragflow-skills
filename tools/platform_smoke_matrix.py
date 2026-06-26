#!/usr/bin/env python3
"""Run cross-platform smoke checks for public RAGFlow skill artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from build_release import build_release


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
PROFILE_PATH = ROOT / "skills" / "ragflow-kb-build" / "templates" / "default-en-768.json"


@dataclass(frozen=True)
class PlatformProfile:
    id: str
    platform: str
    runtime_mode: str
    config_mode: str
    notes: str


PLATFORM_PROFILES: tuple[PlatformProfile, ...] = (
    PlatformProfile(
        id="hermes-local-source",
        platform="Hermes local",
        runtime_mode="source-pythonpath",
        config_mode="cli",
        notes="Development-style smoke using the source runtime on PYTHONPATH.",
    ),
    PlatformProfile(
        id="hermes-local-vendor",
        platform="Hermes local",
        runtime_mode="vendored-release",
        config_mode="cli",
        notes="Release artifact smoke using skill-local _vendor runtime.",
    ),
    PlatformProfile(
        id="claude-code-cli",
        platform="Claude Code",
        runtime_mode="vendored-release",
        config_mode="cli",
        notes="CLI-only smoke with no editable install.",
    ),
    PlatformProfile(
        id="opencode-cli",
        platform="opencode",
        runtime_mode="vendored-release",
        config_mode="cli",
        notes="CLI-only smoke for opencode-style programming agents.",
    ),
    PlatformProfile(
        id="strict-vendor-env",
        platform="Strict vendor/env runner",
        runtime_mode="vendored-release",
        config_mode="env",
        notes="Compatibility stress profile with no editable install and env-provided RAGFlow config.",
    ),
    PlatformProfile(
        id="artifact-runner-cli",
        platform="Artifact-oriented CLI runner",
        runtime_mode="vendored-release",
        config_mode="env",
        notes="CLI smoke writes handoff, evidence, and validation report artifacts.",
    ),
    PlatformProfile(
        id="openclaw-cli-v1",
        platform="OpenClaw",
        runtime_mode="vendored-release",
        config_mode="cli",
        notes="V1 CLI path; long-running serve mode is intentionally deferred.",
    ),
)

PROFILE_ALIASES = {
    "saas-sandbox-https": "strict-vendor-env",
    "manus-artifact-cli": "artifact-runner-cli",
}


def _minimal_env(profile: PlatformProfile) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
    }
    if profile.runtime_mode == "source-pythonpath":
        env["PYTHONPATH"] = str(RUNTIME_SRC)
    if profile.config_mode == "env":
        env["RAGFLOW_BASE_URL"] = "https://ragflow.example.test"
        env["RAGFLOW_API_KEY"] = "test-key"
    return env


def _scripts_root(profile: PlatformProfile, dist_dir: Path) -> Path:
    if profile.runtime_mode == "source-pythonpath":
        return ROOT / "skills"
    return dist_dir


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 30.0,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": f"timed out after {timeout} seconds",
            "ok": False,
        }
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ok": result.returncode == 0,
    }


def _record_command_check(
    checks: list[dict[str, Any]],
    name: str,
    result: dict[str, Any],
    *,
    required_stdout: str | None = None,
) -> bool:
    ok = bool(result["ok"])
    error = ""
    if ok and required_stdout and required_stdout not in result["stdout"]:
        ok = False
        error = f"stdout did not contain {required_stdout!r}"
    elif not ok:
        error = result["stderr"] or result["stdout"] or f"exit {result['returncode']}"
    checks.append(
        {
            "name": name,
            "ok": ok,
            "returncode": result["returncode"],
            "error": error,
        }
    )
    return ok


def _write_input_doc(workspace: Path) -> Path:
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "platform-smoke.md").write_text(
        "# Platform Smoke\n\nThis document contains a known term for portable validation.\n",
        encoding="utf-8",
    )
    return input_dir


def _write_fake_mineru_cli(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "out_dir = Path(args[args.index('-o') + 1])\n"
        "source = Path(args[args.index('-p') + 1])\n"
        "backend = args[args.index('-b') + 1]\n"
        "images_dir = out_dir / 'images'\n"
        "images_dir.mkdir(parents=True, exist_ok=True)\n"
        "(images_dir / 'chart.jpg').write_bytes(b'fake image bytes')\n"
        "(out_dir / (source.stem + '.md')).write_text(\n"
        "    f'# MinerU CLI Smoke\\n\\nConverted through mineru-cli backend={backend}.\\n\\n![chart](images/chart.jpg)\\n',\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run_mineru_env_check(
    *,
    profile: PlatformProfile,
    convert_script: Path,
    workspace: Path,
    checks: list[dict[str, Any]],
    env: dict[str, str],
) -> Path | None:
    if profile.config_mode != "env":
        return None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path.endswith("/parse"):
                body = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "markdown": "# MinerU Sync Service Smoke\n\nConverted through mineru-sync env config.\n"
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self.path.endswith("/parse/file"):
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(
                {
                    "code": 0,
                    "data": {
                        "task_id": "smoke-task",
                        "file_url": f"http://127.0.0.1:{self.server.server_port}/upload/smoke-task",
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(204)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/parse/smoke-task":
                body = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "state": "done",
                            "markdown_url": f"http://127.0.0.1:{self.server.server_port}/markdown/smoke-task.md",
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/markdown/smoke-task.md":
                body = b"# MinerU Service Smoke\n\nConverted through MINERU_* env config.\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            return

    mineru_input = workspace / "mineru-input"
    mineru_output = workspace / "mineru-handoff"
    mineru_cli_output = workspace / "mineru-cli-handoff"
    mineru_sync_output = workspace / "mineru-sync-handoff"
    mineru_input.mkdir(parents=True, exist_ok=True)
    (mineru_input / "mineru.pdf").write_bytes(b"%PDF mineru service smoke")
    fake_mineru_cli = _write_fake_mineru_cli(workspace / "mineru")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        mineru_cli_env = {
            **env,
            "DOC_TO_MD_BACKEND": "auto",
            "MINERU_CLI_PATH": str(fake_mineru_cli),
            "MINERU_CLI_BACKEND": "pipeline",
            "MINERU_TIMEOUT": "5",
        }
        cli_result = _run_command(
            [
                sys.executable,
                str(convert_script),
                "--input",
                str(mineru_input),
                "--output",
                str(mineru_cli_output),
                "--json",
            ],
            cwd=workspace,
            env=mineru_cli_env,
        )
        mineru_env = {
            **env,
            "DOC_TO_MD_BACKEND": "mineru",
            "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "MINERU_API_KEY": "smoke-key",
            "MINERU_TIMEOUT": "5",
            "MINERU_POLL_INTERVAL": "0.1",
        }
        result = _run_command(
            [
                sys.executable,
                str(convert_script),
                "--input",
                str(mineru_input),
                "--output",
                str(mineru_output),
                "--json",
            ],
            cwd=workspace,
            env=mineru_env,
        )
        mineru_sync_env = {
            **env,
            "DOC_TO_MD_BACKEND": "mineru-sync",
            "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}/sync",
            "MINERU_API_KEY": "smoke-key",
            "MINERU_TIMEOUT": "5",
        }
        sync_result = _run_command(
            [
                sys.executable,
                str(convert_script),
                "--input",
                str(mineru_input),
                "--output",
                str(mineru_sync_output),
                "--json",
            ],
            cwd=workspace,
            env=mineru_sync_env,
        )
        backend_probe_result = _run_command(
            [
                sys.executable,
                str(convert_script),
                "backend",
                "probe",
                "--backend",
                "mineru-cli",
                "--mineru-cli-path",
                str(fake_mineru_cli),
                "--report-json",
                str(workspace / "backend_probe.json"),
                "--report-md",
                str(workspace / "backend_probe.md"),
                "--json",
            ],
            cwd=workspace,
            env=env,
        )
        backend_warmup_result = _run_command(
            [
                sys.executable,
                str(convert_script),
                "backend",
                "warmup",
                "--backend",
                "mineru-cli",
                "--fixture",
                str(mineru_input / "mineru.pdf"),
                "--mineru-cli-path",
                str(fake_mineru_cli),
                "--report-json",
                str(workspace / "backend_warmup.json"),
                "--report-md",
                str(workspace / "backend_warmup.md"),
                "--json",
                "--fail-on-failed",
            ],
            cwd=workspace,
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    _record_command_check(
        checks,
        "doc-to-md mineru-cli auto backend",
        cli_result,
        required_stdout='"ok": true',
    )
    _record_command_check(
        checks,
        "doc-to-md mineru env backend",
        result,
        required_stdout='"ok": true',
    )
    _record_command_check(
        checks,
        "doc-to-md mineru-sync env backend",
        sync_result,
        required_stdout='"ok": true',
    )
    _record_command_check(
        checks,
        "doc-to-md backend probe",
        backend_probe_result,
        required_stdout='"schema": "ragflow_doc_backend_probe_report_v1"',
    )
    _record_command_check(
        checks,
        "doc-to-md backend warmup",
        backend_warmup_result,
        required_stdout='"schema": "ragflow_doc_backend_warmup_report_v1"',
    )
    markdown_path = mineru_output / "documents" / "mineru.md"
    ok = markdown_path.exists() and "MinerU Service Smoke" in markdown_path.read_text(
        encoding="utf-8"
    )
    checks.append(
        {
            "name": "mineru service markdown produced",
            "ok": ok,
            "returncode": 0 if ok else 1,
            "error": "" if ok else f"missing or invalid {markdown_path}",
        }
    )
    cli_markdown_path = mineru_cli_output / "documents" / "mineru.md"
    cli_ok = cli_markdown_path.exists() and "MinerU CLI Smoke" in cli_markdown_path.read_text(
        encoding="utf-8"
    )
    checks.append(
        {
            "name": "mineru-cli markdown produced",
            "ok": cli_ok,
            "returncode": 0 if cli_ok else 1,
            "error": "" if cli_ok else f"missing or invalid {cli_markdown_path}",
        }
    )
    cli_image_path = mineru_cli_output / "documents" / "images" / "chart.jpg"
    cli_image_ok = cli_image_path.exists()
    checks.append(
        {
            "name": "mineru-cli local image asset copied",
            "ok": cli_image_ok,
            "returncode": 0 if cli_image_ok else 1,
            "error": "" if cli_image_ok else f"missing {cli_image_path}",
        }
    )
    cli_quality_path = mineru_cli_output / "quality_report.json"
    cli_quality_status = None
    if cli_quality_path.exists():
        cli_quality_status = json.loads(cli_quality_path.read_text(encoding="utf-8")).get("gate", {}).get("status")
    checks.append(
        {
            "name": "mineru-cli quality gate passes with local image",
            "ok": cli_quality_status == "PASS",
            "returncode": 0 if cli_quality_status == "PASS" else 1,
            "error": "" if cli_quality_status == "PASS" else f"expected PASS, got {cli_quality_status}",
        }
    )
    cli_runtime_path = mineru_cli_output / "runtime_report.json"
    cli_runtime_summary = None
    cli_runtime_ok = False
    if cli_runtime_path.exists():
        cli_runtime_payload = json.loads(cli_runtime_path.read_text(encoding="utf-8"))
        cli_runtime_summary = cli_runtime_payload.get("summary", {})
        cli_runtime_ok = (
            cli_runtime_payload.get("schema") == "ragflow_doc_runtime_report_v1"
            and cli_runtime_summary.get("process_attempts") == 1
            and cli_runtime_summary.get("success") == 1
        )
    checks.append(
        {
            "name": "mineru-cli runtime report summarizes process attempt",
            "ok": cli_runtime_ok,
            "returncode": 0 if cli_runtime_ok else 1,
            "error": "" if cli_runtime_ok else f"unexpected runtime summary: {cli_runtime_summary}",
        }
    )
    sync_markdown_path = mineru_sync_output / "documents" / "mineru.md"
    sync_ok = sync_markdown_path.exists() and "MinerU Sync Service Smoke" in sync_markdown_path.read_text(
        encoding="utf-8"
    )
    checks.append(
        {
            "name": "mineru-sync service markdown produced",
            "ok": sync_ok,
            "returncode": 0 if sync_ok else 1,
            "error": "" if sync_ok else f"missing or invalid {sync_markdown_path}",
        }
    )
    manifest_path = mineru_output / "doc_manifest.json"
    return manifest_path if manifest_path.exists() else None


def _run_model_provider_probe_check(
    *,
    build_script: Path,
    workspace: Path,
    artifacts_dir: Path,
    checks: list[dict[str, Any]],
    env: dict[str, str],
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/v1/llm/factories":
                body = json.dumps(
                    {
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
                ).encode("utf-8")
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

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_command(
            [
                sys.executable,
                str(build_script),
                "model-providers",
                "probe",
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--api-key",
                "smoke-key",
                "--embedding-model",
                "bge-m3",
                "--rerank-model",
                "bge-reranker",
                "--embedding-adapter-url",
                f"http://127.0.0.1:{server.server_port}/embeddings",
                "--rerank-adapter-url",
                f"http://127.0.0.1:{server.server_port}/rerank",
                "--report-json",
                str(artifacts_dir / "model_provider_probe.json"),
                "--report-md",
                str(artifacts_dir / "model_provider_probe.md"),
                "--redaction-report",
                str(artifacts_dir / "model_provider_redaction.json"),
                "--json",
            ],
            cwd=workspace,
            env=env,
        )
        _record_command_check(
            checks,
            "kb model-providers probe",
            result,
            required_stdout='"schema": "ragflow_model_provider_probe_report_v1"',
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_fake_kb_manifest(workspace: Path, artifacts_dir: Path) -> Path:
    manifest_path = artifacts_dir / "kb_manifest.json"
    payload = {
        "version": "0.1",
        "ragflow_base_url": "https://ragflow.example.test/api/v1",
        "dataset": {"id": "ds-platform-smoke", "name": "kb:platform-smoke"},
        "profile": {"id": "platform-smoke"},
        "documents": [
            {
                "document_id": "doc-platform-smoke",
                "source_path": str(workspace / "input" / "platform-smoke.md"),
                "markdown_path": str(workspace / "handoff" / "documents" / "platform-smoke.md"),
                "status": "smoke",
                "chunk_count": 1,
            }
        ],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _write_query_set(artifacts_dir: Path) -> Path:
    queries_path = artifacts_dir / "validation_queries.json"
    queries_path.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "q1",
                        "question": "Where is the known term?",
                        "expected_terms": ["known term"],
                        "expected_documents": ["platform-smoke.md"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return queries_path


def _write_qrels(artifacts_dir: Path) -> Path:
    qrels_path = artifacts_dir / "qrels.json"
    qrels_path.write_text(
        json.dumps({"q1": {"platform-smoke.md": 1}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return qrels_path


def _write_grounded_qa(artifacts_dir: Path) -> Path:
    qa_path = artifacts_dir / "qa.json"
    qa_path.write_text(
        json.dumps(
            {
                "schema": "ragflow_grounded_qa_v1",
                "items": [
                    {
                        "id": "qa-q1",
                        "query_id": "q1",
                        "question": "Where is the known term?",
                        "answer": "This document contains a known term for portable validation.",
                        "evidence": [
                            {
                                "document": "platform-smoke.md",
                                "text": "This document contains a known term for portable validation.",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return qa_path


def _write_benchmark_report(path: Path, *, mrr: float) -> Path:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "dataset": {"id": "ds-platform-smoke", "name": "kb:platform-smoke"},
                "benchmark": {
                    "metrics": {
                        "query_count": 1,
                        "hit_rate": 1.0,
                        "mrr": mrr,
                        "precision_at_k": 0.5,
                        "recall_at_k": 1.0,
                        "ndcg_at_k": mrr,
                        "map_at_k": mrr,
                        "empty_result_rate": 0.0,
                        "supporting_document_coverage": 1.0,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _write_suppression_input(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "ok": False,
                "level": "benchmark",
                "dataset": {"id": "ds-platform-smoke", "name": "kb:platform-smoke"},
                "cases": [
                    {
                        "id": "q1",
                        "question": "Where is the known term?",
                        "passed": False,
                        "document_hits": ["platform-smoke.md"],
                        "metadata": {"type": "fact", "allowed_tags": ["example-tag"]},
                        "top_chunks": [
                            {
                                "content": "Known bridge term appears in an unrelated finance source.",
                                "document_name": "finance.md",
                                "document_id": "doc-finance",
                                "chunk_id": "wrong-1",
                                "raw": {
                                    "content_with_weight": "Known bridge term appears in an unrelated finance source.",
                                    "docnm_kwd": "finance.md",
                                    "doc_id": "doc-finance",
                                    "id": "wrong-1",
                                    "tags": ["example-tag", "finance"],
                                },
                            }
                        ],
                    }
                ],
                "benchmark": {
                    "metrics": {"wrong_document_rate": 1.0, "tag_pollution_rate": 1.0},
                    "per_query": [{"id": "q1", "wrong_document_count": 1, "unexpected_tag_count": 1}],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _runtime_args(profile: PlatformProfile) -> list[str]:
    if profile.config_mode == "env":
        return []
    return ["--base-url", "https://ragflow.example.test", "--api-key", "test-key"]


def _write_query_runner(
    *,
    runner_path: Path,
    query_script: Path,
    kb_manifest: Path,
    artifacts_dir: Path,
    profile: PlatformProfile,
) -> None:
    runtime_args = _runtime_args(profile)
    runner_path.write_text(
        f"""\
from __future__ import annotations

import contextlib
import importlib.util
import json
from io import StringIO
from pathlib import Path

script = Path({str(query_script)!r})
kb_manifest = Path({str(kb_manifest)!r})
artifacts_dir = Path({str(artifacts_dir)!r})
runtime_args = {runtime_args!r}

spec = importlib.util.spec_from_file_location("platform_query_cli", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
        return {{
            "data": {{
                "chunks": [
                    {{
                        "content_with_weight": f"portable validation chunk with known term for {{question}}",
                        "docnm_kwd": "platform-smoke.md",
                        "similarity": 0.98,
                        "kb_id": dataset_ids[0],
                    }}
                ]
            }}
        }}


module.RAGFlowClient = FakeClient
payloads = []
for mode, extra, output_name in [
    ("direct", ["--json"], "query_direct.json"),
    (
        "agentic",
        [
            "--host-assisted",
            "--json",
            "--trace-json",
            str(artifacts_dir / "query_trace.json"),
            "--trace-md",
            str(artifacts_dir / "query_trace.md"),
        ],
        "query_host_assisted.json",
    ),
]:
    argv = (
        runtime_args
        + [
            "ask",
            "Where is the known term?",
            "--kb-manifest",
            str(kb_manifest),
            "--mode",
            mode,
        ]
        + extra
    )
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = module.main(argv)
    if code != 0:
        raise SystemExit(code)
    payload = json.loads(stdout.getvalue())
    if not payload.get("ok") or not payload.get("chunks"):
        raise SystemExit(3)
    if not payload.get("evidence"):
        raise SystemExit(5)
    if payload.get("retrieval_status") != "success":
        raise SystemExit(20)
    if payload.get("retrieval_status_report", {{}}).get("schema") != "ragflow_retrieval_status_v1":
        raise SystemExit(21)
    (artifacts_dir / output_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\\n",
        encoding="utf-8",
    )
    payloads.append({{"mode": mode, "chunk_count": len(payload.get("chunks", []))}})

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    agentic_retrieval_code = module.main(
        runtime_args
        + [
            "ask",
            "Compare runtime configuration and metadata routing tradeoffs",
            "--kb-manifest",
            str(kb_manifest),
            "--mode",
            "agentic",
            "--host-assisted",
            "--max-subqueries",
            "2",
            "--reflection-budget",
            "1",
            "--include-trace",
            "--json",
        ]
    )
if agentic_retrieval_code != 0:
    raise SystemExit(agentic_retrieval_code)
agentic_retrieval_payload = json.loads(stdout.getvalue())
agentic_plan = agentic_retrieval_payload.get("agentic_plan", {{}})
if agentic_plan.get("schema") != "ragflow_agentic_plan_v1":
    raise SystemExit(25)
if agentic_plan.get("summary", {{}}).get("generated_subquery_count", 0) < 1:
    raise SystemExit(26)
if agentic_retrieval_payload.get("metadata", {{}}).get("retrieval_call_count", 0) < 2:
    raise SystemExit(27)
agentic_trace = agentic_retrieval_payload.get("agentic_trace", {{}})
if agentic_trace.get("schema") != "ragflow_agentic_trace_v1":
    raise SystemExit(28)
if agentic_trace.get("llm_calls") != 0:
    raise SystemExit(29)
if agentic_trace.get("cost_trace", {{}}).get("estimated_total_usd") != 0.0:
    raise SystemExit(30)
host_contract = agentic_retrieval_payload.get("host_synthesis_contract", {{}})
if host_contract.get("schema") != "ragflow_host_synthesis_contract_v1":
    raise SystemExit(31)
if host_contract.get("citation_policy", {{}}).get("compatible_with") != "audit-citations":
    raise SystemExit(32)
if not host_contract.get("citation_policy", {{}}).get("valid_citation_ids"):
    raise SystemExit(33)
(artifacts_dir / "query_agentic_retrieval.json").write_text(
    json.dumps(agentic_retrieval_payload, ensure_ascii=False, indent=2) + "\\n",
    encoding="utf-8",
)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    rewrite_code = module.main([
        "rewrite",
        "How do I configure runtime?",
        "--rewrite",
        "simple",
        "--report-json",
        str(artifacts_dir / "query_rewrite.json"),
        "--report-md",
        str(artifacts_dir / "query_rewrite.md"),
        "--json",
    ])
if rewrite_code != 0:
    raise SystemExit(rewrite_code)
rewrite_payload = json.loads(stdout.getvalue())
if rewrite_payload.get("schema") != "ragflow_query_rewrite_plan_v1":
    raise SystemExit(14)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    intent_code = module.main([
        "intent",
        "classify",
        "Compare runtime config versus metadata routing",
        "--report-json",
        str(artifacts_dir / "query_intent.json"),
        "--report-md",
        str(artifacts_dir / "query_intent.md"),
        "--json",
    ])
if intent_code != 0:
    raise SystemExit(intent_code)
intent_payload = json.loads(stdout.getvalue())
if intent_payload.get("schema") != "ragflow_query_intent_v1":
    raise SystemExit(18)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    intent_route_code = module.main([
        "intent",
        "route",
        "What about it?",
        "--report-json",
        str(artifacts_dir / "query_intent_route.json"),
        "--report-md",
        str(artifacts_dir / "query_intent_route.md"),
        "--json",
    ])
if intent_route_code != 0:
    raise SystemExit(intent_route_code)
intent_route_payload = json.loads(stdout.getvalue())
if intent_route_payload.get("schema") != "ragflow_query_route_decision_v1":
    raise SystemExit(19)

session_path = artifacts_dir / "query_session.json"
session_path.write_text(
    json.dumps(
        {{
            "schema": "ragflow_query_session_v1",
            "session_id": "platform-session",
            "turns": [
                {{"role": "user", "content": "How do I configure runtime settings?"}},
                {{"role": "assistant", "content": "Use a runtime config file."}},
            ],
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    session_inspect_code = module.main([
        "session",
        "inspect",
        "--session",
        str(session_path),
        "--report-json",
        str(artifacts_dir / "query_session_inspect.json"),
        "--report-md",
        str(artifacts_dir / "query_session_inspect.md"),
        "--json",
    ])
if session_inspect_code != 0:
    raise SystemExit(session_inspect_code)
session_inspect_payload = json.loads(stdout.getvalue())
if session_inspect_payload.get("schema") != "ragflow_query_session_inspection_v1":
    raise SystemExit(22)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    session_enrich_code = module.main([
        "session",
        "enrich",
        "What about it?",
        "--session",
        str(session_path),
        "--report-json",
        str(artifacts_dir / "query_session_enrich.json"),
        "--report-md",
        str(artifacts_dir / "query_session_enrich.md"),
        "--json",
    ])
if session_enrich_code != 0:
    raise SystemExit(session_enrich_code)
session_enrich_payload = json.loads(stdout.getvalue())
if session_enrich_payload.get("schema") != "ragflow_query_session_enrichment_v1":
    raise SystemExit(23)
if not session_enrich_payload.get("context_applied"):
    raise SystemExit(24)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    agentic_plan_code = module.main([
        "agentic-plan",
        "Compare runtime configuration and metadata routing tradeoffs",
        "--max-subqueries",
        "3",
        "--reflection-budget",
        "1",
        "--report-json",
        str(artifacts_dir / "query_agentic_plan.json"),
        "--report-md",
        str(artifacts_dir / "query_agentic_plan.md"),
        "--json",
    ])
if agentic_plan_code != 0:
    raise SystemExit(agentic_plan_code)
agentic_plan_payload = json.loads(stdout.getvalue())
if agentic_plan_payload.get("schema") != "ragflow_agentic_plan_v1":
    raise SystemExit(17)

multi_query_path = artifacts_dir / "query_multi_input.json"
multi_query_path.write_text(
    json.dumps({{"queries": [{{"id": "rewrite-cn", "query": "运行时 配置"}}]}}, ensure_ascii=False, indent=2)
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    multi_code = module.main(
        runtime_args
        + [
            "ask",
            "How do I configure runtime?",
            "--kb-manifest",
            str(kb_manifest),
            "--mode",
            "direct",
            "--rewrite",
            "simple",
            "--multi-query",
            str(multi_query_path),
            "--trace-json",
            str(artifacts_dir / "query_multi_trace.json"),
            "--include-trace",
            "--json",
        ]
    )
if multi_code != 0:
    raise SystemExit(multi_code)
multi_payload = json.loads(stdout.getvalue())
if "retrievals" not in multi_payload or not multi_payload.get("trace", {{}}).get("rewrite"):
    raise SystemExit(15)
if multi_payload.get("retrieval_status") != "success":
    raise SystemExit(20)
(artifacts_dir / "query_multi.json").write_text(
    json.dumps(multi_payload, ensure_ascii=False, indent=2) + "\\n",
    encoding="utf-8",
)

answer_path = artifacts_dir / "answer.md"
answer_path.write_text("The known term is present in the portable validation chunk [1].\\n", encoding="utf-8")
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    audit_code = module.main([
        "audit-citations",
        "--query-output",
        str(artifacts_dir / "query_host_assisted.json"),
        "--answer-file",
        str(answer_path),
        "--report-json",
        str(artifacts_dir / "citation_audit.json"),
        "--report-md",
        str(artifacts_dir / "citation_audit.md"),
        "--json",
    ])
if audit_code != 0:
    raise SystemExit(audit_code)
audit_payload = json.loads(stdout.getvalue())
if not audit_payload.get("ok"):
    raise SystemExit(6)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    answer_eval_code = module.main([
        "evaluate-answer",
        "--query-output",
        str(artifacts_dir / "query_host_assisted.json"),
        "--answer-file",
        str(answer_path),
        "--expected-term",
        "known term",
        "--require-citation",
        "--report-json",
        str(artifacts_dir / "query_answer_eval.json"),
        "--report-md",
        str(artifacts_dir / "query_answer_eval.md"),
        "--json",
    ])
if answer_eval_code != 0:
    raise SystemExit(answer_eval_code)
answer_eval_payload = json.loads(stdout.getvalue())
if answer_eval_payload.get("schema") != "ragflow_answer_evaluation_report_v1":
    raise SystemExit(16)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    diagnostic_code = module.main([
        "diagnose-result",
        "--query-output",
        str(artifacts_dir / "query_host_assisted.json"),
        "--trace-json",
        str(artifacts_dir / "query_trace.json"),
        "--citation-audit",
        str(artifacts_dir / "citation_audit.json"),
        "--expected-term",
        "known term",
        "--report-json",
        str(artifacts_dir / "query_diagnostic.json"),
        "--report-md",
        str(artifacts_dir / "query_diagnostic.md"),
        "--json",
    ])
if diagnostic_code != 0:
    raise SystemExit(diagnostic_code)
diagnostic_payload = json.loads(stdout.getvalue())
if not diagnostic_payload.get("ok"):
    raise SystemExit(7)

pollution_input = artifacts_dir / "query_pollution_input.json"
pollution_input.write_text(
    json.dumps(
        {{
            "ok": True,
            "question": "Where is the known term?",
            "dataset_ids": ["ds-platform-smoke"],
            "chunks": [
                {{
                    "content": "portable validation chunk with known term",
                    "document_name": "platform-smoke.md",
                    "similarity": 0.98,
                }},
                {{
                    "content": "translated bridge term only match",
                    "document_name": "translated.md",
                    "similarity": 0.4,
                }},
            ],
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    pollution_code = module.main([
        "pollution-report",
        "--query-output",
        str(pollution_input),
        "--expanded-term",
        "translated",
        "--report-json",
        str(artifacts_dir / "query_pollution.json"),
        "--report-md",
        str(artifacts_dir / "query_pollution.md"),
        "--json",
    ])
if pollution_code != 0:
    raise SystemExit(pollution_code)
pollution_payload = json.loads(stdout.getvalue())
if pollution_payload.get("schema") != "ragflow_query_pollution_report_v1":
    raise SystemExit(8)

rerank_input = artifacts_dir / "query_rerank.json"
rerank_input.write_text(
    json.dumps(
        {{
            "results": [
                {{"chunk_id": "platform-translated", "score": 0.91}},
                {{"chunk_id": "platform-known", "score": 0.42}},
            ]
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
rerank_query_input = artifacts_dir / "query_rerank_input.json"
rerank_query_input.write_text(
    json.dumps(
        {{
            "ok": True,
            "question": "Where is the translated bridge term?",
            "dataset_ids": ["ds-platform-smoke"],
            "chunks": [
                {{
                    "chunk_id": "platform-known",
                    "content": "portable validation chunk with known term",
                    "document_name": "platform-smoke.md",
                    "similarity": 0.98,
                }},
                {{
                    "chunk_id": "platform-translated",
                    "content": "translated bridge term only match",
                    "document_name": "translated.md",
                    "similarity": 0.4,
                }},
            ],
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    rerank_code = module.main([
        "rerank-ab",
        "--query-output",
        str(rerank_query_input),
        "--rerank-json",
        str(rerank_input),
        "--expected-term",
        "translated bridge",
        "--expected-chunk",
        "platform-translated",
        "--top-k",
        "1",
        "--report-json",
        str(artifacts_dir / "query_rerank_ab.json"),
        "--report-md",
        str(artifacts_dir / "query_rerank_ab.md"),
        "--json",
    ])
if rerank_code != 0:
    raise SystemExit(rerank_code)
rerank_payload = json.loads(stdout.getvalue())
if rerank_payload.get("schema") != "ragflow_query_rerank_ab_report_v1":
    raise SystemExit(9)

cross_language_candidate = artifacts_dir / "query_cross_language_candidate.json"
cross_language_candidate.write_text(
    json.dumps(
        {{
            "ok": True,
            "question": "Where is the translated bridge term?",
            "dataset_ids": ["ds-platform-smoke"],
            "chunks": [
                {{
                    "chunk_id": "platform-translated",
                    "content": "translated bridge term only match",
                    "document_name": "translated.md",
                    "similarity": 0.7,
                }},
                {{
                    "chunk_id": "platform-known",
                    "content": "portable validation chunk with known term",
                    "document_name": "platform-smoke.md",
                    "similarity": 0.62,
                }},
            ],
            "metadata": {{"retrieval_ms": 12.0}},
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    cross_language_code = module.main([
        "cross-language-ab",
        "--baseline-output",
        str(rerank_query_input),
        "--candidate-output",
        str(cross_language_candidate),
        "--baseline-label",
        "original",
        "--candidate-label",
        "translated",
        "--report-json",
        str(artifacts_dir / "query_cross_language_ab.json"),
        "--report-md",
        str(artifacts_dir / "query_cross_language_ab.md"),
        "--json",
    ])
if cross_language_code != 0:
    raise SystemExit(cross_language_code)
cross_language_payload = json.loads(stdout.getvalue())
if cross_language_payload.get("schema") != "ragflow_cross_language_ab_report_v1":
    raise SystemExit(12)

fusion_source = artifacts_dir / "query_fusion_source.json"
fusion_source.write_text(
    json.dumps(
        {{
            "ok": True,
            "question": "Where is the known term?",
            "dataset_ids": ["ds-platform-secondary"],
            "chunks": [
                {{
                    "chunk_id": "platform-secondary",
                    "content": "secondary KB chunk with known term",
                    "document_name": "secondary.md",
                    "similarity": 0.88,
                }},
                {{
                    "chunk_id": "platform-known",
                    "content": "portable validation chunk with known term",
                    "document_name": "platform-smoke.md",
                    "similarity": 0.75,
                }},
            ],
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    fusion_code = module.main([
        "fusion",
        "--query-output",
        str(rerank_query_input),
        "--query-output",
        str(fusion_source),
        "--top-k",
        "3",
        "--report-json",
        str(artifacts_dir / "query_fusion.json"),
        "--report-md",
        str(artifacts_dir / "query_fusion.md"),
        "--json",
    ])
if fusion_code != 0:
    raise SystemExit(fusion_code)
fusion_payload = json.loads(stdout.getvalue())
if fusion_payload.get("schema") != "ragflow_fusion_report_v1":
    raise SystemExit(10)

fusion_cases = artifacts_dir / "query_fusion_cases.json"
fusion_cases.write_text(
    json.dumps(
        {{
            "cases": [
                {{
                    "id": "platform-shared-evidence",
                    "query_outputs": [rerank_query_input.name, fusion_source.name],
                    "top_k": 3,
                    "expected_top_chunk": "platform-known",
                    "expected_chunks": ["platform-known"],
                    "expected_terms": ["known term"],
                    "min_source_count": 2,
                }}
            ]
        }},
        ensure_ascii=False,
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    fusion_test_code = module.main([
        "fusion-test",
        "--cases",
        str(fusion_cases),
        "--report-json",
        str(artifacts_dir / "query_fusion_test.json"),
        "--report-md",
        str(artifacts_dir / "query_fusion_test.md"),
        "--json",
    ])
if fusion_test_code != 0:
    raise SystemExit(fusion_test_code)
fusion_test_payload = json.loads(stdout.getvalue())
if fusion_test_payload.get("schema") != "ragflow_fusion_test_report_v1":
    raise SystemExit(11)

stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    fallback_test_code = module.main([
        "fallback-test",
        "--report-json",
        str(artifacts_dir / "query_fallback_test.json"),
        "--report-md",
        str(artifacts_dir / "query_fallback_test.md"),
        "--json",
    ])
if fallback_test_code != 0:
    raise SystemExit(fallback_test_code)
fallback_test_payload = json.loads(stdout.getvalue())
if fallback_test_payload.get("schema") != "ragflow_query_fallback_test_report_v1":
    raise SystemExit(13)
if fallback_test_payload.get("summary", {{}}).get("covered_required_mode_count") != len(fallback_test_payload.get("required_failure_modes", [])):
    raise SystemExit(14)

print(json.dumps({{"ok": True, "payloads": payloads, "audit": audit_payload, "diagnostic": diagnostic_payload, "pollution": pollution_payload, "rerank": rerank_payload, "cross_language": cross_language_payload, "fusion": fusion_payload, "fusion_test": fusion_test_payload, "fallback_test": fallback_test_payload}}, ensure_ascii=False))
""",
        encoding="utf-8",
    )


def _write_validate_runner(
    *,
    runner_path: Path,
    validate_script: Path,
    kb_manifest: Path,
    queries_path: Path,
    metadata_path: Path,
    artifacts_dir: Path,
    profile: PlatformProfile,
) -> None:
    runtime_args = _runtime_args(profile)
    report_json = artifacts_dir / "validation_report.json"
    report_md = artifacts_dir / "validation_report.md"
    runner_path.write_text(
        f"""\
from __future__ import annotations

import contextlib
import importlib.util
import json
from io import StringIO
from pathlib import Path

script = Path({str(validate_script)!r})
kb_manifest = Path({str(kb_manifest)!r})
queries_path = Path({str(queries_path)!r})
metadata_path = Path({str(metadata_path)!r})
report_json = Path({str(report_json)!r})
report_md = Path({str(report_md)!r})
runtime_args = {runtime_args!r}

spec = importlib.util.spec_from_file_location("platform_validate_cli", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, config):
        self.config = config

    def retrieve(self, *, question, dataset_ids, top_k=3):
        return {{
            "data": {{
                "chunks": [
                    {{
                        "content_with_weight": "portable validation chunk with known term",
                        "docnm_kwd": "platform-smoke.md",
                        "similarity": 0.98,
                    }}
                ]
            }}
        }}


module.RAGFlowClient = FakeClient
argv = runtime_args + [
    "--kb-manifest",
    str(kb_manifest),
    "--level",
    "regression",
    "--queries",
    str(queries_path),
    "--metadata",
    str(metadata_path),
    "--report-json",
    str(report_json),
    "--report-md",
    str(report_md),
]
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    code = module.main(argv)
if code != 0:
    raise SystemExit(code)
payload = json.loads(stdout.getvalue())
if not payload.get("ok") or not payload.get("metadata_summary", {{}}).get("ok") or not report_json.exists() or not report_md.exists():
    raise SystemExit(4)
print(json.dumps({{"ok": True, "report_json": str(report_json), "report_md": str(report_md)}}, ensure_ascii=False))
""",
        encoding="utf-8",
    )


def _run_imported_cli_check(
    *,
    name: str,
    runner_path: Path,
    checks: list[dict[str, Any]],
    cwd: Path,
    env: dict[str, str],
) -> bool:
    result = _run_command([sys.executable, str(runner_path)], cwd=cwd, env=env)
    return _record_command_check(checks, name, result, required_stdout='"ok": true')


def run_profile(profile: PlatformProfile, *, dist_dir: Path, work_root: Path) -> dict[str, Any]:
    workspace = work_root / profile.id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir()

    env = _minimal_env(profile)
    script_root = _scripts_root(profile, dist_dir)
    input_dir = _write_input_doc(workspace)
    checks: list[dict[str, Any]] = []

    convert_script = script_root / "ragflow-doc-to-md" / "scripts" / "convert.py"
    handoff_dir = workspace / "handoff"
    convert_result = _run_command(
        [
            sys.executable,
            str(convert_script),
            "--input",
            str(input_dir),
            "--output",
            str(handoff_dir),
            "--mode",
            "passthrough",
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(checks, "doc-to-md passthrough", convert_result, required_stdout='"ok": true')
    doc_manifest = handoff_dir / "doc_manifest.json"
    image_input = workspace / "image-fallback-input"
    image_input.mkdir(parents=True, exist_ok=True)
    (image_input / "diagram.png").write_bytes(b"fake platform image fallback bytes")
    image_handoff = workspace / "image-fallback-handoff"
    image_fallback_result = _run_command(
        [
            sys.executable,
            str(convert_script),
            "--input",
            str(image_input),
            "--output",
            str(image_handoff),
            "--backend",
            "remote",
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md image fallback",
        image_fallback_result,
        required_stdout='"status": "PASS_WITH_REVIEW"',
    )
    image_quality = image_handoff / "quality_report.json"
    image_quality_status = None
    image_count = 0
    if image_quality.exists():
        image_quality_status = json.loads(image_quality.read_text(encoding="utf-8")).get("gate", {}).get("status")
        image_count = len(list((image_handoff / "documents" / "images").glob("diagram-*.png")))
    image_review_ok = image_quality_status == "PASS_WITH_REVIEW" and image_count == 1
    checks.append(
        {
            "name": "image fallback preserves source image with review gate",
            "ok": image_review_ok,
            "returncode": 0 if image_review_ok else 1,
            "error": "" if image_review_ok else f"status={image_quality_status}, copied_images={image_count}",
        }
    )
    package_result = _run_command(
        [
            sys.executable,
            str(convert_script),
            "package",
            "--handoff",
            str(handoff_dir),
            "--rich",
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md rich handoff package",
        package_result,
        required_stdout='"schema": "ragflow_handoff_package_v1"',
    )
    for rich_name in (
        "metadata.json",
        "artifact_index.json",
        "profile_suggestions.json",
        "retrieval_hints.json",
        "assistant_profile.json",
        "assistant_test_plan.json",
    ):
        rich_path = handoff_dir / rich_name
        checks.append(
            {
                "name": f"rich handoff {rich_name} produced",
                "ok": rich_path.exists(),
                "returncode": 0 if rich_path.exists() else 1,
                "error": "" if rich_path.exists() else f"missing {rich_path}",
            }
        )
    postprocess_dir = workspace / "postprocessed-handoff"
    postprocess_result = _run_command(
        [
            sys.executable,
            str(convert_script),
            "postprocess",
            "--doc-manifest",
            str(doc_manifest),
            "--profile",
            "safe",
            "--output",
            str(postprocess_dir),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md postprocess safe",
        postprocess_result,
        required_stdout='"schema": "doc_postprocess_report_v1"',
    )
    postprocess_report = postprocess_dir / "postprocess_report.json"
    checks.append(
        {
            "name": "postprocess report produced",
            "ok": postprocess_report.exists(),
            "returncode": 0 if postprocess_report.exists() else 1,
            "error": "" if postprocess_report.exists() else f"missing {postprocess_report}",
        }
    )
    mineru_doc_manifest = _run_mineru_env_check(
        profile=profile,
        convert_script=convert_script,
        workspace=workspace,
        checks=checks,
        env=env,
    )
    checks.append(
        {
            "name": "doc_manifest produced",
            "ok": doc_manifest.exists(),
            "returncode": 0 if doc_manifest.exists() else 1,
            "error": "" if doc_manifest.exists() else f"missing {doc_manifest}",
        }
    )

    build_script = script_root / "ragflow-kb-build" / "scripts" / "build.py"
    build_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:platform-smoke",
            "--profile",
            str(PROFILE_PATH),
            "--dry-run",
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(checks, "kb-build dry-run", build_result, required_stdout='"dry_run": true')
    _run_model_provider_probe_check(
        build_script=build_script,
        workspace=workspace,
        artifacts_dir=artifacts_dir,
        checks=checks,
        env=env,
    )
    inspect_handoff_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "inspect-handoff",
            "--handoff",
            str(handoff_dir),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build inspect rich handoff",
        inspect_handoff_result,
        required_stdout='"schema": "ragflow_handoff_inspection_v1"',
    )
    metadata_template = artifacts_dir / "metadata.template.json"
    metadata_lint_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "metadata",
            "generate-template",
            "--doc-manifest",
            str(doc_manifest),
            "--output",
            str(metadata_template),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb metadata generate-template",
        metadata_lint_result,
        required_stdout='"schema": "ragflow_metadata_v1"',
    )
    metadata_lint_report = _run_command(
        [
            sys.executable,
            str(build_script),
            "metadata",
            "lint",
            "--metadata",
            str(metadata_template),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb metadata lint",
        metadata_lint_report,
        required_stdout='"schema": "ragflow_metadata_lint_report_v1"',
    )
    topology_advice = artifacts_dir / "kb_topology_advice.json"
    topology_advice_md = artifacts_dir / "kb_topology_advice.md"
    topology_advice_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "topology",
            "advise",
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:platform-topology",
            "--metadata",
            str(metadata_template),
            "--retrieval-hints",
            str(handoff_dir / "retrieval_hints.json"),
            "--future-growth",
            "high",
            "--output",
            str(topology_advice),
            "--report-md",
            str(topology_advice_md),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb topology advise",
        topology_advice_result,
        required_stdout='"schema": "kb_topology_advice_v1"',
    )
    tagset_template = artifacts_dir / "tagset.template.json"
    tagset_template_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "tagset",
            "generate-template",
            "--output",
            str(tagset_template),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb tagset generate-template",
        tagset_template_result,
        required_stdout='"schema": "ragflow_tagset_v1"',
    )
    tagset_report_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "tagset",
            "report",
            "--tagset",
            str(tagset_template),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb tagset report",
        tagset_report_result,
        required_stdout='"schema": "ragflow_tagset_report_v1"',
    )

    kb_manifest = _write_fake_kb_manifest(workspace, artifacts_dir)
    queries_path = _write_query_set(artifacts_dir)

    benchmark_dir = artifacts_dir / "benchmark"
    qrels_path = _write_qrels(artifacts_dir)
    qa_path = _write_grounded_qa(artifacts_dir)
    benchmark_import_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "benchmark",
            "import",
            "--queries",
            str(queries_path),
            "--qrels",
            str(qrels_path),
            "--qa",
            str(qa_path),
            "--output",
            str(benchmark_dir),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb benchmark import",
        benchmark_import_result,
        required_stdout='"schema": "ragflow_benchmark_import_report_v1"',
    )
    qa_generated = artifacts_dir / "qa.generated.json"
    qa_generate_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "qa",
            "generate",
            "--source-dir",
            str(input_dir),
            "--output",
            str(qa_generated),
            "--count",
            "1",
            "--min-span-chars",
            "20",
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb qa generate",
        qa_generate_result,
        required_stdout='"schema": "ragflow_grounded_qa_generate_report_v1"',
    )
    qa_validate_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "qa",
            "validate",
            "--qa",
            str(benchmark_dir / "qa.json"),
            "--source-dir",
            str(input_dir),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb qa validate",
        qa_validate_result,
        required_stdout='"schema": "ragflow_grounded_qa_validate_report_v1"',
    )
    chunk_snapshot = artifacts_dir / "chunk_snapshot.json"
    chunk_snapshot_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "snapshot-chunks",
            "--input",
            str(input_dir),
            "--output",
            str(chunk_snapshot),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb snapshot-chunks",
        chunk_snapshot_result,
        required_stdout='"schema": "ragflow_chunk_snapshot_report_v1"',
    )
    qa_evidence_map = artifacts_dir / "qa_evidence_map.json"
    qa_map_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "qa",
            "map-evidence",
            "--qa",
            str(benchmark_dir / "qa.json"),
            "--chunk-snapshot",
            str(chunk_snapshot),
            "--output",
            str(qa_evidence_map),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb qa map-evidence",
        qa_map_result,
        required_stdout='"schema": "ragflow_grounded_qa_evidence_map_report_v1"',
    )
    segment_metadata_report = artifacts_dir / "segment_metadata_report.json"
    segment_metadata_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "segment-metadata",
            "report",
            "--chunk-snapshot",
            str(chunk_snapshot),
            "--report-json",
            str(segment_metadata_report),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb segment-metadata report",
        segment_metadata_result,
        required_stdout='"schema": "ragflow_segment_metadata_report_v1"',
    )
    suppression_input = _write_suppression_input(artifacts_dir / "suppression_input.json")
    suppression_report = artifacts_dir / "suppression_report.json"
    suppression_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "suppression-report",
            "--report",
            str(suppression_input),
            "--tagset",
            str(tagset_template),
            "--report-json",
            str(suppression_report),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb suppression-report",
        suppression_result,
        required_stdout='"schema": "ragflow_suppression_report_v1"',
    )
    benchmark_preflight_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "benchmark",
            "preflight",
            "--manifest",
            str(benchmark_dir / "manifest.json"),
            "--chunk-snapshot",
            str(chunk_snapshot),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb benchmark preflight",
        benchmark_preflight_result,
        required_stdout='"schema": "ragflow_benchmark_preflight_report_v1"',
    )
    optimization_plan = artifacts_dir / "optimization_plan.json"
    optimize_plan_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "optimize",
            "--plan-only",
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:platform-smoke",
            "--profile",
            str(PROFILE_PATH),
            "--recommendation",
            "zh:notes",
            "--benchmark-manifest",
            str(benchmark_dir / "manifest.json"),
            "--metadata",
            str(metadata_template),
            "--chunk-snapshot",
            str(chunk_snapshot),
            "--run-id",
            "platform",
            "--output",
            str(optimization_plan),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb optimize plan-only",
        optimize_plan_result,
        required_stdout='"schema": "ragflow_optimization_plan_v1"',
    )
    optimization_cleanup_plan = artifacts_dir / "optimization_cleanup_plan.json"
    optimization_cleanup_plan_md = artifacts_dir / "optimization_cleanup_plan.md"
    optimize_cleanup_plan_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "optimize",
            "cleanup-plan",
            "--plan",
            str(optimization_plan),
            "--output",
            str(optimization_cleanup_plan),
            "--report-md",
            str(optimization_cleanup_plan_md),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb optimize cleanup-plan",
        optimize_cleanup_plan_result,
        required_stdout='"schema": "ragflow_optimization_cleanup_plan_v1"',
    )
    benchmark_sample_dir = artifacts_dir / "benchmark-sample"
    benchmark_sample_result = _run_command(
        [
            sys.executable,
            str(build_script),
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
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb benchmark sample",
        benchmark_sample_result,
        required_stdout='"schema": "ragflow_benchmark_sample_report_v1"',
    )
    current_benchmark_report = _write_benchmark_report(artifacts_dir / "benchmark_current.json", mrr=1.0)
    baseline_benchmark_report = _write_benchmark_report(artifacts_dir / "benchmark_baseline.json", mrr=0.8)
    benchmark_delta_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "benchmark",
            "delta",
            "--report",
            str(current_benchmark_report),
            "--baseline-report",
            str(baseline_benchmark_report),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb benchmark delta",
        benchmark_delta_result,
        required_stdout='"schema": "ragflow_benchmark_delta_report_v1"',
    )
    benchmark_suggest_json = artifacts_dir / "benchmark_suggestions.json"
    benchmark_suggest_md = artifacts_dir / "benchmark_suggestions.md"
    benchmark_suggest_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "benchmark",
            "suggest",
            "--report",
            str(current_benchmark_report),
            "--baseline-report",
            str(baseline_benchmark_report),
            "--current-top-k",
            "3",
            "--current-similarity-threshold",
            "0.25",
            "--report-json",
            str(benchmark_suggest_json),
            "--report-md",
            str(benchmark_suggest_md),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb benchmark suggest",
        benchmark_suggest_result,
        required_stdout='"schema": "ragflow_benchmark_retrieval_suggestion_report_v1"',
    )
    profile_experiment_results = artifacts_dir / "profile_experiment_results.json"
    best_profile_report = artifacts_dir / "best_profile_report.md"
    optimize_summary_result = _run_command(
        [
            sys.executable,
            str(build_script),
            "optimize",
            "summarize",
            "--plan",
            str(optimization_plan),
            "--report",
            str(current_benchmark_report),
            "--report",
            str(baseline_benchmark_report),
            "--output",
            str(profile_experiment_results),
            "--report-md",
            str(best_profile_report),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb optimize summarize",
        optimize_summary_result,
        required_stdout='"schema": "ragflow_profile_experiment_results_v1"',
    )

    profile_script = script_root / "ragflow-kb-build" / "scripts" / "profile.py"
    profile_lint_result = _run_command(
        [
            sys.executable,
            str(profile_script),
            "lint",
            "--profile",
            str(PROFILE_PATH),
            "--report-md",
            str(artifacts_dir / "profile_lint.md"),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb profile lint",
        profile_lint_result,
        required_stdout='"schema": "ragflow_profile_lint_report_v1"',
    )
    profile_experiment_result = _run_command(
        [
            sys.executable,
            str(profile_script),
            "experiment",
            "--base-profile",
            str(PROFILE_PATH),
            "--set",
            "auto_keywords=0,3",
            "--set",
            "auto_questions=0",
            "--set",
            "retrieval.top_k=3,5",
            "--candidate-set",
            str(artifacts_dir / "candidate_profile_set.json"),
            "--report-md",
            str(artifacts_dir / "profile_experiment_matrix.md"),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "kb profile experiment",
        profile_experiment_result,
        required_stdout='"schema": "ragflow_enrichment_experiment_report_v1"',
    )

    query_script = script_root / "ragflow-query" / "scripts" / "query.py"
    fake_lan_endpoint = "https://" + ".".join(("192", "168", "10", "20")) + ":9380"
    fake_vpn_endpoint = "vpn=http://" + ".".join(("100", "64", "10", "20")) + ":8080/v1?token=fake-secret"
    endpoint_report_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "endpoint-report",
            "--base-url",
            fake_lan_endpoint,
            "--api-key",
            "platform-fake-key",
            "--endpoint",
            fake_vpn_endpoint,
            "--report-json",
            str(artifacts_dir / "query_endpoint_report.json"),
            "--report-md",
            str(artifacts_dir / "query_endpoint_report.md"),
            "--redaction-report",
            str(artifacts_dir / "query_endpoint_redaction.json"),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query endpoint-report",
        endpoint_report_result,
        required_stdout='"schema": "ragflow_query_endpoint_report_v1"',
    )
    fallback_test_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "fallback-test",
            "--report-json",
            str(artifacts_dir / "query_fallback_test.json"),
            "--report-md",
            str(artifacts_dir / "query_fallback_test.md"),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query fallback-test",
        fallback_test_result,
        required_stdout='"schema": "ragflow_query_fallback_test_report_v1"',
    )

    routing_config = artifacts_dir / "routing_config.json"
    route_queries = artifacts_dir / "route_queries.json"
    route_tie_queries = artifacts_dir / "route_tie_queries.json"
    route_centroids = artifacts_dir / "route_centroids.json"
    route_query_vector = artifacts_dir / "route_query_vector.json"
    routing_config.write_text(
        json.dumps(
            {
                "version": "0.1",
                "knowledge_bases": [
                    {
                        "name": "kb:platform-general",
                        "dataset_id": "ds-platform-general",
                        "hints": ["general", "platform"],
                    },
                    {
                        "name": "kb:platform-technical",
                        "dataset_id": "ds-platform-technical",
                        "hints": ["known term", "runtime"],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    route_queries.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "route-known-term",
                        "question": "Where is the known term in the runtime?",
                        "expected_kb": "kb:platform-technical",
                        "category": "exact",
                        "locale": "en",
                    },
                    {
                        "id": "route-short-query",
                        "question": "runtime",
                        "expected_kb": "kb:platform-technical",
                        "category": "short_query",
                        "locale": "en",
                    },
                    {
                        "id": "route-negative",
                        "question": "invoice refund policy",
                        "expected_no_route": True,
                        "category": "negative",
                        "locale": "en",
                        "negative_class": "out_of_scope",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    route_tie_queries.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "route-centroid-tie",
                        "question": "platform runtime",
                        "expected_kb": "kb:platform-technical",
                        "query_vector": [1.0, 0.0],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    route_centroids.write_text(
        json.dumps(
            {
                "schema": "ragflow_route_centroid_index_v1",
                "centroids": [
                    {"dataset_id": "ds-platform-general", "status": "ready", "vector": [0.0, 1.0]},
                    {"dataset_id": "ds-platform-technical", "status": "ready", "vector": [1.0, 0.0]},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    route_query_vector.write_text(json.dumps({"query_vector": [1.0, 0.0]}), encoding="utf-8")
    route_test_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "route-test",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-md",
            str(artifacts_dir / "route_test.md"),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-test",
        route_test_result,
        required_stdout='"accuracy": 1.0',
    )
    route_centroid_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "route",
            "platform runtime",
            "--routing-config",
            str(routing_config),
            "--centroid-index",
            str(route_centroids),
            "--query-vector-json",
            str(route_query_vector),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query route centroid tie-breaker",
        route_centroid_result,
        required_stdout='"tie_breaker": "centroid"',
    )
    route_centroid_test = _run_command(
        [
            sys.executable,
            str(query_script),
            "route-test",
            "--routing-config",
            str(routing_config),
            "--centroid-index",
            str(route_centroids),
            "--queries",
            str(route_tie_queries),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-test centroid tie-breaker",
        route_centroid_test,
        required_stdout='"accuracy": 1.0',
    )
    route_report_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "route-report",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-md",
            str(artifacts_dir / "route_report.md"),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-report",
        route_report_result,
        required_stdout='"ragflow_route_report_v1"',
    )
    route_diagnose_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "route-diagnose",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-md",
            str(artifacts_dir / "route_diagnose.md"),
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-diagnose",
        route_diagnose_result,
        required_stdout='"ragflow_route_diagnose_report_v1"',
    )
    centroid_plan_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "centroid",
            "build",
            "--plan-only",
            "--kb-manifest",
            str(kb_manifest),
            "--chunk-snapshot",
            str(chunk_snapshot),
            "--index-output",
            str(artifacts_dir / "centroids.json"),
            "--embedding-model",
            "example-embedding",
            "--embedding-dimension",
            "3",
            "--report-json",
            str(artifacts_dir / "centroid_plan.json"),
            "--report-md",
            str(artifacts_dir / "centroid_plan.md"),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query centroid build plan-only",
        centroid_plan_result,
        required_stdout='"ragflow_route_centroid_build_plan_v1"',
    )
    centroid_chunk_snapshot = artifacts_dir / "centroid_chunk_snapshot.json"
    centroid_chunk_snapshot.write_text(
        json.dumps(
            {
                "schema": "ragflow_chunk_snapshot_v1",
                "chunks": [
                    {
                        "dataset_id": "ds-platform-smoke",
                        "document_name": "platform-smoke.md",
                        "chunk_id": "centroid-chunk-1",
                        "stable_hash": "sha256:platform-centroid-1",
                        "content": "Platform smoke can build centroids from snapshot-owned vectors.",
                        "embedding": [1.0, 0.0, 0.0],
                    },
                    {
                        "dataset_id": "ds-platform-smoke",
                        "document_name": "platform-smoke.md",
                        "chunk_id": "centroid-chunk-2",
                        "stable_hash": "sha256:platform-centroid-2",
                        "content": "Centroid build remains offline and writes checkpoint artifacts.",
                        "embedding": [0.0, 1.0, 0.0],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    centroid_build_result = _run_command(
        [
            sys.executable,
            str(query_script),
            "centroid",
            "build",
            "--kb-manifest",
            str(kb_manifest),
            "--chunk-snapshot",
            str(centroid_chunk_snapshot),
            "--index-output",
            str(artifacts_dir / "centroids.built.json"),
            "--checkpoint",
            str(artifacts_dir / "centroid.checkpoint.json"),
            "--batch-size",
            "8",
            "--embedding-model",
            "example-embedding",
            "--embedding-dimension",
            "3",
            "--report-json",
            str(artifacts_dir / "centroid_build.json"),
            "--report-md",
            str(artifacts_dir / "centroid_build.md"),
            "--json",
        ],
        cwd=workspace,
        env=env,
    )
    _record_command_check(
        checks,
        "query centroid build",
        centroid_build_result,
        required_stdout='"ragflow_route_centroid_build_report_v1"',
    )
    query_runner = workspace / "query_runner.py"
    _write_query_runner(
        runner_path=query_runner,
        query_script=query_script,
        kb_manifest=kb_manifest,
        artifacts_dir=artifacts_dir,
        profile=profile,
    )
    _run_imported_cli_check(
        name="query direct and host-assisted",
        runner_path=query_runner,
        checks=checks,
        cwd=workspace,
        env=env,
    )

    validate_script = script_root / "ragflow-kb-build" / "scripts" / "validate.py"
    validate_runner = workspace / "validate_runner.py"
    _write_validate_runner(
        runner_path=validate_runner,
        validate_script=validate_script,
        kb_manifest=kb_manifest,
        queries_path=queries_path,
        metadata_path=metadata_template,
        artifacts_dir=artifacts_dir,
        profile=profile,
    )
    _run_imported_cli_check(
        name="kb validation regression report",
        runner_path=validate_runner,
        checks=checks,
        cwd=workspace,
        env=env,
    )

    artifact_files = [
        doc_manifest,
        workspace / "image-fallback-handoff" / "doc_manifest.json",
        workspace / "image-fallback-handoff" / "quality_report.json",
        mineru_doc_manifest,
        workspace / "mineru-cli-handoff" / "doc_manifest.json",
        workspace / "mineru-cli-handoff" / "runtime_report.json",
        workspace / "mineru-sync-handoff" / "doc_manifest.json",
        workspace / "backend_probe.json",
        workspace / "backend_probe.md",
        workspace / "backend_warmup.json",
        workspace / "backend_warmup.md",
        kb_manifest,
        artifacts_dir / "query_endpoint_report.json",
        artifacts_dir / "query_endpoint_report.md",
        artifacts_dir / "query_endpoint_redaction.json",
        artifacts_dir / "query_fallback_test.json",
        artifacts_dir / "query_fallback_test.md",
        artifacts_dir / "query_direct.json",
        artifacts_dir / "query_host_assisted.json",
        artifacts_dir / "query_agentic_retrieval.json",
        artifacts_dir / "query_trace.json",
        artifacts_dir / "query_trace.md",
        artifacts_dir / "query_rewrite.json",
        artifacts_dir / "query_rewrite.md",
        artifacts_dir / "query_intent.json",
        artifacts_dir / "query_intent.md",
        artifacts_dir / "query_intent_route.json",
        artifacts_dir / "query_intent_route.md",
        artifacts_dir / "query_session.json",
        artifacts_dir / "query_session_inspect.json",
        artifacts_dir / "query_session_inspect.md",
        artifacts_dir / "query_session_enrich.json",
        artifacts_dir / "query_session_enrich.md",
        artifacts_dir / "query_agentic_plan.json",
        artifacts_dir / "query_agentic_plan.md",
        artifacts_dir / "query_multi.json",
        artifacts_dir / "query_multi_trace.json",
        artifacts_dir / "citation_audit.json",
        artifacts_dir / "citation_audit.md",
        artifacts_dir / "query_answer_eval.json",
        artifacts_dir / "query_answer_eval.md",
        artifacts_dir / "query_diagnostic.json",
        artifacts_dir / "query_diagnostic.md",
        artifacts_dir / "query_pollution.json",
        artifacts_dir / "query_pollution.md",
        artifacts_dir / "query_rerank_ab.json",
        artifacts_dir / "query_rerank_ab.md",
        artifacts_dir / "query_cross_language_ab.json",
        artifacts_dir / "query_cross_language_ab.md",
        artifacts_dir / "query_fusion.json",
        artifacts_dir / "query_fusion.md",
        artifacts_dir / "query_fusion_test.json",
        artifacts_dir / "query_fusion_test.md",
        artifacts_dir / "route_test.md",
        artifacts_dir / "route_report.md",
        artifacts_dir / "route_diagnose.md",
        artifacts_dir / "route_tie_queries.json",
        artifacts_dir / "route_centroids.json",
        artifacts_dir / "route_query_vector.json",
        artifacts_dir / "centroid_plan.json",
        artifacts_dir / "centroid_plan.md",
        artifacts_dir / "centroid_chunk_snapshot.json",
        artifacts_dir / "centroid_build.json",
        artifacts_dir / "centroid_build.md",
        artifacts_dir / "centroid.checkpoint.json",
        artifacts_dir / "centroids.built.json",
        artifacts_dir / "profile_lint.md",
        artifacts_dir / "candidate_profile_set.json",
        artifacts_dir / "profile_experiment_matrix.md",
        artifacts_dir / "model_provider_probe.json",
        artifacts_dir / "model_provider_probe.md",
        artifacts_dir / "model_provider_redaction.json",
        artifacts_dir / "metadata.template.json",
        artifacts_dir / "tagset.template.json",
        artifacts_dir / "benchmark" / "manifest.json",
        artifacts_dir / "benchmark" / "queries.json",
        artifacts_dir / "benchmark" / "qrels.json",
        artifacts_dir / "benchmark" / "qa.json",
        artifacts_dir / "qa.generated.json",
        artifacts_dir / "qa_evidence_map.json",
        artifacts_dir / "segment_metadata_report.json",
        artifacts_dir / "suppression_report.json",
        artifacts_dir / "optimization_plan.json",
        artifacts_dir / "optimization_cleanup_plan.json",
        artifacts_dir / "optimization_cleanup_plan.md",
        artifacts_dir / "profile_experiment_results.json",
        artifacts_dir / "best_profile_report.md",
        artifacts_dir / "benchmark_current.json",
        artifacts_dir / "benchmark_baseline.json",
        artifacts_dir / "benchmark_suggestions.json",
        artifacts_dir / "benchmark_suggestions.md",
        artifacts_dir / "validation_report.json",
        artifacts_dir / "validation_report.md",
    ]
    artifact_files.extend((workspace / "image-fallback-handoff" / "documents" / "images").glob("diagram-*.png"))
    ok = all(check["ok"] for check in checks)
    return {
        "id": profile.id,
        "platform": profile.platform,
        "runtime_mode": profile.runtime_mode,
        "config_mode": profile.config_mode,
        "notes": profile.notes,
        "ok": ok,
        "workspace": str(workspace),
        "checks": checks,
        "artifacts": [str(path) for path in artifact_files if path and path.exists()],
    }


def selected_profiles(ids: list[str] | None = None) -> list[PlatformProfile]:
    if not ids:
        return list(PLATFORM_PROFILES)
    known = {profile.id: profile for profile in PLATFORM_PROFILES}
    resolved_ids = [PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in ids]
    missing = [profile_id for profile_id in resolved_ids if profile_id not in known]
    if missing:
        raise SystemExit(f"unknown platform profile(s): {', '.join(missing)}")
    return [known[profile_id] for profile_id in resolved_ids]


def run_smoke_matrix(
    *,
    dist_dir: Path = DIST_DIR,
    work_root: Path,
    profile_ids: list[str] | None = None,
) -> dict[str, Any]:
    built = build_release(dist_dir)
    profiles = selected_profiles(profile_ids)
    results = [
        run_profile(profile, dist_dir=dist_dir, work_root=work_root)
        for profile in profiles
    ]
    return {
        "ok": all(result["ok"] for result in results),
        "dist": str(dist_dir),
        "work_root": str(work_root),
        "built_skills": [path.name for path in built],
        "profiles": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run cross-platform RAGFlow skill smoke matrix")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release artifact output directory")
    parser.add_argument("--work-dir", help="Directory for smoke workspaces and artifacts")
    parser.add_argument("--profile", action="append", help="Run one profile ID; repeatable")
    parser.add_argument("--list-profiles", action="store_true", help="List platform profile IDs")
    args = parser.parse_args(argv)

    if args.list_profiles:
        for profile in PLATFORM_PROFILES:
            print(f"{profile.id}\t{profile.platform}\t{profile.runtime_mode}")
        return 0

    dist_dir = Path(args.dist).resolve()
    if args.work_dir:
        work_root = Path(args.work_dir).resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        payload = run_smoke_matrix(
            dist_dir=dist_dir,
            work_root=work_root,
            profile_ids=args.profile,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="ragflow-platform-smoke-") as tmp:
            payload = run_smoke_matrix(
                dist_dir=dist_dir,
                work_root=Path(tmp),
                profile_ids=args.profile,
            )
            payload["artifacts_retained"] = False
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 1

    payload["artifacts_retained"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
