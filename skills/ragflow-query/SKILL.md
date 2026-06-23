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
python scripts/query.py list-kbs --routing-config ./templates/routing-config.example.json
python scripts/query.py route "Which API configuration should I use?" --routing-config ./templates/routing-config.example.json --json
python scripts/query.py route-test --routing-config ./templates/routing-config.example.json --queries ./templates/route-test-queries.example.json --report-md ./run/route_test.md
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --mode auto --routing-config ./routing-config.json --json
python scripts/query.py --config /path/to/ragflow-config.local.yaml ask "Question" --kb-manifest ./kb_manifest.json --mode agentic --host-assisted --json --trace-json ./run/query_trace.json --trace-md ./run/query_trace.md
python scripts/query.py audit-citations --query-output ./run/query.json --answer-file ./run/answer.md --report-json ./run/citation_audit.json --report-md ./run/citation_audit.md
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- CLI mode is the v1 interface for Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent tools.
- `--mode auto` uses `--routing-config` or `RAGFLOW_ROUTING_CONFIG` when no explicit `--dataset-id`, `--kb`, or `--kb-manifest` is provided; otherwise it falls back to direct retrieval.
- Routing config is user-owned and deterministic. Use `list-kbs`, `route`, and `route-test` to inspect it before live retrieval.
- `--mode agentic --host-assisted` still retrieves from RAGFlow; the host agent performs final synthesis from returned evidence.
- `ask` returns deterministic evidence weights and can write `--trace-json` / `--trace-md` for host-agent debugging.
- Use `audit-citations` after host synthesis to check simple numeric citations like `[1]` against retrieved evidence.
- See `templates/host-assisted-response.example.json`, `templates/query-trace.example.json`, and `templates/citation-audit.example.json` for expected payload shapes.
- Release artifacts are smoke-tested against a fake RAGFlow endpoint for both direct and host-assisted query paths.
- For v1, agentic mode means host-assisted evidence return only.
- Script-owned agentic planning/synthesis is deferred.
- `serve` is deferred; use CLI mode for v1.
