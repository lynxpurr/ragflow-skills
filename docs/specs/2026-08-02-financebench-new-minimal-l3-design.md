---
doc_type: spec
topic: financebench-new-minimal-l3
status: implemented
created: 2026-08-02
updated: 2026-08-03
canonical: false
outcome: formally_closed_without_l3_evidence
implementation_authority: false
live_authority: false
supersedes: []
superseded_by: null
related:
  - docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md
  - docs/40-marker-aware-evidence-validation-and-promotion-plan.md
  - docs/42-financebench-marker-aware-l3-disposable-validation.md
  - docs/43-agent-session-handoff-lessons.md
---

# FinanceBench NEW_MINIMAL_L3 Design

## Context

FinanceBench still lacks one accepted disposable build, observed-retrieval, and cleanup
lifecycle. That evidence would complete the live FinanceBench side of the existing
two-subset review, but it is not a release blocker and cannot authorize L4 or a default
change.

The earlier preparation path produced a reviewed Stage-B result and a pending run
contract in temporary storage. The contract, its reviews, the request, and the custom
14-file execution package are no longer present. Their recorded hashes cannot recreate
the missing bytes or create live authority. The package sources were not tracked in Git.

The old path also spent more effort constructing handoff and authorization machinery
than exercising the public skill surface. The owner selected `NEW_MINIMAL_L3` to replace
that future-run design. The historical attempt, recovery, forensic, and cleanup-policy
record in `docs/42` remains evidence; only its prospective execution design is
superseded.

## Objective

Bring FinanceBench L3 to a terminal result in at most one working day by using the
existing public RAGFlow commands for one disposable lifecycle:

1. verify that the retained input and current public CLI are sufficient;
2. freeze one durable private run contract;
3. obtain exact-SHA approval for that contract;
4. create, upload, parse, observe, validate, clean up, and prove absence once; and
5. return one sanitized result before any post-L3 or L4 decision.

`Terminal result` means either accepted L3 evidence or a precise fail-closed result. It
does not mean repeatedly revising preparation artifacts until a live run succeeds.

## Non-Goals

This design does not:

- reconstruct or reproduce the lost Stage-B package, request, contract, or reviews;
- add a public CLI command, schema, report surface, runtime helper, or product feature;
- change the FinanceBench source, reviewed query text, qrels, profile, or evidence spans;
- run MinerU, DeepDoc, RAGAS, an LLM evaluation, Stage 8C, or L4;
- compare native-PDF ingestion, upload images, or add a second document;
- modify an existing dataset or inspect an unrelated dataset beyond bounded collision
  listing metadata;
- authorize live RAGFlow access through this tracked document;
- modify, stage, commit, push, stash, or revert unrelated user work; or
- create another chain of prep, repair, and handoff batches after the timebox expires.

## Requirements And Invariants

### Authority

- This spec authorizes no network, credential read, RAGFlow call, or mutation.
- One manual owner instruction may authorize offline feasibility work and one read-only
  Git remote attestation.
- Live work begins only after the owner explicitly authorizes the exact SHA-256 of one
  immutable private run contract.
- Only one session may consume that live authority. A second session may review bytes
  offline but must never execute the lifecycle.
- Contract approval cannot migrate to changed inputs, commands, names, timeouts, cleanup
  rules, or repository runtime bytes.

### Timebox And Stop-Loss

- Offline feasibility has a 60-minute timebox.
- Contract materialization and its reviews have a further 120-minute timebox.
- The live lifecycle uses the contract's bounded parse and cleanup deadlines and receives
  no automatic retry.
- Missing input bytes, a runtime hash mismatch, an incompatible public CLI, inability to
  establish exact cleanup identity, or a need for a new multi-file execution subsystem
  ends the attempt before mutation.
- A failed feasibility gate returns `FORMAL_CLOSE_RECOMMENDED`; it must not create an
  automatic successor request or another audit-only batch.

### Durable Private State

- Required inputs, the contract, its reviews, command captures, checkpoint, manifest,
  evidence, and cleanup proofs live under one owner-only durable private root.
- Authority-bearing or unique evidence must not exist only under `/tmp`.
- Directories are mode `0700`; private files are mode `0600`; symlinks are forbidden.
- The temporary live config is the only intentionally ephemeral authority-bearing file.
  It must be deleted and proven absent on every terminal path.
- A manual handoff message identifies the controlling paths and hashes. The private root
  is not treated as implicit cross-session memory.

### Repository And Runtime Baseline

- The contract records `HEAD`, `develop`, the local tracking ref, and one fresh actual
  remote `develop` attestation.
- The three commit identities must match the approved execution commit before live work.
- Unrelated user-owned tracked or untracked documentation changes are recorded and
  preserved; they are not silently stashed, reverted, staged, or committed.
- Every executable, template, profile, and input used by the lifecycle must be an
  unmodified regular non-symlink whose observed SHA-256 is frozen in the contract.
- Any dirty file that participates in execution fails the gate. Unrelated documentation
  drift does not invalidate runtime identity when it is explicitly inventoried.

### Input Closure

The feasibility gate must locate and verify, without reconstructing provenance:

- the exact reviewed formal Markdown;
- the normalized seven-query set in its reviewed order;
- the reviewed benchmark/qrels and nine evidence spans;
- the exact public profile;
- the current public build, validation, query, cleanup, and reporting entrypoints; and
- a permitted private live-config source whose value is not printed or copied into
  tracked files.

Every required input must have current bytes and an observed digest. A digest recorded in
historical prose is not a substitute for missing bytes. Missing closure ends the attempt.

## Design

### Gate A: Offline Feasibility And Contract

One fresh session performs the following bounded work:

1. Verify input closure, repository/runtime identity, permissions, and current public CLI
   capabilities without contacting RAGFlow.
2. Perform at most one explicitly authorized read-only Git remote attestation for the
   exact `develop` ref; do not fetch or mutate refs.
3. Prove that public commands can create with a checkpoint, parse with a deadline, run
   the two validation passes, clean up by exact identifier/name, and emit sanitized
   reports.
4. Prefer direct public commands. No reusable product code or multi-file private package
   may be written. One small private orchestration file is permitted only to sequence
   existing commands, maintain durable state, handle signals, and guarantee cleanup. It
   must not implement HTTP, parse raw service responses, or replace public CLI behavior.
5. Freeze one `approval_required` contract containing the exact inputs, executable
   hashes, command arrays, environment allowlist, operation ceilings, deadlines,
   checkpoint/state rules, cleanup commands, and retention boundary.
6. Obtain one governance and one execution/cleanup review bound to the same exact
   contract SHA. Exact-SHA dual review is used only here because this is the real live
   authority boundary.
7. Stop and return a sanitized summary. Gate A must not read the credential value,
   create a live config, contact RAGFlow, or mutate a dataset.

If Gate A cannot finish within its timebox, the result is a blocker rather than a request
for another preparation batch.

### Gate B: One Live Lifecycle

After separate owner approval of the exact contract SHA, the sole executor:

1. Rechecks the contract, reviews, runtime hashes, source inputs, remote identity, and
   private permissions before credential use.
2. Materializes one temporary mode-`0600` config without printing its contents.
3. Generates one private disposable name and confirms no exact collision through the
   contract-defined bounded read-only check.
4. Runs one public build of the pinned Markdown: at most one dataset create, one upload,
   one parse trigger, and the bounded parse wait.
5. Persists the returned dataset and document identity immediately in the private
   checkpoint and verifies one parsed document with a positive chunk count.
6. Runs the same seven reviewed queries once for observed discovery at `top_k=3`.
7. Maps all nine reviewed evidence spans to observed stable chunk hashes. If mapping is
   not exactly 9 of 9, skips the second pass and enters cleanup.
8. Runs the same seven queries once for final validation using the reviewed observed
   qrels. It records aggregate metrics and two-pass repeatability without exposing query
   or chunk text publicly.
9. Executes one exact cleanup using the checkpoint-bound dataset identifier and name.
10. Proves identifier absence, bounded exact-name absence, and temporary-config absence.
11. Writes one private result and one sanitized summary, then stops before post-L3 review
    or L4.

The live ceiling is one dataset, one document, one parse, two passes of seven queries,
and one exact delete. Append, update, reparse, a replacement name, a second dataset,
automatic retry, and access to unrelated resource details are forbidden.

### Evidence Boundary

Private evidence retains command captures, checkpoint/manifest identity, raw retrieval
results needed for mapping, observed qrels, metrics, and cleanup proof. Public-safe output
may contain only aggregate counts, metrics, public source/runtime hashes, failure classes,
and cleanup status. It must not contain private endpoints, credentials, private paths,
resource names or identifiers, query text, raw chunks, or raw evidence spans.

### Post-L3 Boundary

An accepted lifecycle supplies FinanceBench evidence for a later maintainer comparison
with the pinned Open RAG checkpoint. That comparison is a separate read-only task. L3
does not itself close cross-subset conclusions, change defaults, or authorize L4.

## Compatibility And Migration

- `docs/42` remains the canonical historical record for the old attempt, recovery,
  forensic, and cleanup-policy outcome.
- This spec supersedes only `docs/42`'s prospective private-package and future live
  execution requirements.
- Historical request, contract, and review hashes remain provenance only and carry no
  authority into this design.
- Existing public CLI compatibility is preserved. If the current CLI cannot satisfy the
  minimal lifecycle without product changes, the attempt stops instead of expanding
  scope.
- Documentation governance and skill-surface simplification implementation remain paused
  until this L3 path reaches a terminal result or the owner formally closes it.

## Failure Handling And Rollback

- Before create: stop without mutation and return one blocker.
- After a confirmed create identity: cleanup is mandatory on every outcome and takes
  priority over evidence generation.
- After an ambiguous create with no exact identifier: do not retry, guess, or delete by
  name alone. Retain bounded read-only facts, delete the temporary config, and report
  `cleanup_risk` for owner action.
- A failed delete or either absence proof reports `cleanup_risk`; it never broadens
  deletion scope.
- Weak retrieval with a correct lifecycle is retained as `completed_with_quality_findings`
  rather than retried or hidden.
- No public or tracked file is used as a rollback store. Private state and the public CLI
  checkpoint provide recovery facts.

## Validation Strategy

Gate A validates:

- all required files exist, have expected ownership/mode/type, and match observed hashes;
- participating runtime files are unchanged from the approved commit;
- contract JSON parses and contains no unresolved placeholder;
- command arrays use public entrypoints, `shell=false`, no retry, and exact inputs;
- the cleanup command requires exact dataset identifier and name confirmation;
- a no-network dry run or synthetic fixture exercises orchestration and cleanup ordering;
- both independent reviews accept the same contract SHA with no open finding; and
- targeted sensitive-value scans return zero disclosure findings.

Gate B validates:

- operation counts remain within the contract;
- one dataset/document reaches parsed state with positive chunks;
- discovery and final passes each contain exactly seven queries in the same order;
- evidence mapping is exactly 9 of 9 before final validation;
- cleanup and both resource-absence checks pass;
- the temporary config is absent; and
- private and sanitized outputs pass their separate retention checks.

## Acceptance Criteria

This design is satisfied when exactly one of these terminal outcomes exists:

1. `ACCEPTED_L3`: Gate A and exact-SHA authorization passed; the one live lifecycle,
   evidence mapping, two-pass validation, cleanup, absence proofs, and redaction checks
   all passed.
2. `COMPLETED_WITH_QUALITY_FINDINGS`: the lifecycle and cleanup passed, while retrieval
   quality produced retained findings that require later review.
3. `FAIL_CLOSED`: no mutation occurred, or a post-create failure was followed by verified
   exact cleanup and config absence.
4. `CLEANUP_RISK`: exact cleanup or absence could not be proved; all forward work stopped
   and owner action is required.
5. `FORMAL_CLOSE_RECOMMENDED`: Gate A could not establish input/runtime/cleanup closure
   within the timebox and created no live authority.

In every outcome there is one sanitized result, no automatic successor batch, no Stage
8C or L4 action, and no modification of unrelated user work.

## Decision Log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-08-02 | Replace the missing Stage-B/Stage-C artifact path with NEW_MINIMAL_L3 | Missing bytes cannot be recovered from hashes, and rebuilding the temporary package would repeat low-value work. |
| 2026-08-02 | Reuse public commands and permit at most one private orchestration file | Preserve cleanup safety without creating another private subsystem. |
| 2026-08-02 | Timebox feasibility and contract work to three hours total | A field trial must not become another day of recursive preparation. |
| 2026-08-02 | Keep exact-SHA dual review only at the live contract boundary | This is the one point where review protects real mutation and cleanup authority. |
| 2026-08-02 | Treat unrelated documentation drift as inventory, not runtime drift | Preserve user work while still hash-binding every file that participates in execution. |

## Formal Closeout

On 2026-08-03 the owner accepted the Gate-A terminal result and formally closed
`NEW_MINIMAL_L3` as:

```text
NEW_MINIMAL_L3=FORMALLY_CLOSED
L3=NOT_COMPLETED_INPUTS_UNAVAILABLE
Gate_B=NOT_STARTED
```

The sanitized Gate-A result has SHA-256
`769f4dfb5a89bcfa9395180771ab9a16b4b2927d16fcb2b654f9ea82c4dd4ae9`.
Gate A found a formal-Markdown candidate whose bytes did not match the reviewed hash,
found zero of seven normalized queries, found no benchmark/qrels input, and found zero of
nine reviewed evidence spans. It stopped before completing the public-profile runtime
closure. The result created no run contract and performed zero credential-value reads,
live-config reads or materializations, RAGFlow calls, or dataset/document operations.

This is successful completion of the spec's bounded fail-closed workflow, not accepted L3
evidence. It creates no current FinanceBench L3 task, live authority, dataset, config, or
cleanup obligation. The missing observed evidence remains unavailable, Gate B must not be
started from this spec, and L4 remains unauthorized. Historical hashes cannot substitute
for the missing input bytes or reopen this workflow.
