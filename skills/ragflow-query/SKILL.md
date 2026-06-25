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
python scripts/query.py ask "Question" --dataset-id ds-a --rewrite simple --multi-query ./fixtures/multi-query.json --trace-json ./run/query_trace.json --json
python scripts/query.py fusion-test --cases ./fixtures/fusion-test-cases.json --report-json ./run/fusion_test.json --report-md ./run/fusion_test.md --json
python scripts/query.py list-kbs --routing-config ./templates/routing-config.example.json
python scripts/query.py route "Which API configuration should I use?" --routing-config ./templates/routing-config.example.json --json
python scripts/query.py route-test --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-md ./run/route_test.md
python scripts/query.py route-report --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-json ./run/route_report.json --report-md ./run/route_report.md
python scripts/query.py route-diagnose --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-json ./run/route_diagnose.json --report-md ./run/route_diagnose.md
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --mode auto --routing-config ./routing-config.json --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --kb-manifest ./kb_manifest.json --mode agentic --host-assisted --json --trace-json ./run/query_trace.json --trace-md ./run/query_trace.md
python scripts/query.py audit-citations --query-output ./run/query.json --answer-file ./run/answer.md --report-json ./run/citation_audit.json --report-md ./run/citation_audit.md
python scripts/query.py diagnose-result --query-output ./run/query.json --trace-json ./run/query_trace.json --citation-audit ./run/citation_audit.json --report-json ./run/query_diagnostic.json --report-md ./run/query_diagnostic.md
python scripts/query.py pollution-report --query-output ./run/query.json --expanded-term translated-term --report-json ./run/query_pollution.json --report-md ./run/query_pollution.md
python scripts/query.py rerank-ab --query-output ./run/query.json --rerank-json ./run/external_rerank.json --expected-term "known term" --report-json ./run/query_rerank_ab.json --report-md ./run/query_rerank_ab.md
python scripts/query.py fusion --query-output ./run/kb_a_query.json --query-output ./run/kb_b_query.json --report-json ./run/fusion.json --report-md ./run/fusion.md
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- CLI mode is the v1 interface for Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent tools.
- `--mode auto` uses `--routing-config` or `RAGFLOW_ROUTING_CONFIG` when no explicit `--dataset-id`, `--kb`, or `--kb-manifest` is provided; otherwise it falls back to direct retrieval.
- Routing config is user-owned and deterministic. Use `list-kbs`, `route`, `route-test`, `route-report`, and `route-diagnose` to inspect it before live retrieval.
- Use `route-report` offline to review hint coverage, missing route tests, ambiguous/low-confidence routes, short-hint word-boundary risks, substring conflicts, and per-KB retrieval parameter coverage.
- Use `route-diagnose` offline to classify route-test failures as missing hints, missing KB config, priority conflicts, regex-order issues, acceptable ambiguity, or low-confidence fallback.
- `ask --fusion rrf` retrieves each selected dataset separately when multiple dataset IDs are present, then returns an offline fusion report and fused evidence order.
- `--mode agentic --host-assisted` still retrieves from RAGFlow; the host agent performs final synthesis from returned evidence.
- `ask` returns deterministic evidence weights and can write `--trace-json` / `--trace-md` for host-agent debugging.
- Use `audit-citations` after host synthesis to check simple numeric citations like `[1]` against retrieved evidence.
- Use `diagnose-result` to review weak retrieval, default routing, missing expected terms, and citation-audit findings from saved artifacts.
- Use `pollution-report` on saved `ask --json` outputs to review likely expansion/BM25 bridge-term pollution. It is offline and advisory; pass `--expanded-term` or `--expanded-terms-json` when translated or rewritten terms are available.
- Use `rerank-ab` on saved `ask --json` outputs and optional host-owned rerank JSON to compare RAGFlow order with a candidate ordering. It is offline; without `--rerank-json`, it uses deterministic evidence scores as the candidate order.
- Use `fusion` on multiple saved `ask --json` outputs to build an offline reciprocal-rank-fusion report with per-source rank contributions and deduplicated chunks.
- Use `fusion-test` on a cases file that points at saved query outputs to verify expected top chunks, expected terms, and minimum source contributions offline.
- Use `rewrite` or `ask --rewrite simple|translate` for deterministic offline query planning; `hyde` is reserved for a host-owned LLM adapter.
- Use `ask --multi-query` with a host-owned JSON file when you need to preserve multiple original/generated queries in the trace and retrieval payload.
- See `templates/host-assisted-response.example.json`, `templates/query-trace.example.json`, `templates/citation-audit.example.json`, and `templates/query-diagnostic.example.json` for expected payload shapes.
- Release artifacts are smoke-tested against a fake RAGFlow endpoint for both direct and host-assisted query paths.
- For v1, agentic mode means host-assisted evidence return only.
- Script-owned agentic planning/synthesis is deferred.
- `serve` is deferred; use CLI mode for v1.
