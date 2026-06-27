---
name: ragflow-doc-to-md
description: Convert raw documents into Markdown handoff bundles for portable RAGFlow ingestion. Use when Codex needs to turn PDF, Office, HTML, TXT, or existing Markdown inputs into normalized Markdown plus a thin manifest for downstream KB build workflows.
---

# RAGFlow Doc To MD

Use scripts in this skill to produce Markdown handoff directories that can be consumed by `ragflow-kb-build`.

Inputs:

- Existing Markdown via `--mode passthrough`.
- Plain text and simple HTML via the built-in converter.
- Office/PDF/EPUB-like formats through `--backend mineru-cli` for an installed local MinerU binary, `--backend mineru` for MinerU Agent API, `--backend mineru-sync` for synchronous multipart `/parse`, `--backend pandoc` when pandoc is installed, or `--backend remote --remote-url ...`.

Command examples:

```bash
python scripts/convert.py --input ./docs --output ./handoff --mode passthrough
python scripts/convert.py --input ./raw --output ./handoff --backend builtin
python scripts/convert.py --input ./raw --output ./handoff --backend mineru-cli --mineru-cli-path /opt/mineru/bin/mineru
python scripts/convert.py --input ./raw --output ./handoff --backend mineru
python scripts/convert.py --input ./raw --output ./handoff --backend remote --remote-url https://converter.example/api/convert
python scripts/convert.py backend probe --backend auto --report-json ./run/backend_probe.json --report-md ./run/backend_probe.md --json
python scripts/convert.py --config /path/to/ragflow-config.local.yaml --input ./raw --output ./handoff --json
python scripts/convert.py inspect --doc-manifest ./handoff/doc_manifest.json --report-md ./handoff/quality_report.md
python scripts/convert.py segment-plan --markdown ./handoff/documents/book.md --output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --plan-output ./handoff/segmentation_plan.json
python scripts/convert.py package --handoff ./handoff --rich
python scripts/convert.py postprocess --doc-manifest ./handoff/doc_manifest.json --profile safe --output ./handoff-clean
```

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Local MinerU CLI conversion can be configured through the host agent environment. `auto` uses this first for PDF/Office/image files when a CLI is available:

```bash
DOC_TO_MD_BACKEND=auto
MINERU_CLI_PATH=/opt/mineru/bin/mineru
MINERU_CLI_BACKEND=pipeline
MINERU_TIMEOUT=300
```

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
- Use `package --rich` when the handoff should carry optional audit and review sidecars such as `metadata.json`, `artifact_index.json`, `profile_suggestions.json`, `retrieval_hints.json`, `assistant_profile.json`, `assistant_test_plan.json`, and `package_readme.md`.
- Use `postprocess` with profiles `none`, `safe`, `ocr`, or `chunk-markers` when Markdown needs deterministic cleanup before ingestion. Use `--output` for non-destructive writes; `--write` is required for in-place rewrites.
- `doc_manifest.json` uses `source_root: "."`, so downstream `ragflow-kb-build` can consume it after the handoff directory moves.
- `quality_gate.status` is written into `doc_manifest.json`; `ragflow-kb-build` blocks `BLOCKED` handoffs unless the user passes `--allow-blocked`.
- Use `--strict` when skipped files should fail the run.
- Use `backend probe` before live conversion to classify backends as `available`, `missing`, `wrong_protocol`, `timeout`, or `not_configured`. It does not convert files, and endpoint checks require explicit `--network-check`.
- Use `backend warmup --fixture <tiny-file>` when the user has approved a small converter fixture and wants to run one bounded conversion readiness check. Add `--fail-on-failed` for CI gates.
- Image inputs fall back to Markdown with the source image copied into `documents/images/` when OCR/conversion is unavailable; this sets `quality_gate.status` to `PASS_WITH_REVIEW`. Use `--no-image-fallback` to skip that behavior.
- When a local process-backed converter such as `mineru-cli` runs, `runtime_report.json` records process attempt status, timeout cleanup, and leftover process counts. Use `--runtime-report-md` for a Markdown copy.
- Use `inspect` to regenerate a quality report from an existing handoff.
- Use `segment-plan` before splitting long Markdown; use `split` when the user wants materialized `segments/*.md` that can be ingested as an ordinary Markdown directory.
- The `mineru-cli` backend runs a local MinerU executable as `mineru -b <backend> -p <source> -o <temp-output>` and reads the Markdown file it produces. Set the path with `MINERU_CLI_PATH`, `mineru.cli_path`, or `--mineru-cli-path`; default CLI backend is `pipeline`.
- The `mineru` and `mineru-agent` backends use the Agent parsing API shape: create parse task at `/parse/file`, upload to signed URL, poll `/parse/{task_id}`, then download Markdown.
- The `mineru-sync` and `mineru-local` backends post multipart form data to `/parse` and expect Markdown text or JSON containing `markdown`, `content`, `text`, `result`, or `markdown_url`.
- The remote backend expects JSON with `filename` and base64 `content_base64`, and returns `markdown` or `content`.
