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
    mineru_sync_output = workspace / "mineru-sync-handoff"
    mineru_input.mkdir(parents=True, exist_ok=True)
    (mineru_input / "mineru.pdf").write_bytes(b"%PDF mineru service smoke")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
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
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

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
                        "content_with_weight": "portable validation chunk with known term",
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
    (artifacts_dir / output_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\\n",
        encoding="utf-8",
    )
    payloads.append({{"mode": mode, "chunk_count": len(payload.get("chunks", []))}})

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

print(json.dumps({{"ok": True, "payloads": payloads, "audit": audit_payload}}, ensure_ascii=False))
""",
        encoding="utf-8",
    )


def _write_validate_runner(
    *,
    runner_path: Path,
    validate_script: Path,
    kb_manifest: Path,
    queries_path: Path,
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
if not payload.get("ok") or not report_json.exists() or not report_md.exists():
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

    kb_manifest = _write_fake_kb_manifest(workspace, artifacts_dir)
    queries_path = _write_query_set(artifacts_dir)

    query_script = script_root / "ragflow-query" / "scripts" / "query.py"
    routing_config = artifacts_dir / "routing_config.json"
    route_queries = artifacts_dir / "route_queries.json"
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
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
        mineru_doc_manifest,
        workspace / "mineru-sync-handoff" / "doc_manifest.json",
        kb_manifest,
        artifacts_dir / "query_direct.json",
        artifacts_dir / "query_host_assisted.json",
        artifacts_dir / "query_trace.json",
        artifacts_dir / "query_trace.md",
        artifacts_dir / "citation_audit.json",
        artifacts_dir / "citation_audit.md",
        artifacts_dir / "route_test.md",
        artifacts_dir / "profile_lint.md",
        artifacts_dir / "validation_report.json",
        artifacts_dir / "validation_report.md",
    ]
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
