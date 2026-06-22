"""RAGFlow API client primitives."""

from __future__ import annotations

from pathlib import Path
import mimetypes
import uuid
from typing import Any, Mapping
from urllib.parse import quote

from .config import RagflowConfig
from .http import JSONHTTPClient


class RAGFlowClient:
    """Small RAGFlow API client for public skill scripts."""

    def __init__(self, config: RagflowConfig):
        self.config = config
        self.base_url = config.normalized_base_url
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self.http = JSONHTTPClient(timeout=config.timeout, headers=headers)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def get(self, path: str) -> Any:
        return self.http.request_json("GET", self._url(path)).data

    def post(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        return self.http.request_json("POST", self._url(path), json_body=payload or {}).data

    def delete(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        return self.http.request_json("DELETE", self._url(path), json_body=payload or {}).data

    def put(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        return self.http.request_json("PUT", self._url(path), json_body=payload or {}).data

    def retrieve(
        self,
        *,
        question: str,
        dataset_ids: list[str],
        top_k: int = 5,
        similarity_threshold: float | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Any:
        """Call RAGFlow retrieval API."""

        payload: dict[str, Any] = {
            "question": question,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
        }
        if similarity_threshold is not None:
            payload["similarity_threshold"] = similarity_threshold
        if extra:
            payload.update(extra)
        return self.post("/retrieval", payload)

    def list_datasets(self, *, page: int = 1, page_size: int = 200, name: str | None = None) -> Any:
        """List datasets, optionally filtering by name when RAGFlow supports it."""

        path = f"/datasets?page={page}&page_size={page_size}"
        if name:
            path += f"&name={quote(name)}"
        return self.get(path)

    def create_dataset(self, name: str, *, profile: Mapping[str, Any] | None = None) -> Any:
        """Create a RAGFlow dataset with an optional normalized profile payload."""

        payload: dict[str, Any] = {"name": name}
        if profile:
            payload.update({k: v for k, v in profile.items() if v is not None})
        return self.post("/datasets", payload)

    def trigger_parse(self, dataset_id: str, document_ids: list[str]) -> Any:
        """Trigger parsing for uploaded documents."""

        return self.post(f"/datasets/{dataset_id}/documents/parse", {"document_ids": document_ids})

    def list_documents(self, dataset_id: str, *, page: int = 1, page_size: int = 200) -> Any:
        """List documents in a dataset."""

        return self.get(f"/datasets/{dataset_id}/documents?page={page}&page_size={page_size}")

    def upload_document(self, dataset_id: str, file_path: str | Path) -> Any:
        """Upload one file with multipart/form-data using only the standard library."""

        path = Path(file_path)
        boundary = f"----ragflow-skill-runtime-{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(path.name)[0] or "text/markdown"
        content = path.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                content,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self.http.request_bytes(
            "POST",
            self._url(f"/datasets/{dataset_id}/documents"),
            body=body,
            headers=headers,
        ).data
