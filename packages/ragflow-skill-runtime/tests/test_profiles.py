from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.profiles import (
    BUILD_PROFILE_MATERIALIZATION_SCHEMA,
    ChunkProfile,
    ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
    ENRICHMENT_EXPERIMENT_REPORT_SCHEMA,
    ProfileError,
    compare_validation_reports,
    decide_profile_from_reports,
    explain_profile,
    lint_profile,
    materialize_profile_suggestion,
    plan_enrichment_experiments,
    load_profile,
    recommend_profile,
    render_enrichment_experiment_markdown,
    render_profile_compare_markdown,
    render_profile_decision_markdown,
    render_profile_lint_markdown,
)

ROOT = Path(__file__).resolve().parents[3]
KB_BUILD_TEMPLATES = ROOT / "skills" / "ragflow-kb-build" / "templates"


class ProfileTests(unittest.TestCase):
    def test_load_profile_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_id": "default-en-768",
                        "chunk_method": "naive",
                        "chunk_size": 768,
                        "chunk_overlap": 96,
                        "embedding_model": "bge-m3",
                        "parser_config": {"auto_keywords": 1},
                    }
                ),
                encoding="utf-8",
            )
            profile = load_profile(path)

        self.assertEqual(profile.profile_id, "default-en-768")
        self.assertEqual(profile.parser_config["chunk_token_num"], 768)
        self.assertEqual(profile.parser_config["auto_keywords"], 1)
        self.assertEqual(profile.parser_config["auto_questions"], 0)

    def test_profile_rejects_overlap_larger_than_chunk(self) -> None:
        with self.assertRaises(ProfileError):
            ChunkProfile.from_dict(
                {
                    "profile_id": "bad",
                    "chunk_size": 128,
                    "chunk_overlap": 128,
                }
            )

    def test_dataset_payload_filters_internal_parser_config_keys(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "default-zh-512",
                "chunk_size": 512,
                "parser_config": {
                    "chunk_token_num": 512,
                    "auto_keywords": 0,
                    "image_context_size": 1,
                    "table_context_size": 2,
                    "page_index": True,
                    "table_to_html": True,
                    "layout_recognize": True,
                    "__language__": "Chinese",
                },
            }
        )

        payload = profile.to_dataset_payload()
        manifest = profile.to_manifest_dict()

        self.assertNotIn("__language__", payload["parser_config"])
        self.assertNotIn("page_index", payload["parser_config"])
        self.assertNotIn("table_to_html", payload["parser_config"])
        self.assertNotIn("layout_recognize", payload["parser_config"])
        self.assertEqual(payload["parser_config"]["chunk_token_num"], 512)
        self.assertEqual(payload["parser_config"]["image_context_size"], 1)
        self.assertEqual(payload["parser_config"]["table_context_size"], 2)
        self.assertEqual(manifest["parser_config"]["image_context_size"], 1)
        self.assertEqual(manifest["parser_config"]["table_context_size"], 2)
        self.assertTrue(manifest["parser_config"]["page_index"])
        self.assertTrue(manifest["parser_config"]["table_to_html"])
        self.assertTrue(manifest["parser_config"]["layout_recognize"])
        self.assertEqual(manifest["parser_config"]["__language__"], "Chinese")

    def test_lint_profile_accepts_chunk_marker_delimiter(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "zh-table-atomic-2048",
                "chunk_size": 2048,
                "chunk_overlap": 0,
                "parser_config": {
                    "chunk_token_num": 2048,
                    "delimiter": "`<!-- chunk -->`",
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "image_context_size": 1,
                    "table_context_size": 2,
                    "__language__": "Chinese",
                },
            }
        )

        report = lint_profile(profile)
        codes = {issue.code for issue in report.issues}
        payload = profile.to_dataset_payload()

        self.assertTrue(report.ok)
        self.assertNotIn("unsupported_parser_key", codes)
        self.assertEqual(payload["parser_config"]["delimiter"], "`<!-- chunk -->`")
        self.assertEqual(payload["parser_config"]["image_context_size"], 1)
        self.assertEqual(payload["parser_config"]["table_context_size"], 2)

    def test_lint_profile_rejects_negative_context_window_sizes(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "bad-context-window",
                "chunk_size": 512,
                "parser_config": {
                    "chunk_token_num": 512,
                    "image_context_size": -1,
                    "table_context_size": -2,
                },
            }
        )

        report = lint_profile(profile)
        codes = {issue.code for issue in report.issues}

        self.assertFalse(report.ok)
        self.assertIn("image_context_size_negative", codes)
        self.assertIn("table_context_size_negative", codes)

    def test_lint_profile_reports_internal_metadata_and_mismatch(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "custom",
                "chunk_size": 512,
                "chunk_overlap": 256,
                "parser_config": {
                    "chunk_token_num": 384,
                    "auto_keywords": 0,
                    "__language__": "English",
                    "provider_specific": True,
                },
            }
        )

        report = lint_profile(profile)
        codes = {issue.code for issue in report.issues}

        self.assertFalse(report.ok)
        self.assertIn("chunk_token_num_mismatch", codes)
        self.assertIn("overlap_high", codes)
        self.assertIn("unsupported_parser_key", codes)
        self.assertIn("internal_parser_metadata", codes)
        self.assertIn("custom", render_profile_lint_markdown(report))

    def test_lint_profile_reports_model_neutral_embedding_guidance(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "default-en-768",
                "chunk_size": 768,
                "chunk_overlap": 96,
                "parser_config": {
                    "chunk_token_num": 768,
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "English",
                },
            }
        )

        report = lint_profile(profile)
        payload = report.to_dict()
        issue = next(item for item in payload["issues"] if item["code"] == "embedding_model_not_configured")
        markdown = render_profile_lint_markdown(report)

        self.assertTrue(report.ok)
        self.assertEqual(issue["severity"], "info")
        self.assertEqual(issue["field"], "embedding_model")
        self.assertIn("model-neutral", issue["message"])
        self.assertIn("model-specific template", issue["recommendation"])
        self.assertIn("embedding_model_not_configured", markdown)
        self.assertIn("model-specific template", markdown)

    def test_public_templates_keep_generic_neutral_and_add_bge_m3_variants(self) -> None:
        generic_en = load_profile(KB_BUILD_TEMPLATES / "default-en-768.json")
        generic_zh = load_profile(KB_BUILD_TEMPLATES / "default-zh-512.json")
        bge_en = load_profile(KB_BUILD_TEMPLATES / "bge-m3-en-768.json")
        bge_zh = load_profile(KB_BUILD_TEMPLATES / "bge-m3-zh-512.json")

        self.assertIsNone(generic_en.embedding_model)
        self.assertIsNone(generic_zh.embedding_model)
        self.assertEqual(bge_en.embedding_model, "bge-m3")
        self.assertEqual(bge_zh.embedding_model, "bge-m3")
        self.assertEqual(bge_en.profile_id, "bge-m3-en-768")
        self.assertEqual(bge_zh.profile_id, "bge-m3-zh-512")
        self.assertNotIn(
            "embedding_model_not_configured",
            {issue.code for issue in lint_profile(bge_en).issues},
        )

    def test_explain_profile_filters_api_payload(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "default-en-768",
                "chunk_size": 768,
                "chunk_overlap": 96,
                "parser_config": {"chunk_token_num": 768, "__language__": "English"},
            }
        )
        payload = explain_profile(profile)

        self.assertTrue(payload["ok"])
        self.assertNotIn("__language__", payload["api_payload"]["parser_config"])
        self.assertEqual(payload["summary"]["language"], "English")

    def test_profile_suggestion_materialization_clamps_delimiter_profile_and_preserves_source(self) -> None:
        profile_suggestions = {
            "schema": "ragflow_profile_suggestions_v1",
            "suggestions": [
                {
                    "id": "default-zh-512",
                    "language": "zh",
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                },
                {
                    "id": "table-atomic-zh-4096",
                    "language": "zh",
                    "chunk_method": "naive",
                    "chunk_size": 4096,
                    "chunk_overlap": 0,
                    "postprocess_profile": "chunk-markers-dense",
                    "parser_config": {
                        "chunk_token_num": 4096,
                        "delimiter": "`<!-- chunk -->`",
                        "auto_keywords": 0,
                        "auto_questions": 0,
                        "__language__": "Chinese",
                    },
                    "avoid_children_delimiter": True,
                },
            ],
        }
        ingest_plan = {
            "schema": "ragflow_ingest_plan_v1",
            "recommended_build": {
                "parser_profile": {
                    "language": "zh",
                    "chunk_size": 4096,
                    "chunk_overlap": 0,
                }
            },
        }

        report = materialize_profile_suggestion(
            profile_suggestions=profile_suggestions,
            ragflow_ingest_plan=ingest_plan,
        )
        profile = report["profile"]
        lint = lint_profile(ChunkProfile.from_dict(profile))

        self.assertEqual(report["schema"], BUILD_PROFILE_MATERIALIZATION_SCHEMA)
        self.assertEqual(profile["profile_id"], "table-atomic-zh-2048")
        self.assertEqual(profile["language"], "Chinese")
        self.assertEqual(profile["chunk_size"], 2048)
        self.assertEqual(profile["parser_config"]["chunk_token_num"], 2048)
        self.assertEqual(profile["parser_config"]["delimiter"], "`<!-- chunk -->`")
        self.assertNotIn("__language__", profile["parser_config"])
        self.assertTrue(lint.ok)
        self.assertEqual(report["materialization"]["selected_suggestion_id"], "table-atomic-zh-4096")
        self.assertEqual(report["materialization"]["clamps"][0]["field"], "parser_config.chunk_token_num")
        self.assertEqual(report["materialization"]["clamps"][0]["original"], 4096)
        self.assertEqual(report["materialization"]["clamps"][0]["effective"], 2048)
        self.assertEqual(report["source_suggestion"]["id"], "table-atomic-zh-4096")

    def test_recommend_profile_for_chinese_notes(self) -> None:
        recommendation = recommend_profile(language="zh", doc_type="notes")
        payload = recommendation.to_dict()

        self.assertEqual(payload["profile"]["chunk_size"], 384)
        self.assertEqual(payload["profile"]["parser_config"]["__language__"], "Chinese")
        self.assertIn("recommended-zh-notes", payload["profile"]["id"])

    def test_compare_validation_reports_ranks_benchmark_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weak = root / "weak.json"
            strong = root / "strong.json"
            weak.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "level": "benchmark",
                        "metrics": {
                            "pass_rate": 0.8,
                            "empty_results": 1,
                            "total": 2,
                            "average_chunks": 1.5,
                            "query_latency_ms": 180.0,
                            "parse_time_ms": 250.0,
                        },
                        "benchmark": {"metrics": {"hit_rate": 0.5, "mrr": 0.3, "ndcg_at_k": 0.4, "empty_result_rate": 0.5}},
                    }
                ),
                encoding="utf-8",
            )
            strong.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "level": "benchmark",
                        "metrics": {
                            "pass_rate": 1.0,
                            "empty_results": 0,
                            "total": 2,
                            "average_chunks": 3.0,
                            "query_latency_ms": 90.0,
                            "parse_time_ms": 125.0,
                        },
                        "benchmark": {"metrics": {"hit_rate": 1.0, "mrr": 0.9, "ndcg_at_k": 0.95, "empty_result_rate": 0.0}},
                    }
                ),
                encoding="utf-8",
            )

            report = compare_validation_reports([weak, strong])

        self.assertEqual(report["winner"]["path"], str(strong))
        self.assertEqual(report["winner"]["metrics"]["empty_result_rate"], 0.0)
        self.assertEqual(report["winner"]["metrics"]["query_latency_ms"], 90.0)
        self.assertEqual(report["winner"]["metrics"]["parse_time_ms"], 125.0)
        rendered = render_profile_compare_markdown(report)
        self.assertIn("Profile Compare", rendered)
        self.assertIn("latency_ms", rendered)

    def test_compare_validation_reports_uses_latency_and_operational_cost_when_quality_ties(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expensive = root / "expensive.json"
            efficient = root / "efficient.json"
            for path, latency_ms, total_cost in (
                (expensive, 480.0, 0.48),
                (efficient, 80.0, 0.02),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "level": "benchmark",
                            "metrics": {"pass_rate": 0.9, "total": 40, "average_chunks": 4.0},
                            "benchmark": {"metrics": {"hit_rate": 0.9, "mrr": 0.8, "ndcg_at_k": 0.85}},
                            "runtime_metrics": {"latency_ms": {"average": latency_ms}},
                            "cost_trace": {"estimated_total_usd": total_cost},
                        }
                    ),
                    encoding="utf-8",
                )

            report = compare_validation_reports([expensive, efficient])

        self.assertEqual(report["winner"]["path"], str(efficient))
        winner_metrics = report["winner"]["metrics"]
        loser_metrics = report["candidates"][1]["metrics"]
        self.assertEqual(winner_metrics["query_latency_ms"], 80.0)
        self.assertEqual(winner_metrics["estimated_cost_usd"], 0.02)
        self.assertEqual(winner_metrics["cost_per_query_usd"], 0.0005)
        self.assertLess(winner_metrics["operational_cost_score"], loser_metrics["operational_cost_score"])
        rendered = render_profile_compare_markdown(report)
        self.assertIn("cost_usd", rendered)
        self.assertIn("cost_per_query_usd", rendered)

    def test_profile_decision_classifies_apollo_evidence_as_insufficient_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_1024 = root / "apollo-1024.json"
            profile_2048 = root / "apollo-2048.json"
            for path, chunk_tokens, score in (
                (profile_1024, 1024, 0.83),
                (profile_2048, 2048, 0.86),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "profile": {"id": f"apollo-{chunk_tokens}", "parser_config": {"chunk_token_num": chunk_tokens}},
                            "metrics": {
                                "pass_rate": score,
                                "total": 6,
                                "average_chunks": 4.5,
                                "query_latency_ms": 120.0 + (chunk_tokens / 100),
                            },
                            "benchmark": {
                                "metrics": {
                                    "hit_rate": score,
                                    "mrr": score - 0.05,
                                    "ndcg_at_k": score - 0.02,
                                    "strict_chunk_recall_at_k": 1.0,
                                    "expected_chunk_hit_rate": 1.0,
                                    "table_recall": 1.0,
                                    "image_recall": 0.0,
                                    "empty_result_rate": 0.0,
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            report = decide_profile_from_reports([profile_1024, profile_2048])
            markdown = render_profile_decision_markdown(report)

        self.assertEqual(report["schema"], "ragflow_profile_decision_report_v1")
        self.assertEqual(report["decision"]["status"], "insufficient_sample_for_default_change")
        self.assertFalse(report["decision"]["default_change_allowed"])
        self.assertEqual(report["summary"]["max_query_count"], 6)
        self.assertIn("minimum_query_count_not_met", {issue["code"] for issue in report["issues"]})
        self.assertIn("insufficient_sample_for_default_change", markdown)

    def test_profile_decision_recommends_default_only_after_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "profile": {"id": "baseline-1024", "parser_config": {"chunk_token_num": 1024}},
                        "metrics": {"pass_rate": 0.72, "total": 36, "average_chunks": 8.0, "query_latency_ms": 160.0},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 0.74,
                                "mrr": 0.70,
                                "ndcg_at_k": 0.72,
                                "strict_chunk_recall_at_k": 0.91,
                                "expected_chunk_hit_rate": 0.90,
                                "table_recall": 0.85,
                                "image_recall": 0.50,
                                "empty_result_rate": 0.05,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            candidate.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "profile": {"id": "candidate-2048", "parser_config": {"chunk_token_num": 2048}},
                        "metrics": {"pass_rate": 0.92, "total": 36, "average_chunks": 6.0, "query_latency_ms": 140.0},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 0.94,
                                "mrr": 0.90,
                                "ndcg_at_k": 0.91,
                                "strict_chunk_recall_at_k": 1.0,
                                "expected_chunk_hit_rate": 1.0,
                                "table_recall": 0.95,
                                "image_recall": 0.75,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = decide_profile_from_reports([baseline, candidate])

        self.assertEqual(report["decision"]["status"], "recommend_default_change")
        self.assertTrue(report["decision"]["default_change_allowed"])
        self.assertEqual(report["decision"]["recommended_profile_id"], "candidate-2048")
        self.assertGreaterEqual(report["summary"]["score_delta"], report["thresholds"]["minimum_score_delta"])

    def test_profile_decision_uses_operational_cost_when_quality_ties(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expensive = root / "expensive.json"
            efficient = root / "efficient.json"
            for path, profile_id, latency_ms, total_cost in (
                (expensive, "expensive-2048", 500.0, 0.5),
                (efficient, "efficient-1024", 90.0, 0.02),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "profile": {"id": profile_id},
                            "metrics": {"pass_rate": 0.92, "total": 40, "average_chunks": 4.0},
                            "benchmark": {
                                "metrics": {
                                    "hit_rate": 0.92,
                                    "mrr": 0.88,
                                    "ndcg_at_k": 0.9,
                                    "strict_chunk_recall_at_k": 1.0,
                                    "expected_chunk_hit_rate": 1.0,
                                    "empty_result_rate": 0.0,
                                }
                            },
                            "runtime_metrics": {"latency_ms": {"average": latency_ms}},
                            "cost_trace": {"estimated_total_usd": total_cost},
                        }
                    ),
                    encoding="utf-8",
                )

            report = decide_profile_from_reports(
                [expensive, efficient],
                minimum_query_count=20,
                minimum_score_delta=0.0,
            )
            markdown = render_profile_decision_markdown(report)

        self.assertEqual(report["winner"]["profile_id"], "efficient-1024")
        self.assertEqual(report["winner"]["metrics"]["estimated_cost_usd"], 0.02)
        self.assertEqual(report["winner"]["metrics"]["cost_per_query_usd"], 0.0005)
        self.assertIn("cost_usd", markdown)
        self.assertIn("operational_cost", markdown)

    def test_plan_enrichment_experiments_expands_matrix(self) -> None:
        base = ChunkProfile.from_dict(
            {
                "profile_id": "base-en",
                "chunk_size": 768,
                "chunk_overlap": 96,
                "parser_config": {
                    "chunk_token_num": 768,
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "English",
                },
            }
        )
        matrix = {
            "schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
            "name": "enrichment-smoke",
            "fixed": {
                "retrieval.top_k": 3,
                "retrieval.vsw": 0.2,
                "retrieval.rerank": True,
                "tag_kb_ids": ["tag-placeholder"],
            },
            "dimensions": {
                "auto_keywords": [0, 3],
                "auto_questions": [0, 2],
                "retrieval.similarity_threshold": [0.01],
            },
        }

        report = plan_enrichment_experiments(base_profile=base, matrix=matrix, profile_id_prefix="phase27")

        self.assertEqual(report["schema"], ENRICHMENT_EXPERIMENT_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["candidate_profile_count"], 4)
        self.assertEqual(report["summary"]["mutation_steps"], 0)
        self.assertEqual(report["candidate_profile_set"]["schema"], "ragflow_candidate_profile_set_v1")
        self.assertEqual(len(report["candidate_profile_set"]["profiles"]), 4)
        issue_codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("llm_backed_enrichment_enabled", issue_codes)
        self.assertIn("low_threshold_pollution_risk", issue_codes)
        self.assertIn("rerank_latency_risk", issue_codes)
        self.assertIn("user_tag_kb_ids", issue_codes)
        profile_ids = {item["profile_id"] for item in report["experiments"]}
        self.assertEqual(len(profile_ids), 4)
        self.assertIn("RAGFlow Enrichment Experiment Matrix", render_enrichment_experiment_markdown(report))

    def test_plan_enrichment_experiments_collapses_aliased_chunk_dimensions(self) -> None:
        base = ChunkProfile.from_dict(
            {
                "profile_id": "base-en",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "parser_config": {
                    "chunk_token_num": 512,
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "English",
                },
            }
        )
        matrix = {
            "schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
            "name": "alias-collapse",
            "dimensions": {
                "chunk_size": [512, 1024],
                "parser_config.chunk_token_num": [512, 1024],
            },
        }

        report = plan_enrichment_experiments(base_profile=base, matrix=matrix, profile_id_prefix="alias")
        markdown = render_enrichment_experiment_markdown(report)

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["planned_experiment_count"], 4)
        self.assertEqual(report["summary"]["raw_experiment_count"], 4)
        self.assertEqual(report["summary"]["candidate_profile_count"], 2)
        self.assertEqual(report["summary"]["unique_effective_profile_count"], 2)
        self.assertEqual(report["summary"]["duplicate_effective_profile_group_count"], 2)
        self.assertEqual(len(report["candidate_profile_set"]["profiles"]), 2)
        effective_sizes = {
            profile["chunk_size"]
            for profile in report["candidate_profile_set"]["profiles"]
        }
        self.assertEqual(effective_sizes, {512, 1024})
        for profile in report["candidate_profile_set"]["profiles"]:
            self.assertEqual(profile["parser_config"]["chunk_token_num"], profile["chunk_size"])
        duplicate_groups = report["effective_profile_deduplication"]["duplicate_effective_profile_groups"]
        self.assertEqual(len(duplicate_groups), 2)
        self.assertTrue(all(len(group["raw_indexes"]) == 2 for group in duplicate_groups))
        self.assertTrue(all(group["override_reason"] == "chunk_token_num_alias" for group in duplicate_groups))
        self.assertIn("duplicate_effective_profile_collapsed", {issue["code"] for issue in report["issues"]})
        self.assertIn("Duplicate Effective Profiles", markdown)

    def test_plan_enrichment_experiments_can_fail_on_duplicate_effective_profiles(self) -> None:
        base = ChunkProfile.from_dict(
            {
                "profile_id": "base-en",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "parser_config": {
                    "chunk_token_num": 512,
                    "auto_keywords": 0,
                    "auto_questions": 0,
                    "__language__": "English",
                },
            }
        )
        matrix = {
            "schema": ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
            "name": "alias-collapse",
            "dimensions": {
                "chunk_size": [512, 1024],
                "chunk_token_num": [512, 1024],
            },
        }

        report = plan_enrichment_experiments(
            base_profile=base,
            matrix=matrix,
            profile_id_prefix="alias",
            fail_on_duplicate_effective_profiles=True,
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["duplicate_effective_profile_group_count"], 2)
        self.assertIn("duplicate_effective_profiles_blocked", {issue["code"] for issue in report["issues"]})


if __name__ == "__main__":
    unittest.main()
