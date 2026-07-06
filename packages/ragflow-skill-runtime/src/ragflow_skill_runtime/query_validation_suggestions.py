"""Deterministic validation query suggestions from retrieval hints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .handoff import RETRIEVAL_HINTS_SCHEMA


VALIDATION_QUERY_SUGGESTIONS_SCHEMA = "ragflow_validation_query_suggestions_v1"
BENCHMARK_QUERIES_SCHEMA = "ragflow_benchmark_queries_v1"
BENCHMARK_QRELS_SCHEMA = "ragflow_benchmark_qrels_v1"


class ValidationQuerySuggestionError(RuntimeError):
    """Raised when validation query suggestion inputs are invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = " ".join(value.split())
    return stripped or None


def _first_text(item: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean_text(item.get(key))
        if value:
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _artifact_expected_chunks(artifact: Mapping[str, Any]) -> list[str]:
    chunks = _string_list(artifact.get("expected_chunks"))
    for key in ("stable_hash", "chunk_hash", "content_sha256", "chunk_id"):
        value = _clean_text(artifact.get(key))
        if value:
            chunks.append(value)
    return sorted(dict.fromkeys(chunks))


def _qrel(
    *,
    query_id: str,
    expected_document: str | None,
    expected_modality: str,
    benchmark_category: str,
    expected_chunks: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "query_id": query_id,
        "expected_modality": expected_modality,
        "benchmark_category": benchmark_category,
        "relevance": 1,
    }
    if expected_document:
        item["expected_documents"] = [expected_document]
    if expected_chunks:
        item["expected_chunks"] = expected_chunks
    return item


def _query(
    *,
    query_id: str,
    question: str,
    benchmark_category: str,
    expected_modality: str | list[str],
    source: str,
    expected_terms: list[str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "benchmark_category": benchmark_category,
        "expected_modality": expected_modality,
        "source": source,
        "llm_invoked": False,
    }
    item: dict[str, Any] = {
        "id": query_id,
        "question": question,
        "min_chunks": 1,
        "metadata": metadata,
    }
    if expected_terms:
        item["expected_terms"] = expected_terms
    return item


def _image_category(artifact: Mapping[str, Any]) -> str:
    kind = (_first_text(artifact, ("semantic_kind", "kind", "type")) or "").casefold()
    if any(token in kind for token in ("diagram", "screenshot", "software")):
        return "diagram_software_screenshot"
    return "visual_identification"


def build_validation_query_suggestions(
    retrieval_hints: Mapping[str, Any],
    *,
    max_tables: int = 3,
    max_images: int = 3,
) -> dict[str, Any]:
    """Build benchmark query/qrels suggestions from retrieval hints without LLM calls."""

    if retrieval_hints.get("schema") != RETRIEVAL_HINTS_SCHEMA:
        raise ValidationQuerySuggestionError(f"retrieval hints schema must be {RETRIEVAL_HINTS_SCHEMA}")
    raw_tables = retrieval_hints.get("table_artifacts", [])
    raw_images = retrieval_hints.get("image_artifacts", [])
    tables = [item for item in raw_tables if isinstance(item, Mapping)][:max_tables] if isinstance(raw_tables, list) else []
    images = [item for item in raw_images if isinstance(item, Mapping)][:max_images] if isinstance(raw_images, list) else []

    queries: list[dict[str, Any]] = []
    qrels: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []

    for index, table in enumerate(tables, start=1):
        label = _first_text(table, ("caption", "source_heading", "title", "document")) or f"table {index}"
        model_labels = _string_list(table.get("model_label_candidates"))
        expected_terms = model_labels[:3]
        query_id = f"table-{index:03d}"
        question = (
            f"Which table evidence for {label} mentions {model_labels[0]}?"
            if model_labels
            else f"What values are captured in the table evidence for {label}?"
        )
        queries.append(
            _query(
                query_id=query_id,
                question=question,
                benchmark_category="table_value",
                expected_modality="table",
                source=f"retrieval_hints.table_artifacts[{index - 1}]",
                expected_terms=expected_terms,
            )
        )
        qrels.append(
            _qrel(
                query_id=query_id,
                expected_document=_first_text(table, ("document", "source_document")),
                expected_modality="table",
                benchmark_category="table_value",
                expected_chunks=_artifact_expected_chunks(table),
            )
        )
        suggestions.append({"id": query_id, "kind": "table", "source_label": label})

    for index, image in enumerate(images, start=1):
        label = _first_text(image, ("caption", "alt_text", "source_heading", "path", "document")) or f"image {index}"
        category = _image_category(image)
        query_id = f"image-{index:03d}"
        queries.append(
            _query(
                query_id=query_id,
                question=f"What visual evidence is shown by {label}?",
                benchmark_category=category,
                expected_modality="image",
                source=f"retrieval_hints.image_artifacts[{index - 1}]",
                expected_terms=[label] if category == "diagram_software_screenshot" else None,
            )
        )
        qrels.append(
            _qrel(
                query_id=query_id,
                expected_document=_first_text(image, ("path", "document", "source_document")),
                expected_modality="image",
                benchmark_category=category,
                expected_chunks=_artifact_expected_chunks(image),
            )
        )
        suggestions.append({"id": query_id, "kind": "image", "source_label": label})

    if tables and images:
        table = tables[0]
        image = images[0]
        table_label = _first_text(table, ("caption", "source_heading", "document")) or "the table"
        image_label = _first_text(image, ("caption", "alt_text", "path", "document")) or "the image"
        query_id = "mixed-table-image-001"
        queries.append(
            _query(
                query_id=query_id,
                question=f"How does {table_label} relate to the visual evidence in {image_label}?",
                benchmark_category="mixed_table_plus_image",
                expected_modality=["table", "image"],
                source="retrieval_hints.table_artifacts[0]+image_artifacts[0]",
            )
        )
        qrels.append(
            _qrel(
                query_id=query_id,
                expected_document=_first_text(table, ("document", "source_document")),
                expected_modality="table",
                benchmark_category="mixed_table_plus_image",
                expected_chunks=_artifact_expected_chunks(table),
            )
        )
        qrels.append(
            _qrel(
                query_id=query_id,
                expected_document=_first_text(image, ("path", "document", "source_document")),
                expected_modality="image",
                benchmark_category="mixed_table_plus_image",
                expected_chunks=_artifact_expected_chunks(image),
            )
        )
        suggestions.append({"id": query_id, "kind": "mixed", "source_label": f"{table_label} + {image_label}"})

    warnings = []
    if not queries:
        warnings.append("retrieval hints did not contain table_artifacts or image_artifacts")

    queries_artifact = {"schema": BENCHMARK_QUERIES_SCHEMA, "queries": queries}
    qrels_artifact = {"schema": BENCHMARK_QRELS_SCHEMA, "qrels": qrels}
    return {
        "ok": bool(queries),
        "schema": VALIDATION_QUERY_SUGGESTIONS_SCHEMA,
        "created_at": _now(),
        "summary": {
            "query_count": len(queries),
            "qrel_count": len(qrels),
            "table_query_count": sum(1 for item in queries if item["metadata"]["benchmark_category"] == "table_value"),
            "image_query_count": sum(1 for item in queries if item["metadata"]["expected_modality"] == "image"),
            "mixed_query_count": sum(1 for item in queries if item["metadata"]["benchmark_category"] == "mixed_table_plus_image"),
            "llm_invoked": False,
            "script_owned_llm_calls": 0,
        },
        "queries_artifact": queries_artifact,
        "qrels_artifact": qrels_artifact,
        "suggestions": suggestions,
        "warnings": warnings,
    }


def render_validation_query_suggestions_markdown(report: Mapping[str, Any]) -> str:
    """Render a Markdown summary for deterministic validation query suggestions."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Validation Query Suggestions",
        "",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- query_count: `{summary.get('query_count', 0)}`",
        f"- qrel_count: `{summary.get('qrel_count', 0)}`",
        f"- llm_invoked: `{str(summary.get('llm_invoked', False)).lower()}`",
        f"- script_owned_llm_calls: `{summary.get('script_owned_llm_calls', 0)}`",
        "",
        "| id | kind | source |",
        "| --- | --- | --- |",
    ]
    suggestions = report.get("suggestions", [])
    if isinstance(suggestions, list) and suggestions:
        for item in suggestions:
            if isinstance(item, Mapping):
                lines.append(f"| `{item.get('id', '')}` | {item.get('kind', '')} | {item.get('source_label', '')} |")
    else:
        lines.append("| - | - | - |")
    warnings = report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"
