#!/usr/bin/env python3
"""Build and install the runtime wheel in a clean no-network smoke environment."""

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

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10 hosts
    tomllib = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "ragflow-skill-runtime"
SCHEMA = "ragflow_wheel_packaging_smoke_v1"


class WheelPackagingSmokeError(RuntimeError):
    """Raised when the wheel packaging smoke cannot be prepared."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pip_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
    }


def _isolated_python_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PYTHONPATH": "",
    }


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


def _tokenize_path(value: str, *, package_dir: Path, work_root: Path) -> str:
    if "\n" in value:
        return (
            value.replace(str(work_root.resolve()), "<work>")
            .replace(str(package_dir.resolve()), "<package>")
            .replace(str(ROOT.resolve()), "<repo>")
        )
    if value.startswith("-") or (not Path(value).is_absolute() and "/" not in value and "\\" not in value):
        return value
    for root, token in (
        (work_root.resolve(), "<work>"),
        (package_dir.resolve(), "<package>"),
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


def _display_command(command: list[str], *, package_dir: Path, work_root: Path) -> list[str]:
    return [_tokenize_path(part, package_dir=package_dir, work_root=work_root) for part in command]


def _parse_json_output(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    package_dir: Path,
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
            "command": _display_command(command, package_dir=package_dir, work_root=work_root),
            "returncode": 124,
            "stdout_preview": _preview(exc.stdout or ""),
            "stderr_preview": f"timed out after {timeout} seconds",
            "stdout_json": None,
            "ok": False,
            "error": f"timed out after {timeout} seconds",
        }

    return {
        "command": _display_command(command, package_dir=package_dir, work_root=work_root),
        "returncode": result.returncode,
        "stdout_preview": _preview(result.stdout),
        "stderr_preview": _preview(result.stderr),
        "stdout_json": _parse_json_output(result.stdout),
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else _preview(f"{result.stdout}\n{result.stderr}"),
    }


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
                if payload.get(key) != expected
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


def _read_project_with_tomllib(pyproject: Path) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("tomllib is unavailable")
    with pyproject.open("rb") as handle:
        payload = tomllib.load(handle)
    project = payload.get("project", {})
    return dict(project) if isinstance(project, Mapping) else {}


def _read_project_fallback(pyproject: Path) -> dict[str, Any]:
    project: dict[str, Any] = {}
    in_project = False
    for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project or "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if key in {"name", "version", "description", "requires-python"}:
            project[key] = raw_value.strip('"')
        elif key == "dependencies":
            project[key] = (
                []
                if raw_value == "[]"
                else [item.strip().strip('"') for item in raw_value.strip("[]").split(",") if item.strip()]
            )
    return project


def _project_metadata(package_dir: Path) -> dict[str, Any]:
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        project = _read_project_with_tomllib(pyproject)
    except RuntimeError:
        project = _read_project_fallback(pyproject)
    return {
        "name": str(project.get("name") or ""),
        "version": str(project.get("version") or ""),
        "dependencies": list(project.get("dependencies") or []),
        "requires_python": str(project.get("requires-python") or ""),
    }


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _import_smoke_code(*, expected_distribution: str, target_dir: Path | None = None) -> str:
    lines = [
        "import importlib.metadata as metadata",
        "import json",
        "import sys",
    ]
    if target_dir is not None:
        lines.append(f"sys.path.insert(0, {str(target_dir)!r})")
    lines.extend(
        [
            "import ragflow_skill_runtime as runtime",
            "print(json.dumps({",
            "    'ok': True,",
            f"    'distribution_version': metadata.version({expected_distribution!r}),",
            "    'runtime_version': getattr(runtime, '__version__', None),",
            "    'module_file': runtime.__file__,",
            "}, sort_keys=True))",
        ]
    )
    return "\n".join(lines)


def _find_wheel(wheel_dir: Path) -> Path | None:
    wheels = sorted(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        return None
    return wheels[0]


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
                raise WheelPackagingSmokeError(f"work directory is not empty: {root}")
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        yield root, True
        return

    if keep_artifacts:
        root = Path(tempfile.mkdtemp(prefix="ragflow-wheel-packaging-smoke-")).resolve()
        yield root, True
        return

    with tempfile.TemporaryDirectory(prefix="ragflow-wheel-packaging-smoke-") as tmp:
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


def run_wheel_packaging_smoke(
    *,
    package_dir: Path = PACKAGE_DIR,
    work_dir: Path | None = None,
    keep_artifacts: bool = False,
    overwrite: bool = False,
    python_executable: str = sys.executable,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Build, install, and import-smoke the runtime wheel without network access."""

    package_dir = package_dir.resolve()
    with _prepared_work_root(work_dir, keep_artifacts=keep_artifacts, overwrite=overwrite) as (
        work_root,
        artifacts_retained,
    ):
        wheel_dir = work_root / "wheelhouse"
        venv_dir = work_root / "venv"
        target_dir = work_root / "target"
        checks: list[dict[str, Any]] = []
        metadata = _project_metadata(package_dir)
        report: dict[str, Any] = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "package": {
                "dir": str(package_dir),
                "name": metadata.get("name", ""),
                "version": metadata.get("version", ""),
                "requires_python": metadata.get("requires_python", ""),
                "dependencies": metadata.get("dependencies", []),
            },
            "network": {
                "no_index": True,
                "no_deps": True,
                "no_build_isolation": True,
            },
            "work_root": str(work_root),
            "artifacts_retained": artifacts_retained,
            "wheel": None,
            "install_environment": None,
            "import_smoke": None,
            "checks": checks,
            "summary": {},
        }

        _record_check(
            checks,
            "package directory exists",
            ok=package_dir.exists(),
            error=f"missing package directory: {package_dir}",
            kind="file",
            path=_relative(package_dir, ROOT),
        )
        _record_check(
            checks,
            "pyproject metadata present",
            ok=bool(metadata.get("name") and metadata.get("version")),
            error=f"missing project name or version in {package_dir / 'pyproject.toml'}",
            kind="metadata",
        )
        _record_check(
            checks,
            "runtime dependencies empty",
            ok=metadata.get("dependencies", []) == [],
            error=f"runtime wheel has dependencies: {metadata.get('dependencies', [])}",
            kind="metadata",
            dependencies=metadata.get("dependencies", []),
        )
        if any(not check.get("ok") for check in checks):
            return _finalize_report(report)

        wheel_dir.mkdir(parents=True, exist_ok=True)
        pip_env = _pip_env()
        build_result = _run_command(
            [
                python_executable,
                "-m",
                "pip",
                "wheel",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheel_dir),
                str(package_dir),
            ],
            cwd=ROOT,
            env=pip_env,
            timeout=timeout,
            package_dir=package_dir,
            work_root=work_root,
        )
        _record_command_check(checks, "build runtime wheel", build_result)

        wheel = _find_wheel(wheel_dir)
        _record_check(
            checks,
            "exactly one wheel produced",
            ok=wheel is not None,
            error=f"expected one wheel in {wheel_dir}, found {len(list(wheel_dir.glob('*.whl')))}",
            kind="file",
            path=_relative(wheel_dir, work_root),
        )
        if wheel is not None:
            report["wheel"] = {
                "path": str(wheel),
                "filename": wheel.name,
                "bytes": wheel.stat().st_size,
            }
        if any(not check.get("ok") for check in checks):
            return _finalize_report(report)

        isolated_env = _isolated_python_env()
        venv_result = _run_command(
            [python_executable, "-m", "venv", str(venv_dir)],
            cwd=ROOT,
            env=isolated_env,
            timeout=timeout,
            package_dir=package_dir,
            work_root=work_root,
        )
        venv_python = _venv_python(venv_dir)
        if venv_result["ok"] and venv_python.exists():
            install_method = "venv"
            install_python = venv_python
            install_command = [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            ]
            import_command = [
                str(venv_python),
                "-c",
                _import_smoke_code(expected_distribution=metadata["name"]),
            ]
            install_env = pip_env
            import_env = isolated_env
            install_location = venv_dir
            venv_available = True
            venv_error = ""
        else:
            install_method = "target"
            install_python = Path(python_executable)
            target_dir.mkdir(parents=True, exist_ok=True)
            install_command = [
                python_executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--target",
                str(target_dir),
                str(wheel),
            ]
            import_command = [
                python_executable,
                "-I",
                "-c",
                _import_smoke_code(target_dir=target_dir, expected_distribution=metadata["name"]),
            ]
            install_env = pip_env
            import_env = isolated_env
            install_location = target_dir
            venv_available = False
            venv_error = venv_result.get("error") or venv_result.get("stderr_preview") or "venv unavailable"

        report["install_environment"] = {
            "method": install_method,
            "path": str(install_location),
            "python": str(install_python),
            "venv_available": venv_available,
            "venv_error_preview": _preview(str(venv_error)) if venv_error else "",
        }
        _record_check(
            checks,
            "prepare isolated install environment",
            ok=True,
            kind="environment",
            method=install_method,
            path=_relative(install_location, work_root),
            venv_available=venv_available,
        )

        install_result = _run_command(
            install_command,
            cwd=work_root,
            env=install_env,
            timeout=timeout,
            package_dir=package_dir,
            work_root=work_root,
        )
        _record_command_check(checks, "install wheel without index", install_result)
        if any(not check.get("ok") for check in checks):
            return _finalize_report(report)

        smoke_result = _run_command(
            import_command,
            cwd=work_root,
            env=import_env,
            timeout=timeout,
            package_dir=package_dir,
            work_root=work_root,
        )
        _record_command_check(
            checks,
            "import installed runtime",
            smoke_result,
            required_json={
                "ok": True,
                "distribution_version": metadata["version"],
                "runtime_version": metadata["version"],
            },
        )
        report["import_smoke"] = smoke_result.get("stdout_json")
        return _finalize_report(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and install the RAGFlow runtime wheel without network access")
    parser.add_argument("--package-dir", default=str(PACKAGE_DIR), help="Runtime package directory")
    parser.add_argument("--work-dir", help="Work directory for wheelhouse and temporary venv")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temporary artifacts when --work-dir is omitted")
    parser.add_argument("--overwrite", action="store_true", help="Remove an existing --work-dir before running")
    parser.add_argument("--report-json", help="Optional path to write the smoke report")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-command timeout in seconds")
    args = parser.parse_args(argv)

    try:
        report = run_wheel_packaging_smoke(
            package_dir=Path(args.package_dir),
            work_dir=Path(args.work_dir) if args.work_dir else None,
            keep_artifacts=args.keep_artifacts,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
    except WheelPackagingSmokeError as exc:
        report = {
            "ok": False,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "error": str(exc),
            "checks": [],
            "summary": {
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
