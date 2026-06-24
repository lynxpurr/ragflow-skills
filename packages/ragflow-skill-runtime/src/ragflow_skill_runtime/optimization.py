"""Offline optimization planning helpers for RAGFlow KB profiles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .benchmark_governance import BenchmarkGovernanceError, preflight_benchmark_dataset, resolve_benchmark_artifacts
from .config import ConfigError, read_config_file
from .profiles import ChunkProfile, ProfileError, lint_profile, load_profile, recommend_profile


CANDIDATE_PROFILE_SET_SCHEMA = "ragflow_candidate_profile_set_v1"
OPTIMIZATION_PLAN_SCHEMA = "ragflow_optimization_plan_v1"
PROFILE_FILE_SUFFIXES = {".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class OptimizationIssue:
    severity: str
    code: str
    message: str
    field: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class _CandidateProfile:
    profile: ChunkProfile
    source: dict[str, Any]
    path: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"profile set not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"profile set is not valid JSON: {source}") from exc
    else:
        try:
            data = read_config_file(source)
        except ConfigError as exc:
            raise ProfileError(str(exc)) from exc
    if not isinstance(data, dict):
        raise ProfileError(f"profile set must be an object: {source}")
    return data


def _issue_counts(issues: Iterable[OptimizationIssue]) -> dict[str, int]:
    items = list(issues)
    return {
        "errors": sum(1 for issue in items if issue.severity == "error"),
        "warnings": sum(1 for issue in items if issue.severity == "warning"),
        "infos": sum(1 for issue in items if issue.severity == "info"),
    }


def _ok(issues: Iterable[OptimizationIssue]) -> bool:
    return not any(issue.severity == "error" for issue in issues)


def _as_path(path: str | Path, *, base_dir: Path | None = None) -> Path:
    value = Path(path)
    if value.is_absolute() or base_dir is None:
        return value
    return base_dir / value


def _profile_files_in_dir(path: str | Path) -> list[Path]:
    root = Path(path)
    if not root.exists():
        raise ProfileError(f"profile dir not found: {root}")
    if not root.is_dir():
        raise ProfileError(f"profile dir is not a directory: {root}")
    files = sorted(item for item in root.iterdir() if item.is_file() and item.suffix.lower() in PROFILE_FILE_SUFFIXES)
    if not files:
        raise ProfileError(f"profile dir does not contain JSON/YAML profiles: {root}")
    return files


def _parse_recommendation_spec(value: str | Mapping[str, Any]) -> dict[str, str | None]:
    if isinstance(value, Mapping):
        language = str(value.get("language") or "auto")
        doc_type = str(value.get("doc_type") or value.get("document_type") or "general")
        profile_id = value.get("profile_id") or value.get("id")
        return {
            "language": language,
            "doc_type": doc_type,
            "profile_id": str(profile_id) if profile_id else None,
        }
    text = str(value).strip()
    if not text:
        raise ProfileError("recommendation spec must not be empty")
    if ":" in text:
        parts = [part.strip() for part in text.split(":")]
    elif "/" in text:
        parts = [part.strip() for part in text.split("/")]
    elif "," in text:
        parts = [part.strip() for part in text.split(",")]
    else:
        parts = ["auto", text]
    if len(parts) not in {2, 3} or not parts[0] or not parts[1]:
        raise ProfileError("recommendation spec must be language:doc_type or language:doc_type:profile_id")
    return {"language": parts[0], "doc_type": parts[1], "profile_id": parts[2] if len(parts) == 3 and parts[2] else None}


def _candidate_from_profile(profile: ChunkProfile, *, source: Mapping[str, Any], path: str | None = None) -> _CandidateProfile:
    return _CandidateProfile(profile=profile, source=dict(source), path=path)


def _load_profile_set_file(path: str | Path) -> tuple[list[_CandidateProfile], list[OptimizationIssue]]:
    profile_set_path = Path(path)
    payload = _read_mapping(profile_set_path)
    issues: list[OptimizationIssue] = []
    if payload.get("schema") not in {None, CANDIDATE_PROFILE_SET_SCHEMA}:
        issues.append(
            OptimizationIssue(
                "error",
                "profile_set_schema_invalid",
                f"profile set schema must be {CANDIDATE_PROFILE_SET_SCHEMA}",
                "schema",
            )
        )
    base_dir = profile_set_path.parent
    candidates: list[_CandidateProfile] = []

    for index, raw_profile in enumerate(payload.get("profiles", []) if isinstance(payload.get("profiles", []), list) else []):
        if isinstance(raw_profile, str):
            profile_path = _as_path(raw_profile, base_dir=base_dir)
            candidates.append(
                _candidate_from_profile(
                    load_profile(profile_path),
                    source={"type": "profile_set_file", "path": str(profile_set_path), "entry": raw_profile},
                    path=str(profile_path),
                )
            )
        elif isinstance(raw_profile, Mapping):
            profile = ChunkProfile.from_dict(raw_profile)
            candidates.append(
                _candidate_from_profile(
                    profile,
                    source={"type": "profile_set_inline", "path": str(profile_set_path), "index": index},
                )
            )
        else:
            issues.append(OptimizationIssue("error", "profile_set_entry_invalid", "profiles entries must be objects or paths", f"profiles[{index}]"))

    for raw_path in payload.get("profile_paths", []) if isinstance(payload.get("profile_paths", []), list) else []:
        profile_path = _as_path(str(raw_path), base_dir=base_dir)
        candidates.append(
            _candidate_from_profile(
                load_profile(profile_path),
                source={"type": "profile_set_path", "path": str(profile_set_path)},
                path=str(profile_path),
            )
        )

    for raw_dir in payload.get("profile_dirs", []) if isinstance(payload.get("profile_dirs", []), list) else []:
        profile_dir = _as_path(str(raw_dir), base_dir=base_dir)
        for profile_path in _profile_files_in_dir(profile_dir):
            candidates.append(
                _candidate_from_profile(
                    load_profile(profile_path),
                    source={"type": "profile_set_dir", "path": str(profile_set_path), "dir": str(profile_dir)},
                    path=str(profile_path),
                )
            )

    for index, raw_recommendation in enumerate(
        payload.get("recommendations", []) if isinstance(payload.get("recommendations", []), list) else []
    ):
        spec = _parse_recommendation_spec(raw_recommendation)
        recommendation = recommend_profile(
            language=spec["language"] or "auto",
            doc_type=spec["doc_type"] or "general",
            profile_id=spec["profile_id"],
        )
        candidates.append(
            _candidate_from_profile(
                recommendation.profile,
                source={
                    "type": "profile_set_recommendation",
                    "path": str(profile_set_path),
                    "index": index,
                    "language": recommendation.language,
                    "doc_type": recommendation.doc_type,
                },
            )
        )

    return candidates, issues


def load_candidate_profile_set(
    *,
    profile_paths: Iterable[str | Path] | None = None,
    profile_dirs: Iterable[str | Path] | None = None,
    profile_set_paths: Iterable[str | Path] | None = None,
    recommendations: Iterable[str | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load candidate profiles from files, directories, profile sets, and recommendations."""

    candidates: list[_CandidateProfile] = []
    issues: list[OptimizationIssue] = []

    for profile_set_path in profile_set_paths or []:
        loaded, loaded_issues = _load_profile_set_file(profile_set_path)
        candidates.extend(loaded)
        issues.extend(loaded_issues)

    for profile_path_value in profile_paths or []:
        profile_path = Path(profile_path_value)
        candidates.append(
            _candidate_from_profile(
                load_profile(profile_path),
                source={"type": "file"},
                path=str(profile_path),
            )
        )

    for profile_dir_value in profile_dirs or []:
        for profile_path in _profile_files_in_dir(profile_dir_value):
            candidates.append(
                _candidate_from_profile(
                    load_profile(profile_path),
                    source={"type": "directory", "dir": str(profile_dir_value)},
                    path=str(profile_path),
                )
            )

    for raw_recommendation in recommendations or []:
        spec = _parse_recommendation_spec(raw_recommendation)
        recommendation = recommend_profile(
            language=spec["language"] or "auto",
            doc_type=spec["doc_type"] or "general",
            profile_id=spec["profile_id"],
        )
        candidates.append(
            _candidate_from_profile(
                recommendation.profile,
                source={"type": "recommendation", "language": recommendation.language, "doc_type": recommendation.doc_type},
            )
        )

    if not candidates:
        issues.append(
            OptimizationIssue(
                "error",
                "candidate_profiles_missing",
                "provide at least one --profile, --profile-dir, --profile-set, or --recommendation",
                "candidates",
            )
        )

    seen: dict[str, int] = {}
    serialized_candidates = []
    for index, candidate in enumerate(candidates):
        lint = lint_profile(candidate.profile)
        profile_id = candidate.profile.profile_id
        if profile_id in seen:
            issues.append(
                OptimizationIssue(
                    "error",
                    "candidate_profile_duplicate_id",
                    "candidate profile ids must be unique",
                    f"candidates[{index}].profile_id",
                    "Rename one profile_id before running optimization experiments.",
                )
            )
        seen[profile_id] = index
        serialized_candidates.append(
            {
                "profile_id": profile_id,
                "path": candidate.path,
                "source": candidate.source,
                "profile": candidate.profile.to_manifest_dict(),
                "lint": lint.to_dict(),
            }
        )

    summary = _issue_counts(issues)
    return {
        "ok": _ok(issues),
        "schema": CANDIDATE_PROFILE_SET_SCHEMA,
        "summary": {
            **summary,
            "candidate_count": len(serialized_candidates),
        },
        "candidates": serialized_candidates,
        "issues": [issue.to_dict() for issue in issues],
    }


def _slug(value: str, *, default: str = "value") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-._:")
    return slug or default


def _run_id(value: str | None, *, kb_name: str, profile_ids: Iterable[str], document_paths: Iterable[str | Path]) -> str:
    if value:
        return _slug(value, default="run")
    digest = hashlib.sha256()
    digest.update(kb_name.encode("utf-8"))
    for profile_id in sorted(profile_ids):
        digest.update(profile_id.encode("utf-8"))
    for document_path in sorted(str(path) for path in document_paths):
        digest.update(document_path.encode("utf-8"))
    return digest.hexdigest()[:10]


def _disposable_kb_name(base_name: str, *, run_id: str, profile_id: str) -> str:
    base = _slug(base_name, default="kb")
    profile = _slug(profile_id, default="profile")
    name = f"{base}__opt__{run_id}__{profile}"
    if len(name) <= 120:
        return name
    suffix = f"__opt__{run_id}__{profile[:40]}"
    return f"{base[: max(12, 120 - len(suffix))]}{suffix}"[:120]


def _path_or_none(path: str | Path | None) -> str | None:
    return str(path) if path else None


def _existing_optional_path(path: str | Path | None, *, field: str, issues: list[OptimizationIssue]) -> None:
    if path and not Path(path).exists():
        issues.append(OptimizationIssue("error", "artifact_not_found", f"artifact not found: {path}", field))


def _candidate_artifacts(artifact_dir: str | Path, profile_id: str) -> dict[str, str]:
    candidate_dir = Path(artifact_dir) / _slug(profile_id, default="profile")
    return {
        "candidate_dir": str(candidate_dir),
        "profile": str(candidate_dir / "profile.json"),
        "kb_manifest": str(candidate_dir / "kb_manifest.json"),
        "validation_report": str(candidate_dir / "validation_report.json"),
        "validation_report_md": str(candidate_dir / "validation_report.md"),
        "diagnostic_report": str(candidate_dir / "diagnostic_report.json"),
        "cleanup_plan": str(candidate_dir / "cleanup_plan.json"),
    }


def _build_command(
    *,
    doc_manifest_path: str | Path | None,
    input_path: str | Path | None,
    kb_name: str,
    profile_path: str,
    kb_manifest_path: str,
    metadata_path: str | Path | None,
) -> list[str]:
    command = ["python3", "scripts/build.py"]
    if doc_manifest_path:
        command.extend(["--doc-manifest", str(doc_manifest_path)])
    elif input_path:
        command.extend(["--input", str(input_path)])
    command.extend(["--kb-name", kb_name, "--profile", profile_path, "--output", kb_manifest_path])
    if metadata_path:
        command.extend(["--metadata", str(metadata_path)])
    return command


def _validate_command(
    *,
    kb_manifest_path: str,
    queries_path: Path | None,
    qrels_path: Path | None,
    report_path: str,
    report_md_path: str,
    metadata_path: str | Path | None,
    gate_config_path: str | Path | None,
    baseline_report_path: str | Path | None,
    chunk_snapshot_path: str | Path | None,
    top_k: int,
    metric_cutoff: int | None,
) -> list[str]:
    command = [
        "python3",
        "scripts/validate.py",
        "--kb-manifest",
        kb_manifest_path,
        "--level",
        "benchmark",
        "--top-k",
        str(top_k),
        "--report-json",
        report_path,
        "--report-md",
        report_md_path,
    ]
    if queries_path:
        command.extend(["--queries", str(queries_path)])
    if qrels_path:
        command.extend(["--qrels", str(qrels_path)])
    if metadata_path:
        command.extend(["--metadata", str(metadata_path)])
    if gate_config_path:
        command.extend(["--gate-config", str(gate_config_path)])
    if baseline_report_path:
        command.extend(["--baseline-report", str(baseline_report_path)])
    if chunk_snapshot_path:
        command.extend(["--chunk-snapshot", str(chunk_snapshot_path)])
    if metric_cutoff:
        command.extend(["--metric-cutoff", str(metric_cutoff)])
    return command


def create_optimization_plan(
    *,
    kb_name: str,
    document_paths: Iterable[str | Path],
    input_path: str | Path | None = None,
    doc_manifest_path: str | Path | None = None,
    profile_paths: Iterable[str | Path] | None = None,
    profile_dirs: Iterable[str | Path] | None = None,
    profile_set_paths: Iterable[str | Path] | None = None,
    recommendations: Iterable[str | Mapping[str, Any]] | None = None,
    benchmark_manifest_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    qrels_path: str | Path | None = None,
    qa_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    tagset_path: str | Path | None = None,
    chunk_snapshot_path: str | Path | None = None,
    gate_config_path: str | Path | None = None,
    baseline_report_path: str | Path | None = None,
    artifact_dir: str | Path = "optimization-artifacts",
    run_id: str | None = None,
    top_k: int = 3,
    metric_cutoff: int | None = None,
) -> dict[str, Any]:
    """Create a non-mutating optimization plan for profile experiments."""

    documents = [str(path) for path in document_paths]
    issues: list[OptimizationIssue] = []
    if not documents:
        issues.append(OptimizationIssue("error", "documents_missing", "optimization planning requires at least one Markdown document", "documents"))
    if not kb_name.strip():
        issues.append(OptimizationIssue("error", "kb_name_missing", "kb_name is required", "kb_name"))
    if top_k <= 0:
        issues.append(OptimizationIssue("error", "top_k_invalid", "top_k must be positive", "top_k"))
    if metric_cutoff is not None and metric_cutoff <= 0:
        issues.append(OptimizationIssue("error", "metric_cutoff_invalid", "metric_cutoff must be positive", "metric_cutoff"))

    candidate_set = load_candidate_profile_set(
        profile_paths=profile_paths,
        profile_dirs=profile_dirs,
        profile_set_paths=profile_set_paths,
        recommendations=recommendations,
    )
    for raw_issue in candidate_set.get("issues", []):
        if isinstance(raw_issue, Mapping):
            issues.append(
                OptimizationIssue(
                    str(raw_issue.get("severity", "warning")),
                    f"candidate_{raw_issue.get('code', 'issue')}",
                    str(raw_issue.get("message", "")),
                    raw_issue.get("field") if isinstance(raw_issue.get("field"), str) else None,
                    raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
                )
            )

    artifacts: dict[str, Path | None]
    try:
        artifacts = resolve_benchmark_artifacts(
            manifest_path=benchmark_manifest_path,
            queries_path=queries_path,
            qrels_path=qrels_path,
            qa_path=qa_path,
        )
        preflight = preflight_benchmark_dataset(
            manifest_path=benchmark_manifest_path,
            queries_path=queries_path,
            qrels_path=qrels_path,
            qa_path=qa_path,
            chunk_snapshot_path=chunk_snapshot_path,
            gate_config_path=gate_config_path,
        )
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        artifacts = {"queries": Path(queries_path) if queries_path else None, "qrels": Path(qrels_path) if qrels_path else None, "qa": Path(qa_path) if qa_path else None}
        preflight = {"ok": False, "summary": {"errors": 1, "warnings": 0, "infos": 0}, "issues": []}
        issues.append(OptimizationIssue("error", "benchmark_preflight_failed", str(exc), "benchmark"))
    else:
        for raw_issue in preflight.get("issues", []):
            if isinstance(raw_issue, Mapping):
                issues.append(
                    OptimizationIssue(
                        str(raw_issue.get("severity", "warning")),
                        f"benchmark_{raw_issue.get('code', 'issue')}",
                        str(raw_issue.get("message", "")),
                        raw_issue.get("field") if isinstance(raw_issue.get("field"), str) else None,
                        raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
                    )
                )

    _existing_optional_path(metadata_path, field="metadata", issues=issues)
    _existing_optional_path(tagset_path, field="tagset", issues=issues)
    _existing_optional_path(baseline_report_path, field="baseline_report", issues=issues)

    candidate_profile_ids = [
        str(candidate.get("profile_id"))
        for candidate in candidate_set.get("candidates", [])
        if isinstance(candidate, Mapping) and candidate.get("profile_id")
    ]
    actual_run_id = _run_id(run_id, kb_name=kb_name, profile_ids=candidate_profile_ids, document_paths=documents)

    disposable_names: dict[str, str] = {}
    plan_candidates = []
    for index, candidate in enumerate(candidate_set.get("candidates", [])):
        if not isinstance(candidate, Mapping):
            continue
        profile_id = str(candidate.get("profile_id"))
        disposable_name = _disposable_kb_name(kb_name, run_id=actual_run_id, profile_id=profile_id)
        if disposable_name in disposable_names:
            issues.append(
                OptimizationIssue(
                    "error",
                    "disposable_kb_name_collision",
                    "candidate disposable KB names must be unique",
                    f"candidates[{index}].disposable_kb_name",
                    "Use unique profile_id values or pass a distinct --run-id.",
                )
            )
        disposable_names[disposable_name] = profile_id

        lint = candidate.get("lint") if isinstance(candidate.get("lint"), Mapping) else {}
        for raw_issue in lint.get("issues", []) if isinstance(lint.get("issues"), list) else []:
            if not isinstance(raw_issue, Mapping):
                continue
            issues.append(
                OptimizationIssue(
                    str(raw_issue.get("severity", "warning")),
                    f"profile_{raw_issue.get('code', 'issue')}",
                    str(raw_issue.get("message", "")),
                    f"candidates[{index}].{raw_issue.get('field')}" if isinstance(raw_issue.get("field"), str) else f"candidates[{index}]",
                    raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
                )
            )

        candidate_artifacts = _candidate_artifacts(artifact_dir, profile_id)
        profile_path = str(candidate.get("path") or candidate_artifacts["profile"])
        build_command = _build_command(
            doc_manifest_path=doc_manifest_path,
            input_path=input_path,
            kb_name=disposable_name,
            profile_path=profile_path,
            kb_manifest_path=candidate_artifacts["kb_manifest"],
            metadata_path=metadata_path,
        )
        validate_command = _validate_command(
            kb_manifest_path=candidate_artifacts["kb_manifest"],
            queries_path=artifacts.get("queries"),
            qrels_path=artifacts.get("qrels"),
            report_path=candidate_artifacts["validation_report"],
            report_md_path=candidate_artifacts["validation_report_md"],
            metadata_path=metadata_path,
            gate_config_path=gate_config_path,
            baseline_report_path=baseline_report_path,
            chunk_snapshot_path=chunk_snapshot_path,
            top_k=top_k,
            metric_cutoff=metric_cutoff,
        )
        plan_candidates.append(
            {
                **candidate,
                "disposable_kb_name": disposable_name,
                "artifacts": candidate_artifacts,
                "commands": {
                    "write_generated_profile": None if candidate.get("path") else ["write-json", candidate_artifacts["profile"]],
                    "build": build_command,
                    "validate": validate_command,
                    "diagnose": [
                        "python3",
                        "scripts/diagnose.py",
                        "--kb-manifest",
                        candidate_artifacts["kb_manifest"],
                        "--report-json",
                        candidate_artifacts["diagnostic_report"],
                    ],
                    "cleanup_preview": [
                        "python3",
                        "scripts/cleanup.py",
                        "--kb-manifest",
                        candidate_artifacts["kb_manifest"],
                        "--output",
                        candidate_artifacts["cleanup_plan"],
                    ],
                },
            }
        )

    issue_summary = _issue_counts(issues)
    return {
        "ok": _ok(issues),
        "schema": OPTIMIZATION_PLAN_SCHEMA,
        "created_at": _now(),
        "mode": "plan-only",
        "mutation_allowed": False,
        "run_id": actual_run_id,
        "base_kb_name": kb_name,
        "inputs": {
            "input": _path_or_none(input_path),
            "doc_manifest": _path_or_none(doc_manifest_path),
            "documents": documents,
            "benchmark": {
                "manifest": _path_or_none(benchmark_manifest_path),
                "queries": str(artifacts.get("queries")) if artifacts.get("queries") else None,
                "qrels": str(artifacts.get("qrels")) if artifacts.get("qrels") else None,
                "qa": str(artifacts.get("qa")) if artifacts.get("qa") else None,
                "preflight": preflight,
            },
            "metadata": _path_or_none(metadata_path),
            "tagset": _path_or_none(tagset_path),
            "chunk_snapshot": _path_or_none(chunk_snapshot_path),
            "gate_config": _path_or_none(gate_config_path),
            "baseline_report": _path_or_none(baseline_report_path),
        },
        "summary": {
            **issue_summary,
            "candidate_count": len(plan_candidates),
            "document_count": len(documents),
            "planned_experiment_count": len(plan_candidates),
            "mutation_steps": 0,
        },
        "candidates": plan_candidates,
        "steps": [
            {
                "order": 1,
                "name": "preflight_inputs",
                "mutation": False,
                "status": "planned",
            },
            {
                "order": 2,
                "name": "build_disposable_kbs",
                "mutation": True,
                "requires_execute": True,
                "status": "not_run_in_plan_only",
            },
            {
                "order": 3,
                "name": "run_benchmark_validation",
                "mutation": False,
                "status": "not_run_in_plan_only",
            },
            {
                "order": 4,
                "name": "diagnose_failed_or_zero_chunk_candidates",
                "mutation": False,
                "status": "conditional",
            },
            {
                "order": 5,
                "name": "compare_profiles_and_select_best",
                "mutation": False,
                "status": "not_run_in_plan_only",
            },
            {
                "order": 6,
                "name": "cleanup_disposable_kbs",
                "mutation": True,
                "requires_execute": True,
                "status": "not_run_in_plan_only",
            },
        ],
        "issues": [issue.to_dict() for issue in issues],
    }


def render_optimization_plan_markdown(plan: Mapping[str, Any]) -> str:
    """Render a compact Markdown view of an optimization plan."""

    summary = plan.get("summary", {}) if isinstance(plan.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Optimization Plan",
        "",
        f"- Status: `{'passed' if plan.get('ok') else 'failed'}`",
        f"- Mode: `{plan.get('mode', 'plan-only')}`",
        f"- Mutates RAGFlow: `{str(bool(plan.get('mutation_allowed'))).lower()}`",
        f"- Run ID: `{plan.get('run_id')}`",
        f"- Base KB name: `{plan.get('base_kb_name')}`",
        f"- Candidates: `{summary.get('candidate_count', 0)}`",
        f"- Documents: `{summary.get('document_count', 0)}`",
        f"- Errors: `{summary.get('errors', 0)}`",
        f"- Warnings: `{summary.get('warnings', 0)}`",
        "",
        "## Candidates",
        "",
        "| profile | source | disposable KB | lint errors | lint warnings |",
        "|---|---|---|---:|---:|",
    ]
    for candidate in plan.get("candidates", []) if isinstance(plan.get("candidates"), list) else []:
        if not isinstance(candidate, Mapping):
            continue
        lint = candidate.get("lint") if isinstance(candidate.get("lint"), Mapping) else {}
        lint_summary = lint.get("summary") if isinstance(lint.get("summary"), Mapping) else {}
        source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
        source_label = source.get("type", "unknown")
        lines.append(
            f"| `{candidate.get('profile_id')}` | {source_label} | `{candidate.get('disposable_kb_name')}` | "
            f"{lint_summary.get('errors', 0)} | {lint_summary.get('warnings', 0)} |"
        )
    lines.extend(["", "## Issues", "", "| severity | code | field | message |", "|---|---|---|---|"])
    for issue in plan.get("issues", []) if isinstance(plan.get("issues"), list) else []:
        if not isinstance(issue, Mapping):
            continue
        lines.append(
            f"| {issue.get('severity')} | `{issue.get('code')}` | {issue.get('field', '-')} | {issue.get('message')} |"
        )
    lines.append("")
    return "\n".join(lines)
