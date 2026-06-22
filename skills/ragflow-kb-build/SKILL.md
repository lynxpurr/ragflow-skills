---
name: ragflow-kb-build
description: Build and validate RAGFlow knowledge bases from Markdown handoff bundles. Use when Codex needs to upload Markdown documents into RAGFlow, apply chunking profiles, inspect parse status, or validate retrieval quality with smoke, regression, or benchmark checks.
---

# RAGFlow KB Build

Use scripts in this skill to create, inspect, and validate RAGFlow datasets from Markdown inputs.

- Consume `doc_manifest.json` or a Markdown directory.
- Emit `kb_manifest.json` after build.
- Keep validation as a first-class command.
- Avoid private or machine-specific assumptions.
