from __future__ import annotations

import unittest

from ragflow_skill_runtime.agentic import (
    AGENTIC_ANSWER_REQUEST_SCHEMA,
    AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA,
    AGENTIC_PLAN_SCHEMA,
    AGENTIC_TRACE_SCHEMA,
    AgenticPlanError,
    HOST_SYNTHESIS_CONTRACT_SCHEMA,
    build_agentic_execution_trace,
    build_agentic_plan,
    build_host_synthesis_contract,
    create_agentic_answer_request,
    render_agentic_answer_request_markdown,
    render_agentic_answer_review_markdown,
    render_agentic_plan_markdown,
    review_agentic_answer,
)


class AgenticPlanTests(unittest.TestCase):
    def test_agentic_plan_decomposes_comparison_without_execution(self) -> None:
        plan = build_agentic_plan(
            "Compare runtime configuration and metadata routing tradeoffs",
            max_subqueries=3,
            reflection_budget=1,
        )
        markdown = render_agentic_plan_markdown(plan)

        self.assertEqual(plan["schema"], AGENTIC_PLAN_SCHEMA)
        self.assertEqual(plan["trace_template"]["schema"], AGENTIC_TRACE_SCHEMA)
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["classification"]["intent"], "comparison")
        self.assertIn("comparison marker detected", plan["classification"]["intent_reasons"])
        self.assertGreaterEqual(plan["summary"]["retrieval_query_count"], 2)
        self.assertEqual(plan["summary"]["llm_calls"], 0)
        self.assertEqual(plan["summary"]["retrieval_calls"], 0)
        self.assertEqual(plan["trace_template"]["estimated_tokens"], 0)
        self.assertEqual(plan["trace_template"]["estimated_cost_usd"], 0.0)
        self.assertEqual(plan["trace_template"]["token_estimate"]["script_llm_total_tokens"], 0)
        self.assertIsNone(plan["trace_template"]["cost_trace"]["retrieval_estimated_usd"])
        self.assertIn("RAGFlow Agentic Plan", markdown)
        self.assertIn("subquery", markdown)

    def test_agentic_execution_trace_records_cost_and_latency_without_llm(self) -> None:
        plan = build_agentic_plan(
            "Compare runtime configuration and metadata routing tradeoffs",
            max_subqueries=2,
            reflection_budget=1,
        )
        trace = build_agentic_execution_trace(
            plan,
            retrieval_call_count=3,
            retrieval_latency_ms=12.34567,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        )

        self.assertEqual(trace["schema"], AGENTIC_TRACE_SCHEMA)
        self.assertEqual(trace["status"], "retrieval_executed")
        self.assertEqual(trace["retrieval_calls"], 3)
        self.assertEqual(trace["planned_retrieval_call_count"], 3)
        self.assertEqual(trace["reflection_budget"], 1)
        self.assertEqual(trace["reflection_iterations"], 0)
        self.assertEqual(trace["latency_ms"], 12.346)
        self.assertIsNone(trace["model"])
        self.assertEqual(trace["estimated_tokens"], 0)
        self.assertEqual(trace["token_estimate"]["script_llm_total_tokens"], 0)
        self.assertEqual(trace["estimated_cost_usd"], 0.0)
        self.assertEqual(trace["cost_trace"]["estimated_total_usd"], 0.0)
        self.assertFalse(trace["script_owned_synthesis"])

    def test_host_synthesis_contract_exposes_audit_compatible_citations(self) -> None:
        plan = build_agentic_plan(
            "Compare runtime configuration and metadata routing tradeoffs",
            max_subqueries=2,
        )
        evidence = [
            {"rank": 1, "citation_id": "[1]", "content_preview": "runtime config evidence"},
            {"rank": 2, "citation_id": "[2]", "content_preview": "metadata routing evidence"},
        ]
        contract = build_host_synthesis_contract(
            plan,
            evidence,
            retrieval_status={"status": "success"},
        )

        self.assertEqual(contract["schema"], HOST_SYNTHESIS_CONTRACT_SCHEMA)
        self.assertEqual(contract["status"], "ready")
        self.assertEqual(contract["retrieval_status"], "success")
        self.assertEqual(contract["answer_generation"], "host_owned")
        self.assertFalse(contract["script_owned_synthesis"])
        self.assertEqual(contract["citation_policy"]["compatible_with"], "audit-citations")
        self.assertEqual(contract["citation_policy"]["format"], "numeric_bracket")
        self.assertTrue(contract["citation_policy"]["required"])
        self.assertEqual(contract["citation_policy"]["valid_citation_ids"], ["[1]", "[2]"])
        self.assertEqual(contract["citation_policy"]["valid_ranks"], [1, 2])
        self.assertFalse(contract["evidence_policy"]["allow_external_facts"])

    def test_agentic_answer_request_packages_evidence_without_llm(self) -> None:
        query_payload = {
            "ok": True,
            "question": "What is portable?",
            "chunks": [
                {
                    "chunk_id": "c1",
                    "content": "Portable release artifacts include vendored runtime files.",
                    "similarity": 0.9,
                    "document_name": "sample.md",
                    "dataset_id": "ds-1",
                }
            ],
            "agentic_plan": build_agentic_plan("What is portable?"),
        }

        request = create_agentic_answer_request(
            query_payload,
            provider_label="external",
            model_label="review-model",
            max_evidence_chars=24,
        )
        markdown = render_agentic_answer_request_markdown(request)

        self.assertEqual(request["schema"], AGENTIC_ANSWER_REQUEST_SCHEMA)
        self.assertTrue(request["ok"])
        self.assertTrue(request["advisory"])
        self.assertFalse(request["llm_invoked"])
        self.assertEqual(request["model"]["script_owned_llm_calls"], 0)
        self.assertEqual(request["summary"]["evidence_count"], 1)
        self.assertTrue(request["citation_policy"]["required"])
        self.assertEqual(request["citation_policy"]["valid_citation_ids"], ["[1]"])
        self.assertLessEqual(len(request["evidence"][0]["content_preview"]), 24)
        self.assertIn("ragflow-query agentic-answer review", request["instructions"]["review_command"])
        self.assertIn("RAGFlow Agentic Answer Request", markdown)

    def test_agentic_answer_review_validates_external_candidate(self) -> None:
        query_payload = {
            "ok": True,
            "question": "What is portable?",
            "chunks": [
                {
                    "chunk_id": "c1",
                    "content": "Portable release artifacts include vendored runtime files.",
                    "similarity": 0.9,
                    "document_name": "sample.md",
                    "dataset_id": "ds-1",
                }
            ],
        }
        request = create_agentic_answer_request(query_payload)
        candidate = {
            "schema": "ragflow_agentic_answer_candidate_v1",
            "advisory": True,
            "generated": True,
            "answer": "Portable release artifacts include vendored runtime files [1].",
        }

        report = review_agentic_answer(
            query_payload,
            candidate["answer"],
            candidate=candidate,
            request=request,
            expected_terms=["portable"],
        )
        markdown = render_agentic_answer_review_markdown(report)

        self.assertEqual(report["schema"], AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA)
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["citation_count"], 1)
        self.assertEqual(report["summary"]["invalid_citation_count"], 0)
        self.assertTrue(report["summary"]["advisory"])
        self.assertTrue(report["summary"]["generated"])
        self.assertEqual(report["summary"]["script_owned_llm_calls"], 0)
        self.assertEqual(report["issues"], [])
        self.assertIn("RAGFlow Agentic Answer Review", markdown)

    def test_agentic_answer_review_rejects_missing_candidate_markers_and_bad_request(self) -> None:
        query_payload = {
            "ok": True,
            "question": "What is portable?",
            "chunks": [
                {
                    "chunk_id": "c1",
                    "content": "Portable release artifacts include vendored runtime files.",
                    "similarity": 0.9,
                }
            ],
        }
        other_query_payload = {
            "ok": True,
            "question": "Different question",
            "chunks": [{"content": "Different evidence.", "similarity": 0.9}],
        }
        request = create_agentic_answer_request(other_query_payload)

        report = review_agentic_answer(
            query_payload,
            "Portable release artifacts include vendored runtime files [1].",
            candidate={"answer": "Portable release artifacts include vendored runtime files [1]."},
            request=request,
        )
        codes = {issue["code"] for issue in report["issues"]}

        self.assertFalse(report["ok"])
        self.assertIn("agentic_answer_not_advisory", codes)
        self.assertIn("agentic_answer_not_generated", codes)
        self.assertIn("agentic_answer_request_query_mismatch", codes)

    def test_agentic_plan_stops_for_clarification(self) -> None:
        plan = build_agentic_plan("What about it?")

        self.assertEqual(plan["status"], "needs_clarification")
        self.assertEqual(plan["classification"]["intent"], "clarification_needed")
        self.assertEqual(plan["retrieval_queries"], [])
        self.assertIn("ask_clarifying_question", {step.get("action") for step in plan["steps"]})

    def test_agentic_plan_rejects_invalid_bounds(self) -> None:
        with self.assertRaisesRegex(AgenticPlanError, "max_subqueries"):
            build_agentic_plan("runtime config", max_subqueries=99)
        with self.assertRaisesRegex(AgenticPlanError, "reflection_budget"):
            build_agentic_plan("runtime config", reflection_budget=99)


if __name__ == "__main__":
    unittest.main()
