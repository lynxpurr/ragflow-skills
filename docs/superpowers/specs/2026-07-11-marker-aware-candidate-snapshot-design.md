# Marker-Aware Candidate Snapshot And Automatic Selection Design

Status: proposed for user review
Date: 2026-07-11
Owning roadmap row: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`

## Objective

Make the knowledge-base workflow easier for non-expert users without weakening the
existing benchmark, privacy, compatibility, or live-mutation gates.

This round builds a deterministic offline foundation that can recognize canonical
Markdown chunk markers, preserve complete HTML tables, create reproducible candidate
chunk snapshots, and explain whether marker-aware splitting is safe. The long-term
user-facing workflow should select a safe mode automatically; users should not need to
understand chunk markers, stable hashes, or benchmark qrels.

The result remains candidate/offline evidence. It is not a RAGFlow server-observed chunk
snapshot and cannot by itself close the Level 3 retrieval regression baseline.

## Current Evidence

The current `snapshot-chunks` Markdown reader returns one `NormalizedChunk` per Markdown
file. A repository-neutral rehearsal against a marker-bearing Markdown file produced one
chunk and one visible-delimiter warning. This confirms that running the command directly
on a dense-marker handoff cannot produce useful expected-chunk evidence today.

The private benchmark sources and generated handoff named by the prior session handoff
are not available in the current session. This round can implement and verify public
offline behavior with neutral fixtures, but it cannot add reviewed private
`expected_chunks` or close the owning roadmap row without the separately retained source
evidence.

## User Experience Goal

The eventual ordinary workflow is:

```text
input document
  -> deterministic source/handoff inspection
  -> automatic boundary-mode decision
  -> conversion and offline quality checks
  -> candidate snapshot and evidence review when requested
  -> live KB creation only through its existing explicit approval gate
```

Normal users should use the high-level workflow with automatic analysis. Advanced users
and maintainers may override the boundary decision for reproducibility or diagnosis.

The low-level command contract will expose:

```text
--markdown-boundary-mode file
--markdown-boundary-mode markers
--markdown-boundary-mode auto
```

For this round, the low-level default remains `file` so existing scripts retain the
current one-file/one-chunk behavior. The high-level workflow may explicitly select
`auto` after it is implemented and verified. Promoting `auto` to the low-level default
is a later compatibility decision, not part of this round.

## Alternatives Considered

### Keep the feature private and prepare candidate JSON manually

This avoids a public runtime change, but it duplicates chunk-boundary logic outside the
tested runtime, cannot be exercised against the missing private handoff in this session,
and does not improve the normal user experience.

### Change the existing default immediately

Making every Markdown snapshot marker-aware would be simple for new users, but it could
silently change existing snapshot counts, hashes, reviews, and downstream qrels. Current
evidence is offline and candidate-only, so an immediate default change is premature.

### Add a compatible deterministic engine, then promote automatic selection

This is the selected approach. First add an explicit, tested marker-aware engine and an
`auto` decision mode while preserving the old default. Then use private reviewed evidence
and release gates to decide whether the high-level workflow, and eventually the low-level
command, should default to `auto`.

## Scope Of This Development Round

### In scope

- Reproduce the current one-file/one-chunk behavior in a focused automated test.
- Add a small marker-aware Markdown splitter in the existing benchmark-governance
  runtime rather than creating a separate private parser.
- Recognize only canonical delimiter lines matching `<!-- chunk -->` with optional
  surrounding horizontal whitespace.
- Preserve source-file ordering and in-document chunk ordering deterministically.
- Preserve document provenance on every derived chunk.
- Preserve complete HTML `<table>...</table>` blocks as one atomic unit.
- Suppress delimiter boundaries encountered inside a complete HTML table and record the
  suppression count.
- Fail closed in forced `markers` mode when HTML table structure is unbalanced.
- Fall back to `file` mode in `auto` mode when table structure is unbalanced or marker
  evidence is insufficient.
- Reuse the existing `sha256:normalized-content-v1` stable content hash contract.
- Add deterministic derived chunk IDs for diagnostics while treating stable content
  hashes as the portable expected-chunk identity.
- Add additive candidate/offline boundary-decision fields to the existing snapshot and
  report surfaces.
- Add CLI help, focused runtime/CLI tests, public guidance, inventory review, schema
  identity review, generated-report safety review, and release validation.
- Produce a neutral, content-bearing synthetic snapshot and run `qa map-evidence` against
  it to prove the offline mapping path end to end.

### Explicitly out of scope

- Any RAGFlow HTTP call, read-only query, KB creation, upload, parse, snapshot, or cleanup.
- Treating marker-derived candidate chunks as server-observed RAGFlow chunks.
- DeepDoc or native-PDF comparison.
- Script-owned LLM or RAGAS execution.
- Stage 8C parameter materialization.
- Downloading, reconstructing, or committing private benchmark sources.
- Adding private content, raw evidence spans, private paths, endpoints, credentials,
  dataset IDs, document IDs, KB names, or task IDs to public artifacts.
- Changing the low-level default from `file` to `auto`.
- Closing the reviewed expected-chunk roadmap row without restored private evidence,
  manual review, normalized qrels approval, and refreshed portfolio evidence.

## Boundary Algorithm

The runtime reads Markdown files in sorted path order. For each file it processes lines
in source order while tracking HTML table depth case-insensitively.

A canonical delimiter is a line whose trimmed content is exactly:

```html
<!-- chunk -->
```

The splitter applies these rules:

1. A delimiter outside an HTML table ends the current candidate chunk.
2. The delimiter line itself is not included in output content.
3. Leading, trailing, or adjacent delimiters do not create empty chunks.
4. A delimiter inside a complete HTML table is removed but does not split the table; the
   report increments `suppressed_table_boundary_count`.
5. A table opening and closing on the same line remains atomic.
6. Nested or repeated table tags are handled through a depth counter.
7. Unbalanced table depth is an error in `markers` mode and a documented fallback reason
   in `auto` mode.
8. Markdown pipe tables are not given new atomicity semantics in this round; only HTML
   table atomicity is required by the owning handoff.

Line endings are normalized by Python text reading, but other content is retained. Stable
hashes continue to use the existing whitespace-normalized content-hash function, so the
portable identity does not depend on a temporary filesystem root.

## Boundary Modes And Automatic Decision

### `file`

Preserve current behavior: one Markdown file becomes one `NormalizedChunk`. Marker
visibility remains available as a review warning.

### `markers`

Require marker-aware splitting. The command fails closed if no canonical marker exists,
no non-empty candidate chunk can be produced, or HTML table structure is unbalanced.

### `auto`

Select `markers` only when all of the following are true:

- at least one canonical marker exists;
- splitting produces at least two non-empty candidate chunks;
- HTML table structure is balanced;
- no complete HTML table is fragmented;
- every produced chunk has non-empty content after whitespace normalization.

Otherwise select `file` and emit a stable reason code. Initial reason codes are:

- `canonical_markers_available`;
- `no_canonical_markers`;
- `insufficient_nonempty_chunks`;
- `unbalanced_html_table`;
- `empty_candidate_chunk`.

Automatic selection is deterministic and does not invoke an LLM. A host AI may explain
the resulting decision report, but it must not silently override a failed safety check.

## Provenance And Snapshot Contract

Every marker-derived `NormalizedChunk` retains:

- `document_name`: source Markdown basename;
- `document_id`: the existing source-file identifier used by the Markdown reader;
- `chunk_id`: deterministic document-local ordinal such as `marker-0001`;
- `content`: the complete candidate chunk text.

The existing snapshot writer continues to derive:

- stable content hash;
- raw SHA-256 content digest;
- aliases containing the stable hash and diagnostic chunk ID;
- deterministic snapshot order;
- content preview and optional full content.

Additive report fields should include:

- requested boundary mode;
- effective boundary mode;
- candidate/offline evidence scope;
- `observed_ragflow_chunks=false`;
- source marker count;
- emitted candidate chunk count;
- suppressed table-boundary count;
- fallback reason when applicable;
- zero RAGFlow calls, zero live writes, and zero script-owned LLM calls.

The existing schema identities remain unchanged unless implementation review proves an
additive field cannot safely express the contract. Any schema change requires the full
public report-surface checklist before completion.

## Error Handling

- Non-Markdown JSON and validation-report inputs reject `markers` and `auto` with a clear
  input-mode error rather than silently ignoring the option.
- Forced `markers` mode reports a non-zero result for missing canonical markers,
  unbalanced table tags, or an empty output set.
- `auto` mode falls back only for documented deterministic reasons and records both the
  requested and effective mode.
- Filesystem errors continue through the current `BenchmarkGovernanceError` boundary.
- Duplicate stable hashes continue to use the existing duplicate-skip semantics and
  runtime partial-failure report.
- Content-bearing snapshots remain private by operator policy; public reports retain
  counts, hashes approved for publication, reason codes, and safety flags only.

## Test Strategy

Implementation must use test-driven development. Required focused coverage:

- legacy Markdown remains one chunk when mode is omitted or `file`;
- canonical markers produce deterministic chunks in `markers` mode;
- leading, trailing, and adjacent markers do not create empty chunks;
- marker-like text that is not a canonical delimiter line is preserved as content;
- markers inside HTML tables do not fragment the table;
- same-line and multiline HTML tables remain atomic;
- unbalanced HTML tables fail in `markers` and fall back in `auto`;
- directory traversal and in-document ordering are stable;
- repeated runs produce identical semantic chunks and stable hashes;
- document names, document IDs, and derived chunk IDs are preserved;
- `auto` reason codes are deterministic;
- JSON inputs reject Markdown-only modes;
- CLI help, return codes, JSON report, Markdown report, and redaction sidecar are covered;
- a synthetic grounded-QA span maps to the expected stable hash through
  `qa map-evidence`;
- public reports state candidate/offline scope and never claim observed RAGFlow chunks;
- no test fixture contains a real endpoint, credential, private source, or raw user data.

## Task Checklist

### A. Baseline And Contract

- [ ] Add a failing focused test that proves current marker-bearing Markdown produces one
  chunk under legacy/default behavior.
- [ ] Add tests for the new mode argument, invalid input combinations, and additive
  decision metadata before changing runtime code.
- [ ] Confirm the existing snapshot schema can carry the additive fields; if not, stop
  and update the design before introducing a new schema identity.

### B. Marker-Aware Runtime

- [ ] Add the canonical delimiter recognizer and table-depth scanner.
- [ ] Add deterministic marker splitting with empty-segment suppression.
- [ ] Add table-boundary suppression and unbalanced-table failure behavior.
- [ ] Preserve document provenance, deterministic ordinals, ordering, and stable hashes.
- [ ] Keep JSON/validation inputs and legacy Markdown behavior unchanged.

### C. Automatic Selection

- [ ] Add `file`, `markers`, and `auto` runtime modes with `file` as the compatible
  low-level default.
- [ ] Add deterministic selection and fallback reason codes.
- [ ] Add candidate/offline, non-observed, and zero-call safety metadata.
- [ ] Verify a host AI can explain the decision entirely from the public-safe report,
  without raw chunk content or an LLM call inside the script.

### D. CLI And Public Guidance

- [ ] Add `--markdown-boundary-mode` to `snapshot-chunks` with concise help.
- [ ] Document `auto` as the intended high-level workflow choice and the other modes as
  expert overrides.
- [ ] Preserve all existing commands and examples when the option is omitted.
- [ ] Review schema identity, report-surface inventory, generated Markdown audit, runtime
  resilience inventory, consumer acceptance, and platform smoke impact.

### E. Offline Evidence Proof

- [ ] Create neutral synthetic Markdown with canonical markers, narrative text, and a
  complete HTML table.
- [ ] Generate a content-bearing candidate snapshot outside committed artifacts.
- [ ] Run `qa map-evidence` and verify that grounded spans map to stable hashes with full
  synthetic coverage.
- [ ] Re-run snapshot generation and confirm identical semantic chunks and hashes.
- [ ] Record sanitized counts, reason codes, and safety flags only.

### F. Validation And Documentation

- [ ] Run focused runtime and CLI tests.
- [ ] Run the complete runtime suite when code changes.
- [ ] Run `git diff --check`.
- [ ] Run schema identity and release hygiene with zero findings.
- [ ] Run consumer acceptance and strict-vendor platform smoke if public CLI/report
  inventory changes require them.
- [ ] Update this document and the owning roadmap row only after implementation and
  verification are complete.

### G. Separately Gated Evidence Follow-Up

- [ ] Restore or reacquire approved private benchmark sources only under a separate
  instruction that defines the allowed private-source scope.
- [ ] Generate private content-bearing Open RAG and FinanceBench candidate snapshots.
- [ ] Run and manually review grounded-QA evidence mappings.
- [ ] Add reviewed `expected_chunks` to normalized qrels only after stable hashes and
  evidence spans are approved.
- [ ] Re-run import, preflight, and portfolio reports.
- [ ] Keep the result candidate/offline and leave observed validation, the two-subset
  regression baseline, and guidance changes open.

### H. Later Default-Promotion Gate

- [ ] Review backward-compatibility impact using retained snapshot counts and hashes.
- [ ] Confirm table safety and mapping quality across more than one representative sample.
- [ ] Decide whether only the high-level workflow or also the low-level command should
  default to `auto`.
- [ ] Require a separate design/update before changing any existing default.

## Completion Criteria For This Round

This implementation round is complete when:

1. Legacy/default behavior remains unchanged.
2. Explicit marker mode is deterministic, table-safe, provenance-preserving, and
   reproducible.
3. Automatic mode chooses or falls back with stable, reviewable reasons.
4. Candidate snapshots are clearly labeled offline and non-observed.
5. Synthetic grounded-QA evidence maps to reviewed stable hashes.
6. Focused tests, the full runtime suite, diff checks, schema/report governance, release
   hygiene, and applicable consumer/platform checks pass.
7. No live RAGFlow, DeepDoc, LLM/RAGAS, Stage 8C, private-source acquisition, or public
   raw-content retention occurs.

The owning expected-chunk roadmap row remains open until the separately gated private
evidence follow-up is restored, reviewed, and its normalized qrels changes are approved.
