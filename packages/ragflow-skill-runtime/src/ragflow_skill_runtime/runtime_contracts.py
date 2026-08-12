"""Offline contracts for release-bound, source-isolated skill runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


BASELINE_SCHEMA = "ragflow_runtime_install_baseline_v1"
COUNT_ONLY_DRIFT_SCHEMA = "ragflow_runtime_count_only_drift_v1"
RAW_DELTA_SCHEMA = "ragflow_runtime_raw_delta_metadata_v1"
CANDIDATE_SCHEMA = "ragflow_runtime_sanitized_candidate_v1"
SWITCH_SCHEMA = "ragflow_runtime_switch_result_v1"
ROLLBACK_SCHEMA = "ragflow_runtime_rollback_result_v1"
ARCHIVE_INVENTORY_SCHEMA = "ragflow_runtime_archive_inventory_v1"

RUNTIME_CONTRACT_SCHEMAS = (
    BASELINE_SCHEMA,
    COUNT_ONLY_DRIFT_SCHEMA,
    RAW_DELTA_SCHEMA,
    CANDIDATE_SCHEMA,
    SWITCH_SCHEMA,
    ROLLBACK_SCHEMA,
)

DRIFT_KEYS = ("modified", "added", "removed", "mode_changed")
FORBIDDEN_TREE_NAMES = {".git"}


class RuntimeContractError(ValueError):
    """Raised when a runtime boundary or immutable contract is violated."""


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contains_parent_reference(path: Path) -> bool:
    return ".." in path.parts


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _require_plain_directory(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if _contains_parent_reference(candidate):
        raise RuntimeContractError(f"{label} must not contain parent traversal")
    if _has_symlink_component(candidate):
        raise RuntimeContractError(f"{label} must not contain a symlink component")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RuntimeContractError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise RuntimeContractError(f"{label} must be a directory")
    return resolved


def _require_profile_root(path: str | Path) -> Path:
    candidate = Path(path)
    if _contains_parent_reference(candidate) or _has_symlink_component(candidate):
        raise RuntimeContractError("profile root must not traverse or contain symlinks")
    candidate.mkdir(parents=True, exist_ok=True)
    return _require_plain_directory(candidate, label="profile root")


def _reject_descendant_symlink(path: str | Path, *, label: str) -> None:
    """Reject symlinked descendants before creating or replacing a bounded child."""

    candidate = Path(path)
    if _contains_parent_reference(candidate) or _has_symlink_component(candidate):
        raise RuntimeContractError(f"{label} must not traverse or contain symlinks")


def _ensure_tree_is_release_safe(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.name in FORBIDDEN_TREE_NAMES:
            raise RuntimeContractError("release tree contains Git metadata")
        if path.is_symlink():
            raise RuntimeContractError("release tree contains a symlink")


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    _ensure_tree_is_release_safe(root)
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        info = path.stat(follow_symlinks=False)
        inventory.append(
            {
                "path": relative,
                "type": "file",
                "mode": stat.S_IMODE(info.st_mode),
                "size": info.st_size,
                "sha256": _sha256_file(path),
            }
        )
    return inventory


def _validate_baseline(baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise RuntimeContractError("baseline schema identity is invalid")
    inventory = baseline.get("inventory")
    if not isinstance(inventory, list):
        raise RuntimeContractError("baseline inventory is invalid")
    expected_digest = baseline.get("manifest_digest")
    unsigned = {key: value for key, value in baseline.items() if key != "manifest_digest"}
    if expected_digest != _digest_payload(unsigned):
        raise RuntimeContractError("baseline manifest digest does not match")
    safety = baseline.get("safety")
    if not isinstance(safety, Mapping):
        raise RuntimeContractError("baseline safety contract is missing")
    if (
        safety.get("git_metadata_absent") is not True
        or safety.get("symlinks_absent") is not True
        or safety.get("source_fallback_allowed") is not False
    ):
        raise RuntimeContractError("baseline safety contract is not source isolated")
    result: list[dict[str, Any]] = []
    for item in inventory:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise RuntimeContractError("baseline inventory entry is invalid")
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeContractError("baseline inventory contains an unsafe path")
        result.append(dict(item))
    return result


def create_install_baseline(
    release_root: str | Path,
    baseline_path: str | Path,
    *,
    release_id: str = "unversioned-release",
    archive_digest: str | None = None,
    installed_at: str | None = None,
    installer_class: str = "offline-contract",
    rollback_identity: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic, immutable manifest for one validated release tree."""

    release = _require_plain_directory(release_root, label="release root")
    destination = Path(baseline_path)
    _reject_descendant_symlink(destination, label="baseline path")
    if destination.exists() or destination.is_symlink():
        raise RuntimeContractError("baseline manifest is immutable and already exists")
    inventory = _file_inventory(release)
    inventory_digest = _digest_payload(inventory)
    unsigned: dict[str, Any] = {
        "schema": BASELINE_SCHEMA,
        "release_id": str(release_id),
        "archive_digest": archive_digest or inventory_digest,
        "inventory_digest": inventory_digest,
        "installed_at": installed_at,
        "installer_class": installer_class,
        "rollback_identity": rollback_identity,
        "active_relative_root": "active",
        "file_count": len(inventory),
        "inventory": inventory,
        "safety": {
            "git_metadata_absent": True,
            "symlinks_absent": True,
            "source_fallback_allowed": False,
        },
    }
    baseline = {**unsigned, "manifest_digest": _digest_payload(unsigned)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    destination.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return baseline


def install_release(
    release_root: str | Path,
    profile_root: str | Path,
    *,
    release_id: str = "unversioned-release",
    archive_digest: str | None = None,
    installed_at: str | None = None,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Install a Git-free active copy from a validated release into a fake profile."""

    if source_root is not None:
        raise RuntimeContractError("public source fallback is forbidden")
    release = _require_plain_directory(release_root, label="release root")
    _ensure_tree_is_release_safe(release)
    profile_candidate = Path(profile_root)
    if _contains_parent_reference(profile_candidate) or _has_symlink_component(profile_candidate):
        raise RuntimeContractError("profile root must not traverse or contain symlinks")
    profile_location = profile_candidate.resolve(strict=False)
    try:
        profile_location.relative_to(release)
    except ValueError:
        pass
    else:
        raise RuntimeContractError("profile root must be outside the release root")
    try:
        release.relative_to(profile_location)
    except ValueError:
        pass
    else:
        raise RuntimeContractError("release root must be outside the profile root")
    profile = _require_profile_root(profile_root)
    active_root = profile / "active"
    baseline_path = profile / "baseline" / "install-baseline.json"
    _reject_descendant_symlink(baseline_path, label="baseline path")
    _reject_descendant_symlink(active_root, label="active path")
    if active_root.exists() or active_root.is_symlink():
        raise RuntimeContractError("active runtime already exists")
    baseline = create_install_baseline(
        release,
        baseline_path,
        release_id=release_id,
        archive_digest=archive_digest,
        installed_at=installed_at,
    )
    try:
        shutil.copytree(release, active_root, symlinks=False)
        active_inventory = _file_inventory(active_root)
        if active_inventory != baseline["inventory"]:
            raise RuntimeContractError("active copy does not match its release baseline")
    except Exception:
        if active_root.exists():
            shutil.rmtree(active_root)
        try:
            baseline_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            baseline_path.unlink()
            baseline_path.parent.rmdir()
        except OSError:
            pass
        raise
    return {
        "baseline": baseline,
        "baseline_path": baseline_path,
        "active": {
            "release_id": release_id,
            "inventory_digest": baseline["inventory_digest"],
            "git_free": True,
            "release_bound": True,
        },
        "active_root": active_root,
    }


def _require_active_root(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.name != "active":
        raise RuntimeContractError("active root must be the fixed profile active target")
    return _require_plain_directory(candidate, label="active root")


def _drift_details(
    baseline: Mapping[str, Any], active_root: str | Path
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    baseline_inventory = _validate_baseline(baseline)
    active = _require_active_root(active_root)
    current_inventory = _file_inventory(active)
    before = {item["path"]: item for item in baseline_inventory}
    after = {item["path"]: item for item in current_inventory}
    details: dict[str, list[dict[str, Any]]] = {key: [] for key in DRIFT_KEYS}
    for relative in sorted(before.keys() | after.keys()):
        old = before.get(relative)
        new = after.get(relative)
        if old is None and new is not None:
            details["added"].append(dict(new))
            continue
        if new is None and old is not None:
            details["removed"].append(dict(old))
            continue
        assert old is not None and new is not None
        if old.get("sha256") != new.get("sha256") or old.get("size") != new.get("size"):
            details["modified"].append(dict(new))
        if old.get("mode") != new.get("mode"):
            details["mode_changed"].append(
                {"path": relative, "before": old.get("mode"), "after": new.get("mode")}
            )
    return details, current_inventory


def compare_active_to_baseline(
    baseline: Mapping[str, Any], active_root: str | Path
) -> dict[str, Any]:
    """Return deterministic count-only drift without paths, content, or private roots."""

    details, current = _drift_details(baseline, active_root)
    counts = {key: len(details[key]) for key in DRIFT_KEYS}
    drift_count = sum(counts.values())
    return {
        "schema": COUNT_ONLY_DRIFT_SCHEMA,
        "baseline_digest": baseline["manifest_digest"],
        "active_inventory_digest": _digest_payload(current),
        "classification": "no_drift" if drift_count == 0 else "drift_detected",
        "drift_detected": drift_count > 0,
        "counts": counts,
        "total_change_count": drift_count,
        "raw_output_included": False,
    }


def _path_class(relative: str) -> str:
    suffix = PurePosixPath(relative).suffix.lower()
    return {
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "configuration",
        ".yml": "configuration",
        ".txt": "text",
    }.get(suffix, "other")


def _private_delta_directory(candidate_root: Path, details: Mapping[str, Any]) -> Path:
    candidate_root.mkdir(parents=True, exist_ok=True)
    candidate_root.chmod(stat.S_IRWXU)
    identity = _digest_payload(details)[:16]
    destination = candidate_root / f"delta-{identity}"
    if destination.exists() or destination.is_symlink():
        raise RuntimeContractError("raw delta destination already exists")
    destination.mkdir(mode=stat.S_IRWXU)
    return destination


_SYMBOLIC_EVIDENCE_REF = re.compile(r"^[a-z][a-z0-9_-]*:[a-z0-9][a-z0-9._-]{0,127}$")


def _validate_evidence_ref(value: str, *, label: str = "evidence reference") -> str:
    if not isinstance(value, str) or not _SYMBOLIC_EVIDENCE_REF.fullmatch(value):
        raise RuntimeContractError(f"{label} must be a symbolic namespace:value reference")
    lowered = value.lower()
    if any(fragment in lowered for fragment in ("token", "secret", "bearer", "key=")):
        raise RuntimeContractError(f"{label} must not contain private value markers")
    return value


def capture_delta(
    baseline: Mapping[str, Any],
    active_root: str | Path,
    candidate_root: str | Path,
) -> dict[str, Any]:
    """Capture exact drift metadata and changed files below a private mode-700 root."""

    active = _require_active_root(active_root)
    details, _ = _drift_details(baseline, active)
    counts = {key: len(details[key]) for key in DRIFT_KEYS}
    private_root = Path(candidate_root)
    if _contains_parent_reference(private_root) or _has_symlink_component(private_root):
        raise RuntimeContractError("candidate root must not traverse or contain symlinks")
    delta_root = _private_delta_directory(private_root, details)
    archive_path = delta_root / "raw-files.tar"
    changed_paths = sorted(
        {
            item["path"]
            for key in ("modified", "added", "mode_changed")
            for item in details[key]
        }
    )
    with tarfile.open(archive_path, mode="w") as archive:
        for relative in changed_paths:
            source = active / PurePosixPath(relative)
            if source.is_file() and not source.is_symlink():
                archive.add(source, arcname=relative, recursive=False)
    archive_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    path_classes: dict[str, int] = {}
    for key in DRIFT_KEYS:
        for item in details[key]:
            path_class = _path_class(str(item["path"]))
            path_classes[path_class] = path_classes.get(path_class, 0) + 1
    metadata_path = delta_root / "raw-delta.json"
    metadata: dict[str, Any] = {
        "schema": RAW_DELTA_SCHEMA,
        "baseline_digest": baseline["manifest_digest"],
        "classification": "no_drift" if not sum(counts.values()) else "captured",
        "counts": counts,
        "details": details,
        "path_classes": dict(sorted(path_classes.items())),
        "archive_sha256": _sha256_file(archive_path),
        "private": True,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return {
        "schema": RAW_DELTA_SCHEMA,
        "baseline_digest": baseline["manifest_digest"],
        "classification": metadata["classification"],
        "counts": counts,
        "path_classes": metadata["path_classes"],
        "raw_path": str(metadata_path),
        "raw_archive": str(archive_path),
        "private": True,
    }


def create_sanitized_candidate(
    drift: Mapping[str, Any],
    raw_delta: Mapping[str, Any],
    candidate_root: str | Path | None = None,
    *,
    redaction_passed: bool = True,
) -> dict[str, Any]:
    """Create a release-safe candidate containing classifications and counts only."""

    if drift.get("schema") != COUNT_ONLY_DRIFT_SCHEMA:
        raise RuntimeContractError("drift schema identity is invalid")
    if raw_delta.get("schema") != RAW_DELTA_SCHEMA:
        raise RuntimeContractError("raw delta schema identity is invalid")
    drift_counts = drift.get("counts")
    if not isinstance(drift_counts, Mapping) or set(drift_counts) != set(DRIFT_KEYS):
        raise RuntimeContractError("drift counts do not match the fixed contract")
    if any(
        not isinstance(drift_counts[key], int)
        or isinstance(drift_counts[key], bool)
        or drift_counts[key] < 0
        for key in DRIFT_KEYS
    ):
        raise RuntimeContractError("drift counts must be non-negative integers")
    counts = {key: drift_counts[key] for key in DRIFT_KEYS}
    if raw_delta.get("private") is not True:
        raise RuntimeContractError("raw delta must be marked private")
    raw_counts = raw_delta.get("counts")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) != set(DRIFT_KEYS):
        raise RuntimeContractError("raw delta counts do not match the fixed contract")
    if any(
        not isinstance(raw_counts[key], int)
        or isinstance(raw_counts[key], bool)
        or raw_counts[key] < 0
        for key in DRIFT_KEYS
    ):
        raise RuntimeContractError("raw delta counts must be non-negative integers")
    normalized_raw_counts = {key: raw_counts[key] for key in DRIFT_KEYS}
    if normalized_raw_counts != counts:
        raise RuntimeContractError("raw delta counts do not match the count-only drift")
    if raw_delta.get("baseline_digest") != drift.get("baseline_digest"):
        raise RuntimeContractError("raw delta baseline identity does not match drift")
    path_classes = raw_delta.get("path_classes")
    allowed_classes = {"python", "markdown", "json", "configuration", "text", "other"}
    if not isinstance(path_classes, Mapping) or not set(path_classes).issubset(allowed_classes):
        raise RuntimeContractError("raw delta contains an unsafe path class")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in path_classes.values()
    ):
        raise RuntimeContractError("raw delta path classes must be non-negative integers")
    normalized_classes = {str(key): value for key, value in path_classes.items()}
    if sum(normalized_classes.values()) != sum(counts.values()):
        raise RuntimeContractError("raw delta path classes do not match drift counts")
    has_drift = sum(counts.values()) > 0
    if not redaction_passed:
        classification = "blocked_candidate"
        status = "needs_redaction"
    elif not has_drift:
        classification = "no_drift"
        status = "rejected"
    else:
        classification = "candidate_ready"
        status = "pending_review"
    return {
        "schema": CANDIDATE_SCHEMA,
        "baseline_digest": drift.get("baseline_digest"),
        "classification": classification,
        "status": status,
        "counts": counts,
        "changed_path_classes": dict(sorted(normalized_classes.items())),
        "provenance_class": "private_runtime_delta",
        "generalized_problem": "runtime behavior differs from the validated release",
        "neutral_proposed_change": "review and implement a source-level change independently",
        "fake_test_idea": "reproduce the classified behavior with neutral temporary fixtures",
        "redaction": {"passed": bool(redaction_passed), "raw_fields_included": False},
        "automatic_public_application": False,
    }


def _rollback_failure(*, evidence_ref: str = "private:rollback-evidence") -> dict[str, Any]:
    return {
        "schema": ROLLBACK_SCHEMA,
        "classification": "rollback_failure_blocking",
        "ok": False,
        "blocking": True,
        "evidence_ref": evidence_ref,
    }


def rollback_active(
    profile_root: str | Path,
    rollback_identity: str | Path,
    *,
    evidence_ref: str = "private:rollback-evidence",
) -> dict[str, Any]:
    """Restore a retained active copy, returning a blocking result on any failure."""

    _validate_evidence_ref(evidence_ref)
    try:
        profile = _require_profile_root(profile_root)
        rollback_root = profile / "rollback"
        _reject_descendant_symlink(rollback_root, label="rollback path")
        identity_path = Path(rollback_identity)
        if identity_path.is_absolute():
            previous = identity_path
            try:
                identity = previous.resolve(strict=True).relative_to(rollback_root.resolve(strict=True)).as_posix()
            except (FileNotFoundError, ValueError):
                return _rollback_failure(evidence_ref=evidence_ref)
        else:
            if _contains_parent_reference(identity_path) or len(identity_path.parts) != 1:
                return _rollback_failure(evidence_ref=evidence_ref)
            identity = identity_path.name
            previous = rollback_root / identity
        previous = _require_plain_directory(previous, label="rollback target")
        previous_inventory = _file_inventory(previous)
        expected_identity = f"previous-{_digest_payload(previous_inventory)}"
        if identity != expected_identity or previous.name != expected_identity:
            return _rollback_failure(evidence_ref=evidence_ref)
        active = profile / "active"
        failed = profile / ".failed-active"
        if failed.exists() or failed.is_symlink():
            return _rollback_failure(evidence_ref=evidence_ref)
        if active.exists():
            active.rename(failed)
        try:
            previous.rename(active)
            if _file_inventory(active) != previous_inventory:
                raise RuntimeContractError("rollback target changed during activation")
        except Exception:
            try:
                if active.exists() or active.is_symlink():
                    active.rename(previous)
                if failed.exists() and not active.exists():
                    failed.rename(active)
            except OSError:
                pass
            return _rollback_failure(evidence_ref=evidence_ref)
        if failed.exists():
            shutil.rmtree(failed)
        return {
            "schema": ROLLBACK_SCHEMA,
            "classification": "rollback_success",
            "ok": True,
            "blocking": False,
            "rollback_identity": identity,
            "evidence_ref": evidence_ref,
        }
    except (OSError, RuntimeContractError):
        return _rollback_failure(evidence_ref=evidence_ref)


def switch_active(
    profile_root: str | Path,
    staged_root: str | Path,
    *,
    staged_baseline: Mapping[str, Any] | None = None,
    pre_switch_check: Callable[[Path], bool] | None = None,
    post_switch_check: Callable[[Path], bool] | None = None,
    evidence_ref: str = "private:switch-evidence",
) -> dict[str, Any]:
    """Boundedly switch to a staged release and roll back a failed post-check."""

    _validate_evidence_ref(evidence_ref)
    base = {
        "schema": SWITCH_SCHEMA,
        "evidence_ref": evidence_ref,
    }
    try:
        profile = _require_profile_root(profile_root)
        active = _require_active_root(profile / "active")
        staged = _require_plain_directory(staged_root, label="staged release")
        _ensure_tree_is_release_safe(staged)
        if staged_baseline is None:
            raise RuntimeContractError("staged release requires a validated baseline contract")
        staged_inventory = _validate_baseline(staged_baseline)
        if _file_inventory(staged) != staged_inventory:
            raise RuntimeContractError("staged release does not match its baseline contract")
        if pre_switch_check is not None and not pre_switch_check(staged):
            return {
                **base,
                "classification": "pre_switch_failure",
                "ok": False,
                "blocking": False,
                "switched": False,
            }
    except (OSError, RuntimeContractError):
        return {
            **base,
            "classification": "pre_switch_failure",
            "ok": False,
            "blocking": False,
            "switched": False,
        }
    inventory = _file_inventory(active)
    rollback_identity = f"previous-{_digest_payload(inventory)}"
    rollback_root = profile / "rollback"
    try:
        _reject_descendant_symlink(rollback_root, label="rollback path")
    except RuntimeContractError:
        return {
            **base,
            "classification": "pre_switch_failure",
            "ok": False,
            "blocking": False,
            "switched": False,
        }
    rollback_root.mkdir(parents=True, exist_ok=True)
    previous = rollback_root / rollback_identity
    incoming = profile / ".incoming-active"
    if previous.exists() or incoming.exists() or incoming.is_symlink():
        return {
            **base,
            "classification": "pre_switch_failure",
            "ok": False,
            "blocking": False,
            "switched": False,
        }
    try:
        shutil.copytree(staged, incoming, symlinks=False)
        if _file_inventory(incoming) != staged_inventory:
            raise RuntimeContractError("copied staged release changed before switch")
        active.rename(previous)
        incoming.rename(active)
    except Exception:
        if previous.exists() and not active.exists():
            previous.rename(active)
        if incoming.exists():
            shutil.rmtree(incoming)
        return {
            **base,
            "classification": "pre_switch_failure",
            "ok": False,
            "blocking": False,
            "switched": False,
        }
    post_ok = True
    try:
        if post_switch_check is not None:
            post_ok = bool(post_switch_check(active))
    except Exception:
        post_ok = False
    if not post_ok:
        rollback = rollback_active(
            profile,
            rollback_identity,
            evidence_ref="private:post-switch-rollback-evidence",
        )
        return {
            **base,
            "classification": "post_switch_failure"
            if rollback["ok"]
            else "rollback_failure_blocking",
            "ok": False,
            "blocking": bool(rollback["blocking"]),
            "switched": True,
            "rollback_identity": rollback_identity,
            "rollback": rollback,
        }
    return {
        **base,
        "classification": "update_success",
        "ok": True,
        "blocking": False,
        "switched": True,
        "rollback_identity": rollback_identity,
    }


def _safe_archive_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeContractError("archive contains an unsafe path")
    if ".git" in path.parts:
        raise RuntimeContractError("archive contains Git metadata")
    return path


def archive_inventory(archive_path: str | Path) -> dict[str, Any]:
    """Return a deterministic, path-safe inventory for a release tar archive."""

    archive = Path(archive_path)
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    with tarfile.open(archive, mode="r:*") as handle:
        for member in sorted(handle.getmembers(), key=lambda item: item.name):
            name = _safe_archive_name(member.name).as_posix()
            if name in seen_paths:
                raise RuntimeContractError("archive contains duplicate normalized paths")
            seen_paths.add(name)
            if member.issym() or member.islnk():
                raise RuntimeContractError("archive contains a link")
            if member.isdir():
                entry_type = "directory"
            elif member.isfile():
                entry_type = "file"
            else:
                raise RuntimeContractError("archive contains an unsupported member type")
            item: dict[str, Any] = {
                "path": name,
                "type": entry_type,
                "mode": stat.S_IMODE(member.mode),
                "size": member.size,
            }
            if member.isfile():
                extracted = handle.extractfile(member)
                if extracted is None:
                    raise RuntimeContractError("archive member cannot be read")
                digest = hashlib.sha256()
                for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                    digest.update(chunk)
                item["sha256"] = digest.hexdigest()
            entries.append(item)
    return {
        "schema": ARCHIVE_INVENTORY_SCHEMA,
        "archive_sha256": _sha256_file(archive),
        "inventory_digest": _digest_payload(entries),
        "member_count": len(entries),
        "file_count": sum(item["type"] == "file" for item in entries),
        "directory_count": sum(item["type"] == "directory" for item in entries),
        "inventory": entries,
        "git_metadata_absent": True,
        "symlinks_absent": True,
    }


def check_archive_inventory(
    archive_path: str | Path,
    *,
    expected_inventory_digest: str | None = None,
    expected_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Check one archive against an optional deterministic expected inventory."""

    inventory = archive_inventory(archive_path)
    actual_paths = [item["path"] for item in inventory["inventory"]]
    if expected_inventory_digest is None and expected_paths is None:
        return {
            "ok": False,
            "schema": ARCHIVE_INVENTORY_SCHEMA,
            "archive_name": Path(archive_path).name,
            "archive_sha256": inventory["archive_sha256"],
            "inventory_digest": inventory["inventory_digest"],
            "member_count": inventory["member_count"],
            "file_count": inventory["file_count"],
            "directory_count": inventory["directory_count"],
            "classification": "missing_expected_inventory",
            "digest_matches": False,
            "paths_match": False,
            "git_metadata_absent": True,
            "symlinks_absent": True,
        }
    expected = sorted(expected_paths) if expected_paths is not None else None
    digest_matches = (
        expected_inventory_digest is None
        or inventory["inventory_digest"] == expected_inventory_digest
    )
    paths_match = expected is None or actual_paths == expected
    return {
        "ok": digest_matches and paths_match,
        "schema": ARCHIVE_INVENTORY_SCHEMA,
        "archive_name": Path(archive_path).name,
        "archive_sha256": inventory["archive_sha256"],
        "inventory_digest": inventory["inventory_digest"],
        "member_count": inventory["member_count"],
        "file_count": inventory["file_count"],
        "directory_count": inventory["directory_count"],
        "classification": "inventory_match" if digest_matches and paths_match else "inventory_mismatch",
        "digest_matches": digest_matches,
        "paths_match": paths_match,
        "git_metadata_absent": True,
        "symlinks_absent": True,
    }
