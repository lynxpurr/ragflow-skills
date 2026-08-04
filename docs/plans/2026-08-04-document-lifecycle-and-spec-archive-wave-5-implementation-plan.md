---
doc_type: plan
topic: document-lifecycle-and-spec-archive-wave-5
status: implemented
created: 2026-08-04
updated: 2026-08-04
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related:
  - docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-4-implementation-plan.md
---

# Document Lifecycle And Spec Archive Wave 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the repository documentation scheme, publish the missing evidence-authoring
entrypoint, and calibrate the lifecycle of the governance spec and its five plans without
performing any deferred migration.

**Architecture:** The existing lifecycle checker already implements the adoption boundary:
after `docs/document-registry.json` sets `adopted=true`, new tool-specific document paths
fail while the four reviewed legacy paths remain grandfathered. Wave 5 therefore needs no
new checker behavior. It performs a pre-closeout validation pass, applies one bounded
documentation transition, then repeats the complete validation on the final bytes.

**Tech Stack:** Markdown, JSON, Python 3.10+ standard library, `unittest`, `rg`, and the
repository-local lifecycle, release-hygiene, and release-build checks.

---

## Governance Binding

| Field | Frozen planning value |
| --- | --- |
| Execution state | `NOT_STARTED` |
| Governing spec | `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` |
| Governing spec SHA-256 | `9faf2204bd4184a5d16b3cf82a6d5b26c7c2dbf1c33fae30a2372b8c8ad373fb` |
| Governing state | `status=approved`, `gate_0=closed`, `implementation_authority=false` |
| Planning branch | `feature/document-lifecycle-governance` |
| Pushed Wave 4 baseline | `957a8e60ace086333addd064fbc68eb4e1adce7f` |
| Wave 4 plan SHA-256 | `4bfca05f8f054bcb78d52e7f7567970caa4f0cbb0b354ad79d29d101640de7e1` |
| Registry baseline before this plan | 65 documents, 20 migrations, `adopted=false` |
| Roadmap baseline | 586 checked, 15 unchecked |

This file is planning evidence only. Its path, bytes, registry entry, review, or checksum
does not authorize Wave 5 execution. Future authority must name this plan's exact SHA-256
and authorize `Wave 5 closeout` explicitly.

Wave 5 authority does not include Wave 2D, either deferred Wave 3 reference, any other
migration, a move of the skill-surface spec, external maintainer files, private handoffs,
network access, credentials, live operations, generated release products, staging,
commit, push, merge, L3, Stage 8C, or L4.

## Planning-Only Change Set

Creating this proposed plan changes exactly three paths:

- create `docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-5-implementation-plan.md`;
- register it in `docs/document-registry.json` as `wave1_governance`;
- link it from `docs/README.md` and record the pushed Wave 4 checkpoint.

Planning acceptance requires lifecycle `66/66/0`, 20 migrations, `adopted=false`, roadmap
`586/15`, empty staging, and exactly these three dirty paths. Every task below describes
future work and remains unauthorized.

## Selected Adoption Contract

Wave 5 adopts the tool-neutral taxonomy for new work. It does not retroactively move the
existing proposed skill-surface spec. That document predates adoption, remains active on
a separate topic, and already has the reviewed `legacy_path=true` registry classification.
Moving it now would add path churn without advancing this governance closeout.

The final four-path compatibility set remains byte-for-byte unchanged:

```text
docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md
docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md
docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md
docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md
```

After adoption:

- a new spec must use `docs/specs/`;
- a new implementation plan must use `docs/plans/`;
- new sanitized outcome evidence must use `docs/evidence/`;
- a new unregistered `docs/superpowers/` document must fail lifecycle validation;
- no new document may claim `legacy_path=true`;
- the four reviewed legacy files remain valid until their own terminal migration is
  separately planned and authorized.

This choice follows the governing spec's rule that registry-listed legacy paths may
remain until terminal migration. It adds no migration record and changes no current
consumer path.

## Final Lifecycle Contract

The final lifecycle values are:

| Path | Current | Final | Rationale |
| --- | --- | --- | --- |
| `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` | `approved` | `active` | It remains the canonical operating policy and registry owner after adoption. |
| `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md` | `proposed` | `implemented` | Its only executable scope, Wave 1, is complete. |
| `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md` | `proposed` | `gated` | Waves 2A-2C are complete; Wave 2D still requires private-handoff closure or refresh. |
| `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-3-implementation-plan.md` | `proposed` | `gated` | Waves 3A-3B are complete; `docs/16` and `docs/43` remain separately blocked. |
| `docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-4-implementation-plan.md` | `proposed` | `implemented` | Waves 4A-4B are complete and pushed. |
| `docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-5-implementation-plan.md` | `proposed` | `implemented` | Adoption and both validation passes will be complete. |

The governing spec deliberately becomes `active`, not `implemented`. The checker requires
the registry governing spec and ordinary plan owner to be canonical and `approved` or
`active`; more importantly, the policy remains in force after rollout. Marking it terminal
would misrepresent that continuing responsibility and invalidate future governed plans.

The Wave 2 and Wave 3 frontmatter gains these exact non-empty structured gates:

```yaml
gate: private_handoff_closure_or_refresh_for_wave_2d
```

```yaml
gate: separate_owner_resolution_for_docs_16_and_docs_43
```

No task checkbox changes. Existing task bodies remain as implementation provenance. Each
plan receives only a short final lifecycle note so stale `NOT_STARTED` text cannot be
mistaken for current state.

## Exact Future Change Set

An authorized Wave 5 execution may change exactly these nine paths:

1. create `docs/evidence/README.md`;
2. modify `docs/README.md`;
3. modify `docs/document-registry.json`;
4. modify `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md`;
5. modify `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md`;
6. modify `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md`;
7. modify `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-3-implementation-plan.md`;
8. modify `docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-4-implementation-plan.md`;
9. modify this Wave 5 plan.

No Python, test, skill, roadmap, archive, reference, release artifact, external file, or
private handoff is in scope.

## Task 0: Read-Only Preflight And Rollback Snapshot

**Files:**

- Read: the nine authorized paths or expected-absent destination above
- Read: `tools/document_lifecycle_check.py`
- Read: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

- [ ] **Step 1: Verify authority and repository identity**

Require an owner instruction naming this plan's exact SHA-256 and `Wave 5 closeout`.
Verify the current branch is `feature/document-lifecycle-governance`, local HEAD equals
the pushed feature ref, staging is empty, and the only pre-existing dirty paths are the
owner-accepted planning artifacts. Do not contact a remote during execution preflight.

- [ ] **Step 2: Verify the frozen governance state**

Verify the governing spec SHA and state, Wave 4 plan SHA, registry `adopted=false`, 20
migrations, roadmap `586/15`, and the exact four-path `WAVE1_LEGACY_PATHS` set. Confirm
`docs/evidence/README.md` does not exist. Any mismatch stops before edits.

- [ ] **Step 3: Create a private rollback snapshot**

Create one owner-only temporary directory with `mktemp -d`, set mode `0700`, and copy the
eight existing future-change files while preserving modes. Record a mode-`0600` SHA-256
inventory and the expected absence of `docs/evidence/README.md`. Do not copy credentials,
private handoffs, generated products, or unrelated dirty files.

## Task 1: Run The Required Pre-Closeout Validation

**Files:**

- Test: `packages/ragflow-skill-runtime/tests/`
- Validate: all registered documentation and release boundaries

- [ ] **Step 1: Run focused lifecycle and release-hygiene tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_document_lifecycle_check.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_release_hygiene.py' -v
```

Expected: both focused suites pass with zero failures and zero errors.

- [ ] **Step 2: Run the full unit suite and governance checks**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 tools/document_lifecycle_check.py
python3 tools/release_hygiene_check.py --no-build
python3 tools/build_release.py --check
git diff --check
```

Expected: the full suite passes; lifecycle is `66/66/0`; release hygiene has zero
findings; build and diff checks pass.

- [ ] **Step 3: Verify pre-closeout invariants**

Confirm roadmap `586/15`, registry 66 documents, 20 migrations, `adopted=false`, all four
legacy paths still registered with `legacy_path=true`, empty staging, and no generated
dirty paths. Any failure stops without performing the transition.

## Task 2: Apply The Atomic Adoption Transition

**Files:**

- Create: `docs/evidence/README.md`
- Modify: the other eight paths in the exact future change set

- [ ] **Step 1: Create the evidence authoring entrypoint**

Create `docs/evidence/README.md` with this complete content:

```markdown
---
doc_type: reference
topic: evidence-authoring-guide
status: reference
created: 2026-08-04
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Evidence Authoring Guide

New outcome evidence belongs in `docs/evidence/` only when it is sanitized, durable, and
owned by a registered spec or plan. Record observable outcomes, validation class, and
residual risk. Do not include credentials, private endpoints, machine-specific paths,
live identifiers, raw responses, raw chunks, or temporary run locations.

Evidence documents use `doc_type: evidence`, `canonical: false`,
`implementation_authority: false`, and an `owner_spec` naming their registered spec or
plan. Evidence records results; they do not authorize implementation or live operations.
```

- [ ] **Step 2: Apply the exact lifecycle metadata transitions**

Change only the `status` and `updated` fields listed in the final lifecycle table. Add the
two exact structured gates to Wave 2 and Wave 3. In each prior plan, replace its stale
final execution marker with the matching current state below. Do not change any checkbox
or earlier execution instruction.

For the Wave 1 plan, replace `` `implementation=NOT_STARTED` `` with:

```markdown
Lifecycle closeout: the owner-reviewed Wave 1 implementation and targeted revision are
complete. The unchecked boxes above preserve the original execution plan; they do not
represent new authority after adoption.

`implementation=WAVE_1_COMPLETE`
```

For the Wave 2 plan, replace `` `implementation=NOT_STARTED` `` with:

```markdown
Lifecycle closeout: owner-authorized Waves 2A-2C completed 18 migrations. Wave 2D remains
gated on private-handoff closure or refresh and is not authorized by registry adoption.

`implementation=WAVES_2A_2B_2C_COMPLETE / WAVE_2D_GATED`
```

For the Wave 3 plan, replace `` `implementation=NOT_STARTED` `` with:

```markdown
Lifecycle closeout: owner-authorized Waves 3A-3B are complete. The `docs/16` and `docs/43`
candidates remain gated and are not authorized by registry adoption.

`implementation=WAVES_3A_3B_COMPLETE / DEFERRED_REFERENCES_GATED`
```

Replace the Wave 4 plan's complete `Current Stop` section with:

```markdown
## Lifecycle Closeout

Owner-authorized Waves 4A and 4B are complete, committed, pushed, and independently
validated. The unchecked boxes above preserve the original execution plan; they create no
new authority after adoption.

`implementation=WAVE_4_COMPLETE`
```

Replace the governing spec's complete `Current Stop` section with:

```markdown
## Current State

The documentation taxonomy is adopted for new work. This spec remains `active` as the
canonical lifecycle policy and registry owner. Wave 2D, the two deferred reference
candidates, and every unrelated product or live-operation gate remain separate and
unchanged. This policy creates no implementation or operational authority.
```

The final state markers are therefore:

```text
implementation=WAVE_1_COMPLETE
implementation=WAVES_2A_2B_2C_COMPLETE / WAVE_2D_GATED
implementation=WAVES_3A_3B_COMPLETE / DEFERRED_REFERENCES_GATED
implementation=WAVE_4_COMPLETE
```

Replace this plan's `Current Stop` section only after every other transition edit is
complete.

- [ ] **Step 3: Update the registry atomically**

Set top-level `adopted` to `true`; add the evidence guide as `wave1_governance`; and make
the six status fields match the final lifecycle table. Keep the governing-spec path,
baseline counts, roadmap counts, 20 migration records, all ownership fields, all legacy
flags, and every other entry unchanged. The final registry contains 67 sorted unique
document paths. Insert this exact sorted entry:

```json
{"path":"docs/evidence/README.md","doc_type":"reference","topic":"evidence-authoring-guide","status":"reference","canonical":true,"implementation_authority":false,"owner":"docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md","related":[],"legacy_metadata":false,"legacy_path":false,"baseline_class":"wave1_governance"}
```

- [ ] **Step 4: Update the default index**

In `Controlling Governance Work`, retain the existing links and replace only their state
prose so it states these exact facts:

```text
Wave 1: implemented; implementation_authority=false.
Wave 2: Waves 2A-2C complete; Wave 2D gated; implementation_authority=false.
Wave 3: Waves 3A-3B complete; docs/16 and docs/43 gated; implementation_authority=false.
Wave 4: implemented, committed, and pushed; implementation_authority=false.
Wave 5: adoption implemented; final validation pending; implementation_authority=false.
```

Change `The registry remains unadopted` to `The registry is adopted for new work` without
changing the migration count or blocked-candidate statement. Add this exact Authoring
bullet:

```markdown
- Sanitized evidence: `docs/evidence/README.md`.
```

Keep all business-roadmap and operational-authority statements unchanged.

- [ ] **Step 5: Close this plan's current-state note**

Replace the planning-only `Current Stop` section with:

```markdown
## Lifecycle Closeout

The repository documentation taxonomy is adopted for new work. Deferred migrations and
references retain their named gates, and no operational authority is created.

`WAVE_5_IMPLEMENTED / FINAL_VALIDATION_PENDING`
```

Do not claim final completion until Task 3 passes.

## Task 3: Validate Final Post-Transition Bytes

**Files:**

- Validate: exactly the nine authorized paths and the complete repository gates

- [ ] **Step 1: Repeat all focused and full validation**

Run every command from Task 1 again on the final bytes. Expected: focused and full tests
pass, lifecycle is `67/67/0`, release hygiene has zero findings, and build/diff checks
pass.

- [ ] **Step 2: Verify final registry and lifecycle semantics**

Require all of the following:

- registry `adopted=true`, 67 sorted unique documents, and 20 migrations;
- governing spec `active`; Wave 1, Wave 4, and Wave 5 plans `implemented`; Wave 2 and
  Wave 3 plans `gated` with non-empty structured gates;
- all changed document metadata agrees with registry entries;
- the exact four legacy paths remain registered and no fifth exemption exists;
- a repository search finds no unregistered post-adoption `docs/superpowers/` document;
- roadmap remains `586/15` and no roadmap checkbox changed;
- exactly nine dirty paths, empty staging, and no generated dirty path;
- Wave 2D, `docs/16`, `docs/43`, skill-surface spec bytes, external maintainer files, and
  private handoffs are unchanged.

- [ ] **Step 3: Review safety and final diff**

Review every sensitive-literal match in the nine changed documents without printing any
matched value. Confirm the diff contains only the exact metadata, state-note, registry,
index, and evidence-guide changes described here.

- [ ] **Step 4: Finalize the Wave 5 note**

Only after Steps 1-3 pass, change this plan's closeout note from
`FINAL_VALIDATION_PENDING` to `FINAL_VALIDATION_PASS`; change the Wave 5 state in
`docs/README.md` from `final validation pending` to `final validation passed`; then rerun
lifecycle, release hygiene, and `git diff --check` and require the same final results.
These final note changes remain within the authorized paths and are not a second
implementation wave.

## Rollback

If any transition or post-transition check fails, restore only the eight pre-existing
authorized files from the private snapshot, remove `docs/evidence/README.md` only after
proving it was created by this batch, rerun lifecycle and `git diff --check`, and stop.
Do not use reset, checkout, clean, stash, or broad deletion. Retain the rollback directory
until the owner accepts the result.

## Stop Conditions

Stop before editing, or roll back only this batch and stop, if:

1. authority does not name this plan's exact SHA-256 and `Wave 5 closeout`;
2. branch, HEAD/tracking state, staging, accepted dirty scope, governing spec, Wave 4
   plan, registry baseline, roadmap counts, or legacy-path set differs;
3. pre-closeout validation has any failure or finding;
4. a requested change falls outside the exact nine-path future change set;
5. adoption would require moving or rewriting the skill-surface spec or another legacy
   path;
6. a roadmap checkbox, migration record, owner, authority field, baseline count, or
   unrelated body changes;
7. Wave 2D, `docs/16`, `docs/43`, an external maintainer file, private handoff, generated
   product, public skill, runtime source, or test file would change;
8. final lifecycle, tests, release hygiene, build, diff, safety, staging, or generated-path
   validation fails;
9. execution would require network, credentials, live operations, staging, commit, push,
   merge, L3, Stage 8C, L4, or another migration.

## Acceptance Criteria

### Planning-only acceptance

1. exactly this plan, `docs/README.md`, and `docs/document-registry.json` change;
2. lifecycle reports `66/66/0`, migrations remain 20, and `adopted=false`;
3. roadmap remains `586/15`, staging is empty, and no generated product changes;
4. the plan resolves the legacy skill-surface path explicitly and contains no unresolved
   design choice or implementation authority.

### Future Wave 5 acceptance

1. the pre-closeout and final validation passes both succeed on their respective bytes;
2. registry adoption becomes true only in the atomic transition and all 67 documents are
   registered;
3. the evidence authoring entrypoint exists and new-work locations are explicit;
4. lifecycle statuses match verified execution reality without changing task checkboxes;
5. the four pre-adoption legacy paths remain bounded while every new tool-specific path
   is forbidden;
6. no migration, business behavior, roadmap count, live authority, generated artifact,
   external file, staging, commit, push, or merge occurs.

## Lifecycle Closeout

The repository documentation taxonomy is adopted for new work. Deferred migrations and
references retain their named gates, and no operational authority is created.

`WAVE_5_IMPLEMENTED / FINAL_VALIDATION_PASS`
