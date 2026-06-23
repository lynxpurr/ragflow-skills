---
name: ragflow-doc-to-md
description: Convert raw documents into Markdown handoff bundles for portable RAGFlow ingestion. Use when Codex needs to turn PDF, Office, HTML, TXT, or existing Markdown inputs into normalized Markdown plus a thin manifest for downstream KB build workflows.
---

# RAGFlow Doc To MD

Use scripts in this skill to produce Markdown handoff directories that can be consumed by `ragflow-kb-build`.

Inputs:

- Existing Markdown via `--mode passthrough`.
- Plain text and simple HTML via the built-in converter.
- Office/PDF/EPUB-like formats through `--backend mineru`, `--backend pandoc` when pandoc is installed, or `--backend remote --remote-url ...`.

Command examples:

```bash
python scripts/convert.py --input ./docs --output ./handoff --mode passthrough
python scripts/convert.py --input ./raw --output ./handoff --backend builtin
python scripts/convert.py --input ./raw --output ./handoff --backend mineru
python scripts/convert.py --input ./raw --output ./handoff --backend remote --remote-url https://converter.example/api/convert
python scripts/convert.py --config /path/to/ragflow-config.local.yaml --input ./raw --output ./handoff --json
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

MinerU service conversion can be configured through the host agent environment:

```bash
DOC_TO_MD_BACKEND=mineru
MINERU_BASE_URL=https://mineru.net/api/v1/agent
MINERU_API_KEY=...
MINERU_TIMEOUT=300
MINERU_POLL_INTERVAL=3
```

Generic remote conversion can also be configured through the host agent environment:

```bash
DOC_TO_MD_BACKEND=remote
DOC_TO_MD_REMOTE_URL=https://converter.example/api/convert
DOC_TO_MD_REMOTE_API_KEY=...
DOC_TO_MD_TIMEOUT=120
```

Notes:

- The output directory contains `documents/*.md` plus `doc_manifest.json`.
- `doc_manifest.json` uses `source_root: "."`, so downstream `ragflow-kb-build` can consume it after the handoff directory moves.
- Use `--strict` when skipped files should fail the run.
- The MinerU backend uses the Agent parsing API shape: create parse task, upload to signed URL, poll task, then download Markdown.
- The remote backend expects JSON with `filename` and base64 `content_base64`, and returns `markdown` or `content`.
