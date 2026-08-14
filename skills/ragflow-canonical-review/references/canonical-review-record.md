# Canonical Review Record

Use `ragflow_canonical_review_v1` as the only public canonical acceptance record. It binds
the exact source, extraction candidate, reviewed Markdown, source coverage, structure and
asset audits, every candidate HTML table decision, and every selected local image.

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
  --asset-root ./review \
  --output ./accepted-review \
  --redaction-report ./accepted-review/canonical-review.redaction.json \
  --json
```

`--output` must be a new directory outside the audited asset root. An accepted review
copies the reviewed Markdown and its selected, hash-matching assets into that directory
and writes `ragflow_canonical_review.json`. A blocked or source-unverified review writes
only the record. The extraction candidate and any original handoff stay byte-for-byte
unchanged.

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
