# RAGFlow API Parameter Taxonomy

> **Source:** Stage 6 read-only discovery plus Stage 7 dataset-create probes,
> reviewed on 2026-07-10.
> **Target:** Retained Markdown-handoff evidence; live identifiers are omitted.
> **Version boundary:** The historical evidence did not retain a correlated RAGFlow
> contract identity. Treat these findings as observed behavior, not a guarantee for
> every RAGFlow version.

## Discovery Methodology

Two-phase approach without DeepDoc baseline:

1. **Stage 6 - Read-only discovery**: use dataset detail read-back to observe
   `parser_config`, then compare it with dry-run `build_payload_preview` through
   `parameter-audit`.
2. **Stage 7 - Dataset-create probes**: attempt four disposable create profiles with
   zero and non-zero image/table context combinations. Every create request containing
   either context key was rejected before a disposable KB was created.
3. Historical notes also described update rejection, but the public evidence does not
   bind that observation to the same input bundle and RAGFlow version. Update behavior
   therefore remains uncorrelated here rather than being promoted to a version-independent
   fact.

## Field Classification

### Writeable (SUPPORTED_PARSER_KEYS)

These four keys form the current public profile write allowlist and matched Stage 6
read-back evidence. Future versions still require contract-bound verification.

| API Key | Stage 6 read-back | Current public contract |
|---------|:---:|:---:|
| `chunk_token_num` | Exact match | Supported |
| `delimiter` | Exact match | Supported |
| `auto_keywords` | Exact match | Supported |
| `auto_questions` | Exact match | Supported |

### Read-Only Server Defaults

These keys appeared in read-back `parser_config` and were rejected by every Stage 7
dataset-create probe that supplied them:

| API Key | Observed read-back | Dataset create | Update evidence |
|---------|:---:|:---:|:---:|
| `image_context_size` | Server-populated default | Rejected, code 101 | Uncorrelated historical note |
| `table_context_size` | Server-populated default | Rejected, code 101 | Uncorrelated historical note |

**Implication**: `to_dataset_payload()` filters to `SUPPORTED_PARSER_KEYS` so these
keys cannot break dataset creation. They remain visible in manifests and audits as
`read_only_server_default` for the observed contract.

### API-Visible, Writeability Unconfirmed

These keys appeared in Stage 6 read-back but have no correlated create/update probe.
Read-back visibility is not proof that a caller may write them.

| API Key | Observed read-back | Current disposition |
|---------|:---:|---|
| `children_delimiter` | Empty default | Manifest/audit only; writeability unconfirmed |
| `ext` | Empty object | Manifest/audit only; writeability unconfirmed |
| `filename_embd_weight` | Server-populated numeric default | Manifest/audit only; writeability unconfirmed |

### API-Visible but Scope-Limited

| API Key | Read-Back Value | Scope | Notes |
|---------|---------|-------|-------|
| `pages` | `null` | deepdoc_native | Null for Markdown handoff KBs; may hold page range for native PDF parsing |
| `html4excel` | `false` | deepdoc_native | Different from "Table to HTML" UI toggle; native PDF parser only |
| `layout_recognize` | `"DeepDOC"` | deepdoc_native | Parser engine selection |

### Not Visible in API

These UI controls have no corresponding field in `parser_config` read-back:

| UI Control | Status |
|-------------|--------|
| Automatic metadata | `contract_conflict` on RAGFlow `v0.25.5`; not Stage 8C eligible |
| Overlap percent | `runtime_only_not_api_writable` on RAGFlow `v0.25.5`; `chunk_overlap` remains a separate local planning field |

### DeepDoc Native-Only

These keys are present in read-back but only meaningful for native PDF parsing, not Markdown handoff:

| API Key | Typical Value |
|---------|--------------|
| `graphrag` | `{method: "light", use_graphrag: false, ...}` |
| `raptor` | `{...}` |
| `parent_child` | `{...}` |
| `table_column_mode` | varies |
| `table_column_names` | varies |
| `table_column_roles` | varies |
| `llm_id` | Model identifier for LLM enrichment |
| `tag_kb_ids` | varies |
| `task_page_size` | varies |
| `topn_tags` | varies |

## Code Impact

### `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py`

`SUPPORTED_PARSER_KEYS` (line 21) is correct — only 4 writeable keys:

```python
SUPPORTED_PARSER_KEYS = {
    "chunk_token_num",
    "auto_keywords",
    "auto_questions",
    "delimiter",
}
```

### `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`

`KNOWN_RAGFLOW_UI_CONTROLS` records the Stage 6/7 scope as follows:

- `ragflow_ui.image_context_window`: `markdown_handoff`, `read_only_server_default`;
- `ragflow_ui.table_context_window`: `markdown_handoff`, `read_only_server_default`;
- `ragflow_ui.page_index`: `deepdoc_native`, because `pages` was null for the
  Markdown-handoff evidence.

### `to_dataset_payload()` behavior

Currently filters `parser_config` to `SUPPORTED_PARSER_KEYS`. Unsupported, native-only,
unknown, and read-only default fields remain available to manifests and audit reports but
do not reach dataset create payloads.

## API Endpoint Behavior Summary

| Endpoint | `image_context_size` | `table_context_size` |
|----------|:---:|:---:|
| Dataset create | Rejected, code 101 | Rejected, code 101 |
| Dataset update | No correlated public evidence | No correlated public evidence |
| Dataset detail read-back | Server default observed | Server default observed |
| `DELETE /api/v1/datasets` | N/A | N/A |

**DELETE note**: Must use `{"ids": ["<dataset_id>"]}` in body. `DELETE /api/v1/datasets/{id}` returns 405 Method Not Allowed.

## Stage 8B Version-Bound Contract Audit

Stage 8B completed the next-candidate review against deployed RAGFlow `v0.25.5` and
upstream tag `v0.25.5` at commit `90c76e73d072a2fba9ffdd8cdde694a9cb4a31af`. The deployed
image is `infiniflow/ragflow:v0.25.5` with OCI digest
`sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724`.
Eight request, route, service, frontend, parser, normalization, and metadata-execution
source files match the pinned upstream tag byte for byte. This proves reviewed-source
parity, not live API acceptance.

### Overlap Percent

- Frontend payload path: `parser_config.overlapped_percent`.
- Markdown runtime consumer: the naive parser normalizes and consumes the same key.
- Dataset request boundary: strict `ParserConfig` uses `extra="forbid"` and does not
  declare `overlapped_percent`.
- Classification: `runtime_only_not_api_writable`.

The local `chunk_overlap` profile value remains a character-window estimate used for
planning. It is not automatically equivalent to RAGFlow's percentage field and must not
be converted into a dataset payload.

### Automatic Metadata

- `CreateDatasetReq` / `UpdateDatasetReq` expose top-level `auto_metadata_config` with
  `metadata` and `built_in_metadata`.
- A dedicated dataset metadata-config GET/PUT route validates and persists those fields.
- Dataset create/update service compatibility mapping still reads legacy `fields` and
  `enabled` values.
- The frontend submits `parser_config.metadata`, `parser_config.built_in_metadata`, and
  `parser_config.enable_metadata`, which are absent from strict `ParserConfig`.
- Runtime execution creates a chat-model bundle and schedules asynchronous per-chunk
  metadata generation during parse/reparse.
- Classification: `contract_conflict` with unresolved model/provider, cost,
  asynchronous-execution, parse/reparse, and metadata-governance gates.

Neither candidate is eligible for Stage 8C materialization on this contract. The
structured evidence is generated by `tools/ragflow_parameter_contract_audit.py`; the
copy-paste Hermes L0 replay is documented in
`docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md`.
