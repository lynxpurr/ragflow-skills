#!/usr/bin/env python3
"""Inspect a RAGFlow KB manifest and optional live document status."""

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
    extract_document_states,
    load_config,
    load_kb_manifest,
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
        payload: dict[str, Any] = {
            "ok": True,
            "dataset": {"id": manifest.dataset.id, "name": manifest.dataset.name},
            "document_count": len(manifest.documents),
            "documents": [
                {
                    "document_id": doc.document_id,
                    "source_path": doc.source_path,
                    "markdown_path": doc.markdown_path,
                    "status": doc.status,
                    "chunk_count": doc.chunk_count,
                }
                for doc in manifest.documents
            ],
        }
        if args.live:
            config = _load_config(args)
            client = RAGFlowClient(config)
            live = client.list_documents(manifest.dataset.id)
            payload["live_documents"] = list(
                extract_document_states(
                    live,
                    document_ids=[doc.document_id for doc in manifest.documents],
                ).values()
            )
        _dump_json(payload)
        return 0
    except (ConfigError, ManifestError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a RAGFlow KB manifest")
    parser.add_argument("--kb-manifest", required=True)
    parser.add_argument("--live", action="store_true", help="Query live RAGFlow document status")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
