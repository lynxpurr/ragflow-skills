---
name: ragflow-query
description: Unified direct and host-assisted agentic RAGFlow retrieval for portable agent platforms. Use when Codex needs to query one or more RAGFlow knowledge bases, choose direct retrieval, return evidence chunks, or produce host-assisted evidence for an outer agent to synthesize.
---

# RAGFlow Query

Use scripts in this skill to run `--mode auto|direct|agentic` retrieval against RAGFlow.

Commands:

```bash
python scripts/query.py --base-url https://ragflow.example.test --api-key "$RAGFLOW_API_KEY" ask "Question" --kb-manifest ./kb_manifest.json --mode direct --json
python scripts/query.py --base-url https://ragflow.example.test --api-key "$RAGFLOW_API_KEY" ask "Question" --kb-manifest ./kb_manifest.json --mode agentic --host-assisted --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --kb-manifest ./kb_manifest.json --mode direct --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --dataset-id ds-a --dataset-id ds-b --fusion rrf --json
python scripts/query.py rewrite "Question" --rewrite simple --report-json ./run/rewrite.json --report-md ./run/rewrite.md --json
python scripts/query.py intent classify "Compare runtime config versus metadata routing" --report-json ./run/intent.json --report-md ./run/intent.md --json
python scripts/query.py intent route "What about it?" --report-json ./run/intent_route.json --report-md ./run/intent_route.md --json
python scripts/query.py session inspect --session ./run/session.json --report-json ./run/session_inspect.json --report-md ./run/session_inspect.md --json
python scripts/query.py session enrich "What about it?" --session ./run/session.json --report-json ./run/session_enrich.json --report-md ./run/session_enrich.md --json
python scripts/query.py agentic-plan "Compare runtime configuration and metadata routing tradeoffs" --max-subqueries 3 --reflection-budget 1 --report-json ./run/agentic_plan.json --report-md ./run/agentic_plan.md --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml endpoint-report --endpoint embedding=http://vpn-endpoint.local:8080/v1 --report-json ./run/query_endpoint_report.json --report-md ./run/query_endpoint_report.md --redaction-report ./run/query_endpoint_redaction.json --json
python scripts/query.py ask "Question" --dataset-id ds-a --rewrite simple --multi-query ./fixtures/multi-query.json --trace-json ./run/query_trace.json --json
python scripts/query.py fusion-test --cases ./fixtures/fusion-test-cases.json --report-json ./run/fusion_test.json --report-md ./run/fusion_test.md --json
python scripts/query.py fallback-test --report-json ./run/fallback_test.json --report-md ./run/fallback_test.md --json
python scripts/query.py list-kbs --routing-config ./templates/routing-config.example.json
python scripts/query.py route "Which API configuration should I use?" --routing-config ./templates/routing-config.example.json --json
python scripts/query.py route "Which API configuration should I use?" --routing-config ./routing-config.json --centroid-index ./run/centroids.json --query-vector-json ./run/query_vector.json --json
python scripts/query.py route-test --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-md ./run/route_test.md
python scripts/query.py route-report --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-json ./run/route_report.json --report-md ./run/route_report.md
python scripts/query.py route-diagnose --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-json ./run/route_diagnose.json --report-md ./run/route_diagnose.md
python scripts/query.py route-activation-check --activation-plan ./run/kb_activation_plan.json --routing-config ./routing-config.json --queries ./templates/route-test-queries.example.json --report-json ./run/route_activation_check.json --report-md ./run/route_activation_check.md
python scripts/query.py assistant-profile recommend --assistant-profile ./handoff/assistant_profile.json --retrieval-hints ./handoff/retrieval_hints.json --report-json ./run/assistant_profile_recommendation.json --report-md ./run/assistant_profile_recommendation.md
python scripts/query.py centroid build --plan-only --kb-manifest ./kb_manifest.json --chunk-snapshot ./chunk_snapshot.json --index-output ./run/centroids.json --report-json ./run/centroid_plan.json --report-md ./run/centroid_plan.md --json
python scripts/query.py centroid build --kb-manifest ./kb_manifest.json --chunk-snapshot ./chunk_snapshot.embeddings.json --index-output ./run/centroids.json --checkpoint ./run/centroid.checkpoint.json --batch-size 64 --embedding-model text-embedding-3-small --embedding-dimension 1536 --report-json ./run/centroid_build.json --report-md ./run/centroid_build.md --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --mode auto --routing-config ./routing-config.json --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --kb-manifest ./kb_manifest.json --mode agentic --host-assisted --json --trace-json ./run/query_trace.json --trace-md ./run/query_trace.md
python scripts/query.py audit-citations --query-output ./run/query.json --answer-file ./run/answer.md --report-json ./run/citation_audit.json --report-md ./run/citation_audit.md
python scripts/query.py evaluate-answer --query-output ./run/query.json --answer-file ./run/answer.md --expected-term "known term" --require-citation --report-json ./run/answer_eval.json --report-md ./run/answer_eval.md --json
python scripts/query.py diagnose-result --query-output ./run/query.json --trace-json ./run/query_trace.json --citation-audit ./run/citation_audit.json --report-json ./run/query_diagnostic.json --report-md ./run/query_diagnostic.md
python scripts/query.py pollution-report --query-output ./run/query.json --expanded-term translated-term --report-json ./run/query_pollution.json --report-md ./run/query_pollution.md
python scripts/query.py rerank-ab --query-output ./run/query.json --rerank-json ./run/external_rerank.json --expected-term "known term" --report-json ./run/query_rerank_ab.json --report-md ./run/query_rerank_ab.md
python scripts/query.py cross-language-ab --baseline-output ./run/query_original.json --candidate-output ./run/query_translated.json --baseline-label original --candidate-label translated --report-json ./run/query_cross_language_ab.json --report-md ./run/query_cross_language_ab.md --json
python scripts/query.py fusion --query-output ./run/kb_a_query.json --query-output ./run/kb_b_query.json --report-json ./run/fusion.json --report-md ./run/fusion.md
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- CLI mode is the v1 interface for Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent tools.
- `--mode auto` uses `--routing-config` or `RAGFLOW_ROUTING_CONFIG` when no explicit `--dataset-id`, `--kb`, or `--kb-manifest` is provided; otherwise it falls back to direct retrieval.
- Routing config is user-owned and deterministic. Use `list-kbs`, `route`, `route-test`, `route-report`, `route-diagnose`, and `route-activation-check` to inspect it before live retrieval.
- Use `route-report` offline to review hint coverage, English hint coverage by KB/category, required route-test category gaps, ambiguous/low-confidence routes, short-hint word-boundary conflicts, substring conflicts, and per-KB `top_k` / `similarity_threshold` default coverage.
- `route-report` and `route-diagnose` warn when legacy/descriptive `kb_routing_hints` fields are present but ignored by the public routing schema; put active route hints in per-KB `hints`.
- Use `centroid build --plan-only` to review a user-owned centroid index plan from KB manifests or chunk snapshots. It does not call embedding APIs or write a centroid index.
- Use `centroid build` without `--plan-only` only with user-owned chunk snapshots that already contain `embedding`, `embedding_vector`, or `vector` fields. It processes at most `--batch-size` chunks per run, writes `--checkpoint` and `--index-output`, resumes with `--resume`, and does not call embedding APIs or mutate RAGFlow.
- `route`, `route-test`, `route-report`, `route-diagnose`, and `ask --mode auto` can use `--centroid-index` as a tie-breaker for equal positive hint scores. Provide `--query-vector-json` for single-query commands or per-query `query_vector` fields in route-test fixtures; the script does not generate embeddings.
- Route-test queries may set `expected_no_route: true` for negative/out-of-scope cases; this passes when no positive hint route is selected, even if a default KB fallback is present.
- Use `route-diagnose` offline to classify route-test failures as missing hints, missing KB config, priority conflicts, regex-order issues, acceptable ambiguity, or low-confidence fallback.
- Use `route-activation-check` offline with `kb_activation_plan_v1` to review route config registration, stale activation inputs, route-test coverage, and optional centroid alignment. It does not mutate route config or RAGFlow.
- Use `assistant-profile recommend` offline with rich-handoff `assistant_profile.json` and optional `retrieval_hints.json` to review assistant retrieval settings. It does not mutate RAGFlow assistant settings.
- `ask --fusion rrf` retrieves each selected dataset separately when multiple dataset IDs are present, then returns an offline fusion report and fused evidence order.
- `--mode agentic --host-assisted` builds a deterministic `ragflow_agentic_plan_v1`, executes bounded sub-query retrieval, and returns evidence plus `ragflow_agentic_trace_v1` cost/latency data and `ragflow_host_synthesis_contract_v1` citation policy for host synthesis. It does not call an LLM or synthesize an answer.
- `ask` returns deterministic evidence weights and can write `--trace-json` / `--trace-md` for host-agent debugging.
- `ask --json` includes `retrieval_status` plus a `ragflow_retrieval_status_v1` report so hosts can distinguish `success`, `empty`, `low_quality`, `needs_refinement`, `clarification`, `rejected`, `error`, `timeout`, and `partial`.
- Use `audit-citations` after host synthesis to check simple numeric citations like `[1]` against retrieved evidence.
- Use `evaluate-answer` after host synthesis for deterministic offline answer checks: required citations, citation reachability, unsupported uncited statements, expected terms, cited evidence score, and no-evidence abstention behavior. It does not call an LLM evaluator.
- Use `diagnose-result` to review weak retrieval, default routing, missing expected terms, and citation-audit findings from saved artifacts.
- Use `pollution-report` on saved `ask --json` outputs to review likely expansion/BM25 bridge-term pollution. It is offline and advisory; pass `--expanded-term` or `--expanded-terms-json` when translated or rewritten terms are available.
- Use `rerank-ab` on saved `ask --json` outputs and optional host-owned rerank JSON to compare RAGFlow order with a candidate ordering. It is offline; without `--rerank-json`, it uses deterministic evidence scores as the candidate order.
- Use `cross-language-ab` on saved original and translated/reconfigured `ask --json` outputs to compare zero-result rate, chunk-count delta, top-1 stability, top-similarity delta, and latency delta before changing defaults.
- Use `fusion` on multiple saved `ask --json` outputs to build an offline reciprocal-rank-fusion report with per-source rank contributions and deduplicated chunks.
- Use `fusion-test` on a cases file that points at saved query outputs to verify expected top chunks, expected terms, and minimum source contributions offline.
- Use `fallback-test` to run offline fixtures for LLM unavailable, malformed JSON, network timeout, partial failure, and direct retrieval fallback coverage; it reports fallback success-rate metrics without calling RAGFlow or an LLM.
- Use `rewrite` or `ask --rewrite simple|translate` for deterministic offline query planning; `hyde` is reserved for a host-owned LLM adapter.
- Use `intent classify` and `intent route` to classify `knowledge_query`, `comparison`, `clarification_needed`, and `out_of_scope` requests before retrieval. These commands are offline and include confidence plus low-confidence disclaimers.
- Use `session inspect` and `session enrich` with user-owned `ragflow_query_session_v1` JSON to bound recent context, detect short follow-ups/pronouns, and enrich queries without retrieval or LLM calls.
- Use `agentic-plan` to create a deterministic, non-executing plan for classification, bounded sub-query planning, optional reflection budget, and host-owned synthesis/citation policy. It does not retrieve, mutate RAGFlow, or call an LLM.
- Use `endpoint-report` before live query work to classify configured RAGFlow/LLM/extra endpoints as local, LAN, VPN/private, or public; it writes redacted URL summaries, can emit `--redaction-report`, and only runs reachability checks when `--network-check` is passed.
- Use `ask --multi-query` with a host-owned JSON file when you need to preserve multiple original/generated queries in the trace and retrieval payload.
- See `templates/host-assisted-response.example.json`, `templates/query-trace.example.json`, `templates/citation-audit.example.json`, and `templates/query-diagnostic.example.json` for expected payload shapes.
- Release artifacts are smoke-tested against a fake RAGFlow endpoint for both direct and host-assisted query paths.
- For v1, agentic mode means host-assisted evidence return only.
- Script-owned agentic synthesis is deferred.
- `serve` is deferred; use CLI mode for v1.
