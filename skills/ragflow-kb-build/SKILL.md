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
python scripts/build.py model-providers probe --config /path/to/ragflow-config.local.yaml --embedding-model bge-m3 --rerank-model bge-reranker --embedding-adapter-url https://embedding.example/v1/embeddings --rerank-adapter-url https://rerank.example/rerank --report-md ./run/model_provider_probe.md --redaction-report ./run/model_provider_redaction.json --json
python scripts/build.py inspect-handoff --handoff ./handoff --report-md ./run/handoff_inspection.md
python scripts/build.py metadata generate-template --doc-manifest ./handoff/doc_manifest.json --output ./run/metadata.template.json
python scripts/build.py metadata lint --metadata ./run/metadata.template.json --report-md ./run/metadata_lint.md
python scripts/build.py metadata merge --doc-manifest ./handoff/doc_manifest.json --handoff-metadata ./handoff/metadata.json --metadata ./run/metadata.template.json --output ./run/metadata.merged.json
python scripts/build.py tagset generate-template --output ./run/tagset.template.json
python scripts/build.py tagset lint --tagset ./run/tagset.template.json --report-md ./run/tagset_lint.md
python scripts/build.py tagset export --tagset ./run/tagset.template.json --format csv --output ./run/tagset.csv
python scripts/build.py tagset report --tagset ./run/tagset.template.json --metadata ./run/metadata.merged.json --report-md ./run/tagset_report.md
python scripts/build.py benchmark import --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --output ./run/benchmark
python scripts/build.py benchmark import --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --output ./run/benchmark --checkpoint ./run/benchmark-import.checkpoint.json --batch-size 25
python scripts/build.py benchmark import --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --output ./run/benchmark --checkpoint ./run/benchmark-import.checkpoint.json --resume --batch-size 25
python scripts/build.py benchmark preflight --manifest ./run/benchmark/manifest.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_preflight.md
python scripts/build.py benchmark sample --manifest ./run/benchmark/manifest.json --output ./run/benchmark-sample --size 25 --strategy stratified --seed 7 --report-md ./run/benchmark_sample.md
python scripts/build.py benchmark summarize --report ./run/benchmark_report.json --report-md ./run/benchmark_summary.md
python scripts/build.py benchmark gate --report ./run/benchmark_report.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_gate.md
python scripts/build.py benchmark trend --report ./run/benchmark_report.json --baseline-report ./run/baseline_benchmark_report.json --gate-config ./templates/benchmark-gate.example.json --report-md ./run/benchmark_trend.md
python scripts/build.py benchmark delta --report ./run/benchmark_report.json --baseline-report ./run/baseline_benchmark_report.json --report-md ./run/benchmark_delta.md
python scripts/build.py benchmark suggest --report ./run/benchmark_report.json --baseline-report ./run/baseline_benchmark_report.json --gate-config ./templates/benchmark-gate.example.json --current-top-k 3 --current-similarity-threshold 0.25 --report-md ./run/benchmark_suggestions.md
python scripts/build.py snapshot-chunks --input ./run/benchmark_report.json --output ./run/chunk_snapshot.json --report-md ./run/chunk_snapshot.md
python scripts/build.py suppression-report --report ./run/benchmark_report.json --tagset ./run/tagset.template.json --report-md ./run/suppression_report.md
python scripts/build.py qa generate --source-dir ./handoff --output ./run/benchmark/qa.generated.json --count 20 --report-md ./run/qa_generate.md
python scripts/build.py qa validate --qa ./run/benchmark/qa.json --source-dir ./handoff --report-md ./run/qa_validate.md
python scripts/build.py qa map-evidence --qa ./run/benchmark/qa.json --chunk-snapshot ./run/chunk_snapshot.json --output ./run/qa_evidence_map.json --report-md ./run/qa_evidence_map.md
python scripts/build.py segment-metadata report --chunk-snapshot ./run/chunk_snapshot.json --metadata ./run/metadata.merged.json --segmentation-plan ./run/segmentation_plan.json --report-md ./run/segment_metadata.md
python scripts/build.py topology advise --doc-manifest ./handoff/doc_manifest.json --kb-name kb:example --metadata ./run/metadata.merged.json --retrieval-hints ./handoff/retrieval_hints.json --future-growth high --output ./run/kb_topology_advice.json --report-md ./run/kb_topology_advice.md --json
python scripts/build.py topology split-plan --doc-manifest ./handoff/doc_manifest.json --kb-name kb:example --metadata ./run/metadata.merged.json --retrieval-hints ./handoff/retrieval_hints.json --output ./run/kb_split_plan.json --report-md ./run/kb_split_plan.md --json
python scripts/build.py activation-plan --kb-manifest ./run/kb_manifest.json --doc-manifest ./handoff/doc_manifest.json --route-config ./routing.json --retrieval-hints ./handoff/retrieval_hints.json --chunk-snapshot ./run/chunk_snapshot.json --route-tests ./route_tests.json --output ./run/kb_activation_plan.json --report-md ./run/kb_activation_plan.md --json
python scripts/build.py parse-report --kb-manifest ./run/kb_manifest.json --documents-json ./run/ragflow_documents.json --parse-log ./run/parse.log --profile ./profiles/default.json --report-json ./run/parse_report.json --report-md ./run/parse_report.md --json
python scripts/build.py health-report --kb-manifest ./run/kb_manifest.json --parse-report ./run/parse_report.json --activation-plan ./run/kb_activation_plan.json --expected-embedding-model bge-m3 --report-json ./run/kb_health_report.json --report-md ./run/kb_health_report.md --json
python scripts/build.py optimize --plan-only --doc-manifest ./handoff/doc_manifest.json --kb-name kb:example --profile ./profiles/default.json --recommendation en:manual --benchmark-manifest ./run/benchmark/manifest.json --output ./run/optimization_plan.json --report-md ./run/optimization_plan.md --command-manifest-output ./run/optimization_command_manifest.json
python scripts/build.py optimize --execute --validate-benchmark --doc-manifest ./handoff/doc_manifest.json --kb-name kb:example --profile ./profiles/default.json --benchmark-manifest ./run/benchmark/manifest.json --run-id reviewed-run --confirm-live-build --confirm-kb-name kb:example --confirm-run-id reviewed-run --output ./run/optimization_execute_plan.json
python scripts/build.py optimize summarize --plan ./run/optimization_plan.json --output ./run/profile_experiment_results.json --report-md ./run/best_profile_report.md
python scripts/build.py optimize cleanup-plan --plan ./run/optimization_plan.json --output ./run/cleanup_plan.json --report-md ./run/cleanup_plan.md
python scripts/build.py optimize cleanup-execute --cleanup-plan ./run/cleanup_plan.json --execute --confirm-dataset-id DATASET_ID --confirm-kb-name kb:example__opt__reviewed-run__default --output ./run/cleanup_execution_report.json
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
python scripts/profile.py experiment --base-profile ./templates/default-en-768.json --set auto_keywords=0,3 --set auto_questions=0,2 --set retrieval.top_k=3,5 --candidate-set ./run/candidate_profile_set.json --report-md ./run/profile_experiment_matrix.md
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level regression --queries ./templates/validation-queries.example.json --report-md ./run/validation.md
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level benchmark --queries ./templates/benchmark-queries.example.json --qrels ./templates/qrels.example.json --chunk-snapshot ./run/chunk_snapshot.json --gate-config ./templates/benchmark-gate.example.json --include-raw --report-md ./run/benchmark.md
```

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- `build.py` creates the dataset, uploads Markdown, triggers parse, waits for parse completion by default, and emits `kb_manifest.json`.
- When a `doc_manifest.json` contains `quality_gate.status: BLOCKED`, `build.py` refuses to upload by default. Use `--allow-blocked` only after the user explicitly accepts the risk.
- Use `--dry-run` to validate local inputs without touching RAGFlow; dry-run prints JSON and does not write `kb_manifest.json`.
- Use `--no-wait` only when the host platform should continue while RAGFlow parses asynchronously.
- Use `model-providers probe` before live builds to check read-only RAGFlow model-provider endpoints, optional expected embedding/rerank model names, explicit adapter empty-input request shapes, and optional `--redaction-report` sidecars without creating datasets.
- Use `inspect-handoff` before upload when a `ragflow-doc-to-md package --rich` handoff includes optional sidecars.
- Use `metadata` and `tagset` subcommands to prepare advisory public metadata and tag reports offline. Metadata summaries can be attached to build reports with `--metadata`; default upload behavior is unchanged.
- Use `benchmark import/sample/preflight/summarize/gate` and `snapshot-chunks` for offline benchmark lifecycle checks around `validate.py --level benchmark`; these commands do not touch RAGFlow. `benchmark import --checkpoint --batch-size ...` can be resumed with `--resume` when normalizing large local query/qrel sets.
- Benchmark summarize/gate/trend/delta reports include deterministic root-cause hints for coverage, ranking, pollution, grounding, citation, abstention, and cost/latency regressions when matching metrics are present.
- Use `benchmark suggest` to derive conservative `top_k` and `similarity_threshold` experiment suggestions from benchmark metrics, optional baseline deltas, and optional gate thresholds.
- Use `suppression-report` on validation or benchmark reports to review bridge-term, source-boundary, allowed-tag, and unexpected-tag candidates. Run benchmark validation with `--include-raw --max-report-chunks ...` when tag localization needs raw chunk tags; raw payloads are opt-in, and suppression reports are advisory only.
- Use `qa generate` to create a deterministic, offline grounded QA scaffold from exact source spans; it does not call an LLM or mutate RAGFlow.
- Use `qa validate` before feeding generated QA into benchmark gates; it checks required questions, answers, evidence spans, and exact source-span grounding when `--sources` or `--source-dir` is provided.
- Use `qa map-evidence` after `snapshot-chunks` to map exact QA evidence spans onto chunk snapshot IDs and stable hashes for strict `expected_chunks` qrels; the report includes deterministic mapping confidence and mapped chunk coverage.
- Use `segment-metadata report` to measure document metadata and segment provenance coverage in chunk snapshots before relying on segment-aware benchmark analysis.
- Use `topology advise` before upload when deciding whether a corpus should become a new KB, merge with an existing route, or be reviewed for splitting; it is advisory only and does not edit RAGFlow or routing config.
- Use `topology split-plan` to turn split-review signals into sidecar KB grouping suggestions and boundary route-test questions before creating separate KBs.
- Use `activation-plan` after build to review content, chunks, route registration, hints, optional centroids, and route-test readiness without editing route config.
- Use `parse-report` with local status/log/profile sidecars to review parse states, stale counts, slow phases, and expensive parser settings; it does not call RAGFlow or repair DB/Redis/Docker/system services.
- Use `health-report` to aggregate local KB manifests, parse reports, and activation plans into embedding-model, chunk-completeness, parse-state, and route-readiness risks without live calls or private repairs. Add `--expected-embedding-model` to warn when a built KB needs rebuild or re-parse after a model change.
- Use `optimize --plan-only` to load candidate profiles, resolve benchmark artifacts, lint candidates, and plan disposable KB experiment names without creating or deleting anything in RAGFlow; add `--command-manifest-output` to write a dry-run review manifest of the disposable build, validation, diagnostic, and cleanup-preview commands.
- Use `optimize --execute` only after reviewing the command manifest; it builds selected disposable candidate KBs and writes retained candidate `kb_manifest.json` files. Add `--validate-benchmark` to run benchmark validation for each built candidate and write retained validation reports. It requires `--confirm-live-build`, exact `--confirm-kb-name`, and exact `--confirm-run-id`.
- Use `optimize summarize` after candidate validation reports exist; it ranks profile results and writes a best-profile report without building or validating live KBs. Failed, missing, or zero-chunk validation results trigger local non-live diagnostics from candidate manifests when available.
- Use `optimize cleanup-plan` after planning or experiment builds to produce a non-mutating aggregate cleanup plan; ready targets include exact `cleanup.py --execute --confirm-dataset-id ... --confirm-kb-name ...` commands, while missing manifests remain pending.
- Use `optimize cleanup-execute` only after reviewing `cleanup-plan`; it deletes every ready target in the aggregate cleanup plan and requires repeated exact `--confirm-dataset-id` plus matching `--confirm-kb-name` values for all ready targets.
- Use `append.py` without `--execute` first; it creates an append plan and does not mutate RAGFlow. `--execute` uploads only planned new files and parses only the newly uploaded document IDs.
- Use `cleanup.py` without `--execute` first; deletion requires `--execute`, an exact `--confirm-dataset-id`, and the matching `--confirm-kb-name` when the name is known.
- Use `probe.py` to check safe RAGFlow API compatibility before live build operations.
- Use `diagnose.py` to explain manifest, parse-state, duplicate-name, short-ID, and zero-chunk symptoms without private database access.
- Use `profile.py lint/explain/recommend/compare` to review chunk profiles before upload and compare validation reports after profile experiments.
- Use `profile.py experiment` to expand an offline enrichment experiment matrix into a local candidate profile set for `optimize --profile-set`; it records retrieval settings and warns about slow or LLM-backed enrichment without touching RAGFlow.
- `profile.py compare` and `optimize summarize` surface latency, parse-time, empty-result, chunk-count, and benchmark quality metrics when existing validation reports provide them.
- `validate.py` supports `smoke`, `regression`, and `benchmark`; regression requires a query set, and benchmark requires both a query set and qrels.
- Query sets are small JSON files with `question`, optional `min_chunks`, `expected_terms`, and `expected_documents`.
- Benchmark qrels are small JSON files mapping query IDs to relevant documents/chunks; qrels can include `expected_chunks` that match live chunk IDs or stable chunk snapshot hashes, and query/qrel metadata can include expected or allowed tags for pollution diagnostics. Chunk snapshots include content/provenance coverage and per-document chunk distribution. Benchmark reports include hit rate, MRR, precision@k, recall@k, nDCG@k, MAP@k, empty-result rate, strict chunk recall when applicable, wrong-document/tag pollution metrics when metadata is present, query-type breakdown, optional gate checks, and optional baseline deltas.
