---
doc_type: plan
topic: canonical-multimodal-ingest-quality
status: proposed
created: 2026-08-14
updated: 2026-08-14
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related:
  - docs/03-development-plan.md
  - docs/15-field-trial-observation-plan.md
  - docs/16-system-closeout-report.md
---

# Canonical Multimodal Ingest Quality Improvement Plan

Status: proposed; implementation and live mutation are not authorized by this document
Date: 2026-08-14
Scope: `ragflow-doc-to-md` -> `ragflow-canonical-review` -> `ragflow-kb-build` -> `ragflow-query`

## Objective / Scope / Boundaries

Make canonical review an explicit, verifiable stage before a formal KB build when the host
selects canonical mode. The smallest useful outcome is:

1. HTML tables are reviewed and converted to Markdown when they are source-faithful row and
   column facts, or are retained only with an explicit source-backed exception.
2. Selected image assets are present in the new handoff and the existing image-ingestion
   workflow is actually executed when live image ingestion is requested.
3. `ragflow-kb-build` cannot consume a canonical-mode handoff without a matching review
   record.

The ownership boundaries remain unchanged:

- `ragflow-doc-to-md` extracts content and materializes local assets; it does not claim
  source-fidelity review.
- `ragflow-canonical-review` reconciles the candidate with the exact source, repairs local
  Markdown, audits assets, and emits a review record. It does not call a live KB.
- `ragflow-kb-build` owns text and image transport through the target deployment's verified
  RAGFlow API contract. Canonical review is not a network `PUT` operation.
- `ragflow-query` validates table and image retrieval after an authorized build.

Provider and model selection is always supplied by the user or deployment. No provider name,
model, management-plane enumeration endpoint, or implicit default is part of this plan's
schemas or control flow.

This plan does not authorize credentials, network access, live mutation, deletion, production
activation, commit, push, or publication. It does not authorize changing or deleting the
retained field-trial KB. Existing generic build behavior remains unchanged when canonical
mode is not selected.

## Problem Description

The retained MinerU-to-RAGFlow field trial exposed a skipped workflow stage rather than a
missing conversion backend:

- the live build consumed the extraction handoff without canonical audit or acceptance;
- the Markdown contained six balanced HTML tables and zero Markdown tables; postprocessing
  preserved all six HTML table fingerprints and 258 cells, proving integrity only;
- the handoff contained 13 Markdown image references and 24 image artifact records, but the
  plan was offline-only and image readiness/execution were never invoked; the KB therefore
  contained only the Markdown document;
- `PASS_WITH_REVIEW` and `ready_with_review` allowed text ingestion to proceed without
  distinguishing “conversion succeeded” from “canonical review accepted”.

The current repository already provides useful primitives that must be reused:

- `audit_markdown_structure.py` reports HTML residue, table boundaries, chunk findings, and
  image-reference integrity;
- `audit_canonical_assets.py` provides positive asset-boundary review;
- `asset-upload-plan`, `image-ingestion-readiness`, and `image-ingestion-execute` already
  provide planning, transport capability gates, exact confirmations, checkpoint/resume,
  upload, parse, and server-state read-back;
- the generic runtime already keeps provider, parse, retrieval, and activation evidence
  separate.

## Review Findings And Scope Controls

The first version of this plan was too broad. The following items are deliberately removed
from the mandatory work:

- a second table-normalization schema and a general-purpose automatic converter;
- six new readiness dimensions copied into build, checkpoint, manifest, refresh, parse, and
  health reports;
- a new image-ingestion state machine or a curated image-text `PUT` adapter without a
  verified target API contract;
- provider-specific adapter or provider-enumeration work;
- a new public evidence summary that duplicates the existing private field-trial record.

These are not required to prevent the observed failure. They become future work only when a
reviewed trigger is met: at least two independent field trials show the same deterministic
table conversion error, an existing image command fails with a verified transport contract,
or a concrete provider/API contract requires an adapter.

## Minimal Design

### One canonical review record

Add one machine-readable `ragflow_canonical_review_v1` record after source review. It binds:

- exact source SHA-256;
- candidate Markdown SHA-256 and accepted Markdown SHA-256;
- source-coverage status, coverage-record SHA-256, and uncovered-unit count;
- structural and asset audit report hashes;
- per-table action: `converted_to_markdown` or
  `retained_html_by_exception`, with source reference, before/after table hash, and reason;
- selected image paths and SHA-256 values after positive asset review;
- unresolved item count and final status: `accepted`, `blocked`, or
  `needs_source_verification`.

The record is an acceptance assertion, not an automatic source-fidelity proof. Exact-source
review remains a host-agent responsibility. Hashes prevent the accepted record from being
silently reused with different Markdown or assets.

The source-coverage input is intentionally small: `status` (`complete` or `incomplete`),
`covered_units`, `uncovered_units`, and its SHA-256. An `accepted` record requires
`status=complete` and an empty `uncovered_units` list; no separate coverage schema or
service is introduced.

### Table handling

Keep `audit_markdown_structure.py` read-only. During canonical review, repair the six tables
in the candidate Markdown using the existing table rules:

- expand inherited `rowspan` values when each row must stand alone;
- flatten multi-level headers into explicit field paths;
- preserve units, conditions, footnotes, order, blanks, and inline math;
- keep one complete table in one chunk;
- stop on ambiguity instead of inventing cells or units.

For the current source, each table must receive a recorded decision. Expected reusable
row/column tables should become Markdown; a retained HTML table needs an explicit reason and
visual source reference. No automatic converter is required for the first implementation
slice. A deterministic helper can be proposed later only after the trigger in the scope
controls is met.

### Image handling

Use the final canonical Markdown and the existing positive asset audit as the source of truth.
Then run the existing sequence:

```text
asset-upload-plan
  -> image-ingestion-readiness
  -> explicit mutation approval
  -> image-ingestion-execute
  -> server document-state read-back
```

Do not introduce a new image state model. The existing execution report already distinguishes
upload and parse outcomes and supports transport evidence, checkpoint/resume, and partial
failure. `parsed_visual_only` is not a claim that curated image text was produced; a curated
text update remains separately gated on a verified deployment contract.

### Canonical build gate

Add an optional `--canonical-review` input to `ragflow-kb-build`. In canonical mode it must:

- validate `ragflow_canonical_review_v1`;
- verify the supplied source, Markdown, audit, and selected-asset hashes;
- reject blocked, source-unverified, stale, or unresolved review records before client
  creation;
- bind the review-record hash into the build checkpoint and `kb_manifest.json`.

Do not copy the new record into refresh, parse, health, or query reports unless a later
consumer demonstrates a concrete need. Existing reports can reference the KB manifest and
checkpoint as the single lineage source.

## Update Plan

### P0 - Correct the host workflow and historical claims

Update canonical-review and KB-build host guidance so the required order is explicit:

```text
MinerU handoff
  -> structural audit and exact-source canonical review
  -> table decisions and asset audit
  -> new canonical passthrough handoff
  -> inspect-handoff and asset-upload-plan
  -> image readiness and build dry-run
  -> approved live text/image operations
```

Correct the field-trial observation wording that currently describes the conversion path as
sufficient for high-quality handoff: conversion and table integrity passed, but canonical
acceptance and live image ingestion were not demonstrated.

### P1 - Implement the single acceptance record

Add a small `finalize_review.py` adapter under `skills/ragflow-canonical-review/scripts/`
and shared validation helpers under `ragflow_skill_runtime`. It consumes the existing
Markdown/asset audit reports, a source-coverage record, and a reviewed table-decision file
and emits one JSON record.
It must never overwrite the candidate Markdown.

Focused tests cover accepted, blocked, source-unavailable, missing-image, stale-hash,
unreviewed-HTML, and explicit-retained-HTML cases.

### P2 - Bind the record at the build boundary

Add the optional canonical-review input to dry-run and live build. Add fake-client tests
proving that missing or stale acceptance fails before dataset creation, and that an accepted
record's hash appears in the checkpoint and KB manifest. Leave non-canonical builds and
existing image commands backward compatible.

### P3 - Re-run the existing offline chain

For the representative PDF:

1. preserve the original extraction handoff as pre-change evidence;
2. review and repair all six tables against the exact source;
3. classify the images and create the accepted canonical handoff;
4. run `inspect-handoff`, `asset-upload-plan`, `image-ingestion-readiness`, and build
   dry-run against the new handoff;
5. require zero unreviewed HTML tables, zero missing selected assets, and matching hashes.

No RAGFlow mutation is needed for this phase.

### P4 - Run a separately authorized live correction

Only after P0-P3 and offline release gates pass:

1. create a new correction KB and retain the earlier KB unchanged;
2. use the provider and models explicitly selected for that run;
3. upload/parse selected images through the existing transport-gated command;
4. verify server document-state read-back, parsed counts, table retrieval, image-context
   retrieval, and optional configured rerank behavior;
5. retain both KBs and private evidence, with no cleanup unless separately approved.

Repairing the earlier KB in place is outside this plan and requires a separate target and
rollback review.

## Task Checklist

### P0 - Workflow and documentation

- [x] Update canonical-review and KB-build host guidance with the ordered, non-skippable
  canonical stage and existing image commands.
- [x] Reconcile field-trial observation and closeout wording so conversion success is not
  presented as canonical or multimodal completion.
- [x] Define the one `ragflow_canonical_review_v1` schema and stop conditions.

### P1 - Acceptance implementation

- [x] Add focused tests for accepted, blocked, missing-source, incomplete-coverage,
  missing-asset, stale-hash,
  unreviewed-HTML, and retained-HTML decisions.
- [x] Implement shared hash/decision validation and `finalize_review.py`.
- [x] Preserve candidate and pre-change handoff bytes; write accepted outputs separately.

### P2 - Build binding

- [x] Add optional canonical-review input and canonical-mode fail-closed validation to
  `ragflow-kb-build` dry-run/live paths.
- [x] Bind only the review-record hash into the build checkpoint and KB manifest.
- [x] Add fake-client tests for missing, stale, blocked, and accepted review records.

### P3 - Offline evidence

- [ ] Review all six tables against the exact source and record one decision per table.
- [ ] Generate a new canonical handoff and verify zero unreviewed HTML residue.
- [ ] Run existing handoff, asset-plan, image-readiness, and build-dry-run checks with no
  live mutation.
- [ ] Preserve the original run as pre-change evidence and retain sanitized metrics only in
  public documentation.

### P4 - Approval-gated live evidence

- [ ] Obtain explicit approval for a new retained correction KB and listed mutation types.
- [ ] Build with the explicitly selected provider/model configuration and verify operations
  rather than provider enumeration.
- [ ] Execute existing image ingestion with matching capability evidence and server read-back.
- [ ] Validate table facts, image context, direct retrieval, and optional configured rerank.
- [ ] Retain the earlier and correction KBs; perform no cleanup.

### Deferred only on evidence

- [ ] Add an automatic table normalizer only if two independent trials demonstrate repeated
  deterministic conversion errors or unacceptable manual review cost.
- [ ] Add curated image-text update support only after a concrete, verified deployment API
  contract and a user-approved adapter scope exist.

## Current Development Progress

P0, P1, and P2 are implemented and verified for the public offline surface. Canonical-review
and KB-build host guidance now enforces the ordered review/new-handoff/readiness sequence;
field-trial and closeout wording distinguishes conversion evidence from canonical or
multimodal completion; and `ragflow_canonical_review_v1` is the single public acceptance
record. The shared runtime and thin `finalize_review.py` CLI validate exact-byte hashes,
source coverage, table decisions, selected assets, and accepted-output isolation. Focused
runtime/CLI and schema/report/inventory tests cover the required success and stop cases.
KB-build now accepts the review record plus its exact source and audit evidence on dry-run
and live paths, rehashes the new handoff Markdown and selected assets before client
creation, and binds only `canonical_review_sha256` into the live checkpoint and
`kb_manifest.json`. Generic builds remain compatible when canonical options are absent.

P3 and P4 are not implemented. The representative six-table offline chain has not been
replayed into a new canonical handoff, and no live correction has been attempted. P4 still
requires a new, target-specific authorization that names the exact live text/image
mutations; no earlier field-trial or repository-maintenance approval can be reused.
Deferred automatic table conversion and curated image-text update work remain closed until
their documented evidence triggers are met.

## Validation Evidence / Residual Gated Work

### Offline evidence

For the implementation slice, run focused canonical-review, HTML-table, handoff, and KB-build
tests, then the full runtime suite and the repository's document lifecycle, schema identity,
release hygiene, build-release, consumer acceptance, and strict-vendor platform smoke checks.
The `ragflow_canonical_review_v1` acceptance schema is registered in the existing schema,
report, sanitization, and runtime-resilience inventories; no new report family is created
for table normalization.

### Live acceptance evidence

| Dimension | Minimum evidence |
| --- | --- |
| Canonical content | Accepted review record; exact source bound; zero unresolved required decisions. |
| Tables | Six table decisions; zero unreviewed HTML residue; Markdown tables structurally valid and source-faithful. |
| Assets | Selected assets hash-bound; zero missing selected assets; asset plan agrees with handoff. |
| Text | Accepted Markdown hash bound to handoff, checkpoint, and KB manifest; parse succeeds. |
| Images | Existing image execute report shows upload/parse outcome and server read-back; no silent skip. |
| Models | User-selected embedding/rerank operations succeed; provider enumeration is not required. |
| Retrieval | Table-fact and image-context queries return accepted evidence. |
| Retention | Earlier and correction KBs remain present; no cleanup call. |

### Residual gated work

- Live KB creation and image mutation require explicit target-specific authority.
- A deployment without a verified curated image-text update contract may stop at
  `parsed_visual_only`; it must not claim enhanced image text.
- Source-faithful review remains mandatory for merged headers, visual grouping, footnotes,
  and ambiguous blanks.
- Provider adapters, production activation, route switching, and in-place repair of the
  earlier KB remain outside this plan.

## Rollback And Stop Conditions

Write canonical Markdown and review outputs beside the extraction candidate. Never overwrite
the candidate or pre-change evidence. Stop before live client creation when the review record
is missing, stale, blocked, source-unverified, unresolved, or hash-inconsistent; when selected
assets are missing; when image transport evidence does not match the existing command; or
when explicit mutation approval is absent.

During an approved correction, stop on partial mutation, record the existing checkpoint,
re-read server state, and resume only verified image plan entries. Do not delete either KB as
rollback. Any in-place repair needs a separate plan with exact target identity, before-state
evidence, rollback bytes, and owner approval.
