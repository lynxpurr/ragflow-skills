# KB Parameter Stage 8B Contract Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic offline audit that compares deployed and upstream RAGFlow source contracts for overlap and automatic metadata, records the v0.25.5 conflict evidence, and produces a safe Hermes L0 replay instruction without enabling live mutation.

**Architecture:** A standalone maintainer tool reads two explicit RAGFlow source roots, verifies eight required files and public version identities, uses Python AST plus bounded exact-source rules to classify five evidence layers, and emits sanitized JSON/Markdown. It does not discover Docker, clone/download source, inspect config, or call RAGFlow. Schema identity and release hygiene govern the stable report, while the 104 public skill command inventory remains unchanged.

**Tech Stack:** Python 3.11 standard library (`argparse`, `ast`, `hashlib`, `json`, `pathlib`, `re`), existing `ragflow_skill_runtime` report sanitizer, unittest-style pytest tests, Markdown planning docs.

---

### Task 1: Define The Offline Contract Audit In Failing Tests

**Files:**
- Create: `packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py`
- Create: `tools/ragflow_parameter_contract_audit.py`

- [x] **Step 1: Add a paired synthetic source-root fixture helper**

The test helper writes the eight paths from the approved design. Its minimal source must include:

```python
class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class AutoMetadataConfig(Base):
    metadata: Annotated[list[AutoMetadataField], Field(default_factory=list)]
    built_in_metadata: Annotated[list[AutoMetadataField], Field(default_factory=list)]

class ParserConfig(Base):
    chunk_token_num: Annotated[int, Field(default=512, ge=1, le=2048)]

class CreateDatasetReq(Base):
    parser_config: Annotated[ParserConfig | None, Field(default=None)]
    auto_metadata_config: Annotated[AutoMetadataConfig | None, Field(default=None)]

class UpdateDatasetReq(CreateDatasetReq):
    pass
```

The other fixture files must carry exact evidence for
`parser_config.overlapped_percent`, `normalize_overlapped_percent`,
`auto_meta.get("fields")`, `auto_meta.get("enabled")`, the metadata config GET/PUT
route, `parser_config.enable_metadata`, `LLMBundle`, and `asyncio.create_task`.

- [x] **Step 2: Write the main expected-classification test**

Import `SCHEMA` and `audit_parameter_contract`. Assert:

```python
report, redaction = audit_parameter_contract(
    deployment_root=deployment,
    upstream_root=upstream,
    deployment_version="v0.25.5",
    deployment_image="infiniflow/ragflow:v0.25.5",
    deployment_image_digest="sha256:" + "1" * 64,
    upstream_tag="v0.25.5",
    upstream_commit="9" * 40,
)
assert report["schema"] == "ragflow_parameter_contract_audit_v1"
assert report["ok"] is True
assert report["source_integrity"]["all_required_files_identical"] is True
assert by_id["overlap_percent"]["classification"] == "runtime_only_not_api_writable"
assert by_id["automatic_metadata"]["classification"] == "contract_conflict"
assert report["summary"]["stage8c_eligible_candidate_count"] == 0
assert report["safety"]["ragflow_calls"] == 0
assert report["safety"]["writes_live_ragflow"] is False
```

Also assert the automatic-metadata side effects record model/provider dependency,
potential cost, asynchronous per-chunk work, parse/reparse scope, and metadata-governance impact.

- [x] **Step 3: Write fail-closed tests**

Add independent tests for:

- one upstream file changed: `ok=false`, `source_drift`, no Stage 8C eligibility;
- one required file absent: `ok=false`, `audit_incomplete`;
- malformed image digest, version, tag, or commit: `ok=false` with identity finding;
- `overlapped_percent` added to `ParserConfig`: classification changes only when all required layers agree; runtime/frontend evidence alone never confirms writeability;
- report and redaction JSON contain neither source-root absolute path.

- [x] **Step 4: Add CLI/Markdown/redaction tests**

Run the tool as a subprocess with the paired roots and all required identity flags. Assert
exit 0, JSON/Markdown/redaction files exist, Markdown includes
`runtime_only_not_api_writable`, `contract_conflict`, and `Stage 8C eligible: false`, and
no absolute fixture root appears in any output.

- [x] **Step 5: Run the new test file and verify RED**

Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py -q
```

Expected: collection/import failure because the new tool contract is not implemented.

### Task 2: Implement The Audit And Report Renderer

**Files:**
- Create: `tools/ragflow_parameter_contract_audit.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py`

- [x] **Step 1: Add constants and identity validation**

Define:

```python
SCHEMA = "ragflow_parameter_contract_audit_v1"
REQUIRED_SOURCE_FILES = (
    "api/utils/validation_utils.py",
    "api/apps/restful_apis/dataset_api.py",
    "api/apps/services/dataset_api_service.py",
    "rag/app/naive.py",
    "common/float_utils.py",
    "web/src/pages/dataset/dataset-setting/form-schema.ts",
    "web/src/pages/dataset/dataset-setting/configuration/common-item.tsx",
    "rag/svr/task_executor.py",
)
CLASSIFICATIONS = {
    "writable_contract_confirmed",
    "contract_conflict",
    "runtime_only_not_api_writable",
    "not_found",
    "audit_incomplete",
}
```

Accept versions/tags as short ASCII release labels, require `sha256:<64-hex>` for the
image digest, and require a 40-hex upstream commit. Invalid identity is a report finding,
not an uncaught exception.

- [x] **Step 2: Implement source integrity without publishing roots**

For every required relative path, read deployment/upstream bytes, compute SHA-256, and
emit only relative path, both digests, existence, and equality. Missing/unreadable files
create findings. `all_required_files_identical` is true only when every pair exists and
matches.

- [x] **Step 3: Implement AST request-model extraction**

Use `ast.parse` on `validation_utils.py` to extract class bases, annotated field names,
and the `Base.model_config` call. Establish exactly:

- strict unknown-field rejection through `extra="forbid"`;
- whether `ParserConfig` declares `overlapped_percent`;
- whether `CreateDatasetReq` declares top-level `auto_metadata_config`;
- whether `AutoMetadataConfig` declares `metadata` and `built_in_metadata`;
- `UpdateDatasetReq` inheritance from `CreateDatasetReq`.

Unsupported AST shapes become `audit_incomplete`; do not approximate them as writable.

- [x] **Step 4: Implement bounded evidence rules and classification**

Use exact literals/identifiers scoped to their owning required files. Record rule ID,
matched boolean, relative path, and matching line numbers. Build the five evidence layers.

Classify overlap as `runtime_only_not_api_writable` when frontend/runtime rules match,
strict extra rejection is present, and `ParserConfig.overlapped_percent` is absent.

Classify automatic metadata as `contract_conflict` when the top-level model and dedicated
route use `metadata`/`built_in_metadata`, while create/update service mapping uses
`fields`/`enabled` or frontend/runtime use parser-config fields absent from strict
`ParserConfig`. Record `LLMBundle` plus async per-chunk task evidence as an unresolved
side-effect gate.

Set `stage8c_eligible=true` only when classification is
`writable_contract_confirmed`, sources are identical, all evidence is complete, and no
side-effect gate remains.

- [x] **Step 5: Sanitize and render outputs**

Build the raw report without absolute roots, then call `sanitize_report_payload` with both
root paths as home/config path context. `render_markdown` includes identity, source
integrity, candidate table, evidence layers, side effects, issues, safety, and a false
Stage 8C gate for v0.25.5.

- [x] **Step 6: Implement CLI output behavior**

Add all flags from the design. Write JSON, Markdown, and redaction sidecar when requested,
print JSON to stdout, and return 0 only when audit execution is complete (`report.ok`),
even though candidate classifications are blocked. Return non-zero for missing/drifted
sources or invalid identity.

- [x] **Step 7: Run focused tests to GREEN**

Run:

```bash
python3 -m py_compile tools/ragflow_parameter_contract_audit.py
python3 -m pytest packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py -q
```

Expected: all new tests pass.

### Task 3: Add Governance, Documentation, And Hermes L0 Handoff

**Files:**
- Modify: `tools/schema_identity_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_schema_identity_check.py`
- Create: `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md`
- Modify: `references/ragflow-api-parameter-taxonomy.md`
- Modify: `docs/03-development-plan.md`
- Modify: `docs/16-system-closeout-report.md`
- Modify: `docs/36-ragflow-kb-parameter-materialization-plan.md`

- [x] **Step 1: Add schema identity coverage**

Register `parameter_contract_audit` in group `kb_build` with source root
`tools/ragflow_parameter_contract_audit.py` and coverage root
`packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py`. Extend the
schema-identity unit test to assert the key exists. The identity count may increase, but
the public command inventory must remain 104.

- [x] **Step 2: Add the Hermes L0 copy-paste instruction**

Create `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md` with:

- source commit/status preflight;
- explicit L0 authorization only;
- commands to prepare two private source roots and run the audit;
- prohibition on config/env/database/user-data inspection and all RAGFlow HTTP calls;
- stop condition `approval_required` for L1/L2;
- required JSON, Markdown, redaction sidecar, and Chinese summary;
- final report template with identity, digest equality, candidate classifications,
  command status, redaction review, skipped gates, and residual risks.

Use placeholders rather than a real container name or private path. State that the user
may copy the prompt to Hermes and return its artifacts for the next iteration.

- [x] **Step 3: Record the v0.25.5 findings**

Update the taxonomy and owning plans with the exact two classifications and evidence
boundary. Record public image tag/digest and upstream tag/commit, but no container name or
host path. Explain that identical file digests prove deployment/upstream source parity,
not live API acceptance.

- [x] **Step 4: Preserve checklist and command totals**

Keep `docs/03` at 586 completed / 15 open and `docs/36` at 5 completed / 5 open. Keep
report/runtime command inventories at 104 commands. Mark Stage 8B complete only after the
real audit and validation in Task 4 pass.

- [x] **Step 5: Run focused governance and docs checks**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py \
  packages/ragflow-skill-runtime/tests/test_schema_identity_check.py -q
python3 tools/schema_identity_check.py \
  --report-json /tmp/kb-parameter-stage8b-schema-identity.json \
  >/tmp/kb-parameter-stage8b-schema-identity.stdout
git diff --check
```

Run the maintainer changed-doc redaction scan and manually classify every hit.

### Task 4: Run Real Dual-Source Audit And Release Validation

**Files:**
- Verify: `tools/ragflow_parameter_contract_audit.py`
- Verify: `docs/36-ragflow-kb-parameter-materialization-plan.md`
- Verify: `docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md`

- [x] **Step 1: Prepare private deployment/upstream v0.25.5 source roots**

Under fresh `/tmp` directories, copy only the eight approved files from the deployed
RAGFlow image and download or extract the same eight paths from upstream tag `v0.25.5`.
Do not copy environment, config, database, logs, or user data.

- [x] **Step 2: Run the real audit**

Run the tool with:

```text
deployment version v0.25.5
deployment image infiniflow/ragflow:v0.25.5
deployment digest sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724
upstream tag v0.25.5
upstream commit 90c76e73d072a2fba9ffdd8cdde694a9cb4a31af
```

Write JSON, Markdown, and redaction outputs under `/tmp`. Assert all required digests are
identical, overlap is `runtime_only_not_api_writable`, automatic metadata is
`contract_conflict`, and Stage 8C eligible count is zero.

- [x] **Step 3: Run full runtime and release gates**

Run sequentially:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests -q
git diff --check
python3 tools/manifest_schema_check.py
python3 tools/schema_identity_check.py --report-json /tmp/kb-parameter-stage8b-final-schema-identity.json
python3 tools/release_hygiene_check.py >/tmp/kb-parameter-stage8b-final-release-hygiene.json
python3 tools/build_release.py --check
```

No archive export, consumer acceptance, or platform smoke is required unless the release
gate or implementation reveals an affected packaged surface; the new tool is outside
public skill archives.

- [x] **Step 4: Perform final review**

Review the complete diff, current checklist counts, schema identity, redaction hits,
untracked files, and real audit report. Do not stage, commit, push, call live RAGFlow, or
send a Hermes task unless the user explicitly requests that action.
