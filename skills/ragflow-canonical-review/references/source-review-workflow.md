# Source Review Workflow

Compare one candidate Markdown bundle with one exact source version. Keep the review
document-scoped unless a claim explicitly depends on another named source.

## Establish provenance

Record document identity, source filename and version, source hash, conversion lineage,
candidate location, canonical destination, and review state. Use `source_verified`,
`in_review`, or `needs_source_verification` consistently.

Never reconstruct missing source identity from extracted prose. When multiple sources
address one claim, record the claim, source location, source role, exact wording, and
decision or blocker. Keep authoritative text, interpretation, supplemental notes, and
reviewer observations separate.

## Freeze and render evidence

- Preserve the original in an immutable source layer.
- Preserve raw extraction output separately from canonical content.
- Render pages, slides, or sheets with a stable viewer for visual comparison.
- Inspect adjacent units when clauses, lists, tables, captions, or notes may continue.
- Use OCR confidence as a diagnostic only; visible source evidence remains authoritative.
- Record conversion intermediates without promoting them over the exact original.

## Build a coverage map

For every in-scope source unit, record the source range, role, candidate section, tables,
images, disposition, and verification state. Use one of these dispositions:

- represented as text;
- represented as an image;
- represented by both text and image;
- omitted as non-knowledge decoration with a reason;
- unresolved and blocked.

A clean static audit cannot detect a completely omitted source unit.

## Repair in source order

1. Restore document identity, source roles, cross-unit clauses, and source order.
2. Rebuild headings from semantic relationships and source-confirmed numbering.
3. Repair tables without losing dimensions, units, scope, exceptions, or notes.
4. Classify images and repair captions, alt text, references, and filenames.
5. Place chunk markers around self-contained retrieval units.
6. Remove duplicate OCR or decorative residue only after coverage is proven.
7. Normalize grammar or typography only when meaning remains unchanged.
8. Recheck actor, action, condition, channel, limit, exception, and consequence.

## Structural-only mode

When the exact source is unavailable, mark `needs_source_verification`; repair only broken
references, malformed tables, empty chunks, or demonstrably generic asset identity;
preserve uncertain wording, numbering, relationships, and assets; and do not claim semantic
fidelity or generate current retrieval truth.

## Static acceptance

Require complete source dispositions, visually checked edits, resolved or blocked
conflicts, faithful rules and tables, coherent hierarchy, resolving image references,
reviewed unreferenced assets, self-contained chunks, no unresolved audit errors, and an
explicit keep-or-fix decision for every warning.

Static acceptance does not prove RAGFlow parser behavior, retrieval quality, answer
grounding, or front-end image delivery.
