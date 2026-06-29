"""Endpoint classification and reachability reports for ragflow-query."""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import re
import socket
import ssl
import time
from typing import Any, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlparse

from .runtime_cache import RuntimeCache, runtime_cache_secret_digest
from .runtime_metrics import RuntimeMetrics
from .runtime_resilience import (
    RuntimeCircuitBreaker,
    RuntimeCircuitBreakerPolicy,
    RuntimeRateLimitPolicy,
    RuntimeRateLimiter,
    RuntimeRetryPolicy,
    run_with_retry,
)


QUERY_ENDPOINT_REPORT_SCHEMA = "ragflow_query_endpoint_report_v1"
QUERY_ENDPOINT_REACHABILITY_STATUSES = (
    "not_configured",
    "invalid_url",
    "not_checked",
    "reachable",
    "unauthorized",
    "missing",
    "wrong_protocol",
    "timeout",
    "unreachable",
    "error",
    "circuit_open",
)

_HTTP_URL_RE = re.compile(r"https?://[^\s\"']+")
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_LAN_NETWORKS = (
    ipaddress.ip_network((3232235520, 16)),
    ipaddress.ip_network((2886729728, 12)),
)
_VPN_NETWORKS = (
    ipaddress.ip_network((167772160, 8)),
    ipaddress.ip_network((1681915904, 10)),
)


def _sanitize_message(value: str) -> str:
    return _HTTP_URL_RE.sub("<redacted-url>", str(value))


def _clean_label(value: str | None, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_")
    if not cleaned or "http:" in cleaned.lower() or "https:" in cleaned.lower():
        return fallback
    return cleaned[:64]


def _endpoint_kind(value: str | None) -> str:
    text = str(value or "custom").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")
    return cleaned[:32] or "custom"


def _strip_ipv6_brackets(host: str) -> str:
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def classify_endpoint_host(host: str | None) -> str:
    """Classify an endpoint host without returning the host itself."""

    if not host:
        return "unknown"
    lowered = _strip_ipv6_brackets(str(host).strip().lower())
    if lowered in _LOCAL_HOSTNAMES:
        return "local"
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        if lowered.endswith((".local", ".lan")):
            return "lan"
        if "." not in lowered:
            return "hostname"
        return "public"

    if ip.is_loopback:
        return "local"
    if ip.version == 4:
        for network in _LAN_NETWORKS:
            if ip in network:
                return "lan"
        for network in _VPN_NETWORKS:
            if ip in network:
                return "vpn"
    if ip.is_link_local:
        return "lan"
    if ip.is_private:
        return "private"
    if ip.is_global:
        return "public"
    return "private"


def _host_token(network_zone: str) -> str:
    tokens = {
        "local": "<local-host>",
        "lan": "<lan-host>",
        "vpn": "<vpn-host>",
        "private": "<private-host>",
        "public": "<public-host>",
        "hostname": "<hostname>",
    }
    return tokens.get(network_zone, "<host>")


def _path_depth(path: str) -> int:
    return len([part for part in path.split("/") if part])


def _port_configured(parsed: Any) -> bool:
    try:
        return parsed.port is not None
    except ValueError:
        return True


def _valid_endpoint_url(url: str | None) -> tuple[bool, str]:
    if not url:
        return False, "endpoint URL is not configured"
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "endpoint URL must use http or https"
    try:
        parsed.port
    except ValueError:
        return False, "endpoint URL port is invalid"
    return True, f"{parsed.scheme} endpoint configured"


def endpoint_url_summary(url: str | None) -> dict[str, Any]:
    """Return a redaction-safe endpoint URL summary."""

    if not url:
        return {"configured": False, "valid": False}
    parsed = urlparse(str(url))
    valid, reason = _valid_endpoint_url(str(url))
    network_zone = classify_endpoint_host(parsed.hostname)
    path_configured = bool(parsed.path and parsed.path != "/")
    redacted = None
    if parsed.scheme:
        redacted = f"{parsed.scheme}://{_host_token(network_zone)}"
        if _port_configured(parsed):
            redacted += ":<port>"
        if path_configured:
            redacted += "/<path>"
        if parsed.query:
            redacted += "?<query>"
        if parsed.fragment:
            redacted += "#<fragment>"
    return {
        "configured": True,
        "valid": valid,
        "reason": reason,
        "scheme": parsed.scheme or None,
        "https": parsed.scheme == "https",
        "network_zone": network_zone,
        "redacted_url": redacted,
        "host_redacted": _host_token(network_zone),
        "port_configured": _port_configured(parsed),
        "path_configured": path_configured,
        "path_depth": _path_depth(parsed.path),
        "query_configured": bool(parsed.query),
        "fragment_configured": bool(parsed.fragment),
    }


def _ssl_context(*, verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    return ssl._create_unverified_context()


def _network_probe(
    url: str,
    *,
    api_key: str | None,
    timeout: float,
    verify_ssl: bool,
) -> tuple[str, str, int | None]:
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "ragflow-query-endpoint-report",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, method="HEAD", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl=verify_ssl)) as resp:
            return "reachable", f"endpoint responded with HTTP {resp.status}", resp.status
    except error.HTTPError as exc:
        if exc.code in {401, 403}:
            return "unauthorized", "endpoint exists but credentials were rejected or required", exc.code
        if exc.code == 404:
            return "missing", "endpoint returned HTTP 404", exc.code
        if exc.code in {400, 405, 415} or 200 <= exc.code < 500:
            return "reachable", f"endpoint responded with HTTP {exc.code}; service is reachable", exc.code
        if 500 <= exc.code < 600:
            return "error", f"endpoint returned HTTP {exc.code}", exc.code
        return "wrong_protocol", f"endpoint returned HTTP {exc.code}", exc.code
    except TimeoutError:
        return "timeout", f"endpoint check timed out after {timeout:g}s", None
    except socket.timeout:
        return "timeout", f"endpoint check timed out after {timeout:g}s", None
    except error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "timeout", f"endpoint check timed out after {timeout:g}s", None
        return "unreachable", f"endpoint check failed: {_sanitize_message(str(exc.reason))}", None
    except OSError as exc:
        return "unreachable", f"endpoint check failed: {_sanitize_message(str(exc))}", None


def _endpoint_report_entry(
    *,
    label: str,
    kind: str,
    url: str | None,
    api_key_configured: bool,
    api_key: str | None,
    network_check: bool,
    timeout: float,
    verify_ssl: bool,
    retry_policy: RuntimeRetryPolicy,
    runtime_cache: RuntimeCache | None = None,
    rate_limiter: RuntimeRateLimiter | None = None,
    circuit_breaker: RuntimeCircuitBreaker | None = None,
) -> dict[str, Any]:
    summary = endpoint_url_summary(url)
    checks: list[dict[str, Any]] = [
        {"name": "url_configured", "ok": bool(url)},
        {"name": "http_url", "ok": bool(summary.get("valid"))},
        {"name": "https", "ok": summary.get("https") if summary.get("configured") else None},
        {"name": "api_key_configured", "ok": bool(api_key_configured)},
    ]
    if not url:
        checks.append({"name": "network_check", "ok": None, "skipped": True})
        return {
            "label": label,
            "kind": kind,
            "status": "not_configured",
            "endpoint": summary,
            "api_key_configured": bool(api_key_configured),
            "checks": checks,
            "reason": "endpoint URL is not configured",
        }
    if not summary.get("valid"):
        checks.append({"name": "network_check", "ok": None, "skipped": True})
        return {
            "label": label,
            "kind": kind,
            "status": "invalid_url",
            "endpoint": summary,
            "api_key_configured": bool(api_key_configured),
            "checks": checks,
            "reason": str(summary.get("reason") or "endpoint URL is invalid"),
        }
    if not network_check:
        checks.append({"name": "network_check", "ok": None, "skipped": True})
        return {
            "label": label,
            "kind": kind,
            "status": "not_checked",
            "endpoint": summary,
            "api_key_configured": bool(api_key_configured),
            "checks": checks,
            "reason": "network check disabled",
        }

    cache_lookup = None
    if runtime_cache is not None:
        cache_lookup = runtime_cache.get(
            {
                "label": label,
                "kind": kind,
                "url": str(url),
                "api_key": runtime_cache_secret_digest(api_key),
                "timeout": float(timeout),
                "verify_ssl": bool(verify_ssl),
                "retry_policy": retry_policy.to_report(),
            }
        )
        if cache_lookup.status == "hit" and isinstance(cache_lookup.value, Mapping):
            cached = cache_lookup.value
            status = str(cached.get("status") or "error")
            if status not in QUERY_ENDPOINT_REACHABILITY_STATUSES:
                status = "error"
            reason = str(cached.get("reason") or "cached endpoint check result")
            checks.append({"name": "network_check", "ok": status in {"reachable", "unauthorized"}, "cached": True})
            entry: dict[str, Any] = {
                "label": label,
                "kind": kind,
                "status": status,
                "endpoint": summary,
                "api_key_configured": bool(api_key_configured),
                "checks": checks,
                "cache": cache_lookup.to_report(),
                "cached": True,
                "reason": reason,
            }
            http_status = cached.get("http_status")
            if isinstance(http_status, int):
                entry["http_status"] = http_status
            return entry

    if circuit_breaker is not None:
        circuit_decision = circuit_breaker.before_request()
        if not circuit_decision.get("allowed"):
            checks.append({"name": "network_check", "ok": False, "skipped": True, "circuit_open": True})
            return {
                "label": label,
                "kind": kind,
                "status": "circuit_open",
                "endpoint": summary,
                "api_key_configured": bool(api_key_configured),
                "checks": checks,
                "circuit_breaker": circuit_decision,
                "reason": str(circuit_decision.get("reason") or "circuit breaker is open"),
            }

    started = time.monotonic()

    def probe_once() -> tuple[str, str, int | None]:
        if rate_limiter is not None and rate_limiter.enabled:
            rate_limiter.acquire()
        return _network_probe(
            str(url),
            api_key=api_key,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    probe = run_with_retry(
        probe_once,
        status_getter=lambda result: str(result[0]),
        policy=retry_policy,
    )
    status, reason, http_status = probe.result
    if circuit_breaker is not None:
        circuit_breaker.record_result(status)
    checks.append({"name": "network_check", "ok": status in {"reachable", "unauthorized"}})
    entry: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "status": status if status in QUERY_ENDPOINT_REACHABILITY_STATUSES else "error",
        "endpoint": summary,
        "api_key_configured": bool(api_key_configured),
        "checks": checks,
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "retry_trace": probe.trace,
        "reason": reason,
    }
    if http_status is not None:
        entry["http_status"] = http_status
    if runtime_cache is not None and cache_lookup is not None:
        cache_report = cache_lookup.to_report()
        store = runtime_cache.put(
            cache_lookup.cache_key,
            {
                "status": entry["status"],
                "reason": reason,
                "http_status": http_status,
            },
        )
        cache_report["write_status"] = store.status
        entry["cache"] = cache_report
    return entry


def _normal_endpoint_specs(extra_endpoints: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, endpoint in enumerate(extra_endpoints or [], start=1):
        if not isinstance(endpoint, Mapping):
            continue
        fallback = f"custom_{index}"
        entries.append(
            {
                "label": _clean_label(str(endpoint.get("label") or ""), fallback=fallback),
                "kind": _endpoint_kind(str(endpoint.get("kind") or "custom")),
                "url": endpoint.get("url"),
                "api_key_configured": bool(endpoint.get("api_key_configured")),
                "api_key": endpoint.get("api_key") if isinstance(endpoint.get("api_key"), str) else None,
            }
        )
    return entries


def _issue_for_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(entry.get("status") or "")
    label = str(entry.get("label") or "endpoint")
    endpoint = entry.get("endpoint") if isinstance(entry.get("endpoint"), Mapping) else {}
    if status == "invalid_url":
        return {
            "severity": "error",
            "code": "endpoint_invalid_url",
            "message": f"{label} endpoint URL is invalid: {entry.get('reason')}",
            "recommendation": "Use a full http:// or https:// endpoint URL.",
        }
    if status in {"timeout", "unreachable", "error", "wrong_protocol"}:
        return {
            "severity": "error",
            "code": f"endpoint_{status}",
            "message": f"{label} endpoint check failed: {entry.get('reason')}",
            "recommendation": "Check network route, service health, protocol, and timeout settings.",
        }
    if status == "circuit_open":
        return {
            "severity": "error",
            "code": "endpoint_circuit_open",
            "message": f"{label} endpoint check was skipped because the circuit breaker is open.",
            "recommendation": "Inspect earlier endpoint failures or increase the circuit-breaker threshold.",
        }
    if status in {"missing", "unauthorized"}:
        return {
            "severity": "warning",
            "code": f"endpoint_{status}",
            "message": f"{label} endpoint responded with status `{status}`: {entry.get('reason')}",
            "recommendation": "Confirm the endpoint path and credentials before running live retrieval.",
        }
    if endpoint.get("network_zone") == "public" and endpoint.get("scheme") == "http":
        return {
            "severity": "warning",
            "code": "endpoint_public_http",
            "message": f"{label} endpoint is public and not HTTPS.",
            "recommendation": "Prefer HTTPS for public endpoints or keep the endpoint on a private network.",
        }
    if endpoint.get("query_configured"):
        return {
            "severity": "warning",
            "code": "endpoint_url_query",
            "message": f"{label} endpoint URL includes a query string.",
            "recommendation": "Move tokens and credentials to headers or config fields instead of URL query parameters.",
        }
    return None


def build_query_endpoint_report(
    *,
    ragflow_base_url: str | None,
    ragflow_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    extra_endpoints: Sequence[Mapping[str, Any]] | None = None,
    network_check: bool = False,
    timeout: float = 5.0,
    verify_ssl: bool = True,
    retry_budget: int = 1,
    retry_backoff_seconds: float = 0.0,
    cache_dir: str | None = None,
    cache_ttl_seconds: float = 300.0,
    rate_limit_per_second: float | None = None,
    rate_limit_burst: int = 1,
    circuit_breaker_failure_threshold: int | None = None,
    circuit_breaker_recovery_seconds: float | None = None,
) -> dict[str, Any]:
    """Build a redaction-safe endpoint report for query workflows."""

    if timeout <= 0:
        raise ValueError("endpoint report timeout must be greater than zero")
    retry_policy = RuntimeRetryPolicy(
        retry_budget=retry_budget,
        backoff_seconds=retry_backoff_seconds,
    )
    runtime_cache = RuntimeCache(
        operation=QUERY_ENDPOINT_REPORT_SCHEMA,
        cache_dir=cache_dir,
        ttl_seconds=cache_ttl_seconds,
        namespace="endpoint-report",
    )
    rate_limiter = RuntimeRateLimiter(
        policy=RuntimeRateLimitPolicy(
            rate_per_second=rate_limit_per_second,
            burst=rate_limit_burst,
        )
    )
    circuit_breaker = RuntimeCircuitBreaker(
        policy=RuntimeCircuitBreakerPolicy(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_seconds=circuit_breaker_recovery_seconds,
        )
    )

    specs = [
        {
            "label": "ragflow_api",
            "kind": "ragflow",
            "url": ragflow_base_url,
            "api_key_configured": bool(ragflow_api_key),
            "api_key": ragflow_api_key,
        }
    ]
    if llm_base_url:
        specs.append(
            {
                "label": "llm_api",
                "kind": "llm",
                "url": llm_base_url,
                "api_key_configured": bool(llm_api_key),
                "api_key": llm_api_key,
            }
        )
    specs.extend(_normal_endpoint_specs(extra_endpoints))

    endpoints = [
        _endpoint_report_entry(
            label=str(spec["label"]),
            kind=str(spec["kind"]),
            url=spec.get("url") if isinstance(spec.get("url"), str) else None,
            api_key_configured=bool(spec.get("api_key_configured")),
            api_key=spec.get("api_key") if isinstance(spec.get("api_key"), str) else None,
            network_check=network_check,
            timeout=timeout,
            verify_ssl=verify_ssl,
            retry_policy=retry_policy,
            runtime_cache=runtime_cache,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
        )
        for spec in specs
    ]
    status_counts = {status: 0 for status in QUERY_ENDPOINT_REACHABILITY_STATUSES}
    zone_counts: dict[str, int] = {}
    https_count = 0
    configured_count = 0
    for entry in endpoints:
        status = str(entry.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        endpoint = entry.get("endpoint") if isinstance(entry.get("endpoint"), Mapping) else {}
        if endpoint.get("configured"):
            configured_count += 1
        if endpoint.get("https"):
            https_count += 1
        zone = str(endpoint.get("network_zone") or "unknown")
        zone_counts[zone] = zone_counts.get(zone, 0) + 1

    issues = [issue for issue in (_issue_for_entry(entry) for entry in endpoints) if issue]
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    network_attempt_count = 0
    retry_count = 0
    for entry in endpoints:
        retry_trace = entry.get("retry_trace") if isinstance(entry.get("retry_trace"), Mapping) else {}
        network_attempt_count += int(retry_trace.get("attempt_count", 0) or 0)
        retry_count += int(retry_trace.get("retry_count", 0) or 0)
    runtime_metrics = RuntimeMetrics(operation=QUERY_ENDPOINT_REPORT_SCHEMA)
    runtime_metrics.increment_counter("endpoint_count", len(endpoints))
    runtime_metrics.increment_counter("configured_endpoint_count", configured_count)
    runtime_metrics.increment_counter("checked_endpoint_count", len(endpoints) if network_check else 0)
    runtime_metrics.increment_counter("network_attempt_count", network_attempt_count)
    runtime_metrics.increment_counter("retry_count", retry_count)
    runtime_metrics.increment_counter("reachable_endpoint_count", status_counts.get("reachable", 0))
    runtime_metrics.increment_counter("warning_count", warning_count)
    runtime_metrics.increment_counter("error_count", error_count)
    for status in QUERY_ENDPOINT_REACHABILITY_STATUSES:
        runtime_metrics.increment_counter(f"status_{status}", status_counts.get(status, 0))
    if endpoints:
        runtime_metrics.set_gauge("configured_endpoint_ratio", configured_count / len(endpoints))
        runtime_metrics.set_gauge("https_endpoint_ratio", https_count / len(endpoints))
    else:
        runtime_metrics.set_gauge("configured_endpoint_ratio", 0.0)
        runtime_metrics.set_gauge("https_endpoint_ratio", 0.0)
    for entry in endpoints:
        latency = entry.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            runtime_metrics.observe_latency_ms(latency)
    runtime_cache_report = runtime_cache.to_report()
    cache_summary = runtime_cache_report["summary"]
    for name, value in runtime_cache_report["counters"].items():
        runtime_metrics.increment_counter(f"cache_{name}", value)
    runtime_rate_limit_report = rate_limiter.to_report()
    rate_limit_summary = runtime_rate_limit_report["summary"]
    runtime_metrics.increment_counter("rate_limit_acquire_count", rate_limit_summary["acquire_count"])
    runtime_metrics.increment_counter("rate_limit_delayed_count", rate_limit_summary["delayed_count"])
    runtime_circuit_breaker_report = circuit_breaker.to_report()
    circuit_breaker_summary = runtime_circuit_breaker_report["summary"]
    runtime_metrics.increment_counter("circuit_breaker_failure_count", circuit_breaker_summary["failure_count"])
    runtime_metrics.increment_counter("circuit_breaker_open_count", circuit_breaker_summary["open_count"])
    runtime_metrics.increment_counter(
        "circuit_breaker_short_circuit_count",
        circuit_breaker_summary["short_circuit_count"],
    )
    return {
        "schema": QUERY_ENDPOINT_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": error_count == 0,
        "network_check": bool(network_check),
        "timeout_seconds": timeout,
        "verify_ssl": bool(verify_ssl),
        "retry_policy": retry_policy.to_report(),
        "allowed_statuses": list(QUERY_ENDPOINT_REACHABILITY_STATUSES),
        "summary": {
            "endpoint_count": len(endpoints),
            "configured_endpoint_count": configured_count,
            "https_endpoint_count": https_count,
            "checked_endpoint_count": len(endpoints) if network_check else 0,
            "network_attempt_count": network_attempt_count,
            "retry_count": retry_count,
            "reachable_endpoint_count": status_counts.get("reachable", 0),
            "warning_count": warning_count,
            "error_count": error_count,
            "cache_hit_count": cache_summary["hit_count"],
            "cache_miss_count": cache_summary["miss_count"],
            "cache_stale_count": cache_summary["stale_count"],
            "rate_limit_acquire_count": rate_limit_summary["acquire_count"],
            "rate_limit_delayed_count": rate_limit_summary["delayed_count"],
            "circuit_breaker_failure_count": circuit_breaker_summary["failure_count"],
            "circuit_breaker_open_count": circuit_breaker_summary["open_count"],
            "circuit_breaker_short_circuit_count": circuit_breaker_summary["short_circuit_count"],
        },
        "status_counts": status_counts,
        "network_zone_counts": zone_counts,
        "runtime_metrics": runtime_metrics.to_report(),
        "runtime_cache": runtime_cache_report,
        "runtime_rate_limit": runtime_rate_limit_report,
        "runtime_circuit_breaker": runtime_circuit_breaker_report,
        "endpoints": endpoints,
        "issues": issues,
    }


def render_query_endpoint_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown endpoint report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    retry_policy = report.get("retry_policy") if isinstance(report.get("retry_policy"), Mapping) else {}
    runtime_metrics = report.get("runtime_metrics") if isinstance(report.get("runtime_metrics"), Mapping) else {}
    latency = runtime_metrics.get("latency_ms") if isinstance(runtime_metrics.get("latency_ms"), Mapping) else {}
    runtime_cache = report.get("runtime_cache") if isinstance(report.get("runtime_cache"), Mapping) else {}
    cache_summary = runtime_cache.get("summary") if isinstance(runtime_cache.get("summary"), Mapping) else {}
    runtime_rate_limit = report.get("runtime_rate_limit") if isinstance(report.get("runtime_rate_limit"), Mapping) else {}
    rate_limit_summary = (
        runtime_rate_limit.get("summary") if isinstance(runtime_rate_limit.get("summary"), Mapping) else {}
    )
    runtime_circuit_breaker = (
        report.get("runtime_circuit_breaker")
        if isinstance(report.get("runtime_circuit_breaker"), Mapping)
        else {}
    )
    circuit_breaker_summary = (
        runtime_circuit_breaker.get("summary")
        if isinstance(runtime_circuit_breaker.get("summary"), Mapping)
        else {}
    )
    lines = [
        "# RAGFlow Query Endpoint Report",
        "",
        f"- schema: `{report.get('schema', QUERY_ENDPOINT_REPORT_SCHEMA)}`",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- network_check: `{str(report.get('network_check', False)).lower()}`",
        f"- endpoints: `{summary.get('endpoint_count', 0)}`",
        f"- configured: `{summary.get('configured_endpoint_count', 0)}`",
        f"- https: `{summary.get('https_endpoint_count', 0)}`",
        f"- reachable: `{summary.get('reachable_endpoint_count', 0)}`",
        f"- retry_budget: `{retry_policy.get('retry_budget', 1)}`",
        f"- retry_count: `{summary.get('retry_count', 0)}`",
    ]
    if runtime_metrics:
        p95 = latency.get("p95")
        lines.extend(
            [
                f"- latency_samples: `{latency.get('sample_count', 0)}`",
                f"- latency_p95_ms: `{p95 if p95 is not None else 'n/a'}`",
            ]
        )
    if runtime_cache:
        lines.extend(
            [
                f"- cache_enabled: `{str(runtime_cache.get('enabled', False)).lower()}`",
                f"- cache_hits: `{cache_summary.get('hit_count', 0)}`",
                f"- cache_misses: `{cache_summary.get('miss_count', 0)}`",
            ]
        )
    if runtime_rate_limit:
        lines.extend(
            [
                f"- rate_limit_enabled: `{str(runtime_rate_limit.get('enabled', False)).lower()}`",
                f"- rate_limit_acquires: `{rate_limit_summary.get('acquire_count', 0)}`",
                f"- rate_limit_delays: `{rate_limit_summary.get('delayed_count', 0)}`",
            ]
        )
    if runtime_circuit_breaker:
        lines.extend(
            [
                f"- circuit_breaker_enabled: `{str(runtime_circuit_breaker.get('enabled', False)).lower()}`",
                f"- circuit_breaker_state: `{circuit_breaker_summary.get('state', 'closed')}`",
                f"- circuit_breaker_opens: `{circuit_breaker_summary.get('open_count', 0)}`",
                f"- circuit_breaker_short_circuits: `{circuit_breaker_summary.get('short_circuit_count', 0)}`",
            ]
        )
    lines.extend(
        [
            "",
            "| endpoint | status | zone | scheme | URL summary | reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for entry in report.get("endpoints", []) if isinstance(report.get("endpoints"), list) else []:
        if not isinstance(entry, Mapping):
            continue
        endpoint = entry.get("endpoint") if isinstance(entry.get("endpoint"), Mapping) else {}
        reason = str(entry.get("reason", "")).replace("|", "\\|")
        lines.append(
            f"| `{entry.get('label', '')}` | `{entry.get('status', '')}` | "
            f"`{endpoint.get('network_zone', '')}` | `{endpoint.get('scheme', '')}` | "
            f"`{endpoint.get('redacted_url', '')}` | {reason} |"
        )
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    if issues:
        lines.extend(["", "## Issues", ""])
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
            if issue.get("recommendation"):
                lines.append(f"  Recommendation: {issue.get('recommendation')}")
    return "\n".join(lines).rstrip() + "\n"
