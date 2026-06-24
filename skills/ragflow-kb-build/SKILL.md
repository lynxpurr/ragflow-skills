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
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --metadata ./run/metadata.merged.json --kb-name kb:project --profile ./templates/default-en-768.json --dry-run --json
python scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name kb:project --profile ./templates/default-en-768.json --allow-blocked
python scripts/build.py inspect-handoff --handoff ./handoff --report-md ./run/handoff_inspection.md
python scripts/build.py metadata generate-template --doc-manifest ./handoff/doc_manifest.json --output ./run/metadata.template.json
python scripts/build.py metadata lint --metadata ./run/metadata.template.json --report-md ./run/metadata_lint.md
python scripts/build.py metadata merge --doc-manifest ./handoff/doc_manifest.json --handoff-metadata ./handoff/metadata.json --metadata ./run/metadata.template.json --output ./run/metadata.merged.json
python scripts/build.py tagset generate-template --output ./run/tagset.template.json
python scripts/build.py tagset lint --tagset ./run/tagset.template.json --report-md ./run/tagset_lint.md
python scripts/build.py tagset export --tagset ./run/tagset.template.json --format csv --output ./run/tagset.csv
python scripts/build.py tagset report --tagset ./run/tagset.template.json --metadata ./run/metadata.merged.json --report-md ./run/tagset_report.md
python scripts/build.py benchmark import --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --output ./run/benchmark
python scripts/build.py benchmark preflight --manifest ./run/benchmark/manifest.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_preflight.md
python scripts/build.py benchmark sample --manifest ./run/benchmark/manifest.json --output ./run/benchmark-sample --size 25 --strategy stratified --seed 7 --report-md ./run/benchmark_sample.md
python scripts/build.py benchmark summarize --report ./run/benchmark_report.json --report-md ./run/benchmark_summary.md
python scripts/build.py benchmark gate --report ./run/benchmark_report.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_gate.md
python scripts/build.py benchmark trend --report ./run/benchmark_report.json --baseline-report ./run/baseline_benchmark_report.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_trend.md
python scripts/build.py benchmark delta --report ./run/benchmark_report.json --baseline-report ./run/baseline_benchmark_report.json --report-md ./run/benchmark_delta.md
python scripts/build.py snapshot-chunks --input ./run/benchmark_report.json --output ./run/chunk_snapshot.json --report-md ./run/chunk_snapshot.md
python scripts/build.py qa validate --qa ./run/benchmark/qa.json --source-dir ./handoff --report-md ./run/qa_validate.md
python scripts/build.py qa map-evidence --qa ./run/benchmark/qa.json --chunk-snapshot ./run/chunk_snapshot.json --output ./run/qa_evidence_map.json --report-md ./run/qa_evidence_map.md
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
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level benchmark --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --chunk-snapshot ./run/chunk_snapshot.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark.md
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- `build.py` creates the dataset, uploads Markdown, triggers parse, waits for parse completion by default, and emits `kb_manifest.json`.
- When a `doc_manifest.json` contains `quality_gate.status: BLOCKED`, `build.py` refuses to upload by default. Use `--allow-blocked` only after the user explicitly accepts the risk.
- Use `--dry-run` to validate local inputs without touching RAGFlow; dry-run prints JSON and does not write `kb_manifest.json`.
- Use `--no-wait` only when the host platform should continue while RAGFlow parses asynchronously.
- Use `inspect-handoff` before upload when a `ragflow-doc-to-md package --rich` handoff includes optional sidecars.
- Use `metadata` and `tagset` subcommands to prepare advisory public metadata and tag reports offline. Metadata summaries can be attached to build reports with `--metadata`; default upload behavior is unchanged.
- Use `benchmark import/sample/preflight/summarize/gate` and `snapshot-chunks` for offline benchmark lifecycle checks around `validate.py --level benchmark`; these commands do not touch RAGFlow.
- Benchmark summarize/gate/trend/delta reports include deterministic root-cause hints for coverage, ranking, pollution, grounding, citation, abstention, and cost/latency regressions when matching metrics are present.
- Use `qa validate` before feeding generated QA into benchmark gates; it checks required questions, answers, evidence spans, and exact source-span grounding when `--sources` or `--source-dir` is provided.
- Use `qa map-evidence` after `snapshot-chunks` to map exact QA evidence spans onto chunk snapshot IDs and stable hashes for strict `expected_chunks` qrels.
- Use `append.py` without `--execute` first; it creates an append plan and does not mutate RAGFlow. `--execute` uploads only planned new files and parses only the newly uploaded document IDs.
- Use `cleanup.py` without `--execute` first; deletion requires `--execute`, an exact `--confirm-dataset-id`, and the matching `--confirm-kb-name` when the name is known.
- Use `probe.py` to check safe RAGFlow API compatibility before live build operations.
- Use `diagnose.py` to explain manifest, parse-state, duplicate-name, short-ID, and zero-chunk symptoms without private database access.
- Use `profile.py lint/explain/recommend/compare` to review chunk profiles before upload and compare validation reports after profile experiments.
- `validate.py` supports `smoke`, `regression`, and `benchmark`; regression requires a query set, and benchmark requires both a query set and qrels.
- Query sets are small JSON files with `question`, optional `min_chunks`, `expected_terms`, and `expected_documents`.
- Benchmark qrels are small JSON files mapping query IDs to relevant documents/chunks; qrels can include `expected_chunks` that match live chunk IDs or stable chunk snapshot hashes. Benchmark reports include hit rate, MRR, precision@k, recall@k, nDCG@k, MAP@k, empty-result rate, strict chunk recall when applicable, query-type breakdown, optional gate checks, and optional baseline deltas.
