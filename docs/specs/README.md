---
doc_type: reference
topic: spec-authoring-guide
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Spec Authoring Guide

A spec owns one coherent problem and defines intended behavior, constraints, migration,
rollback, validation, acceptance criteria, and decisions. It does not contain an
implementation checklist or grant live authority.

New specs use `docs/specs/TEMPLATE.md`. A spec starts as `proposed`; owner approval is
required before an implementation plan may be prepared. Only an approved or active spec
plus its linked plan can participate in implementation authorization.

Do not place credentials, private endpoints, private paths, live identifiers, raw
responses, or raw chunks in metadata or public body text.
