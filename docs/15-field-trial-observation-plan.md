---
doc_type: plan
topic: field-trial-observation
status: active
created: 2026-07-02
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
---

# Field Trial Observation Plan

Status: active observation gate
Date: 2026-07-02

## Objective

Use the existing public skill suite in real workflows before opening any remaining gated
implementation work. The goal is to collect enough sanitized evidence to decide whether a
local service wrapper, product adapter, optional script-owned LLM backend, or private
bridge is actually needed.

This plan is intentionally observational. It does not add public command behavior, default
hosted services, script-owned model calls, live mutation, or private product logic.

## Observation Boundary

Public records may include:

- command names and sanitized flags;
- source type, approximate document count, and approximate size;
- artifact type and relative artifact names;
- elapsed time, pass/fail status, and summarized report metrics;
- redacted error classes and friction notes;
- a gated-work recommendation.

Public records must not include:

- API keys, bearer tokens, cookies, or secret fragments;
- real private endpoints, private IPs, or private hostnames;
- full home paths or private config paths;
- private KB names, private corpus names, or proprietary document titles;
- raw retrieved chunk text, raw model prompts, or raw model responses;
- private adapter implementation notes that belong outside public release artifacts.

Raw local artifacts can be retained under a private run directory, but public summaries
should keep only sanitized findings and paths that are safe to share.

## Signals To Watch

| Track | Signals | Evidence to collect |
| --- | --- | --- |
| CLI sufficiency | Repeated command spawning is slow, artifact handoff is brittle, or host agents struggle to preserve paths between steps. | Workflow name, command count, elapsed time, failed step, and whether one-shot CLI was enough. |
| `ragflow-query serve` | A host needs health checks, request IDs, persistent state, high request volume, explicit shutdown, or lower per-call latency than CLI spawning can provide. | Target host, CLI insufficiency, request profile, lifecycle owner, auth/redaction expectations, and success/failure criteria. |
| Handoff quality | `doc_manifest.json` is missing, invalid, blocked by quality gate, references missing assets, or contains empty/garbled Markdown. | `convert --json`, `inspect` summary, quality gate status, document count, warning classes, and sanitized report paths. |
| KB build stability | `build --dry-run` fails, parser settings are unclear, live parse stalls, cleanup is risky, or runtime partial failures repeat. | Dry-run result, profile ID, probe result, runtime metrics, parse report summary, and cleanup readiness summary. |
| Query quality | Zero results, wrong top document, unstable top-k, weak citation coverage, unsupported answer claims, or poor follow-up behavior. | Query mode, validation report summary, trace summary, `audit-citations` result, `evaluate-answer` result, and expected metric movement. |
| Private handoff bridge | Private content can or cannot become an ordinary Markdown handoff without a custom adapter. | Sanitized source shape, handoff result, whether passthrough produced `doc_manifest.json`, and why adapter code would be needed. |
| Remote conversion | Existing builtin, MinerU, generic remote, and local CLI conversion paths do not match a real converter contract. | Endpoint protocol summary, auth shape, request/response examples with fake values, error model, and fake-server fixture requirements. |
| Provider abstraction | A concrete non-current provider contract is needed and cannot fit existing OpenAI-compatible or request/review paths. | Provider label, API shape, config keys, fake-provider fixture, fallback behavior, and downstream acceptance criteria. |
| Reranker adapter | Saved-query or benchmark evidence shows retrieval/fusion/rewrite/profile tuning is insufficient and reranking has a measurable target. | Saved query output, external rerank JSON if available, benchmark delta, expected metric movement, and direct-retrieval fallback policy. |
| Optional LLM backend | Request/review workflows work but manual external model use becomes repetitive or error-prone. | Request/review frequency, failure classes, fake-provider requirements, advisory marking, citation compatibility, and redaction needs. |
| Release health | Real use changes assumptions about archives, runtime wheels, vendoring, platform smoke, or generated report safety. | Validation command list, pass/fail result, generated artifact list, and release-hygiene notes. |

## Per-Run Record Template

Create one short record per meaningful real workflow. Keep private details outside the
public repository and paste only sanitized summaries into public planning notes.

```markdown
## YYYY-MM-DD run-NNN

Workflow:
- doc-to-md / kb-build / query / private-handoff / host-agent / release-validation

Input summary:
- Source type:
- Approximate document count:
- Approximate size:
- Private details removed:

Commands:
- Sanitized command or command group:

Artifacts:
- Public-safe artifact names:
- Private artifact location retained outside public repo:

Results:
- Pass/fail:
- Elapsed time:
- Quality gate:
- Build/probe/parse status:
- Query or validation summary:

Friction:
- What was slow, brittle, unclear, repetitive, or unsafe:

Gated trigger:
- none / serve / private bridge / remote conversion / provider / reranker / LLM backend

Decision:
- keep observing / open design gate / implement focused slice / reject for now
```

## Trigger Rules

Open gated implementation only when observation evidence crosses one of these thresholds:

- `ragflow-query serve`: at least three real host-agent runs show one-shot CLI is the
  wrong shape, or one critical host workflow requires health, lifecycle, request
  correlation, or persistent endpoint semantics.
- Private bridge: at least one real private workflow cannot reliably produce a public
  Markdown `doc_manifest.json` handoff through passthrough conversion.
- Remote conversion client: a user-owned converter endpoint has a concrete protocol,
  auth shape, request/response examples, error model, and fake-server fixture plan.
- Provider abstraction: one named provider contract cannot fit current config,
  OpenAI-compatible behavior, or request/review artifacts, and has a fake-provider test
  plan.
- Reranker adapter: saved-query or benchmark evidence defines a measurable ranking target
  that current retrieval, fusion, rewrite, profile tuning, or `rerank-ab` comparison
  cannot cover.
- Optional LLM backend: request/review artifacts are stable, manual external model use is
  a real bottleneck, and fake-provider fixtures can prove auth failure, timeout,
  malformed output, unsupported claims, missing citations, overlong output, and redaction.

If none of these triggers is met, keep using the current CLI/archive path and run periodic
release validation instead of adding more product surface.

## Review Cadence

Use this lightweight loop during the field trial:

1. Record sanitized findings after each meaningful workflow.
2. Review accumulated records after five runs, after a repeated failure pattern, or before
   any request to implement gated work.
3. Update `docs/03-development-plan.md` only when a gate is satisfied, rejected, or
   intentionally deferred with evidence.
4. Run docs-only validation for planning updates and the release-facing chain for public
   command, artifact, or release-surface changes.

Use `docs/16-system-closeout-report.md` as the current system baseline when reviewing
field-trial evidence. Update the closeout backlog only when accumulated records change a
decision, satisfy a trigger, reject a gated track, or reveal a new release-health risk.

## Metrics Aggregator

Use `tools/field_trial_metrics.py` to summarize existing field-trial artifacts without
turning observation into telemetry.

The tool is intentionally narrow:

- it scans only directories or JSON files passed on the command line;
- it reads existing reports and does not call RAGFlow, converters, rerankers, or LLMs;
- it emits sanitized JSON and Markdown summaries plus an optional redaction sidecar;
- it can consume explicit `ragflow_field_trial_record_v1` JSON records when a run wants to
  record a gated trigger such as `serve`, `private_bridge`, `remote_conversion`,
  `provider`, `reranker`, or `llm_backend`;
- it now includes a `ragflow_retirement_observation_matrix_v1` summary for the current
  sanitized quality sample classes: scanned PDFs, extractable PDFs, image-heavy PDFs,
  long documents, complex tables, Office table documents, mixed-language documents, and
  low-quality OCR samples;
- release hygiene schema identity checks cover both `ragflow_field_trial_metrics_v1` and
  `ragflow_retirement_observation_matrix_v1`;
- it does not mark roadmap checkboxes, start services, upload reports, or inspect private
  directories unless the operator passes them explicitly.

Example:

```bash
python3 tools/field_trial_metrics.py /tmp/ragflow-field-trial-runs/run-001 \
  --report-json /tmp/ragflow-field-trial-runs/run-001/field_trial_summary.json \
  --report-md /tmp/ragflow-field-trial-runs/run-001/field_trial_summary.md \
  --redaction-report /tmp/ragflow-field-trial-runs/run-001/field_trial_summary.redaction.json
```

The summary should be treated as evidence for review, not as an automatic product
decision. A triggered track means "inspect this pattern"; it does not by itself approve
`serve`, private bridge, remote conversion, provider, reranker, or LLM backend work.

## Current Observation Records

### 2026-07-03 run-001

Workflow:
- `ragflow-doc-to-md` / `ragflow-kb-build`

Input summary:
- Source type: Chinese product datasheet PDF.
- Approximate document count: one document; full-document attempt plus a page-0 subset
  retry.
- Private details removed: exact source path, endpoint, and retained run-root paths.

Commands:
- Read-only MinerU FastAPI backend probe.
- `ragflow-doc-to-md pipeline --backend mineru-fastapi --mineru-asset-mode markdown_assets
  --postprocess-profile chunk-markers`
- `ragflow-kb-build inspect-handoff`
- `ragflow-kb-build --dry-run`
- `tools/field_trial_metrics.py` over explicit local run roots.

Artifacts:
- Public-safe artifact names: `runtime_report.json`, `doc_manifest.json`,
  `quality_report.json`, `postprocess_report.json`, `artifact_index.json`,
  `retrieval_hints.json`, `ragflow_ingest_plan.yaml`, `inspect_handoff.json`,
  `kb_build_dry_run.json`, field-trial metrics summary.
- Private artifact location retained outside public repo.

Results:
- Pass/fail: full-document pipeline failed inside MinerU with `task_failed` /
  CUDA out-of-memory before conversion output; page-0 subset passed.
- Quality gate: page-0 subset `PASS`.
- Handoff summary: one local image asset landed, rich sidecars were present, and
  `inspect-handoff` reported `ingestion_readiness.status: ready`.
- Build/probe status: MinerU probe available; `build.py --dry-run` passed with the
  reviewed `default-zh-512` profile.
- Live mutation: not run.

Friction:
- Full representative sample is blocked by MinerU GPU capacity or tenant contention.
- Page-0 evidence proves the asset handoff path can work, but it does not cover the full
  document's table/page/chunk-marker/baseline-retirement requirements.

Gated trigger:
- none. This does not open new product-surface work and does not close the RAGFlux
  retirement gate.

Decision:
- keep observing; retry the full MinerU FastAPI field-trial after GPU capacity is
  available, then run disposable RAGFlow live E2E only after explicit approval.

### 2026-07-03 run-002

Workflow:
- `ragflow-doc-to-md` / `ragflow-kb-build` / `ragflow-query`

Input summary:
- Source type: Chinese product datasheet PDF with images, tables, headings, and numeric
  product specifications.
- Approximate document count: one full representative PDF.
- Private details removed: exact source path, endpoint, credential, run-root path, KB
  name, dataset id, document id, and retrieved chunk text.

Commands:
- Reduced MinerU GPU pressure by stopping an unused stale MinerU service while leaving the
  active FastAPI backend available.
- `ragflow-doc-to-md pipeline --backend mineru-fastapi --mineru-asset-mode markdown_assets
  --postprocess-profile chunk-markers`
- `ragflow-kb-build inspect-handoff`
- `ragflow-kb-build --dry-run`
- User-approved disposable RAGFlow live build with parse wait.
- `ragflow-kb-build validate --level smoke`
- `ragflow-kb-build parse-report` and `health-report`
- `ragflow-query ask` in direct and host-assisted modes.
- `ragflow-kb-build cleanup` preview and execute.
- `tools/field_trial_metrics.py` over a curated explicit run-root subset.

Artifacts:
- Public-safe artifact names: `runtime_report.json`, `doc_manifest.json`,
  `quality_report.json`, `postprocess_report.json`, `artifact_index.json`,
  `retrieval_hints.json`, `ragflow_ingest_plan.yaml`, `inspect_handoff.json`,
  `kb_build_dry_run.json`, `kb_manifest.json`, `parse_report.json`,
  `kb_health_report.json`, `validation_smoke.json`, `query_direct.json`,
  `query_host_assisted.json`, `cleanup_execute.json`, field-trial metrics summary, and
  RAGFlux comparison summary.
- Private artifact location retained outside public repo.

Results:
- Pass/fail: passed for the full representative PDF after GPU pressure was reduced.
- Quality gate: `PASS`; no missing-image quality errors.
- Handoff summary: one Markdown document, 21 local image assets, 9 chunk markers, 10
  section boundaries, 21 image artifact signals, 26 question candidates, rich sidecars,
  and `ragflow_ingest_plan.yaml`.
- Build/probe status: `inspect-handoff` reported `ingestion_readiness.status: ready`;
  dry-run passed with the reviewed Chinese 512-token profile.
- Live mutation: one disposable KB was created, parsed, validated, queried, and deleted.
- Parse/query summary: parse succeeded with 13 chunks; smoke validation passed with one
  query and no empty results; direct and host-assisted query modes both returned evidence.
- Cleanup: automatic delete succeeded; the post-cleanup probe still succeeded.
- Field-trial metrics: curated summary `ok: true`, zero findings, quality `PASS`, no
  runtime failures, and no zero-result query outputs.

Friction:
- A stale private RAGFlow credential caused the first probe to fail; a temporary private
  config with a current credential was used for the approved live E2E and deleted after
  cleanup.
- The model-provider probe path returned a version/path compatibility 404, but dataset
  build, parse, validation, direct query, host-assisted query, and cleanup all succeeded.
- The retained RAGFlux package has denser chunk markers than the new pipeline. The new
  pipeline still produced successful live RAGFlow chunks and smoke evidence, so this is a
  follow-up observation item rather than a blocker for this sample.
- The health report did not have an embedding-model value in the manifest and no separate
  activation plan was supplied; these remained advisory review notes, not live failures.

Gated trigger:
- none for new product surface. The existing CLI pipeline, kb-build, and query surfaces
  were sufficient for this run.

Decision:
- The representative-sample RAGFlux retirement field-trial gate passes for the current
  replacement workflow. Keep observing additional real PDFs before treating this as a
  broad corpus-quality guarantee, and require a separate explicit live-mutation approval
  for any paired RAGFlux live A/B run.

### 2026-07-04 run-003

Workflow:
- `ragflow-doc-to-md` / `ragflow-kb-build`

Input summary:
- Source type: Chinese product datasheet PDF with complex HTML tables, images, headings,
  formulas, and numeric product specifications.
- Approximate document count: one full representative PDF.
- Private details removed: exact source path, endpoint, run-root path, and raw Markdown.

Commands:
- `ragflow-doc-to-md pipeline --backend mineru-fastapi --table-quality high
  --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers-dense`
- `ragflow-kb-build inspect-handoff`
- `ragflow-kb-build --dry-run` with a reviewed table-atomic profile using
  the `<!-- chunk -->` delimiter wrapped in backticks and no `children_delimiter`.

Artifacts:
- Public-safe artifact names: `runtime_report.json`, `quality_report.json`,
  `postprocess_report.json`, `chunk_profile_report.json`, `retrieval_hints.json`,
  `profile_suggestions.json`, `ingest_readiness_report.json`, `inspect_handoff.json`,
  and dry-run JSON output.
- Private artifact location retained outside public repo.

Results:
- Pass/fail: passed for the full representative PDF with the high-accuracy FastAPI
  backend; no fallback was used.
- Quality gate: `PASS_WITH_REVIEW`; review warnings are table-structure warnings for
  complex HTML tables, not missing assets or blocked conversion.
- Handoff summary: one Markdown document, 6 HTML tables, 6 table artifacts, 24 image
  artifacts, 15 section boundaries, 29 question candidates, rich sidecars, and
  `ragflow_ingest_plan.yaml`.
- Table safety: postprocess preserved all 6 HTML table fingerprints, inserted 6 table
  boundary markers through the dense profile, and inserted 0 markers inside table blocks.
- Runtime summary: the conversion reused a persistent MinerU FastAPI service, selected a
  high-accuracy backend, completed one remote attempt successfully, and reported no
  resource failure, timeout, or degraded table-quality fallback.
- Handoff inspection: `ingestion_readiness.status: ready_with_review`, rich and pipeline
  sidecars complete, 0 missing image assets, and quality table count aligned with table
  artifact count.
- Dry-run: passed with the reviewed table-atomic parser profile.
- Live mutation: not run.

Friction:
- Complex-table warnings remain intentionally conservative. They should drive human review
  before live KB creation, not force a fallback to the lower-quality pipeline backend.
- KB-side upload packaging for Markdown plus local images now has an offline
  `ragflow-kb-build asset-upload-plan` review path; live package upload remains a
  separate mutation-gated design question.

Gated trigger:
- none for new product surface. The current CLI pipeline is sufficient for high-quality
  table handoff generation and dry-run review.

Decision:
- Treat `--table-quality high` plus `chunk-markers-dense` as the recommended formal path
  for complex-table PDFs when a compatible MinerU FastAPI service is available. Keep live
  RAGFlow KB creation gated by explicit user approval.

### 2026-07-05 run-004

Workflow:
- `ragflow-doc-to-md` / `ragflow-kb-build` / retired-consumer comparison review

Input summary:
- Source type: Chinese scanned product datasheet PDF with images and complex tables.
- Approximate document count: one full representative PDF.
- Private details removed: exact source path, endpoint, run-root path, dataset ids,
  document ids, and raw chunks.

Commands:
- Unit regression tests for `ragflow-skill-runtime`.
- `ragflow-doc-to-md inspect-source`
- `ragflow-doc-to-md adaptive --decision-only`
- `ragflow-doc-to-md adaptive` with explicit MinerU FastAPI `pipeline` backend,
  Markdown assets, Chinese language intent, and dense chunk markers.
- `ragflow-kb-build inspect-handoff`
- Retired `ragflux` and `ragflow-kb-ops` comparison checks, used only as transition
  evidence.

Artifacts:
- Public-safe artifact names: `document_features.json`, `pipeline_decision.json`,
  `adaptive_summary.json`, `quality_report.json`, `postprocess_report.json`,
  `chunk_profile_report.json`, `artifact_index.json`, `profile_suggestions.json`,
  `handoff_inspection.json`, and retired-consumer chunk snapshot/run summaries.
- Private artifact location retained outside public repo.

Results:
- Pass/fail: passed for the current `ragflow-skills` regression matrix.
- Unit tests: 518 runtime tests passed.
- Source inspection: scanned/low-text PDF handling selected `primary_language: zh`, used
  low-confidence language evidence instead of binary PDF garbage, and reported the PDF as
  likely scanned.
- Adaptive decision: recommended `table-atomic-zh-4096` and preserved the explicitly
  requested `pipeline` backend.
- Pipeline: completed with `PASS_WITH_REVIEW`, 32 chunk markers, 6 HTML tables, no marker
  inside table blocks, 21 image artifacts, and 15 Markdown image references.
- Handoff inspection: `ingestion_readiness.status: ready_with_review`, rich and pipeline
  sidecars complete, and missing image count zero.
- Retired-consumer comparison: the old consumer could create a chunk snapshot, but its
  run summary showed requested 4096-token table-atomic profile settings were not fully
  applied by that old path. This proves structural consumption, not profile parity.

Friction:
- The old `ragflow-kb-ops` cleanup path showed SDK signature drift. Because that skill is
  retiring, this is not a follow-up implementation target for the current public suite.
- The retired consumer's requested/effective profile drift should be treated as a signal
  to keep current `ragflow-kb-build` reports explicit about requested versus effective
  parser settings when current-suite live or dry-run evidence is collected.
- The old `ragflux` comparison path may start its own temporary MinerU FastAPI service in
  CLI-oriented runs, so it remains a GPU/process-contention observation item rather than
  a replacement-path blocker.

Gated trigger:
- none. No post-CLI adapter, optional LLM/backend, private bridge, or old-skill repair
  track is opened by this run.

Decision:
- Keep follow-up work focused on the current four public skills. Use retired-skill
  failures only as migration evidence; do not spend this roadmap repairing
  `ragflow-kb-ops`. The next useful work is current-suite observation, sample-matrix
  validation, release-path health, and current `ragflow-kb-build` visibility for
  requested/effective parser behavior.

## Current Decision

The next stage remains observation, not feature expansion. The representative PDF
field-trial shows the current CLI pipeline is sufficient for the RAGFlux replacement
workflow when GPU capacity is available and credentials are current. The remaining
post-CLI, private-bridge, provider, reranker, and optional LLM/backend work should stay
gated until this plan produces concrete evidence that one of them is needed.

The MinerU v4 platform backend is implemented and release-validated through fake-server
tests, consumer acceptance, and strict-vendor platform smoke. A real MinerU v4 platform
run is still observation-gated: it requires an explicit user request, credentials,
a throwaway small fixture, no private corpus disclosure, and sanitized evidence capture.

The system-level closeout baseline and ongoing observation/improvement backlog are
recorded in `docs/16-system-closeout-report.md`.

### 2026-07-11 run-005

Workflow:
- `ragflow-kb-build` read-only benchmark validation for marker-aware observed evidence.

Input summary:
- One reviewed Open RAG target document with ten queries and grounded evidence.
- One reviewed FinanceBench target was searched for but had no suitable existing KB.
- Private endpoints, credentials, KB names, dataset/document IDs, paths, queries, and raw
  chunks were excluded from this record.

Results:
- Read-only compatibility and discovery passed across 186 existing datasets.
- Two equivalent Open RAG baseline KBs reproduced the same 24 observed chunk hashes and
  the same metrics.
- All 16 grounded spans mapped to observed chunks. At k=3, strict chunk recall was 0.95;
  expected chunk hit rate, expected-term recall, and table-term recall were 1.0; empty
  result and wrong-document rates were 0.
- Public-safe review/retention outputs passed sensitive scans with zero endpoint,
  credential, private path/identifier, raw-query, or raw-chunk matches.
- No create, upload, parse, reparse, update, delete, cleanup, MinerU, DeepDoc, LLM/RAGAS,
  Stage 8C, or default-changing action occurred.

Friction:
- Duplicate chunks from one document qrel could inflate precision and nDCG beyond valid
  bounds; the metric now counts each ranked qrel target once.
- Public-safe retention incorrectly reported zero RAGFlow calls; validation and retention
  outputs now retain accurate read-only call counts and explicit non-mutation state.
- Independent merge review found that invalid local benchmark inputs were loaded after
  retrieval. The CLI now validates qrels, gate, baseline, chunk-snapshot, and observed-
  state inputs before constructing the live validation path.

Gated trigger:
- FinanceBench observed validation requires a separately approved disposable L3
  build/query/cleanup lifecycle because no exactly pinnable existing KB was available.

Decision:
- Accept the Open RAG result as a pinned read-only subset checkpoint only. Keep the true
  two-subset baseline, cross-subset guidance review, and all default-promotion decisions
  open until FinanceBench observed evidence and cleanup proof exist.

### 2026-08-03 FinanceBench Evidence Closeout

The later bounded `NEW_MINIMAL_L3` feasibility gate stopped before contract creation or
live execution because the reviewed FinanceBench input bytes were incomplete. The owner
accepted `L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` and formally closed that workflow.

Run-005 remains valid historical observation, but its L3 trigger is no longer a current
task. FinanceBench observed evidence and the two-subset comparison remain unavailable;
the corresponding evidence rows stay open, no replacement live run is implied, and L4
remains unauthorized.
