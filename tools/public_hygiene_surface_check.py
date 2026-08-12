#!/usr/bin/env python3
"""Classify repository surfaces used by the public hygiene check.

Inventory and classification stay separate so each Git surface can be checked
without following working-tree symlinks or leaking source values.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Sequence

from release_hygiene_check import ALLOW_MARKER, FORBIDDEN_PATTERNS


SCHEMA = "ragflow_public_hygiene_candidate_check_v1"
ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EXCLUDE_ROOTS: tuple[str, ...] = (
    "reqs",
    "dist",
    "release-artifacts",
    "output",
)
_SECURE_DIR_FD_AVAILABLE = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in getattr(os, "supports_dir_fd", ())
)

# These values intentionally describe a conservative, deterministic heuristic.
# Entropy is only considered after a credential-like assignment has been found,
# so identifiers and build metadata with similar character distributions remain
# outside the check's scope.
_ENTROPY_MIN_LENGTH = 24
_ENTROPY_MIN_BITS_PER_CHAR = 4.0
_COMMON_HASH_RE = re.compile(
    r"(?i)^(?:(?:md5|sha(?:1|224|256|384|512))[:= -]?)?"
    r"(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{56}|[0-9a-f]{64}|"
    r"[0-9a-f]{96}|[0-9a-f]{128})$"
)
_SAFE_ENTROPY_WORDS = re.compile(
    r"(?i)(?:redacted|placeholder|fixture|example|fake|dummy|"
    r"changeme|change[-_ ]?me|replace[-_ ]?me|not[-_ ]?real|your[-_ ]?)"
)
_CREDENTIAL_NAME_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?:token|secret|credential|api[-_]?key|password|"
    r"authorization|access[-_]?key)(?![a-z0-9])"
)
_QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<name>[a-z0-9_.-]+)\s*[\"']?\s*"
    r"(?:=|:)\s*(?P<quote>[\"'])(?P<value>[^\"'\r\n]*)(?P=quote)"
)
_BARE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<name>[a-z0-9_.-]+)\s*[\"']?\s*"
    r"(?:=|:)\s*(?P<value>[A-Za-z0-9+/=_-]{24,})"
)


@dataclass(frozen=True)
class _InventoryDescriptor:
    """Private candidate descriptor retained for the classifier task.

    ``content`` is the exact byte payload selected by the source.  For index
    entries it comes from the index blob, while working-tree entries are read
    without following symlinks.
    """

    surface: str
    path: str
    source: str
    index_mode: str | None
    content: bytes | None


class _GitCommandError(RuntimeError):
    """Internal error for a failed Git inventory command."""


def _run_git(
    root: Path,
    args: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with an argument list scoped to ``root``.

    No shell is involved and callers pass path values as individual arguments.
    ``stderr`` is intentionally not surfaced in the public report because Git
    diagnostics can contain local absolute paths.
    """

    command = ["git", "-C", str(root), *args]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise _GitCommandError("git inventory command failed")
    return result


def _validate_git_root(root: Path) -> Path:
    """Return a canonical Git root or reject a non-repository input."""

    candidate = Path(root)
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("root must be an existing Git repository")
    candidate = candidate.resolve()
    result = _run_git(candidate, ("rev-parse", "--show-toplevel"), check=False)
    if result.returncode:
        raise ValueError("root must be an existing Git repository")
    # Git can report a different worktree root when ``root`` is a subdirectory.
    # The public API is defined in terms of a repository root, so reject that
    # ambiguity rather than silently broadening the scan.
    try:
        reported = result.stdout.decode("utf-8", "strict").strip()
        reported_path = Path(reported).resolve()
    except (OSError, UnicodeDecodeError, ValueError):
        raise ValueError("root must be an existing Git repository") from None
    if reported_path != candidate:
        raise ValueError("root must be the Git repository root")
    return candidate


def _normalise_relative_path(value: str, *, label: str) -> str:
    """Validate a repository-relative candidate path without exposing it."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"unsafe {label}")
    # Git's canonical path separator is ``/``.  A backslash is rejected rather
    # than interpreted as a separator, avoiding platform-dependent aliases.
    if "\\" in value:
        raise ValueError(f"unsafe {label}")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if path.is_absolute() or windows_path.drive or ".." in path.parts:
        raise ValueError(f"unsafe {label}")
    normalised = path.as_posix()
    if normalised in {"", "."}:
        raise ValueError(f"unsafe {label}")
    return normalised


def _normalise_exclude_roots(exclude_roots: Iterable[str]) -> tuple[str, ...]:
    values = list(DEFAULT_EXCLUDE_ROOTS)
    values.extend(exclude_roots)
    normalised = {
        _normalise_relative_path(value, label="exclude root") for value in values
    }
    return tuple(sorted(normalised))


def _is_excluded(path: str, exclude_roots: Sequence[str]) -> bool:
    parts = PurePosixPath(path).parts
    return any(
        parts[: len(PurePosixPath(root).parts)] == PurePosixPath(root).parts
        for root in exclude_roots
    )


def _split_nul(output: bytes) -> tuple[str, ...]:
    if not output:
        return ()
    values: list[str] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        try:
            value = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise ValueError("Git returned an unsafe candidate path") from None
        values.append(_normalise_relative_path(value, label="candidate path"))
    return tuple(values)


def _index_entries(root: Path) -> tuple[tuple[str, str], ...]:
    """Return ``(path, mode)`` entries from the index in stable order."""

    result = _run_git(root, ("ls-files", "-s", "-z"))
    entries: list[tuple[str, str]] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            header, encoded_path = raw.split(b"\t", 1)
            mode = header.split(maxsplit=1)[0].decode("ascii", "strict")
            path = encoded_path.decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Git returned an unsafe index entry") from None
        entries.append((_normalise_relative_path(path, label="candidate path"), mode))
    return tuple(sorted(set(entries)))


def _staged_paths(root: Path) -> tuple[tuple[str, str], tuple[str, ...]]:
    """Return staged non-deletions and staged deletion names from the index."""

    result = _run_git(root, ("diff", "--cached", "--name-status", "-z"))
    staged: list[tuple[str, str]] = []
    deleted: list[str] = []
    fields = result.stdout.split(b"\0")
    index = 0
    while index < len(fields):
        status_raw = fields[index]
        index += 1
        if not status_raw:
            continue
        try:
            status = status_raw.decode("ascii", "strict")
        except UnicodeDecodeError:
            raise ValueError("Git returned an unsafe staged path") from None
        if not status:
            raise ValueError("Git returned an unsafe staged path")
        code = status[0]
        names_needed = 2 if code in {"R", "C"} else 1
        names: list[str] = []
        for _ in range(names_needed):
            if index >= len(fields) or not fields[index]:
                raise ValueError("Git returned an unsafe staged path")
            try:
                name = fields[index].decode("utf-8", "strict")
            except UnicodeDecodeError:
                raise ValueError("Git returned an unsafe staged path") from None
            index += 1
            names.append(_normalise_relative_path(name, label="candidate path"))
        if code == "D":
            deleted.append(names[-1])
        elif code in {"R", "C"}:
            staged.append((names[-1], "100644"))
        else:
            staged.append((names[0], ""))
    return tuple(sorted(set(staged))), tuple(sorted(set(deleted)))


def _index_content(root: Path, path: str) -> bytes:
    """Read exactly the staged index blob for ``path``."""

    _normalise_relative_path(path, label="candidate path")
    result = _run_git(root, ("show", f":{path}"), check=False)
    if result.returncode:
        raise _GitCommandError("staged index content is unavailable")
    return result.stdout


def _safe_index_content(root: Path, path: str) -> bytes | None:
    """Read an index blob, retaining an unreadable marker for fail-closed scans."""

    try:
        return _index_content(root, path)
    except (_GitCommandError, OSError):
        return None


def _working_tree_content(root: Path, path: str) -> bytes | None:
    """Read a working-tree regular file through repository-bound descriptors."""

    if not _SECURE_DIR_FD_AVAILABLE:
        # A path-based fallback could follow an ancestor replaced after lstat.
        # Treat the content as unreadable on platforms without secure openat.
        return None
    path_parts = PurePosixPath(path).parts
    if not path_parts:
        return None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    file_flags |= getattr(os, "O_BINARY", 0)
    directory_descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        root_descriptor = os.open(root, directory_flags)
        directory_descriptors.append(root_descriptor)
        parent_descriptor = root_descriptor
        for part in path_parts[:-1]:
            parent_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            directory_descriptors.append(parent_descriptor)
            if not stat.S_ISDIR(os.fstat(parent_descriptor).st_mode):
                return None
        file_descriptor = os.open(
            path_parts[-1],
            file_flags,
            dir_fd=parent_descriptor,
        )
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            return None
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        for directory_descriptor in reversed(directory_descriptors):
            try:
                os.close(directory_descriptor)
            except OSError:
                pass


def _lexical_symlink_escape(parent_parts: Sequence[str], target: str) -> bool:
    """Return whether a symlink target is absolute or escapes the repository lexically."""

    # ``PureWindowsPath`` catches drive-qualified and UNC targets even when the
    # checker itself runs on POSIX.  Backslash-rooted paths are also absolute in
    # Windows notation, while a normal POSIX absolute path is handled below.
    windows_target = PureWindowsPath(target)
    if (
        PurePosixPath(target).is_absolute()
        or windows_target.is_absolute()
        or bool(windows_target.drive)
        or (target.startswith("\\") and bool(windows_target.root))
    ):
        return True

    # Normalize only for lexical traversal.  No filesystem lookup or target
    # read is performed, and the target itself is never included in a report.
    stack = list(parent_parts)
    target_parts = target.replace("\\", "/").split("/")
    for part in target_parts:
        if not part or part == ".":
            continue
        if part == "..":
            if not stack:
                return True
            stack.pop()
            continue
        stack.append(part)
    return False


def _working_tree_symlink_kind(root: Path, path: str) -> str | None:
    """Inspect each working-tree component without following symlinks."""

    parts = PurePosixPath(path).parts
    current = root
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            mode = os.lstat(candidate).st_mode
        except OSError:
            return None
        if stat.S_ISLNK(mode):
            try:
                target = os.readlink(candidate)
            except OSError:
                return "symlink_candidate"
            parent_parts = parts[:index]
            return (
                "symlink_escape"
                if _lexical_symlink_escape(parent_parts, target)
                else "symlink_candidate"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            return None
        current = candidate
    return None


def _index_symlink_kind(
    path: str, index_mode: str | None, content: bytes | None
) -> str | None:
    """Classify an index mode 120000 entry without treating its blob as text."""

    if index_mode != "120000":
        return None
    if content is None:
        return "symlink_candidate"
    try:
        target = content.decode("utf-8", "strict")
    except UnicodeDecodeError:
        # Preserve ASCII separators such as ``/`` and ``..`` for lexical
        # classification while keeping undecodable bytes out of all reports.
        target = content.decode("utf-8", "surrogateescape")
    parent_parts = PurePosixPath(path).parts[:-1]
    return (
        "symlink_escape"
        if _lexical_symlink_escape(parent_parts, target)
        else "symlink_candidate"
    )


def _shannon_entropy(value: str) -> float:
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    )


def _is_high_entropy_credential_value(
    value: str, name: str, *, context: str = ""
) -> bool:
    """Apply the bounded credential-context entropy heuristic."""

    if len(value) < _ENTROPY_MIN_LENGTH or not value.strip():
        return False
    if not _CREDENTIAL_NAME_RE.search(name):
        return False
    if (
        _SAFE_ENTROPY_WORDS.search(value)
        or _SAFE_ENTROPY_WORDS.search(name)
        or _SAFE_ENTROPY_WORDS.search(context)
    ):
        return False
    if _COMMON_HASH_RE.fullmatch(value):
        return False
    return (
        len(set(value)) >= 8
        and _shannon_entropy(value) >= _ENTROPY_MIN_BITS_PER_CHAR
    )


def _credential_entropy_matches(line: str, path: str = "") -> bool:
    """Return whether a line assigns an opaque value near a credential name."""

    if line.lstrip().startswith(("#", ";", "//")):
        return False
    matches = [
        *_QUOTED_ASSIGNMENT_RE.finditer(line),
        *_BARE_ASSIGNMENT_RE.finditer(line),
    ]
    return any(
        _is_high_entropy_credential_value(
            match.group("value"), match.group("name"), context=path
        )
        for match in matches
    )


def _tracked_content(root: Path, path: str, index_mode: str) -> bytes | None:
    """Select tracked bytes while retaining the index payload for symlink modes."""

    if index_mode == "120000":
        return _safe_index_content(root, path)
    return _working_tree_content(root, path)


def _inventory(
    *, root: Path, exclude_roots: Sequence[str]
) -> tuple[tuple[_InventoryDescriptor, ...], dict[str, int]]:
    index_entries = _index_entries(root)
    staged_entries, staged_deleted = _staged_paths(root)

    tracked = tuple(
        _InventoryDescriptor(
            surface="tracked",
            path=path,
            source="working_tree",
            index_mode=mode,
            content=_tracked_content(root, path, mode),
        )
        for path, mode in index_entries
        if not _is_excluded(path, exclude_roots)
    )

    staged = tuple(
        _InventoryDescriptor(
            surface="staged",
            path=path,
            source="index",
            index_mode=next((mode for candidate, mode in index_entries if candidate == path), None),
            content=_safe_index_content(root, path),
        )
        for path, _status_mode in staged_entries
        if not _is_excluded(path, exclude_roots)
    )

    untracked_paths = _split_nul(
        _run_git(root, ("ls-files", "--others", "--exclude-standard", "-z")).stdout
    )
    untracked = tuple(
        _InventoryDescriptor(
            surface="untracked",
            path=path,
            source="working_tree",
            index_mode=None,
            content=_working_tree_content(root, path),
        )
        for path in untracked_paths
        if not _is_excluded(path, exclude_roots)
    )

    counts = {
        "tracked_count": len(tracked),
        "staged_count": len(staged),
        "untracked_count": len(untracked),
        "staged_deleted_count": sum(not _is_excluded(path, exclude_roots) for path in staged_deleted),
    }
    # Sorting here makes the private inventory deterministic even when Git's
    # platform-specific directory traversal order changes.
    descriptors = tuple(
        sorted(
            (*tracked, *staged, *untracked),
            key=lambda item: (item.surface, item.path),
        )
    )
    return descriptors, counts


def _finding(
    descriptor: _InventoryDescriptor,
    finding_type: str,
    *,
    line: int | None = None,
) -> dict[str, object]:
    """Build the public finding shape without carrying source values or errors."""

    finding: dict[str, object] = {
        "surface": descriptor.surface,
        "path": descriptor.path,
        "finding_type": finding_type,
    }
    if line is not None:
        finding["line"] = line
    return finding


def _classify_descriptor(
    descriptor: _InventoryDescriptor, *, root: Path
) -> list[dict[str, object]]:
    """Classify one inventory descriptor with fail-closed, metadata-only findings."""

    if descriptor.index_mode == "120000":
        symlink_kind = _index_symlink_kind(
            descriptor.path,
            descriptor.index_mode,
            descriptor.content,
        )
    elif descriptor.source == "working_tree":
        symlink_kind = _working_tree_symlink_kind(root, descriptor.path)
    else:
        symlink_kind = _index_symlink_kind(
            descriptor.path,
            descriptor.index_mode,
            descriptor.content,
        )
    if symlink_kind is not None:
        return [_finding(descriptor, symlink_kind)]

    content = descriptor.content
    if content is None:
        return [_finding(descriptor, "unreadable_candidate")]
    if b"\x00" in content:
        return [_finding(descriptor, "binary_artifact")]
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return [_finding(descriptor, "binary_artifact")]

    findings: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                findings.append(_finding(descriptor, label, line=line_no))
        if _credential_entropy_matches(line, descriptor.path):
            findings.append(
                _finding(
                    descriptor,
                    "high_entropy_credential_value",
                    line=line_no,
                )
            )
    return findings


def run_public_hygiene_surface_check(
    *, root: Path = ROOT, exclude_roots: Sequence[str] = ()
) -> dict[str, object]:
    """Classify public hygiene candidates across tracked, staged, and untracked surfaces."""

    repository_root = _validate_git_root(root)
    excludes = _normalise_exclude_roots(exclude_roots)
    descriptors, counts = _inventory(root=repository_root, exclude_roots=excludes)
    findings = [
        finding
        for descriptor in descriptors
        for finding in _classify_descriptor(descriptor, root=repository_root)
    ]
    findings.sort(
        key=lambda finding: (
            str(finding["surface"]),
            str(finding["path"]),
            str(finding["finding_type"]),
            int(finding.get("line", 0)),
        )
    )
    summary = {
        **counts,
        "finding_count": len(findings),
    }
    return {
        "ok": not findings,
        "schema": SCHEMA,
        "summary": summary,
        "findings": findings,
    }


class _InputArgumentParser(argparse.ArgumentParser):
    """Raise a sanitized input error instead of printing parser diagnostics."""

    def error(self, _message: str) -> None:
        raise ValueError("invalid input")


def _invalid_input_report() -> dict[str, object]:
    """Return the public failure shape without exposing input details."""

    return {
        "ok": False,
        "schema": SCHEMA,
        "summary": {
            "tracked_count": 0,
            "staged_count": 0,
            "untracked_count": 0,
            "staged_deleted_count": 0,
            "finding_count": 1,
        },
        "findings": [
            {
                "surface": "repository",
                "path": "repository",
                "finding_type": "invalid_input",
            }
        ],
    }


def _render_report(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_report(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _InputArgumentParser(
        description="Check tracked, staged, and untracked public hygiene surfaces"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Git repository root to inspect",
    )
    parser.add_argument(
        "--exclude-root",
        action="append",
        default=[],
        help="Repository-relative root to exclude; repeat for multiple roots",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional path for the JSON report",
    )

    report_path: Path | None = None
    try:
        args = parser.parse_args(argv)
        report_path = args.report_json
        report = run_public_hygiene_surface_check(
            root=args.root,
            exclude_roots=args.exclude_root,
        )
    except (OSError, ValueError, _GitCommandError):
        report = _invalid_input_report()

    rendered = _render_report(report)
    if report_path is not None:
        try:
            _write_report(report_path, rendered)
        except (OSError, ValueError):
            # Output-path failures are input failures too.  Keep stdout and any
            # best-effort report file sanitized and free of local paths.
            report = _invalid_input_report()
            rendered = _render_report(report)
            try:
                _write_report(report_path, rendered)
            except (OSError, ValueError):
                pass
    sys.stdout.write(rendered)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
