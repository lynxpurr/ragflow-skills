# Marker-Aware Evidence Validation And Promotion Plan

Status: approved plan; Hermes L0 instruction documented, independent execution pending
Date: 2026-07-11
Owning prior work:
`docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`

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

Out of scope for the current approved slice:

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

The next Hermes run has a maximum authority of L0. It must return
`approval_required` rather than proceeding if any higher-level action appears necessary.

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

- [ ] Run the approved Hermes L0 instruction from the current committed clean checkout.
- [ ] Verify legacy `file`, deterministic `markers`/`auto`/`mixed`, Markdown extension,
  duplicate-basename, empty-directory, table, fence, and unbalanced-input cases.
- [ ] Verify repeated snapshot identity and neutral `qa map-evidence` stable-hash output.
- [ ] Verify JSON, Markdown, redaction, zero-call, non-mutation, and sensitive-scan
  evidence.
- [ ] Confirm the final repository state and commit match the initial state.
- [ ] Review the Hermes result independently and record only sanitized evidence here.

### L1 Private Offline Candidate Evidence

- [ ] Obtain separate authorization naming the private Open RAG and FinanceBench source
  and artifact scope.
- [ ] Generate repeatable private candidate snapshots and review automatic boundary
  decisions and table integrity.
- [ ] Map grounded QA evidence and manually approve aliases and stable hashes.
- [ ] Approve normalized qrels changes, then rerun import, preflight, and portfolio
  reports.
- [ ] Close the `docs/38` reviewed expected-chunk row only after both subset reviews and
  public-safe evidence are complete.

### L2/L3 Observed Validation

- [ ] Obtain separate L2 authorization for pinned read-only RAGFlow observed evidence.
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
  and final clean-worktree proof. Local command calibration passed, but the independent
  Hermes run has not started;
- no private source, network service, RAGFlow endpoint, MinerU backend, DeepDoc path,
  LLM/RAGAS backend, or Stage 8C action has been accessed or authorized by this plan;
- the three open `docs/38` rows remain open: reviewed expected chunks, a true two-subset
  observed retrieval-quality baseline, and complete metric review before guidance
  changes;
- the low-level default remains `file`; high-level callers may explicitly use the
  implemented `auto` mode, but no new default decision has been made.

## Validation Evidence / Residual Gated Work

Required validation for this docs-only planning slice:

```bash
git diff --check
python3 tools/release_hygiene_check.py
```

The changed document must also be scanned for private paths, endpoints, credential-like
values, dataset or document identifiers, KB identifiers, and raw evidence. Every match
must be reviewed manually rather than treated as automatically safe or unsafe.

Residual work remains classified as follows:

- ordinary public offline work: author and run the separately reviewed Hermes L0 replay;
- private offline work: Open RAG and FinanceBench candidate snapshots, QA mapping review,
  and normalized qrels approval under L1;
- read-only live work: pinned observed RAGFlow validation under L2;
- live mutation work: disposable build/query/cleanup only under L3;
- decision work: high-level and possible low-level automatic-default promotion under L4;
- separately blocked work: DeepDoc/native comparison, script-owned LLM/RAGAS, Stage 8C,
  private adapters, and unrelated post-CLI surfaces.

No closeout or retrospective is recorded yet. Add it only after the approved execution
level is complete and verified, while leaving all higher levels explicitly gated.
