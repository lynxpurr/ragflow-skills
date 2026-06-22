"""RAGFlow API client primitives."""

from __future__ import annotations

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
