---
name: ragflow-skills
description: "Route document conversion, canonical source review, reviewed KB construction, retrieval, and answer-support checks across the four public RAGFlow skills. Use when Codex needs to select the shortest safe suite workflow before opening a child skill."
version: 1.0.1
author: Architect (Luca)
_updated: '2026-07-09'
license: MIT
metadata:
  hermes:
    tags: [ragflow, rag, document-pipeline, knowledge-base, mineru, markdown, chunking, regression-test]
    related_skills: [ragflow-doc-to-md, ragflow-canonical-review, ragflow-kb-build, ragflow-query]
---

# RAGFlow Skills

This suite routes document preparation, knowledge-base construction, and evidence
retrieval to four public skills. Select the smallest matching workflow; do not treat the
suite root as an operations manual.

## Intent routing

| User intent | Skill | Canonical workflow |
| --- | --- | --- |
| Convert source documents, or formalize reviewed Markdown without reconversion | `ragflow-doc-to-md` | Convert ordinary documents |
| Inspect a source and choose a deterministic conversion | `ragflow-doc-to-md` | Inspect and decide deterministically |
| Reconcile extracted Markdown with an exact source | `ragflow-canonical-review` | Review canonical source |
| Audit canonical allowlists, control files, and assets | `ragflow-canonical-review` | Audit canonical boundaries |
| Check a handoff before ingestion | `ragflow-kb-build` | Inspect a handoff |
| Validate build readiness without mutation | `ragflow-kb-build` | Validate build readiness without mutation |
| Build one reviewed KB | `ragflow-kb-build` | Build one reviewed KB |
| Validate retrieval quality | `ragflow-kb-build` | Validate retrieval quality |
| Inspect KB health or failure state | `ragflow-kb-build` | Inspect KB health |
| Clean up a disposable KB | `ragflow-kb-build` | Clean up a disposable KB |
| Retrieve evidence from one or more KBs | `ragflow-query` | Retrieve evidence |
| Review whether an answer is supported | `ragflow-query` | Review answer support |

If two workflows remain equally plausible and their side effects differ, ask one concise
clarifying question. Do not open advanced guidance merely to avoid asking.

## Normal sequence

1. Use `ragflow-doc-to-md` to convert raw documents or inspect conversion choices.
2. Use `ragflow-canonical-review` to reconcile the candidate with its source and accept canonical content.
3. Use `ragflow-doc-to-md pipeline --mode passthrough` to create a formal handoff.
4. Use `ragflow-kb-build` to inspect the handoff and run a dry-run.
5. Build only after explicit live approval, then validate and retain cleanup proof.
6. Use `ragflow-query` to retrieve evidence and review citations or answer support.

## Shared safety rules

- Run a dry-run before mutation and stop on `BLOCKED`, identity ambiguity, or missing
  authority.
- Require explicit approval for every live build, query using private configuration, or
  cleanup execution.
- Keep endpoints and credentials in a private config or host secret store, never in the
  skill directory or tracked output.
- Preview cleanup first; execute only with the exact dataset ID and matching KB name.
- Do not bypass a failed readiness result with raw API calls, guessed identifiers, or an
  unavailable helper.
- Load only the advanced reference named by an explicit request or a core-command finding.

## Public skills

- [RAGFlow Doc To MD](skills/ragflow-doc-to-md/SKILL.md)
- [RAGFlow Canonical Review](skills/ragflow-canonical-review/SKILL.md)
- [RAGFlow KB Build](skills/ragflow-kb-build/SKILL.md)
- [RAGFlow Query](skills/ragflow-query/SKILL.md)
