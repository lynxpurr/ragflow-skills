# High-Value Feature Roadmap

Status: active roadmap for v0.2+
Date: 2026-06-23

## Objective

Extend the public RAGFlow skill suite with the strongest reusable ideas from the earlier
RAGFlux, RAGFlow KB Ops, smart-query, and agentic-rag systems while preserving the public
suite's current release standards:

- keep three public skills with clear ownership;
- keep release artifacts self-contained and portable;
- keep private workflows, private datasets, and personal infrastructure out of public artifacts;
- prefer deterministic local checks before optional LLM-assisted or live-service features;
- expose advanced quality engineering through small, discoverable subcommands instead of script sprawl.

The target users remain controllable programming-agent CLI environments such as Hermes,
OpenClaw, Claude Code, opencode, and similar runners.

## Current Baseline

The v0.1 public suite already provides:

- `ragflow-doc-to-md`: Markdown passthrough, builtin text/HTML conversion, remote conversion,
  MinerU Agent API backend, MinerU sync multipart backend, and `doc_manifest.json`.
- `ragflow-kb-build`: Markdown discovery, RAGFlow dataset creation, document upload, parse
  trigger and polling, `kb_manifest.json`, inspect, and lightweight validation.
- `ragflow-query`: direct retrieval, dataset resolution by ID/name/manifest, normalized chunk
  output, and host-assisted agentic evidence mode.
- release tooling: vendored runtime, consumer acceptance, platform smoke matrix, release hygiene,
  export archives, and artifact-level security checks.

The missing high-value areas are not basic connectivity. They are quality gates, long-document
handling, RAGFlow operational diagnostics, benchmark-grade validation, routing quality, and
agentic observability.

## Source Feature Inventory

The earlier systems contain several valuable ideas that are worth migrating in neutral form:

| Source system | Reusable capability | Public-suite destination |
| --- | --- | --- |
| RAGFlux | document quality reports and gate status | `ragflow-doc-to-md inspect` |
| RAGFlux | large package segmentation and materialized segments | `ragflow-doc-to-md segment` |
| RAGFlux | richer handoff package with hashes, artifacts, and downstream hints | optional package mode |
| RAGFlow KB Ops | RAGFlow API pitfall handling and diagnostics | `ragflow-kb-build probe/diagnose` |
| RAGFlow KB Ops | append/rebuild safety for large KBs | `ragflow-kb-build append/rebuild` |
| RAGFlow KB Ops | qrels metrics, benchmark gates, trend/delta reports | `ragflow-kb-build validate --level benchmark` |
| RAGFlow KB Ops | chunk profile linting, comparison, and optimization | `ragflow-kb-build profile ...` |
| RAGFlow KB Ops | metadata enrichment and tagset governance | optional metadata/tagset commands |
| smart-query | routing hints, route regression, route A/B methodology | `ragflow-query route` and `--mode auto` |
| agentic-rag | planning, reflection, citation audit, cost and trace logs | optional agentic query layer |

Do not migrate private KB names, private corpora, personal paths, private service assumptions,
dedao-specific flows, direct MySQL/ES repair scripts, or long-running daemons as required defaults.

## Design Principles

### Keep Skill Boundaries Stable

`ragflow-doc-to-md` owns source-to-Markdown quality and package structure.

`ragflow-kb-build` owns RAGFlow ingestion, RAGFlow operational checks, profile behavior, and
retrieval validation against built KBs.

`ragflow-query` owns retrieval, route selection, host-assisted evidence, and optional agentic
answer support.

Shared implementation should live in `ragflow-skill-runtime`, then be vendored into every
release artifact.

### Keep Advanced Features Optional

Every new feature should have a no-network or dry-run path when possible. LLM-assisted features,
live RAGFlow operations, and live MinerU conversion must stay opt-in and must not require secrets
in skill folders.

### Prefer Small Public Schemas

Use lightweight versioned payloads rather than heavy schema systems:

- `doc_quality_report_v1`
- `doc_segmentation_plan_v1`
- `ragflow_kb_diagnostic_report_v1`
- `ragflow_benchmark_report_v1`
- `ragflow_routing_config_v1`
- `ragflow_query_trace_v1`

Validate required fields with dataclasses and clear error messages.

### Keep Private Operations Private

Direct database repair, direct ES backfill, private KB migration, personal benchmark corpora, and
provider-specific local operations should remain outside public release artifacts. Public tools may
diagnose and report recommended actions, but should not perform high-risk private repair by default.

## Feature Designs

### 1. Document Quality Gate

Add an `inspect` command to `ragflow-doc-to-md`.

Expected outputs:

- `quality_report.json`
- optional `quality_report.md`
- gate status in `doc_manifest.json`

Checks:

- Markdown file exists and is non-empty.
- Markdown has enough text relative to source size when source size is known.
- Local image references exist.
- Conversion warnings are summarized by severity.
- OCR/manual-review warnings can mark `PASS_WITH_REVIEW`.
- Blocking conversion errors mark `BLOCKED`.

Gate statuses:

- `PASS`: safe to ingest.
- `PASS_WITH_REVIEW`: ingestable, but host agent should tell the user review is recommended.
- `BLOCKED`: do not run `ragflow-kb-build` unless `--allow-blocked` is explicitly passed.

Public value:

- Agents can stop bad parses before polluting a KB.
- Live E2E can distinguish conversion quality failures from RAGFlow failures.

### 2. Long Document Segmentation

Add segmentation support to `ragflow-doc-to-md`.

Commands:

- `segment-plan`: inspect a Markdown file or handoff and create a non-mutating plan.
- `split`: materialize `segments/*.md` and update the handoff manifest.

Strategy:

- Prefer heading boundaries.
- Respect explicit `<!-- chunk -->` markers.
- Track line ranges, char counts, image counts, and segment titles.
- Avoid segmenting below a minimum useful size.

Suggested defaults:

- soft max: 24,000 characters.
- hard max: 32,000 characters.
- minimum segment size: 4,000 characters.

Public value:

- Prevents very large documents from causing parse timeouts or poor retrieval granularity.
- Lets users inspect segmentation before ingestion.

### 3. Rich Handoff Package Mode

Keep the current `doc_manifest.json` as the default. Add an optional package mode for users who
want stronger auditability.

Package contents:

- `documents/*.md`
- `artifacts/` for extracted tables or images when a backend produces them.
- `doc_manifest.json`
- `quality_report.json`
- `segmentation_plan.json` when applicable.
- `profile_suggestions.json` when profile recommendation is enabled.

The package should remain consumable by `ragflow-kb-build` without teaching kb-build private
RAGFlux package details. The contract is still the public manifest plus optional public sidecars.

### 4. RAGFlow Capability Probe and Diagnostics

Add `ragflow-kb-build probe` and `ragflow-kb-build diagnose`.

Probe checks:

- Base URL and auth are reachable.
- Dataset list endpoint works with pagination.
- Dataset IDs are full-length and stable.
- Upload response shape is recognized.
- Parse trigger endpoint is supported.
- Document list with page/page_size returns parse and chunk fields.
- Delete endpoint support can be tested only in dry-run or disposable mode.

Diagnose checks:

- Documents stuck in `UNSTART`, `RUNNING`, or failed states.
- `code=0` parse trigger with no created task symptoms.
- Duplicate dataset names and `(1)` suffix fragments.
- Zero `chunk_count` with parsed documents.
- Missing or short dataset IDs in manifests.

Outputs:

- `ragflow_kb_diagnostic_report.json`
- optional Markdown report for host agents.

Public value:

- Turns old RAGFlow operational pitfall knowledge into a safe public diagnostic surface.
- Gives host agents concrete next steps without asking users to know RAGFlow internals.

### 5. Safe Append and Rebuild

Extend `ragflow-kb-build` beyond one-shot build.

Commands:

- `append`: add new Markdown documents to an existing KB.
- `rebuild`: create a replacement disposable KB from a document set.
- `cleanup`: delete or mark disposable KBs when explicitly confirmed.

Safety rules:

- Resolve existing KB by exact name or explicit dataset ID.
- Never use truncated dataset IDs.
- Snapshot existing document IDs before upload.
- Parse only newly uploaded document IDs by default.
- Require confirmation for deletion.
- Emit progress JSON during upload and parse wait.

Public value:

- Supports realistic KB maintenance without re-parsing everything.
- Avoids the old large-batch timeout failure mode.

### 6. Benchmark-Grade Validation

Expand `ragflow-kb-build validate`.

Levels:

- `smoke`: current lightweight check.
- `regression`: user query set with expected terms/documents.
- `benchmark`: qrels-based ranking metrics and gate thresholds.

Metrics:

- hit rate
- MRR
- precision@k
- recall@k
- nDCG@k
- MAP@k
- empty result rate
- supporting document coverage for multi-hop cases
- query type breakdown

Inputs:

- `queries.json`
- `qrels.json`
- optional document metadata
- optional gate config

Outputs:

- `validation_report.json`
- `validation_report.md`
- optional `validation_delta.json` when comparing to a baseline.

Public value:

- Makes retrieval quality measurable and repeatable.
- Lets users test profile changes before accepting a KB build.

### 7. Profile Lint, Recommend, and Compare

Add profile subcommands to `ragflow-kb-build`.

Commands:

- `profile lint`
- `profile explain`
- `profile recommend`
- `profile compare`

Rule-based recommendations:

- language: Chinese vs English.
- document type: book, manual, paper, notes, mixed.
- chunk size and overlap range.
- `auto_keywords` and `auto_questions` defaults.
- unsupported parser keys.
- `__language__` metadata handling.

Avoid default LLM use in v0.2. LLM-assisted profile planning can be added later as an explicit
optional mode.

Public value:

- Captures old profile hardening knowledge while remaining deterministic and easy to test.

### 8. Metadata and Tagset Governance

Add optional metadata support after profile and benchmark foundations are stable.

Capabilities:

- `metadata lint`
- `metadata merge`
- `metadata generate` when an LLM config is explicitly provided.
- `tagset lint`
- `tagset report`

Safe field set:

- domain
- topic
- module
- doc_type
- audience
- question_types
- entities
- summary
- locale
- status

Public value:

- Helps users build KBs that support filtered retrieval and better evaluation.
- Keeps AI-generated metadata reviewable instead of silently mutating documents.

### 9. Neutral Auto Routing

Make `ragflow-query --mode auto` real without shipping private route tables.

Add a user-owned routing config:

```json
{
  "version": "0.1",
  "knowledge_bases": [
    {
      "name": "kb:example",
      "dataset_id": "dataset-id",
      "description": "Example KB",
      "hints": ["example", "sample topic"],
      "params": {
        "top_k": 5,
        "similarity_threshold": 0.1
      }
    }
  ]
}
```

Commands:

- `ragflow-query list-kbs`
- `ragflow-query route "question"`
- `ragflow-query route-test --queries routes.json`
- `ragflow-query ask --mode auto`

Routing stages:

1. exact or regex hints;
2. optional keyword scoring;
3. optional centroid scoring when user provides centroids;
4. fallback to user-selected default KBs or a clear error.

Public value:

- Preserves smart-query's major quality win without leaking private KB names or hints.

### 10. Agentic Observability and Optional Synthesis

Keep host-assisted mode as the default public agentic path. Add optional observability first.

Near-term additions:

- evidence weighting
- structured query trace JSON
- citation audit for host-generated answers
- retrieval cost/time metadata

Later optional additions:

- planner mode
- reflection mode
- script-owned synthesis with configured LLM provider

Do not require an LLM key for normal retrieval.

Public value:

- Host agents get better evidence and debugging without forcing a specific LLM stack.
- Optional synthesis can mature without destabilizing direct retrieval.

## Cross-Cutting Contracts

### Report Files

Every non-trivial command should support JSON output and optional report files:

- `--json` for stdout.
- `--report-json PATH`
- `--report-md PATH`

Reports must redact secrets and must not include raw API keys, key fragments, or local private
config paths.

### Dry-Run and Live Modes

Commands that mutate RAGFlow must provide a dry-run or preview mode when practical.

Deletion, cleanup, and rebuild operations must require explicit confirmation flags.

### Release Hygiene

Every new feature must pass:

- unit tests;
- `tools/build_release.py --check`;
- `tools/release_hygiene_check.py`;
- artifact unpack security scan;
- consumer acceptance;
- platform smoke matrix when command surfaces change.

### Backward Compatibility

The current v0.1 command surfaces should remain valid:

- existing `doc_manifest.json` stays consumable;
- existing `kb_manifest.json` stays consumable;
- `ragflow-query ask --mode direct|agentic --host-assisted` keeps its current behavior.

Add new fields as optional fields, not required fields, until a new manifest major version is
explicitly planned.

## Non-Goals

These should not be added to the public suite:

- dedao download or bookshelf automation;
- private KB route hints or private datasets;
- personal service paths, personal auth files, or fixed internal hosts;
- required background daemons;
- direct MySQL repair or ES backfill as default public commands;
- Fleet control-plane integration;
- commercial SaaS sandbox support as a v0.2 target.

## Phased Development Plan

### Phase 13: Document Quality and Segmentation

Goal: make `ragflow-doc-to-md` produce auditable handoffs that can block bad parses.

Tasks:

- [x] Add quality report dataclasses to `ragflow_skill_runtime`.
- [x] Add Markdown existence, emptiness, image-reference, and warning-severity checks.
- [x] Add `ragflow-doc-to-md inspect`.
- [x] Add optional `quality_report.json` to convert output.
- [x] Add gate status to `doc_manifest.json` as an optional field.
- [x] Add `--allow-blocked` guard in `ragflow-kb-build`.
- [x] Add segmentation plan dataclasses.
- [x] Add `segment-plan` command.
- [x] Add `split` command that materializes `segments/*.md`.
- [x] Add consumer acceptance coverage for quality reports and segmentation commands.
- [ ] Add optional manifest rewrite/package mode for split outputs.

Exit criteria:

- A bad or empty Markdown conversion is blocked before live RAGFlow upload.
- A long Markdown document can be segmented and then ingested through the existing kb-build path by pointing `ragflow-kb-build --input` at the segment directory.

Implementation note:

- The current MVP keeps segmentation manifest rewriting deferred. This avoids surprising mutation of an existing handoff while still allowing safe ingestion of `segments/*.md`.

### Phase 14: RAGFlow Diagnostics and Safe Maintenance

Goal: turn old RAGFlow operational pitfalls into safe public diagnostics.

Tasks:

- [ ] Add client helpers for dataset detail, dataset deletion, document deletion, and paginated document lists.
- [ ] Add `ragflow-kb-build probe`.
- [ ] Add `ragflow-kb-build diagnose`.
- [ ] Add duplicate-name and suffix-fragment detection.
- [ ] Add short-ID validation for manifests and CLI inputs.
- [ ] Add stuck parse and zero chunk diagnostics.
- [ ] Add `append` with upload-before/after diff.
- [ ] Add parse-only-new-documents default behavior.
- [ ] Add cleanup preview and explicit-confirm cleanup mode.
- [ ] Add live disposable tests for probe/append/cleanup where credentials are present.

Exit criteria:

- Host agents can explain common RAGFlow ingestion failures without private DB access.
- Users can append documents safely without full KB rebuilds.

### Phase 15: Benchmark Validation

Goal: promote validation from smoke checks to measurable retrieval quality gates.

Tasks:

- [ ] Port qrels metric primitives into `ragflow_skill_runtime/validation.py` or a new metrics module.
- [ ] Define public `queries.json` and `qrels.json` examples.
- [ ] Add `validate --level benchmark`.
- [ ] Add gate config support.
- [ ] Add Markdown and JSON benchmark reports.
- [ ] Add baseline comparison support.
- [ ] Add query type breakdown.
- [ ] Add public sanitized sample benchmark fixtures.
- [ ] Keep benchmark data small enough for release artifacts or ship larger examples only as source docs.

Exit criteria:

- A user can run a public benchmark gate and see ranking metrics, failures, and recommended next checks.

### Phase 16: Profile Engineering

Goal: make chunk profile selection explicit, explainable, and testable.

Tasks:

- [ ] Add profile subcommand entrypoint under `ragflow-kb-build`.
- [ ] Implement `profile lint`.
- [ ] Implement `profile explain`.
- [ ] Implement rule-based `profile recommend`.
- [ ] Implement `profile compare` using validation reports.
- [ ] Add warnings for unsupported or high-risk parser_config keys.
- [ ] Add language-specific guidance using `parser_config.__language__` while filtering API payloads.
- [ ] Add docs and tests for common Chinese/English book/manual profiles.

Exit criteria:

- Users can choose or review profiles before upload instead of accepting hidden defaults.

### Phase 17: Neutral Routing

Goal: make `ragflow-query --mode auto` useful without private route tables.

Tasks:

- [ ] Define `ragflow_routing_config_v1`.
- [ ] Add config loading for user-owned route hints.
- [ ] Add `ragflow-query list-kbs`.
- [ ] Add `ragflow-query route`.
- [ ] Add `ragflow-query route-test`.
- [ ] Wire `ask --mode auto` to the route resolver.
- [ ] Add deterministic route regression fixtures.
- [ ] Add optional centroid fields without requiring centroid computation.

Exit criteria:

- A user can maintain their own routing hints and run auto retrieval with measurable route accuracy.

### Phase 18: Agentic Observability

Goal: improve agentic evidence quality without making LLM synthesis mandatory.

Tasks:

- [ ] Add evidence weighting to normalized query results.
- [ ] Add optional query trace JSON output.
- [ ] Add timing and retrieval parameter metadata.
- [ ] Add citation-audit input format for host-generated answers.
- [ ] Add `ragflow-query audit-citations`.
- [ ] Add optional LLM provider config only after audit and tracing are stable.
- [ ] Add script-owned planner/synthesis as an experimental opt-in mode.

Exit criteria:

- Host agents can explain why evidence was selected, audit citations, and debug weak retrievals.

## Recommended Implementation Order

1. Phase 13 quality gate and segmentation.
2. Phase 14 RAGFlow diagnostics and append.
3. Phase 15 benchmark validation.
4. Phase 16 profile engineering.
5. Phase 17 neutral routing.
6. Phase 18 agentic observability and optional synthesis.

This order starts with deterministic, low-secret, high-safety features before adding routing and
LLM-dependent behavior.

## Open Questions

- Should rich handoff package mode remain under `ragflow-doc-to-md`, or should it be a shared
  runtime helper used by both doc conversion and kb-build?
- Should benchmark fixtures ship inside release artifacts, or should artifacts contain only the
  runner and minimal examples?
- Should `append` and `cleanup` be in `build.py`, or should `ragflow-kb-build` gain a unified CLI
  wrapper with subcommands?
- Should route hints support regex in v0.2, or begin with exact/substring hints for easier safety?
- Should optional LLM synthesis live in `ragflow-query` or remain host-agent assisted until v0.3?
