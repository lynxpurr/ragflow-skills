# Marker-Aware Candidate Snapshot And Automatic Selection Design

Status: reviewed with amendments; awaiting final user approval
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
- Preserve complete HTML `<table>...</table>` blocks as one atomic unit by reusing or
  narrowly extending the repository's existing `html_tables.py` parser rather than
  adding an independent regex-only HTML parser.
- Suppress delimiter boundaries encountered inside a complete HTML table and record the
  suppression count.
- Fail closed in forced `markers` mode when HTML table structure is unbalanced.
- Fall back to `file` mode in `auto` mode when table structure is unbalanced or marker
  evidence is insufficient.
- Reuse the existing `sha256:normalized-content-v1` stable content hash contract.
- Add deterministic derived source-chunk IDs for diagnostics while treating stable
  content hashes as the portable expected-chunk identity. Do not reuse the RAGFlow-facing
  `chunk_id` field for an offline marker ordinal.
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

The runtime reads Markdown files in sorted path order and processes lines in source
order. HTML table ranges and balance must reuse or narrowly extend the existing
`ragflow_skill_runtime.html_tables` parser, which is based on Python's `HTMLParser` and
masks fenced code blocks before parsing. This avoids creating a second, less capable
HTML interpretation path for quoted attributes, mixed-case tags, same-line tags, and
self-closing tags. The current parser finalizes still-open tables at end of input, so the
narrow extension must expose unclosed-table state explicitly; callers must not infer
balanced structure merely because `parse_html_tables()` returned an artifact.

A canonical delimiter is a line whose trimmed content is exactly:

```html
<!-- chunk -->
```

The splitter applies these rules:

1. A delimiter outside an HTML table ends the current candidate chunk.
2. The delimiter line itself is not included in output content.
3. Leading, trailing, or adjacent delimiters do not create empty chunks.
   Empty means the segment has no content after the existing whitespace normalization
   used by stable chunk hashing.
4. A delimiter line inside a fenced code block is literal content, not a boundary; it is
   retained and counted as `ignored_fenced_marker_count`.
5. A delimiter inside a complete HTML table is removed but does not split the table; the
   report increments `suppressed_table_boundary_count`.
6. A table opening and closing on the same line remains atomic.
7. Nested, repeated, mixed-case, attributed, and self-closing table tags use the existing
   HTML parser semantics rather than manual line regex counting.
8. Fenced code blocks do not contribute HTML table ranges. Inline-code masking is not
   added in this round; a literal table tag in inline code may conservatively make the
   structure unsafe and cause forced mode to fail or automatic mode to fall back.
9. Unbalanced table structure is an error in `markers` mode and a documented fallback
   reason in `auto` mode.
10. Markdown pipe tables are not given new atomicity semantics in this round; only HTML
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
For a Markdown directory, every document must satisfy these requirements; one unsafe
document fails the forced operation rather than silently mixing modes.

### `auto`

Select `markers` only when all of the following are true:

- at least one canonical marker exists;
- splitting produces at least two non-empty candidate chunks;
- HTML table structure is balanced;
- no complete HTML table is fragmented;
- every produced chunk has non-empty content after whitespace normalization.

Otherwise select `file` and emit a stable reason code. Initial reason codes are:

- successful selection code: `markers_selected`;
- ordered fallback codes:
  1. `unbalanced_html_table`;
  2. `table_atomicity_violation`;
  3. `no_canonical_markers`;
  4. `insufficient_nonempty_chunks`.

The decision report also contains ordered checks rather than overloading the primary
reason code:

- `canonical_markers_available`;
- `sufficient_nonempty_chunks`;
- `balanced_html_table`;
- `table_atomicity_preserved`.

Checks run in the documented order, while fallback codes use the fixed priority above.
Whitespace-only segments are suppressed before counting, so a separate
`empty_candidate_chunk` fallback would duplicate `insufficient_nonempty_chunks` and is
not part of the contract.

Automatic decisions are evaluated per Markdown document. The aggregate effective mode
is `markers` when every document selects markers, `file` when every document falls back,
and `mixed` when both outcomes occur. Aggregate public decision metadata records only
document-mode and reason-code counts; it does not add source filenames or paths. Chunk
items retain the existing document provenance inside the snapshot contract.

Automatic selection is deterministic and does not invoke an LLM. A host AI may explain
the resulting decision report, but it must not silently override a failed safety check.

## Provenance And Snapshot Contract

Every marker-derived candidate retains this provenance across the in-memory chunk and
written snapshot item:

- `document_name`: source Markdown basename;
- `document_id`: the existing source-file identifier used by the Markdown reader;
- `chunk_id`: unset, because this field may represent a RAGFlow server chunk identity in
  existing retrieval and validation paths;
- `source_chunk_id`: deterministic offline identity such as
  `marker-<relative-path-digest>-0001`, retained on the snapshot item and in aliases.
  The digest is derived from the source path relative to the explicit Markdown input
  root, preventing cross-document ordinal collisions without publishing the path;
- `content`: the complete candidate chunk text.

The existing snapshot writer continues to derive:

- stable content hash;
- raw SHA-256 content digest;
- aliases containing the stable hash and diagnostic chunk ID;
- deterministic snapshot order;
- content preview and optional full content.

The snapshot and report aggregate additive fields under a `boundary` sub-object so the
existing top-level contracts remain compact. Existing schema loaders accept additive
fields and `tools/schema_identity_check.py` verifies identity/coverage references rather
than a field whitelist, so no schema version or identity-list change is required solely
for this additive object. Focused producer/consumer tests and the report-surface release
gate remain required.

The `boundary` object should include:

- requested boundary mode;
- effective boundary mode;
- candidate/offline evidence scope;
- `observed_ragflow_chunks=false`;
- source marker count;
- emitted candidate chunk count;
- suppressed table-boundary count;
- ignored fenced-marker count;
- fallback reason when applicable;
- zero RAGFlow calls, zero live writes, and zero script-owned LLM calls.

The existing schema identities remain unchanged unless implementation review proves an
additive field cannot safely express the contract. Any schema change requires the full
public report-surface checklist before completion.

## Error Handling

- `snapshot_chunks` classifies the input as a Markdown file, Markdown directory, or JSON
  payload before parsing content. Non-Markdown JSON and validation-report inputs reject
  `markers` and `auto` at the runtime boundary with a clear input-mode error rather than
  relying only on CLI suffix checks or silently ignoring the option.
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
- self-closing, nested, mixed-case, and attributed table tags follow the shared HTML
  parser semantics;
- fenced-code table literals are ignored, while the documented inline-code limitation
  fails or falls back safely;
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
- marker-aware output removes canonical delimiters, so
  `delimiter_visible_chunk_count` is zero for the focused fixture;
- the precise boundary atomicity result passes for the focused fixture. The existing
  `possible_split_table_chunk_count` remains an advisory heuristic and is not required
  to be zero for every multi-table document because adjacent independent table chunks
  can trigger it;
- no test fixture contains a real endpoint, credential, private source, or raw user data.

## Task Checklist

### A. Baseline And Contract

- [ ] Add a failing focused test that proves current marker-bearing Markdown produces one
  chunk under legacy/default behavior.
- [ ] Add tests for the new mode argument, invalid input combinations, and additive
  decision metadata before changing runtime code.
- [ ] Confirm the existing snapshot schema and consumers accept a `boundary` child
  object, and confirm `schema_identity_check` still passes without a new identity. If a
  consumer rejects additive fields, stop and update the design before introducing a new
  schema identity.

### B. Marker-Aware Runtime

- [ ] Add the canonical delimiter recognizer and reuse or narrowly extend
  `html_tables.py` for balanced table ranges and fenced-code masking.
- [ ] Add deterministic marker splitting with empty-segment suppression.
- [ ] Add table-boundary suppression and unbalanced-table failure behavior.
- [ ] Preserve document provenance, deterministic non-colliding `source_chunk_id`
  identities, ordering, aliases, and stable hashes without populating candidate values
  into `chunk_id`.
- [ ] Keep JSON/validation inputs and legacy Markdown behavior unchanged.

### C. Automatic Selection

- [ ] Add `file`, `markers`, and `auto` runtime modes with `file` as the compatible
  low-level default.
- [ ] Add deterministic selection and fallback reason codes.
- [ ] Add ordered selection checks, fixed fallback priority, and candidate/offline,
  non-observed, and zero-call safety metadata under the `boundary` object.
- [ ] Verify a host AI can explain the decision entirely from the public-safe report,
  without raw chunk content or an LLM call inside the script.

### D. CLI And Public Guidance

- [ ] Add `--markdown-boundary-mode` to `snapshot-chunks` with concise help.
- [ ] Document `auto` as the intended high-level workflow choice and the other modes as
  expert overrides.
- [ ] Preserve all existing commands and examples when the option is omitted.
- [ ] Review schema identity, report-surface inventory, generated Markdown audit, runtime
  resilience inventory, consumer acceptance, and platform smoke impact.
  Adding an option or additive report field does not automatically require an inventory
  count change; update inventory expectations only if the command's output categories or
  public schema identities actually change.

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
