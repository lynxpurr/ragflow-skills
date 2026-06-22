"""Authentication loading helpers for portable RAGFlow skills."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class AuthError(RuntimeError):
    """Raised when required authentication material is missing or invalid."""


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthError(f"auth file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuthError(f"auth file is not valid JSON: {path}") from exc


def _extract_api_key(data: Mapping[str, Any], service: str) -> str | None:
    nested = data.get(service)
    if isinstance(nested, Mapping):
        value = nested.get("api_key") or nested.get("token")
        if isinstance(value, str) and value.strip():
            return value.strip()

    flat_keys = [
        f"{service}_api_key",
        f"{service.upper()}_API_KEY",
        "api_key" if service == "ragflow" else "",
    ]
    for key in flat_keys:
        if not key:
            continue
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_api_key(
    service: str = "ragflow",
    *,
    env: Mapping[str, str] | None = None,
    auth_file: str | Path | None = None,
    required: bool = False,
) -> str | None:
    """Load an API key from environment or a JSON auth file.

    Lookup order:
    1. ``<SERVICE>_API_KEY`` environment variable.
    2. ``RAGFLOW_API_KEY`` for the default RAGFlow service.
    3. Explicit ``auth_file``.
    4. ``RAGFLOW_AUTH_FILE`` environment variable.
    """

    env_map = os.environ if env is None else env
    service_env = f"{service.upper()}_API_KEY"
    candidates = [service_env]
    if service == "ragflow":
        candidates.append("RAGFLOW_API_KEY")

    for key in candidates:
        value = env_map.get(key)
        if value and value.strip():
            return value.strip()

    file_value = auth_file or env_map.get("RAGFLOW_AUTH_FILE")
    if file_value:
        api_key = _extract_api_key(_read_json(Path(file_value).expanduser()), service)
        if api_key:
            return api_key

    if required:
        sources = ", ".join(candidates + ["RAGFLOW_AUTH_FILE"])
        raise AuthError(f"missing {service} API key; checked {sources}")
    return None
