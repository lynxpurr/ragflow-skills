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
- it now includes a `ragflow_retirement_observation_matrix_v1` summary for explicit
  sample types such as scanned documents, long documents, papers, contracts, complex
  tables, image-heavy sources, low-quality OCR, and multi-document handoffs;
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

## Current Decision

The next stage remains observation, not feature expansion. The representative PDF
field-trial shows the current CLI pipeline is sufficient for the RAGFlux replacement
workflow when GPU capacity is available and credentials are current. The remaining
post-CLI, private-bridge, provider, reranker, and optional LLM/backend work should stay
gated until this plan produces concrete evidence that one of them is needed. The
system-level closeout baseline and ongoing observation/improvement backlog are recorded
in `docs/16-system-closeout-report.md`.
