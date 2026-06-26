from __future__ import annotations

import unittest

from ragflow_skill_runtime.agentic import (
    AGENTIC_PLAN_SCHEMA,
    AGENTIC_TRACE_SCHEMA,
    AgenticPlanError,
    HOST_SYNTHESIS_CONTRACT_SCHEMA,
    build_agentic_execution_trace,
    build_agentic_plan,
    build_host_synthesis_contract,
    render_agentic_plan_markdown,
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
