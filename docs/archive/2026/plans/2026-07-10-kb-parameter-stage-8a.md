---
doc_type: plan
topic: kb-parameter-stage-8a
status: historical
created: 2026-07-10
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
archived: 2026-08-03
historical_reason: completed
original_sha256: 945461f9366bc03ac83a58a8a2bedfbd9ded13900c996aa9719492c36ea1ad5a
---

> **Historical archive:** This document is immutable context and creates no current task,
> implementation, operational, network, credential, mutation, or live authority.

# KB Parameter Stage 8A Implementation Plan

Status: completed
Implementation commit: `efa4b89`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the offline documentation drift and add public-safe evidence binding to the existing KB parameter read-back audit without enabling live RAGFlow mutation.

**Architecture:** Preserve `ragflow_parameter_read_back_audit_v1` and add an optional `evidence_binding` block. The runtime computes deterministic SHA-256 digests from canonical JSON inputs, accepts only a caller-supplied UUID correlation ID, and records a caller-asserted RAGFlow contract version/source pair; it never derives identity from KB names or dataset IDs and never claims tool-verified correlation.

**Tech Stack:** Python 3.11, `argparse`, standard-library `hashlib`/`json`/`uuid`, `unittest`-style pytest coverage, existing report sanitization and schema/release gates.

---

### Task 1: Define Evidence Binding In Runtime Tests

**Files:**
- Modify: `packages/ragflow-skill-runtime/tests/test_kb_build.py`
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`

- [x] **Step 1: Write a failing test for canonical input digests**

Add a test that creates two semantically identical dry-run/read-back mappings with different key order and asserts equal `sha256:` digests in `evidence_binding`.

- [x] **Step 2: Run the focused test and verify the missing block fails**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build.py::KbBuildTests::test_parameter_read_back_audit_binds_canonical_input_digests -q`

Expected: FAIL because `evidence_binding` is absent.

- [x] **Step 3: Implement canonical JSON digests and unbound defaults**

Add private helpers that serialize JSON with sorted keys and compact separators, return `sha256:<hex>`, normalize a UUID bundle ID, validate a version/source pair, and build:

```python
{
    "binding_status": "unbound" | "caller_asserted",
    "verification_scope": "input_integrity_only" | "caller_asserted_correlation",
    "digest_algorithm": "sha256",
    "canonicalization": "json_sort_keys_compact_v1",
    "dry_run_report_digest": "sha256:<hex>",
    "observed_state_digest": "sha256:<hex>" | None,
    "evidence_bundle_id": "<canonical UUID>" | None,
    "ragflow_contract_identity": {
        "version": "<caller label>",
        "source": "server_reported" | "openapi" | "server_request_model" | "operator_supplied",
        "assertion": "caller_asserted",
    } | None,
    "tool_verified_same_run": False,
}
```

- [x] **Step 4: Run the runtime test file**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build.py -q`

Expected: PASS.

### Task 2: Expose Safe CLI Inputs And Markdown Evidence

**Files:**
- Modify: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`

- [x] **Step 1: Write failing CLI tests**

Extend the existing `parameter-audit` subprocess test to pass a UUID, version, and fixed contract source. Assert the JSON and Markdown report expose caller-asserted correlation, both digests, and `tool_verified_same_run: false`. Add a negative test for an invalid non-UUID bundle ID.

- [x] **Step 2: Run the focused CLI tests and verify failure**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -k parameter_audit -q`

Expected: FAIL because the new CLI options do not exist.

- [x] **Step 3: Add minimal CLI and renderer support**

Add `--evidence-bundle-id`, `--ragflow-contract-version`, and `--ragflow-contract-source`. Require version and source together, pass them to the runtime producer, include evidence-binding details in generated Markdown, and keep the existing redaction sidecar path.

- [x] **Step 4: Run runtime and CLI focused tests**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -k 'parameter_read_back or parameter_audit' -q`

Expected: PASS.

### Task 3: Calibrate Public Documentation

**Files:**
- Modify: `SKILL.md`
- Modify: `references/ragflow-api-parameter-taxonomy.md`
- Modify: `docs/03-development-plan.md`
- Modify: `docs/16-system-closeout-report.md`
- Modify: `docs/36-ragflow-kb-parameter-materialization-plan.md`

- [x] **Step 1: Correct stale payload behavior and sanitize taxonomy evidence**

State that `to_dataset_payload()` currently filters to `SUPPORTED_PARSER_KEYS`, remove the retained KB name, separate verified read-only defaults from API-visible/writeability-unconfirmed keys, and scope Stage 7 claims to the observed unversioned contract.

- [x] **Step 2: Align roadmap inventory counts without changing checklist totals**

Record 104 public command surfaces, report coverage 95/9, and runtime coverage 22/82 in current-status passages. Keep the roadmap at 586 completed and 15 intentionally gated items.

- [x] **Step 3: Close Stage 8A and preserve Stage 8B/8C gates**

Document evidence-binding limitations, keep the live retention checkbox open until an approved run produces correlated artifacts, and restrict the next contract search to overlap plus automatic metadata. Keep PageIndex/table/DeepDoc on a separate approval path.

- [x] **Step 4: Run docs safety checks**

Run: `git diff --check`

Run the changed-doc redaction scan from the maintainer validation chain and manually classify every hit.

### Task 4: Verify Report And Release Gates

**Files:**
- Verify: `tools/schema_identity_check.py`
- Verify: `tools/report_surface_inventory.py`
- Verify: `tools/generated_markdown_audit.py`
- Verify: `tools/runtime_resilience_inventory.py`

- [x] **Step 1: Compile changed Python files**

Run: `python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py skills/ragflow-kb-build/scripts/build.py`

- [x] **Step 2: Run focused report-gate tests**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py packages/ragflow-skill-runtime/tests/test_generated_markdown_audit.py packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py -q`

Expected: PASS with the command inventory unchanged at 104.

- [x] **Step 3: Run full runtime tests and release hygiene**

Run: `python3 -m pytest packages/ragflow-skill-runtime/tests -q`

Run: `python3 tools/schema_identity_check.py --report-json /tmp/kb-parameter-stage8a-schema-identity.json`

Run: `python3 tools/release_hygiene_check.py > /tmp/kb-parameter-stage8a-release-hygiene.json`

Expected: all tests pass; schema identity and release hygiene report zero findings.

- [x] **Step 4: Review final diff and leave commit decisions to the user**

Run: `git status --short --branch`, `git diff --stat`, `git diff --check`, and review the complete diff. Do not stage, commit, push, or run live RAGFlow operations unless explicitly requested.
