#!/usr/bin/env python3
"""Validate release artifacts from a clean consumer workspace."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_DIR = ROOT / "release-artifacts"
REQUIRED_ASSETS = (
    "ragflow-doc-to-md.tar.gz",
    "ragflow-kb-build.tar.gz",
    "ragflow-query.tar.gz",
    "release-manifest.json",
)
COMMAND_MANIFEST_SCHEMA = "ragflow_consumer_command_manifest_v1"

RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import configured_private_hosts_from_urls, sanitize_report_payload  # noqa: E402


def _preview(text: str, *, limit: int = 500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _minimal_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
    }
    if extra:
        env.update({key: value for key, value in extra.items() if value})
    return env


def _github_env() -> dict[str, str]:
    env = _minimal_env()
    env["GH_PROMPT_DISABLED"] = "1"
    for key in (
        "HOME",
        "XDG_CONFIG_HOME",
        "GH_CONFIG_DIR",
        "GH_HOST",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITHUB_HOST",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float = 60.0,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=dict(env),
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
    required_output: str | None = None,
    expect_failure: bool = False,
) -> bool:
    combined = f"{result['stdout']}\n{result['stderr']}"
    ok = result["returncode"] != 0 if expect_failure else bool(result["ok"])
    error = ""
    if ok and required_output and required_output not in combined:
        ok = False
        error = f"output did not contain {required_output!r}"
    elif not ok:
        expected = "non-zero exit" if expect_failure else "zero exit"
        error = _preview(combined) or f"expected {expected}, got {result['returncode']}"

    checks.append(
        {
            "name": name,
            "ok": ok,
            "returncode": result["returncode"],
            "command": result["command"],
            "stdout_preview": _preview(result["stdout"]),
            "stderr_preview": _preview(result["stderr"]),
            "error": error,
        }
    )
    return ok


def _record_file_check(checks: list[dict[str, Any]], name: str, path: Path) -> bool:
    ok = path.exists()
    checks.append(
        {
            "name": name,
            "ok": ok,
            "path": str(path),
            "error": "" if ok else f"missing {path}",
        }
    )
    return ok


def _record_redaction_sidecar_check(
    checks: list[dict[str, Any]],
    name: str,
    redaction_path: Path,
    *,
    result: Mapping[str, Any] | None = None,
    checked_paths: Sequence[Path] = (),
    forbidden_literals: Sequence[str] = (),
) -> bool:
    error = ""
    ok = redaction_path.exists()
    combined = ""
    if not ok:
        error = f"missing {redaction_path}"
    else:
        try:
            redaction_payload = json.loads(redaction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            ok = False
            error = f"invalid redaction sidecar: {exc}"
        else:
            ok = redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            if not ok:
                error = "unexpected redaction sidecar schema"
        combined = redaction_path.read_text(encoding="utf-8") if redaction_path.exists() else ""
    if ok and result is not None:
        combined += "\n" + str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
    if ok:
        for path in checked_paths:
            if path.exists():
                combined += "\n" + path.read_text(encoding="utf-8")
        leaked = [literal for literal in forbidden_literals if literal and literal in combined]
        if leaked:
            ok = False
            error = f"redaction output leaked forbidden literal {leaked[0]!r}"
    checks.append(
        {
            "name": name,
            "ok": ok,
            "path": str(redaction_path),
            "error": error,
        }
    )
    return ok


def _prepare_work_root(work_root: Path, *, overwrite: bool) -> None:
    if work_root.exists():
        if not overwrite and any(work_root.iterdir()):
            raise RuntimeError(f"work directory is not empty; pass --overwrite to replace it: {work_root}")
        if overwrite:
            shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)


def _validate_artifacts_dir(artifacts_dir: Path) -> dict[str, Path]:
    missing = [name for name in REQUIRED_ASSETS if not (artifacts_dir / name).exists()]
    if missing:
        raise RuntimeError(f"missing release artifact(s) in {artifacts_dir}: {', '.join(missing)}")
    return {name: artifacts_dir / name for name in REQUIRED_ASSETS}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (base / member.name).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError(f"unsafe path in archive {archive}: {member.name}")
        try:
            tar.extractall(base, filter="data")
        except TypeError:
            tar.extractall(base)


def _extract_skills(artifacts: Mapping[str, Path], extract_dir: Path) -> None:
    for name in REQUIRED_ASSETS:
        if name.endswith(".tar.gz"):
            _safe_extract(artifacts[name], extract_dir)


def _write_sample_input(work_root: Path) -> Path:
    input_dir = work_root / "input-docs"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "sample.md").write_text(
        "# Consumer Acceptance\n\nThis release artifact can run without repository source context.\n",
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
        "    f'# MinerU CLI Acceptance\\n\\nConverted through mineru-cli backend={backend}.\\n\\n![chart](images/chart.jpg)\\n',\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class _ModelProviderHandler(BaseHTTPRequestHandler):
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

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextlib.contextmanager
def _model_provider_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class _DiagnosticProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/v1/datasets"):
            body = json.dumps({"data": {"datasets": [{"id": "short", "name": "kb:consumer-diagnostic"}]}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextlib.contextmanager
def _diagnostic_probe_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DiagnosticProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_reports(payload: dict[str, Any], reports_dir: Path) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_json = reports_dir / "consumer-acceptance-report.json"
    report_md = reports_dir / "consumer-acceptance-report.md"
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Consumer Acceptance Report",
        "",
        f"- ok: `{str(payload['ok']).lower()}`",
        f"- source: `{payload['source']['type']}`",
        f"- work_root: `{payload['work_root']}`",
        "",
        "## Checks",
        "",
        "| Check | OK | Detail |",
        "| --- | --- | --- |",
    ]
    for check in payload["checks"]:
        detail = check.get("error") or check.get("path") or ""
        lines.append(f"| {check['name']} | {str(check['ok']).lower()} | {detail} |")
    lines.extend(["", "## Produced Artifacts", ""])
    for artifact in payload["produced_artifacts"]:
        lines.append(f"- `{artifact}`")
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(report_json), "markdown": str(report_md)}


def _skill_path(extract_dir: Path, skill_name: str, *parts: str) -> Path:
    return extract_dir / skill_name / Path(*parts)


def _tokenize_manifest_value(
    value: str,
    *,
    work_root: Path,
    extract_dir: Path,
    artifacts_dir: Path,
    env_map: Mapping[str, str],
) -> str:
    for key in ("RAGFLOW_BASE_URL", "RAGFLOW_API_KEY", "RAGFLOW_DATASET_ID"):
        if env_map.get(key) and value == env_map[key]:
            return f"<env:{key}>"
    if value.startswith("-") or (not Path(value).is_absolute() and "/" not in value and "\\" not in value):
        return value
    for root, token in (
        (extract_dir.resolve(), "<unpacked>"),
        (work_root.resolve(), "<work>"),
        (artifacts_dir.resolve(), "<artifacts>"),
        (ROOT.resolve(), "<repo>"),
    ):
        try:
            path = Path(value).resolve()
        except OSError:
            continue
        try:
            return f"{token}/{path.relative_to(root)}"
        except ValueError:
            continue
    return value


def _tokenize_manifest_command(
    command: list[str],
    *,
    work_root: Path,
    extract_dir: Path,
    artifacts_dir: Path,
    env_map: Mapping[str, str],
) -> list[str]:
    return [
        _tokenize_manifest_value(
            part,
            work_root=work_root,
            extract_dir=extract_dir,
            artifacts_dir=artifacts_dir,
            env_map=env_map,
        )
        for part in command
    ]


def _tokenize_manifest_path(
    path: Path,
    *,
    work_root: Path,
    extract_dir: Path,
    artifacts_dir: Path,
    env_map: Mapping[str, str],
) -> str:
    return _tokenize_manifest_value(
        str(path),
        work_root=work_root,
        extract_dir=extract_dir,
        artifacts_dir=artifacts_dir,
        env_map=env_map,
    )


def _manifest_config_checks(*, live: bool, live_build: bool, env_map: Mapping[str, str]) -> list[dict[str, Any]]:
    required_for: dict[str, list[str]] = {}
    if live:
        for name in ("RAGFLOW_BASE_URL", "RAGFLOW_API_KEY", "RAGFLOW_DATASET_ID"):
            required_for.setdefault(name, []).append("live")
    if live_build:
        for name in ("RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"):
            required_for.setdefault(name, []).append("live_build")
    return [
        {
            "name": name,
            "required_for": flows,
            "configured": bool(env_map.get(name)),
            "source": "environment",
            "value": "<configured>" if env_map.get(name) else None,
        }
        for name, flows in sorted(required_for.items())
    ]


def _command_manifest_entry(
    *,
    command_id: str,
    label: str,
    command: list[str],
    mutates_ragflow: bool,
    mutation_label: str,
    required_config: list[str],
    expected_artifacts: list[Path],
    cleanup_notes: list[str],
    work_root: Path,
    extract_dir: Path,
    artifacts_dir: Path,
    env_map: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "id": command_id,
        "label": label,
        "command": _tokenize_manifest_command(
            command,
            work_root=work_root,
            extract_dir=extract_dir,
            artifacts_dir=artifacts_dir,
            env_map=env_map,
        ),
        "mutates_ragflow": mutates_ragflow,
        "mutation_label": mutation_label,
        "required_config": required_config,
        "missing_config": [name for name in required_config if not env_map.get(name)],
        "expected_artifacts": [
            {
                "path": _tokenize_manifest_path(
                    path,
                    work_root=work_root,
                    extract_dir=extract_dir,
                    artifacts_dir=artifacts_dir,
                    env_map=env_map,
                ),
                "when": "on_success",
            }
            for path in expected_artifacts
        ],
        "cleanup_notes": cleanup_notes,
    }


def _build_consumer_command_manifest(
    *,
    artifacts_dir: Path,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env_map: Mapping[str, str],
    live: bool,
    live_build: bool,
    question: str,
    top_k: int,
    kb_name: str | None,
    parse_timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    build_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "build.py")
    validate_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "validate.py")
    profile = _skill_path(extract_dir, "ragflow-kb-build", "templates", "default-en-768.json")
    doc_manifest = work_root / "handoff" / "doc_manifest.json"
    live_dir = work_root / "live"
    kb_manifest = live_dir / "kb_manifest.json"
    planned_kb_name = kb_name or "kb:consumer-acceptance-<generated>"

    if live:
        commands.append(
            _command_manifest_entry(
                command_id="live-query-existing",
                label="Query an existing live RAGFlow dataset",
                command=[
                    python_executable,
                    str(query_script),
                    "ask",
                    question,
                    "--dataset-id",
                    env_map.get("RAGFLOW_DATASET_ID", "<env:RAGFLOW_DATASET_ID>"),
                    "--mode",
                    "direct",
                    "--top-k",
                    str(top_k),
                    "--json",
                ],
                mutates_ragflow=False,
                mutation_label="read_only_retrieval",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY", "RAGFLOW_DATASET_ID"],
                expected_artifacts=[work_root / "live-query-result.json"],
                cleanup_notes=["No RAGFlow cleanup is required for read-only retrieval."],
                work_root=work_root,
                extract_dir=extract_dir,
                artifacts_dir=artifacts_dir,
                env_map=env_map,
            )
        )

    if live_build:
        commands.append(
            _command_manifest_entry(
                command_id="live-build-disposable-kb",
                label="Create and parse a disposable RAGFlow KB",
                command=[
                    python_executable,
                    str(build_script),
                    "--doc-manifest",
                    str(doc_manifest),
                    "--kb-name",
                    planned_kb_name,
                    "--profile",
                    str(profile),
                    "--output",
                    str(kb_manifest),
                    "--parse-timeout",
                    str(parse_timeout),
                    "--poll-interval",
                    str(poll_interval),
                    "--json",
                ],
                mutates_ragflow=True,
                mutation_label="creates_dataset_uploads_documents_and_triggers_parse",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[kb_manifest],
                cleanup_notes=[
                    "Delete the disposable KB from RAGFlow after review.",
                    "Use the dataset_id recorded in <work>/live/kb_manifest.json after live execution.",
                ],
                work_root=work_root,
                extract_dir=extract_dir,
                artifacts_dir=artifacts_dir,
                env_map=env_map,
            )
        )
        commands.append(
            _command_manifest_entry(
                command_id="live-validate-smoke",
                label="Validate the disposable KB with a smoke query",
                command=[
                    python_executable,
                    str(validate_script),
                    "--kb-manifest",
                    str(kb_manifest),
                    "--level",
                    "smoke",
                    "--query",
                    question,
                    "--top-k",
                    str(top_k),
                    "--report-json",
                    str(live_dir / "validation_report.json"),
                    "--report-md",
                    str(live_dir / "validation_report.md"),
                ],
                mutates_ragflow=False,
                mutation_label="read_only_validation",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[live_dir / "validation_report.json", live_dir / "validation_report.md"],
                cleanup_notes=["No additional RAGFlow cleanup is required beyond deleting the disposable KB."],
                work_root=work_root,
                extract_dir=extract_dir,
                artifacts_dir=artifacts_dir,
                env_map=env_map,
            )
        )
        for mode, extra, output_name in (
            ("direct", ["--json"], "live-query-direct.json"),
            ("agentic", ["--host-assisted", "--json"], "live-query-host-assisted.json"),
        ):
            commands.append(
                _command_manifest_entry(
                    command_id=f"live-query-{mode}",
                    label=f"Query the disposable KB in {mode} mode",
                    command=[
                        python_executable,
                        str(query_script),
                        "ask",
                        question,
                        "--kb-manifest",
                        str(kb_manifest),
                        "--mode",
                        mode,
                        "--top-k",
                        str(top_k),
                        *extra,
                    ],
                    mutates_ragflow=False,
                    mutation_label="read_only_retrieval",
                    required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                    expected_artifacts=[live_dir / output_name],
                    cleanup_notes=["No additional RAGFlow cleanup is required beyond deleting the disposable KB."],
                    work_root=work_root,
                    extract_dir=extract_dir,
                    artifacts_dir=artifacts_dir,
                    env_map=env_map,
                )
            )

    config_checks = _manifest_config_checks(live=live, live_build=live_build, env_map=env_map)
    return {
        "ok": True,
        "schema": COMMAND_MANIFEST_SCHEMA,
        "mode": "dry_run",
        "source": "consumer_acceptance",
        "work_root": "<work>",
        "artifacts_dir": "<artifacts>",
        "live_flows": {
            "live": live,
            "live_build": live_build,
        },
        "local_configuration": {
            "checks": config_checks,
            "missing_required": sorted(
                {check["name"] for check in config_checks if not check["configured"]}
            ),
        },
        "commands": commands,
        "expected_artifacts": [
            artifact
            for command in commands
            for artifact in command["expected_artifacts"]
        ],
        "cleanup": {
            "required": live_build,
            "notes": [
                "Review this command manifest before running live acceptance.",
                "Delete any disposable KB created by live-build after validation.",
                "Local artifacts under <work>/live can be removed after reports are collected.",
            ],
        },
        "summary": {
            "command_count": len(commands),
            "mutating_command_count": sum(1 for command in commands if command["mutates_ragflow"]),
            "expected_artifact_count": sum(len(command["expected_artifacts"]) for command in commands),
        },
    }


def _write_command_manifest(
    *,
    path: Path,
    redaction_path: Path,
    artifacts_dir: Path,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env_map: Mapping[str, str],
    live: bool,
    live_build: bool,
    question: str,
    top_k: int,
    kb_name: str | None,
    parse_timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    raw_manifest = _build_consumer_command_manifest(
        artifacts_dir=artifacts_dir,
        extract_dir=extract_dir,
        work_root=work_root,
        python_executable=python_executable,
        env_map=env_map,
        live=live,
        live_build=live_build,
        question=question,
        top_k=top_k,
        kb_name=kb_name,
        parse_timeout=parse_timeout,
        poll_interval=poll_interval,
    )
    sanitized, redaction_report = sanitize_report_payload(
        raw_manifest,
        explicit_secrets=[
            env_map.get("RAGFLOW_API_KEY"),
            env_map.get("RAGFLOW_DATASET_ID"),
        ],
        private_hosts=configured_private_hosts_from_urls([env_map.get("RAGFLOW_BASE_URL")]),
        home_paths=[str(work_root), str(extract_dir), str(artifacts_dir)],
        config_paths=[env_map.get("RAGFLOW_CONFIG")],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    redaction_path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redaction_path.write_text(json.dumps(redaction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "json": str(path),
        "redaction": str(redaction_path),
        "schema": COMMAND_MANIFEST_SCHEMA,
        "command_count": sanitized["summary"]["command_count"],
        "mutating_command_count": sanitized["summary"]["mutating_command_count"],
        "redaction_summary": redaction_report["summary"],
    }


def _write_generated_report_redaction_fixture(work_root: Path) -> tuple[dict[str, Any], list[Path]]:
    report_path = work_root / "generated_report_fixture.json"
    redaction_path = work_root / "generated_report_fixture.redaction.json"
    fake_secret = "fake-generated-report-secret"
    fake_config_path = str(work_root / "private" / "config.local.yaml")
    raw_report = {
        "schema": "ragflow_acceptance_generated_report_fixture_v1",
        "endpoint": "http://" + ".".join(("100", "64", "10", "20")) + f":8080/v1?token={fake_secret}",
        "message": f"api_key={fake_secret}",
        "config_path": fake_config_path,
    }
    sanitized, redaction_report = sanitize_report_payload(
        raw_report,
        explicit_secrets=[fake_secret],
        private_hosts=configured_private_hosts_from_urls([raw_report["endpoint"]]),
        home_paths=[str(work_root)],
        config_paths=[fake_config_path],
    )
    report_path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redaction_path.write_text(json.dumps(redaction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    combined = report_path.read_text(encoding="utf-8") + redaction_path.read_text(encoding="utf-8")
    ok = (
        fake_secret not in combined
        and fake_config_path not in combined
        and redaction_report["summary"]["redaction_count"] >= 3
    )
    return (
        {
            "name": "generated report redaction fixture",
            "ok": ok,
            "path": str(report_path),
            "error": "" if ok else "fake generated report fixture leaked a secret or did not redact expected fields",
        },
        [report_path, redaction_path],
    )


def _run_no_network_checks(
    *,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[Path]]:
    checks: list[dict[str, Any]] = []
    produced: list[Path] = []

    redaction_check, redaction_artifacts = _write_generated_report_redaction_fixture(work_root)
    checks.append(redaction_check)
    produced.extend(redaction_artifacts)

    _record_file_check(
        checks,
        "vendored runtime present",
        _skill_path(extract_dir, "ragflow-query", "scripts", "_vendor", "ragflow_skill_runtime", "__init__.py"),
    )

    input_dir = _write_sample_input(work_root)
    handoff_dir = work_root / "handoff"
    convert_script = _skill_path(extract_dir, "ragflow-doc-to-md", "scripts", "convert.py")
    convert_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "--input",
            str(input_dir),
            "--output",
            str(handoff_dir),
            "--mode",
            "passthrough",
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md passthrough", convert_result, required_output='"ok": true')
    doc_manifest = handoff_dir / "doc_manifest.json"
    _record_file_check(checks, "doc_manifest produced", doc_manifest)
    if doc_manifest.exists():
        produced.append(doc_manifest)
    quality_report = handoff_dir / "quality_report.json"
    _record_file_check(checks, "quality_report produced", quality_report)
    if quality_report.exists():
        produced.append(quality_report)

    convert_redaction_input = work_root / "convert-redaction-input"
    convert_redaction_input.mkdir(parents=True, exist_ok=True)
    (convert_redaction_input / "convert.local-token=convert-secret.md").write_text(
        "# Convert redaction\n\nReady.\n",
        encoding="utf-8",
    )
    convert_redaction_output = work_root / "convert-redaction-handoff"
    convert_redaction_report = work_root / "convert_redaction.json"
    convert_quality_md = convert_redaction_output / "quality_report.md"
    convert_redaction_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "--input",
            str(convert_redaction_input),
            "--output",
            str(convert_redaction_output),
            "--mode",
            "passthrough",
            "--quality-report-md",
            str(convert_quality_md),
            "--redaction-report",
            str(convert_redaction_report),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md convert redaction", convert_redaction_result, required_output='"ok": true')
    convert_quality_report = convert_redaction_output / "quality_report.json"
    if convert_quality_report.exists():
        produced.append(convert_quality_report)
    if convert_quality_md.exists():
        produced.append(convert_quality_md)
    if convert_redaction_report.exists():
        produced.append(convert_redaction_report)
        redaction_payload = json.loads(convert_redaction_report.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                convert_redaction_result.get("stdout", ""),
                convert_quality_report.read_text(encoding="utf-8") if convert_quality_report.exists() else "",
                convert_quality_md.read_text(encoding="utf-8") if convert_quality_md.exists() else "",
                convert_redaction_report.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 1
            and "convert-secret" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md convert redaction sidecar",
                "ok": redaction_ok,
                "path": str(convert_redaction_report),
                "error": "" if redaction_ok else "top-level convert redaction did not hide fake-sensitive values",
            }
        )

    image_input = work_root / "image-fallback-input"
    image_input.mkdir(parents=True, exist_ok=True)
    (image_input / "diagram.png").write_bytes(b"fake image fallback bytes")
    image_handoff = work_root / "image-fallback-handoff"
    image_fallback_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "--input",
            str(image_input),
            "--output",
            str(image_handoff),
            "--backend",
            "remote",
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md image fallback",
        image_fallback_result,
        required_output='"status": "PASS_WITH_REVIEW"',
    )
    image_manifest = image_handoff / "doc_manifest.json"
    image_quality = image_handoff / "quality_report.json"
    _record_file_check(checks, "image fallback doc_manifest produced", image_manifest)
    _record_file_check(checks, "image fallback quality_report produced", image_quality)
    if image_manifest.exists():
        produced.append(image_manifest)
    if image_quality.exists():
        quality_status = json.loads(image_quality.read_text(encoding="utf-8")).get("gate", {}).get("status")
        copied_image_paths = list((image_handoff / "documents" / "images").glob("diagram-*.png"))
        image_count = len(copied_image_paths)
        review_ok = quality_status == "PASS_WITH_REVIEW" and image_count == 1
        checks.append(
            {
                "name": "image fallback preserves source image with review gate",
                "ok": review_ok,
                "path": str(image_quality),
                "error": "" if review_ok else f"status={quality_status}, copied_images={image_count}",
            }
        )
        produced.append(image_quality)
        produced.extend(copied_image_paths)

    package_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "package",
            "--handoff",
            str(handoff_dir),
            "--rich",
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md rich handoff package", package_result, required_output='"schema": "ragflow_handoff_package_v1"')
    for rich_name in (
        "metadata.json",
        "artifact_index.json",
        "profile_suggestions.json",
        "retrieval_hints.json",
        "assistant_profile.json",
        "assistant_test_plan.json",
        "package_readme.md",
    ):
        rich_path = handoff_dir / rich_name
        _record_file_check(checks, f"rich handoff {rich_name} produced", rich_path)
        if rich_path.exists():
            produced.append(rich_path)

    mineru_cli_input = work_root / "mineru-cli-input"
    mineru_cli_input.mkdir(parents=True, exist_ok=True)
    (mineru_cli_input / "sample.pdf").write_bytes(b"%PDF fake mineru cli acceptance")
    mineru_cli_output = work_root / "mineru-cli-handoff"
    fake_mineru_cli = _write_fake_mineru_cli(work_root / "mineru-token=runtime-secret")
    mineru_cli_redaction = work_root / "convert_runtime_redaction.json"
    mineru_cli_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "--input",
            str(mineru_cli_input),
            "--output",
            str(mineru_cli_output),
            "--backend",
            "auto",
            "--redaction-report",
            str(mineru_cli_redaction),
            "--json",
        ],
        cwd=work_root,
        env=_minimal_env(
            {
                **env,
                "MINERU_CLI_PATH": str(fake_mineru_cli),
                "MINERU_CLI_BACKEND": "pipeline",
            }
        ),
    )
    _record_command_check(checks, "doc-to-md mineru-cli auto", mineru_cli_result, required_output='"ok": true')
    mineru_cli_manifest = mineru_cli_output / "doc_manifest.json"
    _record_file_check(checks, "mineru-cli doc_manifest produced", mineru_cli_manifest)
    if mineru_cli_manifest.exists():
        produced.append(mineru_cli_manifest)
    mineru_cli_image = mineru_cli_output / "documents" / "images" / "chart.jpg"
    _record_file_check(checks, "mineru-cli local image asset copied", mineru_cli_image)
    mineru_cli_quality = mineru_cli_output / "quality_report.json"
    _record_file_check(checks, "mineru-cli quality_report produced", mineru_cli_quality)
    if mineru_cli_quality.exists():
        quality_status = json.loads(mineru_cli_quality.read_text(encoding="utf-8")).get("gate", {}).get("status")
        checks.append(
            {
                "name": "mineru-cli quality gate passes with local image",
                "ok": quality_status == "PASS",
                "path": str(mineru_cli_quality),
                "error": "" if quality_status == "PASS" else f"expected PASS, got {quality_status}",
            }
        )
        produced.append(mineru_cli_quality)
    mineru_cli_runtime = mineru_cli_output / "runtime_report.json"
    _record_file_check(checks, "mineru-cli runtime_report produced", mineru_cli_runtime)
    if mineru_cli_runtime.exists():
        runtime_payload = json.loads(mineru_cli_runtime.read_text(encoding="utf-8"))
        runtime_summary = runtime_payload.get("summary", {})
        runtime_ok = (
            runtime_payload.get("schema") == "ragflow_doc_runtime_report_v1"
            and runtime_summary.get("process_attempts") == 1
            and runtime_summary.get("success") == 1
        )
        checks.append(
            {
                "name": "mineru-cli runtime report summarizes process attempt",
                "ok": runtime_ok,
                "path": str(mineru_cli_runtime),
                "error": "" if runtime_ok else f"unexpected runtime summary: {runtime_summary}",
            }
        )
        produced.append(mineru_cli_runtime)
    if mineru_cli_redaction.exists():
        produced.append(mineru_cli_redaction)
        redaction_payload = json.loads(mineru_cli_redaction.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                mineru_cli_result.get("stdout", ""),
                mineru_cli_runtime.read_text(encoding="utf-8") if mineru_cli_runtime.exists() else "",
                mineru_cli_redaction.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 1
            and "runtime-secret" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md convert runtime redaction",
                "ok": redaction_ok,
                "path": str(mineru_cli_redaction),
                "error": "" if redaction_ok else "top-level convert runtime redaction did not hide fake-sensitive values",
            }
        )

    backend_probe_json = work_root / "backend_probe.json"
    backend_probe_md = work_root / "backend_probe.md"
    backend_probe_redaction = work_root / "backend_probe_redaction.json"
    backend_probe_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "backend",
            "probe",
            "--backend",
            "mineru-cli",
            "--mineru-cli-path",
            str(fake_mineru_cli),
            "--report-json",
            str(backend_probe_json),
            "--report-md",
            str(backend_probe_md),
            "--redaction-report",
            str(backend_probe_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md backend probe",
        backend_probe_result,
        required_output='"schema": "ragflow_doc_backend_probe_report_v1"',
    )
    if backend_probe_json.exists():
        produced.append(backend_probe_json)
    if backend_probe_md.exists():
        produced.append(backend_probe_md)
    if backend_probe_redaction.exists():
        produced.append(backend_probe_redaction)

    backend_warmup_json = work_root / "backend_warmup.json"
    backend_warmup_md = work_root / "backend_warmup.md"
    backend_warmup_redaction = work_root / "backend_warmup_redaction.json"
    backend_warmup_fixture = work_root / "warmup.local-token=warmup-secret.pdf"
    backend_warmup_fixture.write_bytes(b"%PDF fake warmup")
    backend_warmup_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "backend",
            "warmup",
            "--backend",
            "mineru-cli",
            "--fixture",
            str(backend_warmup_fixture),
            "--mineru-cli-path",
            str(fake_mineru_cli),
            "--mineru-base-url",
            "http://warmup.local:8080/api/v1?token=warmup-secret",
            "--remote-api-key",
            "warmup-secret",
            "--report-json",
            str(backend_warmup_json),
            "--report-md",
            str(backend_warmup_md),
            "--redaction-report",
            str(backend_warmup_redaction),
            "--json",
            "--fail-on-failed",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "doc-to-md backend warmup",
        backend_warmup_result,
        required_output='"schema": "ragflow_doc_backend_warmup_report_v1"',
    )
    if backend_warmup_json.exists():
        produced.append(backend_warmup_json)
    if backend_warmup_md.exists():
        produced.append(backend_warmup_md)
    if backend_warmup_redaction.exists():
        produced.append(backend_warmup_redaction)
        redaction_payload = json.loads(backend_warmup_redaction.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                backend_warmup_result.get("stdout", ""),
                backend_warmup_json.read_text(encoding="utf-8") if backend_warmup_json.exists() else "",
                backend_warmup_md.read_text(encoding="utf-8") if backend_warmup_md.exists() else "",
                backend_warmup_redaction.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 2
            and "warmup-secret" not in combined
            and "warmup.local" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md backend warmup redaction",
                "ok": redaction_ok,
                "path": str(backend_warmup_redaction),
                "error": "" if redaction_ok else "backend warmup redaction did not hide fake-sensitive values",
            }
        )

    inspect_handoff = work_root / "inspect-redaction-handoff"
    inspect_docs = inspect_handoff / "documents"
    inspect_docs.mkdir(parents=True, exist_ok=True)
    (inspect_docs / "sample.md").write_text("# Inspect\n\nready\n", encoding="utf-8")
    inspect_manifest = inspect_handoff / "doc_manifest.json"
    inspect_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "source_root": ".",
                "documents": [
                    {
                        "source_path": "http://inspect.local/source.md?token=inspect-secret",
                        "markdown_path": "documents/sample.md",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    inspect_report = work_root / "quality_report.inspect.json"
    inspect_report_md = work_root / "quality_report.inspect.md"
    inspect_redaction = work_root / "quality_report.inspect_redaction.json"
    inspect_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "inspect",
            "--doc-manifest",
            str(inspect_manifest),
            "--report-json",
            str(inspect_report),
            "--report-md",
            str(inspect_report_md),
            "--redaction-report",
            str(inspect_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md inspect quality", inspect_result, required_output='"status": "PASS"')
    if inspect_report.exists():
        produced.append(inspect_report)
    if inspect_report_md.exists():
        produced.append(inspect_report_md)
    if inspect_redaction.exists():
        produced.append(inspect_redaction)
        redaction_payload = json.loads(inspect_redaction.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                inspect_result.get("stdout", ""),
                inspect_report.read_text(encoding="utf-8") if inspect_report.exists() else "",
                inspect_report_md.read_text(encoding="utf-8") if inspect_report_md.exists() else "",
                inspect_redaction.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 2
            and "inspect-secret" not in combined
            and "inspect.local" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md inspect redaction",
                "ok": redaction_ok,
                "path": str(inspect_redaction),
                "error": "" if redaction_ok else "inspect redaction did not hide fake-sensitive values",
            }
        )

    postprocess_dir = work_root / "postprocessed-handoff"
    postprocess_redaction = work_root / "postprocess_redaction.json"
    postprocess_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "postprocess",
            "--doc-manifest",
            str(doc_manifest),
            "--profile",
            "safe",
            "--output",
            str(postprocess_dir),
            "--redaction-report",
            str(postprocess_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md postprocess safe", postprocess_result, required_output='"schema": "doc_postprocess_report_v1"')
    postprocess_report = postprocess_dir / "postprocess_report.json"
    _record_file_check(checks, "postprocess_report produced", postprocess_report)
    _record_file_check(checks, "doc-to-md postprocess redaction", postprocess_redaction)
    if postprocess_report.exists():
        produced.append(postprocess_report)
    if postprocess_redaction.exists():
        produced.append(postprocess_redaction)
    postprocessed_manifest = postprocess_dir / "doc_manifest.json"
    if postprocessed_manifest.exists():
        produced.append(postprocessed_manifest)

    long_markdown = work_root / "long.md"
    long_markdown.write_text(
        "# http://segment.local/doc?token=segment-secret\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n",
        encoding="utf-8",
    )
    segmentation_plan = work_root / "segmentation_plan.json"
    segmentation_plan_redaction = work_root / "segmentation_plan_redaction.json"
    segment_plan_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "segment-plan",
            "--markdown",
            str(long_markdown),
            "--output",
            str(segmentation_plan),
            "--redaction-report",
            str(segmentation_plan_redaction),
            "--soft-max-chars",
            "50",
            "--hard-max-chars",
            "90",
            "--min-segment-chars",
            "20",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md segment plan", segment_plan_result, required_output='"recommended": true')
    if segmentation_plan.exists():
        produced.append(segmentation_plan)
    if segmentation_plan_redaction.exists():
        produced.append(segmentation_plan_redaction)
        redaction_payload = json.loads(segmentation_plan_redaction.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                segment_plan_result.get("stdout", ""),
                segmentation_plan.read_text(encoding="utf-8") if segmentation_plan.exists() else "",
                segmentation_plan_redaction.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 2
            and "segment-secret" not in combined
            and "segment.local" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md segment plan redaction",
                "ok": redaction_ok,
                "path": str(segmentation_plan_redaction),
                "error": "" if redaction_ok else "segment plan redaction did not hide fake-sensitive values",
            }
        )

    segments_dir = work_root / "segments"
    split_plan = work_root / "split_plan.json"
    split_redaction = work_root / "split_plan_redaction.json"
    split_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "split",
            "--markdown",
            str(long_markdown),
            "--output",
            str(segments_dir),
            "--plan-output",
            str(split_plan),
            "--redaction-report",
            str(split_redaction),
            "--soft-max-chars",
            "50",
            "--hard-max-chars",
            "90",
            "--min-segment-chars",
            "20",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md split", split_result, required_output='"segment_count": 2')
    if split_plan.exists():
        produced.append(split_plan)
    if split_redaction.exists():
        produced.append(split_redaction)
        redaction_payload = json.loads(split_redaction.read_text(encoding="utf-8"))
        combined = "\n".join(
            [
                split_result.get("stdout", ""),
                split_plan.read_text(encoding="utf-8") if split_plan.exists() else "",
                split_redaction.read_text(encoding="utf-8"),
            ]
        )
        redaction_ok = (
            redaction_payload.get("schema") == "ragflow_report_redaction_report_v1"
            and redaction_payload.get("summary", {}).get("redaction_count", 0) >= 2
            and "segment-secret" not in combined
            and "segment.local" not in combined
        )
        checks.append(
            {
                "name": "doc-to-md split redaction",
                "ok": redaction_ok,
                "path": str(split_redaction),
                "error": "" if redaction_ok else "split redaction did not hide fake-sensitive values",
            }
        )

    build_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "build.py")
    profile = _skill_path(extract_dir, "ragflow-kb-build", "templates", "default-en-768.json")
    vendor_parent = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "_vendor")
    profile_payload_check = _run_command(
        [
            python_executable,
            "-c",
            (
                "import json, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, str(Path(sys.argv[1])))\n"
                "from ragflow_skill_runtime.profiles import load_profile\n"
                "profile = load_profile(sys.argv[2])\n"
                "payload = profile.to_dataset_payload()\n"
                "parser_config = payload.get('parser_config', {})\n"
                "if any(key.startswith('__') for key in parser_config):\n"
                "    print(json.dumps({'ok': False, 'parser_config': parser_config}, ensure_ascii=False))\n"
                "    raise SystemExit(1)\n"
                "print(json.dumps({'ok': True, 'parser_config': parser_config}, ensure_ascii=False))\n"
            ),
            str(vendor_parent),
            str(profile),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "profile api payload filters internal metadata",
        profile_payload_check,
        required_output='"ok": true',
    )
    metadata_template = work_root / "metadata.template.json"
    metadata_merged = work_root / "metadata.merged.json"
    metadata_lint_json = work_root / "metadata_lint.json"
    metadata_lint_md = work_root / "metadata_lint.md"
    metadata_lint_redaction = work_root / "metadata_lint_redaction.json"
    metadata_merge_json = work_root / "metadata_merge.json"
    metadata_merge_md = work_root / "metadata_merge.md"
    metadata_merge_redaction = work_root / "metadata_merge_redaction.json"
    metadata_template_result = _run_command(
        [
            python_executable,
            str(build_script),
            "metadata",
            "generate-template",
            "--doc-manifest",
            str(doc_manifest),
            "--output",
            str(metadata_template),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build metadata generate-template",
        metadata_template_result,
        required_output='"schema": "ragflow_metadata_v1"',
    )
    metadata_lint_result = _run_command(
        [
            python_executable,
            str(build_script),
            "metadata",
            "lint",
            "--metadata",
            str(metadata_template),
            "--report-json",
            str(metadata_lint_json),
            "--report-md",
            str(metadata_lint_md),
            "--redaction-report",
            str(metadata_lint_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build metadata lint",
        metadata_lint_result,
        required_output='"schema": "ragflow_metadata_lint_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build metadata lint redaction",
        metadata_lint_redaction,
        result=metadata_lint_result,
        checked_paths=(metadata_lint_json, metadata_lint_md),
    )
    metadata_merge_result = _run_command(
        [
            python_executable,
            str(build_script),
            "metadata",
            "merge",
            "--doc-manifest",
            str(doc_manifest),
            "--handoff-metadata",
            str(handoff_dir / "metadata.json"),
            "--metadata",
            str(metadata_template),
            "--output",
            str(metadata_merged),
            "--report-json",
            str(metadata_merge_json),
            "--report-md",
            str(metadata_merge_md),
            "--redaction-report",
            str(metadata_merge_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build metadata merge",
        metadata_merge_result,
        required_output='"schema": "ragflow_metadata_merge_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build metadata merge redaction",
        metadata_merge_redaction,
        result=metadata_merge_result,
        checked_paths=(metadata_merge_json, metadata_merge_md),
    )
    for path in (
        metadata_template,
        metadata_merged,
        metadata_lint_json,
        metadata_lint_md,
        metadata_lint_redaction,
        metadata_merge_json,
        metadata_merge_md,
        metadata_merge_redaction,
    ):
        if path.exists():
            produced.append(path)

    topology_advice = work_root / "kb_topology_advice.json"
    topology_advice_md = work_root / "kb_topology_advice.md"
    topology_advice_redaction = work_root / "kb_topology_advice_redaction.json"
    topology_result = _run_command(
        [
            python_executable,
            str(build_script),
            "topology",
            "advise",
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:consumer-topology",
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
            "--redaction-report",
            str(topology_advice_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build topology advise",
        topology_result,
        required_output='"schema": "kb_topology_advice_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build topology advise redaction",
        topology_advice_redaction,
        result=topology_result,
        checked_paths=(topology_advice, topology_advice_md),
    )
    for path in (topology_advice, topology_advice_md, topology_advice_redaction):
        if path.exists():
            produced.append(path)

    split_plan = work_root / "kb_split_plan.json"
    split_plan_md = work_root / "kb_split_plan.md"
    split_plan_redaction = work_root / "kb_split_plan_redaction.json"
    split_plan_result = _run_command(
        [
            python_executable,
            str(build_script),
            "topology",
            "split-plan",
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:consumer-topology",
            "--metadata",
            str(metadata_template),
            "--retrieval-hints",
            str(handoff_dir / "retrieval_hints.json"),
            "--output",
            str(split_plan),
            "--report-md",
            str(split_plan_md),
            "--redaction-report",
            str(split_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build topology split-plan",
        split_plan_result,
        required_output='"schema": "kb_split_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build topology split-plan redaction",
        split_plan_redaction,
        result=split_plan_result,
        checked_paths=(split_plan, split_plan_md),
    )
    for path in (split_plan, split_plan_md, split_plan_redaction):
        if path.exists():
            produced.append(path)

    activation_kb_manifest = work_root / "activation_kb_manifest.json"
    activation_chunk_snapshot = work_root / "activation_chunk_snapshot.json"
    activation_route_config = work_root / "activation_routing.json"
    activation_route_tests = work_root / "activation_route_tests.json"
    activation_plan = work_root / "kb_activation_plan.json"
    activation_plan_md = work_root / "kb_activation_plan.md"
    activation_plan_redaction = work_root / "kb_activation_plan_redaction.json"
    activation_kb_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {"id": "ds-consumer-topology", "name": "kb:consumer-topology"},
                "profile": {"id": "consumer-topology", "embedding_model": "bge-m3"},
                "documents": [
                    {
                        "document_id": "doc-consumer-topology",
                        "source_path": "input-docs/sample.md",
                        "markdown_path": str(handoff_dir / "documents" / "sample.md"),
                        "status": "done",
                        "chunk_count": 1,
                    }
                ],
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
                        "dataset_id": "ds-consumer-topology",
                        "document_id": "doc-consumer-topology",
                        "chunk_id": "chunk-consumer-topology-1",
                        "content": "Consumer topology activation sample.",
                    }
                ],
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
                        "name": "kb:consumer-topology",
                        "dataset_id": "ds-consumer-topology",
                        "hints": ["consumer", "topology", "activation"],
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
                        "id": "activate-1",
                        "question": "How does consumer topology activation work?",
                        "expected_kb": "kb:consumer-topology",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    activation_plan_result = _run_command(
        [
            python_executable,
            str(build_script),
            "activation-plan",
            "--kb-manifest",
            str(activation_kb_manifest),
            "--doc-manifest",
            str(doc_manifest),
            "--route-config",
            str(activation_route_config),
            "--retrieval-hints",
            str(handoff_dir / "retrieval_hints.json"),
            "--chunk-snapshot",
            str(activation_chunk_snapshot),
            "--route-tests",
            str(activation_route_tests),
            "--output",
            str(activation_plan),
            "--report-md",
            str(activation_plan_md),
            "--redaction-report",
            str(activation_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build activation-plan",
        activation_plan_result,
        required_output='"schema": "kb_activation_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build activation-plan redaction",
        activation_plan_redaction,
        result=activation_plan_result,
        checked_paths=(activation_plan, activation_plan_md),
    )
    for path in (
        activation_kb_manifest,
        activation_chunk_snapshot,
        activation_route_config,
        activation_route_tests,
        activation_plan,
        activation_plan_md,
        activation_plan_redaction,
    ):
        if path.exists():
            produced.append(path)

    parse_documents_json = work_root / "parse_documents.json"
    parse_log = work_root / "parse.log"
    parse_report = work_root / "parse_report.json"
    parse_report_md = work_root / "parse_report.md"
    parse_report_redaction = work_root / "parse_report_redaction.json"
    parse_documents_json.write_text(
        json.dumps(
            {
                "data": {
                    "doc_count": 1,
                    "chunk_count": 1,
                    "docs": [
                        {
                            "id": "doc-consumer-topology",
                            "name": "sample.md",
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
    parse_log.write_text("parse phase completed in 1.1s\nchunk phase completed in 90ms\n", encoding="utf-8")
    parse_report_result = _run_command(
        [
            python_executable,
            str(build_script),
            "parse-report",
            "--kb-manifest",
            str(activation_kb_manifest),
            "--documents-json",
            str(parse_documents_json),
            "--parse-log",
            str(parse_log),
            "--profile",
            str(profile),
            "--report-json",
            str(parse_report),
            "--report-md",
            str(parse_report_md),
            "--redaction-report",
            str(parse_report_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build parse-report",
        parse_report_result,
        required_output='"schema": "ragflow_parse_report_v1"',
    )
    _record_file_check(checks, "kb-build parse-report redaction", parse_report_redaction)
    for path in (parse_documents_json, parse_log, parse_report, parse_report_md, parse_report_redaction):
        if path.exists():
            produced.append(path)

    health_report = work_root / "kb_health_report.json"
    health_report_md = work_root / "kb_health_report.md"
    health_report_redaction = work_root / "kb_health_report_redaction.json"
    health_report_result = _run_command(
        [
            python_executable,
            str(build_script),
            "health-report",
            "--kb-manifest",
            str(activation_kb_manifest),
            "--parse-report",
            str(parse_report),
            "--activation-plan",
            str(activation_plan),
            "--expected-embedding-model",
            "bge-m3",
            "--report-json",
            str(health_report),
            "--report-md",
            str(health_report_md),
            "--redaction-report",
            str(health_report_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build health-report",
        health_report_result,
        required_output='"schema": "ragflow_kb_health_report_v1"',
    )
    _record_file_check(checks, "kb-build health-report redaction", health_report_redaction)
    for path in (health_report, health_report_md, health_report_redaction):
        if path.exists():
            produced.append(path)

    tagset_template = work_root / "tagset.template.json"
    tagset_csv = work_root / "tagset.csv"
    tagset_lint_json = work_root / "tagset_lint.json"
    tagset_lint_md = work_root / "tagset_lint.md"
    tagset_lint_redaction = work_root / "tagset_lint_redaction.json"
    tagset_report_json = work_root / "tagset_report.json"
    tagset_report_md = work_root / "tagset_report.md"
    tagset_report_redaction = work_root / "tagset_report_redaction.json"
    tagset_template_result = _run_command(
        [
            python_executable,
            str(build_script),
            "tagset",
            "generate-template",
            "--output",
            str(tagset_template),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build tagset generate-template",
        tagset_template_result,
        required_output='"schema": "ragflow_tagset_v1"',
    )
    tagset_lint_result = _run_command(
        [
            python_executable,
            str(build_script),
            "tagset",
            "lint",
            "--tagset",
            str(tagset_template),
            "--report-json",
            str(tagset_lint_json),
            "--report-md",
            str(tagset_lint_md),
            "--redaction-report",
            str(tagset_lint_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build tagset lint",
        tagset_lint_result,
        required_output='"schema": "ragflow_tagset_lint_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build tagset lint redaction",
        tagset_lint_redaction,
        result=tagset_lint_result,
        checked_paths=(tagset_lint_json, tagset_lint_md),
    )
    tagset_export_result = _run_command(
        [
            python_executable,
            str(build_script),
            "tagset",
            "export",
            "--tagset",
            str(tagset_template),
            "--format",
            "csv",
            "--output",
            str(tagset_csv),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build tagset export",
        tagset_export_result,
        required_output='"format": "csv"',
    )
    tagset_report_result = _run_command(
        [
            python_executable,
            str(build_script),
            "tagset",
            "report",
            "--tagset",
            str(tagset_template),
            "--report-json",
            str(tagset_report_json),
            "--report-md",
            str(tagset_report_md),
            "--redaction-report",
            str(tagset_report_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build tagset report",
        tagset_report_result,
        required_output='"schema": "ragflow_tagset_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build tagset report redaction",
        tagset_report_redaction,
        result=tagset_report_result,
        checked_paths=(tagset_report_json, tagset_report_md),
    )
    for path in (
        tagset_template,
        tagset_lint_json,
        tagset_lint_md,
        tagset_lint_redaction,
        tagset_csv,
        tagset_report_json,
        tagset_report_md,
        tagset_report_redaction,
    ):
        if path.exists():
            produced.append(path)

    build_result = _run_command(
        [
            python_executable,
            str(build_script),
            "--doc-manifest",
            str(doc_manifest),
            "--metadata",
            str(metadata_merged),
            "--kb-name",
            "kb:consumer-acceptance",
            "--profile",
            str(profile),
            "--dry-run",
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "kb-build dry-run", build_result, required_output='"dry_run": true')

    model_provider_json = work_root / "model_provider_probe.json"
    model_provider_md = work_root / "model_provider_probe.md"
    model_provider_redaction = work_root / "model_provider_redaction.json"
    with _model_provider_server() as model_provider_base_url:
        model_provider_result = _run_command(
            [
                python_executable,
                str(build_script),
                "model-providers",
                "probe",
                "--base-url",
                model_provider_base_url,
                "--api-key",
                "consumer-test-key",
                "--embedding-model",
                "bge-m3",
                "--rerank-model",
                "bge-reranker",
                "--embedding-adapter-url",
                f"{model_provider_base_url}/embeddings",
                "--rerank-adapter-url",
                f"{model_provider_base_url}/rerank",
                "--report-json",
                str(model_provider_json),
                "--report-md",
                str(model_provider_md),
                "--redaction-report",
                str(model_provider_redaction),
                "--json",
            ],
            cwd=work_root,
            env=env,
        )
    _record_command_check(
        checks,
        "kb-build model-providers probe",
        model_provider_result,
        required_output='"schema": "ragflow_model_provider_probe_report_v1"',
    )
    for path in (model_provider_json, model_provider_md, model_provider_redaction):
        if path.exists():
            produced.append(path)

    inspect_handoff_json = work_root / "handoff_inspection.json"
    inspect_handoff_report = work_root / "handoff_inspection.md"
    inspect_handoff_redaction = work_root / "handoff_inspection_redaction.json"
    inspect_handoff_result = _run_command(
        [
            python_executable,
            str(build_script),
            "inspect-handoff",
            "--handoff",
            str(handoff_dir),
            "--report-json",
            str(inspect_handoff_json),
            "--report-md",
            str(inspect_handoff_report),
            "--redaction-report",
            str(inspect_handoff_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "kb-build inspect rich handoff", inspect_handoff_result, required_output='"schema": "ragflow_handoff_inspection_v1"')
    _record_redaction_sidecar_check(
        checks,
        "kb-build inspect-handoff redaction",
        inspect_handoff_redaction,
        result=inspect_handoff_result,
        checked_paths=(inspect_handoff_json, inspect_handoff_report),
    )
    for path in (inspect_handoff_json, inspect_handoff_report, inspect_handoff_redaction):
        if path.exists():
            produced.append(path)

    profile_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "profile.py")
    profile_lint_json = work_root / "profile_lint.json"
    profile_lint_md = work_root / "profile_lint.md"
    profile_lint_redaction = work_root / "profile_lint_redaction.json"
    profile_lint_result = _run_command(
        [
            python_executable,
            str(profile_script),
            "lint",
            "--profile",
            str(profile),
            "--report-json",
            str(profile_lint_json),
            "--report-md",
            str(profile_lint_md),
            "--redaction-report",
            str(profile_lint_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build profile lint",
        profile_lint_result,
        required_output='"schema": "ragflow_profile_lint_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build profile lint redaction",
        profile_lint_redaction,
        result=profile_lint_result,
        checked_paths=(profile_lint_json, profile_lint_md),
    )
    for path in (profile_lint_json, profile_lint_md, profile_lint_redaction):
        if path.exists():
            produced.append(path)

    recommended_profile = work_root / "recommended_profile.json"
    profile_recommend_json = work_root / "profile_recommendation.json"
    profile_recommend_redaction = work_root / "profile_recommendation_redaction.json"
    profile_recommend_result = _run_command(
        [
            python_executable,
            str(profile_script),
            "recommend",
            "--language",
            "en",
            "--doc-type",
            "manual",
            "--output",
            str(recommended_profile),
            "--report-json",
            str(profile_recommend_json),
            "--redaction-report",
            str(profile_recommend_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build profile recommend",
        profile_recommend_result,
        required_output='"schema": "ragflow_profile_recommendation_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build profile recommend redaction",
        profile_recommend_redaction,
        result=profile_recommend_result,
        checked_paths=(profile_recommend_json,),
    )
    for path in (recommended_profile, profile_recommend_json, profile_recommend_redaction):
        if path.exists():
            produced.append(path)

    profile_experiment_candidate_set = work_root / "candidate_profile_set.json"
    profile_experiment_json = work_root / "profile_experiment_matrix.json"
    profile_experiment_md = work_root / "profile_experiment_matrix.md"
    profile_experiment_redaction = work_root / "profile_experiment_matrix_redaction.json"
    profile_experiment_result = _run_command(
        [
            python_executable,
            str(profile_script),
            "experiment",
            "--base-profile",
            str(profile),
            "--set",
            "auto_keywords=0,3",
            "--set",
            "auto_questions=0",
            "--set",
            "retrieval.top_k=3,5",
            "--candidate-set",
            str(profile_experiment_candidate_set),
            "--report-json",
            str(profile_experiment_json),
            "--report-md",
            str(profile_experiment_md),
            "--redaction-report",
            str(profile_experiment_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build profile experiment",
        profile_experiment_result,
        required_output='"schema": "ragflow_enrichment_experiment_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build profile experiment redaction",
        profile_experiment_redaction,
        result=profile_experiment_result,
        checked_paths=(profile_experiment_json, profile_experiment_md),
    )
    for path in (
        profile_experiment_candidate_set,
        profile_experiment_json,
        profile_experiment_md,
        profile_experiment_redaction,
    ):
        if path.exists():
            produced.append(path)

    validate_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "validate.py")
    benchmark_manifest = work_root / "benchmark_kb_manifest.json"
    benchmark_queries = work_root / "benchmark_queries.json"
    benchmark_qrels = work_root / "benchmark_qrels.json"
    benchmark_qa = work_root / "benchmark_qa.json"
    segment_metadata_plan = work_root / "segment_metadata_plan.json"
    benchmark_gate = work_root / "benchmark_gate.json"
    benchmark_chunk_input = work_root / "benchmark_chunks.json"
    benchmark_chunk_snapshot = work_root / "benchmark_chunk_snapshot.json"
    benchmark_chunk_snapshot_md = work_root / "benchmark_chunk_snapshot.md"
    benchmark_chunk_snapshot_redaction = work_root / "benchmark_chunk_snapshot_redaction.json"
    benchmark_report_json = work_root / "benchmark_report.json"
    benchmark_report_md = work_root / "benchmark_report.md"
    benchmark_validation_redaction = work_root / "benchmark_validation_redaction.json"
    baseline_benchmark_report_json = work_root / "baseline_benchmark_report.json"
    suppression_input_json = work_root / "suppression_input.json"
    suppression_report_json = work_root / "suppression_report.json"
    suppression_report_md = work_root / "suppression_report.md"
    suppression_report_redaction = work_root / "suppression_report_redaction.json"
    benchmark_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {"id": "ds-consumer-acceptance", "name": "kb:consumer-acceptance"},
                "documents": [],
            }
        ),
        encoding="utf-8",
    )
    benchmark_queries.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "q1",
                        "question": "What can run without repository source context?",
                        "min_chunks": 1,
                        "metadata": {"type": "fact"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    benchmark_chunk_content = "This release artifact can run without repository source context."
    benchmark_chunk_hash = "sha256:" + hashlib.sha256(benchmark_chunk_content.encode("utf-8")).hexdigest()
    benchmark_qrels.write_text(
        json.dumps(
            {
                "qrels": [
                    {
                        "query_id": "q1",
                        "expected_documents": ["sample.md"],
                        "expected_chunks": [benchmark_chunk_hash],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    benchmark_qa.write_text(
        json.dumps(
            {
                "schema": "ragflow_grounded_qa_v1",
                "items": [
                    {
                        "id": "qa-q1",
                        "query_id": "q1",
                        "question": "What can run without repository source context?",
                        "answer": "This release artifact can run without repository source context.",
                        "evidence": [
                            {
                                "document": "sample.md",
                                "text": "This release artifact can run without repository source context.",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    segment_metadata_plan.write_text(
        json.dumps(
            {
                "schema": "doc_segmentation_plan_v1",
                "segments": [{"index": 1, "suggested_markdown_path": "sample.md"}],
            }
        ),
        encoding="utf-8",
    )
    benchmark_chunk_input.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "content": benchmark_chunk_content,
                        "document_name": "sample.md",
                        "chunk_id": "consumer-acceptance-chunk",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    benchmark_gate.write_text(
        json.dumps({"thresholds": {"min_hit_rate": 1.0, "min_mrr": 1.0, "min_strict_chunk_recall_at_k": 1.0}}),
        encoding="utf-8",
    )
    baseline_benchmark_report_json.write_text(
        json.dumps(
            {
                "ok": True,
                "benchmark": {
                    "metrics": {
                        "query_count": 1,
                        "hit_rate": 1.0,
                        "mrr": 0.8,
                        "precision_at_k": 0.25,
                        "recall_at_k": 1.0,
                        "ndcg_at_k": 0.8,
                        "map_at_k": 0.8,
                        "empty_result_rate": 0.0,
                        "supporting_document_coverage": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    suppression_input_json.write_text(
        json.dumps(
            {
                "ok": False,
                "level": "benchmark",
                "dataset": {"id": "ds-consumer-acceptance", "name": "kb:consumer-acceptance"},
                "cases": [
                    {
                        "id": "q1",
                        "question": "What can run without repository source context?",
                        "passed": False,
                        "document_hits": ["sample.md"],
                        "metadata": {"type": "fact", "allowed_tags": ["example-tag"]},
                        "top_chunks": [
                            {
                                "content": "Repository bridge term appears in an unrelated finance source.",
                                "document_name": "finance.md",
                                "document_id": "doc-finance",
                                "chunk_id": "wrong-1",
                                "raw": {
                                    "content_with_weight": "Repository bridge term appears in an unrelated finance source.",
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
            }
        ),
        encoding="utf-8",
    )
    benchmark_snapshot_result = _run_command(
        [
            python_executable,
            str(build_script),
            "snapshot-chunks",
            "--input",
            str(benchmark_chunk_input),
            "--output",
            str(benchmark_chunk_snapshot),
            "--report-md",
            str(benchmark_chunk_snapshot_md),
            "--redaction-report",
            str(benchmark_chunk_snapshot_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build snapshot-chunks",
        benchmark_snapshot_result,
        required_output='"schema": "ragflow_chunk_snapshot_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build snapshot-chunks redaction",
        benchmark_chunk_snapshot_redaction,
        result=benchmark_snapshot_result,
        checked_paths=(benchmark_chunk_snapshot_md,),
    )
    benchmark_runner = work_root / "run_benchmark_validate.py"
    benchmark_runner.write_text(
        f"""\
import importlib.util
import json
from pathlib import Path

script = Path({str(validate_script)!r})
spec = importlib.util.spec_from_file_location("consumer_validate_cli", script)
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
                        "content_with_weight": "This release artifact can run without repository source context.",
                        "docnm_kwd": "sample.md",
                        "similarity": 0.99,
                        "kb_id": dataset_ids[0],
                    }}
                ]
            }}
        }}

module.RAGFlowClient = FakeClient
code = module.main([
    "--kb-manifest", {str(benchmark_manifest)!r},
    "--level", "benchmark",
    "--queries", {str(benchmark_queries)!r},
    "--qrels", {str(benchmark_qrels)!r},
    "--chunk-snapshot", {str(benchmark_chunk_snapshot)!r},
    "--gate-config", {str(benchmark_gate)!r},
    "--base-url", "https://ragflow.example.test",
    "--metadata", {str(metadata_merged)!r},
    "--report-json", {str(benchmark_report_json)!r},
    "--report-md", {str(benchmark_report_md)!r},
    "--redaction-report", {str(benchmark_validation_redaction)!r},
])
raise SystemExit(code)
""",
        encoding="utf-8",
    )
    benchmark_result = _run_command([python_executable, str(benchmark_runner)], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build benchmark validation",
        benchmark_result,
        required_output='"benchmark"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build validate redaction",
        benchmark_validation_redaction,
        result=benchmark_result,
        checked_paths=(benchmark_report_json, benchmark_report_md),
    )
    for path in (benchmark_report_json, benchmark_report_md, benchmark_validation_redaction):
        if path.exists():
            produced.append(path)

    suppression_result = _run_command(
        [
            python_executable,
            str(build_script),
            "suppression-report",
            "--report",
            str(suppression_input_json),
            "--tagset",
            str(tagset_template),
            "--report-json",
            str(suppression_report_json),
            "--report-md",
            str(suppression_report_md),
            "--redaction-report",
            str(suppression_report_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build suppression-report",
        suppression_result,
        required_output='"schema": "ragflow_suppression_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build suppression-report redaction",
        suppression_report_redaction,
        result=suppression_result,
        checked_paths=(suppression_report_json, suppression_report_md),
    )
    for path in (suppression_report_json, suppression_report_md, suppression_report_redaction):
        if path.exists():
            produced.append(path)

    benchmark_dir = work_root / "benchmark"
    benchmark_sample_dir = work_root / "benchmark_sample"
    benchmark_import_md = work_root / "benchmark_import.md"
    benchmark_preflight_md = work_root / "benchmark_preflight.md"
    benchmark_sample_md = work_root / "benchmark_sample.md"
    benchmark_summary_md = work_root / "benchmark_summary.md"
    benchmark_gate_md = work_root / "benchmark_gate.md"
    benchmark_trend_md = work_root / "benchmark_trend.md"
    benchmark_delta_md = work_root / "benchmark_delta.md"
    benchmark_suggest_md = work_root / "benchmark_suggest.md"
    benchmark_import_redaction = work_root / "benchmark_import_redaction.json"
    benchmark_preflight_redaction = work_root / "benchmark_preflight_redaction.json"
    benchmark_sample_redaction = work_root / "benchmark_sample_redaction.json"
    benchmark_summary_redaction = work_root / "benchmark_summary_redaction.json"
    benchmark_gate_redaction = work_root / "benchmark_gate_redaction.json"
    benchmark_trend_redaction = work_root / "benchmark_trend_redaction.json"
    benchmark_delta_redaction = work_root / "benchmark_delta_redaction.json"
    benchmark_suggest_redaction = work_root / "benchmark_suggest_redaction.json"
    qa_generated = work_root / "qa.generated.json"
    qa_generate_md = work_root / "qa_generate.md"
    qa_validate_md = work_root / "qa_validate.md"
    qa_evidence_map = work_root / "qa_evidence_map.json"
    qa_evidence_map_md = work_root / "qa_evidence_map.md"
    segment_metadata_md = work_root / "segment_metadata.md"
    qa_generate_redaction = work_root / "qa_generate_redaction.json"
    qa_validate_redaction = work_root / "qa_validate_redaction.json"
    qa_evidence_map_redaction = work_root / "qa_evidence_map_redaction.json"
    segment_metadata_redaction = work_root / "segment_metadata_redaction.json"
    optimization_plan = work_root / "optimization_plan.json"
    optimization_plan_md = work_root / "optimization_plan.md"
    optimization_plan_redaction = work_root / "optimization_plan_redaction.json"
    optimization_cleanup_plan = work_root / "optimization_cleanup_plan.json"
    optimization_cleanup_plan_md = work_root / "optimization_cleanup_plan.md"
    optimization_cleanup_plan_redaction = work_root / "optimization_cleanup_plan_redaction.json"
    profile_experiment_results = work_root / "profile_experiment_results.json"
    best_profile_report_md = work_root / "best_profile_report.md"
    best_profile_report_redaction = work_root / "best_profile_report_redaction.json"
    benchmark_import_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "import",
            "--queries",
            str(benchmark_queries),
            "--qrels",
            str(benchmark_qrels),
            "--qa",
            str(benchmark_qa),
            "--output",
            str(benchmark_dir),
            "--report-md",
            str(benchmark_import_md),
            "--redaction-report",
            str(benchmark_import_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark import",
        benchmark_import_result,
        required_output='"schema": "ragflow_benchmark_import_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark import redaction",
        benchmark_import_redaction,
        result=benchmark_import_result,
        checked_paths=(benchmark_import_md,),
    )
    qa_generate_result = _run_command(
        [
            python_executable,
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
            "--report-md",
            str(qa_generate_md),
            "--redaction-report",
            str(qa_generate_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build qa generate",
        qa_generate_result,
        required_output='"schema": "ragflow_grounded_qa_generate_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build qa generate redaction",
        qa_generate_redaction,
        result=qa_generate_result,
        checked_paths=(qa_generate_md,),
    )
    qa_validate_result = _run_command(
        [
            python_executable,
            str(build_script),
            "qa",
            "validate",
            "--qa",
            str(benchmark_dir / "qa.json"),
            "--source-dir",
            str(input_dir),
            "--report-md",
            str(qa_validate_md),
            "--redaction-report",
            str(qa_validate_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build qa validate",
        qa_validate_result,
        required_output='"schema": "ragflow_grounded_qa_validate_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build qa validate redaction",
        qa_validate_redaction,
        result=qa_validate_result,
        checked_paths=(qa_validate_md,),
    )
    qa_map_result = _run_command(
        [
            python_executable,
            str(build_script),
            "qa",
            "map-evidence",
            "--qa",
            str(benchmark_dir / "qa.json"),
            "--chunk-snapshot",
            str(benchmark_chunk_snapshot),
            "--output",
            str(qa_evidence_map),
            "--report-md",
            str(qa_evidence_map_md),
            "--redaction-report",
            str(qa_evidence_map_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build qa map-evidence",
        qa_map_result,
        required_output='"schema": "ragflow_grounded_qa_evidence_map_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build qa map-evidence redaction",
        qa_evidence_map_redaction,
        result=qa_map_result,
        checked_paths=(qa_evidence_map_md,),
    )
    segment_metadata_result = _run_command(
        [
            python_executable,
            str(build_script),
            "segment-metadata",
            "report",
            "--chunk-snapshot",
            str(benchmark_chunk_snapshot),
            "--metadata",
            str(metadata_merged),
            "--segmentation-plan",
            str(segment_metadata_plan),
            "--report-md",
            str(segment_metadata_md),
            "--redaction-report",
            str(segment_metadata_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build segment-metadata report",
        segment_metadata_result,
        required_output='"schema": "ragflow_segment_metadata_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build segment-metadata redaction",
        segment_metadata_redaction,
        result=segment_metadata_result,
        checked_paths=(segment_metadata_md,),
    )
    optimize_plan_result = _run_command(
        [
            python_executable,
            str(build_script),
            "optimize",
            "--plan-only",
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            "kb:consumer-acceptance",
            "--profile",
            str(recommended_profile),
            "--recommendation",
            "zh:notes",
            "--benchmark-manifest",
            str(benchmark_dir / "manifest.json"),
            "--metadata",
            str(metadata_merged),
            "--chunk-snapshot",
            str(benchmark_chunk_snapshot),
            "--gate-config",
            str(benchmark_gate),
            "--baseline-report",
            str(baseline_benchmark_report_json),
            "--run-id",
            "acceptance",
            "--output",
            str(optimization_plan),
            "--report-md",
            str(optimization_plan_md),
            "--redaction-report",
            str(optimization_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build optimize plan-only",
        optimize_plan_result,
        required_output='"schema": "ragflow_optimization_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build optimize plan-only redaction",
        optimization_plan_redaction,
        result=optimize_plan_result,
        checked_paths=(optimization_plan, optimization_plan_md),
    )
    optimize_cleanup_plan_result = _run_command(
        [
            python_executable,
            str(build_script),
            "optimize",
            "cleanup-plan",
            "--plan",
            str(optimization_plan),
            "--output",
            str(optimization_cleanup_plan),
            "--report-md",
            str(optimization_cleanup_plan_md),
            "--redaction-report",
            str(optimization_cleanup_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build optimize cleanup-plan",
        optimize_cleanup_plan_result,
        required_output='"schema": "ragflow_optimization_cleanup_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build optimize cleanup-plan redaction",
        optimization_cleanup_plan_redaction,
        result=optimize_cleanup_plan_result,
        checked_paths=(optimization_cleanup_plan, optimization_cleanup_plan_md),
    )
    optimize_summary_result = _run_command(
        [
            python_executable,
            str(build_script),
            "optimize",
            "summarize",
            "--plan",
            str(optimization_plan),
            "--report",
            str(benchmark_report_json),
            "--report",
            str(baseline_benchmark_report_json),
            "--output",
            str(profile_experiment_results),
            "--report-md",
            str(best_profile_report_md),
            "--redaction-report",
            str(best_profile_report_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build optimize summarize",
        optimize_summary_result,
        required_output='"schema": "ragflow_profile_experiment_results_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build optimize summarize redaction",
        best_profile_report_redaction,
        result=optimize_summary_result,
        checked_paths=(profile_experiment_results, best_profile_report_md),
    )
    benchmark_preflight_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "preflight",
            "--manifest",
            str(benchmark_dir / "manifest.json"),
            "--chunk-snapshot",
            str(benchmark_chunk_snapshot),
            "--gate-config",
            str(benchmark_gate),
            "--report-md",
            str(benchmark_preflight_md),
            "--redaction-report",
            str(benchmark_preflight_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark preflight",
        benchmark_preflight_result,
        required_output='"schema": "ragflow_benchmark_preflight_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark preflight redaction",
        benchmark_preflight_redaction,
        result=benchmark_preflight_result,
        checked_paths=(benchmark_preflight_md,),
    )
    benchmark_sample_result = _run_command(
        [
            python_executable,
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
            "--report-md",
            str(benchmark_sample_md),
            "--redaction-report",
            str(benchmark_sample_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark sample",
        benchmark_sample_result,
        required_output='"schema": "ragflow_benchmark_sample_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark sample redaction",
        benchmark_sample_redaction,
        result=benchmark_sample_result,
        checked_paths=(benchmark_sample_md,),
    )
    benchmark_summary_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "summarize",
            "--report",
            str(benchmark_report_json),
            "--report-md",
            str(benchmark_summary_md),
            "--redaction-report",
            str(benchmark_summary_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark summarize",
        benchmark_summary_result,
        required_output='"schema": "ragflow_benchmark_summary_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark summarize redaction",
        benchmark_summary_redaction,
        result=benchmark_summary_result,
        checked_paths=(benchmark_summary_md,),
    )
    benchmark_gate_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "gate",
            "--report",
            str(benchmark_report_json),
            "--gate-config",
            str(benchmark_gate),
            "--report-md",
            str(benchmark_gate_md),
            "--redaction-report",
            str(benchmark_gate_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark gate",
        benchmark_gate_result,
        required_output='"schema": "ragflow_benchmark_gate_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark gate redaction",
        benchmark_gate_redaction,
        result=benchmark_gate_result,
        checked_paths=(benchmark_gate_md,),
    )
    benchmark_trend_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "trend",
            "--report",
            str(benchmark_report_json),
            "--baseline-report",
            str(baseline_benchmark_report_json),
            "--gate-config",
            str(benchmark_gate),
            "--report-md",
            str(benchmark_trend_md),
            "--redaction-report",
            str(benchmark_trend_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark trend",
        benchmark_trend_result,
        required_output='"schema": "ragflow_benchmark_trend_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark trend redaction",
        benchmark_trend_redaction,
        result=benchmark_trend_result,
        checked_paths=(benchmark_trend_md,),
    )
    benchmark_delta_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "delta",
            "--report",
            str(benchmark_report_json),
            "--baseline-report",
            str(baseline_benchmark_report_json),
            "--report-md",
            str(benchmark_delta_md),
            "--redaction-report",
            str(benchmark_delta_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark delta",
        benchmark_delta_result,
        required_output='"schema": "ragflow_benchmark_delta_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark delta redaction",
        benchmark_delta_redaction,
        result=benchmark_delta_result,
        checked_paths=(benchmark_delta_md,),
    )
    benchmark_suggest_result = _run_command(
        [
            python_executable,
            str(build_script),
            "benchmark",
            "suggest",
            "--report",
            str(benchmark_report_json),
            "--baseline-report",
            str(baseline_benchmark_report_json),
            "--gate-config",
            str(benchmark_gate),
            "--current-top-k",
            "3",
            "--current-similarity-threshold",
            "0.25",
            "--report-md",
            str(benchmark_suggest_md),
            "--redaction-report",
            str(benchmark_suggest_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build benchmark suggest",
        benchmark_suggest_result,
        required_output='"schema": "ragflow_benchmark_retrieval_suggestion_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build benchmark suggest redaction",
        benchmark_suggest_redaction,
        result=benchmark_suggest_result,
        checked_paths=(benchmark_suggest_md,),
    )
    for path in (
        benchmark_dir / "manifest.json",
        benchmark_dir / "queries.json",
        benchmark_dir / "qrels.json",
        benchmark_dir / "qa.json",
        benchmark_sample_dir / "manifest.json",
        benchmark_sample_dir / "queries.json",
        benchmark_sample_dir / "qrels.json",
        benchmark_sample_dir / "qa.json",
        benchmark_chunk_snapshot,
        benchmark_chunk_snapshot_md,
        benchmark_chunk_snapshot_redaction,
        benchmark_import_md,
        benchmark_import_redaction,
        qa_generated,
        qa_generate_md,
        qa_generate_redaction,
        qa_validate_md,
        qa_validate_redaction,
        qa_evidence_map,
        qa_evidence_map_md,
        qa_evidence_map_redaction,
        segment_metadata_md,
        segment_metadata_redaction,
        optimization_plan,
        optimization_plan_md,
        optimization_plan_redaction,
        optimization_cleanup_plan,
        optimization_cleanup_plan_md,
        optimization_cleanup_plan_redaction,
        profile_experiment_results,
        best_profile_report_md,
        best_profile_report_redaction,
        benchmark_preflight_md,
        benchmark_preflight_redaction,
        benchmark_sample_md,
        benchmark_sample_redaction,
        benchmark_summary_md,
        benchmark_summary_redaction,
        benchmark_gate_md,
        benchmark_gate_redaction,
        benchmark_trend_md,
        benchmark_trend_redaction,
        benchmark_delta_md,
        benchmark_delta_redaction,
        benchmark_suggest_md,
        benchmark_suggest_redaction,
    ):
        if path.exists():
            produced.append(path)

    append_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "append.py")
    append_help = _run_command([python_executable, str(append_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build append help",
        append_help,
        required_output="Append Markdown documents",
    )
    append_secret = "consumer-append-secret"
    append_host = "append.internal.local"
    append_input = work_root / f"append-token={append_secret}"
    append_input.mkdir(parents=True, exist_ok=True)
    (append_input / f"source-token={append_secret}.md").write_text("# Append\n", encoding="utf-8")
    append_manifest = work_root / f"append-kb-token={append_secret}.json"
    append_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {
                    "id": "append-dataset",
                    "name": f"kb:http://{append_host}:9380?token={append_secret}",
                },
                "documents": [],
            }
        ),
        encoding="utf-8",
    )
    append_plan = work_root / "append_plan.json"
    append_redaction = work_root / "append_plan_redaction.json"
    append_result = _run_command(
        [
            python_executable,
            str(append_script),
            "--kb-manifest",
            str(append_manifest),
            "--input",
            str(append_input),
            "--output",
            str(append_plan),
            "--redaction-report",
            str(append_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build append redaction",
        append_result,
        required_output='"schema": "ragflow_append_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build append redaction sidecar",
        append_redaction,
        result=append_result,
        checked_paths=(append_plan,),
        forbidden_literals=(append_secret, append_host, str(work_root)),
    )
    for path in (append_plan, append_redaction):
        if path.exists():
            produced.append(path)

    cleanup_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "cleanup.py")
    cleanup_help = _run_command([python_executable, str(cleanup_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build cleanup help",
        cleanup_help,
        required_output="Preview or execute cleanup",
    )
    cleanup_secret = "consumer-cleanup-secret"
    cleanup_host = "cleanup.internal.local"
    cleanup_manifest = work_root / f"cleanup-kb-token={cleanup_secret}.json"
    cleanup_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {
                    "id": "cleanup-dataset",
                    "name": f"kb:http://{cleanup_host}:9380?token={cleanup_secret}",
                },
                "documents": [],
            }
        ),
        encoding="utf-8",
    )
    cleanup_plan = work_root / "cleanup_plan.json"
    cleanup_redaction = work_root / "cleanup_plan_redaction.json"
    cleanup_result = _run_command(
        [
            python_executable,
            str(cleanup_script),
            "--kb-manifest",
            str(cleanup_manifest),
            "--output",
            str(cleanup_plan),
            "--redaction-report",
            str(cleanup_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build cleanup redaction",
        cleanup_result,
        required_output='"schema": "ragflow_cleanup_plan_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build cleanup redaction sidecar",
        cleanup_redaction,
        result=cleanup_result,
        checked_paths=(cleanup_plan,),
        forbidden_literals=(cleanup_secret, cleanup_host, str(work_root)),
    )
    for path in (cleanup_plan, cleanup_redaction):
        if path.exists():
            produced.append(path)

    diagnose_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "diagnose.py")
    diagnose_help = _run_command([python_executable, str(diagnose_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build diagnose help",
        diagnose_help,
        required_output="Diagnose a RAGFlow KB manifest",
    )
    diagnostic_secret = "consumer-diagnostic-secret"
    diagnostic_host = "diagnostic.internal.local"
    diagnostic_manifest = work_root / "diagnostic_kb_manifest.json"
    diagnostic_manifest.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {"id": "short", "name": f"kb:http://{diagnostic_host}:9380?token={diagnostic_secret}"},
                "documents": [{"document_id": "doc-1", "status": "running", "chunk_count": 0}],
            }
        ),
        encoding="utf-8",
    )
    diagnose_json = work_root / "diagnostic_report.json"
    diagnose_md = work_root / "diagnostic_report.md"
    diagnose_redaction = work_root / "diagnostic_report_redaction.json"
    diagnose_result = _run_command(
        [
            python_executable,
            str(diagnose_script),
            "--kb-manifest",
            str(diagnostic_manifest),
            "--report-json",
            str(diagnose_json),
            "--report-md",
            str(diagnose_md),
            "--redaction-report",
            str(diagnose_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "kb-build diagnose redaction report",
        diagnose_result,
        required_output='"schema": "ragflow_kb_diagnostic_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build diagnose redaction",
        diagnose_redaction,
        result=diagnose_result,
        checked_paths=(diagnose_json, diagnose_md),
        forbidden_literals=(diagnostic_secret, diagnostic_host),
    )
    for path in (diagnose_json, diagnose_md, diagnose_redaction):
        if path.exists():
            produced.append(path)

    probe_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "probe.py")
    probe_help = _run_command([python_executable, str(probe_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build probe help",
        probe_help,
        required_output="Probe RAGFlow API compatibility",
    )
    probe_json = work_root / "probe_report.json"
    probe_md = work_root / "probe_report.md"
    probe_redaction = work_root / "probe_report_redaction.json"
    with _diagnostic_probe_server() as probe_base_url:
        probe_result = _run_command(
            [
                python_executable,
                str(probe_script),
                "--base-url",
                probe_base_url,
                "--api-key",
                diagnostic_secret,
                "--report-json",
                str(probe_json),
                "--report-md",
                str(probe_md),
                "--redaction-report",
                str(probe_redaction),
                "--json",
            ],
            cwd=work_root,
            env=env,
        )
    _record_command_check(
        checks,
        "kb-build probe redaction report",
        probe_result,
        required_output='"schema": "ragflow_kb_diagnostic_report_v1"',
    )
    _record_redaction_sidecar_check(
        checks,
        "kb-build probe redaction",
        probe_redaction,
        result=probe_result,
        checked_paths=(probe_json, probe_md),
        forbidden_literals=("127.0.0.1", diagnostic_secret),
    )
    for path in (probe_json, probe_md, probe_redaction):
        if path.exists():
            produced.append(path)

    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    query_help = _run_command([python_executable, str(query_script), "--help"], cwd=work_root, env=env)
    _record_command_check(checks, "query top-level help", query_help, required_output="Portable RAGFlow query CLI")

    ask_help = _run_command([python_executable, str(query_script), "ask", "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "query host-assisted help",
        ask_help,
        required_output="--host-assisted",
    )

    rewrite_help = _run_command([python_executable, str(query_script), "rewrite", "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "query rewrite help",
        rewrite_help,
        required_output="Plan deterministic query rewrite variants",
    )
    intent_help = _run_command([python_executable, str(query_script), "intent", "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "query intent help",
        intent_help,
        required_output="Classify query intent offline",
    )
    session_help = _run_command([python_executable, str(query_script), "session", "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "query session help",
        session_help,
        required_output="Inspect bounded session context offline",
    )
    agentic_plan_help = _run_command(
        [python_executable, str(query_script), "agentic-plan", "--help"],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query agentic-plan help",
        agentic_plan_help,
        required_output="Plan deterministic agentic query orchestration",
    )
    endpoint_report_json = work_root / "query_endpoint_report.json"
    endpoint_report_md = work_root / "query_endpoint_report.md"
    endpoint_redaction_json = work_root / "query_endpoint_redaction.json"
    endpoint_cache_dir = work_root / "query_endpoint_cache"
    fake_lan_endpoint = "https://" + ".".join(("192", "168", "10", "20")) + ":9380"
    fake_vpn_endpoint = "vpn=http://" + ".".join(("100", "64", "10", "20")) + ":8080/v1?token=fake-secret"
    endpoint_report = _run_command(
        [
            python_executable,
            str(query_script),
            "endpoint-report",
            "--base-url",
            fake_lan_endpoint,
            "--api-key",
            "consumer-fake-key",
            "--endpoint",
            fake_vpn_endpoint,
            "--cache-dir",
            str(endpoint_cache_dir),
            "--cache-ttl-seconds",
            "60",
            "--report-json",
            str(endpoint_report_json),
            "--report-md",
            str(endpoint_report_md),
            "--redaction-report",
            str(endpoint_redaction_json),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query endpoint-report",
        endpoint_report,
        required_output='"schema": "ragflow_query_endpoint_report_v1"',
    )
    endpoint_metrics_ok = endpoint_report_json.exists()
    endpoint_metrics_error = ""
    if endpoint_metrics_ok:
        try:
            endpoint_payload = json.loads(endpoint_report_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            endpoint_metrics_ok = False
            endpoint_metrics_error = f"invalid endpoint report JSON: {exc}"
        else:
            endpoint_metrics = endpoint_payload.get("runtime_metrics")
            endpoint_latency = endpoint_metrics.get("latency_ms") if isinstance(endpoint_metrics, dict) else {}
            endpoint_metrics_ok = (
                isinstance(endpoint_metrics, dict)
                and endpoint_metrics.get("schema") == "ragflow_runtime_metrics_v1"
                and isinstance(endpoint_latency, dict)
                and endpoint_latency.get("sample_count") == 0
            )
            if not endpoint_metrics_ok:
                endpoint_metrics_error = "missing endpoint runtime metrics summary"
    else:
        endpoint_metrics_error = f"missing {endpoint_report_json}"
    checks.append(
        {
            "name": "query endpoint-report runtime metrics",
            "ok": endpoint_metrics_ok,
            "path": str(endpoint_report_json),
            "error": endpoint_metrics_error,
        }
    )
    endpoint_retry_ok = endpoint_report_json.exists()
    endpoint_retry_error = ""
    if endpoint_retry_ok:
        try:
            endpoint_payload = json.loads(endpoint_report_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            endpoint_retry_ok = False
            endpoint_retry_error = f"invalid endpoint report JSON: {exc}"
        else:
            endpoint_retry = endpoint_payload.get("retry_policy")
            endpoint_summary = endpoint_payload.get("summary")
            endpoint_retry_ok = (
                isinstance(endpoint_retry, dict)
                and endpoint_retry.get("retry_budget") == 1
                and isinstance(endpoint_summary, dict)
                and endpoint_summary.get("network_attempt_count") == 0
                and endpoint_summary.get("retry_count") == 0
            )
            if not endpoint_retry_ok:
                endpoint_retry_error = "missing endpoint retry policy summary"
    else:
        endpoint_retry_error = f"missing {endpoint_report_json}"
    checks.append(
        {
            "name": "query endpoint-report retry policy",
            "ok": endpoint_retry_ok,
            "path": str(endpoint_report_json),
            "error": endpoint_retry_error,
        }
    )
    endpoint_cache_ok = endpoint_report_json.exists()
    endpoint_cache_error = ""
    if endpoint_cache_ok:
        try:
            endpoint_payload = json.loads(endpoint_report_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            endpoint_cache_ok = False
            endpoint_cache_error = f"invalid endpoint report JSON: {exc}"
        else:
            endpoint_cache = endpoint_payload.get("runtime_cache")
            endpoint_cache_summary = endpoint_cache.get("summary") if isinstance(endpoint_cache, dict) else {}
            endpoint_cache_ok = (
                isinstance(endpoint_cache, dict)
                and endpoint_cache.get("schema") == "ragflow_runtime_cache_report_v1"
                and endpoint_cache.get("enabled") is True
                and isinstance(endpoint_cache_summary, dict)
                and endpoint_cache_summary.get("lookup_count") == 0
            )
            if not endpoint_cache_ok:
                endpoint_cache_error = "missing endpoint runtime cache summary"
    else:
        endpoint_cache_error = f"missing {endpoint_report_json}"
    checks.append(
        {
            "name": "query endpoint-report runtime cache",
            "ok": endpoint_cache_ok,
            "path": str(endpoint_report_json),
            "error": endpoint_cache_error,
        }
    )
    for path in (endpoint_report_json, endpoint_report_md, endpoint_redaction_json):
        if path.exists():
            produced.append(path)
    assistant_profile_recommendation_json = work_root / "assistant_profile_recommendation.json"
    assistant_profile_recommendation_md = work_root / "assistant_profile_recommendation.md"
    assistant_profile_recommendation_redaction = work_root / "assistant_profile_recommendation_redaction.json"
    assistant_profile_recommendation = _run_command(
        [
            python_executable,
            str(query_script),
            "assistant-profile",
            "recommend",
            "--assistant-profile",
            str(handoff_dir / "assistant_profile.json"),
            "--retrieval-hints",
            str(handoff_dir / "retrieval_hints.json"),
            "--report-json",
            str(assistant_profile_recommendation_json),
            "--report-md",
            str(assistant_profile_recommendation_md),
            "--redaction-report",
            str(assistant_profile_recommendation_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query assistant-profile recommend",
        assistant_profile_recommendation,
        required_output='"schema": "ragflow_assistant_profile_recommendation_v1"',
    )
    _record_file_check(checks, "query assistant-profile redaction", assistant_profile_recommendation_redaction)
    for path in (
        assistant_profile_recommendation_json,
        assistant_profile_recommendation_md,
        assistant_profile_recommendation_redaction,
    ):
        if path.exists():
            produced.append(path)
    assistant_test_plan_review_json = work_root / "assistant_test_plan_review.json"
    assistant_test_plan_review_md = work_root / "assistant_test_plan_review.md"
    assistant_test_plan_review_redaction = work_root / "assistant_test_plan_review_redaction.json"
    assistant_test_plan_review = _run_command(
        [
            python_executable,
            str(query_script),
            "assistant-test-plan",
            "--test-plan",
            str(handoff_dir / "assistant_test_plan.json"),
            "--assistant-profile",
            str(handoff_dir / "assistant_profile.json"),
            "--retrieval-hints",
            str(handoff_dir / "retrieval_hints.json"),
            "--report-json",
            str(assistant_test_plan_review_json),
            "--report-md",
            str(assistant_test_plan_review_md),
            "--redaction-report",
            str(assistant_test_plan_review_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query assistant-test-plan",
        assistant_test_plan_review,
        required_output='"schema": "ragflow_assistant_test_plan_review_v1"',
    )
    _record_file_check(checks, "query assistant-test-plan redaction", assistant_test_plan_review_redaction)
    for path in (
        assistant_test_plan_review_json,
        assistant_test_plan_review_md,
        assistant_test_plan_review_redaction,
    ):
        if path.exists():
            produced.append(path)

    routing_config = work_root / "routing_config.json"
    route_queries = work_root / "route_queries.json"
    route_tie_queries = work_root / "route_tie_queries.json"
    route_centroids = work_root / "route_centroids.json"
    route_query_vector = work_root / "route_query_vector.json"
    route_activation_fixture_plan = work_root / "route_activation_fixture_plan.json"
    routing_config.write_text(
        json.dumps(
            {
                "version": "0.1",
                "knowledge_bases": [
                    {
                        "name": "kb:consumer-general",
                        "dataset_id": "ds-consumer-general",
                        "hints": ["consumer", "general"],
                    },
                    {
                        "name": "kb:consumer-technical",
                        "dataset_id": "ds-consumer-technical",
                        "hints": ["api", "runtime"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    route_queries.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "route-api",
                        "question": "How does the API runtime work?",
                        "expected_kb": "kb:consumer-technical",
                        "category": "exact",
                        "locale": "en",
                    },
                    {
                        "id": "route-short-query",
                        "question": "api",
                        "expected_kb": "kb:consumer-technical",
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
            }
        ),
        encoding="utf-8",
    )
    route_tie_queries.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "id": "route-centroid-tie",
                        "question": "consumer api",
                        "expected_kb": "kb:consumer-technical",
                        "query_vector": [1.0, 0.0],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    route_centroids.write_text(
        json.dumps(
            {
                "schema": "ragflow_route_centroid_index_v1",
                "centroids": [
                    {"dataset_id": "ds-consumer-general", "status": "ready", "vector": [0.0, 1.0]},
                    {"dataset_id": "ds-consumer-technical", "status": "ready", "vector": [1.0, 0.0]},
                ],
            }
        ),
        encoding="utf-8",
    )
    route_query_vector.write_text(json.dumps({"query_vector": [1.0, 0.0]}), encoding="utf-8")
    route_activation_fixture_plan.write_text(
        json.dumps(
            {
                "schema": "kb_activation_plan_v1",
                "kb_name": "kb:consumer-technical",
                "dataset_id": "ds-consumer-technical",
                "summary": {"blocked_check_count": 0, "review_check_count": 0},
                "inputs": {
                    "route_config": str(routing_config),
                    "route_tests": str(route_queries),
                    "centroid_index": str(route_centroids),
                },
                "route_entry_suggestion": {
                    "name": "kb:consumer-technical",
                    "dataset_id": "ds-consumer-technical",
                    "hints": ["api", "runtime"],
                },
            }
        ),
        encoding="utf-8",
    )
    list_kbs = _run_command(
        [python_executable, str(query_script), "list-kbs", "--routing-config", str(routing_config)],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "query list-kbs", list_kbs, required_output='"count": 2')
    route_result = _run_command(
        [
            python_executable,
            str(query_script),
            "route",
            "How does the API runtime work?",
            "--routing-config",
            str(routing_config),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "query route", route_result, required_output='"dataset_id": "ds-consumer-technical"')
    route_centroid_result = _run_command(
        [
            python_executable,
            str(query_script),
            "route",
            "consumer api",
            "--routing-config",
            str(routing_config),
            "--centroid-index",
            str(route_centroids),
            "--query-vector-json",
            str(route_query_vector),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query route centroid tie-breaker",
        route_centroid_result,
        required_output='"tie_breaker": "centroid"',
    )
    route_test_json = work_root / "route_test.json"
    route_test_report = work_root / "route_test.md"
    route_test_redaction = work_root / "route_test_redaction.json"
    route_test = _run_command(
        [
            python_executable,
            str(query_script),
            "route-test",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-json",
            str(route_test_json),
            "--report-md",
            str(route_test_report),
            "--redaction-report",
            str(route_test_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "query route-test", route_test, required_output='"accuracy": 1.0')
    _record_file_check(checks, "query route-test redaction", route_test_redaction)
    route_centroid_test = _run_command(
        [
            python_executable,
            str(query_script),
            "route-test",
            "--routing-config",
            str(routing_config),
            "--centroid-index",
            str(route_centroids),
            "--queries",
            str(route_tie_queries),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-test centroid tie-breaker",
        route_centroid_test,
        required_output='"accuracy": 1.0',
    )
    for path in (route_test_json, route_test_report, route_test_redaction):
        if path.exists():
            produced.append(path)
    for path in (route_tie_queries, route_centroids, route_query_vector):
        if path.exists():
            produced.append(path)
    route_report_json = work_root / "route_report.json"
    route_report_md = work_root / "route_report.md"
    route_report_redaction = work_root / "route_report_redaction.json"
    route_report = _run_command(
        [
            python_executable,
            str(query_script),
            "route-report",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-json",
            str(route_report_json),
            "--report-md",
            str(route_report_md),
            "--redaction-report",
            str(route_report_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "query route-report", route_report, required_output='"ragflow_route_report_v1"')
    _record_file_check(checks, "query route-report redaction", route_report_redaction)
    for path in (route_report_json, route_report_md, route_report_redaction):
        if path.exists():
            produced.append(path)
    route_diagnose_json = work_root / "route_diagnose.json"
    route_diagnose_md = work_root / "route_diagnose.md"
    route_diagnose_redaction = work_root / "route_diagnose_redaction.json"
    route_diagnose = _run_command(
        [
            python_executable,
            str(query_script),
            "route-diagnose",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-json",
            str(route_diagnose_json),
            "--report-md",
            str(route_diagnose_md),
            "--redaction-report",
            str(route_diagnose_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-diagnose",
        route_diagnose,
        required_output='"ragflow_route_diagnose_report_v1"',
    )
    _record_file_check(checks, "query route-diagnose redaction", route_diagnose_redaction)
    for path in (route_diagnose_json, route_diagnose_md, route_diagnose_redaction):
        if path.exists():
            produced.append(path)
    route_activation_check_json = work_root / "route_activation_check.json"
    route_activation_check_md = work_root / "route_activation_check.md"
    route_activation_check_redaction = work_root / "route_activation_check_redaction.json"
    route_activation_check = _run_command(
        [
            python_executable,
            str(query_script),
            "route-activation-check",
            "--activation-plan",
            str(route_activation_fixture_plan),
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--centroid-index",
            str(route_centroids),
            "--report-json",
            str(route_activation_check_json),
            "--report-md",
            str(route_activation_check_md),
            "--redaction-report",
            str(route_activation_check_redaction),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query route-activation-check",
        route_activation_check,
        required_output='"schema": "ragflow_route_activation_check_v1"',
    )
    _record_file_check(checks, "query route-activation-check redaction", route_activation_check_redaction)
    for path in (
        route_activation_fixture_plan,
        route_activation_check_json,
        route_activation_check_md,
        route_activation_check_redaction,
    ):
        if path.exists():
            produced.append(path)
    centroid_plan_json = work_root / "centroid_plan.json"
    centroid_plan_md = work_root / "centroid_plan.md"
    centroid_plan_redaction = work_root / "centroid_plan_redaction.json"
    centroid_plan = _run_command(
        [
            python_executable,
            str(query_script),
            "centroid",
            "build",
            "--plan-only",
            "--kb-manifest",
            str(benchmark_manifest),
            "--chunk-snapshot",
            str(benchmark_chunk_snapshot),
            "--index-output",
            str(work_root / "centroids.json"),
            "--embedding-model",
            "example-embedding",
            "--embedding-dimension",
            "3",
            "--report-json",
            str(centroid_plan_json),
            "--report-md",
            str(centroid_plan_md),
            "--redaction-report",
            str(centroid_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query centroid build plan-only",
        centroid_plan,
        required_output='"ragflow_route_centroid_build_plan_v1"',
    )
    _record_file_check(checks, "query centroid build plan-only redaction", centroid_plan_redaction)
    for path in (centroid_plan_json, centroid_plan_md, centroid_plan_redaction):
        if path.exists():
            produced.append(path)
    centroid_chunk_snapshot = work_root / "centroid_chunk_snapshot.json"
    centroid_chunk_snapshot.write_text(
        json.dumps(
            {
                "schema": "ragflow_chunk_snapshot_v1",
                "chunks": [
                    {
                        "dataset_id": "ds-consumer-acceptance",
                        "document_name": "sample.md",
                        "chunk_id": "centroid-chunk-1",
                        "stable_hash": "sha256:consumer-centroid-1",
                        "content": "This release artifact can build centroids from snapshot-owned vectors.",
                        "embedding": [1.0, 0.0, 0.0],
                    },
                    {
                        "dataset_id": "ds-consumer-acceptance",
                        "document_name": "sample.md",
                        "chunk_id": "centroid-chunk-2",
                        "stable_hash": "sha256:consumer-centroid-2",
                        "content": "Bounded centroid build writes checkpoint and index artifacts offline.",
                        "embedding": [0.0, 1.0, 0.0],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    centroid_build_json = work_root / "centroid_build.json"
    centroid_build_md = work_root / "centroid_build.md"
    centroid_build_redaction = work_root / "centroid_build_redaction.json"
    centroid_checkpoint = work_root / "centroid.checkpoint.json"
    centroid_index = work_root / "centroids.built.json"
    centroid_build = _run_command(
        [
            python_executable,
            str(query_script),
            "centroid",
            "build",
            "--kb-manifest",
            str(benchmark_manifest),
            "--chunk-snapshot",
            str(centroid_chunk_snapshot),
            "--index-output",
            str(centroid_index),
            "--checkpoint",
            str(centroid_checkpoint),
            "--batch-size",
            "8",
            "--embedding-model",
            "example-embedding",
            "--embedding-dimension",
            "3",
            "--report-json",
            str(centroid_build_json),
            "--report-md",
            str(centroid_build_md),
            "--redaction-report",
            str(centroid_build_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query centroid build",
        centroid_build,
        required_output='"ragflow_route_centroid_build_report_v1"',
    )
    _record_file_check(checks, "query centroid build redaction", centroid_build_redaction)
    for path in (
        centroid_chunk_snapshot,
        centroid_build_json,
        centroid_build_md,
        centroid_build_redaction,
        centroid_checkpoint,
        centroid_index,
    ):
        if path.exists():
            produced.append(path)

    query_output = work_root / "query_output.json"
    citation_audit_json = work_root / "citation_audit.json"
    citation_audit_md = work_root / "citation_audit.md"
    citation_audit_redaction = work_root / "citation_audit_redaction.json"
    query_answer_eval_json = work_root / "query_answer_eval.json"
    query_answer_eval_md = work_root / "query_answer_eval.md"
    query_answer_eval_redaction = work_root / "query_answer_eval_redaction.json"
    query_diagnostic_json = work_root / "query_diagnostic.json"
    query_diagnostic_md = work_root / "query_diagnostic.md"
    query_diagnostic_redaction = work_root / "query_diagnostic_redaction.json"
    query_pollution_json = work_root / "query_pollution.json"
    query_pollution_md = work_root / "query_pollution.md"
    query_pollution_redaction = work_root / "query_pollution_redaction.json"
    query_rerank_input = work_root / "query_rerank.json"
    query_rerank_json = work_root / "query_rerank_ab.json"
    query_rerank_md = work_root / "query_rerank_ab.md"
    query_rerank_redaction = work_root / "query_rerank_ab_redaction.json"
    query_cross_language_json = work_root / "query_cross_language_ab.json"
    query_cross_language_md = work_root / "query_cross_language_ab.md"
    query_cross_language_redaction = work_root / "query_cross_language_ab_redaction.json"
    query_fusion_source = work_root / "query_fusion_source.json"
    query_fusion_cases = work_root / "query_fusion_cases.json"
    query_fusion_json = work_root / "query_fusion.json"
    query_fusion_md = work_root / "query_fusion.md"
    query_fusion_redaction = work_root / "query_fusion_redaction.json"
    query_fusion_test_json = work_root / "query_fusion_test.json"
    query_fusion_test_md = work_root / "query_fusion_test.md"
    query_fusion_test_redaction = work_root / "query_fusion_test_redaction.json"
    query_fallback_test_json = work_root / "query_fallback_test.json"
    query_fallback_test_md = work_root / "query_fallback_test.md"
    query_fallback_test_redaction = work_root / "query_fallback_test_redaction.json"
    query_rewrite_json = work_root / "query_rewrite.json"
    query_rewrite_md = work_root / "query_rewrite.md"
    query_rewrite_redaction = work_root / "query_rewrite_redaction.json"
    query_intent_json = work_root / "query_intent.json"
    query_intent_md = work_root / "query_intent.md"
    query_intent_redaction = work_root / "query_intent_redaction.json"
    query_intent_route_json = work_root / "query_intent_route.json"
    query_intent_route_md = work_root / "query_intent_route.md"
    query_intent_route_redaction = work_root / "query_intent_route_redaction.json"
    query_session_input = work_root / "query_session.json"
    query_session_inspect_json = work_root / "query_session_inspect.json"
    query_session_inspect_md = work_root / "query_session_inspect.md"
    query_session_inspect_redaction = work_root / "query_session_inspect_redaction.json"
    query_session_enrich_json = work_root / "query_session_enrich.json"
    query_session_enrich_md = work_root / "query_session_enrich.md"
    query_session_enrich_redaction = work_root / "query_session_enrich_redaction.json"
    query_agentic_plan_json = work_root / "query_agentic_plan.json"
    query_agentic_plan_md = work_root / "query_agentic_plan.md"
    query_agentic_plan_redaction = work_root / "query_agentic_plan_redaction.json"
    query_output.write_text(
        json.dumps(
            {
                "ok": True,
                "question": "What can run without repository source context?",
                "chunks": [
                    {
                        "chunk_id": "consumer-chunk-1",
                        "content": "This release artifact can run without repository source context.",
                        "similarity": 0.9,
                        "document_name": "sample.md",
                        "dataset_id": "ds-consumer-acceptance",
                    },
                    {
                        "chunk_id": "consumer-chunk-2",
                        "content": "Translated bridge term only match.",
                        "similarity": 0.4,
                        "document_name": "translated.md",
                        "dataset_id": "ds-consumer-acceptance",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    query_rerank_input.write_text(
        json.dumps(
            {"results": [{"chunk_id": "consumer-chunk-2", "score": 0.91}, {"chunk_id": "consumer-chunk-1", "score": 0.42}]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    query_fusion_source.write_text(
        json.dumps(
            {
                "ok": True,
                "question": "What can run without repository source context?",
                "dataset_ids": ["ds-consumer-secondary"],
                "chunks": [
                    {
                        "chunk_id": "consumer-secondary",
                        "content": "Secondary KB evidence for repository source context.",
                        "similarity": 0.8,
                        "document_name": "secondary.md",
                        "dataset_id": "ds-consumer-secondary",
                    },
                    {
                        "chunk_id": "consumer-chunk-1",
                        "content": "This release artifact can run without repository source context.",
                        "similarity": 0.7,
                        "document_name": "sample.md",
                        "dataset_id": "ds-consumer-secondary",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    query_session_input.write_text(
        json.dumps(
            {
                "schema": "ragflow_query_session_v1",
                "session_id": "consumer-session",
                "turns": [
                    {"role": "user", "content": "How do release artifacts run without repository source context?"},
                    {"role": "assistant", "content": "They use vendored runtime files."},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    citation_audit = _run_command(
        [
            python_executable,
            str(query_script),
            "audit-citations",
            "--query-output",
            str(query_output),
            "--answer",
            "The release artifact can run without repository source context [1].",
            "--report-json",
            str(citation_audit_json),
            "--report-md",
            str(citation_audit_md),
            "--redaction-report",
            str(citation_audit_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query citation audit",
        citation_audit,
        required_output='"schema": "ragflow_citation_audit_v1"',
    )
    if citation_audit_json.exists():
        produced.append(citation_audit_json)
    if citation_audit_md.exists():
        produced.append(citation_audit_md)
    _record_file_check(checks, "query citation audit redaction", citation_audit_redaction)
    if citation_audit_redaction.exists():
        produced.append(citation_audit_redaction)

    query_answer_eval = _run_command(
        [
            python_executable,
            str(query_script),
            "evaluate-answer",
            "--query-output",
            str(query_output),
            "--answer",
            "The release artifact can run without repository source context [1].",
            "--expected-term",
            "release",
            "--require-citation",
            "--report-json",
            str(query_answer_eval_json),
            "--report-md",
            str(query_answer_eval_md),
            "--redaction-report",
            str(query_answer_eval_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query answer evaluation",
        query_answer_eval,
        required_output='"schema": "ragflow_answer_evaluation_report_v1"',
    )
    if query_answer_eval_json.exists():
        produced.append(query_answer_eval_json)
    if query_answer_eval_md.exists():
        produced.append(query_answer_eval_md)
    _record_file_check(checks, "query answer evaluation redaction", query_answer_eval_redaction)
    if query_answer_eval_redaction.exists():
        produced.append(query_answer_eval_redaction)

    query_diagnostic = _run_command(
        [
            python_executable,
            str(query_script),
            "diagnose-result",
            "--query-output",
            str(query_output),
            "--citation-audit",
            str(citation_audit_json),
            "--expected-term",
            "release",
            "--report-json",
            str(query_diagnostic_json),
            "--report-md",
            str(query_diagnostic_md),
            "--redaction-report",
            str(query_diagnostic_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query diagnostic report",
        query_diagnostic,
        required_output='"schema": "ragflow_query_diagnostic_report_v1"',
    )
    if query_diagnostic_json.exists():
        produced.append(query_diagnostic_json)
    if query_diagnostic_md.exists():
        produced.append(query_diagnostic_md)
    _record_file_check(checks, "query diagnostic redaction", query_diagnostic_redaction)
    if query_diagnostic_redaction.exists():
        produced.append(query_diagnostic_redaction)

    query_pollution = _run_command(
        [
            python_executable,
            str(query_script),
            "pollution-report",
            "--query-output",
            str(query_output),
            "--expanded-term",
            "translated",
            "--report-json",
            str(query_pollution_json),
            "--report-md",
            str(query_pollution_md),
            "--redaction-report",
            str(query_pollution_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query pollution report",
        query_pollution,
        required_output='"schema": "ragflow_query_pollution_report_v1"',
    )
    if query_pollution_json.exists():
        produced.append(query_pollution_json)
    if query_pollution_md.exists():
        produced.append(query_pollution_md)
    _record_file_check(checks, "query pollution redaction", query_pollution_redaction)
    if query_pollution_redaction.exists():
        produced.append(query_pollution_redaction)

    query_rerank = _run_command(
        [
            python_executable,
            str(query_script),
            "rerank-ab",
            "--query-output",
            str(query_output),
            "--rerank-json",
            str(query_rerank_input),
            "--expected-term",
            "Translated bridge",
            "--expected-chunk",
            "consumer-chunk-2",
            "--top-k",
            "1",
            "--report-json",
            str(query_rerank_json),
            "--report-md",
            str(query_rerank_md),
            "--redaction-report",
            str(query_rerank_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query rerank ab report",
        query_rerank,
        required_output='"schema": "ragflow_query_rerank_ab_report_v1"',
    )
    if query_rerank_json.exists():
        produced.append(query_rerank_json)
    if query_rerank_md.exists():
        produced.append(query_rerank_md)
    _record_file_check(checks, "query rerank ab redaction", query_rerank_redaction)
    if query_rerank_redaction.exists():
        produced.append(query_rerank_redaction)

    query_cross_language = _run_command(
        [
            python_executable,
            str(query_script),
            "cross-language-ab",
            "--baseline-output",
            str(query_output),
            "--candidate-output",
            str(query_fusion_source),
            "--baseline-label",
            "original",
            "--candidate-label",
            "translated",
            "--report-json",
            str(query_cross_language_json),
            "--report-md",
            str(query_cross_language_md),
            "--redaction-report",
            str(query_cross_language_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query cross-language ab report",
        query_cross_language,
        required_output='"schema": "ragflow_cross_language_ab_report_v1"',
    )
    if query_cross_language_json.exists():
        produced.append(query_cross_language_json)
    if query_cross_language_md.exists():
        produced.append(query_cross_language_md)
    _record_file_check(checks, "query cross-language ab redaction", query_cross_language_redaction)
    if query_cross_language_redaction.exists():
        produced.append(query_cross_language_redaction)

    query_fusion = _run_command(
        [
            python_executable,
            str(query_script),
            "fusion",
            "--query-output",
            str(query_output),
            "--query-output",
            str(query_fusion_source),
            "--top-k",
            "3",
            "--report-json",
            str(query_fusion_json),
            "--report-md",
            str(query_fusion_md),
            "--redaction-report",
            str(query_fusion_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query fusion report",
        query_fusion,
        required_output='"schema": "ragflow_fusion_report_v1"',
    )
    if query_fusion_json.exists():
        produced.append(query_fusion_json)
    if query_fusion_md.exists():
        produced.append(query_fusion_md)
    _record_file_check(checks, "query fusion redaction", query_fusion_redaction)
    if query_fusion_redaction.exists():
        produced.append(query_fusion_redaction)

    query_fusion_cases.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "consumer-shared-evidence",
                        "query_outputs": [query_output.name, query_fusion_source.name],
                        "top_k": 3,
                        "expected_top_chunk": "consumer-chunk-1",
                        "expected_chunks": ["consumer-chunk-1"],
                        "expected_terms": ["repository source context"],
                        "min_source_count": 2,
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    query_fusion_test = _run_command(
        [
            python_executable,
            str(query_script),
            "fusion-test",
            "--cases",
            str(query_fusion_cases),
            "--report-json",
            str(query_fusion_test_json),
            "--report-md",
            str(query_fusion_test_md),
            "--redaction-report",
            str(query_fusion_test_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query fusion test report",
        query_fusion_test,
        required_output='"schema": "ragflow_fusion_test_report_v1"',
    )
    if query_fusion_test_json.exists():
        produced.append(query_fusion_test_json)
    if query_fusion_test_md.exists():
        produced.append(query_fusion_test_md)
    _record_file_check(checks, "query fusion test redaction", query_fusion_test_redaction)
    if query_fusion_test_redaction.exists():
        produced.append(query_fusion_test_redaction)

    query_fallback_test = _run_command(
        [
            python_executable,
            str(query_script),
            "fallback-test",
            "--report-json",
            str(query_fallback_test_json),
            "--report-md",
            str(query_fallback_test_md),
            "--redaction-report",
            str(query_fallback_test_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query fallback test report",
        query_fallback_test,
        required_output='"schema": "ragflow_query_fallback_test_report_v1"',
    )
    if query_fallback_test_json.exists():
        produced.append(query_fallback_test_json)
    if query_fallback_test_md.exists():
        produced.append(query_fallback_test_md)
    _record_file_check(checks, "query fallback test redaction", query_fallback_test_redaction)
    if query_fallback_test_redaction.exists():
        produced.append(query_fallback_test_redaction)

    query_rewrite = _run_command(
        [
            python_executable,
            str(query_script),
            "rewrite",
            "How do I configure runtime?",
            "--rewrite",
            "simple",
            "--report-json",
            str(query_rewrite_json),
            "--report-md",
            str(query_rewrite_md),
            "--redaction-report",
            str(query_rewrite_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query rewrite report",
        query_rewrite,
        required_output='"schema": "ragflow_query_rewrite_plan_v1"',
    )
    if query_rewrite_json.exists():
        produced.append(query_rewrite_json)
    if query_rewrite_md.exists():
        produced.append(query_rewrite_md)
    _record_file_check(checks, "query rewrite redaction", query_rewrite_redaction)
    if query_rewrite_redaction.exists():
        produced.append(query_rewrite_redaction)

    query_intent = _run_command(
        [
            python_executable,
            str(query_script),
            "intent",
            "classify",
            "Compare release artifact portability versus repository source context",
            "--report-json",
            str(query_intent_json),
            "--report-md",
            str(query_intent_md),
            "--redaction-report",
            str(query_intent_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query intent classify",
        query_intent,
        required_output='"schema": "ragflow_query_intent_v1"',
    )
    if query_intent_json.exists():
        produced.append(query_intent_json)
    if query_intent_md.exists():
        produced.append(query_intent_md)
    _record_file_check(checks, "query intent classify redaction", query_intent_redaction)
    if query_intent_redaction.exists():
        produced.append(query_intent_redaction)

    query_intent_route = _run_command(
        [
            python_executable,
            str(query_script),
            "intent",
            "route",
            "What about it?",
            "--report-json",
            str(query_intent_route_json),
            "--report-md",
            str(query_intent_route_md),
            "--redaction-report",
            str(query_intent_route_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query intent route",
        query_intent_route,
        required_output='"schema": "ragflow_query_route_decision_v1"',
    )
    if query_intent_route_json.exists():
        produced.append(query_intent_route_json)
    if query_intent_route_md.exists():
        produced.append(query_intent_route_md)
    _record_file_check(checks, "query intent route redaction", query_intent_route_redaction)
    if query_intent_route_redaction.exists():
        produced.append(query_intent_route_redaction)

    query_session_inspect = _run_command(
        [
            python_executable,
            str(query_script),
            "session",
            "inspect",
            "--session",
            str(query_session_input),
            "--report-json",
            str(query_session_inspect_json),
            "--report-md",
            str(query_session_inspect_md),
            "--redaction-report",
            str(query_session_inspect_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query session inspect",
        query_session_inspect,
        required_output='"schema": "ragflow_query_session_inspection_v1"',
    )
    for path in (query_session_input, query_session_inspect_json, query_session_inspect_md):
        if path.exists():
            produced.append(path)
    _record_file_check(checks, "query session inspect redaction", query_session_inspect_redaction)
    if query_session_inspect_redaction.exists():
        produced.append(query_session_inspect_redaction)

    query_session_enrich = _run_command(
        [
            python_executable,
            str(query_script),
            "session",
            "enrich",
            "What about it?",
            "--session",
            str(query_session_input),
            "--report-json",
            str(query_session_enrich_json),
            "--report-md",
            str(query_session_enrich_md),
            "--redaction-report",
            str(query_session_enrich_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query session enrich",
        query_session_enrich,
        required_output='"schema": "ragflow_query_session_enrichment_v1"',
    )
    if query_session_enrich_json.exists():
        produced.append(query_session_enrich_json)
    if query_session_enrich_md.exists():
        produced.append(query_session_enrich_md)
    _record_file_check(checks, "query session enrich redaction", query_session_enrich_redaction)
    if query_session_enrich_redaction.exists():
        produced.append(query_session_enrich_redaction)

    query_agentic_plan = _run_command(
        [
            python_executable,
            str(query_script),
            "agentic-plan",
            "Compare release artifact portability and repository source context tradeoffs",
            "--max-subqueries",
            "3",
            "--reflection-budget",
            "1",
            "--report-json",
            str(query_agentic_plan_json),
            "--report-md",
            str(query_agentic_plan_md),
            "--redaction-report",
            str(query_agentic_plan_redaction),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query agentic plan",
        query_agentic_plan,
        required_output='"schema": "ragflow_agentic_plan_v1"',
    )
    if query_agentic_plan_json.exists():
        produced.append(query_agentic_plan_json)
    if query_agentic_plan_md.exists():
        produced.append(query_agentic_plan_md)
    _record_file_check(checks, "query agentic plan redaction", query_agentic_plan_redaction)
    if query_agentic_plan_redaction.exists():
        produced.append(query_agentic_plan_redaction)

    missing_config = _run_command(
        [
            python_executable,
            str(query_script),
            "ask",
            "Where is the sample?",
            "--dataset-id",
            "ds-consumer-acceptance",
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(
        checks,
        "query missing config guard",
        missing_config,
        required_output="RAGFlow base URL is required",
        expect_failure=True,
    )

    return checks, produced


def _run_live_check(
    *,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env_map: Mapping[str, str],
    question: str,
    top_k: int,
) -> tuple[list[dict[str, Any]], list[Path]]:
    checks: list[dict[str, Any]] = []
    produced: list[Path] = []
    required = ("RAGFLOW_BASE_URL", "RAGFLOW_API_KEY", "RAGFLOW_DATASET_ID")
    missing = [name for name in required if not env_map.get(name)]
    if missing:
        checks.append(
            {
                "name": "live retrieval skipped",
                "ok": True,
                "skipped": True,
                "missing": missing,
                "error": "",
            }
        )
        return checks, produced

    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    live_output = work_root / "live-query-result.json"
    result = _run_command(
        [
            python_executable,
            str(query_script),
            "ask",
            question,
            "--dataset-id",
            env_map["RAGFLOW_DATASET_ID"],
            "--mode",
            "direct",
            "--top-k",
            str(top_k),
            "--json",
        ],
        cwd=work_root,
        env=_minimal_env(
            {
                "RAGFLOW_BASE_URL": env_map["RAGFLOW_BASE_URL"],
                "RAGFLOW_API_KEY": env_map["RAGFLOW_API_KEY"],
            }
        ),
        timeout=120.0,
    )
    ok = _record_command_check(checks, "live query direct", result, required_output='"ok": true')
    if ok:
        live_output.write_text(result["stdout"], encoding="utf-8")
        produced.append(live_output)
    return checks, produced


def _run_live_build_check(
    *,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env_map: Mapping[str, str],
    question: str,
    top_k: int,
    kb_name: str | None,
    parse_timeout: float,
    poll_interval: float,
) -> tuple[list[dict[str, Any]], list[Path]]:
    checks: list[dict[str, Any]] = []
    produced: list[Path] = []
    required = ("RAGFLOW_BASE_URL", "RAGFLOW_API_KEY")
    missing = [name for name in required if not env_map.get(name)]
    if missing:
        checks.append(
            {
                "name": "live build skipped",
                "ok": True,
                "skipped": True,
                "missing": missing,
                "error": "",
            }
        )
        return checks, produced

    live_dir = work_root / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_env = _minimal_env(
        {
            "RAGFLOW_BASE_URL": env_map["RAGFLOW_BASE_URL"],
            "RAGFLOW_API_KEY": env_map["RAGFLOW_API_KEY"],
        }
    )
    live_kb_name = kb_name or f"kb:consumer-acceptance-{uuid.uuid4().hex[:8]}"
    doc_manifest = work_root / "handoff" / "doc_manifest.json"
    kb_manifest = live_dir / "kb_manifest.json"
    build_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "build.py")
    validate_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "validate.py")
    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    profile = _skill_path(extract_dir, "ragflow-kb-build", "templates", "default-en-768.json")

    build_result = _run_command(
        [
            python_executable,
            str(build_script),
            "--doc-manifest",
            str(doc_manifest),
            "--kb-name",
            live_kb_name,
            "--profile",
            str(profile),
            "--output",
            str(kb_manifest),
            "--parse-timeout",
            str(parse_timeout),
            "--poll-interval",
            str(poll_interval),
            "--json",
        ],
        cwd=work_root,
        env=live_env,
        timeout=parse_timeout + 120.0,
    )
    build_ok = _record_command_check(checks, "live build disposable kb", build_result, required_output='"ok": true')
    _record_file_check(checks, "live kb_manifest produced", kb_manifest)
    if not build_ok or not kb_manifest.exists():
        return checks, produced
    produced.append(kb_manifest)

    report_json = live_dir / "validation_report.json"
    report_md = live_dir / "validation_report.md"
    validate_result = _run_command(
        [
            python_executable,
            str(validate_script),
            "--kb-manifest",
            str(kb_manifest),
            "--level",
            "smoke",
            "--query",
            question,
            "--top-k",
            str(top_k),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        cwd=work_root,
        env=live_env,
        timeout=120.0,
    )
    validate_ok = _record_command_check(checks, "live validate smoke", validate_result, required_output='"ok": true')
    if validate_ok:
        produced.extend(path for path in (report_json, report_md) if path.exists())

    for mode, extra, output_name in (
        ("direct", ["--json"], "live-query-direct.json"),
        ("agentic", ["--host-assisted", "--json"], "live-query-host-assisted.json"),
    ):
        output_path = live_dir / output_name
        query_result = _run_command(
            [
                python_executable,
                str(query_script),
                "ask",
                question,
                "--kb-manifest",
                str(kb_manifest),
                "--mode",
                mode,
                "--top-k",
                str(top_k),
                *extra,
            ],
            cwd=work_root,
            env=live_env,
            timeout=120.0,
        )
        query_ok = _record_command_check(checks, f"live query {mode}", query_result, required_output='"ok": true')
        if query_ok:
            output_path.write_text(query_result["stdout"], encoding="utf-8")
            produced.append(output_path)

    return checks, produced


def run_consumer_acceptance(
    *,
    artifacts_dir: Path,
    work_root: Path,
    overwrite: bool = False,
    live: bool = False,
    live_build: bool = False,
    env: Mapping[str, str] | None = None,
    source: Mapping[str, Any] | None = None,
    python_executable: str = sys.executable,
    live_question: str = "Summarize this knowledge base.",
    live_top_k: int = 3,
    live_kb_name: str | None = None,
    live_parse_timeout: float = 300.0,
    live_poll_interval: float = 2.0,
    command_manifest: Path | None = None,
    command_manifest_redaction: Path | None = None,
    command_manifest_only: bool = False,
) -> dict[str, Any]:
    if overwrite and _is_relative_to(artifacts_dir.resolve(), work_root.resolve()):
        raise RuntimeError("artifacts directory must not be inside an overwritten work directory")
    _prepare_work_root(work_root, overwrite=overwrite)
    artifacts = _validate_artifacts_dir(artifacts_dir)
    extract_dir = work_root / "unpacked"
    _extract_skills(artifacts, extract_dir)

    command_env = _minimal_env()
    checks, produced = _run_no_network_checks(
        extract_dir=extract_dir,
        work_root=work_root,
        python_executable=python_executable,
        env=command_env,
    )
    live_env_map = os.environ if env is None else env
    command_manifest_info: dict[str, Any] | None = None
    if command_manifest or command_manifest_only:
        manifest_path = command_manifest or work_root / "reports" / "consumer-command-manifest.json"
        redaction_path = (
            command_manifest_redaction
            or manifest_path.with_name(f"{manifest_path.stem}.redaction.json")
        )
        command_manifest_info = _write_command_manifest(
            path=manifest_path,
            redaction_path=redaction_path,
            artifacts_dir=artifacts_dir,
            extract_dir=extract_dir,
            work_root=work_root,
            python_executable=python_executable,
            env_map=live_env_map,
            live=live,
            live_build=live_build,
            question=live_question,
            top_k=live_top_k,
            kb_name=live_kb_name,
            parse_timeout=live_parse_timeout,
            poll_interval=live_poll_interval,
        )
        checks.append(
            {
                "name": "command manifest dry-run",
                "ok": True,
                "path": command_manifest_info["json"],
                "redaction_report": command_manifest_info["redaction"],
                "error": "",
            }
        )
        produced.extend([manifest_path, redaction_path])

    if command_manifest_only and (live or live_build):
        checks.append(
            {
                "name": "live execution skipped by command manifest dry-run",
                "ok": True,
                "skipped": True,
                "error": "",
            }
        )

    if live and not command_manifest_only:
        live_checks, live_produced = _run_live_check(
            extract_dir=extract_dir,
            work_root=work_root,
            python_executable=python_executable,
            env_map=live_env_map,
            question=live_question,
            top_k=live_top_k,
        )
        checks.extend(live_checks)
        produced.extend(live_produced)

    if live_build and not command_manifest_only:
        live_build_checks, live_build_produced = _run_live_build_check(
            extract_dir=extract_dir,
            work_root=work_root,
            python_executable=python_executable,
            env_map=live_env_map,
            question=live_question,
            top_k=live_top_k,
            kb_name=live_kb_name,
            parse_timeout=live_parse_timeout,
            poll_interval=live_poll_interval,
        )
        checks.extend(live_build_checks)
        produced.extend(live_build_produced)

    payload = {
        "ok": all(check["ok"] for check in checks),
        "source": dict(
            source
            or {
                "type": "local-artifacts",
                "artifacts_dir": str(artifacts_dir),
                "assets": list(REQUIRED_ASSETS),
            }
        ),
        "work_root": str(work_root),
        "checks": checks,
        "produced_artifacts": [str(path) for path in produced if path.exists()],
    }
    if command_manifest_info:
        payload["command_manifest"] = command_manifest_info
    reports = _write_reports(payload, work_root / "reports")
    payload["reports"] = reports
    Path(reports["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def download_github_release(*, tag: str, repo: str, output_dir: Path, timeout: float = 60.0) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "gh",
        "release",
        "download",
        tag,
        "--repo",
        repo,
        "--dir",
        str(output_dir),
        "--clobber",
    ]
    for asset in REQUIRED_ASSETS:
        command.extend(["--pattern", asset])
    result = _run_command(command, cwd=ROOT, env=_github_env(), timeout=timeout)
    return {
        "ok": result["ok"],
        "command": command,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "output_dir": str(output_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run clean-consumer acceptance checks against release artifacts")
    parser.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS_DIR), help="Directory containing release artifacts")
    parser.add_argument("--github-release", help="Download this GitHub release tag before running")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repo owner/name for --github-release; defaults to GITHUB_REPOSITORY",
    )
    parser.add_argument("--download-dir", help="Directory for downloaded GitHub release assets")
    parser.add_argument("--download-timeout", type=float, default=60.0, help="Seconds to wait for gh release download")
    parser.add_argument("--work-dir", help="Acceptance workspace; defaults to a temporary directory")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing work directory")
    parser.add_argument("--live", action="store_true", help="Also query an existing live dataset when RAGFlow env vars are present")
    parser.add_argument("--live-build", action="store_true", help="Also build and validate a disposable live KB when RAGFlow env vars are present")
    parser.add_argument("--live-question", default="Summarize this knowledge base.")
    parser.add_argument("--live-top-k", type=int, default=3)
    parser.add_argument("--live-kb-name", help="Override the disposable live KB name")
    parser.add_argument("--live-parse-timeout", type=float, default=300.0)
    parser.add_argument("--live-poll-interval", type=float, default=2.0)
    parser.add_argument("--command-manifest", help="Write a redacted dry-run command manifest for live acceptance")
    parser.add_argument("--command-manifest-redaction", help="Write the command manifest redaction sidecar")
    parser.add_argument(
        "--command-manifest-only",
        action="store_true",
        help="Generate the command manifest and skip live acceptance execution",
    )
    args = parser.parse_args(argv)
    if args.github_release and not args.repo:
        parser.error("--repo is required with --github-release unless GITHUB_REPOSITORY is set")

    try:
        artifacts_dir = Path(args.artifacts_dir).resolve()
        source: dict[str, Any] | None = None
        if args.github_release:
            download_dir = Path(args.download_dir).resolve() if args.download_dir else None
            if download_dir is None:
                download_dir = Path(tempfile.mkdtemp(prefix="ragflow-release-download-"))
            download = download_github_release(
                tag=args.github_release,
                repo=args.repo,
                output_dir=download_dir,
                timeout=args.download_timeout,
            )
            if not download["ok"]:
                print(json.dumps({"ok": False, "download": download}, ensure_ascii=False, indent=2))
                return 1
            artifacts_dir = download_dir
            source = {
                "type": "github-release",
                "repo": args.repo,
                "tag": args.github_release,
                "download_dir": str(download_dir),
                "assets": list(REQUIRED_ASSETS),
            }

        if args.work_dir:
            work_root = Path(args.work_dir).resolve()
            payload = run_consumer_acceptance(
                artifacts_dir=artifacts_dir,
                work_root=work_root,
                overwrite=args.overwrite,
                live=args.live,
                live_build=args.live_build,
                source=source,
                live_question=args.live_question,
                live_top_k=args.live_top_k,
                live_kb_name=args.live_kb_name,
                live_parse_timeout=args.live_parse_timeout,
                live_poll_interval=args.live_poll_interval,
                command_manifest=Path(args.command_manifest).resolve() if args.command_manifest else None,
                command_manifest_redaction=Path(args.command_manifest_redaction).resolve()
                if args.command_manifest_redaction
                else None,
                command_manifest_only=args.command_manifest_only,
            )
            payload["artifacts_retained"] = True
        else:
            with tempfile.TemporaryDirectory(prefix="ragflow-consumer-acceptance-") as tmp:
                payload = run_consumer_acceptance(
                    artifacts_dir=artifacts_dir,
                    work_root=Path(tmp),
                    live=args.live,
                    live_build=args.live_build,
                    source=source,
                    live_question=args.live_question,
                    live_top_k=args.live_top_k,
                    live_kb_name=args.live_kb_name,
                    live_parse_timeout=args.live_parse_timeout,
                    live_poll_interval=args.live_poll_interval,
                    command_manifest=Path(args.command_manifest).resolve() if args.command_manifest else None,
                    command_manifest_redaction=Path(args.command_manifest_redaction).resolve()
                    if args.command_manifest_redaction
                    else None,
                    command_manifest_only=args.command_manifest_only,
                )
                payload["artifacts_retained"] = False

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
