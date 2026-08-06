#!/usr/bin/env python3
"""Run offline handoff contract fixtures against release/dist skill scripts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from build_release import DIST_DIR, ROOT, build_release


SCHEMA = "ragflow_contract_fixture_gate_v1"


class ContractFixtureGateError(RuntimeError):
    """Raised when the contract fixture gate cannot be prepared."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_env() -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "RAGFLOW_SKILL_RUNTIME_PATH": "",
    }
    return env


def _preview(text: str, *, limit: int = 400) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _tokenize_path(value: str, *, dist_dir: Path, work_root: Path) -> str:
    if value.startswith("-") or (not Path(value).is_absolute() and "/" not in value and "\\" not in value):
        return value
    path_tokens = (
        (work_root.resolve(), "<work>"),
        (dist_dir.resolve(), "<dist>"),
        (ROOT.resolve(), "<repo>"),
    )
    for root, token in path_tokens:
        try:
            path = Path(value).resolve()
        except OSError:
            continue
        try:
            return f"{token}/{path.relative_to(root)}"
        except ValueError:
            continue
    return value


def _json_value(payload: Mapping[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _display_command(command: list[str], *, dist_dir: Path, work_root: Path) -> list[str]:
    return [_tokenize_path(part, dist_dir=dist_dir, work_root=work_root) for part in command]


def _parse_json_output(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _record_file_check(checks: list[dict[str, Any]], name: str, path: Path, *, work_root: Path) -> None:
    exists = path.exists()
    checks.append(
        {
            "name": name,
            "kind": "file",
            "ok": exists,
            "path": _relative(path, work_root) if exists else str(path),
            "error": "" if exists else "file not found",
        }
    )


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    dist_dir: Path,
    work_root: Path,
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
            "command": _display_command(command, dist_dir=dist_dir, work_root=work_root),
            "returncode": 124,
            "stdout_preview": _preview(exc.stdout or ""),
            "stderr_preview": f"timed out after {timeout} seconds",
            "stdout_json": None,
            "ok": False,
            "error": f"timed out after {timeout} seconds",
        }

    payload = _parse_json_output(result.stdout)
    return {
        "command": _display_command(command, dist_dir=dist_dir, work_root=work_root),
        "returncode": result.returncode,
        "stdout_preview": _preview(result.stdout),
        "stderr_preview": _preview(result.stderr),
        "stdout_json": payload,
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else _preview(f"{result.stdout}\n{result.stderr}"),
    }


def _record_command_check(
    checks: list[dict[str, Any]],
    name: str,
    result: dict[str, Any],
    *,
    required_json: Mapping[str, Any] | None = None,
) -> None:
    ok = bool(result["ok"])
    error = str(result.get("error") or "")
    payload = result.get("stdout_json")
    if ok and required_json:
        if not isinstance(payload, dict):
            ok = False
            error = "stdout was not a JSON object"
        else:
            missing = [
                f"{key}={expected!r}"
                for key, expected in required_json.items()
                if _json_value(payload, key) != expected
            ]
            if missing:
                ok = False
                error = "JSON output did not contain " + ", ".join(missing)

    checks.append(
        {
            "name": name,
            "kind": "command",
            "ok": ok,
            "command": result["command"],
            "returncode": result["returncode"],
            "stdout_preview": result["stdout_preview"],
            "stderr_preview": result["stderr_preview"],
            "stdout_json": payload,
            "error": "" if ok else error,
        }
    )


def _write_sample_input(work_root: Path) -> Path:
    input_dir = work_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    sample = input_dir / "contract-fixture.md"
    sample.write_text(
        "\n".join(
            [
                "# Contract Fixture",
                "",
                "This neutral fixture verifies that release handoffs remain compatible.",
                "",
                "It is intentionally small, offline, and free of service credentials.",
                "",
                "## Retrieval Notes",
                "",
                "- Plain handoff consumers should read doc_manifest.json.",
                "- Rich handoff consumers may inspect optional sidecars.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return input_dir


def _artifact(path: Path, *, work_root: Path) -> str:
    return _relative(path, work_root)


@contextmanager
def _prepared_work_root(
    work_dir: Path | None,
    *,
    keep_artifacts: bool,
    overwrite: bool,
) -> Iterator[tuple[Path, bool]]:
    if work_dir is not None:
        root = work_dir.resolve()
        if root.exists() and any(root.iterdir()):
            if not overwrite:
                raise ContractFixtureGateError(f"work directory is not empty: {root}")
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        yield root, True
        return

    if keep_artifacts:
        root = Path(tempfile.mkdtemp(prefix="ragflow-contract-fixture-")).resolve()
        yield root, True
        return

    with tempfile.TemporaryDirectory(prefix="ragflow-contract-fixture-") as tmp:
        yield Path(tmp).resolve(), False


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    failed = [check["name"] for check in report["checks"] if not check.get("ok")]
    report["ok"] = not failed
    report["summary"] = {
        "check_count": len(report["checks"]),
        "failed_count": len(failed),
        "failed_checks": failed,
    }
    return report


def run_contract_fixture_gate(
    *,
    dist_dir: Path = DIST_DIR,
    work_dir: Path | None = None,
    rebuild: bool = True,
    keep_artifacts: bool = False,
    overwrite: bool = False,
    python_executable: str = sys.executable,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run the offline contract fixture gate and return a JSON-serializable report."""

    dist_dir = dist_dir.resolve()
    if rebuild:
        build_release(dist_dir)

    with _prepared_work_root(work_dir, keep_artifacts=keep_artifacts, overwrite=overwrite) as (
        work_root,
        artifacts_retained,
    ):
        report: dict[str, Any] = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "dist": str(dist_dir),
            "work_root": str(work_root),
            "artifacts_retained": artifacts_retained,
            "checks": [],
            "artifacts": {},
            "summary": {},
        }
        checks: list[dict[str, Any]] = report["checks"]

        convert_script = dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"
        build_script = dist_dir / "ragflow-kb-build" / "scripts" / "build.py"
        profile = dist_dir / "ragflow-kb-build" / "templates" / "default-en-768.json"

        _record_file_check(checks, "dist doc-to-md convert script", convert_script, work_root=work_root)
        _record_file_check(checks, "dist kb-build script", build_script, work_root=work_root)
        _record_file_check(checks, "dist default profile", profile, work_root=work_root)
        if any(not check.get("ok") for check in checks):
            return _finalize_report(report)

        input_dir = _write_sample_input(work_root)
        plain_handoff = work_root / "plain-handoff"
        rich_handoff = work_root / "rich-handoff"
        plain_manifest = plain_handoff / "doc_manifest.json"
        rich_manifest = rich_handoff / "doc_manifest.json"
        rich_inspection_json = work_root / "rich_handoff_inspection.json"
        rich_inspection_md = work_root / "rich_handoff_inspection.md"
        env = _stable_env()

        plain_convert = _run_command(
            [
                python_executable,
                str(convert_script),
                "--input",
                str(input_dir),
                "--output",
                str(plain_handoff),
                "--mode",
                "passthrough",
                "--json",
            ],
            cwd=work_root,
            env=env,
            timeout=timeout,
            dist_dir=dist_dir,
            work_root=work_root,
        )
        _record_command_check(checks, "doc-to-md plain handoff", plain_convert, required_json={"ok": True})
        _record_file_check(checks, "plain doc_manifest produced", plain_manifest, work_root=work_root)

        rich_convert = _run_command(
            [
                python_executable,
                str(convert_script),
                "--input",
                str(input_dir),
                "--output",
                str(rich_handoff),
                "--mode",
                "passthrough",
                "--json",
            ],
            cwd=work_root,
            env=env,
            timeout=timeout,
            dist_dir=dist_dir,
            work_root=work_root,
        )
        _record_command_check(checks, "doc-to-md rich handoff source", rich_convert, required_json={"ok": True})
        _record_file_check(checks, "rich doc_manifest produced", rich_manifest, work_root=work_root)

        package_rich = _run_command(
            [
                python_executable,
                str(convert_script),
                "package",
                "--handoff",
                str(rich_handoff),
                "--rich",
                "--json",
            ],
            cwd=work_root,
            env=env,
            timeout=timeout,
            dist_dir=dist_dir,
            work_root=work_root,
        )
        _record_command_check(checks, "doc-to-md rich handoff package", package_rich, required_json={"ok": True})
        rich_sidecars = [
            rich_handoff / name
            for name in (
                "metadata.json",
                "artifact_index.json",
                "profile_suggestions.json",
                "retrieval_hints.json",
                "assistant_profile.json",
                "assistant_test_plan.json",
                "package_readme.md",
            )
        ]
        for sidecar in rich_sidecars:
            _record_file_check(checks, f"rich sidecar {sidecar.name}", sidecar, work_root=work_root)

        for label, manifest, kb_name in (
            ("plain", plain_manifest, "kb:contract-fixture-plain"),
            ("rich", rich_manifest, "kb:contract-fixture-rich"),
        ):
            dry_run = _run_command(
                [
                    python_executable,
                    str(build_script),
                    "--doc-manifest",
                    str(manifest),
                    "--kb-name",
                    kb_name,
                    "--profile",
                    str(profile),
                    "--dry-run",
                    "--json",
                ],
                cwd=work_root,
                env=env,
                timeout=timeout,
                dist_dir=dist_dir,
                work_root=work_root,
            )
            _record_command_check(
                checks,
                f"kb-build {label} handoff dry-run",
                dry_run,
                required_json={"ok": True, "dry_run": True, "kb_name": kb_name},
            )

        inspect_rich = _run_command(
            [
                python_executable,
                str(build_script),
                "inspect-handoff",
                "--handoff",
                str(rich_handoff),
                "--report-json",
                str(rich_inspection_json),
                "--report-md",
                str(rich_inspection_md),
                "--json",
            ],
            cwd=work_root,
            env=env,
            timeout=timeout,
            dist_dir=dist_dir,
            work_root=work_root,
        )
        _record_command_check(
            checks,
            "kb-build inspect rich handoff",
            inspect_rich,
            required_json={"handoff.schema": "ragflow_handoff_inspection_v1"},
        )
        _record_file_check(checks, "rich handoff inspection JSON", rich_inspection_json, work_root=work_root)
        _record_file_check(checks, "rich handoff inspection Markdown", rich_inspection_md, work_root=work_root)

        report["artifacts"] = {
            "input": _artifact(input_dir, work_root=work_root),
            "plain_doc_manifest": _artifact(plain_manifest, work_root=work_root),
            "rich_doc_manifest": _artifact(rich_manifest, work_root=work_root),
            "rich_sidecars": [_artifact(path, work_root=work_root) for path in rich_sidecars],
            "rich_handoff_inspection_json": _artifact(rich_inspection_json, work_root=work_root),
            "rich_handoff_inspection_md": _artifact(rich_inspection_md, work_root=work_root),
        }
        return _finalize_report(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline handoff contract fixtures against release artifacts")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release dist directory to build or reuse")
    parser.add_argument("--no-build", action="store_true", help="Reuse --dist instead of rebuilding release artifacts")
    parser.add_argument("--work-dir", help="Work directory for fixture inputs and outputs")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temporary artifacts when --work-dir is omitted")
    parser.add_argument("--overwrite", action="store_true", help="Remove an existing --work-dir before running")
    parser.add_argument("--report-json", help="Optional path to write the gate report")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-command timeout in seconds")
    args = parser.parse_args(argv)

    try:
        report = run_contract_fixture_gate(
            dist_dir=Path(args.dist),
            work_dir=Path(args.work_dir) if args.work_dir else None,
            rebuild=not args.no_build,
            keep_artifacts=args.keep_artifacts,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
    except ContractFixtureGateError as exc:
        report = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "error": str(exc),
            "checks": [],
            "artifacts": {},
            "summary": {"check_count": 0, "failed_count": 1, "failed_checks": ["prepare work directory"]},
        }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
