"""RAGFlow model provider readiness probes."""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import re
import time
from typing import Any, Mapping
from urllib.parse import urlparse

from .http import JSONHTTPClient


MODEL_PROVIDER_PROBE_REPORT_SCHEMA = "ragflow_model_provider_probe_report_v1"
MODEL_PROVIDER_PROBE_STATUSES = (
    "available",
    "missing",
    "wrong_protocol",
    "timeout",
    "unauthorized",
    "error",
)
ADAPTER_PROBE_STATUSES = (
    "not_configured",
    "handled_empty_input",
    "missing",
    "wrong_protocol",
    "timeout",
    "unauthorized",
    "error",
)
EMBEDDING_ADAPTER_SHAPES = ("openai", "generic")
RERANK_ADAPTER_SHAPES = ("cohere", "generic")
DEFAULT_MODEL_PROVIDER_ENDPOINTS = (
    "/llm/factories",
    "/llm/my_llms",
    "/llm/models",
    "/models",
    "/model-providers",
)

_HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})")
_URL_RE = re.compile(r"https?://[^\s\"']+")
_PROVIDER_LIST_KEYS = (
    "providers",
    "provider",
    "factories",
    "factory",
    "items",
    "list",
    "llms",
    "models",
)
_MODEL_LIST_KEYS = (
    "models",
    "model_list",
    "llms",
    "items",
    "children",
    "available_models",
)
_PROVIDER_ID_KEYS = (
    "id",
    "provider_id",
    "factory",
    "llm_factory",
    "provider",
    "provider_name",
    "name",
)
_PROVIDER_DISPLAY_KEYS = (
    "display_name",
    "label",
    "name",
    "provider_name",
    "factory",
    "id",
)
_MODEL_NAME_KEYS = (
    "name",
    "model",
    "model_name",
    "llm_name",
    "id",
)
_MODEL_TYPE_KEYS = (
    "type",
    "model_type",
    "category",
    "mode",
    "task",
)


def _clean_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _first_string(data: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean_string(data.get(key))
        if value:
            return value
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _unwrap_data(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload


def _extract_list(data: Any, keys: tuple[str, ...]) -> tuple[list[Mapping[str, Any]], str | None]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)], "data"
    if not isinstance(data, Mapping):
        return [], None
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)], key
    for key in keys:
        value = data.get(key)
        if isinstance(value, Mapping):
            nested, nested_key = _extract_list(value, keys)
            if nested:
                return nested, f"{key}.{nested_key}" if nested_key else key
    return [], None


def _model_name(item: Mapping[str, Any]) -> str | None:
    return _first_string(item, _MODEL_NAME_KEYS)


def _model_type(item: Mapping[str, Any]) -> str | None:
    direct = _first_string(item, _MODEL_TYPE_KEYS)
    tokens: list[str] = []
    if direct:
        tokens.append(direct)
    for key in ("tags", "capabilities", "features"):
        value = item.get(key)
        if isinstance(value, str):
            tokens.append(value)
        elif isinstance(value, list):
            tokens.extend(str(part) for part in value)
    name = _model_name(item)
    if name:
        tokens.append(name)
    haystack = " ".join(tokens).lower()
    if "rerank" in haystack or "ranker" in haystack:
        return "rerank"
    if "embed" in haystack or "embedding" in haystack or "vector" in haystack:
        return "embedding"
    return direct


def _is_model_like(item: Mapping[str, Any]) -> bool:
    if any(key in item for key in _MODEL_LIST_KEYS):
        return False
    if not _model_name(item):
        return False
    if _model_type(item):
        return True
    return any(key in item for key in ("name", "model", "model_name", "llm_name"))


def _provider_models(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in _MODEL_LIST_KEYS:
        value = item.get(key)
        if isinstance(value, list):
            return [model for model in value if isinstance(model, Mapping)]
        if isinstance(value, Mapping):
            nested, _ = _extract_list(value, _MODEL_LIST_KEYS)
            if nested:
                return nested
    if _is_model_like(item):
        return [item]
    return []


def _provider_payloads(payload: Any) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    data = _unwrap_data(payload)
    items, list_key = _extract_list(data, _PROVIDER_LIST_KEYS)
    shape = {
        "top_level_type": type(payload).__name__,
        "data_type": type(data).__name__,
        "list_key": list_key,
        "item_count": len(items),
    }
    if not items:
        return [], shape
    model_like_count = sum(1 for item in items if _is_model_like(item))
    provider_like_count = sum(1 for item in items if _provider_models(item) and not _is_model_like(item))
    if model_like_count and provider_like_count == 0:
        return [{"id": "unknown", "display_name": "Unknown provider", "models": items}], shape
    return items, shape


def _normalize_model(item: Mapping[str, Any], *, provider_id: str) -> dict[str, Any]:
    name = _model_name(item) or "unknown"
    model_type = _model_type(item)
    payload = {
        "name": name,
        "provider_id": provider_id,
    }
    if model_type:
        payload["type"] = model_type
    display_name = _first_string(item, ("display_name", "label"))
    if display_name and display_name != name:
        payload["display_name"] = display_name
    return payload


def _normalize_provider(item: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = _first_string(item, _PROVIDER_ID_KEYS) or "unknown"
    display_name = _first_string(item, _PROVIDER_DISPLAY_KEYS) or provider_id
    models = [_normalize_model(model, provider_id=provider_id) for model in _provider_models(item)]
    capabilities = sorted(
        {
            str(model.get("type"))
            for model in models
            if _clean_string(model.get("type")) in {"embedding", "rerank"}
        }
    )
    payload = {
        "id": provider_id,
        "display_name": display_name,
        "model_count": len(models),
        "capabilities": capabilities,
        "models": models,
    }
    status = _clean_string(item.get("status") or item.get("state"))
    if status:
        payload["status"] = status
    return payload


def _http_status_from_error(message: str) -> int | None:
    match = _HTTP_STATUS_RE.search(message)
    if not match:
        return None
    return int(match.group(1))


def _classify_error(exc: Exception) -> tuple[str, str]:
    message = str(exc)
    status = _http_status_from_error(message)
    if status in {401, 403}:
        return "unauthorized", "endpoint exists but credentials were rejected"
    if status == 404:
        return "missing", "endpoint returned HTTP 404"
    if status is not None:
        return "wrong_protocol", f"endpoint returned HTTP {status}"
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout", message
    if "not valid json" in lowered:
        return "wrong_protocol", message
    if "request failed" in lowered:
        return "missing", message
    return "error", message


def _sanitize_message(value: str) -> str:
    return _URL_RE.sub("<redacted-url>", value)


def _host_type(host: str | None) -> str:
    if not host:
        return "unknown"
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        return "local"
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return "private" if lowered.endswith(".local") else "hostname"
    if ip.is_loopback:
        return "local"
    if ip.is_private:
        return "private"
    return "public"


def _url_summary(url: str | None) -> dict[str, Any]:
    if not url:
        return {"configured": False}
    parsed = urlparse(str(url))
    return {
        "configured": True,
        "scheme": parsed.scheme or None,
        "host_type": _host_type(parsed.hostname),
        "path_configured": bool(parsed.path and parsed.path != "/"),
    }


def _response_shape(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    results = None
    if isinstance(data, list):
        results = len(data)
    elif isinstance(payload, Mapping):
        for key in ("results", "items", "scores", "rerank", "embeddings"):
            value = payload.get(key)
            if isinstance(value, list):
                results = len(value)
                break
    return {
        "top_level_type": type(payload).__name__,
        "data_type": type(data).__name__ if data is not None else None,
        "result_count": results,
    }


def _adapter_request_payload(*, kind: str, shape: str, model: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    model_name = model or "ragflow-empty-input-probe"
    if kind == "embedding":
        if shape not in EMBEDDING_ADAPTER_SHAPES:
            allowed = ", ".join(EMBEDDING_ADAPTER_SHAPES)
            raise ValueError(f"embedding adapter shape must be one of: {allowed}")
        if shape == "generic":
            payload = {"model": model_name, "texts": []}
            empty_input_field = "texts"
        else:
            payload = {"model": model_name, "input": []}
            empty_input_field = "input"
    else:
        if shape not in RERANK_ADAPTER_SHAPES:
            allowed = ", ".join(RERANK_ADAPTER_SHAPES)
            raise ValueError(f"rerank adapter shape must be one of: {allowed}")
        payload = {"model": model_name, "query": "", "documents": []}
        empty_input_field = "documents"

    return payload, {
        "kind": kind,
        "shape": shape,
        "method": "POST",
        "json_keys": sorted(payload),
        "empty_input_field": empty_input_field,
        "model_configured": bool(model),
    }


def _classify_adapter_error(exc: Exception) -> tuple[str, str]:
    message = _sanitize_message(str(exc))
    status = _http_status_from_error(message)
    if status in {400, 422}:
        return "handled_empty_input", f"endpoint rejected empty input with HTTP {status}"
    if status in {401, 403}:
        return "unauthorized", "endpoint exists but credentials were rejected"
    if status == 404:
        return "missing", "endpoint returned HTTP 404"
    if status is not None:
        return "error", f"endpoint returned HTTP {status}"
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout", message
    if "not valid json" in lowered:
        return "wrong_protocol", message
    if "request failed" in lowered:
        return "missing", message
    return "error", message


def _probe_adapter_empty_input(
    *,
    kind: str,
    url: str | None,
    api_key: str | None,
    shape: str,
    model: str | None,
    timeout: float,
) -> dict[str, Any]:
    endpoint = _url_summary(url)
    if not url:
        return {
            "kind": kind,
            "status": "not_configured",
            "endpoint": endpoint,
            "request_shape": {"kind": kind, "shape": shape},
            "reason": "adapter URL is not configured",
        }
    payload, request_shape = _adapter_request_payload(kind=kind, shape=shape, model=model)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = time.monotonic()
    try:
        response = JSONHTTPClient(timeout=timeout, headers=headers).request_json("POST", url, json_body=payload)
    except Exception as exc:  # noqa: BLE001 - adapter probes report transport behavior.
        status, reason = _classify_adapter_error(exc)
        return {
            "kind": kind,
            "status": status,
            "endpoint": endpoint,
            "request_shape": request_shape,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "reason": reason,
            "error_type": type(exc).__name__,
        }
    return {
        "kind": kind,
        "status": "handled_empty_input",
        "endpoint": endpoint,
        "request_shape": request_shape,
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "http_status": response.status,
        "response_shape": _response_shape(response.data),
        "reason": "endpoint accepted empty input and returned JSON",
    }


def _dedupe_providers(providers: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in providers:
        provider = _normalize_provider(raw)
        provider_id = provider["id"]
        existing = by_id.get(provider_id)
        if existing is None:
            by_id[provider_id] = provider
            continue
        existing_models = {(model["name"], model.get("type")) for model in existing.get("models", [])}
        for model in provider.get("models", []):
            key = (model["name"], model.get("type"))
            if key not in existing_models:
                existing["models"].append(model)
                existing_models.add(key)
        existing["model_count"] = len(existing.get("models", []))
        existing["capabilities"] = sorted(
            set(existing.get("capabilities", [])) | set(provider.get("capabilities", []))
        )
    return sorted(by_id.values(), key=lambda item: str(item.get("display_name", item.get("id", ""))).lower())


def _probe_endpoint(client: Any, path: str) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    started = time.monotonic()
    try:
        payload = client.get(path)
    except Exception as exc:  # noqa: BLE001 - probe converts failures into report entries.
        status, reason = _classify_error(exc)
        return (
            {
                "path": path,
                "method": "GET",
                "status": status,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "provider_count": 0,
                "model_count": 0,
                "reason": reason,
                "error_type": type(exc).__name__,
            },
            [],
        )

    providers, shape = _provider_payloads(payload)
    normalized = [_normalize_provider(item) for item in providers]
    model_count = sum(int(provider.get("model_count", 0)) for provider in normalized)
    status = "available" if normalized else "wrong_protocol"
    entry = {
        "path": path,
        "method": "GET",
        "status": status,
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "provider_count": len(normalized),
        "model_count": model_count,
        "response_shape": shape,
    }
    if not normalized:
        entry["reason"] = "response did not contain a recognizable provider or model list"
    return entry, providers


def _all_models(providers: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    models: list[Mapping[str, Any]] = []
    for provider in providers:
        for model in provider.get("models", []) if isinstance(provider.get("models"), list) else []:
            if isinstance(model, Mapping):
                models.append(model)
    return models


def _model_lookup(models: list[Mapping[str, Any]]) -> set[str]:
    names = set()
    for model in models:
        name = _clean_string(model.get("name"))
        if name:
            names.add(name.lower())
    return names


def _expected_model_checks(
    *,
    kind: str,
    expected: list[str],
    models: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if not expected:
        return checks, issues
    lookup = _model_lookup(
        [model for model in models if _clean_string(model.get("type")) in {kind, None} or model.get("type") == kind]
    )
    for name in expected:
        normalized = name.strip()
        if not normalized:
            continue
        found = normalized.lower() in lookup
        checks.append({"kind": kind, "model": normalized, "found": found})
        if not found:
            issues.append(
                {
                    "severity": "warning",
                    "code": f"{kind}_model_not_registered",
                    "message": f"expected {kind} model is not visible in provider probe: {normalized}",
                    "recommendation": "Confirm the model is registered in RAGFlow before parsing or validating KBs.",
                }
            )
    return checks, issues


def probe_model_providers(
    client: Any,
    *,
    endpoint_paths: list[str] | tuple[str, ...] | None = None,
    expected_embedding_models: list[str] | tuple[str, ...] | None = None,
    expected_rerank_models: list[str] | tuple[str, ...] | None = None,
    embedding_adapter_url: str | None = None,
    embedding_adapter_api_key: str | None = None,
    embedding_adapter_shape: str = "openai",
    rerank_adapter_url: str | None = None,
    rerank_adapter_api_key: str | None = None,
    rerank_adapter_shape: str = "cohere",
    adapter_timeout: float = 5.0,
) -> dict[str, Any]:
    """Probe read-only RAGFlow model-provider endpoints."""

    if adapter_timeout <= 0:
        raise ValueError("adapter timeout must be greater than zero")

    paths = list(endpoint_paths or DEFAULT_MODEL_PROVIDER_ENDPOINTS)
    if not paths:
        paths = list(DEFAULT_MODEL_PROVIDER_ENDPOINTS)
    endpoint_entries: list[dict[str, Any]] = []
    provider_payloads: list[Mapping[str, Any]] = []
    for path in paths:
        normalized_path = "/" + str(path).strip().lstrip("/")
        entry, providers = _probe_endpoint(client, normalized_path)
        endpoint_entries.append(entry)
        provider_payloads.extend(providers)

    providers = _dedupe_providers(provider_payloads)
    models = _all_models(providers)
    embedding_models = [model for model in models if model.get("type") == "embedding"]
    rerank_models = [model for model in models if model.get("type") == "rerank"]
    embedding_checks, embedding_issues = _expected_model_checks(
        kind="embedding",
        expected=list(expected_embedding_models or []),
        models=models,
    )
    rerank_checks, rerank_issues = _expected_model_checks(
        kind="rerank",
        expected=list(expected_rerank_models or []),
        models=models,
    )
    issues = [*embedding_issues, *rerank_issues]
    if endpoint_entries and not any(entry["status"] == "available" for entry in endpoint_entries):
        issues.append(
            {
                "severity": "error",
                "code": "model_provider_endpoint_unavailable",
                "message": "no probed model-provider endpoint returned a recognizable provider list",
                "recommendation": "Check RAGFlow base URL, API key, version, and provider API path compatibility.",
            }
        )
    adapter_probes = [
        _probe_adapter_empty_input(
            kind="embedding",
            url=embedding_adapter_url,
            api_key=embedding_adapter_api_key,
            shape=embedding_adapter_shape,
            model=next((model for model in expected_embedding_models or [] if str(model).strip()), None),
            timeout=adapter_timeout,
        ),
        _probe_adapter_empty_input(
            kind="rerank",
            url=rerank_adapter_url,
            api_key=rerank_adapter_api_key,
            shape=rerank_adapter_shape,
            model=next((model for model in expected_rerank_models or [] if str(model).strip()), None),
            timeout=adapter_timeout,
        ),
    ]
    adapter_status_counts = {status: 0 for status in ADAPTER_PROBE_STATUSES}
    for probe in adapter_probes:
        status = str(probe.get("status"))
        adapter_status_counts[status] = adapter_status_counts.get(status, 0) + 1
        if status in {"wrong_protocol", "timeout", "error"}:
            issues.append(
                {
                    "severity": "error",
                    "code": f"{probe.get('kind')}_adapter_empty_input_{status}",
                    "message": f"{probe.get('kind')} adapter empty-input probe failed: {probe.get('reason')}",
                    "recommendation": "Check adapter URL, request-shape setting, timeout, and service health.",
                }
            )
        elif status in {"missing", "unauthorized"}:
            issues.append(
                {
                    "severity": "warning",
                    "code": f"{probe.get('kind')}_adapter_empty_input_{status}",
                    "message": f"{probe.get('kind')} adapter empty-input probe could not complete: {probe.get('reason')}",
                    "recommendation": "Confirm the explicit adapter URL and credentials before using the adapter.",
                }
            )
    status_counts = {status: 0 for status in MODEL_PROVIDER_PROBE_STATUSES}
    for entry in endpoint_entries:
        status = str(entry.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    configured_adapter_count = sum(1 for probe in adapter_probes if probe.get("status") != "not_configured")
    return {
        "schema": MODEL_PROVIDER_PROBE_REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": error_count == 0,
        "summary": {
            "endpoint_count": len(endpoint_entries),
            "available_endpoint_count": status_counts.get("available", 0),
            "provider_count": len(providers),
            "model_count": len(models),
            "embedding_model_count": len(embedding_models),
            "rerank_model_count": len(rerank_models),
            "configured_adapter_count": configured_adapter_count,
            "handled_empty_input_adapter_count": adapter_status_counts.get("handled_empty_input", 0),
            "warning_count": warning_count,
            "error_count": error_count,
        },
        "allowed_statuses": list(MODEL_PROVIDER_PROBE_STATUSES),
        "adapter_allowed_statuses": list(ADAPTER_PROBE_STATUSES),
        "status_counts": status_counts,
        "adapter_status_counts": adapter_status_counts,
        "expected_models": {
            "embedding": list(expected_embedding_models or []),
            "rerank": list(expected_rerank_models or []),
        },
        "expected_model_checks": [*embedding_checks, *rerank_checks],
        "endpoints": endpoint_entries,
        "adapter_probes": adapter_probes,
        "providers": providers,
        "issues": issues,
    }


def render_model_provider_probe_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown model-provider probe report."""

    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# RAGFlow Model Provider Probe",
        "",
        f"- schema: `{report.get('schema', MODEL_PROVIDER_PROBE_REPORT_SCHEMA)}`",
        f"- ok: `{str(report.get('ok', False)).lower()}`",
        f"- available endpoints: `{summary.get('available_endpoint_count', 0)}`",
        f"- providers: `{summary.get('provider_count', 0)}`",
        f"- models: `{summary.get('model_count', 0)}`",
        f"- embedding models: `{summary.get('embedding_model_count', 0)}`",
        f"- rerank models: `{summary.get('rerank_model_count', 0)}`",
        f"- configured adapters: `{summary.get('configured_adapter_count', 0)}`",
        f"- handled empty-input adapters: `{summary.get('handled_empty_input_adapter_count', 0)}`",
        "",
        "| endpoint | status | providers | models |",
        "| --- | --- | ---: | ---: |",
    ]
    for entry in report.get("endpoints", []) if isinstance(report.get("endpoints"), list) else []:
        if not isinstance(entry, Mapping):
            continue
        lines.append(
            f"| `{entry.get('path', '')}` | `{entry.get('status', '')}` | "
            f"{entry.get('provider_count', 0)} | {entry.get('model_count', 0)} |"
        )
    providers = report.get("providers", []) if isinstance(report.get("providers"), list) else []
    if providers:
        lines.extend(["", "| provider | capabilities | models |", "| --- | --- | ---: |"])
        for provider in providers:
            if not isinstance(provider, Mapping):
                continue
            capabilities = ", ".join(str(item) for item in provider.get("capabilities", [])).replace("|", "\\|")
            lines.append(
                f"| `{provider.get('display_name', provider.get('id', ''))}` | "
                f"{capabilities or '-'} | {provider.get('model_count', 0)} |"
            )
    adapter_probes = report.get("adapter_probes", []) if isinstance(report.get("adapter_probes"), list) else []
    if adapter_probes:
        lines.extend(["", "| adapter | status | shape | reason |", "| --- | --- | --- | --- |"])
        for probe in adapter_probes:
            if not isinstance(probe, Mapping):
                continue
            shape = probe.get("request_shape") if isinstance(probe.get("request_shape"), Mapping) else {}
            reason = str(probe.get("reason", "")).replace("|", "\\|")
            lines.append(
                f"| `{probe.get('kind', '')}` | `{probe.get('status', '')}` | "
                f"`{shape.get('shape', '')}` | {reason} |"
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
