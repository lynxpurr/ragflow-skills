---
name: ragflow-query
description: Unified direct and agentic RAGFlow retrieval for portable agent platforms. Use when Codex needs to query one or more RAGFlow knowledge bases, choose between direct and agentic retrieval, return chunks or synthesized answers, or expose an optional local HTTP query service.
---

# RAGFlow Query

Use scripts in this skill to run `--mode auto|direct|agentic` retrieval against RAGFlow.

- Prefer CLI mode for Claude Code and SaaS sandboxes.
- Use host-assisted mode when the host agent should synthesize the final answer.
- Treat `serve` as optional local deployment support, not the default interface.
