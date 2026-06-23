"""Document-to-Markdown conversion helpers for public skills."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request


class DocConvertError(RuntimeError):
    """Raised when document conversion cannot proceed."""


MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
TEXT_EXTENSIONS = {".txt", ".text"}
HTML_EXTENSIONS = {".html", ".htm"}
BUILTIN_EXTENSIONS = MARKDOWN_EXTENSIONS | TEXT_EXTENSIONS | HTML_EXTENSIONS
PANDOC_AUTO_EXTENSIONS = {
    ".docx",
    ".epub",
    ".odt",
    ".rtf",
    ".rst",
    ".org",
    ".tex",
}
DEFAULT_MINERU_BASE_URL = "https://mineru.net/api/v1/agent"
MINERU_DONE_STATE = "done"
MINERU_FAILED_STATE = "failed"


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

    def to_manifest_entry(self, *, output_root: Path) -> dict[str, Any]:
        return {
            "source_path": self.source.source_path,
            "markdown_path": self.markdown_path.relative_to(output_root).as_posix(),
            "sha256": self.sha256,
            "title": self.title,
            "warnings": list(self.warnings),
        }


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


def _download_text(url: str, *, timeout: float) -> str:
    req = request.Request(url, headers={"Accept": "text/markdown,text/plain,*/*"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
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
        rendered = "true" if value is True else "false" if value is False else str(value)
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


def _extract_markdown_from_mapping(data: Mapping[str, Any], *, timeout: float) -> str | None:
    for key in ("markdown", "content", "md", "text", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    for key in ("markdown_url", "md_url", "url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _download_text(value, timeout=timeout)

    for key in ("data", "result", "output"):
        value = data.get(key)
        if isinstance(value, Mapping):
            markdown = _extract_markdown_from_mapping(value, timeout=timeout)
            if markdown is not None:
                return markdown
    return None


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
    mineru_language: str = "ch",
    mineru_page_range: str | None = None,
    mineru_enable_table: bool = True,
    mineru_is_ocr: bool = False,
    mineru_enable_formula: bool = True,
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

    should_try_pandoc = backend == "pandoc" or (backend == "auto" and suffix in PANDOC_AUTO_EXTENSIONS)
    if should_try_pandoc:
        try:
            return pandoc_convert(source), warnings
        except DocConvertError as exc:
            if backend == "pandoc":
                raise
            warnings.append(str(exc))

    if backend in {"auto", "remote"} and remote_url:
        return remote_convert(
            source,
            remote_url=remote_url,
            api_key=remote_api_key,
            timeout=remote_timeout,
        ), warnings
    if backend == "remote" and not remote_url:
        raise DocConvertError("remote backend requires --remote-url")
    if backend in {"mineru", "mineru-agent"}:
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
    if backend in {"mineru-sync", "mineru-local"}:
        if not mineru_base_url:
            raise DocConvertError("mineru-sync backend requires --mineru-base-url or MINERU_BASE_URL")
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

    supported = ", ".join(sorted(BUILTIN_EXTENSIONS))
    attempted = f"; attempted fallback: {'; '.join(warnings)}" if warnings else ""
    raise DocConvertError(
        f"no converter available for {source.source_path} ({suffix or 'no extension'}); "
        f"builtin supports {supported}, or configure pandoc/remote/mineru/mineru-sync backend{attempted}"
    )


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
