"""Shared redaction helpers for generated public reports."""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPORT_REDACTION_REPORT_SCHEMA = "ragflow_report_redaction_report_v1"

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{6,}")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|token|access_token|secret|password)=)([^&#\s]+)"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*([:=])\s*([^\s,;\"']+)"
)


def _clean_literal_values(values: Sequence[str | None] | None) -> list[str]:
    unique: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if len(text) >= 4:
            unique.add(text)
    return sorted(unique, key=len, reverse=True)


def _private_host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    host = parsed.hostname
    if not host:
        return None
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        return host
    if lowered.endswith((".local", ".lan")) or "." not in lowered:
        return host
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return None
    if not ip.is_global:
        return host
    return None


def configured_private_hosts_from_urls(urls: Sequence[str | None] | None) -> list[str]:
    """Extract configured local/private hostnames from URL settings."""

    hosts = {host for host in (_private_host_from_url(url) for url in urls or []) if host}
    return sorted(hosts, key=len, reverse=True)


def _path_key(key: Any) -> str:
    text = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return f".{text}"
    return f"[{text!r}]"


def _replace_literals(text: str, values: list[str], replacement: str) -> tuple[str, int]:
    count = 0
    redacted = text
    for value in values:
        occurrences = redacted.count(value)
        if occurrences:
            redacted = redacted.replace(value, replacement)
            count += occurrences
    return redacted, count


def sanitize_report_payload(
    payload: Any,
    *,
    explicit_secrets: Sequence[str | None] | None = None,
    private_hosts: Sequence[str | None] | None = None,
    home_paths: Sequence[str | None] | None = None,
    config_paths: Sequence[str | None] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Sanitize a generated report and return a redaction sidecar report."""

    secrets = _clean_literal_values(explicit_secrets)
    hosts = _clean_literal_values(private_hosts)
    home_targets = _clean_literal_values([*(home_paths or []), str(Path.home())])
    config_targets = _clean_literal_values(config_paths)
    rule_counts = {
        "explicit_secret": 0,
        "bearer_token": 0,
        "query_secret": 0,
        "assignment_secret": 0,
        "private_host": 0,
        "home_path": 0,
        "config_path": 0,
    }
    findings: list[dict[str, Any]] = []

    def record(path: str, rule: str, count: int) -> None:
        if count <= 0:
            return
        rule_counts[rule] += count
        findings.append({"path": path, "rule": rule, "count": count})

    def sanitize_text(value: str, path: str) -> str:
        text = value
        text, count = _BEARER_RE.subn("Bearer <redacted:bearer-token>", text)
        record(path, "bearer_token", count)
        text, count = _QUERY_SECRET_RE.subn(r"\1<redacted:query-secret>", text)
        record(path, "query_secret", count)
        text, count = _ASSIGNMENT_SECRET_RE.subn(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted:secret>",
            text,
        )
        record(path, "assignment_secret", count)
        text, count = _replace_literals(text, secrets, "<redacted:secret>")
        record(path, "explicit_secret", count)
        text, count = _replace_literals(text, hosts, "<redacted:private-host>")
        record(path, "private_host", count)
        text, count = _replace_literals(text, config_targets, "<redacted:config-path>")
        record(path, "config_path", count)
        text, count = _replace_literals(text, home_targets, "<redacted:home-path>")
        record(path, "home_path", count)
        return text

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, str):
            return sanitize_text(value, path)
        if isinstance(value, list):
            return [walk(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, tuple):
            return [walk(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, Mapping):
            sanitized_items: dict[Any, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                sanitized_key = sanitize_text(key, f"{path}.<key[{index}]>") if isinstance(key, str) else key
                output_key = sanitized_key
                if sanitized_key in sanitized_items:
                    output_key = f"{sanitized_key}<duplicate:{index}>" if isinstance(sanitized_key, str) else index
                item_path = f"{path}{_path_key(output_key)}"
                sanitized_items[output_key] = walk(item, item_path)
            return sanitized_items
        return value

    sanitized = walk(payload, "$")
    redaction_count = sum(rule_counts.values())
    report = {
        "schema": REPORT_REDACTION_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "summary": {
            "changed": redaction_count > 0,
            "redaction_count": redaction_count,
            "field_count": len({finding["path"] for finding in findings}),
            "triggered_rule_count": sum(1 for value in rule_counts.values() if value),
        },
        "target_counts": {
            "explicit_secrets": len(secrets),
            "private_hosts": len(hosts),
            "home_paths": len(home_targets),
            "config_paths": len(config_targets),
        },
        "rule_counts": rule_counts,
        "findings": findings,
    }
    return sanitized, report
