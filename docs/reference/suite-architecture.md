---
doc_type: reference
topic: suite-architecture
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: ["docs/archive/2026/specs/02-architecture-design.md"]
superseded_by: null
related: []
---

# RAGFlow Skill Suite Architecture

The public suite has three self-contained skills and one shared runtime:

| Component | Owns | Does not own |
| --- | --- | --- |
| `ragflow-doc-to-md` | source inspection, conversion, Markdown handoff, and document-side quality evidence | RAGFlow dataset mutation or answer synthesis |
| `ragflow-kb-build` | handoff inspection, profiles, gated dataset build, retrieval validation, and cleanup planning | raw-document conversion or final answer generation |
| `ragflow-query` | routing, retrieval, evidence, diagnostics, and host-assisted answer support | KB creation or default script-owned synthesis |
| `ragflow-skill-runtime` | shared config, auth, HTTP, manifests, sanitization, and workflow helpers | public skill discovery or maintainer-only policy |

Source lives under `skills/` and `packages/ragflow-skill-runtime/src/`. Release builds
vendor the shared runtime into each skill; `dist/` and `release-artifacts/` are generated
products and are never edited as source.

Skills exchange JSON-first manifests and reports rather than importing each other.
Network, credentials, live mutation, and script-owned model execution remain explicit,
gated choices. Default tests and smoke paths use deterministic fixtures and no network.

Use these references for operational detail:

- `docs/reference/cli-agent-integration.md` for host configuration and invocation;
- `docs/reference/release-hardening.md` for release validation;
- `docs/reference/cross-platform-smoke.md` for supported no-network platform profiles;
- the public `SKILL.md` and bundled `references/` files for each skill's current command contract.

Historical design evolution remains in
`docs/archive/2026/specs/02-architecture-design.md`; it creates no current authority.
