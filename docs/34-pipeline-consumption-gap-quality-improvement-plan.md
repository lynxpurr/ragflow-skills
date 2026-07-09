# Pipeline Consumption Gap Quality Improvement Plan

Status: offline upgrade batches complete; live enrichment comparison gated
Date: 2026-07-09

## Objective / Scope / Boundaries

This plan records the objective issues found during review of a real PDF
document-to-KB A/B/C/D/E comparison, then turns those findings into a focused
quality-improvement backlog for the current public RAGFlow skill suite.

The active scope is the handoff-to-KB boundary:

- `ragflow-doc-to-md` formal handoff sidecars, profile suggestions, retrieval
  hints, image/table evidence, and ingest-plan guidance.
- `ragflow-kb-build` profile loading, dry-run readiness, dataset creation
  payloads, parse/build manifests, image asset planning, and post-build
  recommendations.
- Retrieval-quality evidence only as a validation target for KB-build profile
  behavior; `ragflow-query` product adapters, hosted services, rerankers, and
  script-owned answer synthesis remain out of scope.

This plan does not enable live RAGFlow mutation by default, does not add
script-owned LLM/RAGAS calls, does not add private adapters, and does not change
the current CLI/archive release baseline. Any live disposable KB validation
remains explicitly approval-gated and must use sanitized public summaries.

## Problem Description

The reviewed field-trial report correctly identified the main architectural
pattern: the document pipeline now produces rich evidence, but the live KB build
path still materializes only a narrow subset of that evidence into RAGFlow.
The precise wording needs correction in several places.

Verified objective issues:

1. `retrieval_hints.json` is read by `ragflow-kb-build` dry-run and post-build
   recommendation logic, but it is not transformed into live RAGFlow parser,
   retrieval, routing, table, or image settings during the standard build.
2. `ChunkProfile.to_dataset_payload()` forwards profile `parser_config` fields
   to dataset creation, but only the reviewed profile values are sent. Keyword
   and question candidates from `retrieval_hints.json` are not used to derive
   `auto_keywords` or `auto_questions`.
3. `__language__` is intentionally treated as an internal profile hint and is
   filtered from the dataset parser payload. As a result, Chinese handoffs can
   still create datasets that require a separate top-level language update.
4. `chunk_overlap` is retained in the local profile manifest and dry-run
   estimates, but it is not part of the currently supported parser payload
   model. The next change must first confirm the current RAGFlow API contract
   before treating overlap as writable.
5. `profile_suggestions.json` can recommend a larger delimiter profile than the
   observed RAGFlow API accepts. The build path needs a materialization/review
   step that clamps unsupported values, records the clamp reason, and keeps the
   original suggestion auditable.
6. `asset-upload-plan` can classify sidecar image references as missing when
   sidecars contain image paths relative to the `documents/` directory but the
   resolver checks only the handoff root.
7. The A/B/C/D/E summary table mixed pairwise and global win-count language.
   Pairwise statements such as "A wins 9/10 against C" should be separated from
   global best-per-query counts.
8. The retained local evidence is enough to verify the handoff sidecars,
   profile payloads, dry-run summaries, and image-ingestion plan behavior, but
   the full live dataset read-back and raw per-query retrieval outputs were not
   retained in a public-safe artifact set. Future comparisons need saved,
   sanitized query-result reports.

Evidence confidence:

| Finding | Confidence | Notes |
| --- | --- | --- |
| Rich handoff sidecars exist and include retrieval hints, profile suggestions, quality, image, and table evidence. | High | Verified from retained local sidecars. |
| `retrieval_hints.json` is summarized but not live-materialized into parser/retrieval settings. | High | Verified from build dry-run behavior and source inspection. |
| Top-level dataset language is not set by the current profile payload path. | High | Verified from profile payload filtering and existing tests. |
| `chunk_overlap` is not currently sent as a supported parser payload field. | High | Verified from the supported parser key set and dry-run output. |
| Delimiter profile improved the reviewed skill-built KB quality relative to naive profile. | Medium | Report metrics are internally consistent, but raw public-safe query-result artifacts are incomplete. |
| Native PDF parsing remained the best observed retrieval baseline for this sample. | Medium | Report metrics support this, but future paired evidence should retain raw query outputs. |
| `auto_keywords` or `auto_questions` will improve recall by a specific percentage. | Low | This remains a hypothesis requiring controlled experiments. |

## Update Plan

### P0 - Make Requested And Effective Build Settings Explicit

Add a build payload preview that shows exactly which profile, parser, language,
embedding, and advisory fields will be sent to RAGFlow and which fields remain
local-only. The report should be emitted in dry-run and optionally embedded in
the live `kb_manifest.json`.

Acceptance target:

- A user can tell before live mutation whether language, delimiter,
  `auto_keywords`, `auto_questions`, and any overlap advice will be sent,
  ignored, or require a separate guarded operation.
- The preview distinguishes source sidecars from actual RAGFlow dataset payload
  fields.

### P0 - Add Safe Dataset Language Materialization

Introduce a top-level language materialization path from reviewed profiles or
ingest plans to RAGFlow dataset settings. This should not put language inside
`parser_config`.

Acceptance target:

- Dry-run reports the selected top-level language and its source.
- Fake-client tests prove create-or-update behavior without live mutation.
- Live execution, when approved, either sends language during dataset creation
  if the API accepts it or performs a guarded dataset update after creation.

### P0 - Add Profile Suggestion Materialization

Create a deterministic helper that converts `profile_suggestions.json` plus
optional `ragflow_ingest_plan.yaml` into a reviewed build profile. It should
preserve original suggestions, apply known API limits, and emit warnings for
local-only or unsupported fields.

Acceptance target:

- The helper can choose a delimiter profile when chunk markers are dense and
  aligned.
- Oversized `chunk_token_num` values are clamped with an explicit reason.
- `__language__` is converted to a top-level language recommendation, not a
  parser config field.
- The resulting profile passes existing profile lint and build dry-run checks.

### P1 - Fix Sidecar Image Path Resolution

Repair sidecar image reference resolution so paths such as `images/...` can be
resolved against both the handoff root and the handoff `documents/` directory
when appropriate.

Acceptance target:

- Existing Markdown image references still resolve relative to the Markdown
  document directory.
- Sidecar-only references no longer create false `image_missing` errors when
  the file exists under `documents/images/...`.
- Semantic alias references remain advisory and do not become upload blockers.

### P1 - Make Handoff Consumption Status First-Class

Add a dry-run or inspect report section that classifies every important handoff
artifact as one of:

- `materialized_to_ragflow`
- `materialized_to_manifest`
- `advisory_after_build`
- `local_audit_only`
- `unsupported_or_gated`

Acceptance target:

- `doc_manifest.json`, Markdown documents, `quality_report.json`,
  `profile_suggestions.json`, `retrieval_hints.json`, `metadata.json`,
  `assistant_profile.json`, `ragflow_ingest_plan.yaml`, image files, and table
  artifacts each receive a clear status.
- The report avoids implying that assistant or query retrieval parameters can be
  written through the KB creation API.

### P1 - Run Controlled Enrichment Experiments

Treat keyword/question enrichment as an experiment, not a default behavior.
Use fake-client/offline planning first, then optionally an approved disposable
KB comparison.

Acceptance target:

- Candidate profiles compare `auto_keywords` and `auto_questions` values such
  as `0`, `1`, and a small bounded non-zero value.
- Benchmarks record recall, precision, empty-result rate, top-k stability, and
  query-specific regressions.
- No default profile changes until benchmark evidence shows net benefit.

### P1 - Improve Delimiter Profile Recommendation

When chunk markers are dense and aligned, dry-run should recommend a delimiter
profile more prominently and explain why naive token slicing will ignore those
markers.

Acceptance target:

- Dry-run already detects ignored chunk markers; the next report should include
  an actionable reviewed-profile command or materialization command.
- The recommendation explains that delimiter controls boundaries but does not
  override server-side parent chunk limits.

### P2 - Add Guarded Image Ingestion Orchestration

Keep image ingestion separate by default, but make the reviewed path easier to
execute after `asset-upload-plan` succeeds.

Acceptance target:

- A command manifest or guarded flag can chain image ingestion only after plan
  review and exact count confirmations.
- Image ingestion remains disabled for dry-run and default build.
- The manifest records Markdown document parsing separately from visual document
  ingestion and parse status.

### P2 - Retain Public-Safe Retrieval Evaluation Artifacts

Future A/B/C/D/E comparisons should retain sanitized query-result artifacts,
not only prose summaries.

Acceptance target:

- Query evaluation records per-query scores, ranks, document/chunk identifiers
  in redacted or synthetic-safe form, and aggregate metrics.
- Reports distinguish global best-per-query counts from pairwise win counts.
- Public docs contain only sanitized metrics and artifact names.

## Task Checklist

- [x] Add a build payload preview to dry-run output and live manifests, including
      sent fields, local-only fields, and unsupported/gated fields.
- [x] Add fake-client tests for top-level dataset language materialization from
      profile and ingest-plan evidence.
- [x] Implement guarded top-level language create-or-update behavior without
      placing language inside `parser_config`.
- [x] Add a profile materialization helper for `profile_suggestions.json` and
      `ragflow_ingest_plan.yaml`.
- [x] Add tests proving oversized delimiter suggestions are clamped and the
      original suggestion remains auditable.
- [x] Fix sidecar image path resolution for `documents/images/...` fallback
      while preserving semantic alias warning behavior.
- [x] Add a handoff consumption status report covering profiles, retrieval
      hints, metadata, assistant profile, ingest plan, image assets, and table
      artifacts.
- [x] Add CLI tests showing retrieval hints are summarized but not silently
      written to live parser settings unless a reviewed profile says so.
- [x] Add delimiter-profile recommendation or materialization guidance when
      chunk markers are dense and aligned.
- [x] Add an enrichment experiment plan for bounded `auto_keywords` and
      `auto_questions` candidates.
- [ ] Run a disposable, approval-gated enrichment comparison only after offline
      planning and cleanup readiness pass.
- [x] Add a public-safe query-result retention format for future A/B/C/D/E
      comparisons.
- [x] Update the relevant user-facing skill guidance after behavior changes are
      implemented and verified.
- [x] Run focused tests, release hygiene, and docs redaction scans before marking
      any checklist item complete.

## Current Development Progress

This document is the initial planning artifact for the consumption-gap follow-up.
No runtime, CLI, schema, public skill guidance, release gate, or live workflow
behavior is changed by this document.

First upgrade batch completed on 2026-07-09:

- `ragflow-kb-build` dry-run and live build reports now include an embedded
  `ragflow_kb_build_payload_preview_v1` block. The preview lists the dataset
  create payload, top-level language source, sent parser fields, local-only
  profile hints such as `chunk_overlap` and `parser_config.__language__`, and
  advisory `retrieval_hints.json` fields that are not silently written to live
  parser settings.
- Reviewed profiles now support top-level `language`. Existing profiles that
  still carry `parser_config.__language__` are normalized to top-level language
  for the RAGFlow dataset create payload while keeping the internal parser key
  out of `parser_config`.
- `--ingest-plan` was added to `build.py`, with automatic discovery of
  `ragflow_ingest_plan.yaml`, `.yml`, or `.json` next to `doc_manifest.json`.
  Ingest-plan language evidence is materialized only into top-level dataset
  language, not into parser config.
- `materialize_profile_suggestion()` turns `profile_suggestions.json` plus
  optional `ragflow_ingest_plan` evidence into a reviewed build profile, chooses
  delimiter profiles when present, clamps oversized `chunk_token_num` values to
  the current reviewed limit, preserves the source suggestion, and emits a
  materialization report.
- `asset-upload-plan` now resolves sidecar image paths such as `images/...`
  against both the handoff root and `documents/`, while keeping semantic image
  aliases advisory.
- User-facing `ragflow-kb-build` guidance now describes payload preview,
  ingest-plan language materialization, reviewed profile clamping, and the
  sidecar image fallback.

Second upgrade batch completed on 2026-07-09:

- `ragflow-kb-build` dry-run output, live stdout payloads, and `kb_manifest.json`
  now include an embedded `ragflow_handoff_consumption_status_v1` block. It
  classifies Markdown documents, `doc_manifest.json`, `quality_report.json`,
  `profile_suggestions.json`, `retrieval_hints.json`, `metadata.json`,
  `assistant_profile.json`, `ragflow_ingest_plan.*`, image assets, and table
  artifacts as materialized to RAGFlow, materialized to the manifest, advisory
  after build, local audit only, or unsupported/gated.
- CLI coverage now proves that `retrieval_hints.json` keyword and question
  candidates are summarized and surfaced in previews, but are not silently
  converted into live `auto_keywords` or `auto_questions` parser settings unless
  a reviewed profile explicitly requests those settings.
- Dry-run ingest readiness now includes `delimiter_profile_guidance` when chunk
  markers are present but the selected profile ignores them. The guidance
  recommends planning a reviewed delimiter candidate and states that delimiters
  do not override server-side parent chunk limits.
- `profile.py experiment --bounded-defaults` now creates the small offline
  `auto_keywords`/`auto_questions` matrix `0`/`1` for conservative enrichment
  planning before any approval-gated disposable live comparison.
- User-facing `ragflow-kb-build` guidance, host-agent setup notes, and the
  onboarding prompt now call out `handoff_consumption_status`, advisory
  retrieval hints, delimiter guidance, and the bounded enrichment planning
  command.

Third upgrade batch completed on 2026-07-09:

- `validate.py` now accepts `--retention-json` and `--retention-md` to emit
  `ragflow_public_query_result_retention_v1`, a public-safe per-query retention
  artifact for future A/B/C/D/E comparisons.
- The retention artifact records per-query pass/fail counts, benchmark metrics
  when available, result ranks, stable content hashes, hashed dataset/document
  and chunk references, and aggregate validation/benchmark metrics.
- The retention artifact deliberately omits raw query text, raw chunk text, raw
  dataset IDs, raw document IDs, raw chunk IDs, raw KB names, and raw document
  names. Its safety block records `ragflow_calls=0` and
  `script_owned_llm_calls=0` because it is derived from the validation payload
  already in memory.
- The retention report includes comparison guidance that keeps
  `global_best_per_query_count` separate from `pairwise_win_count`, fixing the
  wording hazard found in the reviewed A/B/C/D/E summary pattern.
- User-facing `ragflow-kb-build` guidance, host-agent setup notes, and the
  onboarding prompt now recommend `--retention-json` / `--retention-md` for
  retained comparison evidence instead of copying raw query output into shared
  reports.

Current verified baseline:

- The public CLI/archive path remains the canonical release baseline.
- The rich handoff producer is ahead of the default live KB consumer for this
  field-trial pattern.
- Existing dry-run behavior now detects relevant risks including ignored chunk
  markers, language-profile review issues, handoff consumption boundaries, and
  unsupported or gated image/table sidecar materialization.
- Image ingestion can succeed after review, and sidecar image paths such as
  `images/...` are resolved against `documents/images/...` before being reported
  missing.
- Future A/B/C/D/E comparisons can now retain public-safe query-result evidence
  via `ragflow_public_query_result_retention_v1` without publishing raw query
  text, raw chunk text, or raw live identifiers.

All ordinary offline checklist items in this plan are now implemented. The only
remaining checklist item is the disposable enrichment comparison, which remains
live-mutation gated and should start only after offline planning, cleanup
readiness, exact confirmations, and explicit user approval.

## Validation Evidence / Residual Gated Work

Docs-only validation required for this plan:

- `git diff --check`
- a targeted redaction scan over this changed document

Focused implementation validation for future slices:

- profile and build dry-run changes: targeted `test_profiles.py`,
  `test_kb_build_cli.py`, and any new runtime tests;
- asset plan changes: focused `test_kb_build.py` and CLI coverage for
  `asset-upload-plan`;
- report-surface or schema changes: schema identity, report-surface inventory,
  generated Markdown audit, runtime resilience inventory, and release hygiene;
- live disposable comparisons: explicit user approval, dry-run plan, cleanup
  readiness, exact confirmations, cleanup execution, and sanitized evidence.

First upgrade batch validation evidence:

- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/__init__.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py skills/ragflow-kb-build/scripts/build.py tools/schema_identity_check.py packages/ragflow-skill-runtime/tests/test_profiles.py packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py` passed.
- `python3 -m pytest packages/ragflow-skill-runtime/tests/test_profiles.py packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_build_dry_run_via_subprocess packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_build_dry_run_materializes_language_from_ingest_plan packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_build_live_path_reports_runtime_resilience_with_fake_client packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_build_live_path_materializes_language_from_ingest_plan_with_fake_client packages/ragflow-skill-runtime/tests/test_schema_identity_check.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py -q` passed with 45 tests.
- `python3 tools/schema_identity_check.py --report-json /tmp/ragflow-consumption-gap-schema-identity.json` passed with `ok=true`, 100 identities, and 0 findings.
- `python3 tools/report_surface_inventory.py --report-json /tmp/ragflow-consumption-gap-report-surface.json` passed with `ok=true`, 103 commands, and 0 findings.
- `python3 tools/release_hygiene_check.py` passed with `ok=true` and 0 findings.
- `git diff --check` passed.
- Changed-doc redaction scan hits were reviewed as placeholder commands, example
  `/tmp` work directories, environment-variable placeholders, example KB names,
  or technical terms such as `chunk_token_num`; no real endpoint, credential,
  dataset ID, document ID, private path, or raw retrieved chunk was added.

Second upgrade batch validation evidence:

- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/__init__.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/handoff.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py skills/ragflow-kb-build/scripts/build.py skills/ragflow-kb-build/scripts/profile.py tools/schema_identity_check.py packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py` passed.
- `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_profiles.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py -q` passed with 154 tests.
- `python3 tools/schema_identity_check.py --report-json /tmp/ragflow-consumption-gap-batch2-schema-identity.json` passed with `ok=true`, 101 identities, 0 failed identities, and 0 findings.
- `python3 tools/report_surface_inventory.py --report-json /tmp/ragflow-consumption-gap-batch2-report-surface.json` passed with `ok=true`, 103 commands, and 0 findings.
- `python3 tools/release_hygiene_check.py >/tmp/ragflow-consumption-gap-batch2-release-hygiene-after-doc-evidence.json` passed with `ok=true` and 0 findings.
- `git diff --check` passed.
- Changed-doc redaction scan hits were reviewed as placeholder commands, example
  `/tmp` work directories, environment-variable placeholders, example KB names,
  `DATASET_ID` placeholders, or technical terms such as `chunk_token_num`; no
  real endpoint, credential, dataset ID, document ID, private path, or raw
  retrieved chunk was added.

Third upgrade batch validation evidence:

- Red phase:
  `python3 -m pytest packages/ragflow-skill-runtime/tests/test_validation.py::ValidationTests::test_public_query_result_retention_omits_raw_text_and_hashes_identifiers packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_validate_writes_public_safe_query_result_retention_report -q` failed first because `PUBLIC_QUERY_RESULT_RETENTION_SCHEMA` and the retention helper did not exist.
- Green phase:
  `python3 -m pytest packages/ragflow-skill-runtime/tests/test_validation.py::ValidationTests::test_public_query_result_retention_omits_raw_text_and_hashes_identifiers packages/ragflow-skill-runtime/tests/test_kb_build_cli.py::KbBuildCliTests::test_validate_writes_public_safe_query_result_retention_report -q` passed with 2 tests.
- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/__init__.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/validation.py skills/ragflow-kb-build/scripts/validate.py tools/schema_identity_check.py packages/ragflow-skill-runtime/tests/test_validation.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py` passed.
- `python3 -m pytest packages/ragflow-skill-runtime/tests/test_validation.py packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_profiles.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py -q` passed with 180 tests.
- `python3 tools/schema_identity_check.py --report-json /tmp/ragflow-consumption-gap-batch3-schema-identity.json` passed with `ok=true`, 102 identities, 0 failed identities, and 0 findings.
- `python3 tools/report_surface_inventory.py --report-json /tmp/ragflow-consumption-gap-batch3-report-surface.json` passed with `ok=true`, 103 commands, and 0 findings.
- `python3 tools/release_hygiene_check.py >/tmp/ragflow-consumption-gap-batch3-release-hygiene-after-doc-evidence.json` passed with `ok=true` and 0 findings.

Residual gated categories:

- Live RAGFlow mutation remains approval-gated.
- Script-owned LLM/RAGAS generation remains out of scope.
- Reranker, provider, web/API, and service adapters remain post-CLI gated work.
- Private bridge work remains outside public release artifacts.
- Retrieval uplift from keywords, questions, images, or table hints remains a
  hypothesis until controlled benchmark evidence proves it.
