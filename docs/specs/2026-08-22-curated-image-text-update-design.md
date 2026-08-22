---
doc_type: spec
topic: curated-image-text-update
status: active
created: 2026-08-22
updated: 2026-08-22
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related:
  - docs/44-canonical-multimodal-ingest-quality-improvement-plan.md
  - docs/16-system-closeout-report.md
---

# Curated Image-Text Update Design

## Context

The canonical review record (`ragflow_canonical_review_v1`) classifies image assets
with an `ingestion_intent` of `visual_extract`, `context_bound`, or `exclude`.
`context_bound` images only need to be retrievable together with their surrounding
text; they do not need VLM visual understanding. Until now such assets stayed
package-only: they never entered the visual upload plan, and the ingestion-readiness
report hard-blocked any canonical-context claim with
`context_bound_capability_missing` because no verified curated image-text transport
existed (`docs/44-canonical-multimodal-ingest-quality-improvement-plan.md`).

This specification defines the deferred "curated image-text update" adapter: for each
context-bound image, compose a text chunk from the review-pinned textual context and
write it to RAGFlow so it replaces the chunk content the deployment's visual parser
(VLM) produced. The runtime and tests already reserve the contract triple
`curated_image_update` / `json_put` / `document_detail`, gated by
`ragflow_transport_capability_v1` evidence; this design keeps that shape.

The owner approved this adapter scope on 2026-08-22. This document does not authorize
credentials, network access, or live RAGFlow mutation. Live use still requires
target-deployment capability evidence attesting the curated update operation and a
separate target-specific authorization, exactly as docs/44 requires.

## Objective

Provide a standalone, fail-closed `curated-image-update` subcommand in
`ragflow-kb-build` that uploads context-bound image assets, lets the deployment parse
them, and then replaces the resulting chunk content with curated text derived from
the canonical review's hash-pinned context selector, producing an auditable
JSON-first report.

## Non-Goals

- Changing `image-ingestion-execute` behavior or the `parsed_visual_only` staging
  semantics. Visual-extract assets remain that command's responsibility.
- Flipping the multimodal manifest `mutation_lineage.update` slot; the manifest is
  produced at execute time and cannot observe a later curated update.
- Live verification against a real RAGFlow deployment. The default test suite stays
  offline; live runs remain opt-in and separately authorized.
- A new image state machine, automatic table conversion, or any second production
  truth derived from VLM output.

## Requirements And Invariants

- Fail-closed: without `ragflow_transport_capability_v1` evidence attesting
  `curated_image_update` / `json_put` / `document_detail` (plus the existing upload
  and parse triples), no RAGFlow client may be instantiated.
- Hash-pinned text: curated text is extracted from the accepted Markdown via the
  canonical review's `context_selector` (`line:START-END`) and must match
  `context_sha256`; a stale or mismatched hash aborts before any mutation.
- Explicit confirmation: `--execute`, `--dataset-id` with matching
  `--confirm-dataset-id`, and `--confirm-planned-count` equal to the number of
  context-bound assets in the plan are all required.
- Drift detection: each asset's file SHA-256 must match the value recorded in the
  asset upload plan before upload.
- Deterministic chunk replacement: the deployment's first chunk of each parsed image
  document receives the full curated text. Additional chunks are left untouched and
  reported as `extra_chunks_left_untouched` warnings; they are never silently
  rewritten or deleted.
- Auditability: the report records, per asset, the source path, SHA-256, uploaded
  document id, observed and updated chunk ids, `context_selector`, `context_sha256`,
  and `curated_text_sha256`. Reports are JSON-first; Markdown output is a sanitized
  summary, and `--redaction-report` reuses the existing governance sanitizer.
- Readiness semantics: ingestion readiness stays blocked for context-bound assets
  unless transport capability evidence attesting the curated update triple is
  supplied; evidence that lacks the operation must keep the blocked status.

## Design

### Runtime: chunk endpoints

`ragflow_client.py` gains two methods following the existing `update_dataset`
code-check pattern:

- `list_chunks(dataset_id, document_id, *, page=1, page_size=100)` — GET
  `/datasets/{dataset_id}/documents/{document_id}/chunks`.
- `update_chunk(dataset_id, document_id, chunk_id, payload)` — PUT
  `/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}`.

The exact chunk-update endpoint and payload must be verified against the target
deployment (OpenAPI or operator evidence) before any live use; the transport
capability gate is where that verification is enforced.

### Runtime: `curated_image_update.py`

- `build_curated_image_update_plan(asset_plan_path, canonical_review_path,
  accepted_markdown_path)` validates both input schemas, selects assets whose
  `ingestion_intent` is `context_bound`, re-extracts the pinned text with the
  canonical review's `_context_text` helper, verifies `_fragment_sha256` against
  `context_sha256`, and composes the curated text (source heading plus the selected
  context lines, compacted). Output is a `ragflow_curated_image_update_plan_v1`
  mapping with per-asset `source_path`, `sha256`, `mime_type`, `context_selector`,
  `context_sha256`, `curated_text`, and `curated_text_sha256`.
- `create_curated_image_update_report(...)` builds the
  `ragflow_curated_image_update_report_v1` report and its sanitized Markdown
  rendering.

### CLI: `curated-image-update`

A new direct-runner subcommand in `skills/ragflow-kb-build/scripts/build.py`,
dispatched next to `image-ingestion-execute`:

1. Offline assembly: build the curated update plan (above) before any client exists.
2. Gating in the same order as execute: `--execute`, exact confirmations, schema
   checks, per-asset path resolution and SHA-256 drift checks, then all three
   transport gates (`visual_document_upload` / `multipart_post` /
   `dataset_documents`, `visual_document_parse` / `json_post` / `dataset_chunks`,
   `curated_image_update` / `json_put` / `document_detail`).
3. Execution reuses the existing upload, batched parse-trigger, polling, and
   checkpoint helpers. After each document reaches `parsed`, the command lists its
   chunks, PUTs the curated text into the first chunk, and reads back to confirm the
   stored content matches.
4. The report carries per-asset lineage, the `extra_chunks_left_untouched` warnings,
   transport gate evidence, and checkpoint state.

### Readiness unlock

`create_kb_asset_ingestion_readiness_report` accepts an optional
`transport_capability` mapping. When supplied and the curated update triple verifies,
the `context_bound_capability_missing` error becomes an informational
`context_bound_capability_attested` finding and `checks.canonical_context_claim`
reports `READY` with `capability: "attested"` and the evidence SHA-256. Missing or
non-attesting evidence keeps the current blocked behavior. The
`image-ingestion-readiness` CLI gains a `--transport-capability` flag reusing the
existing loader.

## Compatibility And Migration

- Default behavior is unchanged: without capability evidence, readiness stays
  blocked and no code path reaches RAGFlow for context-bound assets.
- Existing report schemas are untouched; the new plan and report use new schema
  names.
- `image-ingestion-execute` output, including `image_enhancement` and
  `parsed_visual_only`, is unchanged.

## Failure Handling And Rollback

- Any gate failure, hash drift, stale context hash, or schema mismatch aborts before
  client instantiation with a non-zero exit and a JSON error.
- Per-asset failures (upload, parse trigger, poll timeout, chunk update, read-back
  mismatch) are isolated: the asset is marked failed, remaining assets continue, and
  the report ends `partial_failure` with a non-zero exit.
- Checkpoints record confirmed uploads and completed updates so `--resume` skips
  finished assets; `--force-reupload-confirmed` requires `--resume`, matching the
  execute command.
- Rollback is operator-driven: the report records prior chunk content hashes
  (never private literals) so a follow-up authorized update can restore earlier
  content. The command itself never deletes chunks or documents.

## Validation Strategy

- Offline unit tests only in the default suite: plan assembly (selector extraction,
  stale-hash refusal, non-context-bound assets skipped), report schema, client
  request shapes, readiness attested/blocked transitions, and CLI gate-first tests
  asserting zero client instantiations on any gate failure.
- End-to-end fake-client CLI tests cover the upload → parse → list → update →
  read-back sequence, multi-chunk warnings, partial failure, checkpoint resume, and
  redaction.
- `tools/document_lifecycle_check.py`, `tools/build_release.py --check`, and
  `tools/release_hygiene_check.py` must pass.

## Acceptance Criteria

- With no context-bound assets, the command exits cleanly without mutation.
- With context-bound assets and no attesting capability evidence, readiness stays
  blocked and `curated-image-update` refuses before client creation.
- With attesting evidence and exact confirmations, each context-bound asset's first
  chunk content equals the curated text after read-back, and the report carries the
  full per-asset lineage.
- All default offline test suites and repository hygiene checks pass.

## Decision Log

- 2026-08-22: Standalone subcommand chosen over extending `image-ingestion-execute`
  to keep visual-extract semantics untouched (owner-approved).
- 2026-08-22: First-chunk replacement with explicit warnings for extra chunks
  chosen over rewriting or deleting additional chunks, to keep mutation minimal and
  auditable.
- 2026-08-22: The adapter ships fail-closed; the docs/44 trigger is satisfied for
  offline code only, and live use still needs target-specific evidence and
  authorization.
