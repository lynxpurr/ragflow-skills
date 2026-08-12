from __future__ import annotations

import json
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.runtime_contracts import (
    ARCHIVE_INVENTORY_SCHEMA,
    COUNT_ONLY_DRIFT_SCHEMA,
    archive_inventory,
)
from runtime_contracts_check import run_count_only_drift_check, run_runtime_contracts_check


class RuntimeContractsCheckTests(unittest.TestCase):
    def test_archive_inventory_is_deterministic_and_source_isolation_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "demo.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                payload = root / "payload.txt"
                payload.write_text("x\n", encoding="utf-8")
                tar.add(payload, arcname="demo/payload.txt")
                runtime = root / "runtime_contracts.py"
                runtime.write_text(
                    'BASELINE_SCHEMA = "ragflow_runtime_install_baseline_v1"\n',
                    encoding="utf-8",
                )
                tar.add(
                    runtime,
                    arcname="demo/scripts/_vendor/ragflow_skill_runtime/runtime_contracts.py",
                )
            inventory = archive_inventory(archive)
            self.assertEqual(inventory["schema"], ARCHIVE_INVENTORY_SCHEMA)
            self.assertEqual(inventory["file_count"], 2)
            report = run_runtime_contracts_check(
                archive_paths=[archive],
                expected_inventory_digests={archive.name: inventory["inventory_digest"]},
                source_root=root / "source",
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["schema"], "ragflow_runtime_contracts_check_v1")
            self.assertEqual(report["summary"]["archive_count"], 1)
            self.assertTrue(report["summary"]["source_isolation"])
            self.assertEqual(
                report["archives"][0]["source_isolation"]["classification"],
                "static_source_isolation_passed",
            )
            self.assertNotIn(str(root), json.dumps(report))

    def test_archive_inventory_rejects_unsafe_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 1
                tar.addfile(info, fileobj=__import__("io").BytesIO(b"x"))
            with self.assertRaises(ValueError):
                archive_inventory(archive)

    def test_check_classifies_unreadable_archive_without_private_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "broken.tar.gz"
            archive.write_text("not an archive\n", encoding="utf-8")
            report = run_runtime_contracts_check(archive_paths=[archive])

            self.assertFalse(report["ok"])
            self.assertEqual(report["summary"]["finding_count"], 1)
            self.assertEqual(report["findings"][0]["archive_name"], "broken.tar.gz")
            self.assertNotIn(str(archive.parent), json.dumps(report))

    def test_source_isolation_blocks_archive_import_that_reads_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            sentinel = source / "sentinel.txt"
            sentinel.write_text("do not read\n", encoding="utf-8")
            archive = root / "source-reader.tar.gz"
            module_text = (
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).read_text(encoding='utf-8')\n"
                'BASELINE_SCHEMA = "ragflow_runtime_install_baseline_v1"\n'
            ).encode("utf-8")
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo(
                    "demo/scripts/_vendor/ragflow_skill_runtime/runtime_contracts.py"
                )
                info.size = len(module_text)
                tar.addfile(info, fileobj=io.BytesIO(module_text))

            report = run_runtime_contracts_check(
                archive_paths=[archive],
                expected_inventory_digests={
                    archive.name: archive_inventory(archive)["inventory_digest"]
                },
                source_root=source,
            )

            self.assertFalse(report["ok"])
            self.assertFalse(report["summary"]["source_isolation"])
            self.assertEqual(
                report["archives"][0]["source_isolation"]["classification"],
                "static_source_reference_rejected",
            )
            self.assertNotIn(str(root), json.dumps(report))

    def test_archive_inventory_rejects_duplicate_normalized_member_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "duplicate.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name, content in (("demo/payload.txt", b"a"), ("demo/./payload.txt", b"b")):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    tar.addfile(info, fileobj=io.BytesIO(content))

            with self.assertRaises(ValueError):
                archive_inventory(archive)

    def test_archive_check_blocks_missing_expected_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "demo.tar.gz"
            module_text = b'BASELINE_SCHEMA = "ragflow_runtime_install_baseline_v1"\n'
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo(
                    "demo/scripts/_vendor/ragflow_skill_runtime/runtime_contracts.py"
                )
                info.size = len(module_text)
                tar.addfile(info, fileobj=io.BytesIO(module_text))

            report = run_runtime_contracts_check(archive_paths=[archive])

            self.assertFalse(report["ok"])
            self.assertEqual(report["archives"][0]["classification"], "missing_expected_inventory")

    def test_count_only_drift_check_never_emits_paths_or_raw_details(self) -> None:
        from ragflow_skill_runtime.runtime_contracts import install_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            active_file = release / "skills" / "demo" / "run.py"
            active_file.parent.mkdir(parents=True)
            active_file.write_text("baseline\n", encoding="utf-8")
            installed = install_release(release, root / "profile")
            active = installed["active_root"]
            (active / "skills" / "demo" / "run.py").write_text("private raw change\n", encoding="utf-8")

            report = run_count_only_drift_check(
                baseline_path=installed["baseline_path"],
                active_root=active,
            )

            serialized = json.dumps(report)
            self.assertTrue(report["ok"])
            self.assertEqual(report["schema"], COUNT_ONLY_DRIFT_SCHEMA)
            self.assertEqual(report["counts"]["modified"], 1)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("run.py", serialized)
            self.assertNotIn("private raw change", serialized)


if __name__ == "__main__":
    unittest.main()
