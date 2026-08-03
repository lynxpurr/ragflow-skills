---
doc_type: plan
topic: document-lifecycle-and-spec-archive-wave-2
status: proposed
created: 2026-08-03
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related:
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md
---

# Document Lifecycle And Spec Archive Wave 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the 18 unblocked terminal documents in Waves 2A-2C with preserved
historical bytes, atomic active-reference updates, and a deterministically verified
migration map, while leaving the 10 blocked Wave 2D documents at their current paths.

**Architecture:** The existing registry remains the source of document ownership and adds
one migration record per completed move. Each batch prepends standardized historical
metadata and a non-authority banner, moves the unchanged original bytes to the target
archive class, updates live references and the archive index in the same slice, and passes
the existing lifecycle/release gates before the next batch. Wave 2D is inventory only and
contains no executable step.

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
| Wave 1 baseline commits | `c15934a`, `b495edc` |
| Roadmap baseline | 586 checked, 15 unchecked |
| Registry adoption | `adopted=false` |
| Executable candidate scope after owner approval | Waves 2A-2C: 18 documents |
| Blocked inventory | Wave 2D: 10 documents |

This file is a proposed plan. Its presence, registry entry, status, checksum, or review
does not authorize execution. Future authority must name the exact SHA-256 of this plan
and the permitted batches. A single owner instruction may authorize 2A-2C together; the
batch boundaries then remain validation and rollback checkpoints rather than additional
approval rounds. Any narrower authorization stops after its last named batch.

No form of approval under this plan authorizes Wave 2D, external maintainer-file edits,
private handoff edits, historical-content deletion, cleanup outside the active batch's
rollback, registry adoption, governing-spec lifecycle transition, network access,
credentials, live operations, staging, commit, push, L3, Stage 8C, or L4.

## Planning-Only Change Set

Creating this proposed plan changes only:

- create `docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md`;
- register that plan in `docs/document-registry.json` with baseline class
  `wave1_governance`;
- link it from `docs/README.md` as proposed and non-authoritative.

The planning change must produce lifecycle `61/61/0`, leave the governing spec and all 28
historical candidates byte-for-byte unchanged, and stop for owner review. The remaining
sections describe future execution only.

## Migration Contract

### Historical prefix

Waves 2A-2C currently contain no YAML frontmatter. For each source, future execution
prepends the following fields using the exact row values in the migration inventory:

```yaml
---
doc_type: plan
topic: folder-plan
status: historical
created: 2026-06-22
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
archived: 2026-08-03
historical_reason: superseded
original_sha256: e036da6843bec57a0199e1e4d35cf4270682f60038289247b24ab13cd534f3a6
---

> **Historical archive:** This document is immutable context and creates no current task,
> implementation, operational, network, credential, mutation, or live authority.

```

The example above is the complete prefix for `docs/01-folder-plan.md` when the first
authorized mutation occurs on 2026-08-03. At Task 0, capture one UTC `MIGRATION_DATE` and
use it for every `updated`, `archived`, registry migration, and archive-index date in the
authorized run. Every other prefix changes only `doc_type`, `topic`, `created`,
`historical_reason`, and `original_sha256` according to its inventory row. The original
source bytes follow the blank line after the banner exactly. `created` preserves existing
structured metadata when present and otherwise records the first Git introduction date.

If any 2A-2C source begins with YAML frontmatter at execution time, its source SHA differs,
or its original bytes are not an exact suffix of the archived file after prefixing, stop
and do not migrate that batch. Wave 2D's existing FinanceBench frontmatter requires a
separate approved transformation and is one reason 2D has no executable steps here.

### Registry migration record

Each completed move appends this exact object shape to `migrations`, sorted by `old_path`:

```json
{
  "old_path": "docs/01-folder-plan.md",
  "new_path": "docs/archive/2026/plans/01-folder-plan.md",
  "archived": "2026-08-03",
  "historical_reason": "superseded",
  "original_sha256": "e036da6843bec57a0199e1e4d35cf4270682f60038289247b24ab13cd534f3a6"
}
```

The matching document entry changes only its path, status, owner, legacy flags, and
archive-related metadata projection:

- `path` becomes `new_path`;
- `status` becomes `historical`;
- `owner` becomes the governing spec path;
- `legacy_metadata=false` and `legacy_path=false`;
- type, topic, canonical state, authority state, related paths, and baseline class remain
  unchanged.

Batch validation must reject duplicate or unsorted migration paths, a missing source
removal, a missing/unregistered destination, a non-historical destination, an invalid
digest, or a mismatch among registry migration data, document frontmatter, and the
archive index. This is a bounded execution check, not a new public command or framework.

### Body preservation and reference policy

- The original whole-file SHA-256 is frozen in the inventory and migration record.
- For 2A-2C the entire original file is the preserved suffix because none has frontmatter.
- Historical inline-code paths inside preserved bodies remain provenance and are not
  rewritten.
- Governing-spec baseline lists, the Wave 1 plan, this plan, registry migration
  `old_path` fields, and archive migration-map `old_path` cells may retain old paths as
  explicit history.
- Every active prose, test, tool, registry entry, structured metadata reference, and
  Markdown link outside those provenance surfaces changes atomically with its move.
- No redirect stub is created.

## Frozen Migration Inventory

| Batch | Source | Destination | Type | Topic | Created | Reason | Original SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2A | `docs/01-folder-plan.md` | `docs/archive/2026/plans/01-folder-plan.md` | plan | folder-plan | 2026-06-22 | superseded | `e036da6843bec57a0199e1e4d35cf4270682f60038289247b24ab13cd534f3a6` |
| 2A | `docs/04-validation-inventory.md` | `docs/archive/2026/legacy/04-validation-inventory.md` | reference | validation-inventory | 2026-06-22 | superseded | `518b86c04dd1cbc82d2e10022d2f37640b34906f1aea848262525fde4c97663a` |
| 2A | `docs/07-first-release.md` | `docs/archive/2026/evidence/07-first-release.md` | evidence | first-release | 2026-06-23 | evidence_only | `a78c2f8fb9d102de10b04f2414860847e1ef7bc49fdb69c22a98d0a93edb7b9c` |
| 2A | `docs/09-high-value-feature-roadmap.md` | `docs/archive/2026/legacy/09-high-value-feature-roadmap.md` | roadmap | high-value-feature-roadmap | 2026-06-23 | superseded | `854999d490f0bc9cfeef78a60a68b7b50ec7b2b5147daf83f56e4da2632b126c` |
| 2A | `docs/17-mineru-fastapi-backend-design.md` | `docs/archive/2026/specs/17-mineru-fastapi-backend-design.md` | spec | mineru-fastapi-backend | 2026-07-02 | completed | `b61dedce1012305d1805dd32a41a3de04471a9941e5b5e7ce3d17df047c7a0ed` |
| 2A | `docs/18-mineru-sync-production-issues.md` | `docs/archive/2026/plans/18-mineru-sync-production-issues.md` | plan | mineru-sync-production-issues | 2026-07-02 | completed | `3326bb402477bbee97cf9d334e1c08841abea78d617f7059a1e0f5fbe6ec4efb` |
| 2A | `docs/24-adaptive-pipeline-quality-fix-plan.md` | `docs/archive/2026/plans/24-adaptive-pipeline-quality-fix-plan.md` | plan | adaptive-pipeline-quality-fix | 2026-07-05 | completed | `1378a30d4bff3aaf81522a0c54f0b20538768944c073d98808616afc2bb31df8` |
| 2A | `docs/25-current-suite-regression-follow-up-plan.md` | `docs/archive/2026/plans/25-current-suite-regression-follow-up-plan.md` | plan | current-suite-regression-follow-up | 2026-07-06 | completed | `ea33d0bf83d895d9745a592cf29652538d1c840bb8edfa5058533550492c22a6` |
| 2B | `docs/21-ragflow-doc-to-md-table-quality-design.md` | `docs/archive/2026/specs/21-ragflow-doc-to-md-table-quality-design.md` | spec | doc-to-md-table-quality | 2026-07-04 | completed | `bf9762763577348b27b09f8932ae1ddc36d7f112cfe293085dc298654888be20` |
| 2B | `docs/22-apollo-table-qa-rectification-plan.md` | `docs/archive/2026/plans/22-apollo-table-qa-rectification-plan.md` | plan | apollo-table-qa | 2026-07-04 | completed | `7c415c603e5768872e68a0f1b6d712d5c5aa5b189c32ac1891020c4ca7caed12` |
| 2B | `docs/26-mineru-v4-platform-backend-design.md` | `docs/archive/2026/specs/26-mineru-v4-platform-backend-design.md` | spec | mineru-v4-platform-backend | 2026-07-06 | completed | `b7ce825d4cb776bba17b041553a0a6c1b5f74c9e35a8dc0d2777c32abb18931b` |
| 2B | `docs/27-current-skills-quality-improvement-checklist.md` | `docs/archive/2026/plans/27-current-skills-quality-improvement-checklist.md` | plan | current-skills-quality-improvement | 2026-07-06 | completed | `b3efa165a4fd8d3bde4fe5372596e6a2339a8dcc786ac2f5ace8c6114fe50c16` |
| 2B | `docs/28-retrieval-optimization-quality-improvement-plan.md` | `docs/archive/2026/plans/28-retrieval-optimization-quality-improvement-plan.md` | plan | retrieval-optimization-quality | 2026-07-07 | completed | `146bfa801966e43af082941ffc56e4972b6e990f0c70607d0a346e3650f417e6` |
| 2B | `docs/33-dedao-pandoc-epub-quality-improvement-plan.md` | `docs/archive/2026/plans/33-dedao-pandoc-epub-quality-improvement-plan.md` | plan | dedao-pandoc-epub-quality | 2026-07-08 | completed | `a142753dfd2296bea180f31466cab23f5cc0207878ac973cb5eb037f6d5753f7` |
| 2B | `docs/34-pipeline-consumption-gap-quality-improvement-plan.md` | `docs/archive/2026/plans/34-pipeline-consumption-gap-quality-improvement-plan.md` | plan | pipeline-consumption-gap | 2026-07-09 | completed | `15a97025b29cbeabd0a1e36ca8419b82d229d4d7e90c6e6a53c728d357adf1fe` |
| 2C | `docs/superpowers/plans/2026-07-10-kb-parameter-stage-8a.md` | `docs/archive/2026/plans/2026-07-10-kb-parameter-stage-8a.md` | plan | kb-parameter-stage-8a | 2026-07-10 | completed | `945461f9366bc03ac83a58a8a2bedfbd9ded13900c996aa9719492c36ea1ad5a` |
| 2C | `docs/superpowers/plans/2026-07-10-kb-parameter-stage-8b-contract-audit.md` | `docs/archive/2026/plans/2026-07-10-kb-parameter-stage-8b-contract-audit.md` | plan | kb-parameter-stage-8b-contract-audit | 2026-07-10 | completed | `8292f9b7e78b5b6ed61a0b45436c3f05f48c5ef995306f4b2c3fca449d17b47a` |
| 2C | `docs/superpowers/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md` | `docs/archive/2026/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md` | spec | kb-parameter-stage-8b-contract-audit-design | 2026-07-10 | completed | `cc86955c70db527b3bde15064a518ff61cc846b63604ad975ca98ec6e385f795` |
| 2D | `docs/10-legacy-feature-gap-closure-design.md` | `docs/archive/2026/specs/10-legacy-feature-gap-closure-design.md` | spec | legacy-feature-gap-closure | 2026-06-24 | superseded | `89d3567d9f95235cc088933e4aa250eea27c97e4676ef891ac6a0dd1c1f2304d` |
| 2D | `docs/19-ragflux-capability-parity-plan.md` | `docs/archive/2026/plans/19-ragflux-capability-parity-plan.md` | plan | ragflux-capability-parity | 2026-07-03 | completed | `76229f65922a276d1c20cffd58fd4f4e8d0d238de86fa13b0d25b7e4bbee0361` |
| 2D | `docs/20-ragflow-doc-to-md-ingest-quality-plan.md` | `docs/archive/2026/plans/20-ragflow-doc-to-md-ingest-quality-plan.md` | plan | doc-to-md-ingest-quality | 2026-07-03 | completed | `bbbf64fc1891106ca1c9750c280b5804a56c2c2b137ea8ee1ada6cfd4ccde3f1` |
| 2D | `docs/39-benchmark-evidence-strengthening-hermes-test.md` | `docs/archive/2026/evidence/39-benchmark-evidence-strengthening-hermes-test.md` | evidence | benchmark-evidence-hermes-l0 | 2026-07-11 | evidence_only | `defa1f770f3a914af22addc3f7ed803a9bcbea81c55ef97f9345e2924ec5b0fe` |
| 2D | `docs/41-marker-aware-candidate-snapshot-hermes-l0.md` | `docs/archive/2026/evidence/41-marker-aware-candidate-snapshot-hermes-l0.md` | evidence | marker-aware-snapshot-hermes-l0 | 2026-07-11 | evidence_only | `5e8570be99a8f31a177843d5607e72803a817b87bb553d13c4c33e1ab71f3c9a` |
| 2D | `docs/42-financebench-marker-aware-l3-disposable-validation.md` | `docs/archive/2026/evidence/42-financebench-marker-aware-l3-disposable-validation.md` | evidence | financebench-marker-aware-l3 | 2026-07-12 | evidence_only | `0744d29110d7362e207f64c1d254b33d193cf6590a0ccc837116ddd355c02309` |
| 2D | `docs/specs/2026-08-02-financebench-new-minimal-l3-design.md` | `docs/archive/2026/specs/2026-08-02-financebench-new-minimal-l3-design.md` | spec | financebench-new-minimal-l3 | 2026-08-02 | completed | `870313be9076d3866b426562853cc581c04b574507e13180c3b56a9bc9c03117` |
| 2D | `docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md` | `docs/archive/2026/plans/2026-07-11-benchmark-evidence-strengthening.md` | plan | benchmark-evidence-strengthening-implementation | 2026-07-11 | completed | `1293a3daea56aaf90dcf126f0995e6915286e73313b4692d813ec441fc535440` |
| 2D | `docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md` | `docs/archive/2026/plans/2026-07-11-marker-aware-candidate-snapshot.md` | plan | marker-aware-candidate-snapshot-implementation | 2026-07-11 | completed | `d93d078db17a10a469b3b8bd4d2fa65fc94a3953eced0eaee6a0885142d52581` |
| 2D | `docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md` | `docs/archive/2026/specs/2026-07-11-marker-aware-candidate-snapshot-design.md` | spec | marker-aware-candidate-snapshot-design | 2026-07-11 | completed | `04104102fd13e8fde8c9e1a82ef621734a2de99512360ce8d9fa97d4fbb9dbc3` |

The 2D digests are planning evidence only. They cannot be used to bypass 2D's later
fresh-input audit and owner gate.

## Exact Inbound-Reference Inventory

### Batch 2A active updates

- `docs/03-development-plan.md`: replace the active reference to `docs/07-first-release.md`.
- `tools/version_date_drift_check.py`: replace the static release-document path with
  `docs/archive/2026/evidence/07-first-release.md`.
- `packages/ragflow-skill-runtime/tests/test_version_date_drift_check.py`: add an assertion
  that the archived path is included and the old path is absent.
- `tools/document_lifecycle_check.py`, `docs/document-registry.json`,
  `docs/archive/README.md`, and `docs/README.md`: apply the common migration changes.

### Batch 2B active updates

- `docs/03-development-plan.md`: update the active reference to the archived `docs/26`.
- `docs/29-kb-build-strict-regression-quality-plan.md`: update the reference to archived
  `docs/28`.
- `docs/35-standard-benchmark-dataset-integration-plan.md` and
  `docs/36-ragflow-kb-parameter-materialization-plan.md`: update references to archived
  `docs/34`.
- `tools/document_lifecycle_check.py`, `docs/document-registry.json`,
  `docs/archive/README.md`, and `docs/README.md`: apply the common migration changes.

The `docs/22` references to `docs/21` are inside the two archived original bodies. They
remain byte-preserved provenance, not active requirements.

### Batch 2C active updates

- `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md`: update its reference to
  the archived Stage 8B design.
- `tools/document_lifecycle_check.py`, `docs/document-registry.json`,
  `docs/archive/README.md`, and `docs/README.md`: apply the common migration changes.

References among the three archived Stage 8A/8B bodies remain byte-preserved provenance.

### Wave 2D blockers

Wave 2D has no executable checkbox. It remains blocked by both of these conditions:

1. External `ragflow-skills-maintainer` instructions still reference exact paths for
   `docs/10`, `docs/19`, and `docs/20`. The affected maintainer files are `SKILL.md` plus
   `phase-map.md`, `release-governance.md`, `secret-live-config-hygiene.md`,
   `task-selection.md`, and `validation-chain.md`. Editing them requires separate owner
   authority outside this repository plan.
2. Five retained private handoff files reference one or more 2D sources. A later 2D plan
   must prove each relevant ACTIVE authority is closed or refresh its references without
   migrating operational authority.

After those gates close, a fresh plan must re-audit active references in
`docs/03-development-plan.md`, `docs/30-hermes-e2e-test-plan.md`,
`docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`,
`docs/40-marker-aware-evidence-validation-and-promotion-plan.md`, and
`docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md`.
It must also define the existing-frontmatter transformation for the FinanceBench minimal
L3 spec and preserve its original body separately from metadata.

## Future Execution File Map

**Create through mechanical moves and historical prefixes:** the 18 destination files in
Waves 2A-2C.

**Modify:**

- `docs/document-registry.json`
- `docs/archive/README.md`
- `docs/README.md`
- `tools/document_lifecycle_check.py`
- `tools/version_date_drift_check.py`
- `packages/ragflow-skill-runtime/tests/test_version_date_drift_check.py`
- the active inbound-reference files named for 2A-2C above

**Must remain unchanged:**

- the governing spec;
- the Wave 1 plan's historical baseline text;
- all 10 Wave 2D sources;
- all external maintainer files and private handoffs;
- public skills, runtime behavior, CLI/report schemas, generated release products, and
  the six owner-modified paths outside `docs/03-development-plan.md`; only the approved
  inbound references in `docs/03-development-plan.md` may change.

## Stop Conditions

Stop before mutation or roll back only the active batch when any condition is true:

1. The governing spec SHA or approved/Gate-0 state differs.
2. The owner instruction does not name this plan's exact current SHA and permitted batch.
3. Any source SHA, type, owner, mode, or non-symlink state differs from the frozen input.
4. Any undeclared inbound reference is found or a declared active reference cannot be
   updated without overwriting unrelated owner work.
5. A source has unexpected frontmatter, a destination exists, or an archive directory is
   a symlink.
6. An original source byte is absent from the archived suffix or its digest differs.
7. Registry coverage, migration-map parity, legacy-allowlist removal, or active link
   resolution is incomplete.
8. Roadmap counts differ from `586/15`, registry adoption changes, or the governing spec
   changes.
9. Focused tests, full tests, lifecycle, release hygiene, build check, diff check, or
   safety review fails.
10. Execution would require Wave 2D, an external/private edit, network, credentials, live
    mutation, staging, commit, push, L3, Stage 8C, or L4.

## Rollback

Before each authorized batch, copy only that batch's sources and declared mutable inbound
files into a new owner-only temporary backup directory, record SHA-256 and modes, and
verify the backup before the first move. If the batch fails, restore only those recorded
paths, remove only newly created destinations from that batch, and rerun its failed check.
Do not use `git reset`, `git checkout`, `git clean`, `git stash`, or a repository-wide
restore. A successfully validated earlier batch remains intact when a later batch fails.

### Task 0: Bind Authority And Freeze The Execution Baseline

**Files:** Read-only verification of this plan, the governing spec, registry, archive
index, 18 authorized sources, declared inbound files, checker, and focused tests.

- [ ] **Step 1: Verify the owner-authorized plan and governing spec**

Run `sha256sum` on this plan and the governing spec. Require the plan digest to equal the
owner instruction and the spec digest to equal the value in Governance Binding. Confirm
`status=proposed`, `implementation_authority=false`, spec `status=approved`, and
`gate_0=closed`.

- [ ] **Step 2: Verify source identity and repository state**

Run `sha256sum` and `stat -c '%F %a %U %N'` over the 18 authorized sources and compare
every digest to the inventory. Require regular non-symlink files owned by the current
user, no pre-existing destination, one worktree, roadmap `586/15`, and no staged changes.
Record the seven pre-existing owner paths and do not treat them as this migration's work.
Capture `MIGRATION_DATE="$(date -u +%F)"` once; do not recalculate it between batches.

- [ ] **Step 3: Repeat exact-path inbound discovery**

Use one fixed-string `rg -n -F` query containing all 18 source paths. Classify every hit
as declared active update, preserved archived-body provenance, governing/plan provenance,
registry/archive migration data, or lifecycle allowlist. Any other class stops execution.

- [ ] **Step 4: Create and verify the per-batch rollback backup**

Create an owner-only directory under `/tmp`, copy only the first authorized batch and its
declared mutable inbound files with modes preserved, and write a sanitized path/SHA/mode
manifest. Verify every copied digest before continuing.

Expected: all control checks pass without changing repository bytes.

### Task 1: Execute Batch 2A

**Files:** the eight 2A source/destination pairs and 2A active updates listed above.

- [ ] **Step 1: Write and run the focused static-path regression test**

Change the import in `test_version_date_drift_check.py` to include `DOC_VERSION_PATHS`,
then add this method to `VersionDateDriftCheckTests`:

```python
def test_first_release_uses_archived_static_path(self) -> None:
    self.assertIn(Path("docs/archive/2026/evidence/07-first-release.md"), DOC_VERSION_PATHS)
    self.assertNotIn(Path("docs/07-first-release.md"), DOC_VERSION_PATHS)
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_version_date_drift_check.py' -v
```

Expected: the new test fails because the old static path is still configured.

- [ ] **Step 2: Prove the batch backup and destination directories**

Create `docs/archive/2026/{legacy,plans,specs,evidence}` only as needed. Require ordinary
directories inside the repository and absent destination files.

- [ ] **Step 3: Move and prefix the eight exact sources**

Use mechanical renames to the inventory destinations. Apply the complete historical
prefix contract using each row's values, then prove each archived file ends with its exact
backed-up source bytes and that each `original_sha256` matches.

- [ ] **Step 4: Update active references and the static release-document path**

Update `docs/03-development-plan.md` and change only this tuple member in
`tools/version_date_drift_check.py`:

```python
Path("docs/archive/2026/evidence/07-first-release.md"),
```

Rerun the focused test and require all cases to pass. Preserve every unrelated owner edit
in the roadmap.

- [ ] **Step 5: Update registry, migration map, archive index, README, and legacy allowlist**

Apply all eight registry path/state records, append the same eight sorted migration rows,
append matching archive-index rows, remove exactly the eight old paths from
`WAVE1_LEGACY_METADATA_PATHS`, and state in `docs/README.md` that 8 of 28 candidates are
archived while Wave 2 remains unadopted.

- [ ] **Step 6: Validate the 2A checkpoint**

Run the two focused test modules, lifecycle, roadmap counts, exact old-path inventory,
`git diff --check`, and release hygiene. Expected: lifecycle `61/61/0`, migrations `8`,
roadmap `586/15`, the eight sources absent, eight destinations present, and zero findings.

### Task 2: Execute Batch 2B

**Files:** the seven 2B source/destination pairs and 2B active updates listed above.

- [ ] **Step 1: Freeze and verify a separate 2B backup**

Repeat Task 0's backup and inbound-reference checks for only 2B. Do not reuse the 2A
backup as proof.

- [ ] **Step 2: Move and prefix the seven exact sources**

Apply the inventory destinations and complete prefix contract, then verify byte suffixes
and original digests against the 2B backup.

- [ ] **Step 3: Update declared active references and governance records**

Update only `docs/03`, `docs/29`, `docs/35`, and `docs/36` active references plus the
registry, migration array, archive index, README progress statement, and lifecycle legacy
allowlist. Do not edit preserved bodies in archived `docs/21` or `docs/22`.

- [ ] **Step 4: Validate the 2B checkpoint**

Run lifecycle focused tests, lifecycle, roadmap counts, exact old-path inventory,
`git diff --check`, and release hygiene. Expected: lifecycle `61/61/0`, migrations `15`,
roadmap `586/15`, 15 completed destinations, and zero findings.

### Task 3: Execute Batch 2C

**Files:** the three 2C source/destination pairs and 2C active updates listed above.

- [ ] **Step 1: Freeze and verify a separate 2C backup**

Repeat Task 0's backup and inbound-reference checks for only 2C. Confirm the three
tool-specific old paths remain legacy files before the move and have no destination.

- [ ] **Step 2: Move and prefix the three exact sources**

Apply the inventory destinations and complete prefix contract, then verify byte suffixes
and original digests against the 2C backup.

- [ ] **Step 3: Update the declared active reference and governance records**

Update only `docs/37` plus the registry, migration array, archive index, README progress
statement, and lifecycle legacy allowlist. Do not rewrite references preserved inside the
three archived bodies.

- [ ] **Step 4: Validate the 2C checkpoint**

Run lifecycle focused tests, lifecycle, roadmap counts, exact old-path inventory,
`git diff --check`, and release hygiene. Expected: lifecycle `61/61/0`, migrations `18`,
roadmap `586/15`, 18 completed destinations, and zero findings.

### Task 4: Run Final Offline Validation And Stop

**Files:** Read-only validation after the last authorized batch.

- [ ] **Step 1: Run focused and full unit tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_document_lifecycle_check.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests \
  -p 'test_version_date_drift_check.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run repository governance checks**

```bash
python3 tools/document_lifecycle_check.py
python3 tools/build_release.py --check
python3 tools/release_hygiene_check.py
git diff --check
```

Expected: lifecycle `61/61/0`, release hygiene zero findings, build check passes, and diff
check passes without changing generated products.

- [ ] **Step 3: Verify preservation, counts, and boundaries**

Require 18 migration entries, 18 exact source absences, 18 destination presences, 18
matching original byte suffixes, 10 unchanged 2D source digests, roadmap `586/15`,
`adopted=false`, unchanged governing spec SHA, empty staging area, and no unexpected
paths. Review all changed governance documents with the repository sensitive-literal
scan and disclose no matching value.

- [ ] **Step 4: Stop at owner review**

Report per-batch outcomes, changed paths, test totals, lifecycle/release results, residual
old-path provenance, and the unchanged 2D blockers. Do not transition the spec or either
plan, set registry adoption, stage, commit, push, contact a remote, edit external/private
files, or begin Wave 2D, Wave 3, Wave 4, or Wave 5.

## Acceptance Criteria

Future 2A-2C execution is acceptable only when:

1. exactly 18 sources move to their listed destinations and all 10 Wave 2D sources remain;
2. every archived file has historical metadata, a non-authority banner, and its exact
   original bytes as a verified suffix;
3. registry, archive index, document metadata, and migration records agree exactly;
4. all declared active references use destination paths and no undeclared dependency is
   introduced;
5. legacy allowlist exemptions are removed only for the 18 migrated sources;
6. lifecycle remains `61/61/0`, roadmap remains `586/15`, and registry remains unadopted;
7. focused/full tests, release hygiene, build check, diff check, and safety review pass;
8. no external maintainer file, private handoff, governing spec, Wave 2D file, live
   surface, generated product, staging area, commit, or remote changes.

## Owner Review Boundary

The next decision is to approve or reject the exact SHA-256 of this proposed plan. An
approval must separately name which of 2A, 2B, and 2C may execute. Wave 2D is not
approvable under this plan and requires a later successor after both blockers close.

`implementation=NOT_STARTED`
