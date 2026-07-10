# KB Parameter Stage 8B Contract Audit Design

Status: implemented and independently corroborated
Date: 2026-07-10
Implementation commit: `7bd0b94`
Hermes L0 corroboration recorded by: `f9daf91`

## Objective

Build a deterministic, offline contract audit for the two unresolved Markdown-handoff
parameter candidates from `docs/36-ragflow-kb-parameter-materialization-plan.md`:

- overlap percent or its actual RAGFlow API equivalent;
- automatic metadata at dataset scope.

The audit must bind findings to both the current deployed RAGFlow source and a pinned
upstream tag. It must distinguish request validation, frontend payload shape, service
mapping, runtime consumption, and side effects before any field can be called writable.

Stage 8B does not add a writable KB field, modify `SUPPORTED_PARSER_KEYS`, call a live
RAGFlow API, create or update a dataset, trigger parsing, run DeepDoc, or invoke an LLM.

## Version And Evidence Boundary

The initial audit target is RAGFlow `v0.25.5`:

- deployed image tag: `infiniflow/ragflow:v0.25.5`;
- deployed image digest:
  `sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724`;
- deployed `/ragflow/VERSION`: `v0.25.5`;
- upstream tag: `v0.25.5`;
- upstream tag commit: `90c76e73d072a2fba9ffdd8cdde694a9cb4a31af`.

The deployed and upstream copies of all eight required evidence files have identical
SHA-256 digests. The audit tool must verify that equality itself from caller-supplied
source roots rather than trusting this design record.

Required source files:

| Evidence layer | Relative path |
| --- | --- |
| Request validation | `api/utils/validation_utils.py` |
| Dataset routes | `api/apps/restful_apis/dataset_api.py` |
| Dataset service mapping | `api/apps/services/dataset_api_service.py` |
| Markdown parser runtime | `rag/app/naive.py` |
| Overlap normalization | `common/float_utils.py` |
| Dataset frontend schema | `web/src/pages/dataset/dataset-setting/form-schema.ts` |
| Dataset frontend controls | `web/src/pages/dataset/dataset-setting/configuration/common-item.tsx` |
| Metadata execution | `rag/svr/task_executor.py` |

Public reports may retain the public image tag/digest, upstream tag/commit, relative
source paths, line numbers, field names, classification, and file digests. They must not
retain container names, host paths, endpoints, credentials, dataset/document IDs, KB
names, user data, or source snippets containing deployment-specific values.

## Alternatives Considered

### Documentation-only discovery

This has the smallest implementation cost, but manual line citations cannot detect
contract drift when a later RAGFlow version changes only one layer. It also makes a
Hermes replay depend on prose interpretation.

### Offline structured contract audit

This is the selected approach. A maintainer tool consumes two explicit source roots plus
public version identity, verifies required files and digests, extracts bounded evidence,
and emits deterministic JSON and Markdown. Synthetic fixtures cover classification and
failure behavior without Docker or network access.

### Immediate materialization

This is rejected for Stage 8B. The `v0.25.5` evidence is internally inconsistent, so
adding payload support now would turn a contract-discovery result into an unsafe write
assumption.

## Audit Architecture

Add `tools/ragflow_parameter_contract_audit.py` as a maintainer/release-governance tool,
not a public skill command. It accepts:

```text
--deployment-root <extracted-ragflow-source>
--upstream-root <pinned-upstream-source>
--deployment-version v0.25.5
--deployment-image infiniflow/ragflow:v0.25.5
--deployment-image-digest sha256:<64-hex>
--upstream-tag v0.25.5
--upstream-commit <40-hex>
--report-json <path>
--report-md <path>
--redaction-report <path>
```

Both roots are explicit inputs. The tool must not discover Docker containers, scan home
directories, clone a repository, download upstream files, read configuration, or call an
HTTP endpoint. Source acquisition remains an operator or Hermes responsibility outside
the audit process.

Python request classes are inspected through the standard-library `ast` module. Bounded
frontend and call-chain evidence uses exact literal/identifier rules tied to the required
relative files. The tool records each matched rule and line number so an unsupported
syntax or renamed field fails closed instead of being inferred from approximate text.

The report schema is `ragflow_parameter_contract_audit_v1`. It contains:

- `contract_identity`: deployed and upstream public version identities;
- `source_integrity`: required-file digests and pairwise equality;
- `candidates`: one record for overlap and one for automatic metadata;
- `summary`: status counts and whether any candidate is eligible for Stage 8C;
- `safety`: zero network calls, zero RAGFlow calls/writes, zero LLM calls, no raw chunks;
- `issues`: missing files, source drift, unsupported syntax, or evidence conflicts.

The Markdown renderer summarizes identities, integrity, candidate classifications,
evidence layers, side effects, issues, and the Stage 8C gate. It must support the shared
report sanitizer and redaction sidecar conventions.

## Evidence Layers And Classification

Every candidate records these layers independently:

1. `request_model`: accepted field, payload level, type, default, validation, and extra
   field policy.
2. `frontend_payload`: form field path and normalized value shape.
3. `service_mapping`: how the validated request is mapped or persisted.
4. `runtime_consumer`: whether parser or task execution reads the effective field.
5. `side_effects`: model/provider dependency, cost, asynchronous work, parse/reparse
   requirement, and metadata-governance impact.

Allowed candidate classifications:

- `writable_contract_confirmed`: all required layers agree on one exact public payload;
- `contract_conflict`: two or more contract layers disagree;
- `runtime_only_not_api_writable`: runtime consumes a field rejected or absent from the
  strict dataset request model;
- `not_found`: no bounded evidence establishes the candidate;
- `audit_incomplete`: required source or extraction evidence is missing.

`stage8c_eligible` is true only for `writable_contract_confirmed`, identical deployed and
upstream required files, complete evidence, and no unresolved side-effect gate. No
classification automatically enables live mutation.

## Initial Expected Findings

### Overlap percent

The frontend uses `parser_config.overlapped_percent`, and Markdown parsing consumes the
same key after normalizing values to a bounded percentage. However, the strict Pydantic
`ParserConfig` model uses `extra="forbid"` and does not declare `overlapped_percent`.
Dataset create/update validation therefore rejects the frontend/runtime field in the
reviewed contract.

Expected classification: `runtime_only_not_api_writable`.

The local profile field `chunk_overlap` is a different, character-window planning value.
It must not be silently converted to `overlapped_percent`.

### Automatic metadata

The strict dataset request model accepts top-level `auto_metadata_config` with
`metadata` and `built_in_metadata`. A dedicated dataset metadata-config PUT route accepts
that same model and persists both fields into `parser_config`. The dataset create/update
service compatibility mapping, however, reads legacy `fields` and `enabled` keys, while
the current frontend submits `parser_config.metadata`, `built_in_metadata`, and
`enable_metadata` fields that are absent from strict `ParserConfig`.

The runtime metadata path also creates a chat-model bundle and schedules per-chunk
metadata generation during parsing. This is model/provider dependent, asynchronous,
potentially billable, and changes metadata governance.

Expected classification: `contract_conflict` with an unresolved side-effect gate.

## Hermes Agent Test Handoff

The implementation must add a copy-paste Hermes instruction block and a final report
template. It follows the existing repository L0/L1/L2 convention:

| Level | Default | Network/API | Mutation | Purpose |
| --- | --- | --- | --- | --- |
| L0 source audit | allowed | no RAGFlow API | none | Extract the two explicit source roots, run the offline audit, and return sanitized artifacts. |
| L1 read-only HTTP evidence | separate approval/instruction | read-only only | none | Confirm version/read-back behavior only when source evidence cannot resolve a question. |
| L2 disposable write probe | explicit user approval required | live | disposable only | Test one exact candidate after Stage 8C prerequisites exist. |

The Stage 8B prompt authorizes L0 only. Hermes must stop and report `approval_required`
instead of upgrading to L1 or L2. It may copy source files from a local deployment or use
an already extracted source root, and may obtain a pinned public tag snapshot, but it
must not read container environment variables, configuration secrets, databases, or user
datasets.

Hermes returns:

- `ragflow_parameter_contract_audit_v1` JSON;
- generated Markdown;
- redaction sidecar;
- a concise Chinese execution report containing source identities, digest equality,
  candidate status, every command result, skipped gated levels, redaction review, and
  residual risks.

The report must not treat a passing L0 audit as live API acceptance. Any future L1/L2
instruction is generated separately after review of the prior report.

## Error Handling

The audit exits non-zero and emits a report when possible for:

- a required source file is missing;
- a deployment/upstream digest differs;
- version, image digest, tag, or commit identity is malformed;
- the Python AST cannot establish the strict base model or candidate request fields;
- a required exact frontend/service/runtime evidence rule is absent;
- a candidate appears writable in one layer but conflicts with another.

Contract conflicts are expected findings and do not make the tool crash. The report may
be `ok: true` while `stage8c_eligible: false`; `ok` means the audit completed, not that a
candidate is writable.

## Testing And Release Gates

Use synthetic paired source roots in unit tests. Required coverage includes:

- identical source roots produce deterministic digests and the two expected
  classifications;
- source-root key order or filesystem location does not change semantic output;
- deployment/upstream drift is reported and blocks Stage 8C;
- missing files and malformed identities fail closed;
- request-model, frontend, service, runtime, and side-effect evidence is independently
  asserted;
- JSON, Markdown, and redaction output contain no host path;
- the Hermes prompt authorizes only L0 and explicitly blocks L1/L2 escalation.

Because this adds a standalone public-safe report schema and generated Markdown, update
schema identity, report-surface/generated-Markdown governance as applicable, focused
tests, release hygiene, and the owning Stage 8 plan. Keep `docs/03` at 586/601 and
`docs/36` at 5/10 unless later implementation genuinely closes an existing checklist
item; Stage 8B contract discovery alone does not do so.

## Completion Criteria

Stage 8B is complete when:

1. The offline audit tool and synthetic tests pass.
2. Deployment and upstream `v0.25.5` evidence produce identical required-file digests.
3. Overlap is classified `runtime_only_not_api_writable`.
4. Automatic metadata is classified `contract_conflict` with model/cost/async/governance
   side effects recorded.
5. No candidate is marked Stage 8C eligible.
6. The Hermes L0 prompt and report template are reviewable and safe to copy.
7. Full runtime and release-facing validation passes with zero hygiene findings.

No live E2E is required to close Stage 8B. A Hermes L0 rerun is optional corroborating
evidence and can be requested after the local implementation is complete.
