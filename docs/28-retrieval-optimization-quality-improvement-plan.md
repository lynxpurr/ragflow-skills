# Retrieval Optimization Quality Improvement Plan

Status: proposed follow-up plan
Date: 2026-07-07

This document focuses on functional and effectiveness improvements for the current
RAGFlow skill suite after the APOLLO optimize field-trial evidence. It intentionally
excludes report wording or presentation cleanup. The scope is limited to improving how
the skills create benchmark evidence, run profile experiments, decide winners, expose
effective RAGFlow behavior, and connect optimization output to query-quality follow-up.

The plan preserves the current public-suite boundaries:

- no live RAGFlow mutation by default;
- no script-owned LLM or RAGAS execution by default;
- no private endpoints, dataset IDs, document IDs, raw chunks, prompts, or secrets in
  public docs;
- deterministic offline reports before any live action;
- explicit confirmation and cleanup evidence for every mutating RAGFlow operation.

## Problem Description

### Weak Benchmark Evidence Can Still Produce Strong-Looking Winners

The optimize workflow can successfully build disposable KBs and rank profile candidates,
but a benchmark with only document-level qrels, one target document, no expected terms,
no grounded QA items, and no expected chunks has low discriminative power. It can prove
that retrieval returns chunks from the expected document, but it cannot prove that the
returned chunks contain the answer span, the right table row, the right field, or the
right visual evidence.

Impact:

- `Precision@k` can reward returning enough same-document chunks rather than precise
  answer evidence.
- `MRR` and `recall@k` can saturate at 1.0 across all candidates and stop helping profile
  selection.
- Optimize can appear to find a robust winner when it has only found a profile that fills
  the top-k context window better on a small benchmark.

### Profile Decisions Need Tie, Confidence, And Cost Awareness

The current optimize summary ranks by composite score and then by profile ID. When two
profiles have identical metrics, an enrichment-heavy profile can win by incidental
identifier order. Runtime and cost fields are optional, so enrichment settings such as
`auto_keywords` can be recommended even when they show no quality gain and no measured
cost.

Impact:

- Users may promote a higher-cost parser configuration without evidence of benefit.
- Equivalent candidates are not surfaced as co-winners.
- Composite scores can be interpreted as absolute quality even when they are only
  relative ranking signals.

### Profile Experiment Matrices Can Contain Aliased Or Redundant Dimensions

`chunk_size` and `parser_config.chunk_token_num` represent the same effective RAGFlow
chunk size in the current profile model. If both are varied independently, the matrix can
expand into many settings that collapse into fewer effective profiles after normalization.

Impact:

- Experiment counts overstate the actual search space.
- Duplicate effective profiles waste build, parse, validation, and cleanup time.
- Users cannot tell whether a dimension was truly tested or silently overridden by an
  aliasing rule.

### Requested Parser Settings Are Not Always Connected To Effective Runtime State

The build profile records requested parser settings, but profile optimization needs
stronger evidence that RAGFlow actually applied the requested delimiter, chunk size,
overlap, enrichment settings, embedding model, and parse behavior. Some of this evidence
can only be observed after parse through chunk snapshots, document-list payloads, refresh
reports, parse reports, and health reports.

Impact:

- A profile can look successful even if a parser setting was ignored or transformed.
- Delimiter behavior cannot be assessed from requested config alone.
- Optimization cannot explain whether a metric changed because of chunk size, server-side
  chunk limits, delimiter consumption, enrichment behavior, or result thresholding.

### Chunk, Table, And Visual Evidence Are Not Required By The Optimize Loop

The suite already supports chunk snapshots, expected chunks, grounded QA evidence maps,
multimodal benchmark extensions, and query diagnostics. The optimize loop can still run
without these stronger artifacts, so the most convenient path remains weaker than the
best available evidence path.

Impact:

- Table-heavy and image-rich documents can pass a benchmark without proving table-row,
  cross-column, image, or mixed-modality recall.
- Query diagnostics receive less context for classifying failures such as table
  fragmentation, wrong modality, route mismatch, or pollution.
- Profile selection does not consistently benefit from rich handoff retrieval hints.

### Disposable Optimization Runs Need Stronger Lifecycle Closure

The optimize execution path correctly creates disposable KBs behind explicit gates and
records cleanup requirements. The quality loop is still incomplete if the summary does
not carry cleanup status, readiness status, field-trial record hints, and post-cleanup
verification into the final evidence chain.

Impact:

- A profile experiment can be treated as complete while disposable KB cleanup is still
  pending.
- Host agents must manually connect execute, summarize, cleanup-plan, cleanup-execute,
  and field-trial records.
- Repeated experiments can leave noisy KB state unless cleanup evidence is first-class.

## Update Plan

### Add Benchmark Strength Assessment

Add a deterministic benchmark-strength layer that runs during `benchmark preflight`,
`validate --level benchmark`, and `optimize summarize`. It should grade whether the
benchmark is suitable for exploratory comparison, profile recommendation, or default
promotion.

Signals should include:

- number of queries;
- number of target documents;
- qrel field distribution;
- presence of `expected_terms`, `expected_documents`, grounded QA items, expected chunks,
  expected modalities, and negative or wrong-document cases;
- query-type coverage for text, table, image, mixed, brand, and lookup classes;
- metric saturation risk when all candidates tie on hit rate, recall, or MRR.

Outputs should be advisory by default. A weak benchmark should not block validation, but
it should downgrade optimize decisions to exploratory status.

### Promote Co-Winner And Conservative Decision Semantics

Change optimization decision outputs from a single unconditional winner to a status-aware
decision:

- `recommended`: one candidate clears minimum evidence and score-delta thresholds.
- `co_winners`: multiple candidates tie within configured epsilon.
- `insufficient_evidence`: sample size, query diversity, or strict evidence is too weak
  for a profile promotion.
- `needs_cost_review`: quality ties but latency, parse time, enrichment, or operational
  cost is missing or worse for the apparent winner.

Default tie policy should prefer lower-cost and lower-risk profiles before enrichment-heavy
ones. The report should keep all tied profiles visible and avoid selecting a higher-risk
profile purely by profile ID.

### Make Profile Matrices Alias-Aware

Teach `profile experiment` to detect effective-profile aliases before emitting a candidate
set. It should warn when dimensions such as `chunk_size` and
`parser_config.chunk_token_num` collide, and it should either collapse duplicates or emit
them in a separate rejected/duplicate section.

The candidate profile set should record:

- original matrix dimension count;
- raw combination count;
- unique effective profile count;
- duplicate groups;
- alias or override reasons;
- recommended corrected matrix.

### Capture Effective Profile And Parse Evidence

Extend the optimization evidence chain so candidate summaries can consume effective state
sidecars when they exist:

- `parse-report` requested-vs-effective parser settings;
- `refresh-report` document states and chunk counts;
- `snapshot-chunks` stable hashes, chunk lengths, source documents, and marker visibility;
- `health-report` embedding model and parser warnings;
- optional read-only document-list payloads when RAGFlow exposes parser config or chunk
  metadata.

Optimize should not require live read-back by default, but when these sidecars exist it
should use them to explain why a profile changed metrics.

### Make Strong Evidence The Easy Path

Add helper paths that generate stronger benchmark artifacts from existing handoff and KB
evidence:

- use `retrieval_hints.json` to suggest table, image, and mixed-modality benchmark cases;
- use `qa map-evidence` and `snapshot-chunks` to convert grounded QA evidence into
  expected chunk qrels;
- suggest negative or wrong-document checks when a corpus contains more than one document
  or KB;
- surface missing strict evidence as an optimize follow-up, not only as a separate
  benchmark concern.

This keeps the default deterministic and no-LLM, while making high-quality validation
more discoverable.

### Normalize Scoring And Add Cost/Latency Penalties

Keep existing metrics for compatibility, but add a normalized decision layer that avoids
mixing raw nDCG-like values with 0-1 metrics without explanation. The decision score
should include quality, strict evidence, modality coverage, empty-result risk, latency,
parse time, enrichment cost, and context warning signals when present.

Missing cost or latency evidence should not become zero-cost evidence. It should be
marked as `unknown` and trigger `needs_cost_review` when enrichment settings are enabled.

### Close The Optimization Lifecycle

Make cleanup and observation part of the optimize evidence chain:

- `optimize summarize` should surface cleanup-required and cleanup-executed state when it
  can read the execute plan or cleanup report.
- `cleanup-plan` should be a standard next-step artifact after every execute run.
- `cleanup-execute` should emit a report that can be consumed by field-trial metrics.
- field-trial record suggestions should include sanitized command groups, elapsed time,
  candidate counts, validation summary, cleanup status, and decision status.

This does not make live mutation automatic. It makes disposable mutation safer and easier
to audit after explicit approval.

## Task Checklist

### Benchmark Strength And Strict Evidence

- [x] Add `benchmark_strength` analysis to benchmark preflight with qrel field
  distribution, target-document diversity, expected-term coverage, expected-chunk
  coverage, grounded-QA item count, modality coverage, and negative-case coverage.
- [x] Add weak-benchmark warnings when all qrels are document-level or all qrels target a
  single document.
- [x] Add metric-saturation warnings when hit rate, recall, or MRR cannot distinguish
  candidates.
- [x] Add gate options for minimum query count, minimum qrel strength, minimum expected
  chunk coverage, and minimum query-type diversity.
- [x] Teach `optimize summarize` to include benchmark-strength status and downgrade weak
  benchmark decisions to exploratory.
- [x] Add no-network tests for document-only qrels, single-target qrels, expected-chunk
  qrels, multimodal qrels, and mixed-strength benchmark sets.

### Optimization Decision Semantics

- [x] Add decision statuses: `recommended`, `co_winners`, `insufficient_evidence`, and
  `needs_cost_review`.
- [x] Replace profile-ID tie-breaking with a deterministic tie policy that prefers lower
  enrichment, lower measured cost, lower latency, and stable input order.
- [x] Add configurable epsilon thresholds for score ties and minimum score deltas.
- [x] Represent co-winners explicitly in JSON and Markdown summaries.
- [x] Mark enrichment-heavy profiles as needing cost review when quality ties and
  latency or parse-cost evidence is missing.
- [x] Add focused unit and CLI tests for equal-score candidates, enrichment ties,
  insufficient sample size, and conservative tie selection.

### Alias-Aware Profile Experiments

- [ ] Detect aliasing between `chunk_size`, `chunk_token_num`, and
  `parser_config.chunk_token_num` during matrix expansion.
- [ ] Emit duplicate effective profile groups with raw settings, normalized settings,
  and override reason.
- [ ] Collapse duplicate effective profiles by default, while preserving a raw matrix
  audit section.
- [ ] Add an option to fail on duplicate effective profiles for expensive live
  experiments.
- [ ] Add tests for matrix dimensions that intentionally and accidentally overlap.
- [ ] Update profile experiment docs and examples to avoid varying aliased fields
  independently.

### Effective Runtime Evidence

- [ ] Allow `optimize summarize` to consume optional parse, refresh, snapshot, and health
  sidecars per candidate.
- [ ] Add requested-vs-effective parser config fields to optimization candidate summaries
  when parse-report evidence exists.
- [ ] Add delimiter-consumption and chunk-boundary evidence from chunk snapshots when
  marker information is available.
- [ ] Add embedding-model and parser-drift warnings from health reports.
- [ ] Add tests that prove summaries remain valid when sidecars are missing, partial, or
  malformed.

### Strong Benchmark Artifact Generation

- [ ] Extend `validation-suggestions` or add a KB-build helper that converts
  `retrieval_hints.json` into table, image, and mixed-modality benchmark suggestions.
- [ ] Add a deterministic path from grounded QA evidence maps to expected-chunk qrels.
- [ ] Suggest negative or wrong-document benchmark cases when multiple documents or KBs
  are present.
- [ ] Add optimize follow-up recommendations when benchmark artifacts lack strict chunk
  or modality evidence.
- [ ] Add no-LLM fixtures that cover table values, image evidence, mixed table-image
  evidence, and wrong-document cases.

### Normalized Scoring And Cost Signals

- [ ] Add a normalized decision score that keeps raw metrics available but separates them
  from recommendation logic.
- [ ] Treat missing latency, parse time, and cost as unknown rather than zero.
- [ ] Add latency, parse-time, and enrichment-cost penalties when evidence exists.
- [ ] Add score component breakdowns for quality, strict recall, modality coverage,
  empty-result risk, cost, and context warnings.
- [ ] Add tests for raw nDCG compatibility and normalized decision scoring.

### Cleanup And Field-Trial Closure

- [ ] Include cleanup-required, cleanup-plan, cleanup-executed, and post-cleanup
  verification status in optimize summaries when related artifacts exist.
- [ ] Add a machine-readable next-step block for `cleanup-plan`, `readiness`, and
  `cleanup-execute` after live optimize execution.
- [ ] Make cleanup execution reports consumable by `tools/field_trial_metrics.py`.
- [ ] Add a sanitized field-trial record suggestion for optimize runs.
- [ ] Add tests that distinguish complete optimization runs from validation-passed but
  cleanup-pending runs.

### Cross-Skill Documentation And Acceptance

- [ ] Update public skill guidance so users know when document-only benchmarks are
  exploratory versus promotable.
- [ ] Add examples that connect `ragflow-doc-to-md` retrieval hints,
  `ragflow-kb-build` benchmark artifacts, optimize decisions, and `ragflow-query`
  diagnostics.
- [ ] Add consumer acceptance coverage for the stronger optimize path with no live
  mutation.
- [ ] Run schema identity, report-surface inventory, generated Markdown audit, release
  hygiene, consumer acceptance, and platform smoke after any public command or schema
  change.
