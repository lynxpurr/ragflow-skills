"""Helpers for Markdown-to-RAGFlow build scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Mapping

from .manifests import DocManifest, KbDocumentEntry
from .profiles import ChunkProfile


class BuildError(RuntimeError):
    """Raised when build inputs are invalid."""


@dataclass(frozen=True)
class BuildDocument:
    path: Path
    manifest_source_path: str | None = None


def discover_markdown_documents(
    *,
    input_path: str | Path | None = None,
    doc_manifest: DocManifest | None = None,
    manifest_base_path: str | Path | None = None,
) -> list[BuildDocument]:
    """Discover Markdown documents from a directory, file, or doc manifest."""

    docs: list[BuildDocument] = []
    if doc_manifest:
        manifest_root = Path(manifest_base_path).parent if manifest_base_path else Path(".")
        base = Path(doc_manifest.source_root) if doc_manifest.source_root else manifest_root
        if not base.is_absolute():
            base = manifest_root / base
        for entry in doc_manifest.documents:
            md_path = Path(entry.markdown_path)
            if not md_path.is_absolute():
                md_path = base / md_path
            docs.append(BuildDocument(path=md_path, manifest_source_path=entry.source_path))
    elif input_path:
        path = Path(input_path)
        if path.is_file():
            docs = [BuildDocument(path=path)]
        elif path.is_dir():
            docs = [BuildDocument(path=p) for p in sorted(path.rglob("*.md"))]
        else:
            raise BuildError(f"input path not found: {path}")
    else:
        raise BuildError("provide --input or --doc-manifest")

    missing = [str(doc.path) for doc in docs if not doc.path.exists()]
    if missing:
        raise BuildError(f"markdown documents not found: {', '.join(missing[:5])}")
    docs = [doc for doc in docs if doc.path.suffix.lower() == ".md"]
    if not docs:
        raise BuildError("no Markdown documents found")
    return docs


def extract_dataset_id(response: Any) -> str:
    """Extract a dataset ID from common RAGFlow response shapes."""

    candidates = []
    if isinstance(response, Mapping):
        data = response.get("data", response)
        if isinstance(data, Mapping):
            candidates.extend([data.get("id"), data.get("dataset_id")])
        candidates.extend([response.get("id"), response.get("dataset_id")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    raise BuildError("could not extract dataset id from RAGFlow response")


def extract_uploaded_document_id(response: Any) -> str:
    """Extract an uploaded document ID from common RAGFlow response shapes."""

    data = response.get("data", response) if isinstance(response, Mapping) else response
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, Mapping):
            value = first.get("id") or first.get("document_id")
            if isinstance(value, str) and value:
                return value
    if isinstance(data, Mapping):
        value = data.get("id") or data.get("document_id")
        if isinstance(value, str) and value:
            return value
    raise BuildError("could not extract document id from upload response")


def make_kb_manifest_payload(
    *,
    base_url: str | None,
    dataset_id: str,
    dataset_name: str,
    profile: ChunkProfile,
    documents: list[tuple[BuildDocument, str, str | None, int | None]],
) -> dict[str, Any]:
    """Create a serializable KB manifest payload."""

    return {
        "version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ragflow_base_url": base_url,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "profile": profile.to_manifest_dict(),
        "documents": [
            {
                "document_id": document_id,
                "source_path": doc.manifest_source_path,
                "markdown_path": str(doc.path),
                "status": status,
                "chunk_count": chunk_count,
            }
            for doc, document_id, status, chunk_count in documents
        ],
    }


def document_entries_from_manifest(payload: Mapping[str, Any]) -> list[KbDocumentEntry]:
    """Return typed document entries from a KB manifest payload."""

    docs = payload.get("documents", [])
    if not isinstance(docs, list):
        raise BuildError("kb manifest documents must be a list")
    return [KbDocumentEntry.from_dict(item) for item in docs]


def _extract_document_items(response: Any) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping):
        return []
    data = response.get("data", response)
    if isinstance(data, Mapping):
        for key in ("docs", "documents", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def extract_document_items(response: Any) -> list[Mapping[str, Any]]:
    """Extract document objects from common RAGFlow list-document response shapes."""

    return _extract_document_items(response)


def extract_document_name(document: Mapping[str, Any]) -> str:
    """Extract a display/document name from common RAGFlow document shapes."""

    for key in ("name", "document_name", "docnm_kwd", "filename", "file_name"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_document_id(document: Mapping[str, Any]) -> str:
    """Extract a document ID from common RAGFlow document shapes."""

    for key in ("id", "document_id"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_parse_status(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _message_indicates_failure(message: str) -> bool:
    lower = message.lower()
    return "[error]" in lower or "exception" in lower or "fail" in lower


def normalize_document_state(document: Mapping[str, Any], *, document_id: str = "") -> dict[str, Any]:
    """Normalize one live document status entry returned by RAGFlow."""

    doc_id = str(document.get("id") or document.get("document_id") or document_id)
    run = _normalize_parse_status(document.get("run"))
    status = _normalize_parse_status(document.get("status"))
    progress = _as_float(document.get("progress"))
    progress_text = _normalize_parse_status(document.get("progress"))
    message = str(document.get("progress_msg") or document.get("message") or document.get("error") or "")
    chunk_count = document.get("chunk_count")
    if chunk_count is not None:
        try:
            chunk_count = int(chunk_count)
        except (TypeError, ValueError):
            chunk_count = None

    if run:
        effective_status = run
    elif progress is not None and progress >= 1:
        effective_status = "1"
    elif progress is not None and progress < 0:
        effective_status = "-1"
    elif _message_indicates_failure(message):
        effective_status = "failed"
    else:
        effective_status = status or progress_text or "pending"

    return {
        "document_id": doc_id,
        "status": effective_status,
        "chunk_count": chunk_count,
        "progress": progress,
        "progress_msg": message,
        "raw_status": status,
        "run": run,
    }


def extract_document_states(response: Any, *, document_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Extract normalized live document states from a RAGFlow list-documents response."""

    wanted = set(document_ids or [])
    states: dict[str, dict[str, Any]] = {}
    for item in _extract_document_items(response):
        state = normalize_document_state(item)
        document_id = state["document_id"]
        if not document_id:
            continue
        if wanted and document_id not in wanted:
            continue
        states[document_id] = state
    return states


def parse_state_succeeded(state: Mapping[str, Any]) -> bool:
    status = str(state.get("status", ""))
    return not parse_state_failed(state) and status in {
        "done",
        "success",
        "completed",
        "parsed",
        "finish",
        "finished",
        "1",
    }


def parse_state_failed(state: Mapping[str, Any]) -> bool:
    status = str(state.get("status", ""))
    progress = state.get("progress")
    return (
        status in {"fail", "failed", "error", "cancelled", "canceled", "-1"}
        or (isinstance(progress, (int, float)) and progress < 0)
        or _message_indicates_failure(str(state.get("progress_msg", "")))
    )


def wait_for_document_states(
    client: Any,
    *,
    dataset_id: str,
    document_ids: list[str],
    timeout: float = 300.0,
    poll_interval: float = 2.0,
) -> dict[str, dict[str, Any]]:
    """Poll live document status until all requested documents are parsed or fail."""

    deadline = time.time() + timeout
    latest: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        response = client.list_documents(dataset_id)
        latest = extract_document_states(response, document_ids=document_ids)
        if latest and all(document_id in latest for document_id in document_ids):
            states = [latest[document_id] for document_id in document_ids]
            if all(parse_state_succeeded(state) for state in states):
                return latest
            failed = [state for state in states if parse_state_failed(state)]
            if failed:
                message = "; ".join(
                    f"{state.get('document_id')}: status={state.get('status')} message={state.get('progress_msg', '')}"
                    for state in failed[:3]
                )
                raise BuildError(f"RAGFlow parsing failed: {message}")
        time.sleep(poll_interval)

    raise BuildError(
        "timed out waiting for RAGFlow parsing: "
        + ", ".join(document_ids[:5])
        + ("..." if len(document_ids) > 5 else "")
    )
