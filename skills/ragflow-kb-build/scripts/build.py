#!/usr/bin/env python3
"""Build a RAGFlow knowledge base from Markdown inputs."""

from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
from typing import Any, Mapping


def bootstrap_runtime() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    BuildError,
    HandoffError,
    RAGFlowClient,
    create_optimization_cleanup_plan,
    create_optimization_plan,
    discover_markdown_documents,
    inspect_rich_handoff,
    load_config,
    load_doc_manifest,
    load_profile,
    lint_metadata_file,
    lint_tagset_file,
    make_kb_manifest_payload,
    make_metadata_template_payload,
    make_tagset_template_payload,
    map_grounded_qa_evidence,
    merge_metadata_payloads,
    probe_model_providers,
    configured_private_hosts_from_urls,
    create_kb_activation_plan,
    create_kb_health_report,
    create_kb_split_plan,
    create_kb_topology_advice,
    create_parse_report,
    render_handoff_inspection_markdown,
    render_kb_health_report_markdown,
    render_governance_markdown,
    render_model_provider_probe_markdown,
    render_parse_report_markdown,
    gate_benchmark_report,
    import_benchmark_dataset,
    preflight_benchmark_dataset,
    render_best_profile_markdown,
    render_benchmark_governance_markdown,
    render_optimization_cleanup_plan_markdown,
    render_suppression_report_markdown,
    sample_benchmark_dataset,
    segment_metadata_report_file,
    render_activation_plan_markdown,
    render_split_plan_markdown,
    render_topology_advice_markdown,
    render_optimization_plan_markdown,
    snapshot_chunks,
    suggest_benchmark_retrieval_parameters,
    summarize_optimization_results,
    summarize_benchmark_report,
    suppression_report_file,
    trend_benchmark_reports,
    delta_benchmark_reports,
    summarize_metadata_for_documents,
    export_tagset_file,
    tagset_report_file,
    generate_grounded_qa,
    validate_grounded_qa,
    wait_for_document_states,
    sanitize_report_payload,
)
from ragflow_skill_runtime.benchmark_governance import BenchmarkGovernanceError  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.health_report import HealthReportError  # noqa: E402
from ragflow_skill_runtime.kb_build import extract_dataset_id, extract_uploaded_document_id  # noqa: E402
from ragflow_skill_runtime.metadata_governance import MetadataGovernanceError  # noqa: E402
from ragflow_skill_runtime.parse_report import ParseReportError  # noqa: E402
from ragflow_skill_runtime.profiles import ChunkProfile  # noqa: E402
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402
from ragflow_skill_runtime.topology import TopologyError  # noqa: E402


_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_ASSIGNMENT_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;\"']+)"
)
OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA = "ragflow_optimization_plan_checkpoint_v1"
OPTIMIZATION_COMMAND_MANIFEST_SCHEMA = "ragflow_optimization_command_manifest_v1"


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _guard_quality_gate(doc_manifest, *, allow_blocked: bool) -> None:
    if not doc_manifest or allow_blocked:
        return
    gate = getattr(doc_manifest, "quality_gate", {}) or {}
    status = gate.get("status") if isinstance(gate, dict) else None
    if status == "BLOCKED":
        raise BuildError(
            "doc_manifest quality gate is BLOCKED; inspect the quality report or pass "
            "--allow-blocked to upload anyway"
        )


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json_file(path: str | Path, *, label: str = "file") -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"{label} not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{label} is not valid JSON: {source}") from exc


def _write_text_file(path: str | None, text: str) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(item).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_hash_map(paths: list[str | None]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        source = Path(path)
        if source.exists() and source.is_file():
            hashes[str(source)] = _sha256_file(source)
        elif source.exists() and source.is_dir():
            hashes[str(source)] = _sha256_directory(source)
    return hashes


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_path_token(path: Any, *, artifact_dir: str | Path | None) -> str:
    text = str(path)
    if not text:
        return text
    if artifact_dir:
        artifact_root = Path(artifact_dir)
        try:
            relative = Path(text).relative_to(artifact_root)
            return f"<artifact-dir>/{relative.as_posix()}"
        except ValueError:
            pass
    if "://" in text:
        return text
    path_obj = Path(text)
    if path_obj.is_absolute():
        try:
            return f"<cwd>/{path_obj.relative_to(Path.cwd()).as_posix()}"
        except ValueError:
            return f"<path>/{path_obj.name}"
    return path_obj.as_posix()


def _manifest_command_tokens(command: list[Any] | None, *, artifact_dir: str | Path | None) -> list[str]:
    if not command:
        return []
    tokens: list[str] = []
    for token in command:
        text = str(token)
        if "/" in text or "\\" in text or text.endswith((".json", ".md", ".yaml", ".yml", ".py", ".txt")):
            tokens.append(_manifest_path_token(text, artifact_dir=artifact_dir))
        else:
            tokens.append(text)
    return tokens


def _command_entry(
    *,
    command_id: str,
    label: str,
    command: list[Any] | None,
    mutates_ragflow: bool,
    mutation_label: str,
    required_config: list[str],
    expected_artifacts: list[Any],
    cleanup_notes: list[str],
    artifact_dir: str | Path | None,
    enabled: bool = True,
    requires_execute: bool = False,
    source_profile_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": command_id,
        "label": label,
        "profile_id": source_profile_id,
        "enabled": bool(enabled),
        "requires_execute": bool(requires_execute),
        "command": _manifest_command_tokens(command, artifact_dir=artifact_dir),
        "mutates_ragflow": bool(mutates_ragflow),
        "mutation_label": mutation_label,
        "required_config": required_config,
        "missing_config": list(required_config),
        "expected_artifacts": [
            {
                "path": _manifest_path_token(path, artifact_dir=artifact_dir),
                "when": "on_success",
            }
            for path in expected_artifacts
            if path
        ],
        "cleanup_notes": cleanup_notes,
    }


def _build_optimization_command_manifest(plan: Mapping[str, Any], *, output_path: str | Path | None = None) -> dict[str, Any]:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    inputs = plan.get("inputs") if isinstance(plan.get("inputs"), Mapping) else {}
    documents = inputs.get("documents") if isinstance(inputs.get("documents"), list) else []
    artifact_dir = None
    if candidates:
        first = candidates[0]
        if isinstance(first, Mapping):
            artifacts = first.get("artifacts") if isinstance(first.get("artifacts"), Mapping) else {}
            kb_manifest = artifacts.get("kb_manifest")
            if kb_manifest:
                artifact_dir = Path(str(kb_manifest)).parent.parent
    commands: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        profile_id = str(candidate.get("profile_id") or f"candidate-{index + 1}")
        artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), Mapping) else {}
        planned = candidate.get("commands") if isinstance(candidate.get("commands"), Mapping) else {}
        mutation_commands = candidate.get("mutation_commands") if isinstance(candidate.get("mutation_commands"), Mapping) else {}
        build = mutation_commands.get("build") if isinstance(mutation_commands.get("build"), Mapping) else {}
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:build-disposable-kb",
                label=f"Build disposable KB for {profile_id}",
                command=build.get("command") if isinstance(build.get("command"), list) else [],
                mutates_ragflow=True,
                mutation_label="creates_dataset_uploads_documents_and_triggers_parse",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[artifacts.get("kb_manifest")],
                cleanup_notes=[
                    "Disabled in command-manifest dry-run.",
                    "Requires future optimize --execute support and explicit user confirmation before mutation.",
                    "After live execution, retain the generated kb_manifest.json so cleanup can confirm the exact dataset id and KB name.",
                ],
                artifact_dir=artifact_dir,
                enabled=bool(build.get("enabled")),
                requires_execute=bool(build.get("requires_execute", True)),
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:benchmark-validation",
                label=f"Run benchmark validation for {profile_id}",
                command=planned.get("validate") if isinstance(planned.get("validate"), list) else [],
                mutates_ragflow=False,
                mutation_label="read_only_benchmark_validation",
                required_config=["RAGFLOW_BASE_URL", "RAGFLOW_API_KEY"],
                expected_artifacts=[artifacts.get("validation_report"), artifacts.get("validation_report_md")],
                cleanup_notes=["No cleanup is required for read-only validation."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:diagnose",
                label=f"Diagnose failed or zero-chunk result for {profile_id}",
                command=planned.get("diagnose") if isinstance(planned.get("diagnose"), list) else [],
                mutates_ragflow=False,
                mutation_label="local_or_read_only_diagnostics",
                required_config=[],
                expected_artifacts=[artifacts.get("diagnostic_report")],
                cleanup_notes=["Diagnostics are advisory and do not create or delete RAGFlow datasets."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )
        commands.append(
            _command_entry(
                command_id=f"{profile_id}:cleanup-preview",
                label=f"Create cleanup preview for {profile_id}",
                command=planned.get("cleanup_preview") if isinstance(planned.get("cleanup_preview"), list) else [],
                mutates_ragflow=False,
                mutation_label="local_cleanup_plan",
                required_config=[],
                expected_artifacts=[artifacts.get("cleanup_plan")],
                cleanup_notes=["Cleanup preview does not delete RAGFlow datasets."],
                artifact_dir=artifact_dir,
                enabled=False,
                source_profile_id=profile_id,
            )
        )

    manifest = {
        "ok": bool(plan.get("ok")),
        "schema": OPTIMIZATION_COMMAND_MANIFEST_SCHEMA,
        "created_at": _utc_now(),
        "mode": "dry_run",
        "source": "ragflow-kb-build optimize --plan-only",
        "plan_schema": plan.get("schema"),
        "plan_output": _manifest_path_token(output_path, artifact_dir=artifact_dir) if output_path else None,
        "run_id": plan.get("run_id"),
        "base_kb_name": plan.get("base_kb_name"),
        "mutation_guard": {
            "mutation_allowed": False,
            "execute_required": True,
            "execute_flag": "--execute",
            "cleanup_confirmation_required": True,
            "cleanup_confirmation_flags": ["--confirm-dataset-id", "--confirm-kb-name"],
            "live_execution_status": "not_implemented",
        },
        "inputs": {
            "input": _manifest_path_token(inputs.get("input"), artifact_dir=artifact_dir) if inputs.get("input") else None,
            "doc_manifest": _manifest_path_token(inputs.get("doc_manifest"), artifact_dir=artifact_dir)
            if inputs.get("doc_manifest")
            else None,
            "documents": [_manifest_path_token(item, artifact_dir=artifact_dir) for item in documents],
        },
        "commands": commands,
        "expected_artifacts": [
            artifact
            for command in commands
            for artifact in command["expected_artifacts"]
        ],
        "cleanup": {
            "required_after_live_execution": any(command["mutates_ragflow"] for command in commands),
            "notes": [
                "Review this manifest before enabling any future live optimization execution.",
                "Do not run mutating commands without credentials, explicit confirmation, and a cleanup plan.",
                "Retain candidate kb_manifest.json files after live execution; cleanup needs exact dataset ids and KB names.",
            ],
        },
        "summary": {
            "candidate_count": len(candidates),
            "command_count": len(commands),
            "mutating_command_count": sum(1 for command in commands if command["mutates_ragflow"]),
            "enabled_mutating_command_count": sum(
                1 for command in commands if command["mutates_ragflow"] and command["enabled"]
            ),
            "expected_artifact_count": sum(len(command["expected_artifacts"]) for command in commands),
        },
    }
    return manifest


def _require_optimize_execute_confirmation(args: argparse.Namespace, plan: Mapping[str, Any]) -> None:
    if not args.confirm_live_build:
        raise ProfileError("optimize --execute requires --confirm-live-build")
    if args.confirm_kb_name != plan.get("base_kb_name"):
        raise ProfileError("optimize --execute requires --confirm-kb-name to match --kb-name exactly")
    if args.confirm_run_id != plan.get("run_id"):
        raise ProfileError("optimize --execute requires --confirm-run-id to match the planned run_id exactly")


def _build_candidate_kb(
    *,
    candidate: Mapping[str, Any],
    docs: list[Any],
    config: Any,
    client: Any,
    metadata_summary: dict[str, Any] | None,
    parse_timeout: float,
    poll_interval: float,
    no_parse: bool,
    no_wait: bool,
) -> dict[str, Any]:
    profile_payload = candidate.get("profile") if isinstance(candidate.get("profile"), Mapping) else None
    if profile_payload is None:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing profile payload")
    profile = ChunkProfile.from_dict(profile_payload)
    kb_name = str(candidate.get("disposable_kb_name") or "")
    if not kb_name:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing disposable_kb_name")
    artifacts = candidate.get("artifacts") if isinstance(candidate.get("artifacts"), Mapping) else {}
    manifest_path = artifacts.get("kb_manifest")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ProfileError(f"candidate {candidate.get('profile_id') or '<unknown>'} is missing artifacts.kb_manifest")

    dataset_response = client.create_dataset(kb_name, profile=profile.to_dataset_payload())
    dataset_id = extract_dataset_id(dataset_response)
    uploaded = []
    document_ids: list[str] = []
    for doc in docs:
        response = client.upload_document(dataset_id, doc.path)
        document_id = extract_uploaded_document_id(response)
        document_ids.append(document_id)
        uploaded.append((doc, document_id, "uploaded", None))

    parse_response = None
    live_states = {}
    if document_ids and not no_parse:
        parse_response = client.trigger_parse(dataset_id, document_ids)
        if not no_wait:
            live_states = wait_for_document_states(
                client,
                dataset_id=dataset_id,
                document_ids=document_ids,
                timeout=parse_timeout,
                poll_interval=poll_interval,
            )
            uploaded = [
                (
                    doc,
                    document_id,
                    live_states.get(document_id, {}).get("status", status),
                    live_states.get(document_id, {}).get("chunk_count", chunk_count),
                )
                for doc, document_id, status, chunk_count in uploaded
            ]

    payload = make_kb_manifest_payload(
        base_url=config.base_url,
        dataset_id=dataset_id,
        dataset_name=kb_name,
        profile=profile,
        documents=uploaded,
    )
    if metadata_summary:
        payload["metadata_summary"] = metadata_summary
    _write_json_file(manifest_path, payload)
    return {
        "profile_id": candidate.get("profile_id"),
        "disposable_kb_name": kb_name,
        "kb_manifest": manifest_path,
        "dataset_id": dataset_id,
        "document_count": len(uploaded),
        "parse_triggered": bool(document_ids and not no_parse),
        "parse_waited": bool(document_ids and not no_parse and not no_wait),
        "parse_response": parse_response,
        "cleanup_required": True,
    }


def _collect_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_collect_urls(item))
        return urls
    if isinstance(value, (list, tuple)):
        urls = []
        for item in value:
            urls.extend(_collect_urls(item))
        return urls
    return []


def _collect_secret_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        values: list[str] = []
        for match in _ASSIGNMENT_SECRET_VALUE_RE.finditer(value):
            secret = match.group(1).strip()
            if len(secret) < 4:
                continue
            values.append(secret)
            stem = Path(secret).stem
            if len(stem) >= 4 and stem != secret:
                values.append(stem)
        return values
    if isinstance(value, dict):
        secrets: list[str] = []
        for item in value.values():
            secrets.extend(_collect_secret_literals(item))
        return secrets
    if isinstance(value, (list, tuple)):
        secrets = []
        for item in value:
            secrets.extend(_collect_secret_literals(item))
        return secrets
    return []


def _collect_path_like_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if (
            "/" in text
            or "\\" in text
            or text.startswith(("~", "."))
            or text.endswith((".json", ".jsonl", ".md", ".yaml", ".yml", ".py", ".toml", ".txt"))
        ):
            paths = [text]
            if "://" not in text:
                path = Path(text)
                if str(path.parent) not in {"", ".", "/"}:
                    paths.append(str(path.parent))
            return paths
        return []
    if isinstance(value, dict):
        paths: list[str] = []
        for item in value.values():
            paths.extend(_collect_path_like_literals(item))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            paths.extend(_collect_path_like_literals(item))
        return paths
    return []


def _expand_config_paths(paths: list[str | None]) -> list[str | None]:
    expanded: list[str | None] = []
    for raw_path in paths:
        if not raw_path:
            continue
        text = str(raw_path)
        expanded.append(text)
        if "://" in text:
            continue
        parent = Path(text).parent
        if str(parent) not in {"", ".", "/"}:
            expanded.append(str(parent))
    return expanded


def _collect_redaction_context_from_json_paths(paths: list[str | None]) -> tuple[list[str], list[str], list[str]]:
    secrets: list[str] = []
    hosts: list[str] = []
    path_literals: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        try:
            payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            continue
        secrets.extend(_collect_secret_literals(payload))
        hosts.extend(configured_private_hosts_from_urls(_collect_urls(payload)))
        path_literals.extend(_collect_path_like_literals(payload))
    return secrets, hosts, path_literals


def _sanitize_governance_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None],
    output_paths: list[str | None] | None = None,
    extra_secret_literals: list[str] | None = None,
    extra_private_hosts: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    config_paths = [
        *_expand_config_paths(input_paths),
        *_expand_config_paths(output_paths or []),
        *_expand_config_paths(
            [
                getattr(args, "report_json", None),
                getattr(args, "report_md", None),
                getattr(args, "redaction_report", None),
            ]
        ),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[*_collect_secret_literals(report), *(extra_secret_literals or [])],
        private_hosts=[*configured_private_hosts_from_urls(urls), *(extra_private_hosts or [])],
        config_paths=config_paths,
    )
    return sanitized, redaction_report


def _run(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        metadata_summary = summarize_metadata_for_documents(args.metadata, [doc.path for doc in docs])
        if metadata_summary and not metadata_summary.get("ok", False):
            raise BuildError("metadata lint failed; run metadata lint for details")
        if args.dry_run:
            _dump_json(
                {
                    "ok": True,
                    "dry_run": True,
                    "kb_name": args.kb_name,
                    "profile": profile.to_manifest_dict(),
                    "documents": [str(doc.path) for doc in docs],
                    "metadata_summary": metadata_summary,
                }
            )
            return 0

        config = _load_config(args)
        client = RAGFlowClient(config)
        dataset_response = client.create_dataset(args.kb_name, profile=profile.to_dataset_payload())
        dataset_id = extract_dataset_id(dataset_response)

        uploaded = []
        document_ids: list[str] = []
        for doc in docs:
            response = client.upload_document(dataset_id, doc.path)
            document_id = extract_uploaded_document_id(response)
            document_ids.append(document_id)
            uploaded.append((doc, document_id, "uploaded", None))

        parse_response = None
        live_states = {}
        if document_ids and not args.no_parse:
            parse_response = client.trigger_parse(dataset_id, document_ids)
            if not args.no_wait:
                live_states = wait_for_document_states(
                    client,
                    dataset_id=dataset_id,
                    document_ids=document_ids,
                    timeout=args.parse_timeout,
                    poll_interval=args.poll_interval,
                )
                uploaded = [
                    (
                        doc,
                        document_id,
                        live_states.get(document_id, {}).get("status", status),
                        live_states.get(document_id, {}).get("chunk_count", chunk_count),
                    )
                    for doc, document_id, status, chunk_count in uploaded
                ]

        payload = make_kb_manifest_payload(
            base_url=config.base_url,
            dataset_id=dataset_id,
            dataset_name=args.kb_name,
            profile=profile,
            documents=uploaded,
        )
        if metadata_summary:
            payload["metadata_summary"] = metadata_summary
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": True,
                "kb_manifest": str(output),
                "dataset_id": dataset_id,
                "document_count": len(uploaded),
                "parse_triggered": not args.no_parse,
                "parse_waited": not args.no_parse and not args.no_wait,
                "parse_response": parse_response,
            }
        )
        return 0
    except (BuildError, ConfigError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect_handoff(args: argparse.Namespace) -> int:
    try:
        report = inspect_rich_handoff(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.handoff, args.manifest_name, *_collect_path_like_literals(report)],
                output_paths=[args.report_json, args.report_md, args.redaction_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_handoff_inspection_markdown(report), encoding="utf-8")
        _dump_json({"ok": True, "handoff": report})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_metadata_file(args.metadata)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(report, args, input_paths=[args.metadata])
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_merge(args: argparse.Namespace) -> int:
    try:
        report = merge_metadata_payloads(
            doc_manifest_path=args.doc_manifest,
            handoff_metadata_path=args.handoff_metadata,
            user_metadata_path=args.metadata,
            derive_from_path=not args.no_derive_from_path,
        )
        _write_json_file(args.output, report["metadata"])
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.doc_manifest, args.handoff_metadata, args.metadata],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Metadata Merge Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_metadata_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_metadata_template_payload(doc_manifest_path=args.doc_manifest)
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "document_count": len(payload["documents"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_lint(args: argparse.Namespace) -> int:
    try:
        report = lint_tagset_file(args.tagset)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(report, args, input_paths=[args.tagset])
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Lint Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_export(args: argparse.Namespace) -> int:
    try:
        exported = export_tagset_file(args.tagset, fmt=args.format)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(exported, str):
            output.write_text(exported, encoding="utf-8")
        else:
            output.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _dump_json({"ok": True, "schema": "ragflow_tagset_export_result_v1", "format": args.format, "output": str(output)})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_report(args: argparse.Namespace) -> int:
    try:
        report = tagset_report_file(args.tagset, metadata_path=args.metadata)
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.tagset, args.metadata],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Tagset Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_tagset_generate_template(args: argparse.Namespace) -> int:
    try:
        payload = make_tagset_template_payload()
        _write_json_file(args.output, payload)
        _dump_json({"ok": True, "schema": payload["schema"], "output": args.output, "tag_count": len(payload["tags"])})
        return 0
    except (MetadataGovernanceError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_benchmark_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None],
    context_json_paths: list[str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths(context_json_paths or [])
    return _sanitize_governance_report(
        report,
        args,
        input_paths=[*input_paths, *context_paths, *_collect_path_like_literals(report)],
        extra_secret_literals=context_secrets,
        extra_private_hosts=context_hosts,
    )


def _optimization_plan_request_hash(plan: Mapping[str, Any]) -> str:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    candidate_summaries = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_summaries.append(
            {
                "profile_id": candidate.get("profile_id"),
                "disposable_kb_name": candidate.get("disposable_kb_name"),
                "profile": candidate.get("profile"),
                "artifacts": candidate.get("artifacts"),
            }
        )
    return _stable_digest(
        {
            "schema": plan.get("schema"),
            "mode": plan.get("mode"),
            "run_id": plan.get("run_id"),
            "base_kb_name": plan.get("base_kb_name"),
            "mutation_allowed": plan.get("mutation_allowed"),
            "inputs": plan.get("inputs"),
            "candidates": candidate_summaries,
            "steps": plan.get("steps"),
        }
    )


def _read_optimization_plan_checkpoint(path: Path) -> dict[str, Any]:
    payload = _read_json_file(path, label="optimization plan checkpoint")
    if not isinstance(payload, Mapping):
        raise ProfileError("optimization plan checkpoint must be a JSON object")
    if payload.get("schema") != OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA:
        raise ProfileError(f"optimization plan checkpoint schema must be {OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA}")
    processed = payload.get("processed_profile_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise ProfileError("optimization plan checkpoint processed_profile_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ProfileError("optimization plan checkpoint source_hashes must be an object")
    return dict(payload)


def _validate_optimization_plan_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
    request_hash: str,
    output_path: str | None,
    artifact_dir: str | None,
) -> None:
    if dict(checkpoint.get("source_hashes") or {}) != dict(source_hashes):
        raise ProfileError("optimization plan checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("request_hash") or "") != request_hash:
        raise ProfileError("optimization plan checkpoint request hash does not match current request")
    expected_output = str(Path(output_path)) if output_path else None
    if (checkpoint.get("output") or None) != expected_output:
        raise ProfileError("optimization plan checkpoint output does not match current output")
    expected_artifact_dir = str(Path(artifact_dir)) if artifact_dir else None
    if (checkpoint.get("artifact_dir") or None) != expected_artifact_dir:
        raise ProfileError("optimization plan checkpoint artifact_dir does not match current request")


def _write_optimization_plan_checkpoint(
    *,
    checkpoint_path: str | Path,
    source_hashes: Mapping[str, str],
    request_hash: str,
    output_path: str | None,
    artifact_dir: str | None,
    processed_profile_ids: list[str],
    total_profile_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_profile_ids))
    payload = {
        "schema": OPTIMIZATION_PLAN_CHECKPOINT_SCHEMA,
        "created_at": created_at or _utc_now(),
        "updated_at": _utc_now(),
        "source_hashes": dict(source_hashes),
        "request_hash": request_hash,
        "output": str(Path(output_path)) if output_path else None,
        "artifact_dir": str(Path(artifact_dir)) if artifact_dir else None,
        "processed_profile_ids": processed,
        "summary": {
            "processed_profile_count": len(processed),
            "total_profile_count": total_profile_count,
            "remaining_profile_count": max(total_profile_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    _write_json_file(str(checkpoint_path), payload)
    return payload


def _apply_optimization_plan_checkpoint(
    plan: dict[str, Any],
    *,
    checkpoint_path: str | None,
    resume: bool,
    batch_size: int | None,
    source_hashes: Mapping[str, str],
    output_path: str | None,
    artifact_dir: str | None,
) -> dict[str, Any]:
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    candidate_ids = [str(item.get("profile_id")) for item in candidates if isinstance(item, Mapping) and item.get("profile_id")]
    request_hash = _optimization_plan_request_hash(plan)
    processed_profile_ids: list[str] = []
    checkpoint_created_at: str | None = None

    if checkpoint_path and resume:
        checkpoint = _read_optimization_plan_checkpoint(Path(checkpoint_path))
        _validate_optimization_plan_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            request_hash=request_hash,
            output_path=output_path,
            artifact_dir=artifact_dir,
        )
        processed_profile_ids = list(checkpoint.get("processed_profile_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    unknown_processed = sorted(set(processed_profile_ids) - set(candidate_ids))
    if unknown_processed:
        raise ProfileError(
            "optimization plan checkpoint contains profile ids that are not present in current candidates: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_profile_ids)
    remaining_profile_ids = [profile_id for profile_id in candidate_ids if profile_id not in processed_set]
    next_profile_ids = remaining_profile_ids if batch_size is None else remaining_profile_ids[:batch_size]
    selected_profile_ids = set(processed_profile_ids) | set(next_profile_ids)
    completed = bool(plan.get("ok")) and len(selected_profile_ids) >= len(candidate_ids)
    filtered_candidates = [
        item
        for item in candidates
        if isinstance(item, Mapping) and str(item.get("profile_id") or "") in selected_profile_ids
    ]

    checkpoint_payload = None
    if checkpoint_path and plan.get("ok"):
        ordered_processed = [profile_id for profile_id in candidate_ids if profile_id in selected_profile_ids]
        checkpoint_payload = _write_optimization_plan_checkpoint(
            checkpoint_path=checkpoint_path,
            source_hashes=source_hashes,
            request_hash=request_hash,
            output_path=output_path,
            artifact_dir=artifact_dir,
            processed_profile_ids=ordered_processed,
            total_profile_count=len(candidate_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    summary = dict(plan.get("summary") if isinstance(plan.get("summary"), Mapping) else {})
    summary.update(
        {
            "candidate_count": len(filtered_candidates),
            "planned_experiment_count": len(filtered_candidates),
            "blocked_mutation_command_count": len(filtered_candidates),
            "completed": completed,
            "checkpoint_enabled": bool(checkpoint_path),
            "checkpoint_resume": bool(resume),
            "checkpoint_new_profile_count": len(next_profile_ids),
            "checkpoint_remaining_profile_count": max(len(candidate_ids) - len(selected_profile_ids), 0),
        }
    )
    plan = dict(plan)
    plan["summary"] = summary
    plan["candidates"] = filtered_candidates
    plan["completed"] = completed
    plan["checkpoint"] = {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "batch_size": batch_size,
        "processed_profile_count": len(selected_profile_ids),
        "new_profile_count": len(next_profile_ids),
        "remaining_profile_count": max(len(candidate_ids) - len(selected_profile_ids), 0),
        "total_profile_count": len(candidate_ids),
        "completed": completed,
        "next_profile_ids": list(next_profile_ids),
    }
    if checkpoint_payload:
        plan["checkpoint_payload"] = checkpoint_payload
    return plan


def _run_benchmark_import(args: argparse.Namespace) -> int:
    try:
        report = import_benchmark_dataset(
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            output_dir=args.output,
            name=args.name,
            description=args.description or "",
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.queries, args.qrels, args.qa, args.output, args.checkpoint],
                context_json_paths=[args.queries, args.qrels, args.qa],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Import Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_snapshot_chunks(args: argparse.Namespace) -> int:
    try:
        report = snapshot_chunks(
            input_path=args.input,
            output_path=args.output,
            name=args.name,
            description=args.description or "",
            include_content=args.include_content,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.input, args.output],
                context_json_paths=[args.input],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Chunk Snapshot Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_preflight(args: argparse.Namespace) -> int:
    try:
        report = preflight_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.manifest, args.queries, args.qrels, args.qa, args.chunk_snapshot, args.gate_config],
                context_json_paths=[args.manifest, args.queries, args.qrels, args.qa, args.chunk_snapshot, args.gate_config],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Preflight Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_sample(args: argparse.Namespace) -> int:
    try:
        report = sample_benchmark_dataset(
            manifest_path=args.manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            output_dir=args.output,
            sample_size=args.size,
            sample_fraction=args.fraction,
            strategy=args.strategy,
            seed=args.seed,
            name=args.name,
            description=args.description or "",
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.manifest, args.queries, args.qrels, args.qa, args.output],
                context_json_paths=[args.manifest, args.queries, args.qrels, args.qa],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Sample Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_summarize(args: argparse.Namespace) -> int:
    try:
        report = summarize_benchmark_report(args.report)
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report],
                context_json_paths=[args.report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Summary Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_gate(args: argparse.Namespace) -> int:
    try:
        report = gate_benchmark_report(
            report_path=args.report,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.gate_config, args.baseline_report],
                context_json_paths=[args.report, args.gate_config, args.baseline_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Gate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_trend(args: argparse.Namespace) -> int:
    try:
        report = trend_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report, args.gate_config],
                context_json_paths=[args.report, args.baseline_report, args.gate_config],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Trend Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_delta(args: argparse.Namespace) -> int:
    try:
        report = delta_benchmark_reports(
            current_report_path=args.report,
            baseline_report_path=args.baseline_report,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report],
                context_json_paths=[args.report, args.baseline_report],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Delta Report"))
        _dump_json(report)
        return 0
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_benchmark_suggest(args: argparse.Namespace) -> int:
    try:
        report = suggest_benchmark_retrieval_parameters(
            report_path=args.report,
            baseline_report_path=args.baseline_report,
            gate_config_path=args.gate_config,
            current_top_k=args.current_top_k,
            current_similarity_threshold=args.current_similarity_threshold,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.baseline_report, args.gate_config],
                context_json_paths=[args.report, args.baseline_report, args.gate_config],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Benchmark Retrieval Suggestions"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_suppression_report(args: argparse.Namespace) -> int:
    try:
        report = suppression_report_file(
            args.report,
            tagset_path=args.tagset,
            max_candidates=args.max_candidates,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.report, args.tagset],
                context_json_paths=[args.report, args.tagset],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_suppression_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_validate(args: argparse.Namespace) -> int:
    try:
        report = validate_grounded_qa(
            qa_path=args.qa,
            sources_path=args.sources,
            source_dir=args.source_dir,
            require_answer=not args.allow_missing_answer,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.qa, args.sources, args.source_dir],
                context_json_paths=[args.qa, args.sources],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Validate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_generate(args: argparse.Namespace) -> int:
    try:
        report = generate_grounded_qa(
            output_path=args.output,
            sources_path=args.sources,
            source_dir=args.source_dir,
            count=args.count,
            strategy=args.strategy,
            seed=args.seed,
            min_span_chars=args.min_span_chars,
            max_span_chars=args.max_span_chars,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.sources, args.source_dir, args.output, args.checkpoint],
                context_json_paths=[args.sources],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow Grounded QA Generate Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_qa_map_evidence(args: argparse.Namespace) -> int:
    try:
        report = map_grounded_qa_evidence(
            qa_path=args.qa,
            chunk_snapshot_path=args.chunk_snapshot,
            output_path=args.output,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.qa, args.chunk_snapshot, args.output],
                context_json_paths=[args.qa, args.chunk_snapshot],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_benchmark_governance_markdown(report, title="RAGFlow QA Evidence Map Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (BenchmarkGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_segment_metadata_report(args: argparse.Namespace) -> int:
    try:
        report = segment_metadata_report_file(
            chunk_snapshot_path=args.chunk_snapshot,
            metadata_path=args.metadata,
            segmentation_plan_path=args.segmentation_plan,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_benchmark_report(
                report,
                args,
                input_paths=[args.chunk_snapshot, args.metadata, args.segmentation_plan],
                context_json_paths=[args.chunk_snapshot, args.metadata, args.segmentation_plan],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_governance_markdown(report, title="RAGFlow Segment Metadata Report"))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (MetadataGovernanceError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize(args: argparse.Namespace) -> int:
    try:
        if args.execute and args.plan_only:
            raise ProfileError("optimize --execute cannot be combined with --plan-only")
        if not args.plan_only and not args.execute:
            raise ProfileError("optimize requires --plan-only or --execute")
        if args.execute and args.command_manifest_output:
            raise ProfileError("optimize --command-manifest-output is for --plan-only dry-run review; omit it with --execute")
        if args.resume and not args.checkpoint:
            raise ProfileError("optimize --resume requires --checkpoint")
        if args.batch_size is not None and not args.checkpoint:
            raise ProfileError("optimize --batch-size requires --checkpoint")
        if args.batch_size is not None and args.batch_size <= 0:
            raise ProfileError("optimize batch_size must be positive")
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        plan = create_optimization_plan(
            kb_name=args.kb_name,
            document_paths=[doc.path for doc in docs],
            input_path=args.input,
            doc_manifest_path=args.doc_manifest,
            profile_paths=args.profile,
            profile_dirs=args.profile_dir,
            profile_set_paths=args.profile_set,
            recommendations=args.recommendation,
            benchmark_manifest_path=args.benchmark_manifest,
            queries_path=args.queries,
            qrels_path=args.qrels,
            qa_path=args.qa,
            metadata_path=args.metadata,
            tagset_path=args.tagset,
            chunk_snapshot_path=args.chunk_snapshot,
            gate_config_path=args.gate_config,
            baseline_report_path=args.baseline_report,
            artifact_dir=args.artifact_dir,
            run_id=args.run_id,
            top_k=args.top_k,
            metric_cutoff=args.metric_cutoff,
        )
        source_hashes = _source_hash_map(
            [
                args.input,
                args.doc_manifest,
                *args.profile,
                *args.profile_dir,
                *args.profile_set,
                args.benchmark_manifest,
                args.queries,
                args.qrels,
                args.qa,
                args.metadata,
                args.tagset,
                args.chunk_snapshot,
                args.gate_config,
                args.baseline_report,
            ]
        )
        plan = _apply_optimization_plan_checkpoint(
            plan,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            batch_size=args.batch_size,
            source_hashes=source_hashes,
            output_path=args.output,
            artifact_dir=args.artifact_dir,
        )
        execution_report = None
        if args.execute:
            _require_optimize_execute_confirmation(args, plan)
            if not plan.get("ok"):
                raise ProfileError("optimize --execute requires a valid optimization plan with ok=true")
            config = _load_config(args)
            client = RAGFlowClient(config)
            metadata_summary = summarize_metadata_for_documents(args.metadata, [doc.path for doc in docs])
            if metadata_summary and not metadata_summary.get("ok", False):
                raise BuildError("metadata lint failed; run metadata lint for details")
            results = []
            for candidate in plan.get("candidates", []):
                if not isinstance(candidate, Mapping):
                    continue
                results.append(
                    _build_candidate_kb(
                        candidate=candidate,
                        docs=docs,
                        config=config,
                        client=client,
                        metadata_summary=metadata_summary,
                        parse_timeout=args.parse_timeout,
                        poll_interval=args.poll_interval,
                        no_parse=args.no_parse,
                        no_wait=args.no_wait,
                    )
                )
            execution_report = {
                "schema": "ragflow_optimization_execute_report_v1",
                "created_at": _utc_now(),
                "mode": "execute-build",
                "run_id": plan.get("run_id"),
                "base_kb_name": plan.get("base_kb_name"),
                "confirmation": {
                    "confirm_live_build": True,
                    "confirm_kb_name": args.confirm_kb_name,
                    "confirm_run_id": args.confirm_run_id,
                },
                "summary": {
                    "candidate_count": len(plan.get("candidates", [])) if isinstance(plan.get("candidates"), list) else 0,
                    "built_candidate_count": len(results),
                    "dataset_count": len(results),
                    "document_count": sum(int(item.get("document_count") or 0) for item in results),
                    "cleanup_required_count": sum(1 for item in results if item.get("cleanup_required")),
                    "benchmark_validation_executed": False,
                    "cleanup_executed": False,
                },
                "results": results,
                "next_steps": [
                    "Run optimize summarize after benchmark validation reports exist.",
                    "Run optimize cleanup-plan before deleting disposable KBs.",
                    "Delete disposable KBs only with exact dataset id and KB name confirmation.",
                ],
            }
            plan["mode"] = "execute-build"
            plan["mutation_allowed"] = True
            plan["execution"] = execution_report
            plan_summary = dict(plan.get("summary") if isinstance(plan.get("summary"), Mapping) else {})
            plan_summary.update(
                {
                    "built_candidate_count": len(results),
                    "cleanup_required_count": execution_report["summary"]["cleanup_required_count"],
                    "benchmark_validation_executed": False,
                    "cleanup_executed": False,
                }
            )
            plan["summary"] = plan_summary
        command_manifest = None
        if args.command_manifest_output:
            command_manifest = _build_optimization_command_manifest(plan, output_path=args.output)
            plan["command_manifest"] = {
                "path": args.command_manifest_output,
                "schema": command_manifest["schema"],
                "command_count": command_manifest["summary"]["command_count"],
                "mutating_command_count": command_manifest["summary"]["mutating_command_count"],
                "enabled_mutating_command_count": command_manifest["summary"]["enabled_mutating_command_count"],
            }
        if args.redaction_report:
            report_payload = {"plan": plan, "command_manifest": command_manifest} if command_manifest else plan
            sanitized, redaction_report = _sanitize_governance_report(
                report_payload,
                args,
                input_paths=[
                    args.input,
                    args.doc_manifest,
                    *args.profile,
                    *args.profile_dir,
                    *args.profile_set,
                    args.benchmark_manifest,
                    args.queries,
                    args.qrels,
                    args.qa,
                    args.metadata,
                    args.tagset,
                    args.chunk_snapshot,
                    args.gate_config,
                    args.baseline_report,
                    args.artifact_dir,
                    args.checkpoint,
                    args.command_manifest_output,
                    args.config,
                    *_collect_path_like_literals(plan),
                ],
                output_paths=[args.output, args.checkpoint, args.command_manifest_output],
                extra_secret_literals=[getattr(args, "api_key", None)],
                extra_private_hosts=configured_private_hosts_from_urls([getattr(args, "base_url", None)]),
            )
            if command_manifest:
                plan = sanitized["plan"]
                command_manifest = sanitized["command_manifest"]
            else:
                plan = sanitized
            _write_json_file(args.redaction_report, redaction_report)
        if args.command_manifest_output and command_manifest:
            _write_json_file(args.command_manifest_output, command_manifest)
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (BuildError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_summarize(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths([args.plan, *args.report])
        results = summarize_optimization_results(
            plan_path=args.plan,
            report_paths=args.report,
        )
        if args.redaction_report:
            results, redaction_report = _sanitize_governance_report(
                results,
                args,
                input_paths=[args.plan, *args.report, *context_paths, *_collect_path_like_literals(results)],
                output_paths=[args.output],
                extra_secret_literals=context_secrets,
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, results)
        _write_text_file(args.report_md, render_best_profile_markdown(results))
        _dump_json(results)
        return 0 if results["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_optimize_cleanup_plan(args: argparse.Namespace) -> int:
    try:
        context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths([args.plan])
        plan = create_optimization_cleanup_plan(
            plan_path=args.plan,
            cleanup_script=args.cleanup_script,
            config_path=args.config,
            require_manifests=args.require_manifests,
        )
        if args.redaction_report:
            plan, redaction_report = _sanitize_governance_report(
                plan,
                args,
                input_paths=[args.plan, args.cleanup_script, args.config, *context_paths, *_collect_path_like_literals(plan)],
                output_paths=[args.output],
                extra_secret_literals=context_secrets,
                extra_private_hosts=context_hosts,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, plan)
        _write_text_file(args.report_md, render_optimization_cleanup_plan_markdown(plan))
        _dump_json(plan)
        return 0 if plan["ok"] else 1
    except (ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_advise(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_topology_advice(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            route_config_path=args.route_config,
            future_growth=args.future_growth,
            min_documents=args.min_documents,
            min_total_chars=args.min_total_chars,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.input, args.doc_manifest, args.metadata, args.retrieval_hints, args.route_config],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_topology_advice_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_topology_split_plan(args: argparse.Namespace) -> int:
    try:
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        report = create_kb_split_plan(
            kb_name=args.kb_name,
            documents=docs,
            metadata_path=args.metadata,
            retrieval_hints_path=args.retrieval_hints,
            min_group_documents=args.min_group_documents,
            min_group_estimated_chunks=args.min_group_estimated_chunks,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[args.input, args.doc_manifest, args.metadata, args.retrieval_hints],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_split_plan_markdown(report))
        _dump_json(report)
        return 0
    except (BuildError, TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_activation_plan(args: argparse.Namespace) -> int:
    try:
        report = create_kb_activation_plan(
            kb_manifest_path=args.kb_manifest,
            doc_manifest_path=args.doc_manifest,
            route_config_path=args.route_config,
            retrieval_hints_path=args.retrieval_hints,
            chunk_snapshot_path=args.chunk_snapshot,
            centroid_index_path=args.centroid_index,
            route_tests_path=args.route_tests,
            min_documents=args.min_documents,
            min_chunks=args.min_chunks,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_governance_report(
                report,
                args,
                input_paths=[
                    args.kb_manifest,
                    args.doc_manifest,
                    args.route_config,
                    args.retrieval_hints,
                    args.chunk_snapshot,
                    args.centroid_index,
                    args.route_tests,
                ],
                output_paths=[args.output],
            )
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.output, report)
        _write_text_file(args.report_md, render_activation_plan_markdown(report))
        _dump_json(report)
        return 0
    except (TopologyError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_parse_report(report: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            args.kb_manifest,
            args.documents_json,
            *args.parse_log,
            args.profile,
            args.parser_config,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _run_parse_report(args: argparse.Namespace) -> int:
    try:
        report = create_parse_report(
            kb_manifest_path=args.kb_manifest,
            documents_json_path=args.documents_json,
            parse_log_paths=args.parse_log,
            profile_path=args.profile,
            parser_config_path=args.parser_config,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_parse_report(report, args)
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_parse_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ParseReportError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_health_report(report: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [*_collect_urls(report)]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[
            *args.kb_manifest,
            *args.parse_report,
            *args.activation_plan,
            args.report_json,
            args.report_md,
            args.redaction_report,
        ],
    )
    return sanitized, redaction_report


def _run_health_report(args: argparse.Namespace) -> int:
    try:
        report = create_kb_health_report(
            kb_manifest_paths=args.kb_manifest,
            parse_report_paths=args.parse_report,
            activation_plan_paths=args.activation_plan,
            min_documents=args.min_documents,
            min_chunks=args.min_chunks,
            expected_embedding_models=args.expected_embedding_model,
        )
        if args.redaction_report:
            report, redaction_report = _sanitize_health_report(report, args)
            _write_json_file(args.redaction_report, redaction_report)
        _write_json_file(args.report_json, report)
        _write_text_file(args.report_md, render_kb_health_report_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (HealthReportError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _sanitize_model_provider_report(report: dict[str, Any], args: argparse.Namespace, config: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    urls = [config.base_url, args.embedding_adapter_url, args.rerank_adapter_url]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=[config.api_key, args.embedding_adapter_api_key, args.rerank_adapter_api_key],
        private_hosts=configured_private_hosts_from_urls(urls),
        config_paths=[args.config],
    )
    return sanitized, redaction_report


def _run_model_providers_probe(args: argparse.Namespace) -> int:
    try:
        overrides: dict[str, Any] = {}
        if args.base_url:
            overrides["base_url"] = args.base_url
        if args.api_key:
            overrides["api_key"] = args.api_key
        if args.timeout is not None:
            overrides["timeout"] = args.timeout
        config = load_config(config_file=args.config, overrides=overrides)
        client = RAGFlowClient(config)
        report = probe_model_providers(
            client,
            endpoint_paths=args.endpoint,
            expected_embedding_models=args.embedding_model,
            expected_rerank_models=args.rerank_model,
            embedding_adapter_url=args.embedding_adapter_url,
            embedding_adapter_api_key=args.embedding_adapter_api_key,
            embedding_adapter_shape=args.embedding_adapter_shape,
            rerank_adapter_url=args.rerank_adapter_url,
            rerank_adapter_api_key=args.rerank_adapter_api_key,
            rerank_adapter_shape=args.rerank_adapter_shape,
            adapter_timeout=args.adapter_timeout,
        )
        report, redaction_report = _sanitize_model_provider_report(report, args, config)
        _write_json_file(args.report_json, report)
        _write_json_file(args.redaction_report, redaction_report)
        _write_text_file(args.report_md, render_model_provider_probe_markdown(report))
        _dump_json(report)
        return 0 if report["ok"] else 1
    except (ConfigError, OSError, RuntimeError, ValueError) as exc:
        return _error(str(exc), json_output=args.json)


def build_inspect_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Markdown handoff and optional rich sidecars")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--report-json", help="Optional JSON inspection report path")
    parser.add_argument("--report-md", help="Optional Markdown inspection report path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_model_providers_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe RAGFlow model-provider registration without mutating KBs")
    subparsers = parser.add_subparsers(dest="model_providers_command", required=True)

    probe = subparsers.add_parser("probe", help="Probe read-only model-provider endpoints")
    probe.add_argument("--config", help="Runtime config file")
    probe.add_argument("--base-url", help="RAGFlow base URL")
    probe.add_argument("--api-key", help="RAGFlow API key")
    probe.add_argument("--timeout", type=float, help="HTTP timeout seconds")
    probe.add_argument("--endpoint", action="append", default=[], help="Provider endpoint path to probe; repeatable")
    probe.add_argument("--embedding-model", action="append", default=[], help="Expected embedding model name; repeatable")
    probe.add_argument("--rerank-model", action="append", default=[], help="Expected rerank model name; repeatable")
    probe.add_argument("--embedding-adapter-url", help="Explicit embedding adapter URL for empty-input request-shape probe")
    probe.add_argument("--embedding-adapter-api-key", help="Embedding adapter bearer token")
    probe.add_argument(
        "--embedding-adapter-shape",
        choices=("openai", "generic"),
        default="openai",
        help="Embedding adapter request shape",
    )
    probe.add_argument("--rerank-adapter-url", help="Explicit rerank adapter URL for empty-input request-shape probe")
    probe.add_argument("--rerank-adapter-api-key", help="Rerank adapter bearer token")
    probe.add_argument(
        "--rerank-adapter-shape",
        choices=("cohere", "generic"),
        default="cohere",
        help="Rerank adapter request shape",
    )
    probe.add_argument("--adapter-timeout", type=float, default=5.0, help="Adapter empty-input probe timeout seconds")
    probe.add_argument("--report-json", help="Optional JSON probe report path")
    probe.add_argument("--report-md", help="Optional Markdown probe report path")
    probe.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    probe.add_argument("--json", action="store_true", help="Emit JSON errors")
    probe.set_defaults(func=_run_model_providers_probe)

    return parser


def build_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, merge, and template public RAGFlow metadata")
    subparsers = parser.add_subparsers(dest="metadata_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_metadata_v1 file")
    lint.add_argument("--metadata", required=True, help="Metadata JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_metadata_lint)

    merge = subparsers.add_parser("merge", help="Merge path-derived, handoff, and user metadata")
    merge.add_argument("--doc-manifest", help="Optional doc_manifest.json")
    merge.add_argument("--handoff-metadata", help="Optional rich handoff metadata.json")
    merge.add_argument("--metadata", help="Optional user ragflow_metadata_v1 file")
    merge.add_argument("--output", required=True, help="Output merged ragflow_metadata_v1 JSON")
    merge.add_argument("--report-json", help="Optional JSON merge report path")
    merge.add_argument("--report-md", help="Optional Markdown merge report path")
    merge.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    merge.add_argument("--no-derive-from-path", action="store_true", help="Do not fill missing fields from document paths")
    merge.add_argument("--json", action="store_true", help="Emit JSON errors")
    merge.set_defaults(func=_run_metadata_merge)

    template = subparsers.add_parser("generate-template", help="Generate a user-editable metadata template")
    template.add_argument("--doc-manifest", help="Optional doc_manifest.json used to list document paths")
    template.add_argument("--output", required=True, help="Output metadata template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_metadata_generate_template)

    return parser


def build_tagset_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint, export, and report public RAGFlow tagsets")
    subparsers = parser.add_subparsers(dest="tagset_command", required=True)

    lint = subparsers.add_parser("lint", help="Lint a ragflow_tagset_v1 file")
    lint.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    lint.add_argument("--report-json", help="Optional JSON lint report path")
    lint.add_argument("--report-md", help="Optional Markdown lint report path")
    lint.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    lint.add_argument("--json", action="store_true", help="Emit JSON errors")
    lint.set_defaults(func=_run_tagset_lint)

    export = subparsers.add_parser("export", help="Export tagset tags as JSON or CSV")
    export.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    export.add_argument("--format", choices=("json", "csv"), default="json", help="Export format")
    export.add_argument("--output", required=True, help="Output JSON or CSV path")
    export.add_argument("--json", action="store_true", help="Emit JSON errors")
    export.set_defaults(func=_run_tagset_export)

    report = subparsers.add_parser("report", help="Report tag coverage, duplicates, and orphan warnings")
    report.add_argument("--tagset", required=True, help="Tagset JSON/YAML file")
    report.add_argument("--metadata", help="Optional metadata file for document coverage checks")
    report.add_argument("--report-json", help="Optional JSON report path")
    report.add_argument("--report-md", help="Optional Markdown report path")
    report.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_tagset_report)

    template = subparsers.add_parser("generate-template", help="Generate a placeholder tagset template")
    template.add_argument("--output", required=True, help="Output tagset template JSON")
    template.add_argument("--json", action="store_true", help="Emit JSON errors")
    template.set_defaults(func=_run_tagset_generate_template)

    return parser


def build_snapshot_chunks_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a stable chunk snapshot from local chunks or validation output")
    parser.add_argument("--input", required=True, help="Input validation/retrieval JSON report, Markdown file, or Markdown directory")
    parser.add_argument("--output", required=True, help="Output ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument("--name", default="chunk-snapshot", help="Chunk snapshot name")
    parser.add_argument("--description", help="Optional chunk snapshot description")
    parser.add_argument("--include-content", action="store_true", help="Include full chunk content in the snapshot")
    parser.add_argument("--report-json", help="Optional snapshot report JSON path")
    parser.add_argument("--report-md", help="Optional snapshot report Markdown path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_snapshot_chunks)
    return parser


def build_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import, sample, preflight, summarize, and gate benchmark artifacts")
    subparsers = parser.add_subparsers(dest="benchmark_command", required=True)

    import_cmd = subparsers.add_parser("import", help="Normalize query/qrels files into a benchmark directory")
    import_cmd.add_argument("--queries", required=True, help="Input benchmark query set JSON")
    import_cmd.add_argument("--qrels", required=True, help="Input benchmark qrels JSON")
    import_cmd.add_argument("--qa", help="Optional grounded QA JSON")
    import_cmd.add_argument("--output", required=True, help="Output benchmark directory")
    import_cmd.add_argument("--name", default="benchmark", help="Benchmark name recorded in manifest")
    import_cmd.add_argument("--description", help="Optional benchmark description")
    import_cmd.add_argument("--checkpoint", help="Checkpoint path for resumable benchmark imports")
    import_cmd.add_argument("--resume", action="store_true", help="Resume from an existing benchmark import checkpoint")
    import_cmd.add_argument("--batch-size", type=int, help="Import at most this many new queries in this run")
    import_cmd.add_argument("--report-json", help="Optional import report JSON path")
    import_cmd.add_argument("--report-md", help="Optional import report Markdown path")
    import_cmd.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    import_cmd.add_argument("--json", action="store_true", help="Emit JSON errors")
    import_cmd.set_defaults(func=_run_benchmark_import)

    preflight = subparsers.add_parser("preflight", help="Check benchmark artifacts before live validation")
    preflight.add_argument("--manifest", help="Benchmark manifest.json")
    preflight.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    preflight.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    preflight.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    preflight.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 file for expected_chunks checks")
    preflight.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    preflight.add_argument("--report-json", help="Optional preflight report JSON path")
    preflight.add_argument("--report-md", help="Optional preflight report Markdown path")
    preflight.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    preflight.add_argument("--json", action="store_true", help="Emit JSON errors")
    preflight.set_defaults(func=_run_benchmark_preflight)

    sample = subparsers.add_parser("sample", help="Create a deterministic benchmark subset")
    sample.add_argument("--manifest", help="Benchmark manifest.json")
    sample.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    sample.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    sample.add_argument("--qa", help="Optional grounded QA JSON when no manifest is provided")
    sample.add_argument("--output", required=True, help="Output sampled benchmark directory")
    sample.add_argument("--size", type=int, help="Number of queries to sample")
    sample.add_argument("--fraction", type=float, help="Fraction of queries to sample")
    sample.add_argument("--strategy", choices=("first", "random", "stratified"), default="stratified", help="Sampling strategy")
    sample.add_argument("--seed", type=int, default=0, help="Deterministic sampling seed")
    sample.add_argument("--name", default="benchmark-sample", help="Benchmark sample name recorded in manifest")
    sample.add_argument("--description", help="Optional benchmark sample description")
    sample.add_argument("--report-json", help="Optional sample report JSON path")
    sample.add_argument("--report-md", help="Optional sample report Markdown path")
    sample.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    sample.add_argument("--json", action="store_true", help="Emit JSON errors")
    sample.set_defaults(func=_run_benchmark_sample)

    summarize = subparsers.add_parser("summarize", help="Summarize an existing benchmark validation report")
    summarize.add_argument("--report", required=True, help="Benchmark validation report JSON")
    summarize.add_argument("--report-json", help="Optional summary report JSON path")
    summarize.add_argument("--report-md", help="Optional summary report Markdown path")
    summarize.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    summarize.add_argument("--json", action="store_true", help="Emit JSON errors")
    summarize.set_defaults(func=_run_benchmark_summarize)

    gate = subparsers.add_parser("gate", help="Apply a gate config to an existing benchmark validation report")
    gate.add_argument("--report", required=True, help="Benchmark validation report JSON")
    gate.add_argument("--gate-config", required=True, help="Benchmark gate threshold JSON")
    gate.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    gate.add_argument("--report-json", help="Optional gate report JSON path")
    gate.add_argument("--report-md", help="Optional gate report Markdown path")
    gate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    gate.add_argument("--json", action="store_true", help="Emit JSON errors")
    gate.set_defaults(func=_run_benchmark_gate)

    trend = subparsers.add_parser("trend", help="Compare current benchmark metrics with a baseline report")
    trend.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    trend.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    trend.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    trend.add_argument("--report-json", help="Optional trend report JSON path")
    trend.add_argument("--report-md", help="Optional trend report Markdown path")
    trend.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    trend.add_argument("--json", action="store_true", help="Emit JSON errors")
    trend.set_defaults(func=_run_benchmark_trend)

    delta = subparsers.add_parser("delta", help="Report metric deltas between two benchmark reports")
    delta.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    delta.add_argument("--baseline-report", required=True, help="Prior benchmark validation report JSON")
    delta.add_argument("--report-json", help="Optional delta report JSON path")
    delta.add_argument("--report-md", help="Optional delta report Markdown path")
    delta.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    delta.add_argument("--json", action="store_true", help="Emit JSON errors")
    delta.set_defaults(func=_run_benchmark_delta)

    suggest = subparsers.add_parser("suggest", help="Suggest retrieval parameter experiments from a benchmark report")
    suggest.add_argument("--report", required=True, help="Current benchmark validation report JSON")
    suggest.add_argument("--baseline-report", help="Optional prior benchmark validation report JSON")
    suggest.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    suggest.add_argument("--current-top-k", type=int, help="Current retrieval top_k, defaults to benchmark cutoff when available")
    suggest.add_argument("--current-similarity-threshold", type=float, help="Current retrieval similarity threshold")
    suggest.add_argument("--report-json", help="Optional suggestion report JSON path")
    suggest.add_argument("--report-md", help="Optional suggestion report Markdown path")
    suggest.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    suggest.add_argument("--json", action="store_true", help="Emit JSON errors")
    suggest.set_defaults(func=_run_benchmark_suggest)

    return parser


def build_suppression_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create advisory suppression candidates from an existing validation report")
    parser.add_argument("--report", required=True, help="Validation or benchmark validation report JSON")
    parser.add_argument("--tagset", help="Optional ragflow_tagset_v1 JSON/YAML for tag labels and aliases")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum candidates to include in the report")
    parser.add_argument("--report-json", help="Optional suppression report JSON path")
    parser.add_argument("--report-md", help="Optional suppression report Markdown path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_suppression_report)
    return parser


def build_qa_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and validate grounded QA artifacts before benchmark use")
    subparsers = parser.add_subparsers(dest="qa_command", required=True)

    generate = subparsers.add_parser("generate", help="Generate deterministic grounded QA from source spans")
    generate.add_argument("--sources", help="Optional source text JSON/Markdown file")
    generate.add_argument("--source-dir", help="Optional directory of source text files")
    generate.add_argument("--output", required=True, help="Output ragflow_grounded_qa_v1 JSON")
    generate.add_argument("--count", type=int, default=20, help="Maximum QA items to generate")
    generate.add_argument("--strategy", choices=("first", "random"), default="first", help="Source span selection strategy")
    generate.add_argument("--seed", type=int, default=0, help="Deterministic seed for random strategy")
    generate.add_argument("--min-span-chars", type=int, default=40, help="Minimum evidence span length")
    generate.add_argument("--max-span-chars", type=int, default=240, help="Maximum evidence span length")
    generate.add_argument("--checkpoint", help="Checkpoint path for resumable deterministic QA generation")
    generate.add_argument("--resume", action="store_true", help="Resume from an existing QA generation checkpoint")
    generate.add_argument("--batch-size", type=int, help="Generate at most this many new QA items in this run")
    generate.add_argument("--report-json", help="Optional generate report JSON path")
    generate.add_argument("--report-md", help="Optional generate report Markdown path")
    generate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    generate.add_argument("--json", action="store_true", help="Emit JSON errors")
    generate.set_defaults(func=_run_qa_generate)

    validate = subparsers.add_parser("validate", help="Validate grounded QA evidence spans")
    validate.add_argument("--qa", required=True, help="Grounded QA JSON")
    validate.add_argument("--sources", help="Optional source text JSON/Markdown file for exact evidence checks")
    validate.add_argument("--source-dir", help="Optional directory of source text files for exact evidence checks")
    validate.add_argument("--allow-missing-answer", action="store_true", help="Allow QA items without answers")
    validate.add_argument("--report-json", help="Optional validate report JSON path")
    validate.add_argument("--report-md", help="Optional validate report Markdown path")
    validate.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    validate.add_argument("--json", action="store_true", help="Emit JSON errors")
    validate.set_defaults(func=_run_qa_validate)

    map_evidence = subparsers.add_parser("map-evidence", help="Map QA evidence spans onto a chunk snapshot")
    map_evidence.add_argument("--qa", required=True, help="Grounded QA JSON")
    map_evidence.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    map_evidence.add_argument("--output", required=True, help="Output ragflow_grounded_qa_evidence_map_v1 JSON")
    map_evidence.add_argument("--report-json", help="Optional map-evidence report JSON path")
    map_evidence.add_argument("--report-md", help="Optional map-evidence report Markdown path")
    map_evidence.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    map_evidence.add_argument("--json", action="store_true", help="Emit JSON errors")
    map_evidence.set_defaults(func=_run_qa_map_evidence)

    return parser


def build_segment_metadata_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report segment provenance metadata coverage for chunk snapshots")
    subparsers = parser.add_subparsers(dest="segment_metadata_command", required=True)

    report = subparsers.add_parser("report", help="Report segment and metadata coverage in a chunk snapshot")
    report.add_argument("--chunk-snapshot", required=True, help="ragflow_chunk_snapshot_v1 JSON")
    report.add_argument("--metadata", help="Optional ragflow_metadata_v1 JSON/YAML for document coverage")
    report.add_argument("--segmentation-plan", help="Optional doc_segmentation_plan_v1 JSON")
    report.add_argument("--report-json", help="Optional segment metadata report JSON path")
    report.add_argument("--report-md", help="Optional segment metadata report Markdown path")
    report.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    report.add_argument("--json", action="store_true", help="Emit JSON errors")
    report.set_defaults(func=_run_segment_metadata_report)

    return parser


def build_optimize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan RAGFlow profile optimization experiments")
    parser.add_argument("--plan-only", action="store_true", help="Create an offline optimization plan without mutating RAGFlow")
    parser.add_argument("--execute", action="store_true", help="Build selected disposable KBs after exact live confirmation")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="Base RAGFlow dataset name used for disposable KB naming")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    parser.add_argument("--profile", action="append", default=[], help="Candidate profile JSON/YAML path; may be repeated")
    parser.add_argument("--profile-dir", action="append", default=[], help="Directory of candidate profile JSON/YAML files; may be repeated")
    parser.add_argument("--profile-set", action="append", default=[], help="ragflow_candidate_profile_set_v1 JSON/YAML; may be repeated")
    parser.add_argument("--recommendation", action="append", default=[], help="Generated candidate as language:doc_type, e.g. en:manual")
    parser.add_argument("--benchmark-manifest", help="Benchmark manifest.json produced by benchmark import/sample")
    parser.add_argument("--queries", help="Benchmark queries JSON when no manifest is provided")
    parser.add_argument("--qrels", help="Benchmark qrels JSON when no manifest is provided")
    parser.add_argument("--qa", help="Optional grounded QA JSON")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file used by build/validation")
    parser.add_argument("--tagset", help="Optional tagset reference recorded in the plan")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 for strict chunk recall")
    parser.add_argument("--gate-config", help="Optional benchmark gate threshold JSON")
    parser.add_argument("--baseline-report", help="Optional previous benchmark report JSON")
    parser.add_argument("--artifact-dir", default="optimization-artifacts", help="Planned experiment artifact directory")
    parser.add_argument("--run-id", help="Optional disposable KB run id; defaults to a deterministic hash")
    parser.add_argument("--top-k", type=int, default=3, help="Planned benchmark validation top_k")
    parser.add_argument("--metric-cutoff", type=int, help="Optional planned benchmark metric cutoff")
    parser.add_argument("--checkpoint", help="Checkpoint path for resumable offline optimization planning")
    parser.add_argument("--resume", action="store_true", help="Resume from an existing optimization planning checkpoint")
    parser.add_argument("--batch-size", type=int, help="Emit at most this many new optimization candidates in this run")
    parser.add_argument("--config", help="Runtime config file used only with --execute")
    parser.add_argument("--base-url", help="RAGFlow base URL used only with --execute")
    parser.add_argument("--api-key", help="RAGFlow API key used only with --execute")
    parser.add_argument("--confirm-live-build", action="store_true", help="Required with --execute to create disposable KBs")
    parser.add_argument("--confirm-kb-name", help="Required with --execute; must exactly match --kb-name")
    parser.add_argument("--confirm-run-id", help="Required with --execute; must exactly match the planned run_id")
    parser.add_argument("--no-parse", action="store_true", help="With --execute, upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="With --execute, do not wait for parse completion")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="With --execute, maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="With --execute, polling interval while waiting for parse completion")
    parser.add_argument("--output", default="optimization_plan.json", help="Output ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization plan Markdown path")
    parser.add_argument("--command-manifest-output", help="Optional dry-run command manifest for future live optimization execution")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize)
    return parser


def build_optimize_summarize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize profile optimization validation reports")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--report", action="append", default=[], help="Validation report JSON; defaults to paths in the plan")
    parser.add_argument("--output", default="profile_experiment_results.json", help="Output ragflow_profile_experiment_results_v1 JSON")
    parser.add_argument("--report-md", default="best_profile_report.md", help="Output best profile Markdown report")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_summarize)
    return parser


def build_optimize_cleanup_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating cleanup plan for profile optimization KBs")
    parser.add_argument("--plan", required=True, help="ragflow_optimization_plan_v1 JSON")
    parser.add_argument("--output", default="cleanup_plan.json", help="Output ragflow_optimization_cleanup_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional optimization cleanup plan Markdown path")
    parser.add_argument("--cleanup-script", default="scripts/cleanup.py", help="Cleanup script path recorded in generated commands")
    parser.add_argument("--config", help="Optional runtime config path recorded in generated execute commands")
    parser.add_argument("--require-manifests", action="store_true", help="Fail when candidate kb_manifest files are not available yet")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for generated reports")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_optimize_cleanup_plan)
    return parser


def build_topology_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create non-mutating KB topology advice")
    subparsers = parser.add_subparsers(dest="topology_command", required=True)

    advise = subparsers.add_parser("advise", help="Advise create, merge, split, or stage decisions")
    advise.add_argument("--input", help="Markdown file or directory")
    advise.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    advise.add_argument("--kb-name", required=True, help="Candidate RAGFlow dataset name")
    advise.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    advise.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    advise.add_argument("--route-config", help="Optional user-owned routing config for overlap checks")
    advise.add_argument(
        "--future-growth",
        choices=("low", "medium", "high"),
        default="medium",
        help="Expected future corpus growth for create-vs-merge advice",
    )
    advise.add_argument("--min-documents", type=int, default=3, help="Minimum documents for a standalone KB signal")
    advise.add_argument("--min-total-chars", type=int, default=1200, help="Minimum total Markdown chars for a standalone KB signal")
    advise.add_argument("--allow-blocked", action="store_true", help="Allow advice with a BLOCKED doc_manifest quality gate")
    advise.add_argument("--output", default="kb_topology_advice.json", help="Output kb_topology_advice_v1 JSON")
    advise.add_argument("--report-md", help="Optional topology advice Markdown path")
    advise.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    advise.add_argument("--json", action="store_true", help="Emit JSON errors")
    advise.set_defaults(func=_run_topology_advise)

    split_plan = subparsers.add_parser("split-plan", help="Plan advisory KB splits by local corpus signals")
    split_plan.add_argument("--input", help="Markdown file or directory")
    split_plan.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    split_plan.add_argument("--kb-name", required=True, help="Source or candidate RAGFlow dataset name")
    split_plan.add_argument("--metadata", help="Optional ragflow_metadata_v1 file")
    split_plan.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    split_plan.add_argument("--min-group-documents", type=int, default=1, help="Minimum documents for a standalone split group")
    split_plan.add_argument(
        "--min-group-estimated-chunks",
        type=int,
        default=1,
        help="Minimum estimated chunks for a standalone split group",
    )
    split_plan.add_argument("--allow-blocked", action="store_true", help="Allow planning with a BLOCKED doc_manifest quality gate")
    split_plan.add_argument("--output", default="kb_split_plan.json", help="Output kb_split_plan_v1 JSON")
    split_plan.add_argument("--report-md", help="Optional split plan Markdown path")
    split_plan.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    split_plan.add_argument("--json", action="store_true", help="Emit JSON errors")
    split_plan.set_defaults(func=_run_topology_split_plan)

    return parser


def build_activation_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a non-mutating KB route activation plan")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--doc-manifest", help="Optional source doc_manifest.json for content quality checks")
    parser.add_argument("--route-config", help="Optional user-owned routing config")
    parser.add_argument("--retrieval-hints", help="Optional rich handoff retrieval_hints.json")
    parser.add_argument("--chunk-snapshot", help="Optional ragflow_chunk_snapshot_v1 JSON")
    parser.add_argument("--centroid-index", help="Optional ragflow_route_centroid_index_v1 JSON")
    parser.add_argument("--route-tests", help="Optional route-test queries JSON")
    parser.add_argument("--min-documents", type=int, default=1, help="Minimum documents before activation")
    parser.add_argument("--min-chunks", type=int, default=1, help="Minimum chunks before activation")
    parser.add_argument("--output", default="kb_activation_plan.json", help="Output kb_activation_plan_v1 JSON")
    parser.add_argument("--report-md", help="Optional activation plan Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_activation_plan)
    return parser


def build_parse_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an offline parser performance and parse-state report")
    parser.add_argument("--kb-manifest", required=True, help="Local kb_manifest.json for the built KB")
    parser.add_argument("--documents-json", help="Optional user-supplied RAGFlow document list/status JSON")
    parser.add_argument("--parse-log", action="append", default=[], help="Optional parser progress log; may be repeated")
    parser.add_argument("--profile", help="Optional chunk profile JSON/YAML to review parser settings")
    parser.add_argument("--parser-config", help="Optional parser_config JSON sidecar; overrides profile parser_config in this report")
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="parse_report.json",
        help="Output ragflow_parse_report_v1 JSON",
    )
    parser.add_argument("--report-md", help="Optional parse report Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_parse_report)
    return parser


def build_health_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an offline aggregate KB health report")
    parser.add_argument("--kb-manifest", action="append", required=True, help="Local kb_manifest.json; may be repeated")
    parser.add_argument("--parse-report", action="append", default=[], help="Optional ragflow_parse_report_v1 JSON; may be repeated")
    parser.add_argument("--activation-plan", action="append", default=[], help="Optional kb_activation_plan_v1 JSON; may be repeated")
    parser.add_argument("--min-documents", type=int, default=1, help="Minimum documents before a KB is considered non-empty")
    parser.add_argument("--min-chunks", type=int, default=1, help="Minimum declared chunks before a KB is considered non-empty")
    parser.add_argument(
        "--expected-embedding-model",
        action="append",
        default=[],
        help="Expected embedding model for built KB manifests; repeatable",
    )
    parser.add_argument(
        "--report-json",
        "--output",
        dest="report_json",
        default="kb_health_report.json",
        help="Output ragflow_kb_health_report_v1 JSON",
    )
    parser.add_argument("--report-md", help="Optional KB health Markdown path")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    parser.set_defaults(func=_run_health_report)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a RAGFlow KB from Markdown")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="RAGFlow dataset name")
    parser.add_argument("--profile", required=True, help="Chunk profile JSON/YAML")
    parser.add_argument("--metadata", help="Optional ragflow_metadata_v1 file to summarize and lint before upload")
    parser.add_argument("--output", default="kb_manifest.json", help="Output kb_manifest.json path for non-dry-run builds")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without touching RAGFlow or writing kb_manifest.json")
    parser.add_argument("--no-parse", action="store_true", help="Upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for parse completion after triggering parse")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow upload when doc_manifest quality_gate.status is BLOCKED")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds while waiting for parse completion")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect-handoff":
            return _run_inspect_handoff(build_inspect_handoff_parser().parse_args(command_args))
        if command == "model-providers":
            model_provider_args = build_model_providers_parser().parse_args(command_args)
            return model_provider_args.func(model_provider_args)
        if command == "metadata":
            metadata_args = build_metadata_parser().parse_args(command_args)
            return metadata_args.func(metadata_args)
        if command == "tagset":
            tagset_args = build_tagset_parser().parse_args(command_args)
            return tagset_args.func(tagset_args)
        if command == "snapshot-chunks":
            snapshot_args = build_snapshot_chunks_parser().parse_args(command_args)
            return snapshot_args.func(snapshot_args)
        if command == "benchmark":
            benchmark_args = build_benchmark_parser().parse_args(command_args)
            return benchmark_args.func(benchmark_args)
        if command == "suppression-report":
            suppression_args = build_suppression_report_parser().parse_args(command_args)
            return suppression_args.func(suppression_args)
        if command == "qa":
            qa_args = build_qa_parser().parse_args(command_args)
            return qa_args.func(qa_args)
        if command == "segment-metadata":
            segment_metadata_args = build_segment_metadata_parser().parse_args(command_args)
            return segment_metadata_args.func(segment_metadata_args)
        if command == "topology":
            topology_args = build_topology_parser().parse_args(command_args)
            return topology_args.func(topology_args)
        if command == "activation-plan":
            activation_plan_args = build_activation_plan_parser().parse_args(command_args)
            return activation_plan_args.func(activation_plan_args)
        if command == "parse-report":
            parse_report_args = build_parse_report_parser().parse_args(command_args)
            return parse_report_args.func(parse_report_args)
        if command == "health-report":
            health_report_args = build_health_report_parser().parse_args(command_args)
            return health_report_args.func(health_report_args)
        if command == "optimize":
            if command_args and command_args[0] == "summarize":
                optimize_summary_args = build_optimize_summarize_parser().parse_args(command_args[1:])
                return optimize_summary_args.func(optimize_summary_args)
            if command_args and command_args[0] == "cleanup-plan":
                optimize_cleanup_args = build_optimize_cleanup_plan_parser().parse_args(command_args[1:])
                return optimize_cleanup_args.func(optimize_cleanup_args)
            optimize_args = build_optimize_parser().parse_args(command_args)
            return optimize_args.func(optimize_args)
    args = build_parser().parse_args(actual_argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
