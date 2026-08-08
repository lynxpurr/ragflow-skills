# Table, Image, and Chunk Patterns

## Tables

Use Markdown tables when reusable row and column facts can be represented faithfully.

- Expand inherited merged-row values when each row must stand alone.
- Flatten multi-level headers into explicit field paths.
- Preserve title, scope, dimensions, units, conditions, exceptions, footnotes, and row order.
- Keep one semantically complete table in one chunk even when a size heuristic marks it long.
- Do not fill blanks, invent units, promote one cell to a global maximum, or treat neighboring
  dimensions as interchangeable.
- Retain a source image when spatial grouping, handwriting, seals, nested layout, or visual
  inspection matters.

When OCR text and an image duplicate the same facts, choose one authoritative retrieval
representation. Keep both only when the image has independent visual value.

## Images

Classify each asset as knowledge-bearing, visual support, display-only, decorative,
fragment or duplicate, or unresolved. Retain knowledge-bearing and support assets with
nearby source-faithful text. Remove decorative or duplicate material only after proving it
carries no unique title, state, rule, navigation meaning, or visual function.

Write compact retrieval text containing the topic, likely user action, stable state or
result, necessary condition, and image reference. Exclude incidental names, identifiers,
addresses, dates, example values, and arithmetic unless the source defines reusable facts.

Use semantic, collision-resistant basenames. Rename a canonical file and every Markdown
reference together, then preserve the reviewed basename downstream when practical.

## Chunk boundaries

Treat `<!-- chunk -->` as a semantic context reset rather than visual spacing or pagination.
A useful chunk contains sufficient heading context plus one coherent rule, table, ordered
procedure, FAQ answer, or image-supported operation.

Review empty, heading-only, or unexplained image-only chunks; boundaries inside tables or
between required notes and images; detached exceptions; mixed topics; and repeated policy
text added only to increase retrieval hits. Repeat the minimum source-supported parent
system, process, actor, or topic when a child chunk would otherwise lose context.
