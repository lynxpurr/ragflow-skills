"""Deterministic query rewrite planning helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


QUERY_REWRITE_PLAN_SCHEMA = "ragflow_query_rewrite_plan_v1"

_TRANSLATION_STUB_TERMS = {
    "api": ["接口"],
    "apis": ["接口"],
    "authentication": ["认证"],
    "auth": ["认证"],
    "chunk": ["分块"],
    "chunks": ["分块"],
    "citation": ["引用"],
    "citations": ["引用"],
    "config": ["配置"],
    "configuration": ["配置"],
    "dataset": ["数据集"],
    "datasets": ["数据集"],
    "document": ["文档"],
    "documents": ["文档"],
    "evidence": ["证据"],
    "index": ["索引"],
    "metadata": ["元数据"],
    "profile": ["配置档"],
    "query": ["查询"],
    "rerank": ["重排"],
    "retrieval": ["检索"],
    "rewrite": ["改写"],
    "route": ["路由"],
    "routing": ["路由"],
    "runtime": ["运行时"],
    "source": ["来源"],
    "sources": ["来源"],
    "trace": ["追踪"],
    "validation": ["验证"],
}


class QueryRewriteError(ValueError):
    """Raised when query rewrite input cannot be planned safely."""


def _normalize_query(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise QueryRewriteError(f"{field_name} must be a string")
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        raise QueryRewriteError(f"{field_name} must be non-empty")
    return normalized


def _dedupe_queries(queries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in queries:
        query = _normalize_query(item.get("query"), field_name="query")
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append({**dict(item), "query": query})
    return deduped


def _simple_rewrite_queries(question: str) -> list[str]:
    variants: list[str] = []
    normalized = _normalize_query(question, field_name="question")
    without_trailing = normalized.rstrip("?.!。！？").strip()
    lowered = without_trailing.lower()
    if without_trailing and without_trailing != normalized:
        variants.append(without_trailing)
    replacements = [
        (r"^how do i\s+", "how to "),
        (r"^how can i\s+", "how to "),
        (r"^what is the\s+", ""),
        (r"^what is\s+", ""),
        (r"^where is the\s+", ""),
        (r"^where can i find\s+", ""),
    ]
    for pattern, replacement in replacements:
        rewritten = re.sub(pattern, replacement, lowered, count=1).strip()
        if rewritten and rewritten != lowered:
            variants.append(rewritten)
    tokens = re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]+", without_trailing)
    if 2 <= len(tokens) <= 8:
        variants.append(" ".join(tokens))
    return variants


def _translate_stub_queries(question: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z_]+|[\u4e00-\u9fff]+", question.lower())
    translated_terms: list[str] = []
    for token in tokens:
        for term in _TRANSLATION_STUB_TERMS.get(token, []):
            if term not in translated_terms:
                translated_terms.append(term)
    if not translated_terms:
        return []
    return [f"{question} {' '.join(translated_terms)}"]


def _multi_query_item(item: Any, *, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        query = _normalize_query(item, field_name=f"queries[{index}]")
        return {
            "id": f"multi-{index + 1}",
            "query": query,
            "source": "multi_query",
            "kind": "generated",
        }
    if not isinstance(item, Mapping):
        raise QueryRewriteError(f"queries[{index}] must be a string or object")
    query = _normalize_query(item.get("query") or item.get("question"), field_name=f"queries[{index}].query")
    item_id = str(item.get("id") or f"multi-{index + 1}").strip() or f"multi-{index + 1}"
    source = str(item.get("source") or "multi_query").strip() or "multi_query"
    kind = str(item.get("kind") or "generated").strip() or "generated"
    payload = {
        "id": item_id,
        "query": query,
        "source": source,
        "kind": kind,
    }
    if isinstance(item.get("metadata"), Mapping):
        payload["metadata"] = dict(item["metadata"])
    return payload


def load_multi_query_file(path: str | Path) -> list[dict[str, Any]]:
    """Load host-owned multi-query variants from JSON."""

    query_path = Path(path)
    try:
        data = json.loads(query_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QueryRewriteError(f"multi-query file not found: {query_path}") from exc
    except json.JSONDecodeError as exc:
        raise QueryRewriteError(f"multi-query file is not valid JSON: {query_path}") from exc

    raw_queries = data.get("queries") if isinstance(data, Mapping) else data
    if not isinstance(raw_queries, list) or not raw_queries:
        raise QueryRewriteError("multi-query file must be a non-empty list or object with queries")
    return [_multi_query_item(item, index=index) for index, item in enumerate(raw_queries)]


def build_query_rewrite_plan(
    question: str,
    *,
    mode: str = "none",
    multi_queries: Sequence[Mapping[str, Any]] | None = None,
    llm_configured: bool = False,
) -> dict[str, Any]:
    """Build a traceable query rewrite plan without calling external services."""

    original_query = _normalize_query(question, field_name="question")
    normalized_mode = (mode or "none").strip().lower()
    if normalized_mode not in {"none", "simple", "translate", "hyde"}:
        raise QueryRewriteError("rewrite mode must be one of: none, simple, translate, hyde")
    if normalized_mode == "hyde":
        if not llm_configured:
            raise QueryRewriteError(
                "rewrite mode hyde requires explicit LLM config; set llm_base_url and llm_api_key"
            )
        raise QueryRewriteError(
            "rewrite mode hyde requires a host-owned LLM rewrite adapter; script-owned HyDE generation is deferred"
        )

    generated: list[dict[str, Any]] = []
    if normalized_mode == "simple":
        for index, query in enumerate(_simple_rewrite_queries(original_query), start=1):
            generated.append(
                {
                    "id": f"rewrite-simple-{index}",
                    "query": query,
                    "source": "rewrite",
                    "kind": "simple",
                }
            )
    elif normalized_mode == "translate":
        for index, query in enumerate(_translate_stub_queries(original_query), start=1):
            generated.append(
                {
                    "id": f"rewrite-translate-{index}",
                    "query": query,
                    "source": "rewrite",
                    "kind": "translated_stub",
                }
            )

    for item in multi_queries or []:
        generated.append(dict(item))

    original = {
        "id": "original",
        "query": original_query,
        "source": "original",
        "kind": "original",
    }
    retrieval_queries = _dedupe_queries([original, *generated])
    generated_queries = [item for item in retrieval_queries if item["id"] != "original"]
    return {
        "ok": True,
        "schema": QUERY_REWRITE_PLAN_SCHEMA,
        "mode": normalized_mode,
        "original_query": original_query,
        "generated_queries": generated_queries,
        "retrieval_queries": retrieval_queries,
        "summary": {
            "generated_query_count": len(generated_queries),
            "retrieval_query_count": len(retrieval_queries),
            "llm_calls": 0,
            "llm_configured": bool(llm_configured),
        },
        "warnings": []
        if generated_queries or normalized_mode == "none"
        else [f"rewrite mode {normalized_mode} produced no deterministic query variants"],
    }


def render_query_rewrite_markdown(plan: Mapping[str, Any]) -> str:
    """Render a compact Markdown query rewrite plan."""

    summary = plan.get("summary", {}) if isinstance(plan.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Query Rewrite Plan",
        "",
        f"- schema: `{plan.get('schema', QUERY_REWRITE_PLAN_SCHEMA)}`",
        f"- mode: `{plan.get('mode', '')}`",
        f"- original_query: `{plan.get('original_query', '')}`",
        f"- generated_query_count: `{summary.get('generated_query_count', 0)}`",
        f"- retrieval_query_count: `{summary.get('retrieval_query_count', 0)}`",
        "",
        "## Retrieval Queries",
        "",
        "| id | kind | source | query |",
        "| --- | --- | --- | --- |",
    ]
    for item in plan.get("retrieval_queries", []):
        if not isinstance(item, Mapping):
            continue
        query = str(item.get("query", "")).replace("|", "\\|")
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('kind', '')}` | `{item.get('source', '')}` | {query} |"
        )
    warnings = [str(item) for item in plan.get("warnings", []) if str(item)]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"
