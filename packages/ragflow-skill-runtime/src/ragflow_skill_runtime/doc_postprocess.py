"""Deterministic Markdown post-processing for document handoffs."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .doc_quality import load_doc_manifest_payload


POSTPROCESS_REPORT_SCHEMA = "doc_postprocess_report_v1"
POSTPROCESS_PROFILES = {"none", "safe", "ocr", "chunk-markers"}

HEADING_WITHOUT_SPACE_RE = re.compile(r"^(#{1,6})([^#\s].*)$")
MARKDOWN_IMAGE_TARGET_RE = re.compile(r"(!\[[^\]]*]\()([^)]+)(\))")
CJK_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


class DocPostprocessError(RuntimeError):
    """Raised when Markdown post-processing cannot proceed."""


@dataclass(frozen=True)
class PostprocessRuleResult:
    rule_id: str
    description: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "count": self.count,
        }


@dataclass(frozen=True)
class PostprocessDocumentResult:
    markdown_path: str
    output_path: str
    profile: str
    changed: bool
    line_count_before: int
    line_count_after: int
    rule_results: list[PostprocessRuleResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "markdown_path": self.markdown_path,
            "output_path": self.output_path,
            "profile": self.profile,
            "changed": self.changed,
            "line_count_before": self.line_count_before,
            "line_count_after": self.line_count_after,
            "rules": [result.to_dict() for result in self.rule_results if result.count],
            "warnings": list(self.warnings),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_profile(profile: str) -> str:
    normalized = profile.strip().lower()
    if normalized not in POSTPROCESS_PROFILES:
        allowed = ", ".join(sorted(POSTPROCESS_PROFILES))
        raise DocPostprocessError(f"postprocess profile must be one of: {allowed}")
    return normalized


def _line_counts(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _ensure_trailing_newline(text: str) -> tuple[str, int]:
    if text and not text.endswith("\n"):
        return text + "\n", 1
    return text, 0


def _normalize_line_endings(text: str) -> tuple[str, int]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, 1 if normalized != text else 0


def _strip_trailing_spaces(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    changed = 0
    output = []
    for line in lines:
        newline = ""
        body = line
        if line.endswith("\n"):
            newline = "\n"
            body = line[:-1]
        stripped = body.rstrip(" \t")
        if stripped != body:
            changed += 1
        output.append(stripped + newline)
    return "".join(output), changed


def _collapse_blank_lines(text: str) -> tuple[str, int]:
    collapsed = re.sub(r"\n{3,}", "\n\n", text)
    if collapsed == text:
        return text, 0
    return collapsed, 1


def _repair_heading_spacing(text: str) -> tuple[str, int]:
    changed = 0
    output = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        if body.strip().startswith("```") or body.strip().startswith("~~~"):
            in_fence = not in_fence
        if not in_fence:
            match = HEADING_WITHOUT_SPACE_RE.match(body)
            if match:
                body = f"{match.group(1)} {match.group(2).strip()}"
                changed += 1
        output.append(body + ("\n" if line.endswith("\n") else ""))
    return "".join(output), changed


def _normalize_markdown_image_targets(text: str) -> tuple[str, int]:
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        prefix, raw, suffix = match.groups()
        value = raw.strip()
        if value.lower().startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        if value.startswith("<") and ">" in value:
            target, rest = value[1:].split(">", 1)
            angle = True
        else:
            parts = value.split(maxsplit=1)
            target = parts[0] if parts else value
            rest = f" {parts[1]}" if len(parts) == 2 else ""
            angle = False
        normalized = target.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        absolute_like = normalized.startswith(("/", "~/")) or bool(re.match(r"^[A-Za-z]:/", normalized))
        if absolute_like and "/images/" in normalized:
            normalized = f"images/{normalized.rsplit('/images/', 1)[1]}"
        if " " in normalized and not angle:
            replacement = f"<{normalized}>{rest}"
        else:
            replacement = f"<{normalized}>{rest}" if angle else f"{normalized}{rest}"
        if replacement != raw:
            changed += 1
        return f"{prefix}{replacement}{suffix}"

    return MARKDOWN_IMAGE_TARGET_RE.sub(replace, text), changed


def _remove_cjk_inner_spaces(text: str) -> tuple[str, int]:
    pattern = re.compile(fr"([{CJK_RE}])\s+([{CJK_RE}])")
    changed = 0
    previous = text
    while True:
        current, count = pattern.subn(r"\1\2", previous)
        changed += count
        if current == previous:
            return current, changed
        previous = current


def _fix_ocr_punctuation_spacing(text: str) -> tuple[str, int]:
    replacements = [
        (re.compile(r"\s+([,.;:!?，。；：！？、])"), r"\1"),
        (re.compile(r"([，。；：！？、])\s+"), r"\1"),
        (re.compile(r"([（([{])\s+"), r"\1"),
        (re.compile(r"\s+([）)\]}])"), r"\1"),
    ]
    changed = 0
    current = text
    for pattern, replacement in replacements:
        current, count = pattern.subn(replacement, current)
        changed += count
    return current, changed


def _normalize_ocr_ligatures(text: str) -> tuple[str, int]:
    replacements = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
    }
    changed = 0
    current = text
    for old, new in replacements.items():
        count = current.count(old)
        if count:
            current = current.replace(old, new)
            changed += count
    return current, changed


def _insert_chunk_markers(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines:
        return text, 0
    output: list[str] = []
    changed = 0
    in_fence = False
    seen_content = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        is_heading = bool(re.match(r"^#{1,3}\s+\S", stripped))
        previous = output[-1].strip().lower() if output else ""
        if (
            is_heading
            and not in_fence
            and seen_content
            and previous != "<!-- chunk -->"
        ):
            if output and output[-1].strip():
                output.append("")
            output.append("<!-- chunk -->")
            changed += 1
        output.append(line)
        if stripped and stripped != "<!-- chunk -->":
            seen_content = True
    return "\n".join(output) + ("\n" if text.endswith("\n") else ""), changed


def postprocess_markdown_text(text: str, *, profile: str) -> tuple[str, list[PostprocessRuleResult]]:
    """Post-process Markdown content and return applied rule counts."""

    profile = _validate_profile(profile)
    rule_results: list[PostprocessRuleResult] = []

    def apply(rule_id: str, description: str, func) -> None:
        nonlocal text
        text, count = func(text)
        rule_results.append(PostprocessRuleResult(rule_id=rule_id, description=description, count=count))

    if profile == "none":
        return text, []

    apply("safe.line_endings", "Normalize CRLF/CR line endings to LF", _normalize_line_endings)
    apply("safe.trailing_space", "Strip trailing spaces and tabs", _strip_trailing_spaces)
    apply("safe.blank_lines", "Collapse three or more blank lines to two", _collapse_blank_lines)
    apply("safe.heading_spacing", "Repair obvious Markdown heading spacing", _repair_heading_spacing)
    apply("safe.image_paths", "Normalize simple local Markdown image paths", _normalize_markdown_image_targets)
    apply("safe.trailing_newline", "Ensure a final newline", _ensure_trailing_newline)

    if profile in {"ocr", "chunk-markers"}:
        apply("ocr.cjk_spaces", "Remove spaces inserted between adjacent CJK characters", _remove_cjk_inner_spaces)
        apply("ocr.punctuation_spacing", "Remove OCR spaces before punctuation or closing brackets", _fix_ocr_punctuation_spacing)
        apply("ocr.ligatures", "Normalize common OCR ligatures", _normalize_ocr_ligatures)

    if profile == "chunk-markers":
        apply("chunk_markers.heading_boundaries", "Insert conservative chunk markers before level 1-3 headings", _insert_chunk_markers)

    return text, rule_results


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def postprocess_markdown_file(
    markdown_path: str | Path,
    *,
    profile: str,
    output_path: str | Path | None = None,
    write: bool = False,
    root_for_report: str | Path | None = None,
    source_root_for_report: str | Path | None = None,
    output_root_for_report: str | Path | None = None,
) -> PostprocessDocumentResult:
    """Post-process one Markdown file."""

    source = Path(markdown_path)
    if not source.is_file():
        raise DocPostprocessError(f"markdown file not found: {source}")
    if source.suffix.lower() not in {".md", ".markdown", ".mdown", ".mkd"}:
        raise DocPostprocessError(f"postprocess expects a Markdown file: {source}")
    if write and output_path:
        raise DocPostprocessError("use either --write or --output, not both")
    if not write and not output_path:
        raise DocPostprocessError("postprocess requires --output unless --write is used")

    before = source.read_text(encoding="utf-8")
    after, rules = postprocess_markdown_text(before, profile=profile)
    target = source if write else Path(output_path)  # type: ignore[arg-type]
    if target.exists() and target.is_dir():
        target = target / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after, encoding="utf-8")

    fallback_root = Path(root_for_report) if root_for_report else target.parent
    source_root = Path(source_root_for_report) if source_root_for_report else fallback_root
    output_root = Path(output_root_for_report) if output_root_for_report else fallback_root
    return PostprocessDocumentResult(
        markdown_path=_relative(source, source_root),
        output_path=_relative(target, output_root),
        profile=_validate_profile(profile),
        changed=before != after,
        line_count_before=_line_counts(before),
        line_count_after=_line_counts(after),
        rule_results=rules,
    )


def _manifest_markdown_paths(manifest: Mapping[str, Any], *, manifest_path: Path) -> list[tuple[Mapping[str, Any], Path]]:
    source_root = Path(str(manifest.get("source_root") or "."))
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise DocPostprocessError("doc_manifest.documents must be a non-empty list")
    output: list[tuple[Mapping[str, Any], Path]] = []
    for index, item in enumerate(documents):
        if not isinstance(item, Mapping):
            raise DocPostprocessError(f"documents[{index}] must be an object")
        markdown_path = item.get("markdown_path")
        if not isinstance(markdown_path, str) or not markdown_path:
            raise DocPostprocessError(f"documents[{index}].markdown_path is required")
        path = Path(markdown_path)
        if not path.is_absolute():
            path = source_root / path
        output.append((item, path))
    return output


def _manifest_source_root(manifest: Mapping[str, Any], *, manifest_path: Path) -> Path:
    source_root = Path(str(manifest.get("source_root") or "."))
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root
    return source_root


def _copy_handoff_assets(*, source_root: Path, output_root: Path) -> None:
    for container in ("documents", "artifacts"):
        base = source_root / container
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() in {".md", ".markdown", ".mdown", ".mkd"}:
                continue
            rel = path.relative_to(source_root)
            destination = output_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(path, destination)


def _report_payload(*, profile: str, mode: str, documents: list[PostprocessDocumentResult]) -> dict[str, Any]:
    changed = sum(1 for document in documents if document.changed)
    rule_counts: dict[str, int] = {}
    for document in documents:
        for rule in document.rule_results:
            rule_counts[rule.rule_id] = rule_counts.get(rule.rule_id, 0) + rule.count
    return {
        "schema": POSTPROCESS_REPORT_SCHEMA,
        "created_at": _now(),
        "profile": _validate_profile(profile),
        "mode": mode,
        "summary": {
            "documents": len(documents),
            "changed_documents": changed,
            "total_rule_applications": sum(rule_counts.values()),
            "rule_counts": rule_counts,
        },
        "documents": [document.to_dict() for document in documents],
    }


def postprocess_handoff(
    doc_manifest_path: str | Path,
    *,
    profile: str,
    output_dir: str | Path | None = None,
    write: bool = False,
    report_json: str | Path | None = None,
) -> dict[str, Any]:
    """Post-process all Markdown documents referenced by a doc_manifest."""

    manifest_path = Path(doc_manifest_path)
    manifest = load_doc_manifest_payload(manifest_path)
    if write and output_dir:
        raise DocPostprocessError("use either --write or --output, not both")
    if not write and not output_dir:
        raise DocPostprocessError("handoff postprocess requires --output unless --write is used")

    output_root = Path(output_dir) if output_dir else manifest_path.parent
    source_root = _manifest_source_root(manifest, manifest_path=manifest_path)
    results: list[PostprocessDocumentResult] = []
    for item, markdown_path in _manifest_markdown_paths(manifest, manifest_path=manifest_path):
        raw_rel = Path(str(item.get("markdown_path")))
        target = markdown_path if write else output_root / raw_rel
        results.append(
            postprocess_markdown_file(
                markdown_path,
                profile=profile,
                output_path=None if write else target,
                write=write,
                source_root_for_report=source_root,
                output_root_for_report=source_root if write else output_root,
            )
        )

    if not write:
        _copy_handoff_assets(source_root=source_root, output_root=output_root)
        copied_manifest = dict(manifest)
        copied_manifest["source_root"] = "."
        copied_manifest["postprocess_report"] = "postprocess_report.json"
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / manifest_path.name).write_text(json.dumps(copied_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        for sidecar_name in ("quality_report", "quality_report_md"):
            sidecar = manifest.get(sidecar_name)
            if isinstance(sidecar, str) and (manifest_path.parent / sidecar).is_file():
                destination = output_root / sidecar
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_path.parent / sidecar, destination)

    report = _report_payload(profile=profile, mode="handoff", documents=results)
    report_path = Path(report_json) if report_json else (output_root / "postprocess_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def postprocess_single_markdown(
    markdown_path: str | Path,
    *,
    profile: str,
    output_path: str | Path | None = None,
    write: bool = False,
    report_json: str | Path | None = None,
) -> dict[str, Any]:
    """Post-process one Markdown file and write a report."""

    result = postprocess_markdown_file(
        markdown_path,
        profile=profile,
        output_path=output_path,
        write=write,
        root_for_report=Path(output_path).parent if output_path else Path(markdown_path).parent,
    )
    report = _report_payload(profile=profile, mode="markdown", documents=[result])
    if report_json:
        report_path = Path(report_json)
    elif output_path:
        output = Path(output_path)
        report_path = (output if output.exists() and output.is_dir() else output.parent) / "postprocess_report.json"
    else:
        report_path = Path(markdown_path).parent / "postprocess_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
