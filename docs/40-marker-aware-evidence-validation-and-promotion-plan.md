# Marker-Aware Evidence Validation and Promotion Plan

Status: Hermes L0 and private offline L1 complete; Open RAG L2 read-only checkpoint
complete; FinanceBench L3 formally closed without observed evidence; L4 remains gated and
unauthorized
Date: 2026-07-11
Owning prior work:
`docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`

## 2026-08-03 FinanceBench L3 Formal Closeout

The bounded `NEW_MINIMAL_L3` feasibility gate stopped before contract creation or live
execution because the reviewed FinanceBench input bytes were incomplete. The owner
accepted `L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` and formally closed that workflow.

The unchecked observed-validation and promotion rows below remain open. They record an
evidence gap, not current execution authority: there is no active FinanceBench L3 task,
the cross-subset review cannot proceed without observed evidence, and L4 remains
unauthorized.

## Objective / Scope / Boundaries

This plan owns the evidence-validation sequence after the public offline marker-aware
candidate snapshot implementation. Its purpose is to make the ordinary RAGFlow knowledge
base workflow easier for non-expert users while preserving compatibility, privacy, and
live-operation gates.

The desired user experience remains:

```text
ordinary user provides a document or handoff
  -> deterministic inspection selects a safe boundary mode
  -> the user can accept the reviewed default path
  -> advanced users may override the mode for diagnosis or reproducibility
```

The implemented `auto` mode is the intended high-level automatic choice. The low-level
`snapshot-chunks` default remains `file` until a later evidence-based compatibility
decision explicitly changes it. No result from this plan may silently convert a failed
safety check into marker splitting.

This plan coordinates, but does not replace, the existing owners:

- `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md` owns the
  reviewed expected-chunk, two-subset regression, and metric-review rows;
- `docs/35-standard-benchmark-dataset-integration-plan.md` owns benchmark maturity and
  subset evidence requirements;
- `docs/15-field-trial-observation-plan.md` owns sanitized real-run evidence and trigger
  rules;
- `docs/36-ragflow-kb-parameter-materialization-plan.md` owns Stage 8C and remains
  blocked independently of this work.

In scope:

- independently replay the committed marker-aware candidate snapshot path with neutral
  repository fixtures;
- keep legacy `file`, explicit `markers`, automatic `auto`, and directory-level `mixed`
  behavior deterministic and reviewable;
- prove candidate snapshot hashes, source IDs, QA evidence mapping, JSON, Markdown, and
  redaction outputs through a repository-only Hermes L0 run;
- define separately approved gates for private candidate evidence, observed RAGFlow
  validation, disposable live validation, and any later default-promotion decision;
- maintain one checklist that distinguishes completed public offline behavior from
  residual private, read-only, live, and promotion work.

Out of scope for the original plan-writing and L0 authorization below. L1 and L2 were
later authorized separately as recorded in this document; neither authorization opened
L3 or L4:

- no Open RAG or FinanceBench private source access;
- no network access or RAGFlow HTTP call, including read-only calls;
- no RAGFlow dataset or KB creation, upload, parse, query, snapshot, delete, or cleanup;
- no MinerU, DeepDoc, native-PDF comparison, or private-source conversion;
- no script-owned LLM or RAGAS execution;
- no Stage 8C parameter materialization;
- no change from the low-level `file` default to `auto`;
- no executable Hermes instruction or Hermes run before this document is reviewed and
  approved;
- no raw content-bearing snapshots, private identifiers, private run roots, endpoints,
  credentials, or raw retrieved chunks in the public repository.

## Problem Description

### The implementation is newer than the existing independent replay

The public marker-aware implementation and hardening landed after the commit replayed by
`docs/39-benchmark-evidence-strengthening-hermes-test.md`. That replay independently
validated benchmark import, sampling, and portfolio behavior, but it did not validate the
later marker-aware snapshot and QA mapping chain.

Local tests and release gates provide strong implementation evidence, but they are not an
independent agent replay. A new repository-only Hermes pass is useful before private or
observed evidence is introduced because it can verify the complete public contract from a
clean committed checkout without relying on the implementation session's assumptions.

### Candidate evidence and observed evidence must remain distinct

Marker-derived chunks are deterministic offline candidates. They are not chunks observed
from a RAGFlow server. Stable expected-chunk hashes mapped from candidate snapshots can
strengthen qrels after manual review, but they cannot establish observed strict chunk
recall or close the Level 3 retrieval-quality regression baseline by themselves.

The evidence sequence therefore needs explicit authority boundaries. Passing a lower
level does not authorize, imply, or satisfy a higher level.

### Ease of use requires evidence, not an immediate default change

The long-term product direction is for normal users to rely on deterministic automatic
analysis instead of understanding marker syntax, stable hashes, or benchmark qrels. The
current compatible implementation supports that direction by allowing high-level callers
to select `auto` while preserving the low-level `file` default.

Changing a default too early could alter snapshot counts, hashes, reviews, and normalized
qrels for existing callers. Default promotion therefore remains a separate decision gate
that compares compatibility impact and representative observed evidence.

## Authorization Matrix

Each level requires its own reviewed instruction and explicit approval. Authority is not
inherited from a completed lower level.

| Level | Maximum authority | Required evidence | Explicit exclusions |
| --- | --- | --- | --- |
| L0 | Repository-only neutral fixtures and offline commands | Determinism, fail-closed behavior, report safety, zero-call counters, clean repository | No network, private data, RAGFlow, MinerU, DeepDoc, LLM, mutation, commit, or push |
| L1 | Separately approved private offline Open RAG and FinanceBench candidate snapshots | Content-bearing candidate snapshots, manual QA mapping review, stable hashes, reviewed normalized qrels | No RAGFlow HTTP, observed-chunk claim, live mutation, LLM/RAGAS, or public raw content |
| L2 | Separately approved read-only RAGFlow observed validation | Pinned per-subset observed chunks or retrieval reports, strict metrics, wrong-document and pollution evidence | No create, upload, parse, reparse, update, delete, cleanup, or default change |
| L3 | Separately approved disposable live build, query, and cleanup | Exact disposable scope, build/parse/query evidence, cleanup proof, sanitized retention | No persistent production mutation, unreviewed resources, or implicit reuse of prior approval |
| L4 | Evidence-based default-promotion decision | Compatibility comparison plus representative candidate and observed evidence | No automatic promotion, no safety-check override, and no default change without a separate design/update |

The completed Hermes replay documented in
`docs/41-marker-aware-candidate-snapshot-hermes-l0.md` had a maximum authority of L0. Its
contract required `approval_required` rather than proceeding whenever a higher-level
action appeared necessary.

L3 may be skipped only after a maintainer reviews the pinned, comparable L2 evidence and
records a written conclusion that it is sufficient for the intended comparison. L3
exists for cases where a controlled disposable lifecycle is still needed to produce or
reproduce that evidence. L4 is a decision gate, not authorization to run new live
operations.

## Update Plan

### Phase A - Freeze The L0 Contract

After this document is reviewed, create the separate copy-paste Hermes instruction at
`docs/41-marker-aware-candidate-snapshot-hermes-l0.md`. The instruction must pin the
tested repository commit, require clean initial and final worktree states, write
artifacts only outside the repository, and forbid repository modification. It must
explicitly prohibit changing `.gitignore` or any other repository file and prohibit
`git add`, `git commit`, and `git push`.

The L0 contract must independently verify:

- omitted mode and explicit `file` retain legacy one-file/one-chunk behavior;
- `markers` splits only canonical marker lines and fails closed on unsafe input;
- `auto` selects or falls back with stable ordered reason codes;
- a Markdown directory can report deterministic aggregate `mixed` behavior;
- both `.md` and `.markdown` inputs are supported;
- duplicate basenames remain distinct through stable document/source IDs;
- empty directories fail clearly without producing a misleading snapshot;
- nested, same-line, attributed, mixed-case, and self-closing HTML tables remain atomic;
- long or mismatched fence sequences keep marker and table literals masked correctly;
- unbalanced HTML tables fail in `markers` and fall back in `auto`;
- repeated snapshots reproduce ordered content, source IDs, stable hashes, and boundary
  decisions;
- `qa map-evidence` maps neutral grounded spans from the exact committed synthetic
  fixture specification in the L0 instruction to `sha256:` expected chunks;
- JSON, Markdown, and redaction sidecars describe candidate/offline, non-observed scope;
- `ragflow_calls=0`, `writes_live_ragflow=false`, and
  `script_owned_llm_calls=0` remain true;
- generated tool reports and agent-authored prose are scanned separately and contain no
  unresolved private path, endpoint, credential, private identifier, or raw-content
  leakage;
- the final commit and worktree match the initial state.

The L0 report must not restate private handoff paths or use private sources as fixtures.
It should retain only a public-safe run label and report basenames.

### Phase B - Review The Independent L0 Result

Maintainer review must compare the Hermes report with the committed contract rather than
accepting a pass label alone. Review includes:

- exact commit and initial/final repository state;
- executed commands and skipped actions;
- expected mode decisions, reason codes, counts, hashes, and source IDs;
- zero-call and non-mutation counters;
- separate sensitive scans for generated reports and agent prose;
- any unexpected warning, fallback, nondeterminism, or repository write.

An L0 pass closes only the independent repository replay row in this document. It does
not close any open row in `docs/38`.

### Phase C - Run The Private Offline Candidate Gate Only After Approval

L1 requires a new instruction that names the approved private Open RAG and FinanceBench
scope. Content-bearing snapshots and evidence mapping outputs remain outside version
control.

The L1 review must:

- generate candidate snapshots with `--markdown-boundary-mode auto`;
- record requested and effective modes and fallback reasons per document;
- reproduce stable hashes across repeated runs;
- run `qa map-evidence` against grounded evidence spans;
- manually review mapped spans, aliases, hashes, and table integrity;
- update normalized qrels only after explicit evidence review;
- rerun import, preflight, and portfolio reports after approved qrels changes;
- publish only sanitized aggregate metrics and artifact basenames.

L1 can close the reviewed expected-chunk row in `docs/38` only when both subsets meet the
owning plan's review standard. It still cannot claim observed RAGFlow behavior.

### Phase D - Collect Observed Evidence Only Through Separate Gates

L2 should use pinned, read-only RAGFlow evidence when an existing suitable KB and explicit
authorization are available. It must keep candidate and observed identities separate and
review zero-result, wrong-document, pollution, strict chunk recall, expected-term,
table-term, and citation-support evidence per subset.

L3 may be opened only when observed evidence requires a controlled disposable build. Its
instruction must define the exact source subset, disposable naming, mutation scope,
queries, stop conditions, cleanup confirmations, post-cleanup proof, and sanitized
retention. Any cleanup uncertainty blocks acceptance.

Neither L2 nor L3 may infer Stage 8C eligibility or change a default automatically.

### Phase E - Make A Separate Promotion Decision

L4 evaluates two different promotion questions:

1. Should the high-level ordinary workflow select `auto` by default while the low-level
   command remains compatible?
2. Is there enough compatibility and observed evidence to propose changing the low-level
   command default from `file` to `auto`?

The first decision has a lower compatibility blast radius and is the preferred product
direction when evidence is sufficient. The second requires retained snapshot count/hash
comparisons, multi-sample table safety, qrels migration analysis, public guidance updates,
and a separate design before implementation.

Any promotion must preserve expert overrides, deterministic reports, and fail-closed
safety checks. An AI may explain or select among verified modes, but it must not override
an `auto` fallback or invent a successful marker decision.

## Task Checklist

### Plan And L0 Preparation

- [x] Verify the committed clean baseline and identify that the existing Hermes replay
  predates marker-aware snapshot behavior.
- [x] Create this owning validation and promotion plan with explicit L0-L4 authority
  boundaries.
- [x] Obtain user review and approval of this written plan.
- [x] Create `docs/41-marker-aware-candidate-snapshot-hermes-l0.md` as a separate
  L0-only Hermes instruction after plan approval.
- [x] Self-review the instruction for placeholders, private references, ambiguous
  authority, and accidental network or mutation steps.

### L0 Independent Repository Replay

- [x] Run the approved Hermes L0 instruction from the current committed clean checkout.
- [x] Verify legacy `file`, deterministic `markers`/`auto`/`mixed`, Markdown extension,
  duplicate-basename, empty-directory, table, fence, and unbalanced-input cases.
- [x] Verify repeated snapshot identity and neutral `qa map-evidence` stable-hash output.
- [x] Verify JSON, Markdown, redaction, zero-call, non-mutation, and sensitive-scan
  evidence.
- [x] Confirm the final repository state and commit match the initial state.
- [x] Review the Hermes result independently and record only sanitized evidence here.

### L1 Private Offline Candidate Evidence

- [x] Obtain separate authorization naming the private Open RAG and FinanceBench source
  and artifact scope.
- [x] Generate repeatable private candidate snapshots and review automatic boundary
  decisions and table integrity.
- [x] Map grounded QA evidence and manually approve aliases and stable hashes.
- [x] Approve normalized qrels changes, then rerun import, preflight, and portfolio
  reports.
- [x] Close the `docs/38` reviewed expected-chunk row only after both subset reviews and
  public-safe evidence are complete.

### L2/L3 Observed Validation

- [x] Obtain separate L2 authorization for pinned read-only RAGFlow observed evidence.
- [ ] Review per-subset strict retrieval, wrong-document, pollution, term, table, and
  citation-support metrics without mutation.
- [ ] Open L3 only if a disposable live lifecycle is necessary and separately approved.
- [ ] When L3 is used, verify exact cleanup and post-cleanup absence before accepting the
  evidence.
- [ ] Close the true two-subset observed regression and metric-review rows in `docs/38`
  only when their owning acceptance criteria are met.

### L4 Promotion Decision

- [ ] Compare candidate and observed behavior across more than one representative sample.
- [ ] Review retained legacy snapshot counts, hashes, warnings, and downstream qrels for
  compatibility impact.
- [ ] Decide first whether the high-level workflow should select `auto` by default.
- [ ] Consider a low-level default change only through a separate approved design and
  implementation plan.
- [ ] Keep `file` as the low-level default until that separate decision is implemented
  and fully release-validated.

## Current Development Progress

Baseline recorded on 2026-07-11:

- repository branch `develop` was clean and matched its tracked remote at commit
  `22d4524` before this plan was created;
- the public marker-aware implementation is complete for offline scope: compatible
  `file`, fail-closed `markers`, deterministic per-document `auto`, aggregate `mixed`,
  table atomicity, fence masking, stable source IDs/hashes, and neutral QA mapping are
  covered by current tests and release validation;
- `docs/39-benchmark-evidence-strengthening-hermes-test.md` replayed commit `3b94d93`, so
  it is valid evidence for the earlier benchmark portfolio chain but not for the later
  marker-aware end-to-end chain;
- `docs/41-marker-aware-candidate-snapshot-hermes-l0.md` now provides the reviewed,
  repository-only instruction with exact neutral fixtures, focused tests, public CLI
  replay, negative cases, deterministic assertions, separate tool/prose sensitive scans,
  and final clean-worktree proof;
- Hermes independently replayed L0 against commit `fb38de2`: 16 focused governance tests
  with 5 subtests and 4 focused CLI tests passed; omitted/default and explicit `file`
  matched at one chunk and the same stable hash; forced `markers` produced three chunks;
  directory `auto` produced deterministic `mixed` mode across three documents; all four
  negative cases returned code 2 with the expected failure classes;
- the repeated directory snapshots matched on ordered content, stable hashes, source
  IDs, and boundary decisions. Neutral QA mapping covered 2 of 2 spans and produced only
  `sha256:` expected chunks;
- maintainer review reran the committed semantic verification block, inspected the
  negative outputs, key snapshot and QA artifacts, redaction sidecars, and separate tool
  and agent-prose scan logs. Path/endpoint and raw-content scans had no matches;
  credential and identifier matches were limited to zero counters, schema/coverage
  labels, redaction JSON paths, and sanitized config-path values, with zero unresolved
  sensitive findings;
- Hermes recorded identical initial and final commit `fb38de2`, an empty porcelain
  status, zero RAGFlow/LLM calls, no live writes, and no repository modification. The
  retained public-safe run label is
  `ragflow-marker-aware-hermes-l0-20260711T103549Z`;
- L1 was separately authorized for the retained private Open RAG and FinanceBench source
  and artifact scope. The original ephemeral evidence root was unavailable, so the run
  used retained local source/artifact copies and prior reviewed local records without
  reacquisition or a conversion-backend call;
- repeated `auto` snapshots were semantically identical. Open RAG produced 17 candidate
  chunks from 16 markers with no duplicate hash; FinanceBench produced 492 candidate
  chunks from 491 markers and retained 487 unique hashes after five repeated-heading
  duplicates were skipped;
- exact structural review confirmed all 9 Open RAG and 110 FinanceBench HTML tables were
  balanced, unfragmented, and contained by exactly one emitted chunk. The generic
  adjacent-table heuristic remained advisory for these multi-table documents;
- Open RAG mapped 16 of 16 grounded spans and FinanceBench mapped 9 of 9 reviewed formal-
  handoff spans. Every span matched one chunk, every match retained a marker ordinal
  alias and a `sha256:` stable hash, and each subset mapped to five unique hashes;
- all 10 Open RAG and 7 FinanceBench qrels now carry reviewed candidate-only
  `expected_chunks`. Import and preflight passed with full expected-term, grounded-QA,
  and expected-chunk query coverage; the refreshed portfolio contains 17 judged queries,
  35 document/chunk qrels, and 8 table/numeric queries;
- the portfolio remains `ready_with_review` solely because observed validation is absent.
  No network, RAGFlow, MinerU/DeepDoc, LLM/RAGAS, Stage 8C, or default-changing action
  occurred during L1;
- L2 was separately authorized for read-only RAGFlow observation. The compatibility probe
  passed, and exact discovery reviewed 186 existing datasets and 11,339 observed documents
  without mutation. Four existing Open RAG document matches were found; no exactly
  pinnable FinanceBench document was present;
- two equivalent Open RAG baseline KBs produced identical 24-chunk stable-hash sets and
  identical metrics. All 16 reviewed grounded spans mapped to five observed chunks;
  hit rate, expected chunk hit rate, expected-term recall, and table-term recall were 1.0,
  zero-result and wrong-document rates were 0, and strict chunk recall at 3 was 0.95;
- the L2 metric review exposed two public defects and closed them with focused tests:
  duplicate chunks from one document target no longer inflate precision/nDCG, and
  validation plus public-safe retention reports now record actual read-only RAGFlow call
  counts with `writes_live_ragflow=false`;
- independent merge review added a third fail-before-network hardening fix: qrels, gate,
  baseline, chunk-snapshot, and observed-state inputs are validated before retrieval;
- L2 made 280 RAGFlow calls: 220 GET calls and 60 read-only retrieval POST calls. It made
  zero create, upload, parse, reparse, update, delete, cleanup, MinerU, DeepDoc, LLM/RAGAS,
  Stage 8C, or default-changing calls/actions;
- FinanceBench observed validation remains absent because no suitable existing KB was
  available. This activates the documented `l3_required` stop condition but does not
  authorize L3;
- two `docs/38` rows remain open: a true two-subset observed retrieval-quality baseline
  and complete metric review before guidance changes;
- the low-level default remains `file`; high-level callers may explicitly use the
  implemented `auto` mode, but no new default decision has been made.

## Validation Evidence / Residual Gated Work

Required validation for docs-only maintenance of this plan:

```bash
git diff --check
python3 tools/release_hygiene_check.py
```

The changed document must also be scanned for private paths, endpoints, credential-like
values, dataset or document identifiers, KB identifiers, and raw evidence. Every match
must be reviewed manually rather than treated as automatically safe or unsafe.

Residual work remains classified as follows:

- completed public offline work: marker-aware implementation, local instruction
  calibration, and independent Hermes L0 replay;
- completed private offline work: Open RAG and FinanceBench candidate snapshots, QA
  mapping review, stable-hash approval, normalized qrels, and portfolio replay under L1;
- completed read-only live work: pinned Open RAG observed validation under L2;
- formally closed evidence gap: FinanceBench observed evidence remains unavailable, with
  no current L3 live-mutation workstream;
- unavailable decision work: high-level and possible low-level automatic-default
  promotion under L4 remains gated on representative observed evidence;
- separately blocked work: DeepDoc/native comparison, script-owned LLM/RAGAS, Stage 8C,
  private adapters, and unrelated post-CLI surfaces.

## L0 Closeout / Retrospective

L0 closed on 2026-07-11 after independent replay and maintainer artifact review:

- the repository-only marker-aware path is reproducible from a clean committed checkout;
- legacy/default compatibility, deterministic automatic selection, table/fence safety,
  duplicate-basename isolation, failure paths, report safety, and neutral QA mapping all
  met the L0 contract;
- the replay made no network, private-source, RAGFlow, MinerU, DeepDoc, LLM/RAGAS,
  Stage 8C, default, repository, commit, or push change;
- no `docs/38` row closes from L0 because reviewed private expected chunks and observed
  retrieval evidence remain absent;
- at L0 closeout the next actionable gate was L1. That gate was later separately
  authorized and completed without changing the L0 result or inheriting L2 authority.

## L1 Closeout / Retrospective

L1 closed on 2026-07-11 after private artifact reconstruction, repeated candidate
generation, exact evidence review, qrels approval, and portfolio replay:

- both documents selected `markers` under `auto`, repeated snapshots and evidence-map
  templates were semantically identical, and all zero-call/non-mutation fields remained
  explicit;
- FinanceBench source evidence used plain-text tables while the formal handoff used HTML.
  The original normalized QA remained unchanged; a private candidate-map QA copy bound
  reviewed evidence to exact formal-Markdown paragraphs or complete HTML tables;
- five duplicate FinanceBench candidates were repeated short headings, not tables or
  mapped evidence, so stable-hash deduplication did not remove a reviewed target;
- report redaction sidecars were successful, the public-safe portfolio had zero findings,
  and no content-bearing artifact or private execution path was added to the repository;
- L1 closes only candidate expected-chunk evidence. It does not establish observed strict
  chunk recall, authorize RAGFlow HTTP, open a disposable lifecycle, or support a default
  change.

## L2 Partial Closeout / Retrospective

L2 completed the maximum evidence available without mutation:

- existing Open RAG data was suitable and reproducible across two equivalent baseline
  KBs;
- candidate and observed identities remained separate, and observed qrels were derived
  only after exact grounded evidence mapped to server-observed stable hashes;
- the retrieval-evidence citation-support proxy was 1.0 because every query retrieved at
  least one mapped grounded-evidence chunk; no answer-level citation audit was claimed;
- tag-pollution evidence was unavailable for the single-document, no-tag-qrel subset, so
  no broad pollution conclusion was inferred from a zero wrong-document rate;
- FinanceBench could not be completed under L2 because no existing dataset matched the
  reviewed source identity. The two-subset baseline and guidance review remain open;
- all public-safe review artifacts passed separate endpoint, credential, private path,
  identifier, raw-query, and raw-chunk scans with zero matches.
- final branch verification passed 723 runtime tests with 38 subtests, 109 of 109 schema
  identity checks, 3 manifest schema checks, release hygiene with zero findings, release
  build/export for all three archives, 264 of 264 consumer-acceptance checks, and 154 of
  154 strict-vendor smoke checks.

`NEW_MINIMAL_L3` is formally closed and has no automatic successor. The missing
FinanceBench observed evidence leaves the two-subset and promotion reviews unavailable;
neither another L3 lifecycle nor an L4 decision is a current action under this plan.
