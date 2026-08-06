"""Chunk profile loading and linting."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import read_config_file


class ProfileError(RuntimeError):
    """Raised when a build profile is invalid."""


SUPPORTED_PARSER_KEYS = {
    "chunk_token_num",
    "auto_keywords",
    "auto_questions",
    "delimiter",
}
READ_ONLY_SERVER_DEFAULT_PARSER_KEYS = {
    "image_context_size",
    "table_context_size",
}
RAGFLOW_CHUNK_TOKEN_NUM_MAX = 2048
BUILD_PROFILE_MATERIALIZATION_SCHEMA = "ragflow_build_profile_materialization_v1"
ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA = "ragflow_enrichment_experiment_matrix_v1"
ENRICHMENT_EXPERIMENT_REPORT_SCHEMA = "ragflow_enrichment_experiment_report_v1"
CANDIDATE_PROFILE_SET_SCHEMA = "ragflow_candidate_profile_set_v1"
PROFILE_DECISION_REPORT_SCHEMA = "ragflow_profile_decision_report_v1"
DEFAULT_BOUNDED_ENRICHMENT_EXPERIMENT_NAME = "bounded-keyword-question-enrichment"

DOC_TYPES = {"general", "book", "manual", "paper", "notes", "mixed"}
LANGUAGE_ALIASES = {
    "auto": "auto",
    "zh": "Chinese",
    "ch": "Chinese",
    "cn": "Chinese",
    "zho": "Chinese",
    "chinese": "Chinese",
    "中文": "Chinese",
    "en": "English",
    "eng": "English",
    "english": "English",
}


def normalize_profile_language(value: Any) -> str | None:
    """Normalize a profile language hint without treating unknown labels as valid."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = LANGUAGE_ALIASES.get(text.lower())
    return normalized


@dataclass(frozen=True)
class ChunkProfile:
    profile_id: str
    language: str | None = None
    chunk_method: str = "naive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str | None = None
    parser_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChunkProfile":
        profile_id = data.get("profile_id") or data.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ProfileError("profile_id is required")
        chunk_size = int(data.get("chunk_size", data.get("chunk_token_num", 512)))
        chunk_overlap = int(data.get("chunk_overlap", 64))
        if chunk_size <= 0:
            raise ProfileError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ProfileError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ProfileError("chunk_overlap must be smaller than chunk_size")
        parser_config = data.get("parser_config", {})
        if parser_config is None:
            parser_config = {}
        if not isinstance(parser_config, dict):
            raise ProfileError("parser_config must be an object")

        parser_config = dict(parser_config)
        parser_config.setdefault("chunk_token_num", chunk_size)
        parser_config.setdefault("auto_keywords", 0)
        parser_config.setdefault("auto_questions", 0)
        language = normalize_profile_language(data.get("language"))
        if language is None:
            language = normalize_profile_language(parser_config.get("__language__"))

        return cls(
            profile_id=profile_id.strip(),
            language=language,
            chunk_method=str(data.get("chunk_method", "naive")),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model=data.get("embedding_model"),
            parser_config=parser_config,
        )

    def to_dataset_payload(self) -> dict[str, Any]:
        parser_config = {
            key: value
            for key, value in self.parser_config.items()
            if not key.startswith("__")
            and key in SUPPORTED_PARSER_KEYS
            and not (key == "delimiter" and value == "")
        }
        payload: dict[str, Any] = {
            "chunk_method": self.chunk_method,
            "parser_config": parser_config,
        }
        if self.embedding_model:
            payload["embedding_model"] = self.embedding_model
        return payload

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "language": self.language,
            "chunk_method": self.chunk_method,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "parser_config": self.parser_config,
        }


@dataclass(frozen=True)
class ProfileIssue:
    severity: str
    code: str
    message: str
    field: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class ProfileLintReport:
    profile: ChunkProfile
    issues: list[ProfileIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def summary(self) -> dict[str, int]:
        return {
            "errors": sum(1 for issue in self.issues if issue.severity == "error"),
            "warnings": sum(1 for issue in self.issues if issue.severity == "warning"),
            "infos": sum(1 for issue in self.issues if issue.severity == "info"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema": "ragflow_profile_lint_report_v1",
            "profile": self.profile.to_manifest_dict(),
            "summary": self.summary(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ProfileRecommendation:
    profile: ChunkProfile
    language: str
    doc_type: str
    rationale: list[str]
    retrieval_hints_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": True,
            "schema": "ragflow_profile_recommendation_v1",
            "language": self.language,
            "doc_type": self.doc_type,
            "profile": self.profile.to_manifest_dict(),
            "rationale": list(self.rationale),
        }
        if self.retrieval_hints_summary is not None:
            payload["retrieval_hints_summary"] = dict(self.retrieval_hints_summary)
        return payload


def load_profile(path: str | Path) -> ChunkProfile:
    """Load a JSON or simple YAML chunk profile."""

    profile_path = Path(path)
    if profile_path.suffix.lower() == ".json":
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"profile not found: {profile_path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"profile is not valid JSON: {profile_path}") from exc
    else:
        data = read_config_file(profile_path)
    if not isinstance(data, dict):
        raise ProfileError("profile must be an object")
    return ChunkProfile.from_dict(data)


def _numeric_parser_value(profile: ChunkProfile, key: str) -> int | None:
    value = profile.parser_config.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def lint_profile(profile: ChunkProfile) -> ProfileLintReport:
    """Return deterministic profile lint findings."""

    issues: list[ProfileIssue] = []
    parser_chunk_size = _numeric_parser_value(profile, "chunk_token_num")
    if parser_chunk_size is None:
        issues.append(
            ProfileIssue(
                severity="error",
                code="chunk_token_num_not_numeric",
                field="parser_config.chunk_token_num",
                message="parser_config.chunk_token_num must be numeric",
                recommendation="Set parser_config.chunk_token_num to the same value as chunk_size.",
            )
        )
    elif parser_chunk_size != profile.chunk_size:
        issues.append(
            ProfileIssue(
                severity="error",
                code="chunk_token_num_mismatch",
                field="parser_config.chunk_token_num",
                message="parser_config.chunk_token_num differs from chunk_size",
                recommendation="Keep chunk_size and parser_config.chunk_token_num aligned.",
            )
        )

    if profile.chunk_size < 256:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="chunk_size_small",
                field="chunk_size",
                message="chunk_size is small and may fragment long passages",
                recommendation="Use 384-768 for most public KBs unless documents are very short.",
            )
        )
    if profile.chunk_size > 1536:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="chunk_size_large",
                field="chunk_size",
                message="chunk_size is large and may reduce retrieval precision",
                recommendation="Use 512-1024 for most public KBs before benchmarking larger chunks.",
            )
        )

    if not profile.embedding_model:
        issues.append(
            ProfileIssue(
                severity="info",
                code="embedding_model_not_configured",
                field="embedding_model",
                message="profile is model-neutral and does not declare an embedding_model",
                recommendation=(
                    "Keep generic templates model-neutral for portability, or use a model-specific template "
                    "when validating an expected embedding model."
                ),
            )
        )

    overlap_ratio = profile.chunk_overlap / profile.chunk_size
    if overlap_ratio < 0.05:
        issues.append(
            ProfileIssue(
                severity="info",
                code="overlap_low",
                field="chunk_overlap",
                message="chunk overlap is below 5 percent of chunk size",
                recommendation="Use roughly 10-20 percent overlap for long-form documents.",
            )
        )
    if overlap_ratio > 0.35:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="overlap_high",
                field="chunk_overlap",
                message="chunk overlap is high and may duplicate evidence",
                recommendation="Keep overlap below 35 percent unless a benchmark proves it helps.",
            )
        )

    for key in ("auto_keywords", "auto_questions"):
        value = _numeric_parser_value(profile, key)
        if value is None:
            issues.append(
                ProfileIssue(
                    severity="warning",
                    code=f"{key}_not_numeric",
                    field=f"parser_config.{key}",
                    message=f"parser_config.{key} should be numeric",
                    recommendation=f"Use 0 to disable {key} or a small integer after testing.",
                )
            )
        elif value < 0:
            issues.append(
                ProfileIssue(
                    severity="error",
                    code=f"{key}_negative",
                    field=f"parser_config.{key}",
                    message=f"parser_config.{key} must be non-negative",
                    recommendation=f"Use 0 to disable {key}.",
                )
            )

    for key in ("image_context_size", "table_context_size"):
        value = _numeric_parser_value(profile, key)
        if value is None:
            continue
        if value < 0:
            issues.append(
                ProfileIssue(
                    severity="error",
                    code=f"{key}_negative",
                    field=f"parser_config.{key}",
                    message=f"parser_config.{key} must be non-negative",
                    recommendation=f"Use 0 to disable {key}, or a small reviewed integer before live validation.",
                )
            )

    for key in sorted(profile.parser_config):
        if key.startswith("__"):
            issues.append(
                ProfileIssue(
                    severity="info",
                    code="internal_parser_metadata",
                    field=f"parser_config.{key}",
                    message="internal parser metadata is preserved in manifests and filtered from API payloads",
                )
            )
            continue
        if key not in SUPPORTED_PARSER_KEYS:
            read_only_server_default = key in READ_ONLY_SERVER_DEFAULT_PARSER_KEYS
            issues.append(
                ProfileIssue(
                    severity="error" if read_only_server_default else "warning",
                    code="unsupported_parser_key",
                    field=f"parser_config.{key}",
                    message=(
                        "parser_config key is an observed server default rejected by observed dataset create probes"
                        if read_only_server_default
                        else "parser_config key is not part of the writable public profile contract"
                    ),
                    recommendation=(
                        "Keep this key in manifests and read-back audits only; do not send it in dataset create payloads unless a future version-bound contract proves write support."
                        if read_only_server_default
                        else "Keep provider-specific parser keys in manifests only until API write support is proven."
                    ),
                )
            )

    language = profile.language or profile.parser_config.get("__language__")
    if not isinstance(language, str) or not language.strip():
        issues.append(
            ProfileIssue(
                severity="info",
                code="language_metadata_missing",
                field="language",
                message="profile has no language metadata",
                recommendation="Add top-level language as neutral metadata for host-agent explanations.",
            )
        )

    return ProfileLintReport(profile=profile, issues=issues)


def explain_profile(profile: ChunkProfile) -> dict[str, Any]:
    """Return a concise explanation of a chunk profile."""

    lint = lint_profile(profile)
    return {
        "ok": lint.ok,
        "schema": "ragflow_profile_explanation_v1",
        "profile": profile.to_manifest_dict(),
        "api_payload": profile.to_dataset_payload(),
        "api_update_payload": {"language": profile.language} if profile.language else {},
        "summary": {
            "chunk_method": profile.chunk_method,
            "chunk_size": profile.chunk_size,
            "chunk_overlap": profile.chunk_overlap,
            "overlap_ratio": profile.chunk_overlap / profile.chunk_size,
            "language": profile.language or profile.parser_config.get("__language__") or "unknown",
            "embedding_model": profile.embedding_model,
        },
        "notes": [
            "parser_config keys beginning with __ are local metadata and are not sent to RAGFlow.",
            "Run benchmark validation before accepting profile changes for a production KB.",
        ],
        "lint": lint.to_dict(),
    }


def _normalize_language(language: str) -> str:
    normalized = normalize_profile_language(language)
    if normalized is None or normalized not in {"auto", "Chinese", "English"}:
        raise ProfileError("language must be one of auto, zh, ch, cn, zho, en, eng")
    return normalized


def recommend_profile(
    *,
    language: str = "auto",
    doc_type: str = "general",
    profile_id: str | None = None,
    retrieval_hints_summary: Mapping[str, Any] | None = None,
) -> ProfileRecommendation:
    """Create a deterministic starter profile."""

    normalized_language = _normalize_language(language)
    if doc_type not in DOC_TYPES:
        raise ProfileError(f"doc_type must be one of {', '.join(sorted(DOC_TYPES))}")

    if normalized_language == "Chinese":
        sizes = {
            "general": (512, 64),
            "book": (512, 64),
            "manual": (512, 64),
            "paper": (512, 64),
            "notes": (384, 48),
            "mixed": (640, 80),
        }
        language_label = "Chinese"
        suffix = "zh"
    elif normalized_language == "English":
        sizes = {
            "general": (768, 96),
            "book": (768, 96),
            "manual": (768, 96),
            "paper": (768, 96),
            "notes": (512, 64),
            "mixed": (640, 80),
        }
        language_label = "English"
        suffix = "en"
    else:
        sizes = {
            "general": (640, 80),
            "book": (640, 80),
            "manual": (640, 80),
            "paper": (640, 80),
            "notes": (512, 64),
            "mixed": (640, 80),
        }
        language_label = "auto"
        suffix = "auto"

    chunk_size, chunk_overlap = sizes[doc_type]
    profile = ChunkProfile.from_dict(
        {
            "profile_id": profile_id or f"recommended-{suffix}-{doc_type}-{chunk_size}",
            "chunk_method": "naive",
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "parser_config": {
                "chunk_token_num": chunk_size,
                "auto_keywords": 0,
                "auto_questions": 0,
                "__language__": language_label,
            },
        }
    )
    rationale = [
        "Use the portable naive chunk method as a neutral public default.",
        "Keep auto keyword/question generation disabled until a benchmark proves it helps.",
        "Set overlap near 12.5 percent of chunk size for long-form continuity.",
    ]
    if doc_type == "notes":
        rationale.append("Use smaller chunks for short notes to avoid merging unrelated snippets.")
    if doc_type == "mixed":
        rationale.append("Use a middle-size chunk for mixed document sets before per-domain tuning.")
    if retrieval_hints_summary and retrieval_hints_summary.get("exists"):
        table_count = int(retrieval_hints_summary.get("table_artifact_count", 0) or 0)
        image_count = int(retrieval_hints_summary.get("image_artifact_count", 0) or 0)
        if table_count or image_count:
            rationale.append(
                "Use retrieval hints to seed table/image benchmark validation before changing profile defaults."
            )
    return ProfileRecommendation(
        profile=profile,
        language=language_label,
        doc_type=doc_type,
        rationale=rationale,
        retrieval_hints_summary=dict(retrieval_hints_summary) if retrieval_hints_summary is not None else None,
    )


def _profile_suggestion_records(profile_suggestions: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if profile_suggestions.get("schema") not in {None, "ragflow_profile_suggestions_v1"}:
        raise ProfileError("profile suggestions schema must be ragflow_profile_suggestions_v1")
    suggestions = profile_suggestions.get("suggestions")
    if not isinstance(suggestions, list):
        raise ProfileError("profile suggestions must contain a suggestions list")
    records = [item for item in suggestions if isinstance(item, Mapping)]
    if not records:
        raise ProfileError("profile suggestions contains no usable suggestions")
    return records


def _suggestion_has_delimiter(record: Mapping[str, Any]) -> bool:
    parser_config = record.get("parser_config") if isinstance(record.get("parser_config"), Mapping) else {}
    delimiter = parser_config.get("delimiter")
    if isinstance(delimiter, str) and delimiter.strip():
        return True
    postprocess_profile = record.get("postprocess_profile")
    return isinstance(postprocess_profile, str) and "chunk-marker" in postprocess_profile


def _select_profile_suggestion(
    records: list[Mapping[str, Any]],
    *,
    suggestion_id: str | None,
) -> Mapping[str, Any]:
    if suggestion_id:
        for record in records:
            if str(record.get("id") or record.get("profile_id") or "") == suggestion_id:
                return record
        raise ProfileError(f"profile suggestion not found: {suggestion_id}")
    for record in records:
        if _suggestion_has_delimiter(record):
            return record
    return records[0]


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _ingest_plan_parser_profile(ragflow_ingest_plan: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(ragflow_ingest_plan, Mapping):
        return {}
    if ragflow_ingest_plan.get("schema") not in {None, "ragflow_ingest_plan_v1"}:
        raise ProfileError("ragflow ingest plan schema must be ragflow_ingest_plan_v1")
    recommended_build = (
        ragflow_ingest_plan.get("recommended_build")
        if isinstance(ragflow_ingest_plan.get("recommended_build"), Mapping)
        else {}
    )
    parser_profile = (
        recommended_build.get("parser_profile")
        if isinstance(recommended_build.get("parser_profile"), Mapping)
        else {}
    )
    return parser_profile


def _suggestion_language(
    suggestion: Mapping[str, Any],
    *,
    ingest_parser_profile: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    parser_config = suggestion.get("parser_config") if isinstance(suggestion.get("parser_config"), Mapping) else {}
    candidates = (
        ("profile_suggestions.suggestions[].parser_config.__language__", parser_config.get("__language__")),
        ("profile_suggestions.suggestions[].language", suggestion.get("language")),
        ("ragflow_ingest_plan.recommended_build.parser_profile.language", ingest_parser_profile.get("language")),
    )
    for source, value in candidates:
        normalized = normalize_profile_language(value)
        if normalized:
            return normalized, source
    return None, None


def _materialized_profile_id(source_id: str, *, original_tokens: int | None, effective_tokens: int) -> str:
    base = _slug(source_id, default="materialized-profile")
    if original_tokens and original_tokens != effective_tokens and str(original_tokens) in base:
        return base.replace(str(original_tokens), str(effective_tokens))
    if original_tokens and original_tokens != effective_tokens:
        return f"{base}-{effective_tokens}"
    return base


def materialize_profile_suggestion(
    *,
    profile_suggestions: Mapping[str, Any],
    ragflow_ingest_plan: Mapping[str, Any] | None = None,
    suggestion_id: str | None = None,
    max_chunk_token_num: int = RAGFLOW_CHUNK_TOKEN_NUM_MAX,
) -> dict[str, Any]:
    """Convert advisory handoff profile suggestions into a reviewed build profile."""

    if max_chunk_token_num <= 0:
        raise ProfileError("max_chunk_token_num must be positive")
    records = _profile_suggestion_records(profile_suggestions)
    suggestion = _select_profile_suggestion(records, suggestion_id=suggestion_id)
    parser_config = suggestion.get("parser_config") if isinstance(suggestion.get("parser_config"), Mapping) else {}
    ingest_parser_profile = _ingest_plan_parser_profile(ragflow_ingest_plan)
    original_tokens = _first_int(
        parser_config.get("chunk_token_num"),
        suggestion.get("chunk_size"),
        ingest_parser_profile.get("chunk_size"),
    )
    if original_tokens is None or original_tokens <= 0:
        original_tokens = 512
    effective_tokens = min(original_tokens, max_chunk_token_num)
    clamps: list[dict[str, Any]] = []
    if effective_tokens != original_tokens:
        clamps.append(
            {
                "field": "parser_config.chunk_token_num",
                "original": original_tokens,
                "effective": effective_tokens,
                "reason": "ragflow_chunk_token_num_max",
            }
        )

    language, language_source = _suggestion_language(suggestion, ingest_parser_profile=ingest_parser_profile)
    source_id = str(suggestion.get("id") or suggestion.get("profile_id") or "materialized-profile")
    chunk_overlap = _first_int(suggestion.get("chunk_overlap"), ingest_parser_profile.get("chunk_overlap"))
    if chunk_overlap is None:
        chunk_overlap = 0 if _suggestion_has_delimiter(suggestion) else min(64, max(effective_tokens - 1, 0))
    if chunk_overlap >= effective_tokens:
        chunk_overlap = max(effective_tokens - 1, 0)

    effective_parser_config: dict[str, Any] = {"chunk_token_num": effective_tokens}
    unsupported_fields: list[str] = []
    local_only_fields: list[str] = []
    for key, value in parser_config.items():
        key_text = str(key)
        if key_text.startswith("__"):
            local_only_fields.append(f"parser_config.{key_text}")
            continue
        if key_text == "chunk_token_num":
            continue
        if key_text in SUPPORTED_PARSER_KEYS:
            effective_parser_config[key_text] = value
        else:
            unsupported_fields.append(f"parser_config.{key_text}")
    effective_parser_config.setdefault("auto_keywords", 0)
    effective_parser_config.setdefault("auto_questions", 0)

    profile_payload: dict[str, Any] = {
        "profile_id": _materialized_profile_id(
            source_id,
            original_tokens=original_tokens,
            effective_tokens=effective_tokens,
        ),
        "language": language,
        "chunk_method": str(suggestion.get("chunk_method") or "naive"),
        "chunk_size": effective_tokens,
        "chunk_overlap": chunk_overlap,
        "parser_config": effective_parser_config,
    }
    embedding_model = suggestion.get("embedding_model")
    if isinstance(embedding_model, str) and embedding_model.strip():
        profile_payload["embedding_model"] = embedding_model.strip()

    materialized_profile = ChunkProfile.from_dict(profile_payload)
    lint = lint_profile(materialized_profile).to_dict()
    warning_count = len(clamps) + len(unsupported_fields)
    return {
        "ok": lint["ok"],
        "schema": BUILD_PROFILE_MATERIALIZATION_SCHEMA,
        "created_at": _now(),
        "profile": materialized_profile.to_manifest_dict() | {"profile_id": materialized_profile.profile_id},
        "source_suggestion": dict(suggestion),
        "materialization": {
            "selected_suggestion_id": source_id,
            "selection_reason": "delimiter_profile" if _suggestion_has_delimiter(suggestion) else "first_suggestion",
            "language": language,
            "language_source": language_source,
            "max_chunk_token_num": max_chunk_token_num,
            "clamps": clamps,
            "local_only_fields": local_only_fields,
            "unsupported_fields": unsupported_fields,
        },
        "summary": {
            "source_suggestion_count": len(records),
            "clamp_count": len(clamps),
            "local_only_field_count": len(local_only_fields),
            "unsupported_field_count": len(unsupported_fields),
            "warning_count": warning_count,
        },
        "lint": lint,
    }


def _number_from(mapping: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _first_number(mappings: list[Mapping[str, Any]], *keys: str) -> float | None:
    for mapping in mappings:
        value = _number_from(mapping, *keys)
        if value is not None:
            return value
    return None


def _mapping_from(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def _runtime_latency_average_ms(runtime_metrics: Mapping[str, Any]) -> float | None:
    latency = _mapping_from(runtime_metrics, "latency_ms")
    return _number_from(latency, "average", "p50", "p95", "max")


def _empty_result_rate(metrics: Mapping[str, Any], benchmark_metrics: Mapping[str, Any]) -> float:
    direct = _first_number([benchmark_metrics, metrics], "empty_result_rate", "empty_rate")
    if direct is not None:
        return direct
    empty_results = _number_from(metrics, "empty_results")
    total = _number_from(metrics, "total", "query_count")
    if empty_results is not None and total and total > 0:
        return empty_results / total
    return 0.0


def _report_score(report: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), Mapping) else {}
    benchmark_metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), Mapping) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), Mapping) else {}
    timing = report.get("timing") if isinstance(report.get("timing"), Mapping) else {}
    runtime_metrics = report.get("runtime_metrics") if isinstance(report.get("runtime_metrics"), Mapping) else {}
    cost = report.get("cost") if isinstance(report.get("cost"), Mapping) else {}
    cost_trace = report.get("cost_trace") if isinstance(report.get("cost_trace"), Mapping) else {}
    runtime_cost = _mapping_from(runtime_metrics, "cost")
    runtime_cost_trace = _mapping_from(runtime_metrics, "cost_trace")
    pass_rate = _number_from(metrics, "pass_rate") or 0.0
    mrr = _number_from(benchmark_metrics, "mrr") or 0.0
    ndcg = _number_from(benchmark_metrics, "ndcg_at_k") or 0.0
    hit_rate = _number_from(benchmark_metrics, "hit_rate") or 0.0
    empty_rate = _empty_result_rate(metrics, benchmark_metrics)
    average_chunks = _number_from(metrics, "average_chunks", "avg_chunks") or 0.0
    query_count = _query_count_from_report(report)
    query_latency_ms = _first_number(
        [benchmark_metrics, metrics, timing, metadata, runtime_metrics],
        "query_latency_ms",
        "average_query_latency_ms",
        "avg_query_latency_ms",
        "latency_ms",
        "duration_ms",
    )
    if query_latency_ms is None:
        query_latency_ms = _runtime_latency_average_ms(runtime_metrics)
    query_latency_ms = query_latency_ms or 0.0
    parse_time_ms = _first_number(
        [metrics, timing, metadata],
        "parse_time_ms",
        "parse_duration_ms",
        "average_parse_time_ms",
        "avg_parse_time_ms",
    ) or 0.0
    cost_sources = [benchmark_metrics, metrics, timing, metadata, cost, cost_trace, runtime_cost, runtime_cost_trace]
    estimated_cost_usd = _first_number(
        cost_sources,
        "estimated_cost_usd",
        "cost_usd",
        "total_cost_usd",
        "estimated_total_usd",
        "total_estimated_usd",
    ) or 0.0
    cost_per_query_usd = _first_number(
        cost_sources,
        "cost_per_query_usd",
        "estimated_cost_per_query_usd",
    )
    if cost_per_query_usd is None and estimated_cost_usd > 0.0 and query_count > 0:
        cost_per_query_usd = estimated_cost_usd / query_count
    cost_per_query_usd = cost_per_query_usd or 0.0
    latency_penalty = min(query_latency_ms / 10000.0, 0.05)
    cost_penalty = min(cost_per_query_usd * 20.0, 0.05)
    if cost_penalty == 0.0 and estimated_cost_usd > 0.0 and query_count <= 0:
        cost_penalty = min(estimated_cost_usd * 0.1, 0.05)
    benchmark_quality = (hit_rate + mrr + ndcg) / 3
    score = (
        (pass_rate * 0.38)
        + (hit_rate * 0.25)
        + (mrr * 0.20)
        + (ndcg * 0.12)
        - (empty_rate * 0.05)
        - latency_penalty
        - cost_penalty
    )
    return score, {
        "pass_rate": pass_rate,
        "hit_rate": hit_rate,
        "mrr": mrr,
        "ndcg_at_k": ndcg,
        "empty_result_rate": empty_rate,
        "average_chunks": average_chunks,
        "query_count": query_count,
        "query_latency_ms": query_latency_ms,
        "parse_time_ms": parse_time_ms,
        "benchmark_quality_score": benchmark_quality,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_per_query_usd": cost_per_query_usd,
        "latency_penalty": latency_penalty,
        "cost_penalty": cost_penalty,
        "operational_cost_score": latency_penalty + cost_penalty,
        "score": score,
    }


def compare_validation_reports(paths: list[str | Path]) -> dict[str, Any]:
    """Compare validation reports from profile experiments."""

    if len(paths) < 2:
        raise ProfileError("profile compare requires at least two validation reports")
    candidates: list[dict[str, Any]] = []
    for path_value in paths:
        path = Path(path_value)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"validation report not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"validation report is not valid JSON: {path}") from exc
        if not isinstance(data, Mapping):
            raise ProfileError(f"validation report must be an object: {path}")
        score, metrics = _report_score(data)
        candidates.append(
            {
                "path": str(path),
                "ok": bool(data.get("ok")),
                "level": data.get("level"),
                "dataset": data.get("dataset", {}),
                "metrics": metrics,
                "score": score,
            }
        )
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    return {
        "ok": True,
        "schema": "ragflow_profile_compare_report_v1",
        "winner": ranked[0],
        "candidates": ranked,
    }


def _profile_id_from_report(report: Mapping[str, Any], *, fallback: str) -> str:
    for container_key in ("profile", "chunk_profile", "candidate_profile"):
        container = report.get(container_key)
        if isinstance(container, Mapping):
            value = container.get("id") or container.get("profile_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("profile_id", "candidate_id"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _query_count_from_report(report: Mapping[str, Any]) -> int:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), Mapping) else {}
    benchmark_summary = benchmark.get("summary") if isinstance(benchmark.get("summary"), Mapping) else {}
    value = _first_number(
        [metrics, summary, benchmark_summary],
        "total",
        "query_count",
        "case_count",
        "item_count",
        "sample_count",
    )
    return int(value or 0)


def _warning_count_from_report(report: Mapping[str, Any]) -> int:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    summary_count = _number_from(summary, "warning_count", "warnings")
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    issue_count = sum(1 for issue in issues if isinstance(issue, Mapping) and issue.get("severity") == "warning")
    return int(summary_count or issue_count or 0)


def _decision_metrics(report: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    score, metrics = _report_score(report)
    benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), Mapping) else {}
    benchmark_metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), Mapping) else {}
    strict_chunk_recall = _number_from(benchmark_metrics, "strict_chunk_recall_at_k", "strict_recall_at_k")
    expected_chunk_hit_rate = _number_from(benchmark_metrics, "expected_chunk_hit_rate", "expected_evidence_hit_rate")
    table_recall = _number_from(benchmark_metrics, "table_recall", "table_strict_recall", "table_recall_at_k")
    image_recall = _number_from(benchmark_metrics, "image_recall", "visual_recall", "image_recall_at_k")
    metrics.update(
        {
            "query_count": _query_count_from_report(report),
            "strict_chunk_recall_at_k": 1.0 if strict_chunk_recall is None else strict_chunk_recall,
            "expected_chunk_hit_rate": 1.0 if expected_chunk_hit_rate is None else expected_chunk_hit_rate,
            "table_recall": table_recall,
            "image_recall": image_recall,
            "context_warning_count": _warning_count_from_report(report),
        }
    )
    recall_components = [
        metrics["strict_chunk_recall_at_k"],
        metrics["expected_chunk_hit_rate"],
        *(value for value in (table_recall, image_recall) if value is not None),
    ]
    recall_score = sum(float(value) for value in recall_components) / len(recall_components) if recall_components else 1.0
    latency_penalty = min(float(metrics.get("query_latency_ms", 0.0) or 0.0) / 10000.0, 0.05)
    warning_penalty = min(float(metrics["context_warning_count"]) * 0.005, 0.03)
    decision_score = (score * 0.75) + (recall_score * 0.25) - latency_penalty - warning_penalty
    metrics["recall_completeness_score"] = recall_score
    metrics["decision_score"] = decision_score
    return decision_score, metrics


def decide_profile_from_reports(
    paths: list[str | Path],
    *,
    minimum_query_count: int = 20,
    minimum_profile_count: int = 2,
    minimum_score_delta: float = 0.03,
) -> dict[str, Any]:
    """Create a conservative profile decision report from validation artifacts."""

    if len(paths) < 2:
        raise ProfileError("profile decision requires at least two validation reports")
    candidates: list[dict[str, Any]] = []
    for path_value in paths:
        path = Path(path_value)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"validation report not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"validation report is not valid JSON: {path}") from exc
        if not isinstance(data, Mapping):
            raise ProfileError(f"validation report must be an object: {path}")
        score, metrics = _decision_metrics(data)
        candidates.append(
            {
                "path": str(path),
                "profile_id": _profile_id_from_report(data, fallback=path.stem),
                "ok": bool(data.get("ok", True)),
                "metrics": metrics,
                "score": score,
            }
        )

    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    score_delta = float(winner["score"]) - float(runner_up["score"] if runner_up else 0.0)
    max_query_count = max(int(candidate["metrics"].get("query_count", 0) or 0) for candidate in ranked)
    issues: list[dict[str, Any]] = []
    if len(ranked) < minimum_profile_count:
        issues.append(
            {
                "severity": "warning",
                "code": "minimum_profile_count_not_met",
                "message": "not enough profile candidates were compared to recommend a default change",
            }
        )
    if max_query_count < minimum_query_count:
        issues.append(
            {
                "severity": "warning",
                "code": "minimum_query_count_not_met",
                "message": "profile comparison has too few validation queries to recommend a default change",
                "evidence": {"max_query_count": max_query_count, "minimum_query_count": minimum_query_count},
            }
        )
    if score_delta < minimum_score_delta:
        issues.append(
            {
                "severity": "warning",
                "code": "score_delta_below_threshold",
                "message": "top profile score delta is too small to recommend a default change",
                "evidence": {"score_delta": round(score_delta, 6), "minimum_score_delta": minimum_score_delta},
            }
        )

    threshold_blocking = any(issue["code"] in {"minimum_profile_count_not_met", "minimum_query_count_not_met"} for issue in issues)
    if threshold_blocking:
        status = "insufficient_sample_for_default_change"
    elif any(issue["code"] == "score_delta_below_threshold" for issue in issues):
        status = "tie_or_no_default_change"
    else:
        status = "recommend_default_change"
    return {
        "ok": True,
        "schema": PROFILE_DECISION_REPORT_SCHEMA,
        "created_at": _now(),
        "decision": {
            "status": status,
            "default_change_allowed": status == "recommend_default_change",
            "recommended_profile_id": winner["profile_id"] if status == "recommend_default_change" else None,
            "winner_profile_id": winner["profile_id"],
            "reason_codes": [str(issue["code"]) for issue in issues],
        },
        "summary": {
            "candidate_count": len(ranked),
            "max_query_count": max_query_count,
            "minimum_query_count": minimum_query_count,
            "minimum_profile_count": minimum_profile_count,
            "score_delta": round(score_delta, 6),
            "winner_profile_id": winner["profile_id"],
        },
        "thresholds": {
            "minimum_query_count": minimum_query_count,
            "minimum_profile_count": minimum_profile_count,
            "minimum_score_delta": minimum_score_delta,
        },
        "winner": winner,
        "candidates": ranked,
        "issues": issues,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, *, default: str = "value") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-._:")
    return slug or default


def load_enrichment_experiment_matrix(path: str | Path) -> dict[str, Any]:
    """Load a JSON/YAML enrichment experiment matrix."""

    matrix_path = Path(path)
    if matrix_path.suffix.lower() == ".json":
        try:
            data = json.loads(matrix_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"experiment matrix not found: {matrix_path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"experiment matrix is not valid JSON: {matrix_path}") from exc
    else:
        data = read_config_file(matrix_path)
    if not isinstance(data, dict):
        raise ProfileError("experiment matrix must be an object")
    return data


def make_bounded_enrichment_experiment_matrix(*, name: str | None = None) -> dict[str, Any]:
    """Return a small offline matrix for reviewing keyword/question enrichment."""

    return {
        "schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
        "name": name or DEFAULT_BOUNDED_ENRICHMENT_EXPERIMENT_NAME,
        "dimensions": {
            "auto_keywords": [0, 1],
            "auto_questions": [0, 1],
        },
    }


def _matrix_issue_counts(issues: list[ProfileIssue]) -> dict[str, int]:
    return {
        "errors": sum(1 for issue in issues if issue.severity == "error"),
        "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        "infos": sum(1 for issue in issues if issue.severity == "info"),
    }


def _matrix_values(
    matrix: Mapping[str, Any],
    *,
    issues: list[ProfileIssue],
) -> tuple[dict[str, Any], list[tuple[str, list[Any]]]]:
    if matrix.get("schema") not in {None, ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA}:
        issues.append(
            ProfileIssue(
                "error",
                "experiment_matrix_schema_invalid",
                f"experiment matrix schema must be {ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA}",
                "schema",
            )
        )
    fixed = matrix.get("fixed", {})
    if fixed is None:
        fixed = {}
    if not isinstance(fixed, Mapping):
        issues.append(ProfileIssue("error", "experiment_matrix_fixed_invalid", "fixed must be an object", "fixed"))
        fixed = {}
    raw_dimensions = matrix.get("dimensions", {})
    if not isinstance(raw_dimensions, Mapping) or not raw_dimensions:
        issues.append(ProfileIssue("error", "experiment_matrix_dimensions_missing", "dimensions must be a non-empty object", "dimensions"))
        return dict(fixed), []

    dimensions = []
    for key, raw_values in raw_dimensions.items():
        field_name = str(key)
        if not isinstance(raw_values, list) or not raw_values:
            issues.append(
                ProfileIssue(
                    "error",
                    "experiment_matrix_dimension_invalid",
                    "each dimension must contain a non-empty list of values",
                    f"dimensions.{field_name}",
                )
            )
            continue
        dimensions.append((field_name, list(raw_values)))
    return dict(fixed), dimensions


def _set_nested(mapping: dict[str, Any], dotted_key: str, value: Any) -> None:
    target = mapping
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        current = target.get(part)
        if not isinstance(current, dict):
            current = {}
            target[part] = current
        target = current
    target[parts[-1]] = value


def _is_chunk_token_alias(key: str) -> bool:
    return key.strip() in {
        "chunk_size",
        "profile.chunk_size",
        "chunk_token_num",
        "profile.chunk_token_num",
        "parser_config.chunk_token_num",
    }


def _chunk_alias_fields(keys: Iterable[str]) -> list[str]:
    aliases = []
    for key in keys:
        normalized = str(key).strip()
        if _is_chunk_token_alias(normalized):
            aliases.append(normalized)
    return sorted(set(aliases))


def _apply_experiment_setting(profile_data: dict[str, Any], settings: dict[str, Any], key: str, value: Any) -> None:
    parser_config = profile_data.setdefault("parser_config", {})
    if not isinstance(parser_config, dict):
        parser_config = {}
        profile_data["parser_config"] = parser_config

    normalized = key.strip()
    if normalized in {"chunk_size", "profile.chunk_size", "chunk_token_num", "profile.chunk_token_num", "parser_config.chunk_token_num"}:
        chunk_size = int(value)
        profile_data["chunk_size"] = chunk_size
        parser_config["chunk_token_num"] = chunk_size
        if normalized == "parser_config.chunk_token_num":
            _set_nested(settings, "parser_config.chunk_token_num", chunk_size)
        elif normalized in {"chunk_token_num", "profile.chunk_token_num"}:
            _set_nested(settings, "profile.chunk_token_num", chunk_size)
        else:
            _set_nested(settings, "profile.chunk_size", chunk_size)
    elif normalized in {"chunk_overlap", "profile.chunk_overlap"}:
        chunk_overlap = int(value)
        profile_data["chunk_overlap"] = chunk_overlap
        _set_nested(settings, "profile.chunk_overlap", chunk_overlap)
    elif normalized in {"chunk_method", "profile.chunk_method"}:
        profile_data["chunk_method"] = str(value)
        _set_nested(settings, "profile.chunk_method", str(value))
    elif normalized in {"embedding_model", "profile.embedding_model"}:
        profile_data["embedding_model"] = value
        _set_nested(settings, "profile.embedding_model", value)
    elif normalized in {"auto_keywords", "parser_config.auto_keywords"}:
        parser_config["auto_keywords"] = int(value)
        _set_nested(settings, "parser_config.auto_keywords", int(value))
    elif normalized in {"auto_questions", "parser_config.auto_questions"}:
        parser_config["auto_questions"] = int(value)
        _set_nested(settings, "parser_config.auto_questions", int(value))
    elif normalized.startswith("parser_config."):
        parser_config[normalized.split(".", 1)[1]] = value
        _set_nested(settings, normalized, value)
    elif normalized.startswith("retrieval."):
        _set_nested(settings, normalized, value)
    elif normalized in {"tag_kb_ids", "tag_ids"}:
        _set_nested(settings, "retrieval.tag_kb_ids", value)
    else:
        _set_nested(settings, f"extra.{normalized}", value)


def _setting_digest(settings: Mapping[str, Any]) -> str:
    payload = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _effective_profile_payload(profile: ChunkProfile) -> dict[str, Any]:
    payload = profile.to_manifest_dict()
    parser_config = payload.get("parser_config")
    if not isinstance(parser_config, dict):
        parser_config = {}
        payload["parser_config"] = parser_config
    chunk_token_num = parser_config.get("chunk_token_num", payload.get("chunk_size"))
    if isinstance(chunk_token_num, bool) or not isinstance(chunk_token_num, (int, float)):
        chunk_token_num = payload.get("chunk_size")
    if not isinstance(chunk_token_num, bool) and isinstance(chunk_token_num, (int, float)):
        effective_chunk_size = int(chunk_token_num)
        payload["chunk_size"] = effective_chunk_size
        parser_config["chunk_token_num"] = effective_chunk_size
    payload.pop("id", None)
    payload.pop("profile_id", None)
    return payload


def _effective_profile_key(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _effective_settings_from_profile(profile_payload: Mapping[str, Any]) -> dict[str, Any]:
    parser_config = profile_payload.get("parser_config") if isinstance(profile_payload.get("parser_config"), Mapping) else {}
    settings: dict[str, Any] = {
        "profile": {"chunk_size": profile_payload.get("chunk_size")},
        "parser_config": {"chunk_token_num": parser_config.get("chunk_token_num")},
    }
    for key in ("auto_keywords", "auto_questions", "delimiter"):
        if key in parser_config:
            settings["parser_config"][key] = parser_config[key]
    return settings


def _normalized_effective_settings(raw_settings: Mapping[str, Any], profile_payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        settings = json.loads(json.dumps(raw_settings, ensure_ascii=False))
    except (TypeError, ValueError):
        settings = dict(raw_settings)
    if not isinstance(settings, dict):
        settings = {}
    effective = _effective_settings_from_profile(profile_payload)
    profile_settings = settings.get("profile")
    if not isinstance(profile_settings, dict):
        profile_settings = {}
        settings["profile"] = profile_settings
    profile_settings["chunk_size"] = effective["profile"]["chunk_size"]
    parser_settings = settings.get("parser_config")
    if not isinstance(parser_settings, dict):
        parser_settings = {}
        settings["parser_config"] = parser_settings
    parser_settings.update(effective["parser_config"])
    return settings


def _matrix_alias_warning(
    *,
    fixed: Mapping[str, Any],
    dimensions: list[tuple[str, list[Any]]],
    issues: list[ProfileIssue],
) -> None:
    alias_fields = _chunk_alias_fields([*fixed.keys(), *(key for key, _ in dimensions)])
    if len(alias_fields) > 1:
        issues.append(
            ProfileIssue(
                "warning",
                "aliased_profile_dimensions",
                "experiment matrix varies aliased chunk-size fields that collapse to effective chunk_token_num values",
                "dimensions",
                "Vary only one of chunk_size, chunk_token_num, or parser_config.chunk_token_num.",
            )
        )


def _duplicate_override_reason(records: list[Mapping[str, Any]]) -> str:
    for record in records:
        settings = record.get("settings") if isinstance(record.get("settings"), Mapping) else {}
        setting_text = json.dumps(settings, ensure_ascii=False, sort_keys=True)
        if "chunk_size" in setting_text or "chunk_token_num" in setting_text:
            return "chunk_token_num_alias"
    return "duplicate_effective_profile"


def _risk_issues(*, profile: ChunkProfile, settings: Mapping[str, Any], index: int) -> list[ProfileIssue]:
    issues: list[ProfileIssue] = []
    for key in ("auto_keywords", "auto_questions"):
        value = _numeric_parser_value(profile, key)
        if value and value > 0:
            issues.append(
                ProfileIssue(
                    "warning",
                    "llm_backed_enrichment_enabled",
                    f"parser_config.{key} may trigger slower or LLM-backed RAGFlow enrichment",
                    f"experiments[{index}].parser_config.{key}",
                    "Benchmark cost, latency, and grounding before promoting this profile.",
                )
            )
    retrieval = settings.get("retrieval") if isinstance(settings.get("retrieval"), Mapping) else {}
    top_k = retrieval.get("top_k")
    if isinstance(top_k, (int, float)) and not isinstance(top_k, bool) and top_k > 20:
        issues.append(
            ProfileIssue(
                "warning",
                "top_k_latency_risk",
                "retrieval.top_k is high and may increase latency or noisy evidence",
                f"experiments[{index}].retrieval.top_k",
            )
        )
    threshold = retrieval.get("similarity_threshold")
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and threshold < 0.05:
        issues.append(
            ProfileIssue(
                "warning",
                "low_threshold_pollution_risk",
                "retrieval.similarity_threshold is low and may increase unrelated chunks",
                f"experiments[{index}].retrieval.similarity_threshold",
            )
        )
    if retrieval.get("rerank"):
        issues.append(
            ProfileIssue(
                "warning",
                "rerank_latency_risk",
                "rerank-enabled experiments should measure added latency and rank stability",
                f"experiments[{index}].retrieval.rerank",
            )
        )
    if retrieval.get("tag_kb_ids"):
        issues.append(
            ProfileIssue(
                "info",
                "user_tag_kb_ids",
                "tag_kb_ids are user-owned experiment inputs and are only recorded in local artifacts",
                f"experiments[{index}].retrieval.tag_kb_ids",
            )
        )
    return issues


def plan_enrichment_experiments(
    *,
    base_profile: ChunkProfile,
    matrix: Mapping[str, Any],
    profile_id_prefix: str | None = None,
    max_experiments: int = 64,
    fail_on_duplicate_effective_profiles: bool = False,
) -> dict[str, Any]:
    """Expand an offline enrichment experiment matrix into candidate profiles."""

    issues: list[ProfileIssue] = []
    if max_experiments <= 0:
        issues.append(ProfileIssue("error", "max_experiments_invalid", "max_experiments must be positive", "max_experiments"))
    fixed, dimensions = _matrix_values(matrix, issues=issues)
    experiment_count = 1
    for _, values in dimensions:
        experiment_count *= len(values)
    if experiment_count > max_experiments:
        issues.append(
            ProfileIssue(
                "error",
                "experiment_matrix_too_large",
                f"matrix expands to {experiment_count} experiments, above max_experiments={max_experiments}",
                "dimensions",
                "Reduce dimensions or pass a larger max_experiments value after reviewing runtime cost.",
            )
        )
    _matrix_alias_warning(fixed=fixed, dimensions=dimensions, issues=issues)

    experiments: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    raw_experiments: list[dict[str, Any]] = []
    records_by_effective_key: dict[str, list[dict[str, Any]]] = {}
    prefix = _slug(profile_id_prefix or base_profile.profile_id, default="profile")
    if not any(issue.severity == "error" for issue in issues):
        keys = [key for key, _ in dimensions]
        for index, values in enumerate(product(*(values for _, values in dimensions)), start=1):
            profile_data = base_profile.to_manifest_dict()
            profile_data["profile_id"] = profile_data.pop("id")
            settings: dict[str, Any] = {}
            try:
                for key, value in fixed.items():
                    _apply_experiment_setting(profile_data, settings, str(key), value)
                for key, value in zip(keys, values):
                    _apply_experiment_setting(profile_data, settings, key, value)
                profile = ChunkProfile.from_dict(profile_data)
                effective_profile = _effective_profile_payload(profile)
                effective_key = _effective_profile_key(effective_profile)
            except (ProfileError, TypeError, ValueError) as exc:
                issues.append(
                    ProfileIssue(
                        "error",
                        "experiment_profile_invalid",
                        str(exc),
                        f"experiments[{index - 1}]",
                    )
                )
                continue
            record = {
                "index": index,
                "settings": settings,
                "effective_profile_key": effective_key,
                "effective_profile": effective_profile,
            }
            raw_experiments.append(
                {
                    "index": index,
                    "settings": settings,
                    "effective_profile_key": effective_key,
                    "normalized_settings": _normalized_effective_settings(settings, effective_profile),
                }
            )
            records_by_effective_key.setdefault(effective_key, []).append(record)

        duplicate_groups = []
        for effective_key, records in records_by_effective_key.items():
            if len(records) <= 1:
                continue
            duplicate_groups.append(
                {
                    "effective_profile_key": effective_key,
                    "raw_indexes": [record["index"] for record in records],
                    "raw_settings": [record["settings"] for record in records],
                    "normalized_settings": _normalized_effective_settings(records[0]["settings"], records[0]["effective_profile"]),
                    "normalized_profile": records[0]["effective_profile"],
                    "override_reason": _duplicate_override_reason(records),
                }
            )
        for group in duplicate_groups:
            severity = "error" if fail_on_duplicate_effective_profiles else "warning"
            issues.append(
                ProfileIssue(
                    severity,
                    "duplicate_effective_profiles_blocked"
                    if fail_on_duplicate_effective_profiles
                    else "duplicate_effective_profile_collapsed",
                    "experiment matrix contains raw combinations that normalize to the same effective profile",
                    "dimensions",
                    "Remove aliased or redundant dimensions before running expensive live experiments.",
                )
            )

        for unique_index, (effective_key, records) in enumerate(records_by_effective_key.items(), start=1):
            representative = records[0]
            effective_profile = dict(representative["effective_profile"])
            settings = _normalized_effective_settings(representative["settings"], effective_profile)
            digest = _setting_digest(settings)
            effective_profile["profile_id"] = f"{prefix}-exp-{unique_index:02d}-{digest}"
            profile = ChunkProfile.from_dict(effective_profile)
            profile_payload = profile.to_manifest_dict()
            risk_issues = _risk_issues(profile=profile, settings=settings, index=unique_index - 1)
            issues.extend(risk_issues)
            profiles.append(profile_payload)
            experiments.append(
                {
                    "index": unique_index,
                    "profile_id": profile.profile_id,
                    "settings": settings,
                    "raw_indexes": [record["index"] for record in records],
                    "effective_profile_key": effective_key,
                    "profile": profile_payload,
                    "lint": lint_profile(profile).to_dict(),
                    "risk_issues": [issue.to_dict() for issue in risk_issues],
                }
            )
    else:
        duplicate_groups = []

    counts = _matrix_issue_counts(issues)
    candidate_profile_set = {
        "schema": CANDIDATE_PROFILE_SET_SCHEMA,
        "metadata": {
            "source_schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
            "source_name": matrix.get("name") if isinstance(matrix.get("name"), str) else None,
            "base_profile_id": base_profile.profile_id,
        },
        "profiles": profiles,
    }
    return {
        "ok": counts["errors"] == 0,
        "schema": ENRICHMENT_EXPERIMENT_REPORT_SCHEMA,
        "created_at": _now(),
        "matrix_schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
        "base_profile": base_profile.to_manifest_dict(),
        "matrix": {
            "name": matrix.get("name"),
            "fixed": fixed,
            "dimensions": {key: values for key, values in dimensions},
        },
        "summary": {
            **counts,
            "dimension_count": len(dimensions),
            "planned_experiment_count": experiment_count if dimensions else 0,
            "raw_experiment_count": len(raw_experiments),
            "unique_effective_profile_count": len(profiles),
            "duplicate_effective_profile_group_count": len(duplicate_groups),
            "candidate_profile_count": len(profiles),
            "mutation_steps": 0,
        },
        "raw_matrix_audit": {
            "raw_experiment_count": len(raw_experiments),
            "experiments": raw_experiments,
        },
        "effective_profile_deduplication": {
            "enabled": True,
            "collapse_duplicates": True,
            "fail_on_duplicate_effective_profiles": fail_on_duplicate_effective_profiles,
            "raw_experiment_count": len(raw_experiments),
            "unique_effective_profile_count": len(profiles),
            "duplicate_effective_profile_group_count": len(duplicate_groups),
            "duplicate_effective_profile_groups": duplicate_groups,
        },
        "candidate_profile_set": candidate_profile_set,
        "experiments": experiments,
        "issues": [issue.to_dict() for issue in issues],
    }


def render_enrichment_experiment_markdown(report: Mapping[str, Any]) -> str:
    """Render an enrichment experiment plan as Markdown."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Enrichment Experiment Matrix",
        "",
        f"- Status: `{'passed' if report.get('ok') else 'failed'}`",
        f"- Mutates RAGFlow: `false`",
        f"- Dimensions: `{summary.get('dimension_count', 0)}`",
        f"- Raw combinations: `{summary.get('raw_experiment_count', summary.get('planned_experiment_count', 0))}`",
        f"- Unique effective profiles: `{summary.get('unique_effective_profile_count', summary.get('candidate_profile_count', 0))}`",
        f"- Duplicate effective profile groups: `{summary.get('duplicate_effective_profile_group_count', 0)}`",
        f"- Candidate profiles: `{summary.get('candidate_profile_count', 0)}`",
        f"- Warnings: `{summary.get('warnings', 0)}`",
        "",
        "## Experiments",
        "",
        "| index | profile | settings | warnings |",
        "|---:|---|---|---:|",
    ]
    for item in report.get("experiments", []) if isinstance(report.get("experiments"), list) else []:
        if not isinstance(item, Mapping):
            continue
        settings = json.dumps(item.get("settings", {}), ensure_ascii=False, sort_keys=True)
        risk_issues = item.get("risk_issues") if isinstance(item.get("risk_issues"), list) else []
        lines.append(f"| {item.get('index')} | `{item.get('profile_id')}` | `{settings}` | {len(risk_issues)} |")
    deduplication = report.get("effective_profile_deduplication") if isinstance(report.get("effective_profile_deduplication"), Mapping) else {}
    duplicate_groups = (
        deduplication.get("duplicate_effective_profile_groups")
        if isinstance(deduplication.get("duplicate_effective_profile_groups"), list)
        else []
    )
    if duplicate_groups:
        lines.extend(
            [
                "",
                "## Duplicate Effective Profiles",
                "",
                "| effective key | raw indexes | reason |",
                "|---|---|---|",
            ]
        )
        for group in duplicate_groups:
            if not isinstance(group, Mapping):
                continue
            raw_indexes = group.get("raw_indexes") if isinstance(group.get("raw_indexes"), list) else []
            lines.append(
                f"| `{group.get('effective_profile_key')}` | {', '.join(str(index) for index in raw_indexes)} | "
                f"{group.get('override_reason') or '-'} |"
            )
    if report.get("issues"):
        lines.extend(["", "## Issues", "", "| severity | code | field | message |", "|---|---|---|---|"])
        for issue in report.get("issues", []) if isinstance(report.get("issues"), list) else []:
            if isinstance(issue, Mapping):
                lines.append(f"| {issue.get('severity')} | `{issue.get('code')}` | {issue.get('field', '-')} | {issue.get('message')} |")
    lines.append("")
    return "\n".join(lines)


def render_profile_lint_markdown(report: ProfileLintReport) -> str:
    summary = report.summary()
    lines = [
        "# RAGFlow Profile Lint Report",
        "",
        f"- Profile: `{report.profile.profile_id}`",
        f"- Status: `{'passed' if report.ok else 'failed'}`",
        f"- Errors: `{summary['errors']}`",
        f"- Warnings: `{summary['warnings']}`",
        f"- Infos: `{summary['infos']}`",
        "",
        "| severity | code | field | message | recommendation |",
        "|---|---|---|---|---|",
    ]
    for issue in report.issues:
        lines.append(
            f"| {issue.severity} | `{issue.code}` | {issue.field or '-'} | "
            f"{issue.message} | {issue.recommendation or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_profile_compare_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RAGFlow Profile Compare Report",
        "",
        "| rank | path | score | pass_rate | hit_rate | mrr | ndcg@k | empty_rate | latency_ms | parse_ms | cost_usd | cost_per_query_usd | operational_cost |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(report.get("candidates", []), start=1):
        metrics = item.get("metrics", {})
        lines.append(
            f"| {index} | `{item.get('path')}` | {item.get('score', 0):.4f} | "
            f"{metrics.get('pass_rate', 0):.4f} | {metrics.get('hit_rate', 0):.4f} | "
            f"{metrics.get('mrr', 0):.4f} | {metrics.get('ndcg_at_k', 0):.4f} | "
            f"{metrics.get('empty_result_rate', 0):.4f} | {metrics.get('query_latency_ms', 0):.1f} | "
            f"{metrics.get('parse_time_ms', 0):.1f} | {metrics.get('estimated_cost_usd', 0):.6f} | "
            f"{metrics.get('cost_per_query_usd', 0):.6f} | {metrics.get('operational_cost_score', 0):.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_profile_decision_markdown(report: Mapping[str, Any]) -> str:
    decision = report.get("decision", {}) if isinstance(report.get("decision"), Mapping) else {}
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Profile Decision Report",
        "",
        f"- schema: `{report.get('schema', PROFILE_DECISION_REPORT_SCHEMA)}`",
        f"- status: `{decision.get('status', 'unknown')}`",
        f"- default_change_allowed: `{str(bool(decision.get('default_change_allowed'))).lower()}`",
        f"- winner_profile_id: `{decision.get('winner_profile_id', '')}`",
        f"- recommended_profile_id: `{decision.get('recommended_profile_id') or ''}`",
        f"- candidate_count: `{summary.get('candidate_count', 0)}`",
        f"- max_query_count: `{summary.get('max_query_count', 0)}`",
        f"- score_delta: `{summary.get('score_delta', 0)}`",
        "",
        "| rank | profile | decision_score | pass_rate | strict_recall | expected_hit | table_recall | image_recall | empty_rate | latency_ms | chunks | cost_usd | operational_cost |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(report.get("candidates", []), start=1):
        if not isinstance(item, Mapping):
            continue
        metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), Mapping) else {}
        table_recall = "" if metrics.get("table_recall") is None else f"{float(metrics.get('table_recall') or 0.0):.4f}"
        image_recall = "" if metrics.get("image_recall") is None else f"{float(metrics.get('image_recall') or 0.0):.4f}"
        lines.append(
            f"| {index} | `{item.get('profile_id', '')}` | {float(item.get('score', 0.0) or 0.0):.4f} | "
            f"{float(metrics.get('pass_rate', 0.0) or 0.0):.4f} | "
            f"{float(metrics.get('strict_chunk_recall_at_k', 0.0) or 0.0):.4f} | "
            f"{float(metrics.get('expected_chunk_hit_rate', 0.0) or 0.0):.4f} | "
            f"{table_recall} | "
            f"{image_recall} | "
            f"{float(metrics.get('empty_result_rate', 0.0) or 0.0):.4f} | "
            f"{float(metrics.get('query_latency_ms', 0.0) or 0.0):.1f} | "
            f"{float(metrics.get('average_chunks', 0.0) or 0.0):.1f} | "
            f"{float(metrics.get('estimated_cost_usd', 0.0) or 0.0):.6f} | "
            f"{float(metrics.get('operational_cost_score', 0.0) or 0.0):.4f} |"
        )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    lines.extend(["", "## Issues", ""])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            if isinstance(issue, Mapping):
                lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    lines.append("")
    return "\n".join(lines)
