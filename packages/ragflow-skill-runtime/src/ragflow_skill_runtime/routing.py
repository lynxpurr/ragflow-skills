"""Deterministic routing helpers for public RAGFlow query skills."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .config import read_config_file


class RoutingError(RuntimeError):
    """Raised when routing inputs are invalid."""


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    raise RoutingError(f"{field_name} must be a string or list of strings")


def _tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", text.lower()) if token}


@dataclass(frozen=True)
class RoutingKnowledgeBase:
    name: str
    dataset_id: str
    description: str = ""
    hints: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int) -> "RoutingKnowledgeBase":
        name = data.get("name") or data.get("kb") or data.get("dataset_name")
        dataset_id = data.get("dataset_id") or data.get("id")
        if not isinstance(name, str) or not name.strip():
            raise RoutingError(f"knowledge_bases[{index}].name is required")
        if not isinstance(dataset_id, str) or not dataset_id.strip():
            raise RoutingError(f"knowledge_bases[{index}].dataset_id is required")
        params = data.get("params", {})
        if not isinstance(params, dict):
            raise RoutingError(f"knowledge_bases[{index}].params must be an object")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise RoutingError(f"knowledge_bases[{index}].metadata must be an object")
        return cls(
            name=name.strip(),
            dataset_id=dataset_id.strip(),
            description=str(data.get("description") or ""),
            hints=_string_list(data.get("hints"), field_name=f"knowledge_bases[{index}].hints"),
            params=dict(params),
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoutingConfig:
    version: str
    knowledge_bases: list[RoutingKnowledgeBase]
    default_kb: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoutingConfig":
        raw_items = data.get("knowledge_bases") or data.get("kbs")
        if not isinstance(raw_items, list) or not raw_items:
            raise RoutingError("routing config requires a non-empty knowledge_bases list")
        items = []
        seen_names: set[str] = set()
        seen_ids: set[str] = set()
        for index, item in enumerate(raw_items):
            if not isinstance(item, Mapping):
                raise RoutingError(f"knowledge_bases[{index}] must be an object")
            kb = RoutingKnowledgeBase.from_dict(item, index=index)
            if kb.name in seen_names:
                raise RoutingError(f"duplicate routing KB name: {kb.name}")
            if kb.dataset_id in seen_ids:
                raise RoutingError(f"duplicate routing dataset_id: {kb.dataset_id}")
            seen_names.add(kb.name)
            seen_ids.add(kb.dataset_id)
            items.append(kb)
        default_kb = data.get("default_kb") or data.get("default")
        if default_kb is not None and not isinstance(default_kb, str):
            raise RoutingError("default_kb must be a string")
        if default_kb and not any(default_kb in {kb.name, kb.dataset_id} for kb in items):
            raise RoutingError(f"default_kb does not match a configured KB: {default_kb}")
        return cls(
            version=str(data.get("version") or "0.1"),
            knowledge_bases=items,
            default_kb=default_kb,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "schema": "ragflow_routing_config_v1",
            "default_kb": self.default_kb,
            "knowledge_bases": [kb.to_dict() for kb in self.knowledge_bases],
        }


@dataclass(frozen=True)
class RouteCandidate:
    kb: RoutingKnowledgeBase
    score: float
    matched_hints: list[str] = field(default_factory=list)
    reason: str = "hint"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.kb.name,
            "dataset_id": self.kb.dataset_id,
            "score": self.score,
            "matched_hints": list(self.matched_hints),
            "reason": self.reason,
            "params": self.kb.params,
            "description": self.kb.description,
        }


@dataclass(frozen=True)
class RouteResult:
    question: str
    selected: RouteCandidate | None
    candidates: list[RouteCandidate]

    @property
    def ok(self) -> bool:
        return self.selected is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema": "ragflow_route_result_v1",
            "question": self.question,
            "selected": self.selected.to_dict() if self.selected else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def load_routing_config(path: str | Path) -> RoutingConfig:
    """Load a routing config from JSON or simple YAML."""

    route_path = Path(path)
    try:
        if route_path.suffix.lower() == ".json":
            data = json.loads(route_path.read_text(encoding="utf-8"))
        else:
            data = read_config_file(route_path)
    except FileNotFoundError as exc:
        raise RoutingError(f"routing config not found: {route_path}") from exc
    except json.JSONDecodeError as exc:
        raise RoutingError(f"routing config is not valid JSON: {route_path}") from exc
    if not isinstance(data, Mapping):
        raise RoutingError("routing config must be an object")
    return RoutingConfig.from_dict(data)


def _score_kb(question: str, kb: RoutingKnowledgeBase) -> RouteCandidate:
    question_lower = question.lower()
    question_tokens = _tokenize(question)
    matched_hints: list[str] = []
    score = 0.0
    for hint in kb.hints:
        hint_lower = hint.lower()
        if hint_lower and hint_lower in question_lower:
            matched_hints.append(hint)
            score += 10.0
            continue
        hint_tokens = _tokenize(hint)
        overlap = question_tokens.intersection(hint_tokens)
        if overlap:
            matched_hints.append(hint)
            score += float(len(overlap))
    name_tokens = _tokenize(kb.name)
    if question_tokens.intersection(name_tokens):
        score += 0.5
    description_tokens = _tokenize(kb.description)
    if description_tokens:
        score += min(len(question_tokens.intersection(description_tokens)) * 0.25, 1.0)
    return RouteCandidate(kb=kb, score=score, matched_hints=matched_hints)


def route_question(config: RoutingConfig, question: str) -> RouteResult:
    """Route a question to the best configured KB using deterministic hints."""

    if not question.strip():
        raise RoutingError("question is required")
    candidates = sorted(
        (_score_kb(question, kb) for kb in config.knowledge_bases),
        key=lambda candidate: (-candidate.score, candidate.kb.name),
    )
    selected = candidates[0] if candidates and candidates[0].score > 0 else None
    if selected is None and config.default_kb:
        default = next(
            kb for kb in config.knowledge_bases if config.default_kb in {kb.name, kb.dataset_id}
        )
        selected = RouteCandidate(kb=default, score=0.0, reason="default")
        candidates = [selected] + [candidate for candidate in candidates if candidate.kb != default]
    return RouteResult(question=question, selected=selected, candidates=candidates)


def load_route_test_queries(path: str | Path) -> list[dict[str, Any]]:
    """Load route-test queries from a compact JSON file."""

    test_path = Path(path)
    try:
        data = json.loads(test_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoutingError(f"route test query file not found: {test_path}") from exc
    except json.JSONDecodeError as exc:
        raise RoutingError(f"route test query file is not valid JSON: {test_path}") from exc
    raw_queries = data.get("queries") if isinstance(data, Mapping) else data
    if not isinstance(raw_queries, list) or not raw_queries:
        raise RoutingError("route test file must be a non-empty list or object with queries")
    queries: list[dict[str, Any]] = []
    for index, item in enumerate(raw_queries):
        if not isinstance(item, Mapping):
            raise RoutingError(f"queries[{index}] must be an object")
        question = item.get("question") or item.get("query")
        expected = item.get("expected_kb") or item.get("expected_dataset_id")
        if not isinstance(question, str) or not question.strip():
            raise RoutingError(f"queries[{index}].question is required")
        if not isinstance(expected, str) or not expected.strip():
            raise RoutingError(f"queries[{index}].expected_kb or expected_dataset_id is required")
        queries.append(
            {
                "id": str(item.get("id") or f"q{index + 1}"),
                "question": question.strip(),
                "expected": expected.strip(),
            }
        )
    return queries


def run_route_tests(config: RoutingConfig, queries: list[dict[str, Any]]) -> dict[str, Any]:
    """Run deterministic route regression checks."""

    cases = []
    passed = 0
    for query in queries:
        result = route_question(config, query["question"])
        selected = result.selected
        actual = selected.kb.name if selected else None
        actual_id = selected.kb.dataset_id if selected else None
        ok = query["expected"] in {actual, actual_id}
        if ok:
            passed += 1
        cases.append(
            {
                "id": query["id"],
                "question": query["question"],
                "expected": query["expected"],
                "actual": actual,
                "actual_dataset_id": actual_id,
                "passed": ok,
                "route": result.to_dict(),
            }
        )
    total = len(cases)
    return {
        "ok": passed == total,
        "schema": "ragflow_route_test_report_v1",
        "metrics": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "accuracy": passed / total if total else 0.0,
        },
        "cases": cases,
    }


def render_route_test_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown route-test report."""

    metrics = report.get("metrics", {})
    lines = [
        "# RAGFlow Route Test Report",
        "",
        f"- Status: `{'passed' if report.get('ok') else 'failed'}`",
        f"- Accuracy: `{float(metrics.get('accuracy', 0.0)):.2%}`",
        "",
        "| id | status | expected | actual |",
        "|---|---|---|---|",
    ]
    for case in report.get("cases", []):
        lines.append(
            f"| `{case.get('id')}` | {'passed' if case.get('passed') else 'failed'} | "
            f"`{case.get('expected')}` | `{case.get('actual') or '-'}` |"
        )
    lines.append("")
    return "\n".join(lines)
