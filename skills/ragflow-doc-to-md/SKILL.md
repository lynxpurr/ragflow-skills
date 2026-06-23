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
python scripts/convert.py inspect --doc-manifest ./handoff/doc_manifest.json --report-md ./handoff/quality_report.md
python scripts/convert.py segment-plan --markdown ./handoff/documents/book.md --output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --plan-output ./handoff/segmentation_plan.json
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

MinerU Agent API conversion can be configured through the host agent environment:

```bash
DOC_TO_MD_BACKEND=mineru
MINERU_BASE_URL=https://mineru.net/api/v1/agent
MINERU_API_KEY=...
MINERU_TIMEOUT=300
MINERU_POLL_INTERVAL=3
```

Self-hosted synchronous multipart `/parse` MinerU services use `mineru-sync`:

```bash
DOC_TO_MD_BACKEND=mineru-sync
MINERU_BASE_URL=http://mineru.internal:8777/api/v1
MINERU_API_KEY=...
MINERU_TIMEOUT=300
```

Generic remote conversion can also be configured through the host agent environment:

```bash
DOC_TO_MD_BACKEND=remote
DOC_TO_MD_REMOTE_URL=https://converter.example/api/convert
DOC_TO_MD_REMOTE_API_KEY=...
DOC_TO_MD_TIMEOUT=120
```

Notes:

- The output directory contains `documents/*.md`, `doc_manifest.json`, and `quality_report.json`.
- `doc_manifest.json` uses `source_root: "."`, so downstream `ragflow-kb-build` can consume it after the handoff directory moves.
- `quality_gate.status` is written into `doc_manifest.json`; `ragflow-kb-build` blocks `BLOCKED` handoffs unless the user passes `--allow-blocked`.
- Use `--strict` when skipped files should fail the run.
- Use `inspect` to regenerate a quality report from an existing handoff.
- Use `segment-plan` before splitting long Markdown; use `split` when the user wants materialized `segments/*.md` that can be ingested as an ordinary Markdown directory.
- The `mineru` and `mineru-agent` backends use the Agent parsing API shape: create parse task at `/parse/file`, upload to signed URL, poll `/parse/{task_id}`, then download Markdown.
- The `mineru-sync` and `mineru-local` backends post multipart form data to `/parse` and expect Markdown text or JSON containing `markdown`, `content`, `text`, `result`, or `markdown_url`.
- The remote backend expects JSON with `filename` and base64 `content_base64`, and returns `markdown` or `content`.
