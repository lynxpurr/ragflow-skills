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


def _run(args: argparse.Namespace) -> int:
    try:
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
                    backend=args.backend,
                    remote_url=args.remote_url,
                    remote_api_key=_remote_api_key(args),
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
    parser.add_argument("--backend", choices=["auto", "builtin", "pandoc", "remote"], default="auto")
    parser.add_argument("--remote-url", help="Remote conversion endpoint for unsupported files")
    parser.add_argument("--remote-api-key", help="Remote conversion bearer token")
    parser.add_argument("--manifest-name", default="doc_manifest.json")
    parser.add_argument("--no-recursive", action="store_true", help="Do not recurse into input directories")
    parser.add_argument("--strict", action="store_true", help="Fail on the first skipped file")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    return _run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
