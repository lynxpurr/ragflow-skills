---
name: ragflow-kb-build
description: Build and validate RAGFlow knowledge bases from Markdown handoff bundles. Use when Codex needs to upload Markdown documents into RAGFlow, apply chunking profiles, inspect parse status, or validate retrieval quality with smoke, regression, or benchmark checks.
---

# RAGFlow KB Build

Use scripts in this skill to create, inspect, and validate RAGFlow datasets from Markdown inputs.

Inputs:

- A Markdown file or directory via `--input`, or a handoff manifest via `--doc-manifest`.
- A chunk profile JSON/YAML via `--profile`.
- RAGFlow connection from `RAGFLOW_BASE_URL` and `RAGFLOW_API_KEY`, or `--base-url` and `--api-key`.

Commands:

```bash
python scripts/build.py --input ./markdown --kb-name kb:project --profile ./templates/default-en-768.json --output ./run/kb_manifest.json
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project --profile ./templates/default-zh-512.json
python scripts/inspect_kb.py --kb-manifest ./run/kb_manifest.json
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
```

Notes:

- `build.py` creates the dataset, uploads Markdown, triggers parse, waits for parse completion by default, and emits `kb_manifest.json`.
- Use `--dry-run` to validate local inputs without touching RAGFlow.
- Use `--no-wait` only when the host platform should continue while RAGFlow parses asynchronously.
- `validate.py` implements `--level smoke` in the MVP; `regression` and `benchmark` are reserved command levels.
