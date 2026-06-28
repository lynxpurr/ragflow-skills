#!/usr/bin/env python3
"""Append Markdown documents to an existing RAGFlow KB safely."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import sys
from typing import Any, Mapping


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
    BuildDocument,
    BuildError,
    RAGFlowClient,
    discover_markdown_documents,
    extract_document_id,
    extract_document_items,
    extract_document_name,
    load_config,
    load_doc_manifest,
    load_kb_manifest,
    wait_for_document_states,
)
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
from ragflow_skill_runtime.kb_build import extract_uploaded_document_id  # noqa: E402
from ragflow_skill_runtime.manifests import ManifestError  # noqa: E402
from _report_redaction import sanitize_cli_report  # noqa: E402


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
            "--allow-blocked to append anyway"
        )


def _snapshot_documents(response: Any) -> dict[str, Any]:
    items = extract_document_items(response)
    documents = []
    for item in items:
        document_id = extract_document_id(item)
        name = extract_document_name(item)
        documents.append(
            {
                "document_id": document_id,
                "name": name,
                "status": item.get("status") or item.get("run") or item.get("progress"),
                "chunk_count": item.get("chunk_count"),
            }
        )
    return {
        "document_count": len(documents),
        "document_ids": [document["document_id"] for document in documents if document["document_id"]],
        "document_names": [document["name"] for document in documents if document["name"]],
        "documents": documents,
    }


def _planned_documents(
    docs: list[BuildDocument],
    *,
    existing_names: set[str],
    allow_duplicates: bool,
) -> list[dict[str, Any]]:
    planned = []
    for doc in docs:
        name = doc.path.name
        duplicate = name in existing_names
        action = "upload"
        reason = ""
        if duplicate and not allow_duplicates:
            action = "skip_existing_name"
            reason = "existing RAGFlow document has the same filename"
        planned.append(
            {
                "markdown_path": str(doc.path),
                "source_path": doc.manifest_source_path,
                "name": name,
                "action": action,
                "duplicate_by_name": duplicate,
                "reason": reason,
            }
        )
    return planned


def _plan_payload(
    *,
    dataset_id: str,
    dataset_name: str,
    docs: list[BuildDocument],
    before_snapshot: dict[str, Any] | None,
    allow_duplicates: bool,
    execute: bool,
) -> dict[str, Any]:
    existing_names = set(before_snapshot.get("document_names", []) if before_snapshot else [])
    planned = _planned_documents(docs, existing_names=existing_names, allow_duplicates=allow_duplicates)
    return {
        "version": "0.1",
        "schema": "ragflow_append_plan_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "execute": execute,
        "dry_run": not execute,
        "dataset": {"id": dataset_id, "name": dataset_name},
        "input_count": len(docs),
        "planned_upload_count": sum(1 for item in planned if item["action"] == "upload"),
        "planned_skip_count": sum(1 for item in planned if item["action"] != "upload"),
        "before_snapshot": before_snapshot,
        "documents": planned,
    }


def _write_output(path: str | None, payload: Mapping[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    try:
        kb_manifest = load_kb_manifest(args.kb_manifest)
        doc_manifest = load_doc_manifest(args.doc_manifest) if args.doc_manifest else None
        _guard_quality_gate(doc_manifest, allow_blocked=args.allow_blocked)
        docs = discover_markdown_documents(
            input_path=args.input,
            doc_manifest=doc_manifest,
            manifest_base_path=args.doc_manifest,
        )
        dataset_id = args.dataset_id or kb_manifest.dataset.id
        dataset_name = args.kb_name or kb_manifest.dataset.name

        client = None
        before_snapshot = None
        if args.live_preview or args.execute:
            config = _load_config(args)
            client = RAGFlowClient(config)
            before_snapshot = _snapshot_documents(client.list_documents(dataset_id, page=1, page_size=args.page_size))

        plan = _plan_payload(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            docs=docs,
            before_snapshot=before_snapshot,
            allow_duplicates=args.allow_duplicates,
            execute=args.execute,
        )

        if not args.execute:
            if args.redaction_report:
                plan, redaction_report = sanitize_cli_report(
                    plan,
                    args,
                    input_paths=[args.kb_manifest, args.input, args.doc_manifest, args.config],
                    output_paths=[args.output, args.redaction_report],
                    context_json_paths=[args.kb_manifest, args.doc_manifest],
                )
                _write_output(args.redaction_report, redaction_report)
            _write_output(args.output, plan)
            _dump_json(plan)
            return 0

        if client is None:
            raise BuildError("internal error: execute mode requires a RAGFlow client")

        uploaded = []
        document_ids: list[str] = []
        upload_actions = [item for item in plan["documents"] if item["action"] == "upload"]
        docs_by_path = {str(doc.path): doc for doc in docs}
        for item in upload_actions:
            doc = docs_by_path[item["markdown_path"]]
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

        after_snapshot = _snapshot_documents(client.list_documents(dataset_id, page=1, page_size=args.page_size))
        append_manifest = {
            "version": "0.1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ragflow_base_url": client.config.base_url,
            "dataset": {"id": dataset_id, "name": dataset_name},
            "profile": dict(kb_manifest.profile),
            "documents": [
                {
                    "document_id": document_id,
                    "source_path": doc.manifest_source_path,
                    "markdown_path": str(doc.path),
                    "status": status,
                    "chunk_count": chunk_count,
                }
                for doc, document_id, status, chunk_count in uploaded
            ],
        }
        payload = {
            **plan,
            "dry_run": False,
            "uploaded_count": len(uploaded),
            "uploaded_document_ids": document_ids,
            "parse_triggered": bool(document_ids) and not args.no_parse,
            "parse_waited": bool(document_ids) and not args.no_parse and not args.no_wait,
            "parse_response": parse_response,
            "after_snapshot": after_snapshot,
            "new_document_ids": [
                document_id
                for document_id in after_snapshot.get("document_ids", [])
                if document_id not in set(before_snapshot.get("document_ids", []) if before_snapshot else [])
            ],
            "append_manifest": append_manifest,
        }
        if args.redaction_report:
            payload, redaction_report = sanitize_cli_report(
                payload,
                args,
                input_paths=[args.kb_manifest, args.input, args.doc_manifest, args.config],
                output_paths=[args.output, args.redaction_report],
                context_json_paths=[args.kb_manifest, args.doc_manifest],
                config=client.config,
            )
            _write_output(args.redaction_report, redaction_report)
        _write_output(args.output, payload)
        _dump_json(payload)
        return 0
    except (BuildError, ConfigError, ManifestError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append Markdown documents to an existing RAGFlow KB")
    parser.add_argument("--kb-manifest", required=True, help="Existing kb_manifest.json for target KB")
    parser.add_argument("--input", help="Markdown file or directory to append")
    parser.add_argument("--doc-manifest", help="Document handoff manifest to append")
    parser.add_argument("--dataset-id", help="Override target dataset ID from kb_manifest")
    parser.add_argument("--kb-name", help="Override target dataset name from kb_manifest")
    parser.add_argument("--output", help="Optional append plan or execution report path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for append plan or execution reports")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--live-preview", action="store_true", help="Read live document list before planning")
    parser.add_argument("--execute", action="store_true", help="Actually upload planned documents")
    parser.add_argument("--allow-duplicates", action="store_true", help="Upload documents even when live preview finds matching filenames")
    parser.add_argument("--allow-blocked", action="store_true", help="Allow append when doc_manifest quality_gate.status is BLOCKED")
    parser.add_argument("--no-parse", action="store_true", help="Upload documents without triggering parse")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for parse completion after triggering parse")
    parser.add_argument("--parse-timeout", type=float, default=300.0, help="Maximum seconds to wait for parse completion")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds while waiting for parse completion")
    parser.add_argument("--page-size", type=int, default=200, help="Live document list page size")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
