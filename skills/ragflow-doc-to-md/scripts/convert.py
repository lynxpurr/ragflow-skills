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
    DEFAULT_HARD_MAX_CHARS,
    DEFAULT_MIN_SEGMENT_CHARS,
    DEFAULT_SOFT_MAX_CHARS,
    DocConvertError,
    DocQualityError,
    DocPostprocessError,
    DocSegmentError,
    QualityDocument,
    convert_source_to_markdown,
    create_rich_handoff_package,
    configured_private_hosts_from_urls,
    discover_source_documents,
    extract_markdown_title,
    HandoffError,
    load_doc_manifest_payload,
    load_skill_config,
    make_doc_manifest_payload,
    make_doc_runtime_report_payload,
    make_quality_report_payload,
    materialize_segments,
    plan_markdown_segmentation,
    postprocess_handoff,
    postprocess_single_markdown,
    probe_conversion_backends,
    quality_documents_from_manifest,
    render_backend_probe_markdown,
    render_backend_warmup_markdown,
    render_doc_runtime_markdown,
    render_quality_markdown,
    safe_markdown_name,
    sanitize_report_payload,
    sha256_file,
    warmup_conversion_backend,
)


BACKEND_CHOICES = {
    "auto",
    "builtin",
    "mineru",
    "mineru-agent",
    "mineru-cli",
    "mineru-local",
    "mineru-sync",
    "pandoc",
    "remote",
}


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _error(message: str, *, json_output: bool) -> int:
    if json_output:
        _dump_json({"ok": False, "error": message})
    else:
        print(f"error: {message}", file=sys.stderr)
    return 2


def _remote_api_key(args: argparse.Namespace, config) -> str | None:
    return args.remote_api_key or config.doc_to_md.remote_api_key


def _remote_url(args: argparse.Namespace, config) -> str | None:
    return args.remote_url or config.doc_to_md.remote_url


def _backend(args: argparse.Namespace, config) -> str:
    backend = args.backend or config.doc_to_md.backend or "auto"
    if backend not in BACKEND_CHOICES:
        allowed = ", ".join(sorted(BACKEND_CHOICES))
        raise DocConvertError(f"DOC_TO_MD_BACKEND must be one of: {allowed}")
    return backend


def _remote_timeout(args: argparse.Namespace) -> float:
    value = args.remote_timeout
    if value in (None, ""):
        return 120.0
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be a number of seconds") from exc
    if timeout <= 0:
        raise DocConvertError("DOC_TO_MD_TIMEOUT must be greater than zero")
    return timeout


def _sidecar_path(root: Path, name: str | None) -> Path | None:
    if not name:
        return None
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _write_runtime_report(
    *,
    output_root: Path,
    args: argparse.Namespace,
    process_attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, Path | None, Path | None]:
    if not process_attempts:
        return None, None, None
    report = make_doc_runtime_report_payload(
        output_root=output_root,
        process_attempts=process_attempts,
    )
    report_json_path = _sidecar_path(output_root, args.runtime_report_name)
    if report_json_path:
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_path = _sidecar_path(output_root, args.runtime_report_md)
    if report_md_path:
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        report_md_path.write_text(render_doc_runtime_markdown(report), encoding="utf-8")
    return report, report_json_path, report_md_path


def _config_or_arg(args: argparse.Namespace, field: str, config_value, default=None):
    value = getattr(args, field)
    return value if value not in (None, "") else config_value if config_value not in (None, "") else default


def _float_config_or_arg(
    args: argparse.Namespace,
    field: str,
    config_value,
    default: float,
    *,
    label: str,
) -> float:
    value = getattr(args, field)
    if value is None:
        value = config_value
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DocConvertError(f"{label} must be a number of seconds") from exc
    if parsed <= 0:
        raise DocConvertError(f"{label} must be greater than zero")
    return parsed


def _bool_config_or_arg(args: argparse.Namespace, field: str, config_value, default: bool, *, label: str) -> bool:
    value = getattr(args, field)
    if value is None:
        value = config_value
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise DocConvertError(f"{label} must be true or false")


def _run(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = _backend(args, config)
        remote_url = _remote_url(args, config)
        remote_timeout = (
            _remote_timeout(args)
            if args.remote_timeout is not None
            else config.doc_to_md.remote_timeout or 120.0
        )
        mineru_timeout = _float_config_or_arg(
            args,
            "mineru_timeout",
            config.mineru.timeout,
            300.0,
            label="MINERU_TIMEOUT",
        )
        mineru_poll_interval = _float_config_or_arg(
            args,
            "mineru_poll_interval",
            config.mineru.poll_interval,
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
        process_attempts: list[dict[str, Any]] = []

        for source in sources:
            output_name = safe_markdown_name(source, used=used_names)
            markdown_path = docs_dir / output_name
            try:
                markdown, warnings = convert_source_to_markdown(
                    source,
                    mode=args.mode,
                    backend=backend,
                    remote_url=remote_url,
                    remote_api_key=_remote_api_key(args, config),
                    remote_timeout=remote_timeout,
                    mineru_base_url=_config_or_arg(args, "mineru_base_url", config.mineru.base_url),
                    mineru_api_key=_config_or_arg(args, "mineru_api_key", config.mineru.api_key),
                    mineru_timeout=mineru_timeout,
                    mineru_poll_interval=mineru_poll_interval,
                    mineru_cli_path=_config_or_arg(args, "mineru_cli_path", config.mineru.cli_path),
                    mineru_cli_backend=_config_or_arg(
                        args,
                        "mineru_cli_backend",
                        config.mineru.cli_backend,
                        "pipeline",
                    )
                    or "pipeline",
                    asset_output_dir=markdown_path.parent,
                    mineru_language=_config_or_arg(args, "mineru_language", config.mineru.language, "ch") or "ch",
                    mineru_page_range=_config_or_arg(args, "mineru_page_range", config.mineru.page_range),
                    mineru_enable_table=_bool_config_or_arg(
                        args,
                        "mineru_enable_table",
                        config.mineru.enable_table,
                        True,
                        label="MINERU_ENABLE_TABLE",
                    ),
                    mineru_is_ocr=_bool_config_or_arg(
                        args,
                        "mineru_is_ocr",
                        config.mineru.is_ocr,
                        False,
                        label="MINERU_IS_OCR",
                    ),
                    mineru_enable_formula=_bool_config_or_arg(
                        args,
                        "mineru_enable_formula",
                        config.mineru.enable_formula,
                        True,
                        label="MINERU_ENABLE_FORMULA",
                    ),
                    process_attempts=process_attempts,
                    allow_image_fallback=not args.no_image_fallback,
                )
            except (UnicodeDecodeError, OSError, DocConvertError) as exc:
                if args.strict:
                    _write_runtime_report(
                        output_root=output_root,
                        args=args,
                        process_attempts=process_attempts,
                    )
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

        runtime_report, runtime_report_path, runtime_report_md_path = _write_runtime_report(
            output_root=output_root,
            args=args,
            process_attempts=process_attempts,
        )
        if not converted:
            raise DocConvertError("no documents were converted")

        manifest = make_doc_manifest_payload(output_root=output_root, documents=converted)
        quality_documents = [
            QualityDocument(
                source_path=document.source.source_path,
                markdown_path=document.markdown_path,
                warnings=document.warnings,
            )
            for document in converted
        ]
        quality_report = make_quality_report_payload(
            output_root=output_root,
            documents=quality_documents,
        )
        quality_report_path = _sidecar_path(output_root, args.quality_report_name)
        if quality_report_path:
            quality_report_path.parent.mkdir(parents=True, exist_ok=True)
            quality_report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["quality_report"] = args.quality_report_name
        quality_report_md_path = _sidecar_path(output_root, args.quality_report_md)
        if quality_report_md_path:
            quality_report_md_path.parent.mkdir(parents=True, exist_ok=True)
            quality_report_md_path.write_text(render_quality_markdown(quality_report), encoding="utf-8")
            manifest["quality_report_md"] = args.quality_report_md
        if runtime_report_path:
            manifest["runtime_report"] = args.runtime_report_name
        if runtime_report_md_path:
            manifest["runtime_report_md"] = args.runtime_report_md
        manifest["quality_gate"] = quality_report["gate"]
        manifest_path = output_root / args.manifest_name
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        _dump_json(
            {
                "ok": True,
                "doc_manifest": str(manifest_path),
                "quality_report": str(quality_report_path) if quality_report_path else None,
                "quality_gate": quality_report["gate"],
                "runtime_report": str(runtime_report_path) if runtime_report_path else None,
                "runtime_summary": runtime_report["summary"] if runtime_report else None,
                "document_count": len(converted),
                "skipped": skipped,
            }
        )
        return 0 if not skipped else 1
    except (DocConvertError, DocQualityError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_inspect(args: argparse.Namespace) -> int:
    try:
        manifest = load_doc_manifest_payload(args.doc_manifest)
        output_root, documents = quality_documents_from_manifest(
            manifest,
            manifest_path=args.doc_manifest,
        )
        report = make_quality_report_payload(output_root=output_root, documents=documents)
        report_json = Path(args.report_json) if args.report_json else Path(args.doc_manifest).parent / "quality_report.json"
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_quality_markdown(report), encoding="utf-8")
        _dump_json(
            {
                "ok": True,
                "quality_report": str(report_json),
                "quality_report_md": str(args.report_md) if args.report_md else None,
                "quality_gate": report["gate"],
                "document_count": len(documents),
            }
        )
        if args.fail_on_blocked and report["gate"].get("status") == "BLOCKED":
            return 1
        return 0
    except (DocQualityError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_segment_plan(args: argparse.Namespace) -> int:
    try:
        plan = plan_markdown_segmentation(
            args.markdown,
            soft_max_chars=args.soft_max_chars,
            hard_max_chars=args.hard_max_chars,
            min_segment_chars=args.min_segment_chars,
        )
        payload = plan.to_dict()
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _dump_json({"ok": True, "segmentation_plan": payload, "output": args.output})
        return 0
    except (DocSegmentError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_split(args: argparse.Namespace) -> int:
    try:
        materialized = materialize_segments(
            args.markdown,
            output_dir=args.output,
            plan_output=args.plan_output,
            soft_max_chars=args.soft_max_chars,
            hard_max_chars=args.hard_max_chars,
            min_segment_chars=args.min_segment_chars,
            force=args.force,
        )
        _dump_json(materialized.to_dict())
        return 0
    except (DocSegmentError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_package(args: argparse.Namespace) -> int:
    try:
        if not args.rich:
            raise HandoffError("package currently supports only --rich")
        payload = create_rich_handoff_package(
            handoff_root=args.handoff,
            doc_manifest_name=args.manifest_name,
            metadata_name=args.metadata_name,
            artifact_index_name=args.artifact_index_name,
            profile_suggestions_name=args.profile_suggestions_name,
            retrieval_hints_name=args.retrieval_hints_name,
            assistant_profile_name=args.assistant_profile_name,
            assistant_test_plan_name=args.assistant_test_plan_name,
            package_readme_name=args.package_readme_name,
        )
        _dump_json({"ok": True, "package": payload})
        return 0
    except (HandoffError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_postprocess(args: argparse.Namespace) -> int:
    try:
        if bool(args.markdown) == bool(args.doc_manifest):
            raise DocPostprocessError("provide exactly one of --markdown or --doc-manifest")
        if args.markdown:
            report = postprocess_single_markdown(
                args.markdown,
                profile=args.profile,
                output_path=args.output,
                write=args.write,
                report_json=args.report_json,
            )
        else:
            report = postprocess_handoff(
                args.doc_manifest,
                profile=args.profile,
                output_dir=args.output,
                write=args.write,
                report_json=args.report_json,
            )
        _dump_json({"ok": True, "postprocess_report": report})
        return 0
    except (DocPostprocessError, OSError, UnicodeDecodeError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_backend_probe(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = args.backend or config.doc_to_md.backend or "auto"
        remote_url = _config_or_arg(args, "remote_url", config.doc_to_md.remote_url)
        mineru_base_url = _config_or_arg(args, "mineru_base_url", config.mineru.base_url)
        mineru_api_key = _config_or_arg(args, "mineru_api_key", config.mineru.api_key)
        mineru_cli_path = _config_or_arg(args, "mineru_cli_path", config.mineru.cli_path)
        report = probe_conversion_backends(
            backend=backend,
            remote_url=remote_url,
            mineru_base_url=mineru_base_url,
            mineru_api_key=mineru_api_key,
            mineru_cli_path=mineru_cli_path,
            network_check=args.network_check,
            timeout=args.probe_timeout,
        )
        if args.redaction_report:
            report, redaction_report = sanitize_report_payload(
                report,
                explicit_secrets=[config.doc_to_md.remote_api_key, config.mineru.api_key, args.mineru_api_key],
                private_hosts=configured_private_hosts_from_urls([remote_url, mineru_base_url]),
                home_paths=[mineru_cli_path],
                config_paths=[args.config, os.environ.get("RAGFLOW_CONFIG")],
            )
            redaction_path = Path(args.redaction_report)
            redaction_path.parent.mkdir(parents=True, exist_ok=True)
            redaction_path.write_text(json.dumps(redaction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_backend_probe_markdown(report), encoding="utf-8")
        if args.json or not args.report_json:
            _dump_json(report)
        if args.fail_on_unavailable:
            statuses = [item.get("status") for item in report.get("backends", []) if isinstance(item, dict)]
            if "available" not in statuses:
                return 1
            if report.get("selected_backend") != "auto" and any(status != "available" for status in statuses):
                return 1
        return 0
    except (DocConvertError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _run_backend_warmup(args: argparse.Namespace) -> int:
    try:
        config = load_skill_config(config_file=args.config)
        backend = args.backend or config.doc_to_md.backend or "auto"
        remote_timeout = (
            _remote_timeout(args)
            if args.remote_timeout is not None
            else config.doc_to_md.remote_timeout or 120.0
        )
        report = warmup_conversion_backend(
            fixture_path=args.fixture,
            backend=backend,
            output_markdown=args.output_markdown,
            remote_url=_config_or_arg(args, "remote_url", config.doc_to_md.remote_url),
            remote_api_key=_remote_api_key(args, config),
            remote_timeout=remote_timeout,
            mineru_base_url=_config_or_arg(args, "mineru_base_url", config.mineru.base_url),
            mineru_api_key=_config_or_arg(args, "mineru_api_key", config.mineru.api_key),
            mineru_timeout=_float_config_or_arg(
                args,
                "mineru_timeout",
                config.mineru.timeout,
                300.0,
                label="MINERU_TIMEOUT",
            ),
            mineru_poll_interval=_float_config_or_arg(
                args,
                "mineru_poll_interval",
                config.mineru.poll_interval,
                3.0,
                label="MINERU_POLL_INTERVAL",
            ),
            mineru_cli_path=_config_or_arg(args, "mineru_cli_path", config.mineru.cli_path),
            mineru_cli_backend=_config_or_arg(
                args,
                "mineru_cli_backend",
                config.mineru.cli_backend,
                "pipeline",
            )
            or "pipeline",
            mineru_language=_config_or_arg(args, "mineru_language", config.mineru.language, "ch") or "ch",
            mineru_page_range=_config_or_arg(args, "mineru_page_range", config.mineru.page_range),
            mineru_enable_table=_bool_config_or_arg(
                args,
                "mineru_enable_table",
                config.mineru.enable_table,
                True,
                label="MINERU_ENABLE_TABLE",
            ),
            mineru_is_ocr=_bool_config_or_arg(
                args,
                "mineru_is_ocr",
                config.mineru.is_ocr,
                False,
                label="MINERU_IS_OCR",
            ),
            mineru_enable_formula=_bool_config_or_arg(
                args,
                "mineru_enable_formula",
                config.mineru.enable_formula,
                True,
                label="MINERU_ENABLE_FORMULA",
            ),
        )
        if args.report_json:
            report_json = Path(args.report_json)
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report_md:
            report_md = Path(args.report_md)
            report_md.parent.mkdir(parents=True, exist_ok=True)
            report_md.write_text(render_backend_warmup_markdown(report), encoding="utf-8")
        if args.json or not args.report_json:
            _dump_json(report)
        if args.fail_on_failed and report.get("status") != "success":
            return 1
        return 0
    except (DocConvertError, OSError) as exc:
        return _error(str(exc), json_output=args.json)


def _add_segmentation_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--soft-max-chars", type=int, default=DEFAULT_SOFT_MAX_CHARS)
    parser.add_argument("--hard-max-chars", type=int, default=DEFAULT_HARD_MAX_CHARS)
    parser.add_argument("--min-segment-chars", type=int, default=DEFAULT_MIN_SEGMENT_CHARS)
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")


def build_inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a doc_manifest handoff and write a quality report")
    parser.add_argument("--doc-manifest", required=True, help="Path to doc_manifest.json")
    parser.add_argument("--report-json", help="Output quality_report.json path; defaults beside the doc manifest")
    parser.add_argument("--report-md", help="Optional Markdown quality report path")
    parser.add_argument("--fail-on-blocked", action="store_true", help="Return exit code 1 when the gate status is BLOCKED")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_segment_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan Markdown segmentation without writing segment files")
    parser.add_argument("--markdown", required=True, help="Markdown file to inspect")
    parser.add_argument("--output", help="Optional segmentation_plan.json output path")
    _add_segmentation_threshold_args(parser)
    return parser


def build_split_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize Markdown segments from a long document")
    parser.add_argument("--markdown", required=True, help="Markdown file to split")
    parser.add_argument("--output", required=True, help="Output directory for segment Markdown files")
    parser.add_argument("--plan-output", help="Optional segmentation_plan.json output path")
    parser.add_argument("--force", action="store_true", help="Allow writing into a non-empty output directory")
    _add_segmentation_threshold_args(parser)
    return parser


def build_package_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create optional rich handoff sidecars beside a doc_manifest")
    parser.add_argument("--handoff", required=True, help="Handoff directory containing doc_manifest.json")
    parser.add_argument("--rich", action="store_true", help="Generate rich package sidecars")
    parser.add_argument("--manifest-name", default="doc_manifest.json", help="Doc manifest name under the handoff directory")
    parser.add_argument("--metadata-name", default="metadata.json", help="Metadata sidecar name")
    parser.add_argument("--artifact-index-name", default="artifact_index.json", help="Artifact index sidecar name")
    parser.add_argument("--profile-suggestions-name", default="profile_suggestions.json", help="Profile suggestions sidecar name")
    parser.add_argument("--retrieval-hints-name", default="retrieval_hints.json", help="Retrieval hints sidecar name")
    parser.add_argument("--assistant-profile-name", default="assistant_profile.json", help="Assistant profile sidecar name")
    parser.add_argument("--assistant-test-plan-name", default="assistant_test_plan.json", help="Assistant test plan sidecar name")
    parser.add_argument("--package-readme-name", default="package_readme.md", help="Package README sidecar name")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def build_postprocess_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply deterministic Markdown post-processing profiles")
    parser.add_argument("--markdown", help="Single Markdown file to post-process")
    parser.add_argument("--doc-manifest", help="Process every Markdown file referenced by a doc_manifest")
    parser.add_argument("--profile", choices=["none", "safe", "ocr", "chunk-markers"], default="safe")
    parser.add_argument("--output", help="Output file for --markdown or output handoff directory for --doc-manifest")
    parser.add_argument("--write", action="store_true", help="Rewrite the source Markdown file(s) in place")
    parser.add_argument("--report-json", help="Optional postprocess_report.json output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def _add_backend_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Unified config file; defaults to RAGFLOW_CONFIG or .ragflow/config*.yaml")
    parser.add_argument("--backend", choices=sorted(BACKEND_CHOICES), help="Backend to inspect; auto uses configured backend selection")
    parser.add_argument("--remote-url", help="Remote conversion endpoint; defaults to DOC_TO_MD_REMOTE_URL")
    parser.add_argument("--mineru-base-url", help="MinerU service base URL")
    parser.add_argument("--mineru-api-key", help="MinerU API key; probe reports presence only, warmup uses it for service calls")
    parser.add_argument("--mineru-cli-path", help="Local MinerU CLI path; defaults to MINERU_CLI_PATH or PATH lookup")


def build_backend_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect document conversion backend readiness")
    sub = parser.add_subparsers(dest="backend_command", required=True)
    probe = sub.add_parser("probe", help="Probe configured conversion backend readiness")
    _add_backend_config_args(probe)
    probe.add_argument("--network-check", action="store_true", help="Attempt a bounded endpoint reachability check")
    probe.add_argument("--probe-timeout", type=float, default=2.0, help="Maximum seconds for each network probe")
    probe.add_argument("--report-json", help="Optional backend probe JSON report path")
    probe.add_argument("--report-md", help="Optional backend probe Markdown report path")
    probe.add_argument("--redaction-report", help="Optional JSON redaction sidecar output path")
    probe.add_argument("--fail-on-unavailable", action="store_true", help="Return non-zero when the selected backend is unavailable")
    probe.add_argument("--json", action="store_true", help="Emit JSON")
    probe.set_defaults(func=_run_backend_probe)
    warmup = sub.add_parser("warmup", help="Run an explicit fixture through a configured conversion backend")
    _add_backend_config_args(warmup)
    warmup.add_argument("--fixture", required=True, help="Tiny user-approved fixture file to convert")
    warmup.add_argument("--output-markdown", help="Optional converted Markdown output path")
    warmup.add_argument("--remote-api-key", help="Remote conversion bearer token; defaults to DOC_TO_MD_REMOTE_API_KEY")
    warmup.add_argument("--remote-timeout", type=float, help="Remote conversion timeout in seconds; defaults to DOC_TO_MD_TIMEOUT or 120")
    warmup.add_argument("--mineru-timeout", type=float, help="MinerU parse timeout in seconds; defaults to MINERU_TIMEOUT or 300")
    warmup.add_argument("--mineru-poll-interval", type=float, help="MinerU parse polling interval; defaults to MINERU_POLL_INTERVAL or 3")
    warmup.add_argument("--mineru-cli-backend", help="Local MinerU CLI backend passed with -b; defaults to MINERU_CLI_BACKEND, mineru.cli_backend, or pipeline")
    warmup.add_argument("--mineru-language", help="MinerU language option; defaults to MINERU_LANGUAGE or ch")
    warmup.add_argument("--mineru-page-range", help="MinerU page range; defaults to MINERU_PAGE_RANGE")
    warmup.add_argument("--mineru-enable-table", help="MinerU table parsing true/false; defaults to MINERU_ENABLE_TABLE or true")
    warmup.add_argument("--mineru-is-ocr", help="MinerU OCR mode true/false; defaults to MINERU_IS_OCR or false")
    warmup.add_argument("--mineru-enable-formula", help="MinerU formula parsing true/false; defaults to MINERU_ENABLE_FORMULA or true")
    warmup.add_argument("--report-json", help="Optional backend warmup JSON report path")
    warmup.add_argument("--report-md", help="Optional backend warmup Markdown report path")
    warmup.add_argument("--fail-on-failed", action="store_true", help="Return non-zero when warmup conversion fails")
    warmup.add_argument("--json", action="store_true", help="Emit JSON")
    warmup.set_defaults(func=_run_backend_warmup)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert documents into a Markdown handoff bundle",
        epilog="Commands: backend probe, backend warmup, inspect, segment-plan, split.",
    )
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--output", required=True, help="Output handoff directory")
    parser.add_argument("--config", help="Unified config file; defaults to RAGFLOW_CONFIG or .ragflow/config*.yaml")
    parser.add_argument("--mode", choices=["auto", "passthrough", "convert"], default="auto")
    parser.add_argument("--backend", choices=sorted(BACKEND_CHOICES), help="Conversion backend; defaults to DOC_TO_MD_BACKEND or auto")
    parser.add_argument("--remote-url", help="Remote conversion endpoint; defaults to DOC_TO_MD_REMOTE_URL")
    parser.add_argument("--remote-api-key", help="Remote conversion bearer token; defaults to DOC_TO_MD_REMOTE_API_KEY")
    parser.add_argument("--remote-timeout", type=float, help="Remote conversion timeout in seconds; defaults to DOC_TO_MD_TIMEOUT or 120")
    parser.add_argument("--mineru-base-url", help="MinerU service base URL; Agent API defaults to MINERU_BASE_URL or https://mineru.net/api/v1/agent, mineru-sync appends /parse when needed")
    parser.add_argument("--mineru-api-key", help="MinerU API key; defaults to MINERU_API_KEY")
    parser.add_argument("--mineru-timeout", type=float, help="MinerU parse timeout in seconds; defaults to MINERU_TIMEOUT or 300")
    parser.add_argument("--mineru-poll-interval", type=float, help="MinerU parse polling interval; defaults to MINERU_POLL_INTERVAL or 3")
    parser.add_argument("--mineru-cli-path", help="Local MinerU CLI path; defaults to MINERU_CLI_PATH, mineru.cli_path, or PATH lookup")
    parser.add_argument("--mineru-cli-backend", help="Local MinerU CLI backend passed with -b; defaults to MINERU_CLI_BACKEND, mineru.cli_backend, or pipeline")
    parser.add_argument("--mineru-language", help="MinerU language option; defaults to MINERU_LANGUAGE or ch")
    parser.add_argument("--mineru-page-range", help="MinerU page range; defaults to MINERU_PAGE_RANGE")
    parser.add_argument("--mineru-enable-table", help="MinerU table parsing true/false; defaults to MINERU_ENABLE_TABLE or true")
    parser.add_argument("--mineru-is-ocr", help="MinerU OCR mode true/false; defaults to MINERU_IS_OCR or false")
    parser.add_argument("--mineru-enable-formula", help="MinerU formula parsing true/false; defaults to MINERU_ENABLE_FORMULA or true")
    parser.add_argument("--manifest-name", default="doc_manifest.json")
    parser.add_argument("--quality-report-name", default="quality_report.json", help="Quality report sidecar name under the output directory")
    parser.add_argument("--quality-report-md", help="Optional Markdown quality report sidecar name under the output directory")
    parser.add_argument("--runtime-report-name", default="runtime_report.json", help="Runtime process cleanup report sidecar name; written when local process-backed converters run")
    parser.add_argument("--runtime-report-md", help="Optional Markdown runtime report sidecar name under the output directory")
    parser.add_argument("--no-image-fallback", action="store_true", help="Skip source-image Markdown fallback when OCR/conversion is unavailable")
    parser.add_argument("--no-recursive", action="store_true", help="Do not recurse into input directories")
    parser.add_argument("--strict", action="store_true", help="Fail on the first skipped file")
    parser.add_argument("--json", action="store_true", help="Emit JSON errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    if actual_argv:
        command = actual_argv[0]
        command_args = actual_argv[1:]
        if command == "inspect":
            return _run_inspect(build_inspect_parser().parse_args(command_args))
        if command == "segment-plan":
            return _run_segment_plan(build_segment_plan_parser().parse_args(command_args))
        if command == "split":
            return _run_split(build_split_parser().parse_args(command_args))
        if command == "package":
            return _run_package(build_package_parser().parse_args(command_args))
        if command == "postprocess":
            return _run_postprocess(build_postprocess_parser().parse_args(command_args))
        if command == "backend":
            parsed = build_backend_parser().parse_args(command_args)
            return parsed.func(parsed)
    return _run(build_parser().parse_args(actual_argv))


if __name__ == "__main__":
    raise SystemExit(main())
