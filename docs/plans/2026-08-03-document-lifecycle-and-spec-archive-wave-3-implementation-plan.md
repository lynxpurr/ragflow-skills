---
doc_type: plan
topic: document-lifecycle-and-spec-archive-wave-3
status: gated
created: 2026-08-03
updated: 2026-08-04
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related:
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md
gate: separate_owner_resolution_for_docs_16_and_docs_43
---

# Document Lifecycle And Spec Archive Wave 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize the unblocked durable documentation into a small `docs/reference/`
surface, archive superseded design records without losing their bytes, and leave every
candidate with an unresolved authority dependency at its current path.

**Architecture:** Wave 3A handles only repository-local changes: eight current references
move to `docs/reference/`, the stale architecture snapshot moves to the archive, and a
short current architecture reference replaces it. Wave 3B is separately gated because
archiving the adaptive-pipeline completion record requires atomic edits to the external
maintainer skill. Two other candidates remain inventory-only because current private
handoffs and a frozen Wave 2D metadata reference prevent a safe move.

**Tech Stack:** Markdown, JSON, Python 3.10+ standard library, `unittest`, Git mechanical
renames, `rg`, and repository-local lifecycle and release-hygiene checks.

---

## Governance Binding

| Field | Value |
| --- | --- |
| Execution state | `NOT_STARTED` |
| Governing spec | `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` |
| Governing spec SHA-256 | `e18d80b60b4a89ee3319c0eac74d44852a744d4b4a0909e677f7af936cb777fd` |
| Governing state | `status=approved`, `gate_0=closed`, `implementation_authority=false` |
| Planning branch | `feature/document-lifecycle-governance` |
| Pushed planning baseline | `ca9c569d197c726e04361d48a2a0918e9213fdf8` |
| Remote feature-ref verification | exact match at plan-authoring time |
| Roadmap baseline | 586 checked, 15 unchecked |
| Registry adoption | `adopted=false` |
| Completed archive migrations | 18 |
| Wave 2D preservation requirement | all 10 paths unchanged |

This file is a proposed plan. Its path, checksum, registry entry, or owner review does
not authorize execution. Future execution authority must name this plan's exact SHA-256
and either `Wave 3A` or `Wave 3A and Wave 3B`. Wave 3B authority must additionally name
the external maintainer root `~/.codex/skills/ragflow-skills-maintainer`.

No approval under this plan authorizes Wave 2D, changes to an ACTIVE private handoff,
changes to the two deferred candidates, registry adoption, governing-spec transition,
network access, credentials, live operations, generated products, staging, commit, push,
merge, L3, Stage 8C, or L4.

## Planning-Only Change Set

Creating this proposed plan changes only:

- create `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-3-implementation-plan.md`;
- register it in `docs/document-registry.json` as `wave1_governance`;
- link it from `docs/README.md` as proposed and non-authoritative.

The planning change must produce lifecycle `62/62/0`, keep all 12 candidate files and
their hashes unchanged, leave migrations at 18, preserve roadmap `586/15`, keep
`adopted=false`, and stop for owner review. All remaining sections describe future work.

## Read-Only Candidate Audit

The audit distinguishes reusable current guidance from chronological evidence and from
paths that cannot move atomically under the current boundary.

| Candidate | Audit result | Disposition |
| --- | --- | --- |
| `docs/02-architecture-design.md` | The three-skill boundary remains useful, but the file is an implementation snapshot and its migration section describes work already completed. Current layout is also covered by the root README and public skill files. | Archive the original bytes; create a short current `docs/reference/suite-architecture.md`. |
| `docs/05-cross-platform-smoke.md` | The tool, profile IDs, aliases, and `--list-profiles` entrypoint exist and have focused tests. | Normalize as a current reference in Wave 3A. |
| `docs/06-release-hardening.md` | Every named release tool exists; it remains the detailed release-validation owner. | Normalize as a current reference in Wave 3A. |
| `docs/08-cli-agent-integration.md` | The archive shape, config precedence, CLI-agent boundary, and smoke commands remain current. | Normalize as a current reference in Wave 3A. |
| `docs/11-public-rename-policy.md` | It is the exact policy input for `rename_governance_check.py`. | Normalize as a current reference in Wave 3A. |
| `docs/12-release-archive-forward-test-prompts.md` | It is the exact prompt input for `forward_test_prompt_check.py`; examples use installed artifacts and `python3`. | Normalize as a current reference in Wave 3A. |
| `docs/16-system-closeout-report.md` | This is chronological closeout evidence. Current priorities and gates are owned by `docs/03` and `docs/15`; external maintainer files and retained private handoffs still bind the old path. | Keep unchanged in this plan. A later successor may archive it only after those bindings are closed or refreshed. |
| `docs/23-adaptive-pipeline-proposal.md` | This mixes completed design history with a current-usage section. Current behavior is already owned by `skills/ragflow-doc-to-md/SKILL.md` and `references/host-agent-setup.md`. | Archive in Wave 3B only with atomic external maintainer updates. |
| `docs/30-hermes-e2e-test-plan.md` | It is a reusable cross-skill matrix with no active checkboxes. Its command blocks still use 40 bare `python` invocations. | Normalize in Wave 3A and change only those command prefixes to `python3`. |
| `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md` | It remains a reusable, explicitly version-pinned L0 audit runbook; L1/L2 stay gated. | Normalize as a current reference in Wave 3A. |
| `docs/43-agent-session-handoff-lessons.md` | The guidance is current, but a frozen Wave 2D FinanceBench spec references this exact path in structured metadata, and retained ACTIVE handoffs also bind it. | Keep unchanged until those authorities close or are explicitly refreshed. |
| `docs/branching-policy.md` | Branch roles remain current, but its copied validation list duplicates release hardening. | Normalize in Wave 3A and replace the duplicate list with one link to release hardening. |

The selected scope is intentionally smaller than a one-shot 12-file move. It avoids
duplicate authority, redirect stubs, edits to frozen authority objects, and an external
maintainer edit hidden inside a repository-only batch.

## Frozen Candidate Inventory And Target Map

| Batch | Source | SHA-256 | Future destination or state |
| --- | --- | --- | --- |
| 3A | `docs/02-architecture-design.md` | `378c201ca9886eb6cacd0ef958acf9b59db50879db295653eccb29ea0abcb097` | `docs/archive/2026/specs/02-architecture-design.md` plus new `docs/reference/suite-architecture.md` |
| 3A | `docs/05-cross-platform-smoke.md` | `bceb70f7e1fc19750fc32f7b612eec6c3f0fb2c0fd6205a25a77293d748cf5a9` | `docs/reference/cross-platform-smoke.md` |
| 3A | `docs/06-release-hardening.md` | `2880998f5fbb0bf36960476cf599fd50a9d7ee824124dee8dc5c70a3c6afb034` | `docs/reference/release-hardening.md` |
| 3A | `docs/08-cli-agent-integration.md` | `8fc86bef46c7d34c528b64676afdcf8ba20025af4c48f6be94cd22a2413fb6e3` | `docs/reference/cli-agent-integration.md` |
| 3A | `docs/11-public-rename-policy.md` | `5b076bbe3eb3b65247ef85c1a4da28abd5d225cfc1f2cc0e5beb98754886c86a` | `docs/reference/public-rename-policy.md` |
| 3A | `docs/12-release-archive-forward-test-prompts.md` | `247ff0ee6c5fd2bbd98d657cb14d87bcfaffc52296099323f61fd768044da2c4` | `docs/reference/release-archive-forward-test-prompts.md` |
| deferred | `docs/16-system-closeout-report.md` | `aa019d5af7e65add4c045efbb0c80e3a1e02a21474314d707af913fe22841ffa` | remain unchanged; desired later archive path is `docs/archive/2026/evidence/16-system-closeout-report.md` |
| 3B | `docs/23-adaptive-pipeline-proposal.md` | `649b0b539a314dcd7ec767a0b2b1c399f442039bc6a085560659d3f45607f2cf` | `docs/archive/2026/specs/23-adaptive-pipeline-proposal.md` |
| 3A | `docs/30-hermes-e2e-test-plan.md` | `d1a8ce0a85ec675363a0e5ecbec2d5ac8b2b9f6045ffb725e3a0f0b972221e0c` | `docs/reference/hermes-e2e-test-plan.md` |
| 3A | `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md` | `4ea23f5c89fb4ea71f870e57be108f51dbeb0d6bbc04c37aca8f6bdc7c91766a` | `docs/reference/ragflow-kb-parameter-contract-audit-hermes-test.md` |
| deferred | `docs/43-agent-session-handoff-lessons.md` | `3ffbdb5e86da4b0c6969ea8665aadc52222833348572397ca47418c17ef9bc51` | remain unchanged; desired later path is `docs/reference/agent-session-handoff-lessons.md` |
| 3A | `docs/branching-policy.md` | `08c465474e4ae5a18eb223bb0beb290aba609e6bc746b190a3302879b14feab6` | `docs/reference/branching-policy.md` |

At execution time, a source hash mismatch does not authorize recalculating this table.
Stop and return the changed path. All sources must also be current-user-owned regular
non-symlinks. Existing observed mode `0600` on `docs/23` is preserved in rollback
evidence and is not silently normalized by this plan.

## Content Preservation Contract

### Historical archive prefix

The two executable archive moves prepend normalized metadata and a non-authority banner,
then preserve the complete original source bytes as an exact suffix:

```yaml
---
doc_type: spec
topic: suite-architecture-snapshot
status: historical
created: 2026-06-22
updated: MIGRATION_DATE
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: docs/reference/suite-architecture.md
related: []
archived: MIGRATION_DATE
historical_reason: superseded
original_sha256: 378c201ca9886eb6cacd0ef958acf9b59db50879db295653eccb29ea0abcb097
---

> **Historical archive:** This document is immutable context and creates no current task,
> implementation, operational, network, credential, mutation, or live authority.

```

For `docs/23`, change the prefix values to `topic: adaptive-pipeline`,
`created: 2026-07-05`, `superseded_by: null`, `historical_reason: completed`, and its
frozen source SHA. Its existing legacy YAML block is part of the preserved original body.

### Normalized reference frontmatter

Each moved current reference receives this exact metadata shape before its existing H1:

```yaml
---
doc_type: reference
topic: TOPIC
status: reference
created: CREATED_DATE
updated: MIGRATION_DATE
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---
```

| Destination | Topic | Created |
| --- | --- | --- |
| `docs/reference/cross-platform-smoke.md` | `cross-platform-smoke` | 2026-06-23 |
| `docs/reference/release-hardening.md` | `release-hardening` | 2026-06-23 |
| `docs/reference/cli-agent-integration.md` | `cli-agent-integration` | 2026-06-23 |
| `docs/reference/public-rename-policy.md` | `public-rename-policy` | 2026-06-27 |
| `docs/reference/release-archive-forward-test-prompts.md` | `release-forward-test-prompts` | 2026-06-27 |
| `docs/reference/hermes-e2e-test-plan.md` | `hermes-e2e-test` | 2026-07-08 |
| `docs/reference/ragflow-kb-parameter-contract-audit-hermes-test.md` | `kb-parameter-contract-audit` | 2026-07-10 |
| `docs/reference/branching-policy.md` | `branching-policy` | 2026-06-22 |

Remove only the legacy `Status:` and `Date:` lines after adding frontmatter. Preserve
`Scope:` and `Last calibrated:` lines. Other allowed body changes are limited to the
exact path substitutions below, 40 command-prefix substitutions in the Hermes E2E
reference, and the branching-policy deduplication. Validate every other line against a
backup-derived transformed-body digest.

### Current architecture replacement

Create `docs/reference/suite-architecture.md` with normal reference frontmatter using
topic `suite-architecture`, created and updated on `MIGRATION_DATE`, and
`supersedes: [docs/archive/2026/specs/02-architecture-design.md]`, followed by this
complete body:

```markdown
# RAGFlow Skill Suite Architecture

The public suite has three self-contained skills and one shared runtime:

| Component | Owns | Does not own |
| --- | --- | --- |
| `ragflow-doc-to-md` | source inspection, conversion, Markdown handoff, and document-side quality evidence | RAGFlow dataset mutation or answer synthesis |
| `ragflow-kb-build` | handoff inspection, profiles, gated dataset build, retrieval validation, and cleanup planning | raw-document conversion or final answer generation |
| `ragflow-query` | routing, retrieval, evidence, diagnostics, and host-assisted answer support | KB creation or default script-owned synthesis |
| `ragflow-skill-runtime` | shared config, auth, HTTP, manifests, sanitization, and workflow helpers | public skill discovery or maintainer-only policy |

Source lives under `skills/` and `packages/ragflow-skill-runtime/src/`. Release builds
vendor the shared runtime into each skill; `dist/` and `release-artifacts/` are generated
products and are never edited as source.

Skills exchange JSON-first manifests and reports rather than importing each other.
Network, credentials, live mutation, and script-owned model execution remain explicit,
gated choices. Default tests and smoke paths use deterministic fixtures and no network.

Use these references for operational detail:

- `docs/reference/cli-agent-integration.md` for host configuration and invocation;
- `docs/reference/release-hardening.md` for release validation;
- `docs/reference/cross-platform-smoke.md` for supported no-network platform profiles;
- the public `SKILL.md` and bundled `references/` files for each skill's current command contract.

Historical design evolution remains in
`docs/archive/2026/specs/02-architecture-design.md`; it creates no current authority.
```

## Exact Active Reference Updates

Prior plan inventories, governing-spec candidate lists, registry `old_path` fields, and
archived bodies may retain old paths as provenance. Apply these active updates atomically
with the corresponding move.

### Wave 3A repository updates

| Old path | Active consumers to update |
| --- | --- |
| `docs/05-cross-platform-smoke.md` | `tools/rename_governance_check.py` |
| `docs/06-release-hardening.md` | `tools/version_date_drift_check.py`; three current roadmap references at `docs/03-development-plan.md:678`, `:705`, and `:729`; duplicate command block in `docs/branching-policy.md` |
| `docs/08-cli-agent-integration.md` | `tools/version_date_drift_check.py`; `docs/03-development-plan.md`; link in normalized release-hardening reference |
| `docs/11-public-rename-policy.md` | `tools/rename_governance_check.py` |
| `docs/12-release-archive-forward-test-prompts.md` | `tools/forward_test_prompt_check.py`; `tools/version_date_drift_check.py` |
| `docs/30-hermes-e2e-test-plan.md` | `docs/31-hermes-e2e-improvement-follow-up-plan.md`; two self references in the moved body |
| `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md` | `references/ragflow-api-parameter-taxonomy.md`; `docs/03-development-plan.md`; one self reference in the moved body |

The old `docs/02` references inside its archived body remain preserved history. The old
`docs/11` and `docs/12` references inside Wave 2D `docs/10` remain unchanged provenance.

Use these exact tool constants:

```python
# tools/rename_governance_check.py
RENAME_POLICY_PATH = Path("docs/reference/public-rename-policy.md")
DEFAULT_COMPATIBILITY_DOC_ROOTS = (Path("docs/reference/cross-platform-smoke.md"),)

# tools/forward_test_prompt_check.py
PROMPT_PATH = Path("docs/reference/release-archive-forward-test-prompts.md")
```

In `tools/version_date_drift_check.py`, retain every non-Wave-3 member and replace only
the three moved paths:

```python
Path("docs/reference/release-hardening.md"),
Path("docs/reference/cli-agent-integration.md"),
Path("docs/reference/release-archive-forward-test-prompts.md"),
```

In `docs/03-development-plan.md`, replace all three exact
`docs/06-release-hardening.md` occurrences at the frozen baseline lines 678, 705, and 729
with `docs/reference/release-hardening.md`. Change no checkbox, surrounding wording, or
roadmap count.

In the normalized Hermes E2E body, replace exactly 40 code-block lines beginning with
`python ` by `python3 `. Do not change prose uses of the word or any command arguments.

In the normalized branching policy, replace the duplicated validation command block
with:

```markdown
4. Run the current release validation sequence from
   `docs/reference/release-hardening.md`; do not maintain a second command list here.
```

### Wave 3B external maintainer updates

Wave 3B must remove current reliance on `docs/23` before archiving it:

- in external `SKILL.md`, replace the instruction to read `docs/23` with the public
  `skills/ragflow-doc-to-md/SKILL.md` and
  `skills/ragflow-doc-to-md/references/host-agent-setup.md`;
- in external `references/task-selection.md`, use those same two current sources for
  adaptive behavior and use `docs/03-development-plan.md` plus
  `docs/15-field-trial-observation-plan.md` for remaining gates;
- in external `references/phase-map.md`, change the completed-round provenance path to
  `docs/archive/2026/specs/23-adaptive-pipeline-proposal.md` and explicitly label it
  historical evidence.

No other maintainer file changes under Wave 3B. Validate with fixed-string `rg` that no
current maintainer instruction still treats the old path as current guidance.

## Registry And Index Contract

Wave 3A creates `docs/reference/README.md` as a non-authoritative index. It lists the 12
candidates, their exact old path, final/current path, disposition, and original SHA. Its
frontmatter uses `doc_type: index`, topic `durable-reference-index`, status `reference`,
canonical `true`, owner spec equal to the governing spec, and baseline class
`wave1_governance` in the registry.

For eight normalized moves, preserve each registry topic and baseline class, change the
path, set owner to the governing spec, and set both legacy flags false. For archived
`docs/02` and later `docs/23`, set status `historical`, canonical false, owner to the
governing spec, and add archive metadata plus the original SHA. Add only archive moves to
the existing sorted `migrations` array and `docs/archive/README.md` migration map.

Register the new current architecture reference as `wave1_governance`, canonical topic
`suite-architecture`, status `reference`, and owner equal to the governing spec. Keep the
archived snapshot's topic `suite-architecture-snapshot` to avoid ambiguous ownership.

Remove legacy-metadata exemptions only when the matching source completes its move:

- Wave 3A removes `docs/02`, `docs/05`, `docs/06`, `docs/08`, `docs/11`, `docs/12`,
  `docs/30`, `docs/37`, and `docs/branching-policy.md`;
- Wave 3B removes `docs/23`;
- `docs/16` and `docs/43` remain exempt and unchanged.

Update `docs/README.md` after each batch. It must distinguish processed references from
the three, then two, deferred paths without claiming registry adoption or Wave 3
completion.

## Deferred Inventory: No Executable Steps

### `docs/16-system-closeout-report.md`

Do not move or edit it under this plan. It is still referenced by active repository docs,
multiple external maintainer files, and retained private handoffs. A later successor must
first select `docs/03-development-plan.md` and `docs/15-field-trial-observation-plan.md`
as current owners, refresh or close the ACTIVE handoff bindings, and then define atomic
repo/external substitutions before archiving the original report.

### `docs/43-agent-session-handoff-lessons.md`

Do not move, copy, or edit it under this plan. The frozen Wave 2D file
`docs/specs/2026-08-02-financebench-new-minimal-l3-design.md` names the current path in
its `related` metadata, and retained ACTIVE handoffs also bind the path. Updating that
metadata would violate the Wave 2D preservation requirement; leaving it unchanged after
a move would fail lifecycle validation. A later successor may act only after those
authority objects close or are explicitly refreshed.

## Stop Conditions

Stop before mutation, or roll back only the active batch, when any condition is true:

1. The owner instruction does not name this plan's exact current SHA and permitted batch.
2. The governing spec SHA/state, branch, roadmap `586/15`, registry `adopted=false`, or
   the 18 completed migration records differ.
3. A source SHA, owner, regular-file type, mode, or non-symlink state differs from the
   frozen inventory.
4. An undeclared current inbound reference exists or an expected consumer cannot be
   updated without overwriting unrelated work.
5. A destination exists, `docs/reference/` resolves through a symlink, or a backup cannot
   reproduce exact source bytes and modes.
6. An archived source is not an exact suffix after its prefix, or a normalized body has
   any change outside the declared transformation ledger.
7. Batch 3B lacks explicit authority for the external maintainer root.
8. Execution would modify `docs/16`, `docs/43`, any Wave 2D file, ACTIVE private handoff,
   generated product, public CLI/runtime behavior, report schema, or live surface.
9. Focused tests, full tests, lifecycle, release hygiene, build check, roadmap counts,
   diff check, or changed-document safety review fails.
10. Execution would require network, credentials, live mutation, staging, commit, push,
    merge, L3, Stage 8C, or L4.

## Rollback

Before each authorized batch, create a new owner-only directory under `/tmp`, copy only
that batch's sources and declared mutable consumers with modes preserved, and write a
sanitized path/SHA/mode manifest. Verify every backup before the first move.

On failure, restore only paths recorded for the active batch and remove only destinations
created by that batch. Do not use `git reset`, `git checkout`, `git clean`, `git stash`,
or a repository-wide restore. Re-run the failed focused check plus lifecycle and
`git diff --check`. A validated Wave 3A remains intact if separately authorized Wave 3B
later fails; external maintainer bytes must be restored from their own verified backup.

### Task 0: Bind Authority And Freeze The Execution Baseline

**Files:** Read-only verification of this plan, governing spec, registry, indexes, 12
candidates, declared consumers, four tools, four focused tests, external maintainer
references, and private handoff path bindings.

- [ ] **Step 1: Verify exact authority and repository state**

  Require the owner-authorized plan SHA, governing spec SHA, feature branch, clean
  staging area, one worktree, roadmap `586/15`, registry `adopted=false`, and 18 existing
  migrations. Do not contact a remote; the pushed baseline is planning evidence only.

- [ ] **Step 2: Verify candidate identity and destination absence**

  Run `sha256sum` and `stat -c '%F %a %U %N'` for all 12 candidates. Compare every digest
  to the frozen table and require all proposed destinations to be absent regular paths.

- [ ] **Step 3: Repeat fixed-string inbound discovery**

  Use one `rg -n -F` inventory over the repository, external maintainer root, and private
  handoff directory. Classify each hit as declared current consumer, prior-plan/spec
  provenance, archived-body provenance, blocked immutable binding, registry/index state,
  or self reference. Any unclassified hit stops execution.

- [ ] **Step 4: Create and verify the Wave 3A rollback backup**

  Back up only the nine 3A sources and declared mutable consumers. Capture one UTC
  `MIGRATION_DATE` and use it for all metadata and index updates in the authorized run.

Expected: all checks pass without changing repository or external bytes.

### Task 1: Add Focused Path-Migration Tests

**Files:**

- Modify: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_rename_governance_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_forward_test_prompt_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_version_date_drift_check.py`

- [ ] **Step 1: Add failing constant and exemption assertions**

  Import the moved-path constants in their matching tests. Assert the new reference paths
  are present, old paths are absent, and the nine 3A sources are absent from
  `WAVE1_LEGACY_METADATA_PATHS` while `docs/16`, `docs/23`, and `docs/43` remain.

  Use this repository-specific version-path assertion:

  ```python
  def test_wave3_release_references_use_normalized_paths(self) -> None:
      expected = {
          Path("docs/reference/release-hardening.md"),
          Path("docs/reference/cli-agent-integration.md"),
          Path("docs/reference/release-archive-forward-test-prompts.md"),
      }
      self.assertTrue(expected.issubset(DOC_VERSION_PATHS))
      self.assertFalse(
          {
              Path("docs/06-release-hardening.md"),
              Path("docs/08-cli-agent-integration.md"),
              Path("docs/12-release-archive-forward-test-prompts.md"),
          }
          & set(DOC_VERSION_PATHS)
      )
  ```

- [ ] **Step 2: Make temporary-repository fixtures follow the constants**

  In rename and forward-prompt tests, create fixture parents with
  `(root / CONSTANT).parent.mkdir(parents=True, exist_ok=True)` and write the fixture to
  `root / CONSTANT`. Do not retain copied old-path literals in fixtures.

- [ ] **Step 3: Run focused tests and verify RED**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
    python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
    -p 'test_document_lifecycle_check.py' -v
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
    python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
    -p 'test_rename_governance_check.py' -v
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
    python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
    -p 'test_forward_test_prompt_check.py' -v
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
    python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
    -p 'test_version_date_drift_check.py' -v
  ```

  Expected: only the new path/exemption assertions fail because production constants and
  paths still use the old locations.

### Task 2: Execute Wave 3A Repository-Local Normalization

**Files:** Nine source/destination pairs, the new reference index and architecture
reference, declared active consumers, registry, archive index, and lifecycle allowlist.

- [ ] **Step 1: Create safe destination directories and move the nine sources**

  Require ordinary non-symlink `docs/reference/` and archive directories. Move the eight
  current references and archive `docs/02` according to the target map. Apply the exact
  archive prefix, reference metadata, legacy-header cleanup, and body substitutions.

- [ ] **Step 2: Create the two new reference documents**

  Create `docs/reference/README.md` from the Registry And Index Contract and create
  `docs/reference/suite-architecture.md` from the complete body above. Register both with
  normalized metadata and no implementation authority.

- [ ] **Step 3: Update tool-owned paths and active documentation consumers**

  Apply only the constants and active-reference substitutions listed above. Make the 40
  exact `python3` corrections and replace the branching-policy command duplication.
  Leave prior plans/spec inventories, archived bodies, Wave 2D files, private handoffs,
  and external maintainer files unchanged.

- [ ] **Step 4: Update registry, indexes, migration map, and legacy allowlist**

  Apply eight reference moves, one archived snapshot, two new governance documents, one
  new archive migration row, and nine exemption removals. Sort registry documents and
  migrations. Update `docs/README.md`, `docs/reference/README.md`, and
  `docs/archive/README.md` consistently.

- [ ] **Step 5: Run focused tests and validate the 3A checkpoint**

  Run the four focused modules from Task 1, `python3 tools/document_lifecycle_check.py`,
  `python3 tools/release_hygiene_check.py`, `python3 tools/build_release.py --check`,
  roadmap counts, transformed-body checks, `git diff --check`, and a changed-document
  sensitive-literal scan.

  Expected: all checks pass; migrations equal 19; `docs/16`, `docs/23`, `docs/43`, all
  Wave 2D files, external maintainer files, and private handoffs have their original
  hashes; `adopted=false`; roadmap remains `586/15`.

- [ ] **Step 6: Stop unless Wave 3B was separately authorized**

  Report the 3A result and the three deferred candidates. Do not infer external
  maintainer authority from repository-plan approval.

### Task 3: Execute Separately Authorized Wave 3B

**Files:** `docs/23`, its archive destination, registry/index/allowlist records, and the
three exact external maintainer files named above.

- [ ] **Step 1: Bind external authority and create separate backups**

  Require an owner instruction naming this plan SHA, Wave 3B, and the external maintainer
  root. Verify `docs/23` still matches its frozen SHA and back up repository and external
  files into separate owner-only manifests.

- [ ] **Step 2: Update current maintainer guidance before the archive move**

  Apply only the three substitutions in Wave 3B External Maintainer Updates. Run
  fixed-string search to prove the old path remains only where explicitly labeled as
  historical provenance.

- [ ] **Step 3: Archive `docs/23` with exact suffix preservation**

  Move it to `docs/archive/2026/specs/23-adaptive-pipeline-proposal.md`, prepend the exact
  historical prefix, and verify the frozen original bytes are the complete suffix.

- [ ] **Step 4: Update repository governance records and the focused exemption test**

  Add the archive migration row, update registry and both indexes, remove only `docs/23`
  from the legacy exemption, and change the focused test's remaining blocked set from
  three paths to `docs/16` and `docs/43`.

- [ ] **Step 5: Validate and stop at owner review**

  Run the lifecycle focused tests, full lifecycle, release hygiene, build check, roadmap
  counts, body preservation, external path search, `git diff --check`, and safety review.
  Expected: migrations equal 20, two candidates remain deferred, and no runtime,
  authority, generated-product, network, staging, commit, push, or merge change occurred.

### Task 4: Run Final Offline Validation And Stop

**Files:** Read-only verification after the last authorized batch.

- [ ] **Step 1: Run the full unit suite**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
    python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -q
  ```

  Expected: all tests pass.

- [ ] **Step 2: Run repository governance and release checks**

  ```bash
  python3 tools/document_lifecycle_check.py
  python3 tools/build_release.py --check
  python3 tools/release_hygiene_check.py
  git diff --check
  ```

  Expected: lifecycle and registry counts match exactly, release hygiene has zero
  findings, build check passes, and diff check is empty.

- [ ] **Step 3: Verify preservation and authorization boundaries**

  Require exact source/destination counts for the authorized batch, backup-derived body
  parity, roadmap `586/15`, registry `adopted=false`, unchanged governing spec, unchanged
  Wave 2D and deferred files, empty staging, and no unexpected path or generated-product
  changes.

- [ ] **Step 4: Stop for owner review**

  Report dispositions, mappings, test totals, lifecycle/release outcomes, residual
  blockers, and changed paths. Do not stage, commit, push, merge, execute Wave 2D, move a
  deferred candidate, transition lifecycle/adoption state, or begin Wave 4/5.

## Acceptance Criteria

An authorized Wave 3 slice is acceptable only when:

1. every one of the 12 candidates has exactly one explicit disposition;
2. Wave 3A processes exactly nine candidates, creates one concise architecture reference
   and one reference index, and preserves all undeclared bytes;
3. Wave 3B cannot run without explicit external maintainer authority and archives exactly
   one additional candidate with an exact original-byte suffix;
4. `docs/16` and `docs/43` remain at their current paths and byte hashes;
5. all Wave 2D files and private handoffs remain unchanged;
6. tool constants, focused tests, registry, reference index, archive index, and active
   references agree on every completed move;
7. no duplicate current authority, redirect stub, stale active tool path, or unclassified
   inbound reference remains;
8. roadmap stays `586/15`, registry stays `adopted=false`, and the governing spec does not
   transition;
9. focused/full tests, lifecycle, release hygiene, build check, diff check, body
   preservation, and safety review all pass;
10. no network, credential, live operation, generated-product mutation, staging, commit,
    push, merge, L3, Stage 8C, L4, Wave 4, or Wave 5 occurs.

## Owner Review Boundary

The next decision is to approve or reject the exact SHA-256 of this proposed plan. If
approved, the smallest recommended authority is Wave 3A only. Wave 3B requires a second,
explicit external-maintainer scope decision. The two deferred candidates are not
approvable under this plan.

Lifecycle closeout: owner-authorized Waves 3A-3B are complete. The `docs/16` and `docs/43`
candidates remain gated and are not authorized by registry adoption.

`implementation=WAVES_3A_3B_COMPLETE / DEFERRED_REFERENCES_GATED`
