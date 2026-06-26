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
CENTROID_BUILD_REPORT_SCHEMA = "ragflow_route_centroid_build_report_v1"
CENTROID_BUILD_CHECKPOINT_SCHEMA = "ragflow_route_centroid_build_checkpoint_v1"


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


def _chunk_embedding(chunk: Mapping[str, Any]) -> list[float] | None:
    for key in ("embedding", "embedding_vector", "vector"):
        value = chunk.get(key)
        if isinstance(value, list) and value:
            vector: list[float] = []
            for item in value:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    return None
                vector.append(float(item))
            return vector
    return None


def _chunk_key(dataset_id: str, chunk: Mapping[str, Any]) -> str:
    for key in ("stable_hash", "chunk_id", "id", "source_chunk_id"):
        value = _string(chunk.get(key))
        if value:
            return f"{dataset_id}:{key}:{value}"
    content = _chunk_content(chunk)
    if content:
        return f"{dataset_id}:content:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
    return f"{dataset_id}:chunk:{hashlib.sha256(json.dumps(dict(chunk), sort_keys=True, default=str).encode('utf-8')).hexdigest()}"


def _chunk_source_hash(chunk: Mapping[str, Any]) -> str:
    stable_hash = _string(chunk.get("stable_hash"))
    if stable_hash:
        return stable_hash
    content = _chunk_content(chunk)
    payload = content if content else json.dumps(dict(chunk), sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _read_checkpoint(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CentroidRoutingError(f"checkpoint not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CentroidRoutingError(f"checkpoint is not valid JSON: {path}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != CENTROID_BUILD_CHECKPOINT_SCHEMA:
        raise CentroidRoutingError(f"checkpoint schema must be {CENTROID_BUILD_CHECKPOINT_SCHEMA}")
    return dict(payload)


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _number_vector(value: Any, *, field_name: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise CentroidRoutingError(f"{field_name} must be a non-empty numeric vector")
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise CentroidRoutingError(f"{field_name} must be a numeric vector")
        vector.append(float(item))
    return vector


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item.strip()}


def _checkpoint_processed_keys(checkpoint: Mapping[str, Any]) -> set[str]:
    value = checkpoint.get("processed_chunk_keys")
    if not isinstance(value, list):
        raise CentroidRoutingError("checkpoint processed_chunk_keys must be a list")
    return {item for item in value if isinstance(item, str) and item.strip()}


def _checkpoint_dataset_state(checkpoint: Mapping[str, Any], *, dimension: int | None) -> dict[str, dict[str, Any]]:
    raw = checkpoint.get("datasets", {})
    if not isinstance(raw, Mapping):
        raise CentroidRoutingError("checkpoint datasets must be an object")
    state: dict[str, dict[str, Any]] = {}
    for dataset_id, item in raw.items():
        if not isinstance(dataset_id, str) or not isinstance(item, Mapping):
            continue
        vector_sum = _number_vector(item.get("vector_sum"), field_name=f"checkpoint.datasets.{dataset_id}.vector_sum")
        if dimension is not None and len(vector_sum) != dimension:
            raise CentroidRoutingError(
                f"checkpoint dataset {dataset_id!r} vector dimension {len(vector_sum)} does not match {dimension}"
            )
        state[dataset_id] = {
            "dataset_id": dataset_id,
            "kb_name": _string(item.get("kb_name")),
            "chunk_count": int(item.get("chunk_count", 0) or 0),
            "vector_sum": vector_sum,
            "source_hashes": _string_set(item.get("source_hashes")),
            "source_paths": _string_set(item.get("source_paths")),
        }
    return state


def _embedding_from_checkpoint(checkpoint: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not checkpoint:
        return {}
    embedding = checkpoint.get("embedding")
    return embedding if isinstance(embedding, Mapping) else {}


def _resolve_embedding_config(
    *,
    checkpoint: Mapping[str, Any] | None,
    provider: str | None,
    model: str | None,
    dimension: int | None,
) -> dict[str, Any]:
    checkpoint_embedding = _embedding_from_checkpoint(checkpoint)
    checkpoint_provider = _string(checkpoint_embedding.get("provider"))
    checkpoint_model = _string(checkpoint_embedding.get("model"))
    checkpoint_dimension = checkpoint_embedding.get("dimension")
    if isinstance(checkpoint_dimension, bool) or not isinstance(checkpoint_dimension, int):
        checkpoint_dimension = None

    if checkpoint_provider and provider and checkpoint_provider != provider:
        raise CentroidRoutingError(
            f"checkpoint embedding provider {checkpoint_provider!r} does not match requested provider {provider!r}"
        )
    if checkpoint_model and model and checkpoint_model != model:
        raise CentroidRoutingError(
            f"checkpoint embedding model {checkpoint_model!r} does not match requested model {model!r}"
        )
    if checkpoint_dimension and dimension and checkpoint_dimension != dimension:
        raise CentroidRoutingError(
            f"checkpoint embedding dimension {checkpoint_dimension} does not match requested dimension {dimension}"
        )

    return _embedding_config(
        provider=provider or checkpoint_provider,
        model=model or checkpoint_model,
        dimension=dimension or checkpoint_dimension,
    )


def _dataset_item(
    datasets: dict[str, dict[str, Any]],
    dataset_id: str,
    *,
    kb_name: str | None = None,
) -> dict[str, Any]:
    item = datasets.setdefault(
        dataset_id,
        {
            "dataset_id": dataset_id,
            "kb_name": kb_name,
            "manifest_paths": [],
            "snapshot_paths": [],
            "snapshot_chunk_count": 0,
            "eligible_chunk_count": 0,
            "skipped_missing_embedding_count": 0,
            "processed_chunk_count": 0,
        },
    )
    if kb_name and not item.get("kb_name"):
        item["kb_name"] = kb_name
    return item


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


def build_centroid_index(
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
    """Build a bounded, resumable centroid index from snapshot-owned embeddings."""

    manifest_paths = list(kb_manifest_paths or [])
    snapshot_paths = list(chunk_snapshot_paths or [])
    if not snapshot_paths:
        raise CentroidRoutingError("at least one --chunk-snapshot is required for centroid build execution")
    if not index_output:
        raise CentroidRoutingError("--index-output is required for centroid build execution")
    if not checkpoint_path:
        raise CentroidRoutingError("--checkpoint is required for bounded centroid build execution")
    if batch_size <= 0:
        raise CentroidRoutingError("batch_size must be greater than zero")
    if embedding_dimension is not None and embedding_dimension <= 0:
        raise CentroidRoutingError("embedding_dimension must be greater than zero when provided")

    checkpoint_file = Path(checkpoint_path)
    checkpoint = _read_checkpoint(checkpoint_file) if resume else None
    embedding = _resolve_embedding_config(
        checkpoint=checkpoint,
        provider=embedding_provider,
        model=embedding_model,
        dimension=embedding_dimension,
    )
    effective_dimension = embedding.get("dimension")
    if isinstance(effective_dimension, bool) or not isinstance(effective_dimension, int):
        effective_dimension = None

    processed_keys = _checkpoint_processed_keys(checkpoint) if checkpoint else set()
    dataset_state = _checkpoint_dataset_state(checkpoint, dimension=effective_dimension) if checkpoint else {}
    created_at = _string(checkpoint.get("created_at")) if checkpoint else None
    now = _now()

    manifests = [_load_manifest(path) for path in manifest_paths]
    snapshots = [_load_snapshot(path) for path in snapshot_paths]
    manifest_names = {manifest["dataset_id"]: manifest["kb_name"] for manifest in manifests}
    datasets: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, str]] = []

    for manifest in manifests:
        item = _dataset_item(datasets, manifest["dataset_id"], kb_name=manifest["kb_name"])
        item["manifest_paths"].append(manifest["path"])

    if not embedding.get("model"):
        issues.append(
            _issue(
                "info",
                "embedding_model_not_configured",
                "centroid build is using snapshot vectors without an embedding model label",
                path="embedding.model",
                recommendation="Pass --embedding-model to make centroid artifacts easier to audit.",
            )
        )

    single_manifest_dataset = manifests[0]["dataset_id"] if len(manifests) == 1 else None
    candidates: list[dict[str, Any]] = []
    eligible_keys: set[str] = set()
    duplicate_chunk_count = 0

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
            item = _dataset_item(datasets, dataset_id, kb_name=manifest_names.get(dataset_id))
            if snapshot["path"] not in item["snapshot_paths"]:
                item["snapshot_paths"].append(snapshot["path"])
            item["snapshot_chunk_count"] += len(chunks)

            for chunk in chunks:
                vector = _chunk_embedding(chunk)
                if vector is None:
                    item["skipped_missing_embedding_count"] += 1
                    continue
                if effective_dimension is None:
                    effective_dimension = len(vector)
                    embedding["dimension"] = effective_dimension
                if len(vector) != effective_dimension:
                    raise CentroidRoutingError(
                        "chunk embedding dimension mismatch for "
                        f"{_chunk_key(dataset_id, chunk)!r}: expected {effective_dimension}, got {len(vector)}"
                    )
                key = _chunk_key(dataset_id, chunk)
                if key in eligible_keys:
                    duplicate_chunk_count += 1
                    continue
                eligible_keys.add(key)
                item["eligible_chunk_count"] += 1
                candidates.append(
                    {
                        "key": key,
                        "dataset_id": dataset_id,
                        "kb_name": item.get("kb_name"),
                        "vector": vector,
                        "source_hash": _chunk_source_hash(chunk),
                        "snapshot_path": snapshot["path"],
                    }
                )

    if not datasets:
        raise CentroidRoutingError("centroid build inputs did not contain any datasets or chunks")
    if not candidates:
        raise CentroidRoutingError(
            "centroid build found no chunk embeddings; include embedding, embedding_vector, or vector fields"
        )
    if effective_dimension is None:
        raise CentroidRoutingError("centroid build could not infer an embedding dimension")
    for dataset_id, state in dataset_state.items():
        if len(state["vector_sum"]) != effective_dimension:
            raise CentroidRoutingError(
                f"checkpoint dataset {dataset_id!r} vector dimension {len(state['vector_sum'])} "
                f"does not match {effective_dimension}"
            )

    for dataset_id, item in sorted(datasets.items()):
        if item["skipped_missing_embedding_count"]:
            issues.append(
                _issue(
                    "warning",
                    "chunk_embedding_missing",
                    f"{item['skipped_missing_embedding_count']} chunks do not include snapshot-owned embeddings",
                    path=dataset_id,
                    recommendation="Regenerate the chunk snapshot with embedding, embedding_vector, or vector fields.",
                )
            )
        if item["snapshot_chunk_count"] and not item["eligible_chunk_count"]:
            issues.append(
                _issue(
                    "warning",
                    "centroid_dataset_without_embeddings",
                    "dataset has snapshot chunks but no usable embeddings",
                    path=dataset_id,
                    recommendation="Add embeddings to the chunk snapshot before building this dataset centroid.",
                )
            )
    if duplicate_chunk_count:
        issues.append(
            _issue(
                "info",
                "duplicate_chunk_key_skipped",
                f"{duplicate_chunk_count} duplicate chunk keys were skipped",
                path="chunk_snapshots",
                recommendation="Deduplicate snapshot inputs when possible to keep checkpoint state compact.",
            )
        )

    unprocessed = [candidate for candidate in candidates if candidate["key"] not in processed_keys]
    selected = unprocessed[:batch_size]
    for candidate in selected:
        dataset_id = candidate["dataset_id"]
        item = datasets.get(dataset_id, {})
        state = dataset_state.setdefault(
            dataset_id,
            {
                "dataset_id": dataset_id,
                "kb_name": candidate.get("kb_name"),
                "chunk_count": 0,
                "vector_sum": [0.0 for _ in range(effective_dimension)],
                "source_hashes": set(),
                "source_paths": set(),
            },
        )
        if len(state["vector_sum"]) != effective_dimension:
            raise CentroidRoutingError(
                f"checkpoint dataset {dataset_id!r} vector dimension {len(state['vector_sum'])} "
                f"does not match {effective_dimension}"
            )
        if candidate.get("kb_name") and not state.get("kb_name"):
            state["kb_name"] = candidate.get("kb_name")
        state["chunk_count"] += 1
        state["vector_sum"] = [
            float(current) + float(increment)
            for current, increment in zip(state["vector_sum"], candidate["vector"])
        ]
        state["source_hashes"].add(candidate["source_hash"])
        state["source_paths"].update(item.get("manifest_paths", []))
        state["source_paths"].update(item.get("snapshot_paths", []))
        state["source_paths"].add(candidate["snapshot_path"])
        processed_keys.add(candidate["key"])

    processed_input_keys = processed_keys & eligible_keys
    for candidate in candidates:
        if candidate["key"] in processed_keys:
            datasets[candidate["dataset_id"]]["processed_chunk_count"] += 1
    remaining_chunk_count = len(eligible_keys - processed_keys)
    completed = remaining_chunk_count == 0

    dataset_reports: list[dict[str, Any]] = []
    for dataset_id, item in sorted(datasets.items()):
        state = dataset_state.get(dataset_id)
        dataset_reports.append(
            {
                "dataset_id": dataset_id,
                "kb_name": item.get("kb_name") or (state or {}).get("kb_name"),
                "manifest_paths": list(item["manifest_paths"]),
                "snapshot_paths": list(item["snapshot_paths"]),
                "snapshot_chunk_count": int(item["snapshot_chunk_count"]),
                "eligible_chunk_count": int(item["eligible_chunk_count"]),
                "processed_chunk_count": int(item["processed_chunk_count"]),
                "skipped_missing_embedding_count": int(item["skipped_missing_embedding_count"]),
            }
        )

    centroids: list[dict[str, Any]] = []
    for dataset_id, state in sorted(dataset_state.items()):
        chunk_count = int(state["chunk_count"])
        if chunk_count <= 0:
            continue
        item = datasets.get(dataset_id, {})
        eligible_count = int(item.get("eligible_chunk_count", chunk_count) or chunk_count)
        vector = [float(value) / float(chunk_count) for value in state["vector_sum"]]
        source_hashes = sorted(state["source_hashes"])
        source_paths = set(state["source_paths"])
        source_paths.update(item.get("manifest_paths", []))
        source_paths.update(item.get("snapshot_paths", []))
        centroids.append(
            {
                "centroid_id": _centroid_id(dataset_id),
                "dataset_id": dataset_id,
                "kb_name": state.get("kb_name") or item.get("kb_name"),
                "vector": vector,
                "embedding_dimension": effective_dimension,
                "chunk_count": chunk_count,
                "eligible_chunk_count": eligible_count,
                "source_hash": _stable_digest(source_hashes) if source_hashes else None,
                "status": "ready" if completed and chunk_count >= eligible_count else "partial",
                "source_paths": sorted(source_paths),
            }
        )

    skipped_chunk_count = sum(int(item["skipped_missing_embedding_count"]) for item in datasets.values())
    summary = {
        "kb_manifest_count": len(manifest_paths),
        "chunk_snapshot_count": len(snapshot_paths),
        "dataset_count": len(dataset_reports),
        "centroid_count": len(centroids),
        "eligible_chunk_count": len(eligible_keys),
        "processed_chunk_count": len(processed_input_keys),
        "processed_this_run": len(selected),
        "remaining_chunk_count": remaining_chunk_count,
        "skipped_chunk_count": skipped_chunk_count + duplicate_chunk_count,
        "duplicate_chunk_count": duplicate_chunk_count,
        "completed": completed,
        "issue_count": len(issues),
        "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
        "infos": sum(1 for issue in issues if issue["severity"] == "info"),
    }
    index = {
        "schema": CENTROID_INDEX_SCHEMA,
        "version": "0.1",
        "created_at": now,
        "updated_at": now,
        "embedding": embedding,
        "summary": {
            "dataset_count": len(dataset_reports),
            "centroid_count": len(centroids),
            "eligible_chunk_count": len(eligible_keys),
            "processed_chunk_count": len(processed_input_keys),
            "completed": completed,
        },
        "centroids": centroids,
    }
    checkpoint_payload = {
        "ok": True,
        "schema": CENTROID_BUILD_CHECKPOINT_SCHEMA,
        "created_at": created_at or now,
        "updated_at": now,
        "completed": completed,
        "embedding": embedding,
        "inputs": {
            "kb_manifests": [str(path) for path in manifest_paths],
            "chunk_snapshots": [str(path) for path in snapshot_paths],
        },
        "summary": summary,
        "processed_chunk_keys": sorted(processed_keys),
        "datasets": {
            dataset_id: {
                "dataset_id": dataset_id,
                "kb_name": state.get("kb_name"),
                "chunk_count": int(state["chunk_count"]),
                "vector_sum": list(state["vector_sum"]),
                "source_hashes": sorted(state["source_hashes"]),
                "source_paths": sorted(state["source_paths"]),
            }
            for dataset_id, state in sorted(dataset_state.items())
        },
    }
    _write_json(index_output, index)
    _write_json(checkpoint_file, checkpoint_payload)

    return {
        "ok": True,
        "schema": CENTROID_BUILD_REPORT_SCHEMA,
        "mode": "build",
        "plan_only": False,
        "created_at": now,
        "index_schema": CENTROID_INDEX_SCHEMA,
        "index_output": str(index_output),
        "checkpoint_path": str(checkpoint_file),
        "embedding": embedding,
        "execution": {
            "batch_size": batch_size,
            "resume": bool(resume),
            "bounded": True,
            "processed_this_run": len(selected),
            "completed": completed,
        },
        "summary": summary,
        "inputs": {
            "kb_manifests": [str(path) for path in manifest_paths],
            "chunk_snapshots": [str(path) for path in snapshot_paths],
        },
        "datasets": dataset_reports,
        "centroids": centroids,
        "index": index,
        "issues": issues,
        "recommendations": [
            "Run again with --resume and the same --checkpoint until completed is true.",
            "Use centroid scores only as a tie-breaker after explicit hints and user-selected KBs.",
            "Keep centroid artifacts user-owned; this command does not call embedding APIs or mutate RAGFlow.",
        ],
    }


def write_centroid_plan(path: str | Path, report: Mapping[str, Any]) -> None:
    _write_json(path, report)


def write_centroid_report(path: str | Path, report: Mapping[str, Any]) -> None:
    _write_json(path, report)


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


def render_centroid_build_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Centroid Build Report",
        "",
        f"- schema: `{report.get('schema', '')}`",
        f"- mode: `{report.get('mode', '')}`",
        f"- index_schema: `{report.get('index_schema', '')}`",
        f"- index_output: `{report.get('index_output', '')}`",
        f"- checkpoint_path: `{report.get('checkpoint_path', '')}`",
        f"- datasets: `{summary.get('dataset_count', 0)}`",
        f"- centroids: `{summary.get('centroid_count', 0)}`",
        f"- eligible_chunks: `{summary.get('eligible_chunk_count', 0)}`",
        f"- processed_chunks: `{summary.get('processed_chunk_count', 0)}`",
        f"- processed_this_run: `{summary.get('processed_this_run', 0)}`",
        f"- remaining_chunks: `{summary.get('remaining_chunk_count', 0)}`",
        f"- completed: `{str(bool(summary.get('completed'))).lower()}`",
        "",
        "## Centroids",
        "",
    ]
    centroids = report.get("centroids", []) if isinstance(report.get("centroids"), list) else []
    if not centroids:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| dataset | KB | chunks | eligible | dimension | status |",
                "| --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in centroids:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| `{dataset_id}` | `{kb_name}` | {chunks} | {eligible} | {dimension} | `{status}` |".format(
                    dataset_id=item.get("dataset_id", ""),
                    kb_name=item.get("kb_name") or "-",
                    chunks=int(item.get("chunk_count", 0)),
                    eligible=int(item.get("eligible_chunk_count", 0)),
                    dimension=int(item.get("embedding_dimension", 0)),
                    status=item.get("status", ""),
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
