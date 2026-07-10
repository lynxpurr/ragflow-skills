# RAGFlow KB Parameter Materialization Plan

Status: active KB parameter materialization plan; P0 complete, Stage 7 read-only default evidence incorporated
Date: 2026-07-10

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
whose writable API behavior has not been confirmed. Fields that are visible in
read-back but rejected by create/update payloads are classified separately as
read-only server defaults.

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
| PageIndex | Native-parser-only / DeepDoc-gated | Stage 6 read-back observed `parser_config.pages`, but it is null for Markdown handoff KBs. |
| Image/table context window settings | Read-only server defaults | Stage 6 mapped these to `parser_config.image_context_size` and `parser_config.table_context_size`; Stage 7 showed create/update rejects these keys when present, while the server auto-populates default read-back values when they are omitted. |
| Table-to-HTML setting | Native-parser-only / DeepDoc-gated | Belongs to native PDF/DeepDoc parsing rather than the Markdown handoff create payload. |
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
- `read_only_server_default`;
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
- table parser settings only when parser-path compatibility is proven.

Excluded by Stage 7 evidence:

- image/table context window settings are API-visible but not writable through
  the observed create/update payload path, so they must not be added to
  `SUPPORTED_PARSER_KEYS` unless a future RAGFlow API contract changes.

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
- [x] Add a read-only KB parameter read-back audit with public-safe redaction.
- [x] Add fake-client tests and payload guards for candidate parser or dataset
      fields.
- [x] Extend `build_payload_preview` and handoff consumption status to show
      candidate UI/parser fields and why each is materialized or not.
- [x] Incorporate Stage 7 live rejection evidence for image/table context
      windows and classify them as read-only server defaults.
- [ ] Add reviewed materialization for future confirmed writable fields only.
- [ ] Run a disposable live validation for confirmed fields after explicit user
      approval.
- [ ] Record retrieval and read-back evidence in public-safe retention artifacts.
- [ ] Keep DeepDoc/native parser options as a separate approval path unless the
      current run explicitly targets DeepDoc.
- [ ] Update user-facing guidance after implementation and verification.

## Current Development Progress

This document started as the planning artifact for KB parameter materialization.
The first two P0 implementation slices now add an embedded
`parameter_materialization_inventory` block to `ragflow-kb-build --dry-run`
output and a read-only `parameter-audit` command for comparing requested
settings with read-back evidence.

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
- Added `ragflow_parameter_read_back_audit_v1` as a standalone public-safe
  report emitted by `ragflow-kb-build parameter-audit`.
- The audit compares `build_payload_preview` materialized targets with
  read-back `language` and `parser_config` values when those values are present
  in a local observed-state JSON.
- The audit classifies fields as `observed_match`, `observed_missing`,
  `observed_changed`, `not_observable`, `unknown_api_mapping`,
  `native_parser_only`, or `not_requested`.
- The command supports JSON, Markdown, and redaction sidecar outputs, performs
  no RAGFlow calls, performs no live writes, invokes no script-owned LLMs, and
  includes no raw chunks.
- Report surface, generated Markdown, runtime-resilience inventory, and schema
  identity coverage were updated for the new command.

Implemented on 2026-07-10:

- `ChunkProfile.to_dataset_payload()` now filters parser config to the reviewed
  public RAGFlow parser keys only: `chunk_token_num`, `delimiter`,
  `auto_keywords`, and `auto_questions`.
- Unsupported profile parser keys such as candidate PageIndex, native table
  parser, visual/layout, or other provider-specific controls remain visible in
  manifests and preview reports, but are not sent to RAGFlow create payloads.
- `build_payload_preview` now includes known RAGFlow UI/parser controls such as
  PageIndex, image/table context windows, automatic metadata, overlap percent,
  and table-to-HTML with `unknown_api_mapping` or `native_parser_only`
  classifications.
- `handoff_consumption_status` now includes a field-level
  `parameter_fields` block and parameter status counts for ingest-plan,
  retrieval-hint, metadata, and known UI/parser candidate fields.
- Fake-client live-build coverage now verifies that candidate unsupported or
  native-only parser fields do not reach `create_dataset()` payloads while the
  dry-run and handoff reports still explain why they were blocked.

Read-only Stage 6 evidence incorporated on 2026-07-10:

- A retained Markdown handoff KB was inspected through read-only RAGFlow
  read-back; no create, update, delete, upload, parse, reparse, DeepDoc
  baseline, or script-owned LLM/RAGAS call was performed.
- Read-back confirmed exact matches for the currently materialized fields:
  `chunk_token_num`, `delimiter`, `auto_keywords`, `auto_questions`, and
  top-level `language`.
- `parser_config.image_context_size` and
  `parser_config.table_context_size` were observed as API-visible mappings for
  the image and table context-window UI controls, so these controls are no
  longer classified as unknown mappings. Stage 6 alone did not prove writable
  behavior.
- `parser_config.pages` was observed for PageIndex, but it was null for the
  Markdown handoff KB, so PageIndex is classified as DeepDoc/native-path gated.
- Automatic metadata and overlap percent remain unknown API mappings for this
  Markdown handoff path.

Related completed evidence:

- `docs/34-pipeline-consumption-gap-quality-improvement-plan.md` closed the
  handoff-to-KB consumption gap for payload preview, top-level language,
  delimiter guidance, bounded keyword/question enrichment experiments, and
  public-safe retention.
- `docs/35-standard-benchmark-dataset-integration-plan.md` established the
  benchmark evidence path and completed the first exploratory Open RAG Benchmark
  seed through a disposable live comparison.

Stage 7 writable validation evidence incorporated on 2026-07-10:

- A disposable live validation was attempted for four context-window profiles:
  a zero-value control and three non-zero image/table combinations.
- RAGFlow rejected every create payload that included
  `parser_config.image_context_size` or `parser_config.table_context_size`,
  including zero values, with an extra-input validation error.
- No disposable KB was created, so no retrieval comparison or cleanup deletion
  was needed for these profiles.
- Creating the same Markdown handoff profile without these keys remains the
  supported path; RAGFlow read-back may still show server-populated default
  values.
- Code and public guidance must therefore treat these fields as read-only
  server defaults: visible in dry-run/audit reports, preserved in manifests
  when supplied for analysis, but filtered from `create_dataset()` payloads.

Remaining gap:

- The sidecar recommendation surface is now visible in a field-level inventory,
  requested parser settings can now be compared with read-back evidence, and
  candidate UI/parser controls are visible in dry-run and handoff-consumption
  reports. Image/table context-window settings now have read-back API keys but
  are explicitly not writable through the observed create/update payload path.
  Other candidate UI/parser options still need writable payload confirmation,
  fake-client coverage, and disposable live validation before they become
  materialized settings.

## Validation Evidence / Residual Gated Work

Verified on 2026-07-10 for the Stage 7 read-only server-default repair:

- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py skills/ragflow-kb-build/scripts/build.py`;
- `python3 -m pytest packages/ragflow-skill-runtime/tests -q` passed with
  669 tests and 6 subtests;
- `python3 tools/schema_identity_check.py --report-json <temporary-report-json>`;
- `python3 tools/release_hygiene_check.py`;
- `git diff --check`;
- targeted redaction scan over this document and `skills/ragflow-kb-build/SKILL.md`.

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
