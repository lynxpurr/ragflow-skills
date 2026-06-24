#!/usr/bin/env python3
"""Build a RAGFlow knowledge base from Markdown inputs."""

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
    BuildError,
    HandoffError,
    RAGFlowClient,
    discover_markdown_documents,
    inspect_rich_handoff,
    load_config,
    load_doc_manifest,
    load_profile,
    make_kb_manifest_payload,
    render_handoff_inspection_markdown,
    wait_for_document_states,
)
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.kb_build import extract_dataset_id, extract_uploaded_document_id  # noqa: E402
from ragflow_skill_runtime.profiles import ProfileError  # noqa: E402


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _load_config(args: argparse.Namespace):
    overrides = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    return load_config(config_file=args.config, overrides=overrides)


def _guard_quality_gate(doc_manifest, *, allow_blocked: bool) -> None:
    if not doc_manifest or allow_blocked:
        return
    gate = getattr(doc_manifest, "quality_gate", {}) or {}
    status = gate.get("status") if isinstance(gate, dict) else None
    if status == "BLOCKED":
        raise BuildError(
            "doc_manifest quality gate is BLOCKED; inspect the quality report or pass "
            "--allow-blocked to upload anyway"
        )


def _run(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        if args.dry_run:
            _dump_json(
                {
                    "ok": True,
                    "dry_run": True,
                    "kb_name": args.kb_name,
                    "profile": profile.to_manifest_dict(),
                    "documents": [str(doc.path) for doc in docs],
                }
            )
            return 0

        config = _load_config(args)
        client = RAGFlowClient(config)
        dataset_response = client.create_dataset(args.kb_name, profile=profile.to_dataset_payload())
        dataset_id = extract_dataset_id(dataset_response)

        uploaded = []
        document_ids: list[str] = []
        for doc in docs:
            response = client.upload_document(dataset_id, doc.path)
            document_id = extract_uploaded_document_id(response)
            document_ids.append(document_id)
            uploaded.append((doc, document_id, "uploaded", None))

        parse_response = None
        live_states = {}
        if document_ids and not args.no_parse:
            parse_response = client.trigger_parse(dataset_id, document_ids)
            if not args.no_wait:
                live_states = wait_for_document_states(
                    client,
                    dataset_id=dataset_id,
                    document_ids=document_ids,
                    timeout=args.parse_timeout,
                    poll_interval=args.poll_interval,
                )
                uploaded = [
                    (
                        doc,
                        document_id,
                        live_states.get(document_id, {}).get("status", status),
                        live_states.get(document_id, {}).get("chunk_count", chunk_count),
                    )
                    for doc, document_id, status, chunk_count in uploaded
                ]

        payload = make_kb_manifest_payload(
            base_url=config.base_url,
            dataset_id=dataset_id,
            dataset_name=args.kb_name,
            profile=profile,
            documents=uploaded,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": True,
                "kb_manifest": str(output),
                "dataset_id": dataset_id,
                "document_count": len(uploaded),
                "parse_triggered": not args.no_parse,
                "parse_waited": not args.no_parse and not args.no_wait,
                "parse_response": parse_response,
            }
        )
        return 0
    except (BuildError, ConfigError, ProfileError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect_handoff(args: argparse.Namespace) -> int:
    try:
        report = inspect_rich_handoff(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
        )
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_handoff_inspection_markdown(report), encoding="utf-8")
        _dump_json({"ok": True, "handoff": report})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def build_inspect_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a Markdown handoff and optional rich sidecars")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--report-json", help="Optional JSON inspection report path")
    parser.add_argument("--report-md", help="Optional Markdown inspection report path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a RAGFlow KB from Markdown")
    parser.add_argument("--input", help="Markdown file or directory")
    parser.add_argument("--doc-manifest", help="Path to doc_manifest.json")
    parser.add_argument("--kb-name", required=True, help="RAGFlow dataset name")
    parser.add_argument("--profile", required=True, help="Chunk profile JSON/YAML")
    parser.add_argument("--output", default="kb_manifest.json", help="Output kb_manifest.json path for non-dry-run builds")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without touching RAGFlow or writing kb_manifest.json")
    parser.add_argument("--no-parse", action="store_true", help="Upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for parse completion after triggering parse")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow upload when doc_manifest quality_gate.status is BLOCKED")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds while waiting for parse completion")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect-handoff":
            return _run_inspect_handoff(build_inspect_handoff_parser().parse_args(command_args))
    args = build_parser().parse_args(actual_argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
