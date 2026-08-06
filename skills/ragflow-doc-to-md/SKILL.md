---
name: ragflow-doc-to-md
description: Convert source documents into reviewed Markdown handoff bundles. Use when Codex needs a formal RAGFlow pre-ingest handoff, a deterministic source inspection, or a thin Markdown preview; specialized backends and packaging stay behind explicit advanced triggers.
---

# RAGFlow Doc To MD

## When to use

Use this skill to convert PDF, Office, HTML, text, image, EPUB, or existing Markdown
sources into a reviewed handoff for `ragflow-kb-build`. Use `pipeline` for formal ingest;
use the top-level thin conversion only when the user explicitly wants a preview.

## Inputs and outputs

Inputs are a source file or directory, an output directory, and a reviewed backend or
private config when conversion is required. A formal handoff includes `documents/*.md`,
`doc_manifest.json`, `quality_report.json`, `formal_handoff_manifest.json`,
`retrieval_hints.json`, and `ragflow_ingest_plan.yaml` when available.

## Canonical workflows

### Canonical workflow: convert ordinary documents

```bash
python scripts/convert.py pipeline --input ./raw --output ./handoff --backend auto --postprocess-profile chunk-markers-dense --json
```

Review the quality gate and handoff manifests before passing the bundle downstream.
Existing Markdown may use `--mode passthrough`; conversion-required inputs need a backend
that is already configured and approved by the host.

### Canonical workflow: inspect and decide deterministically

```bash
python scripts/convert.py adaptive --input ./raw --output ./review --decision-only --backend auto --json
```

Use the decision-only report when backend choice, table signals, or document quality is
uncertain. Execute the full adaptive path only after its selected backend and output path
are acceptable.

## Decision and stop rules

- Prefer `pipeline` for formal KB ingestion and passthrough for already-reviewed Markdown.
- Stop when the quality gate is `BLOCKED`, required source files are missing, or a remote
  backend is not explicitly configured.
- A core finding may open only the matching advanced trigger; do not scan every backend or
  packaging command for a workaround.
- Handoff guidance does not authorize MinerU access, network calls, or RAGFlow mutation.

## Advanced triggers

Open [Advanced workflows](references/advanced-workflows.md) only for an explicit backend
diagnosis, high-quality table path, split/package request, postprocess request, retained
package comparison, or adaptive-policy investigation. For host configuration and smoke
setup, use [Host agent setup](references/host-agent-setup.md).

## Security

Keep converter endpoints and API keys in a private config, environment, or host secret
store. Tracked handoffs and examples must contain no live endpoint, key, source path, raw
private document content, or temporary run root.
