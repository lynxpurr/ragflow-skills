---
doc_type: plan
topic: generic-runtime-compatibility-implementation
status: implemented
created: 2026-08-13
updated: 2026-08-14
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-13-generic-runtime-compatibility-design.md
supersedes: []
superseded_by: null
related:
  - docs/03-development-plan.md
  - docs/15-field-trial-observation-plan.md
---

# Generic Runtime Compatibility Implementation Plan

**Goal:** Deliver and verify the public, offline-first S0-S3 generic contracts in the
owning specification without accessing a live service.

**Architecture:** Extend the shared runtime and existing artifact families. Public skill
scripts remain thin CLI adapters; deterministic fake clients and local fixtures protect
mutation, review, freeze, release, and consumer boundaries.

**Tech Stack:** Python 3.10+, standard library, `unittest`/`pytest`, existing release and
document-governance tools.

## Authority Boundary

The 2026-08-13 owner request authorized source, test, governed documentation, local
generated-output, and no-network validation changes required by this plan. It did not
authorize credentials, private services, live RAGFlow mutation, production routing, or
publication. A later explicit request separately authorized repository commit and branch
push as version-control closure only; it did not expand operational authority.

### Task 1: S0 Baseline And Lifecycle

**Files:**

- Modify: `docs/document-registry.json`
- Modify: `docs/README.md`
- Modify: `docs/03-development-plan.md`
- Create: `docs/specs/2026-08-13-generic-runtime-compatibility-design.md`
- Create: `docs/plans/2026-08-13-generic-runtime-compatibility-implementation-plan.md`
- Archive locally: reviewed source requirements under `reqs/archive/2026-08-13/`

- [x] Register the approved spec and active plan without exposing private requirement material.
- [x] Record the S0-S3 gap and acceptance matrix in the current roadmap.
- [x] Run document lifecycle, release hygiene, baseline tests, build, consumer, and platform gates.

### Task 2: S1 RCKB-001 API Contract And Recovery

**Files:**

- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Test: `packages/ragflow-skill-runtime/tests/test_kb_build.py`
- Test: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`

- [x] Add canonical construction fingerprint and layered create diagnostics.
- [x] Add unique exact-name, matching-fingerprint recovery for missing create IDs.
- [x] Bind checkpoint resume to name, construction fingerprint, and plan hash.
- [x] Prove malformed, application-failure, zero-match, ambiguous, and drift paths fail closed.

### Task 3: S1 RCKB-002 Multimodal Transport Gate

**Files:**

- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Test: `packages/ragflow-skill-runtime/tests/test_kb_build.py`
- Test: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`

- [x] Add explicit image transport capability evidence and pre-mutation verification.
- [x] Add plan/checkpoint/read-back lineage fields to `ragflow_multimodal_kb_manifest_v1`.
- [x] Preserve `parsed_visual_only` as staging-only evidence.
- [x] Prove unsupported or unknown transports stop before fake-client mutation.

### Task 4: S2 RCKB-003 Reviewed Hint Lifecycle

**Files:**

- Create: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/retrieval_hint_governance.py`
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/handoff.py`
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/topology.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Test: focused runtime and CLI tests beside the existing suite

- [x] Add deterministic candidate IDs, source constraints, document type, and content hash.
- [x] Add exhaustive review artifact creation with accepted/rejected reasons and hashes.
- [x] Require reviewed hints for activation and reject rejected-ID reintroduction.
- [x] Prove operational instructions cannot become product-catalog hints without evidence.

### Task 5: S3 RCKB-004 Evaluation Freeze

**Files:**

- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Test: focused benchmark runtime and CLI tests

- [x] Add split freeze creation with role, time, hashes, tuning, evaluator, and binding digest.
- [x] Add immutable freeze verification against current query/qrel bytes.
- [x] Reject sealed-holdout tuning and non-independent evaluation.
- [x] Preserve existing benchmark behavior when no sealed-holdout claim is made.

### Task 6: S3 RCKB-005 Consistent Evidence

**Files:**

- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/health_report.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Test: `packages/ragflow-skill-runtime/tests/test_health_report.py`
- Test: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`

- [x] Add independent provider, parse, retrieval, and activation readiness dimensions.
- [x] Bind supplied evidence to schema, content hash, and run identity.
- [x] Prove unknown provider enumeration does not collapse overall health to failure.

### Task 7: Public Contract And Release Closure

**Files:**

- Modify: schema identity, report surface, runtime resilience, public skill references,
  and owning roadmap documents as required by the actual surface.

- [x] Update schema identity, report inventory, sanitization, and generated Markdown coverage.
- [x] Run focused tests and the full runtime test suite after the final code change.
- [x] Run document lifecycle, release hygiene, build, archive export, consumer acceptance,
  and strict-vendor platform smoke sequentially.
- [x] Record source revision, validation counts, release manifest/archive hash, installed-copy hash, and residual live-evidence gate.
- [x] Close the plan and revoke implementation authority after all public offline acceptance criteria pass.

## Implementation Closeout

The S0-S3 public offline slice and its release-facing gates completed on 2026-08-14.
The implementation source is commit `57026c3`. The generated archive and installed-copy
hashes below identify the release bytes exported from that commit.

Validation results:

| Gate | Result |
| --- | --- |
| Complete runtime suite | 874 tests passed |
| Document lifecycle | 72 documents, 0 findings |
| Schema identity | 125 identities, 0 failures |
| Manifest schema | 3 schemas, 0 findings |
| Release hygiene | `ok=true`, 0 findings |
| Release build and archive export | passed |
| Clean consumer acceptance | `ragflow_consumer_acceptance_v1`, 268 checks, 0 failures |
| Strict-vendor platform smoke | 154 checks, 0 failures |

Release evidence:

| Artifact | SHA-256 |
| --- | --- |
| Release manifest | `9ad05c37926d61e9893bba96bf04c32578e4d68235766c7b24a263f05a8e9857` |
| `ragflow-doc-to-md.tar.gz` | `e51b0cc0b5ac36cecf076dbe3cd8e48dbb4ead0de59f2355861f380e8fac034b` |
| `ragflow-canonical-review.tar.gz` | `9e796ddf9080d99e1f28446643f3eb11579b5f8ca72362cbcf3b1fa9ea827abf` |
| `ragflow-kb-build.tar.gz` | `9573e1e38b6cbf12e464a8621bec73454eff7d6b1c65e7e32d07ce89ad3fd4ee` |
| `ragflow-query.tar.gz` | `3a5224dbb06a5134e4e3c2fd539fa23056f8d181d7ceecc6b95e05e635d2d594` |

All four consumer-extracted vendored runtime trees report version `0.1.0`, contain 50
files, and match installed-copy SHA-256
`f6c3b57428d1a4cc1d35593fe1389c0b47e618f6d93a55c4ecbe2fc867d46464`.
The digest algorithm is `sha256-relative-path-size-bytes-v1`: each relative path, byte
length, and file content is framed and hashed in sorted relative-path order.

No credentials or live services were used. Live RAGFlow/MinerU compatibility, production
routing, and publication remain unperformed and unauthorized. Repository commit and
branch push are version-control closure only. This plan is therefore implemented and
non-authoritative; the active owning specification preserves the compatibility contract
without reopening operational authority.

## Rollback

Revert this source slice as one unit and retain the prior verified release archives.
Do not migrate or rewrite user artifacts automatically. Additive fields may be ignored by
older consumers; new hint/freeze artifacts can be removed without changing existing
candidate or benchmark files.

## Stop Conditions

- A required behavior cannot be implemented without credentials or live mutation.
- A public contract requires a backward-incompatible schema meaning change.
- Recovery cannot prove one exact matching dataset fingerprint.
- Existing release/consumer gates reveal an unrelated baseline failure that prevents a
  trustworthy acceptance decision.
