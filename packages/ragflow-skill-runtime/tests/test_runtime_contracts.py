from __future__ import annotations

import json
import hashlib
import os
import stat
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ragflow_skill_runtime.runtime_contracts import (
    BASELINE_SCHEMA,
    CANDIDATE_SCHEMA,
    COUNT_ONLY_DRIFT_SCHEMA,
    RAW_DELTA_SCHEMA,
    RAW_DELTA_SCHEMA,
    ROLLBACK_SCHEMA,
    SWITCH_SCHEMA,
    RuntimeContractError,
    capture_delta,
    compare_active_to_baseline,
    create_install_baseline,
    create_sanitized_candidate,
    install_release,
    rollback_active,
    switch_active,
)


class RuntimeContractsTests(unittest.TestCase):
    def make_tree(self, root: Path) -> None:
        (root / "skills" / "demo").mkdir(parents=True)
        (root / "skills" / "demo" / "run.py").write_text("print('ok')\n", encoding="utf-8")
        (root / "skills" / "demo" / "README.md").write_text("demo\n", encoding="utf-8")

    def test_install_baseline_is_immutable_and_active_copy_is_git_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            profile = root / "fake-home" / "profile"
            default_profile = root / "fake-home" / "default" / "sentinel.txt"
            self.make_tree(release)
            default_profile.parent.mkdir(parents=True)
            default_profile.write_text("unchanged\n", encoding="utf-8")
            result = install_release(release, profile, release_id="release-a")

            self.assertEqual(result["baseline"]["schema"], BASELINE_SCHEMA)
            self.assertEqual(result["active"]["release_id"], "release-a")
            self.assertNotIn(".git", {p.name for p in result["active_root"].rglob("*")})
            baseline_text = result["baseline_path"].read_text(encoding="utf-8")
            with self.assertRaises(RuntimeContractError):
                create_install_baseline(release, result["baseline_path"], release_id="changed")
            self.assertEqual(result["baseline_path"].read_text(encoding="utf-8"), baseline_text)
            self.assertEqual(default_profile.read_text(encoding="utf-8"), "unchanged\n")
            self.assertEqual(
                compare_active_to_baseline(result["baseline"], result["active_root"])["classification"],
                "no_drift",
            )

    def test_install_rejects_git_source_fallback_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            profile = root / "profile"
            outside = root / "outside.txt"
            self.make_tree(release)
            outside.write_text("private\n", encoding="utf-8")
            os.symlink(outside, release / "skills" / "demo" / "escape.txt")
            with self.assertRaises(RuntimeContractError):
                install_release(release, profile)
            os.unlink(release / "skills" / "demo" / "escape.txt")
            with self.assertRaises(RuntimeContractError):
                install_release(release, profile, source_root=root / "git-source")

    def test_install_rejects_baseline_descendant_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            profile = root / "profile"
            outside = root / "outside-baseline"
            self.make_tree(release)
            profile.mkdir()
            outside.mkdir()
            os.symlink(outside, profile / "baseline")

            with self.assertRaises(RuntimeContractError):
                install_release(release, profile)

            self.assertEqual(list(outside.iterdir()), [])

    def test_install_rejects_profile_contained_by_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            profile = release / "nested-profile"
            self.make_tree(release)

            with self.assertRaises(RuntimeContractError):
                install_release(release, profile)

            self.assertFalse(profile.exists())

    def test_drift_is_count_only_and_raw_delta_stays_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, candidate_root = root / "release", root / "profile", root / "private-candidates"
            self.make_tree(release)
            result = install_release(release, profile, release_id="r1")
            active = result["active_root"]
            (active / "skills" / "demo" / "run.py").write_text("changed-secret-looking-content\n", encoding="utf-8")
            (active / "skills" / "demo" / "added.txt").write_text("new\n", encoding="utf-8")
            (active / "skills" / "demo" / "README.md").unlink()
            mode_path = active / "skills" / "demo" / "run.py"
            mode_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            drift = compare_active_to_baseline(result["baseline"], active)
            self.assertEqual(drift["schema"], COUNT_ONLY_DRIFT_SCHEMA)
            self.assertEqual(drift["counts"], {"modified": 1, "added": 1, "removed": 1, "mode_changed": 1})
            self.assertNotIn("changed-secret-looking-content", json.dumps(drift))
            raw = capture_delta(result["baseline"], active, candidate_root)
            self.assertEqual(raw["schema"], RAW_DELTA_SCHEMA)
            self.assertTrue(Path(raw["raw_path"]).is_file())
            self.assertIn("run.py", Path(raw["raw_path"]).read_text(encoding="utf-8"))
            candidate = create_sanitized_candidate(drift, raw, candidate_root)
            self.assertEqual(candidate["schema"], CANDIDATE_SCHEMA)
            self.assertNotIn(str(candidate_root), json.dumps(candidate))
            self.assertNotIn("changed-secret-looking-content", json.dumps(candidate))
            blocked = create_sanitized_candidate(drift, raw, candidate_root, redaction_passed=False)
            self.assertEqual(blocked["classification"], "blocked_candidate")
            self.assertEqual(blocked["status"], "needs_redaction")

    def test_path_traversal_and_symlink_active_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile = root / "release", root / "profile"
            self.make_tree(release)
            result = install_release(release, profile)
            with self.assertRaises(RuntimeContractError):
                compare_active_to_baseline(result["baseline"], profile / ".." / "outside")
            os.symlink(root, profile / "active-link")
            with self.assertRaises(RuntimeContractError):
                compare_active_to_baseline(result["baseline"], profile / "active-link")

    def test_update_switch_and_rollback_classifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile = root / "release", root / "profile"
            self.make_tree(release)
            result = install_release(release, profile)
            staged = root / "staged"
            self.make_tree(staged)
            staged_baseline = create_install_baseline(
                staged,
                root / "staged-baseline.json",
                release_id="release-b",
            )
            pre_switch = switch_active(
                profile,
                staged,
                staged_baseline=staged_baseline,
                pre_switch_check=lambda _: False,
            )
            self.assertEqual(pre_switch["classification"], "pre_switch_failure")
            self.assertFalse(pre_switch["switched"])
            success = switch_active(profile, staged, staged_baseline=staged_baseline)
            self.assertEqual(success["schema"], SWITCH_SCHEMA)
            self.assertEqual(success["classification"], "update_success")
            rollback = rollback_active(profile, success["rollback_identity"])
            self.assertEqual(rollback["schema"], ROLLBACK_SCHEMA)
            self.assertEqual(rollback["classification"], "rollback_success")
            blocked = rollback_active(profile, root / "missing")
            self.assertEqual(blocked["classification"], "rollback_failure_blocking")
            self.assertTrue(blocked["blocking"])

    def test_post_switch_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")
            result = switch_active(
                profile,
                staged,
                staged_baseline=staged_baseline,
                post_switch_check=lambda _: False,
            )
            self.assertEqual(result["classification"], "post_switch_failure")
            self.assertEqual(result["rollback"]["classification"], "rollback_success")
            self.assertFalse(result["blocking"])

    def test_switch_rejects_unbound_staged_directory_and_rollback_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            outside = root / "outside-rollback"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            outside.mkdir()
            os.symlink(outside, profile / "rollback")

            unbound = switch_active(profile, staged)

            self.assertEqual(unbound["classification"], "pre_switch_failure")
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")
            escaped = switch_active(profile, staged, staged_baseline=staged_baseline)
            self.assertEqual(escaped["classification"], "pre_switch_failure")
            self.assertEqual(list(outside.iterdir()), [])

    def test_switch_rejects_baseline_without_source_isolation_safety_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")
            forged = dict(staged_baseline)
            forged["safety"] = dict(staged_baseline["safety"])
            forged["safety"]["source_fallback_allowed"] = True
            unsigned = {key: value for key, value in forged.items() if key != "manifest_digest"}
            forged["manifest_digest"] = hashlib.sha256(
                json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()

            result = switch_active(profile, staged, staged_baseline=forged)

            self.assertEqual(result["classification"], "pre_switch_failure")

    def test_switch_rechecks_copied_inventory_after_pre_switch_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            installed = install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")

            def mutate_after_validation(candidate: Path) -> bool:
                (candidate / "skills" / "demo" / "run.py").write_text("mutated\n", encoding="utf-8")
                return True

            result = switch_active(
                profile,
                staged,
                staged_baseline=staged_baseline,
                pre_switch_check=mutate_after_validation,
            )

            self.assertEqual(result["classification"], "pre_switch_failure")
            self.assertEqual(
                compare_active_to_baseline(installed["baseline"], installed["active_root"])["classification"],
                "no_drift",
            )

    def test_evidence_references_must_be_symbolic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")

            with self.assertRaises(RuntimeContractError):
                switch_active(
                    profile,
                    staged,
                    staged_baseline=staged_baseline,
                    evidence_ref=str(root / "private-evidence.json"),
                )
            with self.assertRaises(RuntimeContractError):
                rollback_active(profile, "missing", evidence_ref="private:https://example.invalid")

    def test_rollback_rejects_absolute_target_through_rollback_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile = root / "release", root / "profile"
            outside = root / "outside-rollback"
            previous = outside / "previous"
            self.make_tree(release)
            installed = install_release(release, profile)
            self.make_tree(previous)
            os.symlink(outside, profile / "rollback")

            result = rollback_active(profile, previous)

            self.assertEqual(result["classification"], "rollback_failure_blocking")
            self.assertTrue(result["blocking"])
            self.assertTrue(previous.is_dir())
            self.assertTrue(installed["active_root"].is_dir())

    def test_sanitized_candidate_rejects_forged_private_path_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile = root / "release", root / "profile"
            self.make_tree(release)
            installed = install_release(release, profile)
            drift = compare_active_to_baseline(installed["baseline"], installed["active_root"])
            forged_raw = {
                "schema": RAW_DELTA_SCHEMA,
                "private": True,
                "counts": {key: 0 for key in ("modified", "added", "removed", "mode_changed")},
                "path_classes": {"/private/path": 1},
            }

            with self.assertRaises(RuntimeContractError):
                create_sanitized_candidate(drift, forged_raw, root / "private-candidates")

    def test_sanitized_candidate_requires_exact_raw_baseline_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile = root / "release", root / "profile"
            self.make_tree(release)
            installed = install_release(release, profile)
            drift = compare_active_to_baseline(installed["baseline"], installed["active_root"])
            forged_raw = {
                "schema": RAW_DELTA_SCHEMA,
                "private": True,
                "counts": {key: 0 for key in ("modified", "added", "removed", "mode_changed")},
                "path_classes": {},
            }

            with self.assertRaises(RuntimeContractError):
                create_sanitized_candidate(drift, forged_raw, root / "private-candidates")

    def test_rollback_rejects_modified_retained_target_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")
            switched = switch_active(profile, staged, staged_baseline=staged_baseline)
            previous = profile / "rollback" / switched["rollback_identity"]
            (previous / "skills" / "demo" / "run.py").write_text("tampered\n", encoding="utf-8")

            result = rollback_active(profile, switched["rollback_identity"])

            self.assertEqual(result["classification"], "rollback_failure_blocking")
            self.assertTrue((profile / "active").is_dir())
            self.assertTrue(previous.is_dir())

    def test_rollback_post_move_validation_failure_restores_original_active(self) -> None:
        from ragflow_skill_runtime import runtime_contracts as contracts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release, profile, staged = root / "release", root / "profile", root / "staged"
            self.make_tree(release)
            install_release(release, profile)
            self.make_tree(staged)
            staged_baseline = create_install_baseline(staged, root / "staged-baseline.json")
            switched = switch_active(profile, staged, staged_baseline=staged_baseline)
            previous = profile / "rollback" / switched["rollback_identity"]
            previous_inventory = contracts._file_inventory(previous)
            active_before = contracts._file_inventory(profile / "active")

            with patch.object(
                contracts,
                "_file_inventory",
                side_effect=[previous_inventory, RuntimeContractError("injected post-move failure")],
            ):
                result = rollback_active(profile, switched["rollback_identity"])

            self.assertEqual(result["classification"], "rollback_failure_blocking")
            self.assertEqual(contracts._file_inventory(profile / "active"), active_before)
            self.assertTrue(previous.is_dir())


if __name__ == "__main__":
    unittest.main()
