# RAGFlow Skills Folder Plan

Status: draft
Date: 2026-06-22

## Goal

Create a cross-platform public RAGFlow skill suite that can run in Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools. The public suite must not depend on dedao tools, personal paths, implicit localhost services, or editable installs.

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
      scripts/
      references/
      templates/
    ragflow-kb-build/
      SKILL.md
      scripts/
      references/
      templates/
    ragflow-query/
      SKILL.md
      scripts/
      references/
      templates/
  tools/
    build_release.py
    export_release_archives.py
    live_integration_check.py
    platform_smoke_matrix.py
    release_hygiene_check.py
```

## Directory Responsibilities

| Path | Responsibility |
|---|---|
| `packages/ragflow-skill-runtime/` | Shared Python runtime used by all public skills. Source-of-truth during development. |
| `skills/ragflow-doc-to-md/` | Convert PDF, Office, HTML, TXT, and existing Markdown inputs into a Markdown handoff directory. |
| `skills/ragflow-kb-build/` | Upload Markdown into RAGFlow, apply profiles, wait for parsing, inspect KB health, and validate retrieval quality. |
| `skills/ragflow-query/` | Unified direct and host-assisted agentic retrieval interface with `--mode auto|direct|agentic`. |
| `tools/build_release.py` | Build self-contained release artifacts by vendoring `ragflow_skill_runtime` into each skill. |
| `tools/export_release_archives.py` | Export deterministic per-skill `.tar.gz` archives and checksums. |
| `tools/live_integration_check.py` | Run an opt-in live retrieval check when a real RAGFlow endpoint is configured. |
| `tools/platform_smoke_matrix.py` | Smoke-test source and vendored artifacts across target platform profiles. |
| `tools/release_hygiene_check.py` | Gate release artifacts and public source against private or non-portable references. |
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
- Strict vendor/env compatibility: scripts can import vendored runtime from local files without editable installs.

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
python scripts/convert.py --input ./docs --output ./handoff --backend remote --remote-url https://converter.example/api/convert
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
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project-docs --profile ./templates/default-en-768.json
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
python scripts/inspect_kb.py --kb-manifest ./run/kb_manifest.json
```

### `ragflow-query`

Input:

- User question.
- KB name, KB manifest, or retrieval config.
- Optional host-assisted mode for an outer agent to synthesize from evidence.

Output:

- JSON result with chunks, mode, dataset IDs, and host-assisted metadata.

Primary commands:

```bash
python scripts/query.py ask "What does the policy say?" --mode auto --routing-config ./routing-config.json --json
python scripts/query.py ask "Compare A and B" --mode agentic --host-assisted --json
```

## Private Skills Kept Outside This Suite

These remain in the current workspace but are not part of public release artifacts:

- `dedao-bookshelf-automation`
- `dedao-dl`
- `dedao-to-ragflow-pipeline`

Private dedao workflows may produce Markdown handoff directories consumed by the public skills, but public skills must never import or depend on dedao code.

## Folder Creation Status

The initial folder skeleton has been created. Implementation status is tracked in `docs/03-development-plan.md`.
