#!/usr/bin/env python3
"""Export the optional runtime wheel artifact after no-network smoke validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from wheel_packaging_smoke import PACKAGE_DIR, ROOT, run_wheel_packaging_smoke


SCHEMA = "ragflow_runtime_wheel_export_v1"
DEFAULT_OUTPUT_DIR = ROOT / "release-artifacts" / "wheels"
MANIFEST_NAME = "runtime-wheel-manifest.json"


class RuntimeWheelExportError(RuntimeError):
    """Raised when runtime wheel export cannot be prepared."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@contextmanager
def _prepared_work_root(
    work_dir: Path | None,
    *,
    overwrite: bool,
) -> Iterator[tuple[Path, bool]]:
    if work_dir is not None:
        root = work_dir.resolve()
        if root.exists() and any(root.iterdir()):
            if not overwrite:
                raise RuntimeWheelExportError(f"work directory is not empty: {root}")
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        yield root, True
        return

    with tempfile.TemporaryDirectory(prefix="ragflow-runtime-wheel-export-") as tmp:
        yield Path(tmp).resolve(), False


def _failure_report(
    *,
    output_dir: Path,
    work_root: Path | None,
    artifacts_retained: bool,
    smoke: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    failed = ["wheel packaging smoke"] if smoke is not None else ["prepare wheel export"]
    return {
        "ok": False,
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "source_commit": source_commit(),
        "output_dir": str(output_dir),
        "work_root": str(work_root) if work_root else None,
        "artifacts_retained": artifacts_retained,
        "manifest": None,
        "wheel": None,
        "smoke": smoke,
        "error": error,
        "summary": {
            "wheel_count": 0,
            "failed_count": 1,
            "failed_checks": failed,
        },
    }


def export_runtime_wheel(
    *,
    package_dir: Path = PACKAGE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    work_dir: Path | None = None,
    overwrite: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Export a smoke-validated runtime wheel and manifest."""

    package_dir = package_dir.resolve()
    output_dir = output_dir.resolve()
    with _prepared_work_root(work_dir, overwrite=overwrite) as (work_root, artifacts_retained):
        smoke_work = work_root / "smoke"
        smoke = run_wheel_packaging_smoke(
            package_dir=package_dir,
            work_dir=smoke_work,
            keep_artifacts=True,
            overwrite=True,
            timeout=timeout,
        )
        if not smoke.get("ok"):
            return _failure_report(
                output_dir=output_dir,
                work_root=work_root,
                artifacts_retained=artifacts_retained,
                smoke=smoke,
                error="wheel packaging smoke failed",
            )

        wheel_info = smoke.get("wheel")
        wheel_source = Path(str(wheel_info.get("path"))) if isinstance(wheel_info, dict) else None
        if wheel_source is None or not wheel_source.exists():
            return _failure_report(
                output_dir=output_dir,
                work_root=work_root,
                artifacts_retained=artifacts_retained,
                smoke=smoke,
                error="wheel packaging smoke did not produce a wheel path",
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        wheel_path = output_dir / wheel_source.name
        shutil.copy2(wheel_source, wheel_path)
        wheel_payload = {
            "filename": wheel_path.name,
            "path": str(wheel_path),
            "sha256": sha256_file(wheel_path),
            "bytes": wheel_path.stat().st_size,
        }
        manifest = {
            "ok": True,
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "source_commit": source_commit(),
            "output_dir": str(output_dir),
            "work_root": str(work_root),
            "artifacts_retained": artifacts_retained,
            "package": smoke.get("package", {}),
            "wheel": wheel_payload,
            "smoke": {
                "ok": True,
                "schema": smoke.get("schema"),
                "install_method": (smoke.get("install_environment") or {}).get("method"),
                "summary": smoke.get("summary", {}),
            },
            "summary": {
                "wheel_count": 1,
                "failed_count": 0,
                "failed_checks": [],
            },
        }
        manifest_path = output_dir / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["manifest"] = str(manifest_path)
        return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a smoke-validated RAGFlow runtime wheel")
    parser.add_argument("--package-dir", default=str(PACKAGE_DIR), help="Runtime package directory")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Wheel artifact output directory")
    parser.add_argument("--work-dir", help="Work directory for wheel smoke artifacts")
    parser.add_argument("--overwrite", action="store_true", help="Remove an existing --work-dir before running")
    parser.add_argument("--report-json", help="Optional path to write the export report")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-command timeout in seconds")
    args = parser.parse_args(argv)

    try:
        payload = export_runtime_wheel(
            package_dir=Path(args.package_dir),
            output_dir=Path(args.output_dir),
            work_dir=Path(args.work_dir) if args.work_dir else None,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
    except RuntimeWheelExportError as exc:
        payload = _failure_report(
            output_dir=Path(args.output_dir).resolve(),
            work_root=Path(args.work_dir).resolve() if args.work_dir else None,
            artifacts_retained=bool(args.work_dir),
            error=str(exc),
        )

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
