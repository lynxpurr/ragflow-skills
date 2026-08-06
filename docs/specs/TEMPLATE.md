---
doc_type: template
topic: spec-template
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/README.md
supersedes: []
superseded_by: null
related: []
---

# Spec Template

Create a new file under `docs/specs/` with the following structure. Replace the example
topic and dates with reviewed values before requesting approval.

```yaml
---
doc_type: spec
topic: short-stable-topic-id
status: proposed
created: YYYY-MM-DD
updated: YYYY-MM-DD
canonical: true
implementation_authority: false
supersedes: []
superseded_by: null
related: []
---
```

```markdown
# Literal Feature Or System Name

## Context

## Objective

## Non-Goals

## Requirements And Invariants

## Design

## Compatibility And Migration

## Failure Handling And Rollback

## Validation Strategy

## Acceptance Criteria

## Decision Log
```

A spec normally stays below 400 lines. Crossing 500 lines requires a decomposition note
or a decision-log justification.
