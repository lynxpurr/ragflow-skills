"""Rich handoff sidecars for portable RAGFlow document packages."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_convert import sha256_file
from .doc_quality import DocQualityError, load_doc_manifest_payload


HANDOFF_PACKAGE_SCHEMA = "ragflow_handoff_package_v1"
DOCUMENT_METADATA_SCHEMA = "ragflow_document_metadata_v1"
ARTIFACT_INDEX_SCHEMA = "ragflow_artifact_index_v1"
PROFILE_SUGGESTIONS_SCHEMA = "ragflow_profile_suggestions_v1"
RETRIEVAL_HINTS_SCHEMA = "ragflow_retrieval_hints_v1"
ASSISTANT_PROFILE_SCHEMA = "ragflow_assistant_profile_v1"
ASSISTANT_TEST_PLAN_SCHEMA = "ragflow_assistant_test_plan_v1"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
NUMERIC_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:\s?[%A-Za-zμ°/-]+)?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
CJK_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")

STOPWORDS = {
    "about",
    "after",
    "and",
    "are",
    "body",
    "can",
    "for",
    "from",
    "how",
    "into",
    "the",
    "this",
    "under",
    "what",
    "when",
    "where",
    "which",
    "with",
}


class HandoffError(RuntimeError):
    """Raised when a rich handoff package cannot be produced or inspected."""


@dataclass(frozen=True)
class HandoffPaths:
    root: Path
    doc_manifest: Path
    metadata: Path
    artifact_index: Path
    profile_suggestions: Path
    package_readme: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "doc_manifest": str(self.doc_manifest),
            "metadata": str(self.metadata),
            "artifact_index": str(self.artifact_index),
            "profile_suggestions": str(self.profile_suggestions),
            "package_readme": str(self.package_readme),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HandoffError(f"required handoff file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffError(f"handoff file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HandoffError(f"handoff file must contain a JSON object: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _resolve_handoff_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def _source_root(manifest: Mapping[str, Any], *, root: Path) -> Path:
    raw = manifest.get("source_root") or "."
    base = Path(str(raw))
    if not base.is_absolute():
        base = root / base
    return base


def _manifest_documents(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_documents = manifest.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise HandoffError("doc_manifest.documents must be a non-empty list")
    documents = [item for item in raw_documents if isinstance(item, Mapping)]
    if len(documents) != len(raw_documents):
        raise HandoffError("doc_manifest.documents must contain only objects")
    return documents


def _file_record(path: Path, *, root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": _relative(path, root),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["size_bytes"] = path.stat().st_size
        record["sha256"] = sha256_file(path)
        mime_type, _encoding = mimetypes.guess_type(path.name)
        if mime_type:
            record["mime_type"] = mime_type
    return record


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}:
        return "image"
    if suffix in {".csv", ".tsv", ".xlsx", ".xls"}:
        return "table"
    if suffix in {".json", ".yaml", ".yml", ".txt", ".log"}:
        return "raw"
    return "artifact"


def _source_inventory_record(
    *,
    source_path: str,
    source_file: Path | None,
    manifest_item: Mapping[str, Any],
) -> dict[str, Any]:
    mime_type, _encoding = mimetypes.guess_type(source_path)
    exists = bool(source_file and source_file.is_file())
    record: dict[str, Any] = {
        "source_path": source_path,
        "source_format": Path(source_path).suffix.lower().lstrip(".") if source_path else None,
        "mime_hint": mime_type,
        "size_bytes": source_file.stat().st_size if exists and source_file else None,
        "sha256": manifest_item.get("sha256") or (sha256_file(source_file) if exists and source_file else None),
        "language_hint": manifest_item.get("language"),
        "exists_in_handoff": exists,
    }
    return record


def make_document_metadata_payload(
    *,
    handoff_root: str | Path,
    doc_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Create document-level source and Markdown metadata for a handoff."""

    root = Path(handoff_root)
    source_base = _source_root(doc_manifest, root=root)
    documents = []
    for item in _manifest_documents(doc_manifest):
        source_path = str(item.get("source_path") or "")
        markdown_path = str(item.get("markdown_path") or "")
        markdown_file = _resolve_handoff_path(source_base, markdown_path)
        source_file = _resolve_handoff_path(source_base, source_path) if source_path else None
        document: dict[str, Any] = {
            "source_path": source_path,
            "source_format": Path(source_path).suffix.lower().lstrip(".") if source_path else None,
            "source_sha256": item.get("sha256"),
            "source_inventory": _source_inventory_record(
                source_path=source_path,
                source_file=source_file,
                manifest_item=item,
            ),
            "markdown_path": _relative(markdown_file, root),
            "title": item.get("title"),
            "language": item.get("language"),
            "locale": item.get("language"),
            "warnings": list(item.get("warnings", [])) if isinstance(item.get("warnings", []), list) else [],
            "markdown": _file_record(markdown_file, root=root),
        }
        if source_file:
            document["source"] = _file_record(source_file, root=root)
        documents.append(document)

    return {
        "schema": DOCUMENT_METADATA_SCHEMA,
        "created_at": _now(),
        "document_count": len(documents),
        "documents": documents,
    }


def make_artifact_index_payload(*, handoff_root: str | Path) -> dict[str, Any]:
    """Index local package artifacts without including source documents as artifacts."""

    root = Path(handoff_root)
    artifacts = []
    for container in ("documents", "artifacts"):
        base = root / container
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if container == "documents" and path.suffix.lower() == ".md":
                continue
            artifacts.append(
                {
                    **_file_record(path, root=root),
                    "kind": _artifact_kind(path),
                }
            )
    return {
        "schema": ARTIFACT_INDEX_SCHEMA,
        "created_at": _now(),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def make_profile_suggestions_payload(
    *,
    handoff_root: str | Path,
    metadata: Mapping[str, Any],
    quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic advisory profile hints from handoff metadata."""

    documents = metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []
    total_chars = 0
    image_count = 0
    has_cjk = False
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_path = Path(handoff_root) / str(markdown.get("path", ""))
        if markdown_path.is_file():
            text = markdown_path.read_text(encoding="utf-8", errors="replace")
            total_chars += len(text)
            image_count += text.count("![")
            has_cjk = has_cjk or any("\u4e00" <= char <= "\u9fff" for char in text[:5000])

    gate = quality_report.get("gate", {}) if isinstance(quality_report, Mapping) else {}
    quality_status = gate.get("status") if isinstance(gate, Mapping) else None
    language = "zh" if has_cjk else "en"
    average_chars = int(total_chars / len(documents)) if documents else 0
    chunk_size = 512 if language == "zh" else 768
    if average_chars > 24000:
        chunk_size = 1024 if language == "en" else 768

    warnings: list[str] = []
    if quality_status == "BLOCKED":
        warnings.append("quality gate is BLOCKED; fix the handoff before building unless the user explicitly allows it")
    if image_count:
        warnings.append("image-rich Markdown detected; verify parser profile preserves image/table context as needed")
    if average_chars > 32000:
        warnings.append("large average document size detected; consider segmentation before upload")

    return {
        "schema": PROFILE_SUGGESTIONS_SCHEMA,
        "created_at": _now(),
        "suggestions": [
            {
                "id": f"default-{language}-{chunk_size}",
                "language": language,
                "chunk_size": chunk_size,
                "chunk_overlap": 96 if chunk_size >= 768 else 64,
                "reason": "deterministic starter suggestion based on language and document size",
            }
        ],
        "signals": {
            "document_count": len(documents),
            "total_chars": total_chars,
            "average_chars": average_chars,
            "image_count": image_count,
            "quality_status": quality_status,
        },
        "warnings": warnings,
    }


def _read_markdown(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _count_table_blocks(lines: list[str]) -> int:
    count = 0
    in_table = False
    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.count("|") >= 2 and not stripped.startswith("```")
        if is_table_line and not in_table:
            count += 1
        in_table = is_table_line
    return count


def _section_stats(lines: list[str], *, line_start: int, line_end: int) -> dict[str, int]:
    section_lines = lines[max(line_start - 1, 0) : max(line_end, line_start - 1)]
    section_text = "\n".join(section_lines)
    return {
        "image_count": len(IMAGE_RE.findall(section_text)),
        "table_count": _count_table_blocks(section_lines),
        "list_item_count": sum(1 for line in section_lines if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)),
        "chunk_marker_count": sum(1 for line in section_lines if "<!-- chunk -->" in line),
    }


def _section_boundaries(*, markdown_rel: str, text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line)
        if match:
            headings.append(
                {
                    "document": markdown_rel,
                    "title": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "line_start": index,
                }
            )
    if not headings and lines:
        headings.append(
            {
                "document": markdown_rel,
                "title": Path(markdown_rel).stem,
                "level": 0,
                "line_start": 1,
            }
        )
    for position, heading in enumerate(headings):
        next_start = headings[position + 1]["line_start"] if position + 1 < len(headings) else len(lines) + 1
        heading["line_end"] = max(int(next_start) - 1, int(heading["line_start"]))
        heading.update(_section_stats(lines, line_start=int(heading["line_start"]), line_end=int(heading["line_end"])))
    return headings


def _add_keyword_candidate(candidates: dict[str, dict[str, Any]], *, term: str, source: str, weight: float) -> None:
    normalized = " ".join(term.strip(" #`*_:-").split())
    if not normalized:
        return
    key = normalized.lower()
    if len(key) < 3 or key in STOPWORDS:
        return
    if key not in candidates:
        candidates[key] = {"term": normalized, "source": source, "weight": weight}


def _keyword_candidates(*, sections: list[Mapping[str, Any]], documents: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for document in documents:
        title = document.get("title")
        if isinstance(title, str):
            _add_keyword_candidate(candidates, term=title, source="document_title", weight=1.0)
    for section in sections:
        title = section.get("title")
        if not isinstance(title, str):
            continue
        _add_keyword_candidate(candidates, term=title, source="heading", weight=0.9)
        for word in WORD_RE.findall(title):
            _add_keyword_candidate(candidates, term=word, source="heading_word", weight=0.5)
        for phrase in CJK_PHRASE_RE.findall(title):
            _add_keyword_candidate(candidates, term=phrase, source="heading_phrase", weight=0.7)
    return list(candidates.values())[:40]


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _question_candidates(*, sections: list[Mapping[str, Any]], numeric_candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for section in sections[:12]:
        title = section.get("title")
        if not isinstance(title, str) or not title:
            continue
        question = f"请概述“{title}”的关键信息。" if _has_cjk(title) else f"What key facts are covered in {title}?"
        questions.append(
            {
                "question": question,
                "type": "section_summary",
                "source_document": section.get("document"),
                "source_heading": title,
                "line_start": section.get("line_start"),
            }
        )
        if section.get("table_count"):
            questions.append(
                {
                    "question": f"Which table-backed facts are listed under {title}?",
                    "type": "table_fact",
                    "source_document": section.get("document"),
                    "source_heading": title,
                    "line_start": section.get("line_start"),
                }
            )
        if section.get("image_count"):
            questions.append(
                {
                    "question": f"Which visual or image-backed details are associated with {title}?",
                    "type": "visual_fact",
                    "source_document": section.get("document"),
                    "source_heading": title,
                    "line_start": section.get("line_start"),
                }
            )
    for candidate in numeric_candidates[:5]:
        questions.append(
            {
                "question": f"Where is the numeric value {candidate.get('value')} stated?",
                "type": "exact_numeric_fact",
                "source_document": candidate.get("document"),
                "source_heading": candidate.get("source_heading"),
                "line_start": candidate.get("line"),
            }
        )
    return questions[:30]


def _numeric_candidates(*, markdown_rel: str, text: str, sections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    section_by_line = sorted(sections, key=lambda item: int(item.get("line_start", 0)))
    for index, line in enumerate(text.splitlines(), start=1):
        for match in NUMERIC_RE.finditer(line):
            heading = None
            for section in section_by_line:
                if int(section.get("line_start", 0)) <= index <= int(section.get("line_end", 0)):
                    heading = section.get("title")
                    break
            output.append(
                {
                    "value": match.group(0).strip(),
                    "document": markdown_rel,
                    "line": index,
                    "source_heading": heading,
                }
            )
            if len(output) >= 20:
                return output
    return output


def _quality_risks(*, metadata: Mapping[str, Any], quality_report: Mapping[str, Any] | None, sections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    gate = quality_report.get("gate", {}) if isinstance(quality_report, Mapping) else {}
    status = gate.get("status") if isinstance(gate, Mapping) else None
    if status and status != "PASS":
        risks.append({"severity": "warning", "code": "quality_gate", "message": f"quality gate status is {status}"})
    documents = quality_report.get("documents", []) if isinstance(quality_report, Mapping) else []
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            for issue in document.get("issues", []) if isinstance(document.get("issues"), list) else []:
                if isinstance(issue, Mapping):
                    risks.append(
                        {
                            "severity": issue.get("severity") or "warning",
                            "code": issue.get("issue_type") or "quality_issue",
                            "message": issue.get("message") or "quality issue",
                            "path": issue.get("path"),
                        }
                    )
    for document in metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []:
        if not isinstance(document, Mapping):
            continue
        for warning in document.get("warnings", []) if isinstance(document.get("warnings"), list) else []:
            risks.append({"severity": "warning", "code": "conversion_warning", "message": str(warning)})
    if sum(int(section.get("image_count", 0)) for section in sections) > 10:
        risks.append({"severity": "info", "code": "image_rich", "message": "image-rich handoff; validate visual context retrieval"})
    return risks[:40]


def make_retrieval_hints_payload(
    *,
    handoff_root: str | Path,
    metadata: Mapping[str, Any],
    artifact_index: Mapping[str, Any] | None = None,
    quality_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deterministic retrieval hints from Markdown headings and sidecars."""

    root = Path(handoff_root)
    documents = metadata.get("documents", []) if isinstance(metadata.get("documents"), list) else []
    sections: list[dict[str, Any]] = []
    numeric_candidates: list[dict[str, Any]] = []
    document_summaries: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        markdown = document.get("markdown", {}) if isinstance(document.get("markdown"), Mapping) else {}
        markdown_rel = str(markdown.get("path") or document.get("markdown_path") or "")
        if not markdown_rel:
            continue
        text = _read_markdown(root / markdown_rel)
        document_sections = _section_boundaries(markdown_rel=markdown_rel, text=text)
        sections.extend(document_sections)
        numeric_candidates.extend(_numeric_candidates(markdown_rel=markdown_rel, text=text, sections=document_sections))
        document_summaries.append(
            {
                "markdown_path": markdown_rel,
                "title": document.get("title"),
                "section_count": len(document_sections),
                "line_count": len(text.splitlines()),
                "image_count": text.count("!["),
                "table_count": _count_table_blocks(text.splitlines()),
            }
        )

    artifacts = artifact_index.get("artifacts", []) if isinstance(artifact_index, Mapping) else []
    table_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "table"]
    image_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Mapping) and artifact.get("kind") == "image"]
    quality_risks = _quality_risks(metadata=metadata, quality_report=quality_report, sections=sections)
    keywords = _keyword_candidates(sections=sections, documents=[item for item in documents if isinstance(item, Mapping)])
    questions = _question_candidates(sections=sections, numeric_candidates=numeric_candidates)

    return {
        "schema": RETRIEVAL_HINTS_SCHEMA,
        "created_at": _now(),
        "document_count": len(document_summaries),
        "documents": document_summaries,
        "section_boundaries": sections,
        "table_artifacts": table_artifacts[:30],
        "image_artifacts": image_artifacts[:30],
        "keyword_candidates": keywords,
        "question_candidates": questions,
        "numeric_candidates": numeric_candidates[:20],
        "quality_risks": quality_risks,
        "preferred_boundaries": [
            {
                "document": section.get("document"),
                "line_start": section.get("line_start"),
                "line_end": section.get("line_end"),
                "reason": "heading_boundary",
                "title": section.get("title"),
            }
            for section in sections
            if int(section.get("level", 0)) <= 3
        ][:80],
    }


def make_assistant_profile_payload(
    *,
    retrieval_hints: Mapping[str, Any],
    profile_suggestions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a reviewable assistant retrieval profile without mutating RAGFlow."""

    sections = retrieval_hints.get("section_boundaries", [])
    sections = sections if isinstance(sections, list) else []
    section_count = len(sections)
    keyword_count = len(retrieval_hints.get("keyword_candidates", [])) if isinstance(retrieval_hints.get("keyword_candidates"), list) else 0
    has_visuals = bool(retrieval_hints.get("image_artifacts")) or any(
        isinstance(section, Mapping) and int(section.get("image_count", 0)) > 0
        for section in sections
    )
    top_k = 8 if section_count > 8 or has_visuals else 5
    similarity_threshold = 0.18 if has_visuals else 0.2
    suggestions = profile_suggestions.get("suggestions", []) if isinstance(profile_suggestions, Mapping) else []

    return {
        "schema": ASSISTANT_PROFILE_SCHEMA,
        "created_at": _now(),
        "profile_id": "handoff-review-default",
        "status": "review_required",
        "source_sidecars": {
            "retrieval_hints": "retrieval_hints.json",
            "profile_suggestions": "profile_suggestions.json",
        },
        "retrieval": {
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "vector_weight": 0.7,
            "bm25_weight": 0.3 if keyword_count else 0.0,
            "require_evidence": True,
            "quote_numeric_facts": True,
            "citation_format": "[n]",
        },
        "parser_profile_hint": suggestions[0] if suggestions and isinstance(suggestions[0], Mapping) else None,
        "answer_policy": [
            "Answer only from retrieved evidence.",
            "Cite or quote evidence for numbers, tables, images, and named entities.",
            "Say that the source does not contain the answer when evidence is missing.",
        ],
        "review_notes": [
            "This profile is advisory and does not modify RAGFlow assistant settings.",
            "Review retrieval thresholds after live smoke or benchmark validation.",
        ],
    }


def make_assistant_test_plan_payload(
    *,
    retrieval_hints: Mapping[str, Any],
    assistant_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Create staged assistant tests from retrieval hints."""

    questions = retrieval_hints.get("question_candidates", []) if isinstance(retrieval_hints.get("question_candidates"), list) else []
    sections = retrieval_hints.get("section_boundaries", []) if isinstance(retrieval_hints.get("section_boundaries"), list) else []
    numeric = retrieval_hints.get("numeric_candidates", []) if isinstance(retrieval_hints.get("numeric_candidates"), list) else []
    cases: list[dict[str, Any]] = []

    if questions:
        first = questions[0]
        if isinstance(first, Mapping):
            cases.append(
                {
                    "id": "summary-001",
                    "stage": "summary",
                    "question": first.get("question"),
                    "expected_behavior": "answer from cited retrieved evidence",
                    "source_document": first.get("source_document"),
                    "source_heading": first.get("source_heading"),
                }
            )
    if numeric:
        first_numeric = numeric[0]
        if isinstance(first_numeric, Mapping):
            cases.append(
                {
                    "id": "numeric-001",
                    "stage": "exact_numeric_fact",
                    "question": f"What does the source say about {first_numeric.get('value')}?",
                    "expected_behavior": "return the numeric fact with a citation",
                    "source_document": first_numeric.get("document"),
                    "source_heading": first_numeric.get("source_heading"),
                }
            )
    visual_section = next((section for section in sections if isinstance(section, Mapping) and int(section.get("image_count", 0)) > 0), None)
    if visual_section:
        cases.append(
            {
                "id": "visual-001",
                "stage": "ocr_image_fact",
                "question": f"What visual details are associated with {visual_section.get('title')}?",
                "expected_behavior": "answer only if retrieved evidence contains the visual or OCR-backed detail",
                "source_document": visual_section.get("document"),
                "source_heading": visual_section.get("title"),
            }
        )
    if len(sections) >= 2 and isinstance(sections[0], Mapping) and isinstance(sections[1], Mapping):
        cases.append(
            {
                "id": "flow-001",
                "stage": "logical_flow",
                "question": f"How are {sections[0].get('title')} and {sections[1].get('title')} related in the source?",
                "expected_behavior": "compare only the retrieved source sections and avoid outside assumptions",
                "source_document": sections[0].get("document"),
            }
        )
    for index, question in enumerate(questions[1:4], start=1):
        if isinstance(question, Mapping):
            cases.append(
                {
                    "id": f"paraphrase-{index:03d}",
                    "stage": "paraphrase",
                    "question": question.get("question"),
                    "expected_behavior": "retrieve the same source section even when phrasing differs",
                    "source_document": question.get("source_document"),
                    "source_heading": question.get("source_heading"),
                }
            )
    cases.append(
        {
            "id": "negative-001",
            "stage": "negative_boundary",
            "question": "What private API key or deployment secret is used by this source?",
            "expected_behavior": "abstain because the public handoff must not contain secrets",
        }
    )

    return {
        "schema": ASSISTANT_TEST_PLAN_SCHEMA,
        "created_at": _now(),
        "assistant_profile": assistant_profile.get("profile_id"),
        "status": "review_required",
        "test_count": len(cases),
        "cases": cases,
    }


def make_package_readme(
    *,
    doc_manifest_name: str,
    metadata_name: str,
    artifact_index_name: str,
    profile_suggestions_name: str,
    retrieval_hints_name: str,
    assistant_profile_name: str,
    assistant_test_plan_name: str,
    quality_report_name: str | None,
) -> str:
    """Render a compact README for a rich handoff package."""

    lines = [
        "# RAGFlow Handoff Package",
        "",
        "This directory is a portable document handoff for the public RAGFlow skills.",
        "",
        "## Files",
        "",
        f"- `{doc_manifest_name}`: required v0.1 document manifest.",
        f"- `{metadata_name}`: document-level source and Markdown metadata.",
        f"- `{artifact_index_name}`: hashes and kinds for local assets under `documents/` and `artifacts/`.",
        f"- `{profile_suggestions_name}`: advisory parser/profile hints for review.",
        f"- `{retrieval_hints_name}`: section, keyword, question, and quality-risk hints for retrieval review.",
        f"- `{assistant_profile_name}`: advisory assistant retrieval and answer policy profile.",
        f"- `{assistant_test_plan_name}`: staged assistant validation questions for review.",
    ]
    if quality_report_name:
        lines.append(f"- `{quality_report_name}`: document quality gate report.")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Treat sidecars as advisory public metadata.",
            "- Do not add API keys, private config files, vault paths, or personal endpoints to this package.",
            "- `ragflow-kb-build` consumes `doc_manifest.json` first; rich sidecars remain optional.",
            "",
        ]
    )
    return "\n".join(lines)


def create_rich_handoff_package(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
    metadata_name: str = "metadata.json",
    artifact_index_name: str = "artifact_index.json",
    profile_suggestions_name: str = "profile_suggestions.json",
    retrieval_hints_name: str = "retrieval_hints.json",
    assistant_profile_name: str = "assistant_profile.json",
    assistant_test_plan_name: str = "assistant_test_plan.json",
    package_readme_name: str = "package_readme.md",
) -> dict[str, Any]:
    """Create optional rich sidecars beside an existing doc manifest."""

    root = Path(handoff_root)
    doc_manifest_path = root / doc_manifest_name
    try:
        doc_manifest = load_doc_manifest_payload(doc_manifest_path)
    except DocQualityError as exc:
        raise HandoffError(str(exc)) from exc

    quality_report_name = doc_manifest.get("quality_report")
    quality_report = None
    if isinstance(quality_report_name, str) and quality_report_name:
        quality_path = root / quality_report_name
        if quality_path.exists():
            quality_report = _read_json(quality_path)

    metadata = make_document_metadata_payload(handoff_root=root, doc_manifest=doc_manifest)
    artifact_index = make_artifact_index_payload(handoff_root=root)
    profile_suggestions = make_profile_suggestions_payload(
        handoff_root=root,
        metadata=metadata,
        quality_report=quality_report,
    )
    retrieval_hints = make_retrieval_hints_payload(
        handoff_root=root,
        metadata=metadata,
        artifact_index=artifact_index,
        quality_report=quality_report,
    )
    assistant_profile = make_assistant_profile_payload(
        retrieval_hints=retrieval_hints,
        profile_suggestions=profile_suggestions,
    )
    assistant_test_plan = make_assistant_test_plan_payload(
        retrieval_hints=retrieval_hints,
        assistant_profile=assistant_profile,
    )
    readme = make_package_readme(
        doc_manifest_name=doc_manifest_name,
        metadata_name=metadata_name,
        artifact_index_name=artifact_index_name,
        profile_suggestions_name=profile_suggestions_name,
        retrieval_hints_name=retrieval_hints_name,
        assistant_profile_name=assistant_profile_name,
        assistant_test_plan_name=assistant_test_plan_name,
        quality_report_name=quality_report_name if isinstance(quality_report_name, str) else None,
    )

    metadata_path = root / metadata_name
    artifact_index_path = root / artifact_index_name
    profile_suggestions_path = root / profile_suggestions_name
    retrieval_hints_path = root / retrieval_hints_name
    assistant_profile_path = root / assistant_profile_name
    assistant_test_plan_path = root / assistant_test_plan_name
    package_readme_path = root / package_readme_name
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_index_path.write_text(json.dumps(artifact_index, ensure_ascii=False, indent=2), encoding="utf-8")
    profile_suggestions_path.write_text(json.dumps(profile_suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    retrieval_hints_path.write_text(json.dumps(retrieval_hints, ensure_ascii=False, indent=2), encoding="utf-8")
    assistant_profile_path.write_text(json.dumps(assistant_profile, ensure_ascii=False, indent=2), encoding="utf-8")
    assistant_test_plan_path.write_text(json.dumps(assistant_test_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    package_readme_path.write_text(readme, encoding="utf-8")

    payload = {
        "schema": HANDOFF_PACKAGE_SCHEMA,
        "created_at": _now(),
        "doc_manifest": doc_manifest_name,
        "metadata": metadata_name,
        "artifact_index": artifact_index_name,
        "profile_suggestions": profile_suggestions_name,
        "retrieval_hints": retrieval_hints_name,
        "assistant_profile": assistant_profile_name,
        "assistant_test_plan": assistant_test_plan_name,
        "package_readme": package_readme_name,
        "quality_report": quality_report_name if isinstance(quality_report_name, str) else None,
        "document_count": len(metadata["documents"]),
        "artifact_count": artifact_index["artifact_count"],
        "retrieval_hint_count": len(retrieval_hints["section_boundaries"]),
        "assistant_test_count": assistant_test_plan["test_count"],
        "quality_status": profile_suggestions.get("signals", {}).get("quality_status"),
    }
    return payload


def inspect_rich_handoff(
    *,
    handoff_root: str | Path,
    doc_manifest_name: str = "doc_manifest.json",
) -> dict[str, Any]:
    """Summarize a handoff directory and optional rich sidecars."""

    root = Path(handoff_root)
    doc_manifest = _read_json(root / doc_manifest_name)
    documents = _manifest_documents(doc_manifest)
    sidecars = {}
    for key, filename in {
        "metadata": "metadata.json",
        "artifact_index": "artifact_index.json",
        "profile_suggestions": "profile_suggestions.json",
        "retrieval_hints": "retrieval_hints.json",
        "assistant_profile": "assistant_profile.json",
        "assistant_test_plan": "assistant_test_plan.json",
        "package_readme": "package_readme.md",
        "quality_report": doc_manifest.get("quality_report") if isinstance(doc_manifest.get("quality_report"), str) else None,
    }.items():
        if not filename:
            continue
        path = root / filename
        sidecars[key] = {
            "path": filename,
            "exists": path.exists(),
        }
        if path.is_file():
            sidecars[key]["size_bytes"] = path.stat().st_size

    artifact_count = None
    artifact_index_path = root / "artifact_index.json"
    if artifact_index_path.is_file():
        artifact_index = _read_json(artifact_index_path)
        artifact_count = artifact_index.get("artifact_count")

    retrieval_hint_count = None
    retrieval_hints_path = root / "retrieval_hints.json"
    if retrieval_hints_path.is_file():
        retrieval_hints = _read_json(retrieval_hints_path)
        sections = retrieval_hints.get("section_boundaries")
        retrieval_hint_count = len(sections) if isinstance(sections, list) else None

    assistant_test_count = None
    assistant_test_plan_path = root / "assistant_test_plan.json"
    if assistant_test_plan_path.is_file():
        assistant_test_plan = _read_json(assistant_test_plan_path)
        assistant_test_count = assistant_test_plan.get("test_count")

    quality_status = None
    quality_name = doc_manifest.get("quality_report")
    if isinstance(quality_name, str) and (root / quality_name).is_file():
        quality = _read_json(root / quality_name)
        gate = quality.get("gate", {}) if isinstance(quality.get("gate"), Mapping) else {}
        quality_status = gate.get("status")

    return {
        "schema": "ragflow_handoff_inspection_v1",
        "created_at": _now(),
        "handoff_root": str(root),
        "doc_manifest": doc_manifest_name,
        "document_count": len(documents),
        "quality_status": quality_status,
        "artifact_count": artifact_count,
        "retrieval_hint_count": retrieval_hint_count,
        "assistant_test_count": assistant_test_count,
        "sidecars": sidecars,
    }


def render_handoff_inspection_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown handoff inspection report."""

    lines = [
        "# RAGFlow Handoff Inspection",
        "",
        f"- Documents: {report.get('document_count', 0)}",
        f"- Quality status: `{report.get('quality_status') or 'UNKNOWN'}`",
        f"- Artifact count: {report.get('artifact_count') if report.get('artifact_count') is not None else 'unknown'}",
        f"- Retrieval hint sections: {report.get('retrieval_hint_count') if report.get('retrieval_hint_count') is not None else 'unknown'}",
        f"- Assistant tests: {report.get('assistant_test_count') if report.get('assistant_test_count') is not None else 'unknown'}",
        "",
        "## Sidecars",
        "",
        "| Sidecar | Exists | Path |",
        "| --- | --- | --- |",
    ]
    sidecars = report.get("sidecars", {})
    if isinstance(sidecars, Mapping):
        for name, info in sidecars.items():
            if not isinstance(info, Mapping):
                continue
            lines.append(f"| {name} | {str(bool(info.get('exists'))).lower()} | `{info.get('path', '')}` |")
    return "\n".join(lines).rstrip() + "\n"
