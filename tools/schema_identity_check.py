#!/usr/bin/env python3
"""Check canonical manifest and report schema identities used by the public suite."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ragflow_schema_identity_check_v1"

TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "htmlcov",
    "release-artifacts",
}


@dataclass(frozen=True)
class SchemaIdentity:
    key: str
    group: str
    identity: str
    source_patterns: tuple[str, ...]
    coverage_patterns: tuple[str, ...]
    identity_field: str = "schema"
    description: str = ""
    source_roots: tuple[Path, ...] = ()
    coverage_roots: tuple[Path, ...] = ()


DEFAULT_SOURCE_ROOTS = (
    Path("packages/ragflow-skill-runtime/src"),
    Path("skills/ragflow-doc-to-md/scripts"),
    Path("skills/ragflow-kb-build/scripts"),
    Path("skills/ragflow-query/scripts"),
)
DEFAULT_COVERAGE_ROOTS = (
    Path("packages/ragflow-skill-runtime/tests"),
    Path("tools/consumer_acceptance.py"),
    Path("tools/platform_smoke_matrix.py"),
)


EXPECTED_IDENTITIES = (
    SchemaIdentity(
        key="doc_manifest",
        group="manifest",
        identity="doc_manifest version 0.1",
        identity_field="version",
        source_patterns=("make_doc_manifest_payload",),
        coverage_patterns=("test_load_doc_manifest", "doc_manifest produced"),
        description="Versioned document handoff manifest written as doc_manifest.json.",
    ),
    SchemaIdentity(
        key="kb_manifest",
        group="manifest",
        identity="kb_manifest version 0.1",
        identity_field="version",
        source_patterns=("make_kb_manifest_payload",),
        coverage_patterns=("test_load_kb_manifest", "kb_manifest"),
        description="Versioned KB handoff manifest written as kb_manifest.json.",
    ),
    SchemaIdentity(
        key="doc_quality_report",
        group="quality",
        identity="doc_quality_report_v1",
        source_patterns=("doc_quality_report_v1",),
        coverage_patterns=("doc_quality_report_v1",),
    ),
    SchemaIdentity(
        key="asset_semantics",
        group="manifest",
        identity="ragflow_asset_semantics_v1",
        source_patterns=("ragflow_asset_semantics_v1", "ASSET_SEMANTICS_SCHEMA"),
        coverage_patterns=("ragflow_asset_semantics_v1", "ASSET_SEMANTICS_SCHEMA"),
        description="Embedded image-asset semantics report under artifact_index.json.",
    ),
    SchemaIdentity(
        key="doc_ingest_readiness",
        group="manifest",
        identity="ragflow_doc_ingest_readiness_v1",
        source_patterns=("ragflow_doc_ingest_readiness_v1", "DOC_INGEST_READINESS_SCHEMA"),
        coverage_patterns=("ragflow_doc_ingest_readiness_v1", "DOC_INGEST_READINESS_SCHEMA"),
        description="JSON-first formal document ingest readiness report.",
    ),
    SchemaIdentity(
        key="formal_handoff_manifest",
        group="manifest",
        identity="ragflow_formal_handoff_manifest_v1",
        source_patterns=("ragflow_formal_handoff_manifest_v1", "FORMAL_HANDOFF_MANIFEST_SCHEMA"),
        coverage_patterns=("ragflow_formal_handoff_manifest_v1", "FORMAL_HANDOFF_MANIFEST_SCHEMA"),
        description="Package-level formal handoff audit manifest with sidecar hashes.",
    ),
    SchemaIdentity(
        key="handoff_comparison",
        group="manifest",
        identity="ragflow_handoff_comparison_v1",
        source_patterns=("ragflow_handoff_comparison_v1", "HANDOFF_COMPARISON_SCHEMA"),
        coverage_patterns=("ragflow_handoff_comparison_v1", "compare-retained-package"),
        description="Static retained-package comparison report for legacy replacement evidence.",
    ),
    SchemaIdentity(
        key="benchmark_report",
        group="benchmark",
        identity="ragflow_benchmark_report_v1",
        source_patterns=("ragflow_benchmark_report_v1",),
        coverage_patterns=("ragflow_benchmark_report_v1",),
    ),
    SchemaIdentity(
        key="benchmark_import_report",
        group="benchmark",
        identity="ragflow_benchmark_import_report_v1",
        source_patterns=("ragflow_benchmark_import_report_v1",),
        coverage_patterns=("ragflow_benchmark_import_report_v1", "BENCHMARK_IMPORT_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_sample_report",
        group="benchmark",
        identity="ragflow_benchmark_sample_report_v1",
        source_patterns=("ragflow_benchmark_sample_report_v1",),
        coverage_patterns=("ragflow_benchmark_sample_report_v1", "BENCHMARK_SAMPLE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_preflight_report",
        group="benchmark",
        identity="ragflow_benchmark_preflight_report_v1",
        source_patterns=("ragflow_benchmark_preflight_report_v1",),
        coverage_patterns=("ragflow_benchmark_preflight_report_v1", "BENCHMARK_PREFLIGHT_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_summary_report",
        group="benchmark",
        identity="ragflow_benchmark_summary_report_v1",
        source_patterns=("ragflow_benchmark_summary_report_v1",),
        coverage_patterns=("ragflow_benchmark_summary_report_v1", "BENCHMARK_SUMMARY_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_gate_report",
        group="benchmark",
        identity="ragflow_benchmark_gate_report_v1",
        source_patterns=("ragflow_benchmark_gate_report_v1",),
        coverage_patterns=("ragflow_benchmark_gate_report_v1", "BENCHMARK_GATE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_trend_report",
        group="benchmark",
        identity="ragflow_benchmark_trend_report_v1",
        source_patterns=("ragflow_benchmark_trend_report_v1",),
        coverage_patterns=("ragflow_benchmark_trend_report_v1", "BENCHMARK_TREND_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_delta_report",
        group="benchmark",
        identity="ragflow_benchmark_delta_report_v1",
        source_patterns=("ragflow_benchmark_delta_report_v1",),
        coverage_patterns=("ragflow_benchmark_delta_report_v1", "BENCHMARK_DELTA_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="benchmark_retrieval_suggestion_report",
        group="benchmark",
        identity="ragflow_benchmark_retrieval_suggestion_report_v1",
        source_patterns=("ragflow_benchmark_retrieval_suggestion_report_v1",),
        coverage_patterns=("ragflow_benchmark_retrieval_suggestion_report_v1", "BENCHMARK_RETRIEVAL_SUGGESTION_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="chunk_snapshot",
        group="benchmark",
        identity="ragflow_chunk_snapshot_v1",
        source_patterns=("ragflow_chunk_snapshot_v1",),
        coverage_patterns=("ragflow_chunk_snapshot_v1", "CHUNK_SNAPSHOT_SCHEMA"),
    ),
    SchemaIdentity(
        key="chunk_snapshot_report",
        group="benchmark",
        identity="ragflow_chunk_snapshot_report_v1",
        source_patterns=("ragflow_chunk_snapshot_report_v1",),
        coverage_patterns=("ragflow_chunk_snapshot_report_v1", "CHUNK_SNAPSHOT_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="grounded_qa_generate_report",
        group="benchmark",
        identity="ragflow_grounded_qa_generate_report_v1",
        source_patterns=("ragflow_grounded_qa_generate_report_v1",),
        coverage_patterns=("ragflow_grounded_qa_generate_report_v1", "GROUNDED_QA_GENERATE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="grounded_qa_validate_report",
        group="benchmark",
        identity="ragflow_grounded_qa_validate_report_v1",
        source_patterns=("ragflow_grounded_qa_validate_report_v1",),
        coverage_patterns=("ragflow_grounded_qa_validate_report_v1", "GROUNDED_QA_VALIDATE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="grounded_qa_evidence_map_report",
        group="benchmark",
        identity="ragflow_grounded_qa_evidence_map_report_v1",
        source_patterns=("ragflow_grounded_qa_evidence_map_report_v1",),
        coverage_patterns=("ragflow_grounded_qa_evidence_map_report_v1", "GROUNDED_QA_EVIDENCE_MAP_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="grounded_qa_suggestion_request",
        group="benchmark",
        identity="ragflow_grounded_qa_suggestion_request_v1",
        source_patterns=("ragflow_grounded_qa_suggestion_request_v1",),
        coverage_patterns=("ragflow_grounded_qa_suggestion_request_v1", "GROUNDED_QA_SUGGESTION_REQUEST_SCHEMA"),
    ),
    SchemaIdentity(
        key="grounded_qa_suggestion_review_report",
        group="benchmark",
        identity="ragflow_grounded_qa_suggestion_review_report_v1",
        source_patterns=("ragflow_grounded_qa_suggestion_review_report_v1",),
        coverage_patterns=("ragflow_grounded_qa_suggestion_review_report_v1", "GROUNDED_QA_SUGGESTION_REVIEW_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="suppression_report",
        group="benchmark",
        identity="ragflow_suppression_report_v1",
        source_patterns=("ragflow_suppression_report_v1",),
        coverage_patterns=("ragflow_suppression_report_v1",),
    ),
    SchemaIdentity(
        key="retrieval_status",
        group="query",
        identity="ragflow_retrieval_status_v1",
        source_patterns=("ragflow_retrieval_status_v1",),
        coverage_patterns=("ragflow_retrieval_status_v1", "RETRIEVAL_STATUS_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_endpoint_report",
        group="query",
        identity="ragflow_query_endpoint_report_v1",
        source_patterns=("ragflow_query_endpoint_report_v1",),
        coverage_patterns=("ragflow_query_endpoint_report_v1", "QUERY_ENDPOINT_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_output_cache_report",
        group="query",
        identity="ragflow_query_output_cache_report_v1",
        source_patterns=("ragflow_query_output_cache_report_v1",),
        coverage_patterns=("ragflow_query_output_cache_report_v1", "QUERY_OUTPUT_CACHE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_output_cache_store_report",
        group="query",
        identity="ragflow_query_output_cache_store_report_v1",
        source_patterns=("ragflow_query_output_cache_store_report_v1", "QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA"),
        coverage_patterns=("ragflow_query_output_cache_store_report_v1", "QUERY_OUTPUT_CACHE_STORE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_metrics",
        group="runtime",
        identity="ragflow_runtime_metrics_v1",
        source_patterns=("ragflow_runtime_metrics_v1", "RUNTIME_METRICS_SCHEMA"),
        coverage_patterns=("ragflow_runtime_metrics_v1", "RUNTIME_METRICS_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_cache",
        group="runtime",
        identity="ragflow_runtime_cache_report_v1",
        source_patterns=("ragflow_runtime_cache_report_v1", "RUNTIME_CACHE_REPORT_SCHEMA"),
        coverage_patterns=("ragflow_runtime_cache_report_v1", "RUNTIME_CACHE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_rate_limit",
        group="runtime",
        identity="ragflow_runtime_rate_limit_report_v1",
        source_patterns=("ragflow_runtime_rate_limit_report_v1", "RUNTIME_RATE_LIMIT_REPORT_SCHEMA"),
        coverage_patterns=("ragflow_runtime_rate_limit_report_v1", "RUNTIME_RATE_LIMIT_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_circuit_breaker",
        group="runtime",
        identity="ragflow_runtime_circuit_breaker_report_v1",
        source_patterns=("ragflow_runtime_circuit_breaker_report_v1", "RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA"),
        coverage_patterns=("ragflow_runtime_circuit_breaker_report_v1", "RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_retry_trace",
        group="runtime",
        identity="ragflow_runtime_retry_trace_v1",
        source_patterns=("ragflow_runtime_retry_trace_v1", "RUNTIME_RETRY_TRACE_SCHEMA"),
        coverage_patterns=("ragflow_runtime_retry_trace_v1", "RUNTIME_RETRY_TRACE_SCHEMA"),
    ),
    SchemaIdentity(
        key="runtime_partial_failure",
        group="runtime",
        identity="ragflow_runtime_partial_failure_report_v1",
        source_patterns=("ragflow_runtime_partial_failure_report_v1", "RUNTIME_PARTIAL_FAILURE_REPORT_SCHEMA"),
        coverage_patterns=("ragflow_runtime_partial_failure_report_v1", "RUNTIME_PARTIAL_FAILURE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_fallback_test_report",
        group="query",
        identity="ragflow_query_fallback_test_report_v1",
        source_patterns=("ragflow_query_fallback_test_report_v1",),
        coverage_patterns=("ragflow_query_fallback_test_report_v1", "QUERY_FALLBACK_TEST_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_rewrite_plan",
        group="query",
        identity="ragflow_query_rewrite_plan_v1",
        source_patterns=("ragflow_query_rewrite_plan_v1",),
        coverage_patterns=("ragflow_query_rewrite_plan_v1", "QUERY_REWRITE_PLAN_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_intent",
        group="query",
        identity="ragflow_query_intent_v1",
        source_patterns=("ragflow_query_intent_v1",),
        coverage_patterns=("ragflow_query_intent_v1", "QUERY_INTENT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_route_decision",
        group="query",
        identity="ragflow_query_route_decision_v1",
        source_patterns=("ragflow_query_route_decision_v1",),
        coverage_patterns=("ragflow_query_route_decision_v1", "QUERY_ROUTE_DECISION_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_session",
        group="query",
        identity="ragflow_query_session_v1",
        source_patterns=("ragflow_query_session_v1",),
        coverage_patterns=("ragflow_query_session_v1", "QUERY_SESSION_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_session_inspection",
        group="query",
        identity="ragflow_query_session_inspection_v1",
        source_patterns=("ragflow_query_session_inspection_v1",),
        coverage_patterns=("ragflow_query_session_inspection_v1", "QUERY_SESSION_INSPECTION_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_session_enrichment",
        group="query",
        identity="ragflow_query_session_enrichment_v1",
        source_patterns=("ragflow_query_session_enrichment_v1",),
        coverage_patterns=("ragflow_query_session_enrichment_v1", "QUERY_SESSION_ENRICHMENT_SCHEMA"),
    ),
    SchemaIdentity(
        key="agentic_plan",
        group="query",
        identity="ragflow_agentic_plan_v1",
        source_patterns=("ragflow_agentic_plan_v1",),
        coverage_patterns=("ragflow_agentic_plan_v1", "AGENTIC_PLAN_SCHEMA"),
    ),
    SchemaIdentity(
        key="host_synthesis_contract",
        group="query",
        identity="ragflow_host_synthesis_contract_v1",
        source_patterns=("ragflow_host_synthesis_contract_v1",),
        coverage_patterns=("ragflow_host_synthesis_contract_v1", "HOST_SYNTHESIS_CONTRACT_SCHEMA"),
    ),
    SchemaIdentity(
        key="agentic_answer_request",
        group="query",
        identity="ragflow_agentic_answer_request_v1",
        source_patterns=("ragflow_agentic_answer_request_v1",),
        coverage_patterns=("ragflow_agentic_answer_request_v1", "AGENTIC_ANSWER_REQUEST_SCHEMA"),
    ),
    SchemaIdentity(
        key="agentic_answer_review_report",
        group="query",
        identity="ragflow_agentic_answer_review_report_v1",
        source_patterns=("ragflow_agentic_answer_review_report_v1",),
        coverage_patterns=("ragflow_agentic_answer_review_report_v1", "AGENTIC_ANSWER_REVIEW_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="answer_evaluator_request",
        group="query",
        identity="ragflow_answer_evaluator_request_v1",
        source_patterns=("ragflow_answer_evaluator_request_v1",),
        coverage_patterns=("ragflow_answer_evaluator_request_v1", "ANSWER_EVALUATOR_REQUEST_SCHEMA"),
    ),
    SchemaIdentity(
        key="answer_evaluator_review_report",
        group="query",
        identity="ragflow_answer_evaluator_review_report_v1",
        source_patterns=("ragflow_answer_evaluator_review_report_v1",),
        coverage_patterns=("ragflow_answer_evaluator_review_report_v1", "ANSWER_EVALUATOR_REVIEW_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="citation_audit",
        group="query",
        identity="ragflow_citation_audit_v1",
        source_patterns=("ragflow_citation_audit_v1",),
        coverage_patterns=("ragflow_citation_audit_v1", "CITATION_AUDIT_SCHEMA"),
    ),
    SchemaIdentity(
        key="answer_evaluation_report",
        group="query",
        identity="ragflow_answer_evaluation_report_v1",
        source_patterns=("ragflow_answer_evaluation_report_v1",),
        coverage_patterns=("ragflow_answer_evaluation_report_v1", "ANSWER_EVALUATION_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_pollution_report",
        group="query",
        identity="ragflow_query_pollution_report_v1",
        source_patterns=("ragflow_query_pollution_report_v1",),
        coverage_patterns=("ragflow_query_pollution_report_v1", "QUERY_POLLUTION_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_rerank_ab_report",
        group="query",
        identity="ragflow_query_rerank_ab_report_v1",
        source_patterns=("ragflow_query_rerank_ab_report_v1",),
        coverage_patterns=("ragflow_query_rerank_ab_report_v1", "QUERY_RERANK_AB_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="cross_language_ab_report",
        group="query",
        identity="ragflow_cross_language_ab_report_v1",
        source_patterns=("ragflow_cross_language_ab_report_v1",),
        coverage_patterns=("ragflow_cross_language_ab_report_v1", "QUERY_CROSS_LANGUAGE_AB_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="fusion_report",
        group="query",
        identity="ragflow_fusion_report_v1",
        source_patterns=("ragflow_fusion_report_v1",),
        coverage_patterns=("ragflow_fusion_report_v1", "FUSION_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="fusion_test_report",
        group="query",
        identity="ragflow_fusion_test_report_v1",
        source_patterns=("ragflow_fusion_test_report_v1",),
        coverage_patterns=("ragflow_fusion_test_report_v1", "FUSION_TEST_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="assistant_profile_recommendation",
        group="query",
        identity="ragflow_assistant_profile_recommendation_v1",
        source_patterns=("ragflow_assistant_profile_recommendation_v1",),
        coverage_patterns=(
            "ragflow_assistant_profile_recommendation_v1",
            "ASSISTANT_PROFILE_RECOMMENDATION_SCHEMA",
        ),
    ),
    SchemaIdentity(
        key="assistant_test_plan_review",
        group="query",
        identity="ragflow_assistant_test_plan_review_v1",
        source_patterns=("ragflow_assistant_test_plan_review_v1",),
        coverage_patterns=(
            "ragflow_assistant_test_plan_review_v1",
            "ASSISTANT_TEST_PLAN_REVIEW_SCHEMA",
        ),
    ),
    SchemaIdentity(
        key="query_trace",
        group="trace",
        identity="ragflow_query_trace_v1",
        source_patterns=("ragflow_query_trace_v1",),
        coverage_patterns=("ragflow_query_trace_v1", "TRACE_SCHEMA"),
    ),
    SchemaIdentity(
        key="agentic_trace",
        group="trace",
        identity="ragflow_agentic_trace_v1",
        source_patterns=("ragflow_agentic_trace_v1",),
        coverage_patterns=("ragflow_agentic_trace_v1", "AGENTIC_TRACE_SCHEMA"),
    ),
    SchemaIdentity(
        key="kb_diagnostic_report",
        group="diagnostic",
        identity="ragflow_kb_diagnostic_report_v1",
        source_patterns=("ragflow_kb_diagnostic_report_v1",),
        coverage_patterns=("ragflow_kb_diagnostic_report_v1", "DIAGNOSTIC_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="query_diagnostic_report",
        group="diagnostic",
        identity="ragflow_query_diagnostic_report_v1",
        source_patterns=("ragflow_query_diagnostic_report_v1",),
        coverage_patterns=("ragflow_query_diagnostic_report_v1", "QUERY_DIAGNOSTIC_SCHEMA"),
    ),
    SchemaIdentity(
        key="report_redaction_report",
        group="diagnostic",
        identity="ragflow_report_redaction_report_v1",
        source_patterns=("ragflow_report_redaction_report_v1",),
        coverage_patterns=("ragflow_report_redaction_report_v1", "REPORT_REDACTION_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_test_report",
        group="route",
        identity="ragflow_route_test_report_v1",
        source_patterns=("ragflow_route_test_report_v1",),
        coverage_patterns=("ragflow_route_test_report_v1",),
    ),
    SchemaIdentity(
        key="route_report",
        group="route",
        identity="ragflow_route_report_v1",
        source_patterns=("ragflow_route_report_v1",),
        coverage_patterns=("ragflow_route_report_v1", "ROUTE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_diagnose_report",
        group="route",
        identity="ragflow_route_diagnose_report_v1",
        source_patterns=("ragflow_route_diagnose_report_v1",),
        coverage_patterns=("ragflow_route_diagnose_report_v1", "ROUTE_DIAGNOSE_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_activation_check",
        group="route",
        identity="ragflow_route_activation_check_v1",
        source_patterns=("ragflow_route_activation_check_v1",),
        coverage_patterns=("ragflow_route_activation_check_v1", "ROUTE_ACTIVATION_CHECK_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_centroid_index",
        group="route",
        identity="ragflow_route_centroid_index_v1",
        source_patterns=("ragflow_route_centroid_index_v1",),
        coverage_patterns=("ragflow_route_centroid_index_v1", "CENTROID_INDEX_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_centroid_build_plan",
        group="route",
        identity="ragflow_route_centroid_build_plan_v1",
        source_patterns=("ragflow_route_centroid_build_plan_v1",),
        coverage_patterns=("ragflow_route_centroid_build_plan_v1", "CENTROID_BUILD_PLAN_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_centroid_build_report",
        group="route",
        identity="ragflow_route_centroid_build_report_v1",
        source_patterns=("ragflow_route_centroid_build_report_v1",),
        coverage_patterns=("ragflow_route_centroid_build_report_v1", "CENTROID_BUILD_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="route_centroid_build_checkpoint",
        group="route",
        identity="ragflow_route_centroid_build_checkpoint_v1",
        source_patterns=("ragflow_route_centroid_build_checkpoint_v1",),
        coverage_patterns=("ragflow_route_centroid_build_checkpoint_v1", "CENTROID_BUILD_CHECKPOINT_SCHEMA"),
    ),
    SchemaIdentity(
        key="kb_topology_advice",
        group="topology",
        identity="kb_topology_advice_v1",
        source_patterns=("kb_topology_advice_v1",),
        coverage_patterns=("kb_topology_advice_v1", "KB_TOPOLOGY_ADVICE_SCHEMA"),
    ),
    SchemaIdentity(
        key="kb_split_plan",
        group="topology",
        identity="kb_split_plan_v1",
        source_patterns=("kb_split_plan_v1",),
        coverage_patterns=("kb_split_plan_v1", "KB_SPLIT_PLAN_SCHEMA"),
    ),
    SchemaIdentity(
        key="kb_activation_plan",
        group="topology",
        identity="kb_activation_plan_v1",
        source_patterns=("kb_activation_plan_v1",),
        coverage_patterns=("kb_activation_plan_v1", "KB_ACTIVATION_PLAN_SCHEMA"),
    ),
    SchemaIdentity(
        key="ragflow_parse_report",
        group="kb_health",
        identity="ragflow_parse_report_v1",
        source_patterns=("ragflow_parse_report_v1",),
        coverage_patterns=("ragflow_parse_report_v1", "PARSE_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="ragflow_kb_health_report",
        group="kb_health",
        identity="ragflow_kb_health_report_v1",
        source_patterns=("ragflow_kb_health_report_v1",),
        coverage_patterns=("ragflow_kb_health_report_v1", "HEALTH_REPORT_SCHEMA"),
    ),
    SchemaIdentity(
        key="version_date_drift_check",
        group="release",
        identity="ragflow_version_date_drift_check_v1",
        source_patterns=("ragflow_version_date_drift_check_v1",),
        coverage_patterns=("ragflow_version_date_drift_check_v1", "run_version_date_drift_check"),
        description="Release governance report for package, manifest, docs, and skill metadata version/date drift.",
        source_roots=(Path("tools/version_date_drift_check.py"),),
    ),
    SchemaIdentity(
        key="generated_report_safety_check",
        group="release",
        identity="ragflow_generated_report_safety_check_v1",
        source_patterns=("ragflow_generated_report_safety_check_v1",),
        coverage_patterns=("ragflow_generated_report_safety_check_v1", "run_generated_report_safety_check"),
        description="Release governance report for generated-report and example redaction safety.",
        source_roots=(Path("tools/release_hygiene_check.py"),),
    ),
    SchemaIdentity(
        key="manifest_schema_check",
        group="release",
        identity="ragflow_manifest_schema_check_v1",
        source_patterns=("ragflow_manifest_schema_check_v1", "SCHEMA"),
        coverage_patterns=("ragflow_manifest_schema_check_v1", "run_manifest_schema_check"),
        description="Release governance report for primary manifest JSON Schema templates and examples.",
        source_roots=(Path("tools/manifest_schema_check.py"),),
    ),
    SchemaIdentity(
        key="generated_markdown_audit",
        group="release",
        identity="ragflow_generated_markdown_audit_v1",
        source_patterns=("ragflow_generated_markdown_audit_v1", "SCHEMA"),
        coverage_patterns=("ragflow_generated_markdown_audit_v1", "run_generated_markdown_audit"),
        description="Release governance report for sanitized generated-Markdown report coverage.",
        source_roots=(Path("tools/generated_markdown_audit.py"),),
    ),
    SchemaIdentity(
        key="runtime_resilience_inventory",
        group="runtime",
        identity="ragflow_runtime_resilience_inventory_v1",
        source_patterns=("ragflow_runtime_resilience_inventory_v1", "SCHEMA"),
        coverage_patterns=("ragflow_runtime_resilience_inventory_v1", "run_runtime_resilience_inventory"),
        description="Release governance inventory for runtime-resilience helper coverage and candidates.",
        source_roots=(Path("tools/runtime_resilience_inventory.py"),),
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _iter_text_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in TEXT_SUFFIXES:
                yield path
            continue
        if not path.exists():
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or candidate.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if any(part in IGNORED_DIRS for part in candidate.parts):
                continue
            yield candidate


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _find_pattern_evidence(
    *,
    root: Path,
    search_paths: Iterable[Path],
    patterns: tuple[str, ...],
) -> dict[str, Any]:
    evidence_by_pattern: dict[str, list[dict[str, Any]]] = {pattern: [] for pattern in patterns}
    for path in _iter_text_files(search_paths):
        text = _read_text(path)
        if not text:
            continue
        lines = text.splitlines()
        for pattern in patterns:
            if pattern not in text:
                continue
            matches = [
                {"path": _relative(path, root), "line": line_no}
                for line_no, line in enumerate(lines, start=1)
                if pattern in line
            ]
            evidence_by_pattern[pattern].extend(matches[:5])

    matched = sorted(pattern for pattern, occurrences in evidence_by_pattern.items() if occurrences)
    return {
        "candidate_patterns": list(patterns),
        "matched_patterns": matched,
        "unmatched_patterns": [pattern for pattern in patterns if pattern not in matched],
        "occurrences": {
            pattern: occurrences
            for pattern, occurrences in evidence_by_pattern.items()
            if occurrences
        },
        "ok": bool(matched),
    }


def _resolve_search_paths(root: Path, paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple((root / path).resolve() if not path.is_absolute() else path.resolve() for path in paths)


def _check_identity(
    identity: SchemaIdentity,
    *,
    root: Path,
    source_paths: Iterable[Path],
    coverage_paths: Iterable[Path],
) -> dict[str, Any]:
    source = _find_pattern_evidence(root=root, search_paths=source_paths, patterns=identity.source_patterns)
    coverage = _find_pattern_evidence(root=root, search_paths=coverage_paths, patterns=identity.coverage_patterns)
    ok = bool(source["ok"] and coverage["ok"])
    return {
        "key": identity.key,
        "group": identity.group,
        "identity": identity.identity,
        "identity_field": identity.identity_field,
        "description": identity.description,
        "ok": ok,
        "source_roots": [_relative(path, root) for path in source_paths],
        "coverage_roots": [_relative(path, root) for path in coverage_paths],
        "source": source,
        "coverage": coverage,
        "error": "" if ok else "missing source or coverage evidence for schema identity",
    }


def run_schema_identity_check(
    *,
    root: Path = ROOT,
    identities: tuple[SchemaIdentity, ...] = EXPECTED_IDENTITIES,
    source_roots: tuple[Path, ...] = DEFAULT_SOURCE_ROOTS,
    coverage_roots: tuple[Path, ...] = DEFAULT_COVERAGE_ROOTS,
) -> dict[str, Any]:
    """Run the static schema identity gate and return a JSON-serializable report."""

    root = root.resolve()
    source_paths = _resolve_search_paths(root, source_roots)
    coverage_paths = _resolve_search_paths(root, coverage_roots)
    checks = [
        _check_identity(
            identity,
            root=root,
            source_paths=_resolve_search_paths(root, identity.source_roots) if identity.source_roots else source_paths,
            coverage_paths=_resolve_search_paths(root, identity.coverage_roots) if identity.coverage_roots else coverage_paths,
        )
        for identity in identities
    ]
    failed = [check["key"] for check in checks if not check["ok"]]
    groups = sorted({identity.group for identity in identities})
    return {
        "ok": not failed,
        "schema": SCHEMA,
        "created_at": _utc_now(),
        "root": str(root),
        "source_roots": [_relative(path, root) for path in source_paths],
        "coverage_roots": [_relative(path, root) for path in coverage_paths],
        "groups": groups,
        "checks": checks,
        "summary": {
            "identity_count": len(checks),
            "group_count": len(groups),
            "failed_count": len(failed),
            "failed_identities": failed,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run static schema identity checks for public RAGFlow skills")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--report-json", help="Optional path to write the schema identity report")
    args = parser.parse_args(argv)

    report = run_schema_identity_check(root=Path(args.root))
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
