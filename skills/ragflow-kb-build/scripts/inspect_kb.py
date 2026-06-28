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
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parents[3] / "packages/ragflow-skill-runtime/src",
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
from _report_redaction import sanitize_cli_report  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _write_json_file(path: str | None, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    try:
        manifest = load_kb_manifest(args.kb_manifest)
        config = None
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
        if args.redaction_report:
            payload, redaction_report = sanitize_cli_report(
                payload,
                args,
                input_paths=[args.kb_manifest, args.config],
                output_paths=[args.redaction_report],
                context_json_paths=[args.kb_manifest, args.config],
                config=config,
            )
            _write_json_file(args.redaction_report, redaction_report)
        _dump_json(payload)
        return 0
    except (ConfigError, ManifestError, OSError, RuntimeError) as exc:
        _dump_json({"ok": False, "error": str(exc)})
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a RAGFlow KB manifest")
    parser.add_argument("--kb-manifest", required=True)
    parser.add_argument("--live", action="store_true", help="Query live RAGFlow document status")
    parser.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
