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


ROUTE_REPORT_SCHEMA = "ragflow_route_report_v1"


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


def _rate(count: int | float, total: int | float) -> float:
    return round(float(count) / float(total), 4) if total else 0.0


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _matches_kb_ref(value: Any, kb: "RoutingKnowledgeBase") -> bool:
    return isinstance(value, str) and value in {kb.name, kb.dataset_id}


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


def _hint_tokens(hints: list[str]) -> set[str]:
    tokens: set[str] = set()
    for hint in hints:
        tokens.update(_tokenize(hint))
    return tokens


def _short_hint(hint: str) -> bool:
    compact = hint.strip()
    if not compact:
        return False
    token_count = len(_tokenize(compact))
    return len(compact) <= 8 or token_count <= 2


def _query_category(query: Mapping[str, Any]) -> str:
    for key in ("category", "type", "query_type"):
        value = query.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "uncategorized"


def _query_locale(query: Mapping[str, Any]) -> str:
    value = query.get("locale") or query.get("language")
    return value.strip() if isinstance(value, str) and value.strip() else "unknown"


def _route_case_metadata(query: Mapping[str, Any]) -> dict[str, str]:
    metadata = {
        "category": _query_category(query),
        "locale": _query_locale(query),
    }
    negative_class = query.get("negative_class")
    if isinstance(negative_class, str) and negative_class.strip():
        metadata["negative_class"] = negative_class.strip()
    return metadata


def _route_report_empty_route_test() -> dict[str, Any]:
    return {
        "ok": True,
        "schema": "ragflow_route_test_report_v1",
        "metrics": {"total": 0, "passed": 0, "failed": 0, "accuracy": 0.0},
        "cases": [],
    }


def run_route_report(
    config: RoutingConfig,
    queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize deterministic routing quality signals."""

    queries = list(queries or [])
    route_results = [route_question(config, query["question"]) for query in queries]
    cases: list[dict[str, Any]] = []
    passed = 0
    low_confidence_cases: list[dict[str, Any]] = []
    ambiguous_cases: list[dict[str, Any]] = []
    empty_cases: list[dict[str, Any]] = []
    hint_coverage: dict[str, dict[str, Any]] = {}
    hint_tokens_by_kb: dict[str, set[str]] = {}
    matched_hints_by_kb: dict[str, set[str]] = {}
    params_coverage: dict[str, bool] = {}
    word_boundary_hints: list[dict[str, Any]] = []
    substring_conflicts: list[dict[str, Any]] = []
    total_hints = 0
    total_hint_matches = 0

    for kb in config.knowledge_bases:
        hint_tokens = _hint_tokens(kb.hints)
        hint_tokens_by_kb[kb.name] = hint_tokens
        matched_hints_by_kb[kb.name] = set()
        params_coverage[kb.name] = bool(kb.params)
        short_hints = [hint for hint in kb.hints if _short_hint(hint)]
        if short_hints:
            word_boundary_hints.append(
                {
                    "kb": kb.name,
                    "dataset_id": kb.dataset_id,
                    "hints": short_hints,
                    "reason": "short hints need route-test coverage for word-boundary conflicts",
                }
            )
        total_hints += len(kb.hints)

    for left_index, left_kb in enumerate(config.knowledge_bases):
        for left_hint in left_kb.hints:
            left_lower = left_hint.lower().strip()
            if not left_lower:
                continue
            for right_kb in config.knowledge_bases[left_index + 1 :]:
                for right_hint in right_kb.hints:
                    right_lower = right_hint.lower().strip()
                    if not right_lower or left_lower == right_lower:
                        continue
                    shorter, longer = (
                        (left_hint, right_hint) if len(left_lower) < len(right_lower) else (right_hint, left_hint)
                    )
                    shorter_lower = shorter.lower().strip()
                    longer_lower = longer.lower().strip()
                    if shorter_lower and shorter_lower in longer_lower:
                        substring_conflicts.append(
                            {
                                "kb_a": left_kb.name,
                                "kb_b": right_kb.name,
                                "hint_a": left_hint,
                                "hint_b": right_hint,
                                "shorter_hint": shorter,
                                "longer_hint": longer,
                            }
                        )

    for query, result in zip(queries, route_results, strict=False):
        case = result.to_dict()
        selected = result.selected
        matched_hints = []
        if selected:
            matched_hints = list(selected.matched_hints)
            total_hint_matches += len(matched_hints)
            matched_hints_by_kb[selected.kb.name].update(matched_hints)
        expected = query["expected"]
        passed_case = expected in {
            selected.kb.name if selected else None,
            selected.kb.dataset_id if selected else None,
        }
        case.update(
            {
                "id": query["id"],
                "expected": expected,
                "passed": passed_case,
                "actual": selected.kb.name if selected else None,
                "actual_dataset_id": selected.kb.dataset_id if selected else None,
                "matched_hints": matched_hints,
                "selected_score": selected.score if selected else None,
                "selected_reason": selected.reason if selected else None,
                "candidate_count": len(result.candidates),
                "low_confidence": bool(selected and selected.score < 2.0),
                "ambiguous": bool(
                    result.candidates
                    and len(result.candidates) > 1
                    and result.candidates[0].score > 0
                    and result.candidates[1].score == result.candidates[0].score
                ),
                "empty_route": selected is None,
                **_route_case_metadata(query),
            }
        )
        if passed_case:
            passed += 1
        if case["low_confidence"]:
            low_confidence_cases.append(case)
        if case["ambiguous"]:
            ambiguous_cases.append(case)
        if case["empty_route"]:
            empty_cases.append(case)
        cases.append(case)

    route_test_report = run_route_tests(config, queries) if queries else _route_report_empty_route_test()
    missing_route_tests = []
    for kb in config.knowledge_bases:
        expected_cases = [case for case in cases if _matches_kb_ref(case.get("expected"), kb)]
        passing_cases = [case for case in expected_cases if case.get("passed")]
        routed_cases = [
            case
            for case in cases
            if case.get("actual_dataset_id") == kb.dataset_id or case.get("actual") == kb.name
        ]
        matched_hint_set = matched_hints_by_kb[kb.name]
        coverage = _rate(len(matched_hint_set), len(kb.hints) if kb.hints else 0)
        if not expected_cases:
            missing_route_tests.append(
                {
                    "name": kb.name,
                    "dataset_id": kb.dataset_id,
                    "reason": "no route-test query expects this KB",
                }
            )
        hint_coverage[kb.name] = {
            "name": kb.name,
            "dataset_id": kb.dataset_id,
            "hint_count": len(kb.hints),
            "matched_hint_count": len(matched_hint_set),
            "matched_hints": sorted(matched_hint_set),
            "expected_query_count": len(expected_cases),
            "passing_query_count": len(passing_cases),
            "routed_query_count": len(routed_cases),
            "question_count": len(routed_cases),
            "coverage": coverage,
            "route_test_coverage": _rate(len(expected_cases), len(queries)),
            "route_test_pass_rate": _rate(len(passing_cases), len(expected_cases)),
            "params": dict(kb.params),
            "has_params": bool(kb.params),
            "short_hints": [hint for hint in kb.hints if _short_hint(hint)],
            "hints": list(kb.hints),
            "hint_tokens": sorted(hint_tokens_by_kb[kb.name]),
        }

    category_totals: dict[str, dict[str, Any]] = {}
    locale_totals: dict[str, dict[str, Any]] = {}
    negative_class_totals: dict[str, dict[str, Any]] = {}
    for case in cases:
        for key, target in (
            ("category", category_totals),
            ("locale", locale_totals),
            ("negative_class", negative_class_totals),
        ):
            value = case.get(key)
            if not isinstance(value, str) or not value:
                continue
            bucket = target.setdefault(value, {"total": 0, "passed": 0, "failed": 0})
            bucket["total"] += 1
            if case.get("passed"):
                bucket["passed"] += 1
            else:
                bucket["failed"] += 1
    for target in (category_totals, locale_totals, negative_class_totals):
        for bucket in target.values():
            bucket["pass_rate"] = _rate(bucket["passed"], bucket["total"])

    missing_params = [
        {
            "name": kb.name,
            "dataset_id": kb.dataset_id,
            "reason": "no per-KB retrieval params configured",
        }
        for kb in config.knowledge_bases
        if not kb.params
    ]

    route_scores = [float(case.get("selected_score") or 0.0) for case in cases]
    route_score_avg = _average(route_scores)
    low_confidence_rate = _rate(len(low_confidence_cases), len(cases))
    ambiguous_rate = _rate(len(ambiguous_cases), len(cases))
    empty_rate = _rate(len(empty_cases), len(cases))
    route_test_metrics = route_test_report.get("metrics", {})
    route_pass_rate = route_test_metrics.get("accuracy", 0.0) if isinstance(route_test_metrics, Mapping) else 0.0
    return {
        "ok": True,
        "schema": ROUTE_REPORT_SCHEMA,
        "summary": {
            "kb_count": len(config.knowledge_bases),
            "query_count": len(cases),
            "route_test_pass_rate": route_pass_rate,
            "route_pass_count": passed,
            "route_fail_count": len(cases) - passed,
            "low_confidence_count": len(low_confidence_cases),
            "low_confidence_rate": low_confidence_rate,
            "ambiguous_count": len(ambiguous_cases),
            "ambiguous_rate": ambiguous_rate,
            "empty_route_count": len(empty_cases),
            "empty_route_rate": empty_rate,
            "route_score_average": route_score_avg,
            "route_score_min": min((float(case.get("selected_score") or 0.0) for case in cases), default=0.0),
            "route_score_max": max((float(case.get("selected_score") or 0.0) for case in cases), default=0.0),
            "hint_count": total_hints,
            "hint_match_count": total_hint_matches,
            "hint_match_rate": _rate(total_hint_matches, total_hints),
            "params_coverage_count": sum(1 for has_params in params_coverage.values() if has_params),
            "params_coverage_rate": _rate(sum(1 for has_params in params_coverage.values() if has_params), len(params_coverage)),
            "missing_route_test_count": len(missing_route_tests),
            "missing_params_count": len(missing_params),
            "short_hint_kb_count": len(word_boundary_hints),
            "substring_conflict_count": len(substring_conflicts),
            "category_count": len(category_totals),
            "locale_count": len(locale_totals),
            "negative_class_count": len(negative_class_totals),
            "route_test_total": route_test_metrics.get("total", 0) if isinstance(route_test_metrics, Mapping) else 0,
        },
        "route_test": route_test_report,
        "hint_coverage": list(hint_coverage.values()),
        "missing_route_tests": missing_route_tests,
        "missing_params": missing_params,
        "word_boundary_hints": word_boundary_hints,
        "substring_conflicts": substring_conflicts,
        "coverage_by_category": category_totals,
        "coverage_by_locale": locale_totals,
        "coverage_by_negative_class": negative_class_totals,
        "low_confidence_routes": low_confidence_cases,
        "ambiguous_routes": ambiguous_cases,
        "empty_routes": empty_cases,
        "kb_params": [
            {
                "name": kb.name,
                "dataset_id": kb.dataset_id,
                "has_params": bool(kb.params),
                "params": dict(kb.params),
            }
            for kb in config.knowledge_bases
        ],
        "recommendations": [
            "Add route-test coverage for KBs that have hints but no passing query coverage.",
            "Add per-KB params where route coverage depends on top_k or similarity_threshold defaults.",
            "Review short hints and ambiguous matches for word-boundary conflicts before expanding route rules.",
        ],
    }


def render_route_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown route quality report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Route Report",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- query_count: `{summary.get('query_count', 0)}`",
        f"- route_test_pass_rate: `{summary.get('route_test_pass_rate', 0)}`",
        f"- low_confidence_rate: `{summary.get('low_confidence_rate', 0)}`",
        f"- ambiguous_rate: `{summary.get('ambiguous_rate', 0)}`",
        f"- empty_route_rate: `{summary.get('empty_route_rate', 0)}`",
        f"- missing_route_tests: `{summary.get('missing_route_test_count', 0)}`",
        f"- missing_params: `{summary.get('missing_params_count', 0)}`",
        f"- substring_conflicts: `{summary.get('substring_conflict_count', 0)}`",
        "",
        "## KB Coverage",
        "",
        "| KB | route tests | pass rate | hints | matched | hint coverage | params |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("hint_coverage", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| `{name}` | {expected_query_count} | {route_test_pass_rate:.2f} | {hint_count} | "
            "{matched_hint_count} | {coverage:.2f} | {params} |".format(
                name=item.get("name", ""),
                expected_query_count=int(item.get("expected_query_count", 0)),
                route_test_pass_rate=float(item.get("route_test_pass_rate", 0.0)),
                hint_count=int(item.get("hint_count", 0)),
                matched_hint_count=int(item.get("matched_hint_count", 0)),
                coverage=float(item.get("coverage", 0.0)),
                params="yes" if item.get("has_params") else "no",
            )
        )
    lines.extend(["", "## Route Test", ""])
    route_test = report.get("route_test", {}) if isinstance(report.get("route_test"), Mapping) else {}
    metrics = route_test.get("metrics", {}) if isinstance(route_test.get("metrics"), Mapping) else {}
    lines.extend(
        [
            f"- total: `{metrics.get('total', 0)}`",
            f"- passed: `{metrics.get('passed', 0)}`",
            f"- failed: `{metrics.get('failed', 0)}`",
        ]
    )
    lines.extend(["", "## Missing Route Tests", ""])
    missing_route_tests = report.get("missing_route_tests", []) if isinstance(report.get("missing_route_tests"), list) else []
    if not missing_route_tests:
        lines.append("- None")
    else:
        for item in missing_route_tests:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('name', '')}` `{item.get('dataset_id', '')}`")
    lines.extend(["", "## Missing Params", ""])
    missing_params = report.get("missing_params", []) if isinstance(report.get("missing_params"), list) else []
    if not missing_params:
        lines.append("- None")
    else:
        for item in missing_params:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('name', '')}` `{item.get('dataset_id', '')}`")
    lines.extend(["", "## Category Coverage", ""])
    coverage_by_category = (
        report.get("coverage_by_category", {}) if isinstance(report.get("coverage_by_category"), Mapping) else {}
    )
    if not coverage_by_category:
        lines.append("- None")
    else:
        lines.extend(["| category | total | passed | pass rate |", "| --- | ---: | ---: | ---: |"])
        for category, item in sorted(coverage_by_category.items()):
            if isinstance(item, Mapping):
                lines.append(
                    "| `{category}` | {total} | {passed} | {pass_rate:.2f} |".format(
                        category=category,
                        total=int(item.get("total", 0)),
                        passed=int(item.get("passed", 0)),
                        pass_rate=float(item.get("pass_rate", 0.0)),
                    )
                )
    lines.extend(["", "## Low Confidence", ""])
    low_confidence = report.get("low_confidence_routes", []) if isinstance(report.get("low_confidence_routes"), list) else []
    if not low_confidence:
        lines.append("- None")
    else:
        for case in low_confidence[:10]:
            if isinstance(case, Mapping):
                lines.append(f"- `{case.get('id', '')}` `{case.get('question', '')}` score={case.get('selected_score', 0)}")
    lines.extend(["", "## Ambiguous", ""])
    ambiguous = report.get("ambiguous_routes", []) if isinstance(report.get("ambiguous_routes"), list) else []
    if not ambiguous:
        lines.append("- None")
    else:
        for case in ambiguous[:10]:
            if isinstance(case, Mapping):
                lines.append(f"- `{case.get('id', '')}` `{case.get('question', '')}`")
    lines.extend(["", "## Empty Routes", ""])
    empty_routes = report.get("empty_routes", []) if isinstance(report.get("empty_routes"), list) else []
    if not empty_routes:
        lines.append("- None")
    else:
        for case in empty_routes[:10]:
            if isinstance(case, Mapping):
                lines.append(f"- `{case.get('id', '')}` `{case.get('question', '')}`")
    lines.extend(["", "## Word Boundary Hints", ""])
    word_boundary_hints = report.get("word_boundary_hints", []) if isinstance(report.get("word_boundary_hints"), list) else []
    if not word_boundary_hints:
        lines.append("- None")
    else:
        for item in word_boundary_hints[:10]:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('kb', '')}`: {', '.join(str(hint) for hint in item.get('hints', []))}")
    lines.extend(["", "## Substring Conflicts", ""])
    substring_conflicts = report.get("substring_conflicts", []) if isinstance(report.get("substring_conflicts"), list) else []
    if not substring_conflicts:
        lines.append("- None")
    else:
        for item in substring_conflicts[:10]:
            if isinstance(item, Mapping):
                lines.append(
                    "- `{kb_a}` `{hint_a}` overlaps `{kb_b}` `{hint_b}`".format(
                        kb_a=item.get("kb_a", ""),
                        hint_a=item.get("hint_a", ""),
                        kb_b=item.get("kb_b", ""),
                        hint_b=item.get("hint_b", ""),
                    )
                )
    return "\n".join(lines) + "\n"


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
        query = {
            "id": str(item.get("id") or f"q{index + 1}"),
            "question": question.strip(),
            "expected": expected.strip(),
        }
        for key in ("category", "type", "query_type", "locale", "language", "negative_class"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                query[key] = value.strip()
        queries.append(query)
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
