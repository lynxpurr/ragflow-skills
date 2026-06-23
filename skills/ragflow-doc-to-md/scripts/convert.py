#!/usr/bin/env python3
"""Convert documents into a Markdown handoff bundle."""

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
    ConvertedDocument,
    DocConvertError,
    convert_source_to_markdown,
    discover_source_documents,
    extract_markdown_title,
    make_doc_manifest_payload,
    safe_markdown_name,
    sha256_file,
)


BACKEND_CHOICES = {"auto", "builtin", "mineru", "pandoc", "remote"}


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _remote_api_key(args: argparse.Namespace) -> str | None:
    return args.remote_api_key or os.environ.get("DOC_TO_MD_REMOTE_API_KEY")


def _remote_url(args: argparse.Namespace) -> str | None:
    return args.remote_url or os.environ.get("DOC_TO_MD_REMOTE_URL")


def _backend(args: argparse.Namespace) -> str:
    backend = args.backend or os.environ.get("DOC_TO_MD_BACKEND") or "auto"
    if backend not in BACKEND_CHOICES:
        allowed = ", ".join(sorted(BACKEND_CHOICES))
        raise DocConvertError(f"DOC_TO_MD_BACKEND must be one of: {allowed}")
    return backend


def _remote_timeout(args: argparse.Namespace) -> float:
    value = args.remote_timeout
    if value is None:
        value = os.environ.get("DOC_TO_MD_TIMEOUT")
    if value in (None, ""):
        return 120.0
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be a number of seconds") from exc
    if timeout <= 0:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be greater than zero")
    return timeout


def _env_or_arg(args: argparse.Namespace, field: str, env_name: str, default: str | None = None) -> str | None:
    value = getattr(args, field)
    return value or os.environ.get(env_name) or default


def _float_env_or_arg(
    args: argparse.Namespace,
    field: str,
    env_name: str,
    default: float,
    *,
    label: str,
) -> float:
    value = getattr(args, field)
    if value is None:
        value = os.environ.get(env_name)
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError(f"{label} must be a number of seconds") from exc
    if parsed <= 0:
        raise DocConvertError(f"{label} must be greater than zero")
    return parsed


def _bool_env_or_arg(args: argparse.Namespace, field: str, env_name: str, default: bool) -> bool:
    value = getattr(args, field)
    if value is None:
        value = os.environ.get(env_name)
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise DocConvertError(f"{env_name} must be true or false")


def _run(args: argparse.Namespace) -> int:
    try:
        backend = _backend(args)
        remote_url = _remote_url(args)
        remote_timeout = _remote_timeout(args)
        mineru_timeout = _float_env_or_arg(
            args,
            "mineru_timeout",
            "MINERU_TIMEOUT",
            300.0,
            label="MINERU_TIMEOUT",
        )
        mineru_poll_interval = _float_env_or_arg(
            args,
            "mineru_poll_interval",
            "MINERU_POLL_INTERVAL",
            3.0,
            label="MINERU_POLL_INTERVAL",
        )
        output_root = Path(args.output).expanduser().resolve()
        sources = discover_source_documents(args.input, recursive=not args.no_recursive)
        sources = [
            source
            for source in sources
            if source.path != output_root and output_root not in source.path.parents
        ]
        if not sources:
            raise DocConvertError("no input files found outside the output directory")

        docs_dir = output_root / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        converted: list[ConvertedDocument] = []
        skipped: list[dict[str, str]] = []

        for source in sources:
            output_name = safe_markdown_name(source, used=used_names)
            markdown_path = docs_dir / output_name
            try:
                markdown, warnings = convert_source_to_markdown(
                    source,
                    mode=args.mode,
                    backend=backend,
                    remote_url=remote_url,
                    remote_api_key=_remote_api_key(args),
                    remote_timeout=remote_timeout,
                    mineru_base_url=_env_or_arg(args, "mineru_base_url", "MINERU_BASE_URL"),
                    mineru_api_key=_env_or_arg(args, "mineru_api_key", "MINERU_API_KEY"),
                    mineru_timeout=mineru_timeout,
                    mineru_poll_interval=mineru_poll_interval,
                    mineru_language=_env_or_arg(args, "mineru_language", "MINERU_LANGUAGE", "ch") or "ch",
                    mineru_page_range=_env_or_arg(args, "mineru_page_range", "MINERU_PAGE_RANGE"),
                    mineru_enable_table=_bool_env_or_arg(args, "mineru_enable_table", "MINERU_ENABLE_TABLE", True),
                    mineru_is_ocr=_bool_env_or_arg(args, "mineru_is_ocr", "MINERU_IS_OCR", False),
                    mineru_enable_formula=_bool_env_or_arg(args, "mineru_enable_formula", "MINERU_ENABLE_FORMULA", True),
                )
            except (UnicodeDecodeError, OSError, DocConvertError) as exc:
                if args.strict:
                    raise DocConvertError(str(exc)) from exc
                skipped.append({"source_path": source.source_path, "reason": str(exc)})
                continue

            markdown_path.write_text(markdown, encoding="utf-8")
            converted.append(
                ConvertedDocument(
                    source=source,
                    markdown_path=markdown_path,
                    sha256=sha256_file(source.path),
                    title=extract_markdown_title(markdown),
                    warnings=warnings,
                )
            )

        if not converted:
            raise DocConvertError("no documents were converted")

        manifest = make_doc_manifest_payload(output_root=output_root, documents=converted)
        manifest_path = output_root / args.manifest_name
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": True,
                "doc_manifest": str(manifest_path),
                "document_count": len(converted),
                "skipped": skipped,
            }
        )
        return 0 if not skipped else 1
    except (DocConvertError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert documents into a Markdown handoff bundle")
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--output", required=True, help="Output handoff directory")
    parser.add_argument("--mode", choices=["auto", "passthrough", "convert"], default="auto")
    parser.add_argument("--backend", choices=sorted(BACKEND_CHOICES), help="Conversion backend; defaults to DOC_TO_MD_BACKEND or auto")
    parser.add_argument("--remote-url", help="Remote conversion endpoint; defaults to DOC_TO_MD_REMOTE_URL")
    parser.add_argument("--remote-api-key", help="Remote conversion bearer token; defaults to DOC_TO_MD_REMOTE_API_KEY")
    parser.add_argument("--remote-timeout", type=float, help="Remote conversion timeout in seconds; defaults to DOC_TO_MD_TIMEOUT or 120")
    parser.add_argument("--mineru-base-url", help="MinerU Agent API base URL; defaults to MINERU_BASE_URL or https://mineru.net/api/v1/agent")
    parser.add_argument("--mineru-api-key", help="MinerU API key; defaults to MINERU_API_KEY")
    parser.add_argument("--mineru-timeout", type=float, help="MinerU parse timeout in seconds; defaults to MINERU_TIMEOUT or 300")
    parser.add_argument("--mineru-poll-interval", type=float, help="MinerU parse polling interval; defaults to MINERU_POLL_INTERVAL or 3")
    parser.add_argument("--mineru-language", help="MinerU language option; defaults to MINERU_LANGUAGE or ch")
    parser.add_argument("--mineru-page-range", help="MinerU page range; defaults to MINERU_PAGE_RANGE")
    parser.add_argument("--mineru-enable-table", help="MinerU table parsing true/false; defaults to MINERU_ENABLE_TABLE or true")
    parser.add_argument("--mineru-is-ocr", help="MinerU OCR mode true/false; defaults to MINERU_IS_OCR or false")
    parser.add_argument("--mineru-enable-formula", help="MinerU formula parsing true/false; defaults to MINERU_ENABLE_FORMULA or true")
    parser.add_argument("--manifest-name", default="doc_manifest.json")
    parser.add_argument("--no-recursive", action="store_true", help="Do not recurse into input directories")
    parser.add_argument("--strict", action="store_true", help="Fail on the first skipped file")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
