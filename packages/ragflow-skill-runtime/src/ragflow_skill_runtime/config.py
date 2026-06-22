"""Configuration loading for public RAGFlow skills."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .auth import load_api_key
from .paths import expand_path, project_config_candidates


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or normalized."""


@dataclass(frozen=True)
class RagflowConfig:
    """Runtime configuration shared by public RAGFlow skills."""

    base_url: str | None = None
    api_key: str | None = None
    timeout: float = 60.0
    verify_ssl: bool = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    @property
    def normalized_base_url(self) -> str:
        if not self.base_url:
            raise ConfigError(
                "RAGFlow base URL is required; set RAGFLOW_BASE_URL or pass --base-url"
            )
        return normalize_base_url(self.base_url)


def normalize_base_url(base_url: str) -> str:
    """Normalize a RAGFlow API URL without assuming localhost."""

    value = base_url.strip().rstrip("/")
    if not value:
        raise ConfigError("RAGFlow base URL is empty")
    if value.endswith("/api/v1"):
        return value
    return f"{value}/api/v1"


def _parse_scalar(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip().strip("\"'")


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    """Read a small flat YAML mapping without adding a PyYAML dependency."""

    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ConfigError(f"unsupported config line in {path}: {line!r}")
        key, value = stripped.split(":", 1)
        data[key.strip()] = _parse_scalar(value.strip())
    return data


def read_config_file(path: str | Path) -> dict[str, Any]:
    """Read a JSON or simple flat YAML config file."""

    config_path = expand_path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc

    suffix = config_path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"config file is not valid JSON: {config_path}") from exc
    elif suffix in {".yaml", ".yml"}:
        data = _read_simple_yaml(config_path)
    else:
        raise ConfigError(f"unsupported config file extension: {config_path.suffix}")

    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a mapping: {config_path}")
    return data


def _pick(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _from_mapping(data: Mapping[str, Any]) -> RagflowConfig:
    ragflow = data.get("ragflow") if isinstance(data.get("ragflow"), Mapping) else {}
    llm = data.get("llm") if isinstance(data.get("llm"), Mapping) else {}
    merged = {**data, **ragflow}

    return RagflowConfig(
        base_url=_pick(merged, "base_url", "ragflow_base_url", "url"),
        api_key=_pick(merged, "api_key", "ragflow_api_key"),
        timeout=float(_pick(merged, "timeout", "request_timeout") or 60.0),
        verify_ssl=bool(_pick(merged, "verify_ssl") if _pick(merged, "verify_ssl") is not None else True),
        llm_base_url=_pick(llm, "base_url", "llm_base_url") or _pick(data, "llm_base_url"),
        llm_api_key=_pick(llm, "api_key", "llm_api_key") or _pick(data, "llm_api_key"),
    )


def _merge(base: RagflowConfig, override: RagflowConfig) -> RagflowConfig:
    return RagflowConfig(
        base_url=override.base_url or base.base_url,
        api_key=override.api_key or base.api_key,
        timeout=override.timeout if override.timeout != 60.0 else base.timeout,
        verify_ssl=override.verify_ssl,
        llm_base_url=override.llm_base_url or base.llm_base_url,
        llm_api_key=override.llm_api_key or base.llm_api_key,
    )


def load_config(
    *,
    config_file: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> RagflowConfig:
    """Load runtime config from file, environment, and explicit overrides."""

    env_map = os.environ if env is None else env
    config = RagflowConfig()

    selected_file = config_file or env_map.get("RAGFLOW_CONFIG")
    if not selected_file:
        for candidate in project_config_candidates(Path.cwd()):
            if candidate.exists():
                selected_file = candidate
                break
    if selected_file:
        config = _merge(config, _from_mapping(read_config_file(selected_file)))

    env_config = RagflowConfig(
        base_url=env_map.get("RAGFLOW_BASE_URL"),
        api_key=load_api_key(env=env_map, required=False),
        timeout=float(env_map.get("RAGFLOW_TIMEOUT", config.timeout)),
        verify_ssl=env_map.get("RAGFLOW_VERIFY_SSL", str(config.verify_ssl)).lower()
        not in {"0", "false", "no", "off"},
        llm_base_url=env_map.get("RAGFLOW_LLM_BASE_URL"),
        llm_api_key=env_map.get("RAGFLOW_LLM_API_KEY"),
    )
    config = _merge(config, env_config)

    if overrides:
        config = _merge(config, _from_mapping(overrides))

    return replace(config, base_url=normalize_base_url(config.base_url) if config.base_url else None)
