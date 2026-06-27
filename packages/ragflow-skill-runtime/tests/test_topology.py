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
    KB_SPLIT_PLAN_SCHEMA,
    KB_TOPOLOGY_ADVICE_SCHEMA,
    create_kb_split_plan,
    create_kb_topology_advice,
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


if __name__ == "__main__":
    unittest.main()
