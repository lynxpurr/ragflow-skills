---
name: ragflow-doc-to-md
description: Convert raw documents into Markdown handoff bundles for portable RAGFlow ingestion. Use when Codex needs to turn PDF, Office, HTML, TXT, or existing Markdown inputs into normalized Markdown handoffs; prefer pipeline for formal KB pre-ingest and convert for quick thin previews.
---

# RAGFlow Doc To MD

Use scripts in this skill to produce Markdown handoff directories that can be consumed by `ragflow-kb-build`.

Use `pipeline` for formal RAGFlow KB pre-ingest. It writes `handoff_mode:
formal_ingest` in the summary and manifest, then generates deterministic postprocess
output, rich sidecars, retrieval hints, and a non-secret ingest plan. Use ordinary
`convert` when the user only needs a quick Markdown preview; it writes `handoff_mode:
thin_preview` and an advisory that formal ingestion should use `pipeline`.

## High-Quality Tables

For PDF, Office, and image inputs where table structure matters, the high-quality path is:

```bash
python scripts/convert.py pipeline \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

This must actually use a high-accuracy MinerU FastAPI backend such as
`hybrid-auto-engine`, `vlm-auto-engine`, `hybrid-http-client`, or `vlm-http-client`.
Do not pin `--mineru-fastapi-backend pipeline` when the goal is better table extraction;
that preserves the standard backend and prevents `--table-quality high` from improving
table structure.

For MinerU v4 platform-compatible APIs, including the public `mineru.net` API, use
`--backend mineru-v4` or the alias `--backend mineru-platform`. The same
`--table-quality high` setting maps to `--mineru-v4-model-version vlm`; an explicit
`MinerU-HTML` model is preserved for HTML-centric workflows. The v4 backend uses
`/api/v4/file-urls/batch`, uploads to the returned pre-signed URLs without the bearer
token, polls `/api/v4/extract-results/batch/{batch_id}`, and extracts Markdown from the
returned zip.

`adaptive` is the recommended first-pass command when the document is not yet understood.
If source inspection finds table signals in conversion-required inputs such as PDF,
Office, or images, `adaptive` now selects `mineru-fastapi`, `table_quality: high`,
`mineru_fastapi_backend: hybrid-auto-engine`, `markdown_assets`, and
`chunk-markers-dense` unless the user explicitly overrides those choices or a backend
probe is known bad. Existing Markdown/HTML tables are not forced through MinerU.

Inputs:

- Existing Markdown via `--mode passthrough`.
- Plain text and simple HTML via the built-in converter.
- Office/PDF/EPUB-like formats through `--backend mineru-cli` for an installed local MinerU binary, `--backend mineru` for MinerU Agent API, `--backend mineru-fastapi` for a self-hosted MinerU `mineru-api` service, `--backend mineru-v4` for a MinerU v4 platform-compatible API, `--backend mineru-sync` for synchronous multipart `/parse`, `--backend pandoc` when pandoc is installed, or `--backend remote --remote-url ...`.

Command examples:

```bash
python scripts/convert.py --input ./docs --output ./handoff --mode passthrough
python scripts/convert.py --input ./raw --output ./handoff --backend builtin
python scripts/convert.py --input ./raw --output ./handoff --backend mineru-cli --mineru-cli-path /opt/mineru/bin/mineru
python scripts/convert.py --input ./raw --output ./handoff --backend mineru
python scripts/convert.py --input ./raw --output ./handoff --backend mineru-fastapi --mineru-base-url https://mineru.example.internal
python scripts/convert.py pipeline --input ./raw --output ./handoff --backend mineru-v4 --mineru-base-url https://mineru.net --mineru-api-key "$MINERU_API_KEY" --mineru-v4-model-version vlm --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers-dense --json
python scripts/convert.py pipeline --input ./raw --output ./handoff --backend mineru-fastapi --mineru-base-url https://mineru.example.internal --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers-dense
python scripts/convert.py pipeline --input ./raw --output ./handoff --backend mineru-fastapi --mineru-base-url https://mineru.example.internal --table-quality high --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers-dense
python scripts/convert.py adaptive --input ./raw --output ./handoff --backend auto --json
python scripts/convert.py --input ./raw --output ./handoff --backend remote --remote-url https://converter.example/api/convert
python scripts/convert.py backend probe --backend auto --report-json ./run/backend_probe.json --report-md ./run/backend_probe.md --redaction-report ./run/backend_probe_redaction.json --json
python scripts/convert.py --config /path/to/ragflow-config.local.yaml --input ./raw --output ./handoff --json
python scripts/convert.py inspect --doc-manifest ./handoff/doc_manifest.json --report-md ./handoff/quality_report.md
python scripts/convert.py segment-plan --markdown ./handoff/documents/book.md --output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --plan-output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --manifest-output ./handoff/split_doc_manifest.json --plan-output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --checkpoint ./run/split.checkpoint.json --batch-size 10 --plan-output ./handoff/segmentation_plan.json
python scripts/convert.py split --markdown ./handoff/documents/book.md --output ./handoff/segments --checkpoint ./run/split.checkpoint.json --resume --plan-output ./handoff/segmentation_plan.json
python scripts/convert.py package --handoff ./handoff --rich
python scripts/convert.py compare-retained-package --retained-package ./legacy-retained --replacement-handoff ./handoff --report-json ./run/handoff_comparison.json --report-md ./run/handoff_comparison.md --redaction-report ./run/handoff_comparison.redaction.json --json
python scripts/convert.py compare-adaptive-summaries --baseline ./run/baseline-handoff --candidate ./run/candidate-handoff --report-json ./run/adaptive_comparison.json --report-md ./run/adaptive_comparison.md --redaction-report ./run/adaptive_comparison.redaction.json --json
python scripts/convert.py postprocess --doc-manifest ./handoff/doc_manifest.json --profile safe --output ./handoff-clean
```

In the `mineru-v4` example, `https://mineru.net` is the official public endpoint example.
Replace it with any endpoint that implements the same `/api/v4/file-urls/batch`,
pre-signed upload, `/api/v4/extract-results/batch/{batch_id}`, and `full_zip_url`
contract.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

For stable Hermes/OpenClaw-style use, copy `templates/ragflow-config.example.yaml` to a private host-agent config path, point `RAGFLOW_CONFIG` at it, and keep real secrets in environment variables or the host secret store:

```yaml
doc_to_md:
  backend: mineru-fastapi

mineru:
  base_url: https://mineru.example.internal
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  asset_mode: markdown_assets
  v4_model_version: pipeline
  v4_result_mode: full_zip
  v4_data_id_prefix:
```

Config precedence for MinerU settings is: `--mineru-base-url` overrides `MINERU_BASE_URL`, which overrides `mineru.base_url`; `--mineru-asset-mode` overrides `MINERU_ASSET_MODE`, which overrides `mineru.asset_mode`. v4 model options follow the same order with `--mineru-v4-model-version`, `MINERU_V4_MODEL_VERSION`, and `mineru.v4_model_version`.

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

Self-hosted MinerU 3.2+ `mineru-api` FastAPI services use `mineru-fastapi`:

```bash
DOC_TO_MD_BACKEND=mineru-fastapi
MINERU_BASE_URL=https://mineru.example.internal
MINERU_API_KEY=...
MINERU_TIMEOUT=1800
MINERU_POLL_INTERVAL=3
```

MinerU v4 platform-compatible precision API calls use `mineru-v4`:

```bash
DOC_TO_MD_BACKEND=mineru-v4
MINERU_BASE_URL=https://mineru.net
MINERU_API_KEY=...
MINERU_TIMEOUT=1800
MINERU_POLL_INTERVAL=3
MINERU_V4_MODEL_VERSION=pipeline
MINERU_V4_RESULT_MODE=full_zip
MINERU_V4_DATA_ID_PREFIX=case
```

For remote Hermes-agent deployments backed by a MinerU FastAPI service, set
`DOC_TO_MD_BACKEND=mineru-fastapi` explicitly. Do not rely on `auto` in that topology:
`auto` may intentionally prefer a local `mineru-cli` or another configured converter.

Generic remote conversion can also be configured through the host agent environment:

```bash
DOC_TO_MD_BACKEND=remote
DOC_TO_MD_REMOTE_URL=https://converter.example/api/convert
DOC_TO_MD_REMOTE_API_KEY=...
DOC_TO_MD_TIMEOUT=120
```

Notes:

- The output directory contains `documents/*.md`, `doc_manifest.json`, and `quality_report.json`.
- `templates/doc_manifest.schema.json` documents the public `doc_manifest.json` document-level ingestion contract for host agents and downstream consumers. `templates/formal_handoff_manifest.schema.json` documents the package-level audit manifest.
- Host agents should read `handoff_mode` from stdout or `doc_manifest.json`: `thin_preview` is a quick preview handoff, while `formal_ingest` is the recommended KB pre-ingest handoff.
- For formal pre-ingest handoff generation, prefer `pipeline`; it runs conversion, deterministic postprocess, rich package generation, writes `chunk_profile_report.json` for chunk-marker profiles, writes `ingest_readiness_report.json`, writes `formal_handoff_manifest.json`, and writes the non-secret `ragflow_ingest_plan.yaml` sidecar in one step.
- Use `package --rich` when the handoff should carry optional audit and review sidecars such as `metadata.json`, `artifact_index.json`, `profile_suggestions.json`, `retrieval_hints.json`, `assistant_profile.json`, `assistant_test_plan.json`, `ingest_readiness_report.json`, `formal_handoff_manifest.json`, and `package_readme.md`.
- `formal_handoff_manifest.json` is a package-level audit file with relative sidecar paths, schema/version identities, Markdown/image/report hashes, a package hash, and downstream command suggestions. It does not replace `doc_manifest.json`, which remains the document-level contract consumed by `ragflow-kb-build`.
- Local image assets with hash-like or opaque filenames are renamed before manifest generation using deterministic nearby Markdown semantics, while existing readable names are preserved. Content hashes remain in `doc_manifest.json`, `artifact_index.json`, and `formal_handoff_manifest.json` for audit.
- `artifact_index.json` embeds `ragflow_asset_semantics_v1` for local image assets when available: page, caption, nearby heading/context, semantic kind, bytes, hash, and semantic alias evidence.
- When replacing a legacy preprocessor workflow, use `pipeline` for formal handoff generation, then review `ingest_readiness_report.json` and pass `doc_manifest.json`, `retrieval_hints.json`, and `ragflow_ingest_plan.yaml` to `ragflow-kb-build inspect-handoff` and dry-run before any live build.
- For retrieval-quality work, keep `retrieval_hints.json`, `chunk_profile_report.json`, and `assistant_test_plan.json` with the handoff. They can seed `ragflow-query validation-suggestions`, `ragflow-kb-build benchmark import/preflight`, strict chunk snapshots, and later query diagnostics without calling an LLM or mutating RAGFlow.
- For documents with complex tables, use `--backend mineru-fastapi --table-quality high` or `--backend mineru-v4 --table-quality high`, plus `--postprocess-profile chunk-markers-dense`. FastAPI high quality selects a high-accuracy backend; v4 high quality selects `model_version=vlm` unless `MinerU-HTML` was explicitly configured. `standard` keeps the compatible pipeline path; `--allow-table-quality-fallback` permits a degraded FastAPI pipeline retry after high-accuracy resource or timeout failures.
- Use `compare-retained-package` when a host agent needs a read-only `ragflow_handoff_comparison_v1` report between a legacy retained ingestion package and a `pipeline` handoff. The command excludes obvious retained intermediate/raw/layout/span directories, normalizes chunk markers, blank lines, and image path differences for text similarity, and marks strict paired live A/B as `not_run` unless separate live evidence is supplied. It does not create or mutate RAGFlow KBs.
- Use `compare-adaptive-summaries` to compare two existing adaptive run roots or `adaptive_summary.json` files without conversion, MinerU calls, RAGFlow mutation, or script-owned LLM calls. It emits `ragflow_adaptive_summary_comparison_v1` for language-source, backend, quality-gate, table-atomicity, warning-code, image-naming, asset-policy, build, parse, validation, and query-outcome review.
- Use `postprocess` with profiles `none`, `safe`, `ocr`, `chunk-markers`, `chunk-markers-conservative`, `chunk-markers-dense`, or `chunk-markers-ragflux-like` when Markdown needs deterministic cleanup before ingestion. `chunk-markers` remains the conservative compatibility alias; `chunk-markers-dense` adds page/table/image boundaries, and `chunk-markers-ragflux-like` also adds list boundaries for migration comparison. Use `--output` for non-destructive writes; `--write` is required for in-place rewrites.
- `doc_manifest.json` uses `source_root: "."`, so downstream `ragflow-kb-build` can consume it after the handoff directory moves.
- `quality_gate.status` is written into `doc_manifest.json`; `ragflow-kb-build` blocks `BLOCKED` handoffs unless the user passes `--allow-blocked`.
- `quality_report.json` and process-backed `runtime_report.json` distinguish Markdown and HTML table counts; formal rich handoffs include HTML `<table>` entries in `retrieval_hints.json.table_artifacts`.
- Use `--strict` when skipped files should fail the run.
- Use `backend probe` before live conversion to classify backends as `available`, `missing`, `wrong_protocol`, `timeout`, or `not_configured`. It can emit `--redaction-report`, does not convert files, and endpoint checks require explicit `--network-check`.
- Use `backend warmup --fixture <tiny-file>` when the user has approved a small converter fixture and wants to run one bounded conversion readiness check. Add `--fail-on-failed` for CI gates.
- Image inputs fall back to Markdown with the source image copied into `documents/images/` when OCR/conversion is unavailable; this sets `quality_gate.status` to `PASS_WITH_REVIEW`. Use `--no-image-fallback` to skip that behavior.
- For formal MinerU FastAPI ingestion, use `--mineru-asset-mode markdown_assets` or `mineru.asset_mode: markdown_assets` so Markdown image references are backed by local `documents/images/...` files. Hash-like MinerU image names are rewritten to readable semantic filenames in the final handoff. Keep `markdown_only` for fast text-only preview.
- `runtime_report.json` records conversion/pipeline stage timings with standardized stage/category labels, cold/warm MinerU execution context, process/remote attempts, timeout/resource failure classifications, and measurable asset materialization timing. Use `--runtime-report-md` for a Markdown copy rendered from the same JSON payload.
- Use `inspect` to regenerate a quality report from an existing handoff.
- Use `segment-plan` before splitting long Markdown; use `split` when the user wants materialized `segments/*.md` that can be ingested as an ordinary Markdown directory. Add `--manifest-output` when downstream build should consume the materialized segments through a generated `doc_manifest.json`. For large split jobs, add `--checkpoint` plus `--batch-size`, then rerun with `--resume` until `checkpoint.completed` is true.
- The `mineru-cli` backend runs a local MinerU executable as `mineru -b <backend> -p <source> -o <temp-output>` and reads the Markdown file it produces. Set the path with `MINERU_CLI_PATH`, `mineru.cli_path`, or `--mineru-cli-path`; default CLI backend is `pipeline`.
- The `mineru` and `mineru-agent` backends use the Agent parsing API shape: create parse task at `/parse/file`, upload to signed URL, poll `/parse/{task_id}`, then download Markdown.
- The `mineru-fastapi` backend uses MinerU 3.2+ protocol version 2: submit multipart files to `/tasks`, poll `/tasks/{task_id}`, then read Markdown from `/tasks/{task_id}/result`.
- The `mineru-v4` and `mineru-platform` backends use the MinerU v4 platform-compatible protocol: request upload URLs at `/api/v4/file-urls/batch`, upload local files with `PUT`, poll `/api/v4/extract-results/batch/{batch_id}`, then extract Markdown and optional safe assets from `full_zip_url`. The public `https://mineru.net` service is the official example endpoint, not the only supported domain.
- The `mineru-sync` and `mineru-local` backends are legacy compatibility paths for synchronous multipart `/parse` services. They expect Markdown text or JSON containing `markdown`, `content`, `text`, `result`, or `markdown_url`.
- The remote backend expects JSON with `filename` and base64 `content_base64`, and returns `markdown` or `content`.
