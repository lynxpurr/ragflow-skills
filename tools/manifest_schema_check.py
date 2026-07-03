#!/usr/bin/env python3
"""Validate public JSON Schema contracts for primary RAGFlow manifests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime import (  # noqa: E402
    DocManifest,
    FormalHandoffManifest,
    KbManifest,
    ManifestError,
    manifest_json_schemas,
    validate_payload_with_json_schema,
)


SCHEMA = "ragflow_manifest_schema_check_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _finding(check: str, path: Path, message: str, *, root: Path) -> dict[str, str]:
    return {
        "check": check,
        "path": _relative(path, root),
        "message": message,
    }


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "file not found"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "payload must be a JSON object"
    return payload, ""


def _validate_example(
    *,
    payload: dict[str, Any],
    schema: dict[str, Any],
    loader: Callable[[dict[str, Any]], Any],
) -> str:
    try:
        validate_payload_with_json_schema(payload, schema)
        loader(payload)
    except ManifestError as exc:
        return str(exc)
    return ""


def run_manifest_schema_check(*, root: Path = ROOT) -> dict[str, Any]:
    """Run the source manifest JSON Schema gate."""

    root = root.resolve()
    runtime_schemas = manifest_json_schemas()
    contracts: dict[str, dict[str, Any]] = {
        "doc_manifest": {
            "template": root / "skills" / "ragflow-doc-to-md" / "templates" / "doc_manifest.schema.json",
            "example": root / "skills" / "ragflow-doc-to-md" / "templates" / "doc_manifest.example.json",
            "loader": DocManifest.from_dict,
        },
        "kb_manifest": {
            "template": root / "skills" / "ragflow-kb-build" / "templates" / "kb_manifest.schema.json",
            "example": root / "skills" / "ragflow-kb-build" / "templates" / "kb_manifest.example.json",
            "loader": KbManifest.from_dict,
        },
        "formal_handoff_manifest": {
            "template": root / "skills" / "ragflow-doc-to-md" / "templates" / "formal_handoff_manifest.schema.json",
            "example": root / "skills" / "ragflow-doc-to-md" / "templates" / "formal_handoff_manifest.example.json",
            "loader": FormalHandoffManifest.from_dict,
        },
    }
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []
    for name, contract in contracts.items():
        template_path = Path(contract["template"])
        example_path = Path(contract["example"])
        runtime_schema = runtime_schemas.get(name)
        template_payload, template_error = _load_json(template_path)
        example_payload, example_error = _load_json(example_path)

        template_matches = bool(template_payload is not None and template_payload == runtime_schema)
        example_valid = False
        validation_error = ""
        if template_error:
            findings.append(_finding("manifest_schema_template", template_path, template_error, root=root))
        elif not template_matches:
            findings.append(
                _finding(
                    "manifest_schema_template_drift",
                    template_path,
                    "template schema must exactly match ragflow_skill_runtime.manifest_json_schemas()",
                    root=root,
                )
            )
        if example_error:
            findings.append(_finding("manifest_schema_example", example_path, example_error, root=root))
        elif template_payload is not None and example_payload is not None:
            validation_error = _validate_example(
                payload=example_payload,
                schema=template_payload,
                loader=contract["loader"],
            )
            example_valid = not validation_error
            if validation_error:
                findings.append(
                    _finding(
                        "manifest_schema_example_invalid",
                        example_path,
                        validation_error,
                        root=root,
                    )
                )

        checks.append(
            {
                "name": name,
                "ok": template_matches and example_valid,
                "runtime_schema_id": runtime_schema.get("$id") if isinstance(runtime_schema, dict) else None,
                "template": _relative(template_path, root),
                "example": _relative(example_path, root),
                "template_matches_runtime": template_matches,
                "example_valid": example_valid,
                "error": validation_error or template_error or example_error,
            }
        )

    return {
        "ok": not findings,
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "root": str(root),
        "summary": {
            "schema_count": len(checks),
            "finding_count": len(findings),
            "checked_manifests": sorted(contracts),
        },
        "checks": checks,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate public manifest JSON Schema templates")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--report-json", help="Optional path to write the manifest schema report")
    args = parser.parse_args(argv)

    report = run_manifest_schema_check(root=Path(args.root))
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
