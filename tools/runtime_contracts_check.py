#!/usr/bin/env python3
"""Check deterministic release inventories for the offline runtime contract gate."""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if RUNTIME_SRC.exists() and str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime.runtime_contracts import (  # noqa: E402
    COUNT_ONLY_DRIFT_SCHEMA,
    RuntimeContractError,
    check_archive_inventory,
    compare_active_to_baseline,
)


SCHEMA = "ragflow_runtime_contracts_check_v1"


def _archive_source_isolation(
    archive: Path,
    *,
    source_root: Path,
    expected_inventory_digest: str | None,
    actual_inventory_digest: str,
) -> dict[str, Any]:
    """Statically validate vendored code bound to an expected archive inventory."""

    if (
        expected_inventory_digest is None
        or expected_inventory_digest != actual_inventory_digest
    ):
        return {
            "ok": False,
            "classification": "inventory_not_bound",
            "source_access_attempted": False,
            "source_root_accessed": False,
        }

    module_bytes: bytes | None = None
    with tarfile.open(archive, mode="r:*") as handle:
        for member in handle.getmembers():
            if not member.isfile() or not member.name.endswith(
                "/scripts/_vendor/ragflow_skill_runtime/runtime_contracts.py"
            ):
                continue
            extracted = handle.extractfile(member)
            if extracted is not None:
                module_bytes = extracted.read()
                break
    if module_bytes is None:
        return {
            "ok": False,
            "classification": "runtime_contract_absent",
            "source_access_attempted": False,
            "source_root_accessed": False,
        }
    try:
        source = module_bytes.decode("utf-8")
        tree = ast.parse(source, filename="<archive-runtime-contracts>")
        compile(tree, "<archive-runtime-contracts>", "exec", dont_inherit=True)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return {
            "ok": False,
            "classification": "static_source_invalid",
            "source_access_attempted": False,
            "source_root_accessed": False,
        }
    source_literal = str(source_root.resolve())
    explicit_source_reference = bool(source_literal and source_literal in source)
    forbidden_literal = any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in {"PUBLIC_SOURCE_ROOT", "HERMES_HOME"}
        for node in ast.walk(tree)
    )
    unsafe_source_call = any(
        isinstance(node, ast.Call)
        and any(
            isinstance(child, ast.Name)
            and child.id in {"source_root", "public_source_root", "PUBLIC_SOURCE_ROOT"}
            for child in ast.walk(node)
        )
        for node in ast.walk(tree)
    )
    schema_literal_present = any(
        isinstance(node, ast.Constant)
        and node.value == "ragflow_runtime_install_baseline_v1"
        for node in ast.walk(tree)
    )
    rejected = explicit_source_reference or forbidden_literal or unsafe_source_call
    if rejected:
        classification = "static_source_reference_rejected"
    elif not schema_literal_present:
        classification = "runtime_contract_identity_missing"
    else:
        classification = "static_source_isolation_passed"
    return {
        "ok": classification == "static_source_isolation_passed",
        "classification": classification,
        "source_access_attempted": rejected,
        "source_root_accessed": False,
    }


def run_runtime_contracts_check(
    *,
    archive_paths: Sequence[str | Path],
    expected_inventory_digests: Mapping[str, str] | None = None,
    source_root: str | Path | None = None,
    derive_expected_inventory: bool = False,
) -> dict[str, Any]:
    """Check archives without reading or serializing a repository source root."""

    expected = dict(expected_inventory_digests or {})
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    isolation_source = Path(source_root).resolve() if source_root is not None else ROOT
    for archive_value in sorted(archive_paths, key=lambda item: Path(item).name):
        archive = Path(archive_value)
        try:
            expected_digest = expected.get(archive.name)
            if expected_digest is None and derive_expected_inventory:
                # Explicitly requested clean-build baseline derivation. The caller
                # owns the clean-build assertion; this checker only derives its
                # deterministic inventory digest.
                from ragflow_skill_runtime.runtime_contracts import archive_inventory

                expected_digest = archive_inventory(archive)["inventory_digest"]
            check = check_archive_inventory(
                archive,
                expected_inventory_digest=expected_digest,
            )
            check["source_isolation"] = _archive_source_isolation(
                archive,
                source_root=isolation_source,
                expected_inventory_digest=expected_digest,
                actual_inventory_digest=check["inventory_digest"],
            )
            check["ok"] = bool(check["ok"] and check["source_isolation"]["ok"])
        except (OSError, RuntimeContractError, ValueError, tarfile.ReadError) as exc:
            check = {
                "ok": False,
                "archive_name": archive.name,
                # Keep exception details out of the public report: OSError messages
                # can contain private temporary roots or machine-specific paths.
                "error": type(exc).__name__,
            }
        checks.append(check)
        if not check["ok"]:
            findings.append(
                {
                    "check": "archive_inventory",
                    "archive_name": archive.name,
                    "message": str(check.get("error") or "inventory mismatch"),
                }
            )
    source_isolation = bool(checks) and all(
        bool(check.get("source_isolation", {}).get("ok")) for check in checks
    )
    source_access_attempted = any(
        bool(check.get("source_isolation", {}).get("source_access_attempted"))
        for check in checks
    )
    return {
        "ok": bool(checks) and not findings,
        "schema": SCHEMA,
        "summary": {
            "archive_count": len(checks),
            "finding_count": len(findings),
            "source_isolation": source_isolation,
            "source_root_accessed": False,
            "source_access_attempted": source_access_attempted,
        },
        "archives": checks,
        "findings": findings,
    }


def run_count_only_drift_check(
    *,
    baseline_path: str | Path,
    active_root: str | Path,
) -> dict[str, Any]:
    """Compare one baseline and active root without exposing private paths/details."""

    try:
        payload = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("baseline must be a JSON object")
        drift = compare_active_to_baseline(payload, active_root)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return {
            "ok": False,
            "schema": COUNT_ONLY_DRIFT_SCHEMA,
            "classification": "invalid_input",
            "error": type(exc).__name__,
            "raw_output_included": False,
        }
    return {**drift, "ok": True}


def _load_expected(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise ValueError("expected inventory file must map archive names to digest strings")
    return dict(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check offline runtime contract archive inventories without source fallback"
    )
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        help="Release .tar.gz archive to check; repeat for every exported skill",
    )
    parser.add_argument(
        "--artifacts-dir",
        help="Optional directory whose *.tar.gz archives are checked without rebuilding",
    )
    parser.add_argument(
        "--expected-inventory-digests",
        type=Path,
        help="Optional JSON mapping of archive filename to expected inventory digest",
    )
    parser.add_argument(
        "--derive-clean-build-baseline",
        action="store_true",
        help="Explicitly derive expected archive inventories from clean-build archives",
    )
    parser.add_argument("--baseline", type=Path, help="Baseline manifest for count-only drift checking")
    parser.add_argument("--active-root", type=Path, help="Fixed active root for count-only drift checking")
    parser.add_argument("--report-json", type=Path, help="Optional sanitized JSON report path")
    args = parser.parse_args(argv)

    if bool(args.baseline) != bool(args.active_root):
        parser.error("--baseline and --active-root must be supplied together")
    if args.baseline is not None:
        report = run_count_only_drift_check(
            baseline_path=args.baseline,
            active_root=args.active_root,
        )
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    archive_paths = [Path(value) for value in args.archive]
    if args.artifacts_dir:
        archive_paths.extend(sorted(Path(args.artifacts_dir).glob("*.tar.gz")))
    report = run_runtime_contracts_check(
        archive_paths=archive_paths,
        expected_inventory_digests=_load_expected(args.expected_inventory_digests),
        derive_expected_inventory=args.derive_clean_build_baseline,
    )
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
