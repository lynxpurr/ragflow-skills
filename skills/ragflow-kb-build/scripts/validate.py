#!/usr/bin/env python3
"""Validate a RAGFlow KB manifest."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys
from typing import Any


def bootstrap_runtime() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_runtime()

from ragflow_skill_runtime import (  # noqa: E402
    RAGFlowClient,
    load_config,
    load_kb_manifest,
    normalize_retrieval_response,
)
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.manifests import ManifestError  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _run(args: argparse.Namespace) -> int:
    try:
        manifest = load_kb_manifest(args.kb_manifest)
        if args.level != "smoke":
            _dump_json(
                {
                    "ok": False,
                    "error": f"{args.level} validation is not implemented in this MVP",
                    "implemented_levels": ["smoke"],
                }
            )
            return 2

        config = _load_config(args)
        client = RAGFlowClient(config)
        query = args.query or f"Summarize {manifest.dataset.name}"
        raw = client.retrieve(question=query, dataset_ids=[manifest.dataset.id], top_k=args.top_k)
        chunks = normalize_retrieval_response(raw)
        ok = len(chunks) > 0
        _dump_json(
            {
                "ok": ok,
                "level": args.level,
                "dataset": {"id": manifest.dataset.id, "name": manifest.dataset.name},
                "query": query,
                "chunk_count": len(chunks),
                "top_chunks": [chunk.to_dict() for chunk in chunks[: min(3, len(chunks))]],
            }
        )
        return 0 if ok else 1
    except (ConfigError, ManifestError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a RAGFlow KB")
    parser.add_argument("--kb-manifest", required=True)
    parser.add_argument("--level", choices=["smoke", "regression", "benchmark"], default="smoke")
    parser.add_argument("--query", help="Smoke-test query")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
