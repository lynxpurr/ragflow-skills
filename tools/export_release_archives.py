#!/usr/bin/env python3
"""Export deterministic per-skill release archives."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_release import DIST_DIR, PUBLIC_SKILLS, ROOT, build_release
from release_hygiene_check import run_hygiene_check


ARTIFACTS_DIR = ROOT / "release-artifacts"
DEFAULT_MTIME = 1767225600  # 2026-01-01T00:00:00Z


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


def _archive_paths(skill_root: Path) -> list[Path]:
    return [skill_root] + sorted(skill_root.rglob("*"), key=lambda path: path.relative_to(skill_root).as_posix())


def _tar_mode(path: Path) -> int:
    if path.is_dir():
        return 0o755
    mode = stat.S_IMODE(path.stat().st_mode)
    return 0o755 if mode & 0o111 else 0o644


def create_skill_archive(
    *,
    skill_root: Path,
    dist_dir: Path,
    archive_path: Path,
    mtime: int = DEFAULT_MTIME,
) -> dict[str, Any]:
    """Create one deterministic tar.gz archive for a release skill folder."""

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in _archive_paths(skill_root):
            relative = path.relative_to(dist_dir).as_posix()
            info = tarfile.TarInfo(relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = mtime
            info.mode = _tar_mode(path)
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                info.size = 0
                tar.addfile(info)
            elif path.is_file():
                info.type = tarfile.REGTYPE
                info.size = path.stat().st_size
                with path.open("rb") as handle:
                    tar.addfile(info, handle)

    archive_path.write_bytes(gzip.compress(tar_buffer.getvalue(), compresslevel=9, mtime=mtime))
    return {
        "name": skill_root.name,
        "archive": archive_path.name,
        "sha256": sha256_file(archive_path),
        "bytes": archive_path.stat().st_size,
    }


def export_release_archives(
    *,
    dist_dir: Path = DIST_DIR,
    output_dir: Path = ARTIFACTS_DIR,
    rebuild: bool = True,
    hygiene: bool = True,
    mtime: int = DEFAULT_MTIME,
) -> dict[str, Any]:
    hygiene_payload: dict[str, Any] | None = None
    if hygiene:
        hygiene_payload = run_hygiene_check(dist_dir=dist_dir, rebuild=rebuild, scan_source=True)
        if not hygiene_payload["ok"]:
            return {
                "ok": False,
                "error": "release hygiene check failed",
                "hygiene": hygiene_payload,
            }
    elif rebuild:
        build_release(dist_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    archives = []
    for skill_name in PUBLIC_SKILLS:
        skill_root = dist_dir / skill_name
        if not skill_root.exists():
            return {
                "ok": False,
                "error": f"release skill folder missing: {skill_root}",
            }
        archives.append(
            create_skill_archive(
                skill_root=skill_root,
                dist_dir=dist_dir,
                archive_path=output_dir / f"{skill_name}.tar.gz",
                mtime=mtime,
            )
        )

    manifest = {
        "ok": True,
        "version": "0.1",
        "created_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        "source_commit": source_commit(),
        "dist": dist_dir.name,
        "output_dir": output_dir.name,
        "hygiene": {
            "ok": hygiene_payload["ok"] if hygiene_payload else None,
            "findings": len(hygiene_payload["findings"]) if hygiene_payload else None,
        },
        "archives": archives,
    }
    manifest_path = output_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export deterministic public skill release archives")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Release artifact directory")
    parser.add_argument("--output-dir", default=str(ARTIFACTS_DIR), help="Archive output directory")
    parser.add_argument("--no-build", action="store_true", help="Use an existing dist directory")
    parser.add_argument("--skip-hygiene", action="store_true", help="Skip release hygiene gate")
    parser.add_argument("--mtime", type=int, default=DEFAULT_MTIME, help="Archive mtime as Unix seconds")
    args = parser.parse_args(argv)

    payload = export_release_archives(
        dist_dir=Path(args.dist).resolve(),
        output_dir=Path(args.output_dir).resolve(),
        rebuild=not args.no_build,
        hygiene=not args.skip_hygiene,
        mtime=args.mtime,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
