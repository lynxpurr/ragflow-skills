#!/usr/bin/env python3
"""Build self-contained public skill release artifacts."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
DIST_DIR = ROOT / "dist"
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src" / "ragflow_skill_runtime"
PUBLIC_SKILLS = ["ragflow-doc-to-md", "ragflow-kb-build", "ragflow-query"]

EXCLUDE_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def ignore_filter(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in EXCLUDE_NAMES:
            ignored.add(name)
            continue
        if name.endswith(".pyc") or name.endswith(".pyo"):
            ignored.add(name)
    return ignored


def ensure_public_skills_exist() -> None:
    missing = [name for name in PUBLIC_SKILLS if not (SKILLS_DIR / name).exists()]
    if missing:
        raise SystemExit(f"missing public skill directories: {', '.join(missing)}")
    if not RUNTIME_SRC.exists():
        raise SystemExit(f"missing ragflow-skill-runtime source directory: {RUNTIME_SRC}")


def build_release(dist_dir: Path = DIST_DIR) -> list[Path]:
    ensure_public_skills_exist()
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    built: list[Path] = []
    for skill_name in PUBLIC_SKILLS:
        src = SKILLS_DIR / skill_name
        dst = dist_dir / skill_name
        shutil.copytree(src, dst, ignore=ignore_filter)

        vendor_parent = dst / "scripts" / "_vendor"
        vendor_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(RUNTIME_SRC, vendor_parent / "ragflow_skill_runtime", ignore=ignore_filter)
        built.append(dst)
    return built


def run_release_check(dist_dir: Path = DIST_DIR) -> int:
    build_release(dist_dir)

    smoke_script = dist_dir / "ragflow-query" / "scripts" / "bootstrap_smoke.py"
    if not smoke_script.exists():
        print(f"missing smoke script in release artifact: {smoke_script}", file=sys.stderr)
        return 2

    result = subprocess.run(
        [sys.executable, str(smoke_script)],
        cwd=dist_dir,
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": str(Path("/usr/bin")) + ":" + str(Path("/bin")), "PYTHONNOUSERSITE": "1"},
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Build self-contained public RAGFlow skill artifacts")
    parser.add_argument("--dist", default=str(DIST_DIR), help="Output directory for built artifacts")
    parser.add_argument("--check", action="store_true", help="Build artifacts and run vendor import smoke")
    args = parser.parse_args()

    dist_dir = Path(args.dist).resolve()
    if args.check:
        return run_release_check(dist_dir)

    built = build_release(dist_dir)
    for path in built:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
