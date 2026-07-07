from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.benchmark_governance import (
    BENCHMARK_DELTA_REPORT_SCHEMA,
    BENCHMARK_GATE_REPORT_SCHEMA,
    BENCHMARK_IMPORT_CHECKPOINT_SCHEMA,
    BENCHMARK_IMPORT_REPORT_SCHEMA,
    BENCHMARK_PREFLIGHT_REPORT_SCHEMA,
    BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA,
    BENCHMARK_SAMPLE_REPORT_SCHEMA,
    BENCHMARK_SUMMARY_REPORT_SCHEMA,
    BENCHMARK_TREND_REPORT_SCHEMA,
    CHUNK_SNAPSHOT_REPORT_SCHEMA,
    GROUNDED_QA_EVIDENCE_MAP_REPORT_SCHEMA,
    GROUNDED_QA_EVIDENCE_MAP_SCHEMA,
    GROUNDED_QA_GENERATE_REPORT_SCHEMA,
    GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA,
    GROUNDED_QA_SUGGESTION_REVIEW_REPORT_SCHEMA,
    GROUNDED_QA_VALIDATE_REPORT_SCHEMA,
    SUPPRESSION_REPORT_SCHEMA,
    BenchmarkGovernanceError,
    create_grounded_qa_suggestion_request,
    delta_benchmark_reports,
    gate_benchmark_report,
    generate_grounded_qa,
    import_benchmark_dataset,
    map_grounded_qa_evidence,
    preflight_benchmark_dataset,
    sample_benchmark_dataset,
    snapshot_chunks,
    suggest_benchmark_retrieval_parameters,
    summarize_benchmark_report,
    render_suppression_report_markdown,
    review_grounded_qa_suggestions,
    suppression_report_payload,
    trend_benchmark_reports,
    validate_grounded_qa,
)


class BenchmarkGovernanceTests(unittest.TestCase):
    def test_import_and_preflight_benchmark_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            output = root / "benchmark"
            queries.write_text(
                json.dumps({"queries": [{"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}}]}),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")

            import_report = import_benchmark_dataset(
                queries_path=queries,
                qrels_path=qrels,
                output_dir=output,
                name="example-benchmark",
            )
            preflight = preflight_benchmark_dataset(manifest_path=output / "manifest.json")

        self.assertEqual(import_report["schema"], BENCHMARK_IMPORT_REPORT_SCHEMA)
        self.assertTrue(import_report["ok"])
        self.assertEqual(import_report["summary"]["query_count"], 1)
        self.assertEqual(preflight["schema"], BENCHMARK_PREFLIGHT_REPORT_SCHEMA)
        self.assertTrue(preflight["ok"], preflight["issues"])

    def test_preflight_reports_weak_document_only_benchmark_strength(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}},
                            {"id": "q2", "question": "What is precise?", "metadata": {"type": "fact"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {"query_id": "q1", "target": "source.md", "field": "document"},
                            {"query_id": "q2", "target": "source.md", "field": "document"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(json.dumps({"schema": "ragflow_grounded_qa_v1", "items": []}), encoding="utf-8")

            preflight = preflight_benchmark_dataset(queries_path=queries, qrels_path=qrels, qa_path=qa)

        strength = preflight["benchmark_strength"]
        self.assertTrue(preflight["ok"], preflight["issues"])
        self.assertEqual(strength["schema"], "ragflow_benchmark_strength_v1")
        self.assertEqual(strength["status"], "exploratory")
        self.assertEqual(strength["summary"]["query_count"], 2)
        self.assertEqual(strength["summary"]["target_document_count"], 1)
        self.assertEqual(strength["summary"]["qrel_field_counts"], {"document": 2})
        self.assertEqual(strength["summary"]["expected_chunk_qrel_count"], 0)
        self.assertIn("document_only_qrels", strength["issue_codes"])
        self.assertIn("single_target_document", strength["issue_codes"])
        self.assertIn("missing_strict_evidence", strength["issue_codes"])
        self.assertIn("benchmark_document_only_qrels", {issue["code"] for issue in preflight["issues"]})

    def test_preflight_applies_explicit_benchmark_strength_gate_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            gate = root / "gate.json"
            queries.write_text(
                json.dumps({"queries": [{"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}}]}),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}}), encoding="utf-8")
            gate.write_text(
                json.dumps(
                    {
                        "thresholds": {
                            "min_query_count": 3,
                            "min_qrel_strength": 0.7,
                            "min_expected_chunk_coverage": 1.0,
                            "min_query_type_diversity": 2,
                        }
                    }
                ),
                encoding="utf-8",
            )

            preflight = preflight_benchmark_dataset(queries_path=queries, qrels_path=qrels, gate_config_path=gate)

        self.assertFalse(preflight["ok"])
        self.assertEqual(preflight["benchmark_strength"]["status"], "blocked")
        codes = {issue["code"] for issue in preflight["issues"]}
        self.assertIn("benchmark_min_query_count_not_met", codes)
        self.assertIn("benchmark_min_qrel_strength_not_met", codes)
        self.assertIn("benchmark_min_expected_chunk_coverage_not_met", codes)
        self.assertIn("benchmark_min_query_type_diversity_not_met", codes)

    def test_preflight_reports_mixed_strict_and_multimodal_benchmark_strength(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {
                                "id": "q1",
                                "question": "Which table value is supported?",
                                "expected_terms": ["42"],
                                "metadata": {"type": "table_lookup", "expected_modalities": ["table"]},
                            },
                            {
                                "id": "q2",
                                "question": "Which image evidence is relevant?",
                                "expected_terms": ["diagram"],
                                "metadata": {"type": "image_lookup", "modalities": ["image"]},
                            },
                            {
                                "id": "q3",
                                "question": "Which wrong document should be rejected?",
                                "metadata": {"type": "negative_control"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps(
                    {
                        "qrels": [
                            {
                                "query_id": "q1",
                                "expected_documents": ["table-source.md"],
                                "expected_chunks": ["chunk-table-001"],
                                "metadata": {"expected_modality": "table"},
                            },
                            {
                                "query_id": "q2",
                                "target": "chunk-image-001",
                                "field": "expected_chunk",
                                "metadata": {"expected_modalities": ["image"]},
                            },
                            {
                                "query_id": "q3",
                                "target": "distractor.md",
                                "field": "document",
                                "metadata": {"case_type": "negative_control"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {"id": "qa1", "question_id": "q1", "answer": "42"},
                            {"id": "qa2", "question_id": "q2", "answer": "diagram"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            preflight = preflight_benchmark_dataset(queries_path=queries, qrels_path=qrels, qa_path=qa)

        strength = preflight["benchmark_strength"]
        self.assertTrue(preflight["ok"], preflight["issues"])
        self.assertEqual(strength["status"], "promotable")
        self.assertEqual(strength["summary"]["expected_chunk_qrel_count"], 2)
        self.assertEqual(strength["summary"]["expected_chunk_coverage"], 0.6667)
        self.assertEqual(strength["summary"]["expected_modality_query_count"], 2)
        self.assertEqual(strength["summary"]["expected_modality_coverage"], 0.6667)
        self.assertEqual(strength["summary"]["negative_case_query_count"], 1)
        self.assertEqual(strength["summary"]["negative_case_coverage"], 0.3333)
        self.assertEqual(strength["summary"]["query_type_count"], 3)
        self.assertNotIn("missing_strict_evidence", strength["issue_codes"])

    def test_import_benchmark_dataset_can_checkpoint_and_resume_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            output = root / "benchmark"
            checkpoint = root / "benchmark-import.checkpoint.json"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {"id": "q1", "question": "What is supported?", "metadata": {"type": "fact"}},
                            {"id": "q2", "question": "What can resume?", "metadata": {"type": "workflow"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(json.dumps({"q1": {"source.md": 1}, "q2": {"resume.md": 1}}), encoding="utf-8")
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {"id": "qa1", "query_id": "q1", "question": "What is supported?", "answer": "Benchmark import."},
                            {"id": "qa2", "query_id": "q2", "question": "What can resume?", "answer": "Checkpoint resume."},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            first = import_benchmark_dataset(
                queries_path=queries,
                qrels_path=qrels,
                qa_path=qa,
                output_dir=output,
                checkpoint_path=checkpoint,
                batch_size=1,
            )
            partial_queries = json.loads((output / "queries.json").read_text(encoding="utf-8"))
            partial_qrels = json.loads((output / "qrels.json").read_text(encoding="utf-8"))
            partial_qa = json.loads((output / "qa.json").read_text(encoding="utf-8"))

            second = import_benchmark_dataset(
                queries_path=queries,
                qrels_path=qrels,
                qa_path=qa,
                output_dir=output,
                checkpoint_path=checkpoint,
                resume=True,
                batch_size=1,
            )
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            final_queries = json.loads((output / "queries.json").read_text(encoding="utf-8"))
            final_qrels = json.loads((output / "qrels.json").read_text(encoding="utf-8"))
            final_qa = json.loads((output / "qa.json").read_text(encoding="utf-8"))
            preflight = preflight_benchmark_dataset(manifest_path=output / "manifest.json")

        self.assertEqual(first["schema"], BENCHMARK_IMPORT_REPORT_SCHEMA)
        self.assertFalse(first["completed"])
        self.assertEqual(first["checkpoint"]["new_query_count"], 1)
        self.assertEqual([item["id"] for item in partial_queries["queries"]], ["q1"])
        self.assertEqual([item["query_id"] for item in partial_qrels["qrels"]], ["q1"])
        self.assertEqual([item["id"] for item in partial_qa["items"]], ["qa1"])

        self.assertTrue(second["completed"])
        self.assertEqual(second["checkpoint"]["resume"], True)
        self.assertEqual(second["checkpoint"]["processed_query_count"], 2)
        self.assertEqual(checkpoint_payload["schema"], BENCHMARK_IMPORT_CHECKPOINT_SCHEMA)
        self.assertTrue(checkpoint_payload["summary"]["completed"])
        self.assertEqual(checkpoint_payload["processed_query_ids"], ["q1", "q2"])
        self.assertEqual([item["id"] for item in final_queries["queries"]], ["q1", "q2"])
        self.assertEqual([item["query_id"] for item in final_qrels["qrels"]], ["q1", "q2"])
        self.assertEqual([item["id"] for item in final_qa["items"]], ["qa1", "qa2"])
        self.assertTrue(preflight["ok"], preflight["issues"])

    def test_snapshot_chunks_from_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "validation_report.json"
            snapshot_path = root / "chunk_snapshot.json"
            report_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "q1",
                                "top_chunks": [
                                    {
                                        "content": "Expected evidence body",
                                        "document_name": "source.md",
                                        "chunk_id": "chunk-a",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = snapshot_chunks(input_path=report_path, output_path=snapshot_path)
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], CHUNK_SNAPSHOT_REPORT_SCHEMA)
        self.assertEqual(snapshot["schema"], "ragflow_chunk_snapshot_v1")
        self.assertEqual(snapshot["summary"]["chunk_count"], 1)
        self.assertEqual(snapshot["summary"]["content_coverage"], 1.0)
        self.assertEqual(snapshot["summary"]["document_name_coverage"], 1.0)
        self.assertEqual(snapshot["summary"]["chunk_id_coverage"], 1.0)
        self.assertEqual(snapshot["document_coverage"][0]["document_name"], "source.md")
        self.assertEqual(snapshot["document_coverage"][0]["chunk_count"], 1)
        self.assertTrue(snapshot["chunks"][0]["stable_hash"].startswith("sha256:"))
        self.assertIn("chunk-a", snapshot["chunks"][0]["aliases"])

    def test_snapshot_chunks_reviews_table_fragmentation_duplicates_and_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "validation_report.json"
            snapshot_path = root / "chunk_snapshot.json"
            table = "| Model | Value |\n| --- | --- |\n| HH-A | 10 |"
            report_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "q1",
                                "top_chunks": [
                                    {
                                        "content": table,
                                        "document_name": "table.md",
                                        "chunk_id": "table-a",
                                    },
                                    {
                                        "content": "| Model | Value |\n| HH-B | 20 |",
                                        "document_name": "table.md",
                                        "chunk_id": "table-b",
                                    },
                                    {
                                        "content": table,
                                        "document_name": "duplicate.md",
                                        "chunk_id": "table-duplicate",
                                    },
                                    {
                                        "content": "![chart](images/chart.png)",
                                        "document_name": "image.md",
                                        "chunk_id": "image-only",
                                    },
                                    {
                                        "content": "Plain text <!-- chunk --> still visible.",
                                        "document_name": "plain.md",
                                        "chunk_id": "delimiter",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = snapshot_chunks(input_path=report_path, output_path=snapshot_path)

        review = report["chunk_review"]
        self.assertTrue(review["advisory_only"])
        self.assertEqual(review["ragflow_calls"], 0)
        self.assertEqual(review["metrics"]["table_like_chunk_count"], 3)
        self.assertGreaterEqual(review["metrics"]["possible_split_table_chunk_count"], 1)
        self.assertEqual(review["metrics"]["duplicate_table_like_chunk_count"], 1)
        self.assertEqual(review["metrics"]["delimiter_visible_chunk_count"], 1)
        self.assertEqual(review["metrics"]["image_only_chunk_count"], 1)
        self.assertGreater(report["summary"]["max_chunk_chars"], 0)
        issue_codes = {issue["code"] for issue in review["issues"]}
        self.assertIn("possible_table_fragmentation", issue_codes)
        self.assertIn("duplicate_table_like_chunks", issue_codes)
        self.assertIn("chunk_delimiter_visible_in_snapshot", issue_codes)

    def test_validate_grounded_qa_accepts_exact_source_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "source.md").write_text(
                "# Source\n\nThe supported answer is copied exactly from here.\n",
                encoding="utf-8",
            )
            qa = root / "qa.json"
            qa.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "What is supported?",
                                "answer": "The supported answer.",
                                "evidence": [
                                    {
                                        "document": "source.md",
                                        "text": "The supported answer is copied exactly from here.",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = validate_grounded_qa(qa_path=qa, source_dir=source_dir)

        self.assertEqual(report["schema"], GROUNDED_QA_VALIDATE_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["item_count"], 1)
        self.assertEqual(report["summary"]["grounded_span_count"], 1)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)

    def test_generate_grounded_qa_from_source_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            source = source_dir / "source.md"
            output = root / "qa.json"
            source.write_text(
                "# Runtime Notes\n\nThe deterministic generator copies this exact evidence sentence for validation.\n",
                encoding="utf-8",
            )

            report = generate_grounded_qa(
                source_dir=source_dir,
                output_path=output,
                count=1,
                min_span_chars=20,
            )
            qa_payload = json.loads(output.read_text(encoding="utf-8"))
            validate_report = validate_grounded_qa(qa_path=output, source_dir=source_dir)

        self.assertEqual(report["schema"], GROUNDED_QA_GENERATE_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["item_count"], 1)
        self.assertEqual(qa_payload["schema"], "ragflow_grounded_qa_v1")
        self.assertEqual(qa_payload["items"][0]["answer"], qa_payload["items"][0]["evidence"][0]["text"])
        self.assertTrue(validate_report["ok"], validate_report["issues"])

    def test_generate_grounded_qa_requires_checkpoint_for_batch_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "source.md").write_text(
                "The deterministic generator can resume batches only when a checkpoint is configured.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(BenchmarkGovernanceError, "--batch-size requires --checkpoint"):
                generate_grounded_qa(
                    source_dir=source_dir,
                    output_path=root / "qa.json",
                    count=1,
                    min_span_chars=20,
                    batch_size=1,
                )

    def test_validate_grounded_qa_rejects_missing_or_unmatched_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sources.json"
            source.write_text(json.dumps({"source.md": "Only this source sentence exists."}), encoding="utf-8")
            qa = root / "qa.json"
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {"id": "missing", "question": "Missing evidence?", "answer": "No evidence."},
                            {
                                "id": "unmatched",
                                "question": "Wrong evidence?",
                                "answer": "Wrong evidence.",
                                "evidence": [{"document": "source.md", "quote": "This sentence is not present."}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = validate_grounded_qa(qa_path=qa, sources_path=source)

        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["invalid_item_count"], 2)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "failed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 2)
        self.assertEqual(
            [issue["code"] for issue in report["issues"]],
            ["qa_item_missing_evidence", "evidence_span_not_found"],
        )

    def test_validate_grounded_qa_runtime_partial_failure_reports_mixed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sources.json"
            source.write_text(json.dumps({"source.md": "The grounded sentence is present."}), encoding="utf-8")
            qa = root / "qa.json"
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "valid",
                                "question": "What is present?",
                                "answer": "A grounded sentence.",
                                "evidence": [{"document": "source.md", "text": "The grounded sentence is present."}],
                            },
                            {
                                "id": "invalid",
                                "question": "What is absent?",
                                "answer": "An absent sentence.",
                                "evidence": [{"document": "source.md", "text": "This span is absent."}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = validate_grounded_qa(qa_path=qa, sources_path=source)

        self.assertFalse(report["ok"])
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["validated"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["invalid"], 1)

    def test_validate_grounded_qa_runtime_partial_failure_marks_unchecked_sources_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa = root / "qa.json"
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "unchecked",
                                "question": "What is unchecked?",
                                "answer": "Evidence was supplied.",
                                "evidence": [{"document": "source.md", "text": "The span is not source-checked."}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = validate_grounded_qa(qa_path=qa)

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "skipped")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["skipped_count"], 1)

    def test_grounded_qa_suggestion_request_and_review_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            source = source_dir / "source.md"
            source.write_text("The grounded suggestion answer is copied exactly from this source.\n", encoding="utf-8")
            request_path = root / "qa_suggestion_request.json"
            candidate = root / "qa_suggestion_candidate.json"
            snapshot = root / "chunk_snapshot.json"
            evidence_map = root / "qa_suggestion_evidence_map.json"
            candidate.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "advisory": True,
                        "generated": True,
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "What is copied exactly?",
                                "answer": "The grounded suggestion answer.",
                                "evidence": [
                                    {
                                        "document": "source.md",
                                        "text": "The grounded suggestion answer is copied exactly from this source.",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "c" * 64,
                                "content": "The grounded suggestion answer is copied exactly from this source.",
                                "document_name": "source.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            request = create_grounded_qa_suggestion_request(
                source_dir=source_dir,
                target_count=1,
                question_types=["direct_fact"],
                include_excerpts=True,
            )
            request_path.write_text(json.dumps(request), encoding="utf-8")
            review = review_grounded_qa_suggestions(
                candidate_path=candidate,
                request_path=request_path,
                source_dir=source_dir,
                chunk_snapshot_path=snapshot,
                evidence_map_output_path=evidence_map,
            )
            evidence_map_payload = json.loads(evidence_map.read_text(encoding="utf-8"))

        self.assertEqual(request["schema"], GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA)
        self.assertTrue(request["ok"], request["issues"])
        self.assertFalse(request["llm_invoked"])
        self.assertEqual(request["summary"]["target_count"], 1)
        self.assertIn("request_hash", request)
        self.assertEqual(review["schema"], GROUNDED_QA_SUGGESTION_REVIEW_REPORT_SCHEMA)
        self.assertTrue(review["ok"], review["issues"])
        self.assertTrue(review["summary"]["validation_ok"])
        self.assertTrue(review["summary"]["evidence_map_ok"])
        self.assertEqual(review["summary"]["mapped_span_count"], 1)
        self.assertEqual(evidence_map_payload["schema"], GROUNDED_QA_EVIDENCE_MAP_SCHEMA)

    def test_grounded_qa_suggestion_review_rejects_unmarked_external_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "source.md").write_text("Grounded evidence must be marked as generated.\n", encoding="utf-8")
            candidate = root / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "What must be marked?",
                                "answer": "Generated evidence.",
                                "evidence": [{"document": "source.md", "text": "Grounded evidence must be marked as generated."}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            review = review_grounded_qa_suggestions(candidate_path=candidate, source_dir=source_dir)

        self.assertFalse(review["ok"])
        codes = {issue["code"] for issue in review["issues"]}
        self.assertIn("qa_suggestion_not_advisory", codes)
        self.assertIn("qa_suggestion_not_generated", codes)

    def test_grounded_qa_suggestion_review_requires_evidence_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "advisory": True,
                        "generated": True,
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "What must be documented?",
                                "answer": "Evidence.",
                                "evidence": [{"text": "Evidence without a source document."}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            review = review_grounded_qa_suggestions(candidate_path=candidate)

        self.assertFalse(review["ok"])
        codes = {issue["code"] for issue in review["issues"]}
        self.assertIn("qa_suggestion_evidence_document_missing", codes)

    def test_map_grounded_qa_evidence_to_chunk_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = root / "chunks.json"
            snapshot = root / "chunk_snapshot.json"
            qa = root / "qa.json"
            output = root / "qa_evidence_map.json"
            chunks.write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "content": "The mapped evidence sentence appears in this chunk.",
                                "document_name": "source.md",
                                "chunk_id": "chunk-a",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            snapshot_chunks(input_path=chunks, output_path=snapshot, include_content=True)
            stable_hash = json.loads(snapshot.read_text(encoding="utf-8"))["chunks"][0]["stable_hash"]
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "qa-1",
                                "query_id": "q1",
                                "question": "What evidence is mapped?",
                                "answer": "The mapped evidence sentence.",
                                "evidence": [
                                    {
                                        "document": "source.md",
                                        "text": "The mapped evidence sentence appears in this chunk.",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = map_grounded_qa_evidence(qa_path=qa, chunk_snapshot_path=snapshot, output_path=output)
            evidence_map = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], GROUNDED_QA_EVIDENCE_MAP_REPORT_SCHEMA)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "completed")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(evidence_map["schema"], GROUNDED_QA_EVIDENCE_MAP_SCHEMA)
        self.assertEqual(evidence_map["summary"]["mapped_span_count"], 1)
        self.assertEqual(evidence_map["summary"]["evidence_mapping_coverage"], 1.0)
        self.assertEqual(evidence_map["summary"]["evidence_mapping_confidence"], 1.0)
        self.assertEqual(evidence_map["summary"]["mapped_chunk_coverage"], 1.0)
        self.assertEqual(evidence_map["items"][0]["expected_chunks"], [stable_hash])
        self.assertEqual(evidence_map["summary"]["qrels_template_item_count"], 1)
        self.assertEqual(evidence_map["qrels_template"]["qrels"][0]["query_id"], "q1")
        self.assertEqual(evidence_map["qrels_template"]["qrels"][0]["expected_chunks"], [stable_hash])
        self.assertEqual(evidence_map["qrels_template"]["qrels"][0]["expected_documents"], ["source.md"])
        self.assertEqual(report["qrels_template"]["qrels"][0]["expected_chunks"], [stable_hash])
        self.assertEqual(evidence_map["items"][0]["evidence"][0]["document_match_status"], "document_match")
        self.assertEqual(evidence_map["items"][0]["evidence"][0]["mapping_confidence"], 1.0)

    def test_map_grounded_qa_evidence_reports_unmapped_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            qa = root / "qa.json"
            output = root / "qa_evidence_map.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "a" * 64,
                                "content": "A different sentence.",
                                "document_name": "source.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "qa-1",
                                "question": "What is missing?",
                                "answer": "Missing.",
                                "evidence": [{"document": "source.md", "text": "This span is absent."}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = map_grounded_qa_evidence(qa_path=qa, chunk_snapshot_path=snapshot, output_path=output)

        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["unmapped_span_count"], 1)
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "failed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["unmapped"], 1)
        self.assertEqual(report["summary"]["evidence_mapping_confidence"], 0.0)
        self.assertEqual(report["issues"][0]["code"], "evidence_span_unmapped")

    def test_map_grounded_qa_evidence_runtime_partial_failure_reports_mixed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            qa = root / "qa.json"
            output = root / "qa_evidence_map.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "b" * 64,
                                "content": "The mapped sentence is available.",
                                "document_name": "source.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "mapped",
                                "question": "What maps?",
                                "answer": "The mapped sentence.",
                                "evidence": [{"document": "source.md", "text": "The mapped sentence is available."}],
                            },
                            {
                                "id": "unmapped",
                                "question": "What does not map?",
                                "answer": "The absent sentence.",
                                "evidence": [{"document": "source.md", "text": "The absent sentence is unavailable."}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = map_grounded_qa_evidence(qa_path=qa, chunk_snapshot_path=snapshot, output_path=output)

        self.assertFalse(report["ok"])
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["mapped"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["unmapped"], 1)

    def test_map_grounded_qa_evidence_runtime_partial_failure_reports_warning_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "chunk_snapshot.json"
            qa = root / "qa.json"
            output = root / "qa_evidence_map.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_chunk_snapshot_v1",
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "stable_hash": "sha256:" + "c" * 64,
                                "content": "The mapped sentence is available.",
                                "document_name": "other.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "warning",
                                "question": "What maps elsewhere?",
                                "answer": "The mapped sentence.",
                                "evidence": [{"document": "source.md", "text": "The mapped sentence is available."}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = map_grounded_qa_evidence(qa_path=qa, chunk_snapshot_path=snapshot, output_path=output)

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["issues"][0]["code"], "evidence_document_unmatched")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "completed_with_warnings")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["warning_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["status_counts"]["mapped_with_warnings"], 1)

    def test_sample_benchmark_dataset_is_deterministic_and_filters_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            qa = root / "qa.json"
            imported = root / "benchmark"
            sampled = root / "sampled"
            sampled_again = root / "sampled-again"
            queries.write_text(
                json.dumps(
                    {
                        "queries": [
                            {"id": "q1", "question": "Fact one?", "metadata": {"type": "fact"}},
                            {"id": "q2", "question": "Fact two?", "metadata": {"type": "fact"}},
                            {"id": "q3", "question": "How to compare?", "metadata": {"type": "comparison"}},
                            {"id": "q4", "question": "How to troubleshoot?", "metadata": {"type": "diagnostic"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps(
                    {
                        "q1": {"one.md": 1},
                        "q2": {"two.md": 1},
                        "q3": {"three.md": 1},
                        "q4": {"four.md": 1},
                    }
                ),
                encoding="utf-8",
            )
            qa.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_grounded_qa_v1",
                        "items": [
                            {"query_id": "q1", "answer": "one"},
                            {"query_id": "q2", "answer": "two"},
                            {"query_id": "q3", "answer": "three"},
                            {"query_id": "q4", "answer": "four"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            import_benchmark_dataset(queries_path=queries, qrels_path=qrels, qa_path=qa, output_dir=imported)

            sample = sample_benchmark_dataset(
                manifest_path=imported / "manifest.json",
                output_dir=sampled,
                sample_size=3,
                strategy="stratified",
                seed=7,
            )
            sample_again = sample_benchmark_dataset(
                manifest_path=imported / "manifest.json",
                output_dir=sampled_again,
                sample_size=3,
                strategy="stratified",
                seed=7,
            )
            sampled_queries = json.loads((sampled / "queries.json").read_text(encoding="utf-8"))
            sampled_qrels = json.loads((sampled / "qrels.json").read_text(encoding="utf-8"))
            sampled_qa = json.loads((sampled / "qa.json").read_text(encoding="utf-8"))
            manifest = json.loads((sampled / "manifest.json").read_text(encoding="utf-8"))

        selected_ids = [query["id"] for query in sampled_queries["queries"]]
        self.assertEqual(sample["schema"], BENCHMARK_SAMPLE_REPORT_SCHEMA)
        self.assertEqual(sample["sampling"]["selected_query_ids"], sample_again["sampling"]["selected_query_ids"])
        self.assertEqual(len(selected_ids), 3)
        self.assertEqual(set(sampled_qrels["qrels"][index]["query_id"] for index in range(len(sampled_qrels["qrels"]))), set(selected_ids))
        self.assertEqual(set(item["query_id"] for item in sampled_qa["items"]), set(selected_ids))
        self.assertEqual(manifest["sampling"]["strategy"], "stratified")
        self.assertEqual(manifest["sampling"]["seed"], 7)

    def test_preflight_fails_when_query_has_no_qrels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "Missing qrel?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"q2": {"source.md": 1}}), encoding="utf-8")

            report = preflight_benchmark_dataset(queries_path=queries, qrels_path=qrels)

        self.assertFalse(report["ok"])
        self.assertIn("query_without_qrels", {issue["code"] for issue in report["issues"]})

    def test_summarize_and_gate_existing_benchmark_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "benchmark_report.json"
            gate_path = root / "gate.json"
            report_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "query_count": 1,
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                                "supporting_document_coverage": 1.0,
                            },
                            "query_type_breakdown": {"fact": {"query_count": 1, "hit_rate": 1.0}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate_path.write_text(json.dumps({"thresholds": {"min_hit_rate": 1.0, "max_empty_result_rate": 0.0}}), encoding="utf-8")

            summary = summarize_benchmark_report(report_path)
            gate = gate_benchmark_report(report_path=report_path, gate_config_path=gate_path)

        self.assertEqual(summary["schema"], BENCHMARK_SUMMARY_REPORT_SCHEMA)
        self.assertTrue(summary["ok"])
        self.assertEqual(gate["schema"], BENCHMARK_GATE_REPORT_SCHEMA)
        self.assertTrue(gate["ok"], gate["gate"])

    def test_summarize_reports_root_cause_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "benchmark_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "query_count": 2,
                                "hit_rate": 0.5,
                                "mrr": 0.25,
                                "precision_at_k": 0.2,
                                "recall_at_k": 0.5,
                                "ndcg_at_k": 0.3,
                                "map_at_k": 0.25,
                                "empty_result_rate": 0.5,
                                "supporting_document_coverage": 0.5,
                                "tag_pollution_rate": 0.2,
                                "grounded_answer_rate": 0.7,
                                "citation_coverage": 0.4,
                                "over_abstention_rate": 0.1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_benchmark_report(report_path)

        hint_codes = {hint["code"] for hint in summary["quality_hints"]}
        self.assertIn("retrieval_coverage_gap", hint_codes)
        self.assertIn("ranking_gap", hint_codes)
        self.assertIn("tag_pollution", hint_codes)
        self.assertIn("generation_grounding_gap", hint_codes)
        self.assertIn("citation_gap", hint_codes)
        self.assertIn("over_abstention", hint_codes)

    def test_trend_and_delta_reports_compare_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            gate = root / "gate.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 0.8,
                                "precision_at_k": 0.4,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.8,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.5,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate.write_text(json.dumps({"thresholds": {"min_mrr": 0.9, "max_mrr_drop": 0.05}}), encoding="utf-8")

            trend = trend_benchmark_reports(
                current_report_path=current,
                baseline_report_path=baseline,
                gate_config_path=gate,
            )
            delta = delta_benchmark_reports(current_report_path=current, baseline_report_path=baseline)

        self.assertEqual(trend["schema"], BENCHMARK_TREND_REPORT_SCHEMA)
        self.assertTrue(trend["ok"], trend["gate"])
        self.assertAlmostEqual(trend["delta"]["mrr"]["absolute"], 0.2)
        self.assertEqual(delta["schema"], BENCHMARK_DELTA_REPORT_SCHEMA)
        self.assertIn("mrr", delta["summary"]["improved"])

    def test_benchmark_retrieval_suggestions_from_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            gate = root / "gate.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 0.9,
                                "precision_at_k": 0.7,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.95,
                                "map_at_k": 0.9,
                                "empty_result_rate": 0.0,
                                "strict_chunk_recall_at_k": 1.0,
                                "expected_chunk_hit_rate": 1.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "cutoff": 3,
                            "metrics": {
                                "hit_rate": 0.5,
                                "mrr": 0.4,
                                "precision_at_k": 0.5,
                                "recall_at_k": 0.5,
                                "ndcg_at_k": 0.45,
                                "map_at_k": 0.4,
                                "empty_result_rate": 0.5,
                                "strict_chunk_recall_at_k": 0.5,
                                "expected_chunk_hit_rate": 0.5,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate.write_text(json.dumps({"thresholds": {"min_hit_rate": 0.9, "max_empty_result_rate": 0.0}}), encoding="utf-8")

            report = suggest_benchmark_retrieval_parameters(
                report_path=current,
                baseline_report_path=baseline,
                gate_config_path=gate,
                current_similarity_threshold=0.35,
            )

        self.assertEqual(report["schema"], BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA)
        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(report["current_parameters"]["retrieval.top_k"], 3)
        suggestions = {item["parameter"]: item for item in report["retrieval_parameter_suggestions"]}
        self.assertEqual(suggestions["retrieval.top_k"]["action"], "increase")
        self.assertGreater(suggestions["retrieval.top_k"]["suggested"], 3)
        self.assertEqual(suggestions["retrieval.similarity_threshold"]["action"], "lower")
        self.assertLess(suggestions["retrieval.similarity_threshold"]["suggested"], 0.35)
        self.assertIn("hit_rate", report["delta"])
        self.assertFalse(report["gate"]["ok"], report["gate"])

    def test_suggest_benchmark_artifacts_from_retrieval_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current.json"
            hints = root / "retrieval_hints.json"
            current.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "cutoff": 5,
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 1.0,
                                "precision_at_k": 0.6,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 1.0,
                                "map_at_k": 1.0,
                                "empty_result_rate": 0.0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            hints.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_retrieval_hints_v1",
                        "table_artifacts": [
                            {
                                "document": "documents/apollo.md",
                                "caption": "APOLLO torque table",
                                "source_heading": "Torque specs",
                                "model_label_candidates": ["HH-A", "HH-B"],
                                "header_preview": ["Model", "Rated torque"],
                            }
                        ],
                        "image_artifacts": [
                            {
                                "document": "documents/apollo.md",
                                "path": "images/apollo-panel.png",
                                "caption": "APOLLO control panel",
                                "semantic_kind": "diagram",
                            }
                        ],
                        "section_boundaries": [
                            {"document": "documents/apollo.md", "title": "Torque specs"},
                            {"document": "documents/warranty.md", "title": "Warranty"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = suggest_benchmark_retrieval_parameters(report_path=current, retrieval_hints_path=hints)

        self.assertEqual(report["schema"], BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA)
        self.assertEqual(report["retrieval_hints"]["schema"], "ragflow_retrieval_hints_v1")
        self.assertEqual(report["summary"]["benchmark_artifact_suggestion_count"], 4)
        suggestions = {item["id"]: item for item in report["benchmark_artifact_suggestions"]}
        self.assertEqual(suggestions["hint_table_001"]["query_type"], "table_value")
        self.assertEqual(suggestions["hint_table_001"]["qrel_template"]["expected_modalities"], ["table"])
        self.assertIn("HH-A", suggestions["hint_table_001"]["query_template"])
        self.assertEqual(suggestions["hint_image_001"]["query_type"], "visual_identification")
        self.assertEqual(suggestions["hint_image_001"]["qrel_template"]["expected_modalities"], ["image"])
        self.assertEqual(suggestions["hint_mixed_001"]["query_type"], "mixed_table_plus_image")
        self.assertEqual(suggestions["hint_mixed_001"]["qrel_template"]["expected_modalities"], ["mixed", "table", "image"])
        self.assertEqual(suggestions["hint_negative_001"]["kind"], "wrong_document_negative")

    def test_trend_and_delta_reports_root_cause_regression_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            baseline.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 1.0,
                                "mrr": 0.9,
                                "recall_at_k": 1.0,
                                "ndcg_at_k": 0.9,
                                "map_at_k": 0.9,
                                "empty_result_rate": 0.0,
                                "tag_pollution_rate": 0.0,
                                "grounded_answer_rate": 1.0,
                                "citation_coverage": 1.0,
                                "over_abstention_rate": 0.0,
                                "average_latency_ms": 100.0,
                                "estimated_cost_usd": 0.01,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            current.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "dataset": {"id": "ds-1", "name": "kb:test"},
                        "benchmark": {
                            "metrics": {
                                "hit_rate": 0.8,
                                "mrr": 0.6,
                                "recall_at_k": 0.8,
                                "ndcg_at_k": 0.6,
                                "map_at_k": 0.6,
                                "empty_result_rate": 0.1,
                                "tag_pollution_rate": 0.2,
                                "grounded_answer_rate": 0.6,
                                "citation_coverage": 0.5,
                                "over_abstention_rate": 0.2,
                                "average_latency_ms": 250.0,
                                "estimated_cost_usd": 0.03,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            trend = trend_benchmark_reports(current_report_path=current, baseline_report_path=baseline)
            delta = delta_benchmark_reports(current_report_path=current, baseline_report_path=baseline)

        trend_codes = {hint["code"] for hint in trend["quality_hints"]}
        delta_codes = {hint["code"] for hint in delta["quality_hints"]}
        for code in {
            "retrieval_coverage_gap",
            "ranking_gap",
            "tag_pollution",
            "generation_grounding_gap",
            "citation_gap",
            "over_abstention",
            "cost_or_latency_regression",
        }:
            self.assertIn(code, trend_codes)
            self.assertIn(code, delta_codes)

    def test_suppression_report_identifies_pollution_candidates(self) -> None:
        report = {
            "ok": False,
            "level": "benchmark",
            "dataset": {"id": "ds-1", "name": "kb:test"},
            "cases": [
                {
                    "id": "q1",
                    "question": "What is the payroll retention policy?",
                    "passed": False,
                    "document_hits": ["expected.md"],
                    "metadata": {"type": "fact", "allowed_tags": ["policy"]},
                    "top_chunks": [
                        {
                            "content": "Payroll retention policy expected evidence.",
                            "document_name": "expected.md",
                            "chunk_id": "expected-1",
                            "raw": {
                                "content_with_weight": "Payroll retention policy expected evidence.",
                                "docnm_kwd": "expected.md",
                                "id": "expected-1",
                                "tags": ["policy"],
                            },
                        },
                        {
                            "content": "Payroll bridge term appears in a finance benefits source.",
                            "document_name": "finance.md",
                            "document_id": "doc-finance",
                            "chunk_id": "wrong-1",
                            "raw": {
                                "content_with_weight": "Payroll bridge term appears in a finance benefits source.",
                                "docnm_kwd": "finance.md",
                                "doc_id": "doc-finance",
                                "id": "wrong-1",
                                "tags": ["policy", "finance"],
                            },
                        },
                    ],
                }
            ],
            "benchmark": {
                "metrics": {
                    "wrong_document_rate": 0.5,
                    "tag_pollution_rate": 0.5,
                    "unexpected_tag_hit_rate": 1.0,
                },
                "per_query": [
                    {
                        "id": "q1",
                        "wrong_document_count": 1,
                        "tag_pollution_rate": 0.5,
                        "unexpected_tag_count": 1,
                    }
                ],
                "query_type_breakdown": {"fact": {"query_count": 1, "wrong_document_rate": 0.5}},
            },
        }

        suppression = suppression_report_payload(report)
        candidates_by_kind = {candidate["kind"]: candidate for candidate in suppression["candidates"]}
        markdown = render_suppression_report_markdown(suppression)

        self.assertEqual(suppression["schema"], SUPPRESSION_REPORT_SCHEMA)
        self.assertTrue(suppression["ok"], suppression["issues"])
        self.assertEqual(suppression["summary"]["polluted_case_count"], 1)
        self.assertGreater(suppression["summary"]["raw_chunk_coverage"], 0)
        self.assertIn("bridge_term", candidates_by_kind)
        self.assertIn("source_boundary", candidates_by_kind)
        self.assertIn("allowed_tag_review", candidates_by_kind)
        self.assertIn("unexpected_tag", candidates_by_kind)
        self.assertEqual(candidates_by_kind["bridge_term"]["risk"], "low")
        self.assertEqual(candidates_by_kind["allowed_tag_review"]["risk"], "high")
        self.assertIsInstance(candidates_by_kind["unexpected_tag"]["risk_score"], float)
        self.assertIn("finance.md", candidates_by_kind["source_boundary"]["evidence"]["document_names"])
        self.assertIn("RAGFlow Suppression Report", markdown)
        self.assertIn("Bridge Terms", markdown)


if __name__ == "__main__":
    unittest.main()
