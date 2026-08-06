"""Small read-only cache helpers for public skill reports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any


RUNTIME_CACHE_REPORT_SCHEMA = "ragflow_runtime_cache_report_v1"
CACHE_KEY_ALGORITHM = "sha256"


def _rounded(value: float | int) -> float:
    return round(float(value), 3)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def runtime_cache_secret_digest(value: str | None) -> str | None:
    """Return a deterministic secret fingerprint for cache identity only."""

    if not value:
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_ALGORITHM}:{digest}"


def runtime_cache_digest(operation: str, key_parts: Mapping[str, Any]) -> str:
    """Build a stable digest without exposing raw cache key material."""

    material = {
        "operation": str(operation),
        "parts": _jsonable(key_parts),
    }
    digest = hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_ALGORITHM}:{digest}"


@dataclass(frozen=True)
class RuntimeCacheLookup:
    cache_key: str
    status: str
    value: Any = None
    age_seconds: float | None = None

    def to_report(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cache_key": self.cache_key,
            "age_seconds": _rounded(self.age_seconds) if self.age_seconds is not None else None,
        }


@dataclass(frozen=True)
class RuntimeCacheStoreResult:
    cache_key: str
    status: str


@dataclass
class RuntimeCache:
    """Tiny file-backed cache for read-only probes and list operations."""

    operation: str
    cache_dir: str | Path | None = None
    ttl_seconds: float = 300.0
    namespace: str = "default"
    clock: Callable[[], float] = time.time
    counters: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            return
        try:
            ttl = float(self.ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("cache ttl seconds must be a number") from exc
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("cache ttl seconds must be finite and greater than zero")
        self.ttl_seconds = ttl
        namespace = str(self.namespace or "default").strip()
        namespace = "".join(char if char.isalnum() or char in "._-" else "_" for char in namespace)
        self.namespace = namespace or "default"

    @property
    def enabled(self) -> bool:
        return self.cache_dir is not None

    def _increment(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(value)

    def _path_for_key(self, cache_key: str) -> Path:
        assert self.cache_dir is not None
        digest = cache_key.replace(":", "-")
        return Path(self.cache_dir) / self.namespace / f"{digest}.json"

    def get(self, key_parts: Mapping[str, Any]) -> RuntimeCacheLookup:
        cache_key = runtime_cache_digest(self.operation, key_parts)
        if not self.enabled:
            self._increment("bypass_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="disabled")

        self._increment("lookup_count")
        path = self._path_for_key(cache_key)
        if not path.exists():
            self._increment("miss_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="miss")
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._increment("read_error_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="read_error")
        if not isinstance(entry, Mapping) or entry.get("cache_key") != cache_key:
            self._increment("read_error_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="read_error")
        created_at_epoch = entry.get("created_at_epoch")
        if not isinstance(created_at_epoch, (int, float)) or isinstance(created_at_epoch, bool):
            self._increment("read_error_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="read_error")
        age_seconds = max(0.0, float(self.clock()) - float(created_at_epoch))
        if age_seconds > float(self.ttl_seconds):
            self._increment("stale_count")
            return RuntimeCacheLookup(cache_key=cache_key, status="stale", age_seconds=age_seconds)
        self._increment("hit_count")
        return RuntimeCacheLookup(
            cache_key=cache_key,
            status="hit",
            value=entry.get("value"),
            age_seconds=age_seconds,
        )

    def put(self, cache_key: str, value: Any) -> RuntimeCacheStoreResult:
        if not self.enabled:
            return RuntimeCacheStoreResult(cache_key=cache_key, status="disabled")
        path = self._path_for_key(cache_key)
        entry = {
            "schema": "ragflow_runtime_cache_entry_v1",
            "operation": self.operation,
            "cache_key": cache_key,
            "created_at_epoch": float(self.clock()),
            "ttl_seconds": float(self.ttl_seconds),
            "value": _jsonable(value),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            self._increment("write_error_count")
            return RuntimeCacheStoreResult(cache_key=cache_key, status="write_error")
        self._increment("write_count")
        return RuntimeCacheStoreResult(cache_key=cache_key, status="stored")

    def to_report(self) -> dict[str, Any]:
        counters = {
            "lookup_count": self.counters.get("lookup_count", 0),
            "hit_count": self.counters.get("hit_count", 0),
            "miss_count": self.counters.get("miss_count", 0),
            "stale_count": self.counters.get("stale_count", 0),
            "bypass_count": self.counters.get("bypass_count", 0),
            "read_error_count": self.counters.get("read_error_count", 0),
            "write_count": self.counters.get("write_count", 0),
            "write_error_count": self.counters.get("write_error_count", 0),
        }
        return {
            "schema": RUNTIME_CACHE_REPORT_SCHEMA,
            "operation": self.operation,
            "enabled": self.enabled,
            "namespace": self.namespace,
            "ttl_seconds": _rounded(float(self.ttl_seconds)),
            "cache_key_algorithm": CACHE_KEY_ALGORITHM,
            "summary": dict(counters),
            "counters": dict(counters),
        }
