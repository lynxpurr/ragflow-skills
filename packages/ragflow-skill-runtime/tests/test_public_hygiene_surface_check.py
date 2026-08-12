from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
TOOL = TOOLS_DIR / "public_hygiene_surface_check.py"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import public_hygiene_surface_check as hygiene_surface_check  # noqa: E402
from public_hygiene_surface_check import (  # noqa: E402
    SCHEMA,
    _inventory,
    _normalise_exclude_roots,
    _working_tree_content,
    run_public_hygiene_surface_check,
)


EXPECTED_SCHEMA = "ragflow_public_hygiene_candidate_check_v1"
SUMMARY_COUNT_KEYS = {
    "tracked_count",
    "staged_count",
    "untracked_count",
    "staged_deleted_count",
    "finding_count",
}
FINDING_KEYS = {"surface", "path", "finding_type", "line"}


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
            "LC_ALL": "C",
        }
    )
    return environment


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        capture_output=True,
        env=_git_environment(),
    )


def _commit(root: Path, *paths: str, message: str = "fixture update") -> None:
    _git(root, "add", "--", *paths)
    _git(root, "commit", "--quiet", "-m", message)


def _initialize_repository(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "Public Hygiene Test")
    _git(root, "config", "user.email", "public-hygiene@example.invalid")
    (root / "README.md").write_text("# Neutral fixture\n", encoding="utf-8")
    _commit(root, "README.md", message="initial fixture")


@contextmanager
def _temporary_repository() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        _initialize_repository(root)
        yield root


def _opaque_value(length: int = 80) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(alphabet[(index * 23 + 7) % len(alphabet)] for index in range(length))


def _credential_assignment(value: str | None = None) -> str:
    return f'service_token = "{value or _opaque_value()}"\n'


def _finding_for(report: dict[str, object], path: str) -> dict[str, object]:
    findings = [finding for finding in report["findings"] if finding["path"] == path]
    if len(findings) != 1:
        raise AssertionError(f"expected one finding for {path!r}, got {findings!r}")
    return findings[0]


def _run_cli(
    root: Path,
    *,
    report_json: Path | None = None,
    exclude_roots: Sequence[str] = (),
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(TOOL), "--root", str(root)]
    for exclude_root in exclude_roots:
        command.extend(("--exclude-root", exclude_root))
    if report_json is not None:
        command.extend(("--report-json", str(report_json)))
    return subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
    )


class PublicHygieneSurfaceCheckTests(unittest.TestCase):
    def assert_report_contract(self, report: dict[str, object]) -> None:
        self.assertEqual(report["schema"], EXPECTED_SCHEMA)
        self.assertEqual(report["summary"]["finding_count"], len(report["findings"]))
        self.assertLessEqual(SUMMARY_COUNT_KEYS, set(report["summary"]))
        for key, value in report["summary"].items():
            self.assertTrue(key.endswith("_count"), key)
            self.assertIsInstance(value, int, key)
        for finding in report["findings"]:
            self.assertLessEqual(set(finding), FINDING_KEYS)
            self.assertLessEqual({"surface", "path", "finding_type"}, set(finding))
            self.assertIsInstance(finding["surface"], str, finding)
            self.assertIsInstance(finding["path"], str, finding)
            self.assertIsInstance(finding["finding_type"], str, finding)
            self.assertFalse(Path(finding["path"]).is_absolute(), finding)
            self.assertNotIn("..", Path(finding["path"]).parts, finding)
            if "line" in finding:
                self.assertIsInstance(finding["line"], int, finding)
                self.assertGreaterEqual(finding["line"], 1, finding)

    def test_clean_repository_has_expected_schema_and_surface_counts(self) -> None:
        with _temporary_repository() as root:
            report = run_public_hygiene_surface_check(root=root)

        self.assertEqual(SCHEMA, EXPECTED_SCHEMA)
        self.assert_report_contract(report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            report["summary"],
            {
                "tracked_count": 1,
                "staged_count": 0,
                "untracked_count": 0,
                "staged_deleted_count": 0,
                "finding_count": 0,
            },
        )

    def test_staged_content_is_read_from_index_instead_of_working_tree(self) -> None:
        with _temporary_repository() as root:
            candidate = root / "candidate.py"
            candidate.write_text(_credential_assignment(), encoding="utf-8")
            _git(root, "add", "--", "candidate.py")
            candidate.write_text('status = "safe working tree content"\n', encoding="utf-8")

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["summary"]["staged_count"], 1)
        finding = _finding_for(report, "candidate.py")
        self.assertEqual(finding["surface"], "staged")
        self.assertEqual(finding.get("line"), 1)

    def test_inventory_uses_working_tree_for_tracked_and_index_for_staged(self) -> None:
        with _temporary_repository() as root:
            candidate = root / "candidate.py"
            candidate.write_text("committed content\n", encoding="utf-8")
            _commit(root, "candidate.py", message="add candidate fixture")
            candidate.write_text("staged index content\n", encoding="utf-8")
            _git(root, "add", "--", "candidate.py")
            candidate.write_text("working tree content\n", encoding="utf-8")

            descriptors, counts = _inventory(
                root=root,
                exclude_roots=_normalise_exclude_roots(()),
            )

        tracked = [item for item in descriptors if item.surface == "tracked" and item.path == "candidate.py"]
        staged = [item for item in descriptors if item.surface == "staged" and item.path == "candidate.py"]
        self.assertEqual(counts["tracked_count"], 2)
        self.assertEqual(counts["staged_count"], 1)
        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0].source, "working_tree")
        self.assertEqual(tracked[0].content, b"working tree content\n")
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].source, "index")
        self.assertEqual(staged[0].content, b"staged index content\n")

    def test_inventory_rejects_symlinked_working_tree_ancestors(self) -> None:
        with _temporary_repository() as root:
            nested = root / "nested"
            nested.mkdir()
            candidate = nested / "settings.py"
            candidate.write_text("committed content\n", encoding="utf-8")
            _commit(root, "nested/settings.py", message="add nested candidate")

            outside = root.parent / "outside"
            outside.mkdir()
            (outside / "settings.py").write_text(
                "outside bytes must never be read\n",
                encoding="utf-8",
            )
            candidate.unlink()
            nested.rmdir()
            nested.symlink_to(outside, target_is_directory=True)

            descriptors, _counts = _inventory(
                root=root,
                exclude_roots=_normalise_exclude_roots(()),
            )

        tracked = [
            item
            for item in descriptors
            if item.surface == "tracked" and item.path == "nested/settings.py"
        ]
        self.assertEqual(len(tracked), 1)
        self.assertIsNone(tracked[0].content)

    def test_working_tree_reader_does_not_open_through_swapped_ancestor(self) -> None:
        with _temporary_repository() as root:
            nested = root / "nested"
            nested.mkdir()
            candidate = nested / "settings.py"
            safe_content = b"safe tracked content\n"
            candidate.write_bytes(safe_content)
            _commit(root, "nested/settings.py", message="add nested candidate")

            outside = root.parent / "outside"
            outside.mkdir()
            outside_candidate = outside / "settings.py"
            outside_candidate.write_bytes(b"outside bytes must never be opened\n")
            outside_stat = outside_candidate.stat()
            outside_identity = (outside_stat.st_dev, outside_stat.st_ino)
            original_open = os.open
            opened_outside = False
            swapped = False

            def swapping_open(
                path: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal opened_outside, swapped
                if Path(path).name == "settings.py" and not swapped:
                    nested.rename(root / "nested-original")
                    nested.symlink_to(outside, target_is_directory=True)
                    swapped = True
                kwargs = {"dir_fd": dir_fd} if dir_fd is not None else {}
                descriptor = original_open(path, flags, mode, **kwargs)
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) == outside_identity:
                    opened_outside = True
                return descriptor

            with mock.patch.object(
                hygiene_surface_check.os,
                "open",
                side_effect=swapping_open,
            ):
                content = _working_tree_content(root, "nested/settings.py")

        self.assertTrue(swapped)
        self.assertFalse(opened_outside)
        self.assertIn(content, (safe_content, None))

    def test_nonignored_untracked_forbidden_content_is_blocked(self) -> None:
        with _temporary_repository() as root:
            (root / "local_settings.py").write_text(
                _credential_assignment(),
                encoding="utf-8",
            )

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["summary"]["untracked_count"], 1)
        self.assertEqual(_finding_for(report, "local_settings.py")["surface"], "untracked")

    def test_staged_deletion_is_counted_without_scanning_missing_content(self) -> None:
        with _temporary_repository() as root:
            retired = root / "retired_settings.py"
            retired.write_text(_credential_assignment(), encoding="utf-8")
            _commit(root, "retired_settings.py", message="add retired fixture")
            retired.unlink()
            _git(root, "add", "--update", "--", "retired_settings.py")

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["staged_deleted_count"], 1)
        self.assertNotIn("retired_settings.py", {item["path"] for item in report["findings"]})

    def test_git_ignored_reqs_root_is_not_part_of_untracked_surface(self) -> None:
        with _temporary_repository() as root:
            (root / ".gitignore").write_text("reqs/\n", encoding="utf-8")
            _commit(root, ".gitignore", message="ignore local requirements")
            reqs = root / "reqs"
            reqs.mkdir()
            (reqs / "local_settings.py").write_text(
                _credential_assignment(),
                encoding="utf-8",
            )

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["untracked_count"], 0)
        self.assertEqual(report["findings"], [])

    def test_symlink_escape_is_rejected_without_reading_or_leaking_target(self) -> None:
        target_value = _opaque_value()
        with _temporary_repository() as root:
            outside = root.parent / f"outside_{target_value}.fifo"
            os.mkfifo(outside)
            (root / "escape.py").symlink_to(outside)
            temporary_root = str(root.parent)

            try:
                result = _run_cli(root, timeout=5.0)
            except subprocess.TimeoutExpired as exc:
                self.fail(f"symlink target was opened or read instead of rejected: {exc}")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertNotIn(target_value, result.stderr)
            self.assertNotIn(temporary_root, result.stderr)
            report = json.loads(result.stdout)
            serialized = json.dumps(report, sort_keys=True)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        finding = _finding_for(report, "escape.py")
        self.assertEqual(finding["surface"], "untracked")
        self.assertIn("symlink", finding["finding_type"])
        self.assertNotIn(target_value, serialized)
        self.assertNotIn(temporary_root, serialized)

    def test_tracked_index_symlink_is_rejected_when_working_tree_is_regular(self) -> None:
        with _temporary_repository() as root:
            nested = root / "nested"
            nested.mkdir()
            candidate = nested / "link.py"
            candidate.symlink_to("../README.md")
            _commit(root, "nested/link.py", message="add tracked symlink")

            candidate.unlink()
            candidate.write_text("safe regular replacement\n", encoding="utf-8")

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        finding = _finding_for(report, "nested/link.py")
        self.assertEqual(finding["surface"], "tracked")
        self.assertEqual(finding["finding_type"], "symlink_candidate")

    def test_nul_and_non_utf8_files_are_blocked_as_binary_candidates(self) -> None:
        with _temporary_repository() as root:
            (root / "nul.bin").write_bytes(b"neutral\x00payload\n")
            (root / "non_utf8.bin").write_bytes(b"neutral-\xff\xfe-payload\n")

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["summary"]["untracked_count"], 2)
        for path in ("nul.bin", "non_utf8.bin"):
            finding = _finding_for(report, path)
            self.assertEqual(finding["surface"], "untracked")
            self.assertEqual(finding["finding_type"], "binary_artifact")

    def test_high_entropy_value_is_blocked_only_in_credential_assignment_context(self) -> None:
        opaque = _opaque_value()
        with _temporary_repository() as root:
            (root / "settings.py").write_text(
                _credential_assignment(opaque),
                encoding="utf-8",
            )
            (root / "build_metadata.py").write_text(
                f'build_id = "{opaque}"\n',
                encoding="utf-8",
            )

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertFalse(report["ok"], report)
        self.assertEqual({finding["path"] for finding in report["findings"]}, {"settings.py"})
        finding = _finding_for(report, "settings.py")
        self.assertEqual(finding["finding_type"], "high_entropy_credential_value")
        self.assertEqual(finding.get("line"), 1)

    def test_placeholders_examples_fixtures_and_common_hashes_are_allowed(self) -> None:
        common_empty_sha256 = (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )
        with _temporary_repository() as root:
            (root / "safe_examples.py").write_text(
                "\n".join(
                    (
                        'service_token = "<redacted:service-token>"',
                        'api_key = "example-api-key"',
                        'client_secret = "fixture-secret-value"',
                        f'auth_token = "{common_empty_sha256}"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_public_hygiene_surface_check(root=root)

        self.assert_report_contract(report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["findings"], [])

    def test_report_contains_only_sanitized_relative_metadata_and_counts(self) -> None:
        opaque = _opaque_value()
        with _temporary_repository() as root:
            configs = root / "configs"
            configs.mkdir()
            tracked = configs / "runtime.py"
            tracked.write_text(_credential_assignment(opaque), encoding="utf-8")
            _commit(root, "configs/runtime.py", message="add candidate fixture")

            report = run_public_hygiene_surface_check(root=root)
            serialized = json.dumps(report, sort_keys=True)
            temporary_root = str(root.parent)

        self.assert_report_contract(report)
        self.assertEqual(set(report), {"ok", "schema", "summary", "findings"})
        self.assertFalse(report["ok"], report)
        finding = _finding_for(report, "configs/runtime.py")
        self.assertEqual(finding["surface"], "tracked")
        self.assertNotIn("message", finding)
        self.assertNotIn("value", finding)
        self.assertNotIn("raw", finding)
        self.assertNotIn(opaque, serialized)
        self.assertNotIn(temporary_root, serialized)

    def test_cli_returns_zero_prints_json_and_writes_report_file_when_clean(self) -> None:
        with _temporary_repository() as root:
            report_path = root.parent / "public-hygiene.json"

            result = _run_cli(root, report_json=report_path)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stdout_report, file_report)
        self.assertTrue(stdout_report["ok"], stdout_report)
        self.assertEqual(stdout_report["schema"], EXPECTED_SCHEMA)

    def test_cli_returns_one_and_prints_sanitized_json_when_findings_exist(self) -> None:
        opaque = _opaque_value()
        with _temporary_repository() as root:
            report_path = root.parent / "public-hygiene-findings.json"
            (root / "settings.py").write_text(
                _credential_assignment(opaque),
                encoding="utf-8",
            )

            result = _run_cli(root, report_json=report_path)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stderr, "")
            stdout_report = json.loads(result.stdout)
            file_serialized = report_path.read_text(encoding="utf-8")
            file_report = json.loads(file_serialized)
            temporary_root = str(root.parent)

        self.assertEqual(stdout_report, file_report)
        self.assertFalse(stdout_report["ok"], stdout_report)
        self.assertEqual(stdout_report["schema"], EXPECTED_SCHEMA)
        self.assertNotIn(opaque, result.stdout)
        self.assertNotIn(opaque, result.stderr)
        self.assertNotIn(opaque, file_serialized)
        self.assertNotIn(temporary_root, result.stdout)
        self.assertNotIn(temporary_root, result.stderr)
        self.assertNotIn(temporary_root, file_serialized)

    def test_cli_honors_repeatable_symbolic_exclude_roots(self) -> None:
        with _temporary_repository() as root:
            for directory in ("local-cache", "generated-private"):
                excluded = root / directory
                excluded.mkdir()
                (excluded / "settings.py").write_text(
                    _credential_assignment(),
                    encoding="utf-8",
                )

            result = _run_cli(
                root,
                exclude_roots=("local-cache", "generated-private"),
            )
            report = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["untracked_count"], 0)


if __name__ == "__main__":
    unittest.main()
