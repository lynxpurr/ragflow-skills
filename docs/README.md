---
doc_type: index
topic: document-index
status: active
created: 2026-08-03
updated: 2026-08-05
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Documentation

This file is the sole default entrypoint for repository documentation. Documents classify
and explain work; they do not independently authorize network access, credentials, live
operations, mutation, staging, commit, push, L3, Stage 8C, or L4.

## Current Roadmap

- [Development roadmap](03-development-plan.md) - current priorities and gated backlog.

## Controlling Governance Work

- [Document lifecycle spec](specs/2026-08-02-document-lifecycle-and-spec-archive-design.md) - active lifecycle policy; Gate 0 is closed.
- [Wave 1 implementation plan](plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md) - implemented; `implementation_authority=false`.
- [Wave 2 successor plan](plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md) - Waves 2A-2C complete; Wave 2D gated; `implementation_authority=false`.
- [Wave 3 successor plan](plans/2026-08-03-document-lifecycle-and-spec-archive-wave-3-implementation-plan.md) - Waves 3A-3B complete; `docs/16` and `docs/43` gated; `implementation_authority=false`.
- [Wave 4 successor plan](plans/2026-08-04-document-lifecycle-and-spec-archive-wave-4-implementation-plan.md) - implemented, committed, and pushed; `implementation_authority=false`.
- [Wave 5 successor plan](plans/2026-08-04-document-lifecycle-and-spec-archive-wave-5-implementation-plan.md) - adoption implemented; final validation passed; `implementation_authority=false`.
- `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md` - separate approved track; not part of document-governance Wave 1; `implementation_authority=false`.

## Active, Approved, And Gated Owners

The registry records 13 active, approved, or gated owners at stable paths. Load an owner
only when the current task names its topic. Unchecked evidence or adapter rows do not
create live or implementation authority.

## Durable References

Wave 3A normalized eight durable references under [`docs/reference/`](reference/README.md),
archived the superseded architecture snapshot, and added a concise current architecture
reference. Wave 3B archived the completed adaptive-pipeline record after current maintainer
guidance moved to its public skill sources. `docs/16-system-closeout-report.md` and
`docs/43-agent-session-handoff-lessons.md` remain deferred at their current paths.

## Historical Candidates

The archive records 20 migrations: 18 historical-candidate moves from Waves 2A-2C, the
Wave 3A architecture snapshot, and the Wave 3B adaptive-pipeline record. All 10 blocked
Wave 2D candidates stay at their current paths. The registry is adopted for new work, and
archived documents create no current authority.

## Authoring

- Specs: `docs/specs/README.md` and `docs/specs/TEMPLATE.md`.
- Plans: `docs/plans/README.md` and `docs/plans/TEMPLATE.md`.
- Sanitized evidence: `docs/evidence/README.md`.
- Durable references: `docs/reference/README.md`.
- Archive index: `docs/archive/README.md`.
- Machine-readable registry: `docs/document-registry.json`.

## Validation

Run from the repository root:

```bash
python3 tools/document_lifecycle_check.py
git diff --check
python3 tools/release_hygiene_check.py
```

The lifecycle checker is local and deterministic. It is a maintainer/release gate, not a
public skill command or a source of operational authority.
