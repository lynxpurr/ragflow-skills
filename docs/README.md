---
doc_type: index
topic: document-index
status: active
created: 2026-08-03
updated: 2026-08-03
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

- [Document lifecycle spec](specs/2026-08-02-document-lifecycle-and-spec-archive-design.md) - approved design; Gate 0 is closed.
- [Wave 1 implementation plan](plans/2026-08-03-document-lifecycle-and-spec-archive-implementation-plan.md) - Wave 1 was executed, its targeted revision was owner-accepted, and Wave 1 is complete;
  it did not authorize Wave 2, and the plan/spec lifecycle state and registry adoption
  have not been transitioned. `implementation_authority=false`.
- [Wave 2 successor plan](plans/2026-08-03-document-lifecycle-and-spec-archive-wave-2-implementation-plan.md) - proposed, non-authoritative plan file for 18 historical moves in Waves 2A-2C;
  external owner authority has completed all 18 files across Waves 2A-2C, while all 10
  Wave 2D candidates remain blocked. `implementation_authority=false`.
- `docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md` - separate proposed track; not part of document-governance Wave 1.

## Active And Gated Owners

The registry records 13 active, gated, or proposed owners at stable paths. Load an owner
only when the current task names its topic. Unchecked evidence or adapter rows do not
create live or implementation authority.

## Durable References

The 12 approved reference candidates remain at their current paths during Wave 1. They
are non-authoritative guidance and are not moved until a separately approved Wave 3 plan.

## Historical Candidates

Waves 2A-2C have archived 18 of the 28 approved historical candidates. The remaining 10
are the blocked Wave 2D candidates and stay at their current paths. Wave 2 remains
unadopted, and archived documents create no current authority.

## Authoring

- Specs: `docs/specs/README.md` and `docs/specs/TEMPLATE.md`.
- Plans: `docs/plans/README.md` and `docs/plans/TEMPLATE.md`.
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
