# Current Skills Quality Improvement Checklist

Status: in progress; P0 live build remains gated and P1 multimodal validation is partially complete
Date: 2026-07-06
Last reviewed: 2026-07-07

## Objective

This document records concrete function and performance improvements for the current
`ragflow-doc-to-md`, `ragflow-kb-build`, `ragflow-query`, and shared
`ragflow-skill-runtime` suite after the latest APOLLO representative-document field
trial.

This is not a report-format cleanup plan. It focuses on improving the skills themselves:
better ingestion quality, stronger multimodal asset handling, more reliable KB build
evidence, clearer profile decisions, stronger retrieval validation, and lower workflow
friction.

The document is organized into three parts:

1. Problem description.
2. Solution design.
3. Development task checklist.

The plan keeps the existing public-suite boundaries:

- no live RAGFlow mutation by default;
- no script-owned LLM or RAGAS execution by default;
- no private paths, endpoints, dataset IDs, document IDs, raw chunks, prompts, or secrets
  in public docs;
- deterministic offline reports before any live action;
- explicit confirmation and cleanup evidence for every mutating RAGFlow operation.

## Current Development Progress

Completed public offline work in the current implementation pass:

- `bcd4bb5` added `ragflow_kb_asset_upload_plan_v2`, explicit referenced/residual/missing
  asset classes, planned visual upload separation, APOLLO-style 15-referenced plus
  6-residual fixture coverage, residual review warnings, and schema identity coverage.
- `9ec1d4a` added `ragflow_multimodal_kb_manifest_v1`, fake read-only document-list
  coverage for Markdown and visual documents, thumbnails, chunk counts, parse states, and
  malformed response shapes, plus schema identity coverage.
- `5b028b6` taught `parse-report` and `health-report` to consume multimodal manifest
  fields so visual, thumbnail, and VLM state can flow into downstream KB evidence.
- `a5acf41` added `ragflow_kb_asset_ingestion_report_v1` in readiness mode, the
  non-mutating `image-ingestion-readiness` command, generated Markdown/report-surface
  inventory coverage, runtime resilience inventory updates, CLI tests, and schema
  identity coverage.
- The current slice adds gated `image-ingestion-execute` behavior with `--execute`, exact
  dataset/count confirmations, fake-client visual upload, parse trigger, document-state
  polling, partial-failure reporting, cleanup-readiness evidence, and report/runtime
  inventory coverage.
- Existing formal-ingest readiness and retrieval-hint code already cover table parent
  chunk preflight, table token estimates, row/column/header complexity signals, selected
  `chunk_token_num` warnings, and dense chunk-marker HTML table integrity evidence.
- APOLLO table-QA validation now summarizes strict-recall coverage categories for numeric
  rows, units, model names, and cross-column lookup fixtures.
- `ragflow_profile_decision_report_v1` now ranks profile candidates with retrieval,
  strict recall, table/image recall, empty-result, latency, chunk-count, and context
  warning evidence, while blocking default changes when sample thresholds are too small.
- Benchmark validation now embeds `ragflow_multimodal_benchmark_v1`, preserves qrels
  `expected_modality`, `benchmark_category`, and `expected_chunks` extensions, reports
  result modality distributions, and adds image precision, image recall, visual coverage,
  and table recall metrics for multimodal query sets.
- `ragflow-query diagnose-result` now accepts expected modality, document, dataset, and
  tag scope hints, classifies no-result, wrong-modality, table-fragment, image-evidence,
  pollution, route-mismatch, and low-similarity symptoms, and maps each class to concrete
  follow-up commands in JSON and Markdown reports.

The live disposable Markdown-plus-image build remains gated. It must stay unchecked until
the user explicitly approves live mutation and sanitized cleanup evidence is recorded.

## Part 1: Problem Description

### 1.1 Field-Trial Signals

The APOLLO workflow showed that the replacement path is viable:

- MinerU FastAPI can produce a formal Markdown handoff with tables, images, chunk markers,
  rich sidecars, and ingest readiness.
- RAGFlow can parse the Markdown document and preserve important numeric table evidence.
- Manual image upload as separate visual documents can make RAGFlow create image chunks
  and thumbnails.
- 1024-token and 2048-token profiles produced close retrieval metrics on a small
  six-query comparison set.

The same workflow exposed quality gaps in the current skills:

- `ragflow-kb-build` uploads Markdown documents on the main live path; visual image
  documents are not yet a first-class gated build feature.
- Image-rich KB evidence is not yet captured by the build skill in a reusable manifest.
- Handoff assets need stronger referenced-vs-residual classification before upload
  decisions.
- Profile recommendations need larger, stricter benchmark evidence before becoming
  defaults.
- Production readiness checks should connect build, parse, health, activation, query, and
  cleanup artifacts into one reusable evidence chain.

### 1.2 Functional Quality Problems

#### Markdown And Image Handoff Are Not Fully Connected To KB Build

`ragflow-doc-to-md` can produce Markdown-local images and rich sidecars, and
`ragflow-kb-build asset-upload-plan` can review local assets offline. The normal live
build path still uploads only Markdown documents. This leaves a gap between a high-quality
formal handoff and an image-rich RAGFlow KB.

Impact:

- Host agents must manually upload images if they want visual documents.
- Manual visual uploads do not produce a standard skill-owned manifest.
- Image parse failures, thumbnails, VLM chunks, and image document IDs are hard to audit
  later.

#### Asset Counts Do Not Yet Express Upload Intent Clearly Enough

The representative handoff contains Markdown-referenced images and additional local image
files. Current reports can count these files, but the upload policy needs sharper classes
so users do not upload parser leftovers or duplicate visual documents by accident.

Impact:

- A local image count can be mistaken for the intended upload count.
- Residual parser files can pollute KB visual chunks.
- Review decisions depend on ad hoc interpretation instead of stable schema fields.

#### KB Evidence Is Strong For Markdown Builds But Weak For Image-Rich Builds

Markdown-only builds already produce `kb_manifest.json`, parse reports, and health
reports. Image-rich builds need the same level of machine-readable evidence across
Markdown and visual documents.

Impact:

- Image-rich KBs cannot be refreshed or diagnosed from a single manifest chain.
- `parse-report` and `health-report` cannot fully explain visual-document state.
- Later query validation cannot attribute answer evidence to text, table, or image
  sources reliably.

#### Large Tables Need Stronger Preflight And Retrieval Guarantees

The APOLLO table survived the tested profile choices, but table preservation still
depends on chunk markers, selected token limits, RAGFlow parser behavior, and later query
strategy.

Impact:

- Users can pass dry-run while still choosing a profile that risks table fragmentation.
- Retrieval metrics can pass without proving strict table-row or cross-column recall.
- Table warnings are not yet tied tightly enough to profile and query recommendations.

#### Profile Choice Is Under-Evidenced

The 1024-vs-2048 comparison is useful evidence, but one document and six queries are not
enough to set defaults or claim a stable winner.

Impact:

- Average similarity can overstate small differences.
- Precision, context completeness, table recall, image coverage, and latency are not
  combined into one decision surface.
- Users may keep or change profiles based on anecdotal results.

#### Retrieval Validation Is Not Yet Multimodal Enough

Image chunks can improve coverage without ranking highly for text-heavy queries. Current
validation does not separately measure text, table, image, and mixed evidence.

Impact:

- Visual ingestion can look useless when only text queries are measured.
- Image improvements can hide text/table regressions.
- Query diagnostics cannot always say whether the failure is missing recall, wrong
  modality, table fragmentation, or retrieval pollution.

### 1.3 Operational And Performance Problems

#### Effective Runtime State Is Not Visible Enough

Users need to compare requested profiles with effective RAGFlow parser settings,
embedding model state, parse progress, and activation readiness.

Impact:

- Unknown embedding model or parser drift can be missed until retrieval behaves oddly.
- A parsed KB may be treated as production-ready before route, assistant, and benchmark
  readiness are checked.
- Build artifacts can become stale after server-side reparse or manual changes.

#### Large Corpus Workflows Need Batch And Resume Semantics

The representative run is small. Larger corpora need upload batching, checkpointing,
partial failure handling, and cleanup confidence.

Impact:

- Interrupted builds are hard to resume safely.
- Re-upload and duplicate document risks increase.
- Cleanup can become risky without exact state and confirmation.

#### Performance Costs Are Spread Across Multiple Tools

Conversion, postprocess, asset handling, RAGFlow upload, parse wait, image/VLM parse,
validation, query, and cleanup each contribute time and resource cost.

Impact:

- Users cannot easily see whether the bottleneck is MinerU, RAGFlow parse, image VLM,
  embedding, query, or polling.
- Profile comparisons can ignore latency and operational cost.
- Timeout and slow-path warnings are harder to interpret.

## Part 2: Solution Design

### 2.1 Design Goals

The improved suite should make formal handoff, build, validation, and query evidence flow
through one clear chain:

```text
ragflow-doc-to-md formal handoff
  -> asset/classification and build readiness
  -> gated Markdown plus optional visual-document ingestion
  -> multimodal KB manifest and read-only refresh
  -> parse/health/activation reports
  -> text/table/image benchmark validation and query diagnostics
```

The user-facing behavior should stay conservative:

- offline and read-only first;
- live mutation only after explicit execution flags and confirmation;
- fake-client tests before live approval;
- public docs and reports remain sanitized;
- LLM-backed generation remains outside this improvement plan.

### 2.2 Component Responsibilities

#### `ragflow-doc-to-md`

Owns source-to-handoff quality:

- Markdown generation and local asset materialization.
- Chunk marker and table/image boundary signals.
- Retrieval hints, assistant-test inputs, and ingest readiness.
- Artifact hashes and formal handoff completeness.

It should not create RAGFlow datasets or upload documents.

#### `ragflow-kb-build`

Owns ingestion and KB evidence:

- Markdown build dry-run and live build.
- Asset upload planning and optional gated visual-document ingestion.
- Multimodal KB manifest generation.
- Parse report, health report, activation plan, cleanup plan, and profile decisions.
- Read-only refresh against an existing dataset when credentials are supplied.

It should not mutate RAGFlow without explicit confirmation.

#### `ragflow-query`

Owns retrieval and user-facing evidence quality:

- Direct, routed, fusion, rewrite, and host-assisted query paths.
- Multimodal benchmark validation inputs and saved-query diagnostics.
- Table, image, route, and pollution failure classification.
- Assistant profile/test-plan review from build and handoff evidence.

It should not upload documents or edit assistant settings.

#### Shared Runtime

Owns reusable contracts and helpers:

- Versioned schemas for asset classification, multimodal manifests, profile decision
  reports, and performance telemetry.
- Redaction, partial-failure, runtime metrics, bounded polling, fake-client fixtures, and
  deterministic report rendering.

### 2.3 Data Contracts And Reports

The following report surfaces should be added or strengthened.

| Contract | Owner | Purpose | Default behavior |
| --- | --- | --- | --- |
| `ragflow_kb_asset_upload_plan_v2` | `ragflow-kb-build` | Classify Markdown, referenced images, manifest images, residual images, sidecars, and planned upload set | Offline only |
| `ragflow_kb_asset_ingestion_report_v1` | `ragflow-kb-build` | Record gated visual-document upload execution, parse states, partial failures, and cleanup needs | Mutating only with explicit confirmation |
| `ragflow_multimodal_kb_manifest_v1` | `ragflow-kb-build` / runtime | Link Markdown and visual documents to source handoff assets, hashes, document states, chunk counts, and observable thumbnails/VLM status | Generated after build or read-only refresh |
| `ragflow_profile_decision_report_v1` | `ragflow-kb-build` | Compare profile candidates with retrieval, strict recall, modality coverage, latency, chunk count, and confidence thresholds | Offline or read-only over existing validation artifacts |
| `ragflow_multimodal_benchmark_v1` | `ragflow-kb-build` / `ragflow-query` | Extend qrels and metrics with expected modality and expected chunks | Offline fixtures first |
| `ragflow_kb_refresh_report_v1` | `ragflow-kb-build` | Export current server-observed document and parse state without mutation | Read-only |
| `ragflow_query_diagnostic_v2` | `ragflow-query` | Diagnose text/table/image/pollution/route failure causes from saved query outputs | Offline over saved outputs |

### 2.4 Gated Image Ingestion Flow

The intended flow is:

1. Run `ragflow-doc-to-md pipeline` to produce a formal handoff.
2. Run `ragflow-kb-build inspect-handoff`.
3. Run `ragflow-kb-build asset-upload-plan` and review asset classes.
4. Run normal `ragflow-kb-build --dry-run` with the chosen profile.
5. If visual ingestion is needed, run a non-mutating image-ingestion readiness command.
6. Only after explicit approval, execute Markdown plus referenced-image upload.
7. Wait for parse, record multimodal manifest, and generate parse/health reports.
8. Run smoke or benchmark validation by modality.
9. Preview cleanup before any disposable KB is removed.

Default policy:

- upload only Markdown unless visual ingestion is explicitly requested;
- upload only `markdown_referenced` images unless broader classes are explicitly chosen;
- treat partial image failures as `REVIEW` or `FAILED`, never as silent success;
- preserve exact cleanup confirmation requirements.

### 2.5 Profile Decision Design

Profile decisions should use thresholds and categories rather than raw averages alone.

Inputs:

- validation report metrics;
- expected chunk recall;
- table strict recall;
- image or mixed-modality coverage;
- empty-result rate;
- query latency;
- parse chunk count;
- context completeness warnings;
- sample and query count.

Outputs:

- candidate ranking;
- winner only when minimum sample rules are satisfied;
- tie or insufficient-sample status when deltas are too small;
- explicit explanation of precision-vs-context tradeoffs;
- recommended next benchmark additions.

For the current APOLLO 1024-vs-2048 evidence, the expected classification is
`insufficient_sample_for_default_change`.

### 2.6 Multimodal Query And Diagnostic Design

Retrieval validation should distinguish evidence type:

- text fact;
- table value;
- visual identification;
- diagram or software screenshot;
- caption or nearby context;
- mixed table-plus-image evidence.

Query diagnostics should classify saved failures into actionable categories:

- no result;
- wrong modality;
- missing table fragment;
- missing image evidence;
- noisy keyword or BM25 pollution;
- route or KB mismatch;
- low similarity across candidates.

Each diagnosis should recommend an existing or planned next command, such as
`snapshot-chunks`, table strategy, image benchmark query, profile comparison,
route diagnose, or pollution report.

### 2.7 Performance Design

Performance telemetry should become comparable across the workflow:

- MinerU conversion, backend cold/warm context, and timeout classification;
- postprocess, package, hint generation, and asset plan timing;
- RAGFlow dataset create, document upload, image upload, parse trigger, parse wait, and
  cleanup timing;
- per-document and per-image throughput;
- parse polling status deltas;
- validation and query latency;
- optional host resource metrics with redaction.

Profile comparison should include performance cost, not only retrieval quality.

### 2.8 Error Handling And Safety

All new live-capable features must use the same safety model:

- a non-mutating plan or readiness report exists first;
- mutating commands require explicit execution flags and exact confirmation;
- partial failures are recorded with labels and counts;
- cleanup readiness is generated before live execution where possible;
- reports are JSON-first and Markdown summaries must not contain extra secrets;
- fake-client fixtures cover API drift, 401/403, unsupported image upload, parse timeout,
  partial upload, malformed document-list responses, and cleanup mismatch.

## Part 3: Development Task Checklist

### P0: Build The Multimodal Ingestion Foundation

- [x] Define `ragflow_kb_asset_upload_plan_v2` with explicit asset classes:
  `markdown_referenced`, `manifest_listed`, `sidecar_referenced`,
  `residual_unreferenced`, `outside_handoff`, and `missing`.
- [x] Update `asset-upload-plan` so the planned upload set is separate from all
  discovered local image artifacts.
- [x] Add APOLLO-style fixture coverage that classifies 15 referenced images separately
  from 6 residual hash-named images.
- [x] Add review warnings for residual images that are large, numerous, or likely
  duplicates of referenced images.
- [x] Define `ragflow_multimodal_kb_manifest_v1` for Markdown and visual document state.
- [x] Add fake read-only document-list fixtures covering Markdown docs, visual docs,
  thumbnails, chunk counts, parse states, and malformed response shapes.
- [x] Teach `parse-report` and `health-report` to consume multimodal manifest fields.
- [x] Define `ragflow_kb_asset_ingestion_report_v1` for gated visual-document upload
  execution.
- [x] Add a non-mutating image-ingestion readiness command that consumes
  `asset-upload-plan` and build profile evidence.
- [x] Add explicit live execution flags and confirmation checks for visual-document
  ingestion.
- [x] Implement fake-client visual upload, parse trigger, wait, partial failure, and
  cleanup-readiness tests.
- [ ] Run one user-approved disposable Markdown-plus-image live build only after fake
  coverage and cleanup readiness pass.

### P0: Strengthen Table And Profile Quality

- [x] Promote table-parent chunk preflight into a clear build-readiness status.
- [x] Estimate table token cost, row/column count, header complexity, and parent chunk
  boundary risk.
- [x] Warn when selected `chunk_token_num` is likely too small for a table parent chunk.
- [x] Record when dense chunk markers avoid inserting boundaries inside HTML tables.
- [x] Add table strict-recall benchmark fixtures for numeric rows, units, model names, and
  cross-column lookup.
- [x] Define `ragflow_profile_decision_report_v1`.
- [x] Combine retrieval metrics, expected-chunk recall, table recall, image recall,
  empty-result rate, latency, chunk count, and context warnings in the profile decision.
- [x] Add minimum sample/query thresholds before a profile report can recommend a default
  change.
- [x] Classify current APOLLO 1024-vs-2048 evidence as
  `insufficient_sample_for_default_change`.

### P1: Add Multimodal Validation And Query Diagnostics

- [x] Define multimodal benchmark categories: text fact, table value, visual
  identification, diagram/software screenshot, caption/context, and mixed table-plus-image.
- [x] Extend qrels to mark expected modality and expected chunks.
- [x] Record result modality distribution when document or chunk metadata is available.
- [x] Add image-specific precision/recall and visual coverage metrics.
- [ ] Let `ragflow-kb-build` consume `retrieval_hints.json` during dry-run readiness and
  profile recommendation.
- [ ] Let `ragflow-query` generate deterministic validation query suggestions from table
  and image hints without LLM calls.
- [ ] Add consistency checks between `retrieval_hints.json`, `asset-upload-plan`,
  `chunk_profile_report.json`, and `kb_manifest.json`.
- [x] Extend `diagnose-result` to classify no-result, wrong-modality, table-fragment,
  image-evidence, pollution, route mismatch, and low-similarity failures.
- [x] Map each diagnostic class to concrete next commands.

### P1: Improve Production Readiness And Refresh

- [ ] Capture requested profile and effective parser config when the API exposes them.
- [ ] Record embedding model or `unknown` with reason in build and health reports.
- [ ] Warn when embedding model drift implies rebuild or reparse risk.
- [ ] Connect model-provider probe evidence to health reports without requiring mutation.
- [ ] Make `activation-plan` a standard post-build recommendation.
- [ ] Generate assistant profile and assistant test plan review artifacts from build
  evidence as well as handoff sidecars.
- [ ] Add route-activation checks for KB name, route hints, benchmark smoke queries, and
  retrieval thresholds.
- [ ] Define `ragflow_kb_refresh_report_v1`.
- [ ] Add a read-only refresh command that exports current dataset document states and
  chunk counts.
- [ ] Let `parse-report`, `snapshot-chunks`, `health-report`, and benchmark validation
  share a common observed-state input.

### P2: Scale, Performance, And Adaptive Feedback

- [ ] Add optional batch sizing for Markdown build and asset ingestion.
- [ ] Record per-batch progress, uploaded document IDs, parse trigger status, and retryable
  failures.
- [ ] Support resume from a checkpoint after dataset creation, partial upload, parse
  trigger, or parse wait interruption.
- [ ] Ensure resume never re-uploads confirmed documents unless explicitly requested.
- [ ] Standardize stage timing across conversion, postprocess, packaging, asset planning,
  Markdown upload, image upload, parse wait, validation, query, and cleanup.
- [ ] Add per-document and per-image throughput metrics.
- [ ] Add warning thresholds for slow parse, slow image/VLM processing, high chunk count,
  and polling near timeout.
- [ ] Include latency and operational cost in profile comparison.
- [ ] Record which adaptive decisions led to successful or failed parse and retrieval
  outcomes.
- [ ] Add a no-network adaptive outcome summary comparing backend, table quality, chunk
  profile, asset policy, and build/query metrics.
- [ ] Maintain a sanitized sample-class matrix for scanned PDFs, extractable PDFs,
  image-heavy PDFs, long documents, complex tables, Office table documents, mixed-language
  documents, and low-quality OCR samples.

### Release And Governance Tasks

- [ ] Add schema identity checks for every new JSON contract.
- [ ] Add generated Markdown audit coverage for every new Markdown summary.
- [ ] Add redaction tests for paths, endpoints, tokens, dataset IDs, document IDs, raw
  chunks, and prompts.
- [ ] Add no-network CLI tests for every new planning or read-only command.
- [ ] Add fake-client tests before any live-capable command is considered usable.
- [ ] Update host-agent references after command names and report paths stabilize.
- [ ] Keep public `SKILL.md` files concise; put detailed workflow guidance in docs.
- [ ] Do not mark roadmap checkboxes complete until implementation and verification are
  done.

## Suggested Implementation Order

1. Asset classification cleanup in `asset-upload-plan`. Completed.
2. Multimodal manifest schema and fake read-only document-list fixtures. Completed.
3. Gated image asset ingestion readiness and fake execution path. Completed; live
   disposable execution remains gated.
4. Image-rich parse/health report consumption. Completed.
5. Profile decision report with stricter benchmark thresholds. Completed.
6. Multimodal benchmark categories and query diagnostics. Benchmark categories, qrels
   modality/chunk extensions, result modality distribution, and image/table coverage
   metrics plus `diagnose-result` class mapping are completed; deterministic query
   suggestions and consistency checks remain open.
7. Batch/resume and performance telemetry expansion for larger corpora. Not started.

This order keeps the first slice offline and fake-client-testable, then opens live
mutation only after the review surfaces and cleanup guarantees are ready.

## Performance Improvement Points

| Area | Improvement | Expected benefit | Verification |
| --- | --- | --- | --- |
| MinerU conversion | Better cold/warm timing and timeout classification | Fair comparison between persistent services and one-shot converters | Runtime report stage timing |
| Asset handling | Upload referenced images only by default | Less RAGFlow parse load and less visual noise | Asset plan counts and fake upload set |
| Image parsing | Per-image parse/VLM timing and failure status | Easier diagnosis of slow or failed visual chunks | Multimodal manifest refresh |
| KB build | Batch upload with checkpoint/resume | More reliable large-corpus builds | Fake interruption/resume tests |
| Parse wait | Bounded polling with status deltas | Less unclear waiting and better timeout messages | Runtime partial failure report |
| Profile comparison | Include latency, chunk count, and strict recall | Avoid choosing profiles only by similarity | Profile decision report |
| Query validation | Categorized benchmarks by modality | Better signal on text/table/image value | Benchmark metrics by category |
| Cleanup | Cleanup readiness before live execution | Lower leftover KB risk | Cleanup plan and read-back verification |

## Non-Goals

- Do not improve public report wording or formatting as the primary task here.
- Do not add `ragflow-query serve` unless the existing observation trigger is met.
- Do not add provider, reranker, remote-conversion, or script-owned LLM backends from this
  APOLLO evidence alone.
- Do not mutate real RAGFlow datasets from tests or default commands.
- Do not repair retired RAGFlux or `ragflow-kb-ops` code; use them only as comparison
  evidence.
