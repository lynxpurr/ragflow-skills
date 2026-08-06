#!/usr/bin/env python3
"""Profile lint, explain, recommend, and compare utilities."""

from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from typing import Any, Mapping


def bootstrap_runtime() -> None:
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parents[3] / "packages/ragflow-skill-runtime/src",
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
    compare_validation_reports,
    decide_profile_from_reports,
    explain_profile,
    lint_profile,
    load_enrichment_experiment_matrix,
    load_profile,
    make_bounded_enrichment_experiment_matrix,
    plan_enrichment_experiments,
    recommend_profile,
    render_enrichment_experiment_markdown,
    render_profile_compare_markdown,
    render_profile_decision_markdown,
    render_profile_lint_markdown,
    summarize_retrieval_hints,
)
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402
from _report_redaction import sanitize_cli_report  # noqa: E402


ENRICHMENT_EXPERIMENT_CHECKPOINT_SCHEMA = "ragflow_enrichment_experiment_checkpoint_v1"


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _write_json(path: str | None, data: Any) -> None:
    if not path:
        return
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_file(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"file is not valid JSON: {source}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hash_map(paths: list[str | None]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        source = Path(path)
        if source.exists() and source.is_file():
            hashes[str(source)] = _sha256_file(source)
    return hashes


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _experiment_request_hash(
    *,
    base_profile: Mapping[str, Any],
    matrix: Mapping[str, Any],
    profile_id_prefix: str | None,
    max_experiments: int,
    fail_on_duplicate_effective_profiles: bool,
) -> str:
    return _stable_digest(
        {
            "base_profile": dict(base_profile),
            "matrix": dict(matrix),
            "profile_id_prefix": profile_id_prefix,
            "max_experiments": max_experiments,
            "fail_on_duplicate_effective_profiles": fail_on_duplicate_effective_profiles,
        }
    )


def _read_experiment_checkpoint(path: Path) -> dict[str, Any]:
    payload = _read_json_file(path)
    if not isinstance(payload, Mapping):
        raise ProfileError("profile experiment checkpoint must be a JSON object")
    if payload.get("schema") != ENRICHMENT_EXPERIMENT_CHECKPOINT_SCHEMA:
        raise ProfileError(f"profile experiment checkpoint schema must be {ENRICHMENT_EXPERIMENT_CHECKPOINT_SCHEMA}")
    processed = payload.get("processed_profile_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise ProfileError("profile experiment checkpoint processed_profile_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ProfileError("profile experiment checkpoint source_hashes must be an object")
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ProfileError("profile experiment checkpoint parameters must be an object")
    return dict(payload)


def _validate_experiment_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
    request_hash: str,
    candidate_set: str | None,
    profile_id_prefix: str | None,
    max_experiments: int,
    fail_on_duplicate_effective_profiles: bool,
) -> None:
    if dict(checkpoint.get("source_hashes") or {}) != dict(source_hashes):
        raise ProfileError("profile experiment checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("request_hash") or "") != request_hash:
        raise ProfileError("profile experiment checkpoint request hash does not match current request")
    expected_candidate_set = str(Path(candidate_set)) if candidate_set else None
    if (checkpoint.get("candidate_set") or None) != expected_candidate_set:
        raise ProfileError("profile experiment checkpoint candidate_set does not match current output")
    expected_parameters = {
        "profile_id_prefix": profile_id_prefix,
        "max_experiments": max_experiments,
        "fail_on_duplicate_effective_profiles": fail_on_duplicate_effective_profiles,
    }
    if dict(checkpoint.get("parameters") or {}) != expected_parameters:
        raise ProfileError("profile experiment checkpoint parameters do not match current request")


def _write_experiment_checkpoint(
    *,
    checkpoint_path: str | Path,
    source_hashes: Mapping[str, str],
    request_hash: str,
    candidate_set: str | None,
    profile_id_prefix: str | None,
    max_experiments: int,
    fail_on_duplicate_effective_profiles: bool,
    processed_profile_ids: list[str],
    total_profile_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_profile_ids))
    payload = {
        "schema": ENRICHMENT_EXPERIMENT_CHECKPOINT_SCHEMA,
        "created_at": created_at or _utc_now(),
        "updated_at": _utc_now(),
        "source_hashes": dict(source_hashes),
        "request_hash": request_hash,
        "candidate_set": str(Path(candidate_set)) if candidate_set else None,
        "parameters": {
            "profile_id_prefix": profile_id_prefix,
            "max_experiments": max_experiments,
            "fail_on_duplicate_effective_profiles": fail_on_duplicate_effective_profiles,
        },
        "processed_profile_ids": processed,
        "summary": {
            "processed_profile_count": len(processed),
            "total_profile_count": total_profile_count,
            "remaining_profile_count": max(total_profile_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    _write_json(str(checkpoint_path), payload)
    return payload


def _apply_experiment_checkpoint(
    payload: dict[str, Any],
    *,
    checkpoint_path: str | None,
    resume: bool,
    batch_size: int | None,
    source_hashes: Mapping[str, str],
    request_hash: str,
    candidate_set: str | None,
    profile_id_prefix: str | None,
    max_experiments: int,
    fail_on_duplicate_effective_profiles: bool,
) -> dict[str, Any]:
    experiments = payload.get("experiments") if isinstance(payload.get("experiments"), list) else []
    profile_ids = [str(item.get("profile_id")) for item in experiments if isinstance(item, Mapping) and item.get("profile_id")]
    processed_profile_ids: list[str] = []
    checkpoint_created_at: str | None = None

    if checkpoint_path and resume:
        checkpoint = _read_experiment_checkpoint(Path(checkpoint_path))
        _validate_experiment_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            request_hash=request_hash,
            candidate_set=candidate_set,
            profile_id_prefix=profile_id_prefix,
            max_experiments=max_experiments,
            fail_on_duplicate_effective_profiles=fail_on_duplicate_effective_profiles,
        )
        processed_profile_ids = list(checkpoint.get("processed_profile_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    unknown_processed = sorted(set(processed_profile_ids) - set(profile_ids))
    if unknown_processed:
        raise ProfileError(
            "profile experiment checkpoint contains profile ids that are not present in current matrix: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_profile_ids)
    remaining_profile_ids = [profile_id for profile_id in profile_ids if profile_id not in processed_set]
    next_profile_ids = remaining_profile_ids if batch_size is None else remaining_profile_ids[:batch_size]
    selected_profile_ids = set(processed_profile_ids) | set(next_profile_ids)
    completed = bool(payload.get("ok")) and len(selected_profile_ids) >= len(profile_ids)

    filtered_experiments = [
        item
        for item in experiments
        if isinstance(item, Mapping) and str(item.get("profile_id") or "") in selected_profile_ids
    ]
    candidate_profile_set = payload.get("candidate_profile_set") if isinstance(payload.get("candidate_profile_set"), Mapping) else {}
    candidate_profiles = candidate_profile_set.get("profiles") if isinstance(candidate_profile_set.get("profiles"), list) else []
    filtered_profiles = [
        item
        for item in candidate_profiles
        if isinstance(item, Mapping) and str(item.get("id") or item.get("profile_id") or "") in selected_profile_ids
    ]

    checkpoint_payload = None
    if checkpoint_path and payload.get("ok"):
        ordered_processed = [profile_id for profile_id in profile_ids if profile_id in selected_profile_ids]
        checkpoint_payload = _write_experiment_checkpoint(
            checkpoint_path=checkpoint_path,
            source_hashes=source_hashes,
            request_hash=request_hash,
            candidate_set=candidate_set,
            profile_id_prefix=profile_id_prefix,
            max_experiments=max_experiments,
            fail_on_duplicate_effective_profiles=fail_on_duplicate_effective_profiles,
            processed_profile_ids=ordered_processed,
            total_profile_count=len(profile_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    summary = dict(payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {})
    summary.update(
        {
            "candidate_profile_count": len(filtered_profiles),
            "completed": completed,
            "checkpoint_enabled": bool(checkpoint_path),
            "checkpoint_resume": bool(resume),
            "checkpoint_new_profile_count": len(next_profile_ids),
            "checkpoint_remaining_profile_count": max(len(profile_ids) - len(selected_profile_ids), 0),
        }
    )
    payload = dict(payload)
    payload["summary"] = summary
    payload["completed"] = completed
    payload["candidate_profile_set"] = {**dict(candidate_profile_set), "profiles": filtered_profiles}
    payload["experiments"] = filtered_experiments
    payload["checkpoint"] = {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "batch_size": batch_size,
        "processed_profile_count": len(selected_profile_ids),
        "new_profile_count": len(next_profile_ids),
        "remaining_profile_count": max(len(profile_ids) - len(selected_profile_ids), 0),
        "total_profile_count": len(profile_ids),
        "completed": completed,
        "next_profile_ids": list(next_profile_ids),
    }
    if checkpoint_payload:
        payload["checkpoint_payload"] = checkpoint_payload
    return payload


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _render_profile_lint_markdown_from_payload(payload: dict[str, Any]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Profile Lint Report",
        "",
        f"- Profile: `{profile.get('id', profile.get('profile_id', ''))}`",
        f"- Status: `{'passed' if payload.get('ok') else 'failed'}`",
        f"- Errors: `{_as_int(summary.get('errors'))}`",
        f"- Warnings: `{_as_int(summary.get('warnings'))}`",
        f"- Infos: `{_as_int(summary.get('infos'))}`",
        "",
        "| severity | code | field | message | recommendation |",
        "|---|---|---|---|---|",
    ]
    for issue in payload.get("issues", []) if isinstance(payload.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        lines.append(
            f"| {issue.get('severity', '')} | `{issue.get('code', '')}` | "
            f"{issue.get('field') or '-'} | {issue.get('message', '')} | "
            f"{issue.get('recommendation') or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_profile_compare_markdown_from_payload(payload: dict[str, Any]) -> str:
    lines = [
        "# RAGFlow Profile Compare Report",
        "",
        "| rank | path | score | pass_rate | hit_rate | mrr | ndcg@k | empty_rate | latency_ms | parse_ms | cost_usd | cost_per_query_usd | operational_cost |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    candidates = payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        lines.append(
            f"| {index} | `{item.get('path', '')}` | {_as_float(item.get('score')):.4f} | "
            f"{_as_float(metrics.get('pass_rate')):.4f} | {_as_float(metrics.get('hit_rate')):.4f} | "
            f"{_as_float(metrics.get('mrr')):.4f} | {_as_float(metrics.get('ndcg_at_k')):.4f} | "
            f"{_as_float(metrics.get('empty_result_rate')):.4f} | {_as_float(metrics.get('query_latency_ms')):.1f} | "
            f"{_as_float(metrics.get('parse_time_ms')):.1f} | {_as_float(metrics.get('estimated_cost_usd')):.6f} | "
            f"{_as_float(metrics.get('cost_per_query_usd')):.6f} | {_as_float(metrics.get('operational_cost_score')):.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_enrichment_experiment_markdown_from_payload(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# RAGFlow Enrichment Experiment Matrix",
        "",
        f"- Status: `{'passed' if payload.get('ok') else 'failed'}`",
        f"- Mutates RAGFlow: `false`",
        f"- Dimensions: `{_as_int(summary.get('dimension_count'))}`",
        f"- Candidate profiles: `{_as_int(summary.get('candidate_profile_count'))}`",
        f"- Warnings: `{_as_int(summary.get('warnings'))}`",
        "",
        "## Experiments",
        "",
        "| index | profile | settings | warnings |",
        "|---:|---|---|---:|",
    ]
    experiments = payload.get("experiments", []) if isinstance(payload.get("experiments"), list) else []
    for item in experiments:
        if not isinstance(item, dict):
            continue
        settings = json.dumps(item.get("settings", {}), ensure_ascii=False, sort_keys=True)
        risk_issues = item.get("risk_issues") if isinstance(item.get("risk_issues"), list) else []
        lines.append(f"| {item.get('index')} | `{item.get('profile_id', '')}` | `{settings}` | {len(risk_issues)} |")
    if payload.get("issues"):
        lines.extend(["", "## Issues", "", "| severity | code | field | message |", "|---|---|---|---|"])
        for issue in payload.get("issues", []) if isinstance(payload.get("issues"), list) else []:
            if isinstance(issue, dict):
                lines.append(
                    f"| {issue.get('severity', '')} | `{issue.get('code', '')}` | "
                    f"{issue.get('field', '-')} | {issue.get('message', '')} |"
                )
    lines.append("")
    return "\n".join(lines)


def _sanitize_profile_report(
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None] | None = None,
    output_paths: list[str | None] | None = None,
    context_json_paths: list[str | None] | None = None,
) -> dict[str, Any]:
    if not getattr(args, "redaction_report", None):
        return payload
    sanitized, redaction_report = sanitize_cli_report(
        payload,
        args,
        input_paths=input_paths,
        output_paths=output_paths,
        context_json_paths=context_json_paths,
    )
    _write_json(args.redaction_report, redaction_report)
    return sanitized


def _cmd_lint(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    report = lint_profile(profile)
    payload = report.to_dict()
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.profile],
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=[args.profile],
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_profile_lint_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_profile_lint_markdown(report))
    _dump_json(payload)
    if not report.ok:
        return 1
    if args.fail_on_warning and payload["summary"]["warnings"]:
        return 1
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    payload = explain_profile(load_profile(args.profile))
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.profile],
        output_paths=[args.report_json, args.redaction_report],
        context_json_paths=[args.profile],
    )
    _write_json(args.report_json, payload)
    _dump_json(payload)
    return 0 if payload["ok"] else 1


def _cmd_recommend(args: argparse.Namespace) -> int:
    retrieval_hints_summary = summarize_retrieval_hints(None)
    if args.retrieval_hints:
        retrieval_hints = _read_json_file(args.retrieval_hints)
        if not isinstance(retrieval_hints, Mapping):
            raise ProfileError("retrieval hints must be a JSON object")
        retrieval_hints_summary = summarize_retrieval_hints(retrieval_hints)
    recommendation = recommend_profile(
        language=args.language,
        doc_type=args.doc_type,
        profile_id=args.profile_id,
        retrieval_hints_summary=retrieval_hints_summary,
    )
    payload = recommendation.to_dict()
    _write_json(args.output, payload["profile"])
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.retrieval_hints],
        output_paths=[args.report_json, args.redaction_report],
    )
    _write_json(args.report_json, payload)
    _dump_json(payload)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    payload = compare_validation_reports(args.report)
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=list(args.report),
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=list(args.report),
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_profile_compare_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_profile_compare_markdown(payload))
    _dump_json(payload)
    return 0


def _cmd_decision(args: argparse.Namespace) -> int:
    payload = decide_profile_from_reports(
        args.report,
        minimum_query_count=args.minimum_query_count,
        minimum_profile_count=args.minimum_profile_count,
        minimum_score_delta=args.minimum_score_delta,
    )
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=list(args.report),
        output_paths=[args.report_json, args.report_md, args.redaction_report],
        context_json_paths=list(args.report),
    )
    _write_json(args.report_json, payload)
    _write_text(args.report_md, render_profile_decision_markdown(payload))
    _dump_json(payload)
    return 0


def _parse_cli_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_set_spec(value: str) -> tuple[str, list[Any]]:
    if "=" not in value:
        raise ProfileError("--set values must use key=value1,value2 syntax")
    key, raw_values = value.split("=", 1)
    key = key.strip()
    if not key:
        raise ProfileError("--set key must not be empty")
    raw_values = raw_values.strip()
    if raw_values.startswith("["):
        parsed = _parse_cli_value(raw_values)
        if not isinstance(parsed, list):
            raise ProfileError("--set JSON value must be a list when it starts with [")
        return key, parsed
    return key, [_parse_cli_value(part.strip()) for part in raw_values.split(",") if part.strip()]


def _cmd_experiment(args: argparse.Namespace) -> int:
    if args.resume and not args.checkpoint:
        raise ProfileError("profile experiment --resume requires --checkpoint")
    if args.batch_size is not None and not args.checkpoint:
        raise ProfileError("profile experiment --batch-size requires --checkpoint")
    if args.batch_size is not None and args.batch_size <= 0:
        raise ProfileError("profile experiment batch_size must be positive")

    if args.matrix:
        matrix = load_enrichment_experiment_matrix(args.matrix)
    elif args.bounded_defaults:
        matrix = make_bounded_enrichment_experiment_matrix(name=args.name)
    else:
        matrix = {"schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA, "dimensions": {}}
    if args.name:
        matrix["name"] = args.name
    dimensions = matrix.setdefault("dimensions", {})
    if not isinstance(dimensions, dict):
        raise ProfileError("experiment matrix dimensions must be an object")
    for spec in args.set or []:
        key, values = _parse_set_spec(spec)
        dimensions[key] = values

    base_profile = load_profile(args.base_profile)
    source_hashes = _source_hash_map([args.base_profile, args.matrix])
    request_hash = _experiment_request_hash(
        base_profile=base_profile.to_manifest_dict(),
        matrix=matrix,
        profile_id_prefix=args.profile_id_prefix,
        max_experiments=args.max_experiments,
        fail_on_duplicate_effective_profiles=args.fail_on_duplicate_effective_profiles,
    )
    payload = plan_enrichment_experiments(
        base_profile=base_profile,
        matrix=matrix,
        profile_id_prefix=args.profile_id_prefix,
        max_experiments=args.max_experiments,
        fail_on_duplicate_effective_profiles=args.fail_on_duplicate_effective_profiles,
    )
    payload = _apply_experiment_checkpoint(
        payload,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        batch_size=args.batch_size,
        source_hashes=source_hashes,
        request_hash=request_hash,
        candidate_set=args.candidate_set,
        profile_id_prefix=args.profile_id_prefix,
        max_experiments=args.max_experiments,
        fail_on_duplicate_effective_profiles=args.fail_on_duplicate_effective_profiles,
    )
    _write_json(args.candidate_set, payload["candidate_profile_set"])
    payload = _sanitize_profile_report(
        payload,
        args,
        input_paths=[args.base_profile, args.matrix, args.checkpoint],
        output_paths=[args.candidate_set, args.report_json, args.report_md, args.redaction_report, args.checkpoint],
        context_json_paths=[args.base_profile, args.matrix],
    )
    _write_json(args.report_json, payload)
    if args.redaction_report:
        _write_text(args.report_md, _render_enrichment_experiment_markdown_from_payload(payload))
    else:
        _write_text(args.report_md, render_enrichment_experiment_markdown(payload))
    _dump_json(payload)
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, explain, recommend, compare, and plan RAGFlow chunk profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a chunk profile")
    lint.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    lint.add_argument("--fail-on-warning", action="store_true")
    lint.add_argument("--report-json", help="Optional JSON report output path")
    lint.add_argument("--report-md", help="Optional Markdown report output path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.set_defaults(func=_cmd_lint)

    explain = subparsers.add_parser("explain", help="Explain a chunk profile")
    explain.add_argument("--profile", required=True, help="Profile JSON/YAML path")
    explain.add_argument("--report-json", help="Optional JSON report output path")
    explain.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    explain.set_defaults(func=_cmd_explain)

    recommend = subparsers.add_parser("recommend", help="Recommend a neutral starter profile")
    recommend.add_argument("--language", default="auto", help="auto, zh/ch/cn/zho, or en/eng")
    recommend.add_argument(
        "--doc-type",
        default="general",
        choices=["general", "book", "manual", "paper", "notes", "mixed"],
    )
    recommend.add_argument("--profile-id", help="Override generated profile_id")
    recommend.add_argument("--retrieval-hints", help="Optional retrieval_hints.json used to annotate profile recommendation")
    recommend.add_argument("--output", help="Optional profile JSON output path")
    recommend.add_argument("--report-json", help="Optional recommendation report output path")
    recommend.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    recommend.set_defaults(func=_cmd_recommend)

    compare = subparsers.add_parser("compare", help="Compare validation reports from profile experiments")
    compare.add_argument("--report", action="append", required=True, help="Validation report JSON path")
    compare.add_argument("--report-json", help="Optional JSON report output path")
    compare.add_argument("--report-md", help="Optional Markdown report output path")
    compare.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    compare.set_defaults(func=_cmd_compare)

    decision = subparsers.add_parser("decision", help="Decide whether profile evidence is strong enough for a default change")
    decision.add_argument("--report", action="append", required=True, help="Validation report JSON path")
    decision.add_argument("--minimum-query-count", type=int, default=20, help="Minimum query count before recommending a default change")
    decision.add_argument("--minimum-profile-count", type=int, default=2, help="Minimum compared profile count")
    decision.add_argument("--minimum-score-delta", type=float, default=0.03, help="Minimum decision-score delta")
    decision.add_argument("--report-json", help="Optional JSON decision report output path")
    decision.add_argument("--report-md", help="Optional Markdown decision report output path")
    decision.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    decision.set_defaults(func=_cmd_decision)

    experiment = subparsers.add_parser("experiment", help="Plan offline enrichment experiment profiles")
    experiment.add_argument("--base-profile", required=True, help="Base profile JSON/YAML path")
    experiment.add_argument("--matrix", help="ragflow_enrichment_experiment_matrix_v1 JSON/YAML")
    experiment.add_argument(
        "--bounded-defaults",
        action="store_true",
        help="Use a small offline auto_keywords/auto_questions matrix: 0 and 1 for each",
    )
    experiment.add_argument("--set", action="append", default=[], help="Add/override a dimension as key=value1,value2; may be repeated")
    experiment.add_argument("--name", help="Optional experiment matrix name")
    experiment.add_argument("--profile-id-prefix", help="Prefix for generated candidate profile ids")
    experiment.add_argument("--max-experiments", type=int, default=64, help="Maximum matrix expansion size")
    experiment.add_argument(
        "--fail-on-duplicate-effective-profiles",
        action="store_true",
        help="Fail when raw matrix combinations collapse to duplicate effective profiles",
    )
    experiment.add_argument("--candidate-set", help="Optional ragflow_candidate_profile_set_v1 output path")
    experiment.add_argument("--checkpoint", help="Checkpoint path for resumable offline profile experiment planning")
    experiment.add_argument("--resume", action="store_true", help="Resume from an existing profile experiment checkpoint")
    experiment.add_argument("--batch-size", type=int, help="Emit at most this many new candidate profiles in this run")
    experiment.add_argument("--report-json", help="Optional experiment report JSON output path")
    experiment.add_argument("--report-md", help="Optional experiment report Markdown path")
    experiment.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    experiment.set_defaults(func=_cmd_experiment)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ProfileError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
