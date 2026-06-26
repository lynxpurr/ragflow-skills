from __future__ import annotations

import unittest

from ragflow_skill_runtime.agentic import (
    AGENTIC_PLAN_SCHEMA,
    AGENTIC_TRACE_SCHEMA,
    AgenticPlanError,
    build_agentic_plan,
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
        self.assertIn("RAGFlow Agentic Plan", markdown)
        self.assertIn("subquery", markdown)

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
