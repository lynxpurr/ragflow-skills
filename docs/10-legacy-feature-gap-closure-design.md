# Legacy Feature Gap Closure Design

Status: proposed roadmap for v0.2+
Date: 2026-06-24

## Objective

This document turns the second review of the older `ragflux`, `ragflow-kb-ops`,
`agentic-rag`, and `ragflow-smart-query` skills into a public, implementation-ready
design for the current three-skill RAGFlow suite:

```text
ragflow-doc-to-md  -> source documents to Markdown handoff
ragflow-kb-build   -> Markdown handoff to RAGFlow KB and validation
ragflow-query      -> retrieval, routing, evidence, and optional agentic query support
```

The goal is not to copy the old systems. The goal is to migrate their strongest
reusable behaviors into the new portable suite while preserving the release standards
that have already been validated:

- no personal paths, private IPs, private KB names, private corpora, or real secrets;
- no dependency on editable installs, private repos, or host-specific daemons;
- deterministic offline checks before live RAGFlow, live MinerU, or LLM-assisted paths;
- explicit dry-run/preview behavior for mutating operations;
- small versioned public schemas instead of private package formats.

## Reviewed Sources

The older skills contribute different kinds of value:

| Source | Strongest reusable ideas | Public migration stance |
| --- | --- | --- |
| `ragflux` | MinerU mode selection, Markdown cleanup, quality gates, rich handoff packages, large-document segmentation | Migrate into `ragflow-doc-to-md` as deterministic package and post-processing features |
| `ragflow-kb-ops` | RAGFlow API pitfall handling, batch-safe ingestion, append/rebuild safety, profile experiments, benchmark gates, benchmark import/trend/delta reports, metadata/tagset governance, grounded QA generation, evidence mapping, suppression candidate reports | Migrate into `ragflow-kb-build` as guarded commands and offline reports |
| `ragflow-smart-query` | routing hints, route regression, hint-gap diagnosis, English hint enrichment, per-KB retrieval params, optional centroid routing, cross-language A/B tests, BM25 pollution diagnosis, simple unified query interface | Migrate into `ragflow-query` without shipping private route tables or long-lived services |
| `agentic-rag` | query classification, planning, reflection, citation audit, cost traces, generation evaluation, context-aware query handling | Migrate as opt-in experimental query layers; keep host-assisted evidence as the safe default |

## Current Baseline

The current suite already implements a large part of the first roadmap:

- Markdown passthrough, builtin conversion, remote conversion, MinerU Agent API,
  MinerU synchronous API, local MinerU CLI, and MinerU CLI asset handoff.
- `doc_manifest.json`, quality gate, long-document segmentation plan/split, and local
  asset checks.
- RAGFlow dataset creation, upload, parse polling, append, cleanup, probe, diagnose,
  profile lint/explain/recommend/compare, smoke/regression/benchmark validation, and
  qrels-based metrics.
- Neutral query routing, route tests, host-assisted evidence, query traces, citation
  audit, and query diagnostic reports.
- Release hardening, vendored runtime, consumer acceptance, platform smoke matrix, and
  artifact security scanning.

The remaining gaps are higher-level product features: richer handoff packages, metadata
governance, benchmark governance, automated optimization loops, stricter chunk-level
evaluation, retrieval pollution diagnostics, route-gap diagnosis, multi-KB fusion, query
rewriting, context-aware query handling, optional agentic synthesis, and operational
resilience.

## Design Principles

### Preserve The Three-Skill Boundary

`ragflow-doc-to-md` should only produce clean Markdown, local assets, manifests, and
document-side quality metadata.

`ragflow-kb-build` should own ingestion, RAGFlow mutation, retrieval validation, chunk
profile behavior, metadata/tagset preparation, and build optimization.

`ragflow-query` should own routing, retrieval, evidence ranking, multi-KB result fusion,
query rewriting, optional LLM planning/synthesis, and query-level diagnostics.

Shared schemas and reusable logic should live in `ragflow-skill-runtime` and be vendored
into release artifacts.

### Keep Private Operations Out

The public suite may detect and explain problems that old skills fixed with direct
MySQL, Elasticsearch, systemd, or private config edits. It should not perform those
repairs by default.

Allowed public behavior:

- read-only diagnosis;
- generated remediation plan;
- explicit API-level mutation with dry-run and confirmation;
- exported reports a host agent can review.

Forbidden public defaults:

- direct DB writes;
- direct ES writes;
- private KB routing tables;
- personal vault paths;
- daemon installation;
- hardcoded model providers, hostnames, or home directories.

### Prefer Deterministic MVPs

For each old feature, start with a deterministic version. LLM-assisted behavior can be
added later as an opt-in adapter with explicit config and trace output.

## Second-Pass Gap Findings

The follow-up review found several useful old-skill features that were under-specified in
the first version of this document:

1. Benchmark governance is broader than validation. Old KB Ops included benchmark import,
   preflight gates, trend reports, delta reports, root-cause diagnoses, cost/latency
   thresholds, and public fixture gates. The new suite should treat these as first-class
   benchmark lifecycle commands, not just `validate --level benchmark`.
2. Grounded QA generation and evidence mapping close the loop between source documents,
   expected answers, chunk snapshots, and strict recall. This is stronger than manually
   authored qrels alone.
3. Route quality needs a hint-maintenance workflow: gap diagnosis, regex priority review,
   substring/word-boundary checks, English hint coverage, and category-based route tests.
4. Retrieval quality problems often come from pollution rather than missing recall. The
   old BM25 pollution analysis and suppression-candidate reports should become public
   diagnostics for tag, source, bridge-term, and rerank pollution.
5. Query UX needs safe orchestration states before full agentic synthesis: intent
   classification, clarification-needed, out-of-scope, low-confidence disclaimers, and
   session-aware pronoun/context resolution.
6. Long-running support jobs should use idempotent, bounded batches with resume/progress
   metadata. The old centroid fill pattern is useful, but public centroids must be
   user-generated from user-owned KBs and dynamic embedding config.

Third-pass review added delivery-hardening gaps that are easy to miss when focusing only
on user-facing commands:

1. Runtime capability checks should cover configured conversion backends, local CLI
   availability, optional warmup, timeout cleanup, and image fallback behavior. Public
   skills should not install or supervise daemons, but they can probe and report host
   readiness.
2. Model-provider readiness is separate from service reachability. RAGFlow may require
   provider registration, display-name consistency, empty-input handling, restart/bootstrap
   verification, and embedding-model rebuild warnings.
3. Cross-machine use should be modeled as endpoint/config validation, not localhost
   assumptions. The public suite needs safe reports for LAN/VPN/HTTPS endpoints without
   shipping real IPs or vault paths.
4. Acceptance flows should produce command manifests in dry-run mode. Host agents can then
   show the user exact redacted commands before live RAGFlow mutation.
5. Release readiness should include contract gates, installed-artifact smoke, compatibility
   facade checks, schema identity checks, and rename/naming drift policy.
6. Fallback behavior should be a measurable acceptance surface: LLM unavailable, malformed
   LLM output, timeouts, partial failure, direct retrieval fallback, and fallback metrics.

Fourth-pass review added topology and post-ingest gaps:

1. KB creation is a design decision, not just an API call. Old KB Ops used create/merge/split
   criteria such as independent terminology, minimum useful corpus size, semantic overlap,
   anchor query pairs, chunk volume, and domain purity. The public suite should offer a
   non-mutating KB topology advisor.
2. A new KB is not usable until it is activated in retrieval/routing. Old workflows checked
   content completeness, route-config registration, hints, centroid coverage, and route
   regression tests. The public suite should emit activation plans after build.
3. RAGFlux handoff included retrieval hints: section boundaries, table artifacts,
   keyword candidates, question candidates, profile-search boundaries, and quality risks.
   Rich handoff should preserve these as a public sidecar.
4. Post-ingest assistant configuration is a real deliverable. Old guides captured retrieval
   thresholds, vector/BM25 weights, top-k, prompt guardrails, quote requirements, and staged
   test cases. The new suite should generate assistant profiles and assistant test plans.
5. Parser performance telemetry is distinct from parse success. Old diagnostics tracked
   parse, keywords, questions, chunk, and embed phases, and warned about expensive
   `auto_questions`, visual layout, image/table context, and other slow-path parser config.

## Spec Coding Map

Use this matrix as the bridge between this design document and
`docs/03-development-plan.md`. Each implementation PR or agent coding session should pick
one phase, then implement the listed command surface, schema/report contracts, tests, and
documentation updates for that phase. If a feature spans two phases, the earlier phase owns
schema production and the later phase owns consumption or live workflow integration.

| Feature design | Owning skill | Development phase | Primary command/API surface | Contract artifacts | Required gates |
| --- | --- | --- | --- | --- | --- |
| 1. Rich Handoff 2.0 | `ragflow-doc-to-md`, `ragflow-kb-build` | Phase 24 | `ragflow-doc-to-md package --rich`, `ragflow-kb-build inspect-handoff` | `ragflow_handoff_package_v1`, `metadata.json`, `artifact_index.json`, `package_readme.md` | schema unit tests, CLI tests, consumer acceptance, platform smoke |
| 2. Markdown Post-Processing | `ragflow-doc-to-md` | Phase 24 | post-process profiles `none`, `safe`, `ocr`, `chunk-markers` | `postprocess_report.json` | deterministic rewrite tests, no-write-by-default tests, quality gate tests |
| 3. Metadata And Tagset Governance | `ragflow-kb-build` | Phase 25 | `metadata lint/merge/generate-template`, `tagset lint/export/report` | `ragflow_metadata_v1`, `ragflow_tagset_v1` | offline schema tests, merge precedence tests, redaction tests |
| 4. Optimization Loop | `ragflow-kb-build` | Phase 26 | `optimize --plan-only`, `optimize --execute` | `optimization_plan.json`, `profile_experiment_results.json`, `best_profile_report.md`, `cleanup_plan.json` | fake-client tests, explicit-mutation tests, live disposable tests when approved |
| 5. Chunk Snapshot And Strict Chunk Recall | `ragflow-kb-build` | Phase 26 | `snapshot-chunks`, `validate --level benchmark` extensions | chunk snapshot schema, qrels `expected_chunks` extension | stable-hash tests, strict-recall metrics tests |
| 6. Retrieval Enrichment Experiments | `ragflow-kb-build`, `ragflow-query` | Phase 27 | `profile experiment` or `optimize`, `suppression-report`, `pollution-report`, `rerank-ab` | enrichment experiment matrix, pollution/suppression reports | no-network fake reports, optional live disposable tests |
| 7. Multi-KB Fusion And RRF | `ragflow-query` | Phase 28 | `ask --fusion rrf`, `fusion`, `fusion-test` | `ragflow_fusion_report_v1` | offline fusion fixtures, no-LLM acceptance tests |
| 8. Query Rewrite, HyDE, And Cross-Language Expansion | `ragflow-query` | Phase 28 | `rewrite`, `ask --rewrite ...`, `ask --multi-query` | trace fields for original/generated/translated queries | deterministic rewrite tests, LLM-config gating tests |
| 9. Experimental Agentic Synthesis | `ragflow-query` | Phase 30 | `agentic-plan`, `agentic-answer`, `agentic-eval` | `ragflow_agentic_plan_v1`, `ragflow_agentic_trace_v1` | offline planner tests, explicit LLM-config tests, citation audit compatibility |
| 10. Generation Evaluation | `ragflow-query` | Phase 30 | `evaluate-answer` | answer evaluation report | deterministic citation/support tests, abstention tests |
| 11. Routing Quality Upgrade | `ragflow-query` | Phase 29 | `route-report`, `route-diagnose`, `centroid build --plan-only`, `centroid build` | route report, centroid build report, centroid index schema | route regression fixtures, no-private-route scan |
| 12. Runtime Resilience And Sanitized Reports | shared runtime, all skills | Phase 31 | retry/rate-limit/cache/checkpoint helpers, `--redaction-report` | sanitized report schema, partial-failure reports, cache stats | fake-secret redaction tests, timeout/fallback tests |
| 13. Benchmark Governance | `ragflow-kb-build` | Phase 26 | `benchmark import/sample/preflight/trend/delta/gate/summarize` | normalized benchmark manifest, `queries.json`, `qrels.json`, `qa.json` | import/sample/preflight tests, delta/gate tests |
| 14. Grounded QA And Evidence Mapping | `ragflow-kb-build` | Phase 26 | `qa generate/validate/map-evidence`, `segment-metadata report` | grounded QA and evidence mapping artifacts | evidence-span validation tests, generated-QA gate tests |
| 15. Retrieval Pollution And Suppression Diagnostics | `ragflow-query`, `ragflow-kb-build` | Phase 27 | `pollution-report`, `rerank-ab`, `suppression-report` | pollution and suppression reports | fake pollution fixtures, recommendation-only safety tests |
| 16. Query Orchestration Safety And Conversation Context | `ragflow-query` | Phase 30 | `intent classify/route`, `session enrich/inspect` | `ragflow_query_intent_v1`, `ragflow_query_route_decision_v1`, `ragflow_query_session_v1` | deterministic intent/session tests, bounded-context tests |
| 17. Skill Suite Review And Drift Control | release tooling | Phase 32 | `tools/release_hygiene_check.py --suite-review`, `tools/version_date_drift_check.py` | suite review findings, version/date drift report | static fixture tests, shared-doc hash checks, broken-link tests, version/date drift tests |
| 18. Runtime Capability, Model Provider, And Fallback Gates | all skills | Phase 31 | `backend probe/warmup`, `model-providers probe`, `endpoint-report`, `fallback-test` | backend capability report, model-provider report, fallback coverage report | fake endpoint tests, no-daemon tests, fallback coverage tests |
| 19. Contract, Packaging, And Compatibility Gates | release tooling | Phase 33 | contract fixtures, installed archive smoke, command-manifest dry-run | command manifest, schema identity reports, compatibility findings | installed-artifact smoke, command-manifest redaction tests |
| 20. KB Topology And Routing Activation Advisor | `ragflow-kb-build`, `ragflow-query` | Phase 34 | `topology advise`, `topology split-plan`, `activation-plan`, `route-activation-check` | `kb_topology_advice_v1`, `kb_split_plan_v1`, `kb_activation_plan_v1`, `ragflow_route_activation_check_v1` | advisory-only tests, neutral KB fixtures |
| 21. Handoff Retrieval Hints And Assistant Profiles | `ragflow-doc-to-md`, `ragflow-kb-build`, `ragflow-query` | Phase 24 and Phase 34 | rich sidecar generation, `assistant-profile recommend`, `assistant-test-plan` | `retrieval_hints.json`, `assistant_profile.json`, `assistant_test_plan.json`, `ragflow_assistant_profile_recommendation_v1`, `ragflow_assistant_test_plan_review_v1` | sidecar schema tests, review-artifact tests, no assistant mutation tests |
| 22. Parser Performance And KB Health Telemetry | `ragflow-kb-build` | Phase 35 | `parse-report`, `health-report` | parser performance report, KB health report | fake API/log tests, no DB/Redis repair tests |

Spec coding rules:

- Start every phase with runtime schemas and neutral fixtures, then add CLI command
  surfaces, then reports, then docs and host-agent references.
- Keep each new report JSON-first and Markdown-second. Markdown reports summarize JSON;
  they must not contain extra secrets or host-specific paths.
- Mutating RAGFlow operations must expose a non-mutating plan or dry-run first and require
  explicit execution flags.
- LLM-backed features must have deterministic offline fixtures and must be disabled until
  explicit LLM config is provided.
- Any command that can run live should emit enough artifact paths for Hermes/OpenClaw-style
  agents to produce a Chinese acceptance report without re-running the command.

## Feature Design 1: Rich Handoff 2.0

### Problem

The current `doc_manifest.json` is intentionally thin and portable. That is good for v0.1,
but older RAGFlux packages carried useful audit artifacts: package metadata, output
hashes, image/table artifacts, quality reports, profile suggestions, and package README
files. Those are valuable when documents move between agents or machines.

### Proposed Contract

Add an optional package mode, not a replacement for `doc_manifest.json`:

```text
handoff/
├── doc_manifest.json
├── metadata.json
├── quality_report.json
├── segmentation_plan.json
├── profile_suggestions.json
├── package_readme.md
├── documents/
│   ├── source.md
│   └── images/
└── artifacts/
    ├── tables/
    └── raw/
```

New schemas:

- `ragflow_handoff_package_v1`
- `ragflow_document_metadata_v1`
- `ragflow_profile_suggestions_v1`
- `ragflow_artifact_index_v1`

`ragflow-kb-build` should continue to consume `doc_manifest.json` first, then read optional
sidecars when they exist. It should not depend on private RAGFlux package internals.

### MVP Scope

- Add `ragflow-doc-to-md package --rich`.
- Add package hash and source metadata generation.
- Add optional `package_readme.md` for agent handoff.
- Add `ragflow-kb-build inspect-handoff` to summarize sidecars before upload.

## Feature Design 2: Markdown Post-Processing

### Problem

MinerU and other converters produce valid Markdown, but old RAGFlux added cleanup passes
that improved ingestion quality: heading repair, OCR punctuation fixes, safe image path
normalization, and optional chunk marker insertion.

### Proposed Behavior

Add deterministic post-processing profiles:

- `none`: no rewrite, only quality inspection.
- `safe`: normalize image paths, remove duplicate blank lines, repair obvious heading
  spacing, strip absolute temp paths.
- `ocr`: safe profile plus common OCR punctuation and whitespace fixes.
- `chunk-markers`: insert conservative marker comments at heading boundaries.

Outputs:

- rewritten Markdown under `documents/`;
- `postprocess_report.json`;
- diff summary with changed line counts and rule IDs.

Rules must be deterministic and explainable. Destructive rewriting should require
`--write` or a new output directory.

## Feature Design 3: Metadata And Tagset Governance

### Problem

Old KB Ops carried practical metadata and tag discipline. The new suite has manifests and
profiles, but it still lacks a neutral way to lint, merge, and export document metadata or
RAGFlow tagsets.

### Proposed Commands

In `ragflow-kb-build`:

```text
metadata lint
metadata merge
metadata generate-template
tagset lint
tagset export
tagset report
```

Safe public metadata fields:

- `domain`
- `topic`
- `module`
- `doc_type`
- `audience`
- `question_types`
- `entities`
- `summary`
- `locale`
- `status`
- `source_uri`
- `source_hash`

Metadata can be user-authored or LLM-assisted, but AI-generated metadata is advisory. It
must not become a security boundary or an authorization mechanism.

### MVP Contract

Phase 25 implements deterministic governance first:

- `ragflow_metadata_v1` keeps only safe public fields and reports ignored fields.
- `ragflow_tagset_v1` prepares tags, aliases, metadata defaults, and document
  assignments without mutating RAGFlow.
- Metadata merge precedence is explicit: path-derived fields < rich handoff metadata <
  user-authored metadata.
- Reports redact secret-like values and fail before build or validation when explicit
  metadata contains errors.
- Build and validation can attach metadata summaries with `--metadata`, but upload,
  parse, retrieval, and RAGFlow dataset settings are unchanged.
- LLM-assisted metadata generation remains a future adapter. Its output must be marked
  advisory and must pass the same deterministic lint before use.

## Feature Design 4: Optimization Loop

### Problem

The suite now has profile linting, benchmark validation, probe, diagnose, append, and
cleanup. What is missing is a single guided loop that runs profile experiments against a
disposable KB and recommends the best profile.

### Proposed Command

```text
ragflow-kb-build optimize
```

High-level flow:

1. Read a handoff and a candidate profile set.
2. Generate or load benchmark queries and qrels.
3. Create disposable KBs with clearly marked names.
4. Build each candidate.
5. Run benchmark validation.
6. Run diagnostics for failures.
7. Produce a best-profile report.
8. Offer cleanup plan and explicit cleanup execution.

Outputs:

- `optimization_plan.json`
- `profile_experiment_results.json`
- `best_profile_report.md`
- `cleanup_plan.json`

Mutation must be gated by `--execute`, and cleanup must require exact confirmation flags.

The optimization loop should be able to consume benchmark lifecycle artifacts from Feature
Design 13, including imported public benchmarks, generated QA sets, prior trend baselines,
and delta reports.

MVP `optimize --plan-only` creates an offline `ragflow_optimization_plan_v1` without
creating disposable KBs. It loads candidate profiles from explicit files,
directories, `ragflow_candidate_profile_set_v1` files, and generated recommendations,
resolves benchmark manifest artifacts, lints candidate profiles, assigns disposable KB
names, and reports naming collisions before any live execution is allowed.
Plan-only output includes disabled mutation command templates under `mutation_commands`;
ordinary `commands` do not contain an enabled disposable-KB build command, so experiment
KB creation remains gated on a future explicit `optimize --execute` path.
MVP `optimize summarize` then reads the plan plus existing validation reports and
produces `ragflow_profile_experiment_results_v1` plus a Markdown best-profile report with
metric tradeoffs and recommendation rationale. When a candidate validation report is
missing, failed, or has zero retrieved chunks, summarize runs local non-live diagnostics
from the candidate `kb_manifest.json` when available, writes the planned
`diagnostic_report.json`, and records pending diagnose commands when the manifest is not
available yet. It does not build KBs or run validation.
MVP `optimize cleanup-plan` reads the optimization plan and any available candidate
`kb_manifest.json` files, then produces a non-mutating `ragflow_optimization_cleanup_plan_v1`.
Targets with dataset IDs include exact-confirmation cleanup commands; targets without
manifests stay pending until disposable KB execution creates the manifests.

## Feature Design 5: Chunk Snapshot And Strict Chunk Recall

### Problem

Current benchmark validation can tell whether a query found a relevant document, but old
KB Ops workflows also cared about whether the exact expected chunk was retrieved. That is
important when tuning chunk sizes and overlap.

### Proposed Behavior

Add snapshot export:

```text
ragflow-kb-build snapshot-chunks
```

MVP snapshot export is offline and non-mutating. It accepts a validation/retrieval JSON
report or local Markdown input and emits `ragflow_chunk_snapshot_v1` with
`sha256:normalized-content-v1` stable hashes, source hashes, original chunk IDs when
present, aliases for strict qrels, chunk coverage fields, and per-document chunk
distribution. `validate --level benchmark --chunk-snapshot` can then match
`expected_chunks` against either the live chunk ID or the stable content hash, so
chunk-level recall remains measurable when RAGFlow chunk IDs are unstable.

Add validation metrics:

- strict chunk recall;
- expected chunk hit rate;
- expected evidence rank;
- chunk coverage by document;
- evidence-span-to-chunk mapping confidence;
- segment provenance metadata coverage;
- over-fragmentation and under-fragmentation warnings.

Qrels extension:

```json
{
  "query_id": "q1",
  "expected_documents": ["manual.md"],
  "expected_chunks": ["chunk-id-or-stable-hash"]
}
```

When RAGFlow chunk IDs are unstable, the suite can use stable content hashes as a fallback.

## Feature Design 6: Retrieval Enrichment Experiments

### Problem

Old KB Ops experimented with `auto_keywords`, `auto_questions`, tags, rerank, `vsw`, and
cross-language settings. The current profile tools can compare reports, but there is no
first-class experiment harness for retrieval enrichment.

### Proposed Behavior

Add `profile experiment` or integrate into `optimize`:

- vary `auto_keywords`;
- vary `auto_questions`;
- vary `tag_kb_ids` when provided by the user;
- vary `vsw`, `threshold`, `top_k`, and rerank switches;
- optionally vary query translation/cross-language expansion.

Reports should show quality, parse time, query latency, empty-result rate, and warnings
about cost or slow paths.

MVP `profile experiment` is offline and non-mutating. It reads a base chunk profile and a
`ragflow_enrichment_experiment_matrix_v1`, expands enrichment dimensions into inline
`ragflow_candidate_profile_set_v1` profiles for `optimize --profile-set`, and records
retrieval-only settings such as `top_k`, `threshold`, `vsw`, rerank switches, and
user-owned `tag_kb_ids` as local experiment metadata. The report warns about slow or
LLM-backed paths such as auto keyword/question enrichment, rerank, high `top_k`, and low
thresholds. It does not build KBs, run validation, call rerankers, or ship private tag
IDs in public fixtures.
MVP profile comparison and optimization summary reports also surface query latency, parse
time, empty-result rate, average chunk count, and benchmark quality scores when those
fields are present in existing validation or benchmark reports. They do not collect live
timing data on their own.

Enrichment reports should also call out pollution risk:

- tag pollution rate;
- wrong-document rate;
- bridge terms that repeatedly pull in unrelated chunks;
- source documents that dominate despite weak relevance;
- expected tag hit rate versus unexpected tag hit rate.

MVP benchmark validation derives wrong-document, tag pollution, expected-tag hit,
and unexpected-tag hit rates from qrels, query/qrel metadata, and retrieved chunk
metadata already present in validation reports. The metrics are offline diagnostics
and do not create, delete, or mutate RAGFlow tags or documents.

## Feature Design 7: Multi-KB Fusion And RRF

### Problem

Old smart-query and agentic-rag workflows often queried multiple KBs, then merged evidence.
The current suite supports route selection and explicit dataset lists, but it does not yet
offer an explainable fusion mode with stable scoring.

### Proposed Commands

In `ragflow-query`:

```text
ask --fusion rrf
fusion
fusion-test
```

Fusion features:

- run retrieval per selected KB;
- normalize scores per KB;
- deduplicate near-identical chunks;
- apply reciprocal rank fusion;
- preserve source KB, document name, score components, and rank explanation;
- export `ragflow_fusion_report_v1`.

MVP `ragflow-query fusion` reads multiple saved `ask --json` outputs, normalizes score
ranges per source, deduplicates exact chunk IDs and near-identical content, applies
reciprocal rank fusion, and emits source contribution details for every fused result. It
is offline and does not run retrieval itself; live `ask --fusion rrf` can build on the same
report schema later.

MVP `ask --fusion rrf` uses that same report schema when multiple dataset IDs are selected.
It calls RAGFlow retrieval once per dataset, preserves each per-KB source payload, and
returns fused chunks plus the fusion report in JSON output and trace data. Single-dataset
queries keep the normal direct retrieval path.

This should work without an LLM key.

## Feature Design 8: Query Rewrite, HyDE, And Cross-Language Expansion

### Problem

Old smart-query contained practical query translation and retrieval parameter tuning. Old
agentic-rag added query decomposition. The public suite needs a middle layer before full
agentic synthesis: deterministic or LLM-assisted query rewriting that still returns raw
evidence.

### Proposed Modes

```text
ragflow-query rewrite
ragflow-query ask --rewrite simple
ragflow-query ask --rewrite hyde
ragflow-query ask --rewrite translate
ragflow-query ask --multi-query queries.json
```

Rules:

- default off;
- show all generated queries in trace output;
- never hide original query results;
- require LLM config only for LLM-backed rewrite/HyDE modes;
- provide deterministic synonym/translation stubs for offline tests.

Rewrite and translation experiments should support A/B gates. For example, disabling
cross-language expansion must be rejected if it causes zero-result regressions or large
chunk-count drops. This preserves the old smart-query lesson: data beats assumptions.

Current public implementation includes deterministic rewrite planning for `none`,
`simple`, and `translate`, plus host-owned multi-query orchestration that keeps the
original query visible in trace and retrieval outputs. `hyde` remains an explicit LLM-gated
placeholder until a host-owned adapter is added.

## Feature Design 9: Experimental Agentic Synthesis

### Problem

`ragflow-query` currently provides host-assisted evidence and citation audit, which is the
right safe default. Some users will still want a turnkey agentic retrieval path with query
classification, planning, reflection, synthesis, citations, and cost traces.

### Proposed Scope

Add an experimental namespace:

```text
ragflow-query agentic-plan
ragflow-query agentic-answer
ragflow-query agentic-eval
```

Capabilities:

- classify query as `simple`, `moderate`, or `complex`;
- decompose complex queries into sub-queries;
- call existing direct/auto/fusion retrieval;
- run optional reflection with strict iteration budget;
- synthesize only from retrieved evidence;
- emit citations that can be checked by `audit-citations`;
- emit token, latency, and estimated cost traces.

The existing `ask --mode agentic --host-assisted` remains the recommended default for
agents that can synthesize answers themselves.

Current public implementation adds `ragflow-query agentic-plan` as a deterministic
non-executing planner. It emits `ragflow_agentic_plan_v1` with a
`ragflow_agentic_trace_v1` template, classifies intent and complexity, plans bounded
sub-queries, records a reflection budget, and does not call an LLM, retrieve from RAGFlow,
or mutate RAGFlow.

`ragflow-query ask --mode agentic --host-assisted` can execute the bounded retrieval
queries from that deterministic plan and return fused evidence plus the agentic plan in
JSON output and trace data. The retrieval execution also emits `ragflow_agentic_trace_v1`
with retrieval latency, planned versus actual retrieval calls, zero script-owned LLM calls,
model `null`, deterministic token estimates, and zero estimated script-owned LLM cost. It
also emits `ragflow_host_synthesis_contract_v1`, which tells the host to synthesize only
from returned evidence and use numeric `[n]` citations that can be checked by
`audit-citations`. It still does not run reflection or synthesize an answer; host-owned
synthesis remains the required final step.

## Feature Design 10: Generation Evaluation

### Problem

Retrieval metrics do not prove that a generated answer is faithful. Old agentic-rag used
RAGAS-style checks and citation audits. The current suite has citation audit, but not a
general answer-evaluation report.

### Proposed Command

```text
ragflow-query evaluate-answer
```

MVP checks:

- answer has citations when required;
- cited chunks exist;
- quoted facts are supported by evidence using deterministic overlap checks;
- answer includes unsupported-claim warnings;
- abstention behavior can be checked when no chunks are returned.

Current implementation:

- `ragflow-query evaluate-answer` emits `ragflow_answer_evaluation_report_v1`;
- checks are deterministic and offline, reusing saved `ask --json` outputs and numeric
  citation audit behavior;
- no LLM/RAGAS backend is invoked by the MVP.

Optional LLM/RAGAS backend:

- faithfulness;
- answer relevancy;
- context precision;
- context recall;
- drift report against prior evaluations.

## Feature Design 11: Routing Quality Upgrade

### Problem

The new suite has neutral routing hints and route regression tests. Old smart-query also
used per-KB retrieval parameters, centroid coverage, and strong route regression discipline.

### Proposed Additions

- `ragflow-query route-report`: show hint coverage, missing route tests, ambiguous rules,
  short-hint word-boundary risks, substring conflicts, missing retrieval params, and
  route-test pass rate.
- `ragflow-query route-diagnose`: classify failures as missing hint, regex-order issue,
  priority conflict, acceptable ambiguity, missing KB config, or low-confidence fallback.
  The MVP consumes user-owned route-test queries offline and only treats regex ordering as
  explicit when routing metadata marks a KB as order-sensitive.
- English hint coverage and word-boundary checks for short English names, abbreviations,
  and product terms.
- category, locale, and negative-class coverage reports for public route-test suites.
- optional centroid index generated from public user-owned KB manifests or snapshots;
- centroid scoring as a tie-breaker for equal positive hint scores, not a replacement
  for explicit user hints;
- per-KB retrieval parameter report and benchmark-derived suggestions;
- no shipped private route tables.

Centroid generation should follow an idempotent bounded-batch pattern: dry-run first,
consume only user-owned snapshot vectors, process at most `N` chunks per run, record
progress, and resume without duplicating completed work.
Centroid-aware routing should consume user-owned query vectors and must not call an
embedding API implicitly.

## Feature Design 12: Runtime Resilience And Sanitized Reports

### Problem

Long live runs need stronger operational behavior: retries, rate limits, partial failure
reports, and guaranteed redaction. Old systems accumulated many practical safeguards, but
some were host-specific.

### Proposed Runtime Features

- token-bucket rate limiter for RAGFlow and LLM calls;
- retry/backoff policy with retry budget in traces;
- circuit breaker for repeated service failures;
- local cache for read-only probe/list operations;
- report sanitizer that redacts API keys, bearer tokens, home paths, private IPs when
  configured, and accidental local config paths;
- `--redaction-report` for release and acceptance tests.

No daemon or Prometheus server is required. Reports should be file-based and portable.

## Feature Design 13: Benchmark Governance

### Problem

The current suite has benchmark validation, but the older KB Ops benchmark layer included
the surrounding lifecycle: importing benchmark datasets, checking readiness, comparing
trends, measuring deltas, and separating quality gains from pollution or cost regressions.

### Proposed Commands

In `ragflow-kb-build`:

```text
benchmark import
benchmark sample
benchmark preflight
benchmark trend
benchmark delta
benchmark gate
benchmark summarize
```

Capabilities:

- import public or user-local benchmark formats into normalized `queries.json`,
  `qrels.json`, `qa.json`, and `manifest.json`;
- sample deterministically with seed and strategy fields;
- compute source hashes for imported documents;
- run preflight checks before live benchmark execution;
- compare current summaries against a baseline;
- report metric deltas, including recall gain, nDCG gain, pollution cost, wrong-doc cost,
  empty retrieval delta, latency, and estimated cost;
- map regressions to root-cause hints such as `retrieval_coverage_gap`, `ranking_gap`,
  `tag_pollution`, `generation_grounding_gap`, `citation_gap`, and
  `cost_or_latency_regression`.

MVP root-cause hints are deterministic report annotations on `benchmark summarize`,
`benchmark gate`, `benchmark trend`, and `benchmark delta`. They consume existing numeric
metrics and baseline deltas only; they do not run live diagnostics, generate answers, or
mutate RAGFlow.

## Feature Design 14: Grounded QA And Evidence Mapping

### Problem

Manually authored qrels are valuable but expensive. Old KB Ops could generate grounded QA
sets from source documents, validate that evidence spans were actually present, and map
those spans to chunk snapshots for strict recall.

### Proposed Commands

In `ragflow-kb-build`:

```text
qa generate
qa validate
qa map-evidence
segment-metadata report
```

Capabilities:

- generate direct-fact, short-query, synonym, comparison, confusing-boundary, and
  negative-control questions;
- require every generated item to include grounded evidence spans;
- repair near-match evidence spans only above a threshold;
- map evidence spans to chunk IDs or stable chunk hashes from snapshots;
- measure segment provenance metadata coverage in retrieved chunks;
- export QA and mapping artifacts that can feed benchmark validation and optimization.

LLM-backed generation is optional. Deterministic validation of generated evidence is
required before using generated QA in a benchmark gate.

MVP `qa generate` is an offline deterministic scaffold generator. It reads `--sources`
or `--source-dir`, extracts exact source spans, and emits `ragflow_grounded_qa_v1`
items whose answers and evidence are copied verbatim from the source text. It supports
bounded counts, deterministic random selection, and source-span length limits. It does
not call an LLM, synthesize paraphrases, repair near matches, or mutate RAGFlow.

MVP `qa validate` is an offline exact-span checker. It accepts grounded QA JSON, requires
question, answer, and evidence fields by default, and verifies that evidence spans occur
verbatim in `--sources` or `--source-dir` inputs when source text is provided. It does not
call an LLM, repair near matches, or mutate RAGFlow.

MVP `qa map-evidence` maps exact QA evidence spans onto `ragflow_chunk_snapshot_v1`
chunks using `content` or `content_preview`, and exports per-item `expected_chunks`
references from stable hashes or chunk IDs. It also reports evidence mapping coverage,
deterministic mapping confidence, and mapped chunk coverage. It is deterministic and
offline; it does not repair near matches or query RAGFlow.

MVP `segment-metadata report` measures document metadata matches, segment-like document
paths, explicit segment hints, and segmentation-plan coverage in chunk snapshots. It is an
offline report and does not mutate RAGFlow.

## Feature Design 15: Retrieval Pollution And Suppression Diagnostics

### Problem

Old smart-query and KB Ops showed that weak retrieval is not always a recall problem.
Sometimes the pipeline retrieves too much of the wrong thing: BM25 translation pollution,
overbroad tags, bridge terms, source documents that dominate rankings, or generic overview
documents that suppress more specific evidence.

### Proposed Commands

In `ragflow-query` or `ragflow-kb-build` report tooling:

```text
ragflow-query pollution-report
ragflow-query rerank-ab
ragflow-kb-build suppression-report
```

Capabilities:

- detect likely BM25 pollution by comparing original query terms, translated/expanded
  terms, and returned chunk terms;
- compare RAGFlow ranking against optional external rerank results;
- identify low-risk bridge-term suppression candidates;
- identify high-risk allowed-tag or source-boundary candidates for human review;
- report unexpected tag/source hotspots;
- keep suppression as a recommendation report, not an automatic content mutation.

MVP `ragflow-kb-build suppression-report` reads existing validation or benchmark
validation JSON reports offline. It uses benchmark pollution metrics when present,
compares polluted query terms with returned chunk terms, groups suspect source and tag
hotspots, and emits review-only candidates with low-risk bridge-term and high-risk
allowed-tag/source-boundary scoring. Tag localization can use raw retrieved chunk payloads
from `validate.py --include-raw --max-report-chunks ...` and optional public tagset
labels/aliases, but raw payloads remain opt-in and the report never deletes documents,
edits tags, mutates RAGFlow, or installs hidden filters.

MVP `ragflow-query pollution-report` reads saved `ask --json` output, optional query
trace JSON, and optional expanded or translated term lists. It compares original query
terms against expanded-term-only chunk hits, low original query coverage, repeated bridge
terms, and source dominance. The command is an offline advisory report; it does not call
RAGFlow, translate queries, run BM25 itself, mutate route configs, or install filters.

MVP `ragflow-query rerank-ab` reads saved `ask --json` output and optional external rerank
JSON. It matches chunks by chunk ID, stable content hash, or content-derived hash, then
reports rank movement, top-k overlap, top-rank changes, and expected term/chunk hit
changes. When no external rerank JSON is supplied, it uses deterministic host evidence
scores as a local candidate ordering. The command is offline and does not call or bundle a
reranker service.

Optional external rerankers must be configured by the host and treated as remote/local
services, not bundled daemons.

## Feature Design 16: Query Orchestration Safety And Conversation Context

### Problem

Before full agentic synthesis, `ragflow-query` needs a safe orchestration layer that can
decide whether to retrieve, ask for clarification, reject an out-of-scope request, or add a
low-confidence disclaimer. Old query-understanding code also had useful session-context
handling for pronouns and follow-up queries.

### Proposed Commands

In `ragflow-query`:

```text
intent classify
intent route
session enrich
session inspect
```

Capabilities:

- classify `knowledge_query`, `comparison`, `clarification_needed`, and `out_of_scope`;
- return confidence and route decisions as structured JSON;
- resolve simple follow-up references such as "this", "that", "above", and omitted
  subjects from recent session history;
- enforce a turn count and token budget for session context;
- route low-confidence queries with explicit warnings;
- keep retrieval responses in normalized states: `success`, `empty`, `low_quality`,
  `needs_refinement`, `clarification`, `rejected`, `error`, `timeout`, and `partial`.

This layer should be deterministic by default and LLM-assisted only when explicitly
configured.

Current public implementation adds deterministic `ragflow-query intent classify` and
`ragflow-query intent route`. They emit `ragflow_query_intent_v1` and
`ragflow_query_route_decision_v1`, classify `knowledge_query`, `comparison`,
`clarification_needed`, and `out_of_scope`, include confidence labels and low-confidence
disclaimers, and do not retrieve, mutate RAGFlow, or call an LLM.

`ragflow-query ask` also emits a normalized `retrieval_status` and
`ragflow_retrieval_status_v1` report in JSON output, metadata, and traces. Statuses are
bounded to `success`, `empty`, `low_quality`, `needs_refinement`, `clarification`,
`rejected`, `error`, `timeout`, and `partial`.

Session context is implemented through deterministic `ragflow-query session inspect` and
`ragflow-query session enrich`. They normalize user-owned `ragflow_query_session_v1`
turns, enforce `--max-turns` and `--max-tokens`, detect short follow-ups and pronoun
references, and enrich queries only with bounded recent context. They do not retrieve,
mutate RAGFlow, or call an LLM.

## Feature Design 17: Skill Suite Review And Drift Control

### Problem

The old `skill-two-pass-review-methodology` captured a practical maintenance problem:
multiple related skills drift over time. Trigger phrases overlap, shared references diverge,
version statements go stale, and old pitfalls or paths remain in one skill after another
skill has moved on.

### Proposed Checks

Extend release hygiene with a skill-suite review mode:

```text
tools/release_hygiene_check.py --suite-review
```

Checks:

- frontmatter validity for every `SKILL.md`;
- trigger and description overlap across the three public skills;
- stale references to removed or private skills;
- shared reference/template hash consistency;
- public paths in examples are placeholders or environment-variable based;
- broken relative links inside `SKILL.md` and `references/`;
- accidental legacy or experimental product-name drift in the public release surface;
- declared compatibility references for deprecated aliases and schema names;
- duplicated warnings that should be centralized;
- version/date drift between docs, manifests, and release artifacts.

This should remain a static/offline release check. It should not load private old skills or
scan outside the current repository in normal release mode.

Implementation status: the first `--suite-review` gate is implemented as an offline
release-hygiene mode. It validates public `SKILL.md` frontmatter, required shared
references, shared-reference hash drift, broken relative links, stale/private references,
and high-overlap skill descriptions with fixture coverage. Accidental public naming drift
and declared compatibility references are now covered by the default rename-governance
release gate from Feature Design 19. Version/date drift is now covered by
`tools/version_date_drift_check.py`, which emits `ragflow_version_date_drift_check_v1`
and runs by default from release hygiene. It compares runtime/package version declarations,
release-manifest/build/export major-minor metadata, deterministic release manifest dates,
documented stable release versions, and any declared public skill version/date metadata.
Repeated warning centralization is now covered by the suite-review gate through
`skill_suite_repeated_warning` findings and `repeated_warning_count` summary metadata.
The check ignores intentionally duplicated shared references and reports copied warning
guidance in public `SKILL.md` files that should instead link to
`references/host-agent-setup.md`. The repeated config/key warning previously copied in
each public `SKILL.md` has been centralized through that shared reference. A private
`ragflow-skills-maintainer` Codex skill now records repository-specific development
workflow, validation-chain, task-selection, and release-governance guidance outside the
public release skill tree; maintainer-only skills must not be added under public `skills/`.

## Feature Design 18: Runtime Capability, Model Provider, And Fallback Gates

### Problem

Old RAGFlux and KB Ops work found that "the endpoint is reachable" is not enough. A host may
have a local MinerU CLI but missing models, a MinerU HTTP wrapper with the wrong protocol,
a RAGFlow model provider registered but not usable by parsing, an embedding service that
rejects empty input, or an LLM helper that times out and must fall back to direct retrieval.

### Proposed Commands

Across the suite:

```text
ragflow-doc-to-md backend probe
ragflow-doc-to-md backend warmup
ragflow-kb-build model-providers probe
ragflow-query fallback-test
ragflow-query endpoint-report
```

Capabilities:

- classify configured conversion backends as `available`, `missing`, `wrong_protocol`,
  `timeout`, or `not_configured`;
- run an optional tiny warmup fixture for local or remote converters when the user asks;
- verify timeout cleanup reports without managing a permanent service;
- report image fallback as `PASS_WITH_REVIEW`, preserving the source image when OCR is not
  available;
- verify RAGFlow embedding/rerank provider presence, provider display name, and read-only
  provider response shape when credentials are available;
- warn when an embedding model change requires KB rebuild or re-parse;
- test optional embedding/rerank adapter request shape and empty-input behavior using fake
  or configured endpoints;
- run fallback fixtures for LLM unavailable, malformed JSON, network timeout, partial
  success, and direct retrieval fallback;
- emit fallback coverage and fallback success-rate metrics.

Implementation status: backend probes/warmup, image fallback review gates, model-provider
probes, adapter request-shape probes, `ragflow-query endpoint-report`,
`ragflow-query fallback-test`, and the shared report sanitizer are implemented. Broader
`--redaction-report` coverage remains open, but sidecar coverage now includes
`ragflow-doc-to-md backend probe`, `ragflow-kb-build model-providers probe`, and
`ragflow-query endpoint-report`, `ragflow-query evaluate-answer`, and
`ragflow-query diagnose-result`, `ragflow-query pollution-report`, and
`ragflow-query rerank-ab`, `ragflow-query cross-language-ab`, `ragflow-query fusion`, and
`ragflow-query fusion-test`, `ragflow-query route-test`, `ragflow-query route-report`,
`ragflow-query route-diagnose`, `ragflow-query route-activation-check`,
`ragflow-query assistant-profile recommend`, `ragflow-query assistant-test-plan`,
`ragflow-query rewrite`, `ragflow-query intent classify`, `ragflow-query intent route`,
`ragflow-query session inspect`, `ragflow-query session enrich`, and
`ragflow-query agentic-plan`, `ragflow-query audit-citations`,
`ragflow-query fallback-test`, `ragflow-query centroid build --plan-only`, and
`ragflow-query centroid build`.
Release hygiene now emits
`ragflow_generated_report_safety_check_v1`, scanning generated reports and examples for raw
sensitive literals and requiring valid redaction sidecars when redaction placeholders are
present. Consumer acceptance includes a fake generated-report fixture with fake secret,
private endpoint, and config-path inputs to prove sanitized output plus sidecar behavior
without live endpoints. Public host-agent setup references now document private per-run
storage for sanitized reports and redaction sidecars, and forbid sharing raw reports,
private endpoints, config paths, key fragments, or host logs in transcripts.

Post-Phase 35 sequencing should finish generated-report safety before broad runtime helper
work. First extend `--redaction-report` coverage to remaining report commands that can
include endpoints, config paths, work paths, or host-supplied sidecar paths. Then add the
smallest retry/backoff and metrics helpers with retry budgets and latency summaries in one
or two consuming commands. Rate limiting, circuit breakers, cache invalidation,
checkpoint/resume, and partial-failure schemas should follow only after the narrow helper
path is covered by deterministic tests.

All reports must redact endpoints according to release settings and must not include real
API keys or host-specific paths.

Current public implementation adds `ragflow-doc-to-md backend probe`, which emits
`ragflow_doc_backend_probe_report_v1` and classifies configured conversion backends as
`available`, `missing`, `wrong_protocol`, `timeout`, or `not_configured`. By default it
performs local/configuration checks only; bounded endpoint reachability is opt-in through
`--network-check`. The main conversion command now records local process-backed converter
attempts in `ragflow_doc_runtime_report_v1` when they run, including timeout cleanup,
signals sent, and leftover process counts without storing full command lines or host paths.
`ragflow-doc-to-md backend warmup` now runs only when the user supplies an explicit tiny
fixture with `--fixture`, emits `ragflow_doc_backend_warmup_report_v1`, and can fail CI via
`--fail-on-failed`. Main document conversion now preserves image sources as Markdown
fallbacks when OCR/conversion is unavailable, copies the source image into the handoff, and
marks the quality gate `PASS_WITH_REVIEW`.
`ragflow-kb-build model-providers probe` now emits
`ragflow_model_provider_probe_report_v1`, checks read-only candidate provider endpoints,
records response-shape summaries, normalizes provider display names and embedding/rerank
model entries, and can warn when expected embedding or rerank model names are not visible.
When explicit adapter URLs are supplied, the same report now probes embedding and rerank
empty-input request shapes with redacted endpoint summaries and classifies bounded
HTTP 200/400/422 behavior as handled empty input. `ragflow-kb-build health-report
--expected-embedding-model` now compares local KB manifests with the intended embedding
model and emits advisory rebuild/re-parse warnings when a built KB records a different
model. Unit, consumer-acceptance, and platform smoke tests use fake endpoints or neutral
sidecars for these probes.

## Feature Design 19: Contract, Packaging, And Compatibility Gates

### Problem

The old release checklists were valuable because they tested not just source code, but the
installed artifact, connector handoff contract, naming identity, compatibility facades, and
rollback rules. The public suite already has strong release tooling, but third-pass review
shows these gates should be explicit product requirements.

### Proposed Gates

Extend release tooling with:

- contract fixture gates between `ragflow-doc-to-md` and `ragflow-kb-build`;
- installed release artifact smoke for each skill archive;
- command-manifest dry-run for live acceptance flows;
- compatibility facade checks for deprecated command aliases or schema names;
- schema identity checks for manifests and reports;
- naming drift checks for accidental old/new product names;
- explicit rename policy requiring CLI aliases, schema migration, docs, downstream gates,
  release notes, and rollback plan before any public rename.
- host-agent forward-test prompt templates for validating installed release archives from
  Hermes and OpenClaw.

Acceptance dry-run manifests should include:

- local configuration checks;
- redacted command arrays;
- expected produced artifacts;
- which commands mutate RAGFlow;
- cleanup notes and dataset IDs once live execution occurs.

Recommended implementation sequence:

1. Add a focused offline contract fixture gate before broader packaging work. The MVP
   should create neutral plain and rich handoff fixtures with `ragflow-doc-to-md`, run
   `ragflow-kb-build --dry-run` against both, and emit `ragflow_contract_fixture_gate_v1`.
   It should run against release/dist scripts, use only placeholder KB names, and never
   contact RAGFlow.
2. Add installed archive smoke next, with one minimal no-network check per exported tarball.
   This should prove archive contents work after unpacking, independently from source-tree
   smoke and broader consumer acceptance.
3. Add command-manifest dry-run after archive smoke. These manifests should make live
   acceptance reviewable before mutation by listing redacted commands, expected artifacts,
   mutation labels, cleanup notes, and local config checks.
4. Add schema identity, compatibility facade, rename policy, and naming-drift checks after
   the contract and archive surfaces are explicit. These are static release gates and should
   not depend on live services.
5. Add host-agent forward-test prompt templates after archive smoke exists. These templates
   should ask Hermes/OpenClaw-style agents to validate installed artifacts from
   `release-artifacts/`, not the source tree, and should remain no-network/no-mutation.

Implementation status: the offline contract fixture gate is implemented in
`tools/contract_fixture_gate.py`. It rebuilds or reuses release/dist skill scripts, creates
neutral plain and rich handoffs with `ragflow-doc-to-md`, proves both are accepted by
`ragflow-kb-build --dry-run`, inspects the rich handoff sidecars, and emits
`ragflow_contract_fixture_gate_v1` without requiring RAGFlow credentials. The installed
archive smoke gate is implemented in `tools/installed_archive_smoke.py`; it exports or
reuses release tarballs, verifies manifest hashes, safely unpacks each public skill archive
in an independent workspace, checks vendored runtime presence, and runs a minimal no-network
CLI smoke per skill while emitting `ragflow_installed_archive_smoke_v1`. Command-manifest
dry-run is implemented in `tools/consumer_acceptance.py` with
`ragflow_consumer_command_manifest_v1`, `--command-manifest`, and
`--command-manifest-only`. It writes redacted command arrays plus a redaction sidecar,
records local configuration checks, expected artifacts, mutation labels, and cleanup notes,
and can review live/live-build acceptance commands without executing live mutation. Fixture
coverage uses fake credentials and private paths to prove the generated manifest does not
leak secrets, localhost endpoints, config paths, or work paths. Schema identity checks are
implemented in `tools/schema_identity_check.py` and run by default from
`tools/release_hygiene_check.py`. The gate emits `ragflow_schema_identity_check_v1` and
requires source plus test/smoke evidence for versioned `doc_manifest`/`kb_manifest`
identity and quality, benchmark, query, trace, diagnostic, route, topology, KB health,
and release-governance report schemas.
Rename governance is implemented in `tools/rename_governance_check.py` and also runs by
default from `tools/release_hygiene_check.py`. It emits
`ragflow_rename_governance_check_v1`, validates the explicit public rename policy in
`docs/11-public-rename-policy.md`, checks declared compatibility aliases, and scans the
public release surface for accidental legacy naming drift. CLI and schema aliases are
currently not declared, so command/schema compatibility checks report `not_applicable`;
existing platform-profile aliases are covered by source, docs, and tests. Host-agent
forward-test prompt governance is implemented in `tools/forward_test_prompt_check.py` and
runs by default from `tools/release_hygiene_check.py`. It emits
`ragflow_forward_test_prompt_check_v1`, validates
`docs/12-release-archive-forward-test-prompts.md`, and checks that Hermes/OpenClaw
templates validate installed release archives without repository edits, network calls,
real credentials, or live mutation.

These gates should complement, not replace, unit tests and platform smoke tests.

## Feature Design 20: KB Topology And Routing Activation Advisor

### Problem

`ragflow-kb-build` can create and validate a KB, but old KB Ops showed that users also need
help deciding whether to create a new KB, merge into an existing KB, split a large KB, or
activate a freshly built KB in the query routing layer.

### Proposed Commands

In `ragflow-kb-build` and `ragflow-query`:

```text
ragflow-kb-build topology advise
ragflow-kb-build topology split-plan
ragflow-kb-build activation-plan
ragflow-query route-activation-check
```

Signals:

- terminology independence;
- minimum useful corpus size and future-growth hints;
- semantic overlap with existing KB manifests or route config;
- anchor query pairs that distinguish two candidate KBs;
- cross-domain chunk count and ambiguous-term score;
- dominant-document share;
- route config registration;
- hint coverage;
- optional centroid availability;
- route-test readiness.

Outputs:

- `kb_topology_advice_v1`
- `kb_split_plan_v1`
- `kb_activation_plan_v1`
- `ragflow_route_activation_check_v1`

All recommendations are advisory. The public suite should not automatically merge, split,
rename, or register KBs without explicit user-owned config edits.

Implementation status: initial topology advice, split planning, and activation planning
are implemented in `ragflow_skill_runtime.topology` and exposed as `ragflow-kb-build
topology advise`, `ragflow-kb-build topology split-plan`, and `ragflow-kb-build
activation-plan`. They emit `kb_topology_advice_v1`, `kb_split_plan_v1`, and
`kb_activation_plan_v1`, read local Markdown/doc manifests plus optional public metadata,
rich-handoff `retrieval_hints.json`, user-owned routing config, chunk snapshots, centroid
indexes, and route-test files when relevant, then report create-vs-merge signals,
split-review signals, sidecar KB grouping suggestions, activation readiness checks,
anchor/boundary query pairs, and route-test starter questions without touching RAGFlow or
route files. `ragflow-query route-activation-check` now consumes `kb_activation_plan_v1`,
the user-owned route config, route-test queries or a saved route-test report, and an
optional centroid index, then emits `ragflow_route_activation_check_v1` with activation
drift, missing route coverage, stale-plan inputs, and route-test readiness. It does not
write route config, rebuild centroids, call live RAGFlow, or apply assistant settings.

## Feature Design 21: Handoff Retrieval Hints And Assistant Profiles

### Problem

RAGFlux packages carried `retrieval_hints.json`, which included section boundaries, table
artifacts, keyword candidates, question candidates, preferred chunk boundaries, and quality
risks. Old RAGFlux guides also generated assistant-facing retrieval and prompt guidance
after ingestion. The current rich handoff design mentions profile suggestions but does not
fully preserve these retrieval and assistant hints.

### Proposed Sidecars

Add optional rich-handoff sidecars:

- `retrieval_hints.json` with schema `ragflow_retrieval_hints_v1`;
- `assistant_profile.json` with schema `ragflow_assistant_profile_v1`;
- `assistant_test_plan.json` with schema `ragflow_assistant_test_plan_v1`.

Capabilities:

- capture section boundaries, heading levels, line ranges, table/image/list counts, and
  boundary markers;
- capture table artifacts and image-rich sections;
- generate keyword and question candidates from headings and metadata;
- recommend retrieval parameters such as similarity threshold, vector/BM25 weight, top-k,
  and quote/citation settings;
- generate staged assistant tests: exact numeric facts, OCR/image facts, logical flow,
  paraphrase, summary, and negative/boundary questions;
- keep prompts and assistant profiles as reviewable files, not hidden runtime behavior.

`ragflow-kb-build inspect-handoff` should summarize these sidecars. `ragflow-query` may
consume an assistant profile for local test planning, but it should not mutate RAGFlow chat
assistant settings automatically.

Implementation status: rich-handoff sidecars for retrieval hints, assistant profiles, and
assistant test plans are generated as review artifacts by `ragflow-doc-to-md package
--rich` and surfaced by downstream acceptance/smoke checks. `ragflow-query
assistant-profile recommend` consumes `assistant_profile.json` plus optional
`retrieval_hints.json` offline and emits `ragflow_assistant_profile_recommendation_v1`
with advisory-only settings for `top_k`, similarity threshold, vector/BM25 weights,
quote/citation behavior, and no-answer policy. `ragflow-query assistant-test-plan`
consumes `assistant_test_plan.json` plus optional assistant profile and retrieval hints,
then emits `ragflow_assistant_test_plan_review_v1` with stage coverage, case readiness,
profile consistency, and offline-only execution guards. These commands do not run an
assistant, call an LLM, modify RAGFlow assistant settings, or mutate route/KB config.

## Feature Design 22: Parser Performance And KB Health Telemetry

### Problem

Parse success alone does not reveal why a KB is slow or fragile. Old KB Ops tracked parse
phase timings and found bottlenecks such as `auto_questions`, visual layout recognition, and
image/table context settings. It also performed periodic KB health checks for model
distribution, chunk completeness, and route coverage.

### Proposed Commands

In `ragflow-kb-build`:

```text
parse-report
health-report
```

Capabilities:

- summarize document parse states and chunk counts;
- report phase timings when RAGFlow exposes task progress messages or host-provided logs;
- warn about expensive parser config fields such as `auto_questions`, excessive
  `auto_keywords`, visual layout recognition on large Markdown, image/table context size,
  and unsupported parser keys;
- compare KB detail counts with document-list counts to detect stale or lazy list fields;
- summarize embedding model distribution across selected KBs;
- summarize route activation status for selected KBs;
- produce public remediation suggestions that prefer API-level or config-level actions.

MVP `parse-report` is implemented as an offline `ragflow_parse_report_v1` review surface.
It consumes `kb_manifest.json`, optional user-supplied document status JSON, optional parse
logs, and optional profile/parser-config sidecars. It reports normalized document states,
parse-log error/timing hints, chunk-count mismatches, stale/lazy detail-count signals, and
expensive or unsupported parser settings. MVP `health-report` is implemented as an offline
`ragflow_kb_health_report_v1` aggregate surface. It consumes one or more `kb_manifest.json`
files plus optional `parse-report` and `activation-plan` sidecars, then summarizes embedding
model distribution, zero-document/zero-chunk risks, stale or failed parse risks, route
activation readiness, optional expected-embedding-model rebuild/re-parse warnings, and
parser-performance recommendations. Both reports record zero RAGFlow, DB, Redis, Docker,
and system-service calls.

Direct DB/Redis repair remains out of scope for public commands. Reports may explain that a
private operator should inspect task queues, but the public suite should not execute DB or
Redis cleanup.

## Implementation Notes And Pitfalls

- Keep public fixtures neutral. Convert old private benchmarks, hints, and KB names into
  placeholder examples or tiny synthetic fixtures before shipping.
- Keep `SKILL.md` concise. Detailed new workflows should go into `references/` or repo
  docs, and `SKILL.md` should only point agents to the right reference when needed.
- Treat host runtime management as a boundary. Public skills can probe, warm up on request,
  and report cleanup instructions, but should not install system services or keep daemons
  alive by default.
- Do not conflate endpoint health with RAGFlow usability. Model provider checks should
  verify RAGFlow registration, request shape, and rebuild implications when possible.
- Keep KB topology advice non-mutating. Splitting, merging, route registration, and hint
  edits should be emitted as plans for user-owned config, not applied silently.
- Treat assistant profiles as review artifacts. The suite can generate prompt and retrieval
  recommendations, but should not silently modify a RAGFlow chat assistant.
- Parse performance reports should use public API data or user-supplied logs. They must not
  execute DB/Redis repair in public release artifacts.
- Prefer command manifests for live acceptance. A dry-run manifest lets a host agent show
  exact redacted commands before the user approves mutation.
- Treat route tests as regression gates. Any hint change should have a route-test delta,
  and acceptable ambiguity should be recorded explicitly.
- Do not make cross-language changes from intuition. Require A/B reports that track
  chunk counts, zero-result rate, top-1 document stability, similarity deltas, and latency.
- Keep external rerank optional. The public suite may emit adapter contracts, but must not
  assume a local TEI, Xinference, vLLM, or vendor endpoint exists.
- Record original query, generated query, translated query, and retrieval params in traces
  whenever rewrite, translation, HyDE, or rerank is enabled.
- Make long-running jobs resumable. Centroid builds, benchmark imports, optimization
  experiments, and large report generation should support dry-run, batch size, checkpoint,
  and resume semantics.
- Never turn suppression candidates into automatic deletes or hidden filters. Suppression
  reports are review artifacts until the user explicitly changes metadata, tagsets, or
  routing config.

## Explicit Non-Goals

Do not migrate these old-skill behaviors into public defaults:

- direct MySQL or Elasticsearch repair;
- private dedao ingestion and routing examples;
- personal vault paths or hostnames;
- long-lived HTTP services as required runtime;
- systemd unit generation;
- hardcoded DeepSeek, Tongyi, or local model providers;
- direct raw PDF upload to RAGFlow as the primary path;
- public default daemon installation, systemd units, Docker networking changes, or model
  service bootstrapping.

Direct raw upload / DeepDoc can be considered later as a limited fallback command, but it
must not replace the Markdown handoff contract or bypass document quality reports.

## Phased Roadmap

Recommended implementation order is the Phase 24-35 task list in
`docs/03-development-plan.md`:

1. Phase 24: Rich Handoff 2.0 and Markdown Post-Processing.
2. Phase 25: Metadata and Tagset Governance MVP.
3. Phase 26: Benchmark Governance, Optimization Loop, Grounded QA, Evidence Mapping, and Strict Chunk Recall.
4. Phase 27: Retrieval Enrichment Experiments and pollution/suppression diagnostics.
5. Phase 28: Multi-KB Fusion and Query Rewrite MVP.
6. Phase 29: Routing Quality Upgrade with hint-gap, English-hint, A/B, and centroid workflows.
7. Phase 30: Query Orchestration Safety, Experimental Agentic Synthesis, and Generation Evaluation.
8. Phase 31: Runtime Resilience, sanitized reports, model-provider probes, fallback coverage, and resumable jobs.
9. Phase 32: Skill Suite Review and Drift Control.
10. Phase 33: Contract, Packaging, and Compatibility Gates.
11. Phase 34: KB Topology, Routing Activation, and Assistant Profiles.
12. Phase 35: Parser Performance and KB Health Telemetry.

This order keeps the foundation document-centric before adding more complex query-time and
LLM-assisted behavior, then finishes with release governance and post-ingest operational
guidance.
