# Dedao/Pandoc EPUB Quality Improvement Plan

Status: active improvement plan
Date: 2026-07-08
Scope: `ragflow-doc-to-md` -> `ragflow-kb-build`

## Objective / Scope / Boundaries

This document records sanitized findings from a Dedao-style EPUB-to-RAGFlow A/B field
trial and turns them into a concrete improvement plan for the current public skill suite.

The comparison exercised two document-to-KB paths:

- legacy path: download and pandoc Markdown conversion, then legacy chunk/build tooling;
- replacement path: download and pandoc Markdown conversion, then
  `ragflow-doc-to-md pipeline` and `ragflow-kb-build`.

The goal is not to repair retiring skills. The goal is to improve the current
`ragflow-doc-to-md` and `ragflow-kb-build` path until it can reliably absorb this class
of workflow during the retirement transition.

This plan keeps the public-suite boundaries:

- no live RAGFlow mutation by default;
- no script-owned LLM or RAGAS execution by default;
- no private bridge code in the public `skills/` directory;
- no private paths, endpoints, dataset identifiers, document identifiers, real KB names,
  API keys, raw retrieved chunks, or private run roots in public docs;
- deterministic offline tests and fake-client tests before any approved live retest.

## Problem Description

The field trial showed that the replacement path is close to the legacy path in retrieval
behavior, but the input quality is not yet good enough for confident retirement of the
old workflows on this document class.

Sanitized observed signals:

- Retrieval quality was nearly identical across the two paths on the sampled query set.
  The replacement path did not show a meaningful retrieval-quality regression, but it also
  did not improve the result.
- Top-result agreement was complete for the sampled queries, which suggests both paths
  were mostly limited by the same upstream Markdown quality.
- Chunk quality sampling showed very high pandoc artifact pollution. Inline style
  attributes, fenced div markers, generated anchors, and similar XHTML-to-Markdown
  residue dominated the text seen by the downstream parser.
- The replacement path mainly added chunk marker comments to the handoff Markdown. The
  rest of the Markdown content was effectively unchanged from the pandoc output.
- The current RAGFlow parser/profile used in the trial did not consume those chunk marker
  comments as effective split boundaries. Chunk markers are useful only when paired with a
  parser or profile strategy that actually honors them.
- The replacement handoff hit a blocked readiness state because local image references in
  Markdown passthrough were not materialized into the handoff directory.
- A cleaned Markdown variant removed a large share of text noise and changed the
  document-side quality gate from blocked to pass, indicating that pandoc cleanup is a
  high-leverage improvement.

Root causes identified from local artifact and code review:

1. Pandoc EPUB Markdown noise is a shared upstream bottleneck for both paths. The current
   replacement path preserves that noise unless an appropriate postprocess profile is
   selected.
2. Markdown passthrough conversion does not currently copy adjacent relative image assets
   into the formal handoff when the source is already Markdown. This makes valid source
   images appear missing after handoff packaging.
3. The current Markdown output filename sanitizer strips Chinese characters and other
   Unicode title content, reducing document-name fidelity before upload.
4. Chunk marker generation is currently presented as a quality improvement even when the
   selected downstream RAGFlow parser/profile ignores marker comments.
5. Chinese corpus readiness is not explicit enough. A profile can build successfully while
   still leaving language, tokenizer, and parser expectations unclear.
6. KB name collision behavior can be surprising when RAGFlow or an adapter silently
   creates a suffixed name. The replacement path should surface this as a preflight
   review issue where possible.

## Update Plan

### P0 - Deterministic Handoff Quality Fixes

Make the replacement path produce a cleaner, more complete formal handoff before it
reaches `ragflow-kb-build`.

Planned changes:

- Preserve local Markdown assets during passthrough conversion. Relative references such
  as `images/example.jpg` should be copied or rewritten into the formal handoff when the
  source asset exists.
- Preserve Unicode-safe document names. Chinese title characters and other valid Unicode
  letters or numbers should not be stripped from generated Markdown filenames.
- Add a conservative pandoc EPUB cleanup profile. It should remove obvious pandoc
  structural residue such as marker-only fenced div lines, empty generated anchors, and
  inline attribute tails while preserving visible text and valid image references.
- Emit postprocess rule counts so operators can see how much cleanup occurred and whether
  the profile changed the document materially.

Acceptance criteria:

- A Markdown passthrough fixture with relative local images produces a handoff with no
  false missing-image blocker when files exist.
- A CJK filename fixture keeps a readable title in the output filename.
- A pandoc EPUB fixture loses `style=` residue, marker-only `:::` lines, and generated
  anchor residue while preserving human-readable content.
- Focused runtime tests pass with no network and no RAGFlow mutation.

### P1 - Build Readiness And Profile Warnings

Make `ragflow-kb-build` explain when a handoff is technically ingestible but unlikely to
benefit from the chosen parser/profile.

Planned changes:

- Warn when a handoff contains many chunk marker comments but the selected profile has no
  delimiter or parser behavior that is expected to honor those markers.
- Add or strengthen Chinese-language readiness warnings when document features indicate a
  Chinese corpus but the build profile does not make language or tokenizer expectations
  visible.
- Add a read-only or dry-run collision review for intended KB names when the target
  RAGFlow endpoint can be probed safely. If live probing is unavailable, produce an
  advisory checklist instead of guessing.
- Ensure recommendations stay advisory unless an explicit live mutation workflow is
  approved.

Acceptance criteria:

- Dry-run output distinguishes hard blockers from advisory parser/profile mismatch
  warnings.
- No live endpoint is required for the default test suite.
- Fake-client tests cover any endpoint-dependent preflight behavior.

### P2 - Regression Harness And Retirement Evidence

Turn the field-trial lessons into repeatable retirement-transition evidence rather than
one-off manual observations.

Planned changes:

- Add a sanitized pandoc EPUB regression fixture or synthetic equivalent that represents
  the observed noise classes without carrying private corpus text.
- Track document-side quality metrics before and after cleanup: missing local image
  count, pandoc artifact counts, text-size reduction, quality gate status, and
  postprocess rule counts.
- Track build-side metrics: chunk count, chunk-size coefficient of variation, parser
  warnings, build readiness status, and profile mismatch warnings.
- Track retrieval-side metrics only through explicit benchmark inputs: mean score,
  Hit@k, MRR or equivalent ranking metrics, top-result agreement, empty-result rate, and
  latency.
- Use these metrics to support retirement decisions for the old workflows without
  publishing private KB names or raw retrieved chunks.

Acceptance criteria:

- The regression harness can compare "raw pandoc Markdown" and "cleaned formal handoff"
  without network access.
- The public report contains only sanitized aggregate metrics.
- Live A/B validation remains optional and requires explicit approval, disposable
  resources, and cleanup evidence.

## Task Checklist

- [x] Add a failing unit or CLI test showing that Markdown passthrough preserves existing
  relative local image assets in the formal handoff.
- [x] Implement Markdown passthrough asset materialization and verify the missing-image
  quality gate no longer blocks when source assets exist.
- [x] Add a failing filename test showing that CJK title text is preserved by the Markdown
  output-name sanitizer.
- [x] Implement Unicode-safe Markdown filename sanitization with deterministic collision
  handling.
- [ ] Add a failing postprocess test for pandoc EPUB residue cleanup: marker-only fenced
  divs, empty generated anchors, inline style attributes, and generated anchor tails.
- [ ] Implement a conservative pandoc EPUB cleanup profile and postprocess rule-count
  reporting.
- [ ] Update `ragflow-doc-to-md` public guidance to recommend the pandoc EPUB cleanup
  profile for Dedao-style or pandoc-generated EPUB Markdown before KB build.
- [ ] Add `ragflow-kb-build` dry-run/readiness warning coverage for chunk markers that
  are unlikely to affect the selected downstream parser/profile.
- [ ] Add Chinese corpus profile-readiness warnings or a documented review path for
  language/tokenizer expectations.
- [ ] Add read-only or fake-client-tested KB-name collision review behavior where the
  endpoint contract allows it.
- [ ] Add a sanitized pandoc EPUB regression fixture or synthetic equivalent.
- [ ] Add quality metrics comparing raw pandoc Markdown with cleaned formal handoff
  output.
- [ ] Add build/readiness metrics for chunk count, chunk-size variation, parser/profile
  warnings, and quality gate status.
- [ ] Add retrieval benchmark guidance for future approved A/B runs, including ranking,
  agreement, empty-result, and latency metrics.
- [ ] Re-run focused tests, `git diff --check`, and public-doc redaction scans before
  marking any checklist item complete.

## Current Development Progress

The field-trial report has been reviewed and the main findings have been classified into
three implementation tracks:

- P0 deterministic handoff quality fixes for `ragflow-doc-to-md`;
- P1 build-readiness warnings for `ragflow-kb-build`;
- P2 repeatable regression evidence for retirement-transition decisions.

The 2026-07-08 P0 startup slice adds a CLI regression for Markdown passthrough image
materialization and wires existing local Markdown asset copying into the formal handoff
conversion path. Existing relative image references such as `images/chart.png` are now
copied under `handoff/documents/` before the quality gate, retrieval hints, and rich
handoff sidecars are generated.

The 2026-07-09 P0 filename slice adds a CJK filename regression for
`safe_markdown_name` and preserves Unicode letters and numbers in generated Markdown
filenames while keeping deterministic `-2`, `-3`, ... collision suffixes.

Checklist items should be checked only after implementation, focused verification, and
redaction review are complete.

## Validation Evidence / Residual Gated Work

Current evidence is sanitized field-trial evidence plus local artifact review. It is
strong enough to justify offline fixes, but it is not a blanket retirement certificate
for every Dedao-style EPUB or every RAGFlow deployment.

2026-07-08 P0 handoff asset validation:

- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/__init__.py skills/ragflow-doc-to-md/scripts/convert.py packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py`
- `python3 -m pytest packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py::DocConvertCliTests::test_convert_passthrough_directory packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py::DocConvertCliTests::test_pipeline_creates_rich_handoff_and_ingest_plan packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py::DocConvertCliTests::test_pipeline_passthrough_materializes_relative_markdown_images packages/ragflow-skill-runtime/tests/test_doc_convert.py::DocConvertTests::test_copy_local_markdown_assets_rewrites_absolute_temp_image -q`

2026-07-09 P0 Unicode filename validation:

- `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py packages/ragflow-skill-runtime/tests/test_doc_convert.py`
- `python3 -m pytest packages/ragflow-skill-runtime/tests/test_doc_convert.py -q`

Residual gated work:

- Any live RAGFlow mutation or live A/B retest requires explicit user approval,
  disposable resources, and cleanup confirmation.
- Any script-owned LLM/RAGAS evaluation remains out of scope until the separate LLM
  backend gate is satisfied.
- Private download, bridge, or corpus-specific adapters remain outside the public skill
  release boundary.
- Old skill repositories should remain comparison evidence only; follow-up fixes should
  land in the current public skill suite unless a separate maintenance request targets
  the old code directly.
