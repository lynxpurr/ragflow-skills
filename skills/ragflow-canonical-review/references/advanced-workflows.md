# Advanced Canonical Review Workflows

Load only the section required by the document and review state. None of these workflows
proves live parser, retrieval, answer-grounding, or front-end asset behavior.

## Exact-source reconciliation

Trigger: an exact PDF, Office document, scan, image, or other original is available. Read
[Source review workflow](source-review-workflow.md), then the matching section in
[Source format adapters](source-format-adapters.md). Build a source coverage map before
making meaning-changing edits.

## Source-unavailable structural review

Trigger: the exact original cannot be established. Use the structural audit, repair only
demonstrable defects, retain uncertain content and assets, and mark the document
`needs_source_verification`. Do not claim source fidelity or create current retrieval truth.

## Complex tables, images, and chunks

Trigger: the candidate contains merged tables, screenshots, diagrams, image-supported
procedures, or fragile chunk boundaries. Read
[Table, image, and chunk patterns](table-image-chunk-patterns.md) before editing.

For a server-derived HTML representation, run `table_evidence.py --mode compare`; require
normalized cell-matrix equivalence before treating it as a derived retrieval representation.
For an independent VLM cross-check, create a `--mode vlm-request` artifact from one exact
source crop, then review an external advisory/generated candidate with `--mode vlm-review`.
The script never calls a model, converts the canonical table, or lets a candidate overwrite
source-reviewed Markdown.

## Canonical boundaries and asset changes

Trigger: the task involves allowlists, control files, shared asset roots, duplicate hashes,
renames, moves, directory cleanup, or deletion. Read
[Canonical assets and boundaries](canonical-assets-and-boundaries.md) and require evidence
for both document integrity and knowledge preservation.

## Downstream evidence invalidation

Trigger: canonical meaning, representation, source ownership, or asset identity changed.
Read [Downstream change control](downstream-change-control.md), retain historical payloads
unchanged, and regenerate versioned handoff and validation evidence from the accepted
canonical source.
