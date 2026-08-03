---
doc_type: spec
topic: mineru-v4-platform-backend
status: historical
created: 2026-07-06
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
archived: 2026-08-03
historical_reason: completed
original_sha256: b7ce825d4cb776bba17b041553a0a6c1b5f74c9e35a8dc0d2777c32abb18931b
---

> **Historical archive:** This document is immutable context and creates no current task,
> implementation, operational, network, credential, mutation, or live authority.

# MinerU v4 Platform Backend Design

Status: implemented and release-validated
Date: 2026-07-06

## Objective

Add an independent `mineru-v4` or `mineru-platform` backend to `ragflow-doc-to-md`
for the MinerU v4 platform-compatible precision parsing protocol. The implementation was
validated against the public MinerU API document at `https://mineru.net/apiManage/docs`,
but the backend is not intended to be bound to the `mineru.net` domain. Any endpoint that
implements the same v4 upload, polling, and `full_zip_url` result contract may be used by
setting `MINERU_BASE_URL` / `--mineru-base-url`.

This backend must not overload the existing `mineru`, `mineru-agent`,
`mineru-fastapi`, or `mineru-sync` implementations. The v4 platform-compatible protocol
has a different endpoint shape, upload flow, result contract, model selector, file/page
limits, and output format. Treating it as another base URL for `mineru-fastapi` would
make the CLI call `/tasks`, which is not part of that protocol.

## Background

The current code supports three MinerU service families:

| Existing backend | Intended protocol | Current endpoint shape |
| --- | --- | --- |
| `mineru` / `mineru-agent` | MinerU Agent lightweight API | `POST /api/v1/agent/parse/file`, upload returned `file_url`, poll `/parse/{task_id}`, download `markdown_url` |
| `mineru-fastapi` | Self-hosted MinerU 3.2+ FastAPI protocol v2 | `POST /tasks`, poll `/tasks/{task_id}`, fetch `/tasks/{task_id}/result` |
| `mineru-sync` / `mineru-local` | Legacy synchronous multipart service | `POST /parse` |

The MinerU API management document describes a separate precision API protocol:

- token-authenticated;
- endpoint family `/api/v4/extract/task` and `/api/v4/file-urls/batch`;
- model versions `pipeline`, `vlm`, and `MinerU-HTML`;
- local-file batch submission with returned upload URLs;
- asynchronous polling through `/api/v4/extract-results/batch/{batch_id}`;
- zip result outputs containing Markdown and JSON artifacts.

Therefore the feature should introduce a first-class platform-protocol backend instead of
reusing the self-hosted FastAPI adapter. `https://mineru.net` is the official documented
example endpoint, not a hardcoded routing rule.

## Implementation Notes

2026-07-06 protocol check against the current public MinerU API document confirmed the
v4 platform backend must use the local-file batch upload flow, not the self-hosted
FastAPI `/tasks` protocol:

- `POST /api/v4/file-urls/batch` returns `batch_id` and `file_urls`.
- `file.is_ocr`, `file.data_id`, and `file.page_ranges` are per-file request fields in
  local-file batch mode.
- `enable_formula`, `enable_table`, `language`, and `model_version` are request-level
  fields.
- Batch polling uses `/api/v4/extract-results/batch/{batch_id}` and documented in-progress
  states include `waiting-file`, `pending`, `running`, and `converting`.
- Completed results expose `full_zip_url`; the first implementation supports
  `MINERU_V4_RESULT_MODE=full_zip` only.
- The public document says local-file URL acquisition supports up to 50 files per batch.
  This implementation still submits one file per conversion call, matching the existing
  `ragflow-doc-to-md` per-source conversion contract.

Implementation is offline/fake-server first. No real MinerU v4 API call was made in this
development batch; live validation remains separately gated by explicit user approval,
credentials, a throwaway public fixture, and sanitized evidence capture.

## Design Requirements

### Compatibility

- Add a distinct backend choice, preferably `mineru-v4`; `mineru-platform` may be
  accepted as an alias if useful for user clarity.
- Keep existing backend behavior unchanged:
  - `mineru` and `mineru-agent` continue to target `/api/v1/agent`.
  - `mineru-fastapi` continues to target self-hosted `/tasks`.
  - `mineru-sync` continues to target `/parse`.
- Do not infer v4 behavior solely from a URL such as
  `MINERU_BASE_URL=https://mineru.net/api/v4`; users must select the v4 backend
  explicitly or via adaptive recommendation. The backend choice is protocol-bound, not
  domain-bound.
- Do not run live MinerU v4 calls in tests. Use fake HTTP servers and fixture zip files.

### Configuration

Reuse common MinerU configuration where the meaning is compatible:

- `MINERU_BASE_URL` / `--mineru-base-url`
- `MINERU_API_KEY` / `--mineru-api-key`
- `MINERU_TIMEOUT` / `--mineru-timeout`
- `MINERU_POLL_INTERVAL` / `--mineru-poll-interval`
- `MINERU_VERIFY_SSL` / `--mineru-verify-ssl`
- `MINERU_LANGUAGE` / `--mineru-language`
- `MINERU_ENABLE_TABLE` / `--mineru-enable-table`
- `MINERU_ENABLE_FORMULA` / `--mineru-enable-formula`
- `MINERU_IS_OCR` / `--mineru-is-ocr`
- `MINERU_PAGE_RANGE` / `--mineru-page-range`, only if the v4 API supports an
  equivalent page-range field. Otherwise reject with a clear error instead of silently
  ignoring it.

Add v4-specific knobs:

- `MINERU_V4_MODEL_VERSION` / `--mineru-v4-model-version`
  - allowed values: `pipeline`, `vlm`, `MinerU-HTML`
  - default: `pipeline` for standard compatibility
- `MINERU_V4_RESULT_MODE` / `--mineru-v4-result-mode`
  - initial value: `full_zip`
  - future values may include `markdown_zip` if the API exposes a stable Markdown-only
    zip field.
- `MINERU_V4_DATA_ID_PREFIX` / `--mineru-v4-data-id-prefix`
  - optional stable prefix used when generating `data_id` values.
- Optional callback support should remain out of scope for the first implementation;
  polling is the deterministic CLI-friendly path.

### Table Quality Mapping

The current high-quality table logic for `mineru-fastapi` selects
`hybrid-auto-engine` or VLM-like self-hosted backends. The v4 platform API uses
`model_version` instead.

Map table quality as follows:

| `--table-quality` | v4 model behavior |
| --- | --- |
| `standard` | Preserve the configured `mineru_v4_model_version`, defaulting to `pipeline`. |
| `high` | Use `model_version=vlm` unless the user explicitly configured `MinerU-HTML`; preserve explicit `MinerU-HTML` and report that the user-selected model was kept. |
| `auto` | For PDF/Office/image formal-ingest candidates with table signals, keep the configured or explicitly requested backend. If that backend is `mineru-v4` / `mineru-platform`, recommend `table_quality=high`, `mineru_v4_model_version=vlm`, and `markdown_assets`-compatible asset handling where available. Do not switch to the paid platform path merely because a token exists. |

The table-quality report must distinguish:

- self-hosted FastAPI high-accuracy backend, such as `hybrid-auto-engine`;
- v4 platform high-accuracy model, such as `model_version=vlm`;
- degradation or fallback events.

### Protocol

Implement local-file batch parsing through the v4 upload-url flow.

Submission:

- Normalize base URL so both a v4-compatible service root and a root that already ends in
  `/api/v4` can be supported without producing duplicate `/api/v4/api/v4` paths. Official
  examples include `https://mineru.net` and `https://mineru.net/api/v4`, but compatible
  third-party, gateway, or hosted endpoints should work when they implement the same
  protocol.
- `POST /api/v4/file-urls/batch`
- Auth: `Authorization: Bearer {token}`
- JSON body should include one or more file entries and v4 parse options:
  - file names;
  - `model_version`;
  - `is_ocr`;
  - `enable_formula`;
  - `enable_table`;
  - `language`;
  - generated `data_id`;
  - no callback for the first implementation.
- Parse response `data.batch_id` and `data.file_urls`.

Upload:

- Upload each local file to the returned pre-signed URL with `PUT`.
- Do not attach the MinerU bearer token to the object-storage upload URL unless the
  API documentation explicitly requires it.
- Record upload count and failures in runtime telemetry.

Polling:

- `GET /api/v4/extract-results/batch/{batch_id}`
- Treat waiting, uploading, pending, running, and processing-like states as in progress.
- Treat done/completed/success-like states as completed.
- Treat failed/error-like states as failures and surface per-file error messages when
  available.
- Honor timeout and poll interval.

Result extraction:

- Prefer `full_zip_url` as the primary result contract.
- Download the zip, extract Markdown from `full.md` or the documented Markdown path.
- Preserve useful JSON artifacts, such as content list, middle JSON, layout JSON, or
  model output, when they appear in the zip and the handoff mode requests rich assets.
- Reuse existing asset logic where possible, but do not assume the v4 zip has the same
  shape as self-hosted FastAPI `/tasks/{task_id}/result`.
- Reject missing Markdown with an actionable `DocConvertError`.

### Asset Handling

The first implementation should support Markdown-first conversion and a safe path for
future rich assets:

- `markdown_only`: extract only Markdown and ignore non-required zip entries.
- `markdown_assets`: extract referenced image/table assets from the zip when present,
  save them under `documents/images/<markdown-stem>/...`, and rewrite Markdown links
  using the existing asset-sidecar conventions where compatible.
- Unknown zip entries must not be written outside the handoff directory. Sanitize paths
  and reject `..`, absolute paths, or drive-prefixed names.

### Reports And Redaction

Extend existing runtime and quality reports without leaking secrets:

- Include backend `mineru-v4`.
- Include redacted endpoint and batch/task IDs.
- Include requested and effective `model_version`.
- Include zip download status and artifact extraction summary.
- Redact token values, pre-signed upload/download query strings, and private hostnames
  using existing redaction helpers.
- Add a v4-specific protocol error category for wrong endpoint shape, missing batch ID,
  missing upload URLs, failed upload, failed polling, missing zip URL, bad zip, and
  missing Markdown.

### Probe And Warmup

- `backend probe --backend mineru-v4` should validate URL shape and auth presence.
- A network probe may call a lightweight documented endpoint only if one exists. If no
  stable health endpoint exists, classify network probe as protocol-limited and explain
  that warmup is the real end-to-end check.
- `backend warmup --backend mineru-v4` should run a tiny fixture through fake-server
  tests offline and optionally through the real API only when the user explicitly
  provides credentials and asks for live validation.

### Adaptive Pipeline Integration

- `inspect-source` remains offline and does not call MinerU.
- `adaptive --decision-only` may preserve and tune `mineru-v4` when:
  - input is PDF/Office/image;
  - source inspection finds table signals or complex layout signals;
  - the user requested a platform backend or supplied an explicit policy/override that
    selects the v4 platform path.
- Do not make `mineru-v4` the default adaptive remote backend merely because a token is
  present. Prefer explicit user choice or explicit policy. Backend probe evidence can
  confirm readiness, but it does not by itself opt the run into paid platform routing.
- If `mineru-v4` is selected and `table_quality=high`, set effective
  `model_version=vlm`.

## Development Plan

### Runtime

1. Add constants and backend inventory entries for `mineru-v4`.
2. Add URL helpers:
   - normalize root;
   - build `/api/v4/file-urls/batch`;
   - build `/api/v4/extract-results/batch/{batch_id}`.
3. Add `mineru_v4_convert()` in `doc_convert.py`.
4. Add v4 JSON request helpers that support SSL verification and redacted telemetry.
5. Add safe zip download and extraction helpers.
6. Add v4 result-to-Markdown extraction with fixture coverage.
7. Add v4 asset extraction in `markdown_assets` mode.
8. Add v4 runtime report fields and failure categories.
9. Add v4 backend probe and warmup support.

### CLI

1. Add `mineru-v4` to backend choices.
2. Add v4-specific parser flags.
3. Load v4-specific values from config and environment.
4. Pass v4 options through `convert_source_to_markdown()`.
5. Extend table-quality decision code to produce either FastAPI backend selection or
   v4 model selection depending on selected backend.
6. Extend adaptive recommendation output with `mineru_v4_model_version`.
7. Update JSON and Markdown report generation where new fields are visible.

### Tests

1. Runtime fake-server success test:
   - submit batch;
   - upload to returned URL;
   - poll completed result;
   - download zip;
   - extract `full.md`.
2. Runtime failure tests:
   - missing `batch_id`;
   - missing `file_urls`;
   - upload failure;
   - polling failure state;
   - missing `full_zip_url`;
   - invalid zip;
   - zip without Markdown.
3. CLI conversion test for env/config/flag wiring.
4. Table-quality tests:
   - `high` maps to `vlm`;
   - explicit `MinerU-HTML` is preserved with a review warning;
   - `standard` keeps `pipeline`;
   - `auto` recommends `vlm` for table-bearing formal candidates.
5. Redaction tests for bearer token and pre-signed URLs.
6. Probe/warmup tests with no live network dependency.
7. Zip path traversal tests.

### Documentation

1. Update `skills/ragflow-doc-to-md/SKILL.md`.
2. Update config examples in skill templates.
3. Update architecture/config docs that list MinerU backends.
4. Update table-quality docs to explain FastAPI backend versus v4 model mapping.
5. Add release-note wording once implementation is complete.

### Validation

Before claiming implementation complete, run:

```bash
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py \
  skills/ragflow-doc-to-md/scripts/convert.py
python3 -m pytest packages/ragflow-skill-runtime/tests/test_doc_convert.py -q
python3 -m pytest packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py -q
python3 tools/manifest_schema_check.py
python3 tools/release_hygiene_check.py
python3 tools/consumer_acceptance.py --work-dir /tmp/ragflow-consumer-acceptance-mineru-v4 --overwrite
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/ragflow-platform-mineru-v4
git diff --check
```

Live validation remains optional and gated. It requires an explicit user request, a
throwaway small fixture, a real `MINERU_API_KEY`, and sanitized evidence capture.

## Implementation Checklist

- [x] Confirm exact v4 request/response fields from the current MinerU API document and
      record any drift from this design.
- [x] Choose final backend name and alias policy: `mineru-v4`, `mineru-platform`, or both.
- [x] Add backend inventory constants in runtime and CLI.
- [x] Add v4 config/env/CLI option loading.
- [x] Implement v4 URL normalization helpers.
- [x] Implement v4 batch submission request.
- [x] Implement upload to returned `file_urls`.
- [x] Implement v4 polling loop.
- [x] Implement zip download with timeout and SSL verification.
- [x] Implement safe zip extraction and Markdown selection.
- [x] Implement `markdown_assets` support for v4 zip outputs.
- [x] Implement v4 telemetry and redaction fields.
- [x] Implement v4 backend probe behavior.
- [x] Implement v4 backend warmup behavior.
- [x] Extend `convert_source_to_markdown()` dispatch.
- [x] Extend table-quality decision and report fields for v4 `model_version`.
- [x] Extend adaptive decision recommendations for v4 high-quality table extraction.
- [x] Add runtime fake-server success tests.
- [x] Add runtime protocol failure tests.
- [x] Add CLI wiring tests.
- [x] Add redaction and zip-safety tests.
- [x] Update public skill documentation.
- [x] Update config examples and architecture docs.
- [x] Run focused tests and Python compilation.
- [x] Run release-facing validation gates.
- [x] Record implementation completion status and residual risks in this document.

## Protocol-Binding Follow-Up Patch Checklist

This documentation/help calibration is closed. It did not change the v4 request contract
or switch backend behavior away from the protocol-bound implementation.

- [x] Update CLI help and runtime docstrings so `mineru-v4` is described as a
      v4 platform-compatible protocol backend, with `mineru.net` shown only as an
      official example endpoint.
- [x] Update `skills/ragflow-doc-to-md/SKILL.md` examples and wording to say compatible
      v4 endpoints may replace `https://mineru.net`.
- [x] Update shared `skills/*/references/host-agent-setup.md` guidance and keep the three
      public copies byte-identical after the wording change.
- [x] Update shared `skills/*/references/user-onboarding-prompt.md` guidance and keep the
      three public copies byte-identical after the wording change.
- [x] Update shared `skills/*/templates/ragflow-config.example.yaml` comments so
      `https://mineru.net` is clearly labeled as an example, not the only supported
      domain.
- [x] Update architecture, CLI-agent integration, adaptive/table-quality, and comparison
      references to say "MinerU v4 platform-compatible protocol" where the support model
      is protocol-bound rather than domain-bound.
- [x] Run docs-only validation, shared-reference/template drift checks, and release
      hygiene before closing this follow-up.

## Residual Risks And Follow-Up Questions

- No stable Markdown-only zip result was confirmed; `MINERU_V4_RESULT_MODE` remains
  restricted to `full_zip`.
- v4 local-file batch mode supports `page_ranges`; `MINERU_PAGE_RANGE` maps to
  per-file `page_ranges`.
- Multi-file partial completion semantics remain covered only by documented state names
  and fake-server single-file tests. The public CLI currently converts one source at a
  time.
- `MinerU-HTML` is preserved when explicitly requested, including under
  `--table-quality high`, and the table-quality report emits a review warning.
- `adaptive` recommends v4 high-quality table extraction only when the user explicitly
  requested `mineru-v4` / `mineru-platform`; it does not switch paid/token-based platform
  APIs merely because a token exists.
- Live MinerU v4 validation is not run by default. It remains a future explicit,
  credentialed, sanitized field-trial task.
