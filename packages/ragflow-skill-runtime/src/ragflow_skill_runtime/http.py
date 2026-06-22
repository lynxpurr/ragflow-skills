"""Small standard-library HTTP client for portable skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import error, request


class HTTPError(RuntimeError):
    """Raised for HTTP or JSON transport failures."""


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    data: Any


class JSONHTTPClient:
    """Minimal JSON HTTP client based on ``urllib``."""

    def __init__(self, *, timeout: float = 60.0, headers: Mapping[str, str] | None = None):
        self.timeout = timeout
        self.headers = dict(headers or {})

    def request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse:
        body = None
        merged_headers = {**self.headers, **(headers or {})}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        req = request.Request(url, data=body, method=method.upper(), headers=merged_headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                data = json.loads(raw.decode("utf-8")) if raw else None
                return HTTPResponse(resp.status, dict(resp.headers.items()), data)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HTTPError(f"HTTP {exc.code} for {method.upper()} {url}: {detail}") from exc
        except error.URLError as exc:
            raise HTTPError(f"request failed for {method.upper()} {url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise HTTPError(f"response is not valid JSON for {method.upper()} {url}") from exc
