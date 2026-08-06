"""Local redaction helpers for ragflow-kb-build report scripts."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
from typing import Any

from ragflow_skill_runtime import configured_private_hosts_from_urls, sanitize_report_payload


_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_ASSIGNMENT_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;\"']+)"
)


def _collect_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_collect_urls(item))
        return urls
    if isinstance(value, (list, tuple)):
        urls = []
        for item in value:
            urls.extend(_collect_urls(item))
        return urls
    return []


def _collect_secret_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        values: list[str] = []
        for match in _ASSIGNMENT_SECRET_VALUE_RE.finditer(value):
            secret = match.group(1).strip()
            if len(secret) < 4:
                continue
            values.append(secret)
            stem = Path(secret).stem
            if len(stem) >= 4 and stem != secret:
                values.append(stem)
        return values
    if isinstance(value, dict):
        secrets: list[str] = []
        for item in value.values():
            secrets.extend(_collect_secret_literals(item))
        return secrets
    if isinstance(value, (list, tuple)):
        secrets = []
        for item in value:
            secrets.extend(_collect_secret_literals(item))
        return secrets
    return []


def _collect_path_like_literals(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if (
            "/" in text
            or "\\" in text
            or text.startswith(("~", "."))
            or text.endswith((".json", ".jsonl", ".md", ".yaml", ".yml", ".py", ".toml", ".txt"))
        ):
            paths = [text]
            if "://" not in text:
                path = Path(text)
                if str(path.parent) not in {"", ".", "/"}:
                    paths.append(str(path.parent))
            return paths
        return []
    if isinstance(value, dict):
        paths: list[str] = []
        for item in value.values():
            paths.extend(_collect_path_like_literals(item))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            paths.extend(_collect_path_like_literals(item))
        return paths
    return []


def _expand_config_paths(paths: list[str | None]) -> list[str | None]:
    expanded: list[str | None] = []
    for raw_path in paths:
        if not raw_path:
            continue
        text = str(raw_path)
        expanded.append(text)
        if "://" in text:
            continue
        parent = Path(text).parent
        if str(parent) not in {"", ".", "/"}:
            expanded.append(str(parent))
    return expanded


def _collect_redaction_context_from_json_paths(paths: list[str | None]) -> tuple[list[str], list[str], list[str]]:
    secrets: list[str] = []
    hosts: list[str] = []
    path_literals: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        try:
            payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            continue
        secrets.extend(_collect_secret_literals(payload))
        hosts.extend(configured_private_hosts_from_urls(_collect_urls(payload)))
        path_literals.extend(_collect_path_like_literals(payload))
    return secrets, hosts, path_literals


def sanitize_cli_report(
    report: dict[str, Any],
    args: argparse.Namespace,
    *,
    input_paths: list[str | None] | None = None,
    output_paths: list[str | None] | None = None,
    context_json_paths: list[str | None] | None = None,
    config: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sanitize a generated CLI report using report, argument, and JSON context."""

    context_secrets, context_hosts, context_paths = _collect_redaction_context_from_json_paths(context_json_paths or [])
    config_urls = [
        getattr(config, "base_url", None),
        getattr(config, "llm_base_url", None),
        getattr(args, "base_url", None),
    ]
    explicit_secrets = [
        getattr(config, "api_key", None),
        getattr(config, "llm_api_key", None),
        getattr(args, "api_key", None),
        *_collect_secret_literals(report),
        *context_secrets,
    ]
    urls = [*_collect_urls(report), *config_urls]
    config_paths = [
        *_expand_config_paths(input_paths or []),
        *_expand_config_paths(output_paths or []),
        *_expand_config_paths(
            [
                getattr(args, "config", None),
                getattr(args, "report_json", None),
                getattr(args, "report_md", None),
                getattr(args, "redaction_report", None),
            ]
        ),
        *context_paths,
        *_collect_path_like_literals(report),
    ]
    sanitized, redaction_report = sanitize_report_payload(
        report,
        explicit_secrets=explicit_secrets,
        private_hosts=[*configured_private_hosts_from_urls(urls), *context_hosts],
        config_paths=config_paths,
    )
    return sanitized, redaction_report
