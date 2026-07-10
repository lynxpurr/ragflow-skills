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
| Automatic metadata | No API key found |
| Overlap percent | No API key found (chunk_overlap is a separate top-level field, not in parser_config) |

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
