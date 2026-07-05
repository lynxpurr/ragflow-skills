# Adaptive Pipeline Quality Fix Plan

Status: proposed targeted fix plan
Date: 2026-07-05

## Scope

This document records follow-up work from the real scanned-PDF adaptive pipeline review.
It does not mark any roadmap checklist item complete. It separates local evidence hygiene
from the code-quality issues found while reviewing the field-trial output.

The reviewed run used a real scanned Chinese PDF through a local MinerU FastAPI service.
The run proved that the explicit `pipeline` backend path can complete and that postprocess
chunk markers can preserve HTML table blocks for this sample. The same evidence also
showed several issues that should be fixed before treating the result as a clean
release-facing validation.

## Objective Problem Statement

### Local Artifacts Must Stay Out Of Git

The repository root `output/` directory contains local task-upload copies of source
documents from MinerU field-trial runs. These files are not public fixtures, are not
needed for deterministic tests, and can include user-owned documents. They must remain
outside git history.

The review also found draft public references that include local tool paths, local
endpoints, and private run-root paths. Those files need sanitization before they can be
committed or linked from public skill documentation.

### Scanned PDF Language Is Misclassified

For the scanned Chinese PDF, `inspect-source` reported `primary_language: en`. The binary
PDF probe extracted a long Latin-1-looking garbage sample from compressed PDF content.
Because the sample had Latin characters and was longer than the current short-sample
threshold, filename and user language hints did not override it.

This is not only a reporting issue. The adaptive decision used the inspected language and
recommended an English table-atomic KB profile. After conversion, downstream profile
suggestions detected Chinese from the generated Markdown and recommended the Chinese
profile. That means the pre-conversion decision and post-conversion handoff disagree.

### PDF Inspection Repeats Work And Lacks Reliability Signals

The document record path probes PDF binary features once to create a sample and again to
compute scanned/low-text signals. This doubles file reads and can also make the report
harder to reason about if future probing grows more expensive.

The current feature schema exposes the resulting `sample_text`, but it does not clearly
state whether the sample is reliable human text, binary garbage, or too sparse to support
language/table decisions. Downstream decision logic therefore treats weak signals too
confidently.

### Explicit Backend Preservation Needs Contract Tests

The field trial verified the desired behavior manually: when the user explicitly requests
`--mineru-fastapi-backend pipeline`, `--table-quality high` must not silently replace it
with a high-accuracy backend. This avoids a known MinerU backend failure on the tested
Blackwell host.

The current test suite has broad table-quality coverage, but it needs focused regression
tests for this exact contract in both direct pipeline execution and adaptive
decision-only mode.

### Chunk Marker Counts Are Inconsistent Across Reports

The generated Markdown contained 32 chunk markers and the postprocess report recorded
zero chunk markers inside HTML tables. The quality report, however, recorded a chunk
marker count of zero for the same document. The table-atomicity conclusion is supported
by postprocess evidence, but the inconsistent report surfaces can mislead reviewers and
automated consumers.

### Public Documentation Should Avoid Hardware Overgeneralization

The observed high-accuracy backend failure is real for the tested local MinerU version
and host. The public guidance should present it as a versioned compatibility finding and
recommended workaround, not as a permanent statement that all Blackwell GPUs or all
future MinerU high-accuracy backends are unsupported.

## Improvement Plan

### 1. Isolate Local Run Artifacts

Ignore the repository-root `output/` directory so local task uploads and generated run
copies do not appear as untracked public changes. Keep real source PDFs and full raw run
artifacts under private run roots. Only sanitized metrics and artifact names should be
summarized in public docs.

Before committing any live or representative-document report, run a targeted redaction
scan for home paths, local endpoints, temporary run roots, credentials, dataset IDs,
document IDs, and KB names.

### 2. Add Reliable PDF Text-Sample Classification

Refactor PDF inspection so `_binary_pdf_features()` runs once per PDF record and returns
both the sample and confidence metadata. Add a conservative reliability signal such as
`pdf_text_sample_quality` with values like `extractable_text`, `low_text`, or
`binary_garbage`.

Treat a PDF sample as unreliable when it has indicators such as very low text density,
many non-printable/replacement-like characters, no CJK text despite a CJK filename hint,
or a high ratio of mojibake-like Latin-1 bytes. For unreliable samples, avoid using Latin
characters alone to infer English.

### 3. Make Language Hint Precedence Explicit

For scanned or low-text PDFs, derive language in this order:

1. user-provided language option, when available to the adaptive command;
2. explicit filename hint such as `CN`, `ZH`, `Chinese`, or native-language terms;
3. reliable sampled text;
4. `unknown` or `auto`, not English, when only unreliable binary text exists.

Record the source of the language decision, for example `sample_text`, `filename_hint`,
`user_hint`, or `unknown_low_confidence`. Adaptive decisions should use this source to
lower confidence and preserve review warnings when the signal is weak.

### 4. Align Adaptive Decision With Conversion Hints

Pass relevant user language intent from the adaptive CLI into decision creation, or
include it in the feature payload before calling the decision module. If
`--mineru-language ch` is supplied and the inspected PDF is scanned/low-text, the
recommended KB profile should be Chinese unless stronger reliable text evidence says
otherwise.

When conversion output later contradicts the pre-conversion language decision, the
adaptive summary should flag the mismatch and recommend reviewing the KB profile before
live ingestion.

### 5. Lock Backend Preservation With Focused Tests

Add unit/CLI tests covering:

- direct pipeline with `--table-quality high --mineru-fastapi-backend pipeline` submits
  the `pipeline` backend and emits a review warning that high-accuracy table extraction
  may not be active;
- adaptive `--decision-only` with requested `table_quality=high` and requested
  `mineru_fastapi_backend=pipeline` preserves `pipeline` in `pipeline_decision.json`;
- table-quality `auto` still promotes to a high-accuracy backend when no explicit backend
  was provided and existing candidate conditions are met;
- fallback behavior remains unchanged when a high-accuracy backend is selected and then
  rejected by the service.

### 6. Reconcile Chunk Marker Report Surfaces

Trace why the quality report sees zero chunk markers while postprocess and ingest
readiness see the inserted markers. The likely fix is to ensure quality analysis runs on
the postprocessed Markdown when it is reporting postprocess-sensitive signals, or to make
the quality report explicitly label pre-postprocess metrics.

Acceptance should require the same marker count across Markdown, postprocess report, and
the public readiness surface, or an intentionally documented distinction between pre- and
postprocess counts.

### 7. Sanitize And Reword Public Field-Trial Docs

Rewrite draft public references so they use placeholders for endpoints, source paths,
run roots, and tool paths. Keep only public-safe facts: source class, approximate size,
page count, backend family, MinerU version, status, issue counts, marker counts, image
counts, and quality/readiness status.

Reword the Blackwell note as an observed compatibility pitfall for a specific local
MinerU version and host class. Keep the recommended workaround but avoid a blanket
hardware ban.

## Task Checklist

- [x] Add root `output/` to `.gitignore` so local run artifacts are isolated from git.
- [x] Remove or relocate the current untracked `output/` directory outside the repository
  before staging release-facing changes.
- [x] Sanitize draft field-trial reference docs before committing or linking them from
  public `SKILL.md`.
- [x] Refactor PDF inspection to run `_binary_pdf_features()` once per PDF record.
- [x] Add PDF sample reliability fields and keep binary-garbage samples from implying
  English language.
- [x] Implement scanned/low-text language precedence using user hints, filename hints,
  reliable text, then unknown/auto.
- [x] Propagate adaptive CLI language intent into `make_pipeline_decision()` or the
  feature payload used by that decision.
- [x] Add a mismatch warning when post-conversion profile suggestions disagree with the
  pre-conversion adaptive language/profile decision.
- [x] Add focused tests for explicit `pipeline` backend preservation with
  `--table-quality high`.
- [x] Add focused tests for scanned Chinese PDF language hint behavior using a synthetic
  low-text PDF fixture.
- [x] Add or update tests that prove `auto` table quality still promotes when no explicit
  backend is set.
- [x] Reconcile chunk marker counts across Markdown, `quality_report.json`,
  `postprocess_report.json`, and ingest readiness reports.
- [x] Run targeted validation for changed Python files and tests.
- [x] Run redaction scan over changed public docs and review every hit before commit.

## Acceptance Criteria

- `git status --short` no longer shows repository-root `output/` as an untracked path.
- A synthetic scanned or low-text Chinese PDF fixture produces a Chinese or
  low-confidence unknown adaptive profile, not an English profile from binary garbage.
- Explicit `--mineru-fastapi-backend pipeline` is preserved under
  `--table-quality high` in both direct pipeline and adaptive decision-only coverage.
- Chunk marker counts are consistent across public report surfaces, or clearly labeled as
  pre- versus postprocess metrics.
- Public docs contain no home paths, private endpoints, temporary run-root paths,
  credentials, dataset IDs, document IDs, KB names, or raw source-document paths.

## Closeout Lessons And Follow-Up Signals

### Lessons Learned

The representative scanned-PDF run was valuable because it exercised the pipeline with
real MinerU behavior rather than only synthetic fixtures. It also showed why field-trial
evidence must be tied back to the exact code state under review. Hermes' successful run
was based on local uncommitted changes, so the release-facing work had to separate proven
runtime behavior from unmerged implementation details before accepting the conclusions.

User intent needs to be treated as an explicit contract, not only as a hint. The most
important example was `--mineru-fastapi-backend pipeline`: a high table-quality request
must not silently override a backend explicitly chosen to avoid a known compatibility
failure. The follow-up tests now protect that behavior in both direct conversion and
adaptive decision-only flows.

Scanned and low-text PDFs need reliability-aware inspection. A binary PDF preview can
contain Latin-looking garbage that is long enough to fool simple language heuristics. The
fix works by recording sample quality and language source, then preferring user and
filename intent over unreliable binary samples. This makes low-confidence decisions
visible instead of converting weak evidence into a confident English profile.

Report surfaces should share the same source of truth when they describe postprocess
behavior. The chunk-marker mismatch was not a table-breaking bug in the sample output,
but it was a reviewability bug: different reports appeared to disagree about the same
artifact. Rebuilding quality-sensitive counts from final Markdown makes the evidence
easier for users and automated consumers to trust.

Artifact hygiene is part of quality, not an administrative afterthought. Local `output/`
copies, run roots, endpoints, and source-document paths can leak context even when code is
correct. The fix plan therefore paired implementation work with ignore rules, sanitized
public references, and targeted redaction scans.

### Signals To Monitor

Monitor `pdf_text_sample_quality`, `pdf_text_density`, `pdf_text_mojibake_ratio`, and
`language_source_counts` across future representative runs. A rise in
`binary_garbage`, `low_text`, or `unknown_low_confidence` should trigger review of
language/profile decisions rather than automatic broadening of heuristics.

Track profile disagreement warnings, especially `profile_language_mismatch`, between
pre-conversion adaptive decisions and post-conversion Markdown/profile suggestions. A
non-zero rate is acceptable for difficult scanned PDFs, but repeated mismatches for the
same source class indicate that inspection needs better early signals.

Track explicit backend preservation warnings and backend fallback events separately.
`explicit_backend_preserved` is expected when the user intentionally chooses a backend;
service rejections or fallback retries indicate environment compatibility or MinerU
version drift and should be summarized by backend family and MinerU version.

Keep chunk-marker and table-atomicity metrics aligned across Markdown,
`postprocess_report.json`, `quality_report.json`, and ingest-readiness reports. The key
indicators are marker count, markers inside HTML tables, HTML table count, and any
postprocess warning that says a table boundary could not be preserved.

Track image asset naming quality as a ratio: semantic names versus hash-safe fallback
names. A moderate fallback rate is fine for scanned documents, but a sudden drop in
semantic naming can reveal OCR/caption extraction drift or changed MinerU asset output.

Track quality-gate status distribution for scanned PDFs. `PASS_WITH_REVIEW` can be the
right outcome for low-text sources; the important signal is whether review reasons remain
specific and actionable rather than becoming generic noise.

Continue scanning public docs for private paths, endpoints, source paths, dataset IDs,
document IDs, KB names, credentials, and raw retrieved text whenever field-trial evidence
is summarized.

### Next Improvement Directions

Build a small, sanitized representative corpus that covers scanned Chinese PDFs, mixed
Chinese/English reports, table-heavy PDFs, image-heavy PDFs, and normal extractable-text
PDFs. Use it to watch trend metrics instead of relying on a single successful sample.

Add a lightweight run-summary comparison helper that can compare two adaptive pipeline
runs and highlight language-source shifts, backend-selection changes, table atomicity
changes, image naming ratio changes, and quality-gate movement.

Make backend compatibility documentation versioned by MinerU version, backend family,
host class, and observed failure mode. The current Blackwell note should remain an
observed compatibility pitfall and workaround, not a permanent hardware rule.

Consider a stronger early language signal for scanned PDFs after the current heuristics
prove stable. Good candidates are explicit CLI language, filename conventions, PDF
metadata when available, and a small OCR-derived sample after conversion. Avoid adding
script-owned LLM language detection unless a future gated task explicitly approves it.

Keep public report schemas conservative. When adding new monitoring fields, prefer
existing report structures and update schema identity, report-surface inventory, focused
tests, and release hygiene together so downstream consumers are not surprised.
