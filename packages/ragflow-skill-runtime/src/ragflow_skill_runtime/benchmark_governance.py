"""Offline benchmark lifecycle helpers for RAGFlow skills."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .validation import (
    BenchmarkGate,
    BenchmarkQrel,
    CHUNK_SNAPSHOT_SCHEMA,
    ValidationQuery,
    ValidationError,
    evaluate_benchmark_gate,
    load_chunk_snapshot,
    load_benchmark_baseline,
    load_benchmark_gate,
    load_benchmark_qrels,
    load_validation_queries,
)
from .retrieval import CHUNK_HASH_ALGORITHM, NormalizedChunk, normalize_chunk, normalize_retrieval_response, stable_chunk_hash


BENCHMARK_MANIFEST_SCHEMA = "ragflow_benchmark_manifest_v1"
BENCHMARK_QUERIES_SCHEMA = "ragflow_benchmark_queries_v1"
BENCHMARK_QRELS_SCHEMA = "ragflow_benchmark_qrels_v1"
GROUNDED_QA_SCHEMA = "ragflow_grounded_qa_v1"
GROUNDED_QA_VALIDATE_REPORT_SCHEMA = "ragflow_grounded_qa_validate_report_v1"
BENCHMARK_IMPORT_REPORT_SCHEMA = "ragflow_benchmark_import_report_v1"
BENCHMARK_SAMPLE_REPORT_SCHEMA = "ragflow_benchmark_sample_report_v1"
BENCHMARK_PREFLIGHT_REPORT_SCHEMA = "ragflow_benchmark_preflight_report_v1"
BENCHMARK_SUMMARY_REPORT_SCHEMA = "ragflow_benchmark_summary_report_v1"
BENCHMARK_GATE_REPORT_SCHEMA = "ragflow_benchmark_gate_report_v1"
BENCHMARK_TREND_REPORT_SCHEMA = "ragflow_benchmark_trend_report_v1"
BENCHMARK_DELTA_REPORT_SCHEMA = "ragflow_benchmark_delta_report_v1"
CHUNK_SNAPSHOT_REPORT_SCHEMA = "ragflow_chunk_snapshot_report_v1"


class BenchmarkGovernanceError(RuntimeError):
    """Raised when benchmark lifecycle inputs are invalid."""


@dataclass(frozen=True)
class BenchmarkGovernanceIssue:
    severity: str
    code: str
    message: str
    field: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkGovernanceError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkGovernanceError(f"file is not valid JSON: {source}") from exc


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _issue_counts(issues: Iterable[BenchmarkGovernanceIssue]) -> dict[str, int]:
    items = list(issues)
    return {
        "errors": sum(1 for issue in items if issue.severity == "error"),
        "warnings": sum(1 for issue in items if issue.severity == "warning"),
        "infos": sum(1 for issue in items if issue.severity == "info"),
    }


def _ok(issues: Iterable[BenchmarkGovernanceIssue]) -> bool:
    return not any(issue.severity == "error" for issue in issues)


def _flatten_qrels(qrels: Mapping[str, list[BenchmarkQrel]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for query_id in sorted(qrels):
        for qrel in qrels[query_id]:
            items.append(qrel.to_dict())
    return items


def _qa_payload(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"schema": GROUNDED_QA_SCHEMA, "items": []}
    raw = _read_json(path)
    if isinstance(raw, Mapping):
        if raw.get("schema") == GROUNDED_QA_SCHEMA:
            return dict(raw)
        if isinstance(raw.get("items"), list):
            return {"schema": GROUNDED_QA_SCHEMA, "items": raw["items"], "metadata": raw.get("metadata", {})}
        if isinstance(raw.get("qa"), list):
            return {"schema": GROUNDED_QA_SCHEMA, "items": raw["qa"], "metadata": raw.get("metadata", {})}
    if isinstance(raw, list):
        return {"schema": GROUNDED_QA_SCHEMA, "items": raw}
    raise BenchmarkGovernanceError("qa file must be a JSON object or list")


@dataclass(frozen=True)
class _SourceText:
    name: str
    text: str
    path: str | None = None
    aliases: tuple[str, ...] = ()


_SOURCE_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv", ".yaml", ".yml"}


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _first_string(payload: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = _clean_string(payload.get(key))
        if value:
            return value
    return None


def _source_key(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _source_ref_keys(value: str | None) -> set[str]:
    if not value:
        return set()
    normalized = value.replace("\\", "/").strip()
    keys = {_source_key(normalized)}
    name = Path(normalized).name
    if name:
        keys.add(_source_key(name))
    return {key for key in keys if key}


def _source_aliases(*, path: Path | None = None, root: Path | None = None, name: str | None = None) -> tuple[str, ...]:
    aliases: set[str] = set()
    if name:
        aliases.update(_source_ref_keys(name))
    if path:
        aliases.update(_source_ref_keys(str(path)))
        aliases.update(_source_ref_keys(path.name))
        try:
            aliases.update(_source_ref_keys(str(path.resolve())))
        except OSError:
            pass
        if root:
            try:
                aliases.update(_source_ref_keys(str(path.relative_to(root))))
            except ValueError:
                pass
    return tuple(sorted(aliases))


def _source_from_mapping(payload: Mapping[str, Any], *, fallback_name: str) -> _SourceText | None:
    text = _first_string(payload, ("text", "content", "body", "markdown", "source_text"))
    if not text:
        return None
    name = _first_string(
        payload,
        ("document", "document_name", "source", "source_path", "path", "file", "filename", "name", "id"),
    ) or fallback_name
    return _SourceText(name=name, text=text, aliases=_source_aliases(name=name))


def _sources_from_json_payload(payload: Any, *, fallback_name: str) -> list[_SourceText]:
    if isinstance(payload, list):
        sources: list[_SourceText] = []
        for index, item in enumerate(payload):
            if isinstance(item, str) and item.strip():
                name = f"{fallback_name}#{index + 1}"
                sources.append(_SourceText(name=name, text=item.strip(), aliases=_source_aliases(name=name)))
            elif isinstance(item, Mapping):
                source = _source_from_mapping(item, fallback_name=f"{fallback_name}#{index + 1}")
                if source:
                    sources.append(source)
        return sources

    if isinstance(payload, Mapping):
        for key in ("sources", "documents", "items"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return _sources_from_json_payload(nested, fallback_name=fallback_name)

        direct_source = _source_from_mapping(payload, fallback_name=fallback_name)
        if direct_source:
            return [direct_source]

        sources = []
        for key, value in sorted(payload.items()):
            if key == "schema":
                continue
            if isinstance(value, str) and value.strip():
                sources.append(_SourceText(name=key, text=value.strip(), aliases=_source_aliases(name=key)))
            elif isinstance(value, Mapping):
                source = _source_from_mapping(value, fallback_name=key)
                if source:
                    sources.append(source)
        return sources

    return []


def _load_sources_file(path: Path) -> list[_SourceText]:
    if path.suffix.lower() == ".json":
        return _sources_from_json_payload(_read_json(path), fallback_name=path.name)
    text = path.read_text(encoding="utf-8")
    return [_SourceText(name=path.name, path=str(path), text=text, aliases=_source_aliases(path=path, name=path.name))]


def _load_source_texts(
    *,
    sources_path: str | Path | None = None,
    source_dir: str | Path | None = None,
) -> list[_SourceText]:
    sources: list[_SourceText] = []

    if sources_path:
        source_file = Path(sources_path)
        if not source_file.exists():
            raise BenchmarkGovernanceError(f"sources file not found: {source_file}")
        if source_file.is_dir():
            raise BenchmarkGovernanceError(f"sources must be a file, not a directory: {source_file}")
        sources.extend(_load_sources_file(source_file))

    if source_dir:
        root = Path(source_dir)
        if not root.exists():
            raise BenchmarkGovernanceError(f"source dir not found: {root}")
        files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in files:
            if path.suffix.lower() not in _SOURCE_TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            aliases = _source_aliases(path=path, root=root if root.is_dir() else root.parent, name=path.name)
            sources.append(_SourceText(name=path.name, path=str(path), text=text, aliases=aliases))

    if (sources_path or source_dir) and not sources:
        raise BenchmarkGovernanceError("no source text files were found")
    return sources


def _qa_item_identifier(item: Mapping[str, Any], index: int) -> str:
    return _first_string(item, ("id", "query_id", "question_id", "validation_query_id")) or f"item-{index + 1}"


def _evidence_entries(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, Mapping):
        if any(_clean_string(value.get(key)) for key in ("text", "quote", "span", "content", "evidence", "excerpt")):
            return [value]
        for key in ("spans", "evidence", "items", "quotes"):
            nested = _evidence_entries(value.get(key))
            if nested:
                return nested
        return [value]
    return []


def _qa_evidence_items(item: Mapping[str, Any]) -> list[Any]:
    entries: list[Any] = []
    for key in ("evidence", "evidence_spans", "grounding", "grounded_evidence", "supporting_evidence"):
        entries.extend(_evidence_entries(item.get(key)))
    return entries


def _evidence_span_text(evidence: Any) -> str | None:
    if isinstance(evidence, str):
        return _clean_string(evidence)
    if isinstance(evidence, Mapping):
        return _first_string(evidence, ("text", "quote", "span", "content", "evidence", "excerpt"))
    return None


def _evidence_document_ref(evidence: Any) -> str | None:
    if isinstance(evidence, Mapping):
        return _first_string(
            evidence,
            ("document", "document_name", "source", "source_document", "source_path", "path", "file", "filename", "doc"),
        )
    return None


def _matching_sources(sources: list[_SourceText], document_ref: str | None) -> list[_SourceText]:
    keys = _source_ref_keys(document_ref)
    if not keys:
        return []
    return [source for source in sources if keys.intersection(source.aliases)]


def _sources_containing_span(sources: list[_SourceText], span: str) -> list[_SourceText]:
    return [source for source in sources if span in source.text]


def validate_grounded_qa(
    *,
    qa_path: str | Path,
    sources_path: str | Path | None = None,
    source_dir: str | Path | None = None,
    require_answer: bool = True,
) -> dict[str, Any]:
    """Validate grounded QA items and exact evidence spans without touching RAGFlow."""

    payload = _qa_payload(qa_path)
    raw_items = payload.get("items")
    sources = _load_source_texts(sources_path=sources_path, source_dir=source_dir)
    issues: list[BenchmarkGovernanceIssue] = []
    item_error_ids: set[str] = set()
    evidence_span_count = 0
    checked_span_count = 0
    grounded_span_count = 0

    if not isinstance(raw_items, list):
        issues.append(BenchmarkGovernanceIssue("error", "qa_items_invalid", "qa items must be a list", "items"))
        raw_items = []
    if not raw_items:
        issues.append(BenchmarkGovernanceIssue("error", "qa_empty", "qa file does not contain any items", "items"))

    for index, raw_item in enumerate(raw_items):
        field_prefix = f"items[{index}]"
        if not isinstance(raw_item, Mapping):
            item_id = f"item-{index + 1}"
            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue("error", "qa_item_invalid", "qa item must be a JSON object", field_prefix)
            )
            continue

        item_id = _qa_item_identifier(raw_item, index)
        question = _first_string(raw_item, ("question", "query", "prompt", "input"))
        answer = _first_string(raw_item, ("answer", "expected_answer", "reference_answer", "response"))
        if not question:
            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_item_missing_question",
                    "qa item must include a question or query",
                    f"{field_prefix}.question",
                )
            )
        if require_answer and not answer:
            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_item_missing_answer",
                    "qa item must include an answer",
                    f"{field_prefix}.answer",
                )
            )

        evidence_items = _qa_evidence_items(raw_item)
        if not evidence_items:
            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_item_missing_evidence",
                    "qa item must include grounded evidence spans",
                    f"{field_prefix}.evidence",
                    "Add evidence spans copied exactly from source documents.",
                )
            )
            continue

        for evidence_index, evidence in enumerate(evidence_items):
            evidence_field = f"{field_prefix}.evidence[{evidence_index}]"
            span = _evidence_span_text(evidence)
            document_ref = _evidence_document_ref(evidence)
            if not span:
                item_error_ids.add(item_id)
                issues.append(
                    BenchmarkGovernanceIssue(
                        "error",
                        "evidence_span_missing",
                        "evidence item must include non-empty text, quote, span, content, or evidence",
                        evidence_field,
                    )
                )
                continue

            evidence_span_count += 1
            if not sources:
                continue

            checked_span_count += 1
            candidates = _matching_sources(sources, document_ref)
            if candidates and _sources_containing_span(candidates, span):
                grounded_span_count += 1
                continue

            any_source_matches = _sources_containing_span(sources, span)
            if any_source_matches:
                grounded_span_count += 1
                if document_ref and candidates:
                    issues.append(
                        BenchmarkGovernanceIssue(
                            "warning",
                            "evidence_document_mismatch",
                            "evidence span was found in source text, but not in the referenced document",
                            evidence_field,
                        )
                    )
                elif document_ref:
                    issues.append(
                        BenchmarkGovernanceIssue(
                            "warning",
                            "evidence_document_unmatched",
                            "evidence document reference did not match a loaded source, but the span was found elsewhere",
                            evidence_field,
                        )
                    )
                continue

            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "evidence_span_not_found",
                    "evidence span was not found in the provided sources",
                    evidence_field,
                    "Copy evidence spans exactly from the source document or refresh the QA item.",
                )
            )

    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_VALIDATE_REPORT_SCHEMA,
        "artifacts": {
            "qa": str(qa_path),
            "sources": str(sources_path) if sources_path else None,
            "source_dir": str(source_dir) if source_dir else None,
        },
        "summary": {
            **_issue_counts(issues),
            "item_count": len(raw_items),
            "valid_item_count": max(0, len(raw_items) - len(item_error_ids)),
            "invalid_item_count": len(item_error_ids),
            "evidence_span_count": evidence_span_count,
            "checked_span_count": checked_span_count,
            "grounded_span_count": grounded_span_count,
            "source_count": len(sources),
            "require_answer": require_answer,
        },
        "issues": [issue.to_dict() for issue in issues],
    }


def _source_hashes(paths: Iterable[str | Path | None]) -> list[dict[str, str]]:
    hashes = []
    seen: set[Path] = set()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if path in seen:
            continue
        seen.add(path)
        if path.is_dir():
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                if child in seen:
                    continue
                seen.add(child)
                hashes.append({"path": str(child), "sha256": _sha256_file(child)})
            continue
        hashes.append({"path": str(path), "sha256": _sha256_file(path)})
    return hashes


def _iter_markdown_chunks(path: Path) -> list[NormalizedChunk]:
    if path.is_dir():
        chunks: list[NormalizedChunk] = []
        for markdown in sorted(path.rglob("*.md")):
            chunks.extend(_iter_markdown_chunks(markdown))
        return chunks
    text = path.read_text(encoding="utf-8")
    return [NormalizedChunk(content=text, document_name=path.name, document_id=str(path))]


def _chunks_from_validation_report(payload: Mapping[str, Any]) -> list[NormalizedChunk]:
    chunks: list[NormalizedChunk] = []
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return chunks
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        top_chunks = case.get("top_chunks")
        if not isinstance(top_chunks, list):
            continue
        for item in top_chunks:
            if isinstance(item, Mapping):
                chunks.append(normalize_chunk(item))
    return chunks


def _chunks_from_payload(payload: Any) -> list[NormalizedChunk]:
    if isinstance(payload, Mapping) and payload.get("schema") == CHUNK_SNAPSHOT_SCHEMA:
        chunks = []
        for item in payload.get("chunks", []):
            if not isinstance(item, Mapping):
                continue
            chunks.append(
                NormalizedChunk(
                    content=str(item.get("content") or item.get("content_preview") or ""),
                    document_name=item.get("document_name") if isinstance(item.get("document_name"), str) else None,
                    document_id=item.get("document_id") if isinstance(item.get("document_id"), str) else None,
                    dataset_id=item.get("dataset_id") if isinstance(item.get("dataset_id"), str) else None,
                    chunk_id=item.get("chunk_id") if isinstance(item.get("chunk_id"), str) else None,
                )
            )
        return chunks
    if isinstance(payload, Mapping):
        reported = _chunks_from_validation_report(payload)
        if reported:
            return reported
        if isinstance(payload.get("chunks"), list):
            return [normalize_chunk(item) for item in payload["chunks"] if isinstance(item, Mapping)]
        return normalize_retrieval_response(payload)
    if isinstance(payload, list):
        return normalize_retrieval_response(payload)
    raise BenchmarkGovernanceError("chunk snapshot input must be JSON object, JSON list, Markdown file, or Markdown directory")


def _read_snapshot_input(path: str | Path) -> tuple[list[NormalizedChunk], list[str | Path]]:
    source = Path(path)
    if not source.exists():
        raise BenchmarkGovernanceError(f"chunk snapshot input not found: {source}")
    if source.is_dir() or source.suffix.lower() in {".md", ".markdown"}:
        return _iter_markdown_chunks(source), [source]
    payload = _read_json(source)
    return _chunks_from_payload(payload), [source]


def _chunk_aliases(chunk: NormalizedChunk, stable_hash: str) -> list[str]:
    aliases = {stable_hash, stable_hash.removeprefix("sha256:")}
    if chunk.chunk_id:
        aliases.add(chunk.chunk_id)
    return sorted(aliases)


def _chunk_snapshot_item(
    chunk: NormalizedChunk,
    *,
    index: int,
    include_content: bool,
) -> dict[str, Any]:
    stable_hash = stable_chunk_hash(chunk)
    item: dict[str, Any] = {
        "id": f"chunk-{index + 1}",
        "stable_hash": stable_hash,
        "stable_hash_algorithm": CHUNK_HASH_ALGORITHM,
        "content_sha256": stable_hash.removeprefix("sha256:"),
        "content_preview": chunk.content[:240],
        "document_name": chunk.document_name,
        "document_id": chunk.document_id,
        "dataset_id": chunk.dataset_id,
        "chunk_id": chunk.chunk_id,
        "aliases": _chunk_aliases(chunk, stable_hash),
    }
    if include_content:
        item["content"] = chunk.content
    return {key: value for key, value in item.items() if value not in (None, [], "")}


def snapshot_chunks(
    *,
    input_path: str | Path,
    output_path: str | Path,
    name: str = "chunk-snapshot",
    description: str = "",
    include_content: bool = False,
) -> dict[str, Any]:
    """Create a deterministic chunk snapshot from local chunks or validation output."""

    chunks, source_paths = _read_snapshot_input(input_path)
    if not chunks:
        raise BenchmarkGovernanceError("chunk snapshot input did not contain any chunks")

    seen: set[str] = set()
    snapshot_items: list[dict[str, Any]] = []
    duplicate_hashes = 0
    for chunk in chunks:
        stable_hash = stable_chunk_hash(chunk)
        if stable_hash in seen:
            duplicate_hashes += 1
            continue
        seen.add(stable_hash)
        snapshot_items.append(_chunk_snapshot_item(chunk, index=len(snapshot_items), include_content=include_content))

    snapshot = {
        "schema": CHUNK_SNAPSHOT_SCHEMA,
        "created_at": _now(),
        "name": name,
        "description": description,
        "hash_algorithm": CHUNK_HASH_ALGORITHM,
        "summary": {
            "chunk_count": len(snapshot_items),
            "source_chunk_count": len(chunks),
            "duplicate_stable_hash_count": duplicate_hashes,
            "document_count": len({item.get("document_name") for item in snapshot_items if item.get("document_name")}),
        },
        "source_hashes": _source_hashes(source_paths),
        "chunks": snapshot_items,
    }
    _write_json(output_path, snapshot)
    return {
        "ok": True,
        "schema": CHUNK_SNAPSHOT_REPORT_SCHEMA,
        "chunk_snapshot": str(output_path),
        "summary": dict(snapshot["summary"]),
        "source_hashes": snapshot["source_hashes"],
    }


def _write_benchmark_artifacts(
    *,
    queries: list[ValidationQuery],
    qrels: Mapping[str, list[BenchmarkQrel]],
    qa: Mapping[str, Any],
    output_dir: str | Path,
    name: str,
    description: str,
    source_paths: Iterable[str | Path | None],
    sampling: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    queries_payload = {
        "schema": BENCHMARK_QUERIES_SCHEMA,
        "created_at": _now(),
        "queries": [query.to_dict() for query in queries],
    }
    qrels_payload = {
        "schema": BENCHMARK_QRELS_SCHEMA,
        "created_at": _now(),
        "qrels": _flatten_qrels(qrels),
    }
    qa_payload = {"created_at": _now(), **dict(qa)}

    queries_output = output / "queries.json"
    qrels_output = output / "qrels.json"
    qa_output = output / "qa.json"
    _write_json(queries_output, queries_payload)
    _write_json(qrels_output, qrels_payload)
    _write_json(qa_output, qa_payload)

    query_ids = {query.id for query in queries}
    judged_query_ids = set(qrels)
    manifest: dict[str, Any] = {
        "schema": BENCHMARK_MANIFEST_SCHEMA,
        "created_at": _now(),
        "name": name,
        "description": description,
        "artifacts": {
            "queries": "queries.json",
            "qrels": "qrels.json",
            "qa": "qa.json",
        },
        "summary": {
            "query_count": len(queries),
            "judged_query_count": len(judged_query_ids),
            "qrel_count": sum(len(items) for items in qrels.values()),
            "qa_count": len(qa_payload.get("items", [])) if isinstance(qa_payload.get("items"), list) else 0,
            "queries_without_qrels": sorted(query_ids - judged_query_ids),
            "qrels_without_queries": sorted(judged_query_ids - query_ids),
        },
        "source_hashes": _source_hashes(source_paths),
    }
    if sampling:
        manifest["sampling"] = dict(sampling)
    manifest_output = output / "manifest.json"
    _write_json(manifest_output, manifest)

    return {
        "benchmark_manifest": str(manifest_output),
        "output_dir": str(output),
        "artifacts": {
            "manifest": str(manifest_output),
            "queries": str(queries_output),
            "qrels": str(qrels_output),
            "qa": str(qa_output),
        },
        "summary": dict(manifest["summary"]),
        "source_hashes": manifest["source_hashes"],
        **({"sampling": dict(sampling)} if sampling else {}),
    }


def import_benchmark_dataset(
    *,
    queries_path: str | Path,
    qrels_path: str | Path,
    output_dir: str | Path,
    name: str = "benchmark",
    description: str = "",
    qa_path: str | Path | None = None,
) -> dict[str, Any]:
    """Normalize user benchmark inputs into a portable benchmark directory."""

    queries = load_validation_queries(queries_path)
    qrels = load_benchmark_qrels(qrels_path)
    qa = _qa_payload(qa_path)
    artifacts = _write_benchmark_artifacts(
        queries=queries,
        qrels=qrels,
        qa=qa,
        output_dir=output_dir,
        name=name,
        description=description,
        source_paths=[queries_path, qrels_path, qa_path],
    )

    return {
        "ok": True,
        "schema": BENCHMARK_IMPORT_REPORT_SCHEMA,
        **artifacts,
    }


def _sample_count(
    *,
    total: int,
    sample_size: int | None,
    sample_fraction: float | None,
) -> int:
    if sample_size is None and sample_fraction is None:
        raise BenchmarkGovernanceError("benchmark sample requires --size or --fraction")
    if sample_size is not None and sample_fraction is not None:
        raise BenchmarkGovernanceError("benchmark sample accepts only one of --size or --fraction")
    if sample_size is not None:
        if sample_size <= 0:
            raise BenchmarkGovernanceError("benchmark sample size must be positive")
        if sample_size > total:
            raise BenchmarkGovernanceError("benchmark sample size cannot exceed query count")
        return sample_size
    assert sample_fraction is not None
    if sample_fraction <= 0 or sample_fraction > 1:
        raise BenchmarkGovernanceError("benchmark sample fraction must be greater than 0 and at most 1")
    return max(1, math.ceil(total * sample_fraction))


def _query_type_for_sampling(query: ValidationQuery) -> str:
    value = query.metadata.get("type") or query.metadata.get("query_type") or "default"
    return str(value).strip() or "default"


def _select_sample_queries(
    queries: list[ValidationQuery],
    *,
    count: int,
    strategy: str,
    seed: int,
) -> list[ValidationQuery]:
    if strategy == "first":
        return queries[:count]

    rng = random.Random(seed)
    if strategy == "random":
        selected_indexes = set(rng.sample(range(len(queries)), count))
        return [query for index, query in enumerate(queries) if index in selected_indexes]

    if strategy != "stratified":
        raise BenchmarkGovernanceError("benchmark sample strategy must be one of first, random, stratified")

    groups: dict[str, list[int]] = {}
    for index, query in enumerate(queries):
        groups.setdefault(_query_type_for_sampling(query), []).append(index)

    minimum = 1 if count >= len(groups) else 0
    ideals = {key: len(indexes) / len(queries) * count for key, indexes in groups.items()}
    allocations = {
        key: min(len(indexes), max(minimum, math.floor(ideals[key])))
        for key, indexes in groups.items()
    }

    tie_breakers = {key: rng.random() for key in groups}
    while sum(allocations.values()) > count:
        candidates = [key for key, value in allocations.items() if value > minimum]
        if not candidates:
            break
        key = min(candidates, key=lambda item: (ideals[item] - allocations[item], tie_breakers[item], item))
        allocations[key] -= 1

    while sum(allocations.values()) < count:
        candidates = [key for key, indexes in groups.items() if allocations[key] < len(indexes)]
        if not candidates:
            break
        key = max(candidates, key=lambda item: (ideals[item] - allocations[item], -tie_breakers[item], item))
        allocations[key] += 1

    selected_indexes: set[int] = set()
    for key, indexes in groups.items():
        allocation = allocations[key]
        if allocation <= 0:
            continue
        selected_indexes.update(rng.sample(indexes, allocation))
    return [query for index, query in enumerate(queries) if index in selected_indexes]


def _qa_query_id(item: Mapping[str, Any], known_query_ids: set[str]) -> str | None:
    for key in ("query_id", "queryId", "query", "validation_query_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = item.get("id")
    if isinstance(value, str) and value.strip() in known_query_ids:
        return value.strip()
    return None


def _filter_qa_payload(qa: Mapping[str, Any], selected_query_ids: set[str], known_query_ids: set[str]) -> dict[str, Any]:
    payload = dict(qa)
    items = payload.get("items")
    if not isinstance(items, list):
        payload["items"] = []
        return payload
    kept = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        query_id = _qa_query_id(item, known_query_ids)
        if query_id in selected_query_ids:
            kept.append(dict(item))
    payload["items"] = kept
    return payload


def _sampling_summary(
    *,
    selected_queries: list[ValidationQuery],
    source_queries: list[ValidationQuery],
    strategy: str,
    seed: int,
    sample_size: int | None,
    sample_fraction: float | None,
) -> dict[str, Any]:
    source_type_counts: dict[str, int] = {}
    selected_type_counts: dict[str, int] = {}
    for query in source_queries:
        query_type = _query_type_for_sampling(query)
        source_type_counts[query_type] = source_type_counts.get(query_type, 0) + 1
    for query in selected_queries:
        query_type = _query_type_for_sampling(query)
        selected_type_counts[query_type] = selected_type_counts.get(query_type, 0) + 1
    return {
        "strategy": strategy,
        "seed": seed,
        "requested_size": sample_size,
        "requested_fraction": sample_fraction,
        "source_query_count": len(source_queries),
        "selected_query_count": len(selected_queries),
        "selected_query_ids": [query.id for query in selected_queries],
        "source_query_type_counts": dict(sorted(source_type_counts.items())),
        "selected_query_type_counts": dict(sorted(selected_type_counts.items())),
    }


def sample_benchmark_dataset(
    *,
    output_dir: str | Path,
    sample_size: int | None = None,
    sample_fraction: float | None = None,
    strategy: str = "stratified",
    seed: int = 0,
    manifest_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    qrels_path: str | Path | None = None,
    qa_path: str | Path | None = None,
    name: str = "benchmark-sample",
    description: str = "",
) -> dict[str, Any]:
    """Create a deterministic benchmark subset while preserving normalized artifacts."""

    artifacts = resolve_benchmark_artifacts(
        manifest_path=manifest_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        qa_path=qa_path,
    )
    if not artifacts["queries"]:
        raise BenchmarkGovernanceError("benchmark sample requires queries")
    if not artifacts["qrels"]:
        raise BenchmarkGovernanceError("benchmark sample requires qrels")

    queries = load_validation_queries(artifacts["queries"])
    qrels = load_benchmark_qrels(artifacts["qrels"])
    qa = _qa_payload(artifacts["qa"])
    count = _sample_count(total=len(queries), sample_size=sample_size, sample_fraction=sample_fraction)
    selected_queries = _select_sample_queries(queries, count=count, strategy=strategy, seed=seed)
    selected_query_ids = {query.id for query in selected_queries}
    known_query_ids = {query.id for query in queries}
    selected_qrels = {
        query_id: list(qrels[query_id])
        for query_id in sorted(selected_query_ids)
        if query_id in qrels
    }
    selected_qa = _filter_qa_payload(qa, selected_query_ids, known_query_ids)
    sampling = _sampling_summary(
        selected_queries=selected_queries,
        source_queries=queries,
        strategy=strategy,
        seed=seed,
        sample_size=sample_size,
        sample_fraction=sample_fraction,
    )
    source_paths = [manifest_path, artifacts["queries"], artifacts["qrels"], artifacts["qa"]]
    artifact_report = _write_benchmark_artifacts(
        queries=selected_queries,
        qrels=selected_qrels,
        qa=selected_qa,
        output_dir=output_dir,
        name=name,
        description=description,
        source_paths=source_paths,
        sampling=sampling,
    )
    return {
        "ok": True,
        "schema": BENCHMARK_SAMPLE_REPORT_SCHEMA,
        **artifact_report,
    }


def _manifest_artifact_path(manifest_path: str | Path, key: str) -> Path | None:
    manifest_file = Path(manifest_path)
    manifest = _read_json(manifest_file)
    if not isinstance(manifest, Mapping):
        raise BenchmarkGovernanceError("benchmark manifest must be a JSON object")
    if manifest.get("schema") != BENCHMARK_MANIFEST_SCHEMA:
        raise BenchmarkGovernanceError(f"benchmark manifest schema must be {BENCHMARK_MANIFEST_SCHEMA}")
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        raise BenchmarkGovernanceError("benchmark manifest artifacts must be an object")
    value = artifacts.get(key)
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else manifest_file.parent / path


def resolve_benchmark_artifacts(
    *,
    manifest_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    qrels_path: str | Path | None = None,
    qa_path: str | Path | None = None,
) -> dict[str, Path | None]:
    """Resolve benchmark artifact paths from either a manifest or explicit paths."""

    if manifest_path:
        queries = _manifest_artifact_path(manifest_path, "queries")
        qrels = _manifest_artifact_path(manifest_path, "qrels")
        qa = _manifest_artifact_path(manifest_path, "qa")
    else:
        queries = Path(queries_path) if queries_path else None
        qrels = Path(qrels_path) if qrels_path else None
        qa = Path(qa_path) if qa_path else None
    return {"queries": queries, "qrels": qrels, "qa": qa}


def preflight_benchmark_dataset(
    *,
    manifest_path: str | Path | None = None,
    queries_path: str | Path | None = None,
    qrels_path: str | Path | None = None,
    qa_path: str | Path | None = None,
    chunk_snapshot_path: str | Path | None = None,
    gate_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Check benchmark artifacts before a live validation run uses them."""

    issues: list[BenchmarkGovernanceIssue] = []
    artifacts = resolve_benchmark_artifacts(
        manifest_path=manifest_path,
        queries_path=queries_path,
        qrels_path=qrels_path,
        qa_path=qa_path,
    )
    if not artifacts["queries"]:
        issues.append(BenchmarkGovernanceIssue("error", "queries_missing", "benchmark preflight requires queries"))
    if not artifacts["qrels"]:
        issues.append(BenchmarkGovernanceIssue("error", "qrels_missing", "benchmark preflight requires qrels"))

    queries = []
    qrels: dict[str, list[BenchmarkQrel]] = {}
    if artifacts["queries"]:
        try:
            queries = load_validation_queries(artifacts["queries"])
        except (ValidationError, OSError) as exc:
            issues.append(BenchmarkGovernanceIssue("error", "queries_invalid", str(exc), "queries"))
    if artifacts["qrels"]:
        try:
            qrels = load_benchmark_qrels(artifacts["qrels"])
        except (ValidationError, OSError) as exc:
            issues.append(BenchmarkGovernanceIssue("error", "qrels_invalid", str(exc), "qrels"))
    if artifacts["qa"]:
        try:
            _qa_payload(artifacts["qa"])
        except (BenchmarkGovernanceError, OSError) as exc:
            issues.append(BenchmarkGovernanceIssue("error", "qa_invalid", str(exc), "qa"))
    if chunk_snapshot_path:
        try:
            load_chunk_snapshot(chunk_snapshot_path)
        except (ValidationError, OSError) as exc:
            issues.append(BenchmarkGovernanceIssue("error", "chunk_snapshot_invalid", str(exc), "chunk_snapshot"))
    if gate_config_path:
        try:
            load_benchmark_gate(gate_config_path)
        except (ValidationError, OSError) as exc:
            issues.append(BenchmarkGovernanceIssue("error", "gate_config_invalid", str(exc), "gate_config"))

    query_ids = {query.id for query in queries}
    judged_query_ids = set(qrels)
    for query_id in sorted(query_ids - judged_query_ids):
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "query_without_qrels",
                "query has no positive qrels and cannot be used in benchmark validation",
                f"queries.{query_id}",
            )
        )
    for query_id in sorted(judged_query_ids - query_ids):
        issues.append(
            BenchmarkGovernanceIssue(
                "warning",
                "qrels_without_query",
                "qrels entry has no matching query and will not be used",
                f"qrels.{query_id}",
            )
        )

    return {
        "ok": _ok(issues),
        "schema": BENCHMARK_PREFLIGHT_REPORT_SCHEMA,
        "artifacts": {
            **{key: str(value) if value else None for key, value in artifacts.items()},
            "chunk_snapshot": str(chunk_snapshot_path) if chunk_snapshot_path else None,
        },
        "summary": {
            **_issue_counts(issues),
            "query_count": len(queries),
            "judged_query_count": len(judged_query_ids),
            "qrel_count": sum(len(items) for items in qrels.values()),
            "gate_config": str(gate_config_path) if gate_config_path else None,
            "chunk_snapshot": str(chunk_snapshot_path) if chunk_snapshot_path else None,
        },
        "issues": [issue.to_dict() for issue in issues],
    }


def _benchmark_payload(report_path: str | Path) -> Mapping[str, Any]:
    raw = _read_json(report_path)
    if not isinstance(raw, Mapping):
        raise BenchmarkGovernanceError("benchmark report must be a JSON object")
    benchmark = raw.get("benchmark")
    if not isinstance(benchmark, Mapping):
        raise BenchmarkGovernanceError("validation report does not contain a benchmark section")
    metrics = benchmark.get("metrics")
    if not isinstance(metrics, Mapping):
        raise BenchmarkGovernanceError("benchmark report does not contain metrics")
    return raw


def _benchmark_metrics(report: Mapping[str, Any]) -> dict[str, float]:
    benchmark = report.get("benchmark")
    metrics = benchmark.get("metrics") if isinstance(benchmark, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise BenchmarkGovernanceError("benchmark report does not contain metrics")
    return {
        key: float(value)
        for key, value in metrics.items()
        if isinstance(value, (int, float))
    }


def _metric(metrics: Mapping[str, float], *keys: str) -> float | None:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _hint(
    code: str,
    message: str,
    recommendation: str,
    *,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "recommendation": recommendation,
    }
    if evidence:
        payload["evidence"] = dict(evidence)
    return payload


def _dedupe_hints(hints: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hint in hints:
        code = str(hint.get("code", ""))
        message = str(hint.get("message", ""))
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(hint))
    return deduped


def _quality_hints(metrics: Mapping[str, float]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    if metrics.get("empty_result_rate", 0.0) > 0:
        hints.append(
            _hint(
                "empty_retrieval",
                "Some benchmark queries returned no chunks.",
                "Check dataset parse status, routing, query language, and retrieval thresholds.",
                evidence={"empty_result_rate": metrics.get("empty_result_rate")},
            )
        )
    if (
        metrics.get("hit_rate", 1.0) < 1.0
        or metrics.get("recall_at_k", 1.0) < 1.0
        or metrics.get("supporting_document_coverage", 1.0) < 1.0
    ):
        hints.append(
            _hint(
                "retrieval_coverage_gap",
                "At least one query did not retrieve all judged relevant targets.",
                "Inspect qrels, chunk profiles, expected document names, parse status, routing, and top-k/cutoff settings.",
                evidence={
                    key: value
                    for key, value in {
                        "hit_rate": metrics.get("hit_rate"),
                        "recall_at_k": metrics.get("recall_at_k"),
                        "supporting_document_coverage": metrics.get("supporting_document_coverage"),
                    }.items()
                    if value is not None
                },
            )
        )
    if (
        metrics.get("mrr", 1.0) < metrics.get("hit_rate", 1.0)
        or metrics.get("ndcg_at_k", 1.0) < metrics.get("recall_at_k", 1.0)
        or metrics.get("map_at_k", 1.0) < metrics.get("recall_at_k", 1.0)
    ):
        hints.append(
            _hint(
                "ranking_gap",
                "Relevant evidence is present but not consistently ranked early.",
                "Compare rerank settings, chunk granularity, query wording, and noisy bridge terms.",
                evidence={
                    key: value
                    for key, value in {
                        "mrr": metrics.get("mrr"),
                        "ndcg_at_k": metrics.get("ndcg_at_k"),
                        "map_at_k": metrics.get("map_at_k"),
                    }.items()
                    if value is not None
                },
            )
        )
    if metrics.get("strict_chunk_recall_at_k", 1.0) < 1.0:
        hints.append(
            _hint(
                "strict_chunk_recall_gap",
                "Expected stable chunk evidence was not fully retrieved.",
                "Inspect expected_chunks hashes, chunk boundaries, parser output, and retrieval top-k.",
                evidence={"strict_chunk_recall_at_k": metrics.get("strict_chunk_recall_at_k")},
            )
        )
    pollution = _metric(
        metrics,
        "tag_pollution_rate",
        "pollution_rate",
        "wrong_doc_rate",
        "wrong_document_rate",
        "pollution_cost",
        "wrong_doc_cost",
    )
    if pollution and pollution > 0:
        hints.append(
            _hint(
                "tag_pollution",
                "Retrieved evidence includes wrong-document or pollution signals.",
                "Review tag filters, source routing, bridge terms, and suppression candidates before tuning recall upward.",
                evidence={"pollution_metric": pollution},
            )
        )
    grounding = _metric(metrics, "grounded_answer_rate", "answer_grounding_rate", "answer_support_rate", "support_rate")
    unsupported = _metric(metrics, "unsupported_answer_rate", "ungrounded_answer_rate")
    if (grounding is not None and grounding < 1.0) or (unsupported is not None and unsupported > 0):
        hints.append(
            _hint(
                "generation_grounding_gap",
                "Generated answers are not fully supported by retrieved evidence.",
                "Require grounded evidence spans, verify answer support checks, and keep ungrounded QA out of benchmark gates.",
                evidence={
                    key: value
                    for key, value in {
                        "grounding_rate": grounding,
                        "unsupported_answer_rate": unsupported,
                    }.items()
                    if value is not None
                },
            )
        )
    citation_coverage = _metric(metrics, "citation_coverage", "citation_recall", "cited_evidence_rate")
    citation_precision = _metric(metrics, "citation_precision", "valid_citation_rate")
    invalid_citations = _metric(metrics, "invalid_citation_rate")
    if (
        (citation_coverage is not None and citation_coverage < 1.0)
        or (citation_precision is not None and citation_precision < 1.0)
        or (invalid_citations is not None and invalid_citations > 0)
    ):
        hints.append(
            _hint(
                "citation_gap",
                "Citation coverage or validity is below target.",
                "Audit cited evidence ranks, citation formatting, and unsupported cited or uncited answer spans.",
                evidence={
                    key: value
                    for key, value in {
                        "citation_coverage": citation_coverage,
                        "citation_precision": citation_precision,
                        "invalid_citation_rate": invalid_citations,
                    }.items()
                    if value is not None
                },
            )
        )
    over_abstention = _metric(metrics, "over_abstention_rate", "false_abstention_rate")
    abstention = _metric(metrics, "abstention_rate")
    if (over_abstention and over_abstention > 0) or (
        abstention is not None and abstention > 0 and metrics.get("hit_rate", 0.0) >= 0.8
    ):
        hints.append(
            _hint(
                "over_abstention",
                "The system abstained despite evidence being available.",
                "Inspect confidence thresholds, answerability labels, and prompt instructions for excessive refusal behavior.",
                evidence={
                    key: value
                    for key, value in {
                        "over_abstention_rate": over_abstention,
                        "abstention_rate": abstention,
                        "hit_rate": metrics.get("hit_rate"),
                    }.items()
                    if value is not None
                },
            )
        )
    return _dedupe_hints(hints)


def summarize_benchmark_report(report_path: str | Path) -> dict[str, Any]:
    """Summarize a validation benchmark report without rerunning retrieval."""

    report = _benchmark_payload(report_path)
    benchmark = report["benchmark"]
    metrics = _benchmark_metrics(report)
    gate = benchmark.get("gate") if isinstance(benchmark, Mapping) else None
    return {
        "ok": bool(report.get("ok", True)) and (bool(gate.get("ok", True)) if isinstance(gate, Mapping) else True),
        "schema": BENCHMARK_SUMMARY_REPORT_SCHEMA,
        "report": str(report_path),
        "dataset": report.get("dataset", {}),
        "metrics": metrics,
        "query_type_breakdown": benchmark.get("query_type_breakdown", {}),
        "gate": gate,
        "baseline": benchmark.get("baseline"),
        "quality_hints": _quality_hints(metrics),
    }


def gate_benchmark_report(
    *,
    report_path: str | Path,
    gate_config_path: str | Path,
    baseline_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply a benchmark gate to an existing validation report."""

    report = _benchmark_payload(report_path)
    metrics = _benchmark_metrics(report)
    gate: BenchmarkGate = load_benchmark_gate(gate_config_path)
    baseline_metrics = load_benchmark_baseline(baseline_report_path) if baseline_report_path else None
    baseline_delta = None
    if baseline_metrics:
        baseline_delta = {
            key: metrics[key] - float(value)
            for key, value in baseline_metrics.items()
            if key in metrics
        }
    gate_result = evaluate_benchmark_gate(metrics, gate=gate, baseline_delta=baseline_delta)
    return {
        "ok": bool(gate_result and gate_result["ok"]),
        "schema": BENCHMARK_GATE_REPORT_SCHEMA,
        "report": str(report_path),
        "gate_config": str(gate_config_path),
        "baseline_report": str(baseline_report_path) if baseline_report_path else None,
        "metrics": metrics,
        "baseline_delta": baseline_delta,
        "gate": gate_result,
        "quality_hints": _dedupe_hints(
            [
                *_quality_hints(metrics),
                *(_regression_hints(_delta_from_baseline_delta(metrics, baseline_delta)) if baseline_delta else []),
            ]
        ),
    }


def _metric_delta(
    current_metrics: Mapping[str, float],
    baseline_metrics: Mapping[str, float],
) -> dict[str, dict[str, float | str]]:
    deltas: dict[str, dict[str, float | str]] = {}
    metric_names = sorted(set(current_metrics) | set(baseline_metrics))
    for key in metric_names:
        if key not in current_metrics or key not in baseline_metrics:
            continue
        before = float(baseline_metrics[key])
        after = float(current_metrics[key])
        absolute = after - before
        relative = absolute / before if before else None
        direction = "unchanged"
        if absolute > 0:
            direction = "up"
        elif absolute < 0:
            direction = "down"
        deltas[key] = {
            "baseline": before,
            "current": after,
            "absolute": absolute,
            "relative": relative,
            "direction": direction,
        }
    return deltas


def _delta_from_baseline_delta(
    current_metrics: Mapping[str, float],
    baseline_delta: Mapping[str, float] | None,
) -> dict[str, dict[str, float | str]]:
    if not baseline_delta:
        return {}
    deltas: dict[str, dict[str, float | str]] = {}
    for key, absolute in baseline_delta.items():
        current = current_metrics.get(key)
        if not isinstance(current, (int, float)):
            continue
        baseline = float(current) - float(absolute)
        direction = "unchanged"
        if absolute > 0:
            direction = "up"
        elif absolute < 0:
            direction = "down"
        deltas[key] = {
            "baseline": baseline,
            "current": float(current),
            "absolute": float(absolute),
            "relative": float(absolute) / baseline if baseline else None,
            "direction": direction,
        }
    return deltas


def _delta_evidence(metric: str, delta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": metric,
        "baseline": delta.get("baseline"),
        "current": delta.get("current"),
        "absolute": delta.get("absolute"),
    }


def _regression_hints(deltas: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    coverage_metrics = (
        "hit_rate",
        "recall_at_k",
        "precision_at_k",
        "supporting_document_coverage",
        "strict_chunk_recall_at_k",
        "expected_chunk_hit_rate",
    )
    ranking_metrics = ("mrr", "ndcg_at_k", "map_at_k", "expected_evidence_rank")
    grounding_metrics = ("grounded_answer_rate", "answer_grounding_rate", "answer_support_rate", "support_rate")
    citation_metrics = ("citation_coverage", "citation_recall", "cited_evidence_rate", "citation_precision", "valid_citation_rate")
    pollution_metrics = ("tag_pollution_rate", "pollution_rate", "wrong_doc_rate", "wrong_document_rate", "pollution_cost", "wrong_doc_cost")
    abstention_metrics = ("over_abstention_rate", "false_abstention_rate", "abstention_rate")
    cost_latency_metrics = (
        "latency_ms",
        "average_latency_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "cost_usd",
        "estimated_cost_usd",
        "cost_per_query_usd",
    )

    for metric in coverage_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) < 0:
            hints.append(
                _hint(
                    "retrieval_coverage_gap",
                    f"{metric} decreased versus baseline.",
                    "Inspect changed profile settings, qrels coverage, routing, parser output, and retrieval top-k.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    for metric in ranking_metrics:
        delta = deltas.get(metric)
        if not isinstance(delta, Mapping):
            continue
        absolute = float(delta.get("absolute", 0.0))
        regressed = absolute < 0 if metric != "expected_evidence_rank" else absolute > 0
        if regressed:
            hints.append(
                _hint(
                    "ranking_gap",
                    f"{metric} regressed versus baseline.",
                    "Compare rerank settings, chunk granularity, noisy bridge terms, and changed retrieval thresholds.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    empty_delta = deltas.get("empty_result_rate")
    if isinstance(empty_delta, Mapping) and float(empty_delta.get("absolute", 0.0)) > 0:
        hints.append(
            _hint(
                "empty_retrieval",
                "empty_result_rate increased versus baseline.",
                "Check parse completion, retrieval thresholds, route selection, and query language coverage.",
                evidence=_delta_evidence("empty_result_rate", empty_delta),
            )
        )
    for metric in pollution_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) > 0:
            hints.append(
                _hint(
                    "tag_pollution",
                    f"{metric} increased versus baseline.",
                    "Review tag filters, wrong-document hits, source routing, bridge terms, and suppression candidates.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    for metric in grounding_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) < 0:
            hints.append(
                _hint(
                    "generation_grounding_gap",
                    f"{metric} decreased versus baseline.",
                    "Validate grounded evidence spans and reject ungrounded generated QA before benchmark use.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    unsupported_delta = deltas.get("unsupported_answer_rate") or deltas.get("ungrounded_answer_rate")
    if isinstance(unsupported_delta, Mapping) and float(unsupported_delta.get("absolute", 0.0)) > 0:
        hints.append(
            _hint(
                "generation_grounding_gap",
                "Unsupported answer rate increased versus baseline.",
                "Inspect answer support checks, generated evidence spans, and prompt grounding instructions.",
                evidence=_delta_evidence("unsupported_answer_rate", unsupported_delta),
            )
        )
    for metric in citation_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) < 0:
            hints.append(
                _hint(
                    "citation_gap",
                    f"{metric} decreased versus baseline.",
                    "Audit cited evidence ranks, citation formatting, and unsupported cited or uncited answer spans.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    invalid_delta = deltas.get("invalid_citation_rate")
    if isinstance(invalid_delta, Mapping) and float(invalid_delta.get("absolute", 0.0)) > 0:
        hints.append(
            _hint(
                "citation_gap",
                "Invalid citation rate increased versus baseline.",
                "Audit citation IDs, cited evidence ranks, and answer rendering templates.",
                evidence=_delta_evidence("invalid_citation_rate", invalid_delta),
            )
        )
    for metric in abstention_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) > 0:
            hints.append(
                _hint(
                    "over_abstention",
                    f"{metric} increased versus baseline.",
                    "Inspect answerability labels, confidence thresholds, and refusal instructions.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    for metric in cost_latency_metrics:
        delta = deltas.get(metric)
        if isinstance(delta, Mapping) and float(delta.get("absolute", 0.0)) > 0:
            hints.append(
                _hint(
                    "cost_or_latency_regression",
                    f"{metric} increased versus baseline.",
                    "Compare top-k, rerank, chunk count, model/provider settings, retry behavior, and caching.",
                    evidence=_delta_evidence(metric, delta),
                )
            )
    return _dedupe_hints(hints)


def trend_benchmark_reports(
    *,
    current_report_path: str | Path,
    baseline_report_path: str | Path,
    gate_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare current benchmark metrics with a baseline report."""

    current_report = _benchmark_payload(current_report_path)
    current_metrics = _benchmark_metrics(current_report)
    baseline_metrics = load_benchmark_baseline(baseline_report_path)
    deltas = _metric_delta(current_metrics, baseline_metrics)
    gate_result = None
    if gate_config_path:
        gate = load_benchmark_gate(gate_config_path)
        baseline_delta = {
            key: float(item["absolute"])
            for key, item in deltas.items()
            if isinstance(item.get("absolute"), (int, float))
        }
        gate_result = evaluate_benchmark_gate(current_metrics, gate=gate, baseline_delta=baseline_delta)
    return {
        "ok": bool(gate_result.get("ok", True)) if isinstance(gate_result, Mapping) else True,
        "schema": BENCHMARK_TREND_REPORT_SCHEMA,
        "current_report": str(current_report_path),
        "baseline_report": str(baseline_report_path),
        "gate_config": str(gate_config_path) if gate_config_path else None,
        "dataset": current_report.get("dataset", {}),
        "metrics": current_metrics,
        "baseline_metrics": baseline_metrics,
        "delta": deltas,
        "gate": gate_result,
        "quality_hints": _dedupe_hints([*_quality_hints(current_metrics), *_regression_hints(deltas)]),
    }


def delta_benchmark_reports(
    *,
    current_report_path: str | Path,
    baseline_report_path: str | Path,
) -> dict[str, Any]:
    """Produce a focused metric delta report between two benchmark reports."""

    current_report = _benchmark_payload(current_report_path)
    current_metrics = _benchmark_metrics(current_report)
    baseline_metrics = load_benchmark_baseline(baseline_report_path)
    deltas = _metric_delta(current_metrics, baseline_metrics)
    improved = [key for key, value in deltas.items() if value.get("direction") == "up"]
    regressed = [key for key, value in deltas.items() if value.get("direction") == "down"]
    unchanged = [key for key, value in deltas.items() if value.get("direction") == "unchanged"]
    return {
        "ok": True,
        "schema": BENCHMARK_DELTA_REPORT_SCHEMA,
        "current_report": str(current_report_path),
        "baseline_report": str(baseline_report_path),
        "dataset": current_report.get("dataset", {}),
        "metrics": current_metrics,
        "baseline_metrics": baseline_metrics,
        "delta": deltas,
        "summary": {
            "metric_count": len(deltas),
            "improved": sorted(improved),
            "regressed": sorted(regressed),
            "unchanged": sorted(unchanged),
        },
        "quality_hints": _dedupe_hints([*_quality_hints(current_metrics), *_regression_hints(deltas)]),
    }


def render_benchmark_governance_markdown(report: Mapping[str, Any], *, title: str = "RAGFlow Benchmark Report") -> str:
    """Render a compact Markdown summary for benchmark governance reports."""

    lines = [
        f"# {title}",
        "",
        f"- schema: `{report.get('schema', 'unknown')}`",
        f"- ok: `{str(bool(report.get('ok'))).lower()}`",
    ]
    summary = report.get("summary")
    if isinstance(summary, Mapping):
        for key in sorted(summary):
            lines.append(f"- {key}: `{summary[key]}`")
    metrics = report.get("metrics")
    if isinstance(metrics, Mapping):
        lines.extend(["", "## Metrics", ""])
        for key in sorted(metrics):
            value = metrics[key]
            lines.append(f"- {key}: `{value}`")
    delta = report.get("delta")
    if isinstance(delta, Mapping) and delta:
        lines.extend(["", "## Delta", "", "| metric | baseline | current | absolute | direction |", "| --- | ---: | ---: | ---: | --- |"])
        for key in sorted(delta):
            item = delta[key]
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| {metric} | `{baseline}` | `{current}` | `{absolute}` | {direction} |".format(
                    metric=key,
                    baseline=item.get("baseline", ""),
                    current=item.get("current", ""),
                    absolute=item.get("absolute", ""),
                    direction=item.get("direction", ""),
                )
            )
    gate = report.get("gate")
    if isinstance(gate, Mapping) and isinstance(gate.get("checks"), list):
        lines.extend(["", "## Gate", "", "| metric | actual | operator | threshold | status |", "| --- | ---: | --- | ---: | --- |"])
        for check in gate["checks"]:
            if not isinstance(check, Mapping):
                continue
            lines.append(
                "| {metric} | `{actual}` | `{operator}` | `{threshold}` | {status} |".format(
                    metric=check.get("metric", ""),
                    actual=check.get("actual", ""),
                    operator=check.get("operator", ""),
                    threshold=check.get("threshold", ""),
                    status="passed" if check.get("passed") else "failed",
                )
            )
    issues = report.get("issues")
    if isinstance(issues, list) and issues:
        lines.extend(["", "## Issues", "", "| severity | code | field | message |", "| --- | --- | --- | --- |"])
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(
                "| {severity} | {code} | {field} | {message} |".format(
                    severity=issue.get("severity", ""),
                    code=issue.get("code", ""),
                    field=issue.get("field", ""),
                    message=str(issue.get("message", "")).replace("|", "\\|"),
                )
            )
    hints = report.get("quality_hints")
    if isinstance(hints, list) and hints:
        lines.extend(["", "## Quality Hints", ""])
        for hint in hints:
            if isinstance(hint, Mapping):
                lines.append(f"- `{hint.get('code')}`: {hint.get('message')}")
    lines.append("")
    return "\n".join(lines)
