from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from ragflow_skill_runtime.kb_build import BuildDocument  # noqa: E402
from ragflow_skill_runtime.topology import (  # noqa: E402
    KB_ACTIVATION_PLAN_SCHEMA,
    KB_SPLIT_PLAN_SCHEMA,
    KB_TOPOLOGY_ADVICE_SCHEMA,
    create_kb_activation_plan,
    create_kb_split_plan,
    create_kb_topology_advice,
    render_activation_plan_markdown,
    render_split_plan_markdown,
    render_topology_advice_markdown,
)


class TopologyAdviceTests(unittest.TestCase):
    def test_topology_advice_reports_create_merge_and_split_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            hr = docs / "hr-payroll.md"
            finance = docs / "finance-tax.md"
            hr.write_text(
                "# Payroll Policy\n\n"
                + "Payroll retention employee benefits onboarding policy. " * 40,
                encoding="utf-8",
            )
            finance.write_text(
                "# Tax Policy\n\n"
                + "Payroll tax invoice revenue finance policy. " * 35,
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {"path": str(hr), "metadata": {"domain": "hr", "topic": "Payroll Policy"}},
                            {"path": str(finance), "metadata": {"domain": "finance", "topic": "Tax Policy"}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            hints = root / "retrieval_hints.json"
            hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [
                            {"term": "payroll policy"},
                            {"term": "employee benefits"},
                        ],
                        "question_candidates": [
                            {
                                "question": "What is the payroll retention policy?",
                                "type": "section_summary",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            route = root / "routes.json"
            route.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": "kb:finance",
                                "dataset_id": "ds-finance",
                                "hints": ["finance", "tax", "payroll"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = create_kb_topology_advice(
                kb_name="kb:payroll-policy",
                documents=[BuildDocument(hr), BuildDocument(finance)],
                metadata_path=metadata,
                retrieval_hints_path=hints,
                route_config_path=route,
                future_growth="high",
            )
            markdown = render_topology_advice_markdown(report)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], KB_TOPOLOGY_ADVICE_SCHEMA)
        self.assertTrue(report["advisory_only"])
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["signals"]["minimum_useful_corpus_size"]["status"], "sufficient")
        self.assertEqual(report["signals"]["future_growth"]["level"], "high")
        self.assertEqual(report["signals"]["semantic_overlap"]["candidates"][0]["kb"], "kb:finance")
        self.assertTrue(report["signals"]["split"]["split_review_recommended"])
        self.assertGreaterEqual(len(report["anchor_query_pairs"]), 1)
        self.assertIn("RAGFlow KB Topology Advice", markdown)

    def test_topology_advice_can_run_without_route_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "sample.md"
            doc.write_text("# Sample\n\nTiny standalone note.\n", encoding="utf-8")

            report = create_kb_topology_advice(
                kb_name="kb:sample",
                documents=[doc],
                future_growth="low",
            )

        self.assertEqual(report["signals"]["terminology_independence"]["status"], "unknown")
        self.assertEqual(report["signals"]["minimum_useful_corpus_size"]["status"], "thin")
        self.assertEqual(report["recommendation"]["action"], "stage_until_larger")

    def test_split_plan_groups_documents_and_boundary_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            payroll = docs / "payroll.md"
            tax = docs / "tax.md"
            payroll.write_text(
                "# Payroll Policy\n\n"
                + "Payroll benefits onboarding retention employee policy. " * 45,
                encoding="utf-8",
            )
            tax.write_text(
                "# Tax Policy\n\n"
                + "Tax invoice revenue filing finance policy. " * 45,
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_metadata_v1",
                        "documents": [
                            {"path": str(payroll), "metadata": {"domain": "hr", "topic": "Payroll Policy"}},
                            {"path": str(tax), "metadata": {"domain": "finance", "topic": "Tax Policy"}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            hints = root / "retrieval_hints.json"
            hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "question_candidates": [
                            {
                                "question": "How does payroll retention work?",
                                "type": "exact_fact",
                                "source_document": str(payroll),
                            },
                            {
                                "question": "How are tax invoices filed?",
                                "type": "exact_fact",
                                "source_document": str(tax),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = create_kb_split_plan(
                kb_name="kb:ops",
                documents=[BuildDocument(payroll), BuildDocument(tax)],
                metadata_path=metadata,
                retrieval_hints_path=hints,
            )
            markdown = render_split_plan_markdown(report)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["schema"], KB_SPLIT_PLAN_SCHEMA)
        self.assertTrue(report["advisory_only"])
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["summary"]["split_group_count"], 2)
        self.assertEqual(report["recommendation"]["action"], "split_before_upload")
        self.assertGreaterEqual(len(report["boundary_queries"]), 1)
        suggested = {group["suggested_kb_name"] for group in report["split_groups"]}
        self.assertIn("kb:ops-finance", suggested)
        self.assertIn("kb:ops-hr", suggested)
        self.assertIn("RAGFlow KB Split Plan", markdown)

    def test_activation_plan_reports_route_readiness_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_manifest = root / "kb_manifest.json"
            doc_manifest = root / "doc_manifest.json"
            snapshot = root / "chunk_snapshot.json"
            routing = root / "routing.json"
            hints = root / "retrieval_hints.json"
            route_tests = root / "route_tests.json"
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "ds-activation", "name": "kb:activation"},
                        "documents": [
                            {
                                "document_id": "doc-activation",
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                                "status": "done",
                                "chunk_count": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            doc_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "documents": [
                            {
                                "source_path": "source.md",
                                "markdown_path": "documents/source.md",
                            }
                        ],
                        "quality_gate": {"status": "PASS"},
                    }
                ),
                encoding="utf-8",
            )
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "dataset_id": "ds-activation",
                                "document_id": "doc-activation",
                                "chunk_id": "chunk-1",
                                "content": "Activation smoke routing evidence.",
                            },
                            {
                                "dataset_id": "ds-activation",
                                "document_id": "doc-activation",
                                "chunk_id": "chunk-2",
                                "content": "Route-test activation coverage evidence.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            routing.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "knowledge_bases": [
                            {
                                "name": "kb:activation",
                                "dataset_id": "ds-activation",
                                "hints": ["activation smoke", "route test"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "keyword_candidates": [{"term": "activation smoke"}],
                        "question_candidates": [{"question": "How does activation smoke routing work?"}],
                    }
                ),
                encoding="utf-8",
            )
            route_tests.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "activation-1",
                                "question": "How does activation smoke routing work?",
                                "expected_kb": "kb:activation",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = create_kb_activation_plan(
                kb_manifest_path=kb_manifest,
                doc_manifest_path=doc_manifest,
                route_config_path=routing,
                retrieval_hints_path=hints,
                chunk_snapshot_path=snapshot,
                route_tests_path=route_tests,
            )
            markdown = render_activation_plan_markdown(report)

        self.assertEqual(report["schema"], KB_ACTIVATION_PLAN_SCHEMA)
        self.assertTrue(report["advisory_only"])
        self.assertEqual(report["mutation"], "none")
        self.assertEqual(report["recommendation"]["action"], "ready_for_activation_review")
        self.assertEqual(report["checks"]["route_config_registration"]["status"], "ready")
        self.assertEqual(report["checks"]["route_test_readiness"]["passed_target_query_count"], 1)
        self.assertEqual(report["route_entry_suggestion"]["dataset_id"], "ds-activation")
        self.assertIn("RAGFlow KB Activation Plan", markdown)


if __name__ == "__main__":
    unittest.main()
