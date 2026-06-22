#!/usr/bin/env python3
"""Portable RAGFlow query CLI."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys
from typing import Any


def bootstrap_core() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_core()

from ragflow_skill_runtime import (  # noqa: E402
    ConfigError,
    QueryResult,
    RAGFlowClient,
    RetrievalError,
    load_config,
    load_kb_manifest,
    normalize_retrieval_response,
    resolve_dataset_ids,
)


def _json_dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    payload = {"ok": False, "error": message}
    if json_output:
        _json_dump(payload)
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_runtime(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _ask(args: argparse.Namespace) -> int:
    mode = args.mode
    if mode == "auto":
        mode = "direct"

    if mode == "agentic" and not args.host_assisted:
        return _error(
            "agentic mode is not implemented in this MVP; use --host-assisted or --mode direct",
            json_output=args.json,
        )

    try:
        kb_manifest = load_kb_manifest(args.kb_manifest) if args.kb_manifest else None
        config = _load_runtime(args)
        client = RAGFlowClient(config)
        dataset_ids = resolve_dataset_ids(
            client=client,
            dataset_ids=args.dataset_id,
            dataset_names=args.kb,
            kb_manifest=kb_manifest,
        )
        raw = client.retrieve(
            question=args.question,
            dataset_ids=dataset_ids,
            top_k=args.top_k,
            similarity_threshold=args.similarity_threshold,
        )
        chunks = normalize_retrieval_response(raw)
    except (ConfigError, RetrievalError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)

    result = QueryResult(
        question=args.question,
        mode=mode,
        dataset_ids=dataset_ids,
        chunks=chunks,
        answer=None,
        host_assisted=args.host_assisted,
        metadata={
            "requested_mode": args.mode,
            "top_k": args.top_k,
            "chunk_count": len(chunks),
            "synthesis": "host-assisted" if args.host_assisted else "not-requested",
        },
    )
    payload = {"ok": True, **result.to_dict(include_raw=args.include_raw)}
    if args.json or args.host_assisted:
        _json_dump(payload)
    else:
        for idx, chunk in enumerate(chunks, 1):
            doc = chunk.document_name or chunk.document_id or "unknown document"
            sim = f"{chunk.similarity:.4f}" if chunk.similarity is not None else "n/a"
            print(f"[{idx}] {doc} sim={sim}\n{chunk.content}\n")
    return 0


def _add_runtime_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--config", default=default, help="Path to JSON or simple YAML config")
    parser.add_argument("--base-url", default=default, help="RAGFlow base URL; overrides RAGFLOW_BASE_URL")
    parser.add_argument("--api-key", default=default, help="RAGFlow API key; overrides RAGFLOW_API_KEY")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable RAGFlow query CLI")
    _add_runtime_options(parser)

    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Ask a question against RAGFlow")
    _add_runtime_options(ask, suppress_defaults=True)
    ask.add_argument("question", help="Question to retrieve evidence for")
    ask.add_argument("--mode", choices=["auto", "direct", "agentic"], default="auto")
    ask.add_argument("--dataset-id", action="append", default=[], help="RAGFlow dataset ID; repeatable")
    ask.add_argument("--kb", action="append", default=[], help="RAGFlow KB/dataset name; repeatable")
    ask.add_argument("--kb-manifest", help="Path to kb_manifest.json")
    ask.add_argument("--top-k", type=int, default=5)
    ask.add_argument("--similarity-threshold", type=float)
    ask.add_argument("--host-assisted", action="store_true", help="Return evidence for host agent synthesis")
    ask.add_argument("--json", action="store_true", help="Emit JSON")
    ask.add_argument("--include-raw", action="store_true", help="Include raw RAGFlow chunks in JSON")
    ask.set_defaults(func=_ask)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
