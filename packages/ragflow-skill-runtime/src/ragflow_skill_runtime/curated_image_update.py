"""Curated image-text update planning and reporting for context-bound image assets.

Context-bound images only need to be retrievable together with their surrounding
text. This module assembles a fail-closed update plan from the asset upload plan,
the accepted canonical review record, and the accepted Markdown, and builds the
JSON-first execution report. It never talks to RAGFlow itself; the CLI performs
the gated mutation.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical_review import (
    CANONICAL_REVIEW_SCHEMA,
    _context_text,
    _fragment_sha256,
    _read_normalized_markdown,
    canonical_file_sha256,
    validate_canonical_review_record,
)
from .kb_build import (
    KB_ASSET_UPLOAD_PLAN_SCHEMA,
    BuildError,
    _now,
    _read_json_mapping,
    verify_image_transport_capability,
)

CURATED_IMAGE_UPDATE_PLAN_SCHEMA = "ragflow_curated_image_update_plan_v1"
CURATED_IMAGE_UPDATE_REPORT_SCHEMA = "ragflow_curated_image_update_report_v1"
CURATED_IMAGE_UPDATE_OPERATION = "curated_image_update"
CURATED_IMAGE_UPDATE_TRANSPORT = "json_put"
CURATED_IMAGE_UPDATE_ENDPOINT_CLASS = "document_detail"

_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.*?)\s*#*\s*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def verify_curated_image_transport_capability(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Require explicit capability evidence for the curated image-text update."""

    return verify_image_transport_capability(
        evidence,
        operation=CURATED_IMAGE_UPDATE_OPERATION,
        transport=CURATED_IMAGE_UPDATE_TRANSPORT,
        endpoint_class=CURATED_IMAGE_UPDATE_ENDPOINT_CLASS,
    )


def _nearest_heading_title(lines: Sequence[str], *, start_line: int) -> str | None:
    for index in range(min(start_line - 2, len(lines) - 1), -1, -1):
        match = _HEADING_RE.match(lines[index])
        if match:
            title = match.group("title").strip()
            return title or None
    return None


def compose_curated_chunk_text(accepted_text: str, *, context_selector: str) -> str | None:
    """Compose curated chunk text: nearest preceding heading plus the pinned lines."""

    selected = _context_text(accepted_text, context_selector)
    if selected is None:
        return None
    start = int(context_selector.split(":", 1)[1].split("-", 1)[0])
    heading = _nearest_heading_title(accepted_text.splitlines(), start_line=start)
    if heading:
        return f"{heading}\n\n{selected}"
    return selected


def build_curated_image_update_plan(
    *,
    asset_plan_path: str | Path,
    canonical_review_path: str | Path,
    accepted_markdown_path: str | Path,
) -> dict[str, Any]:
    """Assemble a non-mutating curated image-text update plan.

    Raises BuildError on any schema, binding, or hash mismatch so callers stay
    fail-closed before any RAGFlow mutation.
    """

    plan_path = Path(asset_plan_path)
    plan = _read_json_mapping(plan_path, label="asset_upload_plan")
    if plan.get("schema") != KB_ASSET_UPLOAD_PLAN_SCHEMA:
        raise BuildError(f"asset upload plan schema must be {KB_ASSET_UPLOAD_PLAN_SCHEMA}")

    review_path = Path(canonical_review_path)
    review = _read_json_mapping(review_path, label="canonical_review")
    try:
        validate_canonical_review_record(review)
    except RuntimeError as exc:
        raise BuildError(str(exc)) from exc
    if review.get("schema") != CANONICAL_REVIEW_SCHEMA or review.get("status") != "accepted":
        raise BuildError("curated image-text update requires an accepted ragflow_canonical_review_v1 record")

    planned_review = plan.get("canonical_review")
    if isinstance(planned_review, Mapping):
        recorded = str(planned_review.get("record_sha256") or "").strip().lower()
        if recorded and recorded != canonical_file_sha256(review_path):
            raise BuildError("canonical review record does not match the asset upload plan binding")

    markdown_path = Path(accepted_markdown_path)
    if not markdown_path.is_file():
        raise BuildError(f"accepted Markdown not found: {markdown_path}")
    accepted_block = review.get("markdown", {}).get("accepted", {})
    if isinstance(accepted_block, Mapping):
        expected_markdown_hash = str(accepted_block.get("sha256") or "").strip().lower()
        if expected_markdown_hash and canonical_file_sha256(markdown_path) != expected_markdown_hash:
            raise BuildError("accepted Markdown does not match the canonical review hash")
    accepted_text = _read_normalized_markdown(markdown_path)

    artifacts = plan.get("discovered_image_artifacts")
    if not isinstance(artifacts, list):
        raise BuildError("asset upload plan discovered_image_artifacts must be a list")

    assets: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        if artifact.get("ingestion_intent") != "context_bound":
            continue
        source_path = str(artifact.get("source_path") or artifact.get("raw_path") or "")
        identity = artifact.get("canonical_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        selector = str(identity.get("context_selector") or "").strip()
        context_hash = str(identity.get("context_sha256") or "").strip().lower()
        if not selector or not _SHA256_RE.fullmatch(context_hash):
            raise BuildError(f"context-bound asset lacks a pinned context selector and hash: {source_path}")
        if not artifact.get("exists") or not artifact.get("inside_handoff"):
            raise BuildError(f"context-bound asset is missing or outside the handoff root: {source_path}")
        curated_text = compose_curated_chunk_text(accepted_text, context_selector=selector)
        if curated_text is None:
            raise BuildError(f"asset context selector is outside the accepted Markdown: {source_path}")
        if _fragment_sha256(_context_text(accepted_text, selector) or "") != context_hash:
            raise BuildError(f"stale asset context hash for context-bound asset: {source_path}")
        assets.append(
            {
                "source_path": source_path,
                "sha256": artifact.get("sha256"),
                "mime_type": artifact.get("mime_type"),
                "canonical_name": identity.get("canonical_name"),
                "role": identity.get("role"),
                "source_reference": identity.get("source_reference"),
                "context_selector": selector,
                "context_sha256": context_hash,
                "curated_text": curated_text,
                "curated_text_sha256": _fragment_sha256(curated_text),
            }
        )

    return {
        "schema": CURATED_IMAGE_UPDATE_PLAN_SCHEMA,
        "created_at": _now(),
        "offline_only": True,
        "mutation": "none",
        "ragflow_calls": 0,
        "inputs": {
            "asset_upload_plan": str(plan_path),
            "canonical_review": str(review_path),
            "canonical_review_sha256": canonical_file_sha256(review_path),
            "accepted_markdown": str(markdown_path),
            "accepted_markdown_sha256": canonical_file_sha256(markdown_path),
        },
        "handoff_root": plan.get("handoff_root"),
        "status": "ready",
        "summary": {
            "planned_update_count": len(assets),
        },
        "assets": assets,
    }


def create_curated_image_update_report(
    *,
    plan: Mapping[str, Any],
    dataset_id: str,
    asset_results: Sequence[Mapping[str, Any]],
    transport_gates: Mapping[str, Any] | None = None,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON-first curated image-text update execution report."""

    results = [dict(item) for item in asset_results]
    updated = sum(1 for item in results if item.get("status") == "updated")
    failed = sum(1 for item in results if item.get("status") == "failed")
    warnings = sum(len(item.get("warnings") or []) for item in results)
    planned_count = len(plan.get("assets") or []) if isinstance(plan.get("assets"), list) else 0
    ok = failed == 0 and updated == planned_count
    report: dict[str, Any] = {
        "ok": ok,
        "schema": CURATED_IMAGE_UPDATE_REPORT_SCHEMA,
        "created_at": _now(),
        "mode": "execute",
        "mutation": CURATED_IMAGE_UPDATE_OPERATION,
        "mutation_allowed": True,
        "offline_only": False,
        "inputs": plan.get("inputs"),
        "dataset_id": dataset_id,
        "status": "completed" if ok else "partial_failure",
        "summary": {
            "planned_update_count": planned_count,
            "updated_asset_count": updated,
            "failed_asset_count": failed,
            "warning_count": warnings,
        },
        "assets": results,
    }
    if transport_gates is not None:
        report["transport_gates"] = dict(transport_gates)
    if checkpoint is not None:
        report["checkpoint"] = dict(checkpoint)
    return report


def render_curated_image_update_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise sanitized Markdown summary for a curated update report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Curated Image-Text Update Report",
        "",
        f"- status: `{report.get('status', 'unknown')}`",
        f"- dataset: `{report.get('dataset_id', '')}`",
        f"- planned updates: `{summary.get('planned_update_count', 0)}`",
        f"- updated assets: `{summary.get('updated_asset_count', 0)}`",
        f"- failed assets: `{summary.get('failed_asset_count', 0)}`",
        f"- warnings: `{summary.get('warning_count', 0)}`",
        "",
        "| asset | status | chunk |",
        "| --- | --- | --- |",
    ]
    assets = report.get("assets")
    if isinstance(assets, list):
        for item in assets:
            if isinstance(item, Mapping):
                lines.append(
                    "| {name} | {status} | {chunk} |".format(
                        name=item.get("canonical_name") or item.get("source_path") or "",
                        status=item.get("status") or "",
                        chunk=item.get("updated_chunk_id") or "-",
                    )
                )
    return "\n".join(lines) + "\n"


def chunk_content_sha256(content: str) -> str:
    """Return the SHA-256 digest used for prior chunk content lineage."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()
