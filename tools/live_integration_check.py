#!/usr/bin/env python3
"""Opt-in live RAGFlow integration check."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists():
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import RAGFlowClient, load_config, normalize_retrieval_response  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402


DEFAULT_QUESTION = "Summarize this knowledge base."


def _pick(args: argparse.Namespace | None, env: Mapping[str, str], field: str, env_name: str) -> str | None:
    value = getattr(args, field, None) if args else None
    return value or env.get(env_name)


def run_live_check(
    *,
    args: argparse.Namespace | None = None,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[Any], Any] = RAGFlowClient,
) -> dict[str, Any]:
    env_map = os.environ if env is None else env
    base_url = _pick(args, env_map, "base_url", "RAGFLOW_BASE_URL")
    api_key = _pick(args, env_map, "api_key", "RAGFLOW_API_KEY")
    dataset_id = _pick(args, env_map, "dataset_id", "RAGFLOW_DATASET_ID")
    question = _pick(args, env_map, "question", "RAGFLOW_LIVE_QUERY") or DEFAULT_QUESTION
    try:
        top_k = int(getattr(args, "top_k", None) or env_map.get("RAGFLOW_LIVE_TOP_K", "3"))
    except ValueError:
        return {
            "ok": False,
            "skipped": False,
            "error": "top_k must be an integer",
        }
    required = {
        "RAGFLOW_BASE_URL": base_url,
        "RAGFLOW_API_KEY": api_key,
        "RAGFLOW_DATASET_ID": dataset_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return {
            "ok": True,
            "skipped": True,
            "missing": missing,
            "message": "live integration check skipped; provide all required environment variables",
        }

    try:
        config = load_config(
            env={},
            overrides={
                "base_url": base_url,
                "api_key": api_key,
            },
        )
        client = client_factory(config)
        raw = client.retrieve(question=question, dataset_ids=[dataset_id], top_k=top_k)
        chunks = normalize_retrieval_response(raw)
        return {
            "ok": bool(chunks),
            "skipped": False,
            "base_url": config.base_url,
            "dataset_id": dataset_id,
            "question": question,
            "top_k": top_k,
            "chunk_count": len(chunks),
            "top_chunks": [chunk.to_dict() for chunk in chunks[:3]],
            "error": None if chunks else "live retrieval returned no chunks",
        }
    except (ConfigError, OSError, RuntimeError) as exc:
        return {
            "ok": False,
            "skipped": False,
            "error": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an opt-in live RAGFlow retrieval check")
    parser.add_argument("--base-url", help="RAGFlow base URL; defaults to RAGFLOW_BASE_URL")
    parser.add_argument("--api-key", help="RAGFlow API key; defaults to RAGFLOW_API_KEY")
    parser.add_argument("--dataset-id", help="RAGFlow dataset ID; defaults to RAGFLOW_DATASET_ID")
    parser.add_argument("--question", help="Live retrieval question; defaults to RAGFLOW_LIVE_QUERY")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args(argv)

    payload = run_live_check(args=args)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
