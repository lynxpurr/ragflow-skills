# Canonical Review Record

Use `ragflow_canonical_review_v1` as the only public canonical acceptance record. It binds
the exact source, extraction candidate, reviewed Markdown, source coverage, structure and
asset audits, every candidate HTML table decision, and every selected local image.

For context-aware accepted outputs, add one optional asset-identity input. When supplied,
it must cover every selected asset exactly once:

```json
{
  "assets": [
    {
      "path": "images/image-001.png",
      "role": "diagram",
      "canonical_name": "probe-system-overview.png",
      "source_reference": "page:3 figure:1",
      "context_selector": "line:18-24",
      "context_sha256": "<accepted-context-sha256>",
      "ingestion_intent": "context_bound"
    }
  ]
}
```

Roles are `figure`, `diagram`, `chart`, `table_image`, `screenshot`, `photo`,
`decorative`, or `other`. Intents are `visual_extract`, `context_bound`, or `exclude`;
decorative assets must be excluded. Context selectors are one-based inclusive
`line:START-END` ranges over the final accepted Markdown. Canonical names are portable
ASCII basenames and retain the original extension.

## Review inputs

The source-coverage and table-decision files are host review inputs, not additional public
report schemas. Keep source coverage small:

```json
{
  "status": "complete",
  "source_sha256": "<exact-source-sha256>",
  "covered_units": ["page:1", "page:2"],
  "uncovered_units": []
}
```

Use one decision for every HTML table found in the candidate. A converted table's after
hash must identify a Markdown table in the reviewed document. Retained HTML requires an
exact source reference and a reason explaining why Markdown would not remain faithful:

```json
{
  "decisions": [
    {
      "table_id": "table-001",
      "action": "converted_to_markdown",
      "source_reference": "page:1",
      "before_sha256": "<candidate-html-table-sha256>",
      "after_sha256": "<reviewed-markdown-table-sha256>",
      "reason": "Rows and columns were verified against the exact source."
    }
  ],
  "unresolved_items": []
}
```

File hashes cover exact bytes and use lowercase hexadecimal. Table-fragment hashes cover
the exact UTF-8 table block after removing an optional BOM and normalizing newlines to LF;
surrounding blank lines are excluded. The runtime validates these hashes and does not
convert tables.

## Finalization

```bash
python scripts/finalize_review.py \
  --source ./source/document.pdf \
  --candidate-markdown ./extraction-handoff/documents/document.md \
  --reviewed-markdown ./review/document.md \
  --markdown-audit ./run/markdown-audit.json \
  --asset-audit ./run/asset-audit.json \
  --source-coverage ./run/source-coverage.json \
  --table-decisions ./run/table-decisions.json \
  --asset-identities ./run/asset-identities.json \
  --asset-root ./review \
  --output ./accepted-review \
  --redaction-report ./accepted-review/canonical-review.redaction.json \
  --json
```

`--output` must be a new directory outside the audited asset root. An accepted review
copies the reviewed Markdown and its selected, hash-matching assets into that directory
and writes `ragflow_canonical_review.json`. When asset identities are supplied, the new
output alone receives semantic asset names and rewritten Markdown references; reviewed,
candidate, and original-handoff bytes remain unchanged. Duplicate bindings, path
traversal, name collisions, stale context hashes, and stale asset hashes block acceptance.
A blocked or source-unverified review writes
only the record. The extraction candidate and any original handoff stay byte-for-byte
unchanged.

## Table equivalence and optional VLM evidence

Use `table_evidence.py --mode compare` to compare canonical Markdown with server-derived
HTML by normalized header and cell matrices. The validator expands rowspan values,
flattens multilevel headers, preserves blanks, values, units, and footnotes, and blocks
differences. It validates representations; it is not an HTML converter.

Use `--mode vlm-request` only with an exact page/table crop. The request records crop,
Markdown, fragment, and matrix hashes with `llm_invoked=false`. An external result must
use `ragflow_canonical_table_vlm_candidate_v1`, set `advisory=true` and `generated=true`,
and retain provenance. `--mode vlm-review` blocks unknown/stale bindings, private
literals, and matrix differences. VLM output never becomes a second production truth or
overwrites canonical Markdown.

## Build binding

After creating a new passthrough handoff from the accepted output, supply the record and
the exact private evidence files to both KB-build dry-run and an independently approved
live build:

```bash
python ragflow-kb-build/scripts/build.py \
  --doc-manifest ./handoff/doc_manifest.json \
  --kb-name kb-reviewed \
  --profile ./ragflow-kb-build/templates/default-en-768.json \
  --canonical-review ./accepted-review/ragflow_canonical_review.json \
  --canonical-source ./source/document.pdf \
  --canonical-markdown-audit ./run/markdown-audit.json \
  --canonical-asset-audit ./run/asset-audit.json \
  --dry-run \
  --json
```

The build gate rehashes the supplied source, the one Markdown build input, both audits,
and every selected asset in the new handoff before any client is created. A live
checkpoint and `kb_manifest.json` store only the exact review-record SHA-256, not the
record, evidence paths, or private evidence contents. Omitting `--canonical-review`
preserves the generic non-canonical build path.

## Status and stop rules

- `accepted` requires exact source bytes, complete source coverage, zero uncovered units,
  matching audit hashes, no structural errors, one decision for every candidate and
  retained HTML table, no unresolved items, and every selected local asset present with
  its audited hash.
- `needs_source_verification` means exact source bytes were unavailable and no independent
  blocker was found. It is not canonical acceptance.
- `blocked` covers incomplete coverage, stale hashes, missing assets, unreviewed HTML,
  malformed decisions, audit errors, or explicit unresolved items.

The command is local and deterministic. It performs no network `PUT`, KB build, image
upload, provider discovery, model selection, or script-owned model call.
