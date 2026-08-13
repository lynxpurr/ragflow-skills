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


def _write_parse_report(path: Path, *, drift: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "schema": "ragflow_parse_report_v1",
                "status": "REVIEW" if drift else "PASS",
                "dataset": {"id": "ds-test", "name": path.parent.name},
                "summary": {
                    "manifest_document_count": 1,
                    "effective_chunk_total": 7,
                    "failed_document_count": 0,
                    "pending_document_count": 0,
                },
                "profile_visibility": {
                    "requested_parser_config": {
                        "chunk_token_num": 512,
                        "auto_keywords": 3,
                        "delimiter": "`<!-- chunk -->`",
                    },
                    "effective_parser_config": {
                        "chunk_token_num": 480,
                        "auto_keywords": 0,
                    },
                    "effective_source": "document_list",
                    "drift": {
                        "drift": drift,
                        "changed_keys": ["chunk_token_num", "auto_keywords"] if drift else [],
                        "missing_effective_keys": ["delimiter"] if drift else [],
                    },
                    "unsupported_effective_keys": [],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_refresh_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "schema": "ragflow_kb_refresh_report_v1",
                "summary": {
                    "observed_document_count": 1,
                    "observed_chunk_total": 7,
                    "done_document_count": 1,
                },
                "documents": [
                    {
                        "document_id": "doc-test",
                        "name": "sample.md",
                        "chunk_count": 7,
                        "parse_state": "done",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_chunk_snapshot_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "schema": "ragflow_chunk_snapshot_report_v1",
                "summary": {
                    "chunk_count": 7,
                    "source_chunk_count": 7,
                    "delimiter_visible_chunk_count": 1,
                    "possible_split_table_chunk_count": 2,
                    "table_like_chunk_count": 3,
                    "max_chunk_chars": 740,
                    "observed_state_chunk_total": 7,
                },
                "chunk_review": {
                    "metrics": {
                        "delimiter_visible_chunk_count": 1,
                        "possible_split_table_chunk_count": 2,
                        "table_like_chunk_count": 3,
                        "max_chunk_chars": 740,
                    },
                    "examples": {"delimiter_visible_chunk_indexes": [2]},
                    "issues": [{"severity": "review", "code": "chunk_delimiter_visible_in_snapshot"}],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_health_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "schema": "ragflow_kb_health_report_v1",
                "status": "REVIEW",
                "summary": {
                    "kb_count": 1,
                    "embedding_model_count": 1,
                    "embedding_model_rebuild_required_kb_count": 1,
                    "stale_parse_kb_count": 1,
                    "issue_counts": {"warning": 2},
                },
                "embedding_model_distribution": [
                    {"model": "bge-large-en-v1.5", "kb_count": 1, "dataset_ids": ["ds-test"]},
                ],
                "knowledge_bases": [
                    {
                        "dataset_id": "ds-test",
                        "kb_name": path.parent.name,
                        "status": "REVIEW",
                        "embedding_model": "bge-large-en-v1.5",
                        "embedding_model_check": {
                            "status": "mismatch",
                            "rebuild_or_reparse_required": True,
                            "expected_models": ["bge-m3"],
                            "observed_model": "bge-large-en-v1.5",
                        },
                        "parse": {"failed_document_count": 0, "pending_document_count": 1},
                    }
                ],
                "issues": [
                    {"severity": "warning", "code": "embedding_model_rebuild_required"},
                    {"severity": "warning", "code": "stale_or_failed_parse_state"},
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_kb_manifest(path: Path, *, dataset_id: str = "0123456789abcdef", dataset_name: str = "kb:cleanup") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "0.1",
                "dataset": {"id": dataset_id, "name": dataset_name},
                "documents": [],
            }
        ),
        encoding="utf-8",
    )


def _write_cleanup_execution_report(
    path: Path,
    *,
    cleanup_plan: Path,
    dataset_id: str = "0123456789abcdef",
    dataset_name: str = "kb:cleanup",
    post_cleanup_verified: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "schema": "ragflow_optimization_cleanup_execution_report_v1",
                "cleanup_plan": str(cleanup_plan),
                "execute": True,
                "dry_run": False,
                "mutation_allowed": True,
                "requires_exact_confirmation": True,
                "summary": {
                    "target_count": 1,
                    "deleted_target_count": 1,
                    "failed_target_count": 0,
                    "cleanup_executed": True,
                    "post_cleanup_verified": post_cleanup_verified,
                },
                "post_cleanup_verification": {
                    "status": "verified" if post_cleanup_verified else "not_checked",
                    "network_checked": post_cleanup_verified,
                },
                "results": [
                    {
                        "profile_id": "cleanup-profile",
                        "status": "deleted",
                        "target": {"dataset_id": dataset_id, "dataset_name": dataset_name},
                    }
                ],
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
        self.assertFalse(plan["mutation_guard"]["mutation_commands_enabled"])
        self.assertEqual(plan["summary"]["blocked_mutation_command_count"], 3)
        self.assertEqual(len({candidate["disposable_kb_name"] for candidate in plan["candidates"]}), 3)
        self.assertIn("RAGFlow Optimization Plan", render_optimization_plan_markdown(plan))
        for candidate in plan["candidates"]:
            self.assertFalse(candidate["disposable_kb_name"].endswith("__"))
            for artifact_name in ("parse_report", "refresh_report", "chunk_snapshot", "chunk_snapshot_report", "health_report"):
                self.assertIn(artifact_name, candidate["artifacts"])
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
        followup_codes = {item["code"] for item in results["benchmark_artifact_followups"]}
        self.assertIn("add_expected_chunk_qrels", followup_codes)
        self.assertIn("add_modality_benchmark_cases", followup_codes)
        self.assertGreaterEqual(results["summary"]["benchmark_artifact_followup_count"], 2)
        self.assertIn("weak benchmark evidence", " ".join(results["recommendation"]["rationale"]))

    def test_summarize_optimization_results_explains_single_document_promotion_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "single-doc-profile")
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
            benchmark = plan["inputs"]["benchmark"]
            strength = benchmark["preflight"]["benchmark_strength"]
            strength["status"] = "exploratory"
            strength["issue_codes"] = ["single_target_document"]
            strength["summary"].update(
                {
                    "expected_chunk_coverage": 1.0,
                    "expected_modality_coverage": 1.0,
                    "target_document_count": 1,
                }
            )
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            _write_validation_report(Path(plan["candidates"][0]["artifacts"]["validation_report"]), mrr=1.0, hit_rate=1.0)

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        followups = results["benchmark_artifact_followups"]
        self.assertEqual([item["code"] for item in followups], ["add_multi_document_or_negative_cases"])
        self.assertEqual(followups[0]["severity"], "warning")
        self.assertIn("multi-document or negative", followups[0]["recommendation"])
        self.assertIn("add_multi_document_or_negative_cases", rendered)

    def test_summarize_optimization_results_explains_candidate_local_strict_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "boundary-aware-profile")
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "Which table values?",
                                "expected_terms": ["alpha revenue", "beta margin"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {"query_id": "q1", "document": "sample.md"},
                            {
                                "query_id": "q1",
                                "field": "expected_chunk",
                                "target": "sha256:reference-boundary-hash",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
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
            candidate = plan["candidates"][0]
            report_path = Path(candidate["artifacts"]["validation_report"])
            _write_validation_report(report_path, mrr=1.0, hit_rate=1.0)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["benchmark"]["metrics"].update(
                {
                    "strict_chunk_recall_at_k": 0.0,
                    "expected_chunk_hit_rate": 0.0,
                    "candidate_snapshot_expected_chunk_recall_at_k": 1.0,
                    "candidate_snapshot_expected_chunk_hit_rate": 1.0,
                    "candidate_snapshot_expected_chunk_count": 2,
                    "matched_candidate_snapshot_expected_chunks": 2,
                }
            )
            report_path.write_text(json.dumps(payload), encoding="utf-8")

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        metrics = results["candidates"][0]["metrics"]
        strict = results["candidates"][0]["decision_score"]["components"]["strict_evidence"]["metrics"]
        rationale = " ".join(results["recommendation"]["rationale"])

        self.assertEqual(metrics["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(metrics["candidate_snapshot_expected_chunk_recall_at_k"], 1.0)
        self.assertEqual(strict["strict_chunk_recall_at_k"], 0.0)
        self.assertEqual(strict["candidate_snapshot_expected_chunk_recall_at_k"], 1.0)
        self.assertIn("Candidate-local expected chunk recall@k", rationale)
        self.assertIn("candidate_local_chunk_recall", rendered)
        self.assertIn("Candidate-local expected chunk recall", rendered)

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

    def test_summarize_optimization_results_uses_normalized_decision_score_without_changing_raw_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            fast = root / "fast.json"
            slow = root / "slow.json"
            _write_profile(fast, "fast-profile")
            _write_profile(slow, "slow-enriched-profile", auto_keywords=3)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[slow, fast],
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
                    mrr=1.0 if candidate["profile_id"] == "slow-enriched-profile" else 0.95,
                    hit_rate=1.0,
                    query_latency_ms=650.0 if candidate["profile_id"] == "slow-enriched-profile" else 80.0,
                    parse_time_ms=1500.0 if candidate["profile_id"] == "slow-enriched-profile" else 180.0,
                )

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        self.assertEqual(results["decision"]["score_basis"], "normalized_decision_score")
        self.assertEqual(results["recommendation"]["profile_id"], "fast-profile")
        self.assertLessEqual(results["recommendation"]["decision_score"]["score"], 1.0)
        self.assertNotEqual(results["recommendation"]["decision_score"]["score"], results["recommendation"]["score"])
        raw_slow = next(candidate for candidate in results["candidates"] if candidate["profile_id"] == "slow-enriched-profile")
        self.assertAlmostEqual(raw_slow["metrics"]["ndcg_at_k"], 1.0)
        self.assertAlmostEqual(raw_slow["metrics"]["score"], 1.0)
        self.assertAlmostEqual(raw_slow["score"], 1.0)
        raw_fast = next(candidate for candidate in results["candidates"] if candidate["profile_id"] == "fast-profile")
        self.assertAlmostEqual(raw_fast["metrics"]["score"], 0.9825)
        self.assertGreater(raw_fast["decision_score"]["score"], raw_slow["decision_score"]["score"])
        for candidate in results["candidates"]:
            self.assertEqual(
                set(candidate["decision_score"]["components"]),
                {"quality", "strict_evidence", "modality_coverage", "empty_result_risk", "cost", "context_warnings", "table_atomicity"},
            )
            self.assertEqual(candidate["decision_score"]["components"]["table_atomicity"]["status"], "unknown")
        self.assertIn("decision_score", rendered)
        self.assertIn("raw_score", rendered)

    def test_summarize_optimization_results_demotes_table_atomicity_risk_when_ir_metrics_are_saturated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\n<table><tr><td>Known answer</td></tr></table>\n", encoding="utf-8")
            small = root / "small.json"
            safe = root / "safe.json"
            _write_profile(small, "small-profile", chunk_size=256)
            _write_profile(safe, "safe-profile", chunk_size=1024)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")
            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[doc],
                input_path=root,
                profile_paths=[small, safe],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )
            _mark_benchmark_strength_promotable(plan)
            for candidate in plan["candidates"]:
                risky = candidate["profile_id"] == "small-profile"
                candidate["table_parent_chunk_preflight"] = {
                    "exists": True,
                    "status": "review" if risky else "ready",
                    "selected_profile_id": candidate["profile_id"],
                    "selected_profile_chunk_tokens": 256 if risky else 1024,
                    "table_count": 1,
                    "max_estimated_parent_chunk_tokens": 960,
                    "max_recommended_min_parent_chunk_tokens": 1024,
                    "issues": [
                        {
                            "severity": "warning",
                            "code": "table_parent_chunk_profile_too_small",
                            "message": "selected profile chunk_token_num is smaller than at least one estimated table block",
                        }
                    ]
                    if risky
                    else [],
                }
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for candidate in plan["candidates"]:
                report_path = Path(candidate["artifacts"]["validation_report"])
                _write_validation_report(report_path, mrr=1.0, hit_rate=1.0, query_latency_ms=100.0, parse_time_ms=200.0)
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                payload["benchmark"]["metrics"].update(
                    {
                        "expected_term_recall_at_k": 1.0,
                        "expected_term_hit_rate": 1.0,
                        "table_term_recall_at_k": 1.0,
                        "table_term_hit_rate": 1.0,
                    }
                )
                report_path.write_text(json.dumps(payload), encoding="utf-8")

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        small_result = next(candidate for candidate in results["candidates"] if candidate["profile_id"] == "small-profile")
        safe_result = next(candidate for candidate in results["candidates"] if candidate["profile_id"] == "safe-profile")

        self.assertEqual(results["recommendation"]["profile_id"], "safe-profile")
        self.assertEqual(small_result["decision_score"]["components"]["table_atomicity"]["status"], "risk")
        self.assertEqual(safe_result["decision_score"]["components"]["table_atomicity"]["status"], "pass")
        self.assertGreater(
            small_result["decision_score"]["components"]["table_atomicity"]["penalty"],
            safe_result["decision_score"]["components"]["table_atomicity"]["penalty"],
        )
        self.assertEqual(small_result["table_parent_chunk_preflight"]["status"], "review")
        self.assertEqual(safe_result["table_parent_chunk_preflight"]["status"], "ready")
        self.assertIn("table atomicity", " ".join(results["recommendation"]["rationale"]).lower())
        self.assertIn("Table atomicity", rendered)
        self.assertIn("Table term recall", rendered)

    def test_create_optimization_plan_carries_table_parent_chunk_preflight_per_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs_dir = handoff / "documents"
            docs_dir.mkdir(parents=True)
            markdown = docs_dir / "sample.md"
            markdown.write_text("# Table\n\n<table><tr><td>Known answer</td></tr></table>\n", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "source.pdf", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (handoff / "retrieval_hints.json").write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "table_artifacts": [
                            {
                                "source": "html_table",
                                "document": "documents/sample.md",
                                "row_count": 20,
                                "column_count": 12,
                                "cell_count": 240,
                                "estimated_parent_chunk_tokens": 960,
                                "recommended_min_parent_chunk_tokens": 1024,
                                "table_atomic_target_tokens": 4096,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            small = root / "small.json"
            safe = root / "safe.json"
            _write_profile(small, "small-profile", chunk_size=256)
            _write_profile(safe, "safe-profile", chunk_size=1024)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "What is known?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q1": {"sample.md": 1}}), encoding="utf-8")

            plan = create_optimization_plan(
                kb_name="kb:optimize-test",
                document_paths=[markdown],
                doc_manifest_path=manifest,
                profile_paths=[small, safe],
                queries_path=queries,
                qrels_path=qrels,
                artifact_dir=root / "opt-artifacts",
                run_id="run1",
            )

        by_id = {candidate["profile_id"]: candidate["table_parent_chunk_preflight"] for candidate in plan["candidates"]}
        self.assertEqual(by_id["small-profile"]["status"], "review")
        self.assertEqual(by_id["small-profile"]["selected_profile_chunk_tokens"], 256)
        self.assertEqual(by_id["small-profile"]["max_estimated_parent_chunk_tokens"], 960)
        self.assertEqual(by_id["small-profile"]["issues"][0]["code"], "table_parent_chunk_profile_too_small")
        self.assertEqual(by_id["safe-profile"]["status"], "ready")
        self.assertEqual(by_id["safe-profile"]["selected_profile_chunk_tokens"], 1024)

    def test_summarize_optimization_results_marks_missing_decision_cost_signals_unknown(self) -> None:
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

        enriched_candidate = next(candidate for candidate in results["candidates"] if candidate["profile_id"] == "enriched-profile")
        cost = enriched_candidate["decision_score"]["components"]["cost"]
        self.assertEqual(cost["latency"]["status"], "unknown")
        self.assertEqual(cost["parse_time"]["status"], "unknown")
        self.assertEqual(cost["enrichment"]["status"], "estimated")
        self.assertEqual(cost["status"], "unknown")
        self.assertEqual(results["decision"]["score_basis"], "normalized_decision_score")

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

    def test_summarize_optimization_results_includes_runtime_evidence_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "runtime-evidence-profile", auto_keywords=3)
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
            _mark_benchmark_strength_promotable(plan)
            candidate = plan["candidates"][0]
            artifacts = candidate["artifacts"]
            _write_validation_report(Path(artifacts["validation_report"]), mrr=1.0, hit_rate=1.0)
            _write_parse_report(Path(artifacts["parse_report"]))
            _write_refresh_report(Path(artifacts["refresh_report"]))
            _write_chunk_snapshot_report(Path(artifacts["chunk_snapshot_report"]))
            _write_health_report(Path(artifacts["health_report"]))
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        evidence = results["candidates"][0]["runtime_evidence"]
        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["sidecar_count"], 4)
        self.assertEqual(evidence["parse_report"]["requested_parser_config"]["delimiter"], "`<!-- chunk -->`")
        self.assertEqual(evidence["parse_report"]["effective_parser_config"]["chunk_token_num"], 480)
        self.assertTrue(evidence["parse_report"]["drift"]["drift"])
        self.assertEqual(evidence["refresh_report"]["summary"]["observed_chunk_total"], 7)
        self.assertEqual(evidence["chunk_snapshot"]["boundary_evidence"]["delimiter_visible_chunk_count"], 1)
        self.assertEqual(evidence["chunk_snapshot"]["boundary_evidence"]["possible_split_table_chunk_count"], 2)
        self.assertEqual(evidence["health_report"]["embedding_models"], ["bge-large-en-v1.5"])
        self.assertTrue(evidence["health_report"]["embedding_model_rebuild_required"])
        self.assertEqual(results["summary"]["runtime_evidence_candidate_count"], 1)
        self.assertEqual(results["summary"]["parser_drift_candidate_count"], 1)
        self.assertEqual(results["summary"]["health_warning_candidate_count"], 1)
        issue_codes = {issue["code"] for issue in results["issues"]}
        self.assertIn("runtime_parser_config_drift", issue_codes)
        self.assertIn("runtime_health_embedding_model_rebuild_required", issue_codes)
        self.assertIn("## Runtime Evidence", rendered)
        self.assertIn("runtime-evidence-profile", rendered)

    def test_summarize_optimization_results_tolerates_missing_partial_and_malformed_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text("# Sample\n\nKnown answer.\n", encoding="utf-8")
            profile = root / "profile.json"
            _write_profile(profile, "partial-evidence-profile")
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
            _mark_benchmark_strength_promotable(plan)
            candidate = plan["candidates"][0]
            artifacts = candidate["artifacts"]
            _write_validation_report(Path(artifacts["validation_report"]), mrr=1.0, hit_rate=1.0)
            Path(artifacts["parse_report"]).parent.mkdir(parents=True, exist_ok=True)
            Path(artifacts["parse_report"]).write_text("{not-json", encoding="utf-8")
            Path(artifacts["health_report"]).write_text(json.dumps({"schema": "unexpected_health_schema"}), encoding="utf-8")
            plan_path = root / "optimization_plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            results = summarize_optimization_results(plan_path=plan_path)

        self.assertTrue(results["ok"], results["issues"])
        evidence = results["candidates"][0]["runtime_evidence"]
        self.assertFalse(evidence["available"])
        self.assertFalse(evidence["parse_report"]["available"])
        self.assertFalse(evidence["refresh_report"]["available"])
        self.assertFalse(evidence["chunk_snapshot"]["available"])
        self.assertFalse(evidence["health_report"]["available"])
        issue_codes = {issue["code"] for issue in results["issues"]}
        self.assertIn("runtime_evidence_sidecar_invalid", issue_codes)
        self.assertIn("runtime_evidence_sidecar_schema_invalid", issue_codes)
        self.assertEqual(results["summary"]["runtime_evidence_candidate_count"], 0)

    def test_summarize_optimization_results_tracks_cleanup_lifecycle_until_post_cleanup_verification(self) -> None:
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
            _mark_benchmark_strength_promotable(plan)
            candidate = plan["candidates"][0]
            _write_validation_report(Path(candidate["artifacts"]["validation_report"]), mrr=1.0, hit_rate=1.0)
            _write_kb_manifest(
                Path(candidate["artifacts"]["kb_manifest"]),
                dataset_id="0123456789abcdef",
                dataset_name=candidate["disposable_kb_name"],
            )
            plan["mode"] = "execute-build-validate"
            plan["mutation_allowed"] = True
            plan["execution"] = {
                "schema": "ragflow_optimization_execute_report_v1",
                "summary": {
                    "cleanup_required_count": 1,
                    "cleanup_executed": False,
                    "validated_candidate_count": 1,
                    "benchmark_validation_passed_count": 1,
                },
            }
            plan_path = root / "optimization_plan.json"
            cleanup_path = root / "cleanup_plan.json"
            cleanup_execution_path = root / "cleanup_execution_report.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            cleanup_plan = create_optimization_cleanup_plan(plan_path=plan_path)
            cleanup_path.write_text(json.dumps(cleanup_plan), encoding="utf-8")

            pending = summarize_optimization_results(plan_path=plan_path, cleanup_plan_path=cleanup_path)
            _write_cleanup_execution_report(
                cleanup_execution_path,
                cleanup_plan=cleanup_path,
                dataset_id="0123456789abcdef",
                dataset_name=candidate["disposable_kb_name"],
            )
            cleaned = summarize_optimization_results(
                plan_path=plan_path,
                cleanup_plan_path=cleanup_path,
                cleanup_execution_report_path=cleanup_execution_path,
            )
            rendered = render_best_profile_markdown(cleaned)

        self.assertTrue(pending["cleanup_lifecycle"]["cleanup_required"])
        self.assertEqual(pending["cleanup_lifecycle"]["status"], "cleanup_pending")
        self.assertEqual(pending["cleanup_lifecycle"]["cleanup_plan"]["status"], "ready")
        self.assertEqual(pending["cleanup_lifecycle"]["cleanup_execution"]["status"], "missing")
        self.assertEqual(pending["summary"]["cleanup_pending"], True)
        next_step_names = [step["name"] for step in pending["next_steps"]]
        self.assertEqual(next_step_names, ["cleanup-plan", "readiness", "cleanup-execute", "field-trial-record"])
        self.assertFalse(pending["next_steps"][2]["enabled"])
        self.assertIn("--confirm-dataset-id", pending["next_steps"][2]["command"])
        self.assertEqual(pending["field_trial_record_suggestion"]["cleanup_status"], "cleanup_pending")
        self.assertEqual(pending["field_trial_record_suggestion"]["decision_status"], pending["decision"]["status"])

        self.assertEqual(cleaned["cleanup_lifecycle"]["cleanup_execution"]["status"], "executed")
        self.assertEqual(cleaned["cleanup_lifecycle"]["post_cleanup_verification"]["status"], "not_checked")
        self.assertEqual(cleaned["cleanup_lifecycle"]["status"], "cleanup_executed_unverified")
        self.assertEqual(cleaned["summary"]["cleanup_executed"], True)
        self.assertEqual(cleaned["summary"]["post_cleanup_verification_status"], "not_checked")
        self.assertEqual(cleaned["summary"]["post_cleanup_read_back_verified"], False)
        self.assertIn("## Cleanup Lifecycle", rendered)
        self.assertIn("cleanup_executed_unverified", rendered)

    def test_summarize_optimization_results_auto_discovers_cleanup_lifecycle_sidecars(self) -> None:
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
            _mark_benchmark_strength_promotable(plan)
            candidate = plan["candidates"][0]
            _write_validation_report(Path(candidate["artifacts"]["validation_report"]), mrr=1.0, hit_rate=1.0)
            _write_kb_manifest(
                Path(candidate["artifacts"]["kb_manifest"]),
                dataset_id="0123456789abcdef",
                dataset_name=candidate["disposable_kb_name"],
            )
            plan["mode"] = "execute-build-validate"
            plan["mutation_allowed"] = True
            plan["execution"] = {
                "schema": "ragflow_optimization_execute_report_v1",
                "summary": {
                    "cleanup_required_count": 1,
                    "cleanup_executed": False,
                    "validated_candidate_count": 1,
                    "benchmark_validation_passed_count": 1,
                },
            }
            plan_path = root / "optimization_plan.json"
            cleanup_path = root / "cleanup_plan.json"
            readiness_path = root / "optimization_live_readiness_report.json"
            cleanup_execution_path = root / "cleanup_execution_report.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            cleanup_plan = create_optimization_cleanup_plan(plan_path=plan_path)
            cleanup_path.write_text(json.dumps(cleanup_plan), encoding="utf-8")
            readiness_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "ragflow_optimization_live_readiness_report_v1",
                        "summary": {"cleanup_ready_target_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            _write_cleanup_execution_report(
                cleanup_execution_path,
                cleanup_plan=cleanup_path,
                dataset_id="0123456789abcdef",
                dataset_name=candidate["disposable_kb_name"],
                post_cleanup_verified=True,
            )

            results = summarize_optimization_results(plan_path=plan_path)
            rendered = render_best_profile_markdown(results)

        lifecycle = results["cleanup_lifecycle"]
        self.assertEqual(lifecycle["status"], "complete")
        self.assertEqual(lifecycle["cleanup_plan"]["path"], str(cleanup_path))
        self.assertEqual(lifecycle["readiness"]["path"], str(readiness_path))
        self.assertEqual(lifecycle["cleanup_execution"]["path"], str(cleanup_execution_path))
        self.assertEqual(lifecycle["post_cleanup_verification"]["status"], "verified")
        self.assertEqual(lifecycle["post_cleanup_read_back_verified"], True)
        self.assertEqual(results["summary"]["cleanup_pending"], False)
        self.assertEqual(results["summary"]["post_cleanup_verification_status"], "verified")
        self.assertEqual(results["summary"]["post_cleanup_read_back_verified"], True)
        self.assertEqual(results["field_trial_record_suggestion"]["cleanup_status"], "complete")
        self.assertIn("Status: `complete`", rendered)
        self.assertIn("Post-cleanup verification: `verified`", rendered)

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
                credential_error="fixture config error",
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
