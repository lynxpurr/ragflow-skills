# RAGFlow KB Parameter Materialization Plan

Status: active KB parameter materialization plan; P0 inventory implemented
Date: 2026-07-09

## Objective / Scope / Boundaries

The current document-to-KB path can produce rich sidecar evidence from
`ragflow-doc-to-md`, including `profile_suggestions.json`,
`ragflow_ingest_plan.yaml`, `retrieval_hints.json`, quality reports, table
signals, image signals, and metadata. Recent live inspection showed that a KB
built from the MinerU hybrid Markdown handoff can parse successfully while
several RAGFlow UI parser options remain at their default values.

This plan defines how to safely turn sidecar recommendations into actual
RAGFlow KB parser or dataset settings when the API contract is known and
verified. It is deliberately separate from
`docs/35-standard-benchmark-dataset-integration-plan.md`: `docs/35` defines the
benchmark portfolio and evaluation evidence, while this plan defines parameter
mapping and materialization behavior.

In scope:

- mapping `profile_suggestions.json`, `ragflow_ingest_plan.yaml`, and
  `retrieval_hints.json` fields to reviewed KB build settings;
- distinguishing fields already materialized from local-only, advisory,
  unsupported, gated, and native-parser-only fields;
- adding fake-client coverage before any writable live behavior;
- using disposable KBs and read-back evidence to verify actual RAGFlow behavior;
- updating public guidance only after sanitized validation evidence exists.

Out of scope by default:

- no live RAGFlow mutation without explicit approval;
- no script-owned LLM/RAGAS calls;
- no automatic promotion from one exploratory benchmark;
- no raw chunks, credentials, endpoints, dataset IDs, document IDs, KB names, or
  private run roots in public docs;
- no assumption that Markdown handoff parser settings and DeepDoc/native PDF
  parser settings share the same API fields.

## Problem Description

The first Open RAG Benchmark seed proved that the MinerU hybrid high-quality
path can produce a clean formal handoff and that a delimiter-aware Markdown KB
can parse successfully. However, manual UI inspection of a retained KB showed
that several RAGFlow UI controls were not configured by the current skills:

- PageIndex;
- image/table context windows;
- automatic metadata;
- overlapped percent;
- automatic keyword extraction unless explicitly enabled by a reviewed profile;
- table-to-HTML or native table parser options.

This is not simply a missing `profile_suggestions.json` file. The sidecar exists
and contains useful recommendations. The current gap is that only a small,
reviewed subset of those recommendations is materialized into the RAGFlow create
or update payload.

Current supported parser materialization is intentionally narrow:

- `chunk_token_num`;
- `delimiter`;
- `auto_keywords`;
- `auto_questions`;
- top-level `language`.

Other evidence is currently surfaced through preview, readiness, handoff
consumption status, or recommendations. This avoids silently writing fields
whose API behavior has not been confirmed.

## Current Field Classification

| Field or signal | Current status | Notes |
| --- | --- | --- |
| `parser_config.chunk_token_num` | Materialized when present in reviewed profile | Used for chunk size. |
| `parser_config.delimiter` | Materialized when present in reviewed profile | Used by delimiter-aware profiles such as the Open RAG Benchmark seed path. |
| `parser_config.auto_keywords` | Materialized only from reviewed profile | Stage 5 showed no measured gain on the exploratory seed. |
| `parser_config.auto_questions` | Materialized only from reviewed profile | Stage 5 showed an exploratory similarity lift on the seed. |
| Top-level `language` | Materialized | Derived from reviewed profile or ingest-plan evidence. |
| `chunk_overlap` / overlap percent | Local-only today | Retained in manifests and estimates, but not yet confirmed as writable parser payload. |
| `postprocess_profile` | Local pipeline instruction | Applies to Markdown generation, not automatically to RAGFlow parser config. |
| `avoid_children_delimiter` | Advisory | Needs mapping and API confirmation before materialization. |
| `retrieval_hints.keyword_candidates` | Advisory | Not silently converted to `auto_keywords`. |
| `retrieval_hints.question_candidates` | Advisory | Not silently converted to `auto_questions`. |
| `retrieval_hints.image_artifacts` | Gated/advisory | Standard Markdown build does not upload image assets as visual documents. |
| `retrieval_hints.table_artifacts` | Advisory | Used for review and table sizing; not yet mapped to native table parser settings. |
| `metadata.json` | Local audit/advisory | Not automatically written as RAGFlow automatic metadata. |
| PageIndex | Unknown / candidate mapping | Needs API/UI read-back audit and parser-path classification. |
| Image/table context window settings | Unknown / candidate mapping | Needs API field discovery and retrieval-impact validation. |
| Table-to-HTML setting | Unknown / likely parser-path-specific | May belong to native PDF/DeepDoc parsing rather than Markdown handoff. |
| DeepDoc native parser settings | Separately gated | Requires explicit DeepDoc live baseline approval. |

## Update Plan

### P0 - Build A Parameter Mapping Inventory

Create a public-safe mapping inventory that names each sidecar-derived
recommendation and its current disposition:

- `materialized_to_ragflow`;
- `materialized_to_manifest`;
- `local_audit_only`;
- `advisory_after_build`;
- `unsupported_or_gated`;
- `native_parser_only`;
- `unknown_api_mapping`.

Acceptance target:

- The inventory covers profile suggestions, ingest-plan parser profiles,
  retrieval hints, metadata, image/table signals, and known RAGFlow UI controls.
- Every field has a reason, required verification, and parser-path scope
  (`markdown_handoff`, `deepdoc_native`, or `unknown`).
- The inventory contains no live endpoint, credential, dataset ID, document ID,
  KB name, raw chunk, or private run-root value.

### P0 - Add Read-Back Audit For Existing KBs

Add a read-only audit path that compares requested profile settings, dry-run
payload preview, and RAGFlow read-back state for a user-selected KB.

Acceptance target:

- The audit reports which settings were requested, observed, missing, defaulted,
  or unsupported.
- The audit can run without mutation and can redact all live identifiers.
- The audit distinguishes UI labels from API payload keys.
- The audit explains when a UI option belongs to a native parser path rather
  than the Markdown handoff path.

### P1 - Confirm API Field Mapping With Fake Clients

Before adding writable behavior, create fake-client tests for candidate fields.

Acceptance target:

- Tests prove exact create/update payload shapes for each proposed field.
- Unsupported or unknown fields remain blocked and visible in reports.
- `chunk_overlap` or overlap-percent behavior is not enabled until the API
  contract is confirmed.
- Native-only fields cannot be sent through the Markdown handoff path by
  accident.

### P1 - Add Reviewed Materialization For Confirmed Fields

Extend profile materialization only for fields that pass API mapping and
fake-client coverage.

Candidate fields:

- overlap percent or API-equivalent overlap setting;
- automatic metadata if the API supports a safe dataset-level field;
- PageIndex if the API supports it for the selected parser path;
- image/table context window settings if the API supports them and retrieval
  evidence justifies the change;
- table parser settings only when parser-path compatibility is proven.

Acceptance target:

- Dry-run shows the requested and effective values before live mutation.
- Build payload preview classifies every materialized and non-materialized
  field.
- The live manifest or read-back report records observed values.
- No default profile changes are made from a single exploratory benchmark.

### P1 - Run Disposable Live Validation

Use disposable KBs to verify that confirmed fields are actually accepted,
visible in UI/read-back, and do not regress retrieval evidence.

Acceptance target:

- The run creates only explicitly approved disposable KBs.
- Read-back confirms the intended fields were persisted.
- Retrieval comparison records public-safe aggregate and query-level metrics.
- Cleanup is executed and verified before any checklist item is closed.

### P2 - Split Markdown Handoff And DeepDoc Native Baselines

Keep Markdown handoff parameter materialization separate from DeepDoc/native PDF
parser behavior.

Acceptance target:

- Markdown handoff profiles do not claim to configure native PDF-only parser
  controls.
- DeepDoc baseline work has its own explicit live approval and report.
- Public docs state which parser path each setting applies to.

## Task Checklist

- [x] Add a parameter mapping inventory covering sidecar recommendations,
      current materialization status, parser-path scope, and required
      verification.
- [ ] Add a read-only KB parameter read-back audit with public-safe redaction.
- [ ] Add fake-client tests for any newly writable parser or dataset fields.
- [ ] Extend `build_payload_preview` and handoff consumption status to show
      candidate UI/parser fields and why each is materialized or not.
- [ ] Add reviewed materialization for confirmed fields only.
- [ ] Run a disposable live validation for confirmed fields after explicit user
      approval.
- [ ] Record retrieval and read-back evidence in public-safe retention artifacts.
- [ ] Keep DeepDoc/native parser options as a separate approval path unless the
      current run explicitly targets DeepDoc.
- [ ] Update user-facing guidance after implementation and verification.

## Current Development Progress

This document started as the planning artifact for KB parameter materialization.
The first P0 implementation slice now adds an embedded
`parameter_materialization_inventory` block to `ragflow-kb-build --dry-run`
output.

Implemented on 2026-07-09:

- Added `ragflow_parameter_materialization_inventory_v1` as an embedded KB build
  report block.
- The inventory classifies selected-profile parser settings, profile
  suggestions, retrieval hints, ingest-plan parser evidence, metadata sidecars,
  and known RAGFlow UI controls.
- Each inventory field records disposition, parser-path scope, target, reason,
  and required verification.
- The block is offline-only and records zero RAGFlow calls, zero live writes,
  zero script-owned LLM calls, and no raw chunks.
- Schema identity coverage was added for the embedded block.

Related completed evidence:

- `docs/34-pipeline-consumption-gap-quality-improvement-plan.md` closed the
  handoff-to-KB consumption gap for payload preview, top-level language,
  delimiter guidance, bounded keyword/question enrichment experiments, and
  public-safe retention.
- `docs/35-standard-benchmark-dataset-integration-plan.md` established the
  benchmark evidence path and completed the first exploratory Open RAG Benchmark
  seed through a disposable live comparison.

Remaining gap:

- The sidecar recommendation surface is now visible in a field-level inventory,
  but candidate UI/parser options still need API mapping, fake-client coverage,
  read-back evidence, and disposable live validation before they become
  materialized settings.

## Validation Evidence / Residual Gated Work

Docs-only validation for this plan:

- `git diff --check`;
- targeted public-doc redaction scan over this document and any referencing
  docs;
- release hygiene when the update touches live boundaries or public report
  behavior.

Implementation validation for future slices:

- fake-client tests for any new writable payload field;
- dry-run and build payload preview tests;
- schema identity and report-surface inventory checks if new public reports are
  added;
- explicit live approval, disposable KB cleanup, read-back evidence, and
  public-safe retention artifacts for live validation.

Residual gated work:

- RAGFlow live mutation remains approval-gated.
- DeepDoc/native PDF baseline remains separately approval-gated.
- Script-owned LLM/RAGAS evaluation remains out of scope.
