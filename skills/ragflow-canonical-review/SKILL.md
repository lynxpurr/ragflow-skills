---
name: ragflow-canonical-review
description: Review extracted or existing Markdown and local assets against exact original sources, promote source-faithful content into a canonical RAG layer, audit canonical allowlists and asset integrity, and prepare accepted changes for a new formal RAGFlow handoff. Use after document extraction and before passthrough packaging, KB build, or retrieval validation; also use for structural-only review when the exact source is unavailable.
---

# RAGFlow Canonical Review

## When to use

Use this skill between document conversion and formal handoff packaging. It owns source
reconciliation, canonical Markdown repair, table/image/chunk review, positive ingestion
selection, asset-boundary audit, and downstream evidence invalidation.

Use source review when the exact original is available. Use structural-only review when it
is not, and keep the result marked `needs_source_verification`.

## Inputs and outputs

Inputs are one candidate Markdown document, its local assets, the exact source when
available, the intended canonical path, a positive ingestion allowlist when applicable,
and any prior handoffs or benchmark evidence affected by a change.

Outputs are a reviewed canonical document, source-coverage and table-decision inputs, JSON
audit reports, optional reviewed asset identity/context input, one
`ragflow_canonical_review_v1` record, and an explicit list of downstream artifacts that
became pre-change evidence. This skill does not build or query a live KB.

## Canonical workflows

### Canonical workflow: review canonical source

```bash
python scripts/audit_markdown_structure.py --markdown ./canonical/document.md --image-root ./canonical --asset-scope ./assets/document --source ./source/document.pdf --json-out ./run/markdown-audit.json
```

Review every in-scope page, slide, sheet, table, diagram, and material note in source order.
Repair meaning and provenance before headings, tables, images, filenames, or chunk markers.

### Canonical workflow: audit canonical boundaries

```bash
python scripts/audit_canonical_assets.py ./canonical --allowlist ./active-paths.yaml --project-root . --json-out ./run/asset-audit.json
```

### Canonical workflow: finalize canonical acceptance

```bash
python scripts/finalize_review.py --source ./source/document.pdf --candidate-markdown ./extraction-handoff/documents/document.md --reviewed-markdown ./review/document.md --markdown-audit ./run/markdown-audit.json --asset-audit ./run/asset-audit.json --source-coverage ./run/source-coverage.json --table-decisions ./run/table-decisions.json --asset-root ./review --output ./accepted-review --json
```

For canonical mode, do not skip or reorder: MinerU handoff -> structural and exact-source
review -> table decisions and asset audit -> accepted record -> new passthrough handoff ->
`inspect-handoff` and `asset-upload-plan` -> image readiness and build dry-run -> separately
approved live text/image operations. See [Canonical review record](references/canonical-review-record.md).

Use positive selection for ingestible Markdown. Treat control files, missing references,
unreferenced assets, duplicate hashes, basename collisions, and empty directories as audit
evidence, not automatic move or deletion instructions.

## Decision and stop rules

- Preserve source-stated actors, actions, conditions, limits, units, exceptions, and
  consequences. Keep policy, source-provided interpretation, and reviewer notes distinct.
- Build a source coverage map. A clean structural audit cannot detect an omitted source
  page, slide, sheet, diagram, or workflow.
- Keep complete tables, required image context, and self-contained knowledge units together.
  Treat `<!-- chunk -->` as a context reset.
- When the source is unavailable, repair only demonstrable structural defects and retain
  uncertain wording or assets for later verification.
- Stop meaning-changing edits on unresolved source identity, uncovered source units,
  ambiguous tables or images, conflicting sources, or unclear sensitive-content authority.
- Treat `PASS_WITH_REVIEW`, `ready_with_review`, and conversion success as pre-review
  evidence only; none is a canonical acceptance or multimodal-ingestion result.
- Never overwrite the extraction candidate or original handoff. Finalization writes the
  accepted Markdown, selected assets, and review record under a new output root.
- After canonical content changes, preserve old handoffs, snapshots, qrels, benchmarks, and
  staging reports unchanged while classifying them as pre-change evidence.
- Generate a new passthrough handoff only after canonical acceptance. Validate parser and
  retrieval behavior in `ragflow-kb-build` and `ragflow-query`, not in this skill.

## Advanced triggers

Open [Advanced workflows](references/advanced-workflows.md) for source-format adapters,
conflict ledgers, table-equivalence/VLM advisory evidence, image semantics, asset movement
or deletion, shared asset roots, source-unavailable review, or downstream benchmark invalidation. For private host
setup and suite smoke guidance, use [Host agent setup](references/host-agent-setup.md).

## Security

Keep originals, sensitive content, private absolute paths, endpoints, credentials, raw
queries, and unsanitized evidence in approved private storage. Record portable identities
and hashes without embedding enterprise-specific data in the skill package.
