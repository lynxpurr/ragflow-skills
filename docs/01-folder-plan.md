# RAGFlow Skills Folder Plan

Status: draft
Date: 2026-06-22

## Goal

Create a cross-platform public RAGFlow skill suite that can run in Hermes, OpenClaw, Claude Code, and SaaS agent sandboxes. The public suite must not depend on dedao tools, personal paths, localhost-only services, or editable installs.

## Top-Level Layout

```text
ragflow-skills/
  docs/
  packages/
    ragflow-skill-runtime/
      src/ragflow_skill_runtime/
      tests/
  skills/
    ragflow-doc-to-md/
      SKILL.md
      agents/
      scripts/
      references/
      templates/
    ragflow-kb-build/
      SKILL.md
      agents/
      scripts/
      references/
      templates/
    ragflow-query/
      SKILL.md
      agents/
      scripts/
      references/
      templates/
  tools/
    build_release.py
```

## Directory Responsibilities

| Path | Responsibility |
|---|---|
| `packages/ragflow-skill-runtime/` | Shared Python runtime used by all public skills. Source-of-truth during development. |
| `skills/ragflow-doc-to-md/` | Convert PDF, Office, HTML, TXT, and existing Markdown inputs into a Markdown handoff directory. |
| `skills/ragflow-kb-build/` | Upload Markdown into RAGFlow, apply profiles, wait for parsing, inspect KB health, and validate retrieval quality. |
| `skills/ragflow-query/` | Unified direct and agentic retrieval interface with `--mode auto|direct|agentic`. |
| `tools/build_release.py` | Build self-contained release artifacts by vendoring `ragflow_skill_runtime` into each skill. |
| `docs/` | Architecture and implementation planning documents for this public suite. |

## Source vs Release Layout

Development keeps one shared source tree:

```text
packages/ragflow-skill-runtime/src/ragflow_skill_runtime/
```

Release artifacts vendor that source into each skill:

```text
ragflow-doc-to-md/scripts/_vendor/ragflow_skill_runtime/
ragflow-kb-build/scripts/_vendor/ragflow_skill_runtime/
ragflow-query/scripts/_vendor/ragflow_skill_runtime/
```

This gives us:

- DRY in source: one runtime package to maintain.
- Self-contained in distribution: each skill can run without `pip install -e`.
- SaaS sandbox compatibility: scripts can import vendored runtime from local files.

## Public Skills

### `ragflow-doc-to-md`

Input:

- Local files or directories.
- Optional remote conversion backend.
- Existing Markdown directories for passthrough mode.

Output:

- Markdown documents.
- `doc_manifest.json`.
- Conversion report with warnings and skipped files.

Primary commands:

```bash
python scripts/convert.py --input ./docs --output ./handoff
python scripts/convert.py --input ./docs --output ./handoff --backend remote
python scripts/convert.py --input ./markdown --output ./handoff --mode passthrough
```

### `ragflow-kb-build`

Input:

- Markdown directory.
- `doc_manifest.json`.
- Chunking profile template.

Output:

- `kb_manifest.json`.
- Validation report.
- Optional retrieval config for query-time routing.

Primary commands:

```bash
python scripts/build.py --input ./handoff/doc_manifest.json --kb-name kb:project-docs
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
python scripts/inspect.py --kb-manifest ./run/kb_manifest.json
```

### `ragflow-query`

Input:

- User question.
- KB name, KB manifest, or retrieval config.
- Optional LLM key for script-owned synthesis.

Output:

- JSON result with chunks, answer, citations, mode, and trace summary.

Primary commands:

```bash
python scripts/query.py ask "What does the policy say?" --mode auto --json
python scripts/query.py ask "Compare A and B" --mode agentic --host-assisted --json
python scripts/query.py serve --host 0.0.0.0 --port 8086
```

## Private Skills Kept Outside This Suite

These remain in the current workspace but are not part of public release artifacts:

- `dedao-bookshelf-automation`
- `dedao-dl`
- `dedao-to-ragflow-pipeline`

Private dedao workflows may produce Markdown handoff directories consumed by the public skills, but public skills must never import or depend on dedao code.

## Folder Creation Status

The initial folder skeleton has been created under:

```text
/home/zenz/.hermes/skills/research/ragflow-skills/
```

Implementation files are intentionally deferred to the phased development plan.
