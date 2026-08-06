---
doc_type: template
topic: plan-template
status: reference
created: 2026-08-03
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/plans/README.md
supersedes: []
superseded_by: null
related: []
---

# Implementation Plan Template

Create a new file under `docs/plans/` with compliant frontmatter followed by the required
implementation-plan header.

```yaml
---
doc_type: plan
topic: short-stable-topic-id
status: proposed
created: YYYY-MM-DD
updated: YYYY-MM-DD
canonical: false
implementation_authority: false
owner_spec: docs/specs/YYYY-MM-DD-approved-topic-design.md
supersedes: []
superseded_by: null
related: []
---
```

```markdown
# Literal Feature Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One externally observable outcome.

**Architecture:** Two or three sentences describing boundaries and data flow.

**Tech Stack:** Exact languages, libraries, and test framework.

---

### Task 1: Literal Component Name

**Files:**

- Create: `exact/path`
- Modify: `exact/path`
- Test: `exact/path`

- [ ] **Step 1: Write the complete failing test**
- [ ] **Step 2: Run the exact test and verify the expected failure**
- [ ] **Step 3: Write the complete minimal implementation**
- [ ] **Step 4: Run focused and broader validation**
- [ ] **Step 5: Stop at the named owner checkpoint**

## Rollback

## Stop Conditions
```

Do not leave unresolved design choices or placeholder implementation steps in an approved
plan.
