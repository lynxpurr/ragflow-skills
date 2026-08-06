"""Shared warning thresholds for runtime and parse performance reports."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


SLOW_PARSE_PHASE_MS = 60_000.0
SLOW_VISUAL_VLM_PHASE_MS = 30_000.0
HIGH_TOTAL_CHUNK_COUNT = 10_000
HIGH_DOCUMENT_CHUNK_COUNT = 1_000
POLLING_NEAR_TIMEOUT_RATIO = 0.8

PARSE_PHASES = {"parse", "parser", "chunk", "embedding", "embed"}
VISUAL_VLM_PHASES = {"image", "vision", "ocr", "layout", "table"}


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def performance_warning_thresholds() -> dict[str, Any]:
    return {
        "slow_parse_phase_ms": SLOW_PARSE_PHASE_MS,
        "slow_visual_vlm_phase_ms": SLOW_VISUAL_VLM_PHASE_MS,
        "high_total_chunk_count": HIGH_TOTAL_CHUNK_COUNT,
        "high_document_chunk_count": HIGH_DOCUMENT_CHUNK_COUNT,
        "polling_near_timeout_ratio": POLLING_NEAR_TIMEOUT_RATIO,
    }


def performance_warning(
    *,
    code: str,
    message: str,
    observed: Mapping[str, Any],
    threshold: Mapping[str, Any],
    recommendation: str,
    stage: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    warning: dict[str, Any] = {
        "severity": "warning",
        "code": code,
        "message": message,
        "observed": dict(observed),
        "threshold": dict(threshold),
        "recommendation": recommendation,
    }
    if stage:
        warning["stage"] = stage
    if document_id:
        warning["document_id"] = document_id
    return warning


def performance_warning_report(warnings: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    warning_items = [dict(warning) for warning in warnings]
    return {
        "thresholds": performance_warning_thresholds(),
        "summary": {
            "status": "review" if warning_items else "pass",
            "warning_count": len(warning_items),
        },
        "warnings": warning_items,
    }


def phase_timing_performance_warnings(phase_timings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in phase_timings:
        phase = str(item.get("phase") or "").strip().lower()
        total_ms = _as_float(item.get("total_ms"))
        if not phase or total_ms is None:
            continue
        if phase in VISUAL_VLM_PHASES and total_ms >= SLOW_VISUAL_VLM_PHASE_MS:
            warnings.append(
                performance_warning(
                    code="slow_image_vlm_processing",
                    stage=phase,
                    observed={"phase": phase, "duration_ms": round(total_ms, 3)},
                    threshold={"duration_ms": SLOW_VISUAL_VLM_PHASE_MS},
                    message=f"{phase} processing took {round(total_ms, 3)} ms.",
                    recommendation="Review visual parsing, OCR, VLM, and image asset policy before scaling this profile.",
                )
            )
        elif phase in PARSE_PHASES and total_ms >= SLOW_PARSE_PHASE_MS:
            warnings.append(
                performance_warning(
                    code="slow_parse_phase",
                    stage=phase,
                    observed={"phase": phase, "duration_ms": round(total_ms, 3)},
                    threshold={"duration_ms": SLOW_PARSE_PHASE_MS},
                    message=f"{phase} processing took {round(total_ms, 3)} ms.",
                    recommendation="Review parser profile, source size, chunking, and enrichment settings before scaling.",
                )
            )
    return warnings


def chunk_count_performance_warnings(
    *,
    total_chunk_count: Any,
    documents: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    total = _as_int(total_chunk_count)
    if total is not None and total >= HIGH_TOTAL_CHUNK_COUNT:
        warnings.append(
            performance_warning(
                code="high_total_chunk_count",
                stage="chunk_count",
                observed={"chunk_count": total},
                threshold={"chunk_count": HIGH_TOTAL_CHUNK_COUNT},
                message=f"Total observed chunk count is high: {total}.",
                recommendation="Review segmentation, chunk profile, and retrieval cost before broad validation.",
            )
        )
    for document in documents:
        chunks = _as_int(
            document.get("effective_chunk_count")
            if "effective_chunk_count" in document
            else document.get("chunk_count")
        )
        if chunks is None or chunks < HIGH_DOCUMENT_CHUNK_COUNT:
            continue
        document_id = str(document.get("document_id") or "").strip() or None
        warnings.append(
            performance_warning(
                code="high_document_chunk_count",
                stage="chunk_count",
                document_id=document_id,
                observed={"chunk_count": chunks},
                threshold={"chunk_count": HIGH_DOCUMENT_CHUNK_COUNT},
                message=f"Document chunk count is high: {chunks}.",
                recommendation="Review source segmentation and chunk profile before relying on this KB at scale.",
            )
        )
    return warnings


def stage_duration_performance_warnings(
    *,
    stage: str,
    duration_ms: Any,
    item_count: Any = None,
    visual_or_vlm: bool = False,
) -> list[dict[str, Any]]:
    duration = _as_float(duration_ms)
    if duration is None:
        return []
    threshold = SLOW_VISUAL_VLM_PHASE_MS if visual_or_vlm else SLOW_PARSE_PHASE_MS
    if duration < threshold:
        return []
    code = "slow_image_vlm_processing" if visual_or_vlm else "slow_parse_phase"
    observed: dict[str, Any] = {"duration_ms": round(duration, 3)}
    count = _as_int(item_count)
    if count is not None:
        observed["item_count"] = count
    return [
        performance_warning(
            code=code,
            stage=stage,
            observed=observed,
            threshold={"duration_ms": threshold},
            message=f"{stage} took {round(duration, 3)} ms.",
            recommendation="Review parser profile, asset policy, and parse wait behavior before scaling.",
        )
    ]


def polling_performance_warnings(
    *,
    timeout_seconds: Any,
    elapsed_ms: Any,
    poll_count: Any,
    pending_count: Any = 0,
    wait_performed: bool = True,
) -> list[dict[str, Any]]:
    if not wait_performed:
        return []
    timeout = _as_float(timeout_seconds)
    elapsed = _as_float(elapsed_ms)
    polls = _as_int(poll_count) or 0
    pending = _as_int(pending_count) or 0
    near_timeout = False
    ratio: float | None = None
    if timeout is not None and timeout <= 0 and pending > 0:
        near_timeout = True
    elif timeout and timeout > 0 and elapsed is not None:
        ratio = elapsed / (timeout * 1000.0)
        near_timeout = ratio >= POLLING_NEAR_TIMEOUT_RATIO
    if not near_timeout:
        return []
    observed: dict[str, Any] = {
        "timeout_seconds": timeout,
        "elapsed_ms": round(elapsed, 3) if elapsed is not None else None,
        "poll_count": polls,
        "pending_count": pending,
    }
    if ratio is not None:
        observed["timeout_ratio"] = round(ratio, 3)
    return [
        performance_warning(
            code="polling_near_timeout",
            stage="parse_wait",
            observed=observed,
            threshold={
                "timeout_seconds": timeout,
                "near_timeout_ratio": POLLING_NEAR_TIMEOUT_RATIO,
            },
            message="Parse polling reached or approached the configured timeout.",
            recommendation="Increase timeout, inspect parse progress, or reduce batch/asset size before retrying.",
        )
    ]
