# System Closeout Report

Status: closeout checkpoint
Date: 2026-07-02

## Scope

This report closes the concentrated development round for the public RAGFlow skill suite.
It compares the current design intent, implementation surface, release gates, open task
list, and field-trial observation plan.

Review baseline before this docs-only checkpoint:

- Branch: `develop`
- Latest implementation commit: `d787ba0 Add field trial metrics aggregator`
- Public skills: `ragflow-doc-to-md`, `ragflow-kb-build`, `ragflow-query`
- Shared runtime: `packages/ragflow-skill-runtime`
- Canonical release shape: self-contained per-skill archives, with the runtime vendored
  into release artifacts

This checkpoint does not change public command behavior, enable a local service, add
script-owned LLM calls, mutate RAGFlow, or add private adapter code.

## Executive Decision

The focused build phase is complete for the portable public CLI/archive release path.
The suite should now move into field-trial observation and release-path maintenance.

The remaining roadmap items are not ordinary unfinished implementation work. They are
explicitly gated product or private-adapter tracks:

- local service and post-CLI host wrappers;
- remote conversion, provider, reranker, and web/API adapters;
- optional script-owned LLM/RAGAS backend execution;
- private dedao bridge work outside public release artifacts.

Until a gate is satisfied with real evidence, the default action is to keep using the
current CLI/archive path, collect sanitized field-trial records, and keep validation green.

## Design To Implementation Calibration

| Area | Design intent | Current implementation status | Calibration |
| --- | --- | --- | --- |
| Public suite boundary | Ship three portable public skills without private workflow dependencies. | Public skills live under `skills/`; private maintainer workflow remains outside public artifacts. | Closed for current release path. |
| Runtime foundation | Share config, auth, HTTP, manifests, RAGFlow client, report safety, and workflow helpers. | `ragflow_skill_runtime` contains shared modules for conversion, KB build, retrieval, routing, resilience, sanitization, manifests, and validation. | Closed for current CLI scope; expand only with focused adapters. |
| Document conversion and handoff | Produce Markdown handoff directories with stable `doc_manifest.json`, quality reports, image preservation, split/package support, and backend readiness checks. | `ragflow-doc-to-md` supports passthrough, builtin conversion, MinerU/service/local CLI paths, generic remote paths, inspect, split, package, postprocess, backend probe, and warmup. | Closed for current converters; use field evidence before adding a new remote client. |
| KB build and governance | Build and validate KBs from handoffs while keeping mutation gated and reviewable. | `ragflow-kb-build` covers dry-run/live build gates, profile/metadata/tagset governance, benchmark lifecycle, grounded QA validation, evidence maps, optimization plans, cleanup readiness, topology advice, parse reports, and health reports. | Closed for planned public CLI behavior; future live mutation remains approval-gated. |
| Query and orchestration | Support direct retrieval, routing, diagnostics, fusion/rewrite, host-assisted agentic flows, citation audit, and evaluation without default script-owned synthesis. | `ragflow-query` covers direct/auto/host-assisted ask, routing, route tests, assistant profiles, rewrite, session, fusion, diagnostics, rerank comparison, citation audit, answer evaluation, agentic planning, and request/review boundaries. | Closed for evidence-first CLI use; script-owned answers remain deferred. |
| Runtime resilience and report safety | Make failures observable and sanitized without hidden retries or private leaks. | Current runtime inventory is 21 covered, 0 candidate, 0 deferred, and 68 not-applicable command surfaces after the retained-package comparison report was added as a read-only report. Redaction, generated-report safety, generated Markdown audit, endpoint reports, cache, metrics, rate-limit, circuit-breaker, partial-failure reports, and `ragflow-doc-to-md` runtime performance telemetry are covered for the current inventory. | Closed for current public surfaces; reopen only when new command/report surfaces appear. |
| Release packaging and platform acceptance | Keep archives self-contained and prove installed-artifact behavior. | Release hygiene, manifest schema checks, schema identity, build checks, archive export, installed archive smoke, consumer acceptance, strict-vendor platform smoke, and optional runtime wheel smoke/export are available. | Closed for current release path; run periodically and before public changes. |
| Post-CLI product adapters | Add service, remote conversion, provider, reranker, or web/API adapters only when one-shot CLI is insufficient or a concrete product contract exists. | `docs/13-post-cli-adapter-planning.md` and Phase 37 intake gates define the required evidence and fake-fixture path. | Deferred; observation must prove need before implementation. |
| Optional LLM/RAGAS backend execution | Keep deterministic defaults and request/review boundaries before any script-owned model call. | Metadata, grounded-QA, agentic-answer, and answer-evaluator request/review boundaries exist. `docs/14-optional-llm-backend-planning.md` defines the future backend gate. | Deferred; no model calls should be enabled without explicit config and fake-provider gates. |
| Private dedao bridge | Keep private ingestion outside public release artifacts while consuming public handoff contracts. | Public docs and release hygiene preserve the boundary; current private checkpoint found Markdown passthrough into `doc_manifest.json` sufficient until proven otherwise. | Deferred and private-only. |
| Field-trial observation | Collect sanitized evidence before opening gated work. | `docs/15-field-trial-observation-plan.md` defines signals and trigger rules; `tools/field_trial_metrics.py` aggregates explicit run roots without network calls or background telemetry, emits a multi-sample retirement observation matrix for replacement-path evidence review, and keeps both observation report schema identities under release hygiene. | Active operating loop. |

## Completed Work Summary

The concentrated development round completed the following capability bands:

- Foundation and packaging: repository structure, three public skills, shared runtime,
  vendored release archives, cross-platform smoke, release hygiene, archive export, and
  host-agent setup guidance.
- Document pipeline: document conversion, Markdown handoff, manifest contracts, quality
  gates, image preservation, splitting, rich handoff packages, post-processing, backend
  probes, and backend warmup reports.
- KB build pipeline: dry-run and gated live builds, append/cleanup plans, profile linting
  and recommendations, metadata/tagset governance, chunk snapshots, benchmark lifecycle,
  grounded QA validation, evidence mapping, optimization planning, topology advice, parse
  reports, and KB health reports.
- Query pipeline: direct and routed retrieval, route regression, assistant profile review,
  query rewrite, session enrichment, diagnostics, pollution reports, rerank comparison,
  cross-language comparison, fusion, fallback fixtures, endpoint reports, cache reports,
  centroid routing, citation audit, answer evaluation, and host-assisted agentic planning.
- Resilience and safety: runtime metrics, partial-failure reports, retry/circuit/cache
  pilots, report redaction, generated report safety, generated Markdown audit, schema
  identity, manifest schema validation, and release-surface hygiene.
- Live validation: approved disposable RAGFlow validation covered probe, optimization
  build/validate/cleanup, enrichment comparison, and live runtime resilience, with cleanup
  fixes applied and verified.
- Adapter governance: post-CLI adapter design and intake gates, runtime wheel smoke/export,
  optional LLM backend planning, private bridge boundary review, and field-trial metrics.

## Task List Audit

After this closeout checkpoint, the roadmap has 561 completed items out of 576 tracked
items. The 15 open items remain intentionally gated:

| Category | Open items | Why still open | Trigger before work starts |
| --- | ---: | --- | --- |
| Local service / post-CLI host wrapper | 2 | One-shot CLI remains the canonical path. | Three host-agent runs show CLI shape is wrong, or one critical workflow requires health/lifecycle/request correlation. |
| Other post-CLI product adapters | 4 | No concrete endpoint, provider, reranker, or product contract is currently recorded. | A named contract with fake fixtures, error model, config/auth shape, and acceptance criteria. |
| Optional script-owned LLM/backend execution | 7 | Request/review boundaries cover the safe default; script-owned generation needs stronger gates. | Explicit LLM config, fake-provider fixtures, advisory marking, citation compatibility, and redaction tests. |
| Private dedao bridge | 2 | Current private path can use Markdown passthrough into public `doc_manifest.json`. | A private workflow proves passthrough is insufficient, and adapter work stays outside public `skills/`. |

These tasks should not be closed by wording changes alone. They should close only when a
gated implementation is built and verified, or when field-trial evidence records that a
track is intentionally rejected or superseded.

## Ongoing Observation And Improvement Backlog

| Track | Signals to collect | Collection method | First safe implementation if triggered |
| --- | --- | --- | --- |
| CLI sufficiency and `serve` | Slow repeated spawning, brittle artifact handoff, missing request IDs, need for health/shutdown semantics. | Per-run field-trial records plus `tools/field_trial_metrics.py`; include command count, elapsed time, failed step, and host name class. | Fake-client `ragflow-query serve` with localhost bind, health, direct query, host-assisted request, shutdown, auth boundary, and redacted logs. |
| Handoff quality | Missing/invalid manifests, garbled Markdown, missing assets, blocked quality gates. | `convert --json`, `inspect`, quality reports, redaction sidecars, and field-trial summaries. | Focused converter or postprocessor fix with deterministic fixtures and consumer acceptance coverage. |
| KB build stability | Dry-run failures, parse stalls, cleanup risk, repeated runtime partial failures, or current-suite requested/effective profile drift. | Build/probe/parse/health/cleanup reports retained in explicit run roots. Retired-consumer drift is transition evidence only; it should prompt current `ragflow-kb-build` visibility checks, not old-skill repair. | Narrow resilience, report-clarity, or profile-governance fix in the current suite; live mutation remains explicitly approved and disposable. |
| Query quality | Zero results, wrong top document, unstable rankings, weak citation support, unsupported answer claims. | Saved query outputs, traces, validation reports, citation audits, answer evaluations, and benchmark deltas. | Offline routing/fusion/rewrite/profile fix first; reranker adapter only with measurable target and fallback policy. |
| Remote conversion | Current builtin, MinerU, generic remote, or local CLI paths do not match a real converter. | Sanitized endpoint protocol, auth shape, fake request/response, error model, and fixture plan. | Fake-server client behind explicit config, with no default private endpoint. |
| Provider abstraction | A named provider cannot fit current OpenAI-compatible or request/review paths. | Provider label, API shape, config keys, auth, timeout/error cases, and fake-provider tests. | Minimal provider adapter contract with deterministic failure fixtures. |
| Optional LLM backend | Manual external model use becomes repetitive or error-prone despite request/review artifacts. | Request/review counts, failure classes, candidate artifact quality, citation-audit compatibility, and redaction needs. | Grounded-QA LLM generation with fake provider, advisory output marking, citation checks, and redaction sidecar. |
| Private dedao bridge | Private content cannot reliably become ordinary Markdown handoff material. | Private-only evidence outside public release artifacts; public summary records only sanitized handoff shape. | Private adapter outside public `skills/` that emits public `doc_manifest.json` handoff bundles. |
| Release health | Archive, runtime wheel, platform smoke, report safety, or schema gates drift. | Periodic release validation and release hygiene reports. | Fix the failing gate before opening new product surface. |

## Operating Rules After Closeout

Use this default loop:

1. Run real workflows through the current public CLI/archive path.
2. Keep raw private artifacts outside the public repository.
3. Record sanitized findings with `docs/15-field-trial-observation-plan.md`.
4. Aggregate explicit run roots with `tools/field_trial_metrics.py` when enough evidence
   exists to review a pattern.
5. Open a gated implementation only when the observation trigger is satisfied.
6. For any public command, schema, release, or artifact change, run the appropriate
   validation chain before marking the work complete.

Periodic review cadence:

- after five meaningful field-trial runs;
- after one repeated failure class appears in two or more runs;
- before implementing `serve`, a product adapter, an LLM/backend, or a private bridge;
- before any public release candidate.

## Post-Closeout Adaptive Checkpoint

Checkpoint date: 2026-07-05

Release-path maintenance added a deterministic adaptive formal-ingest helper without
reopening gated product tracks:

- `ragflow-doc-to-md inspect-source` emits `ragflow_document_features_v1` from lightweight
  source sampling.
- `ragflow-doc-to-md adaptive` emits `ragflow_pipeline_decision_v1` and
  `ragflow_adaptive_pipeline_summary_v1`, can stop at `--decision-only`, or can reuse the
  existing formal `pipeline`.
- The summary includes offline review commands for `inspect-handoff`, `asset-upload-plan`,
  and KB dry-run; it does not execute live RAGFlow mutation or script-owned LLM calls.
- Schema identity, report surface inventory, generated Markdown audit, runtime resilience
  inventory, consumer acceptance, and platform smoke coverage were updated for the new
  command/report surface.

## Post-Closeout Follow-Up Calibration

Calibration date: 2026-07-05

The updated scanned-PDF regression supports the adaptive-pipeline fix, but it does not
reopen legacy-skill maintenance. `ragflow-kb-ops` is now a retiring comparison source.
Its cleanup SDK drift and requested/effective profile mismatch should be recorded as
transition evidence only. The public roadmap should not spend implementation capacity
repairing that old code path.

Current-suite follow-up is limited to:

- `ragflow-doc-to-md`: keep collecting real-sample inspection, language-source,
  backend-selection, table-atomicity, and image-asset evidence.
- `ragflow-kb-build`: keep dry-run, readiness, live parse, cleanup, and requested versus
  effective parser behavior visible when current-suite evidence is collected.
- `ragflow-query`: validate retrieval quality against KBs built through the current
  replacement path before considering reranker, provider, service, or LLM/backend gates.

No post-CLI adapter, optional script-owned LLM/backend, private bridge, or live mutation
track is opened by the retired-consumer findings.

## Closeout Conclusion

The project is no longer in a broad feature-construction phase. The current public suite
is ready for sustained real use through the portable CLI/archive path. Future work should
be evidence-led: observe, measure, decide, then implement the smallest gated slice that a
real workflow proves necessary.
