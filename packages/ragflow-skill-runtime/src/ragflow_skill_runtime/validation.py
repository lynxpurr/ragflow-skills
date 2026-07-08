"""Lightweight retrieval validation primitives."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .retrieval import CHUNK_HASH_ALGORITHM, NormalizedChunk, normalize_retrieval_response, stable_chunk_hash
from .runtime_resilience import build_runtime_partial_failure_report


class ValidationError(RuntimeError):
    """Raised when validation inputs are invalid."""


METRIC_KEYS = (
    "hit_rate",
    "mrr",
    "precision_at_k",
    "recall_at_k",
    "ndcg_at_k",
    "map_at_k",
    "empty_result_rate",
    "supporting_document_coverage",
)
STRICT_CHUNK_METRIC_KEYS = (
    "strict_chunk_recall_at_k",
    "expected_chunk_hit_rate",
    "expected_evidence_rank",
)
CANDIDATE_SNAPSHOT_METRIC_KEYS = (
    "candidate_snapshot_expected_chunk_recall_at_k",
    "candidate_snapshot_expected_chunk_hit_rate",
)
EXPECTED_TERM_METRIC_KEYS = (
    "expected_term_recall_at_k",
    "expected_term_hit_rate",
    "table_term_recall_at_k",
    "table_term_hit_rate",
)
POLLUTION_METRIC_KEYS = (
    "wrong_document_rate",
    "tag_pollution_rate",
    "expected_tag_hit_rate",
    "unexpected_tag_hit_rate",
)
MULTIMODAL_METRIC_KEYS = (
    "image_precision_at_k",
    "image_recall_at_k",
    "image_recall",
    "visual_coverage_rate",
    "table_recall_at_k",
    "table_recall",
)
BENCHMARK_METRIC_KEYS = (
    METRIC_KEYS
    + STRICT_CHUNK_METRIC_KEYS
    + CANDIDATE_SNAPSHOT_METRIC_KEYS
    + EXPECTED_TERM_METRIC_KEYS
    + POLLUTION_METRIC_KEYS
    + MULTIMODAL_METRIC_KEYS
)
CHUNK_SNAPSHOT_SCHEMA = "ragflow_chunk_snapshot_v1"
MULTIMODAL_BENCHMARK_SCHEMA = "ragflow_multimodal_benchmark_v1"
MULTIMODAL_BENCHMARK_CATEGORIES = (
    "text_fact",
    "table_value",
    "visual_identification",
    "diagram_software_screenshot",
    "caption_context",
    "mixed_table_plus_image",
)
MULTIMODAL_EXPECTED_MODALITIES = ("text", "table", "image", "mixed")
VALIDATION_RUNTIME_SUCCESS_STATUSES = ("passed",)
VALIDATION_RUNTIME_WARNING_STATUSES = ("failed",)
VALIDATION_RUNTIME_FAILURE_STATUSES = ("error", "timeout")
VALIDATION_RUNTIME_SKIPPED_STATUSES = ("skipped",)
VALIDATION_RUNTIME_TIMEOUT_STATUSES = ("timeout",)


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    raise ValidationError(f"{field_name} must be a string or list of strings")


def _as_metric(value: Any, *, field_name: str) -> float:
    try:
        metric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a number") from exc
    if metric < 0:
        raise ValidationError(f"{field_name} must be non-negative")
    return metric


def _metric_or_none(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _as_metric(value, field_name=field_name)


@dataclass(frozen=True)
class ValidationQuery:
    id: str
    question: str
    min_chunks: int = 1
    expected_terms: list[str] = field(default_factory=list)
    expected_documents: list[str] = field(default_factory=list)
    top_k: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int) -> "ValidationQuery":
        question = data.get("question") or data.get("query")
        if not isinstance(question, str) or not question.strip():
            raise ValidationError(f"query[{index}].question is required")
        min_chunks = int(data.get("min_chunks", 1))
        if min_chunks < 0:
            raise ValidationError(f"query[{index}].min_chunks must be non-negative")
        top_k = data.get("top_k")
        if top_k is not None:
            top_k = int(top_k)
            if top_k <= 0:
                raise ValidationError(f"query[{index}].top_k must be positive")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError(f"query[{index}].metadata must be an object")
        return cls(
            id=str(data.get("id") or data.get("query_id") or f"q{index + 1}"),
            question=question.strip(),
            min_chunks=min_chunks,
            expected_terms=_string_list(
                data.get("expected_terms", data.get("must_contain")),
                field_name=f"query[{index}].expected_terms",
            ),
            expected_documents=_string_list(
                data.get("expected_documents", data.get("expected_docs")),
                field_name=f"query[{index}].expected_documents",
            ),
            top_k=top_k,
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "min_chunks": self.min_chunks,
            "expected_terms": list(self.expected_terms),
            "expected_documents": list(self.expected_documents),
            "top_k": self.top_k,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BenchmarkQrel:
    query_id: str
    target: str
    relevance: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    field: str = "document"

    @property
    def key(self) -> str:
        return f"{self.field}:{self.target}".lower()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int) -> "BenchmarkQrel":
        query_id = data.get("query_id") or data.get("id") or data.get("query")
        if not isinstance(query_id, str) or not query_id.strip():
            raise ValidationError(f"qrel[{index}].query_id is required")

        field_name = str(data.get("field") or "document")
        target = data.get("target")
        if target is None:
            if data.get("chunk_id") is not None:
                field_name = "chunk_id"
                target = data.get("chunk_id")
            elif data.get("document_id") is not None:
                field_name = "document_id"
                target = data.get("document_id")
            else:
                target = (
                    data.get("document")
                    or data.get("document_name")
                    or data.get("doc")
                    or data.get("doc_name")
                )
        if not isinstance(target, str) or not target.strip():
            raise ValidationError(f"qrel[{index}].target or document is required")

        allowed_fields = {
            "document",
            "document_name",
            "document_id",
            "chunk_id",
            "chunk_hash",
            "expected_chunk",
            "content",
        }
        if field_name not in allowed_fields:
            raise ValidationError(
                f"qrel[{index}].field must be one of {', '.join(sorted(allowed_fields))}"
            )

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError(f"qrel[{index}].metadata must be an object")

        return cls(
            query_id=query_id.strip(),
            target=target.strip(),
            relevance=_as_metric(data.get("relevance", 1.0), field_name=f"qrel[{index}].relevance"),
            field=field_name,
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "target": self.target,
            "relevance": self.relevance,
            "field": self.field,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BenchmarkGate:
    min_hit_rate: float | None = None
    min_mrr: float | None = None
    min_precision_at_k: float | None = None
    min_recall_at_k: float | None = None
    min_ndcg_at_k: float | None = None
    min_map_at_k: float | None = None
    min_strict_chunk_recall_at_k: float | None = None
    min_expected_chunk_hit_rate: float | None = None
    min_expected_term_recall_at_k: float | None = None
    min_table_term_recall_at_k: float | None = None
    max_expected_evidence_rank: float | None = None
    max_empty_result_rate: float | None = None
    max_hit_rate_drop: float | None = None
    max_mrr_drop: float | None = None
    max_ndcg_drop: float | None = None
    max_map_drop: float | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkGate":
        raw = data.get("thresholds", data)
        if not isinstance(raw, Mapping):
            raise ValidationError("gate config must be an object")
        return cls(
            min_hit_rate=_metric_or_none(raw.get("min_hit_rate"), field_name="min_hit_rate"),
            min_mrr=_metric_or_none(raw.get("min_mrr"), field_name="min_mrr"),
            min_precision_at_k=_metric_or_none(
                raw.get("min_precision_at_k"), field_name="min_precision_at_k"
            ),
            min_recall_at_k=_metric_or_none(raw.get("min_recall_at_k"), field_name="min_recall_at_k"),
            min_ndcg_at_k=_metric_or_none(raw.get("min_ndcg_at_k"), field_name="min_ndcg_at_k"),
            min_map_at_k=_metric_or_none(raw.get("min_map_at_k"), field_name="min_map_at_k"),
            min_strict_chunk_recall_at_k=_metric_or_none(
                raw.get("min_strict_chunk_recall_at_k"),
                field_name="min_strict_chunk_recall_at_k",
            ),
            min_expected_chunk_hit_rate=_metric_or_none(
                raw.get("min_expected_chunk_hit_rate"),
                field_name="min_expected_chunk_hit_rate",
            ),
            min_expected_term_recall_at_k=_metric_or_none(
                raw.get("min_expected_term_recall_at_k"),
                field_name="min_expected_term_recall_at_k",
            ),
            min_table_term_recall_at_k=_metric_or_none(
                raw.get("min_table_term_recall_at_k"),
                field_name="min_table_term_recall_at_k",
            ),
            max_expected_evidence_rank=_metric_or_none(
                raw.get("max_expected_evidence_rank"),
                field_name="max_expected_evidence_rank",
            ),
            max_empty_result_rate=_metric_or_none(
                raw.get("max_empty_result_rate"), field_name="max_empty_result_rate"
            ),
            max_hit_rate_drop=_metric_or_none(raw.get("max_hit_rate_drop"), field_name="max_hit_rate_drop"),
            max_mrr_drop=_metric_or_none(raw.get("max_mrr_drop"), field_name="max_mrr_drop"),
            max_ndcg_drop=_metric_or_none(raw.get("max_ndcg_drop"), field_name="max_ndcg_drop"),
            max_map_drop=_metric_or_none(raw.get("max_map_drop"), field_name="max_map_drop"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "min_hit_rate": self.min_hit_rate,
                "min_mrr": self.min_mrr,
                "min_precision_at_k": self.min_precision_at_k,
                "min_recall_at_k": self.min_recall_at_k,
                "min_ndcg_at_k": self.min_ndcg_at_k,
                "min_map_at_k": self.min_map_at_k,
                "min_strict_chunk_recall_at_k": self.min_strict_chunk_recall_at_k,
                "min_expected_chunk_hit_rate": self.min_expected_chunk_hit_rate,
                "min_expected_term_recall_at_k": self.min_expected_term_recall_at_k,
                "min_table_term_recall_at_k": self.min_table_term_recall_at_k,
                "max_expected_evidence_rank": self.max_expected_evidence_rank,
                "max_empty_result_rate": self.max_empty_result_rate,
                "max_hit_rate_drop": self.max_hit_rate_drop,
                "max_mrr_drop": self.max_mrr_drop,
                "max_ndcg_drop": self.max_ndcg_drop,
                "max_map_drop": self.max_map_drop,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class BenchmarkEvaluation:
    cutoff: int
    metrics: dict[str, float | int]
    per_query: list[dict[str, Any]]
    query_type_breakdown: dict[str, dict[str, float | int]] = field(default_factory=dict)
    multimodal: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    baseline: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return bool(self.gate.get("ok", True)) if self.gate else True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "ragflow_benchmark_report_v1",
            "cutoff": self.cutoff,
            "metrics": self.metrics,
            "per_query": self.per_query,
            "query_type_breakdown": self.query_type_breakdown,
        }
        if self.multimodal is not None:
            payload["multimodal"] = self.multimodal
        if self.gate is not None:
            payload["gate"] = self.gate
        if self.baseline is not None:
            payload["baseline"] = self.baseline
        return payload


@dataclass(frozen=True)
class ValidationCaseResult:
    query: ValidationQuery
    passed: bool
    chunk_count: int
    term_hits: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    document_hits: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    error: str | None = None
    chunks: list[NormalizedChunk] = field(default_factory=list)

    def to_dict(self, *, max_chunks: int = 3, include_raw: bool = False) -> dict[str, Any]:
        return {
            "id": self.query.id,
            "question": self.query.question,
            "passed": self.passed,
            "chunk_count": self.chunk_count,
            "term_hits": list(self.term_hits),
            "missing_terms": list(self.missing_terms),
            "document_hits": list(self.document_hits),
            "missing_documents": list(self.missing_documents),
            "error": self.error,
            "top_chunks": [chunk.to_dict(include_raw=include_raw) for chunk in self.chunks[:max_chunks]],
            "metadata": self.query.metadata,
        }


def _validation_runtime_status(case: ValidationCaseResult) -> str:
    if case.error:
        error_text = case.error.lower()
        if "timeout" in error_text or "timed out" in error_text:
            return "timeout"
        return "error"
    return "passed" if case.passed else "failed"


@dataclass(frozen=True)
class ValidationReport:
    level: str
    dataset_id: str
    dataset_name: str
    cases: list[ValidationCaseResult]
    benchmark: BenchmarkEvaluation | None = None

    @property
    def ok(self) -> bool:
        return all(case.passed for case in self.cases) and (
            self.benchmark.ok if self.benchmark else True
        )

    def runtime_partial_failure_report(self) -> dict[str, Any]:
        return build_runtime_partial_failure_report(
            "ragflow-kb-build validate",
            [
                {
                    "label": case.query.id,
                    "status": _validation_runtime_status(case),
                }
                for case in self.cases
            ],
            success_statuses=VALIDATION_RUNTIME_SUCCESS_STATUSES,
            warning_statuses=VALIDATION_RUNTIME_WARNING_STATUSES,
            failure_statuses=VALIDATION_RUNTIME_FAILURE_STATUSES,
            skipped_statuses=VALIDATION_RUNTIME_SKIPPED_STATUSES,
            timeout_statuses=VALIDATION_RUNTIME_TIMEOUT_STATUSES,
        )

    def metrics(self) -> dict[str, Any]:
        total = len(self.cases)
        passed = sum(1 for case in self.cases if case.passed)
        expected_terms = sum(len(case.query.expected_terms) for case in self.cases)
        term_hits = sum(len(case.term_hits) for case in self.cases)
        expected_docs = sum(len(case.query.expected_documents) for case in self.cases)
        doc_hits = sum(len(case.document_hits) for case in self.cases)
        chunk_counts = [case.chunk_count for case in self.cases]
        runtime_partial_summary = self.runtime_partial_failure_report()["summary"]
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else 0.0,
            "empty_results": sum(1 for count in chunk_counts if count == 0),
            "average_chunks": sum(chunk_counts) / total if total else 0.0,
            "term_hit_rate": term_hits / expected_terms if expected_terms else None,
            "document_hit_rate": doc_hits / expected_docs if expected_docs else None,
            "runtime_partial_failure_status": runtime_partial_summary["status"],
            "runtime_warning_count": runtime_partial_summary["warning_count"],
            "runtime_failure_count": runtime_partial_summary["failure_count"],
            "runtime_timeout_count": runtime_partial_summary["timeout_count"],
            "runtime_skipped_count": runtime_partial_summary["skipped_count"],
        }

    def status(self) -> dict[str, Any]:
        case_failure_count = sum(1 for case in self.cases if not case.passed)
        gate = self.benchmark.gate if self.benchmark and isinstance(self.benchmark.gate, Mapping) else None
        gate_configured = bool(gate.get("configured")) if gate else False
        gate_failed = bool(gate and gate_configured and not gate.get("ok", True))
        if case_failure_count and gate_failed:
            failure_type = "case_and_gate_threshold"
        elif case_failure_count:
            failure_type = "case"
        elif gate_failed:
            failure_type = "gate_threshold"
        else:
            failure_type = None
        return {
            "ok": self.ok,
            "case_status": "failed" if case_failure_count else "passed",
            "case_failure_count": case_failure_count,
            "benchmark_gate_configured": gate_configured,
            "benchmark_gate_status": gate.get("status", "unknown") if gate else "not_applicable",
            "failure_type": failure_type,
        }

    def to_dict(self, *, max_chunks: int = 3, include_raw: bool = False) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status(),
            "level": self.level,
            "dataset": {"id": self.dataset_id, "name": self.dataset_name},
            "metrics": self.metrics(),
            "runtime_partial_failure": self.runtime_partial_failure_report(),
            "cases": [case.to_dict(max_chunks=max_chunks, include_raw=include_raw) for case in self.cases],
            **({"benchmark": self.benchmark.to_dict()} if self.benchmark else {}),
        }


def load_validation_queries(path: str | Path) -> list[ValidationQuery]:
    """Load validation queries from a JSON file."""

    query_path = Path(path)
    try:
        data = json.loads(query_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"query set not found: {query_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"query set is not valid JSON: {query_path}") from exc

    raw_queries = data.get("queries") if isinstance(data, Mapping) else data
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValidationError("query set must be a non-empty list or object with queries")
    queries = []
    for index, item in enumerate(raw_queries):
        if not isinstance(item, Mapping):
            raise ValidationError(f"query[{index}] must be an object")
        queries.append(ValidationQuery.from_dict(item, index=index))
    return queries


def _expand_qrel_item(item: Mapping[str, Any], *, index: int) -> list[Mapping[str, Any]]:
    query_id = item.get("query_id") or item.get("id") or item.get("query")
    if not isinstance(query_id, str) or not query_id.strip():
        return [item]

    expanded: list[Mapping[str, Any]] = []
    metadata = item.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    metadata = _qrel_metadata_with_multimodal_extensions(item, metadata)
    relevance = item.get("relevance", 1.0)

    if any(key in item for key in ("target", "document", "document_name", "doc", "doc_name", "chunk_id", "document_id")):
        direct_item = dict(item)
        direct_item["metadata"] = dict(metadata)
        expanded.append(direct_item)

    for document in _string_list(item.get("expected_documents"), field_name=f"qrel[{index}].expected_documents"):
        expanded.append(
            {
                "query_id": query_id,
                "target": document,
                "relevance": relevance,
                "field": "document",
                "metadata": dict(metadata),
            }
        )
    for chunk in _string_list(item.get("expected_chunks"), field_name=f"qrel[{index}].expected_chunks"):
        expanded.append(
            {
                "query_id": query_id,
                "target": chunk,
                "relevance": relevance,
                "field": "expected_chunk",
                "metadata": dict(metadata),
            }
        )

    return expanded or [item]


def load_benchmark_qrels(path: str | Path) -> dict[str, list[BenchmarkQrel]]:
    """Load qrels for benchmark validation from a compact JSON file."""

    qrels_path = Path(path)
    try:
        data = json.loads(qrels_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"qrels not found: {qrels_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"qrels are not valid JSON: {qrels_path}") from exc

    raw_qrels: list[Mapping[str, Any]] = []
    if isinstance(data, Mapping) and isinstance(data.get("qrels"), list):
        for index, item in enumerate(data["qrels"]):
            if not isinstance(item, Mapping):
                raise ValidationError("qrels entries must be objects")
            raw_qrels.extend(_expand_qrel_item(item, index=index))
    elif isinstance(data, Mapping):
        index = 0
        for query_id, value in data.items():
            if query_id in {"version", "schema", "metadata"}:
                continue
            if isinstance(value, Mapping):
                for target, relevance in value.items():
                    raw_qrels.append(
                        {
                            "query_id": str(query_id),
                            "target": str(target),
                            "relevance": relevance,
                            "field": "document",
                        }
                    )
                    index += 1
            elif isinstance(value, list):
                for target in value:
                    raw_qrels.append(
                        {
                            "query_id": str(query_id),
                            "target": str(target),
                            "relevance": 1,
                            "field": "document",
                        }
                    )
                    index += 1
            else:
                raise ValidationError(f"qrels[{query_id}] must be an object or list")
    elif isinstance(data, list):
        for index, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise ValidationError("qrels entries must be objects")
            raw_qrels.extend(_expand_qrel_item(item, index=index))
    else:
        raise ValidationError("qrels must be an object or list")

    if not raw_qrels:
        raise ValidationError("qrels must contain at least one judged target")

    grouped: dict[str, list[BenchmarkQrel]] = {}
    for index, raw in enumerate(raw_qrels):
        qrel = BenchmarkQrel.from_dict(raw, index=index)
        if qrel.relevance > 0:
            grouped.setdefault(qrel.query_id, []).append(qrel)
    if not grouped:
        raise ValidationError("qrels must contain at least one positive relevance judgment")
    return grouped


def load_benchmark_gate(path: str | Path) -> BenchmarkGate:
    """Load benchmark threshold config."""

    gate_path = Path(path)
    try:
        data = json.loads(gate_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"gate config not found: {gate_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"gate config is not valid JSON: {gate_path}") from exc
    if not isinstance(data, Mapping):
        raise ValidationError("gate config must be a JSON object")
    return BenchmarkGate.from_dict(data)


def load_chunk_snapshot(path: str | Path) -> dict[str, Any]:
    """Load a chunk snapshot artifact used for strict chunk recall."""

    snapshot_path = Path(path)
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"chunk snapshot not found: {snapshot_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"chunk snapshot is not valid JSON: {snapshot_path}") from exc
    if not isinstance(data, Mapping):
        raise ValidationError("chunk snapshot must be a JSON object")
    if data.get("schema") != CHUNK_SNAPSHOT_SCHEMA:
        raise ValidationError(f"chunk snapshot schema must be {CHUNK_SNAPSHOT_SCHEMA}")
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        raise ValidationError("chunk snapshot chunks must be a list")
    return dict(data)


def load_benchmark_baseline(path: str | Path) -> dict[str, float]:
    """Load benchmark metrics from a previous validation report JSON."""

    baseline_path = Path(path)
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"baseline report not found: {baseline_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"baseline report is not valid JSON: {baseline_path}") from exc
    if not isinstance(data, Mapping):
        raise ValidationError("baseline report must be a JSON object")

    raw_metrics: Any = None
    benchmark = data.get("benchmark")
    if isinstance(benchmark, Mapping):
        raw_metrics = benchmark.get("metrics")
    if raw_metrics is None:
        raw_metrics = data.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        raise ValidationError("baseline report does not contain benchmark metrics")

    metrics: dict[str, float] = {}
    for key, value in raw_metrics.items():
        if isinstance(value, (int, float)):
            metrics[str(key)] = float(value)
    if not metrics:
        raise ValidationError("baseline report does not contain supported benchmark metrics")
    return metrics


def smoke_query(question: str | None, *, dataset_name: str) -> ValidationQuery:
    """Create the default smoke validation query."""

    return ValidationQuery(
        id="smoke",
        question=question or f"Summarize {dataset_name}",
        min_chunks=1,
    )


def _joined_chunk_text(chunks: list[NormalizedChunk]) -> str:
    values = []
    for chunk in chunks:
        values.extend(
            [
                chunk.content or "",
                chunk.document_name or "",
                chunk.document_id or "",
                " ".join(chunk.important_keywords),
            ]
        )
    return "\n".join(values).lower()


def _document_text(chunks: list[NormalizedChunk]) -> str:
    return "\n".join(
        value.lower()
        for chunk in chunks
        for value in (chunk.document_name, chunk.document_id)
        if value
    )


def evaluate_query_result(query: ValidationQuery, chunks: list[NormalizedChunk]) -> ValidationCaseResult:
    """Evaluate normalized chunks against one validation query."""

    joined_text = _joined_chunk_text(chunks)
    doc_text = _document_text(chunks)
    term_hits = [term for term in query.expected_terms if term.lower() in joined_text]
    missing_terms = [term for term in query.expected_terms if term.lower() not in joined_text]
    document_hits = [doc for doc in query.expected_documents if doc.lower() in doc_text]
    missing_documents = [doc for doc in query.expected_documents if doc.lower() not in doc_text]
    passed = (
        len(chunks) >= query.min_chunks
        and not missing_terms
        and not missing_documents
    )
    return ValidationCaseResult(
        query=query,
        passed=passed,
        chunk_count=len(chunks),
        term_hits=term_hits,
        missing_terms=missing_terms,
        document_hits=document_hits,
        missing_documents=missing_documents,
        chunks=chunks,
    )


def _normalize_match_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _target_matches(candidate: str | None, target: str) -> bool:
    candidate_norm = _normalize_match_text(candidate)
    target_norm = _normalize_match_text(target)
    return bool(candidate_norm and target_norm and (candidate_norm == target_norm or target_norm in candidate_norm))


def _chunk_reference_variants(value: str | None) -> set[str]:
    normalized = _normalize_match_text(value)
    if not normalized:
        return set()
    variants = {normalized}
    if normalized.startswith("sha256:"):
        variants.add(normalized.removeprefix("sha256:"))
    elif len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized):
        variants.add(f"sha256:{normalized}")
    return variants


def _chunk_tokens(chunk: NormalizedChunk) -> set[str]:
    tokens = set()
    tokens.update(_chunk_reference_variants(chunk.chunk_id))
    tokens.update(_chunk_reference_variants(stable_chunk_hash(chunk)))
    return tokens


def _snapshot_alias_index(chunk_snapshot: Mapping[str, Any] | None) -> dict[str, set[str]]:
    if not chunk_snapshot:
        return {}
    chunks = chunk_snapshot.get("chunks") if isinstance(chunk_snapshot, Mapping) else None
    if not isinstance(chunks, list):
        return {}

    index: dict[str, set[str]] = {}
    for item in chunks:
        if not isinstance(item, Mapping):
            continue
        aliases: set[str] = set()
        for key in ("stable_hash", "content_sha256", "chunk_id", "source_chunk_id"):
            value = item.get(key)
            if isinstance(value, str):
                aliases.update(_chunk_reference_variants(value))
        raw_aliases = item.get("aliases")
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if isinstance(alias, str):
                    aliases.update(_chunk_reference_variants(alias))
        for alias in list(aliases):
            aliases.update(index.get(alias, set()))
        for alias in aliases:
            index[alias] = set(aliases)
    return index


def _snapshot_chunk_text(item: Mapping[str, Any]) -> str:
    for key in ("content", "content_preview", "text", "page_content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _snapshot_chunk_aliases(item: Mapping[str, Any], chunk: NormalizedChunk) -> set[str]:
    aliases: set[str] = set()
    for key in ("stable_hash", "content_sha256", "chunk_id", "source_chunk_id", "id"):
        value = item.get(key)
        if isinstance(value, str):
            aliases.update(_chunk_reference_variants(value))
    raw_aliases = item.get("aliases")
    if isinstance(raw_aliases, list):
        for alias in raw_aliases:
            if isinstance(alias, str):
                aliases.update(_chunk_reference_variants(alias))
    aliases.update(_chunk_tokens(chunk))
    return aliases


def _snapshot_chunk_key(aliases: set[str]) -> str:
    prefixed = sorted(alias for alias in aliases if alias.startswith("sha256:"))
    if prefixed:
        return prefixed[0]
    return sorted(aliases)[0] if aliases else ""


def _candidate_snapshot_chunks(chunk_snapshot: Mapping[str, Any] | None) -> list[tuple[str, set[str], NormalizedChunk]]:
    if not chunk_snapshot:
        return []
    raw_chunks = chunk_snapshot.get("chunks") if isinstance(chunk_snapshot, Mapping) else None
    if not isinstance(raw_chunks, list):
        return []

    chunks: list[tuple[str, set[str], NormalizedChunk]] = []
    for item in raw_chunks:
        if not isinstance(item, Mapping):
            continue
        text = _snapshot_chunk_text(item)
        if not text:
            continue
        chunk = NormalizedChunk(
            content=text,
            document_name=item.get("document_name") if isinstance(item.get("document_name"), str) else None,
            document_id=item.get("document_id") if isinstance(item.get("document_id"), str) else None,
            dataset_id=item.get("dataset_id") if isinstance(item.get("dataset_id"), str) else None,
            chunk_id=item.get("chunk_id") if isinstance(item.get("chunk_id"), str) else None,
            raw=dict(item),
        )
        aliases = _snapshot_chunk_aliases(item, chunk)
        key = _snapshot_chunk_key(aliases)
        if key:
            chunks.append((key, aliases, chunk))
    return chunks


def _expected_chunk_aliases(qrel: BenchmarkQrel, snapshot_index: Mapping[str, set[str]]) -> set[str]:
    aliases = _chunk_reference_variants(qrel.target)
    for alias in list(aliases):
        aliases.update(snapshot_index.get(alias, set()))
    return aliases


def _expected_chunk_key(qrel: BenchmarkQrel, snapshot_index: Mapping[str, set[str]]) -> str:
    aliases = _expected_chunk_aliases(qrel, snapshot_index)
    prefixed = sorted(alias for alias in aliases if alias.startswith("sha256:"))
    if prefixed:
        return prefixed[0]
    return sorted(aliases)[0] if aliases else qrel.key


def _expected_chunk_match_key(
    chunk: NormalizedChunk,
    expected_qrels: list[BenchmarkQrel],
    snapshot_index: Mapping[str, set[str]],
) -> str | None:
    tokens = _chunk_tokens(chunk)
    for qrel in expected_qrels:
        aliases = _expected_chunk_aliases(qrel, snapshot_index)
        if tokens & aliases:
            return _expected_chunk_key(qrel, snapshot_index)
    return None


def _is_expected_chunk_qrel(qrel: BenchmarkQrel) -> bool:
    return qrel.field in {"expected_chunk", "chunk_hash", "chunk_id"}


def _qrel_matches_chunk(
    qrel: BenchmarkQrel,
    chunk: NormalizedChunk,
    snapshot_index: Mapping[str, set[str]] | None = None,
) -> bool:
    if qrel.field == "chunk_id":
        return _target_matches(chunk.chunk_id, qrel.target)
    if qrel.field in {"chunk_hash", "expected_chunk"}:
        return bool(_chunk_tokens(chunk) & _expected_chunk_aliases(qrel, snapshot_index or {}))
    if qrel.field == "document_id":
        return _target_matches(chunk.document_id, qrel.target)
    if qrel.field == "document_name":
        return _target_matches(chunk.document_name, qrel.target)
    if qrel.field == "content":
        return _target_matches(chunk.content, qrel.target)
    return (
        _target_matches(chunk.document_name, qrel.target)
        or _target_matches(chunk.document_id, qrel.target)
        or _target_matches(chunk.chunk_id, qrel.target)
    )


def _best_matching_qrel(
    chunk: NormalizedChunk,
    qrels: list[BenchmarkQrel],
    snapshot_index: Mapping[str, set[str]] | None = None,
) -> BenchmarkQrel | None:
    matches = [
        qrel
        for qrel in qrels
        if qrel.relevance > 0 and _qrel_matches_chunk(qrel, chunk, snapshot_index=snapshot_index)
    ]
    if not matches:
        return None
    return max(matches, key=lambda qrel: qrel.relevance)


def _dcg(relevances: list[float]) -> float:
    return sum((2**relevance - 1) / math.log2(rank + 2) for rank, relevance in enumerate(relevances))


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _query_type(query: ValidationQuery) -> str:
    value = query.metadata.get("type") or query.metadata.get("query_type") or "default"
    return str(value) if str(value).strip() else "default"


def _qrel_metadata_with_multimodal_extensions(
    item: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    enriched = dict(metadata)
    for key in ("expected_modality", "expected_modalities", "modality"):
        if key in item and key not in enriched:
            enriched[key] = item[key]
    for key in ("benchmark_category", "category", "modality_category", "query_category"):
        if key in item and "benchmark_category" not in enriched:
            enriched["benchmark_category"] = item[key]
            break
    return enriched


def _metadata_values(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> list[Any]:
    values: list[Any] = []
    for key in keys:
        if key in metadata:
            values.append(metadata[key])
    return values


def _normalize_multimodal_category(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")
    aliases = {
        "fact": "text_fact",
        "text": "text_fact",
        "textual": "text_fact",
        "text_fact": "text_fact",
        "table": "table_value",
        "table_value": "table_value",
        "table_row": "table_value",
        "numeric_row": "table_value",
        "visual": "visual_identification",
        "image": "visual_identification",
        "visual_identification": "visual_identification",
        "diagram": "diagram_software_screenshot",
        "screenshot": "diagram_software_screenshot",
        "software_screenshot": "diagram_software_screenshot",
        "diagram_software_screenshot": "diagram_software_screenshot",
        "caption": "caption_context",
        "context": "caption_context",
        "caption_context": "caption_context",
        "mixed": "mixed_table_plus_image",
        "mixed_modality": "mixed_table_plus_image",
        "mixed_table_image": "mixed_table_plus_image",
        "mixed_table_plus_image": "mixed_table_plus_image",
    }
    return aliases.get(normalized)


def _category_implied_modalities(category: str | None) -> set[str]:
    if category == "table_value":
        return {"table"}
    if category in {"visual_identification", "diagram_software_screenshot"}:
        return {"image"}
    if category == "mixed_table_plus_image":
        return {"mixed", "table", "image"}
    if category in {"text_fact", "caption_context"}:
        return {"text"}
    return set()


def _query_multimodal_category(query: ValidationQuery, qrels: list[BenchmarkQrel]) -> str | None:
    for value in _metadata_values(
        query.metadata,
        ("benchmark_category", "category", "modality_category", "type", "query_type"),
    ):
        category = _normalize_multimodal_category(value)
        if category:
            return category
    for qrel in qrels:
        for value in _metadata_values(
            qrel.metadata,
            ("benchmark_category", "category", "modality_category", "type", "query_type"),
        ):
            category = _normalize_multimodal_category(value)
            if category:
                return category
    return None


def _normalize_modality(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if "mixed" in normalized or "multimodal" in normalized:
        return "mixed"
    if text.startswith("image/") or any(token in normalized for token in ("image", "visual", "figure", "diagram", "screenshot")):
        return "image"
    if "table" in normalized:
        return "table"
    if text.startswith("text/") or normalized in {"text", "markdown", "md", "txt", "document"}:
        return "text"
    if normalized in MULTIMODAL_EXPECTED_MODALITIES:
        return normalized
    return None


def _modalities_from_value(value: Any) -> set[str]:
    if isinstance(value, str):
        modality = _normalize_modality(value)
        if modality == "mixed":
            return {"mixed", "table", "image"}
        return {modality} if modality else set()
    if isinstance(value, (list, tuple, set)):
        modalities: set[str] = set()
        for item in value:
            modalities.update(_modalities_from_value(item))
        return modalities
    return set()


def _metadata_expected_modalities(metadata: Mapping[str, Any]) -> set[str]:
    modalities: set[str] = set()
    for value in _metadata_values(metadata, ("expected_modality", "expected_modalities", "modality", "modalities")):
        modalities.update(_modalities_from_value(value))
    if not modalities:
        for value in _metadata_values(metadata, ("benchmark_category", "category", "modality_category", "type", "query_type")):
            modalities.update(_category_implied_modalities(_normalize_multimodal_category(value)))
    return modalities


def _query_expected_modalities(query: ValidationQuery, qrels: list[BenchmarkQrel]) -> set[str]:
    modalities = _metadata_expected_modalities(query.metadata)
    for qrel in qrels:
        modalities.update(_metadata_expected_modalities(qrel.metadata))
    if not modalities:
        modalities.update(_category_implied_modalities(_query_multimodal_category(query, qrels)))
    return modalities


def _mapping_modality(mapping: Mapping[str, Any]) -> str | None:
    for key in (
        "modality",
        "chunk_modality",
        "document_modality",
        "expected_modality",
        "media_type",
        "asset_type",
        "document_type",
        "doc_type",
        "mime_type",
        "content_type",
        "type",
    ):
        modality = _normalize_modality(mapping.get(key))
        if modality:
            return modality
    return None


def _chunk_modality(chunk: NormalizedChunk) -> str:
    raw = chunk.raw if isinstance(chunk.raw, Mapping) else {}
    modality = _mapping_modality(raw)
    if modality:
        return modality
    metadata = raw.get("metadata")
    if isinstance(metadata, Mapping):
        modality = _mapping_modality(metadata)
        if modality:
            return modality
    document_name = (chunk.document_name or "").casefold()
    if document_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")):
        return "image"
    if "<table" in (chunk.content or "").casefold():
        return "table"
    if document_name.endswith((".md", ".markdown", ".txt")):
        return "text"
    return "unknown"


def _modality_distribution(chunks: list[NormalizedChunk]) -> dict[str, int]:
    counts = Counter(_chunk_modality(chunk) for chunk in chunks)
    return {key: counts[key] for key in sorted(counts) if counts[key]}


def _iter_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Mapping):
        for key in ("name", "tag", "tag_name", "label", "value", "id", "tag_id"):
            if key in value:
                values = _iter_string_values(value[key])
                if values:
                    return values
        return []
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_iter_string_values(item))
        return values
    return []


def _normalized_labels_from(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> set[str]:
    labels: set[str] = set()
    for key in keys:
        for value in _iter_string_values(mapping.get(key)):
            normalized = value.strip().casefold()
            if normalized:
                labels.add(normalized)
    return labels


TAG_KEYS = ("tags", "tag", "tag_ids", "tag_id", "tag_names", "tag_name", "tag_kb_ids", "tag_kb_id")
EXPECTED_TAG_KEYS = ("expected_tags", "required_tags", "must_have_tags", "tags", "tag", "tag_ids", "tag_id")
ALLOWED_TAG_KEYS = (
    "allowed_tags",
    "allow_tags",
    "expected_tags",
    "required_tags",
    "must_have_tags",
    "tags",
    "tag",
    "tag_ids",
    "tag_id",
)


def _tag_scope_from_metadata(metadata: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    expected = _normalized_labels_from(metadata, EXPECTED_TAG_KEYS)
    allowed = _normalized_labels_from(metadata, ALLOWED_TAG_KEYS)
    allowed.update(expected)
    return expected, allowed


def _query_tag_scope(query: ValidationQuery, qrels: list[BenchmarkQrel]) -> tuple[set[str], set[str]]:
    expected, allowed = _tag_scope_from_metadata(query.metadata)
    for qrel in qrels:
        qrel_expected, qrel_allowed = _tag_scope_from_metadata(qrel.metadata)
        expected.update(qrel_expected)
        allowed.update(qrel_allowed)
    return expected, allowed


def _chunk_tags(chunk: NormalizedChunk) -> set[str]:
    tags = _normalized_labels_from(chunk.raw, TAG_KEYS)
    metadata = chunk.raw.get("metadata") if isinstance(chunk.raw, Mapping) else None
    if isinstance(metadata, Mapping):
        tags.update(_normalized_labels_from(metadata, TAG_KEYS))
    return tags


def _is_document_qrel(qrel: BenchmarkQrel) -> bool:
    return qrel.field in {"document", "document_name", "document_id"}


def _document_qrel_matches_chunk(qrel: BenchmarkQrel, chunk: NormalizedChunk) -> bool:
    if qrel.field == "document_id":
        return _target_matches(chunk.document_id, qrel.target)
    if qrel.field == "document_name":
        return _target_matches(chunk.document_name, qrel.target)
    return _target_matches(chunk.document_name, qrel.target) or _target_matches(chunk.document_id, qrel.target)


def _query_expected_document_matches_chunk(query: ValidationQuery, chunk: NormalizedChunk) -> bool:
    return any(
        _target_matches(chunk.document_name, document) or _target_matches(chunk.document_id, document)
        for document in query.expected_documents
    )


def _chunk_has_document_identity(chunk: NormalizedChunk) -> bool:
    return bool(chunk.document_name or chunk.document_id)


def _document_pollution_metrics(
    case: ValidationCaseResult,
    qrels: list[BenchmarkQrel],
    ranked_chunks: list[NormalizedChunk],
) -> dict[str, float | int]:
    document_qrels = [qrel for qrel in qrels if qrel.relevance > 0 and _is_document_qrel(qrel)]
    if not document_qrels and not case.query.expected_documents:
        return {}

    scored_chunks = [chunk for chunk in ranked_chunks if _chunk_has_document_identity(chunk)]
    wrong_document_count = 0
    for chunk in scored_chunks:
        if _query_expected_document_matches_chunk(case.query, chunk):
            continue
        if any(_document_qrel_matches_chunk(qrel, chunk) for qrel in document_qrels):
            continue
        wrong_document_count += 1

    return {
        "wrong_document_rate": wrong_document_count / len(scored_chunks) if scored_chunks else 0.0,
        "document_scored_chunk_count": len(scored_chunks),
        "wrong_document_count": wrong_document_count,
    }


def _tag_pollution_metrics(
    case: ValidationCaseResult,
    qrels: list[BenchmarkQrel],
    ranked_chunks: list[NormalizedChunk],
) -> dict[str, float | int]:
    expected_tags, allowed_tags = _query_tag_scope(case.query, qrels)
    if not expected_tags and not allowed_tags:
        return {}

    chunk_tag_sets = [_chunk_tags(chunk) for chunk in ranked_chunks]
    tagged_chunks = [tags for tags in chunk_tag_sets if tags]
    retrieved_tags = set().union(*tagged_chunks) if tagged_chunks else set()
    unexpected_tags = retrieved_tags - allowed_tags

    metrics: dict[str, float | int] = {}
    if expected_tags:
        matched_expected_tags = retrieved_tags & expected_tags
        metrics.update(
            {
                "expected_tag_hit_rate": len(matched_expected_tags) / len(expected_tags),
                "expected_tag_count": len(expected_tags),
                "matched_expected_tags": len(matched_expected_tags),
            }
        )
    if allowed_tags:
        polluted_chunks = [tags for tags in tagged_chunks if tags - allowed_tags]
        metrics.update(
            {
                "tag_pollution_rate": len(polluted_chunks) / len(tagged_chunks) if tagged_chunks else 0.0,
                "unexpected_tag_hit_rate": 1.0 if unexpected_tags else 0.0,
                "tagged_chunk_count": len(tagged_chunks),
                "polluted_tagged_chunk_count": len(polluted_chunks),
                "unexpected_tag_count": len(unexpected_tags),
            }
        )
    return metrics


def _benchmark_expected_term_hits(expected_terms: list[str], chunks: list[NormalizedChunk]) -> list[str]:
    joined_text = re.sub(r"\s+", " ", _joined_chunk_text(chunks)).strip()
    hits: list[str] = []
    for term in expected_terms:
        normalized = re.sub(r"\s+", " ", term.strip().casefold()).strip()
        if normalized and normalized in joined_text:
            hits.append(term)
    return hits


def _query_expected_term_metrics(
    case: ValidationCaseResult,
    ranked_chunks: list[NormalizedChunk],
    *,
    expected_modalities: set[str],
) -> dict[str, float | int]:
    expected_terms = [term for term in case.query.expected_terms if term.strip()]
    if not expected_terms:
        return {}

    matched_terms = _benchmark_expected_term_hits(expected_terms, ranked_chunks)
    expected_count = len(expected_terms)
    matched_count = len(matched_terms)
    recall = matched_count / expected_count
    hit_rate = 1.0 if matched_count == expected_count else 0.0
    metrics: dict[str, float | int] = {
        "expected_term_recall_at_k": recall,
        "expected_term_hit_rate": hit_rate,
        "expected_term_count": expected_count,
        "matched_expected_terms": matched_count,
    }
    if "table" in expected_modalities:
        metrics.update(
            {
                "table_term_recall_at_k": recall,
                "table_term_hit_rate": hit_rate,
                "table_expected_term_count": expected_count,
                "matched_table_expected_terms": matched_count,
            }
        )
    return metrics


def _candidate_snapshot_expected_chunk_metrics(
    case: ValidationCaseResult,
    ranked_chunks: list[NormalizedChunk],
    *,
    expected_chunk_qrels: list[BenchmarkQrel],
    chunk_snapshot: Mapping[str, Any] | None,
) -> dict[str, float | int]:
    expected_terms = [term for term in case.query.expected_terms if term.strip()]
    if not expected_terms or not expected_chunk_qrels:
        return {}

    candidate_chunks = _candidate_snapshot_chunks(chunk_snapshot)
    if not candidate_chunks:
        return {}

    expected_candidate_chunks: list[tuple[str, set[str], set[str]]] = []
    mapped_terms: set[str] = set()
    for key, aliases, chunk in candidate_chunks:
        term_hits = set(_benchmark_expected_term_hits(expected_terms, [chunk]))
        if not term_hits:
            continue
        expected_candidate_chunks.append((key, aliases, term_hits))
        mapped_terms.update(term_hits)

    if not expected_candidate_chunks:
        return {}

    ranked_token_sets = [_chunk_tokens(chunk) for chunk in ranked_chunks]
    matched_candidate_chunks: set[str] = set()
    matched_terms: set[str] = set()
    for key, aliases, term_hits in expected_candidate_chunks:
        if not any(tokens & aliases for tokens in ranked_token_sets):
            continue
        matched_candidate_chunks.add(key)
        matched_terms.update(term_hits)

    candidate_count = len(expected_candidate_chunks)
    matched_count = len(matched_candidate_chunks)
    return {
        "candidate_snapshot_expected_chunk_recall_at_k": matched_count / candidate_count,
        "candidate_snapshot_expected_chunk_hit_rate": 1.0 if matched_count == candidate_count else 0.0,
        "candidate_snapshot_expected_chunk_count": candidate_count,
        "matched_candidate_snapshot_expected_chunks": matched_count,
        "candidate_snapshot_expected_term_count": len(mapped_terms),
        "matched_candidate_snapshot_expected_terms": len(matched_terms),
    }


def _query_benchmark_metrics(
    case: ValidationCaseResult,
    qrels: list[BenchmarkQrel],
    *,
    cutoff: int,
    snapshot_index: Mapping[str, set[str]],
    chunk_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if cutoff <= 0:
        raise ValidationError("benchmark cutoff must be positive")
    positive_qrels = [qrel for qrel in qrels if qrel.relevance > 0]
    ranking_qrels = [qrel for qrel in positive_qrels if not _is_expected_chunk_qrel(qrel)] or positive_qrels
    relevant_keys = {qrel.key for qrel in ranking_qrels}
    if not relevant_keys:
        raise ValidationError(f"query {case.query.id!r} has no positive qrels")

    ranked_chunks = case.chunks[:cutoff]
    result_modality_distribution = _modality_distribution(ranked_chunks)
    expected_modalities = _query_expected_modalities(case.query, positive_qrels)
    multimodal_category = _query_multimodal_category(case.query, positive_qrels)
    rel_by_rank: list[float] = []
    matched_targets: list[str | None] = []
    for chunk in ranked_chunks:
        match = _best_matching_qrel(chunk, ranking_qrels, snapshot_index=snapshot_index)
        rel_by_rank.append(match.relevance if match else 0.0)
        matched_targets.append(match.key if match else None)

    relevant_retrieved = sum(1 for relevance in rel_by_rank if relevance > 0)
    first_relevant_rank = next(
        (index + 1 for index, relevance in enumerate(rel_by_rank) if relevance > 0),
        None,
    )

    unique_hits: set[str] = set()
    precision_sum = 0.0
    unique_hits_so_far = 0
    for index, target in enumerate(matched_targets, start=1):
        if target is None or target in unique_hits:
            continue
        unique_hits.add(target)
        unique_hits_so_far += 1
        precision_sum += unique_hits_so_far / index

    ideal_relevances = sorted((qrel.relevance for qrel in ranking_qrels), reverse=True)[:cutoff]
    dcg = _dcg(rel_by_rank)
    idcg = _dcg(ideal_relevances)
    recall = len(unique_hits) / len(relevant_keys)
    expected_chunk_qrels = [qrel for qrel in positive_qrels if _is_expected_chunk_qrel(qrel)]
    expected_chunk_keys = {
        _expected_chunk_key(qrel, snapshot_index)
        for qrel in expected_chunk_qrels
    }
    matched_expected_chunks: set[str] = set()
    first_expected_rank = None
    for index, chunk in enumerate(ranked_chunks, start=1):
        match_key = _expected_chunk_match_key(chunk, expected_chunk_qrels, snapshot_index)
        if not match_key:
            continue
        matched_expected_chunks.add(match_key)
        if first_expected_rank is None:
            first_expected_rank = index

    strict_metrics: dict[str, float | int] = {}
    if expected_chunk_keys:
        strict_metrics = {
            "strict_chunk_recall_at_k": len(matched_expected_chunks) / len(expected_chunk_keys),
            "expected_chunk_hit_rate": 1.0 if matched_expected_chunks else 0.0,
            "expected_evidence_rank": float(first_expected_rank or cutoff + 1),
            "expected_chunk_count": len(expected_chunk_keys),
            "matched_expected_chunks": len(matched_expected_chunks),
        }
    document_metrics = _document_pollution_metrics(case, positive_qrels, ranked_chunks)
    tag_metrics = _tag_pollution_metrics(case, positive_qrels, ranked_chunks)
    expected_term_metrics = _query_expected_term_metrics(
        case,
        ranked_chunks,
        expected_modalities=expected_modalities,
    )
    candidate_snapshot_metrics = _candidate_snapshot_expected_chunk_metrics(
        case,
        ranked_chunks,
        expected_chunk_qrels=expected_chunk_qrels,
        chunk_snapshot=chunk_snapshot,
    )
    multimodal_metrics = _query_multimodal_metrics(
        expected_modalities=expected_modalities,
        qrels=ranking_qrels,
        ranked_chunks=ranked_chunks,
        matched_targets=matched_targets,
        result_modality_distribution=result_modality_distribution,
        cutoff=cutoff,
    )

    return {
        "id": case.query.id,
        "query_type": _query_type(case.query),
        "multimodal_category": multimodal_category or "uncategorized",
        "expected_modalities": sorted(expected_modalities),
        "result_modality_distribution": result_modality_distribution,
        "hit_rate": 1.0 if first_relevant_rank else 0.0,
        "mrr": 1.0 / first_relevant_rank if first_relevant_rank else 0.0,
        "precision_at_k": relevant_retrieved / cutoff,
        "recall_at_k": recall,
        "ndcg_at_k": dcg / idcg if idcg else 0.0,
        "map_at_k": precision_sum / len(relevant_keys),
        "empty_result_rate": 1.0 if not case.chunks else 0.0,
        "supporting_document_coverage": recall,
        "relevant_targets": len(relevant_keys),
        "matched_targets": len(unique_hits),
        "first_relevant_rank": first_relevant_rank,
        **strict_metrics,
        **candidate_snapshot_metrics,
        **expected_term_metrics,
        **document_metrics,
        **tag_metrics,
        **multimodal_metrics,
    }


def _modality_relevant_keys(qrels: list[BenchmarkQrel], modality: str) -> set[str]:
    keys = {
        qrel.key
        for qrel in qrels
        if qrel.relevance > 0 and modality in _metadata_expected_modalities(qrel.metadata)
    }
    return keys


def _query_modality_recall(
    *,
    modality: str,
    expected_modalities: set[str],
    qrels: list[BenchmarkQrel],
    ranked_chunks: list[NormalizedChunk],
    matched_targets: list[str | None],
) -> tuple[float | None, int, int]:
    if modality not in expected_modalities:
        return None, 0, 0
    relevant_keys = _modality_relevant_keys(qrels, modality) or {qrel.key for qrel in qrels if qrel.relevance > 0}
    matched_keys = {
        target
        for chunk, target in zip(ranked_chunks, matched_targets)
        if target in relevant_keys and _chunk_modality(chunk) == modality
    }
    return (
        len(matched_keys) / len(relevant_keys) if relevant_keys else 0.0,
        len(matched_keys),
        len(relevant_keys),
    )


def _query_multimodal_metrics(
    *,
    expected_modalities: set[str],
    qrels: list[BenchmarkQrel],
    ranked_chunks: list[NormalizedChunk],
    matched_targets: list[str | None],
    result_modality_distribution: Mapping[str, int],
    cutoff: int,
) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}
    image_recall, matched_image_targets, image_relevant_targets = _query_modality_recall(
        modality="image",
        expected_modalities=expected_modalities,
        qrels=qrels,
        ranked_chunks=ranked_chunks,
        matched_targets=matched_targets,
    )
    if image_recall is not None:
        metrics.update(
            {
                "image_precision_at_k": matched_image_targets / cutoff,
                "image_recall_at_k": image_recall,
                "image_recall": image_recall,
                "visual_coverage": 1.0 if result_modality_distribution.get("image", 0) else 0.0,
                "image_result_count": int(result_modality_distribution.get("image", 0)),
                "image_relevant_targets": image_relevant_targets,
                "matched_image_targets": matched_image_targets,
            }
        )

    table_recall, matched_table_targets, table_relevant_targets = _query_modality_recall(
        modality="table",
        expected_modalities=expected_modalities,
        qrels=qrels,
        ranked_chunks=ranked_chunks,
        matched_targets=matched_targets,
    )
    if table_recall is not None:
        metrics.update(
            {
                "table_recall_at_k": table_recall,
                "table_recall": table_recall,
                "table_result_count": int(result_modality_distribution.get("table", 0)),
                "table_relevant_targets": table_relevant_targets,
                "matched_table_targets": matched_table_targets,
            }
        )
    return metrics


def _aggregate_query_metrics(per_query: list[dict[str, Any]]) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {"query_count": len(per_query)}
    for key in METRIC_KEYS:
        metrics[key] = _average([float(item[key]) for item in per_query])
    for key in STRICT_CHUNK_METRIC_KEYS + CANDIDATE_SNAPSHOT_METRIC_KEYS + EXPECTED_TERM_METRIC_KEYS + POLLUTION_METRIC_KEYS:
        values = [float(item[key]) for item in per_query if isinstance(item.get(key), (int, float))]
        if values:
            metrics[key] = _average(values)
            if key == "expected_term_recall_at_k":
                metrics["expected_term_query_count"] = len(values)
            elif key == "candidate_snapshot_expected_chunk_recall_at_k":
                metrics["candidate_snapshot_expected_chunk_query_count"] = len(values)
            elif key == "table_term_recall_at_k":
                metrics["table_term_query_count"] = len(values)
            elif key == "wrong_document_rate":
                metrics["document_scope_query_count"] = len(values)
            elif key == "tag_pollution_rate":
                metrics["tag_scope_query_count"] = len(values)
            elif key == "expected_tag_hit_rate":
                metrics["expected_tag_query_count"] = len(values)
    image_values = [float(item["image_precision_at_k"]) for item in per_query if isinstance(item.get("image_precision_at_k"), (int, float))]
    if image_values:
        metrics["image_scope_query_count"] = len(image_values)
        metrics["image_precision_at_k"] = _average(image_values)
        image_recall_values = [
            float(item["image_recall_at_k"])
            for item in per_query
            if isinstance(item.get("image_recall_at_k"), (int, float))
        ]
        visual_coverage_values = [
            float(item["visual_coverage"])
            for item in per_query
            if isinstance(item.get("visual_coverage"), (int, float))
        ]
        metrics["image_recall_at_k"] = _average(image_recall_values)
        metrics["image_recall"] = metrics["image_recall_at_k"]
        metrics["visual_coverage_rate"] = _average(visual_coverage_values)
    table_values = [float(item["table_recall_at_k"]) for item in per_query if isinstance(item.get("table_recall_at_k"), (int, float))]
    if table_values:
        metrics["table_scope_query_count"] = len(table_values)
        metrics["table_recall_at_k"] = _average(table_values)
        metrics["table_recall"] = metrics["table_recall_at_k"]
    expected_chunk_counts = [
        int(item["expected_chunk_count"])
        for item in per_query
        if isinstance(item.get("expected_chunk_count"), int)
    ]
    if expected_chunk_counts:
        metrics["expected_chunk_query_count"] = len(expected_chunk_counts)
        metrics["expected_chunk_count"] = sum(expected_chunk_counts)
        metrics["matched_expected_chunks"] = sum(
            int(item.get("matched_expected_chunks", 0))
            for item in per_query
            if isinstance(item.get("expected_chunk_count"), int)
        )
    candidate_snapshot_counts = [
        int(item["candidate_snapshot_expected_chunk_count"])
        for item in per_query
        if isinstance(item.get("candidate_snapshot_expected_chunk_count"), int)
    ]
    if candidate_snapshot_counts:
        metrics["candidate_snapshot_expected_chunk_count"] = sum(candidate_snapshot_counts)
        metrics["matched_candidate_snapshot_expected_chunks"] = sum(
            int(item.get("matched_candidate_snapshot_expected_chunks", 0))
            for item in per_query
            if isinstance(item.get("candidate_snapshot_expected_chunk_count"), int)
        )
    for key in (
        "document_scored_chunk_count",
        "wrong_document_count",
        "expected_tag_count",
        "matched_expected_tags",
        "expected_term_count",
        "matched_expected_terms",
        "candidate_snapshot_expected_term_count",
        "matched_candidate_snapshot_expected_terms",
        "table_expected_term_count",
        "matched_table_expected_terms",
        "tagged_chunk_count",
        "polluted_tagged_chunk_count",
        "unexpected_tag_count",
        "image_result_count",
        "image_relevant_targets",
        "matched_image_targets",
        "table_result_count",
        "table_relevant_targets",
        "matched_table_targets",
    ):
        values = [int(item[key]) for item in per_query if isinstance(item.get(key), int)]
        if values:
            metrics[key] = sum(values)
    return metrics


def _multimodal_summary(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts: Counter[str] = Counter()
    expected_modality_counts: Counter[str] = Counter()
    result_counts: Counter[str] = Counter()
    categorized_query_count = 0
    expected_modality_query_count = 0

    for item in per_query:
        category = item.get("multimodal_category")
        if isinstance(category, str) and category != "uncategorized":
            category_counts[category] += 1
            categorized_query_count += 1
        expected_modalities = item.get("expected_modalities")
        if isinstance(expected_modalities, list) and expected_modalities:
            expected_modality_query_count += 1
            for modality in expected_modalities:
                if isinstance(modality, str):
                    expected_modality_counts[modality] += 1
        distribution = item.get("result_modality_distribution")
        if isinstance(distribution, Mapping):
            for modality, count in distribution.items():
                if isinstance(modality, str) and isinstance(count, int):
                    result_counts[modality] += count

    return {
        "schema": MULTIMODAL_BENCHMARK_SCHEMA,
        "allowed_categories": list(MULTIMODAL_BENCHMARK_CATEGORIES),
        "allowed_modalities": list(MULTIMODAL_EXPECTED_MODALITIES),
        "query_count": len(per_query),
        "categorized_query_count": categorized_query_count,
        "expected_modality_query_count": expected_modality_query_count,
        "category_counts": {key: category_counts[key] for key in sorted(category_counts) if category_counts[key]},
        "expected_modality_counts": {
            key: expected_modality_counts[key]
            for key in sorted(expected_modality_counts)
            if expected_modality_counts[key]
        },
        "result_modality_distribution": {
            key: result_counts[key]
            for key in sorted(result_counts)
            if result_counts[key]
        },
    }


def _breakdown_by_query_type(per_query: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in per_query:
        grouped.setdefault(str(item["query_type"]), []).append(item)
    return {
        key: _aggregate_query_metrics(items)
        for key, items in sorted(grouped.items(), key=lambda pair: pair[0])
    }


def _gate_check(
    checks: list[dict[str, Any]],
    *,
    metric: str,
    operator: str,
    actual: float | None,
    threshold: float | None,
) -> None:
    if threshold is None or actual is None:
        return
    if operator == ">=":
        passed = actual >= threshold
    elif operator == "<=":
        passed = actual <= threshold
    else:
        raise ValidationError(f"unsupported gate operator: {operator}")
    checks.append(
        {
            "metric": metric,
            "operator": operator,
            "actual": actual,
            "threshold": threshold,
            "passed": passed,
        }
    )


def _gate_metric(metrics: Mapping[str, float | int], key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def evaluate_benchmark_gate(
    metrics: Mapping[str, float | int],
    *,
    gate: BenchmarkGate | None,
    baseline_delta: Mapping[str, float] | None = None,
) -> dict[str, Any] | None:
    """Evaluate benchmark metrics against optional threshold config."""

    if gate is None:
        return {
            "ok": True,
            "configured": False,
            "status": "not_configured",
            "failure_type": None,
            "failed_metrics": [],
            "thresholds": {},
            "checks": [],
        }
    checks: list[dict[str, Any]] = []
    _gate_check(checks, metric="hit_rate", operator=">=", actual=_gate_metric(metrics, "hit_rate"), threshold=gate.min_hit_rate)
    _gate_check(checks, metric="mrr", operator=">=", actual=_gate_metric(metrics, "mrr"), threshold=gate.min_mrr)
    _gate_check(
        checks,
        metric="precision_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "precision_at_k"),
        threshold=gate.min_precision_at_k,
    )
    _gate_check(
        checks,
        metric="recall_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "recall_at_k"),
        threshold=gate.min_recall_at_k,
    )
    _gate_check(
        checks,
        metric="ndcg_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "ndcg_at_k"),
        threshold=gate.min_ndcg_at_k,
    )
    _gate_check(
        checks,
        metric="map_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "map_at_k"),
        threshold=gate.min_map_at_k,
    )
    _gate_check(
        checks,
        metric="strict_chunk_recall_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "strict_chunk_recall_at_k"),
        threshold=gate.min_strict_chunk_recall_at_k,
    )
    _gate_check(
        checks,
        metric="expected_chunk_hit_rate",
        operator=">=",
        actual=_gate_metric(metrics, "expected_chunk_hit_rate"),
        threshold=gate.min_expected_chunk_hit_rate,
    )
    _gate_check(
        checks,
        metric="expected_term_recall_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "expected_term_recall_at_k"),
        threshold=gate.min_expected_term_recall_at_k,
    )
    _gate_check(
        checks,
        metric="table_term_recall_at_k",
        operator=">=",
        actual=_gate_metric(metrics, "table_term_recall_at_k"),
        threshold=gate.min_table_term_recall_at_k,
    )
    _gate_check(
        checks,
        metric="expected_evidence_rank",
        operator="<=",
        actual=_gate_metric(metrics, "expected_evidence_rank"),
        threshold=gate.max_expected_evidence_rank,
    )
    _gate_check(
        checks,
        metric="empty_result_rate",
        operator="<=",
        actual=_gate_metric(metrics, "empty_result_rate"),
        threshold=gate.max_empty_result_rate,
    )

    deltas = baseline_delta or {}
    _gate_check(
        checks,
        metric="hit_rate_delta",
        operator=">=",
        actual=deltas.get("hit_rate"),
        threshold=-gate.max_hit_rate_drop if gate.max_hit_rate_drop is not None else None,
    )
    _gate_check(
        checks,
        metric="mrr_delta",
        operator=">=",
        actual=deltas.get("mrr"),
        threshold=-gate.max_mrr_drop if gate.max_mrr_drop is not None else None,
    )
    _gate_check(
        checks,
        metric="ndcg_at_k_delta",
        operator=">=",
        actual=deltas.get("ndcg_at_k"),
        threshold=-gate.max_ndcg_drop if gate.max_ndcg_drop is not None else None,
    )
    _gate_check(
        checks,
        metric="map_at_k_delta",
        operator=">=",
        actual=deltas.get("map_at_k"),
        threshold=-gate.max_map_drop if gate.max_map_drop is not None else None,
    )
    ok = all(check["passed"] for check in checks)
    failed_metrics = [str(check["metric"]) for check in checks if not check["passed"]]
    return {
        "ok": ok,
        "configured": True,
        "status": "passed" if ok else "failed",
        "failure_type": None if ok else "threshold",
        "failed_metrics": failed_metrics,
        "thresholds": gate.to_dict(),
        "checks": checks,
    }


def attach_benchmark_evaluation(
    report: ValidationReport,
    *,
    qrels: dict[str, list[BenchmarkQrel]],
    cutoff: int,
    gate: BenchmarkGate | None = None,
    baseline_metrics: Mapping[str, float] | None = None,
    baseline_path: str | None = None,
    chunk_snapshot: Mapping[str, Any] | None = None,
) -> ValidationReport:
    """Attach qrels-based ranking metrics to a validation report."""

    missing = [case.query.id for case in report.cases if case.query.id not in qrels]
    if missing:
        raise ValidationError(f"benchmark qrels missing query id(s): {', '.join(missing)}")

    snapshot_index = _snapshot_alias_index(chunk_snapshot)
    per_query = [
        _query_benchmark_metrics(
            case,
            qrels[case.query.id],
            cutoff=cutoff,
            snapshot_index=snapshot_index,
            chunk_snapshot=chunk_snapshot,
        )
        for case in report.cases
    ]
    metrics = _aggregate_query_metrics(per_query)
    baseline: dict[str, Any] | None = None
    baseline_delta: dict[str, float] | None = None
    if baseline_metrics:
        baseline_delta = {
            key: float(metrics[key]) - float(value)
            for key, value in baseline_metrics.items()
            if key in metrics and isinstance(metrics[key], (int, float))
        }
        baseline = {
            "path": baseline_path,
            "metrics": dict(baseline_metrics),
            "delta": baseline_delta,
        }

    benchmark = BenchmarkEvaluation(
        cutoff=cutoff,
        metrics=metrics,
        per_query=per_query,
        query_type_breakdown=_breakdown_by_query_type(per_query),
        multimodal=_multimodal_summary(per_query),
        gate=evaluate_benchmark_gate(metrics, gate=gate, baseline_delta=baseline_delta),
        baseline=baseline,
    )
    return ValidationReport(
        level=report.level,
        dataset_id=report.dataset_id,
        dataset_name=report.dataset_name,
        cases=report.cases,
        benchmark=benchmark,
    )


def run_retrieval_validation(
    client: Any,
    *,
    level: str,
    dataset_id: str,
    dataset_name: str,
    queries: list[ValidationQuery],
    top_k: int = 3,
) -> ValidationReport:
    """Run retrieval validation queries against one RAGFlow dataset."""

    cases: list[ValidationCaseResult] = []
    for query in queries:
        try:
            raw = client.retrieve(
                question=query.question,
                dataset_ids=[dataset_id],
                top_k=query.top_k or top_k,
            )
            chunks = normalize_retrieval_response(raw)
            cases.append(evaluate_query_result(query, chunks))
        except Exception as exc:  # Keep multi-query validation resilient.
            cases.append(
                ValidationCaseResult(
                    query=query,
                    passed=False,
                    chunk_count=0,
                    error=str(exc),
                )
            )
    return ValidationReport(
        level=level,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        cases=cases,
    )


def render_markdown_report(report: ValidationReport) -> str:
    """Render a compact Markdown validation report."""

    metrics = report.metrics()
    runtime_partial_summary = report.runtime_partial_failure_report()["summary"]
    lines = [
        f"# RAGFlow Validation Report",
        "",
        f"- Level: `{report.level}`",
        f"- Dataset: `{report.dataset_name}` (`{report.dataset_id}`)",
        f"- Status: `{'passed' if report.ok else 'failed'}`",
        f"- Pass rate: `{metrics['pass_rate']:.2%}`",
        f"- runtime_partial_failure_status: `{runtime_partial_summary.get('status', 'unknown')}`",
        f"- runtime_partial_failure_partial: `{str(runtime_partial_summary.get('partial', False)).lower()}`",
        f"- runtime_partial_failure_failures: `{runtime_partial_summary.get('failure_count', 0)}`",
        f"- runtime_partial_failure_timeouts: `{runtime_partial_summary.get('timeout_count', 0)}`",
        f"- runtime_partial_failure_warnings: `{runtime_partial_summary.get('warning_count', 0)}`",
        "",
        "| id | status | chunks | missing terms | missing documents |",
        "|---|---:|---:|---|---|",
    ]
    for case in report.cases:
        status = "passed" if case.passed else "failed"
        missing_terms = ", ".join(case.missing_terms) or "-"
        missing_docs = ", ".join(case.missing_documents) or "-"
        lines.append(
            f"| `{case.query.id}` | {status} | {case.chunk_count} | {missing_terms} | {missing_docs} |"
        )
    if report.benchmark:
        benchmark = report.benchmark
        lines.extend(
            [
                "",
                "## Benchmark",
                "",
                f"- Cutoff: `{benchmark.cutoff}`",
                f"- Hit rate: `{float(benchmark.metrics['hit_rate']):.2%}`",
                f"- MRR: `{float(benchmark.metrics['mrr']):.4f}`",
                f"- Precision@k: `{float(benchmark.metrics['precision_at_k']):.4f}`",
                f"- Recall@k: `{float(benchmark.metrics['recall_at_k']):.4f}`",
                f"- nDCG@k: `{float(benchmark.metrics['ndcg_at_k']):.4f}`",
                f"- MAP@k: `{float(benchmark.metrics['map_at_k']):.4f}`",
                f"- Empty result rate: `{float(benchmark.metrics['empty_result_rate']):.2%}`",
            ]
        )
        if "wrong_document_rate" in benchmark.metrics:
            lines.append(f"- Wrong-document rate: `{float(benchmark.metrics['wrong_document_rate']):.2%}`")
        if "tag_pollution_rate" in benchmark.metrics:
            lines.append(f"- Tag pollution rate: `{float(benchmark.metrics['tag_pollution_rate']):.2%}`")
        if "expected_tag_hit_rate" in benchmark.metrics:
            lines.append(f"- Expected tag hit rate: `{float(benchmark.metrics['expected_tag_hit_rate']):.2%}`")
        if "unexpected_tag_hit_rate" in benchmark.metrics:
            lines.append(f"- Unexpected tag hit rate: `{float(benchmark.metrics['unexpected_tag_hit_rate']):.2%}`")
        if "image_recall_at_k" in benchmark.metrics:
            lines.append(f"- Image precision@k: `{float(benchmark.metrics['image_precision_at_k']):.4f}`")
            lines.append(f"- Image recall@k: `{float(benchmark.metrics['image_recall_at_k']):.4f}`")
            lines.append(f"- Visual coverage rate: `{float(benchmark.metrics['visual_coverage_rate']):.2%}`")
        if "table_recall_at_k" in benchmark.metrics:
            lines.append(f"- Table recall@k: `{float(benchmark.metrics['table_recall_at_k']):.4f}`")
        if "strict_chunk_recall_at_k" in benchmark.metrics:
            lines.extend(
                [
                    f"- Strict chunk recall@k: `{float(benchmark.metrics['strict_chunk_recall_at_k']):.4f}`",
                    f"- Expected chunk hit rate: `{float(benchmark.metrics['expected_chunk_hit_rate']):.2%}`",
                    f"- Expected evidence rank: `{float(benchmark.metrics['expected_evidence_rank']):.4f}`",
                    "- Strict chunk recall uses exact chunk IDs or stable content hashes; expected term metrics are semantic content evidence.",
                ]
            )
        if "candidate_snapshot_expected_chunk_recall_at_k" in benchmark.metrics:
            lines.extend(
                [
                    f"- Candidate snapshot expected chunk recall@k: `{float(benchmark.metrics['candidate_snapshot_expected_chunk_recall_at_k']):.4f}`",
                    f"- Candidate snapshot expected chunk hit rate: `{float(benchmark.metrics['candidate_snapshot_expected_chunk_hit_rate']):.2%}`",
                    f"- Candidate snapshot expected chunks matched: `{int(benchmark.metrics.get('matched_candidate_snapshot_expected_chunks', 0))}/{int(benchmark.metrics.get('candidate_snapshot_expected_chunk_count', 0))}`",
                    "- Candidate snapshot expected chunk metrics are advisory semantic matches against the candidate's own chunk boundaries.",
                ]
            )
        if "expected_term_recall_at_k" in benchmark.metrics:
            lines.extend(
                [
                    f"- Expected term recall@k: `{float(benchmark.metrics['expected_term_recall_at_k']):.4f}`",
                    f"- Expected term hit rate: `{float(benchmark.metrics['expected_term_hit_rate']):.2%}`",
                    f"- Expected terms matched: `{int(benchmark.metrics.get('matched_expected_terms', 0))}/{int(benchmark.metrics.get('expected_term_count', 0))}`",
                ]
            )
        if "table_term_recall_at_k" in benchmark.metrics:
            lines.extend(
                [
                    f"- Table term recall@k: `{float(benchmark.metrics['table_term_recall_at_k']):.4f}`",
                    f"- Table term hit rate: `{float(benchmark.metrics['table_term_hit_rate']):.2%}`",
                ]
            )
        lines.extend(
            [
                "",
                "| id | type | hit | mrr | precision@k | recall@k | ndcg@k | map@k |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in benchmark.per_query:
            lines.append(
                "| `{id}` | {query_type} | {hit_rate:.0%} | {mrr:.4f} | "
                "{precision_at_k:.4f} | {recall_at_k:.4f} | {ndcg_at_k:.4f} | {map_at_k:.4f} |".format(
                    **item
                )
            )
        if benchmark.multimodal:
            result_modalities = ", ".join(
                f"{key}={value}"
                for key, value in benchmark.multimodal.get("result_modality_distribution", {}).items()
            ) or "-"
            category_counts = ", ".join(
                f"{key}={value}"
                for key, value in benchmark.multimodal.get("category_counts", {}).items()
            ) or "-"
            lines.extend(
                [
                    "",
                    "## Multimodal",
                    "",
                    f"- Schema: `{benchmark.multimodal.get('schema', MULTIMODAL_BENCHMARK_SCHEMA)}`",
                    f"- Categories: `{category_counts}`",
                    f"- Result modality distribution: `{result_modalities}`",
                ]
            )
        if benchmark.gate:
            lines.extend(["", "## Gate", ""])
            lines.append(f"- Status: `{benchmark.gate.get('status', 'unknown')}`")
            lines.append(f"- Configured: `{str(bool(benchmark.gate.get('configured'))).lower()}`")
            checks = benchmark.gate.get("checks") if isinstance(benchmark.gate.get("checks"), list) else []
            if checks:
                lines.extend(["", "| metric | actual | operator | threshold | status |", "|---|---:|---|---:|---|"])
            for check in checks:
                lines.append(
                    f"| `{check['metric']}` | `{check['actual']:.4f}` | "
                    f"`{check['operator']}` | `{check['threshold']:.4f}` | "
                    f"{'passed' if check['passed'] else 'failed'} |"
                )
    lines.append("")
    return "\n".join(lines)
