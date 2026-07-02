# MinerU FastAPI Backend Design

Status: offline validated
Date: 2026-07-02

## Objective

Add a native `mineru-fastapi` backend to `ragflow-doc-to-md` so a host agent can
convert PDF, Office, and image inputs through a self-hosted MinerU `mineru-api`
service without using the SaaS Agent API, the synchronous `/parse` adapter, or a local
CLI process.

The target service is MinerU 3.2.1 protocol version 2. In that protocol, `POST /tasks`
is the asynchronous task API. `POST /file_parse` remains a synchronous compatibility
endpoint for legacy plugins and should not be used as the main adapter path.

## Scope

Runtime:

- Add `mineru-fastapi` to the shared conversion backend inventory.
- Add `mineru_fastapi_convert()` in
  `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py`.
- Submit multipart form data to `POST /tasks`.
- Poll `GET /tasks/{task_id}` until `completed` or `failed`.
- Retrieve `GET /tasks/{task_id}/result` and extract Markdown from MinerU result
  payloads.
- Probe `GET /health` and classify healthy protocol-v2 services as available.

CLI:

- Add `mineru-fastapi` to `skills/ragflow-doc-to-md/scripts/convert.py` backend choices.
- Reuse the existing `--mineru-*` configuration flags.
- Keep backend probe and warmup behavior compatible with existing reports and
  redaction sidecars.

Documentation:

- Update `skills/ragflow-doc-to-md/SKILL.md` with the new backend and a placeholder
  self-hosted service example.

Out of scope:

- Starting, supervising, or installing `mineru-api`.
- Mutating RAGFlow.
- Hardcoding local IPs, credentials, private files, or personal paths.
- Running live MinerU conversion unless explicitly requested after offline validation.

## Protocol Mapping

Request:

- URL: `{base_url}/tasks`
- Method: `POST`
- Body: `multipart/form-data`
- File field: `files`
- Auth: `Authorization: Bearer {api_key}` when configured.
- Form fields:
  - `lang_list`: current `mineru_language` value, default `ch`
  - `backend`: default `pipeline`
  - `parse_method`: `ocr` when `mineru_is_ocr` is true, otherwise `auto`
  - `formula_enable`: `mineru_enable_formula`
  - `table_enable`: `mineru_enable_table`
  - `image_analysis`: `true`
  - `return_md`: `true`
  - `return_middle_json`: `false`
  - `return_model_output`: `false`
  - `return_content_list`: `false`
  - `return_images`: `false`
  - `response_format_zip`: `false`
  - `return_original_file`: `false`
  - `client_side_output_generation`: `false`
  - `start_page_id` / `end_page_id`: parsed from `mineru_page_range` when possible,
    otherwise `0` and `99999`.

Status states:

- Pending: `pending`, `processing`
- Success: `completed`
- Failure: `failed`

Result extraction:

- Primary MinerU shape:
  `{"results": {"document_stem": {"md_content": "..."}}}`
- Compatibility fields:
  `markdown`, `content`, `text`, `md`, `result`, nested `data`, `result`, or `output`.
- Empty or missing Markdown raises `DocConvertError`.

## Task Checklist

- [x] Confirm the local MinerU 3.2.1 FastAPI protocol and document field mapping.
- [x] Add the `mineru-fastapi` runtime conversion backend.
- [x] Add the `mineru-fastapi` backend probe path.
- [x] Wire the CLI backend choice and existing config flags.
- [x] Update public skill documentation.
- [x] Add runtime unit tests for success, failure, timeout, and health probe.
- [x] Add CLI regression coverage for convert/probe paths.
- [x] Run targeted Python compilation and test validation.
- [x] Run `git diff --check`.

## Verification Plan

Offline validation:

```bash
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py \
  skills/ragflow-doc-to-md/scripts/convert.py
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_doc_convert.py \
  packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py -q
git diff --check
```

Optional live validation after explicit approval:

```bash
python scripts/convert.py backend probe \
  --backend mineru-fastapi \
  --mineru-base-url http://127.0.0.1:8000 \
  --network-check \
  --json

python scripts/convert.py backend warmup \
  --backend mineru-fastapi \
  --mineru-base-url http://127.0.0.1:8000 \
  --fixture /path/to/tiny-fixture.pdf \
  --json \
  --fail-on-failed
```
