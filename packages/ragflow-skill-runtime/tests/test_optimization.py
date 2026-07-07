from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.optimization import (
    OPTIMIZATION_CLEANUP_PLAN_SCHEMA,
    OPTIMIZATION_LIVE_READINESS_REPORT_SCHEMA,
    OPTIMIZATION_PLAN_SCHEMA,
    PROFILE_EXPERIMENT_RESULTS_SCHEMA,
    create_optimization_cleanup_plan,
    create_optimization_live_readiness_report,
    create_optimization_plan,
    load_candidate_profile_set,
    render_best_profile_markdown,
    render_optimization_cleanup_plan_markdown,
    render_optimization_live_readiness_markdown,
    render_optimization_plan_markdown,
    summarize_optimization_results,
)


def _write_profile(path: Path, profile_id: str, chunk_size: int = 512, *, auto_keywords: int = 0, auto_questions: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "chunk_method": "naive",
                "chunk_size": chunk_size,
                "chunk_overlap": 64,
                "parser_config": {
                    "chunk_token_num": chunk_size,
                    "auto_keywords": auto_keywords,
                    "auto_questions": auto_questions,
                    "__language__": "English",
                },
            }
        ),
        encoding="utf-8",
    )


def _write_validation_report(
    path: Path,
    *,
    mrr: float,
    hit_rate: float = 1.0,
    query_latency_ms: float = 0.0,
    parse_time_ms: float = 0.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "level": "benchmark",
                "metrics": {
                    "pass_rate": hit_rate,
                    "average_chunks": 3.0,
                    "query_latency_ms": query_latency_ms,
                    "parse_time_ms": parse_time_ms,
                },
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


def _write_validation_report_without_cost(path: Path, *, mrr: float, hit_rate: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "level": "benchmark",
                "metrics": {
                    "pass_rate": hit_rate,
                    "average_chunks": 3.0,
                },
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


def _mark_benchmark_strength_promotable(plan: dict[str, object]) -> None:
    inputs = plan.get("inputs")
    assert isinstance(inputs, dict)
    benchmark = inputs.get("benchmark")
    assert isinstance(benchmark, dict)
    preflight = benchmark.get("preflight")
    assert isinstance(preflight, dict)
    strength = preflight.get("benchmark_strength")
    assert isinstance(strength, dict)
    strength["status"] = "promotable"
    strength["issue_codes"] = []


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
        self.assertFalse(plan["mutation_guard"]["mutation_commands_enabled"])
        self.assertEqual(plan["summary"]["blocked_mutation_command_count"], 3)
        self.assertEqual(len({candidate["disposable_kb_name"] for candidate in plan["candidates"]}), 3)
        self.assertIn("RAGFlow Optimization Plan", render_optimization_plan_markdown(plan))
        for candidate in plan["candidates"]:
            self.assertFalse(candidate["disposable_kb_name"].endswith("__"))
            self.assertIsNone(candidate["commands"]["build"])
            self.assertFalse(candidate["mutation_commands"]["build"]["enabled"])
            self.assertTrue(candidate["mutation_commands"]["build"]["requires_execute"])
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
                    query_latency_ms=80.0 if candidate["profile_id"] == "strong-profile" else 150.0,
                    parse_time_ms=120.0 if candidate["profile_id"] == "strong-profile" else 240.0,
                )

            results = summarize_optimization_results(plan_path=plan_path)

        self.assertEqual(results["schema"], PROFILE_EXPERIMENT_RESULTS_SCHEMA)
        self.assertTrue(results["ok"], results["issues"])
        self.assertEqual(results["recommendation"]["profile_id"], "strong-profile")
        self.assertEqual(results["winner"]["metrics"]["query_latency_ms"], 80.0)
        self.assertEqual(results["winner"]["metrics"]["parse_time_ms"], 120.0)
        rendered = render_best_profile_markdown(results)
        self.assertIn("RAGFlow Best Profile Report", rendered)
        self.assertIn("latency_ms", rendered)

    def test_summarize_optimization_results_downgrades_weak_benchmark_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
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
                input_path=root,
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

        self.assertEqual(results["benchmark_strength"]["status"], "exploratory")
        self.assertEqual(results["recommendation"]["decision_status"], "insufficient_evidence")
        self.assertEqual(results["summary"]["benchmark_strength_status"], "exploratory")
        self.assertIn("weak benchmark evidence", " ".join(results["recommendation"]["rationale"]))

    def test_summarize_optimization_results_warns_when_core_metrics_are_saturated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            first = root / "first.json"
            second = root / "second.json"
            _write_profile(first, "first-profile")
            _write_profile(second, "second-profile", chunk_size=768)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[first, second],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                _write_validation_report(Path(candidate["artifacts"]["validation_report"]), mrr=1.0, hit_rate=1.0)

            results = summarize_optimization_results(plan_path=plan_path)

        self.assertEqual(results["summary"]["saturated_metric_count"], 3)
        self.assertEqual(results["metric_saturation"]["saturated_metrics"], ["hit_rate", "mrr", "recall_at_k"])
        self.assertIn("metric_saturation_hit_rate", {issue["code"] for issue in results["issues"]})

    def test_summarize_optimization_results_reports_co_winners_with_conservative_tie_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            enriched = root / "enriched.json"
            baseline = root / "baseline.json"
            _write_profile(enriched, "z-enriched-profile", auto_keywords=3)
            _write_profile(baseline, "a-baseline-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[enriched, baseline],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            _mark_benchmark_strength_promotable(plan)
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                _write_validation_report(
                    Path(candidate["artifacts"]["validation_report"]),
                    mrr=1.0,
                    hit_rate=1.0,
                    query_latency_ms=100.0,
                    parse_time_ms=200.0,
                )

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        self.assertEqual(results["recommendation"]["decision_status"], "co_winners")
        self.assertEqual(results["recommendation"]["profile_id"], "a-baseline-profile")
        self.assertEqual(results["recommendation"]["co_winner_profile_ids"], ["a-baseline-profile", "z-enriched-profile"])
        self.assertEqual(results["summary"]["co_winner_count"], 2)
        self.assertEqual([candidate["profile_id"] for candidate in results["co_winners"]], ["a-baseline-profile", "z-enriched-profile"])
        self.assertIn("Decision status: `co_winners`", rendered)
        self.assertIn("Co-winners: `a-baseline-profile`, `z-enriched-profile`", rendered)

    def test_summarize_optimization_results_requires_cost_review_for_enrichment_tie_with_missing_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            baseline = root / "baseline.json"
            enriched = root / "enriched.json"
            _write_profile(baseline, "baseline-profile")
            _write_profile(enriched, "enriched-profile", auto_keywords=3)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[baseline, enriched],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            _mark_benchmark_strength_promotable(plan)
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                _write_validation_report_without_cost(Path(candidate["artifacts"]["validation_report"]), mrr=1.0, hit_rate=1.0)

            results = summarize_optimization_results(plan_path=plan_path)

        self.assertEqual(results["recommendation"]["decision_status"], "needs_cost_review")
        self.assertEqual(results["recommendation"]["profile_id"], "baseline-profile")
        self.assertIn("optimization_cost_review_required", {issue["code"] for issue in results["issues"]})
        self.assertTrue(results["decision"]["cost_review_required"])

    def test_summarize_optimization_results_uses_min_score_delta_for_insufficient_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            first = root / "first.json"
            second = root / "second.json"
            _write_profile(first, "first-profile")
            _write_profile(second, "second-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[first, second],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            _mark_benchmark_strength_promotable(plan)
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                _write_validation_report(
                    Path(candidate["artifacts"]["validation_report"]),
                    mrr=0.92 if candidate["profile_id"] == "second-profile" else 0.90,
                    hit_rate=0.92 if candidate["profile_id"] == "second-profile" else 0.90,
                    query_latency_ms=100.0,
                    parse_time_ms=200.0,
                )

            results = summarize_optimization_results(plan_path=plan_path, min_score_delta=0.05)

        self.assertEqual(results["recommendation"]["decision_status"], "insufficient_evidence")
        self.assertEqual(results["decision"]["score_delta"], 0.02)
        self.assertIn("minimum score delta", " ".join(results["recommendation"]["rationale"]))

    def test_summarize_optimization_results_generates_diagnostics_for_zero_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "zero-chunk-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[profile],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            candidate = plan["candidates"][0]
            kb_manifest = Path(candidate["artifacts"]["kb_manifest"])
            kb_manifest.parent.mkdir(parents=True, exist_ok=True)
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "0123456789abcdef", "name": candidate["disposable_kb_name"]},
                        "documents": [{"document_id": "doc-0123456789abcdef", "status": "done", "chunk_count": 0}],
                    }
                ),
                encoding="utf-8",
            )
            validation_report = Path(candidate["artifacts"]["validation_report"])
            validation_report.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "level": "benchmark",
                        "dataset": {"id": "0123456789abcdef", "name": candidate["disposable_kb_name"]},
                        "metrics": {"pass_rate": 0.0, "empty_results": 1},
                        "cases": [{"id": "q1", "passed": False, "chunk_count": 0}],
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 0.0,
                                "mrr": 0.0,
                                "precision_at_k": 0.0,
                                "recall_at_k": 0.0,
                                "ndcg_at_k": 0.0,
                                "map_at_k": 0.0,
                                "strict_chunk_recall_at_k": 0.0,
                                "expected_chunk_hit_rate": 0.0,
                                "empty_result_rate": 1.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            results = summarize_optimization_results(plan_path=plan_path)
            diagnostic_report = Path(candidate["artifacts"]["diagnostic_report"])
            self.assertTrue(diagnostic_report.exists())
            self.assertEqual(results["summary"]["diagnostic_required_count"], 1)
            self.assertEqual(results["summary"]["diagnostic_report_count"], 1)
            self.assertEqual(results["summary"]["zero_chunk_candidate_count"], 1)
            diagnostics = results["candidates"][0]["diagnostics"]
            self.assertTrue(diagnostics["generated"])
            self.assertIn("zero_chunks", diagnostics["reason_codes"])
            self.assertIn("document_zero_chunks", diagnostics["summary"]["issue_types"])
            self.assertIn("## Diagnostics", render_best_profile_markdown(results))

    def test_create_optimization_cleanup_plan_with_ready_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "cleanup-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[profile],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            candidate = plan["candidates"][0]
            kb_manifest = Path(candidate["artifacts"]["kb_manifest"])
            kb_manifest.parent.mkdir(parents=True, exist_ok=True)
            kb_manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {
                            "id": "0123456789abcdef",
                            "name": candidate["disposable_kb_name"],
                        },
                        "documents": [],
                    }
                ),
                encoding="utf-8",
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            cleanup = create_optimization_cleanup_plan(plan_path=plan_path, config_path=root / "ragflow.yaml")

        self.assertEqual(cleanup["schema"], OPTIMIZATION_CLEANUP_PLAN_SCHEMA)
        self.assertTrue(cleanup["ok"], cleanup["issues"])
        self.assertFalse(cleanup["mutation_allowed"])
        self.assertEqual(cleanup["summary"]["ready_target_count"], 1)
        target = cleanup["targets"][0]
        self.assertEqual(target["required_confirmation"]["confirm_dataset_id"], "0123456789abcdef")
        self.assertIn("--confirm-dataset-id", target["commands"]["execute"])
        self.assertIn("--config", target["commands"]["execute"])
        self.assertIn("RAGFlow Optimization Cleanup Plan", render_optimization_cleanup_plan_markdown(cleanup))

    def test_create_optimization_cleanup_plan_warns_when_manifests_are_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "pending-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[profile],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            cleanup = create_optimization_cleanup_plan(plan_path=plan_path)

        self.assertTrue(cleanup["ok"], cleanup["issues"])
        self.assertEqual(cleanup["summary"]["warnings"], 1)
        self.assertEqual(cleanup["summary"]["pending_target_count"], 1)
        self.assertIsNone(cleanup["targets"][0]["commands"]["execute"])

    def test_create_optimization_live_readiness_allows_pending_cleanup_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "readiness-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[profile],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            plan_path = root / "optimization_plan.json"
            cleanup_path = root / "cleanup_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            cleanup = create_optimization_cleanup_plan(plan_path=plan_path)
            cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")

            report = create_optimization_live_readiness_report(
                plan_path=plan_path,
                cleanup_plan_path=cleanup_path,
                ragflow_base_url_configured=True,
                ragflow_api_key_configured=True,
                confirm_live_build=True,
                confirm_kb_name="kb:optimize-test",
                confirm_run_id="run1",
            )

        self.assertEqual(report["schema"], OPTIMIZATION_LIVE_READINESS_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertFalse(report["mutation_allowed"])
        self.assertFalse(report["network_checked"])
        self.assertEqual(report["cleanup"]["state"], "pending_manifests")
        self.assertEqual(report["summary"]["cleanup_pending_target_count"], 1)
        self.assertIn("RAGFlow Optimization Live Readiness Report", render_optimization_live_readiness_markdown(report))

    def test_create_optimization_live_readiness_requires_strict_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "strict-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[profile],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            plan_path = root / "optimization_plan.json"
            cleanup_path = root / "cleanup_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            cleanup = create_optimization_cleanup_plan(plan_path=plan_path)
            cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")

            report = create_optimization_live_readiness_report(
                plan_path=plan_path,
                cleanup_plan_path=cleanup_path,
                credential_error="config file not found: ragflow.yaml",
                confirm_live_build=False,
                confirm_kb_name="kb:wrong",
                confirm_run_id="wrong",
                require_cleanup_ready=True,
            )

        self.assertFalse(report["ok"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("ragflow_config_invalid", codes)
        self.assertIn("confirm_live_build_missing", codes)
        self.assertIn("confirm_kb_name_mismatch", codes)
        self.assertIn("confirm_run_id_mismatch", codes)
        self.assertIn("cleanup_targets_pending", codes)


if __name__ == "__main__":
    unittest.main()
