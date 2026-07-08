# KB Build Strict Regression Quality Plan

Status: proposed spec-coding backlog
Date: 2026-07-08

> For agentic workers: implement this plan task-by-task with
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
> Keep checklist items unchecked until the implementation and verification evidence both
> exist.

## Objective / Scope / Boundaries

This document turns the strict R2 regression evidence for `ragflow-kb-build optimize`
into the next quality-improvement backlog. The goal is to make optimization decisions
more trustworthy for table-heavy documents by fixing retrieval evidence metrics, wiring
existing readiness signals into scoring, and closing the final cleanup evidence chain.

The scope is limited to `ragflow-kb-build`, shared `ragflow-skill-runtime` validation and
optimization logic, profile templates, focused tests, and public guidance. It builds on
`docs/28-retrieval-optimization-quality-improvement-plan.md` instead of reopening the
completed R1/R2 quality round.

Boundaries:

- no live RAGFlow mutation by default;
- no script-owned LLM or RAGAS execution;
- no private run roots, private endpoints, raw identifiers, raw chunks, prompts, or
  credentials in public docs;
- no default profile promotion from a single-document benchmark;
- no report-format cleanup unless it affects machine-readable evidence or user safety.

## Problem Description

### R2 Passed The Workflow But Not The Decision Evidence

The strict R2 regression proved that the optimize lifecycle can run end to end: candidate
profiles are generated, disposable builds run, validation reports are produced, cleanup
plans are generated, cleanup execution completes, and a read-back check can confirm no
disposable KBs remain.

The same run did not justify promoting a new default profile. The benchmark was stronger
than the R1 document-level check, but the final decision remained
`insufficient_evidence`, with all six candidates treated as co-winners. That is the right
conservative outcome, but the evidence chain still contains defects that prevent the
skill from learning useful table-retrieval distinctions.

Sanitized R2 evidence:

- `benchmark_strength.status` was `exploratory`.
- `qrel_strength_score` improved to `0.75`.
- `expected_term_coverage` and `expected_chunk_coverage` were both `1.0`.
- The remaining benchmark-strength issue was `single_target_document`.
- `decision.status` was `insufficient_evidence`.
- `co_winner_count` was `6`.
- `strict_chunk_recall_at_k` was `0.045` across all profiles.
- `expected_chunk_hit_rate` was `0.091` across all profiles.
- Seven table-scoped queries produced `table_recall_at_k=0.0`.

### Table Chunks Are Misclassified Before Strict Recall Is Considered

The current validation modality heuristic checks explicit metadata first, then file
extension, and only then table markup. For Markdown sources, a chunk from a `.md` document
is classified as `text` before the code checks whether the content contains `<table>`.

Impact:

- Markdown table chunks can appear in top-k retrieval results while
  `table_result_count` remains zero.
- `table_recall_at_k` can report zero even when retrieved chunks visibly contain table
  content.
- Any later table-specific decision penalty or promotion logic starts from a distorted
  metric.

This is a P0 correctness bug. It is separate from the stable-hash limitation below.

### Stable-Hash Strict Recall Is Too Brittle Across Chunk Sizes

Strict chunk recall currently relies on exact stable-hash matches between expected
chunks and retrieved chunks. That is useful for detecting exact evidence reuse, but it is
not a robust cross-profile metric when the profile matrix varies chunk size. Different
chunk boundaries produce different chunk content and therefore different hashes, even
when the retrieved content contains the right values.

Impact:

- A reference snapshot built with one chunk size cannot fairly score candidates using
  smaller or larger chunk sizes.
- `strict_chunk_recall_at_k` can collapse to the same low value for every candidate.
- Table benchmark evidence becomes unable to distinguish "wrong table evidence" from
  "right table evidence split across different boundaries."

The exact-hash metric should stay, but table-heavy benchmarks need semantic fallback
metrics based on expected terms.

### Optimize Ignores Table Atomicity Readiness Evidence

Dry-run readiness can already flag table-parent chunk risk. In R2, the selected baseline
profile had a table whose estimated parent chunk size exceeded the selected profile's
chunk capacity, yet optimize scoring still ranked the smallest chunk profile first
because the benchmark metrics were saturated.

Impact:

- The decision layer can recommend a profile that fragments known large tables.
- Users see a table risk in dry-run but not in the final optimize decision rationale.
- Profile scoring does not yet use the strongest deterministic evidence available from
  the handoff and readiness reports.

### Cleanup Closure Exists But Can Be Lost From The Final Summary

`optimize summarize` can consume cleanup-plan, readiness, and cleanup-execution artifacts
when those paths are passed. R2 produced those artifacts, but the first final summary did
not include them because the summarize command was run before those paths were supplied.

Impact:

- A completed cleanup can be reported as `not_required` or `missing` in the summary if
  the user does not rerun summarize with the lifecycle artifacts.
- Field-trial records and host-agent handoffs can miss the true closeout state.
- Read-back verification can remain outside the machine-readable report.

### Embedding Model Checks Work But Templates Do Not Make Them Easy

The embedding-model check works when a profile explicitly declares an embedding model and
the user provides an expected model. The generic default templates do not include that
field, so the check reports `not_configured` for the most common starting point.

Impact:

- Users can believe embedding-model drift is being checked when the profile has no
  comparable value.
- Adding a hard-coded model to generic public defaults could reduce portability.
- The next round needs a deliberate template strategy rather than an accidental default.

### Strict Validation Status Needs A Clearer Gate Contract

R2 candidate validation artifacts had `ok=false`, but the `gate` field in the inspected
reports was unset. The benchmark did become stricter, but the report surface does not
cleanly distinguish a configured threshold-gate failure from a case-level validation
failure.

Impact:

- Human reports can say "strict gate failed" while machine output does not identify the
  gate that failed.
- Future automation cannot reliably tell whether to relax a gate, improve qrels, or fix
  retrieved evidence.

## Update Plan

### Phase A: Fix Metric Correctness

First make table evidence observable. Move the table-content heuristic before the
Markdown text fallback, then add semantic expected-term metrics that operate on the
joined top-k evidence for each query.

The new metrics should preserve existing exact-hash fields and add separate semantic
fields, for example:

- `expected_term_recall_at_k`;
- `expected_term_hit_rate`;
- `expected_term_count`;
- `matched_expected_terms`;
- `table_term_recall_at_k` for queries whose expected modality includes table;
- `table_term_hit_rate`.

These fields should appear per query, in aggregate benchmark metrics, and in generated
Markdown. Exact chunk recall remains exact; expected-term metrics explain whether the
evidence content is present despite chunk-boundary changes.

### Phase B: Make Table Atomicity Part Of Optimization Scoring

Feed `table_parent_chunk_preflight` into optimize plan and summarize outputs when a
profile can be checked against retrieval hints. Add a decision-score component or penalty
that records table fragmentation risk without silently overriding retrieval quality.

The decision should be conservative:

- no table penalty when no table hints or preflight evidence exist;
- explicit `unknown` status when table evidence was not available;
- penalty or risk warning when selected profile capacity is below estimated parent-table
  size;
- rationale that explains whether the winner was chosen despite table risk, demoted
  because of table risk, or kept as a co-winner pending better evidence.

### Phase C: Close The Summary And Cleanup Evidence Chain

Make the final optimize summary harder to run incorrectly. Either auto-discover sibling
cleanup artifacts next to the plan, or emit an explicit post-cleanup summarize command in
the next-step block and command manifest. Add a machine-readable read-back verification
artifact or field so cleanup closure does not rely on a separate shell transcript.

The summary should represent these states accurately:

- cleanup not required;
- cleanup required but no cleanup plan yet;
- cleanup planned but not executed;
- cleanup executed but not read-back verified;
- cleanup executed and read-back verified.

### Phase D: Clarify Embedding-Model Template Strategy

Prefer portable generic templates plus explicit model-specific variants. Keep
`default-zh-512.json` and `default-en-768.json` generic unless release governance accepts
an opinionated public default, and add a clearly named model-specific template or example
for common `bge-m3` deployments.

Dry-run and lint should make the status obvious:

- generic template with no model: `not_configured`, with a clear recommendation;
- model-specific template: match or mismatch when expected model input is supplied;
- mismatch: explicit rebuild or reparse warning.

### Phase E: Rerun Strict R3 Before Any Default Promotion

After metric and decision changes, rerun the strict regression with the same shape as R2
but with the new table metrics and cleanup-summary closeout. R3 should be considered a
quality run, not a promotion run, unless it adds multi-document or negative-case evidence.

Minimum R3 acceptance:

- Markdown table chunks are counted as table results when content contains table markup.
- Table-scoped queries produce non-zero table evidence metrics when expected terms are in
  top-k results.
- Exact strict recall remains visible and is not replaced by semantic fallback.
- The decision remains conservative if the benchmark is still single-document only.
- Table-parent chunk risk appears in score components or recommendation rationale.
- Cleanup lifecycle in final summary matches the actual cleanup artifacts.
- No private run roots, endpoints, identifiers, or credentials leak into public docs or
  generated Markdown.

## Spec Coding File Map

Likely files to modify:

- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/validation.py`:
  modality detection, per-query expected-term metrics, aggregate benchmark metrics, gate
  fields, and Markdown rendering.
- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/optimization.py`:
  decision-score consumption of table evidence, table atomicity risk, cleanup lifecycle
  summarize behavior, and field-trial suggestion fields.
- `skills/ragflow-kb-build/scripts/build.py`:
  CLI plumbing for summarize sidecar discovery, cleanup verification, readiness-derived
  confirmations, and execute-result metric inlining.
- `skills/ragflow-kb-build/templates/*.json`:
  embedding-model template strategy.
- `packages/ragflow-skill-runtime/tests/test_validation.py`:
  focused benchmark metric tests.
- `packages/ragflow-skill-runtime/tests/test_optimization.py`:
  decision-score and cleanup lifecycle unit tests.
- `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`:
  CLI behavior, generated JSON/Markdown, redaction, and sidecar-discovery tests.
- `packages/ragflow-skill-runtime/tests/test_profiles.py`:
  profile/template lint behavior if template schema or examples change.
- `skills/ragflow-kb-build/SKILL.md` and related examples:
  concise public guidance after behavior changes.

## Task Checklist

### P0: Table Metric Correctness

- [x] Add a failing validation test showing that a Markdown chunk containing table markup
  is classified as `table`, not `text`.
- [x] Move the table-content heuristic ahead of the Markdown text fallback in
  `validation.py`.
- [x] Add a benchmark fixture where the expected chunk hash does not match but the top-k
  chunks contain all expected terms.
- [x] Add per-query `expected_term_recall_at_k` and `expected_term_hit_rate` metrics.
- [x] Add aggregate expected-term benchmark metrics and include counts for total and
  matched expected terms.
- [x] Add `table_term_recall_at_k` and `table_term_hit_rate` for table-expected queries.
- [x] Preserve `strict_chunk_recall_at_k` as exact-hash evidence and document that it is
  intentionally stricter than semantic term evidence.
- [x] Render the new metrics in benchmark Markdown without removing existing strict
  fields.
- [x] Add focused tests for text-only, table, mixed, and missing-term cases.

### P0: Optimize Decision Evidence

- [x] Add a fixture plan or candidate artifact that carries
  `table_parent_chunk_preflight` into optimize summarization.
- [x] Add a table atomicity decision component with `available`, `unknown`, `pass`, and
  `risk` states.
- [x] Penalize or warn on profiles whose selected chunk capacity is below estimated
  parent-table size.
- [x] Surface table atomicity status in `decision_score.components`.
- [x] Add Markdown rationale for table risk and semantic table evidence.
- [x] Add tests where a smaller profile wins saturated IR metrics but is demoted or kept
  as a co-winner because table atomicity evidence is risky.

### P0/P1: Cleanup Lifecycle Closure

- [x] Add a test that runs summarize after cleanup artifacts exist without manually
  passing every sidecar path, if sidecar auto-discovery is selected.
- [x] Select sidecar auto-discovery instead of the generated next-step-only fallback for
  cleanup-plan, readiness, and cleanup-execution paths.
- [x] Add a machine-readable post-cleanup read-back verification report or field.
- [x] Ensure final summary distinguishes executed-unverified cleanup from verified
  cleanup.
- [x] Update generated Markdown so cleanup lifecycle reflects the same machine-readable
  state.
- [x] Add release-safety tests that generated cleanup summaries do not expose private
  identifiers in Markdown.

### P1: Benchmark Strength And Gate Semantics

- [ ] Add a follow-up message when the only benchmark-strength issue is
  `single_target_document`, explaining that multi-document or negative cases are the
  next promotion requirement.
- [ ] Add optional gate thresholds for expected-term and table-term recall if the report
  surface change is accepted.
- [ ] Make validation output distinguish configured gate threshold failures from
  case-level failures.
- [ ] Add tests for unset gate, passing gate, failing strict-chunk gate, and failing
  expected-term gate.
- [ ] Keep single-document strict benchmarks `exploratory` by default.

### P1: Candidate-Specific Strict Evidence

- [ ] Design a candidate-specific evidence mapping path from expected terms to each
  candidate snapshot.
- [ ] Add a no-network fixture with the same source document split into different chunk
  boundaries.
- [ ] Report candidate-specific expected chunk matches separately from reference-snapshot
  exact matches.
- [ ] Update optimize summaries so strict evidence can explain both exact matches and
  candidate-local semantic matches.
- [ ] Keep this path advisory until at least one strict regression run proves it improves
  discrimination.

### P2: Embedding Template Strategy

- [ ] Decide whether generic templates stay model-neutral or become opinionated defaults.
- [ ] If model-neutral templates remain, add explicit model-specific template variants or
  examples.
- [ ] Update profile lint or dry-run guidance so missing `embedding_model` is visible but
  not confused with mismatch.
- [ ] Add tests for not-configured, match, mismatch, and model-specific template paths.
- [ ] Update public skill guidance with the recommended template choice.

### P2: Operator Ergonomics

- [ ] Inline candidate benchmark metrics in optimize execute results while keeping the
  full validation report path.
- [ ] Add a safe readiness-derived cleanup confirmation mode if it can preserve explicit
  user review.
- [ ] Add tests that the convenience mode refuses to run without `--execute` and without
  a valid readiness artifact.
- [ ] Track doc-to-md backend override failures only if they reproduce in a focused
  rerun; keep them outside this KB-build quality round unless they affect handoff
  contracts.

## Current Development Progress

Completed before this plan:

- Alias-aware profile identity and effective-profile deduplication.
- Benchmark-strength scoring and conservative optimize decisions.
- Co-winner and cost-review semantics.
- Runtime sidecar consumption for parse, refresh, snapshot, and health evidence.
- Cleanup lifecycle fields in optimize summary when artifacts are supplied.
- Embedding-model drift checks when profiles provide an embedding model.
- Strict R2 regression showing the workflow closes but profile promotion is still
  unsupported.

Completed in the current implementation slice:

- Markdown chunks containing table markup are classified as `table` before the Markdown
  text fallback.
- Benchmark reports emit expected-term semantic metrics per query and in aggregate while
  preserving exact strict-chunk metrics.
- Table-expected queries emit table-term semantic metrics, and generated Markdown reports
  show both exact strict evidence and semantic term evidence.
- Focused tests cover text-only, table, mixed, and missing-term expected-term cases.
- Optimize plans carry candidate-specific `table_parent_chunk_preflight` evidence when a
  rich handoff can be checked against candidate profiles.
- Optimize summaries include a table atomicity decision-score component and conservatively
  penalize risky profiles whose selected chunk capacity is below estimated parent-table
  size.
- Best-profile Markdown rationale now surfaces table atomicity risk and semantic table
  evidence alongside retrieval metrics.
- Optimize summaries auto-discover sibling cleanup lifecycle sidecars named
  `cleanup_plan.json`, `optimization_live_readiness_report.json`, and
  `cleanup_execution_report.json` when explicit paths are not supplied.
- Cleanup lifecycle summaries now expose machine-readable post-cleanup read-back status
  fields and distinguish `cleanup_executed_unverified` from verified `complete` cleanup
  in both JSON and generated Markdown.
- Focused CLI coverage verifies that generated cleanup lifecycle Markdown does not expose
  cleanup target dataset IDs or temporary KB names.

Not yet implemented:

- Template strategy that makes embedding-model checking easy without reducing public
  portability.

## Validation Evidence / Residual Gated Work

Focused validation for the first implementation slice:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_validation.py -q
python3 -m pytest packages/ragflow-skill-runtime/tests/test_optimization.py -q
python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -q
git diff --check
```

Broader validation before closing a code round:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests -q
git diff --check
python3 tools/release_hygiene_check.py
```

If public schemas, generated Markdown, or report surfaces change, also run the repository
schema identity and report-surface checks required by the release validation chain.

R3 strict regression remains gated by explicit approval for any live disposable RAGFlow
mutation. The preferred first implementation slice is offline and fake-client testable:
fix table modality detection, add expected-term metrics, and update benchmark rendering.
