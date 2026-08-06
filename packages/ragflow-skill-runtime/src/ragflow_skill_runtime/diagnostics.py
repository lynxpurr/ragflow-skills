"""Safe RAGFlow KB diagnostics for public skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .kb_build import parse_state_failed, parse_state_succeeded
from .manifests import KbManifest
from .runtime_resilience import build_runtime_partial_failure_report


DIAGNOSTIC_REPORT_SCHEMA = "ragflow_kb_diagnostic_report_v1"
DIAGNOSTIC_RUNTIME_SUCCESS_STATUSES = ("success",)
DIAGNOSTIC_RUNTIME_WARNING_STATUSES = ("warning",)
DIAGNOSTIC_RUNTIME_FAILURE_STATUSES = ("error",)
SHORT_ID_MIN_LENGTH = 16
SUFFIX_FRAGMENT_RE = re.compile(r"\(\d+\)$")
HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


def _safe_probe_error_label(raw: str | None) -> str:
    if not raw:
        return "probe_error"
    http_match = HTTP_STATUS_RE.search(raw)
    if http_match:
        return f"HTTP {http_match.group(1)}"
    lowered = raw.lower()
    if "base url" in lowered or "config" in lowered:
        return "config_error"
    if "timeout" in lowered:
        return "timeout"
    if "http://" in lowered or "https://" in lowered or "/datasets" in lowered:
        return "endpoint_error"
    token = re.sub(r"[^A-Za-z0-9_ -]", "", raw.split(":", 1)[0]).strip()
    return token[:64] or "probe_error"


@dataclass(frozen=True)
class DiagnosticIssue:
    severity: str
    issue_type: str
    message: str
    recommendation: str | None = None
    dataset_id: str | None = None
    document_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": self.severity,
            "issue_type": self.issue_type,
            "message": self.message,
        }
        if self.recommendation:
            payload["recommendation"] = self.recommendation
        if self.dataset_id:
            payload["dataset_id"] = self.dataset_id
        if self.document_id:
            payload["document_id"] = self.document_id
        return payload


def _issue_counts(issues: list[DiagnosticIssue]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def _looks_short_id(value: str | None) -> bool:
    if not value:
        return True
    return len(value.strip()) < SHORT_ID_MIN_LENGTH or value.strip().endswith("...")


def _document_state(status: str | None, chunk_count: int | None) -> dict[str, Any]:
    return {
        "status": "" if status is None else str(status).strip().lower(),
        "chunk_count": chunk_count,
    }


def _dataset_items(response: Any) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping):
        return []
    data = response.get("data", response)
    if isinstance(data, Mapping):
        for key in ("datasets", "items", "list", "docs"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def review_kb_name_collision(
    kb_name: str,
    *,
    dataset_candidates: list[Mapping[str, Any]] | None = None,
    probe_performed: bool = False,
    probe_error: str | None = None,
) -> dict[str, Any]:
    """Create a sanitized advisory review for an intended KB name."""

    issues: list[dict[str, str]] = []
    suffix_pattern = re.compile(rf"^{re.escape(kb_name)}\(\d+\)$")
    if probe_error:
        error_type = _safe_probe_error_label(probe_error)
        issues.append(
            {
                "severity": "warning",
                "code": "kb_name_collision_probe_failed",
                "message": f"read-only dataset list probe failed ({error_type})",
                "recommendation": "Check endpoint config or manually confirm the intended KB name before live creation.",
            }
        )
        return {
            "kb_name": kb_name,
            "status": "probe_failed",
            "probe_performed": probe_performed,
            "review_required": True,
            "matching_dataset_count": 0,
            "suffix_match_count": 0,
            "suffix_match_names": [],
            "issues": issues,
            "safety": {
                "live_ragflow_mutation": "not_performed",
                "read_only_endpoint_probe": "attempted" if probe_performed else "failed",
                "dataset_ids_exposed": False,
            },
        }
    if not probe_performed:
        issues.append(
            {
                "severity": "warning",
                "code": "kb_name_collision_probe_not_requested",
                "message": "KB name collision probe was not requested for this dry-run",
                "recommendation": (
                    "Before live creation, either confirm the target name is unused in RAGFlow "
                    "or rerun dry-run with --probe-kb-name-collision and read-only endpoint config."
                ),
            }
        )
        return {
            "kb_name": kb_name,
            "status": "not_probed",
            "probe_performed": False,
            "review_required": True,
            "matching_dataset_count": 0,
            "suffix_match_count": 0,
            "suffix_match_names": [],
            "issues": issues,
            "safety": {
                "live_ragflow_mutation": "not_performed",
                "read_only_endpoint_probe": "not_requested",
                "dataset_ids_exposed": False,
            },
        }

    dataset_names = [
        str(item.get("name"))
        for item in dataset_candidates or []
        if isinstance(item.get("name"), str) and item.get("name")
    ]
    exact_matches = [name for name in dataset_names if name == kb_name]
    suffix_matches = sorted({name for name in dataset_names if suffix_pattern.search(name)})
    if exact_matches:
        issues.append(
            {
                "severity": "warning",
                "code": "kb_name_already_exists",
                "message": f"read-only probe found {len(exact_matches)} existing dataset name match for the requested KB name",
                "recommendation": (
                    "Choose a unique KB name or switch to an explicit append/rebuild flow; avoid relying on server-side suffixing."
                ),
            }
        )
    if suffix_matches:
        issues.append(
            {
                "severity": "warning",
                "code": "kb_name_suffix_collision_candidates",
                "message": "read-only probe found dataset names with duplicate suffix fragments for the requested KB name",
                "recommendation": "Confirm whether prior builds already created suffixed KBs before creating another dataset.",
            }
        )
    return {
        "kb_name": kb_name,
        "status": "review" if issues else "clear",
        "probe_performed": True,
        "review_required": bool(issues),
        "matching_dataset_count": len(exact_matches),
        "suffix_match_count": len(suffix_matches),
        "suffix_match_names": suffix_matches[:5],
        "issues": issues,
        "safety": {
            "live_ragflow_mutation": "not_performed",
            "read_only_endpoint_probe": "performed",
            "dataset_ids_exposed": False,
        },
    }


def _add_dataset_candidate_issues(
    issues: list[DiagnosticIssue],
    *,
    dataset_name: str,
    candidates: list[Mapping[str, Any]] | None,
) -> None:
    if not candidates:
        return
    exact = [item for item in candidates if item.get("name") == dataset_name]
    if len(exact) > 1:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                issue_type="duplicate_dataset_name",
                message=f"found {len(exact)} datasets with the exact name {dataset_name!r}",
                recommendation="Resolve KBs by explicit dataset ID before append, rebuild, or cleanup operations.",
            )
        )
    suffix_matches = [
        str(item.get("name"))
        for item in candidates
        if isinstance(item.get("name"), str) and SUFFIX_FRAGMENT_RE.search(str(item.get("name")))
    ]
    if suffix_matches:
        issues.append(
            DiagnosticIssue(
                severity="warning",
                issue_type="dataset_suffix_fragment",
                message=f"dataset names contain suffix fragments: {', '.join(suffix_matches[:5])}",
                recommendation="Confirm the intended dataset before building or validating; suffix fragments often indicate duplicate-name retries.",
            )
        )


def _diagnostic_runtime_partial_failure_report(
    *,
    operation: str,
    label: str,
    counts: Mapping[str, int],
) -> dict[str, Any]:
    if int(counts.get("error", 0) or 0) > 0:
        status = "error"
    elif int(counts.get("warning", 0) or 0) > 0:
        status = "warning"
    else:
        status = "success"
    return build_runtime_partial_failure_report(
        operation,
        [{"label": label, "status": status}],
        success_statuses=DIAGNOSTIC_RUNTIME_SUCCESS_STATUSES,
        warning_statuses=DIAGNOSTIC_RUNTIME_WARNING_STATUSES,
        failure_statuses=DIAGNOSTIC_RUNTIME_FAILURE_STATUSES,
        skipped_statuses=(),
    )


def diagnose_kb_manifest(
    manifest: KbManifest,
    *,
    live_states: Mapping[str, Mapping[str, Any]] | None = None,
    dataset_candidates: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a safe diagnostic report from a KB manifest and optional live state."""

    issues: list[DiagnosticIssue] = []
    dataset_id = manifest.dataset.id
    dataset_name = manifest.dataset.name
    if _looks_short_id(dataset_id):
        issues.append(
            DiagnosticIssue(
                severity="error",
                issue_type="dataset_id_short",
                message=f"dataset id looks missing, truncated, or unstable: {dataset_id!r}",
                recommendation="Use the full dataset ID from RAGFlow or a freshly produced kb_manifest.json.",
                dataset_id=dataset_id,
            )
        )
    if SUFFIX_FRAGMENT_RE.search(dataset_name):
        issues.append(
            DiagnosticIssue(
                severity="warning",
                issue_type="dataset_name_suffix_fragment",
                message=f"dataset name ends with a duplicate suffix fragment: {dataset_name!r}",
                recommendation="Confirm this is the intended KB before appending documents or comparing validation runs.",
                dataset_id=dataset_id,
            )
        )

    _add_dataset_candidate_issues(issues, dataset_name=dataset_name, candidates=dataset_candidates)

    states = live_states or {}
    for document in manifest.documents:
        document_id = document.document_id
        if _looks_short_id(document_id):
            issues.append(
                DiagnosticIssue(
                    severity="warning",
                    issue_type="document_id_short",
                    message=f"document id looks short or truncated: {document_id!r}",
                    recommendation="Use a manifest created by the current build command before parse or cleanup operations.",
                    dataset_id=dataset_id,
                    document_id=document_id,
                )
            )
        live = states.get(document_id, {})
        state = _document_state(
            str(live.get("status")) if live.get("status") is not None else document.status,
            live.get("chunk_count") if isinstance(live.get("chunk_count"), int) else document.chunk_count,
        )
        status = str(state.get("status") or "")
        chunk_count = state.get("chunk_count")
        if parse_state_failed(state):
            issues.append(
                DiagnosticIssue(
                    severity="error",
                    issue_type="document_parse_failed",
                    message=f"document parse failed or reported an error state: {status}",
                    recommendation="Inspect RAGFlow parse logs, embedding provider status, and source Markdown before retrying parse.",
                    dataset_id=dataset_id,
                    document_id=document_id,
                )
            )
        elif status in {"unstart", "unstarted", "pending", "queued", "running", "parsing", "0"}:
            issues.append(
                DiagnosticIssue(
                    severity="warning",
                    issue_type="document_parse_not_done",
                    message=f"document parse is not complete: {status}",
                    recommendation="Wait for parse completion or rerun inspect with --live before validating retrieval.",
                    dataset_id=dataset_id,
                    document_id=document_id,
                )
            )
        elif parse_state_succeeded(state) and chunk_count == 0:
            issues.append(
                DiagnosticIssue(
                    severity="warning",
                    issue_type="document_zero_chunks",
                    message="document appears parsed but has zero chunks",
                    recommendation="Check chunk profile, source Markdown content, parser settings, and embedding provider health.",
                    dataset_id=dataset_id,
                    document_id=document_id,
                )
            )

    counts = _issue_counts(issues)
    return {
        "schema": DIAGNOSTIC_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": counts["error"] == 0,
        "subject": {
            "dataset": {"id": dataset_id, "name": dataset_name},
            "document_count": len(manifest.documents),
        },
        "summary": counts,
        "issues": [issue.to_dict() for issue in issues],
    }


def probe_ragflow_client(client: Any, *, page_size: int = 50) -> dict[str, Any]:
    """Probe safe RAGFlow API surfaces without mutating server state."""

    issues: list[DiagnosticIssue] = []
    capabilities: dict[str, Any] = {
        "list_datasets": False,
        "dataset_count_sample": 0,
    }
    try:
        response = client.list_datasets(page=1, page_size=page_size)
        items = _dataset_items(response)
        capabilities["list_datasets"] = True
        capabilities["dataset_count_sample"] = len(items)
        for item in items:
            dataset_id = item.get("id") or item.get("dataset_id")
            if isinstance(dataset_id, str) and _looks_short_id(dataset_id):
                issues.append(
                    DiagnosticIssue(
                        severity="warning",
                        issue_type="dataset_id_short",
                        message=f"dataset list returned a short dataset id: {dataset_id!r}",
                        recommendation="Confirm RAGFlow is returning full dataset IDs before append/rebuild automation.",
                        dataset_id=dataset_id,
                    )
                )
    except Exception as exc:  # noqa: BLE001 - probe reports API failures as diagnostics.
        issues.append(
            DiagnosticIssue(
                severity="error",
                issue_type="list_datasets_failed",
                message=f"dataset list endpoint failed: {exc}",
                recommendation="Check RAGFlow base URL, API key, network path, and SSL settings.",
            )
        )

    counts = _issue_counts(issues)
    runtime_partial_failure = _diagnostic_runtime_partial_failure_report(
        operation=DIAGNOSTIC_REPORT_SCHEMA,
        label="list_datasets",
        counts=counts,
    )
    runtime_partial_summary = runtime_partial_failure["summary"]
    return {
        "schema": DIAGNOSTIC_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": counts["error"] == 0,
        "subject": {"base_url": getattr(getattr(client, "config", None), "base_url", None)},
        "summary": {
            **counts,
            "runtime_partial_failure_status": runtime_partial_summary["status"],
            "runtime_failure_count": runtime_partial_summary["failure_count"],
            "runtime_timeout_count": runtime_partial_summary["timeout_count"],
            "runtime_skipped_count": runtime_partial_summary["skipped_count"],
        },
        "runtime_partial_failure": runtime_partial_failure,
        "capabilities": capabilities,
        "issues": [issue.to_dict() for issue in issues],
    }


def render_diagnostic_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown diagnostic report."""

    subject = report.get("subject", {}) if isinstance(report.get("subject"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    runtime_partial = (
        report.get("runtime_partial_failure")
        if isinstance(report.get("runtime_partial_failure"), Mapping)
        else {}
    )
    runtime_partial_summary = (
        runtime_partial.get("summary")
        if isinstance(runtime_partial.get("summary"), Mapping)
        else {}
    )
    lines = [
        "# RAGFlow Diagnostic Report",
        "",
        f"- OK: `{str(report.get('ok', False)).lower()}`",
        f"- Errors: {summary.get('error', 0)}",
        f"- Warnings: {summary.get('warning', 0)}",
        f"- Infos: {summary.get('info', 0)}",
    ]
    if runtime_partial:
        lines.extend(
            [
                f"- runtime_partial_failure_status: `{runtime_partial_summary.get('status', 'unknown')}`",
                f"- runtime_partial_failure_partial: `{str(runtime_partial_summary.get('partial', False)).lower()}`",
                f"- runtime_failures: `{runtime_partial_summary.get('failure_count', 0)}`",
                f"- runtime_timeouts: `{runtime_partial_summary.get('timeout_count', 0)}`",
                f"- runtime_skipped: `{runtime_partial_summary.get('skipped_count', 0)}`",
            ]
        )
    lines.append("")
    dataset = subject.get("dataset") if isinstance(subject.get("dataset"), Mapping) else None
    if dataset:
        lines.extend(
            [
                f"- Dataset: `{dataset.get('name', '')}`",
                f"- Dataset ID: `{dataset.get('id', '')}`",
                "",
            ]
        )
    for issue in report.get("issues", []) if isinstance(report.get("issues"), list) else []:
        if not isinstance(issue, Mapping):
            continue
        lines.append(f"- `{issue.get('severity')}` `{issue.get('issue_type')}`: {issue.get('message')}")
        if issue.get("recommendation"):
            lines.append(f"  Recommendation: {issue.get('recommendation')}")
    return "\n".join(lines).rstrip() + "\n"
