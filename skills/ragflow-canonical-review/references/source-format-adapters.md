# Source Format Adapters

Apply only the sections matching the exact original and conversion lineage.

## PDF and scanned PDF

- Verify page order, columns, headers, footers, footnotes, callouts, and reading order.
- Reconstruct clauses, tables, captions, and qualifications split across page boundaries.
- Compare uncertain OCR directly with the rendered page.
- Preserve signatures, seals, handwriting, and spatial forms as visual evidence unless
  faithful text is explicitly required.
- Keep page identity in review evidence without turning pagination into retrieval structure.

## PowerPoint and PPTX

- Reconstruct hierarchy from section and slide relationships, not font size or extraction
  order.
- Inspect grouped objects, text boxes, diagrams, screenshots, tables, overlays, cropped
  fragments, and approved speaker notes.
- For animation or layered builds, identify the source-supported state and record ambiguity
  instead of combining contradictory frames.

## Word and DOCX

- Verify heading styles, clause numbering, list continuation, captions, cross-references,
  footnotes, endnotes, and text boxes.
- Exclude repeated headers and footers unless they carry material meaning.
- Treat tracked changes and comments according to the approved source version and scope.
- Reconstruct tables or floating objects split across pages.

## Excel and XLSX

- Review every in-scope sheet and record excluded sheets.
- Resolve merged headers, units, formulas versus displayed values, named ranges, comments,
  filters, and print areas.
- Do not expose hidden content without authority or infer meaning from color or blanks.
- Preserve row and column semantics when converting ranges to Markdown.

## Other formats and lineage

For images, HTML, email, text, or proprietary formats, define the authoritative structure,
rendering method, metadata scope, and omission risks before editing. Record every
intermediate, compare canonical meaning with the exact original when available, and use
intermediates only to diagnose lost layout, notes, formulas, or layers.
