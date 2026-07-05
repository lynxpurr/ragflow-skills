from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.query_table_strategy import (
    TABLE_QUERY_STRATEGY_REPORT_SCHEMA,
    build_table_query_strategy_report,
    render_table_query_strategy_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class QueryTableStrategyTests(unittest.TestCase):
    def test_builds_hint_expansion_and_fusion_plan_from_table_review_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            hints = root / "retrieval_hints.json"
            direct_results = root / "direct-results.json"
            fusion_results = root / "fusion-results.json"
            _write_json(
                fixture,
                {
                    "schema": "apollo_table_qa_fixture_v1",
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "HH-A 和 HH-B 的额定扭矩哪个更高？",
                            "difficulty": "cross_table_comparison",
                            "metadata": {"query_type": "cross_table_comparison", "model_labels": ["HH-A", "HH-B"]},
                            "strict_terms": ["HH-A", "HH-B", "12 N·m", "10 N·m"],
                            "normalized_facts": [
                                {"id": "hh_a", "canonical": "HH-A"},
                                {"id": "hh_b", "canonical": "HH-B"},
                                {"id": "hh_a_torque", "canonical": "12 N·m", "aliases": ["12Nm"]},
                                {"id": "hh_b_torque", "canonical": "10 N·m", "aliases": ["10Nm"]},
                            ],
                        },
                        {
                            "id": "apollo-q2",
                            "question": "MPEE 对应的误差值是多少？",
                            "difficulty": "header_alias",
                            "strict_terms": ["$MPE_E$", "0.02 mm"],
                            "normalized_facts": [
                                {"id": "mpe_e", "canonical": "$MPE_E$", "aliases": ["MPEE", "MPE_E"]},
                                {"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]},
                            ],
                        },
                    ],
                },
            )
            _write_json(
                hints,
                {
                    "schema": "ragflow_retrieval_hints_v1",
                    "table_artifacts": [
                        {
                            "kind": "table",
                            "source": "html_table",
                            "document": "documents/apollo.md",
                            "caption": "HH-A / HH-B 扭矩参数",
                            "source_heading": "HH 系列扭矩参数",
                            "model_label_candidates": ["HH-A", "HH-B"],
                            "semantic_risk_score": 5,
                            "semantic_risks": [
                                {"code": "multi_level_header_review", "severity": "warning"},
                                {"code": "merged_cells_review", "severity": "warning"},
                                {"code": "multi_model_header_review", "severity": "warning"},
                            ],
                            "review_required": True,
                            "header_depth": 2,
                            "rowspan_count": 1,
                            "colspan_count": 2,
                        },
                        {
                            "kind": "table",
                            "source": "html_table",
                            "document": "documents/apollo.md",
                            "caption": "APOLLO 误差规格",
                            "source_heading": "术语表",
                            "model_label_candidates": ["APOLLO-H"],
                            "semantic_risk_score": 0,
                            "semantic_risks": [],
                            "review_required": False,
                        },
                    ],
                    "table_term_alias_candidates": [
                        {
                            "source_label": "$MPE_E$",
                            "normalized_label": "MPEE",
                            "candidate_aliases": ["MPE_E", "MPEE"],
                            "document": "documents/apollo.md",
                            "table_index": 2,
                            "caption": "APOLLO 误差规格",
                            "requires_review": True,
                            "rewrites_markdown": False,
                        }
                    ],
                },
            )
            _write_json(
                direct_results,
                {
                    "results": [
                        {"id": "apollo-q1", "chunks": [{"content": "HH-A 额定扭矩为 12Nm。"}]},
                        {"id": "apollo-q2", "chunks": [{"content": "MPEe value is 0.02mm."}]},
                    ]
                },
            )
            _write_json(
                fusion_results,
                {
                    "results": [
                        {"id": "apollo-q1", "chunks": [{"content": "HH-A 额定扭矩 12Nm；HH-B 额定扭矩 10Nm。"}]},
                        {"id": "apollo-q2", "chunks": [{"content": "$MPE_E$ value is 0.02 mm."}]},
                    ]
                },
            )

            report = build_table_query_strategy_report(
                fixture_path=fixture,
                retrieval_hints_path=hints,
                strategy_result_paths={"direct": direct_results, "fusion": fusion_results},
            )
            markdown = render_table_query_strategy_markdown(report)

        by_case = {case["id"]: case for case in report["cases"]}
        q1_queries = {query["kind"]: query["query"] for query in by_case["apollo-q1"]["planned_queries"]}
        q2_queries = {query["kind"]: query["query"] for query in by_case["apollo-q2"]["planned_queries"]}
        evaluations = {item["strategy"]: item for item in report["strategy_evaluations"]}

        self.assertEqual(report["schema"], TABLE_QUERY_STRATEGY_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["llm_calls"], 0)
        self.assertEqual(report["ragflow_calls"], 0)
        self.assertTrue(by_case["apollo-q1"]["classification"]["cross_table"])
        self.assertIn("rrf_fusion", {strategy["id"] for strategy in by_case["apollo-q1"]["strategies"]})
        self.assertIn("multi_model_header_review", by_case["apollo-q1"]["review_hints_used"]["semantic_risk_codes"])
        self.assertIn("HH 系列扭矩参数", q1_queries["table_hint"])
        self.assertIn("$MPE_E$", q2_queries["term_alias_hint"])
        self.assertEqual(evaluations["direct"]["summary"]["normalized_retrieval_pass_count"], 1)
        self.assertEqual(evaluations["fusion"]["summary"]["normalized_retrieval_pass_count"], 2)
        self.assertIn("RAGFlow Table Query Strategy Report", markdown)


if __name__ == "__main__":
    unittest.main()
