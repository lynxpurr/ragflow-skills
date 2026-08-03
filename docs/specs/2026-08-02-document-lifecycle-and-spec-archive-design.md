---
doc_type: spec
topic: document-lifecycle-and-spec-archive
status: approved
created: 2026-08-02
updated: 2026-08-03
canonical: true
implementation_authority: false
gate_0: closed
---

# Document Lifecycle And Spec Archive Design

## Context

The current read-only inventory contains 53 Markdown documents under `docs/`: 49 tracked
files and four untracked files. Roadmaps, architecture decisions, implementation plans,
reusable runbooks, field-trial evidence, completed test instructions, and historical
execution records share the same top-level namespace. Status metadata is inconsistent,
and several completed plans still look actionable to an agent.

This increases context cost and creates three practical risks:

1. an agent may select an obsolete plan instead of the current owner;
2. a completed or rejected instruction may be mistaken for authority to continue work;
3. new specs may repeat old work because there is no canonical registry or lifecycle
   rule.

The earlier FinanceBench Stage C execution baseline is no longer recoverable because its
private temporary contract and package bytes expired. The successor `NEW_MINIMAL_L3`
feasibility gate also stopped before contract creation because the reviewed input bytes
were incomplete. On 2026-08-03 the owner accepted
`L3=NOT_COMPLETED_INPUTS_UNAVAILABLE`, formally closed that workflow, and closed this
design's Gate 0. This document still creates no migration authority: only a separate
implementation plan may be prepared next.

## Objective

Create a small, predictable documentation system in which an agent can identify the
current roadmap, the one controlling spec for a topic, the corresponding implementation
plan, durable reference material, and historical evidence without scanning the entire
repository history.

The system must:

- preserve historical evidence without presenting it as current work;
- separate design, implementation, reference, and evidence concerns;
- make document authority and lifecycle machine-checkable;
- reduce path churn while work is active or gated;
- update internal references atomically when terminal documents are archived;
- keep live-operation and exact-baseline authority outside documentation cleanup;
- avoid turning documentation governance into another large product subsystem.

## Non-Goals

This design does not:

- execute or authorize FinanceBench NEW_MINIMAL_L3;
- change code, CLI behavior, public report schemas, release artifacts, or defaults;
- rewrite historical technical findings to match current implementation;
- delete historical documents;
- merge unrelated roadmap tracks;
- commit or push without a separate owner request;
- require a documentation website, database, or third-party documentation framework.

## Requirements And Invariants

- Gate 0 is closed by the owner-accepted `NEW_MINIMAL_L3` terminal result; this permits
  implementation planning only.
- No documentation migration, archive move, broad rewrite, or code change begins until a
  separate implementation plan is reviewed and approved.
- Every document is classified exactly once by type, topic, lifecycle, and canonical
  ownership.
- Only an approved or active spec plus its linked plan may authorize implementation.
- Gated, reference, evidence, and historical documents create no implicit execution or
  live-operation authority.
- Historical content is retained; cleanup means classification and relocation, not
  deletion or retrospective rewriting.
- Internal references are updated in the same migration slice as a move.
- Roadmap completion counts do not change merely because documents are reorganized.
- Governance remains local, deterministic, no-network, and small enough to review as
  maintenance tooling.

## Audit Findings

### High: no canonical document entrypoint

There is no `docs/README.md` that tells an agent which roadmap, spec, plan, or reference
is current. The numeric filename sequence reflects creation order, not authority.

### High: lifecycle and authority are conflated

Files use values such as `draft`, `active`, `implemented`, `closeout`, `archived reusable
test plan`, and long prose status sentences. Some use `Status:`, some use Chinese status
labels, and some have no structured lifecycle metadata. A historical instruction can
therefore appear equivalent to an active gate.

### Important: document classes are mixed

Several files combine design requirements, implementation checklists, command transcripts,
field-trial results, and future backlog. This makes closeout difficult and encourages
later sessions to append rather than create a focused successor.

### Important: completed work remains prominent

Completed release, backend, quality-improvement, replay, and implementation-plan files
remain beside current plans. Their evidence is useful, but they should not be loaded by
default for ordinary development.

### Important: tool-specific storage is not a durable repository taxonomy

`docs/superpowers/specs/` and `docs/superpowers/plans/` describe the tool that created the
documents rather than their repository role. Future specs and plans should use
tool-neutral locations.

### Important: moving documents can break links and exact baselines

Several current docs and one validation tool refer to exact document paths. A bulk move
without an inbound-reference inventory would create stale instructions. Gate 0 is now
closed, but every broad tracked move still requires an approved implementation plan and
an atomic inbound-reference update.

## Design

The design combines a stable document taxonomy, structured lifecycle metadata, one
canonical index, and a staged migration that separates terminal history from current
work without moving active authority objects prematurely.

### Selected Approach

Use a staged hybrid migration:

1. preserve all current tracked paths until the post-Gate-0 implementation plan is
   reviewed and approved;
2. introduce one canonical index, templates, lifecycle rules, and a bounded checker;
3. archive only terminal documents in the first migration wave;
4. normalize durable references in a second wave;
5. leave active or gated legacy paths stable until their owning work closes or an
   explicitly reviewed move is safe.

This is preferred over status-only cleanup because it materially reduces root clutter.
It is preferred over a one-shot full migration because it limits link churn and keeps
each review slice understandable.

### Target Structure

```text
docs/
  README.md
  roadmap/
  specs/
    README.md
    TEMPLATE.md
  plans/
    README.md
    TEMPLATE.md
  reference/
  evidence/
  archive/
    README.md
    2026/
      legacy/
      specs/
      plans/
      evidence/
```

Directory meaning is stable:

| Directory | Purpose | May drive implementation? |
| --- | --- | --- |
| `roadmap/` | Current priorities, owning links, and gated backlog summary | Only by linking to an approved spec |
| `specs/` | Problem, goals, behavior, constraints, compatibility, and acceptance criteria | Yes, when status is `approved` or `active` |
| `plans/` | File-level implementation steps, tests, rollout, and rollback | Yes, when linked to an approved spec |
| `reference/` | Durable architecture, policy, usage, and reusable runbooks | No independent task authority |
| `evidence/` | Current sanitized validation or decision evidence | No independent task authority |
| `archive/` | Immutable historical context and provenance | Never |

Active and gated files do not move merely because their status changes. A file moves
only once, after it reaches a terminal lifecycle state and its inbound references have
been reviewed.

## Document Lifecycle

Allowed lifecycle values are:

| Status | Meaning | Next valid states |
| --- | --- | --- |
| `draft` | Incomplete authoring; not ready for approval | `proposed`, `superseded` |
| `proposed` | Complete enough for owner review; no implementation authority | `approved`, `draft`, `superseded` |
| `approved` | Design accepted; implementation plan may be prepared | `active`, `gated`, `superseded` |
| `active` | Controlling current implementation or evidence work | `gated`, `implemented`, `superseded` |
| `gated` | Valid future work blocked on a named external condition | `active`, `superseded`, `historical` |
| `implemented` | Required implementation and validation are complete | `historical` |
| `superseded` | Replaced by a named successor | `historical` |
| `historical` | Archived and non-authoritative | terminal |
| `reference` | Durable non-task guidance | `superseded`, `historical` |

`historical` is the only normal status under `docs/archive/`. Archived files may retain
their original checkboxes and result text for provenance, but their metadata and banner
must state that they create no current task or operational authority.

## Required Metadata

New specs, plans, references, and evidence documents use YAML frontmatter:

```yaml
---
doc_type: spec
topic: short-stable-topic-id
status: proposed
created: YYYY-MM-DD
updated: YYYY-MM-DD
canonical: true
implementation_authority: false
supersedes: []
superseded_by: null
related: []
---
```

Additional fields are allowed only when they have a stable governance purpose. Exact
run identifiers, credentials, private paths, endpoints, or temporary artifact locations
must not appear in public metadata.

Archive metadata additionally requires:

```yaml
archived: YYYY-MM-DD
historical_reason: completed|superseded|rejected|evidence_only
```

`canonical: true` must be unique for an active topic. A gated document may remain
canonical, but its gate must be named in the document body.

## Spec Coding Standard

A spec describes the intended system, not the sequence of terminal commands used to
build it. Every new spec contains:

1. `Context`
2. `Objective`
3. `Non-Goals`
4. `Requirements And Invariants`
5. `Design`
6. `Compatibility And Migration`
7. `Failure Handling And Rollback`
8. `Validation Strategy`
9. `Acceptance Criteria`
10. `Decision Log`

Rules:

- one spec owns one coherent problem;
- acceptance criteria are externally observable and testable;
- safety, privacy, compatibility, and authorization boundaries are explicit;
- unresolved choices are recorded before approval, not left as placeholder text;
- implementation task checklists belong in a linked plan;
- test transcripts, hashes, and run results belong in evidence or closeout records;
- a spec should normally remain below 400 lines; crossing 500 lines requires either a
  decomposition note or a justified reason in the decision log;
- a spec must not duplicate the global roadmap or another spec's full requirements;
- exact-SHA dual review is reserved for real authority, destructive action, release, or
  compatibility boundaries, not ordinary documentation.

## Plan, Reference, And Evidence Standards

### Implementation plan

A plan links exactly one approved spec and contains scoped file changes, ordered tasks,
focused tests, release checks, rollback steps, and stop conditions. It may use checkboxes.
It must not silently expand the approved design.

### Reference

A reference explains current architecture, policy, command use, or a reusable runbook.
It contains no active implementation checklist and no chronological session log.

### Evidence

An evidence document binds a result to the relevant spec, plan, code revision, and
validation class. It records sanitized outcomes and residual risk, not raw private
artifacts. Evidence is immutable after closeout except for an explicit correction note.

### Roadmap

The roadmap contains only current priorities, state summaries, and links to owners. It
must not become a second implementation plan or retain completed phase transcripts.

## Complete Baseline Classification

The following classification accounts for all 53 current Markdown documents. It is a
migration proposal, not authority to move files before a separate implementation plan is
reviewed and approved.

### Historical archive candidates: 28

Superseded foundation, inventory, release, or roadmap documents:

- `docs/01-folder-plan.md`
- `docs/04-validation-inventory.md`
- `docs/07-first-release.md`
- `docs/09-high-value-feature-roadmap.md`
- `docs/10-legacy-feature-gap-closure-design.md`

Completed backend, quality, parity, and improvement designs or plans:

- `docs/17-mineru-fastapi-backend-design.md`
- `docs/18-mineru-sync-production-issues.md`
- `docs/19-ragflux-capability-parity-plan.md`
- `docs/20-ragflow-doc-to-md-ingest-quality-plan.md`
- `docs/21-ragflow-doc-to-md-table-quality-design.md`
- `docs/22-apollo-table-qa-rectification-plan.md`
- `docs/24-adaptive-pipeline-quality-fix-plan.md`
- `docs/25-current-suite-regression-follow-up-plan.md`
- `docs/26-mineru-v4-platform-backend-design.md`
- `docs/27-current-skills-quality-improvement-checklist.md`
- `docs/28-retrieval-optimization-quality-improvement-plan.md`
- `docs/33-dedao-pandoc-epub-quality-improvement-plan.md`
- `docs/34-pipeline-consumption-gap-quality-improvement-plan.md`

Completed replay evidence:

- `docs/39-benchmark-evidence-strengthening-hermes-test.md`
- `docs/41-marker-aware-candidate-snapshot-hermes-l0.md`

Closed FinanceBench execution and successor-design evidence:

- `docs/42-financebench-marker-aware-l3-disposable-validation.md`
- `docs/specs/2026-08-02-financebench-new-minimal-l3-design.md`

Completed tool-generated design and implementation records:

- `docs/superpowers/plans/2026-07-10-kb-parameter-stage-8a.md`
- `docs/superpowers/plans/2026-07-10-kb-parameter-stage-8b-contract-audit.md`
- `docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md`
- `docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md`
- `docs/superpowers/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md`
- `docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`

### Durable reference candidates: 12

- `docs/02-architecture-design.md`
- `docs/05-cross-platform-smoke.md`
- `docs/06-release-hardening.md`
- `docs/08-cli-agent-integration.md`
- `docs/11-public-rename-policy.md`
- `docs/12-release-archive-forward-test-prompts.md`
- `docs/16-system-closeout-report.md`
- `docs/23-adaptive-pipeline-proposal.md`
- `docs/30-hermes-e2e-test-plan.md`
- `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md`
- `docs/43-agent-session-handoff-lessons.md`
- `docs/branching-policy.md`

Before relocation, each reference candidate must be checked for stale commands and
whether a shorter existing public reference already owns the same guidance. A candidate
may be archived instead of normalized when no current consumer remains.

### Active, gated, or proposed owners: 13

- `docs/03-development-plan.md`
- `docs/13-post-cli-adapter-planning.md`
- `docs/14-optional-llm-backend-planning.md`
- `docs/15-field-trial-observation-plan.md`
- `docs/29-kb-build-strict-regression-quality-plan.md`
- `docs/31-hermes-e2e-improvement-follow-up-plan.md`
- `docs/32-retirement-transition-action-plan.md`
- `docs/35-standard-benchmark-dataset-integration-plan.md`
- `docs/36-ragflow-kb-parameter-materialization-plan.md`
- `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
- `docs/40-marker-aware-evidence-validation-and-promotion-plan.md`
- `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md`
- `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md`

These paths remain stable during the first migration wave. Their internal status may be
calibrated only when the owning task state is independently verified. The two closed
FinanceBench documents are historical candidates, but their execution and recovery facts
must remain unchanged during any later move.

## Compatibility And Migration

### Gate 0: closed

On 2026-08-03 the owner accepted the sanitized Gate-A outcome
`L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` and formally closed `NEW_MINIMAL_L3`. No run
contract was created and Gate B never started. Gate 0 is therefore closed for document
governance.

This transition permits one implementation-planning task. It does not authorize archive
moves, broad tracked-document rewrites, code changes, commits, pushes, network access, L3,
Stage 8C, or L4.

### Wave 1: establish governance

After a separate implementation plan is reviewed and approved:

- create `docs/README.md` as the only default documentation entrypoint;
- create the directory and template files in the target structure;
- add a small lifecycle/link checker using repository-local deterministic logic;
- register all current documents with type, topic, status, and canonical owner;
- retain existing task state and open-item counts.

### Wave 2: archive terminal documents

- verify the 28 archive candidates against current code and owning plans;
- prepend historical metadata without rewriting the original evidence body;
- move them into the appropriate `archive/2026` class;
- update every internal path reference atomically;
- record old-to-new mappings in `docs/archive/README.md`;
- do not leave one redirect stub per moved document.

### Wave 3: normalize durable references

- review the 12 reference candidates for accuracy and duplication;
- move only still-current guidance into `docs/reference/`;
- archive redundant references instead of maintaining two sources of truth;
- update tool-owned hardcoded documentation paths together with focused tests.

### Wave 4: calibrate active and gated owners

- keep the 13 current paths stable unless an independently reviewed move is safe;
- convert status metadata without changing task completion claims;
- split monolithic documents only through a separate approved spec;
- move a document to the archive only after its gate closes or a successor is accepted.

### Wave 5: adopt the scheme for new work

- place new design specs under `docs/specs/`;
- require an approved spec before creating a detailed plan;
- place implementation plans under `docs/plans/`;
- place sanitized outcome evidence under `docs/evidence/`;
- update `docs/README.md` whenever canonical ownership changes.

## Link And Migration Policy

- Inventory inbound references with exact-path `rg` before every move.
- Update source, tests, tools, docs, and maintainer references in the same reviewed slice.
- Use one migration table instead of per-file redirect stubs.
- Preserve Git history through mechanical renames where practical.
- Do not move a document referenced by an immutable authority object until that authority
  is closed or refreshed.
- Archived documents may link to other archived evidence, but active documents must not
  depend on historical files for current requirements.
- If an external maintainer skill references a moved path, update it in a separate,
  explicitly scoped change rather than silently editing outside the repository.

## Lifecycle Validation

The governance checker should remain small and no-network. It verifies:

- every governed document has a recognized `doc_type`, `topic`, and `status`;
- active canonical topics are unique;
- specs, plans, and evidence link to their owners;
- all repository-relative documentation links resolve;
- archived documents use `status: historical` and include archive metadata;
- active indexes do not present historical documents as executable instructions;
- no post-adoption file is created under `docs/superpowers/`; registry-listed legacy
  files may remain until their terminal migration;
- no public document contains prohibited private paths, endpoints, credentials, tokens,
  live identifiers, raw responses, or raw chunks.

The checker is a maintainer/release gate, not a new public skill command or report schema.

## Failure Handling And Rollback

| Failure | Response |
| --- | --- |
| An inbound reference was missed | Stop the wave, restore the prior paths, and update the migration inventory before retrying. |
| A historical candidate still owns active work | Reclassify it as active/gated and leave its path unchanged. |
| Two documents claim the same canonical topic | Select one owner explicitly; mark the other superseded or reference-only before moving either. |
| A move requires changing an immutable authority object | Stop and wait for that authority to close or be explicitly refreshed. |
| A reference is stale but still useful | Correct it in a separate reviewed slice or archive it; do not silently preserve inaccurate guidance. |
| The checker grows into a general documentation framework | Reduce it to metadata, ownership, link, and safety checks only. |

Each migration wave must be independently reversible. Do not combine archive moves with
runtime, CLI, schema, default, or live-operation changes.

## Validation Strategy

For the design-only Gate 0 closeout state:

- verify the 53-file inventory and 28/12/13 classification;
- scan this spec for placeholders and trailing whitespace;
- run `git diff --check` for existing tracked changes;
- run targeted public-doc redaction review;
- run release hygiene because the design touches public documentation governance.

For each later migration wave:

- compare the before/after document registry;
- require zero missing, duplicate, or unclassified documents;
- verify all internal references after moves;
- verify roadmap completed/open counts are unchanged unless separately authorized;
- run focused tests for any tool-owned path update;
- run `git diff --check` and release hygiene;
- inspect untracked files and confirm no generated release product was added;
- verify the tracked worktree contains only the intended documentation-governance slice.

## Acceptance Criteria

The design is accepted when:

1. all 53 current documents are classified exactly once;
2. the accepted NEW_MINIMAL_L3 terminal result and closed Gate 0 are explicit;
3. target directories have non-overlapping responsibilities;
4. lifecycle states and transitions are unambiguous;
5. spec, plan, reference, evidence, roadmap, and archive responsibilities are separate;
6. the 28 archive candidates, 12 reference candidates, and 13 active/gated/proposed
   owners are
   named;
7. migration is staged, link-aware, reversible, and does not delete evidence;
8. new specs use tool-neutral paths and structured metadata;
9. historical documents cannot create current implementation or operational authority;
10. implementation requires a separate owner-reviewed plan after Gate 0 closeout.

The later migration is complete when:

1. `docs/README.md` provides one reliable starting point;
2. every governed document passes lifecycle and link validation;
3. terminal documents are archived and marked historical;
4. active/gated documents remain discoverable and retain accurate ownership;
5. no roadmap count, code behavior, public schema, release artifact, or live authority
   changes as a side effect;
6. release hygiene reports zero findings.

## Decision Log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-08-02 | Preserve the current FinanceBench Stage C baseline before tracked documentation migration | Avoid invalidating the reviewed execution baseline and repeating Stage B work. |
| 2026-08-02 | Retire the expired Stage C baseline and defer migration until NEW_MINIMAL_L3 is terminal | The private authority bytes expired; a targeted successor is safer than reconstructing authority from hashes. |
| 2026-08-02 | Use staged hybrid migration | It reduces root clutter while bounding link and review risk. |
| 2026-08-02 | Separate specs, plans, references, evidence, and archive | Agents should load only the document class needed for the current decision. |
| 2026-08-02 | Use status metadata rather than active/gated directories | Status changes should not cause path churn. |
| 2026-08-02 | Use one migration map instead of per-file redirect stubs | The archive should reduce clutter rather than replace every old file with another file. |
| 2026-08-02 | Keep governance tooling bounded and repository-local | Documentation order should not become a new service or product surface. |
| 2026-08-02 | Permit this one-time audit spec to exceed 500 lines | The complete baseline classification is retained in one reviewable source; implementation details and move mappings remain in a later plan. |
| 2026-08-03 | Close Gate 0 after the owner accepted `L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` | The bounded successor reached its fail-closed terminal outcome without creating a live contract; documentation planning can resume without implying L3 completion. |

## Current Stop

This spec is approved and Gate 0 is closed, but it creates no implementation authority.
One implementation plan may now be prepared for owner review. No archive migration,
tracked-document rewrite, code change, staging, commit, push, or network operation has
begun.
