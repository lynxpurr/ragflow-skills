# Benchmark Evidence Strengthening And Transition Validation Plan

Status: public offline tooling, synthetic L0, reviewed Open RAG strengthening, normalized
FinanceBench portfolio, and five-run transition aggregation are complete; FinanceBench
formal conversion, handoff inspection, benchmark replay, and KB dry-run are complete;
observed validation and transition sample coverage remain gated
Date: 2026-07-11

## Objective / Scope / Boundaries

This plan owns the next evidence-strengthening round after KB parameter Stage 8B. It does
not reopen Stage 8C materialization. Its purpose is to turn the existing exploratory
benchmark and representative retirement evidence into a reproducible, offline-first
portfolio that can detect table, numeric, document, chunk, pollution, and citation
regressions before any future profile or parameter promotion.

The plan coordinates four existing owners without replacing them:

- `docs/35-standard-benchmark-dataset-integration-plan.md` remains the dataset portfolio,
  normalization, licensing, and benchmark-maturity design source;
- `docs/32-retirement-transition-action-plan.md` remains the broad-corpus retirement
  observation checklist;
- `docs/36-ragflow-kb-parameter-materialization-plan.md` remains the contract and live
  materialization gate;
- `docs/15-field-trial-observation-plan.md` remains the sanitized real-run evidence
  format and trigger source.

In scope:

- add first-class normalized `source_attribution.json` and `selection_report.json`
  support to the benchmark import/sample lifecycle;
- add a deterministic, explicit-input benchmark portfolio summary across multiple
  normalized subsets;
- strengthen the existing Open RAG Benchmark seed with expected terms and, when a
  reviewed chunk snapshot exists, expected chunk aliases or hashes;
- build one small FinanceBench table/numeric slice from operator-selected public source
  material kept outside the repository;
- aggregate benchmark strength, table/numeric evidence, wrong-document, pollution,
  strict chunk recall, citation-support, and release-health evidence;
- define a later Hermes offline replay only after the synthetic fixtures and commands are
  stable.

Out of scope by default:

- no RAGFlow dataset creation, update, upload, parse, reparse, delete, or cleanup;
- no DeepDoc/native PDF baseline;
- no script-owned LLM/RAGAS generation or evaluation;
- no default profile, parser, enrichment, or parameter promotion;
- no raw FinanceBench/Open RAG dataset dump, source PDF, private path, endpoint,
  credential, KB name, dataset/document identifier, or raw retrieved chunk in the public
  repository;
- no automatic Stage 8C eligibility decision from benchmark results.

## Problem Description

At the planning baseline, the repository had strong single-subset benchmark primitives
but no single execution owner for this evidence round:

1. The first Open RAG Benchmark seed is exploratory: one PDF, ten judged queries, and
   mostly document-level evidence.
2. FinanceBench was designed in `docs/35`, but no normalized table/numeric slice was yet
   retained as a reproducible private-source/public-safe-evidence workflow.
3. `benchmark import` currently normalizes `queries.json`, `qrels.json`, and `qa.json`,
   while the `docs/35` artifact contract also requires `source_attribution.json` and
   `selection_report.json`.
4. Existing benchmark commands operate on one subset at a time. Release-health review
   needs an explicit-input portfolio summary without scanning user directories or
   calling RAGFlow.
5. The retirement checklist lacked the full sample matrix, five meaningful runs,
   highest-risk benchmark evidence, and a combined review of zero-result,
   wrong-document, pollution, strict chunk recall, and citation support.
6. `docs/36` correctly has zero Stage 8C candidates. Stronger benchmark evidence is a
   future prerequisite, not authorization to materialize a blocked field.

## Update Plan

### P0 - Complete The Normalized Benchmark Artifact Contract

Extend the existing benchmark import/sample path rather than creating a parallel dataset
normalizer.

Add two versioned artifacts:

- `ragflow_benchmark_source_attribution_v1`:
  - dataset name and public upstream project identifiers;
  - license label;
  - selected public source IDs;
  - source hash labels where available;
  - human/LLM/mixed authorship provenance;
  - public-safe notes only.
- `ragflow_benchmark_selection_report_v1`:
  - selected subset ID;
  - selection criteria;
  - included query types and modalities;
  - excluded case counts and reasons;
  - intended decision tier: `smoke`, `exploratory`, `promotion_candidate`, or
    `regression_baseline`.

`benchmark import` should accept these as optional explicit JSON inputs, copy normalized
versions into the output directory, and reference them from
`ragflow_benchmark_manifest_v1.artifacts`. `benchmark sample` should preserve attribution
and write a derived selection report that records the parent subset and deterministic
sampling parameters.

Acceptance target:

- old query/qrels-only imports remain backward compatible;
- invalid schema, missing license, empty selection criteria, or unsafe values fail
  closed;
- no source PDF or dataset dump is copied into release artifacts;
- import/sample JSON, Markdown, and redaction behavior remains deterministic.

### P0 - Add An Offline Benchmark Portfolio Summary

Add `tools/benchmark_portfolio.py` as a standalone repository tool, not a public skill
command. It reads one explicit portfolio config and the subset artifacts named by that
config. It must not discover directories, download data, call RAGFlow, or invoke an LLM.

The private/operator-owned input config uses
`ragflow_benchmark_portfolio_config_v1` and names each subset with:

- stable subset ID and dataset label;
- license and decision tier;
- sample types;
- benchmark manifest;
- source attribution and selection report;
- optional preflight, validation, retention, citation, and field-trial report paths.

The public-safe output uses `ragflow_benchmark_portfolio_v1` and retains only stable
labels, artifact basenames, canonical input digests, source hashes already approved for
publication, counts, status, metrics, missing-evidence classes, and safety flags. It must
not retain input roots or private identifiers.

Required portfolio summary dimensions:

- subset and dataset count;
- query, judged-query, qrel, and QA counts;
- decision-tier distribution;
- query-type and modality coverage;
- expected-term and expected-chunk coverage;
- table/numeric query coverage;
- negative/unanswerable coverage;
- preflight and benchmark-strength status;
- zero-result, wrong-document, pollution, strict chunk recall, expected-term,
  table-term, and citation-support metrics when supplied;
- field-trial sample-type coverage and missing classes;
- `ready`, `ready_with_review`, or `blocked` assessment with explicit reasons.

Declared expected-chunk coverage and observed strict chunk evidence must remain separate.
The portfolio may count declared expected chunk IDs or hashes from qrels, but it must not
report verified strict chunk recall unless a supplied validation report contains the
corresponding observed metric, including metrics computed against a candidate snapshot.

The tool may report evidence readiness, but it must never recommend a default profile or
mark a Stage 8C field writable.

### P1 - Strengthen The Open RAG Benchmark Seed

Use the existing private seed source and public-safe normalized artifacts. Do not commit
the source PDF or raw retrieved evidence.

Required evidence improvements:

- preserve the current stable query IDs and document qrels;
- add expected terms for core text, table, image/mixed, and abstractive queries;
- add source section/page metadata where the public dataset provides it;
- add negative or no-match coverage when supported by the selected subset;
- after an offline or separately approved chunk snapshot exists, map core evidence to
  candidate snapshot aliases or stable chunk hashes;
- rerun benchmark import, preflight, deterministic sampling, and portfolio summary.

The Open RAG slice remains `exploratory` until strict evidence and query diversity meet
the Level 2 requirements in `docs/35`.

### P1 - Build A FinanceBench Table/Numeric Slice

Select one small or medium public filing and a bounded set of evidence-rich questions.
Raw dataset rows, PDFs, and evidence text stay in a repository-external private run root.

Normalize:

- question to benchmark query;
- document name to document qrel;
- evidence page to qrel/QA metadata;
- evidence text to expected terms and grounded QA evidence;
- answer to grounded QA answer;
- table/numeric case type to query metadata;
- one or more wrong-document or distractor cases where the selected public sample permits
  a deterministic judgment.

Offline acceptance target:

- benchmark import succeeds with attribution and selection artifacts;
- preflight reports table/numeric and expected-term coverage;
- formal handoff conversion, `inspect-handoff`, and KB dry-run pass or produce specific
  review warnings;
- no live KB or chunk snapshot is required to close the offline slice;
- any later live snapshot/benchmark run remains separately approval-gated.

### P2 - Form The Initial Regression Portfolio

Combine the strengthened Open RAG seed and FinanceBench slice in the explicit portfolio
config. Add QASPER only in a later slice after the two-subset baseline is stable.

The first regression portfolio must record:

- pinned subset identifiers and source hashes;
- licenses and selection criteria;
- reproducible handoff and parser profile labels;
- benchmark strength and intended decision tier;
- current release-health command results;
- missing live evidence without treating it as a tooling failure;
- pinned per-subset benchmark validation reports that remain suitable for future
  `benchmark trend` and `benchmark delta` inputs.

Portfolio completion is a release-health evidence milestone. It is not a profile
promotion, broad-corpus retirement guarantee, or Stage 8C authorization.
Without observed per-subset validation reports, the initial output is an artifact/evidence
baseline with `ready_with_review`, not a Level 3 retrieval-quality regression baseline.

### P2 - Close Transition Observation Gaps

Use only sanitized explicit run roots with `tools/field_trial_metrics.py`.

The evidence round should:

- reach at least five meaningful transition runs;
- improve coverage for currently missing sample classes;
- confirm that covered classes have no unexplained empty Markdown or missing assets;
- include benchmark/regression evidence for the highest-risk table/numeric class;
- review zero-result, wrong-document, pollution, strict chunk recall, expected-term, and
  citation-support evidence before changing recommended guidance.

Only update `docs/32` checkboxes after the corresponding public-safe reports and release
checks exist.

### P2 - Prepare A Hermes Offline Replay

Create a copy-paste Hermes instruction only after the portfolio tool, synthetic fixtures,
and offline command chain pass locally.

The first instruction should authorize only:

- clean-worktree preflight;
- focused unit/CLI tests;
- synthetic benchmark import/preflight/sample;
- portfolio JSON/Markdown/redaction generation;
- repository-external artifact roots;
- separate sensitive-value scans for tool output and agent-authored prose;
- final clean-worktree verification.

It must not authorize dataset download into the repository, RAGFlow HTTP calls, live
mutation, DeepDoc, LLM/RAGAS, or Stage 8C. A later private-source or live instruction is
generated separately after review.

## Task Checklist

### Artifact Contract And Offline Tooling

- [x] Add source-attribution and selection-report schemas, validation, import support,
  and backward-compatible manifest references.
- [x] Preserve attribution and derive deterministic selection evidence during benchmark
  sampling.
- [x] Add synthetic table/numeric, expected-term, expected-chunk, negative, and
  multimodal fixtures.
- [x] Add `ragflow_benchmark_portfolio_v1` JSON, Markdown, CLI, and redaction outputs from
  explicit inputs only.
- [x] Add schema identity, focused tests, generated-Markdown safety, and release hygiene
  coverage for all new report identities.

### Open RAG Evidence

- [x] Add public-safe source attribution and selection evidence for the existing Open RAG
  seed.
- [x] Add expected-term coverage for core query types without publishing raw source or
  retrieved evidence.
- [ ] Add expected-chunk or candidate-snapshot evidence only after a reviewed snapshot is
  available.
- [x] Rerun import, preflight, deterministic sample, and portfolio summary for the
  strengthened seed.

### FinanceBench Evidence

- [x] Select one bounded FinanceBench filing/question slice and record license,
  selection, provenance, and source hashes outside raw public artifacts.
- [x] Normalize table/numeric queries, document qrels, evidence-page metadata, expected
  terms, grounded QA, and deterministic distractor cases.
- [x] Run formal conversion, handoff inspection, benchmark import/preflight, and KB
  dry-run without live mutation.
- [x] Add the FinanceBench subset to the initial portfolio and retain public-safe reports.

### Regression And Transition Validation

- [ ] Produce the two-subset Open RAG + FinanceBench regression baseline.
- [x] Aggregate at least five meaningful transition runs and review sample-type coverage.
- [ ] Review zero-result, wrong-document, pollution, strict chunk recall, expected-term,
  table-term, and citation-support evidence before guidance changes.
- [x] Update `docs/32`, `docs/35`, and `docs/16` only when evidence changes their current
  status or closes an existing row.

### Hermes And Release Closure

- [x] Add a repository-safe Hermes offline replay instruction after the local synthetic
  chain is stable.
- [x] Run focused tests, full runtime tests when code changes, schema identity, generated
  Markdown audit, release hygiene, build checks, consumer acceptance, and strict-vendor
  platform smoke as required by the changed surface.
- [x] Record a closeout that separates completed offline work from private-source fill,
  observation work, and separately approved live validation.

## Current Development Progress

Planning baseline on 2026-07-11:

- the Open RAG Stage 0-5 exploratory seed and disposable enrichment comparison are
  complete;
- existing runtime support already covers benchmark import/sample/preflight,
  expected-term metrics, expected chunks, candidate snapshot matching, table-term
  metrics, wrong-document/pollution metrics, trend/delta/gate reports, and sanitized
  retention;
- the missing public offline work is artifact-contract completion plus multi-subset
  portfolio aggregation;
- the missing evidence work is stronger Open RAG qrels, one FinanceBench table/numeric
  slice, broader transition coverage, and a stable regression baseline;
- `docs/36` has zero Stage 8C candidates, so no parameter materialization or live probe is
  part of this plan.

Implementation update on 2026-07-11:

- `benchmark import` and `benchmark sample` now support normalized source attribution
  and selection artifacts while preserving legacy inputs;
- deterministic samples preserve attribution and derive parent-bound selection evidence;
- `tools/benchmark_portfolio.py` produces explicit-input-only, public-safe JSON,
  Markdown, and redaction reports without RAGFlow, directory discovery, or LLM calls;
- committed neutral fixtures exercise text, table, numeric, mixed-modality,
  expected-term, declared expected-chunk, and negative coverage;
- the local synthetic replay produced two subsets, six queries, twelve qrels, six QA
  items, four table/numeric queries, and one negative/unanswerable query;
- the synthetic portfolio is `ready_with_review` because observed validation is absent;
  it is not a Level 3 retrieval regression baseline;
- `docs/39-benchmark-evidence-strengthening-hermes-test.md` now provides the
  repository-only L0 replay instruction;
- Hermes independently replayed the instruction against commit `3b94d93` from a clean
  worktree: 47 governance/portfolio/schema tests with 17 subtests and 2 benchmark CLI
  tests passed, the expected 2-subset/6-query portfolio was reproduced, all safety
  counters remained zero, and the final worktree remained clean;
- focused validation passed with 72 tests and 17 subtests; the complete runtime suite
  passed with 698 tests and 28 subtests; release hygiene, build/export, consumer
  acceptance, and strict-vendor smoke all passed;
- operator-reviewed public sources were acquired into the repository-external private
  evidence root without committing raw data: the Open RAG seed retained 10 stable query
  IDs and gained 21 reviewed expected terms, while a bounded FinanceBench slice retained
  7 judged questions, 25 reviewed expected terms, evidence-page metadata, and two
  deterministic wrong-document alternates;
- both normalized subsets passed import and preflight with 100% expected-term and
  grounded-QA coverage; exact-span QA validation grounded 16 of 16 Open RAG spans and 9
  of 9 FinanceBench spans with zero errors or warnings;
- the private two-subset portfolio contains 17 judged queries, 17 qrels, 17 QA items,
  and 8 table/numeric queries. It remains `ready_with_review` solely because observed
  validation is absent and therefore is not a Level 3 retrieval regression baseline;
- FinanceBench source inspection classified the 190-page filing as table-heavy,
  long-document, high-complexity, and unsuitable for the built-in converter. An approved
  MinerU FastAPI protocol-v2 backend passed a read-only health probe and completed the
  reviewed `hybrid-auto-engine` high-table-quality path after backend and language config
  propagation were aligned with the deployed service. The formal handoff contains one
  document, 134 files, 15 formal sidecars, 491 dense chunk markers, and 111 detected
  tables. Handoff inspection reported complete rich/pipeline sidecars,
  `PASS_WITH_REVIEW`, 115 artifacts, and 379 retrieval hints; KB dry-run passed for one
  document with an estimated 841 chunks. The only retained review warnings are manual
  quality review and the selected default profile treating dense markers as advisory;
- five explicit, public-safe transition records were aggregated with zero findings and
  zero triggered tracks. Five of eight required sample classes were observed; office
  table, mixed-language, and low-quality-OCR samples remain missing, so the retirement
  assessment is still `insufficient_samples`;
- no RAGFlow HTTP call, live mutation, DeepDoc run, script-owned LLM/RAGAS call, or
  Stage 8C action was performed.

## Validation Evidence / Residual Gated Work

Minimum validation for docs-only planning changes:

```bash
git diff --check
python3 tools/release_hygiene_check.py
```

Expected implementation validation when the report/artifact surfaces change:

```bash
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py \
  skills/ragflow-kb-build/scripts/build.py \
  tools/benchmark_portfolio.py
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py \
  packages/ragflow-skill-runtime/tests/test_validation.py \
  packages/ragflow-skill-runtime/tests/test_schema_identity_check.py -q
python3 tools/schema_identity_check.py
python3 tools/release_hygiene_check.py
git diff --check
```

Run consumer acceptance and strict-vendor platform smoke when benchmark CLI artifacts or
packaged templates change. Run the full runtime suite before calling the tooling slice
broadly verified.

Residual gates remain separate:

- reviewed public source acquisition and private normalization are complete for the
  current Open RAG and FinanceBench slices;
- FinanceBench formal conversion, handoff inspection, import/preflight replay, and KB
  dry-run are complete. The built-in converter remains an invalid PDF fallback, and any
  future rerun must continue to pin the reviewed MinerU protocol and deployed language
  model setting;
- RAGFlow read-only HTTP evidence requires its own instruction when needed;
- any disposable RAGFlow mutation requires explicit approval, exact cleanup, and
  sanitized retention;
- DeepDoc/native comparison remains a separate approved baseline;
- script-owned LLM/RAGAS remains out of scope;
- Stage 8C remains blocked until a new pinned RAGFlow contract produces a
  `writable_contract_confirmed` candidate.

## Closeout / Retrospective

Public offline closeout on 2026-07-11:

- closed: normalized attribution/selection contracts, deterministic sampling
  provenance, standalone portfolio aggregation, neutral synthetic fixtures, schema and
  release governance, and the Hermes L0 replay instruction;
- verified: compile, focused tests, full runtime tests, manifest/schema identity,
  generated Markdown, release hygiene, release build/export, consumer acceptance, and
  strict-vendor smoke, plus an independent Hermes L0 replay with separate tool-report
  and agent-prose sensitive scans;
- closed after private evidence review: Open RAG attribution, selection, expected-term,
  exact-span QA, deterministic sample, and portfolio rerun; FinanceBench filing/question
  selection, normalization, source-grounded expected terms, exact-span QA, import,
  preflight, and initial portfolio inclusion;
- still open: reviewed expected chunks, pinned observed per-subset validation, a true
  retrieval-quality regression baseline, and completion of the transition sample-class
  matrix;
- private/live decision: source acquisition and normalization remained offline. MinerU
  was used only for the approved private conversion and produced the formal handoff; its
  temporary config was deleted afterward. No DeepDoc, RAGFlow, LLM/RAGAS, or Stage 8C
  action was performed;
- roadmap effect: no `docs/32` retirement row and no `docs/36` Stage 8C row closes from
  synthetic evidence alone. The current profile, retirement, and parameter
  materialization decisions remain unchanged.
