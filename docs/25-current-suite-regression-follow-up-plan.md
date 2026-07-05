# Current Suite Regression Follow-Up Plan

Status: offline follow-up complete; gated observations remain
Date: 2026-07-05

## Scope

This document reviews the latest scanned-PDF regression round and turns its findings into
current-suite follow-up work for:

- `ragflow-doc-to-md`
- `ragflow-kb-build`
- `ragflow-query`
- shared `ragflow-skill-runtime`

It does not reopen maintenance for retiring comparison skills. `ragflow-kb-ops` and
`ragflux` may still provide transition evidence, but fixes should land in the current
three-skill suite only when they improve current handoff contracts, report clarity,
readiness checks, retrieval validation, or release evidence.

This plan does not authorize live RAGFlow mutation. Live build, parse, query, or cleanup
work remains gated by explicit user approval and disposable resources.

## Regression Findings

### 1. Scanned Chinese PDF Language Handling Is Fixed For The Tested Sample

The updated regression showed the desired behavior for the representative scanned Chinese
PDF:

- `primary_language: zh`
- `pdf_text_sample_quality: binary_garbage`
- `likely_scanned: true`
- adaptive profile recommendation: `table-atomic-zh-4096`
- explicit MinerU FastAPI `pipeline` backend preserved

This is a meaningful fix, but it is not broad corpus proof. The current confidence is
strong for the tested sample plus synthetic low-text coverage, and moderate for other
scanned PDF classes.

Improvement direction: keep the current heuristic conservative, then expand evidence with
a sanitized sample matrix before adding more language rules.

### 2. `PASS_WITH_REVIEW` Is The Correct Outcome, But Review Reasons Need To Stay Sharp

The pipeline completed with `PASS_WITH_REVIEW`, 32 chunk markers, 6 HTML tables, no chunk
marker inside table blocks, and complete sidecars. The warnings were table-review
warnings, not blocked conversion or missing assets.

This is acceptable for scanned table-heavy PDFs. The risk is that review warnings become
too generic for operators to act on.

Improvement direction: preserve specific warning classes and keep table-review summaries
easy to compare across runs.

### 3. Asset Counts Use Multiple Valid Meanings

The run exposed a benign but confusing distinction:

- 21 image artifacts were retained in the package/artifact index.
- 15 image references appeared in Markdown.
- handoff inspection correctly tracked both sides.

The behavior is valid, but reports and acceptance notes should avoid implying one count is
wrong when the counts represent different surfaces.

Improvement direction: make current reports and docs consistently label discovered image
artifacts, manifest assets, Markdown references, and missing assets.

### 4. Retired Consumer Profile Drift Is Transition Evidence, Not An Old-Skill Fix

The retired `ragflow-kb-ops` consumer could create a chunk snapshot, but its run summary
showed requested table-atomic settings were not fully applied by that old path. This only
proves structural handoff consumption; it does not prove profile parity.

Because that skill is retiring, the follow-up should not repair its cleanup or SDK
compatibility. The useful current-suite lesson is that operators need clear requested
versus effective parser/profile evidence when current `ragflow-kb-build` live or dry-run
artifacts are available.

Improvement direction: audit and, if needed, strengthen current `ragflow-kb-build`
requested/effective profile reporting and profile-drift warnings.

### 5. Real Chunk Behavior Needs Current-Suite Evidence

The retired-consumer chunk snapshot suggested RAGFlow may consume delimiters and may
produce table chunks that require closer review. This does not prove a current-suite bug,
but it identifies a quality question that matters after live parse.

Improvement direction: add or improve a current-suite, read-only chunk snapshot review
path that can evaluate table fragmentation, duplicate table-like chunks, missing table
evidence, and delimiter consumption from current `ragflow-kb-build` artifacts.

### 6. MinerU Mode Contention Belongs In Runbooks And Compatibility Notes

The comparison path can start a temporary MinerU FastAPI service even when the workflow is
described as CLI-oriented. That can contend with the current suite's MinerU FastAPI
service on GPU-constrained hosts.

Improvement direction: keep this as an operational compatibility note for comparison
runs and backend selection. Do not add public daemon management to the current skills.

### 7. High-Accuracy Backend Failures Must Stay Versioned

The negative control showed that high-accuracy backend selection can fail on the tested
host/version combination when no explicit compatible backend is requested. Explicit
`pipeline` preservation works.

Improvement direction: keep backend compatibility documentation versioned by MinerU
version, backend family, host class, and observed failure mode. Do not turn this into a
blanket hardware rule.

## Improvement Strategy

### Current-Suite First

Work should improve the active public suite:

- `ragflow-doc-to-md`: source inspection, adaptive decision evidence, backend selection,
  table/image handoff quality, and report clarity.
- `ragflow-kb-build`: handoff inspection, dry-run/readiness, requested/effective profile
  visibility, parse/chunk review, cleanup readiness, and current-suite live evidence.
- `ragflow-query`: retrieval validation for KBs built through the current replacement
  path.

### Offline Before Live

Prefer deterministic offline tasks first:

- report audits;
- fixture-backed unit/CLI tests;
- run-summary comparison over existing JSON artifacts;
- chunk-snapshot review over retained current-suite snapshots;
- docs/runbook improvements.

Live RAGFlow mutation or query checks are useful only after explicit approval and should
remain disposable.

### Evidence Before New Product Surface

The regression does not trigger `ragflow-query serve`, remote converter clients, provider
abstractions, reranker adapters, optional script-owned LLM backends, or private bridges.
Those remain gated by the existing observation plan.

## Development Task Checklist

Checklist status: all current offline follow-up tasks are complete. Remaining live,
private-sample, and query-validation work is tracked in the Gate Ledger below and is not
authorized by this document alone.

### P0 - Boundary And Safety

- [x] Keep `ragflow-kb-ops` and `ragflux` findings classified as retired-consumer or
  comparison evidence in future reports.
- [x] Reject old-skill cleanup or SDK repair work from this roadmap unless a separate
  explicit request targets that retiring repository.
- [x] Before any public field-trial summary, run the changed-doc redaction scan for
  private paths, endpoints, dataset ids, document ids, KB names, credentials, and raw
  retrieved text.

### P1 - `ragflow-doc-to-md` Evidence And Report Clarity

- [x] Build an initial sanitized representative sample matrix covering scanned Chinese PDFs,
  scanned Chinese PDFs without filename language hints, mixed Chinese/English PDFs,
  English PDFs, image-heavy PDFs, and extractable-text PDFs.
- [x] Add or extend deterministic tests for scanned PDFs without `CN`/`ZH` filename hints
  so binary garbage cannot silently become confident English.
- [x] Add a lightweight adaptive run-summary comparison helper that highlights language
  source shifts, backend-selection changes, quality-gate movement, table-atomicity
  changes, and image naming ratio changes.
- [x] Ensure adaptive summaries distinguish inspected language source from user-provided
  language intent when both are present.
- [x] Keep backend compatibility notes versioned by MinerU version, backend family, host
  class, and observed failure mode.

### P1 - `ragflow-kb-build` Requested/Effective Profile Visibility

- [x] Audit current `ragflow-kb-build` JSON reports for requested parser settings,
  effective parser settings, unsupported settings, and profile-drift wording.
- [x] If the audit finds a visibility gap, add a current-suite warning or review block
  for requested/effective profile drift without depending on retired-consumer output.
- [x] Add fixture coverage proving that profile-drift warnings are advisory, sanitized,
  and do not mark a dry-run as live mutation.
- [x] Update `inspect-handoff`, dry-run, parse-report, or health-report docs only where
  the current report surface actually exposes the relevant evidence.

### P1 - Asset And Table Review Clarity

- [x] Normalize report wording for image counts: discovered artifacts, manifest assets,
  Markdown references, and missing assets.
- [x] Keep table warning classes specific, including header-missing, suspected column
  misalignment, large table, marker-inside-table, and unbalanced table cases.
- [x] Add a small report-consistency fixture that proves quality, postprocess,
  chunk-profile, and ingest-readiness reports agree on chunk marker and HTML table counts.
- [x] Document that `PASS_WITH_REVIEW` is acceptable for scanned table-heavy PDFs when
  warnings are actionable and no build-blocking errors exist.

### P2 - Current-Suite Chunk Snapshot Review

- [x] Design a read-only chunk snapshot review path for current `ragflow-kb-build`
  artifacts. It should not call RAGFlow by default.
- [x] Define metrics for table fragmentation, duplicate table-like chunks, missing table
  evidence, delimiter consumption, image-only chunks, and max chunk length.
- [x] Add neutral fixture snapshots that cover intact table chunks, split table chunks,
  duplicate table chunks, and missing table chunks.
- [x] Decide whether the review belongs in an existing command/report or needs a new
  report surface. If it needs a new public report, follow schema identity, report-surface,
  generated-Markdown, redaction, and release-hygiene rules.

Decision: the read-only chunk review now lives in the existing `snapshot-chunks` report
surface as a `chunk_review` block, so the raw `ragflow_chunk_snapshot_v1` artifact remains
unchanged and no new standalone chunk-review schema is introduced.

## Gate Ledger

These items are intentionally not open checkboxes. They require private sample material,
explicit live approval, or observation trigger evidence before work starts.

| Gate | Status | Trigger | Acceptance |
| --- | --- | --- | --- |
| Broader sanitized sample matrix | Observation only | User supplies or approves additional private samples beyond deterministic fixtures and retained public-safe summaries. | Record only sanitized artifact names, count summaries, language-source classes, backend decisions, quality status, table/image metrics, and failure classes. |
| Query-side validation | Live gated | A disposable current-suite KB build is explicitly approved and completed. | Run `ragflow-query` smoke checks against table/image evidence, capture sanitized traces/citation audit/zero-result counts, then tune routing/fusion/rewrite/profile guidance only from observed failures. |
| Disposable current-suite KB build | Live gated | Explicit user approval plus disposable resources and cleanup confirmation. | Capture requested/effective parser evidence from `kb_manifest.json`, parse-report, health-report, and chunk snapshot; verify cleanup through current `ragflow-kb-build`, not retired `ragflow-kb-ops`; record sanitized results in `docs/15-field-trial-observation-plan.md`. |
| Post-CLI adapters, rerankers, providers, service wrappers, optional LLM/backend execution, private bridge | Deferred | Existing observation plan trigger proves the CLI/request-review baseline is insufficient. | Follow the existing Phase 37/38/private-bridge gates with fake fixtures, advisory marking, redaction, citation compatibility, and release hygiene. |

## Implementation Evidence

- Boundary: `docs/15-field-trial-observation-plan.md` and
  `docs/16-system-closeout-report.md` classify retired `ragflow-kb-ops` and `ragflux`
  findings as transition evidence only.
- Language evidence: `packages/ragflow-skill-runtime/tests/test_adaptive_pipeline.py`
  covers scanned PDFs without filename hints and verifies adaptive summaries expose
  inspected language, decision language, effective language source, and user-requested
  language separately.
- Adaptive comparison: `ragflow-doc-to-md compare-adaptive-summaries` emits
  `ragflow_adaptive_summary_comparison_v1` over existing JSON artifacts, with Markdown,
  redaction sidecar, schema identity, report-surface inventory, generated-Markdown audit,
  and runtime inventory coverage.
- Backend compatibility: `references/ragflow-doc-to-md-table-parameter-impact.md` records
  MinerU version, backend family, host class, and observed high-accuracy failure mode.
- Profile visibility: `ragflow-kb-build parse-report` now emits `profile_visibility`
  with requested/effective parser config, unsupported effective keys, advisory drift
  issues, Markdown summary, and no live mutation.
- Asset wording: `ragflow-kb-build asset-upload-plan` now labels Markdown image
  references, discovered image artifacts, planned image files, missing image assets, and
  unreferenced handoff images separately.
- Chunk review: `ragflow-kb-build snapshot-chunks` now includes a read-only
  `chunk_review` block for table-like chunks, possible table fragmentation, duplicate
  table-like chunks, missing table evidence, visible delimiters, image-only chunks, and
  max chunk length without changing the standalone chunk snapshot schema.
- Table/report consistency and `PASS_WITH_REVIEW`: the runtime report-consistency fixture
  covers quality, postprocess, chunk-profile, and ingest-readiness agreement for chunk
  markers and HTML table counts, and `docs/15-field-trial-observation-plan.md` records
  `PASS_WITH_REVIEW` as acceptable when table warnings are actionable and no
  build-blocking missing-asset or quality errors exist.

## Representative Sample Matrix

This matrix is a sanitized planning/evidence map, not a claim that broad private-corpus
quality is complete. It identifies which classes are covered by current deterministic or
retained public-safe evidence and which require future user-approved sample expansion.

| Sample class | Current evidence | Status |
| --- | --- | --- |
| Scanned Chinese PDF with language hint | 2026-07-05 retained public-safe field-trial summary and deterministic adaptive test. | Covered for regression guard. |
| Scanned Chinese PDF without filename language hint | `test_scanned_pdf_without_filename_hint_stays_unknown_not_confident_english`. | Covered for binary-garbage language guard. |
| Mixed Chinese/English PDF | Matrix row defined; needs additional sanitized private sample or synthetic fixture before broad quality claims. | Observation gated. |
| English PDF | Matrix row defined; existing English Markdown/table adaptive fixtures cover language/profile mechanics, not PDF corpus breadth. | Observation gated. |
| Image-heavy PDF or image source | Existing image fallback, asset policy, and asset-upload-plan fixtures cover packaging semantics. | Covered for report semantics; broader OCR quality gated. |
| Extractable-text PDF | Matrix row defined; existing text/Markdown source inspection fixtures cover low-risk language mechanics. | Observation gated for PDF-specific corpus breadth. |

## Acceptance Criteria

The follow-up round can be considered complete when:

- old-skill repair remains outside this roadmap;
- the current suite has clearer language/profile/backend evidence across representative
  samples;
- image/table/chunk review surfaces use unambiguous count labels;
- current `ragflow-kb-build` can expose requested/effective parser behavior when that
  evidence exists;
- any new report surface has focused tests, schema identity coverage, generated Markdown
  review, redaction checks, and release hygiene;
- live validation, if performed, is explicitly approved, disposable, cleaned up, and
  recorded with sanitized evidence.

## Suggested Next Slice

The suggested offline slice is complete:

1. `parse-report` now exposes a current-suite requested/effective parser visibility block
   and advisory drift warning.
2. `compare-adaptive-summaries` compares existing adaptive JSON artifacts for language,
   backend, quality-gate, table-atomicity, and image-naming drift.
3. Deterministic scanned-PDF coverage now verifies no-hint binary preview text does not
   become confident English.

No unchecked task remains in this document. Further work should follow the Gate Ledger:
observe more sanitized samples when supplied, run live/query validation only with explicit
approval, or fix release-health regressions if validation fails.
