---
doc_type: plan
topic: document-lifecycle-and-spec-archive-wave-4
status: implemented
created: 2026-08-04
updated: 2026-08-04
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related:
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md
  - docs/plans/2026-08-03-document-lifecycle-and-spec-archive-wave-3-implementation-plan.md
---

# Document Lifecycle And Spec Archive Wave 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize lifecycle metadata for the 13 stable active, gated, or proposed
document owners without moving paths, changing task state, or changing any owner body.

**Architecture:** Wave 4A prepends reviewed frontmatter to the 12 legacy-header owners
and preserves every existing byte as an exact suffix. Wave 4B separately calibrates only
the existing frontmatter of the governing lifecycle spec and preserves everything after
its current closing delimiter byte-for-byte. A focused checker change recognizes
canonical non-authoritative root owners and structured gate metadata without weakening
ordinary plan ownership rules.

**Tech Stack:** Markdown, JSON, Python 3.10+ standard library, `unittest`, `rg`, SHA-256,
and repository-local lifecycle and release-hygiene checks.

---

## Governance Binding

| Field | Frozen value |
| --- | --- |
| Execution state | `NOT_STARTED` |
| Governing spec | `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` |
| Governing spec SHA-256 | `e18d80b60b4a89ee3319c0eac74d44852a744d4b4a0909e677f7af936cb777fd` |
| Governing state | `status=approved`, `gate_0=closed`, `implementation_authority=false` |
| Planning branch | `feature/document-lifecycle-governance` |
| Pushed Wave 3B baseline | `e0e5fdf3886724fbfd4ee9aabce903359cc1f5d7` |
| Roadmap baseline | 586 checked, 15 unchecked |
| Registry baseline | 64 documents, 20 migrations, `adopted=false` |
| Wave 2D preservation requirement | all 10 paths unchanged |
| Deferred reference preservation | `docs/16-system-closeout-report.md` and `docs/43-agent-session-handoff-lessons.md` unchanged |

This proposed plan is planning evidence only. Its path, bytes, checksum, registry entry,
or review does not authorize either execution batch. A future owner instruction must
name this plan's exact SHA-256 and authorize exactly one of the following:

1. `Wave 4A` only; or
2. `Wave 4B` only, after Wave 4A has completed and been independently accepted.

Wave 4A authority never flows into Wave 4B. Wave 4B must not begin in the same execution
session unless the owner sends a new instruction after reviewing the completed Wave 4A
result. Neither batch authorizes Wave 2D, Wave 5, registry adoption, lifecycle closeout,
path moves, body edits, checkbox changes, external maintainer edits, network access,
credentials, live operations, generated release products, staging, commit, push, merge,
L3, Stage 8C, or L4.

## Planning-Only Change Set

Creating this proposed plan changes exactly three paths:

- create `docs/plans/2026-08-04-document-lifecycle-and-spec-archive-wave-4-implementation-plan.md`;
- register it in `docs/document-registry.json` as `wave1_governance`;
- link it from `docs/README.md` as proposed and non-authoritative.

The planning change must produce lifecycle `65/65/0`, keep registry migrations at 20,
preserve roadmap `586/15`, keep `adopted=false`, keep all 13 owner SHA-256 values below
unchanged, leave staging empty, and stop for owner review. Every task after this section
describes future work and remains unauthorized.

## Frozen Owner Inventory

Every row was observed as a current-user-owned, mode-`0664`, regular non-symlink file.
Any type, owner, mode, path, or SHA-256 mismatch is a pre-edit stop condition.

| Batch | Path | Frozen SHA-256 |
| --- | --- | --- |
| 4A | `docs/03-development-plan.md` | `4f26008ef478c9fb3bbe9221fc5ae41371615ad3a2413e0b1d515108a43dbc6f` |
| 4A | `docs/13-post-cli-adapter-planning.md` | `f0cb0e984ac0fefcb0efafae38ccfb89478b1ae7ed98725b6ef9c229b0e7c37e` |
| 4A | `docs/14-optional-llm-backend-planning.md` | `c41564e51acd0794a31649f773a32e434226595851642da4b9cb76d9c38a2d71` |
| 4A | `docs/15-field-trial-observation-plan.md` | `590a10b4a3fbf388315a8c080be221db3ab60e6fbaf31fde741ce40a03c227ad` |
| 4A | `docs/29-kb-build-strict-regression-quality-plan.md` | `6b5865ea2a86ef0bb883491905a320825147189f17d2e2a8482faba1a42852f3` |
| 4A | `docs/31-hermes-e2e-improvement-follow-up-plan.md` | `256aaa5740186a6560fc89c4f97513ddfbc69bd2acdda95bde5541e0cf125690` |
| 4A | `docs/32-retirement-transition-action-plan.md` | `19adb8b63b37509c34bc891106e816005bcf371170e1c374bc27f246473bffa7` |
| 4A | `docs/35-standard-benchmark-dataset-integration-plan.md` | `e6ebbd15f468f9129215dc8b937194b7a84732661d158c0b9dd42b30e5181476` |
| 4A | `docs/36-ragflow-kb-parameter-materialization-plan.md` | `75ff37f7692fdbd4a5d917405a1e001e2f76468ba34d8d92be8bb4476b15b39f` |
| 4A | `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md` | `a868ce0d56440b89c5f99ac30a801f51b86cd97e7448695dcd0dfbec8cb498dd` |
| 4A | `docs/40-marker-aware-evidence-validation-and-promotion-plan.md` | `718c128017f78d8a2d1bd6d018c54ce85d1068edffec5786bc6ffcdcabd18155` |
| 4A | `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md` | `bf28a7ea846cd0c62315c516877ad1e5d65937a16b341b5662f4d50481219f7e` |
| 4B | `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` | `e18d80b60b4a89ee3319c0eac74d44852a744d4b4a0909e677f7af936cb777fd` |

The four Wave 3 rollback directories recorded at plan-authoring time remain protected:

- `ragflow-wave3a-rollback-LAdOiEnC`;
- `ragflow-wave3a-rollback-RePDeaOD`;
- `ragflow-wave3b-repository-rollback.btTQ3f`;
- `ragflow-wave3b-external-rollback.Kq5l53`.

The external maintainer files modified during Wave 3B are read-only protected inputs for
this plan:

| Role | Frozen SHA-256 |
| --- | --- |
| maintainer `SKILL.md` | `96c27a379ebfb36f4853dae02e3fc0826710c171706d436d8a1eae1ebd73d051` |
| maintainer `references/task-selection.md` | `b4938fc7b374f155521d116a3b2f7b7fde46d8f5534fe02c5d96c9957d8351c8` |
| maintainer `references/phase-map.md` | `eebdba5a634a1e2a2cc9420f26bd922c506b57061fcabce1b73905cded4dd3f2` |

Wave 4 must neither modify these files nor require access to their containing directory.

## Exact Metadata Contract

### Fields shared by all 13 owners

The final metadata for every owner uses these exact common values:

```yaml
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
```

`owner_spec: null` is intentional. These 13 files are the reviewed canonical roots of
pre-governance topics, not implementation plans derived from an approved topic spec.
Assigning the governing lifecycle spec or another unrelated spec as their owner would be
semantically false. The null owner does not create implementation authority.

The row table supplies every varying value. A dash in the `gate` column means the key is
absent. The exact gate strings name existing blockers and do not open those gates.

| Path | `doc_type` | `topic` | `status` | `created` | Exact `gate` value |
| --- | --- | --- | --- | --- | --- |
| `docs/03-development-plan.md` | `roadmap` | `current-development` | `active` | `2026-07-02` | - |
| `docs/13-post-cli-adapter-planning.md` | `plan` | `post-cli-adapters` | `gated` | `2026-07-02` | `concrete_host_or_product_workflow_with_contract_fixtures_and_acceptance_evidence` |
| `docs/14-optional-llm-backend-planning.md` | `plan` | `optional-llm-backends` | `gated` | `2026-07-02` | `explicit_backend_implementation_request_with_deterministic_fixtures_and_safety_gates` |
| `docs/15-field-trial-observation-plan.md` | `plan` | `field-trial-observation` | `active` | `2026-07-02` | - |
| `docs/29-kb-build-strict-regression-quality-plan.md` | `plan` | `kb-build-strict-regression` | `gated` | `2026-07-08` | `explicit_owner_approval_for_disposable_r3_live_regression` |
| `docs/31-hermes-e2e-improvement-follow-up-plan.md` | `plan` | `hermes-e2e-follow-up` | `gated` | `2026-07-08` | `explicit_owner_request_for_optional_p2_routing_validation` |
| `docs/32-retirement-transition-action-plan.md` | `plan` | `retirement-transition` | `active` | `2026-07-08` | - |
| `docs/35-standard-benchmark-dataset-integration-plan.md` | `plan` | `standard-benchmark-datasets` | `gated` | `2026-07-09` | `reviewed_financebench_input_closure_and_separate_disposable_lifecycle_approval` |
| `docs/36-ragflow-kb-parameter-materialization-plan.md` | `plan` | `kb-parameter-materialization` | `gated` | `2026-07-10` | `new_version_bound_writable_contract_candidate_and_separate_live_approval` |
| `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md` | `plan` | `benchmark-evidence-strengthening` | `gated` | `2026-07-11` | `reviewed_financebench_input_closure_disposable_lifecycle_approval_and_transition_sample_coverage` |
| `docs/40-marker-aware-evidence-validation-and-promotion-plan.md` | `plan` | `marker-aware-evidence-promotion` | `gated` | `2026-07-11` | `representative_observed_evidence_and_separate_l4_promotion_authorization` |
| `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md` | `spec` | `skill-surface-simplification` | `proposed` | `2026-08-02` | - |
| `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md` | `spec` | `document-lifecycle-and-spec-archive` | `approved` | `2026-08-02` | - |

### Wave 4A exact prefix

Each Wave 4A file currently has no frontmatter. Serialize keys in this exact order:
`doc_type`, `topic`, `status`, `created`, `updated`, `canonical`,
`implementation_authority`, `owner_spec`, `supersedes`, `superseded_by`, `related`, and
then `gate` only for a gated row. The row table and common-field block are normative.
The exact non-gated prefix for the roadmap is:

```yaml
---
doc_type: roadmap
topic: current-development
status: active
created: 2026-07-02
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
---

```

The exact gated suffix to the common key sequence is one line such as the following
literal value for `docs/13-post-cli-adapter-planning.md`:

```yaml
gate: concrete_host_or_product_workflow_with_contract_fixtures_and_acceptance_evidence
```

The other seven literal values come directly from their complete table rows. The
complete pre-edit bytes, beginning with the existing level-one heading, follow the final
blank line and remain an exact byte suffix.

### Wave 4B exact frontmatter

Wave 4B replaces only the governing spec's current frontmatter with these exact bytes:

```yaml
---
doc_type: spec
topic: document-lifecycle-and-spec-archive
status: approved
created: 2026-08-02
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
gate_0: closed
---
```

Everything after the existing closing delimiter remains byte-identical. In particular,
Wave 4B does not rewrite the title, requirements, decision log, current stop, or any
historical FinanceBench statement.

## Checker Compatibility Contract

The current checker has three pre-Wave-4 assumptions that must be changed narrowly:

1. every normalized `plan` requires an approved or active spec owner;
2. every normalized `gated` document requires a body line beginning `Gate:`,
   `Blocked on:`, or `Blocking condition:`;
3. `WAVE1_LEGACY_PATHS` is derived from `WAVE1_LEGACY_METADATA_PATHS`.

Wave 4 must implement these exact semantics:

- a plan may use a null owner only when its registry entry has
  `baseline_class=active_owner`, `canonical=true`,
  `implementation_authority=false`, and `owner=null`;
- every other normalized plan still requires a registered spec in `approved` or `active`
  state;
- a gated document passes the named-gate rule when either its body matches the existing
  gate regex or its frontmatter has a non-empty string `gate` value;
- a present `gate` value that is not a non-empty string produces `invalid_gate` and does
  not satisfy the named-gate rule;
- `WAVE1_LEGACY_PATHS` becomes an explicit reviewed set independent of metadata
  exemptions, so the normalized skill-surface spec may retain `legacy_path=true` until
  Wave 5 without retaining `legacy_metadata=true`;
- each owner leaves `WAVE1_LEGACY_METADATA_PATHS` only in the same authorized batch that
  installs its normalized metadata and flips its registry entry to
  `legacy_metadata=false`.

The explicit legacy path set after Wave 4A remains:

```python
WAVE1_LEGACY_PATHS = frozenset(
    {
        "docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md",
        "docs/superpowers/plans/2026-07-11-marker-aware-candidate-snapshot.md",
        "docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md",
        "docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md",
    }
)
```

This is compatibility metadata only. It does not authorize a path move or post-adoption
tool-specific document creation.

## Preservation And Rollback Contract

Before either batch edits a file, create one private rollback root with `mktemp -d`, set
it to mode `0700`, copy only that batch's authorized paths while preserving modes, and
write a mode-`0600` SHA-256 inventory. Do not delete any earlier rollback directory.

Wave 4A succeeds only if, for each owner:

```python
after_bytes.endswith(before_bytes)
```

and the suffix begins at exactly `len(after_bytes) - len(before_bytes)`. The SHA-256 of
that suffix must equal the frozen pre-edit SHA in the inventory.

Wave 4B splits the old governing-spec bytes at the first closing frontmatter delimiter,
retains the entire post-delimiter byte sequence including its leading newline, and
verifies:

```python
new_post_delimiter_bytes == old_post_delimiter_bytes
```

Rollback restores only the active batch's authorized paths from its backup, reruns the
focused lifecycle tests and lifecycle checker, and stops. Rollback must not use
`git reset`, `git checkout`, `git clean`, stash, or broad deletion because unrelated
owner work may coexist in the worktree.

## Task 0: Read-Only Preflight For Either Batch

**Files:**

- Read: this exact plan and its governing spec
- Read: the batch's owner files
- Read: `docs/document-registry.json`
- Read: `tools/document_lifecycle_check.py`
- Read: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

- [ ] **Step 1: Verify execution authority and repository identity**

Confirm the owner's message names the exact current SHA-256 of this plan and exactly one
batch. Verify branch `feature/document-lifecycle-governance`, local `HEAD`, local feature
tracking ref, empty staging, one worktree, and the pre-existing dirty-path set. Do not
contact a remote. Any unexpected path or ref drift stops the batch.

- [ ] **Step 2: Verify governing inputs and protected boundaries**

Recompute the governing spec SHA, registry state, roadmap counts, migration count, all
13 owner identities, the external maintainer hashes when readable without expanding
authority, and the four Wave 3 rollback-directory identities. A missing or changed
protected input stops before backup or edit.

- [ ] **Step 3: Run pre-edit governance checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 tools/document_lifecycle_check.py
git diff --check
```

Expected lifecycle result before Wave 4A is `65/65/0`. Before Wave 4B, require the
accepted Wave 4A result and the post-4A clean validation baseline named by that result.

- [ ] **Step 4: Create the batch-scoped rollback root**

Use `mktemp -d` with prefix `ragflow-wave4a-rollback.` or
`ragflow-wave4b-rollback.`, apply mode `0700`, copy only authorized files, and record the
frozen hashes and modes in a mode-`0600` inventory. Stop if an exclusive private root
cannot be created.

## Task 1: Add Focused Checker Semantics With TDD

**Files:**

- Modify: `tools/document_lifecycle_check.py`
- Test: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

This task belongs to Wave 4A only.

- [ ] **Step 1: Extend the fixture helper and write failing tests**

Change `_write_doc` so a test may explicitly request `owner_spec: null` without changing
the default fixtures, and so it accepts an optional structured gate:

```python
def _write_doc(
    root: Path,
    relative_path: str,
    *,
    doc_type: str,
    topic: str,
    status: str,
    canonical: bool,
    body: str,
    owner_spec: str | None = None,
    include_null_owner_spec: bool = False,
    gate: str | None = None,
    archive_fields: bool = False,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if owner_spec is not None:
        owner_line = f"owner_spec: {owner_spec}\n"
    elif include_null_owner_spec:
        owner_line = "owner_spec: null\n"
    else:
        owner_line = ""
    gate_line = f"gate: {json.dumps(gate)}\n" if gate is not None else ""
    archive_lines = "archived: 2026-08-03\nhistorical_reason: completed\n" if archive_fields else ""
    path.write_text(
        "---\n"
        f"doc_type: {doc_type}\n"
        f"topic: {topic}\n"
        f"status: {status}\n"
        "created: 2026-08-03\n"
        "updated: 2026-08-03\n"
        f"canonical: {'true' if canonical else 'false'}\n"
        "implementation_authority: false\n"
        f"{owner_line}"
        "supersedes: []\n"
        "superseded_by: null\n"
        "related: []\n"
        f"{gate_line}"
        f"{archive_lines}"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
```

Add tests with these literal contracts:

```python
def test_canonical_active_owner_plan_may_have_null_owner(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/root-plan.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="root-plan",
            status="active",
            canonical=True,
            include_null_owner_spec=True,
            body="# Root Plan\n\nCurrent root owner.\n",
        )
        entries.append(
            _entry(
                path,
                doc_type="plan",
                topic="root-plan",
                status="active",
                canonical=True,
                baseline_class="active_owner",
            )
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertTrue(report["ok"], report)

def test_ordinary_plan_with_null_owner_is_reported(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/plans/unowned.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="unowned",
            status="proposed",
            canonical=False,
            include_null_owner_spec=True,
            body="# Unowned Plan\n",
        )
        entries.append(
            _entry(path, doc_type="plan", topic="unowned", status="proposed", canonical=False)
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertIn("invalid_plan_owner", self._checks(report))

def test_gated_active_owner_accepts_nonempty_structured_gate(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/gated-root.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="gated-root",
            status="gated",
            canonical=True,
            include_null_owner_spec=True,
            gate="explicit_owner_decision",
            body="# Gated Root\n\nWork remains deferred.\n",
        )
        entries.append(
            _entry(
                path,
                doc_type="plan",
                topic="gated-root",
                status="gated",
                canonical=True,
                baseline_class="active_owner",
            )
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertTrue(report["ok"], report)

def test_empty_structured_gate_is_reported(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/gated-root.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="gated-root",
            status="gated",
            canonical=True,
            include_null_owner_spec=True,
            gate="",
            body="# Gated Root\n\nWork remains deferred.\n",
        )
        entries.append(
            _entry(
                path,
                doc_type="plan",
                topic="gated-root",
                status="gated",
                canonical=True,
                baseline_class="active_owner",
            )
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertIn("invalid_gate", self._checks(report))
    self.assertIn("missing_named_gate", self._checks(report))

def test_non_string_structured_gate_is_reported(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/gated-root.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="gated-root",
            status="gated",
            canonical=True,
            include_null_owner_spec=True,
            gate="temporary_valid_value",
            body="# Gated Root\n\nWork remains deferred.\n",
        )
        document = root / path
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                'gate: "temporary_valid_value"',
                "gate: []",
            ),
            encoding="utf-8",
        )
        entries.append(
            _entry(
                path,
                doc_type="plan",
                topic="gated-root",
                status="gated",
                canonical=True,
                baseline_class="active_owner",
            )
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertIn("invalid_gate", self._checks(report))
    self.assertIn("missing_named_gate", self._checks(report))

def test_existing_body_named_gate_remains_supported(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = _valid_fixture(root)
        path = "docs/plans/body-gated.md"
        _write_doc(
            root,
            path,
            doc_type="plan",
            topic="body-gated",
            status="gated",
            canonical=True,
            owner_spec="docs/specs/example.md",
            body="# Body-Gated Plan\n\nGate: explicit owner decision.\n",
        )
        entries.append(
            _entry(
                path,
                doc_type="plan",
                topic="body-gated",
                status="gated",
                canonical=True,
                owner="docs/specs/example.md",
            )
        )
        _write_registry(root, entries)
        report = run_document_lifecycle_check(root=root)

    self.assertTrue(report["ok"], report)
```

Retain the existing test proving that an ordinary plan owned by a proposed spec is
rejected and the existing test proving that a gated body without a named gate is
rejected.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -p 'test_document_lifecycle_check.py' -v
```

Expected failures are limited to the new root-owner and structured-gate cases. Any
unrelated failure stops the batch.

- [ ] **Step 3: Implement the minimal checker behavior**

Add this helper near the metadata validators:

```python
def _has_structured_gate(metadata: dict[str, object]) -> bool:
    value = metadata.get("gate")
    return isinstance(value, str) and bool(value.strip())
```

Replace the gated-document check with:

```python
        if "gate" in metadata and not _has_structured_gate(metadata):
            findings.append(Finding("invalid_gate", path, "metadata gate must be a non-empty string"))
        if (
            status == "gated"
            and not legacy_metadata
            and not _has_structured_gate(metadata)
            and not GATE_RE.search(body)
        ):
            findings.append(Finding("missing_named_gate", path, "gated document must name its blocking condition"))
```

Replace the normalized-plan owner condition with:

```python
        if entry.get("doc_type") == "plan" and not legacy_metadata:
            owner = entry.get("owner")
            owner_entry = entry_by_path.get(str(owner)) if isinstance(owner, str) else None
            is_canonical_root_owner = (
                entry.get("baseline_class") == "active_owner"
                and entry.get("canonical") is True
                and entry.get("implementation_authority") is False
                and owner is None
            )
            if not is_canonical_root_owner and (
                owner_entry is None
                or owner_entry.get("doc_type") != "spec"
                or owner_entry.get("status") not in {"approved", "active"}
            ):
                findings.append(Finding("invalid_plan_owner", path, "plan owner must be an approved or active spec"))
```

Replace the derived `WAVE1_LEGACY_PATHS` with the explicit four-path set in the checker
compatibility contract. Do not remove an owner from `WAVE1_LEGACY_METADATA_PATHS` yet.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the complete lifecycle-checker test file. Expected result: all tests pass, including
the existing body-gate and ordinary-plan-owner cases. Do not continue if the exception
accepts a non-canonical plan, an authoritative plan, or a plan outside
`baseline_class=active_owner`.

## Task 2: Execute Wave 4A Metadata Normalization

**Files:**

- Modify: the 12 Wave 4A owner files in the frozen inventory
- Modify: `docs/document-registry.json`
- Modify: `docs/README.md`
- Modify: `tools/document_lifecycle_check.py`
- Test: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

- [ ] **Step 1: Prepend exact metadata to the 12 owners**

Use `apply_patch` and the exact metadata table. Do not reflow or normalize the existing
body, line endings, whitespace, headings, status prose, checkboxes, or links. Immediately
verify each new file ends with its complete backup bytes.

- [ ] **Step 2: Update registry and metadata exemptions atomically**

For exactly the 12 Wave 4A registry entries, change only
`legacy_metadata:true` to `legacy_metadata:false`. Keep every other field unchanged,
including `owner:null`, `related:[]`, `baseline_class:active_owner`, and the
skill-surface spec's `legacy_path:true`.

Remove exactly those 12 paths from `WAVE1_LEGACY_METADATA_PATHS`. Add a focused test that
asserts the 12-path set has no intersection with the metadata exemption and that the
skill-surface path remains in `WAVE1_LEGACY_PATHS`:

```python
def test_wave4a_owner_metadata_is_normalized_while_legacy_path_remains(self) -> None:
    normalized_paths = {
        "docs/03-development-plan.md",
        "docs/13-post-cli-adapter-planning.md",
        "docs/14-optional-llm-backend-planning.md",
        "docs/15-field-trial-observation-plan.md",
        "docs/29-kb-build-strict-regression-quality-plan.md",
        "docs/31-hermes-e2e-improvement-follow-up-plan.md",
        "docs/32-retirement-transition-action-plan.md",
        "docs/35-standard-benchmark-dataset-integration-plan.md",
        "docs/36-ragflow-kb-parameter-materialization-plan.md",
        "docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md",
        "docs/40-marker-aware-evidence-validation-and-promotion-plan.md",
        "docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md",
    }

    self.assertFalse(normalized_paths & WAVE1_LEGACY_METADATA_PATHS)
    self.assertIn(
        "docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md",
        WAVE1_LEGACY_PATHS,
    )
```

Import `WAVE1_LEGACY_PATHS` beside the existing metadata constant in the test module.

- [ ] **Step 3: Update the default index without changing task state**

Set the `docs/README.md` frontmatter `updated` date to `2026-08-04`. Update only the
Wave 4 bullet to state `Wave_4A=COMPLETE / OWNER_REVIEW_REQUIRED` and
`Wave_4B=NOT_STARTED / NOT_AUTHORIZED`. Do not claim Wave 4 as a whole is complete.

- [ ] **Step 4: Verify Wave 4A preservation and governance**

Run, in order:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -p 'test_document_lifecycle_check.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -p 'test_release_hygiene.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 tools/document_lifecycle_check.py
python3 tools/release_hygiene_check.py --no-build
python3 tools/build_release.py --check
git diff --check
```

Verify lifecycle `65/65/0`, release hygiene with zero findings, full tests passing,
roadmap `586/15`, registry migrations 20, `adopted=false`, 12/12 exact suffix matches,
the untouched governing spec still matching its frozen SHA, empty staging, no generated
dirty path, and no unexpected changed path.

- [ ] **Step 5: Stop at the Wave 4A owner checkpoint**

Report changed paths, test counts, lifecycle summary, suffix preservation, exact
remaining exemptions, protected-file hashes, rollback root, residual risk, and
`Wave_4B=NOT_STARTED`. Do not stage, commit, push, or begin Wave 4B.

## Task 3: Execute Separately Authorized Wave 4B

**Files:**

- Modify: `docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md`
- Modify: `docs/document-registry.json`
- Modify: `docs/README.md`
- Modify: `tools/document_lifecycle_check.py`
- Test: `packages/ragflow-skill-runtime/tests/test_document_lifecycle_check.py`

- [ ] **Step 1: Re-run Task 0 under fresh Wave 4B authority**

Require the accepted Wave 4A exact result, unchanged Wave 4 plan SHA, the complete
post-4A owner inventory, and an owner message that explicitly authorizes Wave 4B. A prior
Wave 4A instruction is insufficient.

- [ ] **Step 2: Replace only the governing-spec frontmatter**

Use the exact Wave 4B frontmatter in this plan. Preserve the old post-delimiter bytes
exactly and verify the new post-delimiter SHA equals the backup post-delimiter SHA. Keep
mode `0664`, current user ownership, regular type, and non-symlink state.

- [ ] **Step 3: Retire the final owner metadata exemption**

Change only the governing spec registry entry's `legacy_metadata` from `true` to `false`
and remove only its path from `WAVE1_LEGACY_METADATA_PATHS`. Add this assertion to the
focused exemption test:

```python
self.assertNotIn(
    "docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md",
    WAVE1_LEGACY_METADATA_PATHS,
)
```

Do not change `gate_0`, registry governing-spec identity, spec status, canonical state,
or implementation authority.

- [ ] **Step 4: Update the default index**

Update only the Wave 4 bullet to state
`Wave_4A_COMPLETE / Wave_4B_COMPLETE / OWNER_REVIEW_REQUIRED`. Do not transition the
governing spec, prior plans, this plan, or registry adoption; those belong to a later
Wave 5 plan.

- [ ] **Step 5: Run final Wave 4 validation**

Run the same focused, full-suite, lifecycle, release-hygiene, build, and diff checks as
Wave 4A. Additionally verify 12/12 Wave 4A suffixes remain intact, the Wave 4B
post-delimiter body is exact, all 13 owner registry entries use
`legacy_metadata=false`, the four-path legacy path exemption remains exact, roadmap is
`586/15`, migrations are 20, `adopted=false`, staging is empty, and no unexpected path or
generated product changed.

- [ ] **Step 6: Stop at the Wave 4 owner checkpoint**

Report `WAVE_4_COMPLETE / OWNER_REVIEW_REQUIRED` and `Wave_5=NOT_STARTED /
NOT_AUTHORIZED`. Do not stage, commit, push, merge, adopt the registry, or write a Wave 5
plan without a separate owner instruction.

## Stop Conditions

Stop before the first edit, or restore only the active batch from its rollback root and
stop, if any of these conditions occurs:

1. authority does not name this plan's exact SHA and the single permitted batch;
2. branch, local HEAD/tracking ref, staging, worktree count, or pre-existing dirty scope
   differs from the accepted checkpoint;
3. a frozen owner, governing input, protected external file, or rollback directory has
   unexpected identity or state;
4. a Wave 4A file already has frontmatter, or the governing spec lacks one unambiguous
   closing frontmatter delimiter;
5. any proposed metadata value differs from the exact table or changes a registry field
   other than the authorized `legacy_metadata` flag;
6. an owner body, existing checkbox, path, mode, owner, type, link, or task-status prose
   changes;
7. the checker exception would permit an ordinary unowned plan, non-canonical owner,
   authoritative owner, or invalid/empty structured gate;
8. the skill-surface spec loses its reviewed legacy-path exemption before adoption;
9. suffix or post-delimiter preservation fails for one byte;
10. roadmap counts, migration count, registry adoption, governing status, or Gate 0
    changes;
11. a lifecycle, test, release-hygiene, build, diff, sensitive-value, staging, or
    generated-path check fails;
12. execution would touch a Wave 2D file, deferred reference, external maintainer file,
    private handoff, prior rollback backup, release artifact, or path outside the active
    batch;
13. execution would require network, credentials, live operations, staging, commit,
    push, merge, L3, Stage 8C, L4, Wave 5, or a second batch without fresh authority.

## Acceptance Criteria

### Planning-only acceptance

1. exactly this plan, `docs/README.md`, and `docs/document-registry.json` change;
2. lifecycle reports `65/65/0` and registry remains 20 migrations with
   `adopted=false`;
3. all 13 frozen owner SHA-256 values and roadmap `586/15` remain unchanged;
4. the plan contains complete SHA, metadata, gate, preservation, rollback, TDD,
   validation, authorization, and stop-condition contracts;
5. staging stays empty and no execution, network, remote, commit, push, or live action
   occurs.

### Future Wave 4A acceptance

1. all 12 legacy-header owners have the exact reviewed frontmatter and unchanged existing
   bytes as exact suffixes;
2. all eight gated owners have their exact structured gate value;
3. null owner semantics apply only to canonical, non-authoritative active-owner roots;
4. ordinary plan owner checks and body-named gate compatibility remain strict;
5. the 12 registry entries and metadata exemptions are calibrated atomically while the
   skill-surface legacy-path exemption remains;
6. all validation passes, and execution stops before Wave 4B.

### Future Wave 4B acceptance

1. the governing spec has the exact reviewed frontmatter, including unchanged
   `gate_0=closed`;
2. every post-delimiter body byte is unchanged;
3. the final owner metadata exemption is retired atomically with its registry flag;
4. all 13 stable owners are normalized without any path, body, checkbox, authority,
   adoption, roadmap, migration, or external-file change;
5. all validation passes, and execution stops with Wave 5 unauthorized.

## Lifecycle Closeout

Owner-authorized Waves 4A and 4B are complete, committed, pushed, and independently
validated. The unchecked boxes above preserve the original execution plan; they create no
new authority after adoption.

`implementation=WAVE_4_COMPLETE`
