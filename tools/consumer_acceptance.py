#!/usr/bin/env python3
"""Validate release artifacts from a clean consumer workspace."""

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
import uuid
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
    quality_report = handoff_dir / "quality_report.json"
    _record_file_check(checks, "quality_report produced", quality_report)
    if quality_report.exists():
        produced.append(quality_report)

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
    fake_mineru_cli = _write_fake_mineru_cli(work_root / "mineru")
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

    inspect_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "inspect",
            "--doc-manifest",
            str(doc_manifest),
            "--report-json",
            str(work_root / "quality_report.inspect.json"),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md inspect quality", inspect_result, required_output='"status": "PASS"')
    inspect_report = work_root / "quality_report.inspect.json"
    if inspect_report.exists():
        produced.append(inspect_report)

    postprocess_dir = work_root / "postprocessed-handoff"
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
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "doc-to-md postprocess safe", postprocess_result, required_output='"schema": "doc_postprocess_report_v1"')
    postprocess_report = postprocess_dir / "postprocess_report.json"
    _record_file_check(checks, "postprocess_report produced", postprocess_report)
    if postprocess_report.exists():
        produced.append(postprocess_report)
    postprocessed_manifest = postprocess_dir / "doc_manifest.json"
    if postprocessed_manifest.exists():
        produced.append(postprocessed_manifest)

    long_markdown = work_root / "long.md"
    long_markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")
    segmentation_plan = work_root / "segmentation_plan.json"
    segment_plan_result = _run_command(
        [
            python_executable,
            str(convert_script),
            "segment-plan",
            "--markdown",
            str(long_markdown),
            "--output",
            str(segmentation_plan),
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

    segments_dir = work_root / "segments"
    split_plan = work_root / "split_plan.json"
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
    metadata_lint_md = work_root / "metadata_lint.md"
    metadata_merge_md = work_root / "metadata_merge.md"
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
            "--report-md",
            str(metadata_lint_md),
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
            "--report-md",
            str(metadata_merge_md),
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
    for path in (metadata_template, metadata_merged, metadata_lint_md, metadata_merge_md):
        if path.exists():
            produced.append(path)

    tagset_template = work_root / "tagset.template.json"
    tagset_csv = work_root / "tagset.csv"
    tagset_report_md = work_root / "tagset_report.md"
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
            "--report-md",
            str(tagset_report_md),
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
    for path in (tagset_template, tagset_csv, tagset_report_md):
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

    inspect_handoff_report = work_root / "handoff_inspection.md"
    inspect_handoff_result = _run_command(
        [
            python_executable,
            str(build_script),
            "inspect-handoff",
            "--handoff",
            str(handoff_dir),
            "--report-md",
            str(inspect_handoff_report),
            "--json",
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "kb-build inspect rich handoff", inspect_handoff_result, required_output='"schema": "ragflow_handoff_inspection_v1"')
    if inspect_handoff_report.exists():
        produced.append(inspect_handoff_report)

    profile_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "profile.py")
    profile_lint_result = _run_command(
        [
            python_executable,
            str(profile_script),
            "lint",
            "--profile",
            str(profile),
            "--report-md",
            str(work_root / "profile_lint.md"),
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
    profile_lint_md = work_root / "profile_lint.md"
    if profile_lint_md.exists():
        produced.append(profile_lint_md)

    recommended_profile = work_root / "recommended_profile.json"
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
    if recommended_profile.exists():
        produced.append(recommended_profile)

    validate_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "validate.py")
    benchmark_manifest = work_root / "benchmark_kb_manifest.json"
    benchmark_queries = work_root / "benchmark_queries.json"
    benchmark_qrels = work_root / "benchmark_qrels.json"
    benchmark_qa = work_root / "benchmark_qa.json"
    benchmark_gate = work_root / "benchmark_gate.json"
    benchmark_chunk_input = work_root / "benchmark_chunks.json"
    benchmark_chunk_snapshot = work_root / "benchmark_chunk_snapshot.json"
    benchmark_chunk_snapshot_md = work_root / "benchmark_chunk_snapshot.md"
    benchmark_report_json = work_root / "benchmark_report.json"
    benchmark_report_md = work_root / "benchmark_report.md"
    baseline_benchmark_report_json = work_root / "baseline_benchmark_report.json"
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
    benchmark_chunk_content = "Consumer Acceptance can run without repository source context."
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
                        "content_with_weight": "Consumer Acceptance can run without repository source context.",
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
    for path in (benchmark_report_json, benchmark_report_md):
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
    qa_validate_md = work_root / "qa_validate.md"
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
        benchmark_import_md,
        qa_validate_md,
        benchmark_preflight_md,
        benchmark_sample_md,
        benchmark_summary_md,
        benchmark_gate_md,
        benchmark_trend_md,
        benchmark_delta_md,
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

    cleanup_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "cleanup.py")
    cleanup_help = _run_command([python_executable, str(cleanup_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build cleanup help",
        cleanup_help,
        required_output="Preview or execute cleanup",
    )

    diagnose_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "diagnose.py")
    diagnose_help = _run_command([python_executable, str(diagnose_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build diagnose help",
        diagnose_help,
        required_output="Diagnose a RAGFlow KB manifest",
    )

    probe_script = _skill_path(extract_dir, "ragflow-kb-build", "scripts", "probe.py")
    probe_help = _run_command([python_executable, str(probe_script), "--help"], cwd=work_root, env=env)
    _record_command_check(
        checks,
        "kb-build probe help",
        probe_help,
        required_output="Probe RAGFlow API compatibility",
    )

    query_script = _skill_path(extract_dir, "ragflow-query", "scripts", "query.py")
    query_help = _run_command([python_executable, str(query_script), "--help"], cwd=work_root, env=env)
    _record_command_check(checks, "query top-level help", query_help, required_output="Portable RAGFlow query CLI")

    ask_help = _run_command([python_executable, str(query_script), "ask", "--help"], cwd=work_root, env=env)
    _record_command_check(checks, "query host-assisted help", ask_help, required_output="--host-assisted")

    routing_config = work_root / "routing_config.json"
    route_queries = work_root / "route_queries.json"
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
                    }
                ]
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
    route_test_report = work_root / "route_test.md"
    route_test = _run_command(
        [
            python_executable,
            str(query_script),
            "route-test",
            "--routing-config",
            str(routing_config),
            "--queries",
            str(route_queries),
            "--report-md",
            str(route_test_report),
        ],
        cwd=work_root,
        env=env,
    )
    _record_command_check(checks, "query route-test", route_test, required_output='"accuracy": 1.0')
    if route_test_report.exists():
        produced.append(route_test_report)

    query_output = work_root / "query_output.json"
    citation_audit_json = work_root / "citation_audit.json"
    citation_audit_md = work_root / "citation_audit.md"
    query_diagnostic_json = work_root / "query_diagnostic.json"
    query_diagnostic_md = work_root / "query_diagnostic.md"
    query_output.write_text(
        json.dumps(
            {
                "ok": True,
                "question": "What can run without repository source context?",
                "chunks": [
                    {
                        "content": "This release artifact can run without repository source context.",
                        "similarity": 0.9,
                        "document_name": "sample.md",
                        "dataset_id": "ds-consumer-acceptance",
                    }
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

    if live_build:
        live_build_checks, live_build_produced = _run_live_build_check(
            extract_dir=extract_dir,
            work_root=work_root,
            python_executable=python_executable,
            env_map=os.environ if env is None else env,
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
                )
                payload["artifacts_retained"] = False

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
