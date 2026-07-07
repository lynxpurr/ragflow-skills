"""Offline benchmark lifecycle helpers for RAGFlow skills."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
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
from .runtime_resilience import build_runtime_partial_failure_report
from .handoff import CJK_PHRASE_RE, STOPWORDS, WORD_RE
from .metadata_governance import lint_tagset_file, tagset_report_file
from .kb_build import BuildError, KB_REFRESH_REPORT_SCHEMA, load_kb_refresh_report, summarize_kb_refresh_observed_state


BENCHMARK_MANIFEST_SCHEMA = "ragflow_benchmark_manifest_v1"
BENCHMARK_QUERIES_SCHEMA = "ragflow_benchmark_queries_v1"
BENCHMARK_QRELS_SCHEMA = "ragflow_benchmark_qrels_v1"
GROUNDED_QA_SCHEMA = "ragflow_grounded_qa_v1"
GROUNDED_QA_GENERATE_REPORT_SCHEMA = "ragflow_grounded_qa_generate_report_v1"
GROUNDED_QA_GENERATE_CHECKPOINT_SCHEMA = "ragflow_grounded_qa_generate_checkpoint_v1"
GROUNDED_QA_VALIDATE_REPORT_SCHEMA = "ragflow_grounded_qa_validate_report_v1"
GROUNDED_QA_EVIDENCE_MAP_SCHEMA = "ragflow_grounded_qa_evidence_map_v1"
GROUNDED_QA_EVIDENCE_MAP_REPORT_SCHEMA = "ragflow_grounded_qa_evidence_map_report_v1"
GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA = "ragflow_grounded_qa_suggestion_request_v1"
GROUNDED_QA_SUGGESTION_REVIEW_REPORT_SCHEMA = "ragflow_grounded_qa_suggestion_review_report_v1"
BENCHMARK_IMPORT_REPORT_SCHEMA = "ragflow_benchmark_import_report_v1"
BENCHMARK_IMPORT_CHECKPOINT_SCHEMA = "ragflow_benchmark_import_checkpoint_v1"
BENCHMARK_SAMPLE_REPORT_SCHEMA = "ragflow_benchmark_sample_report_v1"
BENCHMARK_PREFLIGHT_REPORT_SCHEMA = "ragflow_benchmark_preflight_report_v1"
BENCHMARK_SUMMARY_REPORT_SCHEMA = "ragflow_benchmark_summary_report_v1"
BENCHMARK_GATE_REPORT_SCHEMA = "ragflow_benchmark_gate_report_v1"
BENCHMARK_TREND_REPORT_SCHEMA = "ragflow_benchmark_trend_report_v1"
BENCHMARK_DELTA_REPORT_SCHEMA = "ragflow_benchmark_delta_report_v1"
BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA = "ragflow_benchmark_retrieval_suggestion_report_v1"
SUPPRESSION_REPORT_SCHEMA = "ragflow_suppression_report_v1"
CHUNK_SNAPSHOT_REPORT_SCHEMA = "ragflow_chunk_snapshot_report_v1"
_SUPPRESSION_STOPWORDS = STOPWORDS | {
    "appear",
    "appears",
    "being",
    "can",
    "chunk",
    "chunks",
    "document",
    "documents",
    "does",
    "doing",
    "doesn",
    "example",
    "include",
    "includes",
    "issue",
    "issues",
    "query",
    "queries",
    "result",
    "results",
    "retrieval",
    "source",
    "sources",
    "the",
    "this",
    "those",
    "what",
    "when",
    "where",
    "which",
    "why",
    "wrong",
}


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


def _rate(count: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(count) / float(total), 4)


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


def _source_title(source: _SourceText) -> str:
    for line in source.text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title[:80]
    stem = Path(source.name).stem
    return (stem or source.name or "source")[:80]


def _evidence_line_candidates(text: str, *, max_span_chars: int) -> list[str]:
    candidates: list[str] = []
    in_code_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped.startswith("#") or stripped.startswith("!"):
            continue
        if re.fullmatch(r"[-*_=\s]{3,}", stripped):
            continue
        if re.fullmatch(r"\|?[\s:|.-]+\|?", stripped):
            continue
        if len(stripped) <= max_span_chars:
            candidates.append(stripped)
            continue
        pieces = [piece.strip() for piece in re.split(r"(?<=[.!?。！？])\s+", stripped) if piece.strip()]
        for piece in pieces:
            if len(piece) <= max_span_chars:
                candidates.append(piece)
            else:
                candidates.append(piece[:max_span_chars].rstrip())
    return candidates


def _span_topic(span: str) -> str:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", span)
    if terms:
        return " ".join(terms[:5])[:80]
    return "the cited evidence"


def _generate_question(*, source: _SourceText, span: str) -> str:
    title = _source_title(source)
    topic = _span_topic(span)
    return f"What does {title} state about {topic}?"


def _qa_candidate_spans(
    sources: list[_SourceText],
    *,
    min_span_chars: int,
    max_span_chars: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for span in _evidence_line_candidates(source.text, max_span_chars=max_span_chars):
            if len(span) < min_span_chars:
                continue
            key = (_source_key(source.name), span.casefold())
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"source": source, "span": span})
    return candidates


def _qa_generate_item(candidate: Mapping[str, Any], *, item_id: str, strategy: str) -> dict[str, Any]:
    source = candidate["source"]
    span = str(candidate["span"])
    return {
        "id": item_id,
        "query_id": item_id,
        "question": _generate_question(source=source, span=span),
        "answer": span,
        "evidence": [
            {
                "document": source.name,
                "text": span,
            }
        ],
        "metadata": {
            "generator": "deterministic_source_span_v1",
            "source": source.name,
            "source_path": source.path,
            "strategy": strategy,
        },
    }


def _read_qa_generate_checkpoint(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise BenchmarkGovernanceError("QA generate checkpoint must be a JSON object")
    if payload.get("schema") != GROUNDED_QA_GENERATE_CHECKPOINT_SCHEMA:
        raise BenchmarkGovernanceError(
            f"QA generate checkpoint schema must be {GROUNDED_QA_GENERATE_CHECKPOINT_SCHEMA}"
        )
    processed = payload.get("processed_item_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise BenchmarkGovernanceError("QA generate checkpoint processed_item_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise BenchmarkGovernanceError("QA generate checkpoint source_hashes must be an object")
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        raise BenchmarkGovernanceError("QA generate checkpoint parameters must be an object")
    return dict(payload)


def _validate_qa_generate_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
    output_path: str | Path,
    count: int,
    strategy: str,
    seed: int,
    min_span_chars: int,
    max_span_chars: int,
) -> None:
    if dict(checkpoint.get("source_hashes") or {}) != dict(source_hashes):
        raise BenchmarkGovernanceError("QA generate checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("output") or "") != str(Path(output_path)):
        raise BenchmarkGovernanceError("QA generate checkpoint output does not match current output")
    expected_parameters = {
        "count": count,
        "strategy": strategy,
        "seed": seed,
        "min_span_chars": min_span_chars,
        "max_span_chars": max_span_chars,
    }
    if dict(checkpoint.get("parameters") or {}) != expected_parameters:
        raise BenchmarkGovernanceError("QA generate checkpoint parameters do not match current request")


def _write_qa_generate_checkpoint(
    *,
    checkpoint_path: str | Path,
    source_hashes: Mapping[str, str],
    output_path: str | Path,
    count: int,
    strategy: str,
    seed: int,
    min_span_chars: int,
    max_span_chars: int,
    processed_item_ids: Iterable[str],
    total_item_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_item_ids))
    payload = {
        "schema": GROUNDED_QA_GENERATE_CHECKPOINT_SCHEMA,
        "created_at": created_at or _now(),
        "updated_at": _now(),
        "source_hashes": dict(source_hashes),
        "output": str(Path(output_path)),
        "parameters": {
            "count": count,
            "strategy": strategy,
            "seed": seed,
            "min_span_chars": min_span_chars,
            "max_span_chars": max_span_chars,
        },
        "processed_item_ids": processed,
        "summary": {
            "processed_item_count": len(processed),
            "total_item_count": total_item_count,
            "remaining_item_count": max(total_item_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    _write_json(checkpoint_path, payload)
    return payload


def generate_grounded_qa(
    *,
    output_path: str | Path,
    sources_path: str | Path | None = None,
    source_dir: str | Path | None = None,
    count: int = 20,
    strategy: str = "first",
    seed: int = 0,
    min_span_chars: int = 40,
    max_span_chars: int = 240,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Generate a deterministic, offline grounded QA scaffold from source spans."""

    if resume and not checkpoint_path:
        raise BenchmarkGovernanceError("QA generate --resume requires --checkpoint")
    if batch_size is not None and not checkpoint_path:
        raise BenchmarkGovernanceError("QA generate --batch-size requires --checkpoint")
    if batch_size is not None and batch_size <= 0:
        raise BenchmarkGovernanceError("QA generate batch_size must be positive")

    issues: list[BenchmarkGovernanceIssue] = []
    if not sources_path and not source_dir:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_generate_sources_missing",
                "provide --sources or --source-dir for deterministic QA generation",
                "sources",
            )
        )
        sources: list[_SourceText] = []
    else:
        sources = _load_source_texts(sources_path=sources_path, source_dir=source_dir)

    if count <= 0:
        issues.append(BenchmarkGovernanceIssue("error", "qa_generate_count_invalid", "count must be positive", "count"))
    if min_span_chars <= 0:
        issues.append(
            BenchmarkGovernanceIssue("error", "qa_generate_min_span_invalid", "min span chars must be positive", "min_span_chars")
        )
    if max_span_chars < min_span_chars:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_generate_span_range_invalid",
                "max span chars must be greater than or equal to min span chars",
                "max_span_chars",
            )
        )
    if strategy not in {"first", "random"}:
        issues.append(BenchmarkGovernanceIssue("error", "qa_generate_strategy_invalid", "strategy must be first or random", "strategy"))

    candidates = [] if issues else _qa_candidate_spans(sources, min_span_chars=min_span_chars, max_span_chars=max_span_chars)
    if not candidates and not any(issue.severity == "error" for issue in issues):
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_generate_candidates_empty",
                "no source spans met the QA generation length constraints",
                "sources",
                "Lower --min-span-chars or provide source files with complete prose sentences.",
            )
        )
    if strategy == "random" and candidates:
        rng = random.Random(seed)
        rng.shuffle(candidates)

    source_hashes = _source_hash_map([sources_path, source_dir])
    checkpoint: dict[str, Any] | None = None
    processed_item_ids: list[str] = []
    checkpoint_created_at: str | None = None
    if checkpoint_path and resume:
        checkpoint = _read_qa_generate_checkpoint(Path(checkpoint_path))
        _validate_qa_generate_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            output_path=output_path,
            count=count,
            strategy=strategy,
            seed=seed,
            min_span_chars=min_span_chars,
            max_span_chars=max_span_chars,
        )
        processed_item_ids = list(checkpoint.get("processed_item_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    target_candidates = candidates[: max(0, count)]
    item_ids = [f"qa-{index:04d}" for index in range(1, len(target_candidates) + 1)]
    unknown_processed = sorted(set(processed_item_ids) - set(item_ids))
    if unknown_processed:
        raise BenchmarkGovernanceError(
            "QA generate checkpoint contains item ids that are not present in current candidates: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_item_ids)
    remaining_item_ids = [item_id for item_id in item_ids if item_id not in processed_set]
    next_item_ids = remaining_item_ids if batch_size is None else remaining_item_ids[:batch_size]
    selected_item_ids = set(processed_item_ids) | set(next_item_ids)
    items = [
        _qa_generate_item(candidate, item_id=item_id, strategy=strategy)
        for candidate, item_id in zip(target_candidates, item_ids, strict=True)
        if item_id in selected_item_ids
    ]
    completed = _ok(issues) and len(selected_item_ids) >= len(item_ids)

    qa_payload = {
        "schema": GROUNDED_QA_SCHEMA,
        "created_at": _now(),
        "metadata": {
            "generator": "deterministic_source_span_v1",
            "strategy": strategy,
            "seed": seed,
            "requested_count": count,
            "min_span_chars": min_span_chars,
            "max_span_chars": max_span_chars,
        },
        "items": items,
    }
    _write_json(output_path, qa_payload)

    checkpoint_payload = None
    if checkpoint_path and _ok(issues):
        ordered_processed = [item_id for item_id in item_ids if item_id in selected_item_ids]
        checkpoint_payload = _write_qa_generate_checkpoint(
            checkpoint_path=checkpoint_path,
            source_hashes=source_hashes,
            output_path=output_path,
            count=count,
            strategy=strategy,
            seed=seed,
            min_span_chars=min_span_chars,
            max_span_chars=max_span_chars,
            processed_item_ids=ordered_processed,
            total_item_count=len(item_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    checkpoint_report = {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "batch_size": batch_size,
        "processed_item_count": len(selected_item_ids),
        "new_item_count": len(next_item_ids),
        "remaining_item_count": max(len(item_ids) - len(selected_item_ids), 0),
        "completed": completed,
        "next_item_ids": list(next_item_ids),
    }

    summary = {
        **_issue_counts(issues),
        "source_count": len(sources),
        "candidate_span_count": len(candidates),
        "item_count": len(items),
        "requested_count": count,
        "completed": completed,
        "strategy": strategy,
        "seed": seed,
        "min_span_chars": min_span_chars,
        "max_span_chars": max_span_chars,
        "checkpoint_enabled": bool(checkpoint_path),
        "checkpoint_resume": bool(resume),
        "checkpoint_new_item_count": len(next_item_ids),
        "checkpoint_remaining_item_count": max(len(item_ids) - len(selected_item_ids), 0),
    }
    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_GENERATE_REPORT_SCHEMA,
        "grounded_qa": str(output_path),
        "completed": completed,
        "artifacts": {
            "sources": str(sources_path) if sources_path else None,
            "source_dir": str(source_dir) if source_dir else None,
            "output": str(output_path),
        },
        "summary": summary,
        "checkpoint": checkpoint_report,
        **({"checkpoint_payload": checkpoint_payload} if checkpoint_payload else {}),
        "issues": [issue.to_dict() for issue in issues],
    }


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_request_item(source: _SourceText, *, index: int, include_excerpts: bool, max_excerpt_chars: int) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"source-{index:04d}",
        "name": source.name,
        "path": source.path,
        "aliases": list(source.aliases),
        "text_sha256": hashlib.sha256(source.text.encode("utf-8")).hexdigest(),
        "char_count": len(source.text),
        "line_count": len(source.text.splitlines()),
    }
    if include_excerpts:
        excerpt = source.text[: max(0, max_excerpt_chars)]
        item["excerpt"] = excerpt
        item["excerpt_truncated"] = len(source.text) > len(excerpt)
        item["max_excerpt_chars"] = max_excerpt_chars
    return {key: value for key, value in item.items() if value not in (None, [], "")}


def create_grounded_qa_suggestion_request(
    *,
    sources_path: str | Path | None = None,
    source_dir: str | Path | None = None,
    target_count: int = 20,
    question_types: Iterable[str] | None = None,
    include_excerpts: bool = False,
    max_excerpt_chars: int = 1200,
    min_evidence_chars: int = 20,
    max_evidence_chars: int = 240,
) -> dict[str, Any]:
    """Create a no-LLM grounded-QA request artifact for an external model.

    The request packages source identity, hashes, policy, and exact evidence
    requirements. It never invokes an LLM and never mutates RAGFlow.
    """

    issues: list[BenchmarkGovernanceIssue] = []
    if not sources_path and not source_dir:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_sources_missing",
                "provide --sources or --source-dir so external QA suggestions can be grounded",
                "sources",
            )
        )
        sources: list[_SourceText] = []
    else:
        sources = _load_source_texts(sources_path=sources_path, source_dir=source_dir)

    if target_count <= 0:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_target_count_invalid",
                "target count must be positive",
                "target_count",
            )
        )
    if max_excerpt_chars < 0:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_max_excerpt_chars_invalid",
                "max excerpt chars must not be negative",
                "max_excerpt_chars",
            )
        )
    if min_evidence_chars <= 0:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_min_evidence_chars_invalid",
                "minimum evidence chars must be positive",
                "min_evidence_chars",
            )
        )
    if max_evidence_chars < min_evidence_chars:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_evidence_range_invalid",
                "maximum evidence chars must be greater than or equal to minimum evidence chars",
                "max_evidence_chars",
            )
        )

    normalized_question_types = [
        str(item).strip()
        for item in (question_types or ("direct_fact", "short_query", "negative_control"))
        if str(item).strip()
    ]
    if not normalized_question_types:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_question_types_empty",
                "at least one question type must be supplied",
                "question_types",
            )
        )

    source_items = [
        _source_request_item(
            source,
            index=index,
            include_excerpts=include_excerpts,
            max_excerpt_chars=max_excerpt_chars,
        )
        for index, source in enumerate(sources, start=1)
    ]
    source_hashes = _source_hashes([sources_path, source_dir])
    policy = {
        "target_count": target_count,
        "question_types": normalized_question_types,
        "min_evidence_chars": min_evidence_chars,
        "max_evidence_chars": max_evidence_chars,
        "require_answer": True,
        "require_exact_evidence_spans": True,
        "require_evidence_document": True,
        "require_advisory_marker": True,
        "require_generated_marker": True,
    }
    request_core = {
        "schema": GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA,
        "grounded_qa_schema": GROUNDED_QA_SCHEMA,
        "source_hashes": source_hashes,
        "policy": policy,
        "sources": source_items,
    }

    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA,
        "created_at": _now(),
        "grounded_qa_schema": GROUNDED_QA_SCHEMA,
        "advisory": True,
        "llm_invoked": False,
        "request_hash": _stable_digest(request_core),
        "artifacts": {
            "sources": str(sources_path) if sources_path else None,
            "source_dir": str(source_dir) if source_dir else None,
        },
        "summary": {
            **_issue_counts(issues),
            "source_count": len(source_items),
            "source_hash_count": len(source_hashes),
            "target_count": target_count,
            "question_type_count": len(normalized_question_types),
            "include_excerpts": include_excerpts,
            "max_excerpt_chars": max_excerpt_chars,
            "llm_invoked": False,
        },
        "redaction": {
            "source_excerpts_included": include_excerpts,
            "source_paths_included": True,
            "review_redaction_report_recommended": True,
            "notes": [
                "Run review commands with --redaction-report before sharing request, review, or Markdown outputs externally.",
                "Do not include credentials, private endpoints, or authorization material in candidate QA.",
            ],
        },
        "instructions": {
            "purpose": "Suggest advisory ragflow_grounded_qa_v1 items grounded only in the listed sources.",
            "required_output_schema": GROUNDED_QA_SCHEMA,
            "requirements": [
                "Return JSON only.",
                "Set top-level advisory to true.",
                "Set top-level generated to true.",
                "Use only source documents listed in this request.",
                "Every QA item must include question, answer, and evidence.",
                "Every evidence item must include document and exact text copied from a listed source.",
                "Do not invent facts, source hashes, credentials, private endpoints, or authorization material.",
                "Generated QA is advisory and must pass ragflow-kb-build qa suggest-review before benchmark use.",
            ],
            "review_command": (
                "ragflow-kb-build qa suggest-review --candidate CANDIDATE.json --request REQUEST.json "
                "--sources SOURCES_OR --source-dir SOURCE_DIR"
            ),
        },
        "policy": policy,
        "source_hashes": source_hashes,
        "sources": source_items,
        "issues": [issue.to_dict() for issue in issues],
    }


def _request_source_aliases(request: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    raw_sources = request.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("name", "path"):
            value = source.get(key)
            if isinstance(value, str) and not value.startswith("<redacted:"):
                aliases.update(_source_ref_keys(value))
        raw_aliases = source.get("aliases")
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if isinstance(alias, str) and not alias.startswith("<redacted:"):
                    aliases.update(_source_ref_keys(alias))
    return {alias for alias in aliases if alias}


def _review_issue_from_report(*, prefix: str, raw_issue: Mapping[str, Any]) -> BenchmarkGovernanceIssue:
    return BenchmarkGovernanceIssue(
        severity=str(raw_issue.get("severity", "warning")),
        code=f"{prefix}_{raw_issue.get('code', 'issue')}",
        message=str(raw_issue.get("message", "")),
        field=raw_issue.get("field") if isinstance(raw_issue.get("field"), str) else None,
        recommendation=raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
    )


def _candidate_grounded_qa_items(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = candidate.get("items")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _append_suggestion_evidence_policy_issues(
    *,
    candidate: Mapping[str, Any],
    request_aliases: set[str],
    issues: list[BenchmarkGovernanceIssue],
) -> None:
    for item_index, item in enumerate(_candidate_grounded_qa_items(candidate)):
        item_id = _qa_item_identifier(item, item_index)
        evidence_items = _qa_evidence_items(item)
        for evidence_index, evidence in enumerate(evidence_items):
            field = f"items[{item_index}].evidence[{evidence_index}]"
            document_ref = _evidence_document_ref(evidence)
            if not document_ref:
                issues.append(
                    BenchmarkGovernanceIssue(
                        "error",
                        "qa_suggestion_evidence_document_missing",
                        "external QA suggestions must include a document reference for every evidence span",
                        field,
                        f"Add a document value for QA item {item_id}.",
                    )
                )
                continue
            if request_aliases and not _source_ref_keys(document_ref).intersection(request_aliases):
                issues.append(
                    BenchmarkGovernanceIssue(
                        "error",
                        "qa_suggestion_unknown_source_document",
                        "candidate evidence references a document that is not present in the suggestion request",
                        field,
                    )
                )


def review_grounded_qa_suggestions(
    *,
    candidate_path: str | Path,
    request_path: str | Path | None = None,
    sources_path: str | Path | None = None,
    source_dir: str | Path | None = None,
    chunk_snapshot_path: str | Path | None = None,
    evidence_map_output_path: str | Path | None = None,
    require_answer: bool = True,
    require_advisory: bool = True,
    require_generated: bool = True,
) -> dict[str, Any]:
    """Review external grounded-QA suggestions with deterministic gates."""

    raw_candidate = _read_json(candidate_path)
    if not isinstance(raw_candidate, Mapping):
        raise BenchmarkGovernanceError("candidate grounded QA must be a JSON object")
    candidate = dict(raw_candidate)

    issues: list[BenchmarkGovernanceIssue] = []
    if candidate.get("schema") != GROUNDED_QA_SCHEMA:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_candidate_schema_invalid",
                f"candidate schema must be {GROUNDED_QA_SCHEMA}",
                "schema",
            )
        )
    if require_advisory and candidate.get("advisory") is not True:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_not_advisory",
                "external grounded-QA suggestions must set advisory to true",
                "advisory",
            )
        )
    if require_generated and candidate.get("generated") is not True:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_not_generated",
                "external grounded-QA suggestions must set generated to true",
                "generated",
            )
        )
    if chunk_snapshot_path and not evidence_map_output_path:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_evidence_map_output_missing",
                "--chunk-snapshot review requires --evidence-map-output so compatibility can be audited",
                "evidence_map_output",
            )
        )
    if evidence_map_output_path and not chunk_snapshot_path:
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "qa_suggestion_chunk_snapshot_missing",
                "--evidence-map-output requires --chunk-snapshot",
                "chunk_snapshot",
            )
        )

    request_document_count = 0
    request_hash = None
    request_aliases: set[str] = set()
    if request_path:
        request = _read_json(request_path)
        if not isinstance(request, Mapping):
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_suggestion_request_invalid",
                    "suggestion request must be a JSON object",
                    "request",
                )
            )
        elif request.get("schema") != GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA:
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_suggestion_request_schema_invalid",
                    f"request schema must be {GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA}",
                    "request.schema",
                )
            )
        else:
            raw_sources = request.get("sources")
            request_sources = [item for item in raw_sources if isinstance(item, Mapping)] if isinstance(raw_sources, list) else []
            request_document_count = len(request_sources)
            request_hash = str(request.get("request_hash") or "") or None
            request_aliases = _request_source_aliases(request)
    _append_suggestion_evidence_policy_issues(
        candidate=candidate,
        request_aliases=request_aliases,
        issues=issues,
    )

    validate_report = validate_grounded_qa(
        qa_path=candidate_path,
        sources_path=sources_path,
        source_dir=source_dir,
        require_answer=require_answer,
    )
    for raw_issue in validate_report.get("issues", []):
        if isinstance(raw_issue, Mapping):
            issues.append(_review_issue_from_report(prefix="qa_validate", raw_issue=raw_issue))

    evidence_map_report = None
    if chunk_snapshot_path and evidence_map_output_path:
        evidence_map_report = map_grounded_qa_evidence(
            qa_path=candidate_path,
            chunk_snapshot_path=chunk_snapshot_path,
            output_path=evidence_map_output_path,
        )
        for raw_issue in evidence_map_report.get("issues", []):
            if isinstance(raw_issue, Mapping):
                issues.append(_review_issue_from_report(prefix="qa_map_evidence", raw_issue=raw_issue))

    candidate_items = _candidate_grounded_qa_items(candidate)
    validate_summary = validate_report.get("summary") if isinstance(validate_report.get("summary"), Mapping) else {}
    evidence_map_summary = (
        evidence_map_report.get("summary")
        if isinstance(evidence_map_report, Mapping) and isinstance(evidence_map_report.get("summary"), Mapping)
        else {}
    )
    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_SUGGESTION_REVIEW_REPORT_SCHEMA,
        "created_at": _now(),
        "grounded_qa_schema": GROUNDED_QA_SCHEMA,
        "candidate_schema": candidate.get("schema"),
        "request_schema": GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA if request_path else None,
        "request_hash": request_hash,
        "summary": {
            **_issue_counts(issues),
            "candidate_item_count": len(candidate_items),
            "request_source_count": request_document_count,
            "advisory": candidate.get("advisory") is True,
            "generated": candidate.get("generated") is True,
            "validation_ok": bool(validate_report.get("ok")),
            "validation_checked_span_count": int(validate_summary.get("checked_span_count") or 0),
            "validation_grounded_span_count": int(validate_summary.get("grounded_span_count") or 0),
            "evidence_map_checked": evidence_map_report is not None,
            "evidence_map_ok": bool(evidence_map_report.get("ok")) if evidence_map_report else None,
            "mapped_span_count": int(evidence_map_summary.get("mapped_span_count") or 0),
        },
        "artifacts": {
            "candidate": str(candidate_path),
            "request": str(request_path) if request_path else None,
            "sources": str(sources_path) if sources_path else None,
            "source_dir": str(source_dir) if source_dir else None,
            "chunk_snapshot": str(chunk_snapshot_path) if chunk_snapshot_path else None,
            "evidence_map_output": str(evidence_map_output_path) if evidence_map_output_path else None,
        },
        "issues": [issue.to_dict() for issue in issues],
        "validation_report": {
            "schema": validate_report.get("schema"),
            "ok": validate_report.get("ok"),
            "summary": validate_report.get("summary"),
            "issues": validate_report.get("issues", []),
            "runtime_partial_failure": validate_report.get("runtime_partial_failure"),
        },
        **(
            {
                "evidence_map_report": {
                    "schema": evidence_map_report.get("schema"),
                    "ok": evidence_map_report.get("ok"),
                    "summary": evidence_map_report.get("summary"),
                    "issues": evidence_map_report.get("issues", []),
                    "runtime_partial_failure": evidence_map_report.get("runtime_partial_failure"),
                }
            }
            if evidence_map_report
            else {}
        ),
        "candidate_preview": {
            "schema": candidate.get("schema"),
            "advisory": candidate.get("advisory"),
            "generated": candidate.get("generated"),
            "item_count": len(candidate_items),
            "item_ids": [_qa_item_identifier(item, index) for index, item in enumerate(candidate_items[:20])],
        },
    }


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


def _qa_validate_runtime_partial_failure_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    return build_runtime_partial_failure_report(
        "ragflow-kb-build qa validate",
        items,
        success_statuses=("validated",),
        warning_statuses=("warning",),
        failure_statuses=("invalid",),
        skipped_statuses=("skipped",),
        timeout_statuses=(),
    )


def _qa_evidence_map_runtime_partial_failure_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    return build_runtime_partial_failure_report(
        "ragflow-kb-build qa map-evidence",
        items,
        success_statuses=("mapped",),
        warning_statuses=("mapped_with_warnings",),
        failure_statuses=("invalid", "partially_mapped", "unmapped"),
        skipped_statuses=(),
        timeout_statuses=(),
    )


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
    runtime_items: list[dict[str, Any]] = []

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
            runtime_items.append({"label": item_id, "status": "invalid"})
            issues.append(
                BenchmarkGovernanceIssue("error", "qa_item_invalid", "qa item must be a JSON object", field_prefix)
            )
            continue

        item_id = _qa_item_identifier(raw_item, index)
        issue_start = len(issues)
        item_checked_span_count = 0
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
            runtime_items.append({"label": item_id, "status": "invalid"})
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
            item_checked_span_count += 1
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

        item_issues = issues[issue_start:]
        if any(issue.severity == "error" for issue in item_issues):
            status = "invalid"
        elif any(issue.severity == "warning" for issue in item_issues):
            status = "warning"
        elif sources and item_checked_span_count > 0:
            status = "validated"
        else:
            status = "skipped"
        runtime_items.append({"label": item_id, "status": status})

    if not runtime_items and issues:
        runtime_items.append({"label": "items", "status": "invalid"})
    runtime_partial_failure = _qa_validate_runtime_partial_failure_report(runtime_items)
    runtime_partial_summary = runtime_partial_failure["summary"]
    summary = {
        **_issue_counts(issues),
        "item_count": len(raw_items),
        "valid_item_count": max(0, len(raw_items) - len(item_error_ids)),
        "invalid_item_count": len(item_error_ids),
        "evidence_span_count": evidence_span_count,
        "checked_span_count": checked_span_count,
        "grounded_span_count": grounded_span_count,
        "source_count": len(sources),
        "require_answer": require_answer,
        "runtime_partial_failure_status": runtime_partial_summary["status"],
        "runtime_warning_count": runtime_partial_summary["warning_count"],
        "runtime_failure_count": runtime_partial_summary["failure_count"],
        "runtime_timeout_count": runtime_partial_summary["timeout_count"],
        "runtime_skipped_count": runtime_partial_summary["skipped_count"],
    }

    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_VALIDATE_REPORT_SCHEMA,
        "artifacts": {
            "qa": str(qa_path),
            "sources": str(sources_path) if sources_path else None,
            "source_dir": str(source_dir) if source_dir else None,
        },
        "summary": summary,
        "runtime_partial_failure": runtime_partial_failure,
        "issues": [issue.to_dict() for issue in issues],
    }


def _snapshot_text(item: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for key in ("content", "content_preview"):
        value = _clean_string(item.get(key))
        if value:
            return value, key
    return None, None


def _snapshot_document_aliases(item: Mapping[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("document", "document_name", "document_id", "source", "source_path", "path", "file", "filename"):
        value = _clean_string(item.get(key))
        aliases.update(_source_ref_keys(value))
    return aliases


def _snapshot_candidate_chunks(chunks: list[Mapping[str, Any]], document_ref: str | None) -> list[Mapping[str, Any]]:
    keys = _source_ref_keys(document_ref)
    if not keys:
        return []
    return [chunk for chunk in chunks if keys.intersection(_snapshot_document_aliases(chunk))]


def _snapshot_expected_chunk_ref(item: Mapping[str, Any]) -> str | None:
    stable_hash = _clean_string(item.get("stable_hash"))
    if stable_hash:
        return stable_hash
    content_sha256 = _clean_string(item.get("content_sha256"))
    if content_sha256:
        return content_sha256 if content_sha256.startswith("sha256:") else f"sha256:{content_sha256}"
    return _clean_string(item.get("chunk_id")) or _clean_string(item.get("id"))


def _snapshot_chunk_match(item: Mapping[str, Any], *, span: str) -> dict[str, Any] | None:
    text, text_field = _snapshot_text(item)
    if not text or text_field is None:
        return None
    span_start = text.find(span)
    if span_start < 0:
        return None
    aliases = item.get("aliases")
    return {
        "snapshot_id": item.get("id"),
        "stable_hash": item.get("stable_hash"),
        "content_sha256": item.get("content_sha256"),
        "chunk_id": item.get("chunk_id"),
        "document_name": item.get("document_name"),
        "document_id": item.get("document_id"),
        "expected_chunk": _snapshot_expected_chunk_ref(item),
        "match_field": text_field,
        "span_start": span_start,
        "span_end": span_start + len(span),
        "aliases": aliases if isinstance(aliases, list) else [],
    }


def _find_evidence_chunk_matches(
    *,
    chunks: list[Mapping[str, Any]],
    span: str,
    document_ref: str | None,
) -> tuple[list[dict[str, Any]], str]:
    candidates = _snapshot_candidate_chunks(chunks, document_ref)
    if candidates:
        matches = [match for chunk in candidates if (match := _snapshot_chunk_match(chunk, span=span))]
        if matches:
            return matches, "document_match"
    matches = [match for chunk in chunks if (match := _snapshot_chunk_match(chunk, span=span))]
    if not matches:
        return matches, "unmapped"
    if document_ref and candidates:
        return matches, "document_mismatch"
    if document_ref:
        return matches, "document_unmatched"
    return matches, "no_document_ref"


def _evidence_mapping_confidence(*, match_count: int, document_status: str) -> float:
    if match_count <= 0:
        return 0.0
    if document_status == "document_match":
        base = 1.0
    elif document_status == "no_document_ref":
        base = 0.85
    elif document_status == "document_unmatched":
        base = 0.65
    elif document_status == "document_mismatch":
        base = 0.5
    else:
        base = 0.0
    ambiguity_penalty = min(0.25, max(0, match_count - 1) * 0.05)
    return round(max(0.0, base - ambiguity_penalty), 4)


def map_grounded_qa_evidence(
    *,
    qa_path: str | Path,
    chunk_snapshot_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Map grounded QA evidence spans onto a chunk snapshot."""

    try:
        snapshot = load_chunk_snapshot(chunk_snapshot_path)
    except ValidationError as exc:
        raise BenchmarkGovernanceError(str(exc)) from exc

    payload = _qa_payload(qa_path)
    raw_items = payload.get("items")
    raw_chunks = snapshot.get("chunks")
    chunks = [item for item in raw_chunks if isinstance(item, Mapping)] if isinstance(raw_chunks, list) else []
    issues: list[BenchmarkGovernanceIssue] = []
    evidence_span_count = 0
    mapped_span_count = 0
    match_count = 0
    mapping_confidence_sum = 0.0
    mapped_confidence_sum = 0.0
    mapped_expected_chunks: set[str] = set()
    item_error_ids: set[str] = set()
    mapped_items: list[dict[str, Any]] = []
    runtime_items: list[dict[str, Any]] = []

    if not chunks:
        issues.append(
            BenchmarkGovernanceIssue("error", "chunk_snapshot_empty", "chunk snapshot does not contain any chunks", "chunk_snapshot")
        )
    if chunks and not any(_snapshot_text(chunk)[0] for chunk in chunks):
        issues.append(
            BenchmarkGovernanceIssue(
                "error",
                "chunk_snapshot_missing_text",
                "chunk snapshot chunks must include content or content_preview for evidence mapping",
                "chunk_snapshot.chunks",
            )
        )
    if not isinstance(raw_items, list):
        issues.append(BenchmarkGovernanceIssue("error", "qa_items_invalid", "qa items must be a list", "items"))
        raw_items = []
    if not raw_items:
        issues.append(BenchmarkGovernanceIssue("error", "qa_empty", "qa file does not contain any items", "items"))

    for item_index, raw_item in enumerate(raw_items):
        field_prefix = f"items[{item_index}]"
        if not isinstance(raw_item, Mapping):
            item_id = f"item-{item_index + 1}"
            item_error_ids.add(item_id)
            runtime_items.append({"label": item_id, "status": "invalid"})
            issues.append(
                BenchmarkGovernanceIssue("error", "qa_item_invalid", "qa item must be a JSON object", field_prefix)
            )
            continue

        item_id = _qa_item_identifier(raw_item, item_index)
        issue_start = len(issues)
        evidence_items = _qa_evidence_items(raw_item)
        item_expected_chunks: set[str] = set()
        item_confidence_sum = 0.0
        item_span_count = 0
        item_mapped_span_count = 0
        item_unmapped_span_count = 0
        evidence_mappings: list[dict[str, Any]] = []
        if not evidence_items:
            item_error_ids.add(item_id)
            issues.append(
                BenchmarkGovernanceIssue(
                    "error",
                    "qa_item_missing_evidence",
                    "qa item must include evidence spans before they can be mapped",
                    f"{field_prefix}.evidence",
                )
            )

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
            item_span_count += 1
            matches, document_status = _find_evidence_chunk_matches(
                chunks=chunks,
                span=span,
                document_ref=document_ref,
            )
            mapping_confidence = _evidence_mapping_confidence(
                match_count=len(matches),
                document_status=document_status,
            )
            mapping_confidence_sum += mapping_confidence
            item_confidence_sum += mapping_confidence
            expected_chunks = sorted(
                {str(match["expected_chunk"]) for match in matches if match.get("expected_chunk")}
            )
            item_expected_chunks.update(expected_chunks)
            mapped_expected_chunks.update(expected_chunks)
            if matches:
                mapped_span_count += 1
                item_mapped_span_count += 1
                match_count += len(matches)
                mapped_confidence_sum += mapping_confidence
                if document_status == "document_mismatch":
                    issues.append(
                        BenchmarkGovernanceIssue(
                            "warning",
                            "evidence_document_mismatch",
                            "evidence span was mapped to a chunk outside the referenced document",
                            evidence_field,
                        )
                    )
                elif document_status == "document_unmatched":
                    issues.append(
                        BenchmarkGovernanceIssue(
                            "warning",
                            "evidence_document_unmatched",
                            "evidence span was mapped, but the referenced document was not found in the chunk snapshot",
                            evidence_field,
                        )
                    )
            else:
                item_error_ids.add(item_id)
                issues.append(
                    BenchmarkGovernanceIssue(
                        "error",
                        "evidence_span_unmapped",
                        "evidence span was not found in the chunk snapshot",
                        evidence_field,
                        "Regenerate the chunk snapshot with content, check chunk boundaries, or refresh the QA evidence.",
                    )
                )
                item_unmapped_span_count += 1

            evidence_mappings.append(
                {
                    "index": evidence_index,
                    "text": span,
                    "document": document_ref,
                    "mapped": bool(matches),
                    "mapping_confidence": mapping_confidence,
                    "document_match_status": document_status,
                    "match_count": len(matches),
                    "expected_chunks": expected_chunks,
                    "matches": matches,
                }
            )

        mapped_items.append(
            {
                "id": item_id,
                "query_id": _first_string(raw_item, ("query_id", "query", "validation_query_id")),
                "question": _first_string(raw_item, ("question", "query", "prompt", "input")),
                "expected_chunks": sorted(item_expected_chunks),
                "summary": {
                    "evidence_span_count": item_span_count,
                    "mapped_span_count": item_mapped_span_count,
                    "mapping_coverage": _rate(item_mapped_span_count, item_span_count),
                    "mapping_confidence": _rate(item_confidence_sum, item_span_count),
                    "expected_chunk_count": len(item_expected_chunks),
                },
                "evidence": evidence_mappings,
            }
        )

        item_issues = issues[issue_start:]
        if any(issue.severity == "error" for issue in item_issues):
            if item_mapped_span_count > 0 and item_unmapped_span_count > 0:
                status = "partially_mapped"
            elif item_unmapped_span_count > 0:
                status = "unmapped"
            else:
                status = "invalid"
        elif any(issue.severity == "warning" for issue in item_issues):
            status = "mapped_with_warnings"
        elif item_span_count > 0 and item_mapped_span_count == item_span_count:
            status = "mapped"
        else:
            status = "invalid"
        runtime_items.append({"label": item_id, "status": status})

    summary = {
        **_issue_counts(issues),
        "item_count": len(raw_items),
        "invalid_item_count": len(item_error_ids),
        "evidence_span_count": evidence_span_count,
        "mapped_span_count": mapped_span_count,
        "unmapped_span_count": max(0, evidence_span_count - mapped_span_count),
        "match_count": match_count,
        "evidence_mapping_coverage": _rate(mapped_span_count, evidence_span_count),
        "evidence_mapping_confidence": _rate(mapping_confidence_sum, evidence_span_count),
        "mapped_span_confidence": _rate(mapped_confidence_sum, mapped_span_count),
        "mapped_chunk_count": len(mapped_expected_chunks),
        "mapped_chunk_coverage": _rate(len(mapped_expected_chunks), len(chunks)),
        "chunk_count": len(chunks),
    }
    if not runtime_items and issues:
        runtime_items.append({"label": "items", "status": "invalid"})
    runtime_partial_failure = _qa_evidence_map_runtime_partial_failure_report(runtime_items)
    runtime_partial_summary = runtime_partial_failure["summary"]
    report_summary = {
        **summary,
        "runtime_partial_failure_status": runtime_partial_summary["status"],
        "runtime_warning_count": runtime_partial_summary["warning_count"],
        "runtime_failure_count": runtime_partial_summary["failure_count"],
        "runtime_timeout_count": runtime_partial_summary["timeout_count"],
        "runtime_skipped_count": runtime_partial_summary["skipped_count"],
    }
    artifact = {
        "schema": GROUNDED_QA_EVIDENCE_MAP_SCHEMA,
        "created_at": _now(),
        "qa": str(qa_path),
        "chunk_snapshot": str(chunk_snapshot_path),
        "summary": summary,
        "items": mapped_items,
        "issues": [issue.to_dict() for issue in issues],
    }
    _write_json(output_path, artifact)

    return {
        "ok": _ok(issues),
        "schema": GROUNDED_QA_EVIDENCE_MAP_REPORT_SCHEMA,
        "evidence_map": str(output_path),
        "artifacts": {
            "qa": str(qa_path),
            "chunk_snapshot": str(chunk_snapshot_path),
            "output": str(output_path),
        },
        "summary": report_summary,
        "runtime_partial_failure": runtime_partial_failure,
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


def _document_chunk_coverage(chunks: list[NormalizedChunk]) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        document_name = chunk.document_name or "<unknown>"
        item = documents.setdefault(
            document_name,
            {
                "document_name": document_name,
                "document_id": chunk.document_id,
                "chunk_count": 0,
                "content_char_count": 0,
            },
        )
        item["chunk_count"] += 1
        item["content_char_count"] += len(chunk.content)
        if not item.get("document_id") and chunk.document_id:
            item["document_id"] = chunk.document_id
    for item in documents.values():
        item["average_chunk_chars"] = round(item["content_char_count"] / item["chunk_count"], 2) if item["chunk_count"] else 0.0
    return sorted(documents.values(), key=lambda item: (item["document_name"], item.get("document_id") or ""))


TABLE_HINT_RE = re.compile(r"(<table\b|</table>|\|[^\n]*\|)", re.IGNORECASE)
IMAGE_HINT_RE = re.compile(r"!\[[^\]]*]\([^)]+\)|<img\b", re.IGNORECASE)
CHUNK_DELIMITER_RE = re.compile(r"<!--\s*chunk\s*-->", re.IGNORECASE)


def _table_signature(content: str) -> str:
    rows = []
    for line in content.splitlines():
        stripped = " ".join(line.strip().lower().split())
        if not stripped:
            continue
        if "|" in stripped or "<tr" in stripped or "<td" in stripped or "<th" in stripped:
            rows.append(stripped)
    return "\n".join(rows[:12])[:2000]


def _chunk_snapshot_review(chunks: list[NormalizedChunk], *, source_chunks: list[NormalizedChunk] | None = None) -> dict[str, Any]:
    review_chunks = list(source_chunks or chunks)
    table_like_indexes: list[int] = []
    image_only_indexes: list[int] = []
    delimiter_consumed_indexes: list[int] = []
    max_chunk_chars = 0
    table_signatures: dict[str, int] = {}
    documents_with_table_chunks: set[str] = set()
    documents_without_table_chunks: set[str] = set()

    for index, chunk in enumerate(review_chunks, start=1):
        content = chunk.content or ""
        text_without_images = IMAGE_HINT_RE.sub("", content).strip()
        has_table = bool(TABLE_HINT_RE.search(content))
        has_image = bool(IMAGE_HINT_RE.search(content))
        max_chunk_chars = max(max_chunk_chars, len(content))
        document_name = chunk.document_name or chunk.document_id or "<unknown>"
        if has_table:
            table_like_indexes.append(index)
            documents_with_table_chunks.add(document_name)
            signature = _table_signature(content)
            if signature:
                table_signatures[signature] = table_signatures.get(signature, 0) + 1
        else:
            documents_without_table_chunks.add(document_name)
        if has_image and not text_without_images:
            image_only_indexes.append(index)
        if CHUNK_DELIMITER_RE.search(content):
            delimiter_consumed_indexes.append(index)

    duplicate_table_like_count = sum(count - 1 for count in table_signatures.values() if count > 1)
    split_table_chunk_count = 0
    previous_table_doc = None
    for index in table_like_indexes:
        document_name = review_chunks[index - 1].document_name or review_chunks[index - 1].document_id or "<unknown>"
        if previous_table_doc == document_name:
            split_table_chunk_count += 1
        previous_table_doc = document_name
    missing_table_evidence_count = len(documents_without_table_chunks) if table_like_indexes else 0
    issues: list[dict[str, Any]] = []
    if split_table_chunk_count:
        issues.append(
            {
                "severity": "review",
                "code": "possible_table_fragmentation",
                "message": "Adjacent table-like chunks may indicate table fragmentation.",
            }
        )
    if duplicate_table_like_count:
        issues.append(
            {
                "severity": "review",
                "code": "duplicate_table_like_chunks",
                "message": "Repeated table-like chunk signatures may indicate duplicate table evidence.",
            }
        )
    if missing_table_evidence_count:
        issues.append(
            {
                "severity": "info",
                "code": "documents_without_table_evidence",
                "message": "Some documents in the snapshot have no table-like chunk evidence.",
            }
        )
    if delimiter_consumed_indexes:
        issues.append(
            {
                "severity": "review",
                "code": "chunk_delimiter_visible_in_snapshot",
                "message": "One or more chunks still contain the chunk delimiter marker.",
            }
        )
    return {
        "advisory_only": True,
        "ragflow_calls": 0,
        "metrics": {
            "chunk_count": len(chunks),
            "source_chunk_count": len(review_chunks),
            "table_like_chunk_count": len(table_like_indexes),
            "possible_split_table_chunk_count": split_table_chunk_count,
            "duplicate_table_like_chunk_count": duplicate_table_like_count,
            "missing_table_evidence_document_count": missing_table_evidence_count,
            "delimiter_visible_chunk_count": len(delimiter_consumed_indexes),
            "image_only_chunk_count": len(image_only_indexes),
            "max_chunk_chars": max_chunk_chars,
        },
        "examples": {
            "table_like_chunk_indexes": table_like_indexes[:20],
            "image_only_chunk_indexes": image_only_indexes[:20],
            "delimiter_visible_chunk_indexes": delimiter_consumed_indexes[:20],
        },
        "issues": issues,
    }


def snapshot_chunks(
    *,
    input_path: str | Path,
    output_path: str | Path,
    name: str = "chunk-snapshot",
    description: str = "",
    include_content: bool = False,
    observed_state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a deterministic chunk snapshot from local chunks or validation output."""

    chunks, source_paths = _read_snapshot_input(input_path)
    if not chunks:
        raise BenchmarkGovernanceError("chunk snapshot input did not contain any chunks")
    try:
        observed_state_report = load_kb_refresh_report(observed_state_path) if observed_state_path else None
    except BuildError as exc:
        raise BenchmarkGovernanceError(str(exc)) from exc
    observed_state = (
        summarize_kb_refresh_observed_state(observed_state_report)
        if observed_state_report
        else {"available": False, "schema": KB_REFRESH_REPORT_SCHEMA, "source": None, "summary": {}}
    )

    seen: set[str] = set()
    snapshot_items: list[dict[str, Any]] = []
    unique_chunks: list[NormalizedChunk] = []
    runtime_items: list[dict[str, Any]] = []
    duplicate_hashes = 0
    for source_index, chunk in enumerate(chunks, start=1):
        stable_hash = stable_chunk_hash(chunk)
        label = chunk.chunk_id or f"source_chunk_{source_index}"
        if stable_hash in seen:
            duplicate_hashes += 1
            runtime_items.append({"label": label, "status": "duplicate_skipped"})
            continue
        seen.add(stable_hash)
        unique_chunks.append(chunk)
        snapshot_items.append(_chunk_snapshot_item(chunk, index=len(snapshot_items), include_content=include_content))
        runtime_items.append(
            {
                "label": label,
                "status": "snapshotted" if chunk.content.strip() else "missing_content",
            }
        )

    chunk_count = len(snapshot_items)
    chunks_with_content = sum(1 for chunk in unique_chunks if chunk.content.strip())
    chunks_with_document_name = sum(1 for chunk in unique_chunks if chunk.document_name)
    chunks_with_document_id = sum(1 for chunk in unique_chunks if chunk.document_id)
    chunks_with_dataset_id = sum(1 for chunk in unique_chunks if chunk.dataset_id)
    chunks_with_chunk_id = sum(1 for chunk in unique_chunks if chunk.chunk_id)
    content_char_count = sum(len(chunk.content) for chunk in unique_chunks)
    document_coverage = _document_chunk_coverage(unique_chunks)
    review = _chunk_snapshot_review(unique_chunks, source_chunks=chunks)
    snapshot = {
        "schema": CHUNK_SNAPSHOT_SCHEMA,
        "created_at": _now(),
        "name": name,
        "description": description,
        "hash_algorithm": CHUNK_HASH_ALGORITHM,
        "summary": {
            "chunk_count": chunk_count,
            "source_chunk_count": len(chunks),
            "duplicate_stable_hash_count": duplicate_hashes,
            "document_count": len({item.get("document_name") for item in snapshot_items if item.get("document_name")}),
            "chunks_with_content": chunks_with_content,
            "chunks_with_document_name": chunks_with_document_name,
            "chunks_with_document_id": chunks_with_document_id,
            "chunks_with_dataset_id": chunks_with_dataset_id,
            "chunks_with_chunk_id": chunks_with_chunk_id,
            "content_coverage": _rate(chunks_with_content, chunk_count),
            "document_name_coverage": _rate(chunks_with_document_name, chunk_count),
            "document_id_coverage": _rate(chunks_with_document_id, chunk_count),
            "dataset_id_coverage": _rate(chunks_with_dataset_id, chunk_count),
            "chunk_id_coverage": _rate(chunks_with_chunk_id, chunk_count),
            "content_char_count": content_char_count,
            "average_chunk_chars": round(content_char_count / chunk_count, 2) if chunk_count else 0.0,
        },
        "source_hashes": _source_hashes(source_paths),
        "document_coverage": document_coverage,
        "chunks": snapshot_items,
    }
    _write_json(output_path, snapshot)
    runtime_partial_failure = build_runtime_partial_failure_report(
        "ragflow-kb-build snapshot-chunks",
        runtime_items,
        success_statuses=("snapshotted",),
        warning_statuses=("missing_content",),
        failure_statuses=(),
        skipped_statuses=("duplicate_skipped",),
        timeout_statuses=(),
    )
    runtime_partial_summary = runtime_partial_failure["summary"]
    report_summary = dict(snapshot["summary"])
    report_summary.update(
        {
            "runtime_partial_failure_status": runtime_partial_summary["status"],
            "runtime_warning_count": runtime_partial_summary["warning_count"],
            "runtime_failure_count": runtime_partial_summary["failure_count"],
            "runtime_timeout_count": runtime_partial_summary["timeout_count"],
            "runtime_skipped_count": runtime_partial_summary["skipped_count"],
            "table_like_chunk_count": review["metrics"]["table_like_chunk_count"],
            "possible_split_table_chunk_count": review["metrics"]["possible_split_table_chunk_count"],
            "duplicate_table_like_chunk_count": review["metrics"]["duplicate_table_like_chunk_count"],
            "missing_table_evidence_document_count": review["metrics"]["missing_table_evidence_document_count"],
            "delimiter_visible_chunk_count": review["metrics"]["delimiter_visible_chunk_count"],
            "image_only_chunk_count": review["metrics"]["image_only_chunk_count"],
            "max_chunk_chars": review["metrics"]["max_chunk_chars"],
            "observed_state_document_count": (
                observed_state.get("summary", {}).get("observed_document_count", 0)
                if isinstance(observed_state.get("summary"), Mapping)
                else 0
            ),
            "observed_state_chunk_total": (
                observed_state.get("summary", {}).get("observed_chunk_total")
                if isinstance(observed_state.get("summary"), Mapping)
                else None
            ),
        }
    )
    return {
        "ok": True,
        "schema": CHUNK_SNAPSHOT_REPORT_SCHEMA,
        "chunk_snapshot": str(output_path),
        "summary": report_summary,
        "observed_state": observed_state,
        "runtime_partial_failure": runtime_partial_failure,
        "chunk_review": review,
        "document_coverage": document_coverage,
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


def _source_hash_map(paths: Iterable[str | Path | None]) -> dict[str, str]:
    return {item["path"]: item["sha256"] for item in _source_hashes(paths)}


def _read_benchmark_import_checkpoint(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise BenchmarkGovernanceError("benchmark import checkpoint must be a JSON object")
    if payload.get("schema") != BENCHMARK_IMPORT_CHECKPOINT_SCHEMA:
        raise BenchmarkGovernanceError(f"benchmark import checkpoint schema must be {BENCHMARK_IMPORT_CHECKPOINT_SCHEMA}")
    processed = payload.get("processed_query_ids")
    if not isinstance(processed, list) or not all(isinstance(item, str) for item in processed):
        raise BenchmarkGovernanceError("benchmark import checkpoint processed_query_ids must be a list of strings")
    source_hashes = payload.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise BenchmarkGovernanceError("benchmark import checkpoint source_hashes must be an object")
    return dict(payload)


def _validate_benchmark_import_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    source_hashes: Mapping[str, str],
    output_dir: str | Path,
    name: str,
    description: str,
) -> None:
    checkpoint_hashes = checkpoint.get("source_hashes")
    if dict(checkpoint_hashes or {}) != dict(source_hashes):
        raise BenchmarkGovernanceError("benchmark import checkpoint source hashes do not match current inputs")
    if str(checkpoint.get("output_dir") or "") != str(Path(output_dir)):
        raise BenchmarkGovernanceError("benchmark import checkpoint output_dir does not match current output")
    if str(checkpoint.get("name") or "") != name:
        raise BenchmarkGovernanceError("benchmark import checkpoint name does not match current name")
    if str(checkpoint.get("description") or "") != description:
        raise BenchmarkGovernanceError("benchmark import checkpoint description does not match current description")


def _write_benchmark_import_checkpoint(
    *,
    checkpoint_path: str | Path,
    source_hashes: Mapping[str, str],
    output_dir: str | Path,
    name: str,
    description: str,
    processed_query_ids: Iterable[str],
    total_query_count: int,
    completed: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    processed = list(dict.fromkeys(str(item) for item in processed_query_ids))
    payload = {
        "schema": BENCHMARK_IMPORT_CHECKPOINT_SCHEMA,
        "created_at": created_at or _now(),
        "updated_at": _now(),
        "source_hashes": dict(source_hashes),
        "output_dir": str(Path(output_dir)),
        "name": name,
        "description": description,
        "processed_query_ids": processed,
        "summary": {
            "processed_query_count": len(processed),
            "total_query_count": total_query_count,
            "remaining_query_count": max(total_query_count - len(processed), 0),
            "completed": bool(completed),
        },
    }
    _write_json(checkpoint_path, payload)
    return payload


def import_benchmark_dataset(
    *,
    queries_path: str | Path,
    qrels_path: str | Path,
    output_dir: str | Path,
    name: str = "benchmark",
    description: str = "",
    qa_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Normalize user benchmark inputs into a portable benchmark directory."""

    if resume and not checkpoint_path:
        raise BenchmarkGovernanceError("benchmark import --resume requires --checkpoint")
    if batch_size is not None and batch_size <= 0:
        raise BenchmarkGovernanceError("benchmark import batch_size must be positive")

    queries = load_validation_queries(queries_path)
    qrels = load_benchmark_qrels(qrels_path)
    qa = _qa_payload(qa_path)
    source_paths = [queries_path, qrels_path, qa_path]
    source_hashes = _source_hash_map(source_paths)

    checkpoint: dict[str, Any] | None = None
    processed_query_ids: list[str] = []
    checkpoint_created_at: str | None = None
    if checkpoint_path and resume:
        checkpoint_file = Path(checkpoint_path)
        checkpoint = _read_benchmark_import_checkpoint(checkpoint_file)
        _validate_benchmark_import_checkpoint(
            checkpoint,
            source_hashes=source_hashes,
            output_dir=output_dir,
            name=name,
            description=description,
        )
        processed_query_ids = list(checkpoint.get("processed_query_ids") or [])
        checkpoint_created_at = str(checkpoint.get("created_at") or "") or None

    all_query_ids = [query.id for query in queries]
    known_query_ids = set(all_query_ids)
    unknown_processed = sorted(set(processed_query_ids) - known_query_ids)
    if unknown_processed:
        raise BenchmarkGovernanceError(
            "benchmark import checkpoint contains query ids that are not present in current queries: "
            + ", ".join(unknown_processed[:5])
        )

    processed_set = set(processed_query_ids)
    remaining_query_ids = [query_id for query_id in all_query_ids if query_id not in processed_set]
    next_query_ids = remaining_query_ids if batch_size is None else remaining_query_ids[:batch_size]
    selected_query_ids = set(processed_query_ids) | set(next_query_ids)
    selected_queries = [query for query in queries if query.id in selected_query_ids]
    selected_qrels = {query_id: qrels[query_id] for query_id in sorted(qrels) if query_id in selected_query_ids}
    selected_qa = _filter_qa_payload(qa, selected_query_ids, known_query_ids)
    completed = len(selected_query_ids) >= len(all_query_ids)

    artifacts = _write_benchmark_artifacts(
        queries=selected_queries,
        qrels=selected_qrels,
        qa=selected_qa,
        output_dir=output_dir,
        name=name,
        description=description,
        source_paths=source_paths,
    )
    checkpoint_payload = None
    if checkpoint_path:
        ordered_processed = [query_id for query_id in all_query_ids if query_id in selected_query_ids]
        checkpoint_payload = _write_benchmark_import_checkpoint(
            checkpoint_path=checkpoint_path,
            source_hashes=source_hashes,
            output_dir=output_dir,
            name=name,
            description=description,
            processed_query_ids=ordered_processed,
            total_query_count=len(all_query_ids),
            completed=completed,
            created_at=checkpoint_created_at,
        )

    checkpoint_report = {
        "enabled": bool(checkpoint_path),
        "path": str(checkpoint_path) if checkpoint_path else None,
        "resume": bool(resume),
        "batch_size": batch_size,
        "processed_query_count": len(selected_query_ids),
        "new_query_count": len(next_query_ids),
        "remaining_query_count": max(len(all_query_ids) - len(selected_query_ids), 0),
        "completed": completed,
        "next_query_ids": list(next_query_ids),
    }

    return {
        "ok": True,
        "schema": BENCHMARK_IMPORT_REPORT_SCHEMA,
        **artifacts,
        "completed": completed,
        "checkpoint": checkpoint_report,
        **({"checkpoint_payload": checkpoint_payload} if checkpoint_payload else {}),
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


def _retrieval_metric_evidence(
    metrics: Mapping[str, float],
    deltas: Mapping[str, Mapping[str, Any]],
    keys: Iterable[str],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for key in keys:
        if key in metrics:
            evidence[key] = metrics[key]
        if key in deltas:
            evidence[f"{key}_delta"] = dict(deltas[key])
    return evidence


def _action_counts(suggestions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for suggestion in suggestions:
        action = str(suggestion.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))


def _suggested_top_k_values(current_top_k: int | None) -> list[int]:
    current = current_top_k or 3
    moderate = max(current + 1, int(math.ceil(current * 1.5)))
    broad = max(current + 2, int(math.ceil(current * 2.0)))
    return sorted({current, moderate, min(broad, 20)})


def _threshold_value(value: float | None, *, direction: str) -> float | None:
    if value is None:
        return None
    if direction == "lower":
        return round(max(0.0, value - 0.05), 4)
    if direction == "raise":
        return round(min(1.0, value + 0.05), 4)
    return value


def _retrieval_suggestion(
    *,
    parameter: str,
    action: str,
    current: Any,
    suggested: Any,
    confidence: str,
    reason: str,
    evidence: Mapping[str, Any],
    guardrail: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "parameter": parameter,
        "action": action,
        "current": current,
        "suggested": suggested,
        "confidence": confidence,
        "reason": reason,
        "evidence": dict(evidence),
        "guardrail": guardrail,
    }
    return payload


def suggest_benchmark_retrieval_parameters(
    *,
    report_path: str | Path,
    baseline_report_path: str | Path | None = None,
    gate_config_path: str | Path | None = None,
    current_top_k: int | None = None,
    current_similarity_threshold: float | None = None,
) -> dict[str, Any]:
    """Suggest conservative retrieval parameter experiments from benchmark metrics."""

    if current_top_k is not None and current_top_k <= 0:
        raise BenchmarkGovernanceError("current_top_k must be positive when provided")
    if current_similarity_threshold is not None and not 0.0 <= current_similarity_threshold <= 1.0:
        raise BenchmarkGovernanceError("current_similarity_threshold must be between 0 and 1 when provided")

    current_report = _benchmark_payload(report_path)
    benchmark = current_report["benchmark"]
    metrics = _benchmark_metrics(current_report)
    inferred_top_k = current_top_k
    cutoff = benchmark.get("cutoff") if isinstance(benchmark, Mapping) else None
    if inferred_top_k is None and isinstance(cutoff, (int, float)) and not isinstance(cutoff, bool) and int(cutoff) > 0:
        inferred_top_k = int(cutoff)

    baseline_metrics = load_benchmark_baseline(baseline_report_path) if baseline_report_path else None
    deltas = _metric_delta(metrics, baseline_metrics) if baseline_metrics else {}
    gate_result = None
    if gate_config_path:
        gate = load_benchmark_gate(gate_config_path)
        baseline_delta = {
            key: float(item["absolute"])
            for key, item in deltas.items()
            if isinstance(item.get("absolute"), (int, float))
        } if deltas else None
        gate_result = evaluate_benchmark_gate(metrics, gate=gate, baseline_delta=baseline_delta)

    hit_rate = metrics.get("hit_rate", 1.0)
    recall = metrics.get("recall_at_k", 1.0)
    precision = metrics.get("precision_at_k", 1.0)
    document_coverage = metrics.get("supporting_document_coverage", 1.0)
    strict_recall = metrics.get("strict_chunk_recall_at_k", 1.0)
    expected_hit = metrics.get("expected_chunk_hit_rate", 1.0)
    empty_rate = metrics.get("empty_result_rate", 0.0)
    mrr = metrics.get("mrr", hit_rate)
    ndcg = metrics.get("ndcg_at_k", recall)
    pollution = max(
        metrics.get("tag_pollution_rate", 0.0),
        metrics.get("wrong_document_rate", 0.0),
        metrics.get("wrong_doc_rate", 0.0),
        metrics.get("unexpected_tag_hit_rate", 0.0),
    )
    coverage_gap = (
        hit_rate < 0.98
        or recall < 0.98
        or document_coverage < 0.98
        or strict_recall < 1.0
        or expected_hit < 1.0
    )
    ranking_gap = mrr + 0.05 < hit_rate or ndcg + 0.05 < recall
    precision_gap = precision < 0.35
    pollution_risk = pollution > 0.0

    suggestions: list[dict[str, Any]] = []
    coverage_keys = (
        "hit_rate",
        "recall_at_k",
        "supporting_document_coverage",
        "strict_chunk_recall_at_k",
        "expected_chunk_hit_rate",
        "empty_result_rate",
    )
    pollution_keys = (
        "precision_at_k",
        "tag_pollution_rate",
        "wrong_document_rate",
        "wrong_doc_rate",
        "unexpected_tag_hit_rate",
    )
    if coverage_gap and not pollution_risk:
        values = _suggested_top_k_values(inferred_top_k)
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.top_k",
                action="increase",
                current=inferred_top_k,
                suggested=values[-1],
                confidence="medium" if empty_rate == 0 else "high",
                reason="Coverage, empty-result, or strict chunk recall metrics show relevant evidence is missing.",
                evidence=_retrieval_metric_evidence(metrics, deltas, coverage_keys),
                guardrail="Reject the change if precision, pollution, latency, or cost regress beyond the benchmark gate.",
            )
        )
    elif coverage_gap and pollution_risk:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.top_k",
                action="sweep",
                current=inferred_top_k,
                suggested=_suggested_top_k_values(inferred_top_k),
                confidence="medium",
                reason="Coverage gaps coexist with pollution signals, so a paired sweep is safer than simply increasing top_k.",
                evidence=_retrieval_metric_evidence(metrics, deltas, (*coverage_keys, *pollution_keys)),
                guardrail="Prefer the smallest top_k that restores recall without increasing wrong-document or tag pollution.",
            )
        )
    elif precision_gap or pollution_risk:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.top_k",
                action="decrease",
                current=inferred_top_k,
                suggested=max(1, inferred_top_k - 1) if inferred_top_k else None,
                confidence="medium",
                reason="Precision or pollution metrics indicate too many low-quality candidates may be entering the result set.",
                evidence=_retrieval_metric_evidence(metrics, deltas, pollution_keys),
                guardrail="Keep recall and strict chunk recall at or above the current benchmark result.",
            )
        )
    else:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.top_k",
                action="hold",
                current=inferred_top_k,
                suggested=inferred_top_k,
                confidence="medium",
                reason="Benchmark retrieval coverage and pollution metrics do not justify changing top_k yet.",
                evidence=_retrieval_metric_evidence(metrics, deltas, (*coverage_keys, *pollution_keys)),
                guardrail="Revisit top_k only after adding harder qrels or observing regressions.",
            )
        )

    if (empty_rate > 0 or coverage_gap) and not pollution_risk:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.similarity_threshold",
                action="lower",
                current=current_similarity_threshold,
                suggested=_threshold_value(current_similarity_threshold, direction="lower"),
                confidence="medium" if current_similarity_threshold is not None else "low",
                reason="Coverage gaps without pollution suggest the cutoff may be excluding relevant evidence.",
                evidence=_retrieval_metric_evidence(metrics, deltas, coverage_keys),
                guardrail="Reject if wrong-document rate, tag pollution, or unsupported answers increase.",
            )
        )
    elif pollution_risk or (precision_gap and not coverage_gap):
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.similarity_threshold",
                action="raise",
                current=current_similarity_threshold,
                suggested=_threshold_value(current_similarity_threshold, direction="raise"),
                confidence="medium" if current_similarity_threshold is not None else "low",
                reason="Pollution or low precision suggests the cutoff may be admitting noisy evidence.",
                evidence=_retrieval_metric_evidence(metrics, deltas, pollution_keys),
                guardrail="Reject if hit rate, recall, or strict chunk recall falls.",
            )
        )
    elif ranking_gap:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.similarity_threshold",
                action="sweep",
                current=current_similarity_threshold,
                suggested=[
                    value
                    for value in (
                        _threshold_value(current_similarity_threshold, direction="lower"),
                        current_similarity_threshold,
                        _threshold_value(current_similarity_threshold, direction="raise"),
                    )
                    if value is not None
                ] or None,
                confidence="low",
                reason="Ranking metrics lag behind hit rate, so threshold tuning should be tested rather than assumed.",
                evidence=_retrieval_metric_evidence(metrics, deltas, ("hit_rate", "mrr", "recall_at_k", "ndcg_at_k")),
                guardrail="Prefer rerank or chunk-profile fixes if threshold sweeps do not improve early precision.",
            )
        )
    else:
        suggestions.append(
            _retrieval_suggestion(
                parameter="retrieval.similarity_threshold",
                action="hold",
                current=current_similarity_threshold,
                suggested=current_similarity_threshold,
                confidence="medium" if current_similarity_threshold is not None else "low",
                reason="Benchmark metrics do not show a threshold-specific retrieval gap.",
                evidence=_retrieval_metric_evidence(metrics, deltas, (*coverage_keys, *pollution_keys)),
                guardrail="Add a threshold sweep only when qrels expose missed evidence or noisy evidence.",
            )
        )

    recommended_experiments = []
    top_k_values = _suggested_top_k_values(inferred_top_k)
    if any(item["action"] in {"increase", "sweep"} for item in suggestions if item["parameter"] == "retrieval.top_k"):
        recommended_experiments.append(
            {
                "id": "top_k_recall_sweep",
                "parameters": {"retrieval.top_k": top_k_values},
                "success_metrics": ["hit_rate", "recall_at_k", "strict_chunk_recall_at_k", "expected_chunk_hit_rate"],
                "guardrails": ["precision_at_k", "tag_pollution_rate", "wrong_document_rate", "empty_result_rate"],
            }
        )
    if any(item["action"] in {"lower", "raise", "sweep"} for item in suggestions if item["parameter"] == "retrieval.similarity_threshold"):
        threshold_values = [
            value
            for value in (
                _threshold_value(current_similarity_threshold, direction="lower"),
                current_similarity_threshold,
                _threshold_value(current_similarity_threshold, direction="raise"),
            )
            if value is not None
        ]
        recommended_experiments.append(
            {
                "id": "similarity_threshold_sweep",
                "parameters": {"retrieval.similarity_threshold": sorted(set(threshold_values)) if threshold_values else "provide current threshold and sweep +/-0.05"},
                "success_metrics": ["hit_rate", "mrr", "ndcg_at_k", "precision_at_k"],
                "guardrails": ["empty_result_rate", "strict_chunk_recall_at_k", "tag_pollution_rate", "wrong_document_rate"],
            }
        )

    status = "REVIEW" if any(item["action"] != "hold" for item in suggestions) or (isinstance(gate_result, Mapping) and not gate_result.get("ok", True)) else "PASS"
    return {
        "ok": True,
        "schema": BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA,
        "status": status,
        "report": str(report_path),
        "baseline_report": str(baseline_report_path) if baseline_report_path else None,
        "gate_config": str(gate_config_path) if gate_config_path else None,
        "dataset": current_report.get("dataset", {}),
        "current_parameters": {
            "retrieval.top_k": inferred_top_k,
            "retrieval.similarity_threshold": current_similarity_threshold,
        },
        "metrics": metrics,
        "baseline_metrics": baseline_metrics,
        "delta": deltas,
        "gate": gate_result,
        "summary": {
            "suggestion_count": len(suggestions),
            "status": status,
            "coverage_gap": coverage_gap,
            "ranking_gap": ranking_gap,
            "precision_gap": precision_gap,
            "pollution_risk": pollution_risk,
            "action_counts": _action_counts(suggestions),
        },
        "retrieval_parameter_suggestions": suggestions,
        "recommended_experiments": recommended_experiments,
        "quality_hints": _dedupe_hints([*_quality_hints(metrics), *_regression_hints(deltas)]),
    }


def _suppression_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Mapping):
        for key in ("name", "tag", "tag_name", "label", "value", "id", "tag_id"):
            if key in value:
                values = _suppression_string_values(value[key])
                if values:
                    return values
        return []
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_suppression_string_values(item))
        return values
    return []


def _suppression_terms_from_text(text: str | None) -> set[str]:
    if not text:
        return set()
    terms: set[str] = set()
    for word in WORD_RE.findall(text):
        normalized = word.strip().casefold()
        if normalized and normalized not in _SUPPRESSION_STOPWORDS:
            terms.add(normalized)
    for phrase in CJK_PHRASE_RE.findall(text):
        normalized = phrase.strip()
        if len(normalized) >= 2:
            terms.add(normalized)
    return terms


def _suppression_terms_from_value(value: Any) -> set[str]:
    terms: set[str] = set()
    for item in _suppression_string_values(value):
        terms.update(_suppression_terms_from_text(item))
    return terms


def _suppression_query_terms(case: Mapping[str, Any]) -> set[str]:
    terms = _suppression_terms_from_text(_clean_string(case.get("question")))
    metadata = case.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("topic", "domain", "module", "summary", "description", "doc_type", "audience", "locale", "title"):
            terms.update(_suppression_terms_from_value(metadata.get(key)))
        terms.update(_suppression_terms_from_value(metadata.get("entities")))
    return terms


def _suppression_tag_scope(
    metadata: Mapping[str, Any] | None,
    *,
    tag_lookup: Mapping[str, Mapping[str, Any]] | None = None,
) -> set[str]:
    if not isinstance(metadata, Mapping):
        return set()
    scope: set[str] = set()
    for key in ("allowed_tags", "allow_tags", "expected_tags", "required_tags", "must_have_tags", "tags", "tag", "tag_ids", "tag_id"):
        for value in _suppression_string_values(metadata.get(key)):
            normalized, _entry = _suppression_canonical_tag(value, tag_lookup=tag_lookup)
            if normalized:
                scope.add(normalized)
    return scope


def _suppression_tag_lookup(tagset_path: str | Path | None) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not tagset_path:
        return {}, None
    lint_report = lint_tagset_file(tagset_path)
    normalized = lint_report.get("normalized_preview", {})
    tags = normalized.get("tags", []) if isinstance(normalized, Mapping) else []
    lookup: dict[str, dict[str, Any]] = {}
    for item in tags:
        if not isinstance(item, Mapping):
            continue
        name = _clean_string(item.get("name"))
        if not name:
            continue
        entry = {
            "name": name,
            "label": _clean_string(item.get("label")) or name,
            "description": _clean_string(item.get("description")) or "",
            "aliases": sorted({alias.casefold() for alias in _suppression_string_values(item.get("aliases")) if alias.strip()}),
        }
        lookup[name.casefold()] = entry
        for alias in entry["aliases"]:
            lookup[alias] = entry
    return lookup, tagset_report_file(tagset_path)


def _suppression_canonical_tag(value: str, tag_lookup: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[str, dict[str, Any] | None]:
    normalized = value.strip().casefold()
    if not normalized:
        return "", None
    entry = tag_lookup.get(normalized) if tag_lookup else None
    if entry:
        canonical = _clean_string(entry.get("name")) or normalized
        return canonical.casefold(), dict(entry)
    return normalized, None


def _suppression_chunk_payload(chunk: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = chunk.get("raw")
    return raw if isinstance(raw, Mapping) else chunk


def _suppression_chunk_string(chunk: Mapping[str, Any], *keys: str) -> str | None:
    payload = _suppression_chunk_payload(chunk)
    for key in keys:
        value = _clean_string(chunk.get(key))
        if value:
            return value
        value = _clean_string(payload.get(key))
        if value:
            return value
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            value = _clean_string(metadata.get(key))
            if value:
                return value
    return None


def _suppression_chunk_terms(chunk: Mapping[str, Any]) -> set[str]:
    payload = _suppression_chunk_payload(chunk)
    terms: set[str] = set()
    content = _suppression_chunk_string(chunk, "content", "content_preview", "content_with_weight", "text", "page_content")
    if content:
        terms.update(_suppression_terms_from_text(content))
    for key in ("document_name", "document_id", "chunk_id", "title", "heading", "section_title"):
        terms.update(_suppression_terms_from_value(_suppression_chunk_string(chunk, key)))
    terms.update(_suppression_terms_from_value(chunk.get("important_keywords")))
    terms.update(_suppression_terms_from_value(payload.get("important_keywords")))
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("title", "heading", "section_title", "document_title"):
            terms.update(_suppression_terms_from_value(metadata.get(key)))
    return terms


def _suppression_chunk_tags(chunk: Mapping[str, Any], *, tag_lookup: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any] | None]:
    payload = _suppression_chunk_payload(chunk)
    tags: dict[str, dict[str, Any] | None] = {}
    for source in (chunk, payload):
        if not isinstance(source, Mapping):
            continue
        for key in ("tags", "tag", "tag_names", "tag_name", "tag_ids", "tag_id"):
            for raw_tag in _suppression_string_values(source.get(key)):
                canonical, entry = _suppression_canonical_tag(raw_tag, tag_lookup=tag_lookup)
                if canonical:
                    tags[canonical] = entry
        metadata = source.get("metadata")
        if isinstance(metadata, Mapping):
            for key in ("tags", "tag", "tag_names", "tag_name", "tag_ids", "tag_id"):
                for raw_tag in _suppression_string_values(metadata.get(key)):
                    canonical, entry = _suppression_canonical_tag(raw_tag, tag_lookup=tag_lookup)
                    if canonical:
                        tags[canonical] = entry
    return tags


def _suppression_chunk_document_identity(chunk: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    payload = _suppression_chunk_payload(chunk)
    document_name = _suppression_chunk_string(chunk, "document_name", "docnm_kwd", "document_keyword", "doc_name", "source", "source_path", "path", "file", "filename")
    document_id = _suppression_chunk_string(chunk, "document_id", "doc_id", "dataset_id", "kb_id")
    chunk_id = _suppression_chunk_string(chunk, "chunk_id", "id")
    if not document_name:
        document_name = _suppression_chunk_string(payload, "document_name", "docnm_kwd", "document_keyword", "doc_name", "source", "source_path", "path", "file", "filename")
    if not document_id:
        document_id = _suppression_chunk_string(payload, "document_id", "doc_id", "dataset_id", "kb_id")
    if not chunk_id:
        chunk_id = _suppression_chunk_string(payload, "chunk_id", "id")
    return document_name, document_id, chunk_id


def _suppression_chunk_hash(chunk: Mapping[str, Any]) -> str:
    payload = _suppression_chunk_payload(chunk)
    return stable_chunk_hash(payload if payload is not chunk else chunk)


def _suppression_chunk_snippet(chunk: Mapping[str, Any], limit: int = 160) -> str:
    content = _suppression_chunk_string(chunk, "content", "content_preview", "content_with_weight", "text", "page_content") or ""
    content = " ".join(content.split())
    return content[:limit]


def _suppression_case_polluted(case: Mapping[str, Any], benchmark_item: Mapping[str, Any] | None) -> bool:
    if isinstance(benchmark_item, Mapping):
        for key in ("wrong_document_rate", "tag_pollution_rate", "unexpected_tag_hit_rate"):
            value = benchmark_item.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                return True
        for key in ("wrong_document_count", "tagged_chunk_count", "polluted_tagged_chunk_count", "unexpected_tag_count"):
            value = benchmark_item.get(key)
            if isinstance(value, int) and value > 0:
                return True
    return not bool(case.get("passed", True))


def _suppression_case_document_hits(case: Mapping[str, Any]) -> set[str]:
    hits: set[str] = set()
    for value in _suppression_string_values(case.get("document_hits")):
        normalized = value.strip().casefold()
        if normalized:
            hits.add(normalized)
    return hits


def _suppression_recommendation(kind: str, label: str) -> str:
    if kind == "bridge_term":
        return f"Review whether {label!r} should stay in the query rewrite or suppression path."
    if kind == "source_boundary":
        return "Review source boundaries or downranking; this source appears in polluted retrievals."
    if kind == "allowed_tag_review":
        return "Review the allowed-tag scope; this tag is still surfacing in polluted retrievals."
    if kind == "unexpected_tag":
        return "Review tag assignment and filters; this tag is outside the expected scope."
    return "Review this candidate manually."


def _suppression_risk(kind: str, *, polluted_query_count: int, polluted_chunk_count: int) -> tuple[str, float]:
    base_map = {
        "bridge_term": 0.25,
        "source_boundary": 0.82,
        "allowed_tag_review": 0.88,
        "unexpected_tag": 0.93,
    }
    base = base_map.get(kind, 0.75)
    risk_score = min(0.99, base + min(0.15, polluted_query_count * 0.03) + min(0.1, polluted_chunk_count * 0.02))
    risk = "low" if kind == "bridge_term" else "high"
    return risk, round(risk_score, 2)


def _suppression_bucket(
    buckets: dict[tuple[str, str], dict[str, Any]],
    *,
    kind: str,
    key: str,
    label: str,
    recommendation: str,
) -> dict[str, Any]:
    bucket = buckets.setdefault(
        (kind, key),
        {
            "kind": kind,
            "key": key,
            "label": label,
            "recommendation": recommendation,
            "score": 0.0,
            "query_ids": set(),
            "document_names": set(),
            "document_ids": set(),
            "tag_names": set(),
            "tag_labels": set(),
            "matched_terms": set(),
            "chunk_ids": set(),
            "examples": [],
            "polluted_chunk_count": 0,
            "raw_chunk_count": 0,
        },
    )
    bucket["label"] = label or bucket["label"]
    bucket["recommendation"] = recommendation or bucket["recommendation"]
    return bucket


def _suppression_bucket_add_example(
    bucket: dict[str, Any],
    *,
    query_id: str,
    document_name: str | None,
    document_id: str | None,
    chunk_id: str | None,
    stable_hash: str,
    snippet: str,
    matched_terms: Iterable[str] = (),
    raw_tags: Iterable[str] = (),
    tag_label: str | None = None,
) -> None:
    if len(bucket["examples"]) >= 3:
        return
    example = {
        "query_id": query_id,
        "document_name": document_name,
        "document_id": document_id,
        "chunk_id": chunk_id,
        "stable_hash": stable_hash,
        "snippet": snippet,
    }
    matched = sorted({term for term in matched_terms if term})
    if matched:
        example["matched_terms"] = matched
    tags = sorted({tag for tag in raw_tags if tag})
    if tags:
        example["raw_tags"] = tags
    if tag_label:
        example["tag_label"] = tag_label
    bucket["examples"].append(example)


def _suppression_bucket_touch(
    bucket: dict[str, Any],
    *,
    query_id: str,
    document_name: str | None,
    document_id: str | None,
    chunk_id: str | None,
    stable_hash: str,
    snippet: str,
    matched_terms: Iterable[str] = (),
    raw_tags: Iterable[str] = (),
    tag_label: str | None = None,
    raw_payload_present: bool = False,
) -> None:
    bucket["query_ids"].add(query_id)
    if document_name:
        bucket["document_names"].add(document_name)
    if document_id:
        bucket["document_ids"].add(document_id)
    if chunk_id:
        bucket["chunk_ids"].add(chunk_id)
    if raw_payload_present:
        bucket["raw_chunk_count"] += 1
    matched = {term for term in matched_terms if term}
    if matched:
        bucket["matched_terms"].update(matched)
    tags = {tag for tag in raw_tags if tag}
    if tags:
        bucket["tag_names"].update(tags)
    if tag_label:
        bucket["tag_labels"].add(tag_label)
    bucket["polluted_chunk_count"] += 1
    bucket["score"] += 1.0 + 0.5 * len(matched) + 0.25 * len(tags)
    _suppression_bucket_add_example(
        bucket,
        query_id=query_id,
        document_name=document_name,
        document_id=document_id,
        chunk_id=chunk_id,
        stable_hash=stable_hash,
        snippet=snippet,
        matched_terms=matched,
        raw_tags=tags,
        tag_label=tag_label,
    )


def _suppression_bucket_to_candidate(bucket: Mapping[str, Any]) -> dict[str, Any]:
    query_ids = sorted(bucket.get("query_ids", []))
    document_names = sorted(bucket.get("document_names", []))
    document_ids = sorted(bucket.get("document_ids", []))
    tag_names = sorted(bucket.get("tag_names", []))
    tag_labels = sorted(bucket.get("tag_labels", []))
    matched_terms = sorted(bucket.get("matched_terms", []))
    polluted_query_count = len(query_ids)
    polluted_chunk_count = int(bucket.get("polluted_chunk_count", 0))
    raw_chunk_count = int(bucket.get("raw_chunk_count", 0))
    risk, risk_score = _suppression_risk(
        str(bucket.get("kind", "")),
        polluted_query_count=polluted_query_count,
        polluted_chunk_count=polluted_chunk_count,
    )
    candidate = {
        "id": f"{bucket.get('kind', 'candidate')}:{bucket.get('key', '')}",
        "kind": bucket.get("kind"),
        "label": bucket.get("label"),
        "risk": risk,
        "risk_score": risk_score,
        "score": round(float(bucket.get("score", 0.0)), 4),
        "recommendation": bucket.get("recommendation"),
        "evidence": {
            "query_ids": query_ids,
            "document_names": document_names,
            "document_ids": document_ids,
            "tag_names": tag_names,
            "tag_labels": tag_labels,
            "matched_terms": matched_terms,
            "polluted_query_count": polluted_query_count,
            "polluted_chunk_count": polluted_chunk_count,
            "raw_chunk_count": raw_chunk_count,
            "examples": list(bucket.get("examples", [])),
        },
    }
    if not candidate["evidence"]["document_ids"]:
        candidate["evidence"].pop("document_ids")
    if not candidate["evidence"]["tag_names"]:
        candidate["evidence"].pop("tag_names")
    if not candidate["evidence"]["tag_labels"]:
        candidate["evidence"].pop("tag_labels")
    if not candidate["evidence"]["matched_terms"]:
        candidate["evidence"].pop("matched_terms")
    if not candidate["evidence"]["examples"]:
        candidate["evidence"].pop("examples")
    return candidate


def _suppression_hotspot(candidate: Mapping[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), Mapping) else {}
    hotspot = {
        "id": candidate.get("id"),
        "kind": candidate.get("kind"),
        "label": candidate.get("label"),
        "risk": candidate.get("risk"),
        "risk_score": candidate.get("risk_score"),
        "score": candidate.get("score"),
        "polluted_query_count": evidence.get("polluted_query_count", 0),
        "polluted_chunk_count": evidence.get("polluted_chunk_count", 0),
    }
    return hotspot


def _suppression_top_candidates(candidates: list[dict[str, Any]], *, kind: str, limit: int = 5) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate.get("kind") == kind][:limit]


def suppression_report_payload(
    report: Mapping[str, Any],
    *,
    tagset_path: str | Path | None = None,
    max_candidates: int = 20,
) -> dict[str, Any]:
    """Create a recommendation-only suppression report from a validation report."""

    if not isinstance(report, Mapping):
        raise BenchmarkGovernanceError("suppression report input must be a JSON object")
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise BenchmarkGovernanceError("suppression report requires a validation report with cases")

    benchmark = report.get("benchmark")
    benchmark_per_query = {}
    benchmark_metrics: dict[str, float] = {}
    query_type_breakdown: dict[str, Any] = {}
    if isinstance(benchmark, Mapping):
        benchmark_metrics = {
            key: float(value)
            for key, value in benchmark.get("metrics", {}).items()
            if isinstance(value, (int, float))
        }
        per_query = benchmark.get("per_query")
        if isinstance(per_query, list):
            for item in per_query:
                if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                    benchmark_per_query[str(item["id"])] = item
        breakdown = benchmark.get("query_type_breakdown")
        if isinstance(breakdown, Mapping):
            query_type_breakdown = dict(breakdown)

    tag_lookup, tagset_report = _suppression_tag_lookup(tagset_path)
    issues: list[BenchmarkGovernanceIssue] = []
    if tagset_report:
        if not tagset_report.get("ok", True):
            for raw_issue in tagset_report.get("issues", []):
                if not isinstance(raw_issue, Mapping):
                    continue
                issues.append(
                    BenchmarkGovernanceIssue(
                        severity=str(raw_issue.get("severity", "warning")),
                        code=f"tagset_{raw_issue.get('code', 'issue')}",
                        message=str(raw_issue.get("message", "")),
                        field=raw_issue.get("field") if isinstance(raw_issue.get("field"), str) else None,
                        recommendation=raw_issue.get("recommendation") if isinstance(raw_issue.get("recommendation"), str) else None,
                    )
                )

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    polluted_case_count = 0
    suspect_chunk_count = 0
    raw_chunk_count = 0
    top_chunk_count = 0

    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        query_id = _clean_string(case.get("id")) or _clean_string(case.get("query_id")) or f"case-{index + 1}"
        question = _clean_string(case.get("question")) or ""
        metadata = case.get("metadata") if isinstance(case.get("metadata"), Mapping) else {}
        benchmark_item = benchmark_per_query.get(query_id)
        if not _suppression_case_polluted(case, benchmark_item):
            continue
        polluted_case_count += 1
        query_terms = _suppression_query_terms(case)
        document_hits = _suppression_case_document_hits(case)
        raw_chunks = case.get("top_chunks")
        if not isinstance(raw_chunks, list):
            continue

        suspect_chunks = []
        for chunk in raw_chunks:
            if not isinstance(chunk, Mapping):
                continue
            top_chunk_count += 1
            document_name, document_id, _chunk_id = _suppression_chunk_document_identity(chunk)
            chunk_key = {value.casefold() for value in (document_name, document_id) if value}
            if document_hits and chunk_key and chunk_key.intersection(document_hits):
                continue
            suspect_chunks.append(chunk)

        if not suspect_chunks and benchmark_item:
            if any(
                isinstance(benchmark_item.get(key), (int, float)) and float(benchmark_item.get(key)) > 0
                for key in ("wrong_document_rate", "tag_pollution_rate", "unexpected_tag_hit_rate")
            ) or any(
                isinstance(benchmark_item.get(key), int) and int(benchmark_item.get(key)) > 0
                for key in ("wrong_document_count", "tagged_chunk_count", "polluted_tagged_chunk_count", "unexpected_tag_count")
            ):
                suspect_chunks = [chunk for chunk in raw_chunks if isinstance(chunk, Mapping)]
        elif not suspect_chunks:
            suspect_chunks = [chunk for chunk in raw_chunks if isinstance(chunk, Mapping)]

        for chunk in suspect_chunks:
            document_name, document_id, chunk_id = _suppression_chunk_document_identity(chunk)
            raw_payload = _suppression_chunk_payload(chunk)
            stable_hash = _suppression_chunk_hash(chunk)
            snippet = _suppression_chunk_snippet(chunk)
            chunk_terms = _suppression_chunk_terms(chunk)
            raw_tags = _suppression_chunk_tags(chunk, tag_lookup=tag_lookup)
            raw_tag_names = set(raw_tags)
            raw_chunk_present = isinstance(chunk.get("raw"), Mapping)
            if raw_chunk_present:
                raw_chunk_count += 1
            suspect_chunk_count += 1

            matched_terms = sorted(query_terms.intersection(chunk_terms))
            for term in matched_terms:
                bucket = _suppression_bucket(
                    buckets,
                    kind="bridge_term",
                    key=term,
                    label=term,
                    recommendation=_suppression_recommendation("bridge_term", term),
                )
                _suppression_bucket_touch(
                    bucket,
                    query_id=query_id,
                    document_name=document_name,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    stable_hash=stable_hash,
                    snippet=snippet,
                    matched_terms=[term],
                    raw_tags=raw_tag_names,
                    raw_payload_present=raw_chunk_present,
                )

            source_key = "|".join(part for part in (document_name, document_id) if part)
            if source_key:
                source_label = document_name or document_id or source_key
                bucket = _suppression_bucket(
                    buckets,
                    kind="source_boundary",
                    key=source_key.casefold(),
                    label=source_label,
                    recommendation=_suppression_recommendation("source_boundary", source_label),
                )
                _suppression_bucket_touch(
                    bucket,
                    query_id=query_id,
                    document_name=document_name,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    stable_hash=stable_hash,
                    snippet=snippet,
                    raw_tags=raw_tag_names,
                    raw_payload_present=raw_chunk_present,
                )

            scope_tags = _suppression_tag_scope(metadata, tag_lookup=tag_lookup)
            if raw_tag_names:
                for canonical_tag in sorted(raw_tag_names):
                    tag_entry = raw_tags.get(canonical_tag)
                    tag_label = _clean_string(tag_entry.get("label")) if isinstance(tag_entry, Mapping) else None
                    display_label = tag_label or (tag_entry.get("name") if isinstance(tag_entry, Mapping) else None) or canonical_tag
                    if canonical_tag in scope_tags:
                        bucket = _suppression_bucket(
                            buckets,
                            kind="allowed_tag_review",
                            key=canonical_tag,
                            label=display_label,
                            recommendation=_suppression_recommendation("allowed_tag_review", display_label),
                        )
                        _suppression_bucket_touch(
                            bucket,
                            query_id=query_id,
                            document_name=document_name,
                            document_id=document_id,
                            chunk_id=chunk_id,
                            stable_hash=stable_hash,
                            snippet=snippet,
                            raw_tags=[canonical_tag],
                            tag_label=display_label,
                            raw_payload_present=raw_chunk_present,
                        )
                    else:
                        bucket = _suppression_bucket(
                            buckets,
                            kind="unexpected_tag",
                            key=canonical_tag,
                            label=display_label,
                            recommendation=_suppression_recommendation("unexpected_tag", display_label),
                        )
                        _suppression_bucket_touch(
                            bucket,
                            query_id=query_id,
                            document_name=document_name,
                            document_id=document_id,
                            chunk_id=chunk_id,
                            stable_hash=stable_hash,
                            snippet=snippet,
                            raw_tags=[canonical_tag],
                            tag_label=display_label,
                            raw_payload_present=raw_chunk_present,
                        )

    candidates = [_suppression_bucket_to_candidate(bucket) for bucket in buckets.values()]
    kind_order = {
        "bridge_term": 0,
        "source_boundary": 1,
        "allowed_tag_review": 2,
        "unexpected_tag": 3,
    }
    candidates.sort(
        key=lambda item: (
            kind_order.get(str(item.get("kind")), 9),
            -float(item.get("score", 0.0)),
            -float(item.get("risk_score", 0.0)),
            str(item.get("label", "")),
        )
    )
    limited_candidates = candidates[:max_candidates]
    hotspots = {
        "bridge_terms": [_suppression_hotspot(candidate) for candidate in _suppression_top_candidates(candidates, kind="bridge_term")],
        "sources": [_suppression_hotspot(candidate) for candidate in _suppression_top_candidates(candidates, kind="source_boundary")],
        "tags": [
            _suppression_hotspot(candidate)
            for candidate in _suppression_top_candidates(candidates, kind="allowed_tag_review")
        ]
        + [_suppression_hotspot(candidate) for candidate in _suppression_top_candidates(candidates, kind="unexpected_tag")],
    }

    summary = {
        "case_count": len(cases),
        "polluted_case_count": polluted_case_count,
        "top_chunk_count": top_chunk_count,
        "suspect_chunk_count": suspect_chunk_count,
        "raw_chunk_count": raw_chunk_count,
        "raw_chunk_coverage": _rate(raw_chunk_count, suspect_chunk_count),
        "candidate_count": len(candidates),
        "bridge_term_candidate_count": sum(1 for candidate in candidates if candidate.get("kind") == "bridge_term"),
        "source_boundary_candidate_count": sum(1 for candidate in candidates if candidate.get("kind") == "source_boundary"),
        "allowed_tag_review_candidate_count": sum(1 for candidate in candidates if candidate.get("kind") == "allowed_tag_review"),
        "unexpected_tag_candidate_count": sum(1 for candidate in candidates if candidate.get("kind") == "unexpected_tag"),
        "low_risk_candidate_count": sum(1 for candidate in candidates if candidate.get("risk") == "low"),
        "high_risk_candidate_count": sum(1 for candidate in candidates if candidate.get("risk") == "high"),
    }
    if tagset_report:
        summary.update(
            {
                "tagset_ok": tagset_report.get("ok", True),
                "tagset_tag_count": tagset_report.get("summary", {}).get("tag_count", 0),
                "tagset_assignment_count": tagset_report.get("summary", {}).get("assignment_count", 0),
                "tagset_unused_tag_count": tagset_report.get("summary", {}).get("unused_tag_count", 0),
                "tagset_orphan_tag_count": tagset_report.get("summary", {}).get("orphan_tag_count", 0),
            }
        )

    metrics = dict(benchmark_metrics)
    if benchmark_metrics:
        metrics.update(
            {
                "polluted_case_count": polluted_case_count,
                "raw_chunk_count": raw_chunk_count,
                "suspect_chunk_count": suspect_chunk_count,
            }
        )

    return {
        "ok": _ok(issues),
        "schema": SUPPRESSION_REPORT_SCHEMA,
        "validation_report": str(report.get("report") or report.get("validation_report") or ""),
        "dataset": report.get("dataset", {}),
        "validation_level": report.get("level"),
        "metrics": metrics,
        "query_type_breakdown": query_type_breakdown,
        "tagset": tagset_report,
        "summary": summary,
        "hotspots": hotspots,
        "candidates": limited_candidates,
        "issues": [issue.to_dict() for issue in issues],
    }


def suppression_report_file(
    path: str | Path,
    *,
    tagset_path: str | Path | None = None,
    max_candidates: int = 20,
) -> dict[str, Any]:
    """Load a validation report and generate a suppression report."""

    report = _read_json(path)
    if not isinstance(report, Mapping):
        raise BenchmarkGovernanceError("suppression report input must be a JSON object")
    output = suppression_report_payload(report, tagset_path=tagset_path, max_candidates=max_candidates)
    output["validation_report"] = str(path)
    return output


def _suppression_table_rows(candidates: list[dict[str, Any]], *, kind: str) -> list[str]:
    rows: list[str] = []
    filtered = [candidate for candidate in candidates if candidate.get("kind") == kind]
    if not filtered:
        return rows
    if kind == "bridge_term":
        rows = [
            "",
            "| label | risk | risk score | score | queries | chunks | documents | recommendation |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for candidate in filtered:
            evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), Mapping) else {}
            rows.append(
                "| {label} | {risk} | `{risk_score}` | `{score}` | `{queries}` | `{chunks}` | {documents} | {recommendation} |".format(
                    label=str(candidate.get("label", "")).replace("|", "\\|"),
                    risk=candidate.get("risk", ""),
                    risk_score=candidate.get("risk_score", ""),
                    score=candidate.get("score", ""),
                    queries=", ".join(evidence.get("query_ids", [])[:5]) or "-",
                    chunks=evidence.get("polluted_chunk_count", 0),
                    documents=", ".join(evidence.get("document_names", [])[:4]) or "-",
                    recommendation=str(candidate.get("recommendation", "")).replace("|", "\\|"),
                )
            )
        return rows
    if kind == "source_boundary":
        rows = [
            "",
            "| label | risk | risk score | score | queries | chunks | documents | recommendation |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for candidate in filtered:
            evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), Mapping) else {}
            rows.append(
                "| {label} | {risk} | `{risk_score}` | `{score}` | `{queries}` | `{chunks}` | {documents} | {recommendation} |".format(
                    label=str(candidate.get("label", "")).replace("|", "\\|"),
                    risk=candidate.get("risk", ""),
                    risk_score=candidate.get("risk_score", ""),
                    score=candidate.get("score", ""),
                    queries=", ".join(evidence.get("query_ids", [])[:5]) or "-",
                    chunks=evidence.get("polluted_chunk_count", 0),
                    documents=", ".join(evidence.get("document_names", [])[:4]) or "-",
                    recommendation=str(candidate.get("recommendation", "")).replace("|", "\\|"),
                )
            )
        return rows
    if kind in {"allowed_tag_review", "unexpected_tag"}:
        rows = [
            "",
            "| kind | label | risk | risk score | score | queries | chunks | tags | recommendation |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for candidate in filtered:
            evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), Mapping) else {}
            tags = evidence.get("tag_labels") or evidence.get("tag_names") or []
            rows.append(
                "| {kind} | {label} | {risk} | `{risk_score}` | `{score}` | `{queries}` | `{chunks}` | {tags} | {recommendation} |".format(
                    kind=str(candidate.get("kind", "")).replace("|", "\\|"),
                    label=str(candidate.get("label", "")).replace("|", "\\|"),
                    risk=candidate.get("risk", ""),
                    risk_score=candidate.get("risk_score", ""),
                    score=candidate.get("score", ""),
                    queries=", ".join(evidence.get("query_ids", [])[:5]) or "-",
                    chunks=evidence.get("polluted_chunk_count", 0),
                    tags=", ".join(tags[:4]) or "-",
                    recommendation=str(candidate.get("recommendation", "")).replace("|", "\\|"),
                )
            )
        return rows
    return rows


def render_suppression_report_markdown(report: Mapping[str, Any], *, title: str = "RAGFlow Suppression Report") -> str:
    """Render a compact Markdown summary for suppression candidates."""

    base = render_benchmark_governance_markdown(report, title=title).rstrip()
    candidates = report.get("candidates", []) if isinstance(report.get("candidates"), list) else []
    if not candidates:
        return base + "\n"
    lines = [base, "", "## Bridge Terms"]
    bridge = _suppression_table_rows(candidates, kind="bridge_term")
    lines.extend(bridge or ["- none"])
    lines.extend(["", "## Sources"])
    sources = _suppression_table_rows(candidates, kind="source_boundary")
    lines.extend(sources or ["- none"])
    lines.extend(["", "## Tags"])
    tags = _suppression_table_rows(candidates, kind="allowed_tag_review") + _suppression_table_rows(
        candidates, kind="unexpected_tag"
    )
    lines.extend(tags or ["- none"])
    return "\n".join(lines) + "\n"


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
    suggestions = report.get("retrieval_parameter_suggestions")
    if isinstance(suggestions, list) and suggestions:
        lines.extend(
            [
                "",
                "## Retrieval Parameter Suggestions",
                "",
                "| parameter | action | current | suggested | confidence | reason |",
                "| --- | --- | ---: | ---: | --- | --- |",
            ]
        )
        for suggestion in suggestions:
            if not isinstance(suggestion, Mapping):
                continue
            lines.append(
                "| {parameter} | `{action}` | `{current}` | `{suggested}` | `{confidence}` | {reason} |".format(
                    parameter=suggestion.get("parameter", ""),
                    action=suggestion.get("action", ""),
                    current=suggestion.get("current", ""),
                    suggested=suggestion.get("suggested", ""),
                    confidence=suggestion.get("confidence", ""),
                    reason=str(suggestion.get("reason", "")).replace("|", "\\|"),
                )
            )
    experiments = report.get("recommended_experiments")
    if isinstance(experiments, list) and experiments:
        lines.extend(["", "## Recommended Experiments", ""])
        for experiment in experiments:
            if isinstance(experiment, Mapping):
                lines.append(f"- `{experiment.get('id')}`")
    lines.append("")
    return "\n".join(lines)
