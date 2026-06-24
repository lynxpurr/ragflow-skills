"""Configuration loading for public RAGFlow skills."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .auth import load_api_key
from .paths import expand_path, project_config_candidates


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or normalized."""


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class RagflowConfig:
    """Runtime configuration shared by public RAGFlow skills."""

    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    verify_ssl: bool | None = True
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    @property
    def normalized_base_url(self) -> str:
        if not self.base_url:
            raise ConfigError(
                "RAGFlow base URL is required; set RAGFLOW_BASE_URL or pass --base-url"
            )
        return normalize_base_url(self.base_url)


@dataclass(frozen=True)
class DocToMdConfig:
    """Document conversion configuration shared by doc-to-md scripts."""

    backend: str | None = None
    remote_url: str | None = None
    remote_api_key: str | None = None
    remote_timeout: float | None = None


@dataclass(frozen=True)
class MineruConfig:
    """MinerU service configuration for public document conversion."""

    base_url: str | None = None
    api_key: str | None = None
    cli_path: str | None = None
    cli_backend: str | None = None
    timeout: float | None = None
    poll_interval: float | None = None
    language: str | None = None
    page_range: str | None = None
    enable_table: bool | None = None
    is_ocr: bool | None = None
    enable_formula: bool | None = None


@dataclass(frozen=True)
class SkillConfig:
    """Unified public skill configuration."""

    ragflow: RagflowConfig = RagflowConfig()
    doc_to_md: DocToMdConfig = DocToMdConfig()
    mineru: MineruConfig = MineruConfig()


def normalize_base_url(base_url: str) -> str:
    """Normalize a RAGFlow API URL without assuming localhost."""

    value = base_url.strip().rstrip("/")
    if not value:
        raise ConfigError("RAGFlow base URL is empty")
    if value.endswith("/api/v1"):
        return value
    return f"{value}/api/v1"


def _parse_scalar(value: str) -> Any:
    if value == "":
        return None
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


def _parse_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"boolean config value must be true or false: {value!r}")


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    """Read a small YAML mapping without adding a PyYAML dependency.

    This intentionally supports only top-level keys and one nested mapping level,
    which is enough for the public skill config template.
    """

    data: dict[str, Any] = {}
    current_section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            raise ConfigError(f"tabs are not supported in config file: {path}")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if ":" not in stripped:
            raise ConfigError(f"unsupported config line in {path}: {line!r}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if indent == 0:
            if value == "":
                current_section = key
                data[current_section] = {}
            else:
                current_section = None
                data[key] = _parse_scalar(value)
        elif indent == 2 and current_section:
            section = data.get(current_section)
            if not isinstance(section, dict):
                raise ConfigError(f"invalid nested config section in {path}: {current_section}")
            section[key] = _parse_scalar(value)
        else:
            raise ConfigError(f"unsupported config indentation in {path}: {line!r}")
    return data


def _substitute_env(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            return env.get(match.group(1), "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {key: _substitute_env(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item, env) for item in value]
    return value


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def read_config_file(path: str | Path, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
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
    env_map = os.environ if env is None else env
    return _substitute_env(data, env_map)


def read_config_files(paths: list[str | Path], *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Read and merge config files, later files overriding earlier files."""

    merged: dict[str, Any] = {}
    for path in paths:
        merged = _deep_merge(merged, read_config_file(path, env=env))
    return merged


def _pick(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _from_mapping(data: Mapping[str, Any]) -> RagflowConfig:
    ragflow = data.get("ragflow") if isinstance(data.get("ragflow"), Mapping) else {}
    llm = data.get("llm") if isinstance(data.get("llm"), Mapping) else {}
    merged = {**data, **ragflow}
    verify_ssl = _pick(merged, "verify_ssl")

    return RagflowConfig(
        base_url=_pick(merged, "base_url", "ragflow_base_url", "url"),
        api_key=_pick(merged, "api_key", "ragflow_api_key"),
        timeout=float(_pick(merged, "timeout", "request_timeout"))
        if _pick(merged, "timeout", "request_timeout") is not None
        else None,
        verify_ssl=_parse_bool(verify_ssl, default=None),
        llm_base_url=_pick(llm, "base_url", "llm_base_url") or _pick(data, "llm_base_url"),
        llm_api_key=_pick(llm, "api_key", "llm_api_key") or _pick(data, "llm_api_key"),
    )


def _doc_to_md_from_mapping(data: Mapping[str, Any]) -> DocToMdConfig:
    section = data.get("doc_to_md") if isinstance(data.get("doc_to_md"), Mapping) else {}
    merged = {**data, **section}
    timeout = _pick(merged, "remote_timeout", "timeout")
    return DocToMdConfig(
        backend=_pick(merged, "backend"),
        remote_url=_pick(merged, "remote_url"),
        remote_api_key=_pick(merged, "remote_api_key"),
        remote_timeout=float(timeout) if timeout is not None else None,
    )


def _mineru_from_mapping(data: Mapping[str, Any]) -> MineruConfig:
    section = data.get("mineru") if isinstance(data.get("mineru"), Mapping) else {}
    merged = {**data, **section}
    timeout = _pick(merged, "timeout")
    poll_interval = _pick(merged, "poll_interval")
    return MineruConfig(
        base_url=_pick(merged, "base_url", "mineru_base_url", "url"),
        api_key=_pick(merged, "api_key", "mineru_api_key"),
        cli_path=_pick(merged, "cli_path", "mineru_cli_path"),
        cli_backend=_pick(merged, "cli_backend", "mineru_cli_backend"),
        timeout=float(timeout) if timeout is not None else None,
        poll_interval=float(poll_interval) if poll_interval is not None else None,
        language=_pick(merged, "language"),
        page_range=_pick(merged, "page_range"),
        enable_table=_pick(merged, "enable_table"),
        is_ocr=_pick(merged, "is_ocr"),
        enable_formula=_pick(merged, "enable_formula"),
    )


def _merge(base: RagflowConfig, override: RagflowConfig) -> RagflowConfig:
    return RagflowConfig(
        base_url=override.base_url or base.base_url,
        api_key=override.api_key or base.api_key,
        timeout=override.timeout if override.timeout is not None else base.timeout,
        verify_ssl=override.verify_ssl if override.verify_ssl is not None else base.verify_ssl,
        llm_base_url=override.llm_base_url or base.llm_base_url,
        llm_api_key=override.llm_api_key or base.llm_api_key,
    )


def _merge_doc_to_md(base: DocToMdConfig, override: DocToMdConfig) -> DocToMdConfig:
    return DocToMdConfig(
        backend=override.backend or base.backend,
        remote_url=override.remote_url or base.remote_url,
        remote_api_key=override.remote_api_key or base.remote_api_key,
        remote_timeout=override.remote_timeout if override.remote_timeout is not None else base.remote_timeout,
    )


def _merge_mineru(base: MineruConfig, override: MineruConfig) -> MineruConfig:
    return MineruConfig(
        base_url=override.base_url or base.base_url,
        api_key=override.api_key or base.api_key,
        cli_path=override.cli_path or base.cli_path,
        cli_backend=override.cli_backend or base.cli_backend,
        timeout=override.timeout if override.timeout is not None else base.timeout,
        poll_interval=override.poll_interval if override.poll_interval is not None else base.poll_interval,
        language=override.language or base.language,
        page_range=override.page_range or base.page_range,
        enable_table=override.enable_table if override.enable_table is not None else base.enable_table,
        is_ocr=override.is_ocr if override.is_ocr is not None else base.is_ocr,
        enable_formula=override.enable_formula if override.enable_formula is not None else base.enable_formula,
    )


def _skill_from_mapping(data: Mapping[str, Any]) -> SkillConfig:
    return SkillConfig(
        ragflow=_from_mapping(data),
        doc_to_md=_doc_to_md_from_mapping(data),
        mineru=_mineru_from_mapping(data),
    )


def _merge_skill(base: SkillConfig, override: SkillConfig) -> SkillConfig:
    return SkillConfig(
        ragflow=_merge(base.ragflow, override.ragflow),
        doc_to_md=_merge_doc_to_md(base.doc_to_md, override.doc_to_md),
        mineru=_merge_mineru(base.mineru, override.mineru),
    )


def _config_paths(
    *,
    config_file: str | Path | None,
    env_map: Mapping[str, str],
    cwd: Path,
) -> list[str | Path]:
    selected = config_file or env_map.get("RAGFLOW_CONFIG")
    if selected:
        return [selected]
    return [candidate for candidate in project_config_candidates(cwd) if candidate.exists()]


def load_skill_config(
    *,
    config_file: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> SkillConfig:
    """Load unified config from files, environment, and explicit overrides."""

    env_map = os.environ if env is None else env
    config = SkillConfig()

    paths = _config_paths(config_file=config_file, env_map=env_map, cwd=cwd or Path.cwd())
    if paths:
        config = _merge_skill(config, _skill_from_mapping(read_config_files(paths, env=env_map)))

    env_config = SkillConfig(
        ragflow=RagflowConfig(
            base_url=env_map.get("RAGFLOW_BASE_URL"),
            api_key=load_api_key(env=env_map, required=False),
            timeout=float(env_map["RAGFLOW_TIMEOUT"]) if env_map.get("RAGFLOW_TIMEOUT") else None,
            verify_ssl=_parse_bool(env_map.get("RAGFLOW_VERIFY_SSL"), default=None),
            llm_base_url=env_map.get("RAGFLOW_LLM_BASE_URL"),
            llm_api_key=env_map.get("RAGFLOW_LLM_API_KEY"),
        ),
        doc_to_md=DocToMdConfig(
            backend=env_map.get("DOC_TO_MD_BACKEND"),
            remote_url=env_map.get("DOC_TO_MD_REMOTE_URL"),
            remote_api_key=env_map.get("DOC_TO_MD_REMOTE_API_KEY"),
            remote_timeout=float(env_map["DOC_TO_MD_TIMEOUT"])
            if env_map.get("DOC_TO_MD_TIMEOUT")
            else None,
        ),
        mineru=MineruConfig(
            base_url=env_map.get("MINERU_BASE_URL"),
            api_key=env_map.get("MINERU_API_KEY"),
            cli_path=env_map.get("MINERU_CLI_PATH"),
            cli_backend=env_map.get("MINERU_CLI_BACKEND"),
            timeout=float(env_map["MINERU_TIMEOUT"]) if env_map.get("MINERU_TIMEOUT") else None,
            poll_interval=float(env_map["MINERU_POLL_INTERVAL"])
            if env_map.get("MINERU_POLL_INTERVAL")
            else None,
            language=env_map.get("MINERU_LANGUAGE"),
            page_range=env_map.get("MINERU_PAGE_RANGE"),
            enable_table=_parse_scalar(env_map["MINERU_ENABLE_TABLE"])
            if env_map.get("MINERU_ENABLE_TABLE")
            else None,
            is_ocr=_parse_scalar(env_map["MINERU_IS_OCR"])
            if env_map.get("MINERU_IS_OCR")
            else None,
            enable_formula=_parse_scalar(env_map["MINERU_ENABLE_FORMULA"])
            if env_map.get("MINERU_ENABLE_FORMULA")
            else None,
        ),
    )
    config = _merge_skill(config, env_config)

    if overrides:
        config = _merge_skill(config, _skill_from_mapping(overrides))

    ragflow = replace(
        config.ragflow,
        base_url=normalize_base_url(config.ragflow.base_url) if config.ragflow.base_url else None,
        timeout=60.0 if config.ragflow.timeout is None else config.ragflow.timeout,
        verify_ssl=True if config.ragflow.verify_ssl is None else config.ragflow.verify_ssl,
    )
    return replace(config, ragflow=ragflow)


def load_config(
    *,
    config_file: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> RagflowConfig:
    """Load runtime config from file, environment, and explicit overrides."""

    return load_skill_config(config_file=config_file, overrides=overrides, env=env).ragflow
