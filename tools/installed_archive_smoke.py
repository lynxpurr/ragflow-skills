#!/usr/bin/env python3
"""Smoke test exported skill archives after unpacking them independently."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from build_release import DIST_DIR, PUBLIC_SKILLS, ROOT
from export_release_archives import ARTIFACTS_DIR, export_release_archives


SCHEMA = "ragflow_installed_archive_smoke_v1"
MANIFEST_NAME = "release-manifest.json"


class InstalledArchiveSmokeError(RuntimeError):
    """Raised when installed archive smoke cannot be prepared."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _minimal_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "RAGFLOW_SKILL_RUNTIME_PATH": "",
    }


def _preview(text: str, *, limit: int = 400) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokenize_path(value: str, *, artifacts_dir: Path, work_root: Path) -> str:
    if value.startswith("-") or (not Path(value).is_absolute() and "/" not in value and "\\" not in value):
        return value
    for root, token in (
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


def _display_command(command: list[str], *, artifacts_dir: Path, work_root: Path) -> list[str]:
    return [_tokenize_path(part, artifacts_dir=artifacts_dir, work_root=work_root) for part in command]


def _record_check(
    checks: list[dict[str, Any]],
    name: str,
    *,
    ok: bool,
    error: str = "",
    **extra: Any,
) -> None:
    payload = {"name": name, "ok": ok, "error": "" if ok else error}
    payload.update(extra)
    checks.append(payload)


def _record_file_check(checks: list[dict[str, Any]], name: str, path: Path, *, root: Path) -> None:
    try:
        display_path = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        display_path = str(path)
    _record_check(
        checks,
        name,
        ok=path.exists(),
        error=f"missing {path}",
        kind="file",
        path=display_path,
    )


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    artifacts_dir: Path,
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
            "command": _display_command(command, artifacts_dir=artifacts_dir, work_root=work_root),
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": "",
            "stdout_preview": _preview(exc.stdout or ""),
            "stderr_preview": f"timed out after {timeout} seconds",
            "ok": False,
            "error": f"timed out after {timeout} seconds",
        }
    return {
        "command": _display_command(command, artifacts_dir=artifacts_dir, work_root=work_root),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "stdout_preview": _preview(result.stdout),
        "stderr_preview": _preview(result.stderr),
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else _preview(f"{result.stdout}\n{result.stderr}"),
    }


def _record_command_check(
    checks: list[dict[str, Any]],
    name: str,
    result: dict[str, Any],
    *,
    required_output: str | None = None,
) -> None:
    ok = bool(result["ok"])
    error = str(result.get("error") or "")
    if ok and required_output:
        combined = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        if required_output not in combined:
            ok = False
            error = f"output did not contain {required_output!r}"
    checks.append(
        {
            "name": name,
            "kind": "command",
            "ok": ok,
            "command": result["command"],
            "returncode": result["returncode"],
            "stdout_preview": result["stdout_preview"],
            "stderr_preview": result["stderr_preview"],
            "error": "" if ok else error,
        }
    )


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (base / member.name).resolve()
            if target != base and base not in target.parents:
                raise InstalledArchiveSmokeError(f"unsafe path in archive {archive}: {member.name}")
        try:
            tar.extractall(base, filter="data")
        except TypeError:
            tar.extractall(base)


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
                raise InstalledArchiveSmokeError(f"work directory is not empty: {root}")
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        yield root, True
        return

    if keep_artifacts:
        root = Path(tempfile.mkdtemp(prefix="ragflow-installed-archive-smoke-")).resolve()
        yield root, True
        return

    with tempfile.TemporaryDirectory(prefix="ragflow-installed-archive-smoke-") as tmp:
        yield Path(tmp).resolve(), False


def _archive_manifest(artifacts_dir: Path) -> dict[str, Any] | None:
    manifest_path = artifacts_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _expected_archive_item(manifest: Mapping[str, Any] | None, skill_name: str) -> Mapping[str, Any] | None:
    for item in (manifest or {}).get("archives", []):
        if isinstance(item, Mapping) and item.get("name") == skill_name:
            return item
    return None


def _smoke_commands(skill_name: str, skill_root: Path, python_executable: str) -> list[tuple[str, list[str], str]]:
    if skill_name == "ragflow-doc-to-md":
        return [
            (
                "doc-to-md convert help",
                [python_executable, str(skill_root / "scripts" / "convert.py"), "--help"],
                "Convert documents into a Markdown handoff bundle",
            )
        ]
    if skill_name == "ragflow-kb-build":
        return [
            (
                "kb-build build help",
                [python_executable, str(skill_root / "scripts" / "build.py"), "--help"],
                "Build a RAGFlow KB from Markdown",
            )
        ]
    if skill_name == "ragflow-query":
        return [
            (
                "query bootstrap smoke",
                [python_executable, str(skill_root / "scripts" / "bootstrap_smoke.py")],
                '"ok": true',
            ),
            (
                "query CLI help",
                [python_executable, str(skill_root / "scripts" / "query.py"), "--help"],
                "Portable RAGFlow query CLI",
            ),
        ]
    return []


def _smoke_one_archive(
    *,
    skill_name: str,
    archive: Path,
    expected_item: Mapping[str, Any] | None,
    work_root: Path,
    artifacts_dir: Path,
    python_executable: str,
    timeout: float,
) -> dict[str, Any]:
    archive_root = work_root / "archives" / skill_name
    extract_root = archive_root / "unpacked"
    skill_root = extract_root / skill_name
    checks: list[dict[str, Any]] = []

    _record_file_check(checks, "archive exists", archive, root=artifacts_dir)
    if not archive.exists():
        return {
            "name": skill_name,
            "archive": archive.name,
            "ok": False,
            "extract_root": str(extract_root),
            "checks": checks,
        }

    actual_sha256 = _sha256_file(archive)
    expected_sha256 = str(expected_item.get("sha256")) if expected_item and expected_item.get("sha256") else None
    _record_check(
        checks,
        "archive sha256 matches manifest",
        ok=expected_sha256 is None or actual_sha256 == expected_sha256,
        error=f"expected {expected_sha256}, got {actual_sha256}",
        kind="archive",
        actual_sha256=actual_sha256,
        expected_sha256=expected_sha256,
    )

    try:
        _safe_extract(archive, extract_root)
        _record_check(checks, "archive extracts safely", ok=True, kind="archive", path=str(extract_root))
    except (tarfile.TarError, OSError, InstalledArchiveSmokeError) as exc:
        _record_check(checks, "archive extracts safely", ok=False, kind="archive", error=str(exc))
        return {
            "name": skill_name,
            "archive": archive.name,
            "ok": False,
            "extract_root": str(extract_root),
            "checks": checks,
        }

    _record_file_check(checks, "skill root present", skill_root, root=extract_root)
    _record_file_check(checks, "SKILL.md present", skill_root / "SKILL.md", root=extract_root)
    _record_file_check(
        checks,
        "vendored runtime present",
        skill_root / "scripts" / "_vendor" / "ragflow_skill_runtime" / "__init__.py",
        root=extract_root,
    )

    env = _minimal_env()
    for name, command, required_output in _smoke_commands(skill_name, skill_root, python_executable):
        result = _run_command(
            command,
            cwd=archive_root,
            env=env,
            timeout=timeout,
            artifacts_dir=artifacts_dir,
            work_root=work_root,
        )
        _record_command_check(checks, name, result, required_output=required_output)

    return {
        "name": skill_name,
        "archive": archive.name,
        "ok": all(check.get("ok") for check in checks),
        "extract_root": str(extract_root),
        "checks": checks,
    }


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    failed_checks = []
    check_count = 0
    for archive in report["archives"]:
        for check in archive["checks"]:
            check_count += 1
            if not check.get("ok"):
                failed_checks.append(f"{archive['name']}: {check['name']}")
    report["ok"] = not failed_checks
    report["summary"] = {
        "archive_count": len(report["archives"]),
        "check_count": check_count,
        "failed_count": len(failed_checks),
        "failed_checks": failed_checks,
    }
    return report


def run_installed_archive_smoke(
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
    dist_dir: Path = DIST_DIR,
    work_dir: Path | None = None,
    export_archives: bool = True,
    hygiene: bool = True,
    keep_artifacts: bool = False,
    overwrite: bool = False,
    python_executable: str = sys.executable,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run no-network smoke checks against each exported release archive."""

    artifacts_dir = artifacts_dir.resolve()
    dist_dir = dist_dir.resolve()
    export_payload: dict[str, Any] | None = None
    if export_archives:
        export_payload = export_release_archives(
            dist_dir=dist_dir,
            output_dir=artifacts_dir,
            rebuild=True,
            hygiene=hygiene,
        )
        if not export_payload.get("ok"):
            return {
                "ok": False,
                "schema": SCHEMA,
                "created_at": _utc_now(),
                "artifacts_dir": str(artifacts_dir),
                "work_root": None,
                "export": export_payload,
                "archives": [],
                "summary": {
                    "archive_count": 0,
                    "check_count": 0,
                    "failed_count": 1,
                    "failed_checks": ["export release archives"],
                },
            }

    with _prepared_work_root(work_dir, keep_artifacts=keep_artifacts, overwrite=overwrite) as (
        work_root,
        artifacts_retained,
    ):
        manifest = _archive_manifest(artifacts_dir)
        report: dict[str, Any] = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "artifacts_dir": str(artifacts_dir),
            "work_root": str(work_root),
            "artifacts_retained": artifacts_retained,
            "export": export_payload,
            "release_manifest": {
                "path": str(artifacts_dir / MANIFEST_NAME),
                "found": manifest is not None,
                "archive_count": len(manifest.get("archives", [])) if manifest else 0,
            },
            "archives": [],
            "summary": {},
        }
        archives: list[dict[str, Any]] = report["archives"]
        for skill_name in PUBLIC_SKILLS:
            expected_item = _expected_archive_item(manifest, skill_name)
            archive_name = str(expected_item.get("archive")) if expected_item and expected_item.get("archive") else f"{skill_name}.tar.gz"
            archives.append(
                _smoke_one_archive(
                    skill_name=skill_name,
                    archive=artifacts_dir / archive_name,
                    expected_item=expected_item,
                    work_root=work_root,
                    artifacts_dir=artifacts_dir,
                    python_executable=python_executable,
                    timeout=timeout,
                )
            )
        return _finalize_report(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test exported RAGFlow skill archives after installation")
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR), help="Directory containing release archives")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release dist directory used when exporting archives")
    parser.add_argument("--no-export", action="store_true", help="Reuse existing archives instead of exporting first")
    parser.add_argument("--skip-hygiene", action="store_true", help="Skip hygiene when exporting archives")
    parser.add_argument("--work-dir", help="Work directory for unpacked archives")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temporary artifacts when --work-dir is omitted")
    parser.add_argument("--overwrite", action="store_true", help="Remove an existing --work-dir before running")
    parser.add_argument("--report-json", help="Optional path to write the smoke report")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-command timeout in seconds")
    args = parser.parse_args(argv)

    try:
        report = run_installed_archive_smoke(
            artifacts_dir=Path(args.artifacts_dir),
            dist_dir=Path(args.dist),
            work_dir=Path(args.work_dir) if args.work_dir else None,
            export_archives=not args.no_export,
            hygiene=not args.skip_hygiene,
            keep_artifacts=args.keep_artifacts,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
    except InstalledArchiveSmokeError as exc:
        report = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "error": str(exc),
            "archives": [],
            "summary": {
                "archive_count": 0,
                "check_count": 0,
                "failed_count": 1,
                "failed_checks": ["prepare work directory"],
            },
        }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
