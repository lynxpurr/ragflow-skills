"""Chunk profile loading and linting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .config import read_config_file


class ProfileError(RuntimeError):
    """Raised when a build profile is invalid."""


SUPPORTED_PARSER_KEYS = {
    "chunk_token_num",
    "auto_keywords",
    "auto_questions",
}

DOC_TYPES = {"general", "book", "manual", "paper", "notes", "mixed"}
LANGUAGE_ALIASES = {
    "auto": "auto",
    "zh": "Chinese",
    "ch": "Chinese",
    "cn": "Chinese",
    "zho": "Chinese",
    "en": "English",
    "eng": "English",
}


@dataclass(frozen=True)
class ChunkProfile:
    profile_id: str
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

        return cls(
            profile_id=profile_id.strip(),
            chunk_method=str(data.get("chunk_method", "naive")),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model=data.get("embedding_model"),
            parser_config=parser_config,
        )

    def to_dataset_payload(self) -> dict[str, Any]:
        parser_config = {
            key: value for key, value in self.parser_config.items() if not key.startswith("__")
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema": "ragflow_profile_recommendation_v1",
            "language": self.language,
            "doc_type": self.doc_type,
            "profile": self.profile.to_manifest_dict(),
            "rationale": list(self.rationale),
        }


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
            issues.append(
                ProfileIssue(
                    severity="warning",
                    code="unsupported_parser_key",
                    field=f"parser_config.{key}",
                    message="parser_config key is not part of the public profile contract",
                    recommendation="Keep provider-specific parser keys only when a live probe or benchmark requires them.",
                )
            )

    language = profile.parser_config.get("__language__")
    if not isinstance(language, str) or not language.strip():
        issues.append(
            ProfileIssue(
                severity="info",
                code="language_metadata_missing",
                field="parser_config.__language__",
                message="profile has no language metadata",
                recommendation="Add parser_config.__language__ as neutral metadata for host-agent explanations.",
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
        "summary": {
            "chunk_method": profile.chunk_method,
            "chunk_size": profile.chunk_size,
            "chunk_overlap": profile.chunk_overlap,
            "overlap_ratio": profile.chunk_overlap / profile.chunk_size,
            "language": profile.parser_config.get("__language__") or "unknown",
            "embedding_model": profile.embedding_model,
        },
        "notes": [
            "parser_config keys beginning with __ are local metadata and are not sent to RAGFlow.",
            "Run benchmark validation before accepting profile changes for a production KB.",
        ],
        "lint": lint.to_dict(),
    }


def _normalize_language(language: str) -> str:
    key = language.strip().lower()
    if key not in LANGUAGE_ALIASES:
        raise ProfileError("language must be one of auto, zh, ch, cn, zho, en, eng")
    return LANGUAGE_ALIASES[key]


def recommend_profile(
    *,
    language: str = "auto",
    doc_type: str = "general",
    profile_id: str | None = None,
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
    return ProfileRecommendation(
        profile=profile,
        language=language_label,
        doc_type=doc_type,
        rationale=rationale,
    )


def _report_score(report: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), Mapping) else {}
    benchmark_metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), Mapping) else {}
    pass_rate = float(metrics.get("pass_rate", 0.0)) if isinstance(metrics.get("pass_rate"), (int, float)) else 0.0
    mrr = float(benchmark_metrics.get("mrr", 0.0)) if isinstance(benchmark_metrics.get("mrr"), (int, float)) else 0.0
    ndcg = (
        float(benchmark_metrics.get("ndcg_at_k", 0.0))
        if isinstance(benchmark_metrics.get("ndcg_at_k"), (int, float))
        else 0.0
    )
    hit_rate = (
        float(benchmark_metrics.get("hit_rate", 0.0))
        if isinstance(benchmark_metrics.get("hit_rate"), (int, float))
        else 0.0
    )
    score = (pass_rate * 0.4) + (hit_rate * 0.25) + (mrr * 0.2) + (ndcg * 0.15)
    return score, {
        "pass_rate": pass_rate,
        "hit_rate": hit_rate,
        "mrr": mrr,
        "ndcg_at_k": ndcg,
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
        "| severity | code | field | message |",
        "|---|---|---|---|",
    ]
    for issue in report.issues:
        lines.append(
            f"| {issue.severity} | `{issue.code}` | {issue.field or '-'} | {issue.message} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_profile_compare_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RAGFlow Profile Compare Report",
        "",
        "| rank | path | score | pass_rate | hit_rate | mrr | ndcg@k |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for index, item in enumerate(report.get("candidates", []), start=1):
        metrics = item.get("metrics", {})
        lines.append(
            f"| {index} | `{item.get('path')}` | {item.get('score', 0):.4f} | "
            f"{metrics.get('pass_rate', 0):.4f} | {metrics.get('hit_rate', 0):.4f} | "
            f"{metrics.get('mrr', 0):.4f} | {metrics.get('ndcg_at_k', 0):.4f} |"
        )
    lines.append("")
    return "\n".join(lines)
