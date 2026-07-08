# Hermes E2E Improvement Follow-Up Plan

Status: P0 retest closed; P1 improvement tracking active
Date: 2026-07-08
Scope: `ragflow-doc-to-md` -> `ragflow-kb-build`

## Objective / Scope / Boundaries

This document records sanitized improvement findings from the Hermes end-to-end run over
the document-to-KB build path, then defines a focused retest plan for the next Hermes
agent execution.

The initial validated baseline was:

- offline Markdown formal handoff, handoff inspection, asset plan, build dry-run, profile
  lint, metadata/tagset lint, and benchmark preflight passed;
- read-only RAGFlow probe and document backend probe passed;
- model-provider probe returned a version or endpoint compatibility warning;
- a real MinerU FastAPI PDF conversion produced a formal handoff with local image assets;
- an approved disposable KB build, smoke validation, parse and health reports, safety
  checks, and cleanup passed.

The follow-up Hermes retest closed the main evidence gap: a real PDF handoff now has
sanitized evidence for conversion, handoff inspection, asset planning, dry-run,
consistency review, approved disposable live build, parse, smoke validation, post-build
reports, cleanup, and clean field-trial metrics aggregation.

This plan does not enable live mutation by default, add script-owned LLM calls, add a
local service wrapper, repair private services, or open a provider, reranker, web/API, or
private bridge adapter. Any disposable live KB retest still requires explicit user
approval in the active Hermes session.

Do not copy raw private run roots, private endpoints, dataset IDs, document IDs, raw
retrieved chunks, real KB names, API keys, token fragments, or private document paths into
public docs. Keep raw artifacts in private run storage.

## Problem Description

The E2E run proved the current CLI path works, but it exposed several follow-up quality
and evidence gaps:

1. File identity can be confused by an extension. An initial source labeled as PDF was
   actually HTML, which caused a converter failure before a real PDF replacement passed.
2. MinerU protocol and port selection still needs a clear preflight decision. The run
   succeeded with a FastAPI protocol, but the operator had to distinguish it from sync,
   v4, and other backend shapes.
3. Model-provider probing is not compatible with the observed RAGFlow endpoint set. The
   missing provider endpoints did not block dataset creation, parse, validation, or
   cleanup, so this should be treated as a compatibility warning unless a workflow needs
   provider management.
4. Field-trial aggregation was affected by a zero-byte intermediate JSON file from an
   attempted converter path. Human E2E reporting was valid, but automatic metrics
   aggregation needs clean JSON or log-only failure artifacts.
5. The live KB build originally validated the Markdown fixture path. The follow-up retest
   closed this gap by building and validating a disposable KB from a real PDF formal
   handoff.
6. The tested profile was model-neutral. A deployment-specific embedding model check
   remains useful before treating the target environment as production-ready.
7. Routing activation remained advisory. Route config, hint coverage, and route tests are
   outside the document-to-KB build baseline and should be tested only when routing is in
   scope.
8. `asset-upload-plan` can report phantom missing-image entries for semantic aliases even
   when `inspect-handoff` confirms that no real local image assets are missing.
9. `refresh-report` may see a version-dependent zero-document response from the current
   RAGFlow document-list API even when build and parse evidence show a parsed document and
   chunks.

## Update Plan

### P0 - Evidence Closure

Closed by a focused retest that used the successful real PDF formal handoff as the input to
`ragflow-kb-build`, then executed handoff inspection, asset planning, dry-run, approved
live disposable build, smoke validation, parse/health reporting, cleanup, and metrics
aggregation.

The main acceptance goal is to prove the complete chain:

```text
real PDF
  -> MinerU FastAPI formal handoff
  -> inspect-handoff / asset-upload-plan / consistency-check
  -> build dry-run
  -> approved disposable live build
  -> smoke validation / parse report / health report
  -> cleanup
  -> clean field-trial metrics summary
```

### P1 - Operator Friction Reduction

Classify extension/content mismatches and backend protocol ambiguity before conversion.
Hermes should record the detected file kind, chosen backend protocol, and reason for the
backend choice in the retest report.

### P1 - Compatibility Classification

Keep model-provider probe failures separate from KB build failures. If provider endpoints
return 404 but build, parse, validate, and cleanup pass, record
`compatibility_warning:model_provider_endpoint_missing` instead of treating the whole
read-only readiness stage as failed.

### P1 - Aggregation Hygiene

Ensure failed experimental converter attempts write either valid JSON failure reports or
plain log files. A zero-byte `*.json` file should be treated as an artifact hygiene issue
and excluded or replaced before running `tools/field_trial_metrics.py`.

### P1 - Asset Alias Consistency

Separate true missing local image assets from semantic alias references in
`asset-upload-plan` and consistency reporting. The follow-up retest showed
`inspect-handoff` reporting zero real missing images while `asset-upload-plan` still
surfaced alias-derived missing-image entries. That should remain a review warning rather
than a live-build blocker until the report model distinguishes the two cases.

### P1 - Refresh API Compatibility

Clarify `refresh-report` behavior when a RAGFlow document-list endpoint returns zero
documents even though build, parse, and chunk evidence exist. Follow-up work should either
classify this as a version-specific read-only API limitation or add fallback explanation
in parse and health reports.

### P2 - Production Readiness Checks

Run deployment-specific checks only after the focused P0 chain passes:

- expected embedding model drift checks;
- image asset consistency checks for real PDF handoffs;
- route activation and route-test coverage if retrieval routing is in scope;
- optional `ragflow-query` direct or host-assisted retrieval once the KB is live.

## Task Checklist

- [x] Run pre-conversion file identity checks for the retest source and record whether the
  source is a real PDF, HTML, Office file, image, or Markdown.
- [x] Run backend probe or equivalent protocol review and record why the selected MinerU
  backend is `mineru-fastapi`, `mineru-v4`, `mineru-sync`, `mineru-cli`, or another
  explicit backend.
- [x] Generate a real PDF formal handoff with `ragflow-doc-to-md pipeline`, local image
  asset materialization, and a chunk-marker postprocess profile.
- [x] Run `ragflow-kb-build inspect-handoff` against the real PDF handoff and require no
  blocked quality gate or missing image assets before live mutation.
- [x] Run `ragflow-kb-build asset-upload-plan` against the real PDF handoff and inspect
  image asset counts, package contents, and `ragflow_calls=0`.
- [x] Run `ragflow-kb-build consistency-check` when the required handoff sidecars and
  build artifacts are available.
- [x] Run `ragflow-kb-build --dry-run` with retrieval hints and a reviewed profile before
  any live build.
- [x] If the user explicitly approves live mutation, create one disposable KB from the
  real PDF handoff, wait for parse, run smoke validation, generate refresh, parse,
  activation, and health reports, then execute cleanup with exact confirmations.
- [x] Re-run `tools/field_trial_metrics.py` after removing or replacing zero-byte JSON
  artifacts, and require the metrics summary to be valid JSON with no unreadable-report
  findings.
- [x] Record model-provider probe failures as compatibility warnings when the core KB
  lifecycle passes.
- [ ] Add or refine reporting so `asset-upload-plan` and consistency checks distinguish
  true missing image files from semantic alias references.
- [ ] Add or refine `refresh-report`, parse-report, or health-report guidance for
  RAGFlow document-list API variants that return zero documents despite build/parse/chunk
  evidence.
- [ ] Run deployment-specific embedding model checks if a concrete expected embedding
  model is known.
- [ ] Keep route config, route tests, and `ragflow-query` validation as optional follow-up
  scope unless the user asks to test retrieval routing.

## Current Development Progress

P0 evidence closure is complete from the follow-up Hermes retest. The retest used a real
PDF source, confirmed the selected MinerU FastAPI protocol, produced a formal ingest
handoff, passed handoff review and KB dry-run, executed an approved disposable live KB
build, validated retrieval with a content-specific smoke query, generated post-build
reports, cleaned up the disposable KB, and produced clean field-trial metrics with
`ok=true` and zero findings.

No code changes have been made from this plan yet. Remaining work is limited to P1/P2
report clarity and production-readiness follow-up.

## Validation Evidence / Residual Gated Work

Existing sanitized evidence shows that the Markdown fixture E2E path and cleanup path
passed, and the follow-up retest closed the complete real-PDF-to-live-KB chain. The
retest evidence includes:

- real PDF identity check passed before conversion;
- MinerU FastAPI protocol selection was explicit and read-only probed;
- formal handoff was generated with local image assets, chunk markers, retrieval hints,
  and package sidecars;
- `inspect-handoff` found no true missing local image assets;
- `asset-upload-plan` remained offline-only and reported no RAGFlow calls;
- dry-run and consistency review passed, with alias-related image findings remaining
  review-only;
- approved disposable live KB build parsed successfully and produced chunks;
- smoke validation passed with a content-specific query;
- refresh, parse, activation, and health reports were generated;
- cleanup executed with exact confirmations and post-cleanup probe succeeded;
- field-trial metrics reported `ok=true`, zero findings, and no zero-byte JSON artifacts.

Residual gated work:

- live disposable KB mutation remains approval-gated;
- model provider management remains a compatibility track, not a build blocker;
- routing activation is a separate retrieval-readiness track;
- provider, reranker, service wrapper, LLM backend, and private bridge adapters remain
  out of scope unless future field evidence satisfies their gates.

Residual P1/P2 follow-up:

- distinguish semantic image aliases from true missing local assets in asset planning and
  consistency reports;
- clarify refresh/document-list API compatibility when read-only refresh evidence
  disagrees with build or parse evidence;
- run deployment-specific embedding model checks before treating a concrete production
  profile as validated;
- keep route config, route tests, and `ragflow-query` validation outside this baseline
  unless retrieval routing becomes the active test scope.

## P0 Retest Closeout / Retrospective

The P0 retest changed the status of this plan from "evidence gap open" to "real PDF
handoff baseline verified." It did not change runtime code, CLI behavior, skill guidance,
schemas, or release gates. It contributed sanitized live field-trial evidence only.

What closed:

- real PDF formal handoff reached live KB build and cleanup;
- field-trial metrics aggregation became clean;
- model-provider endpoint failures were classified as compatibility warnings;
- artifact hygiene no longer had zero-byte JSON issues.

What remains open:

- report clarity for semantic image alias findings;
- read-only refresh API compatibility explanation;
- model-specific profile validation for a concrete deployment;
- optional retrieval routing and query validation when requested.

## Original Hermes Retest Prompt

This prompt is retained for replay or audit. It is no longer the next required action
because the P0 retest has closed. Replace angle-bracket placeholders with private local
values inside the Hermes session only if a future operator intentionally reruns this same
test.

```text
Please run a focused follow-up E2E retest for the current RAGFlow public skills:
- ragflow-doc-to-md
- ragflow-kb-build

Read these files first:
- skills/ragflow-doc-to-md/SKILL.md
- skills/ragflow-doc-to-md/references/host-agent-setup.md
- skills/ragflow-kb-build/SKILL.md
- skills/ragflow-kb-build/references/host-agent-setup.md
- docs/30-hermes-e2e-test-plan.md
- docs/31-hermes-e2e-improvement-follow-up-plan.md

Goal:
Close the evidence gap from the prior E2E run by testing a real PDF formal handoff all
the way through ragflow-kb-build. The prior run proved the Markdown fixture live path and
proved real PDF conversion separately; this run should prove the real PDF handoff can also
inspect, asset-plan, dry-run, optionally live-build, validate, report, clean up, and
aggregate cleanly.

Safety rules:
- Do not print or write API keys, token fragments, private endpoints, full private paths,
  dataset IDs, document IDs, raw private chunks, or private source names into shared
  transcripts or public docs.
- Keep raw artifacts under a private run root.
- Prefer the private host config path and environment variables; do not copy secrets into
  the skill directory.
- RAGFlow and MinerU are external services; do not start, patch, or repair them from the
  skill folders.
- Live disposable KB creation requires explicit user approval in this Hermes session.
- Cleanup must use the dataset ID from the live kb_manifest plus the exact disposable KB
  name.
- Every report that can contain paths, endpoints, or diagnostics should have a redaction
  sidecar when the command supports it.

Required offline and read-only steps:
1. Create a new private run root and reports directory.
2. Verify command help for the relevant doc-to-md and kb-build commands.
3. Check the selected source with file identity checks before conversion:
   - record whether the content is a real PDF, HTML, Office file, image, or Markdown;
   - if a file extension and content disagree, stop and report file_type_mismatch instead
     of sending it to MinerU as a PDF.
4. Probe or review the MinerU backend protocol and choose one explicit backend:
   mineru-fastapi, mineru-v4, mineru-sync, mineru-cli, mineru, or remote. Record the
   reason for the choice.
5. Run ragflow-doc-to-md pipeline on the real PDF with local image assets and a
   chunk-marker postprocess profile.
6. Confirm the output is formal_ingest and includes doc_manifest.json, quality_report.json,
   runtime_report.json, postprocess_report.json, chunk_profile_report.json,
   retrieval_hints.json, ingest_readiness_report.json, formal_handoff_manifest.json,
   package_readme.md, and ragflow_ingest_plan.yaml.
7. Run ragflow-kb-build inspect-handoff against the real PDF handoff.
8. Run ragflow-kb-build asset-upload-plan against the real PDF handoff.
9. Run ragflow-kb-build --dry-run with retrieval_hints.json and a reviewed profile.
10. If enough artifacts exist, run ragflow-kb-build consistency-check before live build.
11. Run RAGFlow probe and model-provider probe if config is available. If model-provider
    endpoints return 404 but RAGFlow build/probe is otherwise usable, classify it as
    compatibility_warning:model_provider_endpoint_missing.

Optional live phase, only after explicit user approval:
12. Create one disposable KB from the real PDF handoff.
13. Wait for parse unless the user explicitly asks for async parse.
14. Run smoke validation against content expected from the real PDF handoff.
15. Generate refresh-report, parse-report, activation-plan, and health-report.
16. Preview cleanup, then execute cleanup with exact dataset ID and KB name.
17. Run post-cleanup probe or read-back verification when possible.

Artifact hygiene and aggregation:
18. Ensure failed experimental command outputs are either valid JSON failure reports or
    plain log files. Do not leave zero-byte *.json files.
19. Run tools/field_trial_metrics.py on the private run root and write JSON, Markdown, and
    redaction sidecar outputs.
20. If metrics returns ok=false, report the exact unreadable or unsafe artifact and whether
    the main E2E result is still valid.

Final report:
Save a Chinese report under the private run root reports directory. Include:
- pass/fail/skip for each step;
- sanitized command summaries;
- selected source kind and backend protocol;
- formal handoff status, quality status, image asset count, chunk marker count, and hint
  counts;
- inspect-handoff, asset-upload-plan, dry-run, and consistency-check summaries;
- model-provider compatibility classification;
- live KB result only if approved, including sanitized KB lifecycle summary and cleanup
  result without publishing dataset or document IDs;
- field_trial_metrics ok/finding count;
- redaction review;
- whether the real PDF handoff is ready for current KB build use;
- residual risks and recommended next action.
```
