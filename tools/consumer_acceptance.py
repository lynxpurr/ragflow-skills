#!/usr/bin/env python3
"""Validate release artifacts from a clean consumer workspace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_DIR = ROOT / "release-artifacts"
REQUIRED_ASSETS = (
    "ragflow-doc-to-md.tar.gz",
    "ragflow-kb-build.tar.gz",
    "ragflow-query.tar.gz",
    "release-manifest.json",
)


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


def _run_no_network_checks(
    *,
    extract_dir: Path,
    work_root: Path,
    python_executable: str,
    env: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[Path]]:
    checks: list[dict[str, Any]] = []
    produced: list[Path] = []

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

    build_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "build.py")
    profile = _skill_path(extract_dir, "ragflow-kb-build", "templates", "default-en-768.json")
    build_result = _run_command(
        [
            python_executable,
            str(build_script),
            "--doc-manifest",
            str(doc_manifest),
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

    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    query_help = _run_command([python_executable, str(query_script), "--help"], cwd=work_root, env=env)
    _record_command_check(checks, "query top-level help", query_help, required_output="Portable RAGFlow query CLI")

    ask_help = _run_command([python_executable, str(query_script), "ask", "--help"], cwd=work_root, env=env)
    _record_command_check(checks, "query host-assisted help", ask_help, required_output="--host-assisted")

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


def run_consumer_acceptance(
    *,
    artifacts_dir: Path,
    work_root: Path,
    overwrite: bool = False,
    live: bool = False,
    env: Mapping[str, str] | None = None,
    source: Mapping[str, Any] | None = None,
    python_executable: str = sys.executable,
    live_question: str = "Summarize this knowledge base.",
    live_top_k: int = 3,
) -> dict[str, Any]:
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

    if live:
        live_checks, live_produced = _run_live_check(
            extract_dir=extract_dir,
            work_root=work_root,
            python_executable=python_executable,
            env_map=os.environ if env is None else env,
            question=live_question,
            top_k=live_top_k,
        )
        checks.extend(live_checks)
        produced.extend(live_produced)

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
    reports = _write_reports(payload, work_root / "reports")
    payload["reports"] = reports
    Path(reports["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def download_github_release(*, tag: str, repo: str, output_dir: Path) -> dict[str, Any]:
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
    result = _run_command(command, cwd=ROOT, env=_minimal_env(), timeout=180.0)
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
    parser.add_argument("--repo", default="lynxpurr/ragflow-skills", help="GitHub repo for --github-release")
    parser.add_argument("--download-dir", help="Directory for downloaded GitHub release assets")
    parser.add_argument("--work-dir", help="Acceptance workspace; defaults to a temporary directory")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing work directory")
    parser.add_argument("--live", action="store_true", help="Also run a live query when RAGFlow env vars are present")
    parser.add_argument("--live-question", default="Summarize this knowledge base.")
    parser.add_argument("--live-top-k", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        artifacts_dir = Path(args.artifacts_dir).resolve()
        source: dict[str, Any] | None = None
        if args.github_release:
            download_dir = Path(args.download_dir).resolve() if args.download_dir else None
            if download_dir is None:
                if args.work_dir:
                    download_dir = Path(args.work_dir).resolve() / "downloads"
                else:
                    download_dir = Path(tempfile.mkdtemp(prefix="ragflow-release-download-"))
            download = download_github_release(tag=args.github_release, repo=args.repo, output_dir=download_dir)
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
                source=source,
                live_question=args.live_question,
                live_top_k=args.live_top_k,
            )
            payload["artifacts_retained"] = True
        else:
            with tempfile.TemporaryDirectory(prefix="ragflow-consumer-acceptance-") as tmp:
                payload = run_consumer_acceptance(
                    artifacts_dir=artifacts_dir,
                    work_root=Path(tmp),
                    live=args.live,
                    source=source,
                    live_question=args.live_question,
                    live_top_k=args.live_top_k,
                )
                payload["artifacts_retained"] = False

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
