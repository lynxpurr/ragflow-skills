#!/usr/bin/env python3
"""Audit version-bound RAGFlow parameter contracts from explicit source roots."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import sanitize_report_payload  # noqa: E402


SCHEMA = "ragflow_parameter_contract_audit_v1"
REQUIRED_SOURCE_FILES = (
    "api/utils/validation_utils.py",
    "api/apps/restful_apis/dataset_api.py",
    "api/apps/services/dataset_api_service.py",
    "rag/app/naive.py",
    "common/float_utils.py",
    "web/src/pages/dataset/dataset-setting/form-schema.ts",
    "web/src/pages/dataset/dataset-setting/configuration/common-item.tsx",
    "rag/svr/task_executor.py",
)
CLASSIFICATIONS = {
    "writable_contract_confirmed",
    "contract_conflict",
    "runtime_only_not_api_writable",
    "not_found",
    "audit_incomplete",
}

_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]{1,128}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9._/-]+:[A-Za-z0-9._+-]{1,128}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

_VALIDATION_PATH = "api/utils/validation_utils.py"
_ROUTE_PATH = "api/apps/restful_apis/dataset_api.py"
_SERVICE_PATH = "api/apps/services/dataset_api_service.py"
_NAIVE_PATH = "rag/app/naive.py"
_FLOAT_PATH = "common/float_utils.py"
_FRONTEND_SCHEMA_PATH = "web/src/pages/dataset/dataset-setting/form-schema.ts"
_FRONTEND_CONTROL_PATH = "web/src/pages/dataset/dataset-setting/configuration/common-item.tsx"
_EXECUTOR_PATH = "rag/svr/task_executor.py"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _issue(check: str, path: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"check": check, "path": path, "message": message, **extra}


def _validate_identities(
    *,
    deployment_version: str,
    deployment_image: str,
    deployment_image_digest: str,
    upstream_tag: str,
    upstream_commit: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    values = (
        ("deployment_version", deployment_version, _VERSION_RE),
        ("deployment_image", deployment_image, _IMAGE_RE),
        ("deployment_image_digest", deployment_image_digest, _DIGEST_RE),
        ("upstream_tag", upstream_tag, _VERSION_RE),
        ("upstream_commit", upstream_commit, _COMMIT_RE),
    )
    for key, value, pattern in values:
        if not pattern.fullmatch(str(value or "")):
            issues.append(
                _issue(
                    "invalid_contract_identity",
                    f"contract_identity.{key}",
                    f"{key} does not match the public contract identity format",
                )
            )
    return issues


def _read_required_sources(
    deployment_root: Path,
    upstream_root: Path,
) -> tuple[dict[str, str], dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    deployment_text: dict[str, str] = {}
    upstream_text: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for relative in REQUIRED_SOURCE_FILES:
        deployment_path = deployment_root / relative
        upstream_path = upstream_root / relative
        deployment_bytes: bytes | None = None
        upstream_bytes: bytes | None = None
        try:
            deployment_bytes = deployment_path.read_bytes()
            deployment_text[relative] = deployment_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(
                _issue(
                    "required_source_missing",
                    relative,
                    "deployment source is missing, unreadable, or not UTF-8",
                    source="deployment",
                    error_type=type(exc).__name__,
                )
            )
        try:
            upstream_bytes = upstream_path.read_bytes()
            upstream_text[relative] = upstream_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(
                _issue(
                    "required_source_missing",
                    relative,
                    "upstream source is missing, unreadable, or not UTF-8",
                    source="upstream",
                    error_type=type(exc).__name__,
                )
            )

        equal = deployment_bytes is not None and upstream_bytes is not None and deployment_bytes == upstream_bytes
        files.append(
            {
                "path": relative,
                "deployment_exists": deployment_bytes is not None,
                "upstream_exists": upstream_bytes is not None,
                "deployment_digest": _sha256(deployment_bytes) if deployment_bytes is not None else None,
                "upstream_digest": _sha256(upstream_bytes) if upstream_bytes is not None else None,
                "identical": equal,
            }
        )
        if deployment_bytes is not None and upstream_bytes is not None and not equal:
            issues.append(
                _issue(
                    "source_drift",
                    relative,
                    "deployment and upstream source digests differ",
                )
            )

    return deployment_text, upstream_text, files, issues


def _class_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _class_name(node.value)
    return ""


def _literal_keyword(call: ast.Call, name: str) -> Any:
    for keyword in call.keywords:
        if keyword.arg == name:
            try:
                return ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                return None
    return None


def _field_metadata(annotation: ast.expr) -> str | None:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Call) and _class_name(node.func) == "Field":
            return ast.unparse(node)
    return None


def _extract_request_model(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {}, [
            _issue(
                "request_model_parse_failed",
                _VALIDATION_PATH,
                "validation source could not be parsed as Python AST",
                line=exc.lineno,
            )
        ]

    classes: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields: dict[str, dict[str, Any]] = {}
        config: dict[str, Any] = {}
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                fields[statement.target.id] = {
                    "line": statement.lineno,
                    "annotation": ast.unparse(statement.annotation),
                    "default": (
                        ast.unparse(statement.value)
                        if statement.value is not None
                        else _field_metadata(statement.annotation)
                    ),
                }
            if (
                isinstance(statement, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "model_config" for target in statement.targets)
                and isinstance(statement.value, ast.Call)
                and _class_name(statement.value.func) == "ConfigDict"
            ):
                config = {
                    "extra": _literal_keyword(statement.value, "extra"),
                    "strict": _literal_keyword(statement.value, "strict"),
                    "line": statement.lineno,
                }
        classes[node.name] = {
            "bases": [_class_name(base) for base in node.bases],
            "fields": fields,
            "model_config": config,
            "line": node.lineno,
        }

    required_classes = {"Base", "AutoMetadataConfig", "ParserConfig", "CreateDatasetReq", "UpdateDatasetReq"}
    missing = sorted(required_classes - classes.keys())
    if missing:
        issues.append(
            _issue(
                "request_model_incomplete",
                _VALIDATION_PATH,
                "required request-model classes are missing",
                missing_classes=missing,
            )
        )

    base = classes.get("Base", {})
    parser = classes.get("ParserConfig", {})
    auto_metadata = classes.get("AutoMetadataConfig", {})
    create = classes.get("CreateDatasetReq", {})
    update = classes.get("UpdateDatasetReq", {})
    base_config = base.get("model_config", {}) if isinstance(base, Mapping) else {}
    result = {
        "strict_extra_forbid": base_config.get("extra") == "forbid" and base_config.get("strict") is True,
        "strict_extra_forbid_line": base_config.get("line"),
        "parser_config_fields": dict(parser.get("fields", {})) if isinstance(parser, Mapping) else {},
        "auto_metadata_fields": dict(auto_metadata.get("fields", {})) if isinstance(auto_metadata, Mapping) else {},
        "create_dataset_fields": dict(create.get("fields", {})) if isinstance(create, Mapping) else {},
        "update_inherits_create": "CreateDatasetReq" in update.get("bases", []) if isinstance(update, Mapping) else False,
        "update_dataset_line": update.get("line") if isinstance(update, Mapping) else None,
    }
    if not result["strict_extra_forbid"]:
        issues.append(
            _issue(
                "request_model_incomplete",
                _VALIDATION_PATH,
                "strict Base model extra=forbid and strict=true could not be established",
            )
        )
    return result, issues


def _rule(rule_id: str, path: str, text: str, needles: Sequence[str], *, require_all: bool = True) -> dict[str, Any]:
    lines: set[int] = set()
    matches: list[str] = []
    for needle in needles:
        needle_lines = [number for number, line in enumerate(text.splitlines(), start=1) if needle in line]
        if needle_lines:
            matches.append(needle)
            lines.update(needle_lines)
    matched = len(matches) == len(needles) if require_all else bool(matches)
    return {
        "rule": rule_id,
        "matched": matched,
        "path": path,
        "lines": sorted(lines),
        "matched_literals": matches,
    }


def _rule_in_window(
    rule_id: str,
    path: str,
    text: str,
    *,
    anchor: str,
    needles: Sequence[str],
    window_lines: int = 100,
) -> dict[str, Any]:
    source_lines = text.splitlines()
    anchor_lines = [number for number, line in enumerate(source_lines, start=1) if anchor in line]
    for anchor_line in anchor_lines:
        start = anchor_line - 1
        window = source_lines[start : start + window_lines]
        matched_lines: set[int] = set()
        matched_literals: list[str] = []
        for needle in needles:
            hits = [start + offset + 1 for offset, line in enumerate(window) if needle in line]
            if hits:
                matched_literals.append(needle)
                matched_lines.update(hits)
        if len(matched_literals) == len(needles):
            return {
                "rule": rule_id,
                "matched": True,
                "path": path,
                "lines": sorted({anchor_line, *matched_lines}),
                "matched_literals": matched_literals,
                "anchor_line": anchor_line,
            }
    return {
        "rule": rule_id,
        "matched": False,
        "path": path,
        "lines": anchor_lines,
        "matched_literals": [],
        "anchor_line": anchor_lines[0] if anchor_lines else None,
    }


def _evidence_rules(sources: Mapping[str, str], request_model: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    parser_fields = request_model.get("parser_config_fields", {})
    auto_fields = request_model.get("auto_metadata_fields", {})
    create_fields = request_model.get("create_dataset_fields", {})

    overlap_request = {
        "rule": "parser_config_overlapped_percent_declared",
        "matched": "overlapped_percent" in parser_fields,
        "path": _VALIDATION_PATH,
        "lines": [parser_fields["overlapped_percent"]["line"]] if "overlapped_percent" in parser_fields else [],
        "strict_extra_forbid": bool(request_model.get("strict_extra_forbid")),
        "field_contract": parser_fields.get("overlapped_percent"),
    }
    overlap_frontend_schema = _rule(
        "frontend_overlap_schema",
        _FRONTEND_SCHEMA_PATH,
        sources.get(_FRONTEND_SCHEMA_PATH, ""),
        ("overlapped_percent",),
    )
    overlap_frontend_control = _rule(
        "frontend_overlap_payload_path",
        _FRONTEND_CONTROL_PATH,
        sources.get(_FRONTEND_CONTROL_PATH, ""),
        ("parser_config.overlapped_percent",),
    )
    overlap_service = _rule(
        "service_forwards_parser_config",
        _SERVICE_PATH,
        sources.get(_SERVICE_PATH, ""),
        ('req.get("parser_config")',),
        require_all=False,
    )
    overlap_runtime = _rule(
        "markdown_runtime_consumes_overlap",
        _NAIVE_PATH,
        sources.get(_NAIVE_PATH, ""),
        ("normalize_overlapped_percent", 'parser_config.get("overlapped_percent"'),
    )
    overlap_normalizer = _rule(
        "overlap_normalizer_present",
        _FLOAT_PATH,
        sources.get(_FLOAT_PATH, ""),
        ("def normalize_overlapped_percent", "min(", "90"),
    )

    auto_request = {
        "rule": "auto_metadata_request_model",
        "matched": (
            "auto_metadata_config" in create_fields
            and {"metadata", "built_in_metadata"}.issubset(auto_fields)
            and bool(request_model.get("update_inherits_create"))
        ),
        "path": _VALIDATION_PATH,
        "lines": sorted(
            line
            for line in (
                (create_fields.get("auto_metadata_config") or {}).get("line"),
                (auto_fields.get("metadata") or {}).get("line"),
                (auto_fields.get("built_in_metadata") or {}).get("line"),
                request_model.get("update_dataset_line"),
            )
            if isinstance(line, int)
        ),
        "payload_level": "dataset.auto_metadata_config",
        "fields": ["metadata", "built_in_metadata"],
        "field_contract": create_fields.get("auto_metadata_config"),
        "nested_field_contracts": {
            "metadata": auto_fields.get("metadata"),
            "built_in_metadata": auto_fields.get("built_in_metadata"),
        },
    }
    required_auto_parser_fields = {"metadata", "built_in_metadata", "enable_metadata"}
    missing_auto_parser_fields = sorted(required_auto_parser_fields - set(parser_fields))
    auto_parser_contract = {
        "rule": "parser_config_auto_metadata_fields_declared",
        "matched": not missing_auto_parser_fields,
        "path": _VALIDATION_PATH,
        "lines": sorted(
            field["line"]
            for name, field in parser_fields.items()
            if name in required_auto_parser_fields and isinstance(field.get("line"), int)
        ),
        "strict_extra_forbid": bool(request_model.get("strict_extra_forbid")),
        "required_fields": sorted(required_auto_parser_fields),
        "missing_fields": missing_auto_parser_fields,
        "field_contracts": {
            name: parser_fields.get(name)
            for name in sorted(required_auto_parser_fields)
        },
    }
    auto_route = _rule(
        "dedicated_auto_metadata_routes",
        _ROUTE_PATH,
        sources.get(_ROUTE_PATH, ""),
        ('/metadata/config", methods=["GET"]', '/metadata/config", methods=["PUT"]', "AutoMetadataConfig"),
    )
    auto_legacy_mapping = _rule(
        "dataset_service_legacy_auto_metadata_mapping",
        _SERVICE_PATH,
        sources.get(_SERVICE_PATH, ""),
        ('auto_meta.get("fields"', 'auto_meta.get("enabled"'),
    )
    auto_dedicated_mapping = _rule(
        "dedicated_auto_metadata_persistence",
        _SERVICE_PATH,
        sources.get(_SERVICE_PATH, ""),
        ('cfg.get("metadata")', 'cfg.get("built_in_metadata")'),
    )
    auto_frontend_schema = _rule(
        "frontend_auto_metadata_parser_config_schema",
        _FRONTEND_SCHEMA_PATH,
        sources.get(_FRONTEND_SCHEMA_PATH, ""),
        ("metadata:", "built_in_metadata:", "enable_metadata:"),
    )
    auto_frontend_control = _rule(
        "frontend_auto_metadata_parser_config_payload",
        _FRONTEND_CONTROL_PATH,
        sources.get(_FRONTEND_CONTROL_PATH, ""),
        ("parser_config.metadata", "parser_config.built_in_metadata", "parser_config.enable_metadata"),
    )
    auto_runtime_gate = _rule(
        "metadata_runtime_gate",
        _EXECUTOR_PATH,
        sources.get(_EXECUTOR_PATH, ""),
        ("enable_metadata",),
    )
    auto_runtime_model = _rule_in_window(
        "metadata_runtime_model_dependency",
        _EXECUTOR_PATH,
        sources.get(_EXECUTOR_PATH, ""),
        anchor='get("enable_metadata", False)',
        needles=("LLMBundle",),
    )
    auto_runtime_async = _rule_in_window(
        "metadata_runtime_async_per_chunk",
        _EXECUTOR_PATH,
        sources.get(_EXECUTOR_PATH, ""),
        anchor='get("enable_metadata", False)',
        needles=("asyncio.create_task",),
    )

    return {
        "overlap_request": overlap_request,
        "overlap_frontend_schema": overlap_frontend_schema,
        "overlap_frontend_control": overlap_frontend_control,
        "overlap_service": overlap_service,
        "overlap_runtime": overlap_runtime,
        "overlap_normalizer": overlap_normalizer,
        "auto_request": auto_request,
        "auto_parser_contract": auto_parser_contract,
        "auto_route": auto_route,
        "auto_legacy_mapping": auto_legacy_mapping,
        "auto_dedicated_mapping": auto_dedicated_mapping,
        "auto_frontend_schema": auto_frontend_schema,
        "auto_frontend_control": auto_frontend_control,
        "auto_runtime_gate": auto_runtime_gate,
        "auto_runtime_model": auto_runtime_model,
        "auto_runtime_async": auto_runtime_async,
    }


def _candidate_reports(
    rules: Mapping[str, Mapping[str, Any]],
    *,
    request_model: Mapping[str, Any],
    source_integrity_ok: bool,
    audit_sources_complete: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not audit_sources_complete or not request_model:
        incomplete = [
            {
                "id": candidate_id,
                "ui_label": label,
                "classification": "audit_incomplete",
                "stage8c_eligible": False,
                "evidence_layers": {},
                "side_effects": {},
                "reason": "required contract source or request-model evidence is incomplete",
            }
            for candidate_id, label in (
                ("overlap_percent", "Overlapped percent"),
                ("automatic_metadata", "Automatic metadata"),
            )
        ]
        return incomplete, issues

    overlap_required = (
        rules["overlap_frontend_schema"]["matched"],
        rules["overlap_frontend_control"]["matched"],
        rules["overlap_service"]["matched"],
        rules["overlap_runtime"]["matched"],
        rules["overlap_normalizer"]["matched"],
    )
    overlap_request = bool(rules["overlap_request"]["matched"])
    strict_extra = bool(rules["overlap_request"].get("strict_extra_forbid"))
    if not all(overlap_required):
        overlap_classification = "audit_incomplete"
        issues.append(
            _issue(
                "candidate_evidence_incomplete",
                "candidates.overlap_percent",
                "one or more required overlap evidence layers are missing",
            )
        )
    elif overlap_request:
        overlap_classification = "writable_contract_confirmed"
    elif strict_extra:
        overlap_classification = "runtime_only_not_api_writable"
    else:
        overlap_classification = "not_found"
    overlap_eligible = overlap_classification == "writable_contract_confirmed" and source_integrity_ok
    overlap = {
        "id": "overlap_percent",
        "ui_label": "Overlapped percent",
        "classification": overlap_classification,
        "stage8c_eligible": overlap_eligible,
        "effective_field": "parser_config.overlapped_percent",
        "local_profile_field": "chunk_overlap",
        "local_profile_mapping": "not_equivalent_and_not_automatic",
        "evidence_layers": {
            "request_model": rules["overlap_request"],
            "frontend_payload": [rules["overlap_frontend_schema"], rules["overlap_frontend_control"]],
            "service_mapping": rules["overlap_service"],
            "runtime_consumer": [rules["overlap_runtime"], rules["overlap_normalizer"]],
        },
        "side_effects": {
            "model_provider_dependency": False,
            "cost_scope": "none_identified",
            "execution_scope": "deterministic_chunk_boundary_behavior",
            "activation_scope": "parse_or_reparse_required_for_effective_chunks",
            "metadata_governance": "not_applicable",
            "unresolved_gate": False,
        },
        "reason": (
            "frontend and Markdown runtime use parser_config.overlapped_percent, but the strict dataset ParserConfig does not declare it"
            if overlap_classification == "runtime_only_not_api_writable"
            else "classification derived from the complete version-bound evidence layers"
        ),
    }

    auto_required = (
        rules["auto_request"]["matched"],
        rules["auto_route"]["matched"],
        rules["auto_dedicated_mapping"]["matched"],
        rules["auto_frontend_schema"]["matched"],
        rules["auto_frontend_control"]["matched"],
        rules["auto_runtime_gate"]["matched"],
        rules["auto_runtime_model"]["matched"],
        rules["auto_runtime_async"]["matched"],
    )
    if not all(auto_required):
        auto_classification = "audit_incomplete"
        issues.append(
            _issue(
                "candidate_evidence_incomplete",
                "candidates.automatic_metadata",
                "one or more required automatic-metadata evidence layers are missing",
            )
        )
    elif rules["auto_legacy_mapping"]["matched"] or (
        rules["auto_parser_contract"].get("strict_extra_forbid")
        and not rules["auto_parser_contract"]["matched"]
    ):
        auto_classification = "contract_conflict"
    elif not rules["auto_parser_contract"]["matched"]:
        auto_classification = "audit_incomplete"
        issues.append(
            _issue(
                "candidate_evidence_incomplete",
                "candidates.automatic_metadata",
                "automatic-metadata ParserConfig acceptance could not be established",
            )
        )
    else:
        auto_classification = "writable_contract_confirmed"
    auto_side_effects = {
        "model_provider_dependency": bool(rules["auto_runtime_model"]["matched"]),
        "cost_scope": "potentially_billable",
        "execution_scope": "asynchronous_per_chunk_during_parse",
        "activation_scope": "parse_or_reparse_required",
        "metadata_governance": "generated_chunk_metadata",
        "unresolved_gate": True,
    }
    auto_eligible = (
        auto_classification == "writable_contract_confirmed"
        and source_integrity_ok
        and not auto_side_effects["unresolved_gate"]
    )
    automatic_metadata = {
        "id": "automatic_metadata",
        "ui_label": "Automatic metadata",
        "classification": auto_classification,
        "stage8c_eligible": auto_eligible,
        "effective_field": None,
        "evidence_layers": {
            "request_model": [rules["auto_request"], rules["auto_parser_contract"]],
            "frontend_payload": [rules["auto_frontend_schema"], rules["auto_frontend_control"]],
            "service_mapping": [rules["auto_legacy_mapping"], rules["auto_dedicated_mapping"]],
            "runtime_consumer": [rules["auto_runtime_gate"], rules["auto_runtime_model"], rules["auto_runtime_async"]],
            "dedicated_route": rules["auto_route"],
        },
        "side_effects": auto_side_effects,
        "reason": (
            "request and dedicated-route metadata/built_in_metadata fields conflict with legacy fields/enabled create-update mapping and parser_config frontend payloads"
            if auto_classification == "contract_conflict"
            else "classification derived from the complete version-bound evidence layers"
        ),
    }
    return [overlap, automatic_metadata], issues


def audit_parameter_contract(
    *,
    deployment_root: str | Path,
    upstream_root: str | Path,
    deployment_version: str,
    deployment_image: str,
    deployment_image_digest: str,
    upstream_tag: str,
    upstream_commit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit two explicit RAGFlow source roots without network or service access."""

    deployment_path = Path(deployment_root).resolve()
    upstream_path = Path(upstream_root).resolve()
    identity_issues = _validate_identities(
        deployment_version=deployment_version,
        deployment_image=deployment_image,
        deployment_image_digest=deployment_image_digest,
        upstream_tag=upstream_tag,
        upstream_commit=upstream_commit,
    )
    issues = list(identity_issues)
    deployment_sources, _upstream_sources, file_reports, source_issues = _read_required_sources(
        deployment_path,
        upstream_path,
    )
    issues.extend(source_issues)
    sources_complete = len(deployment_sources) == len(REQUIRED_SOURCE_FILES) and all(
        item["deployment_exists"] and item["upstream_exists"] for item in file_reports
    )
    integrity_ok = sources_complete and all(item["identical"] for item in file_reports)

    request_model: dict[str, Any] = {}
    if _VALIDATION_PATH in deployment_sources:
        request_model, model_issues = _extract_request_model(deployment_sources[_VALIDATION_PATH])
        issues.extend(model_issues)
    rules = _evidence_rules(deployment_sources, request_model) if deployment_sources else {}
    candidates, candidate_issues = _candidate_reports(
        rules,
        request_model=request_model,
        source_integrity_ok=integrity_ok and not identity_issues,
        audit_sources_complete=sources_complete,
    )
    issues.extend(candidate_issues)
    status_counts = Counter(item["classification"] for item in candidates)
    stage8c_count = sum(1 for item in candidates if item.get("stage8c_eligible"))
    raw_report = {
        "schema": SCHEMA,
        "ok": not issues,
        "contract_identity": {
            "deployment": {
                "version": deployment_version,
                "image": deployment_image,
                "image_digest": deployment_image_digest,
                "source": "deployed_image_source",
            },
            "upstream": {
                "tag": upstream_tag,
                "commit": upstream_commit,
                "source": "upstream_tag_source",
            },
        },
        "source_integrity": {
            "required_file_count": len(REQUIRED_SOURCE_FILES),
            "complete_file_pair_count": sum(
                1 for item in file_reports if item["deployment_exists"] and item["upstream_exists"]
            ),
            "identical_file_pair_count": sum(1 for item in file_reports if item["identical"]),
            "all_required_files_identical": integrity_ok,
            "files": file_reports,
        },
        "request_model_summary": request_model,
        "candidates": candidates,
        "summary": {
            "candidate_count": len(candidates),
            "classification_counts": dict(sorted(status_counts.items())),
            "stage8c_eligible_candidate_count": stage8c_count,
            "stage8c_eligible": stage8c_count > 0,
            "issue_count": len(issues),
        },
        "safety": {
            "network_calls": 0,
            "ragflow_calls": 0,
            "writes_live_ragflow": False,
            "script_owned_llm_calls": 0,
            "raw_chunks_included": False,
            "source_roots_disclosed": False,
        },
        "issues": issues,
    }
    sanitized, redaction = sanitize_report_payload(
        raw_report,
        home_paths=[str(deployment_path), str(upstream_path)],
        config_paths=[str(deployment_path), str(upstream_path)],
    )
    return sanitized, redaction


def _bool_text(value: Any) -> str:
    return str(bool(value)).lower()


def render_markdown(report: Mapping[str, Any]) -> str:
    identity = report.get("contract_identity", {}) if isinstance(report.get("contract_identity"), Mapping) else {}
    deployment = identity.get("deployment", {}) if isinstance(identity.get("deployment"), Mapping) else {}
    upstream = identity.get("upstream", {}) if isinstance(identity.get("upstream"), Mapping) else {}
    integrity = report.get("source_integrity", {}) if isinstance(report.get("source_integrity"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Parameter Contract Audit",
        "",
        f"- schema: `{report.get('schema', SCHEMA)}`",
        f"- audit complete: `{_bool_text(report.get('ok'))}`",
        f"- deployment version: `{deployment.get('version') or '-'}`",
        f"- deployment image: `{deployment.get('image') or '-'}`",
        f"- deployment image digest: `{deployment.get('image_digest') or '-'}`",
        f"- upstream tag: `{upstream.get('tag') or '-'}`",
        f"- upstream commit: `{upstream.get('commit') or '-'}`",
        f"- required files identical: `{_bool_text(integrity.get('all_required_files_identical'))}`",
        f"- Stage 8C eligible: `{_bool_text(summary.get('stage8c_eligible'))}`",
        "",
        "## Candidate Classification",
        "",
        "| Candidate | Classification | Stage 8C Eligible | Reason |",
        "| --- | --- | --- | --- |",
    ]
    candidates = report.get("candidates", []) if isinstance(report.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        reason = str(candidate.get("reason") or "").replace("|", "\\|")
        lines.append(
            f"| `{candidate.get('id')}` | `{candidate.get('classification')}` | "
            f"`{_bool_text(candidate.get('stage8c_eligible'))}` | {reason} |"
        )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        lines.extend(["", f"### {candidate.get('ui_label') or candidate.get('id')}", ""])
        layers = candidate.get("evidence_layers", {}) if isinstance(candidate.get("evidence_layers"), Mapping) else {}
        for layer, evidence in layers.items():
            entries = evidence if isinstance(evidence, list) else [evidence]
            states = []
            for entry in entries:
                if isinstance(entry, Mapping):
                    states.append(f"{entry.get('rule')}: {_bool_text(entry.get('matched'))}")
            lines.append(f"- `{layer}`: " + ("; ".join(states) if states else "not established"))
        side_effects = candidate.get("side_effects", {}) if isinstance(candidate.get("side_effects"), Mapping) else {}
        if side_effects:
            lines.append(
                "- side effects: model/provider `{}`, cost `{}`, execution `{}`, activation `{}`, governance `{}`, unresolved gate `{}`".format(
                    _bool_text(side_effects.get("model_provider_dependency")),
                    side_effects.get("cost_scope"),
                    side_effects.get("execution_scope"),
                    side_effects.get("activation_scope"),
                    side_effects.get("metadata_governance"),
                    _bool_text(side_effects.get("unresolved_gate")),
                )
            )
    lines.extend(["", "## Source Integrity", ""])
    files = integrity.get("files", []) if isinstance(integrity.get("files"), list) else []
    for item in files:
        if isinstance(item, Mapping):
            lines.append(
                f"- `{item.get('path')}` identical `{_bool_text(item.get('identical'))}`; "
                f"deployment `{item.get('deployment_digest') or '-'}`; upstream `{item.get('upstream_digest') or '-'}`"
            )
    lines.extend(["", "## Issues", ""])
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if not issues:
        lines.append("- none")
    for issue in issues:
        if isinstance(issue, Mapping):
            lines.append(f"- `{issue.get('check')}` `{issue.get('path')}`: {issue.get('message')}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- offline source audit only",
            "- no RAGFlow API call or mutation",
            "- no script-owned LLM call",
            "- no raw chunks, dataset identifiers, KB names, credentials, endpoints, or source roots retained",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write(path_value: str | None, content: str) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit version-bound RAGFlow parameter contracts offline")
    parser.add_argument("--deployment-root", required=True, help="Explicit deployed RAGFlow source root")
    parser.add_argument("--upstream-root", required=True, help="Explicit pinned upstream RAGFlow source root")
    parser.add_argument("--deployment-version", required=True, help="Public deployed RAGFlow version label")
    parser.add_argument("--deployment-image", required=True, help="Public deployed RAGFlow image tag")
    parser.add_argument("--deployment-image-digest", required=True, help="Deployed OCI image sha256 digest")
    parser.add_argument("--upstream-tag", required=True, help="Pinned upstream RAGFlow tag")
    parser.add_argument("--upstream-commit", required=True, help="Pinned upstream 40-hex commit")
    parser.add_argument("--report-json", help="Optional JSON report output")
    parser.add_argument("--report-md", help="Optional Markdown report output")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar output")
    args = parser.parse_args(argv)

    report, redaction = audit_parameter_contract(
        deployment_root=args.deployment_root,
        upstream_root=args.upstream_root,
        deployment_version=args.deployment_version,
        deployment_image=args.deployment_image,
        deployment_image_digest=args.deployment_image_digest,
        upstream_tag=args.upstream_tag,
        upstream_commit=args.upstream_commit,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    _write(args.report_json, rendered)
    _write(args.report_md, render_markdown(report))
    if args.redaction_report:
        _write(args.redaction_report, json.dumps(redaction, ensure_ascii=False, indent=2) + "\n")
    print(rendered, end="")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
