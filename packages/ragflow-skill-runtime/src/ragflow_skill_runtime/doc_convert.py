"""Document-to-Markdown conversion helpers for public skills."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib import error, request
from urllib.parse import unquote, urljoin, urlparse

from .runtime_resilience import build_runtime_partial_failure_report


class DocConvertError(RuntimeError):
    """Raised when document conversion cannot proceed."""


class MinerUFastAPIError(DocConvertError):
    """Raised for categorized MinerU FastAPI async protocol failures."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        stage: str | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.category = category
        self.stage = stage
        self.http_status = http_status
        self.retryable = retryable


MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
TEXT_EXTENSIONS = {".txt", ".text"}
HTML_EXTENSIONS = {".html", ".htm"}
BUILTIN_EXTENSIONS = MARKDOWN_EXTENSIONS | TEXT_EXTENSIONS | HTML_EXTENSIONS
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PANDOC_AUTO_EXTENSIONS = {
    ".docx",
    ".epub",
    ".odt",
    ".rtf",
    ".rst",
    ".org",
    ".tex",
}
MINERU_AUTO_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}
DEFAULT_MINERU_BASE_URL = "https://mineru.net/api/v1/agent"
BACKEND_PROBE_REPORT_SCHEMA = "ragflow_doc_backend_probe_report_v1"
BACKEND_PROBE_STATUSES = ("available", "missing", "wrong_protocol", "timeout", "not_configured")
BACKEND_PROBE_RUNTIME_SUCCESS_STATUSES = ("available",)
BACKEND_PROBE_RUNTIME_FAILURE_STATUSES = ("missing", "wrong_protocol", "timeout")
BACKEND_PROBE_RUNTIME_SKIPPED_STATUSES = ("not_configured",)
BACKEND_WARMUP_REPORT_SCHEMA = "ragflow_doc_backend_warmup_report_v1"
BACKEND_WARMUP_STATUSES = ("success", "failed")
DOC_RUNTIME_REPORT_SCHEMA = "ragflow_doc_runtime_report_v1"
MINERU_FASTAPI_ASSET_SIDECAR_SCHEMA = "ragflow_mineru_fastapi_asset_sidecar_v1"
PROCESS_ATTEMPT_STATUSES = ("success", "failed", "timeout", "execution_error")
CONVERSION_BACKENDS = (
    "builtin",
    "pandoc",
    "mineru-cli",
    "remote",
    "mineru",
    "mineru-agent",
    "mineru-fastapi",
    "mineru-sync",
    "mineru-local",
)
MINERU_DONE_STATE = "done"
MINERU_FAILED_STATE = "failed"
MINERU_FASTAPI_DONE_STATES = {"completed", "done"}
MINERU_FASTAPI_FAILED_STATES = {"failed", "fail", "error"}
MINERU_FASTAPI_PENDING_STATES = {"pending", "processing", "queued", "running"}
MINERU_FASTAPI_RETRY_HTTP_CODES = {429, 500, 502, 503, 504}
MINERU_FASTAPI_DEFAULT_END_PAGE_ID = 99999
MINERU_FASTAPI_ASSET_MODES = {"markdown_only", "markdown_assets"}
MINERU_FASTAPI_MAX_IMAGE_BYTES = 512 * 1024 * 1024
MARKDOWN_IMAGE_RE = re.compile(r"(!\[[^\]]*]\()([^)]+)(\))")
HTML_IMAGE_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc=[\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)
DATA_URL_RE = re.compile(r"^data:([^;,]+)?(?:;[^,]*)?;base64,(.*)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    source_path: str


@dataclass(frozen=True)
class ConvertedDocument:
    source: SourceDocument
    markdown_path: Path
    sha256: str
    title: str | None = None
    warnings: list[str] = field(default_factory=list)
    assets: dict[str, Any] = field(default_factory=dict)

    def to_manifest_entry(self, *, output_root: Path) -> dict[str, Any]:
        entry = {
            "source_path": self.source.source_path,
            "markdown_path": self.markdown_path.relative_to(output_root).as_posix(),
            "sha256": self.sha256,
            "title": self.title,
            "warnings": list(self.warnings),
        }
        if self.assets:
            entry["assets"] = self.assets
        return entry


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_source_documents(input_path: str | Path, *, recursive: bool = True) -> list[SourceDocument]:
    """Discover input files from a file or directory."""

    root = Path(input_path).expanduser().resolve()
    if root.is_file():
        return [SourceDocument(path=root, source_path=root.name)]
    if not root.is_dir():
        raise DocConvertError(f"input path not found: {root}")

    pattern = "**/*" if recursive else "*"
    docs: list[SourceDocument] = []
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        docs.append(SourceDocument(path=path, source_path=rel))
    if not docs:
        raise DocConvertError(f"no input files found: {root}")
    return docs


def safe_markdown_name(source: SourceDocument, *, used: set[str]) -> str:
    """Create a stable, collision-resistant Markdown filename."""

    raw = source.source_path.rsplit("/", 1)[-1]
    stem = Path(raw).stem or "document"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "document"
    candidate = f"{safe}.md"
    counter = 2
    while candidate in used:
        candidate = f"{safe}-{counter}.md"
        counter += 1
    used.add(candidate)
    return candidate


def extract_markdown_title(markdown: str) -> str | None:
    """Extract a lightweight title from Markdown content."""

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            return title or None
        return stripped[:120]
    return None


def text_to_markdown(text: str, *, title: str | None = None) -> str:
    """Normalize plain text as Markdown."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    if title and not normalized.lstrip().startswith("#"):
        return f"# {title}\n\n{normalized}\n"
    return normalized + "\n"


class _HTMLToMarkdownParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[str] = []
        self.link_stack: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self._block()
            self.parts.append("#" * level + " ")
        elif tag in self.BLOCK_TAGS:
            self._block()
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"ul", "ol"}:
            self.list_stack.append(tag)
            self._block()
        elif tag == "li":
            self._block()
            marker = "1. " if self.list_stack and self.list_stack[-1] == "ol" else "- "
            self.parts.append(marker)
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code":
            self.parts.append("`")
        elif tag == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value
                    break
            self.link_stack.append(href)
            self.parts.append("[")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code":
            self.parts.append("`")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.parts.append(f"]({href})" if href else "]")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "li"} | self.BLOCK_TAGS:
            self._block()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._block()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = html.unescape(data)
        if text.strip():
            self.parts.append(re.sub(r"\s+", " ", text))

    def _block(self) -> None:
        current = "".join(self.parts)
        if current and not current.endswith("\n\n"):
            if current.endswith("\n"):
                self.parts.append("\n")
            else:
                self.parts.append("\n\n")

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + ("\n" if text.strip() else "")


def html_to_markdown(source: str) -> str:
    """Convert simple HTML to Markdown without external dependencies."""

    parser = _HTMLToMarkdownParser()
    parser.feed(source)
    return parser.markdown()


def remote_convert(
    source: SourceDocument,
    *,
    remote_url: str,
    api_key: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Convert a document through a remote JSON endpoint.

    The endpoint receives JSON with ``filename`` and base64 ``content`` and should
    return either ``{"markdown": "..."}`` or ``{"content": "..."}``.
    """

    payload = {
        "filename": source.path.name,
        "content_base64": base64.b64encode(source.path.read_bytes()).decode("ascii"),
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(
        remote_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"remote conversion failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise DocConvertError(f"remote conversion request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise DocConvertError("remote conversion response is not valid JSON") from exc

    if not isinstance(data, Mapping):
        raise DocConvertError("remote conversion response must be a JSON object")
    markdown = data.get("markdown") or data.get("content")
    if not isinstance(markdown, str):
        raise DocConvertError("remote conversion response must include markdown or content")
    return markdown


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 120.0,
) -> Mapping[str, Any]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise DocConvertError(f"MinerU request timed out after {timeout:g}s") from exc
    except socket.timeout as exc:
        raise DocConvertError(f"MinerU request timed out after {timeout:g}s") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise DocConvertError("MinerU response is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise DocConvertError("MinerU response must be a JSON object")
    code = data.get("code")
    if code not in (None, 0):
        message = data.get("msg") or data.get("message") or "unknown MinerU error"
        raise DocConvertError(f"MinerU API returned code {code}: {message}")
    return data


def _ssl_context(*, verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    return ssl._create_unverified_context()


def _download_text(url: str, *, timeout: float, verify_ssl: bool = True) -> str:
    req = request.Request(url, headers={"Accept": "text/markdown,text/plain,*/*"})
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            return resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU markdown download failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU markdown download failed: {exc.reason}") from exc


def _upload_file(upload_url: str, source: SourceDocument, *, timeout: float) -> None:
    req = request.Request(upload_url, data=source.path.read_bytes(), method="PUT")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 201, 204):
                raise DocConvertError(f"MinerU upload failed with HTTP {resp.status}")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU upload failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU upload failed: {exc.reason}") from exc


def _multipart_body(
    *,
    fields: Mapping[str, Any],
    file_field: str,
    filename: str,
    file_content: bytes,
) -> tuple[bytes, str]:
    boundary = f"----ragflow-skill-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        if value in (None, ""):
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item in (None, ""):
                continue
            rendered = "true" if item is True else "false" if item is False else str(item)
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                    rendered.encode("utf-8"),
                    b"\r\n",
                ]
            )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), boundary


def _extract_markdown_from_mapping(
    data: Mapping[str, Any],
    *,
    timeout: float,
    verify_ssl: bool = True,
) -> str | None:
    for key in ("markdown", "content", "md", "text", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    value = data.get("md_content")
    if isinstance(value, str) and value.strip():
        return value

    for key in ("markdown_url", "md_url", "url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _download_text(value, timeout=timeout, verify_ssl=verify_ssl)

    for key in ("data", "result", "results", "output"):
        value = data.get(key)
        if isinstance(value, Mapping):
            markdown = _extract_markdown_from_mapping(value, timeout=timeout, verify_ssl=verify_ssl)
            if markdown is not None:
                return markdown

    for value in data.values():
        if isinstance(value, Mapping):
            markdown = _extract_markdown_from_mapping(value, timeout=timeout, verify_ssl=verify_ssl)
            if markdown is not None:
                return markdown
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    markdown = _extract_markdown_from_mapping(item, timeout=timeout, verify_ssl=verify_ssl)
                    if markdown is not None:
                        return markdown
    return None


def _extract_markdown_candidate_from_mapping(
    data: Mapping[str, Any],
    *,
    timeout: float,
    verify_ssl: bool = True,
) -> tuple[bool, str | None]:
    for key in ("markdown", "content", "md", "text", "result", "md_content"):
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, str):
            return True, value
        if isinstance(value, Mapping):
            found, markdown = _extract_markdown_candidate_from_mapping(
                value,
                timeout=timeout,
                verify_ssl=verify_ssl,
            )
            if found:
                return found, markdown

    for key in ("markdown_url", "md_url", "url"):
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return True, _download_text(value, timeout=timeout, verify_ssl=verify_ssl)
        if isinstance(value, str):
            return True, ""

    for key in ("data", "result", "results", "output"):
        value = data.get(key)
        if isinstance(value, Mapping):
            found, markdown = _extract_markdown_candidate_from_mapping(
                value,
                timeout=timeout,
                verify_ssl=verify_ssl,
            )
            if found:
                return found, markdown

    for value in data.values():
        if isinstance(value, Mapping):
            found, markdown = _extract_markdown_candidate_from_mapping(
                value,
                timeout=timeout,
                verify_ssl=verify_ssl,
            )
            if found:
                return found, markdown
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    found, markdown = _extract_markdown_candidate_from_mapping(
                        item,
                        timeout=timeout,
                        verify_ssl=verify_ssl,
                    )
                    if found:
                        return found, markdown
    return False, None


def _validate_mineru_response_status(data: Mapping[str, Any]) -> None:
    success = data.get("success")
    if success is False:
        message = data.get("msg") or data.get("message") or data.get("error") or "unknown MinerU error"
        raise DocConvertError(f"MinerU sync API returned error: {message}")
    code = data.get("code")
    if code not in (None, 0, "0", 200, "200"):
        message = data.get("msg") or data.get("message") or data.get("error") or "unknown MinerU error"
        raise DocConvertError(f"MinerU sync API returned code {code}: {message}")
    status = data.get("status") or data.get("state")
    if isinstance(status, str) and status.lower() in {"error", "failed", "fail"}:
        message = data.get("msg") or data.get("message") or data.get("error") or "unknown MinerU error"
        raise DocConvertError(f"MinerU sync API returned status {status}: {message}")


def _mineru_sync_parse_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/parse"):
        return root
    return f"{root}/parse"


def _should_try_mineru_service_auto(base_url: str | None, api_key: str | None) -> bool:
    if not base_url:
        return False
    if base_url.rstrip("/") == DEFAULT_MINERU_BASE_URL and not api_key:
        return False
    return True


def mineru_agent_convert(
    source: SourceDocument,
    *,
    base_url: str = DEFAULT_MINERU_BASE_URL,
    api_key: str | None = None,
    timeout: float = 300.0,
    poll_interval: float = 3.0,
    language: str = "ch",
    page_range: str | None = None,
    enable_table: bool = True,
    is_ocr: bool = False,
    enable_formula: bool = True,
) -> str:
    """Convert one file with the MinerU Agent parsing API."""

    if timeout <= 0:
        raise DocConvertError("MinerU timeout must be greater than zero")
    if poll_interval <= 0:
        raise DocConvertError("MinerU poll interval must be greater than zero")
    root = base_url.rstrip("/")
    payload: dict[str, Any] = {
        "file_name": source.path.name,
        "language": language,
        "enable_table": enable_table,
        "is_ocr": is_ocr,
        "enable_formula": enable_formula,
    }
    if page_range:
        payload["page_range"] = page_range

    deadline = time.monotonic() + timeout
    create = _json_request(
        f"{root}/parse/file",
        method="POST",
        payload=payload,
        api_key=api_key,
        timeout=min(timeout, 120.0),
    )
    data = create.get("data")
    if not isinstance(data, Mapping):
        raise DocConvertError("MinerU create-task response missing data")
    task_id = data.get("task_id")
    upload_url = data.get("file_url")
    if not isinstance(task_id, str) or not task_id:
        raise DocConvertError("MinerU create-task response missing task_id")
    if not isinstance(upload_url, str) or not upload_url:
        raise DocConvertError("MinerU create-task response missing file_url")

    _upload_file(upload_url, source, timeout=min(max(deadline - time.monotonic(), 1.0), 120.0))

    last_state = "unknown"
    while time.monotonic() < deadline:
        remaining = max(deadline - time.monotonic(), 1.0)
        status = _json_request(
            f"{root}/parse/{task_id}",
            api_key=api_key,
            timeout=min(remaining, 120.0),
        )
        status_data = status.get("data")
        if not isinstance(status_data, Mapping):
            raise DocConvertError("MinerU status response missing data")
        state = status_data.get("state")
        last_state = str(state)
        if state == MINERU_DONE_STATE:
            markdown_url = status_data.get("markdown_url")
            if not isinstance(markdown_url, str) or not markdown_url:
                raise DocConvertError("MinerU completed without markdown_url")
            return _download_text(markdown_url, timeout=min(remaining, 120.0))
        if state == MINERU_FAILED_STATE:
            message = status_data.get("err_msg") or status_data.get("message") or "unknown error"
            raise DocConvertError(f"MinerU parsing failed: {message}")
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0.0)))

    raise DocConvertError(f"MinerU parsing timed out after {timeout:g}s; last state: {last_state}")


def mineru_sync_convert(
    source: SourceDocument,
    *,
    base_url: str,
    api_key: str | None = None,
    timeout: float = 300.0,
    language: str = "ch",
    page_range: str | None = None,
    enable_table: bool = True,
    is_ocr: bool = False,
    enable_formula: bool = True,
) -> str:
    """Convert one file through a synchronous MinerU multipart /parse API."""

    if timeout <= 0:
        raise DocConvertError("MinerU timeout must be greater than zero")
    url = _mineru_sync_parse_url(base_url)
    body, boundary = _multipart_body(
        fields={
            "language": language,
            "page_range": page_range,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        },
        file_field="file",
        filename=source.path.name,
        file_content=source.path.read_bytes(),
    )
    headers = {
        "Accept": "application/json,text/markdown,text/plain,*/*",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU sync request failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU sync request failed: {exc.reason}") from exc

    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if "json" not in content_type.lower() and not stripped.startswith("{"):
        if stripped:
            return text
        raise DocConvertError("MinerU sync response is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocConvertError("MinerU sync response is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise DocConvertError("MinerU sync response must be a JSON object")
    _validate_mineru_response_status(data)
    markdown = _extract_markdown_from_mapping(data, timeout=timeout)
    if not isinstance(markdown, str):
        raise DocConvertError("MinerU sync response must include markdown, content, text, result, or markdown_url")
    return markdown


def _multipart_json_request(
    url: str,
    *,
    fields: Mapping[str, Any],
    file_field: str,
    filename: str,
    file_content: bytes,
    api_key: str | None = None,
    timeout: float = 120.0,
) -> Mapping[str, Any]:
    body, boundary = _multipart_body(
        fields=fields,
        file_field=file_field,
        filename=filename,
        file_content=file_content,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU FastAPI request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise DocConvertError(f"MinerU FastAPI request timed out after {timeout:g}s") from exc
    except socket.timeout as exc:
        raise DocConvertError(f"MinerU FastAPI request timed out after {timeout:g}s") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU FastAPI request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise DocConvertError("MinerU FastAPI response is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise DocConvertError("MinerU FastAPI response must be a JSON object")
    return data


def _redacted_endpoint(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"}:
        return "<redacted-endpoint>"
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://<redacted-host>{path}"


def _trim_remote_detail(detail: str, *, limit: int = 500) -> str:
    value = re.sub(r"https?://[^\s\"'<>]+", "<redacted-url>", detail.strip())
    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", value)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _mineru_fastapi_http_category(code: int) -> str:
    if code in {401, 403}:
        return "auth_failed"
    if code in {408, 504}:
        return "request_timeout"
    if code == 429 or 500 <= code <= 599:
        return "transient_remote_error"
    return "protocol_error"


def _mineru_fastapi_request_json_once(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 120.0,
    verify_ssl: bool = True,
    stage: str,
) -> Mapping[str, Any]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = _trim_remote_detail(exc.read().decode("utf-8", errors="replace"))
        category = _mineru_fastapi_http_category(exc.code)
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} failed with HTTP {exc.code}: {detail}",
            category=category,
            stage=stage,
            http_status=exc.code,
            retryable=exc.code in MINERU_FASTAPI_RETRY_HTTP_CODES,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} timed out after {timeout:g}s",
            category="request_timeout",
            stage=stage,
            retryable=True,
        ) from exc
    except error.URLError as exc:
        reason = exc.reason
        category = "request_timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "transient_remote_error"
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} request failed: {reason}",
            category=category,
            stage=stage,
            retryable=True,
        ) from exc
    except OSError as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} request failed: {exc}",
            category="transient_remote_error",
            stage=stage,
            retryable=True,
        ) from exc
    except json.JSONDecodeError as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response is not valid JSON",
            category="protocol_error",
            stage=stage,
        ) from exc
    if not isinstance(data, Mapping):
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response must be a JSON object",
            category="protocol_error",
            stage=stage,
        )
    code = data.get("code")
    if code not in (None, 0, "0", 200, "200"):
        message = data.get("msg") or data.get("message") or data.get("error") or "unknown MinerU FastAPI error"
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response returned code {code}: {message}",
            category="protocol_error",
            stage=stage,
        )
    return data


def _mineru_fastapi_multipart_json_once(
    url: str,
    *,
    fields: Mapping[str, Any],
    file_field: str,
    filename: str,
    file_content: bytes,
    api_key: str | None = None,
    timeout: float = 120.0,
    verify_ssl: bool = True,
    stage: str,
) -> Mapping[str, Any]:
    body, boundary = _multipart_body(
        fields=fields,
        file_field=file_field,
        filename=filename,
        file_content=file_content,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = _trim_remote_detail(exc.read().decode("utf-8", errors="replace"))
        category = _mineru_fastapi_http_category(exc.code)
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} failed with HTTP {exc.code}: {detail}",
            category=category,
            stage=stage,
            http_status=exc.code,
            retryable=exc.code in MINERU_FASTAPI_RETRY_HTTP_CODES,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} timed out after {timeout:g}s",
            category="request_timeout",
            stage=stage,
            retryable=True,
        ) from exc
    except error.URLError as exc:
        reason = exc.reason
        category = "request_timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "transient_remote_error"
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} request failed: {reason}",
            category=category,
            stage=stage,
            retryable=True,
        ) from exc
    except OSError as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} request failed: {exc}",
            category="transient_remote_error",
            stage=stage,
            retryable=True,
        ) from exc
    except json.JSONDecodeError as exc:
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response is not valid JSON",
            category="protocol_error",
            stage=stage,
        ) from exc
    if not isinstance(data, Mapping):
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response must be a JSON object",
            category="protocol_error",
            stage=stage,
        )
    code = data.get("code")
    if code not in (None, 0, "0", 200, "200"):
        message = data.get("msg") or data.get("message") or data.get("error") or "unknown MinerU FastAPI error"
        raise MinerUFastAPIError(
            f"MinerU FastAPI {stage} response returned code {code}: {message}",
            category="protocol_error",
            stage=stage,
        )
    return data


def _mineru_fastapi_retry_delay(backoff: float, retry_index: int, *, deadline: float) -> float:
    delay = max(backoff, 0.0) * (2 ** max(retry_index - 1, 0))
    remaining = max(deadline - time.monotonic(), 0.0)
    return min(delay, remaining)


def _mineru_fastapi_call_with_retries(
    operation,
    *,
    stage: str,
    deadline: float,
    retry_budget: int,
    retry_backoff_seconds: float,
    metrics: dict[str, int],
) -> Mapping[str, Any]:
    retries = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MinerUFastAPIError(
                f"MinerU FastAPI {stage} timed out before the next request",
                category="request_timeout",
                stage=stage,
            )
        metrics["http_attempts"] = int(metrics.get("http_attempts", 0)) + 1
        try:
            return operation(timeout=min(max(remaining, 0.1), 120.0))
        except MinerUFastAPIError as exc:
            if not exc.retryable or retries >= retry_budget:
                raise
            delay = _mineru_fastapi_retry_delay(retry_backoff_seconds, retries + 1, deadline=deadline)
            if delay <= 0:
                raise
            retries += 1
            metrics["retry_count"] = int(metrics.get("retry_count", 0)) + 1
            time.sleep(delay)


def _mineru_fastapi_page_bounds(page_range: str | None) -> tuple[int, int]:
    if not page_range:
        return 0, MINERU_FASTAPI_DEFAULT_END_PAGE_ID
    value = page_range.strip()
    if not value:
        return 0, MINERU_FASTAPI_DEFAULT_END_PAGE_ID
    if value.lower() in {"all", "*"}:
        return 0, MINERU_FASTAPI_DEFAULT_END_PAGE_ID
    if "-" in value:
        start_raw, end_raw = value.split("-", 1)
        start_page_id = int(start_raw.strip()) if start_raw.strip() else 0
        end_page_id = (
            int(end_raw.strip()) if end_raw.strip() else MINERU_FASTAPI_DEFAULT_END_PAGE_ID
        )
    else:
        start_page_id = int(value)
        end_page_id = start_page_id
    if start_page_id < 0 or end_page_id < 0 or end_page_id < start_page_id:
        raise DocConvertError("MinerU FastAPI page_range must have non-negative start and end page ids")
    return start_page_id, end_page_id


def _mineru_fastapi_language_list(language: str) -> list[str]:
    values = [item.strip() for item in str(language or "ch").split(",")]
    return [item for item in values if item] or ["ch"]


def _normalize_mineru_fastapi_asset_mode(asset_mode: str | None) -> str:
    mode = (asset_mode or "markdown_only").strip().lower().replace("-", "_")
    if mode not in MINERU_FASTAPI_ASSET_MODES:
        allowed = ", ".join(sorted(MINERU_FASTAPI_ASSET_MODES))
        raise DocConvertError(f"MinerU FastAPI asset mode must be one of: {allowed}")
    return mode


def _mineru_fastapi_asset_policy(
    fields: Mapping[str, Any],
    *,
    asset_mode: str,
    saved_images: int = 0,
    image_paths: list[str] | None = None,
    image_assets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    saved_image_paths = list(image_paths or [])
    sidecar_status = "not_requested" if asset_mode == "markdown_only" else "saved"
    if asset_mode != "markdown_only" and saved_images == 0:
        sidecar_status = "requested_empty"
    return {
        "mode": asset_mode,
        "sidecar_schema": MINERU_FASTAPI_ASSET_SIDECAR_SCHEMA,
        "sidecar_status": sidecar_status,
        "requested": {
            "return_md": bool(fields.get("return_md")),
            "return_images": bool(fields.get("return_images")),
            "return_content_list": bool(fields.get("return_content_list")),
            "return_middle_json": bool(fields.get("return_middle_json")),
            "return_model_output": bool(fields.get("return_model_output")),
        },
        "saved": {
            "images": saved_images > 0,
            "image_count": saved_images,
            "image_paths": saved_image_paths[:50],
            "image_assets": [_public_image_asset_record(item) for item in list(image_assets or [])[:50]],
            "content_list": False,
            "middle_json": False,
            "model_output": False,
        },
        "manifest_assets": saved_images > 0,
        "reason": (
            "Markdown-only release path; MinerU structured assets were not requested."
            if asset_mode == "markdown_only"
            else "Markdown asset mode requested MinerU images and saved recognized image assets beside Markdown."
        ),
    }


def _download_bytes(url: str, *, timeout: float, verify_ssl: bool = True, api_key: str | None = None) -> bytes:
    headers = {"Accept": "image/*,application/octet-stream,*/*"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            return resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DocConvertError(f"MinerU asset download failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise DocConvertError(f"MinerU asset download failed: {exc.reason}") from exc


def _safe_asset_filename(value: str | None, *, default: str) -> str:
    raw = (value or default).strip().replace("\\", "/")
    name = PurePosixPath(raw).name or default
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or default
    suffix = Path(safe).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        safe = f"{safe}.png"
    return safe


def _looks_like_download_url(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} or text.startswith("/")


def _resolve_asset_url(value: str, *, base_url: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return text
    return urljoin(f"{base_url.rstrip('/')}/", text)


def _public_image_asset_record(item: Mapping[str, str]) -> dict[str, str]:
    record: dict[str, str] = {"path": item.get("path", "")}
    if item.get("sha256"):
        record["sha256"] = item["sha256"]
    if item.get("bytes"):
        record["bytes"] = item["bytes"]
    return record


def _safe_asset_stem(source: SourceDocument) -> str:
    stem = Path(source.source_path).stem or source.path.stem or "document"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "document"


def _safe_asset_document_stem(value: str | None, *, source: SourceDocument) -> str:
    if not value:
        return _safe_asset_stem(source)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or _safe_asset_stem(source)


def _asset_reference_keys(value: str | None) -> set[str]:
    if not value:
        return set()
    raw = value.strip()
    if not raw:
        return set()
    decoded = unquote(raw).replace("\\", "/")
    keys = {decoded, decoded.lstrip("./")}
    basename = PurePosixPath(decoded).name
    if basename:
        keys.add(basename)
    return {item for item in keys if item}


def _decode_inline_asset(value: str) -> tuple[bytes | None, str | None]:
    stripped = value.strip()
    if not stripped:
        return None, None
    match = DATA_URL_RE.match(stripped)
    if match:
        media_type = (match.group(1) or "").lower()
        payload = match.group(2).strip()
        try:
            return base64.b64decode(payload, validate=True), media_type
        except (ValueError, TypeError):
            return None, media_type
    if stripped.lower().startswith(("http://", "https://")):
        return None, None
    try:
        return base64.b64decode(stripped, validate=True), None
    except (ValueError, TypeError):
        return None, None


def _image_suffix_from_media_type(media_type: str | None) -> str | None:
    if not media_type:
        return None
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return mapping.get(media_type.lower())


def _asset_candidate_from_mapping(
    data: Mapping[str, Any],
    *,
    default_key: str | None = None,
) -> dict[str, Any] | None:
    source_key = str(
        data.get("source_key")
        or data.get("key")
        or data.get("path")
        or data.get("relative_path")
        or data.get("filename")
        or data.get("file_name")
        or data.get("name")
        or default_key
        or ""
    )
    filename = str(
        data.get("filename")
        or data.get("file_name")
        or data.get("name")
        or data.get("path")
        or data.get("relative_path")
        or default_key
        or "image.png"
    )
    content_value = (
        data.get("content")
        or data.get("data")
        or data.get("base64")
        or data.get("b64")
        or data.get("image_base64")
        or data.get("data_base64")
    )
    url = data.get("url") or data.get("image_url") or data.get("download_url")
    if isinstance(content_value, str):
        return {"source_key": source_key, "filename": filename, "content": content_value}
    if isinstance(url, str) and _looks_like_download_url(url):
        return {"source_key": source_key or url, "filename": filename or url, "url": url}
    return None


def _asset_candidates_from_value(value: Any, *, default_key: str | None = None) -> list[dict[str, Any]]:
    if isinstance(value, str):
        if _looks_like_download_url(value):
            return [{"source_key": default_key or value, "filename": default_key or value, "url": value}]
        if _decode_inline_asset(value)[0] is not None:
            return [{"source_key": default_key or value, "filename": default_key or "image.png", "content": value}]
        return []
    if isinstance(value, Mapping):
        candidate = _asset_candidate_from_mapping(value, default_key=default_key)
        return [candidate] if candidate else []
    if isinstance(value, list):
        output: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            output.extend(_asset_candidates_from_value(item, default_key=default_key or f"image-{index}.png"))
        return output
    return []


def _collect_mineru_fastapi_image_candidates(data: Any) -> list[dict[str, Any]]:
    image_keys = {"images", "image", "image_artifacts", "assets", "files"}
    zip_keys = {"zip", "zip_content", "zip_base64", "zip_data", "result_zip", "output_zip"}
    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                if key_lower in image_keys:
                    if isinstance(item, Mapping):
                        for image_key, image_value in item.items():
                            candidates.extend(_asset_candidates_from_value(image_value, default_key=str(image_key)))
                    else:
                        candidates.extend(_asset_candidates_from_value(item))
                elif key_lower in zip_keys and isinstance(item, str):
                    candidates.append({"source_key": key_text, "filename": f"{key_text}.zip", "zip_content": item})
                elif isinstance(item, (Mapping, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(data)
    return candidates


def _extract_zip_image_assets(value: str) -> list[dict[str, Any]]:
    payload, _ = _decode_inline_asset(value)
    if not payload:
        return []
    output: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                suffix = Path(name).suffix.lower()
                if suffix not in IMAGE_EXTENSIONS:
                    continue
                with archive.open(name) as handle:
                    output.append({"source_key": name, "filename": name, "bytes": handle.read()})
    except zipfile.BadZipFile:
        return []
    return output


def _write_mineru_fastapi_image_assets(
    result_payload: Mapping[str, Any],
    *,
    source: SourceDocument,
    asset_output_dir: str | Path,
    asset_document_stem: str | None,
    base_url: str,
    api_key: str | None,
    timeout: float,
    verify_ssl: bool,
) -> list[dict[str, str]]:
    output_root = Path(asset_output_dir)
    document_stem = _safe_asset_document_stem(asset_document_stem, source=source)
    image_dir = output_root / "images" / document_stem
    staging_dir = output_root / "images" / f".{document_stem}.tmp-{uuid.uuid4().hex}"
    saved: list[dict[str, str]] = []
    used_names: set[str] = set()

    def unique_name(raw_name: str | None, *, default: str) -> str:
        base = _safe_asset_filename(raw_name, default=default)
        candidate = base
        counter = 2
        while candidate in used_names:
            path = Path(base)
            candidate = f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        used_names.add(candidate)
        return candidate

    candidates: list[dict[str, Any]] = []
    for candidate in _collect_mineru_fastapi_image_candidates(result_payload):
        if "zip_content" in candidate:
            candidates.extend(_extract_zip_image_assets(str(candidate["zip_content"])))
        else:
            candidates.append(candidate)

    try:
        for index, candidate in enumerate(candidates, start=1):
            raw_bytes = candidate.get("bytes")
            media_type = None
            if isinstance(raw_bytes, bytes):
                content = raw_bytes
            elif isinstance(candidate.get("url"), str):
                content = _download_bytes(
                    _resolve_asset_url(str(candidate["url"]), base_url=base_url),
                    timeout=timeout,
                    verify_ssl=verify_ssl,
                    api_key=api_key,
                )
            elif isinstance(candidate.get("content"), str):
                content, media_type = _decode_inline_asset(str(candidate["content"]))
                if content is None and _looks_like_download_url(str(candidate["content"])):
                    content = _download_bytes(
                        _resolve_asset_url(str(candidate["content"]), base_url=base_url),
                        timeout=timeout,
                        verify_ssl=verify_ssl,
                        api_key=api_key,
                    )
            else:
                content = None
            if not content:
                continue
            if len(content) > MINERU_FASTAPI_MAX_IMAGE_BYTES:
                raise DocConvertError(
                    f"MinerU image asset exceeds the maximum supported size "
                    f"({len(content)} > {MINERU_FASTAPI_MAX_IMAGE_BYTES} bytes)"
                )
            raw_filename = str(candidate.get("filename") or "")
            media_suffix = _image_suffix_from_media_type(media_type)
            default_filename = f"image-{index}{media_suffix or '.png'}"
            raw_suffix = Path(PurePosixPath(raw_filename.replace("\\", "/")).name).suffix.lower()
            filename_seed = raw_filename
            if media_suffix and raw_suffix not in IMAGE_EXTENSIONS:
                raw_stem = Path(PurePosixPath(raw_filename.replace("\\", "/")).name).stem or Path(default_filename).stem
                filename_seed = f"{raw_stem}{media_suffix}"
            filename = unique_name(filename_seed, default=default_filename)
            staging_dir.mkdir(parents=True, exist_ok=True)
            destination = staging_dir / filename
            destination.write_bytes(content)
            relative = (Path("images") / document_stem / filename).as_posix()
            source_key = str(candidate.get("source_key") or candidate.get("filename") or filename)
            saved.append(
                {
                    "source_key": source_key,
                    "path": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": str(len(content)),
                }
            )
        if saved:
            image_dir.parent.mkdir(parents=True, exist_ok=True)
            if image_dir.exists():
                shutil.rmtree(image_dir)
            staging_dir.rename(image_dir)
        elif staging_dir.exists():
            shutil.rmtree(staging_dir)
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise
    return saved


def _rewrite_mineru_fastapi_asset_references(markdown: str, saved_assets: list[dict[str, str]]) -> str:
    if not saved_assets:
        return markdown
    exact: dict[str, str] = {}
    basename: dict[str, str | None] = {}
    for item in saved_assets:
        path = item["path"]
        for key in _asset_reference_keys(item.get("source_key")) | _asset_reference_keys(item.get("path")):
            exact[key] = path
            base = PurePosixPath(key).name
            if base:
                basename[base] = path if base not in basename else None

    def replacement_for(raw: str) -> str | None:
        target, suffix, angle_wrapped = _split_markdown_asset_target(raw)
        target_keys = _asset_reference_keys(target)
        for key in target_keys:
            if key in exact:
                value = exact[key]
                return f"<{value}>{suffix}" if angle_wrapped else f"{value}{suffix}"
        base = PurePosixPath(unquote(target).replace("\\", "/")).name
        if base and basename.get(base):
            value = basename[base]
            return f"<{value}>{suffix}" if angle_wrapped else f"{value}{suffix}"
        return None

    def replace_markdown(match: re.Match[str]) -> str:
        prefix, raw_target, suffix = match.groups()
        replacement = replacement_for(raw_target)
        if not replacement:
            return match.group(0)
        return f"{prefix}{replacement}{suffix}"

    def replace_html(match: re.Match[str]) -> str:
        prefix, raw_target, suffix = match.groups()
        replacement = replacement_for(raw_target)
        if not replacement:
            return match.group(0)
        target, _, _ = _split_markdown_asset_target(replacement)
        return f"{prefix}{target}{suffix}"

    markdown = MARKDOWN_IMAGE_RE.sub(replace_markdown, markdown)
    return HTML_IMAGE_SRC_RE.sub(replace_html, markdown)


def _extract_mineru_task_id(data: Mapping[str, Any]) -> str:
    task_id = data.get("task_id")
    if isinstance(task_id, str) and task_id:
        return task_id
    nested = data.get("data")
    if isinstance(nested, Mapping):
        task_id = nested.get("task_id")
        if isinstance(task_id, str) and task_id:
            return task_id
    raise MinerUFastAPIError(
        "MinerU FastAPI create-task response missing task_id",
        category="protocol_error",
        stage="submit",
    )


def _mineru_fastapi_status_state(data: Mapping[str, Any]) -> str:
    state = data.get("status") or data.get("state")
    if not isinstance(state, str):
        nested = data.get("data")
        if isinstance(nested, Mapping):
            state = nested.get("status") or nested.get("state")
    if not isinstance(state, str):
        raise MinerUFastAPIError(
            "MinerU FastAPI status response missing status",
            category="protocol_error",
            stage="poll",
        )
    return state


def _mineru_fastapi_error_message(data: Mapping[str, Any]) -> str:
    for key in ("error", "message", "detail", "msg", "err_msg"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown error"


def _probe_mineru_fastapi_backend(
    *,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    network_check: bool,
    timeout: float,
    verify_ssl: bool = True,
) -> dict[str, Any]:
    valid, reason = _valid_http_url(base_url)
    checks = [
        {"name": "url_configured", "ok": bool(base_url)},
        {"name": "http_url", "ok": valid},
    ]
    if not base_url:
        return _backend_probe_entry(backend, "not_configured", [reason], checks)
    if not valid:
        return _backend_probe_entry(backend, "wrong_protocol", [reason], checks)
    if not network_check:
        checks.append({"name": "network_check", "ok": None, "skipped": True})
        return _backend_probe_entry(
            backend,
            "available",
            [reason, "network check disabled"],
            checks,
        )

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(f"{base_url.rstrip('/')}/health", headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403} and not api_key:
            checks.append({"name": "api_key_configured", "ok": False})
            return _backend_probe_entry(
                backend,
                "not_configured",
                ["MinerU FastAPI health endpoint requires an API key"],
                checks,
            )
        if exc.code == 404:
            checks.append({"name": "health_endpoint", "ok": False})
            return _backend_probe_entry(
                backend,
                "missing",
                [f"health endpoint not found: HTTP {exc.code}: {detail}"],
                checks,
            )
        if exc.code in {401, 403}:
            checks.append({"name": "api_key_configured", "ok": bool(api_key)})
            return _backend_probe_entry(
                backend,
                "wrong_protocol",
                [f"MinerU FastAPI health endpoint rejected the request: HTTP {exc.code}: {detail}"],
                checks,
            )
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(
            backend,
            "wrong_protocol",
            [f"health endpoint returned HTTP {exc.code}: {detail}"],
            checks,
        )
    except TimeoutError:
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(backend, "timeout", [f"health probe timed out after {timeout:g}s"], checks)
    except socket.timeout:
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(backend, "timeout", [f"health probe timed out after {timeout:g}s"], checks)
    except error.URLError as exc:
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(backend, "missing", [f"health probe failed: {exc.reason}"], checks)
    except json.JSONDecodeError as exc:
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(backend, "wrong_protocol", ["health endpoint did not return valid JSON"], checks)
    except OSError as exc:
        checks.append({"name": "health_endpoint", "ok": False})
        return _backend_probe_entry(backend, "missing", [f"health probe failed: {exc}"], checks)

    if not isinstance(payload, Mapping):
        checks.append({"name": "health_payload", "ok": False})
        return _backend_probe_entry(backend, "wrong_protocol", ["health endpoint did not return a JSON object"], checks)

    status = payload.get("status")
    protocol_version = payload.get("protocol_version")
    checks.append({"name": "health_status", "ok": status == "healthy"})
    checks.append({"name": "protocol_version", "ok": protocol_version == 2})
    checks.append({"name": "verify_ssl", "ok": bool(verify_ssl)})
    if not isinstance(status, str):
        return _backend_probe_entry(
            backend,
            "wrong_protocol",
            ["health endpoint status field must be a string"],
            checks,
        )
    if status == "healthy" and protocol_version == 2:
        return _backend_probe_entry(
            backend,
            "available",
            ["MinerU FastAPI health endpoint reported healthy"],
            checks,
        )
    if status == "healthy":
        return _backend_probe_entry(
            backend,
            "wrong_protocol",
            [f"MinerU FastAPI protocol_version must be 2; got {protocol_version!r}"],
            checks,
        )

    if status == "unhealthy" and not api_key and payload.get("error"):
        return _backend_probe_entry(
            backend,
            "not_configured",
            [str(payload.get("error"))],
            checks,
        )

    message = payload.get("error") or payload.get("detail") or payload.get("message") or "health endpoint did not report healthy"
    return _backend_probe_entry(
        backend,
        "wrong_protocol",
        [str(message)],
        checks,
    )


def mineru_fastapi_convert(
    source: SourceDocument,
    *,
    base_url: str,
    api_key: str | None = None,
    timeout: float = 300.0,
    poll_interval: float = 3.0,
    verify_ssl: bool = True,
    language: str = "ch",
    page_range: str | None = None,
    enable_table: bool = True,
    is_ocr: bool = False,
    enable_formula: bool = True,
    asset_mode: str = "markdown_only",
    asset_output_dir: str | Path | None = None,
    asset_document_stem: str | None = None,
    remote_attempts: list[dict[str, Any]] | None = None,
    retry_budget: int = 2,
    retry_backoff_seconds: float = 0.25,
) -> str:
    """Convert one file through the MinerU 3.2+ FastAPI async task API."""

    if timeout <= 0:
        raise DocConvertError("MinerU FastAPI timeout must be greater than zero")
    if poll_interval <= 0:
        raise DocConvertError("MinerU FastAPI poll interval must be greater than zero")
    if retry_budget < 0:
        raise DocConvertError("MinerU FastAPI retry budget must be zero or greater")
    if retry_backoff_seconds < 0:
        raise DocConvertError("MinerU FastAPI retry backoff must be zero or greater")
    if not base_url:
        raise DocConvertError("mineru-fastapi backend requires --mineru-base-url or MINERU_BASE_URL")
    normalized_asset_mode = _normalize_mineru_fastapi_asset_mode(asset_mode)
    if normalized_asset_mode != "markdown_only" and asset_output_dir is None:
        raise DocConvertError("MinerU FastAPI markdown_assets mode requires an asset output directory")

    start_page_id, end_page_id = _mineru_fastapi_page_bounds(page_range)
    root = base_url.rstrip("/")
    request_images = normalized_asset_mode == "markdown_assets"
    fields: dict[str, Any] = {
        "lang_list": _mineru_fastapi_language_list(language),
        "backend": "pipeline",
        "parse_method": "ocr" if is_ocr else "auto",
        "formula_enable": enable_formula,
        "table_enable": enable_table,
        "image_analysis": True,
        "return_md": True,
        "return_middle_json": False,
        "return_model_output": False,
        "return_content_list": False,
        "return_images": request_images,
        "response_format_zip": False,
        "return_original_file": False,
        "client_side_output_generation": False,
        "start_page_id": start_page_id,
        "end_page_id": end_page_id,
    }

    metrics = {"http_attempts": 0, "retry_count": 0}
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    attempt: dict[str, Any] = {
        "source_path": source.source_path,
        "backend": "mineru-fastapi",
        "endpoint": _redacted_endpoint(root),
        "status": "failed",
        "task_id": None,
        "poll_count": 0,
        "status_history": [],
        "final_status": None,
        "submit_duration_ms": None,
        "result_fetch_duration_ms": None,
        "total_duration_ms": None,
        "timeout_seconds": timeout,
        "poll_interval_seconds": poll_interval,
        "http_attempts": 0,
        "retry_count": 0,
        "retry_budget": retry_budget,
        "retry_backoff_seconds": retry_backoff_seconds,
        "verify_ssl": bool(verify_ssl),
        "asset_policy": _mineru_fastapi_asset_policy(fields, asset_mode=normalized_asset_mode),
        "error_category": None,
        "error": None,
        "failed_stage": None,
    }
    task_id: str | None = None
    stage = "submit"
    try:
        submit_started = time.monotonic()
        create = _mineru_fastapi_call_with_retries(
            lambda *, timeout: _mineru_fastapi_multipart_json_once(
                f"{root}/tasks",
                fields=fields,
                file_field="files",
                filename=source.path.name,
                file_content=source.path.read_bytes(),
                api_key=api_key,
                timeout=timeout,
                verify_ssl=verify_ssl,
                stage="submit",
            ),
            stage="submit",
            deadline=deadline,
            retry_budget=retry_budget,
            retry_backoff_seconds=retry_backoff_seconds,
            metrics=metrics,
        )
        attempt["submit_duration_ms"] = round((time.monotonic() - submit_started) * 1000, 3)
        task_id = _extract_mineru_task_id(create)
        attempt["task_id"] = task_id

        last_state = "unknown"
        while time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), 0.1)
            stage = "poll"
            status_payload = _mineru_fastapi_call_with_retries(
                lambda *, timeout: _mineru_fastapi_request_json_once(
                    f"{root}/tasks/{task_id}",
                    api_key=api_key,
                    timeout=timeout,
                    verify_ssl=verify_ssl,
                    stage="poll",
                ),
                stage="poll",
                deadline=deadline,
                retry_budget=retry_budget,
                retry_backoff_seconds=retry_backoff_seconds,
                metrics=metrics,
            )
            state = _mineru_fastapi_status_state(status_payload)
            normalized_state = state.lower()
            last_state = state
            attempt["poll_count"] = int(attempt["poll_count"]) + 1
            attempt["final_status"] = state
            status_history = attempt["status_history"]
            if isinstance(status_history, list):
                status_history.append(state)
            if normalized_state in MINERU_FASTAPI_DONE_STATES:
                stage = "result"
                result_started = time.monotonic()
                result_payload = _mineru_fastapi_call_with_retries(
                    lambda *, timeout: _mineru_fastapi_request_json_once(
                        f"{root}/tasks/{task_id}/result",
                        api_key=api_key,
                        timeout=timeout,
                        verify_ssl=verify_ssl,
                        stage="result",
                    ),
                    stage="result",
                    deadline=deadline,
                    retry_budget=retry_budget,
                    retry_backoff_seconds=retry_backoff_seconds,
                    metrics=metrics,
                )
                attempt["result_fetch_duration_ms"] = round((time.monotonic() - result_started) * 1000, 3)
                found, markdown = _extract_markdown_candidate_from_mapping(
                    result_payload,
                    timeout=remaining,
                    verify_ssl=verify_ssl,
                )
                if not found:
                    raise MinerUFastAPIError(
                        "MinerU FastAPI result response must include md_content, markdown, content, text, result, or markdown_url",
                        category="result_missing",
                        stage="result",
                    )
                if not isinstance(markdown, str) or not markdown.strip():
                    raise MinerUFastAPIError(
                        "MinerU FastAPI task completed but produced empty Markdown",
                        category="result_empty",
                        stage="result",
                    )
                saved_assets: list[dict[str, str]] = []
                if normalized_asset_mode == "markdown_assets" and asset_output_dir is not None:
                    saved_assets = _write_mineru_fastapi_image_assets(
                        result_payload,
                        source=source,
                        asset_output_dir=asset_output_dir,
                        asset_document_stem=asset_document_stem,
                        base_url=root,
                        api_key=api_key,
                        timeout=remaining,
                        verify_ssl=verify_ssl,
                    )
                    markdown = _rewrite_mineru_fastapi_asset_references(markdown, saved_assets)
                    attempt["asset_policy"] = _mineru_fastapi_asset_policy(
                        fields,
                        asset_mode=normalized_asset_mode,
                        saved_images=len(saved_assets),
                        image_paths=[item["path"] for item in saved_assets],
                        image_assets=saved_assets,
                    )
                attempt["status"] = "success"
                return markdown
            if normalized_state in MINERU_FASTAPI_FAILED_STATES:
                message = _mineru_fastapi_error_message(status_payload)
                raise MinerUFastAPIError(
                    f"MinerU FastAPI parsing failed: {message}",
                    category="task_failed",
                    stage="poll",
                )
            if normalized_state not in MINERU_FASTAPI_PENDING_STATES:
                raise MinerUFastAPIError(
                    f"MinerU FastAPI status response returned unknown state: {state}",
                    category="protocol_error",
                    stage="poll",
                )
            time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0.0)))

        raise MinerUFastAPIError(
            f"MinerU FastAPI parsing timed out after {timeout:g}s; last state: {last_state}",
            category="request_timeout",
            stage="poll",
        )
    except MinerUFastAPIError as exc:
        attempt["status"] = "timeout" if exc.category == "request_timeout" else "failed"
        attempt["error_category"] = exc.category
        attempt["failed_stage"] = exc.stage or stage
        attempt["error"] = str(exc)
        raise
    except DocConvertError as exc:
        attempt["status"] = "failed"
        attempt["error_category"] = "protocol_error"
        attempt["failed_stage"] = stage
        attempt["error"] = str(exc)
        raise
    finally:
        attempt["http_attempts"] = int(metrics.get("http_attempts", 0))
        attempt["retry_count"] = int(metrics.get("retry_count", 0))
        attempt["total_duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        if remote_attempts is not None:
            remote_attempts.append(attempt)


def resolve_mineru_cli_path(cli_path: str | None = None) -> str | None:
    """Resolve a local MinerU CLI path from explicit config, environment, or PATH."""

    candidate = cli_path or os.environ.get("MINERU_CLI_PATH") or None
    if not candidate:
        candidate = shutil.which("mineru")
    if not candidate:
        return None
    if "/" not in candidate and "\\" not in candidate:
        return shutil.which(candidate)

    path = Path(candidate).expanduser()
    if path.exists() and path.is_file():
        return str(path.resolve())
    return None


def _valid_http_url(value: str | None) -> tuple[bool, str]:
    if not value:
        return False, "endpoint URL is not configured"
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "endpoint URL must use http or https"
    return True, f"{parsed.scheme} endpoint configured"


def _network_probe(url: str, *, timeout: float) -> tuple[str, list[str]]:
    req = request.Request(url, method="HEAD", headers={"User-Agent": "ragflow-doc-to-md-backend-probe"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return "available", [f"endpoint responded with HTTP {resp.status}"]
    except error.HTTPError as exc:
        if exc.code in {401, 403, 405, 415} or 200 <= exc.code < 500 and exc.code != 404:
            return "available", [f"endpoint responded with HTTP {exc.code}; service is reachable"]
        return "wrong_protocol", [f"endpoint responded with HTTP {exc.code}"]
    except TimeoutError:
        return "timeout", [f"endpoint probe timed out after {timeout:g}s"]
    except socket.timeout:
        return "timeout", [f"endpoint probe timed out after {timeout:g}s"]
    except error.URLError as exc:
        if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
            return "timeout", [f"endpoint probe timed out after {timeout:g}s"]
        return "missing", [f"endpoint probe failed: {exc.reason}"]
    except OSError as exc:
        return "missing", [f"endpoint probe failed: {exc}"]


def _probe_http_backend(
    *,
    backend: str,
    url: str | None,
    network_check: bool,
    timeout: float,
    requires_api_key: bool = False,
    api_key: str | None = None,
) -> dict[str, Any]:
    valid, reason = _valid_http_url(url)
    checks = [{"name": "url_configured", "ok": bool(url)}, {"name": "http_url", "ok": valid}]
    if requires_api_key:
        checks.append({"name": "api_key_configured", "ok": bool(api_key)})
    if not url or requires_api_key and not api_key:
        reasons = [reason] if not url else ["API key is not configured"]
        return _backend_probe_entry(backend, "not_configured", reasons, checks)
    if not valid:
        return _backend_probe_entry(backend, "wrong_protocol", [reason], checks)
    if network_check:
        status, reasons = _network_probe(str(url), timeout=timeout)
        checks.append({"name": "network_check", "ok": status == "available"})
        return _backend_probe_entry(backend, status, reasons, checks)
    checks.append({"name": "network_check", "ok": None, "skipped": True})
    return _backend_probe_entry(
        backend,
        "available",
        [reason, "network check disabled"],
        checks,
    )


def _backend_probe_entry(
    backend: str,
    status: str,
    reasons: list[str],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "backend": backend,
        "status": status if status in BACKEND_PROBE_STATUSES else "missing",
        "reasons": reasons,
        "checks": checks,
    }


def _backend_runtime_partial_failure_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return build_runtime_partial_failure_report(
        BACKEND_PROBE_REPORT_SCHEMA,
        entries,
        label_field="backend",
        success_statuses=BACKEND_PROBE_RUNTIME_SUCCESS_STATUSES,
        warning_statuses=(),
        failure_statuses=BACKEND_PROBE_RUNTIME_FAILURE_STATUSES,
        skipped_statuses=BACKEND_PROBE_RUNTIME_SKIPPED_STATUSES,
    )


def _probe_single_backend(
    backend: str,
    *,
    remote_url: str | None = None,
    mineru_base_url: str | None = None,
    mineru_api_key: str | None = None,
    mineru_cli_path: str | None = None,
    mineru_verify_ssl: bool = True,
    network_check: bool = False,
    timeout: float = 2.0,
) -> dict[str, Any]:
    if backend == "builtin":
        return _backend_probe_entry(
            backend,
            "available",
            ["built-in Markdown, text, and HTML conversion is always available"],
            [{"name": "builtin_converter", "ok": True}],
        )
    if backend == "pandoc":
        resolved = shutil.which("pandoc")
        return _backend_probe_entry(
            backend,
            "available" if resolved else "missing",
            ["pandoc executable found"] if resolved else ["pandoc executable was not found on PATH"],
            [{"name": "pandoc_on_path", "ok": bool(resolved)}],
        )
    if backend == "mineru-cli":
        resolved = resolve_mineru_cli_path(mineru_cli_path)
        checks = [
            {"name": "cli_path_configured", "ok": bool(mineru_cli_path or os.environ.get("MINERU_CLI_PATH"))},
            {"name": "mineru_on_path", "ok": bool(shutil.which("mineru"))},
            {"name": "resolved_cli", "ok": bool(resolved)},
        ]
        if not resolved:
            return _backend_probe_entry(
                backend,
                "missing",
                ["mineru executable was not found from config, environment, or PATH"],
                checks,
            )
        return _backend_probe_entry(backend, "available", ["mineru executable resolved"], checks)
    if backend == "remote":
        return _probe_http_backend(
            backend=backend,
            url=remote_url,
            network_check=network_check,
            timeout=timeout,
        )
    if backend in {"mineru", "mineru-agent"}:
        base_url = mineru_base_url or DEFAULT_MINERU_BASE_URL
        return _probe_http_backend(
            backend=backend,
            url=base_url,
            network_check=network_check,
            timeout=timeout,
            requires_api_key=True,
            api_key=mineru_api_key,
        )
    if backend == "mineru-fastapi":
        return _probe_mineru_fastapi_backend(
            backend=backend,
            base_url=mineru_base_url,
            api_key=mineru_api_key,
            network_check=network_check,
            timeout=timeout,
            verify_ssl=mineru_verify_ssl,
        )
    if backend in {"mineru-sync", "mineru-local"}:
        if mineru_base_url and str(mineru_base_url).rstrip("/").endswith("/agent"):
            return _backend_probe_entry(
                backend,
                "wrong_protocol",
                ["mineru-sync expects a synchronous service base URL, not the MinerU Agent API URL"],
                [{"name": "sync_base_url_shape", "ok": False}],
            )
        parse_url = _mineru_sync_parse_url(mineru_base_url) if mineru_base_url else None
        return _probe_http_backend(
            backend=backend,
            url=parse_url,
            network_check=network_check,
            timeout=timeout,
        )
    return _backend_probe_entry(
        backend,
        "wrong_protocol",
        [f"unsupported backend: {backend}"],
        [{"name": "known_backend", "ok": False}],
    )


def probe_conversion_backends(
    *,
    backend: str = "auto",
    remote_url: str | None = None,
    mineru_base_url: str | None = None,
    mineru_api_key: str | None = None,
    mineru_cli_path: str | None = None,
    mineru_verify_ssl: bool = True,
    network_check: bool = False,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Probe configured document conversion backend readiness without converting files."""

    normalized_backend = str(backend or "auto").strip().lower()
    if normalized_backend not in {"auto", *CONVERSION_BACKENDS}:
        allowed = ", ".join(["auto", *CONVERSION_BACKENDS])
        raise DocConvertError(f"backend must be one of: {allowed}")
    if timeout <= 0:
        raise DocConvertError("probe timeout must be greater than zero")
    backends = list(CONVERSION_BACKENDS) if normalized_backend == "auto" else [normalized_backend]
    entries = [
        _probe_single_backend(
            item,
            remote_url=remote_url,
            mineru_base_url=mineru_base_url,
            mineru_api_key=mineru_api_key,
            mineru_cli_path=mineru_cli_path,
            mineru_verify_ssl=mineru_verify_ssl,
            network_check=network_check,
            timeout=timeout,
        )
        for item in backends
    ]
    status_counts = {status: 0 for status in BACKEND_PROBE_STATUSES}
    for entry in entries:
        status_counts[str(entry.get("status"))] = status_counts.get(str(entry.get("status")), 0) + 1
    runtime_partial_failure = _backend_runtime_partial_failure_report(entries)
    runtime_partial_summary = runtime_partial_failure["summary"]
    return {
        "ok": True,
        "schema": BACKEND_PROBE_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_backend": normalized_backend,
        "network_check": bool(network_check),
        "timeout_seconds": timeout,
        "allowed_statuses": list(BACKEND_PROBE_STATUSES),
        "summary": {
            "backend_count": len(entries),
            "available": status_counts.get("available", 0),
            "missing": status_counts.get("missing", 0),
            "wrong_protocol": status_counts.get("wrong_protocol", 0),
            "timeout": status_counts.get("timeout", 0),
            "not_configured": status_counts.get("not_configured", 0),
            "runtime_partial_failure_status": runtime_partial_summary["status"],
            "runtime_failure_count": runtime_partial_summary["failure_count"],
            "runtime_timeout_count": runtime_partial_summary["timeout_count"],
            "runtime_skipped_count": runtime_partial_summary["skipped_count"],
        },
        "runtime_partial_failure": runtime_partial_failure,
        "backends": entries,
    }


def render_backend_probe_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown backend probe report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    runtime_partial = (
        report.get("runtime_partial_failure")
        if isinstance(report.get("runtime_partial_failure"), Mapping)
        else {}
    )
    runtime_partial_summary = (
        runtime_partial.get("summary")
        if isinstance(runtime_partial.get("summary"), Mapping)
        else {}
    )
    lines = [
        "# RAGFlow Doc Backend Probe",
        "",
        f"- schema: `{report.get('schema', BACKEND_PROBE_REPORT_SCHEMA)}`",
        f"- selected_backend: `{report.get('selected_backend', '')}`",
        f"- network_check: `{str(report.get('network_check', False)).lower()}`",
        f"- available: `{summary.get('available', 0)}`",
        f"- missing: `{summary.get('missing', 0)}`",
        f"- wrong_protocol: `{summary.get('wrong_protocol', 0)}`",
        f"- timeout: `{summary.get('timeout', 0)}`",
        f"- not_configured: `{summary.get('not_configured', 0)}`",
    ]
    if runtime_partial:
        lines.extend(
            [
                f"- runtime_partial_failure_status: `{runtime_partial_summary.get('status', 'unknown')}`",
                f"- runtime_partial_failure_partial: `{str(runtime_partial_summary.get('partial', False)).lower()}`",
                f"- runtime_failures: `{runtime_partial_summary.get('failure_count', 0)}`",
                f"- runtime_timeouts: `{runtime_partial_summary.get('timeout_count', 0)}`",
                f"- runtime_skipped: `{runtime_partial_summary.get('skipped_count', 0)}`",
            ]
        )
    lines.extend(
        [
            "",
            "| backend | status | reasons |",
            "| --- | --- | --- |",
        ]
    )
    for entry in report.get("backends", []):
        if not isinstance(entry, Mapping):
            continue
        reasons = "; ".join(str(item) for item in entry.get("reasons", []) if str(item)).replace("|", "\\|")
        lines.append(f"| `{entry.get('backend', '')}` | `{entry.get('status', '')}` | {reasons} |")
    return "\n".join(lines) + "\n"


def _short_process_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if len(detail) > 1000:
        return detail[:1000] + "..."
    return detail


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_external_asset_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "data:", "#"))


def _split_markdown_asset_target(raw: str) -> tuple[str, str, bool]:
    value = raw.strip()
    if not value:
        return "", "", False
    if value.startswith("<"):
        end = value.find(">")
        if end != -1:
            return value[1:end], value[end + 1 :], True
    match = re.match(r"(\S+)(.*)", value, flags=re.DOTALL)
    if not match:
        return value, "", False
    return match.group(1), match.group(2), False


def _safe_relative_asset_path(reference_path: str) -> PurePosixPath | None:
    normalized = reference_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return None
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure


def _local_asset_source_path(
    reference_path: str,
    *,
    markdown_path: Path,
    source_root: Path,
) -> Path | None:
    if _is_external_asset_reference(reference_path):
        return None
    decoded = unquote(reference_path.strip())
    if not decoded:
        return None
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = markdown_path.parent / candidate
    candidate = candidate.resolve()
    source_root = source_root.resolve()
    if not _is_relative_to(candidate, source_root):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _copy_local_markdown_asset(
    reference_path: str,
    *,
    markdown_path: Path,
    source_root: Path,
    asset_output_dir: Path,
) -> str | None:
    source_path = _local_asset_source_path(
        reference_path,
        markdown_path=markdown_path,
        source_root=source_root,
    )
    if not source_path:
        return None

    relative_target = None
    if not Path(reference_path).is_absolute():
        relative_target = _safe_relative_asset_path(reference_path)
    if relative_target is None:
        relative_target = PurePosixPath("images") / source_path.name

    destination = asset_output_dir / Path(*relative_target.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != destination.resolve():
        shutil.copy2(source_path, destination)
    return relative_target.as_posix()


def copy_local_markdown_assets(
    markdown: str,
    *,
    markdown_path: Path,
    source_root: Path,
    asset_output_dir: str | Path | None,
) -> str:
    """Copy local assets referenced by Markdown into a final handoff directory."""

    if asset_output_dir is None:
        return markdown
    output_dir = Path(asset_output_dir)

    def replace_markdown(match: re.Match[str]) -> str:
        prefix, raw_target, suffix = match.groups()
        target_path, target_suffix, angle_wrapped = _split_markdown_asset_target(raw_target)
        copied = _copy_local_markdown_asset(
            target_path,
            markdown_path=markdown_path,
            source_root=source_root,
            asset_output_dir=output_dir,
        )
        if not copied:
            return match.group(0)
        replacement = f"<{copied}>{target_suffix}" if angle_wrapped else f"{copied}{target_suffix}"
        return f"{prefix}{replacement}{suffix}"

    def replace_html(match: re.Match[str]) -> str:
        prefix, raw_target, suffix = match.groups()
        copied = _copy_local_markdown_asset(
            raw_target,
            markdown_path=markdown_path,
            source_root=source_root,
            asset_output_dir=output_dir,
        )
        if not copied:
            return match.group(0)
        return f"{prefix}{copied}{suffix}"

    markdown = MARKDOWN_IMAGE_RE.sub(replace_markdown, markdown)
    return HTML_IMAGE_SRC_RE.sub(replace_html, markdown)


def _short_executable_name(command: list[str]) -> str:
    executable = command[0] if command else ""
    return Path(executable).name or executable


def _coerce_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _read_linux_process_stat(pid: int) -> tuple[int, str, str] | None:
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    close = stat.rfind(")")
    if close < 0:
        return None
    name_start = stat.find("(")
    name = stat[name_start + 1 : close] if name_start >= 0 else str(pid)
    fields = stat[close + 2 :].split()
    if len(fields) < 3:
        return None
    try:
        process_group_id = int(fields[2])
    except ValueError:
        return None
    return process_group_id, name, fields[0]


def _collect_process_group_members(process_group_id: int, *, direct_pid: int) -> list[dict[str, Any]]:
    proc_root = Path("/proc")
    if os.name != "posix" or not proc_root.is_dir():
        return []
    members: list[dict[str, Any]] = []
    current_pid = os.getpid()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == current_pid:
            continue
        stat = _read_linux_process_stat(pid)
        if not stat:
            continue
        member_group_id, name, state = stat
        if member_group_id != process_group_id:
            continue
        members.append(
            {
                "pid": pid,
                "name": name,
                "state": state,
                "direct_child": pid == direct_pid,
            }
        )
    return sorted(members, key=lambda item: int(item["pid"]))


def _cleanup_timed_out_process(
    process: subprocess.Popen[str],
    *,
    process_group_id: int | None,
) -> dict[str, Any]:
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    cleanup: dict[str, Any] = {
        "attempted": True,
        "method": "process_group" if os.name == "posix" and process_group_id is not None else "process",
        "signals_sent": [],
        "process_exited": False,
        "leftover_processes": [],
        "leftover_process_count": 0,
    }
    use_process_group = (
        os.name == "posix"
        and process_group_id is not None
        and process_group_id != os.getpgrp()
    )

    def send_signal(sig: signal.Signals, name: str) -> None:
        try:
            if use_process_group:
                os.killpg(process_group_id, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
            cleanup["signals_sent"].append(name)
        except ProcessLookupError:
            return
        except OSError as exc:
            cleanup.setdefault("errors", []).append(f"{name}: {exc.__class__.__name__}")

    send_signal(signal.SIGTERM, "SIGTERM")
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass

    leftovers = (
        _collect_process_group_members(process_group_id, direct_pid=process.pid)
        if use_process_group
        else []
    )
    if process.poll() is None or leftovers:
        send_signal(kill_signal, "SIGKILL" if kill_signal != signal.SIGTERM else "KILL")
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass

    cleanup["process_exited"] = process.poll() is not None
    final_leftovers = (
        _collect_process_group_members(process_group_id, direct_pid=process.pid)
        if use_process_group
        else []
    )
    cleanup["leftover_processes"] = final_leftovers
    cleanup["leftover_process_count"] = len(final_leftovers)
    return cleanup


def _close_process_pipes(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _run_local_process_with_cleanup(
    command: list[str],
    *,
    timeout: float,
    backend: str,
    source_path: str,
) -> tuple[subprocess.CompletedProcess[str] | None, dict[str, Any]]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    event: dict[str, Any] = {
        "backend": backend,
        "source_path": source_path,
        "executable": _short_executable_name(command),
        "timeout_seconds": timeout,
        "started_at": started_at,
    }
    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        event.update(
            {
                "status": "execution_error",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "returncode": None,
                "error_type": exc.__class__.__name__,
                "cleanup": {
                    "attempted": False,
                    "method": "none",
                    "signals_sent": [],
                    "process_exited": False,
                    "leftover_processes": [],
                    "leftover_process_count": 0,
                },
            }
        )
        return None, event

    event["pid"] = process.pid
    process_group_id: int | None = None
    if os.name == "posix":
        try:
            process_group_id = os.getpgid(process.pid)
        except OSError:
            process_group_id = None

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        cleanup = _cleanup_timed_out_process(process, process_group_id=process_group_id)
        _close_process_pipes(process)
        event.update(
            {
                "status": "timeout",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "returncode": process.returncode,
                "cleanup": cleanup,
            }
        )
        return (
            subprocess.CompletedProcess(
                command,
                process.returncode,
                _coerce_timeout_output(exc.stdout),
                _coerce_timeout_output(exc.stderr),
            ),
            event,
        )

    status = "success" if process.returncode == 0 else "failed"
    event.update(
        {
            "status": status,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "returncode": process.returncode,
            "cleanup": {
                "attempted": False,
                "method": "none",
                "signals_sent": [],
                "process_exited": True,
                "leftover_processes": [],
                "leftover_process_count": 0,
            },
        }
    )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), event


def make_doc_runtime_report_payload(
    *,
    output_root: str | Path,
    process_attempts: list[Mapping[str, Any]],
    remote_attempts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a portable report for conversion runtime attempts."""

    normalized = [dict(attempt) for attempt in process_attempts]
    normalized_remote = [dict(attempt) for attempt in (remote_attempts or [])]
    cleanups = [
        item.get("cleanup", {}) if isinstance(item.get("cleanup"), Mapping) else {}
        for item in normalized
    ]
    remote_error_categories: dict[str, int] = {}
    for item in normalized_remote:
        category = item.get("error_category")
        if isinstance(category, str) and category:
            remote_error_categories[category] = remote_error_categories.get(category, 0) + 1
    summary = {
        "process_attempts": len(normalized),
        "success": sum(1 for item in normalized if item.get("status") == "success"),
        "failed": sum(1 for item in normalized if item.get("status") == "failed"),
        "timeout": sum(1 for item in normalized if item.get("status") == "timeout"),
        "execution_error": sum(1 for item in normalized if item.get("status") == "execution_error"),
        "cleanup_attempts": sum(1 for cleanup in cleanups if cleanup.get("attempted")),
        "leftover_processes": sum(
            int(cleanup.get("leftover_process_count", 0) or 0)
            for cleanup in cleanups
        ),
        "remote_attempts": len(normalized_remote),
        "remote_success": sum(1 for item in normalized_remote if item.get("status") == "success"),
        "remote_failed": sum(1 for item in normalized_remote if item.get("status") == "failed"),
        "remote_timeout": sum(1 for item in normalized_remote if item.get("status") == "timeout"),
        "remote_retry_count": sum(int(item.get("retry_count", 0) or 0) for item in normalized_remote),
        "http_attempts": sum(int(item.get("http_attempts", 0) or 0) for item in normalized_remote),
        "remote_insecure_tls": sum(1 for item in normalized_remote if item.get("verify_ssl") is False),
        "remote_error_categories": remote_error_categories,
    }
    summary["incomplete_cleanup"] = sum(
        1
        for cleanup in cleanups
        if cleanup.get("attempted")
        and (
            not cleanup.get("process_exited")
            or int(cleanup.get("leftover_process_count", 0) or 0) > 0
        )
    )
    return {
        "schema": DOC_RUNTIME_REPORT_SCHEMA,
        "version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": ".",
        "output_root": ".",
        "summary": summary,
        "process_attempts": normalized,
        "remote_attempts": normalized_remote,
    }


def render_doc_runtime_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown runtime report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Doc Runtime Report",
        "",
        f"- schema: `{report.get('schema', DOC_RUNTIME_REPORT_SCHEMA)}`",
        f"- process attempts: `{summary.get('process_attempts', 0)}`",
        f"- success: `{summary.get('success', 0)}`",
        f"- failed: `{summary.get('failed', 0)}`",
        f"- timeout: `{summary.get('timeout', 0)}`",
        f"- cleanup attempts: `{summary.get('cleanup_attempts', 0)}`",
        f"- leftover processes: `{summary.get('leftover_processes', 0)}`",
        f"- incomplete cleanup: `{summary.get('incomplete_cleanup', 0)}`",
        f"- remote attempts: `{summary.get('remote_attempts', 0)}`",
        f"- remote success: `{summary.get('remote_success', 0)}`",
        f"- remote failed: `{summary.get('remote_failed', 0)}`",
        f"- remote timeout: `{summary.get('remote_timeout', 0)}`",
        f"- remote retries: `{summary.get('remote_retry_count', 0)}`",
        f"- http attempts: `{summary.get('http_attempts', 0)}`",
        "",
        "| Source | Backend | Status | Cleanup | Leftovers |",
        "| --- | --- | --- | --- | --- |",
    ]
    attempts = report.get("process_attempts", [])
    if isinstance(attempts, list):
        for item in attempts:
            if not isinstance(item, Mapping):
                continue
            cleanup = item.get("cleanup", {}) if isinstance(item.get("cleanup"), Mapping) else {}
            cleanup_state = "attempted" if cleanup.get("attempted") else "not needed"
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("source_path", "")),
                        str(item.get("backend", "")),
                        str(item.get("status", "")),
                        cleanup_state,
                        str(cleanup.get("leftover_process_count", 0)),
                    ]
                )
                + " |"
            )
    remote_attempts = report.get("remote_attempts", [])
    if isinstance(remote_attempts, list) and remote_attempts:
        lines.extend(
            [
                "",
                "## Remote Attempts",
                "",
                "| Source | Backend | Status | Task | Polls | Final | HTTP | Retries | Error Category | Stage | Endpoint |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in remote_attempts:
            if not isinstance(item, Mapping):
                continue
            row = [
                str(item.get("source_path", "")).replace("|", "\\|"),
                str(item.get("backend", "")).replace("|", "\\|"),
                str(item.get("status", "")).replace("|", "\\|"),
                str(item.get("task_id", "") or "").replace("|", "\\|"),
                str(item.get("poll_count", 0)).replace("|", "\\|"),
                str(item.get("final_status", "") or "").replace("|", "\\|"),
                str(item.get("http_attempts", 0)).replace("|", "\\|"),
                str(item.get("retry_count", 0)).replace("|", "\\|"),
                str(item.get("error_category", "") or "").replace("|", "\\|"),
                str(item.get("failed_stage", "") or "").replace("|", "\\|"),
                str(item.get("endpoint", "") or "").replace("|", "\\|"),
            ]
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def mineru_cli_convert(
    source: SourceDocument,
    *,
    cli_path: str | None = None,
    cli_backend: str | None = None,
    timeout: float = 300.0,
    asset_output_dir: str | Path | None = None,
    process_attempts: list[dict[str, Any]] | None = None,
) -> str:
    """Convert one file through an installed local MinerU CLI."""

    if timeout <= 0:
        raise DocConvertError("MinerU CLI timeout must be greater than zero")
    resolved_cli = resolve_mineru_cli_path(cli_path)
    if not resolved_cli:
        hint = "MINERU_CLI_PATH, mineru.cli_path, or a mineru binary on PATH"
        raise DocConvertError(f"mineru-cli backend requires {hint}")

    backend = (cli_backend or "pipeline").strip() or "pipeline"
    with tempfile.TemporaryDirectory(prefix="ragflow-skill-mineru-") as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            resolved_cli,
            "-b",
            backend,
            "-p",
            str(source.path),
            "-o",
            str(output_dir),
        ]
        result, process_attempt = _run_local_process_with_cleanup(
            command,
            timeout=timeout,
            backend="mineru-cli",
            source_path=source.source_path,
        )
        if process_attempts is not None:
            process_attempts.append(process_attempt)

        if process_attempt["status"] == "timeout":
            raise DocConvertError(f"MinerU CLI timed out after {timeout:g}s for {source.source_path}")
        if process_attempt["status"] == "execution_error":
            error_type = process_attempt.get("error_type", "OSError")
            raise DocConvertError(f"MinerU CLI could not be executed: {error_type}")
        if result is None:
            raise DocConvertError(f"MinerU CLI did not return a process result for {source.source_path}")

        if result.returncode != 0:
            detail = _short_process_detail(result)
            raise DocConvertError(f"MinerU CLI failed for {source.source_path}: {detail or result.returncode}")

        markdown_files = sorted(
            path for path in output_dir.rglob("*.md") if path.is_file()
        )
        if not markdown_files:
            detail = _short_process_detail(result)
            suffix = f": {detail}" if detail else ""
            raise DocConvertError(f"MinerU CLI produced no Markdown output for {source.source_path}{suffix}")
        markdown_file = markdown_files[0]
        markdown = markdown_file.read_text(encoding="utf-8")
        return copy_local_markdown_assets(
            markdown,
            markdown_path=markdown_file,
            source_root=output_dir,
            asset_output_dir=asset_output_dir,
        )


def pandoc_convert(source: SourceDocument) -> str:
    """Convert with an installed pandoc binary."""

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise DocConvertError("pandoc is not available on PATH")
    result = subprocess.run(
        [pandoc, str(source.path), "-t", "gfm"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DocConvertError(f"pandoc conversion failed for {source.source_path}: {detail}")
    return result.stdout


def image_fallback_markdown(
    source: SourceDocument,
    *,
    asset_output_dir: str | Path | None,
) -> str:
    """Preserve an unconverted source image as Markdown that requires review."""

    if asset_output_dir is None:
        raise DocConvertError("image fallback requires an asset output directory")
    suffix = source.path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise DocConvertError(f"image fallback only supports image files: {source.source_path}")
    digest = sha256_file(source.path)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source.source_path).stem).strip(".-") or "image"
    image_name = f"{stem}-{digest[:12]}{suffix}"
    output_dir = Path(asset_output_dir) / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / image_name
    if source.path.resolve() != destination.resolve():
        shutil.copy2(source.path, destination)
    title = Path(source.source_path).stem or "Image"
    alt = title.replace("[", "").replace("]", "").strip() or "source image"
    return (
        f"# {title}\n\n"
        "> Source image preserved for manual review because OCR/conversion was unavailable.\n\n"
        f"![{alt}](images/{image_name})\n"
    )


def _image_fallback_result(
    source: SourceDocument,
    *,
    warnings: list[str],
    asset_output_dir: str | Path | None,
) -> tuple[str, list[str]]:
    warnings.append(
        "image_fallback_review_required: source image preserved because OCR/conversion was unavailable"
    )
    return image_fallback_markdown(source, asset_output_dir=asset_output_dir), warnings


def convert_source_to_markdown(
    source: SourceDocument,
    *,
    mode: str = "auto",
    backend: str = "auto",
    remote_url: str | None = None,
    remote_api_key: str | None = None,
    remote_timeout: float = 120.0,
    mineru_base_url: str | None = None,
    mineru_api_key: str | None = None,
    mineru_timeout: float = 300.0,
    mineru_poll_interval: float = 3.0,
    mineru_verify_ssl: bool = True,
    mineru_cli_path: str | None = None,
    mineru_cli_backend: str | None = None,
    asset_output_dir: str | Path | None = None,
    asset_document_stem: str | None = None,
    mineru_language: str = "ch",
    mineru_page_range: str | None = None,
    mineru_enable_table: bool = True,
    mineru_is_ocr: bool = False,
    mineru_enable_formula: bool = True,
    mineru_asset_mode: str = "markdown_only",
    process_attempts: list[dict[str, Any]] | None = None,
    remote_attempts: list[dict[str, Any]] | None = None,
    allow_image_fallback: bool = False,
) -> tuple[str, list[str]]:
    """Convert one source document to Markdown and return warnings."""

    suffix = source.path.suffix.lower()
    warnings: list[str] = []
    if suffix in MARKDOWN_EXTENSIONS:
        return source.path.read_text(encoding="utf-8"), warnings
    if mode == "passthrough":
        raise DocConvertError(f"passthrough mode only supports Markdown: {source.source_path}")

    if backend in {"auto", "builtin"} and suffix in TEXT_EXTENSIONS:
        title = Path(source.source_path).stem
        return text_to_markdown(source.path.read_text(encoding="utf-8"), title=title), warnings
    if backend in {"auto", "builtin"} and suffix in HTML_EXTENSIONS:
        return html_to_markdown(source.path.read_text(encoding="utf-8")), warnings

    should_try_mineru_cli = backend == "mineru-cli" or (
        backend == "auto"
        and suffix in MINERU_AUTO_EXTENSIONS
        and resolve_mineru_cli_path(mineru_cli_path)
    )
    if should_try_mineru_cli:
        try:
            return mineru_cli_convert(
                source,
                cli_path=mineru_cli_path,
                cli_backend=mineru_cli_backend,
                timeout=mineru_timeout,
                asset_output_dir=asset_output_dir,
                process_attempts=process_attempts,
            ), warnings
        except DocConvertError as exc:
            if backend == "mineru-cli":
                if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                    return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
                raise
            warnings.append(str(exc))

    should_try_pandoc = backend == "pandoc" or (backend == "auto" and suffix in PANDOC_AUTO_EXTENSIONS)
    if should_try_pandoc:
        try:
            return pandoc_convert(source), warnings
        except DocConvertError as exc:
            if backend == "pandoc":
                raise
            warnings.append(str(exc))

    if backend in {"auto", "remote"} and remote_url:
        try:
            return remote_convert(
                source,
                remote_url=remote_url,
                api_key=remote_api_key,
                timeout=remote_timeout,
            ), warnings
        except DocConvertError:
            if backend == "remote" and allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise
    if backend == "remote" and not remote_url:
        if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
            return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
        raise DocConvertError("remote backend requires --remote-url")
    if backend == "auto" and suffix in MINERU_AUTO_EXTENSIONS and _should_try_mineru_service_auto(
        mineru_base_url,
        mineru_api_key,
    ):
        try:
            if mineru_base_url.rstrip("/").endswith("/agent"):
                return mineru_agent_convert(
                    source,
                    base_url=mineru_base_url,
                    api_key=mineru_api_key,
                    timeout=mineru_timeout,
                    poll_interval=mineru_poll_interval,
                    language=mineru_language,
                    page_range=mineru_page_range,
                    enable_table=mineru_enable_table,
                    is_ocr=mineru_is_ocr,
                    enable_formula=mineru_enable_formula,
                ), warnings
            return mineru_sync_convert(
                source,
                base_url=mineru_base_url,
                api_key=mineru_api_key,
                timeout=mineru_timeout,
                language=mineru_language,
                page_range=mineru_page_range,
                enable_table=mineru_enable_table,
                is_ocr=mineru_is_ocr,
                enable_formula=mineru_enable_formula,
            ), warnings
        except DocConvertError:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise
    if backend in {"mineru", "mineru-agent"}:
        try:
            return mineru_agent_convert(
                source,
                base_url=mineru_base_url or DEFAULT_MINERU_BASE_URL,
                api_key=mineru_api_key,
                timeout=mineru_timeout,
                poll_interval=mineru_poll_interval,
                language=mineru_language,
                page_range=mineru_page_range,
                enable_table=mineru_enable_table,
                is_ocr=mineru_is_ocr,
                enable_formula=mineru_enable_formula,
            ), warnings
        except DocConvertError:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise
    if backend == "mineru-fastapi":
        if not mineru_base_url:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise DocConvertError("mineru-fastapi backend requires --mineru-base-url or MINERU_BASE_URL")
        try:
            return mineru_fastapi_convert(
                source,
                base_url=mineru_base_url,
                api_key=mineru_api_key,
                timeout=mineru_timeout,
                poll_interval=mineru_poll_interval,
                verify_ssl=mineru_verify_ssl,
                language=mineru_language,
                page_range=mineru_page_range,
                enable_table=mineru_enable_table,
                is_ocr=mineru_is_ocr,
                enable_formula=mineru_enable_formula,
                asset_mode=mineru_asset_mode,
                asset_output_dir=asset_output_dir,
                asset_document_stem=asset_document_stem,
                remote_attempts=remote_attempts,
            ), warnings
        except DocConvertError:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise
    if backend in {"mineru-sync", "mineru-local"}:
        if not mineru_base_url:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise DocConvertError("mineru-sync backend requires --mineru-base-url or MINERU_BASE_URL")
        try:
            return mineru_sync_convert(
                source,
                base_url=mineru_base_url,
                api_key=mineru_api_key,
                timeout=mineru_timeout,
                language=mineru_language,
                page_range=mineru_page_range,
                enable_table=mineru_enable_table,
                is_ocr=mineru_is_ocr,
                enable_formula=mineru_enable_formula,
            ), warnings
        except DocConvertError:
            if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
                return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)
            raise

    if allow_image_fallback and suffix in IMAGE_EXTENSIONS:
        return _image_fallback_result(source, warnings=warnings, asset_output_dir=asset_output_dir)

    supported = ", ".join(sorted(BUILTIN_EXTENSIONS))
    attempted = f"; attempted fallback: {'; '.join(warnings)}" if warnings else ""
    raise DocConvertError(
        f"no converter available for {source.source_path} ({suffix or 'no extension'}); "
        f"builtin supports {supported}, or configure pandoc/remote/mineru-cli/mineru/mineru-fastapi/mineru-sync backend{attempted}"
    )


def warmup_conversion_backend(
    *,
    fixture_path: str | Path,
    backend: str = "auto",
    output_markdown: str | Path | None = None,
    remote_url: str | None = None,
    remote_api_key: str | None = None,
    remote_timeout: float = 120.0,
    mineru_base_url: str | None = None,
    mineru_api_key: str | None = None,
    mineru_timeout: float = 300.0,
    mineru_poll_interval: float = 3.0,
    mineru_verify_ssl: bool = True,
    mineru_cli_path: str | None = None,
    mineru_cli_backend: str | None = None,
    mineru_language: str = "ch",
    mineru_page_range: str | None = None,
    mineru_enable_table: bool = True,
    mineru_is_ocr: bool = False,
    mineru_enable_formula: bool = True,
) -> dict[str, Any]:
    """Run an explicit fixture through a configured converter and report the result."""

    normalized_backend = str(backend or "auto").strip().lower()
    if normalized_backend not in {"auto", *CONVERSION_BACKENDS}:
        allowed = ", ".join(["auto", *CONVERSION_BACKENDS])
        raise DocConvertError(f"backend must be one of: {allowed}")

    fixture = Path(fixture_path).expanduser()
    output_path = Path(output_markdown).expanduser() if output_markdown else None
    fixture_entry: dict[str, Any] = {
        "name": fixture.name,
        "suffix": fixture.suffix.lower(),
        "exists": fixture.is_file(),
    }
    process_attempts: list[dict[str, Any]] = []
    remote_attempts: list[dict[str, Any]] = []
    started = time.monotonic()
    status = "failed"
    error_message: str | None = None
    markdown_chars = 0
    markdown_sha256: str | None = None
    title: str | None = None
    warnings: list[str] = []
    output_written = False

    if fixture.is_file():
        try:
            fixture_entry["bytes"] = fixture.stat().st_size
            fixture_entry["sha256"] = sha256_file(fixture)
            with tempfile.TemporaryDirectory(prefix="ragflow-skill-warmup-") as tmp:
                asset_output_dir = output_path.parent if output_path else Path(tmp) / "assets"
                source = SourceDocument(path=fixture.resolve(), source_path=fixture.name)
                markdown, warnings = convert_source_to_markdown(
                    source,
                    mode="convert",
                    backend=normalized_backend,
                    remote_url=remote_url,
                    remote_api_key=remote_api_key,
                    remote_timeout=remote_timeout,
                    mineru_base_url=mineru_base_url,
                    mineru_api_key=mineru_api_key,
                    mineru_timeout=mineru_timeout,
                    mineru_poll_interval=mineru_poll_interval,
                    mineru_verify_ssl=mineru_verify_ssl,
                    mineru_cli_path=mineru_cli_path,
                    mineru_cli_backend=mineru_cli_backend,
                    asset_output_dir=asset_output_dir,
                    mineru_language=mineru_language,
                    mineru_page_range=mineru_page_range,
                    mineru_enable_table=mineru_enable_table,
                    mineru_is_ocr=mineru_is_ocr,
                    mineru_enable_formula=mineru_enable_formula,
                    process_attempts=process_attempts,
                    remote_attempts=remote_attempts,
                )
                markdown_chars = len(markdown)
                markdown_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                title = extract_markdown_title(markdown)
                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(markdown, encoding="utf-8")
                    output_written = True
                status = "success"
        except (DocConvertError, OSError, UnicodeDecodeError) as exc:
            error_message = str(exc)
    else:
        error_message = f"fixture file not found: {fixture.name or fixture}"

    runtime_report = (
        make_doc_runtime_report_payload(
            output_root=".",
            process_attempts=process_attempts,
            remote_attempts=remote_attempts,
        )
        if process_attempts or remote_attempts
        else None
    )
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    summary = {
        "status": status,
        "duration_ms": duration_ms,
        "markdown_chars": markdown_chars,
        "warning_count": len(warnings),
        "process_attempts": len(process_attempts),
        "remote_attempts": len(remote_attempts),
        "remote_retry_count": runtime_report["summary"]["remote_retry_count"] if runtime_report else 0,
        "http_attempts": runtime_report["summary"]["http_attempts"] if runtime_report else 0,
        "cleanup_attempts": runtime_report["summary"]["cleanup_attempts"] if runtime_report else 0,
        "leftover_processes": runtime_report["summary"]["leftover_processes"] if runtime_report else 0,
    }
    return {
        "ok": status == "success",
        "schema": BACKEND_WARMUP_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_backend": normalized_backend,
        "allowed_statuses": list(BACKEND_WARMUP_STATUSES),
        "status": status,
        "summary": summary,
        "fixture": fixture_entry,
        "output": {
            "markdown_written": output_written,
            "markdown_name": output_path.name if output_path else None,
            "markdown_chars": markdown_chars,
            "markdown_sha256": markdown_sha256,
            "title": title,
        },
        "warnings": warnings,
        "error": error_message,
        "runtime_report": runtime_report,
    }


def render_backend_warmup_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown backend warmup report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    fixture = report.get("fixture", {}) if isinstance(report.get("fixture"), Mapping) else {}
    output = report.get("output", {}) if isinstance(report.get("output"), Mapping) else {}
    lines = [
        "# RAGFlow Doc Backend Warmup",
        "",
        f"- schema: `{report.get('schema', BACKEND_WARMUP_REPORT_SCHEMA)}`",
        f"- selected_backend: `{report.get('selected_backend', '')}`",
        f"- status: `{report.get('status', '')}`",
        f"- fixture: `{fixture.get('name', '')}`",
        f"- fixture suffix: `{fixture.get('suffix', '')}`",
        f"- duration_ms: `{summary.get('duration_ms', 0)}`",
        f"- markdown_chars: `{summary.get('markdown_chars', 0)}`",
        f"- warnings: `{summary.get('warning_count', 0)}`",
        f"- process_attempts: `{summary.get('process_attempts', 0)}`",
        f"- remote_attempts: `{summary.get('remote_attempts', 0)}`",
        f"- remote_retries: `{summary.get('remote_retry_count', 0)}`",
        f"- http_attempts: `{summary.get('http_attempts', 0)}`",
        f"- cleanup_attempts: `{summary.get('cleanup_attempts', 0)}`",
        f"- leftover_processes: `{summary.get('leftover_processes', 0)}`",
        f"- markdown_written: `{str(output.get('markdown_written', False)).lower()}`",
    ]
    if report.get("error"):
        error_text = str(report.get("error")).replace("|", "\\|")
        lines.extend(["", f"Error: {error_text}"])
    warnings = report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {str(item)}" for item in warnings)
    return "\n".join(lines) + "\n"


def make_doc_manifest_payload(
    *,
    output_root: str | Path,
    documents: list[ConvertedDocument],
) -> dict[str, Any]:
    """Create a serializable document handoff manifest."""

    root = Path(output_root)
    return {
        "version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": ".",
        "documents": [doc.to_manifest_entry(output_root=root) for doc in documents],
    }
