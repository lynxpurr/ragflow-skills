"""Safe RAGFlow KB diagnostics for public skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .kb_build import parse_state_failed, parse_state_succeeded
from .manifests import KbManifest


DIAGNOSTIC_REPORT_SCHEMA = "ragflow_kb_diagnostic_report_v1"
SHORT_ID_MIN_LENGTH = 16
SUFFIX_FRAGMENT_RE = re.compile(r"\(\d+\)$")


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
    return {
        "schema": DIAGNOSTIC_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": counts["error"] == 0,
        "subject": {"base_url": getattr(getattr(client, "config", None), "base_url", None)},
        "summary": counts,
        "capabilities": capabilities,
        "issues": [issue.to_dict() for issue in issues],
    }


def render_diagnostic_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown diagnostic report."""

    subject = report.get("subject", {}) if isinstance(report.get("subject"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Diagnostic Report",
        "",
        f"- OK: `{str(report.get('ok', False)).lower()}`",
        f"- Errors: {summary.get('error', 0)}",
        f"- Warnings: {summary.get('warning', 0)}",
        f"- Infos: {summary.get('info', 0)}",
        "",
    ]
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
