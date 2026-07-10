# RAGFlow API Parameter Taxonomy

> **Source:** Stage 6 (read-only discovery) + Stage 7 (live write probe) — 2026-07-09
> **Target KB:** kb:tsn-industrial-networks-hybrid (naive, delimiter, 768 tokens)

## Discovery Methodology

Two-phase approach without DeepDoc baseline:

1. **Stage 6 — Read-only discovery**: API `GET /datasets/{id}` to observe parser_config, then compare with dry-run `build_payload_preview` via `parameter-read-back-audit`.
2. **Stage 7 — Live write probe**: Attempt `POST /datasets` and `PUT /datasets/{id}` with non-zero values to test writeability.

## Field Classification

### Writeable (SUPPORTED_PARSER_KEYS)

These 4 keys are accepted by RAGFlow create/update API and read back identically:

| API Key | Stage 6 Read-Back | Stage 7 Write Probe |
|---------|:---:|:---:|
| `chunk_token_num` | ✅ 768 ↔ 768 | ✅ Accepted |
| `delimiter` | ✅ `<!-- chunk -->` ↔ `<!-- chunk -->` | ✅ Accepted |
| `auto_keywords` | ✅ 0 ↔ 0 | ✅ Accepted |
| `auto_questions` | ✅ 0 ↔ 0 | ✅ Accepted |

### Read-Only Server Defaults

These keys appear in read-back parser_config but are **rejected** at create/update time with code 101 ("Extra inputs are not permitted"):

| API Key | Read-Back Value | Create Rejected | PUT Rejected |
|---------|:---:|:---:|:---:|
| `image_context_size` | 0 | ✅ 101 | ✅ 101 |
| `table_context_size` | 0 | ✅ 101 | ✅ 101 |
| `children_delimiter` | `""` | Not tested | Not tested |
| `ext` | `{}` | Not tested | Not tested |
| `filename_embd_weight` | 0.1 | Not tested | Not tested |

**Implication**: `to_dataset_payload()` must filter to only SUPPORTED_PARSER_KEYS, otherwise RAGFlow rejects the payload. The code's current behavior of including all parser_config keys causes "could not extract dataset id" errors.

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

`KNOWN_RAGFLOW_UI_CONTROLS` (line 290) needs scope updates based on Stage 6/7 findings:

- `ragflow_ui.image_context_window`: scope should be `markdown_handoff` (API key confirmed as `image_context_size`), but status should reflect **read-only server default**
- `ragflow_ui.table_context_window`: same — `markdown_handoff` scope, read-only server default
- `ragflow_ui.page_index`: scope `deepdoc_native` (API key `pages` is null for markdown handoff)

### `to_dataset_payload()` behavior

Currently passes ALL parser_config keys to the API. This causes "Extra inputs are not permitted" errors when profiles include `image_context_size` or `table_context_size`. Fix: filter to `SUPPORTED_PARSER_KEYS` only.

## API Endpoint Behavior Summary

| Endpoint | image_context_size | table_context_size |
|----------|:---:|:---:|
| `POST /api/v1/datasets` | ❌ 101 Extra inputs not permitted | ❌ 101 Extra inputs not permitted |
| `PUT /api/v1/datasets/{id}` | ❌ 101 Extra inputs not permitted | ❌ 101 Extra inputs not permitted |
| `GET /api/v1/datasets/{id}` | ✅ Returns 0 (server default) | ✅ Returns 0 (server default) |
| `DELETE /api/v1/datasets` | N/A | N/A |

**DELETE note**: Must use `{"ids": ["<dataset_id>"]}` in body. `DELETE /api/v1/datasets/{id}` returns 405 Method Not Allowed.
