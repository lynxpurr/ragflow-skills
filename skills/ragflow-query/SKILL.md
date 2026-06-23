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
```

Use `templates/ragflow-config.example.yaml` as the shared config template. Put the real config in a stable host-agent config path, such as Hermes or OpenClaw config storage, and point scripts to it with `RAGFLOW_CONFIG` or `--config`. Do not put real keys in the skill folder.

When a host agent should prepare config, run smoke checks, or perform end-to-end validation for the user, read `references/host-agent-setup.md` first. When an end user needs a copy-paste prompt to give their own host agent, use `references/user-onboarding-prompt.md`.

Notes:

- CLI mode is the v1 interface for Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent tools.
- `--mode auto` currently falls back to direct retrieval.
- `--mode agentic --host-assisted` still retrieves from RAGFlow; the host agent performs final synthesis from returned evidence.
- See `templates/host-assisted-response.example.json` for the expected evidence payload shape.
- Release artifacts are smoke-tested against a fake RAGFlow endpoint for both direct and host-assisted query paths.
- For v1, agentic mode means host-assisted evidence return only.
- Script-owned agentic planning/synthesis is deferred.
- `serve` is deferred; use CLI mode for v1.
