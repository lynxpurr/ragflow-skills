#!/usr/bin/env python3
"""Build self-contained public skill release artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
DIST_DIR = ROOT / "dist"
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src" / "ragflow_skill_runtime"
PUBLIC_SKILLS = [
    "ragflow-doc-to-md",
    "ragflow-canonical-review",
    "ragflow-kb-build",
    "ragflow-query",
]

EXCLUDE_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "doc",
}

OPTIONAL_RESOURCE_DIRS = {"agents", "references"}


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
        remove_empty_optional_dirs(dst)

        vendor_parent = dst / "scripts" / "_vendor"
        vendor_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(RUNTIME_SRC, vendor_parent / "ragflow_skill_runtime", ignore=ignore_filter)
        built.append(dst)
    return built


def remove_empty_optional_dirs(skill_root: Path) -> None:
    """Drop optional resource folders when they contain no shipped resources."""

    for name in OPTIONAL_RESOURCE_DIRS:
        path = skill_root / name
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _run_query_release_smoke(dist_dir: Path, env: dict[str, str]) -> int:
    query_script = dist_dir / "ragflow-query" / "scripts" / "query.py"
    with tempfile.TemporaryDirectory(prefix="ragflow-query-release-smoke-") as tmp:
        runner = Path(tmp) / "query_release_smoke.py"
        runner.write_text(
            f"""\
import importlib.util
import json
from pathlib import Path

script = Path({str(query_script)!r})
spec = importlib.util.spec_from_file_location("release_query_cli", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
routing = Path(__file__).parent / "routing.json"
routing.write_text(json.dumps({{
    "version": "0.1",
    "knowledge_bases": [
        {{
            "name": "kb:release-smoke",
            "dataset_id": "ds-smoke",
            "hints": ["release smoke"],
            "params": {{"top_k": 5}}
        }}
    ]
}}, ensure_ascii=False), encoding="utf-8")

class FakeClient:
    def __init__(self, config):
        self.config = config
    def retrieve(self, *, question, dataset_ids, top_k=5, similarity_threshold=None):
        return {{
            "data": {{
                "chunks": [
                    {{
                        "content_with_weight": "release smoke chunk for " + str(question),
                        "docnm_kwd": "release-smoke.md",
                        "similarity": 0.99,
                        "kb_id": dataset_ids[0] if dataset_ids else "ds-smoke",
                    }}
                ]
            }}
        }}

module.RAGFlowClient = FakeClient
payloads = []
trace_json = Path(__file__).parent / "query_trace.json"
trace_md = Path(__file__).parent / "query_trace.md"
for argv in [
    ["--base-url", "https://ragflow.example.test", "--api-key", "test-key", "ask", "release smoke", "--dataset-id", "ds-smoke", "--mode", "direct", "--json"],
    ["--base-url", "https://ragflow.example.test", "--api-key", "test-key", "ask", "release smoke", "--dataset-id", "ds-smoke", "--mode", "agentic", "--host-assisted", "--json", "--trace-json", str(trace_json), "--trace-md", str(trace_md)],
    ["--base-url", "https://ragflow.example.test", "--api-key", "test-key", "ask", "release smoke", "--mode", "auto", "--routing-config", str(routing), "--json"],
]:
    from io import StringIO
    import contextlib
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = module.main(argv)
    if code != 0:
        raise SystemExit(code)
    payload = json.loads(stdout.getvalue())
    if not payload.get("ok") or not payload.get("chunks") or not payload.get("evidence"):
        raise SystemExit(2)
    payloads.append(payload)
if not trace_json.exists() or "RAGFlow Query Trace" not in trace_md.read_text(encoding="utf-8"):
    raise SystemExit(3)
query_output = Path(__file__).parent / "query_output.json"
audit_json = Path(__file__).parent / "citation_audit.json"
audit_md = Path(__file__).parent / "citation_audit.md"
diagnostic_json = Path(__file__).parent / "query_diagnostic.json"
diagnostic_md = Path(__file__).parent / "query_diagnostic.md"
query_output.write_text(json.dumps(payloads[1], ensure_ascii=False, indent=2), encoding="utf-8")
from io import StringIO
import contextlib
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    audit_code = module.main([
        "audit-citations",
        "--query-output",
        str(query_output),
        "--answer",
        "Release smoke answer [1].",
        "--report-json",
        str(audit_json),
        "--report-md",
        str(audit_md),
        "--json",
    ])
if audit_code != 0:
    raise SystemExit(audit_code)
audit_payload = json.loads(stdout.getvalue())
if not audit_payload.get("ok") or not audit_json.exists() or not audit_md.exists():
    raise SystemExit(4)
stdout = StringIO()
with contextlib.redirect_stdout(stdout):
    diagnostic_code = module.main([
        "diagnose-result",
        "--query-output",
        str(query_output),
        "--trace-json",
        str(trace_json),
        "--citation-audit",
        str(audit_json),
        "--expected-term",
        "release",
        "--report-json",
        str(diagnostic_json),
        "--report-md",
        str(diagnostic_md),
        "--json",
    ])
if diagnostic_code != 0:
    raise SystemExit(diagnostic_code)
diagnostic_payload = json.loads(stdout.getvalue())
if not diagnostic_payload.get("ok") or not diagnostic_json.exists() or not diagnostic_md.exists():
    raise SystemExit(5)
print(json.dumps({{"ok": True, "payloads": payloads, "audit": audit_payload, "diagnostic": diagnostic_payload}}, ensure_ascii=False))
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(runner)],
            cwd=dist_dir,
            text=True,
            capture_output=True,
            check=False,
            env={**env, "PYTHONNOUSERSITE": "1", "RAGFLOW_SKILL_RUNTIME_PATH": ""},
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode != 0:
            print("query release smoke failed", file=sys.stderr)
        return result.returncode


def run_release_check(dist_dir: Path = DIST_DIR) -> int:
    build_release(dist_dir)

    checks = [
        [sys.executable, str(dist_dir / "ragflow-query" / "scripts" / "bootstrap_smoke.py")],
        [sys.executable, str(dist_dir / "ragflow-query" / "scripts" / "query.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"), "adaptive", "--help"],
        [sys.executable, str(dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"), "inspect-source", "--help"],
        [sys.executable, str(dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"), "package", "--help"],
        [sys.executable, str(dist_dir / "ragflow-doc-to-md" / "scripts" / "convert.py"), "postprocess", "--help"],
        [sys.executable, str(dist_dir / "ragflow-canonical-review" / "scripts" / "audit_markdown_structure.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-canonical-review" / "scripts" / "audit_canonical_assets.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-canonical-review" / "scripts" / "finalize_review.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-kb-build" / "scripts" / "build.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-kb-build" / "scripts" / "build.py"), "inspect-handoff", "--help"],
        [sys.executable, str(dist_dir / "ragflow-kb-build" / "scripts" / "inspect_kb.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-kb-build" / "scripts" / "profile.py"), "--help"],
        [sys.executable, str(dist_dir / "ragflow-kb-build" / "scripts" / "validate.py"), "--help"],
    ]
    env = {
        "PATH": str(Path("/usr/bin")) + ":" + str(Path("/bin")),
        "PYTHONNOUSERSITE": "1",
    }
    for command in checks:
        result = subprocess.run(
            command,
            cwd=dist_dir,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode != 0:
            print(f"release check failed: {' '.join(command)}", file=sys.stderr)
            return result.returncode
    return _run_query_release_smoke(dist_dir, env)


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
