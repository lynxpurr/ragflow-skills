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
python scripts/build.py --config /path/to/ragflow-config.local.yaml --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project --profile ./templates/default-zh-512.json
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project --profile ./templates/default-en-768.json --dry-run --json
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project --profile ./templates/default-en-768.json --allow-blocked
python scripts/build.py inspect-handoff --handoff ./handoff --report-md ./run/handoff_inspection.md
python scripts/append.py --kb-manifest ./run/kb_manifest.json --input ./new-markdown --output ./run/append_plan.json
python scripts/append.py --kb-manifest ./run/kb_manifest.json --input ./new-markdown --live-preview --config /path/to/ragflow-config.local.yaml
python scripts/append.py --kb-manifest ./run/kb_manifest.json --input ./new-markdown --execute --config /path/to/ragflow-config.local.yaml
python scripts/cleanup.py --kb-manifest ./run/kb_manifest.json --output ./run/cleanup_plan.json
python scripts/cleanup.py --kb-manifest ./run/kb_manifest.json --execute --confirm-dataset-id DATASET_ID --confirm-kb-name kb:project --config /path/to/ragflow-config.local.yaml
python scripts/probe.py --config /path/to/ragflow-config.local.yaml --report-md ./run/ragflow_probe.md
python scripts/diagnose.py --kb-manifest ./run/kb_manifest.json --live --report-md ./run/diagnostic.md
python scripts/inspect_kb.py --kb-manifest ./run/kb_manifest.json
python scripts/profile.py lint --profile ./templates/default-en-768.json --report-md ./run/profile_lint.md
python scripts/profile.py explain --profile ./templates/default-zh-512.json
python scripts/profile.py recommend --language en --doc-type manual --output ./run/recommended-profile.json
python scripts/profile.py compare --report ./run/profile-a-validation.json --report ./run/profile-b-validation.json --report-md ./run/profile_compare.md
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level regression --queries ./templates/validation-queries.example.json --report-md ./run/validation.md
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level benchmark --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark.md
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- `build.py` creates the dataset, uploads Markdown, triggers parse, waits for parse completion by default, and emits `kb_manifest.json`.
- When a `doc_manifest.json` contains `quality_gate.status: BLOCKED`, `build.py` refuses to upload by default. Use `--allow-blocked` only after the user explicitly accepts the risk.
- Use `--dry-run` to validate local inputs without touching RAGFlow; dry-run prints JSON and does not write `kb_manifest.json`.
- Use `--no-wait` only when the host platform should continue while RAGFlow parses asynchronously.
- Use `inspect-handoff` before upload when a `ragflow-doc-to-md package --rich` handoff includes optional sidecars.
- Use `append.py` without `--execute` first; it creates an append plan and does not mutate RAGFlow. `--execute` uploads only planned new files and parses only the newly uploaded document IDs.
- Use `cleanup.py` without `--execute` first; deletion requires `--execute`, an exact `--confirm-dataset-id`, and the matching `--confirm-kb-name` when the name is known.
- Use `probe.py` to check safe RAGFlow API compatibility before live build operations.
- Use `diagnose.py` to explain manifest, parse-state, duplicate-name, short-ID, and zero-chunk symptoms without private database access.
- Use `profile.py lint/explain/recommend/compare` to review chunk profiles before upload and compare validation reports after profile experiments.
- `validate.py` supports `smoke`, `regression`, and `benchmark`; regression requires a query set, and benchmark requires both a query set and qrels.
- Query sets are small JSON files with `question`, optional `min_chunks`, `expected_terms`, and `expected_documents`.
- Benchmark qrels are small JSON files mapping query IDs to relevant documents/chunks. Benchmark reports include hit rate, MRR, precision@k, recall@k, nDCG@k, MAP@k, empty-result rate, query-type breakdown, optional gate checks, and optional baseline deltas.
