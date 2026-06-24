from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.optimization import (
    OPTIMIZATION_PLAN_SCHEMA,
    PROFILE_EXPERIMENT_RESULTS_SCHEMA,
    create_optimization_plan,
    load_candidate_profile_set,
    render_best_profile_markdown,
    render_optimization_plan_markdown,
    summarize_optimization_results,
)


def _write_profile(path: Path, profile_id: str, chunk_size: int = 512) -> None:
    path.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "chunk_method": "naive",
                "chunk_size": chunk_size,
                "chunk_overlap": 64,
                "parser_config": {
                    "chunk_token_num": chunk_size,
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "English",
                },
            }
        ),
        encoding="utf-8",
    )


def _write_validation_report(path: Path, *, mrr: float, hit_rate: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "level": "benchmark",
                "metrics": {"pass_rate": hit_rate},
                "dataset": {"id": "ds-test", "name": path.parent.name},
                "benchmark": {
                    "metrics": {
                        "hit_rate": hit_rate,
                        "mrr": mrr,
                        "precision_at_k": 0.5,
                        "recall_at_k": hit_rate,
                        "ndcg_at_k": mrr,
                        "map_at_k": mrr,
                        "strict_chunk_recall_at_k": hit_rate,
                        "expected_chunk_hit_rate": hit_rate,
                        "empty_result_rate": 0.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


class OptimizationTests(unittest.TestCase):
    def test_load_candidate_profile_set_from_file_dir_and_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "explicit.json"
            profile_dir = root / "profiles"
            profile_dir.mkdir()
            _write_profile(explicit, "explicit-profile")
            _write_profile(profile_dir / "dir-profile.json", "dir-profile", chunk_size=768)

            profile_set = load_candidate_profile_set(
                profile_paths=[explicit],
                profile_dirs=[profile_dir],
                recommendations=["en:manual"],
            )

        self.assertTrue(profile_set["ok"], profile_set["issues"])
        self.assertEqual(profile_set["summary"]["candidate_count"], 3)
        self.assertEqual(
            {candidate["source"]["type"] for candidate in profile_set["candidates"]},
            {"file", "directory", "recommendation"},
        )

    def test_create_optimization_plan_resolves_manifest_and_names_disposable_kbs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            doc = docs / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            explicit = root / "explicit.json"
            profile_dir = root / "profiles"
            profile_dir.mkdir()
            _write_profile(explicit, "explicit-profile")
            _write_profile(profile_dir / "dir-profile.json", "dir-profile", chunk_size=768)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            manifest = root / "manifest.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_benchmark_manifest_v1",
                        "artifacts": {"queries": "queries.json", "qrels": "qrels.json"},
                    }
                ),
                encoding="utf-8",
            )

            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=docs,
                profile_paths=[explicit],
                profile_dirs=[profile_dir],
                recommendations=["en:manual"],
                benchmark_manifest_path=manifest,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )

        self.assertEqual(plan["schema"], OPTIMIZATION_PLAN_SCHEMA)
        self.assertTrue(plan["ok"], plan["issues"])
        self.assertEqual(plan["summary"]["candidate_count"], 3)
        self.assertEqual(plan["inputs"]["benchmark"]["queries"], str(queries))
        self.assertEqual(len({candidate["disposable_kb_name"] for candidate in plan["candidates"]}), 3)
        self.assertIn("RAGFlow Optimization Plan", render_optimization_plan_markdown(plan))
        for candidate in plan["candidates"]:
            self.assertFalse(candidate["disposable_kb_name"].endswith("__"))
            self.assertIn("scripts/validate.py", " ".join(candidate["commands"]["validate"]))

    def test_summarize_optimization_results_ranks_validation_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            doc = docs / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            weak = root / "weak.json"
            strong = root / "strong.json"
            _write_profile(weak, "weak-profile")
            _write_profile(strong, "strong-profile", chunk_size=768)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=docs,
                profile_paths=[weak, strong],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                report_path = Path(candidate["artifacts"]["validation_report"])
                _write_validation_report(
                    report_path,
                    mrr=0.95 if candidate["profile_id"] == "strong-profile" else 0.4,
                    hit_rate=1.0 if candidate["profile_id"] == "strong-profile" else 0.7,
                )

            results = summarize_optimization_results(plan_path=plan_path)

        self.assertEqual(results["schema"], PROFILE_EXPERIMENT_RESULTS_SCHEMA)
        self.assertTrue(results["ok"], results["issues"])
        self.assertEqual(results["recommendation"]["profile_id"], "strong-profile")
        self.assertIn("RAGFlow Best Profile Report", render_best_profile_markdown(results))


if __name__ == "__main__":
    unittest.main()
