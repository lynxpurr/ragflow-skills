from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from release_hygiene_check import (  # noqa: E402
    CANONICAL_WORKFLOW_OWNERS,
    run_generated_report_safety_check,
    run_hygiene_check,
    run_suite_review,
    scan_stale_skill_references,
    scan_forbidden_patterns,
    validate_command_guidance_classification,
    validate_primary_guidance,
    validate_release_shape,
)


PUBLIC_SKILLS = (
    "ragflow-doc-to-md",
    "ragflow-canonical-review",
    "ragflow-kb-build",
    "ragflow-query",
)


def _write_skill_fixture(
    skills_root: Path,
    skill_name: str,
    *,
    description: str,
    body: str = "",
    host_reference: str = "shared host setup\n",
    onboarding_reference: str | None = "shared onboarding prompt\n",
) -> None:
    skill_root = skills_root / skill_name
    references = skill_root / "references"
    references.mkdir(parents=True, exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        f"""---
name: {skill_name}
description: {description}
---

# {skill_name}

{body}
""",
        encoding="utf-8",
    )
    (references / "host-agent-setup.md").write_text(host_reference, encoding="utf-8")
    if onboarding_reference is not None:
        (references / "user-onboarding-prompt.md").write_text(onboarding_reference, encoding="utf-8")


class ReleaseHygieneTests(unittest.TestCase):
    def test_hygiene_check_passes_for_built_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_hygiene_check(
                dist_dir=Path(tmp) / "dist",
                rebuild=True,
                scan_source=True,
            )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["findings"], [])
        self.assertTrue(payload["schema_identity"]["ok"])
        self.assertEqual(payload["schema_identity"]["schema"], "ragflow_schema_identity_check_v1")
        self.assertTrue(payload["manifest_schema"]["ok"])
        self.assertEqual(payload["manifest_schema"]["schema"], "ragflow_manifest_schema_check_v1")
        self.assertTrue(payload["rename_governance"]["ok"])
        self.assertEqual(payload["rename_governance"]["schema"], "ragflow_rename_governance_check_v1")
        self.assertTrue(payload["forward_test_prompts"]["ok"])
        self.assertEqual(payload["forward_test_prompts"]["schema"], "ragflow_forward_test_prompt_check_v1")
        self.assertTrue(payload["version_date_drift"]["ok"])
        self.assertEqual(payload["version_date_drift"]["schema"], "ragflow_version_date_drift_check_v1")
        self.assertTrue(payload["generated_report_safety"]["ok"])
        self.assertEqual(payload["generated_report_safety"]["schema"], "ragflow_generated_report_safety_check_v1")
        self.assertTrue(payload["generated_markdown_audit"]["ok"])
        self.assertEqual(payload["generated_markdown_audit"]["schema"], "ragflow_generated_markdown_audit_v1")
        self.assertTrue(payload["runtime_resilience_inventory"]["ok"])
        self.assertEqual(payload["runtime_resilience_inventory"]["schema"], "ragflow_runtime_resilience_inventory_v1")
        self.assertTrue(payload["document_lifecycle"]["ok"])
        self.assertEqual(payload["document_lifecycle"]["schema"], "ragflow_document_lifecycle_check_v1")

    def test_hygiene_check_fails_when_document_lifecycle_fails(self) -> None:
        lifecycle_payload = {
            "ok": False,
            "schema": "ragflow_document_lifecycle_check_v1",
            "findings": [{"check": "private_ipv4_literal", "path": "docs/example.md", "message": "sanitized"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch("release_hygiene_check.run_document_lifecycle_check", return_value=lifecycle_payload):
                payload = run_hygiene_check(
                    dist_dir=Path(tmp) / "dist",
                    rebuild=True,
                    scan_source=False,
                    schema_identity=False,
                    manifest_schema=False,
                    rename_governance=False,
                    forward_test_prompts=False,
                    version_date_drift=False,
                    generated_report_safety=False,
                    runtime_resilience_inventory=False,
                )

        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["document_lifecycle"], lifecycle_payload)

    def test_forbidden_private_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "skill" / "scripts"
            target.mkdir(parents=True)
            private_path = Path("/", "home", "fixture-user", "private")
            (target / "bad.py").write_text(
                f'BAD = "{private_path}"\n', encoding="utf-8"
            )

            findings = scan_forbidden_patterns(root, base=root)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "personal_home_path")
        self.assertEqual(findings[0].line, 1)

    def test_skill_doc_directory_is_ignored_as_local_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "skills" / "ragflow-doc-to-md" / "doc"
            target.mkdir(parents=True)
            private_source = Path(
                "/", "home", "fixture-user", "private", "source.pdf"
            )
            (target / "private-input.md").write_text(
                f"Local next-round input from {private_source}\n",
                encoding="utf-8",
            )

            findings = scan_forbidden_patterns(root, base=root)

        self.assertEqual(findings, [])

    def test_generated_report_safety_accepts_sanitized_report_with_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "query_endpoint_report.json").write_text(
                '{"schema":"ragflow_query_endpoint_report_v1","url":"https://<redacted:private-host>/v1"}\n',
                encoding="utf-8",
            )
            (reports / "query_endpoint_report.redaction.json").write_text(
                '{"schema":"ragflow_report_redaction_report_v1","ok":true,"summary":{"redaction_count":1}}\n',
                encoding="utf-8",
            )

            payload = run_generated_report_safety_check(root=root, report_roots=(Path("reports"),))

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["summary"]["placeholder_file_count"], 1)
        self.assertEqual(payload["summary"]["sidecar_file_count"], 1)

    def test_generated_report_safety_reports_unsanitized_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            private_config = Path(
                "/", "home", "fixture-user", ".ragflow", "config.local.yaml"
            )
            (reports / "bad_report.json").write_text(
                json.dumps(
                    {
                        "schema": "demo",
                        "message": "api_key=fake-generated-report-secret",
                        "path": str(private_config),
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            payload = run_generated_report_safety_check(root=root, report_roots=(Path("reports"),))

        checks = {finding["check"] for finding in payload["findings"]}
        self.assertFalse(payload["ok"], payload)
        self.assertIn("generated_report_sensitive_literal", checks)

    def test_suite_review_passes_for_public_skills(self) -> None:
        payload = run_suite_review()

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["schema"], "ragflow_skill_suite_review_v1")
        self.assertEqual(payload["summary"]["skill_count"], 4)
        self.assertEqual(payload["findings"], [])

    def test_primary_guidance_contract_passes_for_public_suite(self) -> None:
        findings, summary = validate_primary_guidance()

        self.assertEqual(findings, [])
        self.assertLessEqual(summary["nonblank_lines"]["SKILL.md"], 90)
        for skill_name in PUBLIC_SKILLS:
            self.assertLessEqual(summary["nonblank_lines"][f"skills/{skill_name}/SKILL.md"], 120)
        self.assertEqual(summary["canonical_workflow_count"], 12)
        self.assertEqual(summary["core_example_block_count"], 12)
        self.assertEqual(
            summary["workflow_example_counts"],
            {workflow: [1] for workflow in CANONICAL_WORKFLOW_OWNERS},
        )

    def test_primary_guidance_contract_reports_budget_structure_and_safety_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "skills"
            for skill_name in PUBLIC_SKILLS:
                _write_skill_fixture(
                    skills_root,
                    skill_name,
                    description=f"{skill_name} distinct workflow.",
                    body=(
                        "## Canonical Workflows\n\n"
                        "### Canonical workflow: duplicate\n\n"
                        "```bash\npython scripts/example.py\n```\n"
                        "```bash\npython scripts/duplicate.py\n```\n"
                    ),
                )
            root_skill = root / "SKILL.md"
            root_skill.write_text(
                "# Router\n\nManually POST /datasets to bypass a blocked result.\n"
                + "\n".join(f"line {index}" for index in range(100)),
                encoding="utf-8",
            )

            findings, _ = validate_primary_guidance(root=root)

        checks = {finding.check for finding in findings}
        self.assertIn("skill_surface_nonblank_budget", checks)
        self.assertIn("skill_surface_missing_section", checks)
        self.assertIn("skill_surface_duplicate_workflow", checks)
        self.assertIn("skill_surface_forbidden_guidance", checks)
        self.assertIn("skill_surface_missing_advanced_reference", checks)
        self.assertIn("skill_surface_workflow_example_count", checks)
        self.assertIn("skill_surface_core_example_count", checks)

    def test_suite_review_uses_the_reviewed_fixture_root_for_guidance_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "skills"
            skills_root.mkdir()
            with patch(
                "release_hygiene_check.validate_primary_guidance",
                return_value=([], {"source": "fixture"}),
            ) as primary, patch(
                "release_hygiene_check.validate_command_guidance_classification",
                return_value=([], {"source": "fixture"}),
            ) as command:
                payload = run_suite_review(skills_root=skills_root)

        primary.assert_called_once_with(root=root.resolve())
        command.assert_called_once_with(root=root.resolve())
        self.assertEqual(payload["summary"]["primary_guidance"], {"source": "fixture"})
        self.assertEqual(payload["summary"]["command_guidance"], {"source": "fixture"})

    def test_command_guidance_classification_covers_exact_public_inventory(self) -> None:
        findings, summary = validate_command_guidance_classification()

        self.assertEqual(findings, [])
        self.assertEqual(summary["discovered_command_count"], 106)
        self.assertEqual(summary["classified_command_count"], 106)
        self.assertEqual(
            summary["owner_counts"],
            {
                "ragflow-doc-to-md": 12,
                "ragflow-canonical-review": 2,
                "ragflow-kb-build": 58,
                "ragflow-query": 34,
            },
        )
        self.assertEqual(
            summary["tier_counts"],
            {"advanced": 87, "core": 12, "deprecated_candidate": 0, "internal_candidate": 7},
        )

    def test_release_shape_requires_advanced_workflow_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            payload = run_hygiene_check(
                dist_dir=dist,
                rebuild=True,
                scan_source=False,
                schema_identity=False,
                manifest_schema=False,
                rename_governance=False,
                forward_test_prompts=False,
                version_date_drift=False,
                generated_report_safety=False,
                runtime_resilience_inventory=False,
                document_lifecycle=False,
            )
            (dist / "ragflow-query" / "references" / "advanced-workflows.md").unlink()
            broken = validate_release_shape(dist)

        self.assertTrue(payload["ok"], payload)
        self.assertIn("release_shape", {finding.check for finding in broken})

    def test_suite_review_reports_static_drift_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            for skill_name in PUBLIC_SKILLS:
                _write_skill_fixture(
                    skills_root,
                    skill_name,
                    description=f"{skill_name} handles a distinct public workflow.",
                )
            _write_skill_fixture(
                skills_root,
                "ragflow-doc-to-md",
                description="Document conversion workflow.",
                body=(
                    "See [missing](references/missing.md).\n"
                    f"Do not mention {'de' + 'dao'} private adapters.\n"
                ),
                host_reference="drifted host setup\n",
            )
            (skills_root / "ragflow-query" / "references" / "user-onboarding-prompt.md").unlink()

            payload = run_suite_review(skills_root=skills_root, public_skills=PUBLIC_SKILLS)

        checks = {finding["check"] for finding in payload["findings"]}
        self.assertFalse(payload["ok"], payload)
        self.assertIn("skill_suite_broken_link", checks)
        self.assertIn("skill_suite_private_reference", checks)
        self.assertIn("skill_suite_missing_reference", checks)
        self.assertIn("skill_suite_reference_drift", checks)

    def test_stale_reference_scan_allows_chunk_marker_profile_token_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_root = root / "ragflow-doc-to-md"
            skill_root.mkdir()
            skill_file = skill_root / "SKILL.md"
            skill_file.write_text("Use profile chunk-markers-ragflux-like for boundary comparison.\n", encoding="utf-8")

            allowed = scan_stale_skill_references(skill_root, base=root)
            skill_file.write_text(
                "Use profile chunk-markers-ragflux-like.\nDo not publish ragflux package names.\n",
                encoding="utf-8",
            )
            blocked = scan_stale_skill_references(skill_root, base=root)

        self.assertEqual(allowed, [])
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].check, "skill_suite_stale_reference")

    def test_suite_review_reports_description_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            duplicate_description = "Convert and validate portable RAGFlow artifacts for host agents."
            _write_skill_fixture(skills_root, "ragflow-doc-to-md", description=duplicate_description)
            _write_skill_fixture(skills_root, "ragflow-kb-build", description=duplicate_description)
            _write_skill_fixture(
                skills_root,
                "ragflow-query",
                description="Run query retrieval for saved RAGFlow knowledge bases.",
            )

            payload = run_suite_review(skills_root=skills_root, public_skills=PUBLIC_SKILLS)

        checks = {finding["check"] for finding in payload["findings"]}
        self.assertFalse(payload["ok"], payload)
        self.assertIn("skill_suite_description_overlap", checks)

    def test_suite_review_reports_repeated_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            repeated_warning = "Do not put real keys in the skill folder."
            _write_skill_fixture(
                skills_root,
                "ragflow-doc-to-md",
                description="Convert documents into Markdown handoff bundles.",
                body=f"{repeated_warning}\n",
            )
            _write_skill_fixture(
                skills_root,
                "ragflow-kb-build",
                description="Build knowledge bases from Markdown handoff bundles.",
                body=f"{repeated_warning}\n",
            )
            _write_skill_fixture(
                skills_root,
                "ragflow-query",
                description="Query configured RAGFlow knowledge bases.",
            )

            payload = run_suite_review(skills_root=skills_root, public_skills=PUBLIC_SKILLS)

        checks = {finding["check"] for finding in payload["findings"]}
        self.assertFalse(payload["ok"], payload)
        self.assertIn("skill_suite_repeated_warning", checks)
        self.assertEqual(payload["summary"]["repeated_warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
