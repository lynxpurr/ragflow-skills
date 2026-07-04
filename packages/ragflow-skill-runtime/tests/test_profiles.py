from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.profiles import (
    ChunkProfile,
    ENRICHMENT_EXPERIMENT_MATRIX_SCHEMA,
    ENRICHMENT_EXPERIMENT_REPORT_SCHEMA,
    ProfileError,
    compare_validation_reports,
    explain_profile,
    lint_profile,
    plan_enrichment_experiments,
    load_profile,
    recommend_profile,
    render_enrichment_experiment_markdown,
    render_profile_compare_markdown,
    render_profile_lint_markdown,
)


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
                    "__language__": "Chinese",
                },
            }
        )

        payload = profile.to_dataset_payload()
        manifest = profile.to_manifest_dict()

        self.assertNotIn("__language__", payload["parser_config"])
        self.assertEqual(payload["parser_config"]["chunk_token_num"], 512)
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


if __name__ == "__main__":
    unittest.main()
