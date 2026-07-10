from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from schema_identity_check import SCHEMA, SchemaIdentity, run_schema_identity_check  # noqa: E402


class SchemaIdentityCheckTests(unittest.TestCase):
    def test_schema_identity_check_passes_for_public_suite(self) -> None:
        report = run_schema_identity_check()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["summary"]["failed_count"], 0)
        groups = set(report["groups"])
        for group in (
            "manifest",
            "quality",
            "benchmark",
            "query",
            "runtime",
            "trace",
            "diagnostic",
            "route",
            "topology",
            "kb_health",
            "release",
        ):
            self.assertIn(group, groups)
        keys = {check["key"] for check in report["checks"]}
        self.assertIn("version_date_drift_check", keys)
        self.assertIn("field_trial_metrics", keys)
        self.assertIn("retirement_observation_matrix", keys)
        self.assertIn("multimodal_benchmark", keys)
        self.assertIn("validation_query_suggestions", keys)
        self.assertIn("kb_artifact_consistency_report", keys)
        self.assertIn("kb_refresh_report", keys)
        self.assertIn("parameter_read_back_audit", keys)
        self.assertIn("parameter_contract_audit", keys)

    def test_retirement_observation_matrix_coverage_matches_schema_literal(self) -> None:
        report = run_schema_identity_check()

        check = next(item for item in report["checks"] if item["key"] == "retirement_observation_matrix")
        expected_identity = "ragflow_" + "retirement_observation_matrix_v1"
        self.assertNotIn(expected_identity, check["coverage"]["unmatched_patterns"])

    def test_schema_identity_check_reports_missing_source_or_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            coverage = root / "tests"
            source.mkdir()
            coverage.mkdir()
            (source / "producer.py").write_text('SCHEMA = "demo_schema_v1"\n', encoding="utf-8")
            identities = (
                SchemaIdentity(
                    key="demo",
                    group="demo",
                    identity="demo_schema_v1",
                    source_patterns=("demo_schema_v1",),
                    coverage_patterns=("demo_schema_v1",),
                ),
                SchemaIdentity(
                    key="missing-source",
                    group="demo",
                    identity="missing_source_schema_v1",
                    source_patterns=("missing_source_schema_v1",),
                    coverage_patterns=("demo_schema_v1",),
                ),
                SchemaIdentity(
                    key="missing-coverage",
                    group="demo",
                    identity="missing_coverage_schema_v1",
                    source_patterns=("demo_schema_v1",),
                    coverage_patterns=("missing_coverage_schema_v1",),
                ),
            )

            report = run_schema_identity_check(
                root=root,
                identities=identities,
                source_roots=(Path("src"),),
                coverage_roots=(Path("tests"),),
            )

        failed = set(report["summary"]["failed_identities"])
        self.assertFalse(report["ok"], report)
        self.assertIn("demo", failed)
        self.assertIn("missing-source", failed)
        self.assertIn("missing-coverage", failed)


if __name__ == "__main__":
    unittest.main()
