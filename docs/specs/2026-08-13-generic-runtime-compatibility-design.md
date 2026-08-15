---
doc_type: spec
topic: generic-runtime-compatibility
status: active
created: 2026-08-13
updated: 2026-08-14
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related:
  - docs/03-development-plan.md
  - docs/15-field-trial-observation-plan.md
  - docs/plans/2026-08-13-generic-runtime-compatibility-implementation-plan.md
---

# Generic Runtime Compatibility Design

## Context

The public suite owns `ragflow-doc-to-md`, `ragflow-kb-build`, `ragflow-query`, and the
shared Python runtime. A downstream canonical-content workflow needs deterministic,
generic contracts for staging builds, multimodal evidence, reviewed retrieval hints,
and evaluation provenance. Domain allowlists, content approval, production routing, and
deployment policy remain downstream responsibilities.

The reviewed 2026-08-09 handoff was promoted from the private requirements workspace.
The owner request on 2026-08-13 approved this sanitized specification and the linked
public, offline-first implementation plan. The implementation and offline release gates
closed on 2026-08-14, so this specification remains the canonical compatibility contract
but no longer grants implementation authority. It does not authorize credentials,
private fixtures, network access, live RAGFlow mutation, production route changes,
or publication. Repository commit and branch push are separately authorized
version-control closure only and do not expand operational authority.

Existing primitives already cover layered HTTP/application failures, ingestion
checkpoints, `ragflow_multimodal_kb_manifest_v1`, candidate retrieval hints, benchmark
artifacts, health reports, release archives, and consumer validation. This design
extends those contracts instead of adding parallel systems.

## Objective

Provide a backward-compatible generic runtime and self-contained release that a
downstream orchestrator can use for safe staging builds, transport-gated image
ingestion, reviewed-hint activation planning, frozen evaluation splits, and independent
readiness evidence.

| ID | Owner | Observable capability |
| --- | --- | --- |
| `RCKB-001` | shared runtime and `ragflow-kb-build` | read-only API evidence, layered diagnostics, fingerprint-bound create recovery, and idempotent resume |
| `RCKB-002` | both build skills and shared runtime | image transport gate and unified multimodal manifest lineage |
| `RCKB-003` | both build skills and shared runtime | candidate, reviewed, and activation hint lifecycle |
| `RCKB-004` | benchmark governance | development, regression, and sealed-holdout provenance and freeze enforcement |
| `RCKB-005` | health and activation reporting | separate provider, parse, retrieval, and activation readiness evidence |

The established source tests, release hygiene, archive build, consumer acceptance, and
platform smoke chain are S0 prerequisites and the final release gate.

## Non-Goals

- Implement downstream canonical allowlists, domain review, image-description policy,
  or canonical-to-handoff orchestration.
- Perform production route switching, dataset deletion, key rotation, deployment,
  publication, or live-service validation.
- Discover a capability by creating a disposable dataset without separate authority.
- Introduce a second multimodal manifest, checkpoint family, release-readiness schema,
  credential scanner, or downstream source-code copy.
- Make candidate hints operational without an explicit reviewed artifact.
- Treat unknown provider enumeration as parse, retrieval, or activation failure.

## Requirements And Invariants

### API contract, diagnostics, and recovery

- Capability evidence records source as `openapi`, `server_version`, `operator`, or
  `unknown`; optional fields without evidence stay `unknown` and are omitted from
  mutation payloads.
- Diagnostics keep transport status, application status, a sanitized message, response
  root/data shape, and known field paths separate. HTTP success with non-zero
  application status is a failure.
- Every dataset construction attempt has a canonical SHA-256 fingerprint over dataset
  name, normalized create payload, and ordered source content hashes.
- A create response without an identifier can recover only from one exact-name result
  whose observed construction fingerprint equals the requested fingerprint. Zero,
  multiple, or mismatched candidates stop before upload and record a recovery decision.
- Checkpoint resume revalidates dataset name, construction fingerprint, and plan hash.
  Existing version-one checkpoints remain readable, but lack of a fingerprint blocks
  mutation resume until explicitly regenerated.

### Multimodal ingestion

- Every image upload, parse trigger, document update, and deletion step declares its
  transport method and endpoint class. Live image mutation requires capability evidence
  that explicitly permits the planned method and operation.
- A shared HTTP base URL is connectivity evidence only; it is not proof that a curated
  image `PUT` or deletion contract exists.
- Image execution updates the existing `ragflow_multimodal_kb_manifest_v1` lineage with
  upload, document ID, thumbnail, parse, update, deletion, checkpoint, plan hash, and
  read-back states. No competing manifest is added.
- `parsed_visual_only` is an allowed staging outcome but cannot satisfy an enhanced-image
  production gate. Mutation remains behind existing execute and exact-target controls.

### Hint lifecycle

- `ragflow-doc-to-md` emits only `ragflow_retrieval_hints_v1` candidate hints.
- Candidate IDs are deterministic and retain kind, value, source document, source
  document type, source constraint, and input content hash.
- `ragflow-kb-build hints review` creates `ragflow_reviewed_retrieval_hints_v1` from one
  candidate artifact and an explicit decision artifact. Every candidate is accepted or
  rejected with a reason; input and output hashes bind the review.
- Duplicate IDs, unknown decisions, omitted candidates, hash drift, missing source
  constraints, and unsafe product-catalog classification fail closed. Operational
  instructions cannot be accepted as product-catalog hints without source evidence.
- Activation planning consumes reviewed hints only. Rejected IDs are retained in the
  audit lineage and cannot be reintroduced by candidate regeneration or suggestion
  passes.

### Evaluation provenance and freeze

- `ragflow-kb-build benchmark freeze` emits `ragflow_benchmark_split_freeze_v1` with
  split name, role, freeze time, query hash, qrel hash, tuning participation, evaluator
  independence, and a binding digest.
- Roles are `development`, `regression`, and `sealed_holdout`. A sealed holdout cannot
  participate in tuning and requires an evaluator independent of the current diagnostic
  round.
- `ragflow-kb-build benchmark verify-freeze` recomputes hashes and fails on post-freeze
  mutation or provenance mismatch without rewriting the freeze artifact.
- Existing benchmark inputs remain valid when no freeze artifact is supplied; claims
  about sealed-holdout evaluation require a verified freeze.

### Consistent readiness evidence

- A compatibility readiness block reports provider observability, parse readiness,
  retrieval evidence, and activation readiness separately, each as `ready`, `review`,
  `blocked`, or `unknown` with source schema/hash.
- Unknown or unavailable provider enumeration remains `unknown`; it does not collapse an
  otherwise valid parse or retrieval result into an overall failure.
- Inputs and outputs bind by SHA-256 content hashes and run identity. Paths are labels,
  not identity evidence.

### Release and consumer boundary

- Source changes stay under `packages/`, `skills/`, `tools/`, and governed `docs/`.
  Generated output is never edited as source.
- Public standalone reports have stable schema identities, producer tests, report
  inventory coverage, sanitization support where applicable, and release-hygiene checks.
- A downstream consumer can compare source commit, release manifest hash, archive hash,
  runtime version, and installed-copy hash without receiving private configuration.

## Design

Shared behavior belongs in focused runtime modules:

- `kb_build.py` owns construction fingerprints, create-recovery decisions, transport
  capability checks, and multimodal lineage helpers because these extend existing build
  contracts.
- a retrieval-hint governance module owns deterministic candidate normalization, review,
  and reviewed-artifact validation; both build skills call it through thin adapters.
- `benchmark_governance.py` owns freeze creation and verification beside existing
  benchmark import, preflight, sampling, and report comparison.
- `health_report.py` owns the compatibility readiness aggregation embedded in the
  existing `ragflow_kb_health_report_v1`; no second overall health report is introduced.

New CLI surface is limited to `ragflow-kb-build hints review`, `benchmark freeze`, and
`benchmark verify-freeze`. Existing `activation-plan`, live build, image-ingestion, and
health commands gain optional compatible inputs or fields. New fields are additive and
optional for older consumers.

Failure fixtures use fake clients and local JSON only: non-zero application code,
malformed create response, ambiguous exact-name recovery, fingerprint mismatch,
unsupported image transport, manifest read-back drift, omitted/reintroduced/reclassified
hints, sealed split mutation, non-independent holdout evaluation, and unknown provider
state.

## Compatibility And Migration

- Existing command names and successful report fields retain their meaning.
- Version-one ingestion checkpoints remain parseable for audit and cleanup; mutation
  resume requires the new fingerprint binding.
- `ragflow_multimodal_kb_manifest_v1`, `ragflow_retrieval_hints_v1`, benchmark manifests,
  activation plans, and health reports remain the canonical artifact families.
- Candidate producers add deterministic lineage fields. Consumers that ignore them can
  continue reading candidate hints; activation is the boundary that requires a reviewed
  artifact.
- Benchmark freeze artifacts are opt-in for development/regression workflows and
  mandatory only for a sealed-holdout claim.

## Failure Handling And Rollback

- Stop before mutation on unknown contract, target mismatch, unsupported transport,
  ambiguous recovery, plan/fingerprint drift, unreviewed hints, or failed freeze checks.
- Preserve checkpoints and manifests after partial mutation. Resume only verified plan
  entries after re-reading target state.
- Do not issue broad deletes or recreate a dataset to hide an ambiguous create result.
- Rollback selects the previous verified release and installation. This design does not
  authorize production switching or live cleanup.
- If release or consumer gates fail, keep the prior accepted release and leave this
  implementation unaccepted until the failure is resolved.

## Validation Strategy

1. Run focused runtime and CLI tests for each RCKB contract with deterministic fakes.
2. Run affected schema identity, report surface, generated Markdown, runtime resilience,
   document lifecycle, and release hygiene tests.
3. Run the complete runtime test suite.
4. Run release build, archive export, clean consumer acceptance, and strict-vendor
   platform smoke.
5. Record exact commands, result counts, source revision, release-manifest hash, archive
   hash, and installed-copy hash in a sanitized closeout.
6. Keep live RAGFlow validation opt-in and separately authorized.

## Acceptance Criteria

- `RCKB-001`: focused tests prove layered diagnostics, exact unique recovery, fingerprint
  mismatch rejection, ambiguous recovery rejection, and resume drift rejection.
- `RCKB-002`: image execution fails before mutation without matching transport evidence,
  resumes by checkpoint, and updates one multimodal lineage with read-back state.
- `RCKB-003`: candidate review is hash-bound and exhaustive; activation rejects candidate
  schemas, rejected-term reintroduction, and the operational-instruction/catalog case.
- `RCKB-004`: split freeze records required provenance; sealed holdout tuning,
  non-independent evaluation, and post-freeze file changes fail closed.
- `RCKB-005`: health output exposes independent provider, parse, retrieval, and activation
  statuses; unknown providers alone do not cause overall failure.
- Full tests and the release/consumer chain pass, with exact hashes available to a
  downstream consumer. Any unavailable live evidence is reported as unverified rather
  than inferred.

## Implementation Status

The public offline implementation and release acceptance chain completed on 2026-08-14.
The linked implementation plan records the exact test counts, implementation source
commit, release manifest and archive hashes, runtime version, and installed-copy tree
hash. The consumer report now emits `ragflow_consumer_acceptance_v1` and independently
verifies both archive hashes and all four vendored runtime copies.

No live RAGFlow or MinerU compatibility run was authorized or performed. Production
activation and any downstream canonical orchestration therefore remain separate,
evidence-gated work; that limitation does not reopen the completed public offline slice.

## Decision Log

| Decision | Rationale |
| --- | --- |
| Keep downstream canonical orchestration outside this repository | Domain review and production policy are not generic runtime concerns. |
| Extend existing artifact families | Preserves compatibility and avoids competing sources of truth. |
| Use content fingerprints, not paths, for recovery and freeze identity | Paths are mutable labels and cannot prove construction equivalence. |
| Require reviewed hints only at activation | Candidate generation stays useful while the operational boundary fails closed. |
| Keep live validation separately gated | Offline implementation authority does not imply credentials or mutation authority. |
