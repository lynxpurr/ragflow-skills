---
doc_type: reference
topic: evidence-authoring-guide
status: reference
created: 2026-08-04
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Evidence Authoring Guide

New outcome evidence belongs in `docs/evidence/` only when it is sanitized, durable, and
owned by a registered spec or plan. Record observable outcomes, validation class, and
residual risk. Do not include credentials, private endpoints, machine-specific paths,
live identifiers, raw responses, raw chunks, or temporary run locations.

Evidence documents use `doc_type: evidence`, `canonical: false`,
`implementation_authority: false`, and an `owner_spec` naming their registered spec or
plan. Evidence records results; they do not authorize implementation or live operations.
