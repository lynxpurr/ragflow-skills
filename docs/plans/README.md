---
doc_type: reference
topic: plan-authoring-guide
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

# Plan Authoring Guide

An implementation plan links exactly one approved spec and contains exact files, ordered
tasks, complete code or document content, focused tests, validation, rollback, and stop
conditions. A plan must not silently expand its owning spec.

New plans use `docs/plans/TEMPLATE.md`. Plan approval and execution authority are separate:
`implementation_authority=false` remains the safe default, and staging, commit, push,
network, credentials, or live operations require explicit owner authority.
