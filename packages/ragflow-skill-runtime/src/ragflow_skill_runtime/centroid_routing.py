"""Offline centroid routing plan helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .manifests import ManifestError, load_kb_manifest
from .validation import ValidationError, load_chunk_snapshot


CENTROID_INDEX_SCHEMA = "ragflow_route_centroid_index_v1"
CENTROID_BUILD_PLAN_SCHEMA = "ragflow_route_centroid_build_plan_v1"


class CentroidRoutingError(RuntimeError):
    """Raised when centroid routing plan inputs are invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _stable_digest(values: list[str]) -> str:
    payload = "\n".join(sorted(values)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _centroid_id(dataset_id: str) -> str:
    digest = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:16]
    return f"centroid:{digest}"


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    path: str,
    recommendation: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
        "recommendation": recommendation,
    }


def _load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        manifest = load_kb_manifest(path)
    except ManifestError as exc:
        raise CentroidRoutingError(str(exc)) from exc
    declared_chunks = sum(document.chunk_count or 0 for document in manifest.documents)
    return {
        "dataset_id": manifest.dataset.id,
        "kb_name": manifest.dataset.name,
        "document_count": len(manifest.documents),
        "declared_chunk_count": declared_chunks,
        "path": str(path),
    }


def _chunk_dataset_id(chunk: Mapping[str, Any]) -> str | None:
    for key in ("dataset_id", "kb_id", "datasetId"):
        value = _string(chunk.get(key))
        if value:
            return value
    return None


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    value = chunk.get("content") or chunk.get("content_preview") or chunk.get("content_with_weight")
    return value if isinstance(value, str) else ""


def _load_snapshot(path: str | Path) -> dict[str, Any]:
    try:
        snapshot = load_chunk_snapshot(path)
    except ValidationError as exc:
        raise CentroidRoutingError(str(exc)) from exc
    chunks = [item for item in snapshot.get("chunks", []) if isinstance(item, Mapping)]
    by_dataset: dict[str | None, list[Mapping[str, Any]]] = {}
    for chunk in chunks:
        by_dataset.setdefault(_chunk_dataset_id(chunk), []).append(chunk)
    return {
        "path": str(path),
        "name": snapshot.get("name"),
        "summary": snapshot.get("summary") if isinstance(snapshot.get("summary"), Mapping) else {},
        "chunks": chunks,
        "by_dataset": by_dataset,
    }


def _embedding_config(
    *,
    provider: str | None,
    model: str | None,
    dimension: int | None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "configured": bool(model),
    }


def build_centroid_plan(
    *,
    kb_manifest_paths: list[str | Path] | None = None,
    chunk_snapshot_paths: list[str | Path] | None = None,
    index_output: str | Path | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    embedding_dimension: int | None = None,
    batch_size: int = 64,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Create a non-mutating centroid build plan from user-owned manifests/snapshots."""

    manifest_paths = list(kb_manifest_paths or [])
    snapshot_paths = list(chunk_snapshot_paths or [])
    if not manifest_paths and not snapshot_paths:
        raise CentroidRoutingError("at least one --kb-manifest or --chunk-snapshot is required")
    if batch_size <= 0:
        raise CentroidRoutingError("batch_size must be greater than zero")
    if embedding_dimension is not None and embedding_dimension <= 0:
        raise CentroidRoutingError("embedding_dimension must be greater than zero when provided")

    manifests = [_load_manifest(path) for path in manifest_paths]
    snapshots = [_load_snapshot(path) for path in snapshot_paths]
    datasets: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, str]] = []

    for manifest in manifests:
        dataset_id = manifest["dataset_id"]
        item = datasets.setdefault(
            dataset_id,
            {
                "dataset_id": dataset_id,
                "kb_name": manifest["kb_name"],
                "manifest_paths": [],
                "snapshot_paths": [],
                "document_count": 0,
                "declared_chunk_count": 0,
                "snapshot_chunk_count": 0,
                "chunks_with_content": 0,
                "stable_hashes": set(),
            },
        )
        item["kb_name"] = item.get("kb_name") or manifest["kb_name"]
        item["manifest_paths"].append(manifest["path"])
        item["document_count"] += manifest["document_count"]
        item["declared_chunk_count"] += manifest["declared_chunk_count"]

    single_manifest_dataset = manifests[0]["dataset_id"] if len(manifests) == 1 else None
    for snapshot in snapshots:
        for raw_dataset_id, chunks in snapshot["by_dataset"].items():
            dataset_id = raw_dataset_id or single_manifest_dataset
            if not dataset_id:
                dataset_id = f"unknown:{Path(snapshot['path']).stem}"
                issues.append(
                    _issue(
                        "warning",
                        "snapshot_missing_dataset_id",
                        "chunk snapshot has chunks without dataset_id and no single KB manifest to attach them to",
                        path=snapshot["path"],
                        recommendation="Regenerate the snapshot with dataset_id values or pass the matching KB manifest.",
                    )
                )
            item = datasets.setdefault(
                dataset_id,
                {
                    "dataset_id": dataset_id,
                    "kb_name": None,
                    "manifest_paths": [],
                    "snapshot_paths": [],
                    "document_count": 0,
                    "declared_chunk_count": 0,
                    "snapshot_chunk_count": 0,
                    "chunks_with_content": 0,
                    "stable_hashes": set(),
                },
            )
            if snapshot["path"] not in item["snapshot_paths"]:
                item["snapshot_paths"].append(snapshot["path"])
            item["snapshot_chunk_count"] += len(chunks)
            item["chunks_with_content"] += sum(1 for chunk in chunks if _chunk_content(chunk).strip())
            for chunk in chunks:
                stable_hash = _string(chunk.get("stable_hash"))
                if stable_hash:
                    item["stable_hashes"].add(stable_hash)

    if not datasets:
        raise CentroidRoutingError("centroid plan inputs did not contain any datasets or chunks")

    if not embedding_model:
        issues.append(
            _issue(
                "info",
                "embedding_model_not_configured",
                "plan-only run did not specify an embedding model",
                path="embedding.model",
                recommendation="Pass --embedding-model before executing a real centroid build.",
            )
        )

    dataset_items: list[dict[str, Any]] = []
    centroids: list[dict[str, Any]] = []
    for dataset_id, item in sorted(datasets.items()):
        stable_hashes = sorted(item["stable_hashes"])
        content_coverage = (
            round(float(item["chunks_with_content"]) / float(item["snapshot_chunk_count"]), 4)
            if item["snapshot_chunk_count"]
            else 0.0
        )
        ready = bool(item["snapshot_chunk_count"] and item["chunks_with_content"] and not dataset_id.startswith("unknown:"))
        if not item["snapshot_chunk_count"]:
            issues.append(
                _issue(
                    "warning",
                    "centroid_needs_chunk_snapshot",
                    "KB manifest is present but no chunk snapshot is available for centroid construction",
                    path=dataset_id,
                    recommendation="Create a chunk snapshot before executing centroid build.",
                )
            )
        elif content_coverage < 1.0:
            issues.append(
                _issue(
                    "warning",
                    "centroid_snapshot_missing_content",
                    "chunk snapshot has chunks without content; centroid quality may be incomplete",
                    path=dataset_id,
                    recommendation="Regenerate the snapshot with content included.",
                )
            )
        dataset_payload = {
            "dataset_id": dataset_id,
            "kb_name": item.get("kb_name"),
            "manifest_paths": list(item["manifest_paths"]),
            "snapshot_paths": list(item["snapshot_paths"]),
            "document_count": int(item["document_count"]),
            "declared_chunk_count": int(item["declared_chunk_count"]),
            "snapshot_chunk_count": int(item["snapshot_chunk_count"]),
            "chunks_with_content": int(item["chunks_with_content"]),
            "content_coverage": content_coverage,
            "ready_for_execution": ready,
        }
        dataset_items.append(dataset_payload)
        centroids.append(
            {
                "centroid_id": _centroid_id(dataset_id),
                "dataset_id": dataset_id,
                "kb_name": item.get("kb_name"),
                "chunk_count": int(item["snapshot_chunk_count"]),
                "content_coverage": content_coverage,
                "source_hash": _stable_digest(stable_hashes) if stable_hashes else None,
                "status": "planned" if ready else "needs_input",
                "source_paths": sorted(set(item["manifest_paths"] + item["snapshot_paths"])),
            }
        )

    ready_count = sum(1 for item in dataset_items if item["ready_for_execution"])
    embedding = _embedding_config(
        provider=embedding_provider,
        model=embedding_model,
        dimension=embedding_dimension,
    )
    return {
        "ok": True,
        "schema": CENTROID_BUILD_PLAN_SCHEMA,
        "mode": "plan-only",
        "plan_only": True,
        "created_at": _now(),
        "index_schema": CENTROID_INDEX_SCHEMA,
        "index_output": str(index_output) if index_output else None,
        "embedding": embedding,
        "execution": {
            "batch_size": batch_size,
            "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
            "resume": bool(resume),
        },
        "summary": {
            "kb_manifest_count": len(manifest_paths),
            "chunk_snapshot_count": len(snapshot_paths),
            "dataset_count": len(dataset_items),
            "planned_centroid_count": len(centroids),
            "ready_centroid_count": ready_count,
            "blocked_centroid_count": len(centroids) - ready_count,
            "chunk_count": sum(item["snapshot_chunk_count"] for item in dataset_items),
            "issue_count": len(issues),
            "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
            "infos": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "inputs": {
            "kb_manifests": [str(path) for path in manifest_paths],
            "chunk_snapshots": [str(path) for path in snapshot_paths],
        },
        "index_template": {
            "schema": CENTROID_INDEX_SCHEMA,
            "version": "0.1",
            "embedding": embedding,
            "centroids": [],
        },
        "datasets": dataset_items,
        "centroids": centroids,
        "issues": issues,
        "recommendations": [
            "Review this plan before running a real centroid build.",
            "Use centroids only as a tie-breaker after explicit hints and user-selected KBs.",
            "Keep centroid artifacts user-owned and out of public fixtures unless they are synthetic.",
        ],
    }


def write_centroid_plan(path: str | Path, report: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_centroid_plan_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Centroid Build Plan",
        "",
        f"- schema: `{report.get('schema', '')}`",
        f"- mode: `{report.get('mode', '')}`",
        f"- index_schema: `{report.get('index_schema', '')}`",
        f"- datasets: `{summary.get('dataset_count', 0)}`",
        f"- planned_centroids: `{summary.get('planned_centroid_count', 0)}`",
        f"- ready_centroids: `{summary.get('ready_centroid_count', 0)}`",
        f"- blocked_centroids: `{summary.get('blocked_centroid_count', 0)}`",
        f"- chunks: `{summary.get('chunk_count', 0)}`",
        "",
        "## Datasets",
        "",
    ]
    datasets = report.get("datasets", []) if isinstance(report.get("datasets"), list) else []
    if not datasets:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| dataset | KB | chunks | content coverage | ready |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for item in datasets:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| `{dataset_id}` | `{kb_name}` | {chunks} | {coverage:.2f} | `{ready}` |".format(
                    dataset_id=item.get("dataset_id", ""),
                    kb_name=item.get("kb_name") or "-",
                    chunks=int(item.get("snapshot_chunk_count", 0)),
                    coverage=float(item.get("content_coverage", 0.0)),
                    ready=str(bool(item.get("ready_for_execution"))).lower(),
                )
            )
    lines.extend(["", "## Issues", ""])
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if not issues:
        lines.append("- None")
    else:
        for issue in issues[:25]:
            if isinstance(issue, Mapping):
                lines.append(
                    "- `{severity}` `{code}` `{path}`: {message}".format(
                        severity=issue.get("severity", ""),
                        code=issue.get("code", ""),
                        path=issue.get("path", ""),
                        message=issue.get("message", ""),
                    )
                )
    return "\n".join(lines) + "\n"
