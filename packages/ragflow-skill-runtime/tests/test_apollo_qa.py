from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.apollo_qa import (
    APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA,
    APOLLO_TABLE_QA_FIXTURE_SCHEMA,
    APOLLO_TABLE_QA_FIXTURE_VALIDATION_REPORT_SCHEMA,
    APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA,
    APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA,
    APOLLO_TABLE_QA_JUDGE_REVIEW_REPORT_SCHEMA,
    create_apollo_table_qa_judge_request,
    evaluate_apollo_table_qa_results,
    render_apollo_table_qa_markdown,
    review_apollo_table_qa_judge_candidate,
    validate_apollo_table_qa_fixture,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ApolloQaTests(unittest.TestCase):
    def test_validate_fixture_accepts_sanitized_table_qa_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "apollo-fixture.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "metadata": {"name": "sanitized-apollo-table-qa", "item_count": 1},
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the MPEE value for the compact model?",
                            "table_source": "specification-table",
                            "difficulty": "header_alias",
                            "strict_terms": ["$MPE_E$", "0.02 mm"],
                            "normalized_facts": [
                                {"id": "mpe_e", "canonical": "$MPE_E$", "aliases": ["MPE_E", "MPEE", "MPEe"]},
                                {"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]},
                            ],
                        }
                    ],
                },
            )

            report = validate_apollo_table_qa_fixture(fixture)

        self.assertEqual(report["schema"], APOLLO_TABLE_QA_FIXTURE_VALIDATION_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["item_count"], 1)
        self.assertEqual(report["summary"]["strict_term_count"], 2)
        self.assertEqual(report["summary"]["normalized_fact_count"], 2)

    def test_validate_fixture_summarizes_strict_recall_coverage_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "apollo-fixture.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "metadata": {"name": "sanitized-apollo-strict-table-coverage"},
                    "items": [
                        {
                            "id": "apollo-numeric-row",
                            "question": "What value appears in row 7?",
                            "difficulty": "numeric_row",
                            "coverage_categories": ["numeric_row"],
                            "strict_terms": ["row 7", "0.02 mm"],
                        },
                        {
                            "id": "apollo-units",
                            "question": "What torque is listed?",
                            "difficulty": "unit_value",
                            "coverage_categories": ["unit"],
                            "strict_terms": ["12 N·m"],
                        },
                        {
                            "id": "apollo-model-name",
                            "question": "Which models are compared?",
                            "difficulty": "model_name",
                            "coverage_categories": ["model_name"],
                            "strict_terms": ["HH-A", "HH-B"],
                        },
                        {
                            "id": "apollo-cross-column",
                            "question": "What is the MPEE value for HH-A?",
                            "difficulty": "cross_column_lookup",
                            "coverage_categories": ["cross_column_lookup"],
                            "strict_terms": ["HH-A", "$MPE_E$", "0.02 mm"],
                        },
                    ],
                },
            )

            report = validate_apollo_table_qa_fixture(fixture)
            markdown = render_apollo_table_qa_markdown(report, title="APOLLO Table QA Fixture Validation")

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["item_count"], 4)
        self.assertEqual(report["summary"]["coverage_category_count"], 4)
        self.assertEqual(
            report["coverage"]["category_counts"],
            {
                "cross_column_lookup": 1,
                "model_name": 1,
                "numeric_row": 1,
                "unit": 1,
            },
        )
        self.assertEqual(report["coverage"]["missing_recommended_categories"], [])
        self.assertIn("coverage_category_count", markdown)

    def test_validate_fixture_rejects_private_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "apollo-fixture.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "metadata": {"source": "/home/example/private/apollo.pdf"},
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the value?",
                            "strict_terms": ["0.02 mm"],
                        }
                    ],
                },
            )

            report = validate_apollo_table_qa_fixture(fixture)

        self.assertFalse(report["ok"])
        self.assertTrue(any(issue["code"] == "private_literal" for issue in report["issues"]))

    def test_evaluate_results_separates_strict_and_normalized_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            results = root / "apollo-results.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "metadata": {"name": "sanitized-apollo-table-qa"},
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the MPEE value?",
                            "strict_terms": ["$MPE_E$", "0.02 mm"],
                            "normalized_facts": [
                                {"id": "mpe_e", "canonical": "$MPE_E$", "aliases": ["MPE_E", "MPEE", "MPEe"]},
                                {"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]},
                            ],
                        },
                        {
                            "id": "apollo-q2",
                            "question": "What is the operating temperature range?",
                            "strict_terms": ["18°C-22°C"],
                            "normalized_facts": [
                                {"id": "temperature", "canonical": "18°C-22°C", "aliases": ["18℃ - 22℃", "18 C to 22 C"]},
                            ],
                        },
                    ],
                },
            )
            _write_json(
                results,
                {
                    "results": [
                        {
                            "id": "apollo-q1",
                            "answer": "The MPEe value is 0.02mm.",
                            "top_chunks": [{"content": "Header $MPE_E$ lists 0.02 mm for the compact model."}],
                        },
                        {
                            "id": "apollo-q2",
                            "answer": "The range is 18℃ - 22℃.",
                            "top_chunks": [{"content_with_weight": "Operating temperature: 18°C-22°C."}],
                        },
                    ]
                },
            )

            report = evaluate_apollo_table_qa_results(fixture_path=fixture, results_path=results, target="answer")
            markdown = render_apollo_table_qa_markdown(report)

        self.assertEqual(report["schema"], APOLLO_TABLE_QA_EVALUATION_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["case_count"], 2)
        self.assertEqual(report["summary"]["normalized_answer_pass_count"], 2)
        self.assertEqual(report["summary"]["strict_answer_pass_count"], 0)
        self.assertEqual(report["summary"]["normalized_only_answer_correction_count"], 2)
        self.assertIn("normalized_only_answer_correction_count", markdown)

    def test_evaluate_retrieval_target_handles_retrieval_only_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            results = root / "apollo-results.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "Which table contains the torque value?",
                            "strict_terms": ["12 N·m"],
                            "normalized_facts": [{"id": "torque", "canonical": "12 N·m", "aliases": ["12Nm"]}],
                        }
                    ],
                },
            )
            _write_json(
                results,
                {
                    "cases": [
                        {
                            "query_id": "apollo-q1",
                            "chunks": [{"content": "The HH-A torque row lists 12Nm in the specification table."}],
                        }
                    ]
                },
            )

            report = evaluate_apollo_table_qa_results(fixture_path=fixture, results_path=results, target="retrieval")

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["answer_case_count"], 0)
        self.assertEqual(report["summary"]["normalized_retrieval_pass_count"], 1)

    def test_judge_request_packages_baseline_and_no_llm_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            results = root / "apollo-results.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the MPEE value?",
                            "strict_terms": ["$MPE_E$", "0.02 mm"],
                            "normalized_facts": [
                                {"id": "mpe_e", "canonical": "$MPE_E$", "aliases": ["MPEE"]},
                                {"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]},
                            ],
                        }
                    ],
                },
            )
            _write_json(
                results,
                {
                    "results": [
                        {
                            "id": "apollo-q1",
                            "answer": "The MPEE value is 0.02mm.",
                            "top_chunks": [{"content": "Header $MPE_E$ lists 0.02 mm."}],
                        }
                    ]
                },
            )

            request = create_apollo_table_qa_judge_request(fixture_path=fixture, results_path=results, target="answer")
            markdown = render_apollo_table_qa_markdown(request, title="APOLLO Table QA Judge Request")

        self.assertEqual(request["schema"], APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA)
        self.assertTrue(request["ok"], request["issues"])
        self.assertFalse(request["llm_invoked"])
        self.assertEqual(request["summary"]["script_owned_llm_calls"], 0)
        self.assertEqual(request["summary"]["baseline_pass_count"], 1)
        self.assertEqual(request["cases"][0]["baseline"]["status"], "PASS")
        self.assertIn("apollo-q1:answer", {item["id"] for item in request["cases"][0]["evidence"]})
        self.assertIn("llm_invoked", markdown)

    def test_judge_review_accepts_advisory_generated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            results = root / "apollo-results.json"
            request_path = root / "judge-request.json"
            candidate_path = root / "judge-candidate.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the MPEE value?",
                            "strict_terms": ["$MPE_E$", "0.02 mm"],
                            "normalized_facts": [
                                {"id": "mpe_e", "canonical": "$MPE_E$", "aliases": ["MPEE"]},
                                {"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]},
                            ],
                        }
                    ],
                },
            )
            _write_json(
                results,
                {
                    "results": [
                        {
                            "id": "apollo-q1",
                            "answer": "The MPEE value is 0.02mm.",
                            "top_chunks": [{"content": "Header $MPE_E$ lists 0.02 mm."}],
                        }
                    ]
                },
            )
            request = create_apollo_table_qa_judge_request(fixture_path=fixture, results_path=results, target="answer")
            _write_json(request_path, request)
            _write_json(
                candidate_path,
                {
                    "schema": APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA,
                    "advisory": True,
                    "generated": True,
                    "case_verdicts": [
                        {
                            "id": "apollo-q1",
                            "verdict": "pass",
                            "rationale": "The answer states the normalized value and request evidence cites the exact table header.",
                            "evidence_refs": ["apollo-q1:answer", "apollo-q1:retrieval:1"],
                        }
                    ],
                },
            )

            report = review_apollo_table_qa_judge_candidate(request_path=request_path, candidate_path=candidate_path)
            markdown = render_apollo_table_qa_markdown(report, title="APOLLO Table QA Judge Review")

        self.assertEqual(report["schema"], APOLLO_TABLE_QA_JUDGE_REVIEW_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["pass"], 1)
        self.assertEqual(report["summary"]["evidence_ref_count"], 2)
        self.assertIn("candidate_case_count", markdown)

    def test_judge_request_keeps_failed_baseline_as_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "apollo-fixture.json"
            results = root / "apollo-results.json"
            _write_json(
                fixture,
                {
                    "schema": APOLLO_TABLE_QA_FIXTURE_SCHEMA,
                    "items": [
                        {
                            "id": "apollo-q1",
                            "question": "What is the missing value?",
                            "strict_terms": ["0.02 mm"],
                            "normalized_facts": [{"id": "value", "canonical": "0.02 mm", "aliases": ["0.02mm"]}],
                        }
                    ],
                },
            )
            _write_json(results, {"results": [{"id": "apollo-q1", "answer": "The value is not shown."}]})

            request = create_apollo_table_qa_judge_request(fixture_path=fixture, results_path=results, target="answer")

        self.assertTrue(request["ok"], request["issues"])
        self.assertFalse(request["summary"]["baseline_ok"])
        self.assertEqual(request["summary"]["baseline_fail_count"], 1)
        self.assertEqual(request["summary"]["baseline_errors"], 1)

    def test_judge_review_rejects_unmarked_and_unknown_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "judge-request.json"
            candidate_path = root / "judge-candidate.json"
            _write_json(
                request_path,
                {
                    "schema": APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA,
                    "llm_invoked": False,
                    "request_hash": "hash",
                    "cases": [
                        {
                            "id": "apollo-q1",
                            "baseline": {"status": "PASS"},
                            "evidence": [{"id": "apollo-q1:answer", "case_id": "apollo-q1", "source": "answer"}],
                        }
                    ],
                },
            )
            _write_json(
                candidate_path,
                {
                    "schema": APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA,
                    "case_verdicts": [
                        {"id": "apollo-q2", "verdict": "pass", "evidence_refs": ["apollo-q1:answer"]}
                    ],
                },
            )

            report = review_apollo_table_qa_judge_candidate(request_path=request_path, candidate_path=candidate_path)

        self.assertFalse(report["ok"])
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("apollo_table_qa_judge_not_advisory", issue_codes)
        self.assertIn("apollo_table_qa_judge_not_generated", issue_codes)
        self.assertIn("apollo_table_qa_judge_unknown_case", issue_codes)
        self.assertIn("apollo_table_qa_judge_missing_case", issue_codes)

    def test_judge_review_rejects_pass_over_failed_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "judge-request.json"
            candidate_path = root / "judge-candidate.json"
            _write_json(
                request_path,
                {
                    "schema": APOLLO_TABLE_QA_JUDGE_REQUEST_SCHEMA,
                    "llm_invoked": False,
                    "request_hash": "hash",
                    "cases": [
                        {
                            "id": "apollo-q1",
                            "baseline": {"status": "FAIL"},
                            "evidence": [{"id": "apollo-q1:answer", "case_id": "apollo-q1", "source": "answer"}],
                        }
                    ],
                },
            )
            _write_json(
                candidate_path,
                {
                    "schema": APOLLO_TABLE_QA_JUDGE_CANDIDATE_SCHEMA,
                    "advisory": True,
                    "generated": True,
                    "case_verdicts": [
                        {"id": "apollo-q1", "verdict": "pass", "evidence_refs": ["apollo-q1:answer"]}
                    ],
                },
            )

            report = review_apollo_table_qa_judge_candidate(request_path=request_path, candidate_path=candidate_path)

        self.assertFalse(report["ok"])
        self.assertTrue(any(issue["code"] == "apollo_table_qa_judge_baseline_override" for issue in report["issues"]))
