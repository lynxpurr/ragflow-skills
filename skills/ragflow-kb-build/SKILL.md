---
name: ragflow-kb-build
description: Inspect Markdown handoffs, dry-run and build one reviewed RAGFlow knowledge base, validate retrieval quality, inspect health, and perform exact cleanup. Use when Codex owns the handoff-to-KB lifecycle; advanced benchmark, profile, metadata, topology, and optimization work requires an explicit trigger.
---

# RAGFlow KB Build

## When to use

Use this skill after a Markdown handoff exists. It owns handoff inspection, non-mutating
readiness, one explicitly approved KB build, validation, health review, and exact cleanup.

## Inputs and outputs

Inputs are `doc_manifest.json` or reviewed Markdown, a KB name, a chunk profile, and a
private RAGFlow config only when a live or read-only call is approved. Outputs include
dry-run JSON, `kb_manifest.json`, validation and health reports, and cleanup previews.

## Canonical workflows

### Canonical workflow: inspect a handoff

```bash
python scripts/build.py inspect-handoff --handoff ./handoff --report-md ./run/handoff-inspection.md --json
```

### Canonical workflow: validate build readiness without mutation

```bash
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb-example --profile ./templates/default-en-768.json --dry-run --json
```

### Canonical workflow: build one reviewed kb

```bash
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb-example --profile ./templates/default-en-768.json --output ./run/kb_manifest.json
```

Run this only after the same inputs pass dry-run and the user explicitly approves the live
build and exact KB name.

### Canonical workflow: validate retrieval quality

```bash
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke --report-md ./run/validation.md
```

### Canonical workflow: inspect kb health

```bash
python scripts/build.py health-report --kb-manifest ./run/kb_manifest.json --report-json ./run/kb-health.json --report-md ./run/kb-health.md --json
```

### Canonical workflow: clean up a disposable kb

```bash
python scripts/cleanup.py --kb-manifest ./run/kb_manifest.json --output ./run/cleanup-plan.json
python scripts/cleanup.py --kb-manifest ./run/kb_manifest.json --execute --confirm-dataset-id DATASET_ID --confirm-kb-name kb-example --config /private/path/ragflow-config.local.yaml
```

Review the preview first. Execute only with the exact dataset ID, matching KB name, and a
separate cleanup approval.

## Decision and stop rules

- Inspect the handoff and dry-run before every build.
- Use `Inspect a handoff` only to review handoff content, quality, or an existing blocker;
  when asked whether the handoff and profile are build-ready without touching RAGFlow,
  use only `Validate build readiness without mutation` and do not prepend or combine
  `Inspect a handoff`.
- Use core `Inspect KB health` when diagnosing overall KB health or failures from retained
  manifests, reports, or other existing artifacts. Load advanced diagnostics only for a
  named finding or an explicit deeper diagnostic investigation; the verb `diagnose` alone
  is not an advanced trigger.
- Stop on `BLOCKED`, missing identity, name collision, profile failure, absent authority,
  or cleanup ambiguity. Do not substitute a raw API mutation.
- Live build, read-only refresh/query, and cleanup are separate approvals.
- Use the smallest validation level that answers the request; benchmark and optimization
  are advanced workflows, not default build steps.
- Validating a supplied build profile in the core dry-run is not advanced profile work.

## Advanced triggers

Open [Advanced workflows](references/advanced-workflows.md) only for a named finding or an
explicit request involving images, append/resume, metadata, profile selection, profile
comparison or experimentation, benchmark evidence, grounded QA, topology, routing
activation, diagnostics, or optimization. For private configuration and smoke setup, use
[Host agent setup](references/host-agent-setup.md).

## Security

Keep credentials and endpoints outside tracked files. Never guess identifiers, publish
raw retrieved content, broaden mutation authority, or execute cleanup without exact
confirmation and retained proof.
