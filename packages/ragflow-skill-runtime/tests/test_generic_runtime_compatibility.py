from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from ragflow_skill_runtime.benchmark_governance import (
    BenchmarkGovernanceError,
    create_benchmark_split_freeze,
    verify_benchmark_split_freeze,
)
from ragflow_skill_runtime.health_report import HealthReportError, create_compatibility_readiness
from ragflow_skill_runtime.kb_build import (
    BuildError,
    dataset_construction_fingerprint,
    review_dataset_create_recovery,
    verify_image_transport_capability,
    dataset_create_response_diagnostics,
)
from ragflow_skill_runtime.retrieval_hint_governance import (
    RetrievalHintGovernanceError,
    candidate_artifact_sha256,
    create_reviewed_retrieval_hints,
    decorate_candidate_hints,
    validate_reviewed_retrieval_hints,
)
from ragflow_skill_runtime.topology import create_kb_activation_plan


class TestGenericRuntimeCompatibility(unittest.TestCase):
    def test_construction_fingerprint_is_canonical_and_recovery_requires_unique_match(self) -> None:
        first = dataset_construction_fingerprint(
            dataset_name="staging-kb",
            create_payload={"parser_config": {"chunk_token_num": 512}, "chunk_method": "naive"},
            source_hashes=["b" * 64, "a" * 64],
        )
        second = dataset_construction_fingerprint(
            dataset_name="staging-kb",
            create_payload={"chunk_method": "naive", "parser_config": {"chunk_token_num": 512}},
            source_hashes=["b" * 64, "a" * 64],
        )
        self.assertEqual(first, second)
        reordered = dataset_construction_fingerprint(
            dataset_name="staging-kb",
            create_payload={"chunk_method": "naive", "parser_config": {"chunk_token_num": 512}},
            source_hashes=["a" * 64, "b" * 64],
        )
        duplicated = dataset_construction_fingerprint(
            dataset_name="staging-kb",
            create_payload={"chunk_method": "naive", "parser_config": {"chunk_token_num": 512}},
            source_hashes=["b" * 64, "a" * 64, "b" * 64],
        )
        self.assertNotEqual(first, reordered)
        self.assertNotEqual(first, duplicated)
        with self.assertRaisesRegex(BuildError, "SHA-256 source hashes"):
            dataset_construction_fingerprint(
                dataset_name="staging-kb",
                create_payload={},
                source_hashes=["a" * 64, ""],
            )
        recovered = review_dataset_create_recovery(
            dataset_name="staging-kb",
            construction_fingerprint=first,
            candidates=[{"id": "dataset-1", "name": "staging-kb", "construction_fingerprint": first}],
        )
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["dataset_id"], "dataset-1")

        with self.assertRaisesRegex(BuildError, "ambiguous"):
            review_dataset_create_recovery(
                dataset_name="staging-kb",
                construction_fingerprint=first,
                candidates=[
                    {"id": "dataset-1", "name": "staging-kb", "construction_fingerprint": first},
                    {"id": "dataset-2", "name": "staging-kb", "construction_fingerprint": first},
                ],
            )
        with self.assertRaisesRegex(BuildError, "fingerprint"):
            review_dataset_create_recovery(
                dataset_name="staging-kb",
                construction_fingerprint=first,
                candidates=[{"id": "dataset-1", "name": "staging-kb", "construction_fingerprint": "0" * 64}],
            )
        with self.assertRaisesRegex(BuildError, "no exact-name"):
            review_dataset_create_recovery(
                dataset_name="staging-kb",
                construction_fingerprint=first,
                candidates=[{"id": "dataset-1", "name": "other-kb", "construction_fingerprint": first}],
            )
        with self.assertRaisesRegex(BuildError, "identifier"):
            review_dataset_create_recovery(
                dataset_name="staging-kb",
                construction_fingerprint=first,
                candidates=[{"name": "staging-kb", "construction_fingerprint": first}],
            )

    def test_image_transport_requires_explicit_matching_capability(self) -> None:
        evidence = {
            "schema": "ragflow_transport_capability_v1",
            "source": "openapi",
            "server_version": "0.25.5",
            "operations": [
                {
                    "operation": "visual_document_upload",
                    "transport": "multipart_post",
                    "endpoint_class": "dataset_documents",
                    "supported": True,
                }
            ],
        }
        result = verify_image_transport_capability(
            evidence,
            operation="visual_document_upload",
            transport="multipart_post",
            endpoint_class="dataset_documents",
        )
        self.assertTrue(result["ok"])
        with self.assertRaisesRegex(BuildError, "not supported"):
            verify_image_transport_capability(
                evidence,
                operation="curated_image_update",
                transport="json_put",
                endpoint_class="document_detail",
            )
        parse_result = verify_image_transport_capability(
            {**evidence, "operations": [*evidence["operations"], {
                "operation": "visual_document_parse",
                "transport": "json_post",
                "endpoint_class": "dataset_chunks",
                "supported": True,
            }]},
            operation="visual_document_parse",
            transport="json_post",
            endpoint_class="dataset_chunks",
        )
        self.assertTrue(parse_result["ok"])

    def test_create_response_diagnostics_are_sanitized(self) -> None:
        diagnostics = dataset_create_response_diagnostics({"code": 101, "data": {"secret": "do-not-retain"}})
        self.assertEqual(diagnostics["classification"], "application_failure")
        self.assertEqual(diagnostics["transport_status"], "response_received")
        self.assertEqual(diagnostics["application_status"], "failure")
        self.assertEqual(diagnostics["application_code"], 101)
        self.assertEqual(diagnostics["sanitized_message"], "dataset create application status indicates failure")
        self.assertEqual(diagnostics["response_data_type"], "mapping")
        self.assertNotIn("secret", json.dumps(diagnostics))

    def test_candidate_ids_are_order_independent_and_duplicates_fail(self) -> None:
        first_payload = {
            "schema": "ragflow_retrieval_hints_v1",
            "keyword_candidates": [
                {"term": "alpha", "source_document": "doc.md"},
                {"term": "beta", "source_document": "doc.md"},
            ],
            "question_candidates": [],
            "table_term_alias_candidates": [],
        }
        second_payload = {
            **first_payload,
            "keyword_candidates": list(reversed(first_payload["keyword_candidates"])),
        }
        first = decorate_candidate_hints(first_payload, document_hashes={"doc.md": "a" * 64})
        second = decorate_candidate_hints(second_payload, document_hashes={"doc.md": "a" * 64})
        first_ids = {item["term"]: item["candidate_id"] for item in first["keyword_candidates"]}
        second_ids = {item["term"]: item["candidate_id"] for item in second["keyword_candidates"]}
        self.assertEqual(first_ids, second_ids)

        duplicate_payload = {
            **first_payload,
            "keyword_candidates": [first_payload["keyword_candidates"][0]] * 2,
        }
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "duplicate candidate id"):
            decorate_candidate_hints(duplicate_payload, document_hashes={"doc.md": "a" * 64})

    def test_reviewed_hints_are_exhaustive_hash_bound_and_catalog_safe(self) -> None:
        candidates = {
            "schema": "ragflow_retrieval_hints_v1",
            "keyword_candidates": [
                {
                    "candidate_id": "hint-keyword-1",
                    "kind": "keyword",
                    "value": "maintenance procedure",
                    "term": "maintenance procedure",
                    "source_document": "manual.md",
                    "source_document_type": "en_manual",
                    "source_constraint": "document:manual.md",
                    "content_sha256": "a" * 64,
                }
            ],
            "question_candidates": [],
            "table_term_alias_candidates": [],
        }
        digest = candidate_artifact_sha256(candidates)
        decisions = {
            "schema": "ragflow_retrieval_hint_review_decisions_v1",
            "input_sha256": digest,
            "reviewer": "owner-review",
            "decisions": [
                {
                    "candidate_id": "hint-keyword-1",
                    "decision": "reject",
                    "reason": "operational instruction is not catalog evidence",
                }
            ],
        }
        reviewed = create_reviewed_retrieval_hints(candidates, decisions)
        self.assertEqual(reviewed["summary"]["rejected_count"], 1)
        validate_reviewed_retrieval_hints(reviewed)

        inconsistent = json.loads(json.dumps(reviewed))
        inconsistent["rejected_candidates"] = []
        inconsistent["output_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in inconsistent.items() if key not in {"created_at", "output_sha256"}},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "rejected_candidates"):
            validate_reviewed_retrieval_hints(inconsistent)

        unsafe = json.loads(json.dumps(decisions))
        unsafe["decisions"][0] = {
            "candidate_id": "hint-keyword-1",
            "decision": "accept",
            "reason": "treat as catalog",
            "classification": "product_catalog",
        }
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "product catalog"):
            create_reviewed_retrieval_hints(candidates, unsafe)

        forged = json.loads(json.dumps(reviewed))
        forged_record = forged["reviewed_candidates"][0]
        forged_record["decision"] = "accept"
        forged_record["classification"] = "product_catalog"
        forged["accepted_candidates"] = [forged_record]
        forged["rejected_candidates"] = []
        forged["activation_hints"]["keyword_candidates"] = [forged_record["candidate"]]
        forged["summary"]["accepted_count"] = 1
        forged["summary"]["rejected_count"] = 0
        forged["output_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in forged.items() if key not in {"created_at", "output_sha256"}},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "product catalog"):
            validate_reviewed_retrieval_hints(forged)

        omitted = {**decisions, "decisions": []}
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "every candidate"):
            create_reviewed_retrieval_hints(candidates, omitted)

        missing_lineage = json.loads(json.dumps(candidates))
        del missing_lineage["keyword_candidates"][0]["source_document_type"]
        missing_lineage_decisions = json.loads(json.dumps(decisions))
        missing_lineage_decisions["input_sha256"] = candidate_artifact_sha256(missing_lineage)
        with self.assertRaisesRegex(RetrievalHintGovernanceError, "source_document_type"):
            create_reviewed_retrieval_hints(missing_lineage, missing_lineage_decisions)

    def test_empty_candidate_review_is_valid_and_exhaustive(self) -> None:
        candidates = {
            "schema": "ragflow_retrieval_hints_v1",
            "keyword_candidates": [],
            "question_candidates": [],
            "table_term_alias_candidates": [],
        }
        decisions = {
            "schema": "ragflow_retrieval_hint_review_decisions_v1",
            "input_sha256": candidate_artifact_sha256(candidates),
            "reviewer": "owner-review",
            "decisions": [],
        }
        reviewed = create_reviewed_retrieval_hints(candidates, decisions)

        self.assertEqual(validate_reviewed_retrieval_hints(reviewed), reviewed)
        self.assertEqual(reviewed["summary"]["candidate_count"], 0)

    def test_sealed_holdout_freeze_rejects_tuning_and_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queries = root / "queries.json"
            qrels = root / "qrels.json"
            freeze_path = root / "freeze.json"
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "Q?"}]}), encoding="utf-8")
            qrels.write_text(json.dumps({"qrels": [{"query_id": "q1", "document": "doc.md"}]}), encoding="utf-8")

            with self.assertRaisesRegex(BenchmarkGovernanceError, "cannot participate in tuning"):
                create_benchmark_split_freeze(
                    split_name="holdout",
                    role="sealed_holdout",
                    queries_path=queries,
                    qrels_path=qrels,
                    participated_in_tuning=True,
                    evaluator_independent=True,
                )
            freeze = create_benchmark_split_freeze(
                split_name="holdout",
                role="sealed_holdout",
                queries_path=queries,
                qrels_path=qrels,
                participated_in_tuning=False,
                evaluator_independent=True,
            )
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            self.assertTrue(
                verify_benchmark_split_freeze(
                    freeze_path=freeze_path,
                    queries_path=queries,
                    qrels_path=qrels,
                )["ok"]
            )
            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "changed"}]}), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkGovernanceError, "query hash"):
                verify_benchmark_split_freeze(
                    freeze_path=freeze_path,
                    queries_path=queries,
                    qrels_path=qrels,
                )

            queries.write_text(json.dumps({"queries": [{"id": "q1", "question": "Q?"}]}), encoding="utf-8")
            forged = dict(freeze)
            forged["role"] = "unrecognized"
            binding = {
                key: forged.get(key)
                for key in (
                    "split_name", "role", "freeze_time", "query_sha256", "qrel_sha256",
                    "participated_in_tuning", "evaluator_independent", "evaluator_id",
                )
            }
            forged["binding_sha256"] = hashlib.sha256(
                json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            freeze_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkGovernanceError, "role"):
                verify_benchmark_split_freeze(
                    freeze_path=freeze_path,
                    queries_path=queries,
                    qrels_path=qrels,
                )

    def test_unknown_provider_does_not_collapse_other_readiness(self) -> None:
        readiness = create_compatibility_readiness(
            provider={"status": "not_available", "schema": "provider-v1"},
            parse={"status": "PASS", "schema": "parse-v1"},
            retrieval={"status": "PASS", "schema": "retrieval-v1"},
            activation={"status": "ready", "schema": "activation-v1"},
            run_identity="run-1",
        )
        self.assertEqual(readiness["dimensions"]["provider_observability"]["status"], "unknown")
        self.assertEqual(readiness["overall_status"], "ready")
        self.assertTrue(readiness["ok"])

        blocked = create_compatibility_readiness(
            provider={"status": "FAIL", "schema": "provider-v1"},
            parse={"status": "PASS", "schema": "parse-v1"},
            retrieval={"status": "PASS", "schema": "retrieval-v1"},
            activation={"status": "ready", "schema": "activation-v1"},
            run_identity="run-1",
        )
        self.assertEqual(blocked["dimensions"]["provider_observability"]["status"], "blocked")
        self.assertEqual(blocked["overall_status"], "blocked")
        self.assertFalse(blocked["ok"])

    def test_readiness_hash_excludes_source_path_and_accepts_content_hash(self) -> None:
        first = create_compatibility_readiness(
            provider={"status": "pass", "schema": "provider-v1", "_source_path": "/one.json"},
            parse={"status": "PASS", "schema": "parse-v1", "_source_path": "/one.json"},
            retrieval={"status": "PASS", "schema": "retrieval-v1", "_source_path": "/one.json"},
            activation={"status": "ready", "schema": "activation-v1", "_source_path": "/one.json"},
            run_identity="run-1",
        )
        second = create_compatibility_readiness(
            provider={"status": "pass", "schema": "provider-v1", "_source_path": "/two.json"},
            parse={"status": "PASS", "schema": "parse-v1", "_source_path": "/two.json"},
            retrieval={"status": "PASS", "schema": "retrieval-v1", "_source_path": "/two.json"},
            activation={"status": "ready", "schema": "activation-v1", "_source_path": "/two.json"},
            run_identity="run-1",
        )
        self.assertEqual(
            first["dimensions"]["parse_readiness"]["source_sha256"],
            second["dimensions"]["parse_readiness"]["source_sha256"],
        )
        content_hash = "a" * 64
        explicit = create_compatibility_readiness(
            provider=None,
            parse={"status": "PASS", "schema": "parse-v1"},
            retrieval=None,
            activation=None,
            run_identity="run-1",
            evidence_hashes={"parse": content_hash},
        )
        self.assertEqual(explicit["dimensions"]["parse_readiness"]["source_sha256"], content_hash)

        unknown = create_compatibility_readiness(
            provider=None,
            parse={"status": "unexpected-status", "schema": "parse-v1"},
            retrieval=None,
            activation=None,
            run_identity="run-1",
        )
        self.assertEqual(unknown["dimensions"]["parse_readiness"]["status"], "unknown")
        self.assertEqual(unknown["overall_status"], "review")
        with self.assertRaisesRegex(HealthReportError, "run identity"):
            create_compatibility_readiness(
                provider=None,
                parse={"status": "PASS", "schema": "parse-v1", "run_identity": "run-1"},
                retrieval={"status": "PASS", "schema": "retrieval-v1", "run_identity": "run-2"},
                activation=None,
                run_identity=None,
            )
        with self.assertRaisesRegex(HealthReportError, "evidence hash must be SHA-256"):
            create_compatibility_readiness(
                provider=None,
                parse={"status": "PASS", "schema": "parse-v1"},
                retrieval=None,
                activation=None,
                run_identity="run-1",
                evidence_hashes={"parse": "not-a-hash"},
            )

    def test_activation_blocks_candidate_only_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "kb_manifest.json"
            hints = root / "retrieval_hints.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "dataset": {"id": "dataset-1", "name": "staging-kb"},
                        "documents": [{"document_id": "doc-1", "status": "done", "chunk_count": 1}],
                    }
                ),
                encoding="utf-8",
            )
            hints.write_text(
                json.dumps({"schema": "ragflow_retrieval_hints_v1", "keyword_candidates": []}),
                encoding="utf-8",
            )
            report = create_kb_activation_plan(
                kb_manifest_path=manifest,
                retrieval_hints_path=hints,
            )
        self.assertEqual(report["checks"]["hint_review"]["status"], "blocked")
        self.assertIn("hint_review", report["recommendation"]["blocked_checks"])


if __name__ == "__main__":
    unittest.main()
