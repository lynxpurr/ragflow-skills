from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.query_rewrite import (
    QueryRewriteError,
    build_query_rewrite_plan,
    load_multi_query_file,
    render_query_rewrite_markdown,
)


class QueryRewriteTests(unittest.TestCase):
    def test_simple_rewrite_keeps_original_and_generates_variants(self) -> None:
        plan = build_query_rewrite_plan("How do I configure runtime?")

        self.assertEqual(plan["schema"], "ragflow_query_rewrite_plan_v1")
        self.assertEqual(plan["mode"], "none")
        self.assertEqual(plan["retrieval_queries"][0]["query"], "How do I configure runtime?")
        self.assertEqual(plan["summary"]["generated_query_count"], 0)

        simple = build_query_rewrite_plan("How do I configure runtime?", mode="simple")
        queries = [item["query"] for item in simple["retrieval_queries"]]
        self.assertEqual(queries[0], "How do I configure runtime?")
        self.assertIn("how to configure runtime", queries)
        self.assertGreaterEqual(simple["summary"]["generated_query_count"], 1)
        self.assertIn("RAGFlow Query Rewrite Plan", render_query_rewrite_markdown(simple))

    def test_translate_rewrite_uses_deterministic_stub_terms(self) -> None:
        plan = build_query_rewrite_plan("runtime config", mode="translate")
        generated = [item["query"] for item in plan["generated_queries"]]

        self.assertEqual(plan["summary"]["llm_calls"], 0)
        self.assertEqual(generated, ["runtime config 运行时 配置"])

    def test_multi_query_file_supports_strings_and_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.json"
            path.write_text(
                json.dumps(
                    {
                        "queries": [
                            "runtime setup",
                            {"id": "q-cn", "query": "运行时 配置", "metadata": {"locale": "zh"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            queries = load_multi_query_file(path)

        self.assertEqual([item["id"] for item in queries], ["multi-1", "q-cn"])
        self.assertEqual(queries[1]["metadata"]["locale"], "zh")

    def test_hyde_requires_explicit_llm_adapter(self) -> None:
        with self.assertRaisesRegex(QueryRewriteError, "requires explicit LLM config"):
            build_query_rewrite_plan("runtime config", mode="hyde")
        with self.assertRaisesRegex(QueryRewriteError, "host-owned LLM rewrite adapter"):
            build_query_rewrite_plan("runtime config", mode="hyde", llm_configured=True)


if __name__ == "__main__":
    unittest.main()
