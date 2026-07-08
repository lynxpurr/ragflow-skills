# RAGFlux And ragflow-kb-ops Retirement Transition Action Plan

Status: active transition plan
Date: 2026-07-08

## Objective / Scope / Boundaries

This plan defines the transition period for retiring the two legacy comparison skills:

- `ragflux`
- `ragflow-kb-ops`

The target replacement path is the current public three-skill suite:

```text
ragflow-doc-to-md  ->  ragflow-kb-build  ->  ragflow-query
```

The goal is to move real workflows to the current suite while keeping legacy outputs
available only as comparison and regression evidence. The transition is evidence-led:
collect field-trial records, compare stable metrics, improve the current suite when a
real gap appears, and avoid repairing the retiring skills unless a separate explicit
maintenance request targets those repositories.

This plan does not authorize live RAGFlow mutation, live MinerU calls, script-owned LLM
execution, private bridge work, service wrappers, provider adapters, reranker adapters, or
web/API wrappers. Those remain gated by the existing observation and approval rules.

## Current Retirement Position

`ragflow-doc-to-md` can replace the RAGFlux document-preparation segment only through the
formal path, not through thin preview conversion:

```text
inspect-source / adaptive / pipeline
quality reports
local assets
postprocess and chunk markers
rich handoff sidecars
retrieval hints
non-secret ingest plan
```

`ragflow-kb-build` is the default replacement for the public `ragflow-kb-ops` capability
set:

```text
handoff inspection
dry-run and live-build gates
profile, metadata, and tagset governance
append and cleanup plans
benchmark lifecycle
grounded QA validation
evidence mapping
optimization planning
parse and health reports
chunk snapshot review
topology and activation advice
```

Legacy skill findings should be classified as transition evidence:

- Retained RAGFlux package comparison can reveal static differences in Markdown, images,
  chunk markers, hints, sidecars, and package readiness.
- Retired `ragflow-kb-ops` runs can reveal SDK drift, cleanup drift, requested/effective
  profile mismatch, or old consumer behavior.
- Follow-up work should land in the current public suite only when it improves current
  handoff contracts, readiness checks, requested/effective parser visibility, retrieval
  validation, cleanup safety, or release evidence.

## Transition Principles

1. Default new work to the current three-skill suite.
2. Keep legacy skills read-only unless explicitly requested otherwise.
3. Run offline and fake-client checks before any live mutation.
4. Keep live KB work disposable, explicitly approved, cleaned up, and summarized only with
   sanitized evidence.
5. Prefer current-suite fixes over legacy compatibility patches.
6. Treat representative-sample success as transition evidence, not broad corpus proof.
7. Open post-CLI adapters, provider abstractions, rerankers, LLM backends, or private
   bridges only after documented trigger evidence.

## Phase Plan

### Phase 1: Baseline Inventory

Build a stable transition baseline from existing artifacts and future approved runs.

Required sample classes:

| Sample class | Purpose |
| --- | --- |
| Scanned Chinese PDF | OCR, language detection, image/table extraction, table-atomic profile review |
| Extractable-text PDF | Low-risk parser baseline and text fidelity |
| Image-heavy PDF | Local asset landing, image references, image artifact signals |
| Complex-table PDF | HTML table preservation, table markers, table chunk review |
| Long document | segmentation, chunk density, resume/checkpoint behavior |
| Office table document | non-PDF table handoff and dry-run readiness |
| Mixed-language document | language source, profile recommendation, query behavior |
| Low-quality OCR sample | warning quality, review outcome, fallback behavior |
| Multi-document handoff | batch upload, parse grouping, manifest completeness |

For each sample, retain private raw artifacts outside the public repository and record
only public-safe summaries:

- source class, approximate document count, and approximate size;
- command group and sanitized flags;
- generated report names;
- quality status, readiness status, parse/query/cleanup status;
- summarized metrics and redacted failure classes;
- decision: keep observing, fix current suite, open a gated design, or reject for now.

### Phase 2: Shadow Runs

For transition runs, execute the current suite first:

```bash
ragflow-doc-to-md inspect-source
ragflow-doc-to-md adaptive --decision-only
ragflow-doc-to-md adaptive
ragflow-kb-build inspect-handoff
ragflow-kb-build --dry-run
ragflow-kb-build asset-upload-plan
```

When a static legacy comparison is useful:

- compare against the retained RAGFlux ingestion package, not intermediate parser output;
- record whether paired live A/B was actually run;
- use old `ragflow-kb-ops` output only as retired-consumer evidence.

When live validation is explicitly approved, use a disposable current-suite KB:

```bash
ragflow-kb-build probe
ragflow-kb-build build
ragflow-kb-build validate --level smoke
ragflow-kb-build parse-report
ragflow-kb-build health-report
ragflow-query ask
ragflow-kb-build cleanup
```

Do not run a paired legacy live A/B unless it is separately approved with its own
disposable resources and cleanup record.

### Phase 3: Metrics Monitoring

Track metrics by pipeline stage.

#### Document Handoff Metrics

| Metric | Source | Watch for |
| --- | --- | --- |
| conversion status | runtime report | backend failure, timeout, resource failure |
| quality gate | quality report | `BLOCKED`, unclear `PASS_WITH_REVIEW` reasons |
| Markdown size and non-empty status | manifest / quality report | empty output, major text shrinkage |
| image references | Markdown / asset plan | missing local image assets |
| local image assets | manifest / artifact index | asset loss or unreferenced asset growth |
| HTML table count | quality and hints reports | table disappearance or parser drift |
| chunk marker count | postprocess / chunk profile report | too sparse, too dense, marker inside table |
| retrieval hint richness | retrieval hints | missing sections, tables, images, questions |
| language source | inspect/adaptive reports | binary garbage classified as confident text |
| stage timings | runtime report | slow conversion, asset download, packaging regression |

#### KB Build Metrics

| Metric | Source | Watch for |
| --- | --- | --- |
| handoff readiness | inspect-handoff | blocked or vague review reasons |
| dry-run status | build dry-run | profile incompatibility, missing sidecars |
| requested/effective profile visibility | dry-run, parse-report, health-report | profile drift, unsupported settings |
| upload batch success | build report | partial upload, duplicate upload, checkpoint confusion |
| parse state | parse-report / refresh-report | stale documents, parse timeout, zero chunks |
| chunk distribution | snapshot-chunks | extreme chunk count, table fragmentation |
| cleanup readiness | cleanup plan / optimize cleanup-plan | missing confirmations, unsafe targets |
| runtime partial failure | build and query reports | repeated retries, circuit breaker events |

#### Retrieval Metrics

| Metric | Source | Watch for |
| --- | --- | --- |
| smoke pass rate | validate smoke | immediate retrieval failure |
| zero-result rate | validation / query reports | retrieval outage or profile mismatch |
| hit rate, MRR, recall, nDCG, MAP | benchmark report | ranking regression |
| strict chunk recall | benchmark + chunk snapshot | expected evidence not retrieved |
| wrong-document or tag pollution | benchmark / suppression report | cross-source contamination |
| citation support | audit/evaluate reports | unsupported answer claims |
| direct vs host-assisted difference | query traces | orchestration hides retrieval weakness |

#### Safety And Release Metrics

| Metric | Source | Watch for |
| --- | --- | --- |
| redaction findings | redaction reports / release hygiene | leaked endpoint, key, path, KB name, raw chunk |
| schema identity | schema identity gate | untracked report schema drift |
| generated Markdown safety | release hygiene | secret-like text in reports |
| consumer acceptance | acceptance tool | archive or skill packaging drift |
| platform smoke | platform smoke matrix | cross-host execution drift |

### Phase 4: Test Cadence

Run tests at three levels.

#### Per-Change Offline Checks

Use for docs, runtime, report, or CLI changes that do not require live services:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests -q
git diff --check
python3 tools/manifest_schema_check.py
python3 tools/release_hygiene_check.py
```

#### Release-Facing Checks

Use before changing public command surfaces, report schemas, release artifacts, or
retirement gates:

```bash
python3 tools/build_release.py --check
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py --work-dir WORKDIR --overwrite
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir WORKDIR
```

Use fresh private work directories for acceptance and platform smoke runs.

#### Field-Trial Checks

Use on representative samples:

1. `doc-to-md` inspect/adaptive/pipeline.
2. `kb-build inspect-handoff`.
3. `kb-build --dry-run`.
4. Optional approved disposable live build.
5. Smoke, regression, or benchmark validation.
6. Direct and host-assisted query checks.
7. Parse, health, chunk snapshot, and cleanup reports.
8. Field-trial metrics aggregation over explicit run roots.

## Improvement Rules

Classify each finding before opening work:

| Finding class | Default action |
| --- | --- |
| Current-suite bug | Add a focused fixture, fix the current suite, run validation |
| Current-suite report ambiguity | Improve current JSON/Markdown report clarity and tests |
| Legacy skill SDK or cleanup drift | Record as retired-consumer evidence; do not repair old skill |
| Legacy package static difference | Compare against live current-suite evidence before treating as blocker |
| Resource contention | Record host class and failure mode; do not add daemon management |
| Query quality regression | Try profile, fusion, rewrite, benchmark, or suppression diagnostics first |
| Repeated CLI-shape friction | Open `serve` gate only after documented trigger evidence |
| Provider, reranker, remote converter, LLM, or private bridge need | Open the relevant gated design only with concrete fixtures and acceptance criteria |

## Task Checklist

These checklist items represent transition work. Mark them complete only after the
evidence exists and validation has been run.

### Baseline And Evidence

- [ ] Create or identify one public-safe transition record for each required sample class.
- [ ] Record retained RAGFlux package comparison for at least the representative document
  classes where RAGFlux was historically used.
- [ ] Record retired `ragflow-kb-ops` comparison evidence only where it reveals current
  suite reporting or validation needs.
- [ ] Aggregate at least five meaningful transition runs with `tools/field_trial_metrics.py`.

### Current-Suite Handoff Quality

- [ ] Confirm formal `doc-to-md` outputs include local assets, quality report, runtime
  report, retrieval hints, chunk profile report, and ingest plan for representative
  formal-ingest samples.
- [ ] Confirm `PASS_WITH_REVIEW` warnings stay specific and actionable for table-heavy or
  low-quality OCR samples.
- [ ] Confirm no sample class has unexplained missing image assets or empty Markdown.

### Current-Suite KB Build Quality

- [ ] Confirm `inspect-handoff` readiness aligns with dry-run outcomes.
- [ ] Confirm requested/effective parser profile visibility exists for live or observed
  parse evidence.
- [ ] Confirm current `snapshot-chunks` review covers table fragmentation, duplicate
  table-like chunks, missing table evidence, visible delimiters, and image-only chunks.
- [ ] Confirm disposable cleanup succeeds for every approved live transition run.

### Retrieval Quality

- [ ] Confirm smoke validation passes for every approved live transition KB.
- [ ] Confirm benchmark or regression validation exists for at least the highest-risk
  sample classes.
- [ ] Confirm zero-result, wrong-document, pollution, strict chunk recall, and citation
  support metrics are reviewed before defaulting a new profile or handoff mode.

### Release And Safety

- [ ] Run release-facing checks before declaring either legacy skill fully retired from
  the default workflow.
- [ ] Run targeted redaction scans before publishing any transition summary.
- [ ] Confirm no public docs or reports contain live endpoints, keys, private paths,
  dataset identifiers, document identifiers, KB names, or raw retrieved chunks.

## Retirement Decision Gates

### RAGFlux Default-Path Retirement

RAGFlux can remain retired from the default path when:

- formal `doc-to-md` handoff succeeds across the required sample classes or has
  well-explained review warnings;
- image, table, chunk marker, retrieval hint, and ingest plan evidence has no critical
  static regression;
- `kb-build inspect-handoff` and dry-run agree on readiness;
- approved disposable live runs pass parse, smoke/query, and cleanup checks;
- any lower chunk-marker density or package-shape difference is backed by successful live
  parse and retrieval evidence, or is tracked as a current-suite improvement item.

### ragflow-kb-ops Default-Path Retirement

`ragflow-kb-ops` can remain retired from the default path when:

- `ragflow-kb-build` covers the workflow's build, append, cleanup, profile, benchmark,
  QA, evidence-map, metadata/tagset, parse/health, optimization, and topology needs;
- requested/effective parser settings are visible when current-suite evidence exists;
- cleanup uses current `ragflow-kb-build` preview and exact-confirm execution;
- old `ragflow-kb-ops` SDK drift or profile mismatch is recorded only as transition
  evidence;
- no active workflow still requires an old private or unsafe operation.

## Review Cadence

Use this cadence during the transition:

- after every meaningful live or representative-sample run: write a sanitized run record;
- after five meaningful runs: aggregate metrics and review retirement status;
- after a repeated failure class appears twice: decide whether to fix current suite or
  keep observing;
- before a public release candidate: run release-facing checks;
- before opening any gated adapter or live A/B: confirm the trigger evidence and approval
  path.

## Closeout / Retrospective

This section should be completed only after enough transition evidence exists to close the
period. It should record:

- sample matrix coverage;
- validation commands and outcomes;
- remaining review warnings;
- old-skill usage that remains, if any;
- whether each legacy skill is fully retired, retained as read-only comparison evidence,
  or still needed for a narrowly scoped workflow.

## Validation Evidence / Residual Gated Work

At plan creation time, this is a docs-only transition plan. It does not change command
behavior, report schemas, release artifacts, or live workflow defaults.

Residual gated work remains unchanged:

- live RAGFlow mutation requires explicit approval and disposable cleanup;
- paired live A/B with legacy skills requires separate approval;
- live MinerU v4 validation requires explicit credentials and sanitized evidence capture;
- local service wrappers, provider adapters, reranker adapters, remote converter clients,
  optional LLM/RAGAS backends, and private bridges require their existing trigger gates.
