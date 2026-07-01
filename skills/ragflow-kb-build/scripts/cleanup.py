#!/usr/bin/env python3
"""Preview or explicitly execute cleanup for disposable RAGFlow KBs."""

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

from ragflow_skill_runtime import BuildError, RAGFlowClient, load_config, load_kb_manifest  # noqa: E402
from ragflow_skill_runtime.config import ConfigError  # noqa: E402
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


def _target(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.kb_manifest:
        manifest = load_kb_manifest(args.kb_manifest)
        return args.dataset_id or manifest.dataset.id, args.kb_name or manifest.dataset.name
    if not args.dataset_id:
        raise BuildError("provide --kb-manifest or --dataset-id")
    return args.dataset_id, args.kb_name


def _plan_payload(*, dataset_id: str, dataset_name: str | None, execute: bool) -> dict[str, Any]:
    return {
        "version": "0.1",
        "schema": "ragflow_cleanup_plan_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "execute": execute,
        "dry_run": not execute,
        "action": "delete_dataset",
        "target": {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
        },
        "required_confirmation": {
            "confirm_dataset_id": dataset_id,
            "confirm_kb_name": dataset_name,
        },
    }


def _write_output(path: str | None, payload: Mapping[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_confirmation(args: argparse.Namespace, *, dataset_id: str, dataset_name: str | None) -> None:
    if args.confirm_dataset_id != dataset_id:
        raise BuildError("cleanup --execute requires --confirm-dataset-id matching the target dataset id")
    if dataset_name and args.confirm_kb_name != dataset_name:
        raise BuildError("cleanup --execute requires --confirm-kb-name matching the target KB name")


def _validate_delete_response(response: Any) -> None:
    if not isinstance(response, Mapping) or "code" not in response:
        return
    if response.get("code") == 0:
        return
    message = response.get("message") or response.get("msg") or response
    raise BuildError(f"cleanup delete failed: {message}")


def _run(args: argparse.Namespace) -> int:
    try:
        dataset_id, dataset_name = _target(args)
        payload = _plan_payload(dataset_id=dataset_id, dataset_name=dataset_name, execute=args.execute)
        if not args.execute:
            if args.redaction_report:
                payload, redaction_report = sanitize_cli_report(
                    payload,
                    args,
                    input_paths=[args.kb_manifest, args.config],
                    output_paths=[args.output, args.redaction_report],
                    context_json_paths=[args.kb_manifest],
                )
                _write_output(args.redaction_report, redaction_report)
            _write_output(args.output, payload)
            _dump_json(payload)
            return 0

        _validate_confirmation(args, dataset_id=dataset_id, dataset_name=dataset_name)
        config = _load_config(args)
        client = RAGFlowClient(config)
        delete_response = client.delete_dataset(dataset_id)
        _validate_delete_response(delete_response)
        payload = {
            **payload,
            "dry_run": False,
            "delete_response": delete_response,
        }
        if args.redaction_report:
            payload, redaction_report = sanitize_cli_report(
                payload,
                args,
                input_paths=[args.kb_manifest, args.config],
                output_paths=[args.output, args.redaction_report],
                context_json_paths=[args.kb_manifest],
                config=config,
            )
            _write_output(args.redaction_report, redaction_report)
        _write_output(args.output, payload)
        _dump_json(payload)
        return 0
    except (BuildError, ConfigError, ManifestError, OSError, RuntimeError) as exc:
        return _error(str(exc), json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview or execute cleanup for a disposable RAGFlow KB")
    parser.add_argument("--kb-manifest", help="kb_manifest.json for the disposable KB")
    parser.add_argument("--dataset-id", help="Target dataset ID; overrides kb_manifest when provided")
    parser.add_argument("--kb-name", help="Target KB name; overrides kb_manifest when provided")
    parser.add_argument("--output", help="Optional cleanup plan or execution report path")
    parser.add_argument("--redaction-report", help="Optional redaction sidecar for cleanup plan or execution reports")
    parser.add_argument("--execute", action="store_true", help="Actually delete the target dataset")
    parser.add_argument("--confirm-dataset-id", help="Required with --execute; must exactly match the target dataset ID")
    parser.add_argument("--confirm-kb-name", help="Required with --execute when a target KB name is known")
    parser.add_argument("--config", help="Runtime config file")
    parser.add_argument("--base-url", help="RAGFlow base URL")
    parser.add_argument("--api-key", help="RAGFlow API key")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
