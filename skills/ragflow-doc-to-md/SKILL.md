---
name: ragflow-doc-to-md
description: Convert raw documents into Markdown handoff bundles for portable RAGFlow ingestion. Use when Codex needs to turn PDF, Office, HTML, TXT, or existing Markdown inputs into normalized Markdown plus a thin manifest for downstream KB build workflows.
---

# RAGFlow Doc To MD

Use scripts in this skill to produce Markdown handoff directories that can be consumed by `ragflow-kb-build`.

- Prefer passthrough mode when the input is already Markdown.
- Prefer local converters only when they are present.
- Fall back to a remote conversion backend when local tools are unavailable.
- Always emit a `doc_manifest.json` with source paths, Markdown paths, and warnings.
